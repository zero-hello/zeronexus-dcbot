"""ZeroNexus Music DSP Filters Module.

處理音高 (Pitch) 與重低音 (Bass Boost) 等音訊濾鏡數值映射與套用。
"""

from __future__ import annotations

import wavelink


class MusicFilters:
    """音訊數位訊號處理 (DSP) 濾鏡管理器。"""

    @staticmethod
    def map_pitch_percent_to_factor(percent: int) -> float:
        """將 0~100% 音高映射為 0.5x ~ 1.5x 音高乘數 (50% 為 1.0x 原調)。"""
        clamped = max(0, min(100, percent))
        # 50% 時 (50 / 100) = 0.5 -> 0.5 + 0.5 = 1.0
        factor = 0.5 + (clamped / 100.0)
        return round(factor, 2)

    @staticmethod
    def map_bass_percent_to_gain(percent: int) -> float:
        """將 0~100% 重低音映射為低頻 EQ 增益 (0% 為 0.0，100% 為 +0.30)。"""
        clamped = max(0, min(100, percent))
        gain = (clamped / 100.0) * 0.30
        return round(gain, 2)

    @classmethod
    async def apply_pitch(cls, player: wavelink.Player, pitch_percent: int) -> float:
        """套用音高濾鏡並回傳實際倍率。"""
        factor = cls.map_pitch_percent_to_factor(pitch_percent)
        filters: wavelink.Filters = player.filters or wavelink.Filters()
        filters.timescale.set(pitch=factor)
        await player.set_filters(filters)
        return factor

    @classmethod
    async def apply_bassboost(cls, player: wavelink.Player, bass_percent: int) -> float:
        """套用重低音等化器濾鏡並回傳低頻增益值。"""
        gain = cls.map_bass_percent_to_gain(bass_percent)
        filters: wavelink.Filters = player.filters or wavelink.Filters()

        # 等化器 0, 1, 2 頻段分別代表 25Hz, 40Hz, 63Hz 的超重低音
        bands = [
            {"band": 0, "gain": gain},
            {"band": 1, "gain": round(gain * 0.85, 2)},
            {"band": 2, "gain": round(gain * 0.65, 2)},
        ]
        filters.equalizer.set(bands=bands)
        await player.set_filters(filters)
        return gain

    @classmethod
    async def reset_all(cls, player: wavelink.Player) -> None:
        """重設所有音訊濾鏡為預設平坦狀態。"""
        filters = wavelink.Filters()
        await player.set_filters(filters)
