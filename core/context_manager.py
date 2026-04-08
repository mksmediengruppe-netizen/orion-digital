"""
ARCANE Context Manager
Implements Scratchpad and ContextCompactor to prevent context window overflow.

Scratchpad:
  - Persistent key-value store for the agent to remember important facts
  - Injected into system prompt on every iteration
  - Survives context compaction

ContextCompactor:
  - Monitors message list size (token estimate)
  - When approaching context limit, compresses old messages into a summary
  - Preserves: system prompt, last N messages, all tool results with errors
  - Removes: redundant assistant reasoning, successful tool results older than N iterations
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from shared.utils.logger import get_logger

logger = get_logger("core.context_manager")

# Rough token estimation: 1 token ≈ 4 chars for English, 2 chars for Russian
CHARS_PER_TOKEN_LATIN = 4   # ~4 chars per token for English/code
CHARS_PER_TOKEN_CYRILLIC = 2  # ~2 chars per token for Russian/Cyrillic

def _estimate_tokens_for_text(text) -> int:
    """Estimate token count with Cyrillic awareness.
    
    Cyrillic characters use ~2 chars per token vs ~4 for Latin/code.
    We count the ratio and blend accordingly.
    """
    if not text:
        return 0
    # Handle non-string content (multimodal messages, tool results)
    if isinstance(text, dict):
        text = str(text)
    elif isinstance(text, list):
        text = " ".join(str(item) for item in text)
    elif not isinstance(text, str):
        text = str(text)
    cyrillic_count = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    total_chars = len(text)
    if total_chars == 0:
        return 0
    cyrillic_ratio = cyrillic_count / total_chars
    # Weighted average of chars-per-token
    effective_cpt = (
        cyrillic_ratio * CHARS_PER_TOKEN_CYRILLIC +
        (1 - cyrillic_ratio) * CHARS_PER_TOKEN_LATIN
    )
    return max(1, int(total_chars / effective_cpt))


class Scratchpad:
    """
    Agent's working memory — a key-value store that persists across compactions.
    The agent can read/write via the update_scratchpad tool.
    Contents are injected into the system prompt.
    """

    def __init__(self):
        self._data: dict[str, str] = {}
        self._updated_at: float = 0

    def __setitem__(self, key: str, value) -> None:
        """Support dict-style assignment: scratchpad[key] = value."""
        self._data[key] = str(value)
        self._updated_at = time.time()

    def __getitem__(self, key: str) -> str:
        """Support dict-style access: scratchpad[key]."""
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator: key in scratchpad."""
        return key in self._data

    def update(self, key: str, value: str) -> None:
        """Set or update a scratchpad entry."""
        self._data[key] = value
        self._updated_at = time.time()

    def delete(self, key: str) -> bool:
        """Remove a scratchpad entry."""
        if key in self._data:
            del self._data[key]
            self._updated_at = time.time()
            return True
        return False

    def get(self, key: str) -> Optional[str]:
        """Get a single entry."""
        return self._data.get(key)

    def get_all(self) -> dict[str, str]:
        """Get all entries."""
        return dict(self._data)

    def to_prompt_section(self) -> str:
        """Format scratchpad contents for injection into system prompt."""
        if not self._data:
            return ""
        lines = []
        for k, v in self._data.items():
            lines.append(f"  {k}: {v}")
        return "<scratchpad>\n" + "\n".join(lines) + "\n</scratchpad>"

    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return {"data": self._data, "updated_at": self._updated_at}

    @classmethod
    def from_dict(cls, d: dict) -> "Scratchpad":
        """Deserialize from persistence."""
        sp = cls()
        sp._data = d.get("data", {})
        sp._updated_at = d.get("updated_at", 0)
        return sp


