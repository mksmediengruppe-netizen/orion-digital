"""
Predictive Memory — Context Budget Manager + Pre-loading.
"""
import logging
from typing import Dict, List
from .config import MemoryConfig

logger = logging.getLogger("memory.predictive")

class ContextBudget:
    """Динамическое распределение токенов по компонентам контекста."""

    def __init__(self, max_tokens: int = None):
        self.max = max_tokens or MemoryConfig.MAX_CONTEXT_TOKENS
        self.allocated = {}

    def allocate(self) -> Dict[str, int]:
        """Вернуть бюджет токенов для каждого компонента."""
        return {
            "system_prompt": int(self.max * MemoryConfig.BUDGET_SYSTEM_PROMPT),
            "memory":        int(self.max * MemoryConfig.BUDGET_MEMORY),
            "history":       int(self.max * MemoryConfig.BUDGET_HISTORY),
            "anchor":        int(self.max * MemoryConfig.BUDGET_ANCHOR),
            "user_message":  int(self.max * MemoryConfig.BUDGET_USER_MSG),
            "reserve":       int(self.max * MemoryConfig.BUDGET_RESERVE),
        }

    def trim_to_budget(self, text: str, component: str) -> str:
        """Обрезать текст до бюджета компонента."""
        budget = self.allocate()
        max_chars = budget.get(component, 2000) * 4  # ~4 chars per token
        if len(text) <= max_chars: return text
        return text[:max_chars - 50] + "\n...[обрезано по бюджету]"


class PredictivePreload:
    """Предсказание следующего запроса и предзагрузка контекста."""

    @staticmethod
    def predict_context(user_id: str, current_task: str, chat_history: List[Dict]) -> str:
        """Простая эвристика: если последние 3 сообщения про деплой — предзагрузить серверы."""
        if not chat_history: return ""
        recent_text = " ".join(m.get("content","")[:100] for m in chat_history[-3:]).lower()
        deploy_kw = ["деплой", "deploy", "nginx", "docker", "systemctl", "сервер"]
        debug_kw = ["ошибк", "error", "баг", "bug", "не работает", "failed"]
        if any(kw in recent_text for kw in deploy_kw):
            try:
                from .learning import ToolLearning
                # Предзагрузить навыки серверов
                import re
                ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', recent_text)
                if ips:
                    return ToolLearning.get_server_profile(ips[0])
            except: pass
        if any(kw in recent_text for kw in debug_kw):
            try:
                from .learning import ErrorPatterns
                errors = ErrorPatterns.get_common_errors(limit=3)
                if errors:
                    parts = ["ЧАСТЫЕ ОШИБКИ:"]
                    for e in errors:
                        if e.get("fix_description"):
                            parts.append(f"  {e['error_message'][:80]} → {e['fix_description'][:80]}")
                    return "\n".join(parts)
            except: pass
        return ""
