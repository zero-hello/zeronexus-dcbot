"""ZeroNexus AI Daily Quota & Rate Management Service.

Enforces:
- 3-Phase atomic reservation: reserve -> commit / release
- In-flight request concurrency tracking and race condition prevention
- Asia/Taipei timezone (midnight 00:00 rollover)
- Default 80 AI requests / user / day (or configurable limit override)
- Developer bypass: DEV_USERS tracked for analytics, never rejected
- Automatic stale reservation garbage collection
- Natural language quota inquiry detection
- Quota reminder thresholds (20, 10, 5, 1) tracked once per threshold per day
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update

from zeronexus.core.config import config
from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.models.user import AIImageQuotaRecord, AIModelQuotaRecord, AIQuotaRecord


class QuotaReservation:
    """Represents an atomic reservation for a user's daily AI quota."""

    def __init__(
        self,
        user_id: int,
        date_str: str,
        reservation_id: str,
        effective_limit: int,
        is_dev: bool,
        projected_used: int,
    ) -> None:
        self.user_id = user_id
        self.date_str = date_str
        self.reservation_id = reservation_id
        self.effective_limit = effective_limit
        self.is_dev = is_dev
        self.projected_used = projected_used
        self.committed = False
        self.released = False
        self.created_at: float = time.time()


