"""Persistent mini-game score models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zeronexus.core.database import Base


class Game2048BestScore(Base):
    __tablename__ = "game_2048_best_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    best_score: Mapped[int] = mapped_column(Integer, default=0)
    best_tile: Mapped[int] = mapped_column(Integer, default=0)
    best_moves: Mapped[int] = mapped_column(Integer, default=0)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_game_2048_guild_user"),
        Index("ix_game_2048_guild_score", "guild_id", "best_score"),
    )
