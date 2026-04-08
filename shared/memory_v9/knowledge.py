"""
L6: Knowledge Base — RAG по загруженным документам.
Chunking → эмбеддинги → Qdrant → поиск при каждом запросе.
"""
import os, json, hashlib, logging, re
from typing import List, Dict
from .config import MemoryConfig

logger = logging.getLogger("memory.knowledge")

class KnowledgeBase:
    COLLECTION = MemoryConfig.KB_COLLECTION

    def __init__(self):
        self._semantic = None

    def _get_semantic(self):
        if not self._semantic:
            from .semantic import get_semantic
            self._semantic = get_semantic()
        return self._semantic

    def index_document(self, text: str, filename: str, user_id: str,
                       doc_type: str = "document") -> int:
        """Разбить документ на чанки и проиндексировать."""
        chunks = self._chunk_text(text, MemoryConfig.CHUNK_SIZE, MemoryConfig.CHUNK_OVERLAP)
        stored = 0
        sem = self._get_semantic()
        for i, chunk in enumerate(chunks):
            if sem.store(
                content=chunk,
                memory_type="knowledge",
                metadata={"filename": filename, "chunk_idx": i, "doc_type": doc_type},
                user_id=user_id,
                confidence=0.95
            ): stored += 1
        logger.info(f"Indexed {filename}: {stored}/{len(chunks)} chunks")
        return stored

    def search(self, query: str, user_id: str, limit: int = None) -> List[Dict]:
        limit = limit or MemoryConfig.KB_MAX_RESULTS
        sem = self._get_semantic()
        return sem.search(query, limit=limit, user_id=user_id, memory_type="knowledge")

    def get_context_for_prompt(self, query: str, user_id: str) -> str:
        results = self.search(query, user_id, limit=3)
        if not results: return ""
        parts = ["ИЗ БАЗЫ ЗНАНИЙ:"]
        for r in results:
            meta = r.get("metadata", {})
            fn = meta.get("filename", "?")
            parts.append(f"  [{fn}]: {r['content'][:300]}")
        return "\n".join(parts)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
        words = text.split()
        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i:i+chunk_size])
            if chunk.strip(): chunks.append(chunk)
            i += chunk_size - overlap
        return chunks

_kb_instance = None
def get_knowledge_base() -> KnowledgeBase:
    global _kb_instance
    if not _kb_instance: _kb_instance = KnowledgeBase()
    return _kb_instance
