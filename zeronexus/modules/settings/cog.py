"""ZeroNexus Settings Center Command Cog.

18 Fully Implemented Commands under /設定:
- 總覽, 歡迎訊息, 歡迎頻道, 歡迎關閉, 離開訊息, 離開頻道, 離開關閉
- 自動身分組, 自動身分組關閉, 日誌頻道, 日誌設定, 時區, 時區設定, ai每日上限
- 地震通報頻道, 地震通知設定, 天氣通知設定, 重設, 備份設定
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from zeronexus.core.database import db
from zeronexus.models.guild import GuildSettings
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill, ZNTheme
from zeronexus.ui.views import ZNConfirmView


COMMON_TIMEZONES = [
    ("Asia/Taipei (臺灣標準時間 UTC+8)", "Asia/Taipei"),
    ("Asia/Tokyo (日本東京時間 UTC+9)", "Asia/Tokyo"),
    ("Asia/Hong_Kong (香港時間 UTC+8)", "Asia/Hong_Kong"),
    ("Asia/Singapore (新加坡時間 UTC+8)", "Asia/Singapore"),
    ("UTC (世界協調時間 UTC+0)", "UTC"),
    ("America/New_York (美國東部時間 UTC-5/UTC-4)", "America/New_York"),
    ("America/Los_Angeles (美國太平洋時間 UTC-8/UTC-7)", "America/Los_Angeles"),
    ("Europe/London (英國倫敦時間 UTC+0/UTC+1)", "Europe/London"),
    ("Europe/Paris (歐洲巴黎時間 UTC+1/UTC+2)", "Europe/Paris"),
    ("Australia/Sydney (澳洲雪梨時間 UTC+10/UTC+11)", "Australia/Sydney"),
]


async def timezone_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provides fast autocomplete for standard IANA timezones."""
    cur_lower = current.strip().lower()
    matches = [
        app_commands.Choice(name=name, value=val)
        for name, val in COMMON_TIMEZONES
        if cur_lower in name.lower() or cur_lower in val.lower()
    ]
    return matches[:25]


def check_bot_channel_permissions(
    channel: discord.TextChannel,
    bot_member: Optional[discord.Member],
) -> tuple[bool, List[str]]:
    """Checks whether the bot has required permissions to post embeds in target channel."""
    if not bot_member:
        return True, []
    perms = channel.permissions_for(bot_member)
    missing: List[str] = []
    if not perms.view_channel:
        missing.append("檢視頻道")
    if not perms.send_messages:
        missing.append("發送訊息")
    if not perms.embed_links:
        missing.append("嵌入連結")
    return len(missing) == 0, missing


