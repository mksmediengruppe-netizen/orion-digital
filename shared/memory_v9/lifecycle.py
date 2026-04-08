"""
Memory Lifecycle — Decay, Consolidation, Conflict Resolution, Versioning.
Фоновые процессы для здоровья памяти.
"""
import json, os, time, logging, hashlib, shutil
from datetime import datetime, timezone, timedelta
from typing import Dict, List
from .config import MemoryConfig

logger = logging.getLogger("memory.lifecycle")

class MemoryDecay:
    """Снижает уверенность старых неиспользуемых фактов. Удаляет мёртвые."""

    @staticmethod
    def run(user_id: str = None):
        """Запускать по cron раз в сутки."""
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            if not sem._client: return
            from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector
            # Получить все точки пользователя
            scroll_filter = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]) if user_id else None
            points, _ = sem._client.scroll(collection_name=sem.COLLECTION, scroll_filter=scroll_filter, limit=1000, with_payload=True)
            now = time.time()
            to_delete = []
            for p in points:
                created = p.payload.get("created_at", "")
                confidence = p.payload.get("confidence", 0.5)
                try:
                    created_ts = datetime.fromisoformat(created).timestamp()
                    age_days = (now - created_ts) / 86400
                    if age_days > 30 and confidence < 0.5:
                        new_conf = max(0, confidence - MemoryConfig.DECAY_RATE)
                        if new_conf < MemoryConfig.DECAY_DELETE_THRESHOLD:
                            to_delete.append(p.id)
                        else:
                            sem._client.set_payload(collection_name=sem.COLLECTION,
                                                    payload={"confidence": new_conf}, points=[p.id])
                except: pass
            if to_delete:
                sem._client.delete(collection_name=sem.COLLECTION, points_selector=to_delete)
                logger.info(f"Decay: removed {len(to_delete)} stale memories")
        except Exception as e:
            logger.error(f"Decay failed: {e}")


class MemoryConsolidation:
    """Сжимает похожие воспоминания в одно. Запускать раз в неделю."""

    @staticmethod
    def run(user_id: str, call_llm=None):
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            if not sem._client: return
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            scroll_filter = Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])
            points, _ = sem._client.scroll(collection_name=sem.COLLECTION, scroll_filter=scroll_filter, limit=500, with_payload=True, with_vectors=True)
            if len(points) < 10: return
            # Найти пары с высоким сходством
            import numpy as np
            vectors = np.array([p.vector for p in points])
            merged = set()
            for i in range(len(points)):
                if i in merged: continue
                for j in range(i+1, len(points)):
                    if j in merged: continue
                    sim = float(np.dot(vectors[i], vectors[j]))
                    if sim > MemoryConfig.CONSOLIDATION_SIMILARITY:
                        # Объединить: оставить тот что с большей уверенностью
                        pi, pj = points[i], points[j]
                        ci = pi.payload.get("confidence", 0.5)
                        cj = pj.payload.get("confidence", 0.5)
                        keep, remove = (pi, pj) if ci >= cj else (pj, pi)
                        merged.add(points.index(remove))
                        # Повысить уверенность оставшегося
                        new_conf = min(1.0, max(ci, cj) + 0.1)
                        sem._client.set_payload(collection_name=sem.COLLECTION,
                                                payload={"confidence": new_conf}, points=[keep.id])
                        sem._client.delete(collection_name=sem.COLLECTION, points_selector=[remove.id])
            if merged:
                logger.info(f"Consolidation: merged {len(merged)} duplicate memories")
        except Exception as e:
            logger.error(f"Consolidation: {e}")


class MemoryVersioning:
    """Снимки состояния памяти для отката."""
    _dir = os.path.join(MemoryConfig.DATA_DIR, "memory_versions")

    @staticmethod
    def create_snapshot(label: str = "auto"):
        os.makedirs(MemoryVersioning._dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snap_dir = os.path.join(MemoryVersioning._dir, f"{ts}_{label}")
        os.makedirs(snap_dir, exist_ok=True)
        # Копируем все базы
        for db_path in [MemoryConfig.SESSION_DB, MemoryConfig.GRAPH_DB, MemoryConfig.PATTERNS_DB]:
            if os.path.exists(db_path):
                shutil.copy2(db_path, snap_dir)
        # Копируем Qdrant (если persistent)
        if os.path.exists(MemoryConfig.QDRANT_PATH):
            shutil.copytree(MemoryConfig.QDRANT_PATH, os.path.join(snap_dir, "qdrant"), dirs_exist_ok=True)
        # Ротация
        snaps = sorted(os.listdir(MemoryVersioning._dir))
        while len(snaps) > MemoryConfig.MAX_MEMORY_VERSIONS:
            shutil.rmtree(os.path.join(MemoryVersioning._dir, snaps.pop(0)), ignore_errors=True)
        logger.info(f"Memory snapshot: {snap_dir}")

    @staticmethod
    def list_snapshots() -> List[str]:
        if not os.path.exists(MemoryVersioning._dir): return []
        return sorted(os.listdir(MemoryVersioning._dir), reverse=True)


class ConflictResolver:
    """Когда два факта противоречат — выбрать более свежий/уверенный."""

    @staticmethod
    def resolve(facts: List[Dict]) -> List[Dict]:
        """Убрать конфликтующие факты, оставив лучшие."""
        if len(facts) < 2: return facts
        by_key = {}
        for f in facts:
            key = f.get("content", "")[:50].lower()
            if key not in by_key:
                by_key[key] = f
            else:
                existing = by_key[key]
                if f.get("confidence", 0) > existing.get("confidence", 0):
                    by_key[key] = f
                elif f.get("confidence", 0) == existing.get("confidence", 0):
                    if f.get("created_at", "") > existing.get("created_at", ""):
                        by_key[key] = f
        return list(by_key.values())
