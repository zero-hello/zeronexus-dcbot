"""Custom AI Persona Database Model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zeronexus.core.database import Base


class CustomPersonaModel(Base):
    """User-created custom AI personas with distinct personality traits."""

    __tablename__ = "custom_personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text)
    personality: Mapped[str] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(String(64), default="友善自然")
    language: Mapped[str] = mapped_column(String(32), default="繁體中文")
    speaking_habits: Mapped[str] = mapped_column(Text, default="")
    forbidden_behaviors: Mapped[str] = mapped_column(Text, default="")
    emoji_preference: Mapped[str] = mapped_column(String(64), default="適度自然")
    response_style: Mapped[str] = mapped_column(Text, default="條理清晰")

    created_by_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    guild_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
