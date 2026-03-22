"""
ORION Digital — Amendment Extractor Module (TASK 9)
Detects user corrections/amendments in mid-task messages,
extracts structured changes, and updates the TaskCharter.
"""
import logging
import re
import json
from typing import Optional, Dict, List

logger = logging.getLogger("amendment_extractor")

# Keywords that signal an amendment vs a new instruction
AMENDMENT_SIGNALS = [
    "нет", "не так", "неправильно", "исправь", "поменяй", "замени",
    "измени", "переделай", "другой", "другую", "другое", "вместо",
    "лучше", "а не", "не нужно", "убери", "удали", "добавь",
    "no", "wrong", "fix", "change", "replace", "instead", "remove",
    "add", "update", "modify", "correct", "redo", "not like that",
    "стоп", "подожди", "отмена", "cancel", "stop", "wait",
]

NEW_TASK_SIGNALS = [
    "новая задача", "new task", "теперь сделай", "следующее",
    "другой проект", "забудь", "начни заново",
]


class AmendmentExtractor:
    """Extracts amendments from user messages and classifies them."""

    def __init__(self, call_ai_fn=None):
        self.call_ai_fn = call_ai_fn
        self._history: List[Dict] = []

    def classify(self, message: str, task_context: str = "") -> Dict:
        """
        Classify a mid-task user message:
        - amendment: user wants to change something in current task
        - continuation: user provides additional info for current task
        - new_task: user wants to start a completely new task
        - clarification: user asks a question about current task
        """
        msg_lower = message.lower().strip()

        # Quick rule-based classification
        if any(sig in msg_lower for sig in NEW_TASK_SIGNALS):
            return {"type": "new_task", "confidence": 0.8, "message": message}

        is_question = msg_lower.endswith("?") or msg_lower.startswith(("как ", "что ", "почему ", "зачем ", "where", "what", "how", "why"))
        if is_question and len(msg_lower) < 100:
            return {"type": "clarification", "confidence": 0.7, "message": message}

        has_amendment_signal = any(sig in msg_lower for sig in AMENDMENT_SIGNALS)
        if has_amendment_signal:
            amendment = self._extract_amendment(message, task_context)
            return {"type": "amendment", "confidence": 0.85, "amendment": amendment, "message": message}

        # Default: continuation (additional context for current task)
        return {"type": "continuation", "confidence": 0.6, "message": message}

    def _extract_amendment(self, message: str, task_context: str = "") -> Dict:
        """Extract structured amendment details."""
        amendment = {
            "original_message": message,
            "changes": [],
            "priority": "normal",
        }

        msg_lower = message.lower()

        # Detect urgency
        if any(w in msg_lower for w in ["срочно", "urgent", "сейчас", "немедленно", "стоп"]):
            amendment["priority"] = "high"

        # Try LLM extraction if available
        if self.call_ai_fn:
            try:
                llm_result = self._llm_extract(message, task_context)
                if llm_result:
                    amendment["changes"] = llm_result.get("changes", [])
                    amendment["summary"] = llm_result.get("summary", message[:200])
                    return amendment
            except Exception as e:
                logger.debug(f"LLM amendment extraction failed: {e}")

        # Fallback: rule-based extraction
        amendment["changes"] = self._rule_extract(message)
        amendment["summary"] = message[:200]
        return amendment

    def _llm_extract(self, message: str, task_context: str) -> Optional[Dict]:
        """Use LLM to extract structured amendment."""
        if not self.call_ai_fn:
            return None

        prompt = f"""Analyze this user message sent during an active task.
Extract what the user wants to change.

Task context: {task_context[:500]}
User message: {message}

Return JSON:
{{"summary": "brief description of change",
  "changes": [{{"what": "what to change", "from": "old value/behavior", "to": "new value/behavior"}}]
}}"""

        try:
            response = self.call_ai_fn(
                [{"role": "user", "content": prompt}],
                model="openai/gpt-5.4-mini"
            )
            # Parse JSON from response
            text = response.strip()
            text = re.sub(r'^```json\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            return json.loads(text)
        except Exception:
            return None

    def _rule_extract(self, message: str) -> List[Dict]:
        """Rule-based amendment extraction."""
        changes = []
        msg = message.strip()

        # Pattern: "замени X на Y" / "change X to Y"
        patterns = [
            r'(?:замени|поменяй|change|replace)\s+(.+?)\s+(?:на|to|with)\s+(.+)',
            r'(?:вместо|instead of)\s+(.+?)\s+(?:сделай|используй|use|make)\s+(.+)',
            r'(?:не|not)\s+(.+?)\s*[,.]\s*(?:а|but)\s+(.+)',
        ]
        for pat in patterns:
            m = re.search(pat, msg, re.IGNORECASE)
            if m:
                changes.append({"what": "content", "from": m.group(1).strip(), "to": m.group(2).strip()})

        # Pattern: "добавь X" / "add X"
        add_match = re.search(r'(?:добавь|add|включи|include)\s+(.+)', msg, re.IGNORECASE)
        if add_match:
            changes.append({"what": "addition", "from": "", "to": add_match.group(1).strip()})

        # Pattern: "убери X" / "remove X"
        rm_match = re.search(r'(?:убери|удали|remove|delete)\s+(.+)', msg, re.IGNORECASE)
        if rm_match:
            changes.append({"what": "removal", "from": rm_match.group(1).strip(), "to": ""})

        if not changes:
            changes.append({"what": "general", "from": "", "to": msg[:200]})

        return changes

    def apply_to_charter(self, charter_store, task_id: str, amendment: Dict):
        """Apply amendment to the task charter."""
        try:
            charter = charter_store.get(task_id)
            if not charter:
                logger.warning(f"No charter found for task {task_id}")
                return False

            # Append amendment to charter notes
            existing_notes = charter.get("notes", "") or ""
            amendment_note = f"\n[AMENDMENT] {amendment.get('summary', '')}\n"
            for ch in amendment.get("changes", []):
                amendment_note += f"  - {ch.get('what','')}: {ch.get('from','')} → {ch.get('to','')}\n"

            charter_store.update(task_id, notes=existing_notes + amendment_note)
            logger.info(f"[AMENDMENT] Applied to charter {task_id}: {amendment.get('summary','')[:100]}")
            return True
        except Exception as e:
            logger.warning(f"[AMENDMENT] Failed to apply to charter: {e}")
            return False


# Singleton
_amendment_extractor = None

def get_amendment_extractor(call_ai_fn=None):
    global _amendment_extractor
    if _amendment_extractor is None:
        _amendment_extractor = AmendmentExtractor(call_ai_fn=call_ai_fn)
    return _amendment_extractor
