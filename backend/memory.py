"""
Long-term Memory v1.0 — Vector Memory для ORION Digital.

Архитектура:
- TF-IDF embeddings (scikit-learn) — без внешних API, мгновенно
- Qdrant in-memory vector store — быстрый поиск по семантике
- Автоматическое сохранение контекста из каждого чата
- Поиск релевантных воспоминаний при новых запросах
- Cross-Chat Learning: знания из одного чата доступны в других

Типы памяти:
1. Episodic: конкретные действия и результаты (что делал, что получилось)
2. Semantic: факты о серверах, конфигах, предпочтениях пользователя
3. Procedural: паттерны решения задач (как делать деплой, как фиксить ошибки)
"""

import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, MatchValue
)

logger = logging.getLogger("memory")


# ══════════════════════════════════════════════════════════════════
# ██ MEMORY TYPES ██
# ══════════════════════════════════════════════════════════════════

class MemoryType:
    EPISODIC = "episodic"      # Конкретные действия и результаты
    SEMANTIC = "semantic"      # Факты, конфиги, предпочтения
    PROCEDURAL = "procedural"  # Паттерны решения задач


class MemoryEntry:
    """Единица памяти."""
    def __init__(self, content: str, memory_type: str, metadata: dict = None,
                 chat_id: str = None, user_id: str = None):
        self.id = hashlib.md5(f"{content}:{time.time()}".encode()).hexdigest()
        self.content = content
        self.memory_type = memory_type
        self.metadata = metadata or {}
        self.chat_id = chat_id
        self.user_id = user_id or "default"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.access_count = 0
        self.last_accessed = self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "metadata": self.metadata,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed
        }


# ══════════════════════════════════════════════════════════════════
# ██ TF-IDF EMBEDDER ██
# ══════════════════════════════════════════════════════════════════

