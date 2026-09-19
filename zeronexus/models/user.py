"""User Profile, AI Quotas, and Economy Database Models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zeronexus.core.database import Base


class UserProfile(Base):
    """User preferences across ZeroNexus."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    preferred_persona: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    preferred_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    preferred_timezone: Mapped[str] = mapped_column(String(64), default="Asia/Taipei")
    show_thinking: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AIQuotaRecord(Base):
    """Tracks daily AI message usage per user to enforce quota limits."""

    __tablename__ = "ai_quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    date_str: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    limit_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AIImageQuotaRecord(Base):
    """Tracks daily AI image generation usage per user to enforce quota limits (max 3/day)."""

    __tablename__ = "ai_image_quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    date_str: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (Asia/Taipei)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    limit_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AIModelQuotaRecord(Base):
    """Tracks daily AI message usage per user per model to enforce per-model quota limits."""

    __tablename__ = "ai_model_quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    date_str: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (Asia/Taipei)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    limit_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class EconomyWallet(Base):
    """Virtual economy wallet and daily streak tracker."""

    __tablename__ = "economy_wallets"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    points: Mapped[int] = mapped_column(Integer, default=100)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_daily_claim: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UserAffinityRecord(Base):
    """Tracks affinity score (0-100), relationship tier, interactions, and AI impressions."""

    __tablename__ = "user_affinities"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=30.0)  # 預設起始值 30.0，最高 100.0，最低 0.0
    interactions_count: Mapped[int] = mapped_column(Integer, default=0)
    deep_chats_count: Mapped[int] = mapped_column(Integer, default=0)  # 深度心靈/私聊傾訴次數
    ai_impression: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI 心中專屬印象與評價
    last_interaction: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
