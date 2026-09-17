"""AI Conversation & Fact Memory Database Model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zeronexus.core.database import Base


class ConversationMemory(Base):
    """Stores short-term chat logs, shared channel context, and extracted long-term memories."""

    __tablename__ = "conversation_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)  # 'channel_shared', 'user_short_term', 'user_long_term'
    guild_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16))  # 'user', 'assistant', 'system'
    speaker_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    fact_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Key for long-term fact

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        Index("ix_memory_lookup", "scope", "guild_id", "channel_id", "user_id"),
    )
