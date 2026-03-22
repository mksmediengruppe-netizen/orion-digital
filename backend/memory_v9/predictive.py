"""
Predictive Pre-load + Context Budget.
"""
import logging
from typing import List, Dict
from .config import MemoryConfig

logger = logging.getLogger("memory.predictive")


class ContextBudget:
    """Управление бюджетом токенов контекста."""

    CHARS_PER_TOKEN = 4  # приблизительно

    def trim_to_budget(self, text: str, section: str) -> str:
        budget_ratio = {
            "system_prompt": MemoryConfig.BUDGET_SYSTEM_PROMPT + MemoryConfig.BUDGET_MEMORY,
            "history": MemoryConfig.BUDGET_HISTORY,
            "user_msg": MemoryConfig.BUDGET_USER_MSG,
        }.get(section, 0.2)
        max_chars = int(MemoryConfig.MAX_CONTEXT_TOKENS * self.CHARS_PER_TOKEN * budget_ratio)
        if len(text) > max_chars:
            return text[:max_chars] + f"\n...[обрезано до {max_chars} симв.]"
        return text


class PredictivePreload:
    """Предсказывает что понадобится агенту и предзагружает."""

    PATTERNS = {
        "деплой": ["nginx", "systemctl", "gunicorn", "certbot"],
        "deploy": ["nginx", "systemctl", "gunicorn", "certbot"],
        "установи": ["apt", "pip", "npm"],
        "install": ["apt", "pip", "npm"],
        "база данных": ["postgresql", "mysql", "sqlite"],
        "database": ["postgresql", "mysql", "sqlite"],
        "docker": ["docker-compose", "dockerfile", "container"],
        "ssl": ["certbot", "letsencrypt", "nginx"],
        "python": ["pip", "venv", "requirements"],
        "node": ["npm", "package.json", "pm2"],
    }

    @staticmethod
    def predict_context(user_id: str, message: str, history: List[Dict]) -> str:
        msg_lower = message.lower()
        predicted_topics = []
        for keyword, topics in PredictivePreload.PATTERNS.items():
            if keyword in msg_lower:
                predicted_topics.extend(topics)
        if not predicted_topics:
            return ""
        unique_topics = list(set(predicted_topics))[:5]
        return f"ПРЕДСКАЗАННЫЕ ТЕМЫ: {', '.join(unique_topics)}"