class ContextCompactor:
    """
    Monitors and compacts the message list to prevent context window overflow.

    Strategy:
      1. Estimate total tokens in message list
      2. If approaching limit (80% of max_context), trigger compaction
      3. Keep: system message, last `keep_recent` messages, error tool results
      4. Summarize everything else into a single "compacted_history" system message
      5. Preserve scratchpad (it's in system prompt, not messages)
    """

    def __init__(
        self,
        max_context_tokens: int = 128000,
        threshold_ratio: float = 0.75,
        keep_recent: int = 10,
        summary_max_tokens: int = 2000,
        compact_every_n_iterations: int = 6,
        max_messages_before_compact: int = 40,
    ):
        self._max_context = max_context_tokens
        self._threshold = int(max_context_tokens * threshold_ratio)
        self._keep_recent = keep_recent
        self._summary_max_tokens = summary_max_tokens
        self._compact_every_n = compact_every_n_iterations
        self._max_messages = max_messages_before_compact
        self._compaction_count = 0
        self._last_compaction_iteration = 0

    def estimate_tokens(self, messages: list[dict]) -> int:
        """Token estimate with Cyrillic awareness (PATCH-08)."""
        total = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            total += _estimate_tokens_for_text(content)
            # Tool calls are mostly JSON/code — use Latin ratio
            if "tool_calls" in msg:
                tc_str = json.dumps(msg["tool_calls"], default=str)
                total += len(tc_str) // CHARS_PER_TOKEN_LATIN
        return total

    def needs_compaction(self, messages: list[dict], iteration: int = 0) -> bool:
        """Check if the message list needs compaction.

        Three triggers (any one is sufficient):
        1. Token-based: estimated tokens > threshold (original)
        2. Iteration-based: every N iterations since last compaction
        3. Message-count: more than max_messages in the list
        """
        # Trigger 1: token-based (original)
        if self.estimate_tokens(messages) > self._threshold:
            return True
        # Trigger 2: iteration-based (every N iterations)
        if (iteration > 0 and self._compact_every_n > 0
                and iteration - self._last_compaction_iteration >= self._compact_every_n
                and len(messages) > self._keep_recent + 2):
            return True
        # Trigger 3: message-count
        if len(messages) > self._max_messages:
            return True
        return False

    def compact(self, messages: list[dict], iteration: int = 0) -> list[dict]:
        """
        Compact the message list by summarizing old messages.
        Returns a new, shorter message list.
        """
        if len(messages) <= self._keep_recent + 2:
            return messages  # Too few messages to compact

        estimated = self.estimate_tokens(messages)

        self._compaction_count += 1
        if iteration > 0:
            self._last_compaction_iteration = iteration
        logger.info(
            f"Compacting context: {estimated} tokens estimated, "
            f"threshold={self._threshold}, messages={len(messages)}, "
            f"compaction #{self._compaction_count}"
        )

        # Split messages into sections
        # Keep the first message if it's system
        system_msgs = []
        if messages and messages[0].get("role") == "system":
            system_msgs = [messages[0]]
            messages = messages[1:]

        # Keep the last N messages, but ensure tool_call groups stay together
        if len(messages) > self._keep_recent:
            split_idx = len(messages) - self._keep_recent
            # Adjust split point: if we're splitting inside a tool_call group,
            # move the split backwards to include the full group in recent_messages.
            # A tool_call group = assistant msg with tool_calls + all following tool msgs.
            while split_idx > 0:
                msg_at_split = messages[split_idx]
                # If the message at split point is a tool result, its parent assistant
                # message (with tool_calls) might be before the split — pull it in.
                if msg_at_split.get("role") == "tool":
                    split_idx -= 1
                    continue
                break
            # Also check: if the message just before split is an assistant with tool_calls,
            # pull it into recent too (its tool results are already in recent).
            if split_idx > 0 and messages[split_idx - 1].get("role") == "assistant" and messages[split_idx - 1].get("tool_calls"):
                split_idx -= 1
            old_messages = messages[:split_idx]
            recent_messages = messages[split_idx:]
        else:
            return system_msgs + messages  # Nothing to compact

        # Build summary of old messages
        summary_parts = []
        errors_preserved = []

        for msg in old_messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""

            if role == "user":
                # Keep user messages as brief summaries
                truncated = content[:300] + "..." if len(content) > 300 else content
                summary_parts.append(f"<user_message>{truncated}</user_message>")

            elif role == "assistant":
                # Summarize assistant messages
                if msg.get("tool_calls"):
                    # Just note which tools were called
                    tool_names = []
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        tool_names.append(func.get("name", "unknown"))
                    summary_parts.append(
                        f"<tool_call tool=\"{', '.join(tool_names)}\" />"
                    )
                elif content:
                    truncated = content[:200] + "..." if len(content) > 200 else content
                    summary_parts.append(f"<assistant_note>{truncated}</assistant_note>")

            elif role == "tool":
                tool_id = msg.get("tool_call_id", "")
                # Preserve error results fully, truncate success results
                if isinstance(content, list):
                    # Vision message (list of dicts) — treat as non-error, extract text
                    content_str = " ".join(
                        part.get("text", "") for part in content 
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                    is_error = "ERROR" in content_str or "error" in content_str.lower()[:50]
                elif isinstance(content, str):
                    is_error = "ERROR" in content or "error" in content.lower()[:50]
                else:
                    is_error = False
                if is_error:
                    errors_preserved.append(msg)
                else:
                    c_str = content if isinstance(content, str) else " ".join(p.get("text","") for p in content if isinstance(p,dict) and p.get("type")=="text")
                    truncated = c_str[:100] + "..." if len(c_str) > 100 else c_str
                    summary_parts.append(
                        f"<tool_result id=\"{tool_id}\">{truncated}</tool_result>"
                    )

        # Build the compacted history message
        summary_text = "\n".join(summary_parts)
        # Truncate summary if too long
        max_summary_chars = self._summary_max_tokens * CHARS_PER_TOKEN_CYRILLIC  # Use Cyrillic ratio for safety
        if len(summary_text) > max_summary_chars:
            summary_text = summary_text[:max_summary_chars] + "\n... [earlier history truncated]"

        # FIX #7: Extract key findings from old messages before discarding
        key_findings = []
        files_modified = set()
        for msg in old_messages:
            content = msg.get("content", "") or ""
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            # Track files that were written/edited
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    if name in ("file_write", "file_edit", "file_create"):
                        try:
                            import json as _json
                            args = _json.loads(func.get("arguments", "{}"))
                            path = args.get("path", "")
                            if path:
                                files_modified.add(path)
                        except Exception:
                            pass
            # Extract key decisions/findings from assistant messages
            if msg.get("role") == "assistant" and isinstance(content, str) and len(content) > 50:
                # Keep first sentence of substantial assistant messages
                first_line = content.split("\n")[0][:200]
                if first_line and not first_line.startswith("["):
                    key_findings.append(first_line)

        # Build key context section
        key_context_parts = []
        if files_modified:
            key_context_parts.append(f"Files modified in earlier iterations: {', '.join(sorted(files_modified))}")
        if key_findings:
            key_context_parts.append("Key decisions/findings:")
            for kf in key_findings[-5:]:  # Keep last 5 key findings
                key_context_parts.append(f"  - {kf}")
        key_context = "\n".join(key_context_parts)

        compacted_msg = {
            "role": "system",
            "content": (
                f"<compacted_history>\n"
                f"The following is a summary of {len(old_messages)} earlier messages "
                f"(compaction #{self._compaction_count}):\n\n"
                f"{summary_text}\n"
                f"</compacted_history>\n\n"
                f"<key_context>\n{key_context}\n</key_context>" if key_context else
                f"<compacted_history>\n"
                f"The following is a summary of {len(old_messages)} earlier messages "
                f"(compaction #{self._compaction_count}):\n\n"
                f"{summary_text}\n"
                f"</compacted_history>"
            ),
        }

        # FIX #8: Convert preserved error tool messages to a system note
        # to avoid orphaned tool_result messages (Claude API rejects these).
        # Raw tool messages without their matching assistant tool_calls cause 400 errors.
        if errors_preserved:
            error_summaries = []
            for err_msg in errors_preserved:
                _err_content = err_msg.get("content", "")
                if isinstance(_err_content, list):
                    _err_content = " ".join(p.get("text", "") for p in _err_content if isinstance(p, dict))
                _tool_id = err_msg.get("tool_call_id", "unknown")
                error_summaries.append(f"Tool call {_tool_id} returned error: {str(_err_content)[:500]}")
            if error_summaries:
                _err_text = "<previous_errors>\n" + "\n".join(error_summaries) + "\n</previous_errors>\nPlease avoid repeating these errors."
                errors_as_system = {
                    "role": "user",
                    "content": _err_text,
                }
                errors_preserved = [errors_as_system]
            else:
                errors_preserved = []

        # Reconstruct: system + compacted + preserved errors (as user msg) + recent
        result = system_msgs + [compacted_msg] + errors_preserved + recent_messages

        new_estimated = self.estimate_tokens(result)
        logger.info(
            f"Compaction complete: {estimated} -> {new_estimated} tokens, "
            f"{len(messages) + len(system_msgs)} -> {len(result)} messages"
        )

        return result

    @property
    def compaction_count(self) -> int:
        return self._compaction_count


class GoalAnchor:
    """
    Keeps the original user goal visible to prevent drift on long tasks.
    Injected into system prompt alongside scratchpad.
    """

    def __init__(self):
        self._goal: str = ""
        self._set_at: float = 0

    def set_goal(self, goal: str) -> None:
        """Set the task goal (extracted from first user message)."""
        self._goal = goal[:500]  # Cap length
        self._set_at = time.time()

    @property
    def goal(self) -> str:
        return self._goal

    def to_prompt_section(self) -> str:
        """Format goal for injection into system prompt."""
        if not self._goal:
            return ""
        return f"<goal_anchor>\nOriginal user goal: {self._goal}\n</goal_anchor>"

    def to_dict(self) -> dict:
        return {"goal": self._goal, "set_at": self._set_at}

    @classmethod
    def from_dict(cls, d: dict) -> "GoalAnchor":
        ga = cls()
        ga._goal = d.get("goal", "")
        ga._set_at = d.get("set_at", 0)
        return ga
