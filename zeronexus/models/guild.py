"""Guild Settings Database Model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zeronexus.core.database import Base


class GuildSettings(Base):
    """Stores per-server preferences, automated channels, and toggles."""

    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prefix: Mapped[str] = mapped_column(String(16), default="zn!")
    locale: Mapped[str] = mapped_column(String(16), default="zh-TW")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Taipei")

    # Welcome message configuration
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    welcome_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Leave message configuration
    leave_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    leave_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    leave_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Autorole configuration
    autorole_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    autorole_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Audit & moderation logging channel
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    log_events_mask: Mapped[int] = mapped_column(Integer, default=0)

    # AI Channel
    ai_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ai_daily_limit: Mapped[int] = mapped_column(Integer, default=50)
    ai_persona: Mapped[str] = mapped_column(String(64), default="normal_persona")
    ai_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    @property
    def default_ai_model(self) -> Optional[str]:
        return self.ai_model

    @default_ai_model.setter
    def default_ai_model(self, value: Optional[str]) -> None:
        self.ai_model = value

    # Music configuration
    dj_role_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    music_default_volume: Mapped[int] = mapped_column(Integer, default=80)

    # Earthquake auto-notification channel & policies
    earthquake_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    earthquake_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    earthquake_min_magnitude: Mapped[float] = mapped_column(Float, default=4.0)
    earthquake_min_intensity: Mapped[int] = mapped_column(Integer, default=1)

    # Weather auto-notification channel & target county
    weather_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    weather_county: Mapped[str] = mapped_column(String(32), default="臺北市")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class EarthquakeNotificationRecord(Base):
    """Stores persistent deduplication records for sent earthquake notifications across guilds."""

    __tablename__ = "earthquake_notification_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "115060"
    origin_time: Mapped[str] = mapped_column(String(64), default="")
    magnitude: Mapped[float] = mapped_column(Float, default=0.0)
    depth: Mapped[str] = mapped_column(String(32), default="")
    location: Mapped[str] = mapped_column(String(256), default="")
    max_intensity: Mapped[str] = mapped_column(String(32), default="")
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), default="DELIVERED")
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default=None)
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

