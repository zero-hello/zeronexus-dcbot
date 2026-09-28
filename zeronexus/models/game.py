"""Persistent mini-game score models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
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


class PredictionMarketRecord(Base):
    """Durable guild prediction market and settlement state."""

    __tablename__ = "prediction_markets"

    market_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    creator_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(500))
    option_a: Mapped[str] = mapped_column(String(100))
    option_b: Mapped[str] = mapped_column(String(100))
    pool_a: Mapped[int] = mapped_column(BigInteger, default=0)
    pool_b: Mapped[int] = mapped_column(BigInteger, default=0)
    is_settled: Mapped[bool] = mapped_column(Boolean, default=False)
    winning_option: Mapped[str | None] = mapped_column(String(1), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=lambda: __import__("time").time())


class PredictionBetRecord(Base):
    """Durable individual wagers belonging to a prediction market."""

    __tablename__ = "prediction_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    option: Mapped[str] = mapped_column(String(1))
    amount: Mapped[int] = mapped_column(BigInteger)
    timestamp: Mapped[float] = mapped_column(Float, default=lambda: __import__("time").time())
