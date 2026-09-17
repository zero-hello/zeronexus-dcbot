"""ZeroNexus Standalone Root Commands Cog.

4 Fully Implemented Top-Level Commands:
- /幫助 (help): 互動式 Help Center (整合 11 大模組下拉選單、分頁導覽按鈕與首頁全景概覽)
- /ping (ping): 即時三維延遲測量 (WebSocket Gateway、資料庫讀寫、REST API) 與重新測試按鈕
- /當前狀態 (status): 滿載全域平台大盤 (運行時間、伺服器規模、11 大子模組運作狀況展示、資源與金鑰池)
- /診斷 (diagnostics): 系統全域健全度深度診斷與子模組探測掃描
"""

from __future__ import annotations

import time
from typing import Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.core.cache import cache
from zeronexus.core.database import db
from zeronexus.core.diagnostics import diagnostics
from zeronexus.core.stats import stats
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.modules.manager import module_manager
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard, strip_markdown_headings
from zeronexus.ui.components import DebounceGuard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill, ZNTheme


MODULE_METADATA_ORDER = [
    ("moderation", "🛡️ 管理子系統", "成員懲處、身分組管理、訊息維護與伺服器日誌稽核"),
    ("server", "🏛️ 伺服器子系統", "伺服器資訊檢索、成員統計、身分組權限分析與頻道路由總覽"),
    ("tools", "⚙️ 精確工具子系統", "任意精度計算器、台灣氣象與地震報告、密碼學編碼、網路探針與 MC (Minecraft) 伺服器探測"),
    ("ai", "🧠 人工智慧子系統", "三級備援 AI Gateway、15 款人格切換、長短期記憶與群體對話頻道"),
    ("entertainment", "🎲 娛樂遊戲子系統", "互動棋盤小遊戲 (井字棋/四子棋)、21點、俄羅斯輪盤、運勢占卜與社群經濟"),
    ("interactions", "🫂 社群互動子系統", "社群成員社交互動動作、動態關懷與情意表達指令"),
    ("settings", "🔧 伺服器設定子系統", "歡迎/離退廣播設定、自動身分組、日誌頻道、時區偏好與重設"),
    ("system", "📊 系統健康子系統", "全平台健全度掃描、模組生命週期管控、快取資料庫監控與資源檢測"),
    ("agent", "🤖 智慧代理人子系統", "自主思考、工具呼叫與五階思維代理人架構"),
    ("community", "🎉 社群狂歡與多模態套件", "賽博法庭、海龜湯、自動揪團、伺服器內梗百科、預測賭盤、相聲與多模態解析"),
    ("standalone", "🌟 頂層核心指令", "全域運行大盤、互動式幫助中心、多點延遲與系統全景診斷"),
]


class StandaloneModule(BaseModule):
    """Core standalone top-level commands."""

    def __init__(self) -> None:
        super().__init__(
            name="standalone",
            display_name="核心頂層指令",
            description="互動式幫助導覽中心、全域運行狀態大盤、多點網路延遲測量與全景系統診斷",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("幫助", "ZeroNexus 互動式全功能 Help Center 導覽中心", ZNPermissionLevel.EVERYONE),
            ("ping", "測量 Discord WebSocket 心跳、資料庫讀寫與 API 延遲", ZNPermissionLevel.EVERYONE),
            ("當前狀態", "檢視 ZeroNexus 全域平台即時運行大盤與子模組健康度", ZNPermissionLevel.EVERYONE),
            ("診斷", "執行 ZeroNexus 全系統全景健全狀態掃描", ZNPermissionLevel.EVERYONE),
        ]
        for name, desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=name,
                description=desc,
                group_name="頂層",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


# =============================================================================
# Interactive Components V2 Views
# =============================================================================

