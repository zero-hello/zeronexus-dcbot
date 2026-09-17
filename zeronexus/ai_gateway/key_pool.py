"""ZeroNexus Multi-API-Key Pool & Health State Machine.

Manages rotating key pools per provider with:
- Key states: 🟢 Healthy, 🟡 Cooldown, 🔴 Disabled
- Exponential backoff upon 429 / Quota / Timeout
- Automatic recovery when cooldown expires
- Absolute secret redaction (only displays 'Key ••••A91F')
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional

from zeronexus.core.config import mask_secret
from zeronexus.core.logger import log


class KeyState(str, Enum):
    HEALTHY = "🟢 正常"
    COOLDOWN = "🟡 冷卻中"
    DISABLED = "🔴 已停用"


class ManagedKey:
    """Individual API Key tracking metrics and rate-limit states."""

    def __init__(self, raw_key: str, provider: str) -> None:
        self.raw_key = raw_key
        self.provider = provider
        self.masked = f"Key {mask_secret(raw_key, prefix_len=0, suffix_len=4)}"
        self.state: KeyState = KeyState.HEALTHY
        self.cooldown_until: float = 0.0
        self.consecutive_failures: int = 0
        self.total_calls: int = 0
        self.success_calls: int = 0
        self.total_latency_ms: float = 0.0
        self.has_paid_quota: bool = True
        self.is_fallback_key: bool = False
        self.free_only: bool = False

    @property
    def is_available(self) -> bool:
        if self.state == KeyState.DISABLED:
            return False
        if self.state == KeyState.COOLDOWN:
            if time.time() >= self.cooldown_until:
                self.state = KeyState.HEALTHY
                self.consecutive_failures = 0
                log.info(f"API {self.masked} ({self.provider}) cooldown elapsed. Restored to HEALTHY.")
                return True
            return False
        return True

    def is_available_for(self, requires_paid: bool = False) -> bool:
        """Checks if key is available for a request, accounting for paid quota requirement."""
        if not self.is_available:
            return False
        if requires_paid and (not self.has_paid_quota or self.free_only):
            return False
        return True

    def mark_success(self, latency_ms: float) -> None:
        self.total_calls += 1
        self.success_calls += 1
        self.consecutive_failures = 0
        self.total_latency_ms += latency_ms
        self.state = KeyState.HEALTHY

    def mark_paid_quota_exhausted(self) -> None:
        """Flags key as having exhausted paid model quota (e.g. OpenRouter 403 weekly limit)."""
        self.has_paid_quota = False
        log.warning(f"API {self.masked} ({self.provider}) marked as paid quota exhausted.")

    def mark_failure(self, is_quota: bool = True) -> None:
        self.total_calls += 1
        self.consecutive_failures += 1

        # 指數退避底數設限 (最高 2^10 = 1024)，防止極端連續失敗時大數次方爆炸
        backoff_power = min(max(0, self.consecutive_failures - 1), 10)
        backoff_seconds = min(600.0, 30.0 * (2 ** backoff_power))
        self.cooldown_until = time.time() + backoff_seconds

        if self.consecutive_failures >= 5 and not is_quota:
            self.state = KeyState.DISABLED
            log.error(f"API {self.masked} ({self.provider}) exceeded 5 consecutive critical errors. Marked DISABLED.")
        else:
            self.state = KeyState.COOLDOWN
            log.warning(
                f"API {self.masked} ({self.provider}) entered COOLDOWN for {backoff_seconds:.1f}s "
                f"(consecutive failures: {self.consecutive_failures})."
            )

    def summary(self) -> Dict[str, Any]:
        _ = self.is_available  # Refresh state if cooldown elapsed
        now = time.time()
        remaining_cd = max(0, int(self.cooldown_until - now)) if self.state == KeyState.COOLDOWN else 0
        avg_latency = (self.total_latency_ms / self.success_calls) if self.success_calls > 0 else 0.0

        return {
            "masked": self.masked,
            "provider": self.provider,
            "state": self.state.value,
            "cooldown_remaining_seconds": remaining_cd,
            "success_rate": f"{(self.success_calls / self.total_calls * 100):.1f}%" if self.total_calls > 0 else "N/A",
            "avg_latency_ms": round(avg_latency, 2),
            "consecutive_failures": self.consecutive_failures,
            "has_paid_quota": self.has_paid_quota,
        }



class ProviderKeyPool:
    """Manages rotation and failover across multiple keys of a single provider."""

    def __init__(self, provider: str, keys: List[str]) -> None:
        import threading
        self._lock = threading.Lock()
        self.provider = provider
        self._keys: List[ManagedKey] = [self._create_key(k) for k in keys if k.strip()]
        self._index: int = 0

    def _create_key(self, raw_key: str) -> ManagedKey:
        k_obj = ManagedKey(raw_key.strip(), self.provider)
        try:
            from zeronexus.core.config import config
            fb_key = getattr(config.ai, "openrouter_fallback_key", "")
            if self.provider == "openrouter" and fb_key and raw_key.strip() == fb_key:
                k_obj.is_fallback_key = True
                k_obj.free_only = True
        except Exception:
            pass
        return k_obj

    def add_keys(self, new_keys: List[str]) -> None:
        with self._lock:
            existing = {k.raw_key for k in self._keys}
            for k in new_keys:
                if k.strip() and k.strip() not in existing:
                    self._keys.append(self._create_key(k.strip()))

    def get_available_key(self, requires_paid: bool = False) -> Optional[ManagedKey]:
        """Selects the next available healthy key via round-robin.
        If requires_paid is True, filters only keys with active paid quota."""
        with self._lock:
            if not self._keys:
                return None

            total = len(self._keys)
            for _ in range(total):
                candidate = self._keys[self._index % total]
                self._index = (self._index + 1) % total
                if candidate.is_available_for(requires_paid=requires_paid):
                    return candidate
            return None

    @property
    def has_active_keys(self) -> bool:
        with self._lock:
            return any(k.is_available for k in self._keys)

    def has_active_paid_keys(self) -> bool:
        with self._lock:
            return any(k.is_available and k.has_paid_quota for k in self._keys)

    def reset(self) -> None:
        """Resets all keys in the pool to HEALTHY state and clears failure counters."""
        with self._lock:
            for k in self._keys:
                k.state = KeyState.HEALTHY
                k.cooldown_until = 0.0
                k.consecutive_failures = 0
                k.has_paid_quota = True

    def get_status_summary(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [k.summary() for k in self._keys]
