"""
Multi-modal Memory — скриншоты и изображения.
"""
import os, logging, hashlib
from typing import Dict, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.multimodal")


class MultimodalMemory:
    """Хранение и поиск по скриншотам/изображениям."""

    @staticmethod
    def store_screenshot(image_path: str, description: str,
                         user_id: str, context: str = "") -> bool:
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            content = f"Скриншот: {description}\nКонтекст: {context}"
            return sem.store(
                content=content,
                memory_type="visual",
                metadata={"image_path": image_path, "description": description},
                user_id=user_id,
                confidence=0.8
            )
        except Exception as e:
            logger.error(f"MultimodalMemory store: {e}")
            return False

    @staticmethod
    def search_by_description(query: str, user_id: str) -> list:
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            return sem.search(query, limit=3, user_id=user_id, memory_type="visual")
        except:
            return []
