"""ZeroNexus Dual-Mode Cache System.

Features:
- In-Memory LRU + TTL asynchronous cache with thread-safe locks and size limits
- Optional Redis backend (activated if REDIS_URL is configured)
- Automatic cache hit/miss tracking and stats inspection
- Diagnostic health check probe
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional

from zeronexus.core.config import config
from zeronexus.core.logger import log


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class InMemoryCache:
    """High-performance thread-safe in-memory LRU cache with per-item TTL."""

    def __init__(self, max_items: int = 5000) -> None:
        self._max_items = max(1, max_items)
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self.hits: int = 0
        self.misses: int = 0

    @property
    def max_items(self) -> int:
        return self._max_items

    @max_items.setter
    def max_items(self, val: int) -> None:
        self._max_items = max(1, val)
        while len(self._store) > self._max_items and self._store:
            self._store.popitem(last=False)

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._store:
                self.misses += 1
                return None

            entry = self._store[key]
            now = time.time()
            if entry.expires_at > 0 and now > entry.expires_at:
                # Expired
                del self._store[key]
                self.misses += 1
                return None

            # Move to end (most recently used)
            self._store.move_to_end(key)
            self.hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: Optional[int] = 300) -> None:
        async with self._lock:
            now = time.time()
            if ttl is not None and ttl > 0:
                expires_at = now + ttl
            else:
                expires_at = 0.0

            if key in self._store:
                self._store[key] = CacheEntry(value=value, expires_at=expires_at)
                self._store.move_to_end(key)
            else:
                if len(self._store) >= self._max_items:
                    # Attempt to clean expired keys before evicting valid LRU entries
                    expired_keys = [
                        k for k, v in self._store.items()
                        if v.expires_at > 0 and now > v.expires_at
                    ]
                    for k in expired_keys:
                        del self._store[k]

                # Strictly enforce capacity boundary
                while len(self._store) >= self._max_items and self._store:
                    self._store.popitem(last=False)
                self._store[key] = CacheEntry(value=value, expires_at=expires_at)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def clean_expired(self) -> int:
        """Purges expired items from in-memory cache to prevent unbounded growth."""
        async with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._store.items()
                if v.expires_at > 0 and now > v.expires_at
            ]
            for k in expired_keys:
                del self._store[k]
            return len(expired_keys)

    async def count(self) -> int:
        async with self._lock:
            return len(self._store)

    def stats(self) -> Dict[str, Any]:
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0.0
        return {
            "mode": "In-Memory LRU",
            "keys_count": len(self._store),
            "max_items": self.max_items,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate_pct": round(hit_rate, 2),
        }


class CacheManager:
    """Unified cache facade managing either In-Memory or Redis backend."""

    def __init__(self) -> None:
        self._memory = InMemoryCache(max_items=config.cache.max_memory_items)
        self._redis: Any = None
        self._use_redis: bool = False
        self._is_initialized: bool = False

    async def initialize(self) -> None:
        if self._is_initialized:
            return

        redis_url = config.cache.redis_url
        if redis_url:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(redis_url, decode_responses=False)
                await self._redis.ping()
                self._use_redis = True
                log.info("Redis cache backend connected successfully.")
            except Exception as e:
                log.warning(f"Failed to connect to Redis at {redis_url}: {e}. Falling back to In-Memory cache.")
                self._use_redis = False
        self._memory.max_items = max(1, config.cache.max_memory_items)
        self._is_initialized = True

    async def get(self, key: str) -> Optional[Any]:
        if self._use_redis and self._redis:
            try:
                import pickle
                val = await self._redis.get(key)
                if val is not None:
                    return pickle.loads(val)
                return None
            except Exception as e:
                log.warning(f"Redis get failed: {e}. Falling back to memory.")
        return await self._memory.get(key)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else config.cache.default_ttl_seconds
        if self._use_redis and self._redis:
            try:
                import pickle
                data = pickle.dumps(value)
                if effective_ttl > 0:
                    await self._redis.setex(key, effective_ttl, data)
                else:
                    await self._redis.set(key, data)
                return
            except Exception as e:
                log.warning(f"Redis set failed: {e}. Falling back to memory.")
        await self._memory.set(key, value, ttl=effective_ttl)

    async def delete(self, key: str) -> bool:
        deleted = False
        if self._use_redis and self._redis:
            try:
                res = await self._redis.delete(key)
                deleted = bool(res > 0)
            except Exception as e:
                log.warning(f"Redis delete failed: {e}")
        mem_res = await self._memory.delete(key)
        return deleted or mem_res

    async def clear(self) -> None:
        if self._use_redis and self._redis:
            try:
                await self._redis.flushdb()
            except Exception as e:
                log.warning(f"Redis clear failed: {e}")
        await self._memory.clear()

    async def stats(self) -> Dict[str, Any]:
        s = self._memory.stats()
        if self._use_redis and self._redis:
            try:
                info = await self._redis.info()
                s["mode"] = "Redis + In-Memory Fallback"
                s["redis_connected"] = True
                s["redis_used_memory_human"] = info.get("used_memory_human", "N/A")
            except Exception:
                s["redis_connected"] = False
        return s

    async def get_stats(self) -> Dict[str, Any]:
        """相容性別名：獲取快取即時統計數據。"""
        return await self.stats()

    async def clean_expired(self) -> int:
        """Purges expired items from local in-memory store."""
        return await self._memory.clean_expired()

    async def close(self) -> None:
        """Gracefully closes cache connections and clears memory references."""
        if self._use_redis and self._redis:
            try:
                if hasattr(self._redis, "aclose"):
                    t = asyncio.create_task(self._redis.aclose())
                    try:
                        await asyncio.shield(t)
                    except asyncio.CancelledError:
                        await t
                elif hasattr(self._redis, "close"):
                    res = self._redis.close()
                    if inspect.isawaitable(res):
                        t = asyncio.create_task(res)
                        try:
                            await asyncio.shield(t)
                        except asyncio.CancelledError:
                            await t
                log.info("Redis cache connection closed.")
            except Exception as e:
                log.warning(f"Error closing Redis client: {e}")
            self._redis = None
            self._use_redis = False
        await self._memory.clear()
        self._is_initialized = False

    async def health_check(self) -> Dict[str, Any]:
        start_time = time.perf_counter()
        try:
            # Test set and get
            test_key = "__health_check_ping__"
            await self.set(test_key, "ok", ttl=10)
            val = await self.get(test_key)
            await self.delete(test_key)

            latency = (time.perf_counter() - start_time) * 1000
            is_healthy = val == "ok"
            return {
                "status": "GREEN" if is_healthy else "RED",
                "healthy": is_healthy,
                "latency_ms": round(latency, 2),
                "mode": "Redis" if self._use_redis else "In-Memory LRU",
            }
        except Exception as e:
            return {
                "status": "RED",
                "healthy": False,
                "latency_ms": round((time.perf_counter() - start_time) * 1000, 2),
                "error": str(e),
            }


# Singleton cache instance
cache = CacheManager()
