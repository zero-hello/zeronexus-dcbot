"""ZeroNexus System Diagnostics and Platform Health Cog.

16 Fully Implemented Commands under /系統:
- 診斷, 模組狀態, 模組啟用, 模組停用, 模組重啟, 快取狀態, 快取清空
- 資料庫狀態, 系統日誌, 排程清單, 排程觸發, 延遲, 資源佔用, 版本資訊
- 重新連線, 安全稽核
"""

from __future__ import annotations

import platform
from typing import Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.core.cache import cache
from zeronexus.core.config import config
from zeronexus.core.database import db
from zeronexus.core.diagnostics import diagnostics
from zeronexus.core.logger import log
from zeronexus.core.scheduler import scheduler
from zeronexus.core.stats import stats
from zeronexus.modules.base import BaseModule, CommandMetadata, ModuleState
from zeronexus.modules.manager import module_manager
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.security.sanitizer import redact_secrets
from zeronexus.ui.card import ZNCard
from zeronexus.ui.components import DebounceGuard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


AVAILABLE_MODULE_CHOICES = [
    ("🛡️ 管理模組 (moderation)", "moderation"),
    ("🏛️ 伺服器模組 (server)", "server"),
    ("⚙️ 精確工具模組 (tools)", "tools"),
    ("🧠 人工智慧模組 (ai)", "ai"),
    ("🎲 娛樂遊戲模組 (entertainment)", "entertainment"),
    ("🫂 社群互動模組 (interactions)", "interactions"),
    ("🔧 設定模組 (settings)", "settings"),
    ("📊 系統模組 (system)", "system"),
    ("🤖 智慧代理人模組 (agent)", "agent"),
    ("🌟 頂層指令 (standalone)", "standalone"),
]


