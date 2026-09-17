"""ZeroNexus Ticket System Database Models.

Persistence for guild ticket configurations and individual ticket records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zeronexus.core.database import Base


class TicketConfig(Base):
    """Server-wide configuration for the Ticket / Support Desk system."""

    __tablename__ = "ticket_configs"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    support_role_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    panel_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ticket_counter: Mapped[int] = mapped_column(Integer, default=0)


class TicketRecord(Base):
    """Individual ticket records with life-cycle tracking and claim attribution."""

    __tablename__ = "ticket_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    category: Mapped[str] = mapped_column(String(64), default="一般諮詢")
    subject: Mapped[str] = mapped_column(String(256), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="OPEN")  # OPEN, CLAIMED, CLOSED
    claimed_by_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    closed_by_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