class SettingsModule(BaseModule):
    """Server preferences, automated greetings, logging, and quotas."""

    def __init__(self) -> None:
        super().__init__(
            name="settings",
            display_name="設定模組",
            description="歡迎/離退廣播設定、自動身分組、日誌頻道、時區偏好與伺服器出廠重設",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("總覽", "視覺化檢視全伺服器配置狀態", ZNPermissionLevel.ADMINISTRATOR),
            ("歡迎訊息", "設定新成員加入時之歡迎詞樣板", ZNPermissionLevel.ADMINISTRATOR),
            ("歡迎頻道", "指定歡迎訊息發布頻道", ZNPermissionLevel.ADMINISTRATOR),
            ("歡迎關閉", "停用新成員加入歡迎通知", ZNPermissionLevel.ADMINISTRATOR),
            ("離開訊息", "設定成員離退告別通知詞樣板", ZNPermissionLevel.ADMINISTRATOR),
            ("離開頻道", "指定成員離退廣播頻道", ZNPermissionLevel.ADMINISTRATOR),
            ("離開關閉", "停用成員離退廣播通知", ZNPermissionLevel.ADMINISTRATOR),
            ("自動身分組", "設定新進成員自動授予之身分組", ZNPermissionLevel.ADMINISTRATOR),
            ("自動身分組關閉", "停用新成員自動派發身分組", ZNPermissionLevel.ADMINISTRATOR),
            ("日誌頻道", "指定管理與安全稽核發送頻道", ZNPermissionLevel.ADMINISTRATOR),
            ("日誌設定", "配置需被監控之伺服器事件", ZNPermissionLevel.ADMINISTRATOR),
            ("時區", "自訂伺服器標準時區 (預設 Asia/Taipei)", ZNPermissionLevel.ADMINISTRATOR),
            ("時區設定", "自訂伺服器標準時區 (相容別名)", ZNPermissionLevel.ADMINISTRATOR),
            ("ai每日上限", "自訂伺服器每人每日 AI 免費次數", ZNPermissionLevel.ADMINISTRATOR),
            ("地震通報頻道", "指定中央氣象署 (CWA) 顯著有感地震推播頻道與門檻", ZNPermissionLevel.ADMINISTRATOR),
            ("地震通知設定", "指定中央氣象署 (CWA) 顯著有感地震推播頻道 (相容別名)", ZNPermissionLevel.ADMINISTRATOR),
            ("天氣通知設定", "指定 CWA 天氣預報與即時推播頻道", ZNPermissionLevel.ADMINISTRATOR),
            ("重設", "重設伺服器所有設定為出廠預設值", ZNPermissionLevel.ADMINISTRATOR),
            ("備份設定", "匯出伺服器完整設定 JSON 結構檔", ZNPermissionLevel.ADMINISTRATOR),
        ]
        for name, desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"設定 {name}",
                description=desc,
                group_name="設定",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


