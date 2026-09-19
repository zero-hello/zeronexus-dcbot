"""ZeroNexus Music Components V2 Dashboard & Interactive Views.

實作播放控制面板、音量調整 Modal、搜尋結果下拉選單、YouTube 播放清單防爆詢問與播畢待機面板。
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine, List, Optional

import discord
import wavelink

from zeronexus.core.config import config
from zeronexus.lavalink.node_pool import NodePoolManager
from zeronexus.ui.card import ZNCard
from zeronexus.ui.theme import ZNColor, ZNStatusPill


def format_ms_to_clock(duration_ms: int | float) -> str:
    """將毫秒轉換為 mm:ss 或 hh:mm:ss 格式。"""
    total_seconds = int(duration_ms / 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def build_progress_bar(position_ms: int, duration_ms: int, total_blocks: int = 15) -> str:
    """生成動態進度條。"""
    if duration_ms <= 0:
        return "🔘" + "─" * (total_blocks - 1) + " (直播 / 未知)"

    ratio = max(0.0, min(1.0, position_ms / duration_ms))
    active_idx = min(total_blocks - 1, int(ratio * total_blocks))

    blocks = []
    for i in range(total_blocks):
        if i == active_idx:
            blocks.append("🔘")
        else:
            blocks.append("─")

    pos_str = format_ms_to_clock(position_ms)
    dur_str = format_ms_to_clock(duration_ms)
    return f"`{''.join(blocks)}` {pos_str} / {dur_str}"


def build_now_playing_card(player: wavelink.Player, volume: int) -> ZNCard:
    """建構正播放中之 Components V2 核心資訊卡片。"""
    track = player.current
    if not track:
        return ZNCard(
            title="🎵 音樂播放器 (待機中)",
            description="目前沒有正在播放的歌曲。",
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.PRIMARY,
        )

    title = track.title or "未知曲目"
    author = track.author or "未知創作者"
    artwork = getattr(track, "artwork", None)
    uri = getattr(track, "uri", "https://youtube.com")

    pos = int(player.position) if hasattr(player, "position") else 0
    dur = int(track.length) if hasattr(track, "length") else 0
    bar = build_progress_bar(pos, dur)

    queue_count = len(player.queue) if hasattr(player, "queue") else 0
    loop_text = "開啟" if getattr(player.queue, "mode", None) else "關閉"

    desc = (
        f"🎶 標題：**[{title}]({uri})**\n"
        f"👤 歌手 / 頻道：`{author}`\n"
        f"⏱️ 播放進度：{bar}\n"
    )

    card = ZNCard(
        title="🎵 正在播放 (Now Playing)",
        description=desc,
        status_pill=ZNStatusPill.SUCCESS,
        color=ZNColor.PRIMARY,
        footer_text=f"🔊 音量：{volume}%  |  🔁 循環：{loop_text}  |  📜 待播隊列：{queue_count} 首",
    )
    if artwork:
        card.set_thumbnail(artwork)
    return card


class VolumeModal(discord.ui.Modal, title="🔊 調整音樂播放音量"):
    """音量微調彈出視窗表單。"""

    def __init__(self, player: wavelink.Player, current_volume: int, on_refresh: Callable[[], Coroutine[Any, Any, None]]) -> None:
        super().__init__()
        self.player = player
        self.on_refresh = on_refresh
        max_v = config.music.max_volume

        self.volume_input = discord.ui.TextInput(
            label=f"請輸入目標音量 (0% ~ {max_v}%)",
            default=str(current_volume),
            placeholder=f"例如: 100 (預設 100，最大 {max_v})",
            min_length=1,
            max_length=3,
            required=True,
        )
        self.add_item(self.volume_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        val_str = self.volume_input.value.strip()
        try:
            val = int(val_str)
        except ValueError:
            await interaction.followup.send("❌ 音量必須為純整數數字。", ephemeral=True)
            return

        max_v = config.music.max_volume
        clamped = max(0, min(max_v, val))

        # 套用至 Wavelink Player 與持久化儲存
        await self.player.set_volume(clamped)
        if interaction.guild:
            NodePoolManager.get_instance().set_guild_volume(interaction.guild.id, clamped)

        await self.on_refresh()
        await interaction.followup.send(f"🔊 音量已成功設定為 **{clamped}%**！", ephemeral=True)


class AddSongModal(discord.ui.Modal, title="➕ 添加點播新歌曲"):
    """播放完畢後之點歌彈出視窗。"""

    def __init__(self, on_add_song: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]]) -> None:
        super().__init__()
        self.on_add_song = on_add_song
        self.query_input = discord.ui.TextInput(
            label="歌曲名稱或 YouTube 連結",
            placeholder="貼上 YouTube / 搜尋關鍵字...",
            min_length=1,
            max_length=300,
            required=True,
        )
        self.add_item(self.query_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        query = self.query_input.value.strip()
        await self.on_add_song(interaction, query)


class NowPlayingView(discord.ui.View):
    """Components V2 播放器專屬互動控制面板。"""

    def __init__(
        self,
        player: wavelink.Player,
        volume: int,
        guild_id: int,
        message: Optional[discord.Message] = None,
    ) -> None:
        super().__init__(timeout=None)
        self.player = player
        self.volume = volume
        self.guild_id = guild_id
        self.message = message
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        """依播放器狀態更新按鈕樣式與標籤。"""
        is_paused = getattr(self.player, "paused", False)
        self.btn_pause_resume.label = "▶️ 繼續" if is_paused else "⏸️ 暫停"
        self.btn_pause_resume.style = discord.ButtonStyle.success if is_paused else discord.ButtonStyle.primary

    async def refresh_dashboard(self) -> None:
        """更新控制面板卡片與按鈕。"""
        self._sync_buttons()
        vol = NodePoolManager.get_instance().get_guild_volume(self.guild_id)
        self.volume = vol
        card = build_now_playing_card(self.player, vol)
        if self.message:
            try:
                embed = card.to_embed()
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass

    @discord.ui.button(label="⏸️ 暫停", style=discord.ButtonStyle.primary, row=0)
    async def btn_pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        is_paused = getattr(self.player, "paused", False)
        await self.player.pause(not is_paused)
        await self.refresh_dashboard()

    @discord.ui.button(label="⏹️ 停止", style=discord.ButtonStyle.danger, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.player.queue.clear()
        await self.player.stop()
        card = ZNCard(
            title="⏹️ 音樂已停止",
            description="已停止音樂播放並清空待播隊列。",
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.ERROR,
        )
        if self.message:
            try:
                await self.message.edit(embed=card.to_embed(), view=None)
            except Exception:
                pass

    @discord.ui.button(label="⏮️ 上一首", style=discord.ButtonStyle.secondary, row=0)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.player.seek(0)
        await self.refresh_dashboard()

    @discord.ui.button(label="⏭️ 下一首", style=discord.ButtonStyle.primary, row=0)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.player.skip(force=True)

    @discord.ui.button(label="🔊 音量", style=discord.ButtonStyle.secondary, row=0)
    async def btn_volume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = VolumeModal(self.player, self.volume, self.refresh_dashboard)
        await interaction.response.send_modal(modal)


class TrackSelect(discord.ui.Select):
    """前 10 首搜尋結果下拉選單。"""

    def __init__(self, tracks: List[wavelink.Playable], on_select: Callable[[discord.Interaction, wavelink.Playable], Coroutine[Any, Any, None]]) -> None:
        self.tracks = tracks[:10]
        self.on_select = on_select

        options = []
        for idx, t in enumerate(self.tracks):
            dur = format_ms_to_clock(t.length) if hasattr(t, "length") else "未知"
            auth = (t.author or "未知")[:40]
            label = f"{idx + 1}. {t.title}"[:100]
            desc = f"長度: {dur} | 作者: {auth}"[:100]
            options.append(discord.SelectOption(label=label, value=str(idx), description=desc))

        super().__init__(placeholder="🎵 請挑選你想播放的曲目...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        idx = int(self.values[0])
        chosen = self.tracks[idx]
        await self.on_select(interaction, chosen)


class TrackSelectView(discord.ui.View):
    """搜尋結果下拉選單專屬 View。"""

    def __init__(self, tracks: List[wavelink.Playable], on_select: Callable[[discord.Interaction, wavelink.Playable], Coroutine[Any, Any, None]]) -> None:
        super().__init__(timeout=60.0)
        self.select_menu = TrackSelect(tracks, on_select)
        self.add_item(self.select_menu)


class PlaylistPromptView(discord.ui.View):
    """YouTube 播放清單 (&list=) 防爆確認 View。"""

    def __init__(
        self,
        on_choose: Callable[[discord.Interaction, bool], Coroutine[Any, Any, None]],
        playlist_count: int = 0,
    ) -> None:
        super().__init__(timeout=60.0)
        self.on_choose = on_choose
        count_label = f" (共 {playlist_count} 首)" if playlist_count > 0 else ""
        self.btn_load_all.label = f"📋 載入整張清單{count_label}"

    @discord.ui.button(label="📋 載入整張清單", style=discord.ButtonStyle.success)
    async def btn_load_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.on_choose(interaction, True)

    @discord.ui.button(label="🎵 僅播放當前單曲", style=discord.ButtonStyle.primary)
    async def btn_load_single(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.on_choose(interaction, False)

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        if interaction.message:
            try:
                await interaction.message.delete()
            except Exception:
                pass


class TrackEndedView(discord.ui.View):
    """全部曲目播放完畢後之待機面板 View。"""

    def __init__(self, on_add_song: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]]) -> None:
        super().__init__(timeout=180.0)
        self.on_add_song = on_add_song

    @discord.ui.button(label="➕ 添加歌曲", style=discord.ButtonStyle.success)
    async def btn_add_song(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = AddSongModal(self.on_add_song)
        await interaction.response.send_modal(modal)