class ZNHelpView(discord.ui.LayoutView):
    """Interactive Help Center View featuring both a Dropdown Select Menu and Page Buttons."""

    def __init__(
        self,
        bot: commands.Bot,
        author_id: int,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.current_page: int = 0
        self.guard = DebounceGuard(cooldown=0.35)
        self.message: Optional[discord.Message] = None
        self._last_interaction: Optional[discord.Interaction] = None

        # Build all help pages
        self.pages: List[ZNCard] = self._build_all_pages()

        # Select menu for jump navigation
        select_options: List[discord.SelectOption] = [
            discord.SelectOption(
                label="導覽首頁",
                value="0",
                description="ZeroNexus 平台全景總覽與核心快速指引",
                emoji="🏠",
                default=True,
            )
        ]
        for idx, (mod_id, title, desc) in enumerate(MODULE_METADATA_ORDER, start=1):
            emoji_char = title.split()[0] if title else "📦"
            clean_title = title.split(maxsplit=1)[1] if " " in title else title
            select_options.append(
                discord.SelectOption(
                    label=clean_title[:100],
                    value=str(idx),
                    description=desc[:100],
                    emoji=emoji_char,
                )
            )

        self.module_select = discord.ui.Select(
            placeholder="點擊切換子模組頁面...",
            options=select_options,
            custom_id="zn_help_module_select",
        )
        self.module_select.callback = self._on_select_module

        # Navigation buttons
        self.prev_btn = discord.ui.Button(label="◀️ 上一頁", style=discord.ButtonStyle.secondary, custom_id="zn_help_prev")
        self.prev_btn.callback = self._on_prev

        self.home_btn = discord.ui.Button(label="🏠 首頁", style=discord.ButtonStyle.primary, custom_id="zn_help_home")
        self.home_btn.callback = self._on_home

        self.next_btn = discord.ui.Button(label="下一頁 ▶️", style=discord.ButtonStyle.secondary, custom_id="zn_help_next")
        self.next_btn.callback = self._on_next

        self.indicator_btn = discord.ui.Button(
            label=f"1 / {len(self.pages)}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            custom_id="zn_help_indicator",
        )

        self._rebuild_components()

    def _build_all_pages(self) -> List[ZNCard]:
        """Constructs Page 0 (Home overview) + Pages 1..11 (Module command listings)."""
        all_cmds = module_manager.command_registry.list_all()
        total_cmds_count = module_manager.command_registry.count()
        pages: List[ZNCard] = []

        # 1. Page 0: Home Overview
        home_card = ZNCard(
            title="ZeroNexus 互動式導覽中心",
            subtitle="One Platform. Many Capabilities. Zero Dependence on AI.",
            description=(
                f"歡迎使用 **ZeroNexus** 全方位多功能 Discord 服務平台！\n\n"
                f"平台目前已註冊 **`{total_cmds_count}` 條** 高效能斜線指令 (Slash Commands)，"
                f"涵蓋 **11 大業務子系統**，採用微核心與嚴格故障隔離架構，確保各模組獨立穩定運作。\n\n"
                f"💡 **導覽方式**：您可使用下方的 **下拉選單** 直接跳轉至特定模組，或點擊 **上一頁 / 下一頁** 依序瀏覽。"
            ),
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )

        overview_lines = []
        for mod_id, title, desc in MODULE_METADATA_ORDER:
            c_count = len([c for c in all_cmds if c.module_name == mod_id])
            overview_lines.append(f"{title} (`{c_count}` 條) — {desc}")
        home_card.add_section("📚 11 大領域模組一覽", "\n".join(overview_lines), inline=False)

        home_card.add_section(
            "🚀 常用熱門指令指引",
            "- `/幫助` — 開啟本互動式導覽中心\n"
            "- `/當前狀態` — 檢視全平台即時運行大盤與資源指標\n"
            "- `/ping` — 測量 WebSocket 心跳與資料庫延遲\n"
            "- `/診斷` — 執行全子系統健全狀態深度掃描\n"
            "- `/設定 總覽` — 檢視並自訂本伺服器自動化營運配置",
            inline=False,
        )
        pages.append(home_card)

        # 2. Pages 1..11: Modules
        for mod_id, title, desc in MODULE_METADATA_ORDER:
            mod_cmds = [c for c in all_cmds if c.module_name == mod_id]
            card = ZNCard(
                title=f"{title} (共 {len(mod_cmds)} 條指令)",
                subtitle=desc,
                status_pill=ZNStatusPill.TOOL,
                color=ZNColor.PRIMARY,
            )

            if not mod_cmds:
                card.description = "目前此模組尚未登記任何公開斜線指令。"
            else:
                lines = []
                for c in mod_cmds:
                    perm_str = ""
                    if c.permission_level == ZNPermissionLevel.ADMINISTRATOR:
                        perm_str = " `[管理員]`"
                    elif c.permission_level == ZNPermissionLevel.MODERATOR:
                        perm_str = " `[管理]`"
                    elif c.permission_level == ZNPermissionLevel.DEVELOPER:
                        perm_str = " `[開發者]`"
                    lines.append(f"- `/{c.full_name}` — {c.description}{perm_str}")
                card.description = "\n".join(lines)

            pages.append(card)

        return pages

    def _rebuild_components(self) -> None:
        """Constructs Components V2 LayoutView Container for active page."""
        self.clear_items()
        card = self.pages[self.current_page]

        # Update button states
        self.prev_btn.disabled = (self.current_page <= 0)
        self.next_btn.disabled = (self.current_page >= len(self.pages) - 1)
        self.home_btn.disabled = (self.current_page == 0)
        self.indicator_btn.label = f"{self.current_page + 1} / {len(self.pages)}"

        # Update select menu default option
        for opt in self.module_select.options:
            opt.default = (opt.value == str(self.current_page))

        # Assemble Container
        c = discord.ui.Container(accent_color=card.color)
        pill_str = getattr(card.status_pill, "value", str(card.status_pill)) if card.status_pill else ""
        clean_title = strip_markdown_headings(card.title)
        header_text = f"### {pill_str} {clean_title}".strip() if pill_str else f"### {clean_title}"

        c.add_item(discord.ui.TextDisplay(header_text))
        if card.subtitle:
            c.add_item(discord.ui.TextDisplay(f"*{strip_markdown_headings(card.subtitle)}*"))
        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))

        if card.description:
            c.add_item(discord.ui.TextDisplay(card.description))

        for sec in card.sections:
            c.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.TextDisplay(f"**{sec.name}**\n{sec.value}"))

        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(discord.ui.TextDisplay(f"-# ZeroNexus Help Center · {ZNTheme.format_timestamp()}"))

        # Add interactive rows inside Container
        c.add_item(discord.ui.ActionRow(self.module_select))
        c.add_item(discord.ui.ActionRow(self.prev_btn, self.home_btn, self.next_btn, self.indicator_btn))

        self.add_item(c)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(
                interaction,
                "❌ 請自行發起 `/幫助` 指令以瀏覽互動導覽中心。",
                ephemeral=True,
            )
            return False
        return True

    async def _on_select_module(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if not self.module_select.values:
                await InteractionResponder.safe_defer(interaction)
                return
            target_page = int(self.module_select.values[0])
            if 0 <= target_page < len(self.pages):
                self.current_page = target_page
                self._rebuild_components()
                await InteractionResponder.safe_edit(interaction, view=self)
            else:
                await InteractionResponder.safe_defer(interaction)
        finally:
            self.guard.release()

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if self.current_page > 0:
                self.current_page -= 1
                self._rebuild_components()
                await InteractionResponder.safe_edit(interaction, view=self)
            else:
                await InteractionResponder.safe_defer(interaction)
        finally:
            self.guard.release()

    async def _on_home(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if self.current_page != 0:
                self.current_page = 0
                self._rebuild_components()
                await InteractionResponder.safe_edit(interaction, view=self)
            else:
                await InteractionResponder.safe_defer(interaction)
        finally:
            self.guard.release()

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if self.current_page < len(self.pages) - 1:
                self.current_page += 1
                self._rebuild_components()
                await InteractionResponder.safe_edit(interaction, view=self)
            else:
                await InteractionResponder.safe_defer(interaction)
        finally:
            self.guard.release()

    async def on_timeout(self) -> None:
        for child in self.walk_children():
            if hasattr(child, "disabled"):
                child.disabled = True
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class ZNPingView(discord.ui.LayoutView):
    """Interactive Ping View with Re-test button."""

    def __init__(self, bot: commands.Bot, author_id: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.guard = DebounceGuard(cooldown=1.0)
        self.message: Optional[discord.Message] = None
        self._retest_btn = discord.ui.Button(label="🔄 重新測試", style=discord.ButtonStyle.primary, custom_id="zn_ping_retest")
        self._retest_btn.callback = self._on_retest
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        self.clear_items()
        c = discord.ui.Container(accent_color=ZNColor.SUCCESS)
        c.add_item(discord.ui.ActionRow(self._retest_btn))
        self.add_item(c)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 請自行發起 `/ping` 指令以測試網路延遲。", ephemeral=True)
            return False
        return True

    async def _on_retest(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if not await InteractionResponder.safe_defer_update(interaction):
                return
            card = await StandaloneCog.generate_ping_card(self.bot, interaction)
            c = discord.ui.Container(accent_color=card.color)
            c.add_item(discord.ui.TextDisplay(f"### {card.status_pill.value} {card.title}"))
            c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.TextDisplay(card.description))
            for sec in card.sections:
                c.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
                c.add_item(discord.ui.TextDisplay(f"**{sec.name}**\n{sec.value}"))
            c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.ActionRow(self._retest_btn))
            self.clear_items()
            self.add_item(c)
            await InteractionResponder.safe_edit(interaction, view=self)
        finally:
            self.guard.release()


class ZNStatusView(discord.ui.LayoutView):
    """Interactive Status View with Refresh button."""

    def __init__(self, bot: commands.Bot, author_id: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.guard = DebounceGuard(cooldown=1.5)
        self.message: Optional[discord.Message] = None
        self._refresh_btn = discord.ui.Button(label="🔄 重新整理大盤", style=discord.ButtonStyle.primary, custom_id="zn_status_refresh")
        self._refresh_btn.callback = self._on_refresh
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        self.clear_items()
        c = discord.ui.Container(accent_color=ZNColor.PRIMARY)
        c.add_item(discord.ui.ActionRow(self._refresh_btn))
        self.add_item(c)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 請自行發起 `/當前狀態` 指令以檢視大盤。", ephemeral=True)
            return False
        return True

    async def _on_refresh(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if not await InteractionResponder.safe_defer_update(interaction):
                return
            card = await StandaloneCog.generate_status_card(self.bot)
            c = discord.ui.Container(accent_color=card.color)
            c.add_item(discord.ui.TextDisplay(f"### {card.status_pill.value} {card.title}"))
            c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.TextDisplay(card.description))
            for sec in card.sections:
                c.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
                c.add_item(discord.ui.TextDisplay(f"**{sec.name}**\n{sec.value}"))
            c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.ActionRow(self._refresh_btn))
            self.clear_items()
            self.add_item(c)
            await InteractionResponder.safe_edit(interaction, view=self)
        finally:
            self.guard.release()


# =============================================================================
# Standalone Cog Class
# =============================================================================

class StandaloneCog(commands.Cog):
    """Discord Slash Commands for top-level root actions."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @classmethod
    async def measure_database_latency(cls) -> float:
        """Measures roundtrip query execution time against the active database."""
        try:
            t0 = time.perf_counter()
            async with db.session() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))
            return round((time.perf_counter() - t0) * 1000, 2)
        except Exception:
            return -1.0

    @classmethod
    async def generate_ping_card(cls, bot: commands.Bot, interaction: discord.Interaction) -> ZNCard:
        """Builds a comprehensive multi-point network and database latency card."""
        ws_lat = round(bot.latency * 1000, 2) if hasattr(bot, "latency") else -1.0
        db_lat = await cls.measure_database_latency()

        # Measure REST API turnaround
        api_lat_str = "正常"
        if interaction.created_at:
            import datetime
            import pytz
            now = datetime.datetime.now(pytz.UTC)
            dt = interaction.created_at if interaction.created_at.tzinfo else pytz.UTC.localize(interaction.created_at)
            api_turnaround = round((now - dt).total_seconds() * 1000, 2)
            if api_turnaround > 0:
                api_lat_str = f"{api_turnaround} ms"

        is_healthy = ws_lat >= 0 and (db_lat >= 0 or db_lat == -1.0)
        card = ZNCard(
            title="網路與資料庫延遲測量 (Ping)",
            description=(
                f"# 🏓 **{ws_lat} ms** (WebSocket 心跳)\n\n"
                f"ZeroNexus 核心服務端多點連線探測結果如下："
            ),
            status_pill=ZNStatusPill.SUCCESS if is_healthy else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if is_healthy else ZNColor.WARNING,
        )
        card.add_section("🌐 Discord WebSocket Gateway", f"`{ws_lat} ms` (即時心跳連線訊號)", inline=True)
        card.add_section("💾 資料庫往返讀寫延遲", f"`{db_lat} ms`" if db_lat >= 0 else "`本機記憶體模式 (極速)`", inline=True)
        card.add_section("⚡ Discord REST API 響應", f"`{api_lat_str}`", inline=True)
        return card

    @classmethod
    async def generate_status_card(cls, bot: commands.Bot) -> ZNCard:
        """Constructs the complete platform health and submodules status overview."""
        diag = await diagnostics.run_full_diagnostics(bot_instance=bot)
        r = stats.get_system_resources()
        cache_s = await cache.stats()

        summary = module_manager.get_health_summary()
        total_mods = len(summary)
        running_mods = sum(1 for m in summary.values() if m.get("state") in ("RUNNING", "READY"))
        degraded_mods = [m["display_name"] for m in summary.values() if m.get("state") not in ("RUNNING", "READY")]

        guild_count = len(bot.guilds) if hasattr(bot, "guilds") else 0
        user_count = len(bot.users) if hasattr(bot, "users") else 0
        gw_lat = round(bot.latency * 1000, 2) if hasattr(bot, "latency") else 0.0

        card = ZNCard(
            title="ZeroNexus 平台全景即時大盤",
            description=(
                f"**運作狀態**：`{stats.format_uptime()}` (線上穩定運作中)\n"
                f"**服務規模**：`{guild_count}` 座伺服器 | `{user_count}` 位使用者成員\n"
                f"**指令總數**：`{module_manager.command_registry.count()}` 條實體 Slash Commands\n"
                f"**Gateway 延遲**：`{gw_lat} ms`"
            ),
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )

        # 1. Host Resources
        card.add_section(
            "🖥️ 主機與環境資源",
            f"Python `{r['python_version']}` | 程序 RAM: `{r['process_ram_mb']} MB` | 系統 RAM: `{r['system_ram_used_pct']}%` | CPU: `{r['cpu_percent']}%`",
            inline=False,
        )

        # 2. Database & Cache
        db_details = diag.get("subsystems", {}).get("database", {}).get("details", "運作中")
        card.add_section(
            "💾 資料庫與快取引擎",
            f"資料庫: `{db_details}` | 快取模式: `{cache_s.get('mode')}` (命中率: `{cache_s.get('hit_rate_pct')}%`，鍵數: `{cache_s.get('keys_count', 0)}`)",
            inline=False,
        )

        # 3. Submodules Health
        if not degraded_mods:
            mod_status_desc = f"🟢 全部 **{running_mods} / {total_mods}** 個核心子模組運作正常 (RUNNING)"
        else:
            mod_status_desc = f"🟡 運作中: `{running_mods}/{total_mods}` | 異常/隔離模組：`{', '.join(degraded_mods)}`"
        card.add_section("🧩 系統子模組運行狀況", mod_status_desc, inline=False)

        # 4. AI Key Pool
        ai_info = diag.get("subsystems", {}).get("ai_gateway", {})
        if "providers" in ai_info and isinstance(ai_info["providers"], dict):
            ai_lines = []
            for p_name, p_data in ai_info["providers"].items():
                if isinstance(p_data, dict):
                    active_str = "🟢" if p_data.get("active") else "🟡"
                    ai_lines.append(f"{active_str} **{p_name.upper()}** (`{p_data.get('default_model')}`) — {p_data.get('total_keys')} 支金鑰")
            if ai_lines:
                card.add_section("🤖 AI Gateway 金鑰池", "\n".join(ai_lines), inline=False)

        # 5. CWA Weather & Earthquake
        cwa_sub = diag.get("subsystems", {}).get("cwa_weather", {})
        card.add_section("⛅ 中央氣象署 (CWA)", f"{cwa_sub.get('icon', '⚪')} {cwa_sub.get('details', '未配置')}", inline=False)

        return card

    @app_commands.command(name="幫助", description="ZeroNexus 互動式全功能導覽中心")
    @command_guard("standalone")
    async def help_command(self, interaction: discord.Interaction) -> None:
        view = ZNHelpView(bot=self.bot, author_id=interaction.user.id)
        msg = await InteractionResponder.safe_send(interaction, view=view)
        if msg:
            view.message = msg

    @app_commands.command(name="ping", description="測量 Discord WebSocket 心跳、資料庫讀寫與 API 延遲")
    @command_guard("standalone")
    async def ping_command(self, interaction: discord.Interaction) -> None:
        card = await self.generate_ping_card(self.bot, interaction)
        view = ZNPingView(bot=self.bot, author_id=interaction.user.id)
        # Wrap card and view together
        c = discord.ui.Container(accent_color=card.color)
        c.add_item(discord.ui.TextDisplay(f"### {card.status_pill.value} {card.title}"))
        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(discord.ui.TextDisplay(card.description))
        for sec in card.sections:
            c.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.TextDisplay(f"**{sec.name}**\n{sec.value}"))
        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(discord.ui.ActionRow(view._retest_btn))
        view.clear_items()
        view.add_item(c)
        msg = await InteractionResponder.safe_send(interaction, view=view)
        if msg:
            view.message = msg

    @app_commands.command(name="當前狀態", description="檢視 ZeroNexus 全域平台即時運行大盤與子模組健康度")
    @command_guard("standalone")
    async def status_command(self, interaction: discord.Interaction) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return

        card = await self.generate_status_card(self.bot)
        view = ZNStatusView(bot=self.bot, author_id=interaction.user.id)
        c = discord.ui.Container(accent_color=card.color)
        c.add_item(discord.ui.TextDisplay(f"### {card.status_pill.value} {card.title}"))
        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(discord.ui.TextDisplay(card.description))
        for sec in card.sections:
            c.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.TextDisplay(f"**{sec.name}**\n{sec.value}"))
        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(discord.ui.ActionRow(view._refresh_btn))
        view.clear_items()
        view.add_item(c)
        msg = await InteractionResponder.safe_send(interaction, view=view)
        if msg:
            view.message = msg

    @app_commands.command(name="診斷", description="執行全系統子模組全景健全度掃描")
    @command_guard("standalone")
    async def diagnostics_command(self, interaction: discord.Interaction) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return

        diag = await diagnostics.run_full_diagnostics(bot_instance=self.bot)
        card = ZNCard(
            title="ZeroNexus 系統全域健全度診斷報告",
            description="全子系統與業務領域模組探針掃描結果如下：",
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.SUCCESS if diag.get("all_healthy") else ZNColor.WARNING,
        )

        for key, info in diag.get("subsystems", {}).items():
            if isinstance(info, dict) and "name" in info:
                name = info["name"]
                icon = info.get("icon", "⚪")
                lat = f" ({info['latency_ms']}ms)" if "latency_ms" in info and info["latency_ms"] >= 0 else ""
                det = info.get("details", "")
                card.add_section(f"{icon} {name}{lat}", det or "運作中", inline=True)

        # Include module states
        mods_summary = diag.get("modules", {})
        if mods_summary:
            mod_lines = []
            for m_name, m_info in mods_summary.items():
                icon = m_info.get("icon", "🟢")
                d_name = m_info.get("display_name", m_name)
                state = m_info.get("state", "RUNNING")
                mod_lines.append(f"{icon} **{d_name}**: `{state}`")
            card.add_section("🧩 業務領域模組健康狀態", " | ".join(mod_lines[:6]) + "\n" + " | ".join(mod_lines[6:]), inline=False)

        await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StandaloneCog(bot))