class TFIDFEmbedder:
    """
    TF-IDF based embedder — no external API needed.
    Maintains a growing vocabulary and re-fits as needed.
    """

    VECTOR_DIM = 512  # Fixed dimension for Qdrant

    def __init__(self):
        self._vectorizer = TfidfVectorizer(
            max_features=self.VECTOR_DIM,
            ngram_range=(1, 2),
            sublinear_tf=True,
            strip_accents='unicode',
            analyzer='word',
            min_df=1,
            max_df=1.0
        )
        self._corpus: List[str] = []
        self._is_fitted = False

    def _ensure_fitted(self, texts: List[str] = None):
        """Fit or refit the vectorizer with new texts."""
        if texts:
            new_texts = [t for t in texts if t not in self._corpus]
            if new_texts:
                self._corpus.extend(new_texts)
                self._is_fitted = False

        if not self._is_fitted and self._corpus:
            try:
                self._vectorizer.fit(self._corpus)
                self._is_fitted = True
            except Exception as e:
                logger.warning(f"TF-IDF fit error: {e}")

    def embed(self, text: str) -> List[float]:
        """Get embedding vector for a single text."""
        self._ensure_fitted([text])

        if not self._is_fitted:
            # Return zero vector if not enough data
            return [0.0] * self.VECTOR_DIM

        try:
            vec = self._vectorizer.transform([text]).toarray()[0]
            # Pad or truncate to fixed dimension
            if len(vec) < self.VECTOR_DIM:
                vec = np.pad(vec, (0, self.VECTOR_DIM - len(vec)))
            elif len(vec) > self.VECTOR_DIM:
                vec = vec[:self.VECTOR_DIM]
            return vec.tolist()
        except Exception as e:
            logger.warning(f"TF-IDF embed error: {e}")
            return [0.0] * self.VECTOR_DIM

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Get embedding vectors for multiple texts."""
        self._ensure_fitted(texts)

        if not self._is_fitted:
            return [[0.0] * self.VECTOR_DIM for _ in texts]

        try:
            vecs = self._vectorizer.transform(texts).toarray()
            result = []
            for vec in vecs:
                if len(vec) < self.VECTOR_DIM:
                    vec = np.pad(vec, (0, self.VECTOR_DIM - len(vec)))
                elif len(vec) > self.VECTOR_DIM:
                    vec = vec[:self.VECTOR_DIM]
                result.append(vec.tolist())
            return result
        except Exception as e:
            logger.warning(f"TF-IDF batch embed error: {e}")
            return [[0.0] * self.VECTOR_DIM for _ in texts]


# ══════════════════════════════════════════════════════════════════
# ██ VECTOR MEMORY STORE ██
# ══════════════════════════════════════════════════════════════════

class VectorMemory:
    """
    Long-term vector memory using Qdrant (in-memory) + TF-IDF.

    Features:
    - Store memories with type classification
    - Semantic search across all memories
    - Filter by user, chat, memory type
    - Cross-chat learning (search across all chats)
    - Auto-summarization of long contexts
    """

    COLLECTION_NAME = "agent_memory"
    MAX_CONTENT_LENGTH = 2000

    def __init__(self):
        # BUG-5 FIX: Qdrant persistent storage (не теряется при рестарте)
        import os as _os
        _qdrant_path = _os.path.join(
            _os.environ.get("DATA_DIR", "/var/www/orion/backend/data"),
            "qdrant_storage"
        )
        _os.makedirs(_qdrant_path, exist_ok=True)
        try:
            self._client = QdrantClient(path=_qdrant_path)
        except Exception:
            self._client = QdrantClient(":memory:")  # fallback
        self._embedder = TFIDFEmbedder()
        self._point_id_counter = 0
        self._initialized = False
        self._init_collection()

    def _init_collection(self):
        """Initialize Qdrant collection."""
        try:
            collections = self._client.get_collections().collections
            exists = any(c.name == self.COLLECTION_NAME for c in collections)

            if not exists:
                self._client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=TFIDFEmbedder.VECTOR_DIM,
                        distance=Distance.COSINE
                    )
                )
            self._initialized = True
            logger.info("VectorMemory initialized")
        except Exception as e:
            logger.error(f"VectorMemory init error: {e}")
            self._initialized = False

    def store(self, entry: MemoryEntry) -> bool:
        """Store a memory entry."""
        if not self._initialized:
            return False

        try:
            content = entry.content[:self.MAX_CONTENT_LENGTH]
            vector = self._embedder.embed(content)

            self._point_id_counter += 1
            point = PointStruct(
                id=self._point_id_counter,
                vector=vector,
                payload={
                    "memory_id": entry.id,
                    "content": content,
                    "memory_type": entry.memory_type,
                    "metadata": json.dumps(entry.metadata, ensure_ascii=False),
                    "chat_id": entry.chat_id or "",
                    "user_id": entry.user_id,
                    "created_at": entry.created_at,
                    "access_count": entry.access_count
                }
            )

            self._client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=[point]
            )
            return True
        except Exception as e:
            logger.error(f"Memory store error: {e}")
            return False

    def search(self, query: str, limit: int = 5, user_id: str = None,
               chat_id: str = None, memory_type: str = None,
               min_score: float = 0.1) -> List[Dict]:
        """
        Search memories by semantic similarity.

        Args:
            query: search query text
            limit: max results
            user_id: filter by user
            chat_id: filter by chat (None = cross-chat)
            memory_type: filter by memory type
            min_score: minimum similarity score

        Returns: list of memory dicts with scores
        """
        if not self._initialized:
            return []

        try:
            vector = self._embedder.embed(query)

            # Build filter
            conditions = []
            if user_id:
                conditions.append(
                    FieldCondition(key="user_id", match=MatchValue(value=user_id))
                )
            if chat_id:
                conditions.append(
                    FieldCondition(key="chat_id", match=MatchValue(value=chat_id))
                )
            if memory_type:
                conditions.append(
                    FieldCondition(key="memory_type", match=MatchValue(value=memory_type))
                )

            query_filter = Filter(must=conditions) if conditions else None

            response = self._client.query_points(
                collection_name=self.COLLECTION_NAME,
                query=vector,
                limit=limit,
                query_filter=query_filter,
                score_threshold=min_score
            )

            memories = []
            for hit in response.points:
                payload = hit.payload
                metadata = {}
                try:
                    metadata = json.loads(payload.get("metadata", "{}"))
                except Exception:
                    pass

                memories.append({
                    "content": payload.get("content", ""),
                    "memory_type": payload.get("memory_type", ""),
                    "metadata": metadata,
                    "chat_id": payload.get("chat_id", ""),
                    "user_id": payload.get("user_id", ""),
                    "created_at": payload.get("created_at", ""),
                    "score": hit.score
                })

            return memories
        except Exception as e:
            logger.error(f"Memory search error: {e}")
            return []

    def store_from_conversation(self, user_message: str, assistant_response: str,
                                 tool_results: List[Dict] = None,
                                 chat_id: str = None, user_id: str = None):
        """
        Автоматически извлечь и сохранить воспоминания из разговора.

        Извлекает:
        - Episodic: что было сделано (tool calls + results)
        - Semantic: факты о серверах, конфигах
        - Procedural: паттерны решения задач
        """
        stored = 0

        # 1. Episodic: сохранить действия и результаты
        if tool_results:
            for tr in tool_results:
                tool = tr.get("tool", "")
                success = tr.get("success", False)
                preview = tr.get("preview", "")

                if tool and preview:
                    content = f"Действие: {tool} | Результат: {'✅' if success else '❌'} {preview[:200]}"
                    entry = MemoryEntry(
                        content=content,
                        memory_type=MemoryType.EPISODIC,
                        metadata={"tool": tool, "success": success},
                        chat_id=chat_id,
                        user_id=user_id
                    )
                    if self.store(entry):
                        stored += 1

        # 2. Semantic: извлечь факты из сообщений
        # Ищем IP адреса, домены, пути, конфиги
        import re

        # IP addresses
        ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', user_message + " " + assistant_response)
        for ip in set(ips):
            content = f"Сервер: {ip}"
            entry = MemoryEntry(
                content=content,
                memory_type=MemoryType.SEMANTIC,
                metadata={"type": "server_ip", "ip": ip},
                chat_id=chat_id,
                user_id=user_id
            )
            if self.store(entry):
                stored += 1

        # Domain names
        domains = re.findall(r'(?:https?://)?([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)', user_message + " " + assistant_response)
        for domain in set(domains):
            content = f"Домен: {domain}"
            entry = MemoryEntry(
                content=content,
                memory_type=MemoryType.SEMANTIC,
                metadata={"type": "domain", "domain": domain},
                chat_id=chat_id,
                user_id=user_id
            )
            if self.store(entry):
                stored += 1

        # 3. Procedural: сохранить общий контекст задачи
        if len(user_message) > 20:
            summary = f"Задача: {user_message[:300]}"
            if assistant_response:
                summary += f" | Ответ: {assistant_response[:200]}"
            entry = MemoryEntry(
                content=summary,
                memory_type=MemoryType.PROCEDURAL,
                metadata={"type": "task_summary"},
                chat_id=chat_id,
                user_id=user_id
            )
            if self.store(entry):
                stored += 1

        return stored

    def get_relevant_context(self, query: str, user_id: str = None,
                              limit: int = 3) -> str:
        """
        Получить релевантный контекст из памяти для добавления в промпт.
        Cross-chat: ищет по всем чатам пользователя.
        """
        memories = self.search(
            query=query,
            limit=limit,
            user_id=user_id,
            min_score=0.15
        )

        if not memories:
            return ""

        context_parts = []
        for mem in memories:
            mem_type = mem.get("memory_type", "")
            content = mem.get("content", "")
            score = mem.get("score", 0)

            type_label = {
                MemoryType.EPISODIC: "📝",
                MemoryType.SEMANTIC: "💡",
                MemoryType.PROCEDURAL: "🔧"
            }.get(mem_type, "📌")

            context_parts.append(f"{type_label} {content}")

        return "\n".join(context_parts)

    def get_stats(self) -> Dict:
        """Get memory statistics."""
        if not self._initialized:
            return {"total": 0, "initialized": False}

        try:
            info = self._client.get_collection(self.COLLECTION_NAME)
            return {
                "total": info.points_count,
                "initialized": True,
                "vector_dim": TFIDFEmbedder.VECTOR_DIM,
                "collection": self.COLLECTION_NAME
            }
        except Exception as e:
            return {"total": 0, "initialized": False, "error": str(e)}

    def clear(self, user_id: str = None, chat_id: str = None) -> bool:
        """Clear memories (all or filtered)."""
        if not self._initialized:
            return False

        try:
            if not user_id and not chat_id:
                # Clear all
                self._client.delete_collection(self.COLLECTION_NAME)
                self._init_collection()
                self._point_id_counter = 0
                return True

            # Filtered delete
            conditions = []
            if user_id:
                conditions.append(
                    FieldCondition(key="user_id", match=MatchValue(value=user_id))
                )
            if chat_id:
                conditions.append(
                    FieldCondition(key="chat_id", match=MatchValue(value=chat_id))
                )

            from qdrant_client.models import FilterSelector
            self._client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=FilterSelector(filter=Filter(must=conditions))
            )
            return True
        except Exception as e:
            logger.error(f"Memory clear error: {e}")
            return False


# ══════════════════════════════════════════════════════════════════
# ██ SINGLETON ██
# ══════════════════════════════════════════════════════════════════

_memory_instance: Optional[VectorMemory] = None


def get_memory() -> VectorMemory:
    """Get singleton VectorMemory instance."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = VectorMemory()
    return _memory_instance
