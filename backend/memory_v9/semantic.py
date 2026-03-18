"""
L3: Semantic Memory — нейросетевые эмбеддинги + Qdrant persistent.
Fallback на TF-IDF если sentence-transformers не установлен.
"""
import os, json, logging, hashlib, threading
from typing import List, Dict, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.semantic")
_instance = None
_lock = threading.Lock()


class SemanticMemory:
    """Векторная память с Qdrant."""

    COLLECTION = "orion_memory"

    def __init__(self):
        self._client = None
        self._encoder = None
        self._use_neural = False
        self._tfidf_store: List[Dict] = []
        self._init()

    def _init(self):
        # Попытка инициализировать Qdrant
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
            os.makedirs(MemoryConfig.QDRANT_PATH, exist_ok=True)
            self._client = QdrantClient(path=MemoryConfig.QDRANT_PATH)
            # Попытка загрузить нейросетевые эмбеддинги
            if MemoryConfig.USE_NEURAL_EMBEDDINGS:
                try:
                    from sentence_transformers import SentenceTransformer
                    self._encoder = SentenceTransformer(MemoryConfig.EMBEDDING_MODEL)
                    self._use_neural = True
                    dim = MemoryConfig.EMBEDDING_DIM
                    logger.info("Neural embeddings loaded")
                except ImportError:
                    logger.warning("sentence-transformers not found, using TF-IDF fallback")
                    dim = MemoryConfig.EMBEDDING_FALLBACK_DIM
            else:
                dim = MemoryConfig.EMBEDDING_FALLBACK_DIM

            # Создать коллекцию если нет
            try:
                self._client.get_collection(self.COLLECTION)
            except:
                from qdrant_client.models import Distance, VectorParams
                self._client.create_collection(
                    self.COLLECTION,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
                )
        except Exception as e:
            logger.warning(f"Qdrant init failed: {e}, using in-memory fallback")
            self._client = None

    def _embed(self, text: str) -> List[float]:
        if self._use_neural and self._encoder:
            return self._encoder.encode(text).tolist()
        # TF-IDF fallback
        return self._tfidf_embed(text)

    def _tfidf_embed(self, text: str) -> List[float]:
        """Простой хэш-эмбеддинг как fallback."""
        import hashlib
        dim = MemoryConfig.EMBEDDING_FALLBACK_DIM
        vec = [0.0] * dim
        words = text.lower().split()
        for i, word in enumerate(words):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % dim
            vec[idx] += 1.0 / (i + 1)
        # Нормализация
        norm = sum(x*x for x in vec) ** 0.5
        if norm > 0:
            vec = [x/norm for x in vec]
        return vec

    def store(self, content: str, memory_type: str = "semantic",
              metadata: Dict = None, user_id: str = None,
              confidence: float = 0.8) -> bool:
        try:
            point_id = int(hashlib.md5(f"{content}{user_id}".encode()).hexdigest()[:8], 16)
            payload = {
                "content": content[:2000],
                "type": memory_type,
                "user_id": user_id or "default",
                "confidence": confidence,
                **(metadata or {})
            }
            if self._client:
                from qdrant_client.models import PointStruct
                vector = self._embed(content)
                self._client.upsert(
                    collection_name=self.COLLECTION,
                    points=[PointStruct(id=point_id, vector=vector, payload=payload)]
                )
            else:
                # In-memory fallback
                self._tfidf_store.append({"id": point_id, "content": content, **payload})
                if len(self._tfidf_store) > 1000:
                    self._tfidf_store = self._tfidf_store[-1000:]
            return True
        except Exception as e:
            logger.error(f"SemanticMemory store: {e}")
            return False

    def search(self, query: str, limit: int = 5,
               user_id: str = None, memory_type: str = None) -> List[Dict]:
        try:
            if self._client:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                vector = self._embed(query)
                # Build filter with user_id AND memory_type
                conditions = []
                if user_id:
                    conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
                if memory_type:
                    conditions.append(FieldCondition(key="type", match=MatchValue(value=memory_type)))
                filt = Filter(must=conditions) if conditions else None
                results = self._client.search(
                    collection_name=self.COLLECTION,
                    query_vector=vector,
                    limit=limit,
                    query_filter=filt
                )
                out = []
                for r in results:
                    if r.score >= MemoryConfig.MEMORY_MIN_SCORE:
                        item = dict(r.payload)
                        item["score"] = r.score
                        out.append(item)
                return out
            else:
                # In-memory fallback: простой поиск по словам
                query_words = set(query.lower().split())
                scored = []
                for item in self._tfidf_store:
                    if user_id and item.get("user_id") != user_id:
                        continue
                    if memory_type and item.get("type") != memory_type:
                        continue
                    content_words = set(item.get("content", "").lower().split())
                    score = len(query_words & content_words) / max(len(query_words), 1)
                    if score > 0:
                        scored.append({**item, "score": score})
                scored.sort(key=lambda x: x["score"], reverse=True)
                return scored[:limit]
        except Exception as e:
            logger.error(f"SemanticMemory search: {e}")
            return []

    def get_all_by_type(self, memory_type: str, user_id: str = None,
                        limit: int = 100) -> List[Dict]:
        """Загрузить ВСЕ записи определённого типа без семантического поиска."""
        try:
            if self._client:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                conditions = [FieldCondition(key="type", match=MatchValue(value=memory_type))]
                if user_id:
                    conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
                filt = Filter(must=conditions)
                results, _next = self._client.scroll(
                    collection_name=self.COLLECTION,
                    scroll_filter=filt,
                    limit=limit,
                    with_payload=True
                )
                return [dict(r.payload) for r in results if r.payload.get("content")]
            else:
                # In-memory fallback
                out = []
                for item in self._tfidf_store:
                    if item.get("type") != memory_type:
                        continue
                    if user_id and item.get("user_id") != user_id:
                        continue
                    out.append(item)
                return out[:limit]
        except Exception as e:
            logger.error(f"SemanticMemory get_all_by_type: {e}")
            return []

    def rerank(self, results: List[Dict], query: str, call_llm) -> List[Dict]:
        """Переранжировать результаты через LLM."""
        if not results or len(results) <= 1:
            return results
        try:
            items_text = "\n".join(
                f"{i+1}. {r.get('content','')[:150]}"
                for i, r in enumerate(results)
            )
            resp = call_llm([
                {"role": "system", "content": "Выбери наиболее релевантные пункты. Ответь только номерами через запятую: 1,3,2"},
                {"role": "user", "content": f"Запрос: {query}\n\nПункты:\n{items_text}"}
            ])
            nums = [int(x.strip()) - 1 for x in resp.split(",") if x.strip().isdigit()]
            reranked = [results[i] for i in nums if 0 <= i < len(results)]
            remaining = [r for i, r in enumerate(results) if i not in nums]
            return reranked + remaining
        except:
            return results


def get_semantic() -> SemanticMemory:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = SemanticMemory()
    return _instance