class SettingsCog(commands.Cog):
    """Discord Slash Command Group for /設定."""

    settings_group = app_commands.Group(name="設定", description="伺服器自動化與營運偏好設定指令群組", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_or_create_settings(self, session: Any, guild_id: int) -> GuildSettings:
        """Retrieves or atomically creates a GuildSettings record within an active session."""
        stmt = select(GuildSettings).where(GuildSettings.guild_id == guild_id)
        res = await session.execute(stmt)
        s = res.scalars().first()
        if not s:
            try:
                async with session.begin_nested():
                    s = GuildSettings(guild_id=guild_id)
                    session.add(s)
                    await session.flush()
            except Exception:
                res = await session.execute(stmt)
                s = res.scalars().first()
                if not s:
                    raise
        return s

    async def _fetch_or_create_settings(self, guild_id: int) -> GuildSettings:
        """Standalone helper ensuring a GuildSettings record exists and returns it safely."""
        async with db.session() as session:
            return await self._get_or_create_settings(session, guild_id)

    @settings_group.command(name="總覽", description="視覺化檢視全伺服器當前所有配置狀態")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def overview_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        s = await self._fetch_or_create_settings(interaction.guild_id)
        guild_name = interaction.guild.name if interaction.guild else f"伺服器 {interaction.guild_id}"
        card = ZNCard(
            title=f"{guild_name} — 伺服器配置總覽",
            description="當前伺服器自動化廣播、安全稽核與偏好設定狀態如下：",
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )

        welcome_status = (
            f"`開啟` (頻道: <#{s.welcome_channel_id}>)"
            if (s.welcome_enabled and s.welcome_channel_id)
            else ("`開啟 (未綁定頻道)`" if s.welcome_enabled else "`已停用`")
        )
        card.add_section("👋 歡迎通知", welcome_status, inline=True)

        leave_status = (
            f"`開啟` (頻道: <#{s.leave_channel_id}>)"
            if (s.leave_enabled and s.leave_channel_id)
            else ("`開啟 (未綁定頻道)`" if s.leave_enabled else "`已停用`")
        )
        card.add_section("🚪 離開通知", leave_status, inline=True)

        autorole_status = (
            f"`開啟` (身分組: <@&{s.autorole_id}>)"
            if (s.autorole_enabled and s.autorole_id)
            else ("`開啟 (未指定身分組)`" if s.autorole_enabled else "`已停用`")
        )
        card.add_section("🎖️ 自動身分組", autorole_status, inline=True)

        card.add_section("📜 稽核日誌頻道", f"<#{s.log_channel_id}>" if s.log_channel_id else "`未設定`", inline=True)
        card.add_section("🧠 AI 專屬頻道", f"<#{s.ai_channel_id}>" if s.ai_channel_id else "`未限制頻道`", inline=True)

        eq_status = (
            f"<#{s.earthquake_channel_id}> (規模 ≥ {s.earthquake_min_magnitude}, 震度 ≥ {s.earthquake_min_intensity}級, {'啟用' if s.earthquake_enabled else '已暫停'})"
            if s.earthquake_channel_id
            else "`未設定`"
        )
        card.add_section("🌋 地震即時推播", eq_status, inline=True)

        weather_status = (
            f"<#{s.weather_channel_id}> (觀測地區: {s.weather_county or '臺北市'})"
            if s.weather_channel_id
            else "`未設定`"
        )
        card.add_section("🌤️ 天氣即時推播", weather_status, inline=True)

        card.add_section("⏰ 伺服器時區", f"`{s.timezone or 'Asia/Taipei'}`", inline=True)
        card.add_section("📊 AI 每日額度", f"`{s.ai_daily_limit or 80} 次 / 人`", inline=True)

        # Show message preview snippet if configured
        if s.welcome_message:
            w_preview = s.welcome_message if len(s.welcome_message) <= 80 else s.welcome_message[:77] + "..."
            card.add_section("📝 自訂歡迎詞樣板", f"```{w_preview}```", inline=False)
        if s.leave_message:
            l_preview = s.leave_message if len(s.leave_message) <= 80 else s.leave_message[:77] + "..."
            card.add_section("📝 自訂離退詞樣板", f"```{l_preview}```", inline=False)

        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="歡迎訊息", description="設定新成員加入時的歡迎訊息內容")
    @app_commands.describe(內容="歡迎詞內容 (支援變數：{user}, {member}, {server}, {count}, {member_count})")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def welcome_set_command(self, interaction: discord.Interaction, 內容: str) -> None:
        if not interaction.guild_id or not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        msg_content = 內容.strip()
        if not msg_content:
            await InteractionResponder.safe_send(interaction, "❌ 歡迎詞內容不可為空。", ephemeral=True)
            return
        if len(msg_content) > 1000:
            await InteractionResponder.safe_send(interaction, "❌ 歡迎詞長度請限制在 1000 字元以內。", ephemeral=True)
            return

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.welcome_enabled = True
            s.welcome_message = msg_content

        member_count_str = str(interaction.guild.member_count or 1)
        preview = (
            msg_content.replace("{user}", interaction.user.mention)
            .replace("{member}", interaction.user.display_name)
            .replace("{server}", interaction.guild.name)
            .replace("{count}", member_count_str)
            .replace("{member_count}", member_count_str)
        )
        card = ZNCard(
            title="歡迎訊息設定完成",
            description=(
                f"**原始樣板**：\n`{msg_content}`\n\n"
                f"**動態預覽效果**：\n{preview}\n\n"
                f"-# 💡 支援變數：`{{user}}` 成員提及、`{{member}}` 成員暱稱、`{{server}}` 伺服器名稱、`{{count}}` 伺服器總人數"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="歡迎頻道", description="指定歡迎訊息發送頻道")
    @app_commands.describe(頻道="指定用於發送歡迎卡片的文字頻道")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def welcome_channel_command(self, interaction: discord.Interaction, 頻道: discord.TextChannel) -> None:
        if not interaction.guild_id or not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        has_perm, missing = check_bot_channel_permissions(頻道, bot_member)
        warning_note = ""
        if not has_perm:
            warning_note = f"\n\n⚠️ **權限提醒**：ZeroNexus 在 {頻道.mention} 缺少 `{', '.join(missing)}` 權限，請確認頻道身分組設定，否則歡迎卡片將無法順利發布。"

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.welcome_enabled = True
            s.welcome_channel_id = 頻道.id

        card = ZNCard(
            title="歡迎頻道已設定",
            description=f"新進成員歡迎訊息將發送至 {頻道.mention}。{warning_note}",
            status_pill=ZNStatusPill.SUCCESS if has_perm else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if has_perm else ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="歡迎關閉", description="停用新成員加入歡迎廣播")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def welcome_disable_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.welcome_enabled = False

        card = ZNCard(title="歡迎訊息已停用", description="新進成員加入時將不再發布歡迎廣播通知。", status_pill=ZNStatusPill.DARK, color=ZNColor.DARK)
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="離開訊息", description="設定成員離退告別通知詞")
    @app_commands.describe(內容="告別通知內容 (支援變數：{user}, {member}, {server}, {count}, {member_count})")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def leave_set_command(self, interaction: discord.Interaction, 內容: str) -> None:
        if not interaction.guild_id or not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        msg_content = 內容.strip()
        if not msg_content:
            await InteractionResponder.safe_send(interaction, "❌ 離退詞內容不可為空。", ephemeral=True)
            return
        if len(msg_content) > 1000:
            await InteractionResponder.safe_send(interaction, "❌ 離退詞長度請限制在 1000 字元以內。", ephemeral=True)
            return

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.leave_enabled = True
            s.leave_message = msg_content

        member_count_str = str(interaction.guild.member_count or 0)
        preview = (
            msg_content.replace("{user}", interaction.user.display_name)
            .replace("{member}", interaction.user.display_name)
            .replace("{server}", interaction.guild.name)
            .replace("{count}", member_count_str)
            .replace("{member_count}", member_count_str)
        )
        card = ZNCard(
            title="離退訊息設定完成",
            description=(
                f"**原始樣板**：\n`{msg_content}`\n\n"
                f"**動態預覽效果**：\n{preview}\n\n"
                f"-# 💡 支援變數：`{{user}}` 成員名稱、`{{member}}` 成員暱稱、`{{server}}` 伺服器名稱、`{{count}}` 伺服器剩餘人數"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="離開頻道", description="指定離退廣播頻道")
    @app_commands.describe(頻道="指定用於發送成員離退通知的文字頻道")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def leave_channel_command(self, interaction: discord.Interaction, 頻道: discord.TextChannel) -> None:
        if not interaction.guild_id or not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        has_perm, missing = check_bot_channel_permissions(頻道, bot_member)
        warning_note = ""
        if not has_perm:
            warning_note = f"\n\n⚠️ **權限提醒**：ZeroNexus 在 {頻道.mention} 缺少 `{', '.join(missing)}` 權限，請確認頻道身分組設定，否則離退通知將無法順利發送。"

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.leave_enabled = True
            s.leave_channel_id = 頻道.id

        card = ZNCard(
            title="離退通知頻道已設定",
            description=f"成員離開伺服器通知將發送至 {頻道.mention}。{warning_note}",
            status_pill=ZNStatusPill.SUCCESS if has_perm else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if has_perm else ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="離開關閉", description="停用成員離退廣播")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def leave_disable_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.leave_enabled = False

        card = ZNCard(title="離退通知已停用", description="成員離退伺服器時將不再發布廣播通知。", status_pill=ZNStatusPill.DARK, color=ZNColor.DARK)
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="自動身分組", description="設定新成員加入時自動授予之身分組")
    @app_commands.describe(身分組="新成員入群時自動派發的目標身分組")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def autorole_set_command(self, interaction: discord.Interaction, 身分組: discord.Role) -> None:
        if not interaction.guild_id or not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member:
            await InteractionResponder.safe_send(interaction, "❌ 無法取得機器人成員資訊。", ephemeral=True)
            return

        if not bot_member.guild_permissions.manage_roles:
            await InteractionResponder.safe_send(
                interaction,
                "❌ ZeroNexus 缺少伺服器「管理身分組 (Manage Roles)」權限，無法自動派發身分組。",
                ephemeral=True,
            )
            return

        if 身分組.is_default():
            await InteractionResponder.safe_send(interaction, "❌ 無法將 @everyone 預設身分組設為自動派發身分組。", ephemeral=True)
            return

        if getattr(身分組, "managed", False):
            await InteractionResponder.safe_send(interaction, "❌ 受管身分組（如整合機器人身分組）由 Discord 系統管理，無法被自動指派。", ephemeral=True)
            return

        if getattr(身分組, "is_premium_subscriber", lambda: False)():
            await InteractionResponder.safe_send(interaction, "❌ 伺服器加強 (Nitro Booster) 身分組由 Discord 系統專屬管理，無法手動指派。", ephemeral=True)
            return

        if 身分組 >= bot_member.top_role:
            await InteractionResponder.safe_send(
                interaction,
                f"❌ 身分組順位衝突：{身分組.mention} 的層級高於或等於 ZeroNexus 的最高身分組 ({bot_member.top_role.mention})。請在伺服器身分組設定中將 ZeroNexus 的身分組拖曳至該身分組之上。",
                ephemeral=True,
            )
            return

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.autorole_enabled = True
            s.autorole_id = 身分組.id

        card = ZNCard(
            title="自動身分組已設定完成",
            description=f"新進成員加入本伺服器時，系統將自動派發身分組 {身分組.mention}。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="自動身分組關閉", description="停用新成員自動派發身分組功能")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def autorole_disable_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.autorole_enabled = False

        card = ZNCard(title="自動身分組已關閉", description="新進成員加入時將不再自動派發身分組。", status_pill=ZNStatusPill.DARK, color=ZNColor.DARK)
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="日誌頻道", description="指定伺服器安全與稽核日誌專用頻道")
    @app_commands.describe(頻道="指定用於記錄伺服器異動與管理事件的文字頻道")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def log_channel_command(self, interaction: discord.Interaction, 頻道: discord.TextChannel) -> None:
        if not interaction.guild_id or not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        has_perm, missing = check_bot_channel_permissions(頻道, bot_member)
        warning_note = ""
        if not has_perm:
            warning_note = f"\n\n⚠️ **權限提醒**：ZeroNexus 在 {頻道.mention} 缺少 `{', '.join(missing)}` 權限，請確認頻道身分組設定，否則安全日誌將無法正常發送。"

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.log_channel_id = 頻道.id

        card = ZNCard(
            title="稽核日誌頻道已綁定",
            description=f"管理與安全事件將自動記錄於 {頻道.mention}。{warning_note}",
            status_pill=ZNStatusPill.SUCCESS if has_perm else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if has_perm else ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="日誌設定", description="配置需被監控並紀錄的事件類型")
    @app_commands.describe(事件類型="選擇伺服器安全日誌監控模式")
    @app_commands.choices(事件類型=[
        app_commands.Choice(name="全開 (訊息異動、成員進出、管理處置)", value="all"),
        app_commands.Choice(name="僅記錄管理處置 (封鎖、踢出、禁言、警告)", value="moderation_only"),
        app_commands.Choice(name="關閉 (停用日誌事件記錄)", value="off"),
    ])
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def log_events_command(self, interaction: discord.Interaction, 事件類型: str) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if 事件類型 == "all":
            mask = 0b1111
            desc = "已啟用**完整監控**（涵蓋訊息刪除與修改、成員進出、管理懲處事件）。"
        elif 事件類型 == "moderation_only":
            mask = 0b0001
            desc = "已啟用**管理處置監控**（僅記錄封鎖、踢出、禁言與警告等懲處事件）。"
        else:
            mask = 0
            desc = "已**關閉**日誌事件記錄。"

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.log_events_mask = mask

        card = ZNCard(title="日誌監控設定已更新", description=desc, status_pill=ZNStatusPill.SUCCESS, color=ZNColor.SUCCESS)
        await InteractionResponder.safe_send(interaction, card=card)

    async def _handle_timezone_set(self, interaction: discord.Interaction, 時區: str) -> None:
        """Core logic for timezone setting."""
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        clean_tz = 時區.strip()
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(clean_tz)
        except Exception:
            await InteractionResponder.safe_send(
                interaction,
                f"❌ 無效的 IANA 時區名稱「{時區}」。建議使用選項選單或填入如：`Asia/Taipei`、`Asia/Tokyo`、`UTC`。",
                ephemeral=True,
            )
            return

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.timezone = clean_tz

        card = ZNCard(
            title="時區設定已更新",
            description=f"伺服器標準時區已切換為 `{clean_tz}`，所有定時任務與時間標記將依此基準呈現。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="時區", description="自訂伺服器標準時區 (預設 Asia/Taipei)")
    @app_commands.describe(時區="IANA 時區識別碼 (例如 Asia/Taipei, Asia/Tokyo, UTC)")
    @app_commands.autocomplete(時區=timezone_autocomplete)
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def timezone_command(self, interaction: discord.Interaction, 時區: str = "Asia/Taipei") -> None:
        await self._handle_timezone_set(interaction, 時區)

    @settings_group.command(name="時區設定", description="自訂伺服器標準時區 (相容別名)")
    @app_commands.describe(時區="IANA 時區識別碼 (例如 Asia/Taipei, Asia/Tokyo, UTC)")
    @app_commands.autocomplete(時區=timezone_autocomplete)
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def timezone_set_command(self, interaction: discord.Interaction, 時區: str = "Asia/Taipei") -> None:
        await self._handle_timezone_set(interaction, 時區)

    @settings_group.command(name="ai每日上限", description="設定伺服器每人每日 AI 免費對話配額")
    @app_commands.describe(上限次數="每日對話次數上限 (範圍 10~500)")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def ai_limit_command(self, interaction: discord.Interaction, 上限次數: int = 80) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        val = max(10, min(500, 上限次數))
        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.ai_daily_limit = val

        card = ZNCard(
            title="AI 每日配額已設定",
            description=f"全伺服器每位成員每日免費用量上限調整為 **{val} 次**。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    async def _handle_earthquake_set(
        self,
        interaction: discord.Interaction,
        頻道: Optional[discord.TextChannel] = None,
        最低規模: Optional[float] = None,
        最低震度: Optional[int] = None,
        啟用狀態: Optional[bool] = None,
    ) -> None:
        """Core logic for earthquake notification settings."""
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if 最低規模 is not None and not (0.0 <= 最低規模 <= 10.0):
            await InteractionResponder.safe_send(interaction, "❌ 最低地震規模必須介於 0.0 至 10.0 之間。", ephemeral=True)
            return
        if 最低震度 is not None and not (1 <= 最低震度 <= 7):
            await InteractionResponder.safe_send(interaction, "❌ 最低全台最大震度必須介於 1 至 7 級之間。", ephemeral=True)
            return

        bot_member = interaction.guild.me if interaction.guild else None
        warning_note = ""
        if 頻道 is not None:
            has_perm, missing = check_bot_channel_permissions(頻道, bot_member)
            if not has_perm:
                warning_note = f"\n\n⚠️ **權限提醒**：ZeroNexus 在 {頻道.mention} 缺少 `{', '.join(missing)}` 權限，可能影響速報卡片發送。"

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            if 頻道 is not None:
                s.earthquake_channel_id = 頻道.id
                if 啟用狀態 is None:
                    s.earthquake_enabled = True
            if 最低規模 is not None:
                s.earthquake_min_magnitude = round(最低規模, 1)
            if 最低震度 is not None:
                s.earthquake_min_intensity = 最低震度
            if 啟用狀態 is not None:
                s.earthquake_enabled = 啟用狀態

            ch_id = s.earthquake_channel_id
            is_enabled = s.earthquake_enabled
            min_mag = s.earthquake_min_magnitude
            min_int = s.earthquake_min_intensity

        if not ch_id:
            desc = "未指定推播頻道。請提供 `頻道` 參數以啟用中央氣象署地震即時廣播。"
            st = ZNStatusPill.WARNING
            col = ZNColor.WARNING
        elif not is_enabled:
            desc = f"已停用地震廣播（推播目標頻道保留為 <#{ch_id}>）。"
            st = ZNStatusPill.WARNING
            col = ZNColor.WARNING
        else:
            desc = (
                f"✅ **地震即時廣播已啟用**\n\n"
                f"- **推播頻道**：<#{ch_id}>\n"
                f"- **最低規模門檻**：`M ≥ {min_mag}`\n"
                f"- **最低最大震度**：`≥ {min_int} 級`\n"
                f"- **推播資料源**：中央氣象署 (CWA) 官方顯著有感地震速報，資料庫精準去重、零 AI 配額消耗。{warning_note}"
            )
            st = ZNStatusPill.SUCCESS
            col = ZNColor.SUCCESS

        card = ZNCard(title="🌋 地震即時推播設定已更新", description=desc, status_pill=st, color=col)
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="地震通報頻道", description="指定中央氣象署 (CWA) 顯著有感地震推播頻道與門檻")
    @app_commands.describe(
        頻道="推播文字頻道 (留空代表維持目前設定)",
        最低規模="通知之最低地震規模門檻 (預設 4.0，範圍 0.0~10.0)",
        最低震度="通知之全台最大震度門檻 (預設 1 級，範圍 1~7 級)",
        啟用狀態="是否啟用地震推播通知 (True 為啟用，False 為關閉)",
    )
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def earthquake_channel_command(
        self,
        interaction: discord.Interaction,
        頻道: Optional[discord.TextChannel] = None,
        最低規模: Optional[float] = None,
        最低震度: Optional[int] = None,
        啟用狀態: Optional[bool] = None,
    ) -> None:
        await self._handle_earthquake_set(interaction, 頻道, 最低規模, 最低震度, 啟用狀態)

    @settings_group.command(name="地震通知設定", description="指定中央氣象署 (CWA) 顯著有感地震推播頻道 (相容別名)")
    @app_commands.describe(
        頻道="推播文字頻道 (留空代表維持目前設定)",
        最低規模="通知之最低地震規模門檻 (預設 4.0，範圍 0.0~10.0)",
        最低震度="通知之全台最大震度門檻 (預設 1 級，範圍 1~7 級)",
        啟用狀態="是否啟用地震推播通知 (True 為啟用，False 為關閉)",
    )
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def earthquake_notify_command(
        self,
        interaction: discord.Interaction,
        頻道: Optional[discord.TextChannel] = None,
        最低規模: Optional[float] = None,
        最低震度: Optional[int] = None,
        啟用狀態: Optional[bool] = None,
    ) -> None:
        await self._handle_earthquake_set(interaction, 頻道, 最低規模, 最低震度, 啟用狀態)

    @settings_group.command(name="天氣通知設定", description="指定中央氣象署即時天氣推播頻道與目標縣市")
    @app_commands.describe(頻道="推播文字頻道 (留空代表停用)", 縣市="目標推播縣市 (預設為臺北市，例如：新北市、臺中市、高雄市)")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def weather_notify_command(
        self,
        interaction: discord.Interaction,
        頻道: Optional[discord.TextChannel] = None,
        縣市: Optional[str] = "臺北市",
    ) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        target_county = (縣市 or "臺北市").strip()
        from zeronexus.engines.cwa_client import cwa_client
        norm_county = cwa_client.normalize_county_name(target_county) or "臺北市"

        async with db.session() as session:
            s = await self._get_or_create_settings(session, interaction.guild_id)
            s.weather_channel_id = 頻道.id if 頻道 else None
            s.weather_county = norm_county

        desc = f"中央氣象署【{norm_county}】天氣預報與即時更新將自動推播至 {頻道.mention}。" if 頻道 else "已停用天氣即時廣播推播通知。"
        card = ZNCard(title="天氣推播設定已更新", description=desc, status_pill=ZNStatusPill.SUCCESS, color=ZNColor.SUCCESS)
        await InteractionResponder.safe_send(interaction, card=card)

    @settings_group.command(name="重設", description="重設伺服器所有設定為出廠預設值 (需二次確認)")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def reset_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        view = ZNConfirmView(author_id=interaction.user.id, confirm_label="確認完全重設", is_dangerous=True)
        embed = discord.Embed(
            title="⚠️ 確認重設伺服器設定",
            description="您確定要將 **所有自訂配置**（歡迎詞、離退通知、日誌、自動身分組、地震通報、天氣、時區與 AI 配額）恢復為出廠預設值嗎？\n此動作不可復原！",
            color=ZNColor.ERROR,
        )
        embed.set_footer(text=ZNTheme.standard_footer())
        await InteractionResponder.safe_send(interaction, embed=embed, view=view, ephemeral=True)

        await view.wait()
        if view.confirmed:
            async with db.session() as session:
                s = await self._get_or_create_settings(session, interaction.guild_id)
                s.welcome_enabled = False
                s.welcome_channel_id = None
                s.welcome_message = None
                s.leave_enabled = False
                s.leave_channel_id = None
                s.leave_message = None
                s.autorole_enabled = False
                s.autorole_id = None
                s.log_channel_id = None
                s.log_events_mask = 0
                s.ai_channel_id = None
                s.ai_model = None
                s.ai_daily_limit = 80
                s.earthquake_channel_id = None
                s.earthquake_enabled = False
                s.earthquake_min_magnitude = 4.0
                s.earthquake_min_intensity = 1
                s.weather_channel_id = None
                s.weather_county = "臺北市"
                s.timezone = "Asia/Taipei"

            card = ZNCard(
                title="伺服器設定已恢復出廠預設值",
                description="全伺服器所有自動化廣播、頻道綁定與時區設定已全數安全重置為初始狀態。",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @settings_group.command(name="備份設定", description="將伺服器配置匯出為 JSON 結構檔案")
    @command_guard("settings", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def export_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        s = await self._fetch_or_create_settings(interaction.guild_id)
        data = {
            "guild_id": s.guild_id,
            "prefix": s.prefix,
            "timezone": s.timezone,
            "welcome": {"enabled": s.welcome_enabled, "channel": s.welcome_channel_id, "msg": s.welcome_message},
            "leave": {"enabled": s.leave_enabled, "channel": s.leave_channel_id, "msg": s.leave_message},
            "autorole": {"enabled": s.autorole_enabled, "role": s.autorole_id},
            "ai": {"channel": s.ai_channel_id, "daily_limit": s.ai_daily_limit, "model": s.ai_model},
            "notifications": {
                "earthquake_channel": s.earthquake_channel_id,
                "earthquake_enabled": s.earthquake_enabled,
                "earthquake_min_magnitude": s.earthquake_min_magnitude,
                "earthquake_min_intensity": s.earthquake_min_intensity,
                "weather_channel": s.weather_channel_id,
                "weather_county": s.weather_county,
            },
        }
        card = ZNCard(
            title="伺服器配置匯出 JSON",
            description=f"```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
