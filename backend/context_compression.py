"""
ORION Context Compression — Phase 5
Prevents token overflow by intelligently compressing conversation history.
Mirrors Manus AI context management approach.
"""
import logging
import json
from typing import List, Dict, Optional

logger = logging.getLogger("context_compression")

# Token estimation: ~4 chars per token for English, ~2 chars for Russian
CHARS_PER_TOKEN = 3

def estimate_tokens(messages: List[Dict]) -> int:
    """Estimate token count for a list of messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content) // CHARS_PER_TOKEN
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += len(str(part.get("text", ""))) // CHARS_PER_TOKEN
        # Tool calls
        for tc in msg.get("tool_calls", []):
            total += len(json.dumps(tc, ensure_ascii=False)) // CHARS_PER_TOKEN
    return total

def compress_context(
    messages: List[Dict],
    max_tokens: int = 100000,
    keep_system: bool = True,
    keep_last_n: int = 6,
    call_ai_fn=None
) -> List[Dict]:
    """
    Compress conversation context to fit within token budget.
    
    Strategy:
    1. Always keep system message
    2. Always keep last N messages (recent context)
    3. Summarize middle messages if over budget
    4. Truncate tool results that are too long
    """
    if not messages:
        return messages
    
    current_tokens = estimate_tokens(messages)
    if current_tokens <= max_tokens:
        return messages  # No compression needed
    
    logger.info(f"[COMPRESS] Context too large: {current_tokens} tokens > {max_tokens} limit. Compressing...")
    
    result = []
    
    # 1. Keep system message
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    
    if keep_system and system_msgs:
        result.extend(system_msgs)
    
    # 2. Keep last N messages
    if len(other_msgs) <= keep_last_n:
        result.extend(other_msgs)
        return result
    
    old_msgs = other_msgs[:-keep_last_n]
    recent_msgs = other_msgs[-keep_last_n:]
    
    # 3. Truncate long tool results in old messages
    compressed_old = []
    for msg in old_msgs:
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 2000:
                msg = dict(msg)
                msg["content"] = content[:1000] + "\n... [compressed: " + str(len(content)) + " chars] ...\n" + content[-500:]
        compressed_old.append(msg)
    
    # 4. If still too large, summarize old messages
    tokens_after_truncation = estimate_tokens(result + compressed_old + recent_msgs)
    
    if tokens_after_truncation > max_tokens and call_ai_fn:
        # Summarize old conversation
        summary_text = _summarize_messages(compressed_old, call_ai_fn)
        if summary_text:
            result.append({
                "role": "user",
                "content": f"[CONTEXT SUMMARY - previous conversation]\n{summary_text}"
            })
            result.append({
                "role": "assistant", 
                "content": "Understood. I have the context from our previous conversation. Continuing..."
            })
        else:
            # Fallback: just keep compressed old messages
            result.extend(compressed_old)
    elif tokens_after_truncation > max_tokens:
        # No AI available for summary — aggressive truncation
        # Keep only first and last old messages
        if len(compressed_old) > 2:
            result.append(compressed_old[0])
            result.append({
                "role": "user",
                "content": f"[{len(compressed_old) - 2} messages compressed]"
            })
            result.append({
                "role": "assistant",
                "content": "Continuing with the task..."
            })
            result.append(compressed_old[-1])
        else:
            result.extend(compressed_old)
    else:
        result.extend(compressed_old)
    
    # 5. Add recent messages
    result.extend(recent_msgs)
    
    final_tokens = estimate_tokens(result)
    logger.info(f"[COMPRESS] Compressed: {current_tokens} -> {final_tokens} tokens ({len(messages)} -> {len(result)} messages)")
    
    return result

def _summarize_messages(messages: List[Dict], call_ai_fn) -> Optional[str]:
    """Use AI to summarize a list of messages."""
    try:
        # Build conversation text
        conv_text = ""
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                conv_text += f"{role}: {content[:500]}\n"
        
        if not conv_text.strip():
            return None
        
        summary_messages = [
            {"role": "system", "content": "Summarize this conversation concisely. Focus on: what was asked, what tools were used, what results were obtained. Keep it under 500 words. Respond in the same language as the conversation."},
            {"role": "user", "content": conv_text[:8000]}
        ]
        
        result = call_ai_fn(summary_messages)
        if result and len(result) > 50:
            return result
    except Exception as e:
        logger.error(f"[COMPRESS] Summary failed: {e}")
    
    return None

def truncate_tool_result(result: str, max_chars: int = 8000) -> str:
    """Truncate a tool result to max_chars, keeping start and end."""
    if not result or len(result) <= max_chars:
        return result
    
    keep_start = max_chars * 2 // 3
    keep_end = max_chars // 3
    
    return (
        result[:keep_start] + 
        f"\n\n... [{len(result) - max_chars} chars truncated] ...\n\n" + 
        result[-keep_end:]
    )
