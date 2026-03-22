"""
Collaborative Memory — Shared Knowledge + Privacy Layers.
"""
import logging
from typing import Dict, List
from .config import MemoryConfig

logger = logging.getLogger("memory.collaborative")


class SharedMemory:
    """Общая память проекта, доступная всем участникам."""

    @staticmethod
    def store_shared(content: str, project_id: str, author_id: str,
                     privacy: str = "team") -> bool:
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            return sem.store(
                content=content,
                memory_type="shared",
                metadata={"project_id": project_id, "author": author_id, "privacy": privacy},
                user_id=f"shared:{project_id}",
                confidence=0.9
            )
        except:
            return False

    @staticmethod
    def search_shared(query: str, project_id: str, limit: int = 5) -> List[Dict]:
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            return sem.search(query, limit=limit, user_id=f"shared:{project_id}")
        except:
            return []

    @staticmethod
    def get_project_context(project_id: str, query: str) -> str:
        results = SharedMemory.search_shared(query, project_id, limit=3)
        if not results:
            return ""
        parts = ["КОМАНДНАЯ БАЗА ЗНАНИЙ:"]
        for r in results:
            author = r.get("metadata", {}).get("author", "") if isinstance(r.get("metadata"), dict) else ""
            parts.append(f"  [{author}]: {r['content'][:200]}")
        return "\n".join(parts)
