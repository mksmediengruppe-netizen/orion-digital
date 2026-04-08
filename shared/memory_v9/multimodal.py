"""
Multi-modal Memory — индексация скриншотов и изображений через Vision API.
"""
import os, json, logging, hashlib
from typing import Dict, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.multimodal")

class MultiModalMemory:
    """Индексирует скриншоты и изображения через описание от Vision API."""

    @staticmethod
    def index_screenshot(image_path: str, description: str,
                         url: str = "", user_id: str = "",
                         chat_id: str = "") -> bool:
        """Сохранить описание скриншота в семантическую память."""
        if not description: return False
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            content = f"Скриншот {url}: {description[:500]}"
            return sem.store(content=content, memory_type="visual",
                             metadata={"image_path": image_path, "url": url},
                             chat_id=chat_id, user_id=user_id, confidence=0.7)
        except: return False

    @staticmethod
    def search_visual(query: str, user_id: str, limit: int = 3):
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            return sem.search(query, limit=limit, user_id=user_id, memory_type="visual")
        except: return []
