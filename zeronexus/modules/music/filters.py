"""ZeroNexus Music DSP Filters Module.

處理音高 (Pitch) 與重低音 (Bass Boost) 等音訊濾鏡數值映射與套用。
"""

from __future__ import annotations

from typing import Any

import wavelink


# 專業 Hi-Fi 純淨高保真聽感補償曲線 (15-Band Equalizer)
# 保留原始音調 1.0x、原始速度 1.0x，純粹修飾頻率曲線提升通透度與人聲細節
HIFI_BANDS: list[dict[str, Any]] = [
    {"band": 0, "gain": 0.0},     # 25 Hz: 極低頻自然
    {"band": 1, "gain": 0.02},    # 40 Hz: 超低音微增
    {"band": 2, "gain": 0.035},   # 63 Hz: 重低音凝聚力
    {"band": 3, "gain": 0.03},    # 100 Hz: 鼓點扎實度
    {"band": 4, "gain": 0.0},     # 160 Hz: 自然過渡
    {"band": 5, "gain": -0.04},   # 250 Hz: 關鍵！去除 YouTube 塑料箱音混濁發悶感
    {"band": 6, "gain": -0.03},   # 400 Hz: 消除中低頻轟鳴感
    {"band": 7, "gain": 0.0},     # 630 Hz: 中頻基石
    {"band": 8, "gain": 0.015},   # 1.0 kHz: 人聲主體浮凸
    {"band": 9, "gain": 0.035},   # 1.6 kHz: 清澈度提升
    {"band": 10, "gain": 0.045},  # 2.5 kHz: 咬字清晰與樂器分離度
    {"band": 11, "gain": 0.04},   # 4.0 kHz: 歌手穿透力強化
    {"band": 12, "gain": 0.05},   # 6.3 kHz: 高頻樂器泛音與空氣感
    {"band": 13, "gain": 0.04},   # 10.0 kHz: 細膩度提升
    {"band": 14, "gain": 0.02},   # 16.0 kHz: 極高頻光澤
]


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
    async def apply_hifi(cls, player: wavelink.Player) -> None:
        """套用純淨高保真 Hi-Fi 等化補償曲線。"""
        filters: wavelink.Filters = player.filters or wavelink.Filters()
        filters.equalizer.set(bands=HIFI_BANDS)
        await player.set_filters(filters)
        setattr(player, "_hifi_enabled", True)

    @classmethod
    async def apply_flat(cls, player: wavelink.Player) -> None:
        """重設等化器為 Flat 原音直通模式。"""
        filters: wavelink.Filters = player.filters or wavelink.Filters()
        filters.equalizer.reset()
        await player.set_filters(filters)
        setattr(player, "_hifi_enabled", False)

    @classmethod
    async def apply_speed(cls, player: wavelink.Player, speed: float) -> float:
        """套用播放倍速濾鏡 (0.25x ~ 4.0x) 並回傳實際倍率。"""
        clamped = round(max(0.25, min(4.0, float(speed))), 2)
        filters: wavelink.Filters = player.filters or wavelink.Filters()
        filters.timescale.set(speed=clamped)
        await player.set_filters(filters)
        setattr(player, "_playback_speed", clamped)
        return clamped

    @classmethod
    def get_speed(cls, player: wavelink.Player) -> float:
        """取得播放器當前之播放倍速 (預設為 1.0x)。"""
        return getattr(player, "_playback_speed", 1.0)

    @classmethod
    async def reset_all(cls, player: wavelink.Player) -> None:
        """重設所有音訊濾鏡為預設平坦狀態。"""
        filters = wavelink.Filters()
        await player.set_filters(filters)
        setattr(player, "_hifi_enabled", False)
        setattr(player, "_playback_speed", 1.0)
