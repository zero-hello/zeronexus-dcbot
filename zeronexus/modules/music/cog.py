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
            ("音質", "切換純淨高保真 Hi-Fi 增強模式 (提升人聲清澈度與通透感)", ZNPermissionLevel.EVERYONE),
            ("倍速", "調整音樂播放倍速 (0.25x ~ 4.0x)", ZNPermissionLevel.EVERYONE),
            ("循環", "切換音樂循環播放模式 (單曲循環 / 隊列循環 / 關閉)", ZNPermissionLevel.EVERYONE),
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
        self._afk_leave_tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self) -> None:
        """Cog 載入時非同步初始化 Lavalink 節點池並優化日誌過濾。"""
        import logging
        # 抑制 Wavelink 底層 TrackException 冗長之 Java StackTrace 終端刷屏
        logging.getLogger("TrackException").setLevel(logging.CRITICAL)
        self.bot.loop.create_task(self.node_manager.initialize(self.bot))

    def cog_unload(self) -> None:
        """Cog 卸載時清理所有背景進度條刷新任務與無人自動退出計時任務。"""
        for task in self._ticker_tasks.values():
            if task and not task.done():
                task.cancel()
        self._ticker_tasks.clear()

        for task in self._afk_leave_tasks.values():
            if task and not task.done():
                task.cancel()
        self._afk_leave_tasks.clear()

    def _start_ticker(self, guild_id: int, player: wavelink.Player) -> None:
        """啟動該伺服器控制面板進度條背景刷新任務 (每 5 秒平滑更新並自動巡檢播畢狀態)。"""
        self._stop_ticker(guild_id)

        async def _ticker_loop() -> None:
            idle_ticks = 0
            while True:
                await asyncio.sleep(5.0)
                try:
                    if not player or not player.connected:
                        break

                    dashboard = self._dashboards.get(guild_id)
                    if not dashboard or not dashboard.message:
                        continue

                    if player.playing:
                        idle_ticks = 0
                        if getattr(player, "paused", False):
                            continue
                        await dashboard.refresh_dashboard()
                    else:
                        mode = getattr(player.queue, "mode", wavelink.QueueMode.normal)
                        # 未在播放中，僅在「非循環模式」且「隊列為空」時才判定播畢
                        if len(player.queue) == 0 and mode == wavelink.QueueMode.normal:
                            idle_ticks += 1
                            # 連續兩次巡檢 (約 10 秒) 均非播放狀態且隊列為空，主動執行播畢轉換待機面板
                            if idle_ticks >= 2:
                                vol = self.node_manager.get_guild_volume(guild_id)
                                idle_card = ZNCard(
                                    title="🏁 待播隊列已播放完畢 (待機中)",
                                    description="隊列中的歌曲已全部播放完畢！您可以點擊下方「➕ 添加歌曲」按鈕繼續點播新歌曲唷～",
                                    status_pill=ZNStatusPill.INFO,
                                    color=ZNColor.PRIMARY,
                                    footer_text=f"🔊 音量：{vol}%  |  🎵 音樂播放器待機中",
                                )
                                ended_view = TrackEndedView(self._create_on_add_song(player))
                                lv = idle_card.to_layout_view(extra_view=ended_view, timeout=None)
                                try:
                                    await dashboard.message.edit(view=lv, embed=None)
                                    log.info(f"[MusicCog] 背景巡檢主動將伺服器 {guild_id} 控制面板原地轉換為待機卡片")
                                except Exception as e:
                                    log.warning(f"[MusicCog] 背景巡檢更新待機卡片例外: {e}")
                                break
                        else:
                            idle_ticks = 0
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    log.warning(f"[MusicCog] 進度條定時刷新例外: {ex}")
                    await asyncio.sleep(2.0)
                    continue

        self._ticker_tasks[guild_id] = self.bot.loop.create_task(_ticker_loop())

    def _stop_ticker(self, guild_id: int) -> None:
        """終止該伺服器之控制面板進度條刷新任務。"""
        task = self._ticker_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _cancel_afk_timer(self, guild_id: int) -> None:
        """取消指定伺服器之無人語音頻道自動退出倒數計時。"""
        task = self._afk_leave_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _start_afk_timer(self, guild_id: int, timeout_seconds: float = 300.0) -> None:
        """啟動語音頻道無真人使用者自動退出倒數計時 (預設 5 分鐘 / 300 秒)。"""
        existing = self._afk_leave_tasks.get(guild_id)
        if existing and not existing.done():
            return

        async def _afk_leave_coro() -> None:
            try:
                log.info(f"[MusicCog] 伺服器 {guild_id} 語音頻道內無真人使用者，已啟動 {int(timeout_seconds)} 秒自動退出倒數...")
                await asyncio.sleep(timeout_seconds)

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    return
                player: Optional[wavelink.Player] = getattr(guild, "voice_client", None)
                if not player or not player.connected:
                    return

                channel = player.channel
                if not channel:
                    return

                # 再次驗證頻道內是否依然無真人使用者（排除機器人）
                human_members = [m for m in channel.members if not m.bot]
                if len(human_members) > 0:
                    log.info(f"[MusicCog] 伺服器 {guild_id} 語音頻道檢測到已有真人使用者回到頻道，取消自動退出。")
                    return

                log.info(f"[MusicCog] 伺服器 {guild_id} 語音頻道連續 {int(timeout_seconds)} 秒無真人，自動中斷連線並釋放資源。")
                self._stop_ticker(guild_id)

                leave_card = ZNCard(
                    title="👋 已自動退出語音頻道",
                    description="語音頻道已連續 5 分鐘沒有真人使用者，ZeroNexus 已自動退出以釋放系統與伺服器頻寬資源。\n下次想聽音樂時隨時點播即可重新加入唷！",
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.MUTED,
                    footer_text="⚡ ZeroNexus 智慧節能與資源回收機制",
                )

                dashboard = self._dashboards.pop(guild_id, None)
                if dashboard and dashboard.message:
                    try:
                        await dashboard.message.edit(embed=leave_card.to_embed(), view=None)
                    except Exception:
                        pass
                else:
                    text_ch_id = getattr(dashboard, "text_channel_id", None) if dashboard else None
                    target_ch = self.bot.get_channel(text_ch_id) if text_ch_id else None
                    if not target_ch and hasattr(channel, "send"):
                        target_ch = channel
                    if target_ch:
                        try:
                            await target_ch.send(embed=leave_card.to_embed())
                        except Exception:
                            pass

                await player.disconnect(force=True)
            except asyncio.CancelledError:
                log.info(f"[MusicCog] 伺服器 {guild_id} 無人自動退出倒數計時已取消。")
            except Exception as ex:
                log.warning(f"[MusicCog] 執行無人自動退出例外: {ex}")
            finally:
                self._afk_leave_tasks.pop(guild_id, None)

        self._afk_leave_tasks[guild_id] = self.bot.loop.create_task(_afk_leave_coro())

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

        best_node = self.node_manager.get_best_node()
        if player is not None and isinstance(player, wavelink.Player):
            # 若播放器閒置且所在節點並非最優健康節點，主動遷移至最優節點以確保點播品質
            if best_node and player.node != best_node and best_node.status is wavelink.NodeStatus.CONNECTED and not player.playing:
                try:
                    await player.switch_node(best_node)
                except Exception:
                    pass
            player.autoplay = wavelink.AutoPlayMode.partial

        if player is None or not isinstance(player, wavelink.Player):
            try:
                player = await user_voice.channel.connect(
                    cls=wavelink.Player,
                    self_deaf=True,
                    self_mute=False,
                )
                player.autoplay = wavelink.AutoPlayMode.partial
            except Exception as ex:
                await InteractionResponder.safe_send(interaction, f"❌ 無法加入語音頻道：`{ex}`", ephemeral=True)
                return None

        # 連線完成後立即評估語音房真人成員狀態
        if player and player.channel:
            human_count = len([m for m in player.channel.members if not m.bot])
            guild_id = interaction.guild_id or 0
            if human_count == 0:
                self._start_afk_timer(guild_id, timeout_seconds=300.0)
            else:
                self._cancel_afk_timer(guild_id)

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

        # 優先排入健康之優質節點 (如 serenetia)
        for n in getattr(wavelink.Pool, "nodes", {}).values():
            if n.status is wavelink.NodeStatus.CONNECTED and n not in all_nodes:
                ident_low = n.identifier.lower()
                uri_low = str(getattr(n, "uri", "")).lower()
                if any(k in ident_low or k in uri_low for k in ("serenetia", "trinium")):
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
                await InteractionResponder.safe_send(inter, "❌ 找不到該歌曲，請嘗試其他關鍵字或有效網址。", ephemeral=True)
                return

            await self._dispatch_search_result(
                interaction=inter,
                player=player,
                search_res=res,
                query=clean_q,
                ephemeral=True,
            )

        return _on_add

    # --------------------------------------------------------------------------
    # 輔助函式：統一調度搜尋結果 (防爆清單、前 10 首選單與單曲播放)
    # --------------------------------------------------------------------------
    async def _dispatch_search_result(
        self,
        interaction: discord.Interaction,
        player: wavelink.Player,
        search_res: Any,
        query: str,
        ephemeral: bool = False,
    ) -> None:
        """統一調度與處理搜尋結果（包含播放清單防爆、關鍵字前 10 首下拉選單與單曲播放）。"""
        guild_id = interaction.guild_id or 0

        # ----------------------------------------------------------------------
        # 1. 播放清單防爆處理 (wavelink.Playlist 或具備 tracks 屬性之清單容器)
        # ----------------------------------------------------------------------
        if isinstance(search_res, wavelink.Playlist) or (hasattr(search_res, "tracks") and not hasattr(search_res, "title")):
            playlist = search_res
            total_tracks = len(playlist.tracks)

            if total_tracks == 0:
                await InteractionResponder.safe_send(interaction, "❌ 此播放清單內沒有任何可播放的曲目。", ephemeral=ephemeral)
                return

            # 如果清單只有單一曲目，直接播放/加入隊列，不需彈出防爆打擾
            if total_tracks == 1:
                single_track = playlist.tracks[0]
                await self._play_or_enqueue(interaction, player, single_track, ephemeral=ephemeral)
                return

            # 多首曲目：觸發防爆確認
            selected_idx = getattr(playlist, "selected", 0)
            if selected_idx is None or selected_idx < 0 or selected_idx >= total_tracks:
                selected_idx = 0
            single_track = playlist.tracks[selected_idx]

            async def _on_choose_playlist(inter: discord.Interaction, load_all: bool) -> None:
                if load_all:
                    # 載入整張清單（最多 100 首防爆）
                    tracks_to_add = playlist.tracks[:100]
                    first_track = tracks_to_add[0]

                    if not player.playing:
                        vol = self.node_manager.get_guild_volume(guild_id)
                        await player.set_volume(vol)
                        try:
                            await MusicFilters.apply_hifi(player)
                        except Exception:
                            pass
                        await player.play(first_track, volume=vol)

                        for t in tracks_to_add[1:]:
                            await player.queue.put_wait(t)

                        dashboard = NowPlayingView(
                            player=player,
                            volume=vol,
                            guild_id=guild_id,
                            on_add_song=self._create_on_add_song(player),
                            text_channel_id=inter.channel_id,
                        )
                        self._dashboards[guild_id] = dashboard
                        card = build_now_playing_card(player, vol)
                        msg = await InteractionResponder.safe_send(inter, card=card, view=dashboard)
                        if msg:
                            dashboard.message = msg
                        self._start_ticker(guild_id, player)
                    else:
                        for t in tracks_to_add:
                            await player.queue.put_wait(t)
                        dashboard = self._dashboards.get(guild_id)
                        if dashboard:
                            await dashboard.refresh_dashboard()

                    res_card = ZNCard(
                        title="📋 播放清單已載入",
                        description=f"已成功匯入清單 **{playlist.name}** 共 **{len(tracks_to_add)}** 首曲目！",
                        status_pill=ZNStatusPill.SUCCESS,
                        color=ZNColor.SUCCESS,
                    )
                    try:
                        await inter.edit_original_response(embed=res_card.to_embed(), view=None)
                    except Exception:
                        await InteractionResponder.safe_send(inter, card=res_card, ephemeral=ephemeral)
                else:
                    # 僅播放當前單曲
                    await self._play_or_enqueue(inter, player, single_track, ephemeral=ephemeral)
                    dur = format_ms_to_clock(single_track.length) if hasattr(single_track, "length") else "未知"
                    res_card = ZNCard(
                        title="🎶 已加入當前單曲",
                        description=f"已從清單中挑選單曲：**[{single_track.title}]({getattr(single_track, 'uri', '')})** (`{dur}`)",
                        status_pill=ZNStatusPill.SUCCESS,
                        color=ZNColor.PRIMARY,
                    )
                    try:
                        await inter.edit_original_response(embed=res_card.to_embed(), view=None)
                    except Exception:
                        pass

            prompt_view = PlaylistPromptView(_on_choose_playlist, playlist_count=total_tracks)
            prompt_card = ZNCard(
                title="🛡️ YouTube 播放清單防爆確認",
                description=(
                    f"偵測到播放清單連結：**{playlist.name}**\n"
                    f"清單共包含 **{total_tracks}** 首歌曲。\n\n"
                    f"請問您希望匯入整張清單，還是僅播放單一曲目呢？"
                ),
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(
                interaction,
                card=prompt_card,
                view=prompt_view,
                ephemeral=ephemeral,
            )
            return

        # ----------------------------------------------------------------------
        # 2. 關鍵字搜尋多首結果 (list 且非 URL)
        # ----------------------------------------------------------------------
        if isinstance(search_res, list):
            if not query.startswith(("http://", "https://")) and len(search_res) > 1 and not ephemeral:
                # 關鍵字搜尋：彈出前 10 首下拉選單
                async def _on_select_track(inter: discord.Interaction, selected_track: wavelink.Playable) -> None:
                    await self._play_or_enqueue(inter, player, selected_track, ephemeral=ephemeral)
                    try:
                        dur = format_ms_to_clock(selected_track.length) if hasattr(selected_track, "length") else "未知"
                        chosen_card = ZNCard(
                            title="🎶 已選取曲目",
                            description=f"已成功加入：**[{selected_track.title}]({getattr(selected_track, 'uri', '')})** (`{dur}`)",
                            status_pill=ZNStatusPill.SUCCESS,
                            color=ZNColor.SUCCESS,
                        )
                        await inter.edit_original_response(embed=chosen_card.to_embed(), view=None)
                    except Exception:
                        pass

                select_view = TrackSelectView(search_res[:10], _on_select_track)
                select_card = ZNCard(
                    title="🔍 搜尋結果清單 (前 10 首)",
                    description=f"針對「**{query}**」找到了多首曲目，請透過下方選單選取：",
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.PRIMARY,
                )
                await InteractionResponder.safe_send(
                    interaction,
                    card=select_card,
                    view=select_view,
                    ephemeral=ephemeral,
                )
                return

            target_track = search_res[0]
        else:
            target_track = search_res

        # ----------------------------------------------------------------------
        # 3. 單曲播放或加入待播隊列
        # ----------------------------------------------------------------------
        await self._play_or_enqueue(interaction, player, target_track, ephemeral=ephemeral)

    # --------------------------------------------------------------------------
    # 輔助函式：播放或加入待播隊列
    # --------------------------------------------------------------------------
    async def _play_or_enqueue(
        self,
        interaction: discord.Interaction,
        player: wavelink.Player,
        track: wavelink.Playable,
        ephemeral: bool = False,
    ) -> None:
        """執行歌曲播放或推進待播清單。"""
        # 第二道絕對防線：若傳入的是未解包之 Playlist，嚴格強制提取單曲，絕不允許整張直接塞入 queue
        if isinstance(track, wavelink.Playlist) or (hasattr(track, "tracks") and not hasattr(track, "title")):
            log.warning("[MusicCog] 攔截到未解包之 Playlist 傳入 _play_or_enqueue，自動降級為單一曲目！")
            selected_idx = getattr(track, "selected", 0)
            if selected_idx is None or selected_idx < 0 or selected_idx >= len(track.tracks):
                selected_idx = 0
            track = track.tracks[selected_idx]

        guild_id = interaction.guild_id or 0
        volume = self.node_manager.get_guild_volume(guild_id)

        if not player.playing:
            player.autoplay = wavelink.AutoPlayMode.partial
            # 當前未播歌，直接開播並帶上持久化音量
            await player.set_volume(volume)
            # 全自動套用 Hi-Fi 純淨高保真等化補償濾鏡
            try:
                await MusicFilters.apply_hifi(player)
            except Exception as f_ex:
                log.debug(f"[MusicCog] 自動套用 Hi-Fi 濾鏡略過: {f_ex}")
            await player.play(track, volume=volume)

            dashboard = NowPlayingView(
                player=player,
                volume=volume,
                guild_id=guild_id,
                on_add_song=self._create_on_add_song(player),
                text_channel_id=interaction.channel_id,
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
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=ephemeral)

            dashboard = self._dashboards.get(guild_id)
            if dashboard:
                await dashboard.refresh_dashboard()

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
        search_q = query if query.startswith(("http://", "https://")) else f"ytsearch:{query}"
        search_res = await self._safe_search_tracks(search_q, preferred_node=player.node)

        if not search_res:
            await InteractionResponder.safe_send(interaction, "❌ 找不到符合條件的歌曲，請嘗試其他關鍵字或有效網址。")
            return

        await self._dispatch_search_result(
            interaction=interaction,
            player=player,
            search_res=search_res,
            query=query,
            ephemeral=False,
        )

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
        player.queue.mode = wavelink.QueueMode.normal
        player.queue.clear()
        await player.stop()

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
        updated = False
        if dashboard and dashboard.message:
            try:
                lv = card.to_layout_view(extra_view=ended_view)
                await dashboard.message.edit(view=lv, embed=None)
                updated = True
            except Exception:
                pass

        if updated:
            await InteractionResponder.safe_send(interaction, "⏹️ 音樂已停止播放並清空待播隊列。", ephemeral=True)
        else:
            await InteractionResponder.safe_send(interaction, card=card, view=ended_view)

        # 停止後檢查頻道真人狀態，若頻道無人則啟動 5 分鐘自動退出倒數
        if player.channel:
            human_count = len([m for m in player.channel.members if not m.bot])
            if human_count == 0:
                self._start_afk_timer(guild_id, timeout_seconds=300.0)
            else:
                self._cancel_afk_timer(guild_id)

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
    # 11. 音質指令 /音樂 音質
    # --------------------------------------------------------------------------
    @music_group.command(name="音質", description="設定純淨 Hi-Fi 高保真補償或原音直通 (消除悶濁塑料箱音、提亮人聲)")
    @app_commands.describe(模式="選擇音質處理模式 (預設為純淨高保真 Hi-Fi)")
    @app_commands.choices(
        模式=[
            app_commands.Choice(name="✨ 純淨高保真 (Hi-Fi 增強：消除中低頻悶濁箱音、提亮人聲與高頻細節)", value="hifi"),
            app_commands.Choice(name="🎵 原音直通 (Flat 標準：還原純平坦無等化原始聲音)", value="flat"),
        ]
    )
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def quality_command(
        self,
        interaction: discord.Interaction,
        模式: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.connected:
            await InteractionResponder.safe_send(interaction, "❌ 目前播放器未連線至語音頻道。", ephemeral=True)
            return

        current_is_hifi = getattr(player, "_hifi_enabled", True)
        target_mode = 模式.value if 模式 else ("flat" if current_is_hifi else "hifi")

        if target_mode == "hifi":
            await MusicFilters.apply_hifi(player)
            card = ZNCard(
                title="✨ 音質模式已切換：純淨高保真 (Hi-Fi)",
                description=(
                    "已套用專業 **Hi-Fi 15 頻段純淨等化補償曲線**：\n"
                    "• 📉 **消除悶音 (-0.04)**：精準修除 YouTube 250Hz~400Hz 常見的塑料混濁箱音\n"
                    "• 📈 **通透提亮 (+0.05)**：增強 1.6kHz~10kHz 人聲咬字細節與樂器空間空氣感\n"
                    "• 保持 1.0x 原始速度與音調，零破音、不失真，享受最清澈透亮的純粹好聲音！"
                ),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.PRIMARY,
            )
        else:
            await MusicFilters.apply_flat(player)
            card = ZNCard(
                title="🎵 音質模式已切換：原音直通 (Flat)",
                description=(
                    "已關閉所有等化補償濾鏡，切換為 **Flat 標準原音直通模式**。\n"
                    "音樂將完全依照音訊來源原始頻率曲線平直輸出。"
                ),
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.SECONDARY,
            )

        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 12. 倍速指令 /音樂 倍速
    # --------------------------------------------------------------------------
    @music_group.command(name="倍速", description="調整音樂播放倍速 (0.25x ~ 4.0x，預設 1.0x)")
    @app_commands.describe(倍率="請輸入播放倍率 (0.25 到 4.0，例如 1.25、1.5 或 2.0)")
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def speed_command(self, interaction: discord.Interaction, 倍率: float) -> None:
        if 倍率 < 0.25 or 倍率 > 4.0:
            await InteractionResponder.safe_send(interaction, "❌ 播放倍速必須介於 **0.25x 到 4.0x** 之間唷！", ephemeral=True)
            return

        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.connected:
            await InteractionResponder.safe_send(interaction, "❌ 目前播放器未連線至語音頻道。", ephemeral=True)
            return

        actual_speed = await MusicFilters.apply_speed(player, 倍率)
        speed_str = f"{actual_speed:.2f}".rstrip("0").rstrip(".") if actual_speed != int(actual_speed) else f"{int(actual_speed)}"

        if interaction.guild_id and interaction.guild_id in self._dashboards:
            await self._dashboards[interaction.guild_id].refresh_dashboard()

        card = ZNCard(
            title="⚡ 播放倍速已套用",
            description=f"已成功將播放速度調整為 **{speed_str}x**！\n（透過數位音訊濾鏡處理，維持原調不失真變音）",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 13. 循環指令 /音樂 循環
    # --------------------------------------------------------------------------
    @music_group.command(name="循環", description="切換音樂循環播放模式 (單曲循環 / 隊列循環 / 關閉)")
    @app_commands.describe(模式="選擇循環模式 (留空則依序輪流切換)")
    @app_commands.choices(
        模式=[
            app_commands.Choice(name="🔂 單曲循環 (重複播放當前歌曲)", value="loop"),
            app_commands.Choice(name="🔁 隊列循環 (清單播完後從頭輪播)", value="loop_all"),
            app_commands.Choice(name="❌ 關閉循環 (依序播放完畢即停止)", value="normal"),
        ]
    )
    @command_guard("music", required_level=ZNPermissionLevel.EVERYONE)
    async def loop_command(
        self,
        interaction: discord.Interaction,
        模式: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        player: Optional[wavelink.Player] = getattr(interaction.guild, "voice_client", None)
        if not player or not player.connected:
            await InteractionResponder.safe_send(interaction, "❌ 目前播放器未連線至語音頻道。", ephemeral=True)
            return

        player.autoplay = wavelink.AutoPlayMode.partial

        if 模式:
            val = 模式.value
            if val == "loop":
                player.queue.mode = wavelink.QueueMode.loop
                if player.current:
                    player.queue._loaded = player.current
            elif val == "loop_all":
                player.queue.mode = wavelink.QueueMode.loop_all
            else:
                player.queue.mode = wavelink.QueueMode.normal
        else:
            current_mode = getattr(player.queue, "mode", wavelink.QueueMode.normal)
            if current_mode == wavelink.QueueMode.normal:
                player.queue.mode = wavelink.QueueMode.loop
                if player.current:
                    player.queue._loaded = player.current
            elif current_mode == wavelink.QueueMode.loop:
                player.queue.mode = wavelink.QueueMode.loop_all
            else:
                player.queue.mode = wavelink.QueueMode.normal

        new_mode = player.queue.mode
        if new_mode == wavelink.QueueMode.loop:
            mode_desc = "🔂 **單曲循環**（將持續重複播放當前曲目）"
        elif new_mode == wavelink.QueueMode.loop_all:
            mode_desc = "🔁 **隊列循環**（整張清單播畢後將自動從頭重新循環）"
        else:
            mode_desc = "❌ **循環已關閉**（播放清單播畢後將自動進入待機）"

        if interaction.guild_id and interaction.guild_id in self._dashboards:
            await self._dashboards[interaction.guild_id].refresh_dashboard()

        card = ZNCard(
            title="🔁 循環播放模式已更新",
            description=f"目前播放狀態：{mode_desc}",
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
        guild_id = player.guild.id
        track_title = getattr(payload.track, "title", "未知曲目")
        log.info(f"[MusicCog] 歌曲開始播放: {track_title} (伺服器 ID: {guild_id})")
        setattr(player, "_failover_count", 0)
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

        raw_exc = payload.exception
        err_msg = "來源限制或格式不支援"
        if isinstance(raw_exc, dict):
            m = raw_exc.get("message", "")
            if m:
                first_line = m.strip().split("\n")[0]
                if "All clients failed" in first_line:
                    err_msg = "YouTube 來源音訊串流受阻"
                else:
                    err_msg = first_line[:60]
            elif raw_exc.get("severity"):
                err_msg = f"嚴重等級: {raw_exc.get('severity')}"
        elif raw_exc:
            err_msg = str(raw_exc).strip().split("\n")[0][:60]

        log.warning(f"[MusicCog] 節點 {current_ident} 播放受阻 ({err_msg})，曲目: {track_title}")

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
        else:
            # 隊列無剩餘歌曲，停止播放器並將控制面板原地轉換為待機卡片
            guild_id = player.guild.id if player.guild else 0
            self._stop_ticker(guild_id)
            await player.stop()
            vol = self.node_manager.get_guild_volume(guild_id)
            idle_card = ZNCard(
                title="🏁 目前沒有正在播放的音樂 (待機中)",
                description="剛才的歌曲受到 YouTube 存取限制無法取得串流。您可以點擊下方「➕ 添加歌曲」按鈕點播其他歌曲唷～",
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.PRIMARY,
                footer_text=f"🔊 音量：{vol}%  |  🎵 音樂播放器待機中",
            )
            ended_view = TrackEndedView(self._create_on_add_song(player))
            lv = idle_card.to_layout_view(extra_view=ended_view)
            dashboard = self._dashboards.get(guild_id)
            if dashboard and dashboard.message:
                try:
                    await dashboard.message.edit(view=lv, embed=None)
                except Exception:
                    pass

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
        """監聽歌曲結束，若隊列為空且無開啟循環則就地將控制面板轉換為待機卡片。"""
        player = payload.player
        if not player or not player.guild:
            return

        guild_id = player.guild.id
        track_title = getattr(payload.track, "title", "未知曲目")
        reason = getattr(payload, "reason", "finished")
        mode = getattr(player.queue, "mode", wavelink.QueueMode.normal)
        q_len = len(player.queue)
        log.info(f"[MusicCog] 歌曲播放結束: {track_title}, reason={reason}, 循環模式: {mode.name}, 隊列剩餘: {q_len}")

        # 1. 若開啟了單曲循環或隊列循環，Wavelink AutoPlay 會自動續播重播，絕不轉待機
        if mode in (wavelink.QueueMode.loop, wavelink.QueueMode.loop_all):
            log.info(f"[MusicCog] 伺服器 {guild_id} 目前處於循環模式 ({mode.name})，交由 AutoPlay 自動接續播放...")
            return

        # 2. 若隊列中尚有待播曲目，交由 AutoPlay 播放下一首
        if q_len > 0:
            return

        # 3. 若為切歌或重播被取代事件 (replaced)，略過待機轉換
        if reason == "replaced":
            return

        # 4. 隊列真正空了且無任何循環，終止定時器並原地更新控制面板為待機卡片
        self._stop_ticker(guild_id)

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
        lv = card.to_layout_view(extra_view=ended_view, timeout=None)
        dashboard = self._dashboards.get(guild_id)

        updated = False
        if dashboard and dashboard.message:
            try:
                await dashboard.message.edit(view=lv, embed=None)
                updated = True
                log.info(f"[MusicCog] 成功原地更新伺服器 {guild_id} 控制面板為播畢待機卡片")
            except Exception as e:
                log.warning(f"[MusicCog] 播畢原地更新控制面板失敗: {e}")

        if not updated:
            text_ch_id = getattr(dashboard, "text_channel_id", None)
            target_ch = self.bot.get_channel(text_ch_id) if text_ch_id else None
            if not target_ch and hasattr(player.channel, "send"):
                target_ch = player.channel
            if target_ch:
                try:
                    await target_ch.send(view=lv)
                    log.info(f"[MusicCog] 成功於頻道 {target_ch.id} 發送播畢待機卡片")
                except Exception as e:
                    log.warning(f"[MusicCog] 播畢備援發送待機卡片失敗: {e}")

        # 播畢轉待機後，檢查語音頻道是否已無真人，若是則啟動 5 分鐘自動退出倒數
        if player.channel:
            human_count = len([m for m in player.channel.members if not m.bot])
            if human_count == 0:
                self._start_afk_timer(guild_id, timeout_seconds=300.0)
            else:
                self._cancel_afk_timer(guild_id)

    # --------------------------------------------------------------------------
    # 事件監聽：語音狀態異動 (Voice State Update) - 語音頻道無真人 5 分鐘自動退出
    # --------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """監聽語音狀態異動：當語音頻道內無真人成員時啟動 5 分鐘自動退出倒數。"""
        guild = member.guild
        if not guild:
            return

        # 若異動成員為機器人本身且離開了語音頻道，立即清理所有定時器與控制面板
        if self.bot.user and member.id == self.bot.user.id and after.channel is None:
            self._stop_ticker(guild.id)
            self._cancel_afk_timer(guild.id)
            self._dashboards.pop(guild.id, None)
            return

        player: Optional[wavelink.Player] = getattr(guild, "voice_client", None)
        if not player or not player.connected or not player.channel:
            self._cancel_afk_timer(guild.id)
            return

        bot_channel = player.channel
        # 若事件與機器人當前所在的語音頻道無關，則忽略
        if before.channel != bot_channel and after.channel != bot_channel:
            return

        # 統計機器人所在語音頻道內的真人成員（排除機器人）
        human_members = [m for m in bot_channel.members if not m.bot]
        if len(human_members) == 0:
            self._start_afk_timer(guild.id, timeout_seconds=300.0)
        else:
            self._cancel_afk_timer(guild.id)


async def setup(bot: commands.Bot) -> None:
    """載入音樂模組 Cog。"""
    await bot.add_cog(MusicCog(bot))
