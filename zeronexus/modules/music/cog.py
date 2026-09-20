"""ZeroNexus Music Command Cog.

提供 /音樂 主群組完整指令：
- 播放, 暫停, 繼續, 停止, 跳過, 上一首, 隊列
- 音量 (0~300%), 音高 (0~100%), 重低音 (0~100%)
- 支援 YouTube &list= 播放清單防爆詢問、前 10 首搜尋下拉選單與 Components V2 控制面板。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands
import wavelink

from zeronexus.core.config import config
from zeronexus.core.logger import log
from zeronexus.lavalink.node_pool import NodePoolManager
from zeronexus.modules.base import BaseModule, CommandMetadata, ModuleState
from zeronexus.modules.music.dashboard import (
    NowPlayingView,
    PlaylistPromptView,
    TrackEndedView,
    TrackSelectView,
    build_now_playing_card,
    format_ms_to_clock,
)
from zeronexus.modules.music.filters import MusicFilters
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill

PLAYLIST_REGEX = re.compile(r"[?&]list=([a-zA-Z0-9_-]+)")


class MusicModule(BaseModule):
    """ZeroNexus Music Suite Domain Module."""

    def __init__(self) -> None:
        super().__init__(
            name="music",
            display_name="音樂派對模組",
            description="支援多節點 Lavalink 音樂播放、YouTube 播放清單防爆與 Components V2 控制面板",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("播放", "點播 YouTube 歌曲、播放清單或搜尋音樂", ZNPermissionLevel.EVERYONE),
            ("暫停", "暫停目前正在播放的音樂", ZNPermissionLevel.EVERYONE),
            ("繼續", "繼續播放目前暫停的音樂", ZNPermissionLevel.EVERYONE),
            ("停止", "停止音樂播放並清空待播隊列", ZNPermissionLevel.EVERYONE),
            ("跳過", "跳過當前歌曲並播放下一首", ZNPermissionLevel.EVERYONE),
            ("上一首", "重頭播放當前曲目", ZNPermissionLevel.EVERYONE),
            ("隊列", "檢視當前待播音樂隊列清單", ZNPermissionLevel.EVERYONE),
            ("音量", "調整音樂播放音量 (0% ~ 300%)", ZNPermissionLevel.EVERYONE),
            ("音高", "調整音樂音高濾鏡 (0% ~ 100%)", ZNPermissionLevel.EVERYONE),
            ("重低音", "調整重低音強化濾鏡 (0% ~ 100%)", ZNPermissionLevel.EVERYONE),
        ]
        for name, desc, perm in commands_list:
            self.registered_commands.append(
                CommandMetadata(
                    name=name,
                    full_name=f"/音樂 {name}",
                    description=desc,
                    group_name="音樂",
                    module_name=self.name,
                    permission_level=perm,
                )
            )
        self.set_state(ModuleState.RUNNING)

    async def shutdown(self) -> None:
        self.set_state(ModuleState.DISABLED, "音樂模組安全關退")


class MusicCog(commands.Cog):
    """ZeroNexus Discord 音樂系統 Slash Command Group."""

    music_group = app_commands.Group(name="音樂", description="ZeroNexus 音樂播放與語音派對系統", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.node_manager = NodePoolManager.get_instance(bot)
        self._dashboards: dict[int, NowPlayingView] = {}
        self._ticker_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        """Cog 載入時非同步初始化 Lavalink 節點池。"""
        self.bot.loop.create_task(self.node_manager.initialize(self.bot))

    def _start_ticker(self, guild_id: int, player: wavelink.Player) -> None:
        """啟動該伺服器控制面板進度條背景刷新任務 (每 6 秒平滑更新)。"""
        self._stop_ticker(guild_id)

        async def _ticker_loop() -> None:
            while True:
                await asyncio.sleep(6.0)
                try:
                    if not player or not player.connected or not player.playing:
                        break
                    # 若暫停中則略過該次編輯以節省 API 資源
                    if getattr(player, "paused", False):
                        continue
                    dashboard = self._dashboards.get(guild_id)
                    if dashboard and dashboard.message:
                        await dashboard.refresh_dashboard()
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    log.debug(f"[MusicCog] 進度條定時刷新例外: {ex}")
                    break

        self._ticker_tasks[guild_id] = self.bot.loop.create_task(_ticker_loop())

    def _stop_ticker(self, guild_id: int) -> None:
        """終止該伺服器之控制面板進度條刷新任務。"""
        task = self._ticker_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    # --------------------------------------------------------------------------
    # 輔助函式：取得或連線語音播放器 (具備斷線殭屍播放器自我修復)
    # --------------------------------------------------------------------------
    async def _get_or_connect_player(self, interaction: discord.Interaction) -> Optional[wavelink.Player]:
        """驗證使用者語音狀態並連線至該語音頻道。"""
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在伺服器內使用。", ephemeral=True)
            return None

        user_voice = getattr(interaction.user, "voice", None)
        if not user_voice or not user_voice.channel:
            await InteractionResponder.safe_send(interaction, "❌ 請先加入一個語音頻道後再使用音樂指令唷！", ephemeral=True)
            return None

        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if player is not None:
            # 檢查連線狀態是否健康，若已斷線則強制清理以供重新乾淨建立連線
            if not player.connected:
                log.warning("[MusicCog] 偵測到中斷之語音播放器殘留，正在清理並重新建立連線...")
                try:
                    await player.disconnect(force=True)
                except Exception:
                    pass
                player = None
            elif player.channel != user_voice.channel:
                try:
                    await player.move_to(user_voice.channel)
                except Exception:
                    pass

        if player is None or not isinstance(player, wavelink.Player):
            try:
                player = await user_voice.channel.connect(
                    cls=wavelink.Player,
                    self_deaf=True,
                    self_mute=False,
                )
                best_node = self.node_manager.get_best_node()
                if best_node and player.node != best_node and best_node.status is wavelink.NodeStatus.CONNECTED:
                    try:
                        await player.switch_node(best_node)
                    except Exception:
                        pass
            except Exception as ex:
                await InteractionResponder.safe_send(interaction, f"❌ 無法加入語音頻道：`{ex}`", ephemeral=True)
                return None

        return player

    # --------------------------------------------------------------------------
    # 輔助函式：多節點容錯安全搜尋 (防禦 Cloudflare 524 與逾時)
    # --------------------------------------------------------------------------
    async def _safe_search_tracks(
        self,
        query: str,
        preferred_node: Optional[wavelink.Node] = None,
    ) -> Any:
        """安全搜尋歌曲，支援自動節點容錯重試以抵禦 Cloudflare 524 與逾時異常。"""
        all_nodes: list[wavelink.Node] = []
        best_node = self.node_manager.get_best_node()
        if best_node and best_node.status is wavelink.NodeStatus.CONNECTED:
            all_nodes.append(best_node)

        if preferred_node and preferred_node.status is wavelink.NodeStatus.CONNECTED and preferred_node not in all_nodes:
            all_nodes.append(preferred_node)

        # 優先排入具備 yt-sosor 或 millo / serenetia 之優質節點
        for n in getattr(wavelink.Pool, "nodes", {}).values():
            if n.status is wavelink.NodeStatus.CONNECTED and n not in all_nodes:
                ident_low = n.identifier.lower()
                uri_low = str(getattr(n, "uri", "")).lower()
                if any(k in ident_low or k in uri_low for k in ("millo", "serenetia")):
                    all_nodes.insert(1 if best_node in all_nodes else 0, n)
                else:
                    all_nodes.append(n)

        for n in all_nodes:
            try:
                res = await asyncio.wait_for(wavelink.Playable.search(query, node=n), timeout=3.2)
                if res:
                    return res
            except asyncio.TimeoutError:
                log.warning(f"[MusicCog] 節點 {n.identifier} 搜尋超過 3.2 秒逾時，切換至備援節點...")
            except Exception as ex:
                log.warning(f"[MusicCog] 節點 {n.identifier} 搜尋異常 ({ex})，正在自動切換至備援節點重試...")

        # 若指定節點皆未成功，最後以全域預設 Pool 搜尋一次 (上限 3.5 秒防掛死)
        try:
            return await asyncio.wait_for(wavelink.Playable.search(query), timeout=3.5)
        except Exception as ex:
            log.error(f"[MusicCog] 所有節點搜尋均失敗: {ex}")
            return None

    def _create_on_add_song(self, player: wavelink.Player):
        """為控制面板建構添加歌曲之非同步回呼函式。"""
        async def _on_add(inter: discord.Interaction, query: str) -> None:
            clean_q = query.strip()
            search_q = clean_q if clean_q.startswith(("http://", "https://")) else f"ytsearch:{clean_q}"
            res = await self._safe_search_tracks(search_q, preferred_node=player.node)
            if not res:
                await inter.followup.send("❌ 找不到該歌曲，請嘗試其他關鍵字或有效網址。", ephemeral=True)
                return

            track = res[0] if isinstance(res, list) else res
            await self._play_or_enqueue(inter, player, track)
            dur = format_ms_to_clock(track.length) if hasattr(track, "length") else "未知"
            await inter.followup.send(
                f"🎶 已成功加入待播隊列：**[{track.title}]({getattr(track, 'uri', '')})** (`{dur}`)",
                ephemeral=True,
            )

        return _on_add

    # --------------------------------------------------------------------------
    # 輔助函式：播放或加入待播隊列
    # --------------------------------------------------------------------------
    async def _play_or_enqueue(
        self,
        interaction: discord.Interaction,
        player: wavelink.Player,
        track: wavelink.Playable,
    ) -> None:
        """執行歌曲播放或推進待播清單。"""
        guild_id = interaction.guild_id or 0
        volume = self.node_manager.get_guild_volume(guild_id)

        if not player.playing:
            # 當前未播歌，直接開播並帶上持久化音量
            await player.set_volume(volume)
            await player.play(track, volume=volume)

            dashboard = NowPlayingView(
                player=player,
                volume=volume,
                guild_id=guild_id,
                on_add_song=self._create_on_add_song(player),
            )
            self._dashboards[guild_id] = dashboard

            card = build_now_playing_card(player, volume)
            msg = await InteractionResponder.safe_send(interaction, card=card, view=dashboard)
            if msg:
                dashboard.message = msg
            self._start_ticker(guild_id, player)
        else:
            # 當前正有歌曲播放中，加入待播隊列
            await player.queue.put_wait(track)
            dur = format_ms_to_clock(track.length) if hasattr(track, "length") else "未知"
            q_pos = len(player.queue)

            card = ZNCard(
                title="🎶 已加入待播隊列",
                description=(
                    f"歌曲：**[{track.title}]({getattr(track, 'uri', 'https://youtube.com')})**\n"
                    f"歌手：`{track.author or '未知'}` | 長度：`{dur}`\n"
                    f"目前順位：第 **{q_pos}** 首"
                ),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            artwork = getattr(track, "artwork", None)
            if artwork:
                card.set_thumbnail(artwork)
            await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 1. 播放指令 /音樂 播放
    # --------------------------------------------------------------------------
    @music_group.command(name="播放", description="點播 YouTube 歌曲、播放清單或搜尋音樂")
    @app_commands.describe(查詢或連結="輸入歌曲關鍵字搜尋，或貼上 YouTube 音樂網址")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def play_command(self, interaction: discord.Interaction, 查詢或連結: str) -> None:
        # 第一行立即進行 defer ACK，防止語音連線握手超時導致 10062
        await interaction.response.defer()

        player = await self._get_or_connect_player(interaction)
        if not player:
            return

        query = 查詢或連結.strip()

        # 1. 檢查是否包含 YouTube list 播放清單參數
        if PLAYLIST_REGEX.search(query):
            search_res = await self._safe_search_tracks(query, preferred_node=player.node)

            if isinstance(search_res, wavelink.Playlist):
                playlist = search_res
                total_tracks = len(playlist.tracks)

                async def _on_choose_playlist(inter: discord.Interaction, load_all: bool) -> None:
                    if load_all:
                        # 載入整張清單（最多 100 首防爆）
                        tracks_to_add = playlist.tracks[:100]
                        first_track = tracks_to_add[0]

                        if not player.playing:
                            vol = self.node_manager.get_guild_volume(inter.guild_id or 0)
                            await player.set_volume(vol)
                            await player.play(first_track, volume=vol)

                            for t in tracks_to_add[1:]:
                                await player.queue.put_wait(t)

                            dashboard = NowPlayingView(
                                player=player,
                                volume=vol,
                                guild_id=inter.guild_id or 0,
                                on_add_song=self._create_on_add_song(player),
                            )
                            self._dashboards[inter.guild_id or 0] = dashboard
                            card = build_now_playing_card(player, vol)
                            msg = await InteractionResponder.safe_send(inter, card=card, view=dashboard)
                            if msg:
                                dashboard.message = msg
                            self._start_ticker(inter.guild_id or 0, player)
                        else:
                            for t in tracks_to_add:
                                await player.queue.put_wait(t)

                        card = ZNCard(
                            title="📋 播放清單已載入",
                            description=f"已成功匯入清單 **{playlist.name}** 共 **{len(tracks_to_add)}** 首曲目！",
                            status_pill=ZNStatusPill.SUCCESS,
                            color=ZNColor.SUCCESS,
                        )
                        await InteractionResponder.safe_send(inter, card=card)
                    else:
                        # 僅播放當前單曲
                        single_track = playlist.tracks[0]
                        await self._play_or_enqueue(inter, player, single_track)

                prompt_view = PlaylistPromptView(_on_choose_playlist, playlist_count=total_tracks)
                prompt_card = ZNCard(
                    title="📋 偵測到 YouTube 播放清單",
                    description=(
                        f"您輸入的連結包含播放清單參數：**{playlist.name}**\n"
                        f"共包含 **{total_tracks}** 首歌曲。\n\n"
                        f"請問您希望匯入整張清單，還是僅播放單一曲目呢？"
                    ),
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.PRIMARY,
                )
                await interaction.followup.send(embed=prompt_card.to_embed(), view=prompt_view)
                return

        # 2. 一般搜尋或單曲連結
        if not query.startswith(("http://", "https://")):
            # 關鍵字搜尋：抓取前 10 首
            search_res = await self._safe_search_tracks(f"ytsearch:{query}", preferred_node=player.node)

            if not search_res:
                await interaction.followup.send("❌ 找不到符合條件的歌曲，請嘗試其他關鍵字。")
                return

            if isinstance(search_res, list) and len(search_res) > 1:
                # 彈出前 10 首下拉選單
                async def _on_select_track(inter: discord.Interaction, selected_track: wavelink.Playable) -> None:
                    await self._play_or_enqueue(inter, player, selected_track)

                select_view = TrackSelectView(search_res[:10], _on_select_track)
                select_card = ZNCard(
                    title="🔍 搜尋結果清單 (前 10 首)",
                    description=f"針對「**{query}**」找到了多首曲目，請透過下方選單選取：",
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.PRIMARY,
                )
                await interaction.followup.send(embed=select_card.to_embed(), view=select_view)
                return

            track = search_res[0] if isinstance(search_res, list) else search_res
            await self._play_or_enqueue(interaction, player, track)
        else:
            # 直接 URL
            search_res = await self._safe_search_tracks(query, preferred_node=player.node)
            if not search_res:
                await interaction.followup.send("❌ 無法解析該音樂網址，請確認連結有效性或稍後再試。")
                return

            track = search_res[0] if isinstance(search_res, list) else search_res
            await self._play_or_enqueue(interaction, player, track)

    # --------------------------------------------------------------------------
    # 2. 暫停指令 /音樂 暫停
    # --------------------------------------------------------------------------
    @music_group.command(name="暫停", description="暫停目前正在播放的音樂")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def pause_command(self, interaction: discord.Interaction) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.playing:
            await InteractionResponder.safe_send(interaction, "❌ 目前沒有正在播放的音樂。", ephemeral=True)
            return

        if player.paused:
            await InteractionResponder.safe_send(interaction, "⚠️ 音樂已經處於暫停狀態囉！", ephemeral=True)
            return

        await player.pause(True)
        await InteractionResponder.safe_send(interaction, "⏸️ 音樂已暫停播放。")

    # --------------------------------------------------------------------------
    # 3. 繼續指令 /音樂 繼續
    # --------------------------------------------------------------------------
    @music_group.command(name="繼續", description="繼續播放目前暫停的音樂")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def resume_command(self, interaction: discord.Interaction) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.paused:
            await InteractionResponder.safe_send(interaction, "❌ 目前沒有被暫停的音樂。", ephemeral=True)
            return

        await player.pause(False)
        await InteractionResponder.safe_send(interaction, "▶️ 音樂已繼續播放。")

    # --------------------------------------------------------------------------
    # 4. 停止指令 /音樂 停止
    # --------------------------------------------------------------------------
    @music_group.command(name="停止", description="停止音樂播放並清空待播隊列")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def stop_command(self, interaction: discord.Interaction) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player:
            await InteractionResponder.safe_send(interaction, "❌ 機器人目前未在語音頻道內。", ephemeral=True)
            return

        guild_id = interaction.guild_id or 0
        self._stop_ticker(guild_id)
        player.queue.clear()
        vol = self.node_manager.get_guild_volume(guild_id)
        card = ZNCard(
            title="🏁 目前沒有正在播放的音樂 (待機中)",
            description="音樂已停止播放並清空待播隊列。您可以點擊下方「➕ 添加歌曲」按鈕繼續點播新歌曲唷～",
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.PRIMARY,
            footer_text=f"🔊 音量：{vol}%  |  🎵 音樂播放器待機中",
        )
        ended_view = TrackEndedView(self._create_on_add_song(player))
        dashboard = self._dashboards.get(guild_id)
        if dashboard and dashboard.message:
            try:
                lv = card.to_layout_view(extra_view=ended_view)
                await dashboard.message.edit(view=lv, embed=None)
            except Exception:
                pass
        await InteractionResponder.safe_send(interaction, card=card, view=ended_view)

    # --------------------------------------------------------------------------
    # 5. 跳過指令 /音樂 跳過
    # --------------------------------------------------------------------------
    @music_group.command(name="跳過", description="跳過當前歌曲並播放下一首")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def skip_command(self, interaction: discord.Interaction) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.playing:
            await InteractionResponder.safe_send(interaction, "❌ 目前沒有正在播放的音樂可跳過。", ephemeral=True)
            return

        await player.skip(force=True)
        await InteractionResponder.safe_send(interaction, "⏭️ 已跳過當前歌曲。")

    # --------------------------------------------------------------------------
    # 6. 上一首指令 /音樂 上一首
    # --------------------------------------------------------------------------
    @music_group.command(name="上一首", description="重頭播放當前曲目")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def prev_command(self, interaction: discord.Interaction) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.playing:
            await InteractionResponder.safe_send(interaction, "❌ 目前沒有正在播放的音樂。", ephemeral=True)
            return

        await player.seek(0)
        await InteractionResponder.safe_send(interaction, "⏮️ 已重頭開始播放當前曲目。")

    # --------------------------------------------------------------------------
    # 7. 隊列指令 /音樂 隊列
    # --------------------------------------------------------------------------
    @music_group.command(name="隊列", description="檢視當前待播音樂隊列清單")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def queue_command(self, interaction: discord.Interaction) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player:
            await InteractionResponder.safe_send(interaction, "❌ 機器人目前未在語音頻道內。", ephemeral=True)
            return

        curr = player.current
        queue = player.queue

        if not curr and len(queue) == 0:
            await InteractionResponder.safe_send(interaction, "📭 目前隊列空空如也，快使用 `/音樂 播放` 點歌吧！", ephemeral=True)
            return

        desc_lines = []
        if curr:
            curr_dur = format_ms_to_clock(curr.length) if hasattr(curr, "length") else "未知"
            desc_lines.append(f"▶️ **正在播放**：[{curr.title}]({getattr(curr, 'uri', '')}) (`{curr_dur}`)\n")

        if len(queue) > 0:
            desc_lines.append("**📜 待播清單 (即將播放)**：")
            for idx, item in enumerate(list(queue)[:10]):
                dur = format_ms_to_clock(item.length) if hasattr(item, "length") else "未知"
                desc_lines.append(f"`{idx + 1}.` [{item.title}]({getattr(item, 'uri', '')}) - `{dur}`")

            if len(queue) > 10:
                desc_lines.append(f"\n*...以及其他 {len(queue) - 10} 首曲目*")

        card = ZNCard(
            title=f"🎵 音樂隊列清單 (共 {len(queue) + (1 if curr else 0)} 首)",
            description="\n".join(desc_lines),
            status_pill=ZNStatusPill.MUSIC,
            color=ZNColor.PRIMARY,
            footer_text=f"伺服器音量：{self.node_manager.get_guild_volume(interaction.guild_id or 0)}%",
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 8. 音量指令 /音樂 音量
    # --------------------------------------------------------------------------
    @music_group.command(name="音量", description="調整音樂播放音量 (0% ~ 300%)，數值將自動保存")
    @app_commands.describe(數值="請輸入目標音量百分比 (0 到 300，預設 100)")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def volume_command(self, interaction: discord.Interaction, 數值: int) -> None:
        max_v = config.music.max_volume
        if 數值 < 0 or 數值 > max_v:
            await InteractionResponder.safe_send(interaction, f"❌ 音量數值必須介於 0% 到 {max_v}% 之間。", ephemeral=True)
            return

        guild_id = interaction.guild_id or 0
        self.node_manager.set_guild_volume(guild_id, 數值)

        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if player:
            await player.set_volume(數值)
            if guild_id in self._dashboards:
                await self._dashboards[guild_id].refresh_dashboard()

        card = ZNCard(
            title="🔊 音量已調整",
            description=f"已將伺服器音樂播放音量設定為 **{數值}%**（此數值已保存，後續播放將延續）。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 9. 音高指令 /音樂 音高
    # --------------------------------------------------------------------------
    @music_group.command(name="音高", description="調整音樂音高濾鏡 (0% ~ 100%，50% 為預設原調)")
    @app_commands.describe(數值="請輸入音高百分比 (0 到 100，50% 為原調)")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def pitch_command(self, interaction: discord.Interaction, 數值: int) -> None:
        if 數值 < 0 or 數值 > 100:
            await InteractionResponder.safe_send(interaction, "❌ 音高百分比必須介於 0% 到 100% 之間。", ephemeral=True)
            return

        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.playing:
            await InteractionResponder.safe_send(interaction, "❌ 目前沒有正在播放的音樂可套用濾鏡。", ephemeral=True)
            return

        factor = await MusicFilters.apply_pitch(player, 數值)
        hint = " (原調)" if 數值 == 50 else (" (低沉重音)" if 數值 < 50 else " (輕快升調)")
        card = ZNCard(
            title="🎛️ 音高濾鏡已套用",
            description=f"已將音高設定為 **{數值}%** (倍率: `{factor}x`){hint}。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 10. 重低音指令 /音樂 重低音
    # --------------------------------------------------------------------------
    @music_group.command(name="重低音", description="調整重低音強化濾鏡 (0% ~ 100%，0% 為關閉)")
    @app_commands.describe(數值="請輸入重低音強度 (0 到 100，0% 為關閉)")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def bass_command(self, interaction: discord.Interaction, 數值: int) -> None:
        if 數值 < 0 or 數值 > 100:
            await InteractionResponder.safe_send(interaction, "❌ 重低音強度必須介於 0% 到 100% 之間。", ephemeral=True)
            return

        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.playing:
            await InteractionResponder.safe_send(interaction, "❌ 目前沒有正在播放的音樂可套用濾鏡。", ephemeral=True)
            return

        gain = await MusicFilters.apply_bassboost(player, 數值)
        state_text = "已關閉重低音強化 (Flat)" if 數值 == 0 else f"已強化低頻頻段 (+{gain}dB 增益)"
        card = ZNCard(
            title="🎧 重低音等化器已套用",
            description=f"設定值：**{數值}%**\n狀態：`{state_text}`",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 事件監聽：歌曲播放開始 (Track Start)
    # --------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        """監聽歌曲開始播放事件，自動同步刷新控制面板並啟動進度更新與重設容錯計數。"""
        player = payload.player
        if not player or not player.guild:
            return
        setattr(player, "_failover_count", 0)
        guild_id = player.guild.id
        self._start_ticker(guild_id, player)
        dashboard = self._dashboards.get(guild_id)
        if dashboard:
            await dashboard.refresh_dashboard()

    # --------------------------------------------------------------------------
    # 事件監聽：歌曲播放異常 (Track Exception) 與自動容錯遷移 (Failover)
    # --------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload) -> None:
        """監聽歌曲播放異常，自動遷移至備援節點重新播放。"""
        player = payload.player
        track = payload.track
        track_title = getattr(track, "title", "未知曲目")
        current_node = player.node if player else None
        current_ident = current_node.identifier if current_node else "Unknown"

        log.error(f"[MusicCog] 節點 {current_ident} 歌曲播放異常: {payload.exception} (曲目: {track_title})")

        if not player:
            return

        # 尋找池中狀態為 CONNECTED 且非當前節點之備援節點
        connected_nodes = [
            n for n in getattr(wavelink.Pool, "nodes", {}).values()
            if n.status is wavelink.NodeStatus.CONNECTED and n.identifier != current_ident
        ]

        failover_count = getattr(player, "_failover_count", 0)
        if connected_nodes and failover_count < len(connected_nodes):
            backup_node = connected_nodes[failover_count % len(connected_nodes)]
            setattr(player, "_failover_count", failover_count + 1)

            log.warning(f"[MusicCog] 正在將播放器自 {current_ident} 容錯遷移至 {backup_node.identifier} 繼續播放...")
            try:
                await player.switch_node(backup_node)
                # 容錯遷移後，在此健康節點上重新恢復曲目播放
                guild_id = player.guild.id if player.guild else 0
                vol = self.node_manager.get_guild_volume(guild_id)
                await player.set_volume(vol)
                await player.play(track, volume=vol)

                channel = player.channel
                if channel and isinstance(channel, discord.TextChannel):
                    card = ZNCard(
                        title="🔄 自動節點容錯轉移",
                        description=(
                            f"曲目 **[{track_title}]({getattr(track, 'uri', '')})** 播放受阻，\n"
                            f"系統已自動為您無縫轉移至備援節點 **`{backup_node.identifier}`** 繼續播放！"
                        ),
                        status_pill=ZNStatusPill.WARNING,
                        color=ZNColor.WARNING,
                    )
                    await channel.send(embed=card.to_embed())
                return
            except Exception as ex:
                log.error(f"[MusicCog] 容錯切換節點失敗: {ex}")

        # 若已無可用備援節點或全部節點均解碼失敗
        setattr(player, "_failover_count", 0)
        channel = player.channel
        if channel and isinstance(channel, discord.TextChannel):
            card = ZNCard(
                title="⚠️ 歌曲播放受限",
                description=(
                    f"曲目 **{track_title}** 目前受到 YouTube 存取限制（要求登入驗證或非公開保護），所有節點均暫時無法取得音訊串流。\n"
                    f"建議您點播官方正式 MV 或其他搜尋關鍵字版本唷！"
                ),
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            try:
                await channel.send(embed=card.to_embed())
            except Exception:
                pass

        # 若待播隊列中還有歌曲，自動推進播放下一首
        if len(player.queue) > 0:
            await player.skip(force=True)

    # --------------------------------------------------------------------------
    # 事件監聽：語音 WebSocket 關閉 (Websocket Closed)
    # --------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: wavelink.WebsocketClosedEventPayload) -> None:
        """監聽語音 WebSocket 關閉事件。"""
        log.warning(f"[MusicCog] 語音 WebSocket 連線關閉: code={payload.code}, reason={payload.reason}")

    # --------------------------------------------------------------------------
    # 事件監聽：歌曲播放完畢 (Track End)
    # --------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        """監聽歌曲結束，若隊列為空則就地將控制面板轉換為待機卡片。"""
        player = payload.player
        if not player or not player.guild:
            return

        guild_id = player.guild.id
        self._stop_ticker(guild_id)

        # 若隊列還有歌，Wavelink 會自動播放下一首
        if len(player.queue) > 0:
            return

        # 隊列已空，展示完畢待機面板並原地更新控制面板
        vol = self.node_manager.get_guild_volume(guild_id)
        card = ZNCard(
            title="🏁 待播隊列已播放完畢 (待機中)",
            description="隊列中的歌曲已全部播放完畢！您可以點擊下方「➕ 添加歌曲」按鈕繼續點播新歌曲唷～",
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.PRIMARY,
            footer_text=f"🔊 音量：{vol}%  |  🎵 音樂播放器待機中",
        )

        ended_view = TrackEndedView(self._create_on_add_song(player))
        dashboard = self._dashboards.get(guild_id)

        updated = False
        if dashboard and dashboard.message:
            try:
                await dashboard.message.edit(embed=card.to_embed(), view=ended_view)
                updated = True
            except Exception:
                pass

        if not updated:
            channel = player.channel
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=card.to_embed(), view=ended_view)
                except Exception:
                    pass


async def setup(bot: commands.Bot) -> None:
    """載入音樂模組 Cog。"""
    await bot.add_cog(MusicCog(bot))