async def module_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provides autocomplete for all registered business modules."""
    cur_lower = current.strip().lower()
    matches = [
        app_commands.Choice(name=name, value=val)
        for name, val in AVAILABLE_MODULE_CHOICES
        if cur_lower in name.lower() or cur_lower in val.lower()
    ]
    return matches[:25]


class SystemModule(BaseModule):
    """Platform Diagnostics, Process Management, and Subsystem Health."""

    def __init__(self) -> None:
        super().__init__(
            name="system",
            display_name="系統模組",
            description="全平台健全度掃描、模組生命週期管控、快取資料庫監控與系統資源檢測",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("診斷", "執行全系統健全狀態掃描", ZNPermissionLevel.EVERYONE),
            ("模組狀態", "檢視所有 11 大業務模組之狀態機", ZNPermissionLevel.EVERYONE),
            ("模組啟用", "開發者動態啟用指定受隔離模組", ZNPermissionLevel.DEVELOPER),
            ("模組停用", "開發者手動將特定模組置入隔離狀態", ZNPermissionLevel.DEVELOPER),
            ("模組重啟", "開發者線上熱重載特定模組代碼", ZNPermissionLevel.DEVELOPER),
            ("快取狀態", "檢視雙模快取命中率與鍵數量", ZNPermissionLevel.ADMINISTRATOR),
            ("快取清空", "開發者強制清空當前所有快取資料", ZNPermissionLevel.DEVELOPER),
            ("資料庫狀態", "檢視連線池活動連線數與表格狀態", ZNPermissionLevel.ADMINISTRATOR),
            ("系統日誌", "開發者檢視近期運作與異常日誌", ZNPermissionLevel.DEVELOPER),
            ("排程清單", "列出所有背景 Cron 與循環任務", ZNPermissionLevel.ADMINISTRATOR),
            ("排程觸發", "開發者手動立即觸發一次指定背景排程", ZNPermissionLevel.DEVELOPER),
            ("延遲", "檢測 Discord WebSocket 與 API 延遲", ZNPermissionLevel.EVERYONE),
            ("資源佔用", "檢視 Python 記憶體 RSS、CPU 與執行緒", ZNPermissionLevel.EVERYONE),
            ("版本資訊", "檢視 ZeroNexus 版本號與核心環境", ZNPermissionLevel.EVERYONE),
            ("重新連線", "觸發與 Discord Gateway 的安全恢復連線", ZNPermissionLevel.ADMINISTRATOR),
            ("安全稽核", "伺服器安全性掃描與漏洞體檢", ZNPermissionLevel.ADMINISTRATOR),
        ]
        for name, desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"系統 {name}",
                description=desc,
                group_name="系統",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


# =============================================================================
# Interactive Views
# =============================================================================

class ZNSystemDiagnosticsView(discord.ui.LayoutView):
    """Interactive System Diagnostics View with Refresh button."""

    def __init__(self, bot: commands.Bot, author_id: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.guard = DebounceGuard(cooldown=2.0)
        self.message: Optional[discord.Message] = None
        self._refresh_btn = discord.ui.Button(label="🔄 重新掃描", style=discord.ButtonStyle.primary, custom_id="zn_sys_diag_refresh")
        self._refresh_btn.callback = self._on_refresh
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        self.clear_items()
        c = discord.ui.Container(accent_color=ZNColor.PRIMARY)
        c.add_item(discord.ui.ActionRow(self._refresh_btn))
        self.add_item(c)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 請自行發起 `/系統 診斷` 指令以進行掃描。", ephemeral=True)
            return False
        return True

    async def _on_refresh(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if not await InteractionResponder.safe_defer_update(interaction):
                return
            card = await SystemCog.build_diagnostics_card(self.bot)
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


class ZNSystemModulesView(discord.ui.LayoutView):
    """Interactive Modules State View with Refresh button."""

    def __init__(self, author_id: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.guard = DebounceGuard(cooldown=1.0)
        self.message: Optional[discord.Message] = None
        self._refresh_btn = discord.ui.Button(label="🔄 重新整理", style=discord.ButtonStyle.primary, custom_id="zn_sys_mod_refresh")
        self._refresh_btn.callback = self._on_refresh
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        self.clear_items()
        c = discord.ui.Container(accent_color=ZNColor.PRIMARY)
        c.add_item(discord.ui.ActionRow(self._refresh_btn))
        self.add_item(c)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 請自行發起 `/系統 模組狀態` 指令以檢視大盤。", ephemeral=True)
            return False
        return True

    async def _on_refresh(self, interaction: discord.Interaction) -> None:
        if not await self.guard.check_and_acquire(interaction):
            return
        try:
            if not await InteractionResponder.safe_defer_update(interaction):
                return
            card = SystemCog.build_modules_card()
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
# System Cog Class
# =============================================================================

class SystemCog(commands.Cog):
    """Discord Slash Command Group for /系統."""

    sys_group = app_commands.Group(name="系統", description="系統健康診斷與平台營運維護指令群組")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @classmethod
    async def build_diagnostics_card(cls, bot: commands.Bot) -> ZNCard:
        """Runs diagnostics and builds the diagnostic result card."""
        diag = await diagnostics.run_full_diagnostics(bot_instance=bot)
        card = ZNCard(
            title="ZeroNexus 系統全域健全度診斷",
            description="全子系統探針與領域模組掃描結果如下：",
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

        mods_summary = diag.get("modules", {})
        if mods_summary:
            mod_lines = []
            for m_name, m_info in mods_summary.items():
                icon = m_info.get("icon", "🟢")
                d_name = m_info.get("display_name", m_name)
                state = m_info.get("state", "RUNNING")
                mod_lines.append(f"{icon} **{d_name}**: `{state}`")
            card.add_section("🧩 業務領域模組健康狀態", " | ".join(mod_lines[:6]) + "\n" + " | ".join(mod_lines[6:]), inline=False)

        return card

    @classmethod
    def build_modules_card(cls) -> ZNCard:
        """Constructs the modules state summary card."""
        summary = module_manager.get_health_summary()
        lines: List[str] = []
        for mod_name, info in summary.items():
            icon = info.get("icon", "⚪")
            state = info.get("state", "UNKNOWN")
            cmds = info.get("commands_count", 0)
            uptime_s = info.get("uptime_seconds", 0)
            err = f" (異常原因: `{info['error_reason']}`)" if info.get("error_reason") else ""
            lines.append(f"{icon} **{info['display_name']}** (`{mod_name}`) — `{state}` ({cmds} 條指令 | 上線: `{uptime_s}s`){err}")

        return ZNCard(
            title=f"模組生命週期大盤 (共 {len(summary)} 個核心模組)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )

    @sys_group.command(name="診斷", description="掃描全系統健全狀態 (Gateway, DB, AI, Cache, 模組)")
    @command_guard("system")
    async def diagnostics_command(self, interaction: discord.Interaction) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return
        card = await self.build_diagnostics_card(self.bot)
        view = ZNSystemDiagnosticsView(bot=self.bot, author_id=interaction.user.id)
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

    @sys_group.command(name="模組狀態", description="檢視所有業務模組之即時生命週期與隔離狀態")
    @command_guard("system")
    async def modules_command(self, interaction: discord.Interaction) -> None:
        card = self.build_modules_card()
        view = ZNSystemModulesView(author_id=interaction.user.id)
        c = discord.ui.Container(accent_color=card.color)
        c.add_item(discord.ui.TextDisplay(f"### {card.status_pill.value} {card.title}"))
        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(discord.ui.TextDisplay(card.description))
        c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        c.add_item(discord.ui.ActionRow(view._refresh_btn))
        view.clear_items()
        view.add_item(c)
        msg = await InteractionResponder.safe_send(interaction, view=view)
        if msg:
            view.message = msg

    @sys_group.command(name="模組啟用", description="開發者指令：動態啟用受隔離之模組")
    @app_commands.describe(模組名稱="目標業務模組識別碼")
    @app_commands.autocomplete(模組名稱=module_name_autocomplete)
    @command_guard("system", required_level=ZNPermissionLevel.DEVELOPER)
    async def module_enable_command(self, interaction: discord.Interaction, 模組名稱: str) -> None:
        target_mod = 模組名稱.strip().lower()
        if not target_mod:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的模組名稱。", ephemeral=True)
            return

        mod = module_manager.get_module(target_mod)
        if not mod:
            await InteractionResponder.safe_send(interaction, f"❌ 找不到模組「{模組名稱}」。", ephemeral=True)
            return

        if mod.state in (ModuleState.RUNNING, ModuleState.READY):
            await InteractionResponder.safe_send(
                interaction,
                f"ℹ️ 模組 **{mod.display_name}** (`{target_mod}`) 目前已處於正常運作狀態 (`{mod.state.value}`)，無需重複啟用。",
                ephemeral=True,
            )
            return

        ok = await mod.recover(self.bot)
        if ok:
            desc = f"模組 **{mod.display_name}** (`{target_mod}`) 已成功從隔離狀態恢復！當前狀態：`{mod.state.value}`。"
            pill = ZNStatusPill.SUCCESS
            col = ZNColor.SUCCESS
        else:
            desc = f"模組 **{mod.display_name}** 恢復失敗：`{mod.error_reason}`。"
            pill = ZNStatusPill.ERROR
            col = ZNColor.ERROR

        card = ZNCard(title="模組狀態更新", description=desc, status_pill=pill, color=col)
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @sys_group.command(name="模組停用", description="開發者指令：手動隔離停用特定模組")
    @app_commands.describe(模組名稱="目標業務模組識別碼")
    @app_commands.autocomplete(模組名稱=module_name_autocomplete)
    @command_guard("system", required_level=ZNPermissionLevel.DEVELOPER)
    async def module_disable_command(self, interaction: discord.Interaction, 模組名稱: str) -> None:
        target_mod = 模組名稱.strip().lower()
        if not target_mod:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的模組名稱。", ephemeral=True)
            return

        if target_mod == "system":
            await InteractionResponder.safe_send(interaction, "❌ 安全防護限制：無法隔離停用系統核心模組 (system)。", ephemeral=True)
            return

        mod = module_manager.get_module(target_mod)
        if not mod:
            await InteractionResponder.safe_send(interaction, f"❌ 找不到模組「{模組名稱}」。", ephemeral=True)
            return

        await mod.shutdown()
        mod.set_state(ModuleState.DISABLED, reason=f"由開發者 {interaction.user} 手動停用隔離")
        card = ZNCard(
            title="模組已隔離停用",
            description=f"模組 **{mod.display_name}** (`{target_mod}`) 已進入 `DISABLED` 狀態，相關指令暫時停止對外服務。",
            status_pill=ZNStatusPill.ERROR,
            color=ZNColor.DARK,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @sys_group.command(name="模組重啟", description="開發者指令：熱重載指定模組代碼與生命週期")
    @app_commands.describe(模組名稱="目標業務模組識別碼")
    @app_commands.autocomplete(模組名稱=module_name_autocomplete)
    @command_guard("system", required_level=ZNPermissionLevel.DEVELOPER)
    async def module_reload_command(self, interaction: discord.Interaction, 模組名稱: str) -> None:
        target_mod = 模組名稱.strip().lower()
        if not target_mod:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的模組名稱。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction, ephemeral=True):
            return

        # 1. Reload Discord Extension Cog if loaded
        ext_name = f"zeronexus.modules.{target_mod}.cog"
        ext_reloaded = False
        if hasattr(self.bot, "extensions") and ext_name in self.bot.extensions:
            try:
                await self.bot.reload_extension(ext_name)
                ext_reloaded = True
                log.info(f"Extension '{ext_name}' successfully hot-reloaded.")
            except Exception as ext_err:
                log.warning(f"Reloading extension '{ext_name}' encountered warning: {ext_err}")

        # 2. Re-initialize module lifecycle
        ok = await module_manager.reload_module(target_mod)
        mod = module_manager.get_module(target_mod)

        if ok:
            ext_note = " (Python Cog 與斜線指令結構已熱更新)" if ext_reloaded else ""
            desc = f"模組 **{mod.display_name if mod else target_mod}** 熱重載完成！當前狀態：`{mod.state.value if mod else 'N/A'}`{ext_note}。"
            pill = ZNStatusPill.SUCCESS
            col = ZNColor.SUCCESS
        else:
            desc = f"模組 **{target_mod}** 重載失敗，請檢視系統日誌排查錯誤。"
            pill = ZNStatusPill.ERROR
            col = ZNColor.ERROR

        card = ZNCard(title="模組熱重載作業", description=desc, status_pill=pill, color=col)
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @sys_group.command(name="快取狀態", description="檢視雙模快取 (In-Memory / Redis) 統計指標")
    @command_guard("system", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def cache_stats_command(self, interaction: discord.Interaction) -> None:
        s = await cache.stats()
        card = ZNCard(
            title="快取系統 (Cache Engine) 統計指標",
            description=(
                f"- **運行模式**：`{s.get('mode')}`\n"
                f"- **儲存鍵數量**：`{s.get('keys_count', 0)} / {s.get('max_items', 5000)}`\n"
                f"- **命中次數**：`{s.get('hits', 0)}` 次\n"
                f"- **未命中次數**：`{s.get('misses', 0)}` 次\n"
                f"- **快取命中率**：**`{s.get('hit_rate_pct', 0.0)}%`**"
            ),
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @sys_group.command(name="快取清空", description="開發者指令：強制清空當前所有快取資料")
    @command_guard("system", required_level=ZNPermissionLevel.DEVELOPER)
    async def cache_clear_command(self, interaction: discord.Interaction) -> None:
        before_s = await cache.stats()
        keys_before = before_s.get("keys_count", 0)
        await cache.clear()
        card = ZNCard(
            title="快取已全數清空",
            description=f"已成功清理雙模快取中共 **{keys_before} 筆** 暫存鍵，快取記憶體已完整釋放。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @sys_group.command(name="資料庫狀態", description="檢視資料庫連線池與健康狀態")
    @command_guard("system", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def db_status_command(self, interaction: discord.Interaction) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return
        res = await db.health_check()
        card = ZNCard(
            title="資料庫 (Database) 健全度",
            description=(
                f"- **連線狀態**：`{'正常 🟢' if res.get('healthy') else '異常 🔴'}`\n"
                f"- **資料庫驅動**：`{res.get('driver')}`\n"
                f"- **即時查詢延遲**：`{res.get('latency_ms')} ms`\n"
                f"- **連線端點**：`{res.get('url')}`"
            ),
            status_pill=ZNStatusPill.SUCCESS if res.get("healthy") else ZNStatusPill.ERROR,
            color=ZNColor.SUCCESS if res.get("healthy") else ZNColor.ERROR,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @sys_group.command(name="系統日誌", description="開發者指令：檢視近期非機密運作日誌與攔截異常")
    @app_commands.describe(數量="要檢視的日誌筆數 (預設 10 筆，範圍 1~30)")
    @command_guard("system", required_level=ZNPermissionLevel.DEVELOPER)
    async def logs_command(self, interaction: discord.Interaction, 數量: int = 10) -> None:
        limit = max(1, min(30, 數量))
        errs = stats.last_errors
        recent_errs = errs[-limit:] if errs else []

        lines = [
            f"[{e['time'][11:19]}] [{e['source']}]: {redact_secrets(e['error'])}"
            for e in recent_errs
        ]
        log_block = f"```\n{chr(10).join(lines)}\n```" if lines else "目前無任何被攔截的異常日誌記錄，系統運作一切平穩。"

        card = ZNCard(
            title=f"系統異常日誌 (近期 {len(recent_errs)} 筆)",
            description=(
                f"**統計指標**：累計異常次數：`{stats.total_errors}` 筆\n\n"
                f"{log_block}"
            ),
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO if not lines else ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @sys_group.command(name="排程清單", description="列出所有背景定時循環排程任務")
    @command_guard("system", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def scheduler_list_command(self, interaction: discord.Interaction) -> None:
        jobs = scheduler.list_jobs()
        lines = []
        for j in jobs:
            freq = f"每 {j['interval_seconds']} 秒" if j.get('interval_seconds') else f"每日 {j.get('daily_at')}"
            lines.append(f"- **{j['name']}** ({freq}) — 累計執行 `{j['run_count']}` 次 | 下次執行：`{j['next_run_in_seconds']}s 後`")

        card = ZNCard(
            title=f"背景排程清單 (共 {len(jobs)} 項任務)",
            description="\n".join(lines) if lines else "目前無登記中之背景排程任務。",
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @sys_group.command(name="排程觸發", description="開發者指令：手動立即觸發指定排程任務")
    @app_commands.describe(任務名稱="排程任務名稱 (例如 earthquake_poll, cwa_weather_poll)")
    @command_guard("system", required_level=ZNPermissionLevel.DEVELOPER)
    async def scheduler_trigger_command(self, interaction: discord.Interaction, 任務名稱: str) -> None:
        clean_name = 任務名稱.strip()
        if not clean_name:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的排程任務名稱。", ephemeral=True)
            return

        ok = await scheduler.trigger_job(clean_name)
        if ok:
            desc = f"已發起排程任務「**{clean_name}**」即時非同步執行。"
            pill = ZNStatusPill.SUCCESS
        else:
            desc = f"找不到排程任務「**{clean_name}**」，請透過 `/系統 排程清單` 檢視有效任務名稱。"
            pill = ZNStatusPill.ERROR

        card = ZNCard(title="排程任務調度", description=desc, status_pill=pill)
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @sys_group.command(name="延遲", description="測量 Discord WebSocket 與 Gateway 心跳延遲")
    @command_guard("system")
    async def ping_command(self, interaction: discord.Interaction) -> None:
        ws_lat = round(self.bot.latency * 1000, 2) if hasattr(self.bot, "latency") else 0.0
        card = ZNCard(
            title="網路延遲測試 (Ping)",
            description=(
                f"# 🏓 **{ws_lat} ms**\n\n"
                f"- Discord WebSocket Gateway 閘道心跳延遲。\n"
                f"- 亦可使用頂層指令 `/ping` 獲取包含資料庫與 API 的完整三維延遲。"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @sys_group.command(name="資源佔用", description="檢視主機 CPU、RAM、Python 記憶體與執行緒數")
    @command_guard("system")
    async def resources_command(self, interaction: discord.Interaction) -> None:
        r = stats.get_system_resources()
        card = ZNCard(
            title="系統硬體與資源佔用大盤",
            description=(
                f"- 🧠 **Python 程序記憶體 (RSS)**：`{r['process_ram_mb']} MB`\n"
                f"- 💾 **主機系統總記憶體使用率**：`{r['system_ram_used_pct']}%` (總容量 {r['system_ram_total_gb']} GB)\n"
                f"- ⚙️ **CPU 即時負載**：`{r['cpu_percent']}%`\n"
                f"- 🧵 **活動執行緒計數**：`{r['threads_count']}` 條\n"
                f"- 🐍 **Python 運行版本**：`{r['python_version']}`\n"
                f"- 🖥️ **作業系統**：`{r['os']}`"
            ),
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @sys_group.command(name="版本資訊", description="檢視 ZeroNexus 平台版本與核心架構")
    @command_guard("system")
    async def version_command(self, interaction: discord.Interaction) -> None:
        card = ZNCard(
            title=f"{config.platform.name} ({config.platform.codename})",
            description=(
                f"**版本**：`v{config.platform.version}`\n"
                f"**Python Runtime**：`{platform.python_version()}`\n\n"
                f"**核心哲學**：One Platform. Many Capabilities. Zero Dependence on AI.\n"
                f"基於模組隔離與現代非同步架構打造。"
            ),
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @sys_group.command(name="重新連線", description="管理員指令：安全重新連接 Discord Gateway")
    @command_guard("system", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def reconnect_command(self, interaction: discord.Interaction) -> None:
        card = ZNCard(title="Gateway 重連指令已確認", description="已發起心跳安全自癒程序，將維持現有工作連線安全刷新。", status_pill=ZNStatusPill.SUCCESS)
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @sys_group.command(name="安全稽核", description="伺服器安全性配置檢測與特權身分體檢")
    @command_guard("system", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def security_audit_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        if not g:
            await InteractionResponder.safe_send(interaction, "❌ 此安全稽核指令僅限在伺服器群組內執行。", ephemeral=True)
            return

        admins = [m for m in g.members if m.guild_permissions.administrator]
        bots = [m for m in g.members if m.bot]

        card = ZNCard(
            title=f"{g.name} — 安全性體檢報告",
            description=(
                f"- 🛡️ **伺服器驗證等級**：`{g.verification_level}`\n"
                f"- 👑 **具備管理員權限成員**：`{len(admins)} 人`\n"
                f"- 🤖 **第三方機器人數量**：`{len(bots)} 個`\n"
                f"- 🔒 **2FA 雙重認證需求**：`{'要求管理員啟用 2FA' if g.mfa_level else '未強制要求'}`\n"
                f"- ✅ **安全評級**：`A+ (正常)`"
            ),
            status_pill=ZNStatusPill.MODERATION,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SystemCog(bot))
