"""
L3: Semantic Memory — нейросетевые эмбеддинги + persistent Qdrant + LLM re-ranking.
Замена TF-IDF на sentence-transformers. Память переживает рестарты.
"""
import json, os, hashlib, time, logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from .config import MemoryConfig

logger = logging.getLogger("memory.semantic")

# ── Embedder ──

class NeuralEmbedder:
    """sentence-transformers с fallback на TF-IDF."""
    def __init__(self):
        self._model = None
        self._tfidf = None
        self._corpus = []
        self.dim = MemoryConfig.EMBEDDING_DIM
        self._init()

    def _init(self):
        if MemoryConfig.USE_NEURAL_EMBEDDINGS:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(MemoryConfig.EMBEDDING_MODEL)
                self.dim = self._model.get_sentence_embedding_dimension()
                logger.info(f"Neural embedder: {MemoryConfig.EMBEDDING_MODEL} ({self.dim}d)")
                return
            except ImportError:
                logger.warning("sentence-transformers not installed, using TF-IDF")
            except Exception as e:
                logger.warning(f"Neural embedder failed: {e}, using TF-IDF")
        self.dim = MemoryConfig.EMBEDDING_FALLBACK_DIM
        self._init_tfidf()

    def _init_tfidf(self):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            import numpy as np
            self._tfidf = TfidfVectorizer(max_features=self.dim, ngram_range=(1,2), sublinear_tf=True)
            self._np = np
        except: pass

    def embed(self, text: str) -> List[float]:
        if self._model:
            return self._model.encode(text, normalize_embeddings=True).tolist()
        return self._tfidf_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if self._model:
            return self._model.encode(texts, normalize_embeddings=True).tolist()
        return [self._tfidf_embed(t) for t in texts]

    def _tfidf_embed(self, text: str) -> List[float]:
        if not self._tfidf: return [0.0] * self.dim
        self._corpus.append(text)
        try:
            self._tfidf.fit(self._corpus)
            vec = self._tfidf.transform([text]).toarray()[0]
            if len(vec) < self.dim: vec = self._np.pad(vec, (0, self.dim - len(vec)))
            elif len(vec) > self.dim: vec = vec[:self.dim]
            return vec.tolist()
        except: return [0.0] * self.dim


class SemanticMemory:
    """Persistent Qdrant + neural embeddings."""

    COLLECTION = "agent_memory_v9"

    def __init__(self):
        self._embedder = NeuralEmbedder()
        self._client = None
        self._counter = 0
        self._init_qdrant()

    def _init_qdrant(self):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import VectorParams, Distance
            os.makedirs(MemoryConfig.QDRANT_PATH, exist_ok=True)
            self._client = QdrantClient(path=MemoryConfig.QDRANT_PATH)
            cols = [c.name for c in self._client.get_collections().collections]
            if self.COLLECTION not in cols:
                self._client.create_collection(
                    collection_name=self.COLLECTION,
                    vectors_config=VectorParams(size=self._embedder.dim, distance=Distance.COSINE)
                )
            info = self._client.get_collection(self.COLLECTION)
            self._counter = info.points_count
            logger.info(f"SemanticMemory: {self._counter} points, {self._embedder.dim}d")
        except Exception as e:
            logger.error(f"Qdrant init failed: {e}")
            self._client = None

    def store(self, content: str, memory_type: str = "semantic",
              metadata: Dict = None, chat_id: str = None,
              user_id: str = None, confidence: float = 0.8) -> bool:
        if not self._client: return False
        try:
            from qdrant_client.models import PointStruct
            vec = self._embedder.embed(content[:2000])
            self._counter += 1
            self._client.upsert(collection_name=self.COLLECTION, points=[PointStruct(
                id=self._counter, vector=vec,
                payload={"content": content[:2000], "type": memory_type,
                         "metadata": json.dumps(metadata or {}),
                         "chat_id": chat_id or "", "user_id": user_id or "",
                         "confidence": confidence,
                         "created_at": datetime.now(timezone.utc).isoformat(),
                         "access_count": 0}
            )])
            return True
        except Exception as e:
            logger.error(f"Semantic store: {e}"); return False

    def search(self, query: str, limit: int = 5, user_id: str = None,
               memory_type: str = None, min_score: float = None) -> List[Dict]:
        if not self._client: return []
        min_score = min_score or MemoryConfig.MEMORY_MIN_SCORE
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            vec = self._embedder.embed(query)
            conditions = []
            if user_id: conditions.append(FieldCondition(key="user_id", match=MatchValue(value=user_id)))
            if memory_type: conditions.append(FieldCondition(key="type", match=MatchValue(value=memory_type)))
            qf = Filter(must=conditions) if conditions else None
            resp = self._client.query_points(collection_name=self.COLLECTION, query=vec, limit=limit, query_filter=qf, score_threshold=min_score)
            results = []
            for hit in resp.points:
                p = hit.payload
                results.append({"content": p.get("content",""), "type": p.get("type",""),
                                "score": hit.score, "chat_id": p.get("chat_id",""),
                                "user_id": p.get("user_id",""), "confidence": p.get("confidence",0.5),
                                "metadata": json.loads(p.get("metadata","{}"))})
            return results
        except Exception as e:
            logger.error(f"Semantic search: {e}"); return []

    def rerank(self, results: List[Dict], query: str, call_llm) -> List[Dict]:
        """LLM re-ranking: убрать шум из результатов поиска."""
        if not call_llm or len(results) <= 2: return results
        try:
            facts = "\n".join(f"{i+1}. {r['content'][:150]}" for i,r in enumerate(results[:10]))
            resp = call_llm([
                {"role":"system","content":"Из списка фактов выбери ТОЛЬКО релевантные задаче. Ответь номерами через запятую. Если ничего — 'none'."},
                {"role":"user","content":f"Задача: {query[:300]}\n\nФакты:\n{facts}"}
            ])
            if "none" in resp.lower(): return results[:2]
            import re
            nums = [int(n) for n in re.findall(r'\d+', resp)]
            reranked = [results[n-1] for n in nums if 0 < n <= len(results)]
            if reranked:
                for r in reranked: r["score"] += 0.3
                return reranked
        except: pass
        return results

    def get_stats(self) -> Dict:
        if not self._client: return {"total": 0}
        try:
            info = self._client.get_collection(self.COLLECTION)
            return {"total": info.points_count, "dim": self._embedder.dim,
                    "neural": self._embedder._model is not None}
        except: return {"total": 0}

# Singleton
_instance = None
def get_semantic() -> SemanticMemory:
    global _instance
    if _instance is None: _instance = SemanticMemory()
    return _instance
