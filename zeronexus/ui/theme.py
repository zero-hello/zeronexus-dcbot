"""ZeroNexus Design System Themes, Colors, and Typography Standards."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

import discord
import pytz

from zeronexus.core.config import config


class _ZNColorMeta(type):
    """防禦性元類別，當請求未定義之顏色常數時安全回傳 PRIMARY，徹底杜絕 AttributeError。"""
    def __getattr__(cls, name: str) -> discord.Color:
        return cls.PRIMARY


class ZNColor(metaclass=_ZNColorMeta):
    """Standardized color palette for ZeroNexus Components V2 cards."""
    PRIMARY = discord.Color.from_rgb(88, 101, 242)      # ZeroNexus Blurple
    SUCCESS = discord.Color.from_rgb(46, 204, 113)      # Emerald Green
    WARNING = discord.Color.from_rgb(241, 196, 15)      # Amber Gold
    ERROR = discord.Color.from_rgb(237, 66, 69)         # Crimson Red
    INFO = discord.Color.from_rgb(52, 152, 219)         # Ocean Cyan
    CYAN = discord.Color.from_rgb(0, 206, 209)          # Cyber Cyan
    BLUE = discord.Color.from_rgb(52, 152, 219)         # Ocean Blue
    GREEN = discord.Color.from_rgb(46, 204, 113)        # Emerald Green
    RED = discord.Color.from_rgb(237, 66, 69)           # Crimson Red
    GOLD = discord.Color.from_rgb(241, 196, 15)         # Amber Gold
    DARK = discord.Color.from_rgb(43, 45, 49)           # Discord Charcoal
    AI = discord.Color.from_rgb(155, 89, 182)           # Mystic Purple
    PURPLE = discord.Color.from_rgb(155, 89, 182)       # Secret Egg Purple
    MUSIC = discord.Color.from_rgb(230, 126, 34)        # Vibrant Orange
    MINECRAFT = discord.Color.from_rgb(39, 174, 96)     # Grass Green


class _ZNStatusPillMeta(type(Enum)):
    """Fallback metaclass preventing any AttributeError on unknown status pill."""
    def __getattr__(cls, name: str) -> str:
        return "▫️"


class ZNStatusPill(str, Enum, metaclass=_ZNStatusPillMeta):
    """Visual health, module, and category indicator pills.
    
    Guarantees that string formatting always outputs the emoji directly
    rather than 'ZNStatusPill.MEMBER'.
    """
    SUCCESS = "🟢"
    WARNING = "🟡"
    ERROR = "🔴"
    OFFLINE = "⚪"
    THINKING = "🧠"
    PROCESSING = "⏳"
    EGG = "✨"
    MODEL = "🤖"
    AI = "🟣"
    PRIMARY = "🔷"
    DARK = "⬛"
    INFO = "ℹ️"
    VISION = "👁️"
    MUSIC = "🎵"
    MINECRAFT = "⛏️"
    MODERATION = "🛡️"
    SYSTEM = "📊"
    TOOL = "⚙️"
    FUN = "🎲"
    WEATHER = "⛅"

    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, format_spec: str) -> str:
        return str(self.value)


class ZNTheme:
    """Theme helpers for timezone-aware formatting and footer branding."""

    @staticmethod
    def format_timestamp(dt: Optional[datetime] = None, tz_name: Optional[str] = None) -> str:
        """Formats time strictly in the target timezone (e.g. Asia/Taipei: '14:32')."""
        tz = pytz.timezone(tz_name or config.platform.default_timezone)
        target_dt = dt or datetime.now(pytz.UTC)
        if target_dt.tzinfo is None:
            target_dt = pytz.UTC.localize(target_dt)
        local_dt = target_dt.astimezone(tz)
        return local_dt.strftime("%H:%M")

    @classmethod
    def standard_footer(cls, tz_name: Optional[str] = None) -> str:
        """Returns standard footer string: 'ZeroNexus · 14:32'."""
        t_str = cls.format_timestamp(tz_name=tz_name)
        return f"{config.platform.name} · {t_str}"
