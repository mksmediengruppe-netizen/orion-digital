"""
ORION LLM Cache
================
Caches LLM responses to reduce costs and latency.
Supports Redis (if available) with in-memory fallback.

Usage:
    from llm_cache import LLMCache
    cache = LLMCache()
    
    # Check cache before calling LLM
    cached = cache.get(model, messages, tools)
    if cached:
        return cached
    
    # After LLM call, store result
    cache.set(model, messages, tools, response)
"""

import hashlib
import json
import logging
import time
import threading
from typing import Optional, Any, List, Dict
from collections import OrderedDict

logger = logging.getLogger(__name__)

# ── Redis connection (optional) ──
_redis_client = None
_redis_checked = False


def _get_redis():
    """Try to connect to Redis, return None if unavailable."""
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    try:
        import redis
        client = redis.Redis(host="localhost", port=6379, db=2, decode_responses=True)
        client.ping()
        _redis_client = client
        logger.info("[LLM_CACHE] Redis connected (localhost:6379/2)")
    except Exception as e:
        logger.info(f"[LLM_CACHE] Redis not available ({e}), using in-memory cache")
        _redis_client = None
    return _redis_client


class LLMCache:
    """LLM response cache with Redis backend and in-memory fallback."""

    CACHE_PREFIX = "orion:llm_cache:"
    DEFAULT_TTL = 3600  # 1 hour
    MAX_MEMORY_ITEMS = 500

    def __init__(self, ttl: int = None):
        self.ttl = ttl or self.DEFAULT_TTL
        self._memory_cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _make_key(model: str, messages: List[Dict], tools: Optional[List] = None) -> str:
        """Create a deterministic cache key from model + messages + tools."""
        # Only cache based on the last N messages to avoid key explosion
        recent_messages = messages[-10:] if len(messages) > 10 else messages
        
        # Normalize messages for hashing (remove timestamps, etc.)
        normalized = []
        for msg in recent_messages:
            normalized.append({
                "role": msg.get("role", ""),
                "content": str(msg.get("content", ""))[:2000],  # cap content length
            })
        
        key_data = {
            "model": model,
            "messages": normalized,
            "tools": [t.get("function", {}).get("name", "") for t in (tools or [])],
        }
        key_str = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]

    def get(self, model: str, messages: List[Dict],
            tools: Optional[List] = None) -> Optional[Dict]:
        """Get cached LLM response. Returns None on miss."""
        try:
            key = self._make_key(model, messages, tools)
            
            # Try Redis first
            redis_client = _get_redis()
            if redis_client:
                try:
                    cached = redis_client.get(self.CACHE_PREFIX + key)
                    if cached:
                        data = json.loads(cached)
                        logger.debug(f"[LLM_CACHE] Redis HIT for {model} (key={key[:8]})")
                        return data
                except Exception as e:
                    logger.debug(f"[LLM_CACHE] Redis get error: {e}")
            
            # Fallback to memory
            with self._lock:
                if key in self._memory_cache:
                    entry = self._memory_cache[key]
                    if time.time() - entry["ts"] < self.ttl:
                        self._memory_cache.move_to_end(key)
                        logger.debug(f"[LLM_CACHE] Memory HIT for {model} (key={key[:8]})")
                        return entry["data"]
                    else:
                        del self._memory_cache[key]
            
            return None
        except Exception as e:
            logger.debug(f"[LLM_CACHE] get error: {e}")
            return None

    def set(self, model: str, messages: List[Dict],
            tools: Optional[List], response: Dict) -> None:
        """Store LLM response in cache."""
        try:
            # Don't cache tool-call responses (they depend on external state)
            if response.get("tool_calls"):
                return
            
            key = self._make_key(model, messages, tools)
            serialized = json.dumps(response, ensure_ascii=False, default=str)
            
            # Store in Redis
            redis_client = _get_redis()
            if redis_client:
                try:
                    redis_client.setex(self.CACHE_PREFIX + key, self.ttl, serialized)
                except Exception as e:
                    logger.debug(f"[LLM_CACHE] Redis set error: {e}")
            
            # Store in memory
            with self._lock:
                self._memory_cache[key] = {"data": response, "ts": time.time()}
                # Evict oldest if over limit
                while len(self._memory_cache) > self.MAX_MEMORY_ITEMS:
                    self._memory_cache.popitem(last=False)
                    
        except Exception as e:
            logger.debug(f"[LLM_CACHE] set error: {e}")

    def invalidate(self, model: str = None) -> int:
        """Invalidate cache entries. If model is None, clear all."""
        count = 0
        try:
            redis_client = _get_redis()
            if redis_client:
                try:
                    pattern = self.CACHE_PREFIX + "*"
                    keys = list(redis_client.scan_iter(pattern, count=100))
                    if keys:
                        count += redis_client.delete(*keys)
                except Exception as e:
                    logger.debug(f"[LLM_CACHE] Redis invalidate error: {e}")
            
            with self._lock:
                count += len(self._memory_cache)
                self._memory_cache.clear()
                
        except Exception as e:
            logger.debug(f"[LLM_CACHE] invalidate error: {e}")
        
        logger.info(f"[LLM_CACHE] Invalidated {count} entries")
        return count

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        redis_client = _get_redis()
        redis_size = 0
        if redis_client:
            try:
                keys = list(redis_client.scan_iter(self.CACHE_PREFIX + "*", count=100))
                redis_size = len(keys)
            except Exception:
                pass
        
        with self._lock:
            memory_size = len(self._memory_cache)
        
        return {
            "backend": "redis" if redis_client else "memory",
            "redis_entries": redis_size,
            "memory_entries": memory_size,
            "ttl_seconds": self.ttl,
            "max_memory_items": self.MAX_MEMORY_ITEMS,
        }


# ── Singleton instance ──
_default_cache = None
_cache_lock = threading.Lock()


def get_llm_cache() -> LLMCache:
    """Get or create the default LLM cache instance."""
    global _default_cache
    if _default_cache is None:
        with _cache_lock:
            if _default_cache is None:
                _default_cache = LLMCache()
    return _default_cache