class QuotaService:
    """Centralized AI daily quota management service with 3-phase atomicity."""

    try:
        from zoneinfo import ZoneInfo

        class _TaipeiZone(ZoneInfo):
            def utcoffset(self, dt: Optional[datetime] = None) -> Optional[timedelta]:
                if dt is None:
                    dt = datetime.now(self)
                return super().utcoffset(dt)

        TAIPEI_TZ = _TaipeiZone("Asia/Taipei")
    except Exception:
        TAIPEI_TZ = timezone(timedelta(hours=8))

    DAILY_IMAGE_LIMIT: int = 3

    def __init__(self) -> None:
        self._user_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._in_flight: Dict[int, int] = defaultdict(int)
        self._active_reservations: Dict[str, QuotaReservation] = {}
        self._image_in_flight: Dict[int, int] = defaultdict(int)
        self._active_image_reservations: Dict[str, QuotaReservation] = {}
        # (user_id, date_str, threshold) -> bool
        self._reminded_thresholds: Dict[Tuple[int, str, int], bool] = {}

    def get_today_str(self) -> str:
        """Returns the current date string in Asia/Taipei timezone (YYYY-MM-DD)."""
        return datetime.now(self.TAIPEI_TZ).strftime("%Y-%m-%d")

    async def reserve_quota(
        self,
        user_id: int,
        max_daily_override: Optional[int] = None,
    ) -> Tuple[bool, Optional[QuotaReservation], int, int]:
        """Atomically checks and reserves 1 quota slot for user_id.

        Returns (allowed, reservation, projected_used, effective_limit).
        """
        today_str = self.get_today_str()
        default_limit = max_daily_override or config.ai.daily_limit_per_user
        is_dev = config.discord.is_dev(user_id)

        async with self._user_locks[user_id]:
            # Auto-cleanup stale uncommitted/unreleased reservations for this user (> 300s)
            now_ts = time.time()
            stale_user_res = [
                r for r in list(self._active_reservations.values())
                if r.user_id == user_id and not r.committed and not r.released and (now_ts - r.created_at > 300.0 or r.date_str != today_str)
            ]
            for sr in stale_user_res:
                self._in_flight[user_id] = max(0, self._in_flight[user_id] - 1)
                sr.released = True
                self._active_reservations.pop(sr.reservation_id, None)
                log.warning(f"Auto-reclaimed stale AI quota reservation {sr.reservation_id} for user {user_id}.")

            async with db.session() as session:
                stmt = select(AIQuotaRecord).where(
                    AIQuotaRecord.user_id == user_id,
                    AIQuotaRecord.date_str == today_str,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                current_used = record.used_count if record else 0
                effective_limit = (record.limit_override if record and record.limit_override else default_limit)

            # Strictly count in-flight reservations belonging to today's date
            today_in_flight = sum(
                1 for r in self._active_reservations.values()
                if r.user_id == user_id and r.date_str == today_str and not r.committed and not r.released
            )
            # Sync backward compatibility dictionary
            self._in_flight[user_id] = today_in_flight
            projected = current_used + today_in_flight + 1

            if not is_dev and (current_used + today_in_flight >= effective_limit):
                return False, None, current_used + today_in_flight, effective_limit

            self._in_flight[user_id] += 1
            res_id = uuid.uuid4().hex[:12]
            reservation = QuotaReservation(
                user_id=user_id,
                date_str=today_str,
                reservation_id=res_id,
                effective_limit=effective_limit,
                is_dev=is_dev,
                projected_used=projected,
            )
            self._active_reservations[res_id] = reservation
            return True, reservation, projected, effective_limit

    async def commit_quota(self, reservation: QuotaReservation) -> None:
        """Commits the reserved quota into the database upon successful response completion."""
        async with self._user_locks[reservation.user_id]:
            if reservation.committed or reservation.released:
                return

            async with db.session() as session:
                stmt = select(AIQuotaRecord).where(
                    AIQuotaRecord.user_id == reservation.user_id,
                    AIQuotaRecord.date_str == reservation.date_str,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                if not record:
                    record = AIQuotaRecord(
                        user_id=reservation.user_id,
                        date_str=reservation.date_str,
                        used_count=1,
                        limit_override=reservation.effective_limit,
                    )
                    session.add(record)
                else:
                    record.used_count += 1
                await session.flush()

            self._in_flight[reservation.user_id] = max(0, self._in_flight[reservation.user_id] - 1)
            reservation.committed = True
            self._active_reservations.pop(reservation.reservation_id, None)

    async def release_quota(self, reservation: QuotaReservation) -> None:
        """Releases the reserved quota slot without charging the user (e.g. upon pre-execution error or cancel)."""
        async with self._user_locks[reservation.user_id]:
            if reservation.committed or reservation.released:
                return

            self._in_flight[reservation.user_id] = max(0, self._in_flight[reservation.user_id] - 1)
            reservation.released = True
            self._active_reservations.pop(reservation.reservation_id, None)

    async def cleanup_stale_reservations(self, timeout_seconds: float = 300.0) -> int:
        """Purges uncommitted/unreleased reservations older than timeout_seconds to recover in-flight slots."""
        now = time.time()
        stale_reservations: List[QuotaReservation] = []
        for r in list(self._active_reservations.values()):
            if not r.committed and not r.released and (now - r.created_at > timeout_seconds):
                stale_reservations.append(r)

        for r in stale_reservations:
            await self.release_quota(r)
            log.warning(f"Reclaimed stale AI quota reservation {r.reservation_id} for user {r.user_id}.")

        return len(stale_reservations)

    async def get_user_quota_info(self, user_id: int) -> Dict[str, Any]:
        """Reads current quota usage metrics for user_id without modifying state."""
        today_str = self.get_today_str()
        default_limit = config.ai.daily_limit_per_user
        is_dev = config.discord.is_dev(user_id)

        async with db.session() as session:
            stmt = select(AIQuotaRecord).where(
                AIQuotaRecord.user_id == user_id,
                AIQuotaRecord.date_str == today_str,
            )
            res = await session.execute(stmt)
            record = res.scalars().first()
            used = record.used_count if record else 0
            limit = record.limit_override if record and record.limit_override else default_limit

        in_flight = self._in_flight.get(user_id, 0)
        total_used = used + in_flight
        remaining = 999999 if is_dev else max(0, limit - total_used)

        return {
            "user_id": user_id,
            "today_date": today_str,
            "used": total_used,
            "limit": limit,
            "remaining": remaining,
            "is_dev": is_dev,
            "reset_time": "每日凌晨 00:00 (台灣時間 / UTC+8)",
        }

    async def reset_user_quota(self, user_id: int, date_str: Optional[str] = None) -> bool:
        """Resets the quota usage for a specific user for today (or specified date)."""
        target_date = date_str or self.get_today_str()
        async with self._user_locks[user_id]:
            self._in_flight[user_id] = 0
            # Clear reminders
            for t in [20, 10, 5, 1]:
                self._reminded_thresholds.pop((user_id, target_date, t), None)

            async with db.session() as session:
                stmt = select(AIQuotaRecord).where(
                    AIQuotaRecord.user_id == user_id,
                    AIQuotaRecord.date_str == target_date,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                if record:
                    record.used_count = 0
                    await session.flush()
                    return True
                return False

    async def reset_all_daily_quotas(self, date_str: Optional[str] = None) -> int:
        """Resets all quota usage records for the specified date (defaults to today)."""
        target_date = date_str or self.get_today_str()
        self._in_flight.clear()
        self._reminded_thresholds.clear()
        self._active_reservations.clear()

        async with db.session() as session:
            stmt = update(AIQuotaRecord).where(AIQuotaRecord.date_str == target_date).values(used_count=0)
            res = await session.execute(stmt)
            return res.rowcount or 0

    # =========================================================================
    # Daily AI Image Generation Quota Management (Max 3 / user / day)
    # =========================================================================

    async def reserve_image_quota(
        self,
        user_id: int,
        max_daily_override: Optional[int] = None,
    ) -> Tuple[bool, Optional[QuotaReservation], int, int]:
        """Atomically checks and reserves 1 image generation quota slot for user_id (max 3/day).

        Returns (allowed, reservation, projected_used, effective_limit).
        """
        today_str = self.get_today_str()
        default_limit = max_daily_override or self.DAILY_IMAGE_LIMIT
        is_dev = config.discord.is_dev(user_id)

        async with self._user_locks[user_id]:
            # Auto-cleanup stale uncommitted/unreleased reservations for this user (> 300s or expired date)
            now_ts = time.time()
            stale_user_res = [
                r for r in list(self._active_image_reservations.values())
                if r.user_id == user_id and not r.committed and not r.released and (now_ts - r.created_at > 300.0 or r.date_str != today_str)
            ]
            for sr in stale_user_res:
                self._image_in_flight[user_id] = max(0, self._image_in_flight[user_id] - 1)
                sr.released = True
                self._active_image_reservations.pop(sr.reservation_id, None)
                log.warning(f"Auto-reclaimed stale AI image quota reservation {sr.reservation_id} for user {user_id}.")

            async with db.session() as session:
                stmt = select(AIImageQuotaRecord).where(
                    AIImageQuotaRecord.user_id == user_id,
                    AIImageQuotaRecord.date_str == today_str,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                current_used = record.used_count if record else 0
                effective_limit = (record.limit_override if record and record.limit_override else default_limit)

            # Strictly count in-flight reservations belonging to today's date (prevent midnight bleed)
            today_in_flight = sum(
                1 for r in self._active_image_reservations.values()
                if r.user_id == user_id and r.date_str == today_str and not r.committed and not r.released
            )
            self._image_in_flight[user_id] = today_in_flight
            projected = current_used + today_in_flight + 1

            if not is_dev and (current_used + today_in_flight >= effective_limit):
                return False, None, current_used + today_in_flight, effective_limit

            self._image_in_flight[user_id] += 1
            res_id = uuid.uuid4().hex[:12]
            reservation = QuotaReservation(
                user_id=user_id,
                date_str=today_str,
                reservation_id=res_id,
                effective_limit=effective_limit,
                is_dev=is_dev,
                projected_used=projected,
            )
            self._active_image_reservations[res_id] = reservation
            return True, reservation, projected, effective_limit

    async def commit_image_quota(self, reservation: QuotaReservation) -> None:
        """Commits the reserved image quota into the database upon successful image generation."""
        async with self._user_locks[reservation.user_id]:
            if reservation.committed or reservation.released:
                return

            async with db.session() as session:
                stmt = select(AIImageQuotaRecord).where(
                    AIImageQuotaRecord.user_id == reservation.user_id,
                    AIImageQuotaRecord.date_str == reservation.date_str,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                if record:
                    record.used_count += 1
                    record.updated_at = datetime.now(timezone.utc)
                else:
                    record = AIImageQuotaRecord(
                        user_id=reservation.user_id,
                        date_str=reservation.date_str,
                        used_count=1,
                    )
                    session.add(record)
                await session.flush()

            self._image_in_flight[reservation.user_id] = max(0, self._image_in_flight[reservation.user_id] - 1)
            reservation.committed = True
            self._active_image_reservations.pop(reservation.reservation_id, None)

    async def release_image_quota(self, reservation: QuotaReservation) -> None:
        """Releases the reserved image quota slot back if image generation fails or aborts."""
        async with self._user_locks[reservation.user_id]:
            if reservation.committed or reservation.released:
                return

            self._image_in_flight[reservation.user_id] = max(0, self._image_in_flight[reservation.user_id] - 1)
            reservation.released = True
            self._active_image_reservations.pop(reservation.reservation_id, None)

    async def get_user_image_quota_info(self, user_id: int) -> Dict[str, Any]:
        """Reads current image quota usage metrics for user_id."""
        today_str = self.get_today_str()
        default_limit = self.DAILY_IMAGE_LIMIT
        is_dev = config.discord.is_dev(user_id)

        async with db.session() as session:
            stmt = select(AIImageQuotaRecord).where(
                AIImageQuotaRecord.user_id == user_id,
                AIImageQuotaRecord.date_str == today_str,
            )
            res = await session.execute(stmt)
            record = res.scalars().first()
            used = record.used_count if record else 0
            limit = record.limit_override if record and record.limit_override else default_limit

        today_in_flight = sum(
            1 for r in self._active_image_reservations.values()
            if r.user_id == user_id and r.date_str == today_str and not r.committed and not r.released
        )
        self._image_in_flight[user_id] = today_in_flight
        total_used = used + today_in_flight
        remaining = 999999 if is_dev else max(0, limit - total_used)

        return {
            "user_id": user_id,
            "today_date": today_str,
            "used": total_used,
            "limit": limit,
            "remaining": remaining,
            "is_dev": is_dev,
            "reset_time": "每日凌晨 00:00 (台灣時間 / UTC+8)",
        }

    async def reset_user_image_quota(self, user_id: int, date_str: Optional[str] = None) -> bool:
        """Resets the image quota usage for a specific user for today (or specified date)."""
        target_date = date_str or self.get_today_str()
        async with self._user_locks[user_id]:
            self._image_in_flight[user_id] = 0
            async with db.session() as session:
                stmt = select(AIImageQuotaRecord).where(
                    AIImageQuotaRecord.user_id == user_id,
                    AIImageQuotaRecord.date_str == target_date,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                if record:
                    record.used_count = 0
                    await session.flush()
                    return True
                return False

    async def reset_all_daily_image_quotas(self, date_str: Optional[str] = None) -> int:
        """Resets all image quota usage records for the specified date (defaults to today)."""
        target_date = date_str or self.get_today_str()
        self._image_in_flight.clear()
        self._active_image_reservations.clear()

        async with db.session() as session:
            stmt = update(AIImageQuotaRecord).where(AIImageQuotaRecord.date_str == target_date).values(used_count=0)
            res = await session.execute(stmt)
            return res.rowcount or 0

    def is_quota_inquiry(self, text: str) -> bool:
        """Detects whether a user prompt is asking about remaining quota or reset time."""
        clean = (text or "").strip().lower()
        if not clean:
            return False
        patterns = [
            r"(?:我的|個人|目前|查看|查詢)?\s*(?:ai\s*)?對話額度",
            r"(?:我的|查看|查詢|個人|目前)\s*(?:ai\s*)?(?:對話)?\s*(?:可用\s*)?(?:額度|配額|次數)",
            r"(?:剩餘|剩下)\s*(?:的\s*)?(?:ai\s*)?(?:對話)?\s*(?:可用\s*)?(?:額度|配額|次數)",
            r"(?:額度|配額)\s*(?:查詢|查看|剩餘|還有多少)",
            r"(?:還剩|剩下|還有)\s*(?:多少|幾次)\s*(?:額度|配額|次數)?",
            r"(?:今天)?\s*用了\s*(?:多少|幾次)",
            r"(?:今天)?\s*還能\s*(?:問|用|聊|對話)\s*(?:多少|幾次)",
            r"(?:幾點|何時|什麼時候).*?(?:重置|重設|刷新)",
            r"\bquota\b",
        ]
        return any(re.search(p, clean) for p in patterns)

    def check_and_mark_reminder(self, user_id: int, remaining: int, date_str: str) -> Optional[int]:
        """Checks if remaining quota crosses a threshold (20, 10, 5, 1) and hasn't been reminded today.

        Developers have unlimited quota and are never sent low-quota warnings.
        """
        if config.discord.is_dev(user_id):
            return None

        thresholds = [20, 10, 5, 1]
        for t in thresholds:
            if remaining <= t:
                key = (user_id, date_str, t)
                if not self._reminded_thresholds.get(key, False):
                    self._reminded_thresholds[key] = True
                    return t
        return None

    # =========================================================================
    # Per-Model Independent Quota Management (每個模型都有自己的獨立餘額)
    # =========================================================================

    MODEL_DEFAULT_QUOTAS: Dict[str, int] = {
        # 極速輕量旗艦 (50 次/天)
        "gemini-3.1-flash-lite": 50,
        "gemini-2.5-flash": 50,
        "gemini-2.5-flash-lite": 50,
        "google/gemini-2.5-flash": 50,
        "google/gemini-2.5-flash-lite": 50,
        "openai/gpt-4o-mini": 50,
        "openrouter/free": 50,
        "google/gemma-4-26b-a4b-it:free": 50,
        "google/gemma-4-31b-it:free": 50,
        "liquid/lfm-2.5-2.6b:free": 50,
        "nvidia/nemotron-3.5-lightning:free": 50,

        # 頂尖對話與開源旗艦 (30 次/天)
        "deepseek-chat": 30,
        "deepseek/deepseek-chat": 30,
        "deepseek-v4.1-flash": 30,
        "deepseek/deepseek-v4-flash": 30,
        "qwen/qwen-2.5-72b-instruct": 30,
        "qwen/qwq-32b": 25,

        # 多模態視覺與頂級推理 (15~20 次/天)
        "deepseek/deepseek-v4-flash-vision-exp": 20,
        "qwen/qwen-2.5-vl-72b-instruct": 20,
        "deepseek-reasoner": 15,
        "deepseek/deepseek-r1": 15,
        "gemini-2.5-pro": 15,
        "google/gemini-2.5-pro": 15,
        "openai/gpt-4o": 15,
        "x-ai/grok-4.20": 15,

        # 圖像生成模型 (3 次/天)
        "gemini-2.5-flash-image": 3,
    }
    FALLBACK_MODEL_QUOTA: int = 30

    def get_model_default_limit(self, model_id: str) -> int:
        """Determines default daily quota limit for a given model_id."""
        clean_id = (model_id or "").strip().lower()
        if clean_id in self.MODEL_DEFAULT_QUOTAS:
            return self.MODEL_DEFAULT_QUOTAS[clean_id]

        for k, v in self.MODEL_DEFAULT_QUOTAS.items():
            if k.lower() in clean_id:
                return v

        # Heuristic fallbacks
        if any(w in clean_id for w in ["flash-lite", "lite", "mini", "free"]):
            return 50
        if any(w in clean_id for w in ["r1", "reasoner", "pro", "4o", "grok", "o1", "o3"]):
            return 15
        if any(w in clean_id for w in ["vl", "vision"]):
            return 20
        return self.FALLBACK_MODEL_QUOTA

    async def get_user_model_quota(self, user_id: int, model_id: str) -> Dict[str, Any]:
        """Queries daily usage and remaining balance for a specific user and model."""
        today_str = self.get_today_str()
        default_limit = self.get_model_default_limit(model_id)
        is_dev = config.discord.is_dev(user_id)

        async with db.session() as session:
            stmt = select(AIModelQuotaRecord).where(
                AIModelQuotaRecord.user_id == user_id,
                AIModelQuotaRecord.model_id == model_id,
                AIModelQuotaRecord.date_str == today_str,
            )
            res = await session.execute(stmt)
            record = res.scalars().first()
            used = record.used_count if record else 0
            limit = record.limit_override if record and record.limit_override else default_limit

        remaining = 999999 if is_dev else max(0, limit - used)

        return {
            "user_id": user_id,
            "model_id": model_id,
            "today_date": today_str,
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "is_dev": is_dev,
        }

    async def reserve_model_quota(
        self,
        user_id: int,
        model_id: str,
    ) -> Tuple[bool, Optional[QuotaReservation], int, int]:
        """Atomically checks and reserves 1 quota slot for a specific model."""
        today_str = self.get_today_str()
        default_limit = self.get_model_default_limit(model_id)
        is_dev = config.discord.is_dev(user_id)

        async with self._user_locks[user_id]:
            async with db.session() as session:
                stmt = select(AIModelQuotaRecord).where(
                    AIModelQuotaRecord.user_id == user_id,
                    AIModelQuotaRecord.model_id == model_id,
                    AIModelQuotaRecord.date_str == today_str,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                current_used = record.used_count if record else 0
                effective_limit = record.limit_override if record and record.limit_override else default_limit

            projected = current_used + 1
            if not is_dev and (current_used >= effective_limit):
                return False, None, current_used, effective_limit

            res_id = f"m_{uuid.uuid4().hex[:10]}"
            reservation = QuotaReservation(
                user_id=user_id,
                date_str=today_str,
                reservation_id=res_id,
                effective_limit=effective_limit,
                is_dev=is_dev,
                projected_used=projected,
            )
            # Store model_id on reservation
            reservation.model_id = model_id
            self._active_reservations[res_id] = reservation
            return True, reservation, projected, effective_limit

    async def commit_model_quota(self, reservation: QuotaReservation) -> None:
        """Commits model-specific quota usage into database upon successful completion."""
        model_id = getattr(reservation, "model_id", "default")
        async with self._user_locks[reservation.user_id]:
            if reservation.committed or reservation.released:
                return

            async with db.session() as session:
                stmt = select(AIModelQuotaRecord).where(
                    AIModelQuotaRecord.user_id == reservation.user_id,
                    AIModelQuotaRecord.model_id == model_id,
                    AIModelQuotaRecord.date_str == reservation.date_str,
                )
                res = await session.execute(stmt)
                record = res.scalars().first()
                if not record:
                    record = AIModelQuotaRecord(
                        user_id=reservation.user_id,
                        model_id=model_id,
                        date_str=reservation.date_str,
                        used_count=1,
                        limit_override=reservation.effective_limit,
                    )
                    session.add(record)
                else:
                    record.used_count += 1
                await session.flush()

            reservation.committed = True
            self._active_reservations.pop(reservation.reservation_id, None)

    async def format_model_quota_desc(self, user_id: int, model_id: str, tag: str = "") -> str:
        """Formats a descriptive string for Discord Select Menu options (< 100 characters)."""
        info = await self.get_user_model_quota(user_id, model_id)
        if info["is_dev"]:
            prefix = "今日剩餘：無上限"
        else:
            prefix = f"今日剩餘：{info['remaining']}/{info['limit']} 次"

        if tag:
            full = f"{prefix} ｜ {tag}"
        else:
            full = prefix

        return full[:100]


# Singleton instance
quota_service = QuotaService()
