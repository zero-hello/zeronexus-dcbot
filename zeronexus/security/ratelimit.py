"""ZeroNexus Rate Limiting & Cooldown Engine.

Enforces:
- Command cooldowns (per-user / per-guild sliding windows)
- AI burst cooldown (prevent spamming LLM inference)
- AI daily quotas (persisted in database with 00:00 midnight reset)
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Tuple


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter with LRU-style bounded capacity."""

    def __init__(self, max_keys: int = 10000) -> None:
        # key -> list of timestamps
        self._windows: Dict[str, List[float]] = defaultdict(list)
        self._max_keys = max_keys

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: float) -> Tuple[bool, float]:
        """Checks if key exceeded max_requests in window_seconds.

        Returns (is_limited, retry_after_seconds).
        """
        now = time.time()

        # Prevent unbounded dictionary growth under DDoS or high cardinality attacks
        if len(self._windows) >= self._max_keys and key not in self._windows:
            self.cleanup()
            if len(self._windows) >= self._max_keys:
                sorted_keys = sorted(
                    self._windows.keys(),
                    key=lambda k: self._windows[k][-1] if self._windows[k] else 0,
                )
                for k in sorted_keys[:100]:
                    del self._windows[k]

        timestamps = self._windows[key]

        # Purge timestamps older than the window
        cutoff = now - window_seconds
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

        if len(timestamps) >= max_requests:
            retry_after = round(window_seconds - (now - timestamps[0]), 1)
            return True, max(0.1, retry_after)

        timestamps.append(now)
        return False, 0.0

    def reset(self, key: str) -> None:
        if key in self._windows:
            del self._windows[key]

    def cleanup(self) -> int:
        """Prunes stale keys where all timestamps have expired beyond 1 hour."""
        now = time.time()
        stale_keys = [k for k, v in self._windows.items() if not v or (now - v[-1] > 3600)]
        for k in stale_keys:
            del self._windows[k]
        return len(stale_keys)


from zeronexus.ai_gateway.quota_service import (
    QuotaReservation,
    QuotaService,
    quota_service,
)

__all__ = [
    "rate_limiter",
    "RateLimiter",
    "SlidingWindowRateLimiter",
    "QuotaReservation",
    "QuotaService",
    "quota_service",
]


class RateLimiter:
    """Master Rate Limiter combining in-memory cooldowns and persistent AI daily quotas."""

    def __init__(self) -> None:
        self._limiter = SlidingWindowRateLimiter()
        self.quota_service = quota_service

    def cleanup(self) -> int:
        """Prunes stale in-memory rate limit tracking windows."""
        return self._limiter.cleanup()

    def check_command_cooldown(self, user_id: int, command_name: str, cooldown_seconds: float = 2.0) -> Tuple[bool, float]:
        key = f"cmd:{user_id}:{command_name}"
        return self._limiter.is_rate_limited(key, max_requests=1, window_seconds=cooldown_seconds)

    def check_ai_burst(self, user_id: int, cooldown_seconds: float = 5.0) -> Tuple[bool, float]:
        key = f"ai_burst:{user_id}"
        return self._limiter.is_rate_limited(key, max_requests=1, window_seconds=cooldown_seconds)

    async def check_and_consume_ai_quota(self, user_id: int, max_daily_override: int | None = None) -> Tuple[bool, int, int]:
        """Convenience method for command callers to atomically reserve and commit AI quota."""
        allowed, res, used, limit = await self.quota_service.reserve_quota(user_id, max_daily_override)
        if allowed and res:
            await self.quota_service.commit_quota(res)
        return allowed, used, limit


# Singleton instances
rate_limiter = RateLimiter()


