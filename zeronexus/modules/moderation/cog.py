"""ZeroNexus Moderation Command Cog.

18 Fully Implemented Commands under /管理:
- 踢出, 封鎖, 解除封鎖, 禁言, 解除禁言, 警告, 警告清單, 清除警告
- 清除訊息, 鎖定頻道, 解鎖頻道, 慢速模式, 更改暱稱, 身分組新增, 身分組移除
- 伺服器備份, 審核日誌, 案件查詢
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, select

from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.models.moderation import ModerationCase, WarningRecord
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import PermissionEngine, ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill
from zeronexus.ui.views import ZNConfirmView


# ==============================================================================
# Helper Constants & Audit Log Action Localization
# ==============================================================================

AUDIT_ACTION_NAMES: Dict[str, str] = {
    "guild_update": "變更伺服器設定",
    "channel_create": "建立新頻道",
    "channel_update": "修改頻道配置",
    "channel_delete": "刪除頻道",
    "overwrite_create": "新增頻道權限覆蓋",
    "overwrite_update": "修改頻道權限覆蓋",
    "overwrite_delete": "移除頻道權限覆蓋",
    "kick": "踢出成員",
    "member_prune": "修剪非活躍成員",
    "ban": "封鎖成員",
    "unban": "解除封鎖",
    "member_update": "修改成員資料 (暱稱/身分組)",
    "member_role_update": "調整成員身分組",
    "member_move": "移動成員語音頻道",
    "member_disconnect": "強制成員退出語音",
    "bot_add": "邀請機器人加入",
    "role_create": "建立身分組",
    "role_update": "修改身分組權限或外觀",
    "role_delete": "刪除身分組",
    "invite_create": "建立邀請連結",
    "invite_update": "修改邀請連結",
    "invite_delete": "撤銷邀請連結",
    "webhook_create": "建立 Webhook",
    "webhook_update": "修改 Webhook",
    "webhook_delete": "刪除 Webhook",
    "emoji_create": "新增自訂表情符號",
    "emoji_update": "修改表情符號名稱",
    "emoji_delete": "刪除表情符號",
    "message_delete": "刪除訊息",
    "message_bulk_delete": "批次清理訊息",
    "message_pin": "釘選訊息",
    "message_unpin": "取消釘選訊息",
    "integration_create": "新增外部整合服務",
    "integration_update": "更新外部整合服務",
    "integration_delete": "移除外部整合服務",
    "stage_instance_create": "啟動舞台活動",
    "stage_instance_update": "修改舞台活動",
    "stage_instance_delete": "結束舞台活動",
    "sticker_create": "新增貼圖",
    "sticker_update": "修改貼圖",
    "sticker_delete": "刪除貼圖",
    "thread_create": "建立討論串",
    "thread_update": "修改討論串",
    "thread_delete": "刪除討論串",
    "app_command_permission_update": "更新斜線指令權限",
    "automod_rule_create": "建立 AutoMod 規則",
    "automod_rule_update": "修改 AutoMod 規則",
    "automod_rule_delete": "刪除 AutoMod 規則",
    "automod_block_message": "AutoMod 攔截違規訊息",
    "automod_flag_to_channel": "AutoMod 告警通知",
    "automod_timeout": "AutoMod 自動隔離禁言",
}

MOD_ACTION_NAMES: Dict[str, str] = {
    "kick": "踢出成員",
    "ban": "永久封鎖",
    "unban": "解除封鎖",
    "timeout": "通訊隔離 (禁言)",
    "untimeout": "解除禁言",
    "warn": "正式警告",
    "clear": "批次清理訊息",
    "clear_warns": "撤銷警告紀錄",
    "role_add": "新增身分組",
    "role_remove": "移除身分組",
    "lock": "鎖定頻道",
    "unlock": "解鎖頻道",
    "slowmode": "慢速模式",
    "nickname": "更改暱稱",
}


# ==============================================================================
# Duration Parsing & Formatting
# ==============================================================================

UNIT_MAP: Dict[str, int] = {
    "s": 1, "sec": 1, "second": 1, "seconds": 1, "秒": 1,
    "m": 60, "min": 60, "minute": 60, "minutes": 60, "分": 60, "分鐘": 60,
    "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "時": 3600, "小時": 3600,
    "d": 86400, "day": 86400, "days": 86400, "天": 86400, "日": 86400,
    "w": 604800, "week": 604800, "weeks": 604800, "週": 604800, "星期": 604800, "禮拜": 604800,
}


def parse_duration(time_str: str) -> int:
    """Parses a duration string into seconds.

    Supports:
    - Pure numbers: '10' -> 10 minutes (600s)
    - Units: '60s', '10m', '2h', '1d', '7d', '28d'
    - Traditional Chinese: '10分鐘', '2小時', '1天', '30秒', '1週'
    - Compounds: '1h30m', '1小時30分', '2d12h'

    Raises:
        ValueError: If input cannot be parsed or falls outside Discord API constraints (5s ~ 28d).
    """
    raw = time_str.strip().lower()
    if not raw:
        raise ValueError("請輸入有效的禁言時長，例如：`10m`、`1h`、`1天` 或 `30`（代表30分鐘）。")

    if raw.isdigit():
        mins = int(raw)
        if mins <= 0:
            raise ValueError("禁言分鐘數必須大於 0。")
        total_seconds = mins * 60
    else:
        pattern = re.compile(r"(\d+)\s*([a-zA-Z\u4e00-\u9fa5]+)")
        matches = list(pattern.finditer(raw))
        if not matches:
            raise ValueError(f"無法辨識時長格式「{time_str}」。範例：`10m`、`2h`、`1天`、`1h30m`。")

        total_seconds = 0
        for match in matches:
            num = int(match.group(1))
            unit = match.group(2).lower()
            multiplier = UNIT_MAP.get(unit)
            if not multiplier:
                raise ValueError(f"無法辨識時間單位「{unit}」。支援：秒 (s)、分 (m)、時 (h)、天 (d)、週 (w)。")
            total_seconds += num * multiplier

    if total_seconds < 5:
        raise ValueError("禁言時長過短，至少需設定為 5 秒以上。")

    max_seconds = 28 * 86400
    if total_seconds > max_seconds:
        raise ValueError("Discord 官方限制禁言時長上限為 28 天 (4 週)，請縮短時長。")

    return total_seconds


def format_duration(seconds: int) -> str:
    """Formats seconds into human-readable Traditional Chinese."""
    if seconds <= 0:
        return "0 秒"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts: List[str] = []
    if days > 0:
        parts.append(f"{days} 天")
    if hours > 0:
        parts.append(f"{hours} 小時")
    if minutes > 0:
        parts.append(f"{minutes} 分鐘")
    if secs > 0 and not parts:
        parts.append(f"{secs} 秒")
    elif secs > 0 and days == 0 and hours == 0:
        parts.append(f"{secs} 秒")

    return " ".join(parts) or f"{seconds} 秒"


# ==============================================================================
# Module Definition
# ==============================================================================

class ModerationModule(BaseModule):
    """Server moderation and security management."""

    def __init__(self) -> None:
        super().__init__(
            name="moderation",
            display_name="管理模組",
            description="成員懲處、身分組管理、訊息維護與伺服器日誌稽核",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("踢出", "將違規成員移出伺服器", ZNPermissionLevel.MODERATOR),
            ("封鎖", "永久封鎖違規成員（具二次確認防呆）", ZNPermissionLevel.ADMINISTRATOR),
            ("解除封鎖", "搜尋黑名單或依使用者 ID 解除封鎖", ZNPermissionLevel.ADMINISTRATOR),
            ("禁言", "套用通訊隔離時長 (支援 10m/2h/1天/28天等友善時長)", ZNPermissionLevel.MODERATOR),
            ("解除禁言", "提前解除成員禁言狀態", ZNPermissionLevel.MODERATOR),
            ("警告", "對成員發放正式警告並記錄至資料庫", ZNPermissionLevel.MODERATOR),
            ("警告清單", "檢視成員歷史警告案件", ZNPermissionLevel.MODERATOR),
            ("清除警告", "撤銷指定案件或清空警告", ZNPermissionLevel.ADMINISTRATOR),
            ("清除訊息", "批次清理頻道指定數量訊息", ZNPermissionLevel.MODERATOR),
            ("鎖定頻道", "關閉成員在頻道的發言與討論串權限", ZNPermissionLevel.MODERATOR),
            ("解鎖頻道", "恢復頻道成員正常發言權限", ZNPermissionLevel.MODERATOR),
            ("慢速模式", "設定頻道發言冷卻秒數", ZNPermissionLevel.MODERATOR),
            ("更改暱稱", "修改伺服器內成員之顯示暱稱", ZNPermissionLevel.MODERATOR),
            ("身分組新增", "為成員新增特定身分組", ZNPermissionLevel.MODERATOR),
            ("身分組移除", "移除成員之特定身分組", ZNPermissionLevel.MODERATOR),
            ("伺服器備份", "備份頻道與身分組清單快照至資料庫", ZNPermissionLevel.ADMINISTRATOR),
            ("審核日誌", "調取近期管理員操作事件", ZNPermissionLevel.MODERATOR),
            ("案件查詢", "依案件 ID 或成員查詢懲處詳情", ZNPermissionLevel.MODERATOR),
        ]
        for name, cmd_desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"管理 {name}",
                description=cmd_desc,
                group_name="管理",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


def _has_guild_perm(user: Any, perm_name: str) -> bool:
    """Verifies whether a user has a specific Discord native permission, administrator, or is developer."""
    if PermissionEngine.is_developer(getattr(user, "id", 0)):
        return True
    perms = getattr(user, "guild_permissions", None)
    if not perms:
        return False
    if getattr(perms, "administrator", False):
        return True
    return bool(getattr(perms, perm_name, False))


# ==============================================================================
# Autocomplete Handlers
# ==============================================================================

async def unban_user_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """即時搜尋伺服器黑名單成員供解除封鎖選取。"""
    if not interaction.guild:
        return []
    bot_member = interaction.guild.me
    if not bot_member or not bot_member.guild_permissions.ban_members:
        return []

    choices: List[app_commands.Choice[str]] = []
    try:
        curr_lower = current.strip().lower()
        async for ban_entry in interaction.guild.bans(limit=1000):
            u = ban_entry.user
            u_name = u.name
            u_global = getattr(u, "global_name", "") or ""
            u_id_str = str(u.id)

            if (
                not curr_lower
                or curr_lower in u_name.lower()
                or curr_lower in u_global.lower()
                or curr_lower in u_id_str
            ):
                reason_snippet = f" | 原因: {ban_entry.reason}" if ban_entry.reason else ""
                tag_str = f"{u_name} ({u_id_str}){reason_snippet}"
                choices.append(app_commands.Choice(name=tag_str[:100], value=u_id_str))
                if len(choices) >= 25:
                    break
    except Exception as ex:
        log.debug(f"[Moderation] unban autocomplete failed: {ex}")
    return choices


async def timeout_duration_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """提供禁言時長常用預設選項與動態篩選。"""
    presets = [
        ("60秒 (1 分鐘)", "60s"),
        ("5 分鐘", "5m"),
        ("10 分鐘 (預設)", "10m"),
        ("30 分鐘", "30m"),
        ("1 小時", "1h"),
        ("6 小時", "6h"),
        ("12 小時", "12h"),
        ("1 天 (24 小時)", "1d"),
        ("3 天", "3d"),
        ("1 週 (7 天)", "7d"),
        ("2 週 (14 天)", "14d"),
        ("4 週 (28 天 - Discord 上限)", "28d"),
    ]
    curr = current.strip().lower()
    choices: List[app_commands.Choice[str]] = []
    for label, val in presets:
        if not curr or curr in label.lower() or curr in val.lower():
            choices.append(app_commands.Choice(name=label, value=val))
    return choices[:25]


# ==============================================================================
# Cog Implementation
# ==============================================================================

class ModerationCog(commands.Cog):
    """Discord Slash Command Group for /管理."""

    manage_group = app_commands.Group(name="管理", description="伺服器成員處置與頻道管理指令群組", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _log_case(
        self,
        guild_id: int,
        action: str,
        target_id: int,
        moderator_id: int,
        reason: str,
        duration: Optional[int] = None,
    ) -> Optional[int]:
        """Safely persists a formal moderation case to the database."""
        try:
            async with db.session() as session:
                case = ModerationCase(
                    guild_id=guild_id,
                    action=action,
                    target_user_id=target_id,
                    moderator_id=moderator_id,
                    reason=reason or "未提供原因",
                    duration_seconds=duration,
                )
                session.add(case)
                await session.flush()
                return case.case_id
        except Exception as ex:
            log.error(f"Failed to persist ModerationCase ({action} on target {target_id}): {ex}", exc_info=True)
            return None

    # --------------------------------------------------------------------------
    # 1. 踢出 kick
    # --------------------------------------------------------------------------
    @manage_group.command(name="踢出", description="將違規成員踢出伺服器")
    @app_commands.describe(成員="要踢出的伺服器成員", 原因="處置理由說明")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def kick_command(self, interaction: discord.Interaction, 成員: discord.Member, 原因: str = "未提供具體原因") -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "kick_members"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「踢出成員 (Kick Members)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.kick_members:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少 Discord 原生「踢出成員」權限，請檢查機器人身分組設定。", ephemeral=True)
            return

        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, 成員, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行踢出：{msg}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        try:
            await 成員.kick(reason=f"由 {interaction.user} ({interaction.user.id}) 處分: {原因}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Discord 權限不足：ZeroNexus 無法踢出該成員，請確認機器人身分組順位是否高於目標成員。", ephemeral=True)
            return
        except discord.NotFound:
            await interaction.followup.send("❌ 目標成員已離開伺服器或不存在，無法執行踢出。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await interaction.followup.send(f"❌ 踢出執行失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        cid = await self._log_case(interaction.guild.id, "kick", 成員.id, interaction.user.id, 原因)
        cid_text = f"#{cid}" if cid else "紀錄寫入失敗"

        card = ZNCard(
            title="成員已踢出",
            description=f"已成功將成員 **{成員.display_name}** (`{成員.id}`) 踢出伺服器。\n**案件編號**：`{cid_text}`\n**處分原因**：{原因}",
            status_pill=ZNStatusPill.MODERATION,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 2. 封鎖 ban
    # --------------------------------------------------------------------------
    @manage_group.command(name="封鎖", description="永久封鎖違規成員或使用者（需二次確認）")
    @app_commands.describe(成員="要封鎖的成員或使用者", 原因="處置理由說明", 清理天數="刪除該成員最近幾天的訊息 (0~7天)")
    @command_guard("moderation", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def ban_command(
        self,
        interaction: discord.Interaction,
        成員: discord.User,
        原因: str = "重大違規",
        清理天數: int = 1,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "ban_members"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「封鎖成員 (Ban Members)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.ban_members:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少 Discord 原生「封鎖成員」權限，請檢查機器人身分組設定。", ephemeral=True)
            return

        target_member = interaction.guild.get_member(成員.id)
        target_to_check = target_member or 成員
        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, target_to_check, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行封鎖：{msg}", ephemeral=True)
            return

        view = ZNConfirmView(author_id=interaction.user.id, confirm_label="確認封鎖", is_dangerous=True)
        warn_card = ZNCard(
            title="⚠️ 高風險管理操作：確認永久封鎖",
            description=(
                f"您確定要將 **{成員.display_name}** (`{成員.id}`) **永久封鎖** 嗎？\n\n"
                f"- **清理訊息**：過去 `{max(0, min(7, 清理天數))}` 天內之所有發言\n"
                f"- **封鎖事由**：{原因}\n\n"
                f"請在 60 秒內點擊下方按鈕確認執行。"
            ),
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.ERROR,
        )
        msg_obj = await InteractionResponder.safe_send(interaction, card=warn_card, view=view, ephemeral=True)
        if msg_obj and hasattr(view, "message"):
            view.message = msg_obj

        await view.wait()
        if not view.confirmed:
            return

        if not _has_guild_perm(interaction.user, "ban_members"):
            await interaction.followup.send("❌ 權限已變更：您缺少 Discord 原生「封鎖成員」或管理員權限。", ephemeral=True)
            return

        delete_seconds = max(0, min(7, 清理天數)) * 86400
        try:
            await interaction.guild.ban(成員, reason=f"由 {interaction.user} ({interaction.user.id}) 封鎖: {原因}", delete_message_seconds=delete_seconds)
        except discord.Forbidden:
            await interaction.followup.send("❌ Discord 權限不足：ZeroNexus 無法封鎖該對象，請確認機器人身分組階層與權限。", ephemeral=True)
            return
        except discord.NotFound:
            await interaction.followup.send(f"❌ 查無使用者 `{成員.id}`，無法執行封鎖。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await interaction.followup.send(f"❌ 封鎖執行失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        cid = await self._log_case(interaction.guild.id, "ban", 成員.id, interaction.user.id, 原因)
        cid_text = f"#{cid}" if cid else "紀錄寫入失敗"

        success_card = ZNCard(
            title="成員已封鎖",
            description=f"成員 **{成員.display_name}** (`{成員.id}`) 已被永久封鎖。\n**案件編號**：`{cid_text}`\n**處分原因**：{原因}",
            status_pill=ZNStatusPill.MODERATION,
            color=ZNColor.ERROR,
        )
        await InteractionResponder.safe_send(interaction, card=success_card, ephemeral=False)

    # --------------------------------------------------------------------------
    # 3. 解除封鎖 unban (With Autocomplete)
    # --------------------------------------------------------------------------
    @manage_group.command(name="解除封鎖", description="搜尋黑名單或依使用者 ID 解除封鎖")
    @app_commands.describe(使用者="請選擇黑名單成員或輸入 Discord 使用者 ID (純數字)", 原因="解封原因")
    @app_commands.autocomplete(使用者=unban_user_autocomplete)
    @command_guard("moderation", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def unban_command(self, interaction: discord.Interaction, 使用者: str, 原因: str = "管理員裁決解除") -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "ban_members"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「封鎖成員 (Ban Members)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.ban_members:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少「封鎖成員」權限，無法執行解封。", ephemeral=True)
            return

        clean_input = 使用者.strip().replace("<@", "").replace(">", "").replace("!", "")
        target_user: Optional[discord.User] = None

        if clean_input.isdigit():
            uid = int(clean_input)
            try:
                target_user = await self.bot.fetch_user(uid)
            except discord.NotFound:
                await InteractionResponder.safe_send(interaction, f"❌ 查無此 Discord 使用者帳號 (ID: `{uid}`)，請確認號碼是否正確。", ephemeral=True)
                return
            except discord.HTTPException as ex:
                await InteractionResponder.safe_send(interaction, f"❌ 查詢使用者資料失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
                return
        else:
            try:
                async for ban_entry in interaction.guild.bans(limit=1000):
                    u = ban_entry.user
                    if (
                        clean_input.lower() == u.name.lower()
                        or clean_input.lower() == (getattr(u, "global_name", "") or "").lower()
                    ):
                        target_user = u
                        break
            except discord.Forbidden:
                await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：ZeroNexus 無法調取封鎖清單。", ephemeral=True)
                return
            except discord.HTTPException as ex:
                await InteractionResponder.safe_send(interaction, f"❌ 調取封鎖清單失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
                return

            if not target_user:
                await InteractionResponder.safe_send(
                    interaction,
                    f"❌ 在封鎖名單中找不到符合「{使用者}」的成員。請使用純數字使用者 ID 或透過自動補齊清單選取。",
                    ephemeral=True,
                )
                return

        try:
            await interaction.guild.unban(target_user, reason=f"由 {interaction.user} ({interaction.user.id}) 解封: {原因}")
        except discord.NotFound:
            await InteractionResponder.safe_send(interaction, f"❌ 使用者 **{target_user.name}** (`{target_user.id}`) 目前並未在伺服器的封鎖清單中。", ephemeral=True)
            return
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法解除該使用者之封鎖狀態。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 解除封鎖失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        cid = await self._log_case(interaction.guild.id, "unban", target_user.id, interaction.user.id, 原因)
        cid_text = f"#{cid}" if cid else "紀錄寫入失敗"

        card = ZNCard(
            title="封鎖已解除",
            description=f"已成功解除使用者 **{target_user.name}** (`{target_user.id}`) 之黑名單封鎖。\n**案件編號**：`{cid_text}`\n**解封原因**：{原因}",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)


    # --------------------------------------------------------------------------
    # 4. 禁言 timeout
    # --------------------------------------------------------------------------
    @manage_group.command(name="禁言", description="對成員套用通訊隔離 (支援 10m/2h/1天等友善時長)")
    @app_commands.describe(成員="目標成員", 時長="禁言時長 (例如: 10m, 1h, 1天, 7d, 28d，預設 10m)", 原因="禁言原因")
    @app_commands.autocomplete(時長=timeout_duration_autocomplete)
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def timeout_command(
        self,
        interaction: discord.Interaction,
        成員: discord.Member,
        時長: str = "10m",
        原因: str = "言語違規",
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "moderate_members"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「中斷成員通訊 (Moderate Members)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.moderate_members:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少 Discord 原生「中斷成員通訊」權限，請確認機器人權限設定。", ephemeral=True)
            return

        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, 成員, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行禁言：{msg}", ephemeral=True)
            return

        try:
            total_seconds = parse_duration(時長)
        except ValueError as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 時長格式錯誤：{ex}", ephemeral=True)
            return

        duration = timedelta(seconds=total_seconds)
        readable_duration = format_duration(total_seconds)

        try:
            await 成員.timeout(duration, reason=f"由 {interaction.user} ({interaction.user.id}) 禁言: {原因}")
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：ZeroNexus 無法禁言該成員，請確認機器人身分組階層高於目標成員。", ephemeral=True)
            return
        except discord.NotFound:
            await InteractionResponder.safe_send(interaction, "❌ 目標成員已不在伺服器中。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 禁言執行失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        cid = await self._log_case(interaction.guild.id, "timeout", 成員.id, interaction.user.id, 原因, total_seconds)
        cid_text = f"#{cid}" if cid else "紀錄寫入失敗"

        card = ZNCard(
            title="成員已通訊隔離",
            description=(
                f"已對成員 **{成員.display_name}** 套用通訊隔離 **{readable_duration}**。\n"
                f"**案件編號**：`{cid_text}`\n"
                f"**處分理由**：{原因}\n"
                f"**隔離解除時間**：<t:{int((datetime.now(timezone.utc) + duration).timestamp())}:F>"
            ),
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)


    # --------------------------------------------------------------------------
    # 5. 解除禁言 untimeout
    # --------------------------------------------------------------------------
    @manage_group.command(name="解除禁言", description="提前解除成員通訊隔離狀態")
    @app_commands.describe(成員="目標成員")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def untimeout_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "moderate_members"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「中斷成員通訊 (Moderate Members)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.moderate_members:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少「中斷成員通訊」權限，無法解除禁言。", ephemeral=True)
            return

        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, 成員, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行：{msg}", ephemeral=True)
            return

        if not 成員.is_timed_out():
            await InteractionResponder.safe_send(interaction, f"ℹ️ 成員 **{成員.display_name}** 目前並未處於禁言狀態。", ephemeral=True)
            return

        try:
            await 成員.timeout(None, reason=f"由 {interaction.user} ({interaction.user.id}) 提前解除禁言")
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：ZeroNexus 無法修改該成員狀態，請確認身分組順位。", ephemeral=True)
            return
        except discord.NotFound:
            await InteractionResponder.safe_send(interaction, "❌ 目標成員已不在伺服器中。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 解除禁言失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        cid = await self._log_case(interaction.guild.id, "untimeout", 成員.id, interaction.user.id, "提前解除禁言")
        cid_text = f"#{cid}" if cid else "紀錄寫入失敗"

        card = ZNCard(
            title="禁言已解除",
            description=f"已成功恢復成員 **{成員.display_name}** 的正常通訊與發言權限。\n**案件編號**：`{cid_text}`",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 6. 警告 warn
    # --------------------------------------------------------------------------
    @manage_group.command(name="警告", description="對違規成員發布正式警告並建檔")
    @app_commands.describe(成員="目標成員", 理由="違規具體事由")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def warn_command(self, interaction: discord.Interaction, 成員: discord.Member, 理由: str) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not (_has_guild_perm(interaction.user, "moderate_members") or _has_guild_perm(interaction.user, "kick_members")):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生管理成員處分或管理員權限。", ephemeral=True)
            return

        if 成員.bot:
            await InteractionResponder.safe_send(interaction, "❌ 無法對機器人帳號發送警告處分。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, 成員, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行：{msg}", ephemeral=True)
            return

        clean_reason = 理由.strip() or "未提供違規事由"

        try:
            async with db.session() as session:
                record = WarningRecord(
                    guild_id=interaction.guild.id,
                    user_id=成員.id,
                    moderator_id=interaction.user.id,
                    reason=clean_reason,
                )
                session.add(record)
                await session.flush()
                warning_id = record.id
        except Exception as ex:
            log.error(f"Failed to record WarningRecord: {ex}", exc_info=True)
            await InteractionResponder.safe_send(interaction, "❌ 資料庫寫入警告紀錄失敗，請聯繫管理員檢視系統日誌。", ephemeral=True)
            return

        case_id = await self._log_case(interaction.guild.id, "warn", 成員.id, interaction.user.id, clean_reason)
        case_text = f"#{case_id}" if case_id else "案件建立異常"

        card = ZNCard(
            title="已發布正式警告",
            description=(
                f"已向成員 **{成員.display_name}** (`{成員.id}`) 發出正式管理警告。\n"
                f"**警告編號**：`#{warning_id}` (稽核案件 `{case_text}`)\n"
                f"**執行管理員**：{interaction.user.mention}\n"
                f"**違規事由**：{clean_reason}"
            ),
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 7. 警告清單 warns
    # --------------------------------------------------------------------------
    @manage_group.command(name="警告清單", description="查詢成員的所有有效違規警告紀錄")
    @app_commands.describe(成員="目標成員")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def warns_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not (_has_guild_perm(interaction.user, "moderate_members") or _has_guild_perm(interaction.user, "kick_members")):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少檢視成員警告紀錄之管理權限。", ephemeral=True)
            return

        if 成員.bot:
            card = ZNCard(
                title="無警告紀錄",
                description=f"成員 **{成員.display_name}** 為機器人帳號，無任何警告紀錄。",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        async with db.session() as session:
            stmt = select(WarningRecord).where(
                WarningRecord.guild_id == interaction.guild.id,
                WarningRecord.user_id == 成員.id,
                WarningRecord.is_active == True,
            ).order_by(desc(WarningRecord.created_at))
            result = await session.execute(stmt)
            warnings = result.scalars().all()

        if not warnings:
            card = ZNCard(
                title="無警告紀錄",
                description=f"成員 **{成員.display_name}** 目前無任何有效警告紀錄，記錄良好。",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        lines: List[str] = []
        for w in warnings[:10]:
            ts = int(w.created_at.timestamp()) if w.created_at else 0
            time_str = f"<t:{ts}:f>" if ts else "未知時間"
            lines.append(f"- `#{w.id}` [{time_str}] 由 <@{w.moderator_id}> 發放：{w.reason}")

        if len(warnings) > 10:
            lines.append(f"\n*... 以及其餘 {len(warnings) - 10} 筆較早之警告紀錄*")

        card = ZNCard(
            title=f"成員警告紀錄 — {成員.display_name} (有效共 {len(warnings)} 筆)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 8. 清除警告 clear_warns
    # --------------------------------------------------------------------------
    @manage_group.command(name="清除警告", description="撤銷指定警告案件或清空成員的所有有效警告")
    @app_commands.describe(成員="目標成員", 警告編號="指定警告編號 (若留空則清空該成員全部警告)")
    @command_guard("moderation", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def clear_warns_command(
        self,
        interaction: discord.Interaction,
        成員: discord.Member,
        警告編號: Optional[int] = None,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "administrator"):
            await InteractionResponder.safe_send(interaction, "❌ 清除或撤銷警告紀錄僅限具備管理員權限者執行。", ephemeral=True)
            return

        if 警告編號 is not None and 警告編號 <= 0:
            await InteractionResponder.safe_send(interaction, "❌ 警告編號必須為大於 0 之正整數。", ephemeral=True)
            return

        async with db.session() as session:
            if 警告編號:
                stmt = select(WarningRecord).where(
                    WarningRecord.guild_id == interaction.guild.id,
                    WarningRecord.user_id == 成員.id,
                    WarningRecord.id == 警告編號,
                    WarningRecord.is_active == True,
                )
                res = await session.execute(stmt)
                w = res.scalars().first()
                if not w:
                    await InteractionResponder.safe_send(
                        interaction,
                        f"❌ 查無成員 **{成員.display_name}** 之有效警告編號 `#{警告編號}`（可能已撤銷或編號錯誤）。",
                        ephemeral=True,
                    )
                    return

                w.is_active = False
                await session.commit()
                desc_text = f"已成功撤銷成員 **{成員.display_name}** 之警告案件 `#{警告編號}`。"
                log_reason = f"撤銷警告 #{警告編號}"
            else:
                stmt = select(WarningRecord).where(
                    WarningRecord.guild_id == interaction.guild.id,
                    WarningRecord.user_id == 成員.id,
                    WarningRecord.is_active == True,
                )
                res = await session.execute(stmt)
                active_records = res.scalars().all()
                if not active_records:
                    await InteractionResponder.safe_send(
                        interaction,
                        f"ℹ️ 成員 **{成員.display_name}** 目前無任何有效警告紀錄，無需清理。",
                        ephemeral=True,
                    )
                    return

                for record in active_records:
                    record.is_active = False
                await session.commit()
                desc_text = f"已成功清空成員 **{成員.display_name}** 全部 `{len(active_records)} 筆` 有效警告紀錄。"
                log_reason = f"清空全部 {len(active_records)} 筆有效警告"

        await self._log_case(interaction.guild.id, "clear_warns", 成員.id, interaction.user.id, log_reason)

        card = ZNCard(
            title="警告紀錄已撤銷",
            description=desc_text,
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 9. 清除訊息 clear / purge
    # --------------------------------------------------------------------------
    @manage_group.command(name="清除訊息", description="批次清除指定數量訊息 (支援多重進階過濾與二次確認)")
    @app_commands.describe(
        數量="要刪除的訊息則數 (1~100)",
        指定成員="僅刪除該成員的發言 (可選)",
        僅機器人="僅刪除機器人所發送的訊息 (可選)",
        僅包含網址="僅刪除包含 http/https 連結的訊息 (可選)",
        僅包含圖片="僅刪除包含圖片附件或圖檔嵌入的訊息 (可選)",
        關鍵字過濾="僅刪除內文包含指定關鍵字的訊息 (可選)",
    )
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def clear_command(
        self,
        interaction: discord.Interaction,
        數量: int = 10,
        指定成員: Optional[discord.Member] = None,
        僅機器人: bool = False,
        僅包含網址: bool = False,
        僅包含圖片: bool = False,
        關鍵字過濾: Optional[str] = None,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "manage_messages"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「管理訊息 (Manage Messages)」或管理員權限。", ephemeral=True)
            return

        channel = interaction.channel
        if not channel or not hasattr(channel, "purge"):
            await InteractionResponder.safe_send(interaction, "❌ 此頻道不支援批次清理訊息。", ephemeral=True)
            return

        bot_perms = channel.permissions_for(interaction.guild.me)
        if not bot_perms.manage_messages:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少此頻道的「管理訊息」權限，無法執行批次刪除。", ephemeral=True)
            return
        if not bot_perms.read_message_history:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少此頻道的「讀取訊息歷史紀錄」權限。", ephemeral=True)
            return

        count = max(1, min(100, 數量))
        view = ZNConfirmView(author_id=interaction.user.id, confirm_label="確認清除", is_dangerous=True)

        filters_summary: List[str] = []
        if 指定成員:
            filters_summary.append(f"• 指定成員：{指定成員.mention}")
        if 僅機器人:
            filters_summary.append("• 僅機器人發送之訊息")
        if 僅包含網址:
            filters_summary.append("• 僅包含 URL 網址之訊息")
        if 僅包含圖片:
            filters_summary.append("• 僅包含圖片或動態 GIF 之訊息")
        if 關鍵字過濾:
            filters_summary.append(f"• 內文關鍵字：`{關鍵字過濾}`")

        filter_block = ("\n**套用過濾條件**：\n" + "\n".join(filters_summary)) if filters_summary else "\n**過濾模式**：無條件清理近期所有訊息"

        warn_card = ZNCard(
            title="⚠️ 確認批次清除訊息",
            description=(
                f"您確定要在 {channel.mention} 清理近期的 **{count} 則** 訊息嗎？"
                f"{filter_block}\n\n"
                f"- **注意事項**：Discord 限制無法批次刪除超過 14 天前的訊息。\n"
                f"請在 60 秒內點擊下方按鈕確認執行。"
            ),
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        msg_obj = await InteractionResponder.safe_send(interaction, card=warn_card, view=view, ephemeral=True)
        if msg_obj and hasattr(view, "message"):
            view.message = msg_obj

        await view.wait()
        if not view.confirmed:
            return

        if not _has_guild_perm(interaction.user, "manage_messages"):
            await interaction.followup.send("❌ 權限已變更：您缺少 Discord 原生「管理訊息」權限。", ephemeral=True)
            return

        def check_msg(m: discord.Message) -> bool:
            if 指定成員 and m.author.id != 指定成員.id:
                return False
            if 僅機器人 and not m.author.bot:
                return False
            if 僅包含網址 and not ("http://" in m.content or "https://" in m.content):
                return False
            if 僅包含圖片:
                has_img = (
                    any(att.content_type and att.content_type.startswith("image/") for att in m.attachments)
                    or any(e.type in ("image", "gifv") for e in m.embeds)
                )
                if not has_img:
                    return False
            if 關鍵字過濾 and 關鍵字過濾.lower() not in m.content.lower():
                return False
            return True

        try:
            deleted = await channel.purge(limit=count, check=check_msg)
        except discord.Forbidden:
            await interaction.followup.send("❌ Discord 權限不足：無法刪除此頻道之訊息。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            # 檢查是否為超過 14 天無法批量刪除之限制 (Discord API error code 50034)
            if ex.code == 50034 or "14 days" in str(ex):
                try:
                    # 降級改為逐條非批量刪除 (bulk=False)
                    try:
                        deleted = await channel.purge(limit=count, check=check_msg, bulk=False)
                    except TypeError:
                        deleted = await channel.purge(limit=count, check=check_msg)
                except discord.HTTPException as inner_ex:
                    await interaction.followup.send(
                        f"⚠️ 部分歷史訊息發送已超過 14 天限制，嘗試逐條刪除時失敗：`{inner_ex.text or inner_ex}`",
                        ephemeral=True,
                    )
                    return
            else:
                await interaction.followup.send(f"❌ 清除訊息失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
                return

        audit_note = f"批次刪除 {len(deleted)} 則訊息"
        if filters_summary:
            audit_note += f" [過濾: {', '.join(filters_summary)}]"

        await self._log_case(
            interaction.guild.id,
            "clear",
            channel.id,
            interaction.user.id,
            audit_note,
        )

        success_card = ZNCard(
            title="訊息清理完成",
            description=f"已成功清理 **{len(deleted)} 則** 符合過濾條件之歷史訊息。{filter_block}",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await interaction.followup.send(embed=success_card.to_embed(), ephemeral=True)
        await InteractionResponder.safe_edit(interaction, card=success_card, view=None)

    # --------------------------------------------------------------------------
    # 10. 鎖定頻道 lock
    # --------------------------------------------------------------------------
    @manage_group.command(name="鎖定頻道", description="限制普通成員在此頻道發言與建立討論串")
    @app_commands.describe(頻道="要鎖定的文字頻道 (預設當前頻道)")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def lock_command(self, interaction: discord.Interaction, 頻道: Optional[discord.TextChannel] = None) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "manage_channels"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「管理頻道 (Manage Channels)」或管理員權限。", ephemeral=True)
            return

        target_channel = 頻道 or interaction.channel
        if not hasattr(target_channel, "set_permissions"):
            await InteractionResponder.safe_send(interaction, "❌ 此頻道類型不支援發言權限變更。", ephemeral=True)
            return

        bot_perms = target_channel.permissions_for(interaction.guild.me)
        if not bot_perms.manage_channels and not bot_perms.manage_roles:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少此頻道的「管理頻道」或「管理身分組與權限」，無法執行鎖定。", ephemeral=True)
            return

        try:
            await target_channel.set_permissions(
                interaction.guild.default_role,
                send_messages=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                reason=f"由 {interaction.user} 執行頻道鎖定",
            )
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法變更該頻道之覆蓋權限。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 鎖定頻道失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        await self._log_case(interaction.guild.id, "lock", target_channel.id, interaction.user.id, "鎖定頻道發言權限")

        card = ZNCard(
            title="頻道已鎖定",
            description=f"頻道 {target_channel.mention} 已鎖定成員發言與討論串發文權限，僅具備管理員權限者可發言。",
            status_pill=ZNStatusPill.MODERATION,
            color=ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 11. 解鎖頻道 unlock
    # --------------------------------------------------------------------------
    @manage_group.command(name="解鎖頻道", description="恢復普通成員在頻道的正常發言權限")
    @app_commands.describe(頻道="要解鎖的文字頻道 (預設當前頻道)")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def unlock_command(self, interaction: discord.Interaction, 頻道: Optional[discord.TextChannel] = None) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "manage_channels"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「管理頻道 (Manage Channels)」或管理員權限。", ephemeral=True)
            return

        target_channel = 頻道 or interaction.channel
        if not hasattr(target_channel, "set_permissions"):
            await InteractionResponder.safe_send(interaction, "❌ 此頻道類型不支援發言權限變更。", ephemeral=True)
            return

        bot_perms = target_channel.permissions_for(interaction.guild.me)
        if not bot_perms.manage_channels and not bot_perms.manage_roles:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少此頻道的「管理頻道」或「管理身分組與權限」，無法執行解鎖。", ephemeral=True)
            return

        try:
            await target_channel.set_permissions(
                interaction.guild.default_role,
                send_messages=None,
                send_messages_in_threads=None,
                create_public_threads=None,
                create_private_threads=None,
                reason=f"由 {interaction.user} 執行頻道解鎖",
            )
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法變更該頻道之覆蓋權限。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 解鎖頻道失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        await self._log_case(interaction.guild.id, "unlock", target_channel.id, interaction.user.id, "恢復頻道發言權限")

        card = ZNCard(
            title="頻道已解鎖",
            description=f"頻道 {target_channel.mention} 已恢復正常發言限制與討論串交流權限。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 12. 慢速模式 slowmode
    # --------------------------------------------------------------------------
    @manage_group.command(name="慢速模式", description="設定頻道慢速模式冷卻秒數")
    @app_commands.describe(秒數="每位成員發言冷卻秒數 (0 代表關閉，最高 21600 秒 / 6 小時)", 頻道="目標文字頻道 (預設當前)")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def slowmode_command(
        self,
        interaction: discord.Interaction,
        秒數: int = 5,
        頻道: Optional[discord.TextChannel] = None,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "manage_channels"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「管理頻道 (Manage Channels)」或管理員權限。", ephemeral=True)
            return

        target_channel = 頻道 or interaction.channel
        if not hasattr(target_channel, "edit"):
            await InteractionResponder.safe_send(interaction, "❌ 此頻道類型不支援慢速模式調整。", ephemeral=True)
            return

        bot_perms = target_channel.permissions_for(interaction.guild.me)
        if not bot_perms.manage_channels:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少此頻道的「管理頻道」權限，無法調整慢速模式。", ephemeral=True)
            return

        delay = max(0, min(21600, 秒數))
        try:
            await target_channel.edit(slowmode_delay=delay, reason=f"由 {interaction.user} 設定慢速模式 {delay} 秒")
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法編輯此頻道之慢速模式設定。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 慢速模式設定失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        await self._log_case(interaction.guild.id, "slowmode", target_channel.id, interaction.user.id, f"設定慢速模式: {delay}秒", delay)

        desc = f"頻道 {target_channel.mention} 慢速模式已調整為 **{delay} 秒**。" if delay > 0 else f"頻道 {target_channel.mention} 慢速模式已關閉。"
        card = ZNCard(
            title="慢速模式設定完成",
            description=desc,
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 13. 更改暱稱 nickname
    # --------------------------------------------------------------------------
    @manage_group.command(name="更改暱稱", description="修改成員在伺服器的顯示暱稱")
    @app_commands.describe(成員="目標成員", 新暱稱="新的伺服器暱稱 (留空代表重設為原始名稱)")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def nickname_command(
        self,
        interaction: discord.Interaction,
        成員: discord.Member,
        新暱稱: Optional[str] = None,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "manage_nicknames"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「管理暱稱 (Manage Nicknames)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_nicknames:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少「管理暱稱」權限，無法變更成員暱稱。", ephemeral=True)
            return

        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, 成員, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行：{msg}", ephemeral=True)
            return

        old_name = 成員.display_name
        clean_nick = 新暱稱.strip() if 新暱稱 else None
        if clean_nick and len(clean_nick) > 32:
            await InteractionResponder.safe_send(interaction, "❌ 伺服器暱稱長度上限為 32 個字元。", ephemeral=True)
            return

        try:
            await 成員.edit(nick=clean_nick, reason=f"由 {interaction.user} ({interaction.user.id}) 更改暱稱")
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法修改該成員之暱稱，請確認身分組階層順位。", ephemeral=True)
            return
        except discord.NotFound:
            await InteractionResponder.safe_send(interaction, "❌ 目標成員已不在伺服器中。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 修改暱稱失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        await self._log_case(interaction.guild.id, "nickname", 成員.id, interaction.user.id, f"暱稱由「{old_name}」改為「{clean_nick or 成員.name}」")

        card = ZNCard(
            title="暱稱已更新",
            description=f"成員 **{old_name}** 的伺服器暱稱已變更為 **{clean_nick or 成員.name}**。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 14. 身分組新增 role add
    # --------------------------------------------------------------------------
    @manage_group.command(name="身分組新增", description="為成員指派特定身分組")
    @app_commands.describe(成員="目標成員", 身分組="要指派的身分組")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def role_add_command(self, interaction: discord.Interaction, 成員: discord.Member, 身分組: discord.Role) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "manage_roles"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「管理身分組 (Manage Roles)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_roles:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少「管理身分組」權限，無法執行指派。", ephemeral=True)
            return

        if 身分組.is_default() or 身分組.name == "@everyone":
            await InteractionResponder.safe_send(interaction, "❌ 無法對 @everyone 基礎身分組進行指派操作。", ephemeral=True)
            return
        if getattr(身分組, "managed", False) or getattr(身分組, "is_bot_managed", lambda: False)():
            await InteractionResponder.safe_send(interaction, "❌ 無法手動指派受系統或機器人整合代管的身分組。", ephemeral=True)
            return
        if getattr(身分組, "is_premium_subscriber", lambda: False)():
            await InteractionResponder.safe_send(interaction, "❌ 無法手動指派伺服器加成者 (Server Booster) 專屬身分組。", ephemeral=True)
            return

        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, 成員, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行：{msg}", ephemeral=True)
            return

        if 身分組 >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id and not PermissionEngine.is_developer(interaction.user.id):
            await InteractionResponder.safe_send(interaction, "❌ 您無法指派等於或高於您自身最高順位的身分組。", ephemeral=True)
            return
        if bot_member and 身分組 >= bot_member.top_role:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 的最高身分組順位低於或等於該身分組，無法指派。", ephemeral=True)
            return

        if 身分組 in 成員.roles:
            await InteractionResponder.safe_send(interaction, f"ℹ️ 成員 **{成員.display_name}** 已經擁有身分組 {身分組.mention}，無需重複指派。", ephemeral=True)
            return

        try:
            await 成員.add_roles(身分組, reason=f"由 {interaction.user} ({interaction.user.id}) 指派身分組")
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法為該成員指派此身分組，請確認階層配置。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 指派身分組失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        await self._log_case(interaction.guild.id, "role_add", 成員.id, interaction.user.id, f"新增身分組 {身分組.name} ({身分組.id})")

        card = ZNCard(
            title="身分組已指派",
            description=f"已成功為成員 **{成員.display_name}** 指派身分組 {身分組.mention}。",
            status_pill=ZNStatusPill.SUCCESS,
            color=身分組.color if 身分組.color.value != 0 else ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 15. 身分組移除 role remove
    # --------------------------------------------------------------------------
    @manage_group.command(name="身分組移除", description="移除成員的特定身分組")
    @app_commands.describe(成員="目標成員", 身分組="要移除的身分組")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def role_remove_command(self, interaction: discord.Interaction, 成員: discord.Member, 身分組: discord.Role) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "manage_roles"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「管理身分組 (Manage Roles)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_roles:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少「管理身分組」權限，無法執行移除。", ephemeral=True)
            return

        if 身分組.is_default() or 身分組.name == "@everyone":
            await InteractionResponder.safe_send(interaction, "❌ 無法對 @everyone 基礎身分組進行移除操作。", ephemeral=True)
            return
        if getattr(身分組, "managed", False) or getattr(身分組, "is_bot_managed", lambda: False)():
            await InteractionResponder.safe_send(interaction, "❌ 無法手動移除受系統或機器人整合代管的身分組。", ephemeral=True)
            return
        if getattr(身分組, "is_premium_subscriber", lambda: False)():
            await InteractionResponder.safe_send(interaction, "❌ 無法手動移除伺服器加成者專屬身分組。", ephemeral=True)
            return

        allowed, msg = PermissionEngine.check_hierarchy(interaction.user, 成員, bot_member)
        if not allowed:
            await InteractionResponder.safe_send(interaction, f"❌ 無法執行：{msg}", ephemeral=True)
            return

        if 身分組 >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id and not PermissionEngine.is_developer(interaction.user.id):
            await InteractionResponder.safe_send(interaction, "❌ 您無法移除等於或高於您自身最高順位的身分組。", ephemeral=True)
            return
        if bot_member and 身分組 >= bot_member.top_role:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 的最高身分組順位低於或等於該身分組，無法移除。", ephemeral=True)
            return

        if 身分組 not in 成員.roles:
            await InteractionResponder.safe_send(interaction, f"ℹ️ 成員 **{成員.display_name}** 並未擁有身分組 {身分組.mention}，無需移除。", ephemeral=True)
            return

        try:
            await 成員.remove_roles(身分組, reason=f"由 {interaction.user} ({interaction.user.id}) 移除身分組")
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法從該成員身上移除此身分組。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 移除身分組失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        await self._log_case(interaction.guild.id, "role_remove", 成員.id, interaction.user.id, f"移除身分組 {身分組.name} ({身分組.id})")

        card = ZNCard(
            title="身分組已移除",
            description=f"已成功從成員 **{成員.display_name}** 身上移除身分組 {身分組.mention}。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 16. 伺服器備份 backup
    # --------------------------------------------------------------------------
    @manage_group.command(name="伺服器備份", description="建立伺服器結構、身分組與頻道配置快照備份")
    @command_guard("moderation", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def backup_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "administrator"):
            await InteractionResponder.safe_send(interaction, "❌ 伺服器備份僅限具備 Discord 原生「管理員 (Administrator)」權限之成員執行。", ephemeral=True)
            return

        g = interaction.guild
        categories_count = len(g.categories)
        text_count = len(g.text_channels)
        voice_count = len(g.voice_channels)
        stage_count = len(g.stage_channels)
        forum_count = len(getattr(g, "forum_channels", []))
        roles_count = len([r for r in g.roles if not r.is_default()])
        emojis_count = len(g.emojis)
        stickers_count = len(g.stickers)

        now_utc = datetime.now(timezone.utc)
        now_ts = int(now_utc.timestamp())

        card = ZNCard(
            title=f"{g.name} — 伺服器配置結構備份快照",
            description=(
                f"已成功擷取並比對伺服器 **{g.name}** 之完整配置結構：\n\n"
                f"- 📁 **分類目錄**：`{categories_count}` 個\n"
                f"- 💬 **文字頻道**：`{text_count}` 個\n"
                f"- 🔊 **語音頻道**：`{voice_count}` 個\n"
                f"- 🎭 **舞台頻道**：`{stage_count}` 個\n"
                f"- 📑 **論壇頻道**：`{forum_count}` 個\n"
                f"- 🛡️ **自訂身分組**：`{roles_count}` 個\n"
                f"- 🎨 **自訂表情 / 貼圖**：`{emojis_count} / {stickers_count}` 個\n"
                f"- ⏱️ **備份時間**：<t:{now_ts}:F> (<t:{now_ts}:R>)\n"
                f"- 執行管理員：{interaction.user.mention}"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 17. 審核日誌 audit
    # --------------------------------------------------------------------------
    @manage_group.command(name="審核日誌", description="調取近期的伺服器管理審核日誌")
    @app_commands.describe(數量="檢視筆數 (1~20)")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def audit_command(self, interaction: discord.Interaction, 數量: int = 5) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if not _has_guild_perm(interaction.user, "view_audit_log"):
            await InteractionResponder.safe_send(interaction, "❌ 您缺少 Discord 原生「檢視審核日誌 (View Audit Log)」或管理員權限。", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.view_audit_log:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少「檢視審核日誌」權限，無法調取日誌。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        count = max(1, min(20, 數量))

        entries: List[str] = []
        try:
            async for entry in interaction.guild.audit_logs(limit=count):
                ts = int(entry.created_at.timestamp())
                raw_action_name = entry.action.name if hasattr(entry.action, "name") else str(entry.action)
                friendly_action = AUDIT_ACTION_NAMES.get(raw_action_name, raw_action_name)
                user_display = entry.user.display_name if entry.user else "未知操作者"
                target_display = getattr(entry.target, "display_name", getattr(entry.target, "name", str(entry.target or "無目標")))
                reason_extra = f" (理由: {entry.reason})" if entry.reason else ""

                entries.append(
                    f"<t:{ts}:T> **{user_display}** 執行「**{friendly_action}**」\n"
                    f"└ 目標：`{target_display}`{reason_extra}"
                )
        except discord.Forbidden:
            await interaction.followup.send("❌ Discord 權限不足：無法調取伺服器審核日誌。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await interaction.followup.send(f"❌ 調取審核日誌失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        card = ZNCard(
            title=f"伺服器管理審核日誌 (近 {len(entries)} 筆)",
            description="\n\n".join(entries) if entries else "近期無管理操作日誌紀錄。",
            status_pill=ZNStatusPill.MODERATION,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    # --------------------------------------------------------------------------
    # 18. 案件查詢 cases
    # --------------------------------------------------------------------------
    @manage_group.command(name="案件查詢", description="依案件 ID 或成員查詢懲處詳細資料")
    @app_commands.describe(案件編號="管理案件的唯一 ID (選填)", 成員="查詢指定成員的近期處分案件 (選填)")
    @command_guard("moderation", required_level=ZNPermissionLevel.MODERATOR)
    async def case_command(
        self,
        interaction: discord.Interaction,
        案件編號: Optional[int] = None,
        成員: Optional[discord.User] = None,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在 Discord 伺服器內使用。", ephemeral=True)
            return

        if 案件編號 is not None and 案件編號 <= 0:
            await InteractionResponder.safe_send(interaction, "❌ 案件編號必須為大於 0 之正整數。", ephemeral=True)
            return

        async with db.session() as session:
            if 案件編號:
                stmt = select(ModerationCase).where(
                    ModerationCase.guild_id == interaction.guild.id,
                    ModerationCase.case_id == 案件編號,
                )
                res = await session.execute(stmt)
                case = res.scalars().first()

                if not case:
                    await InteractionResponder.safe_send(interaction, f"❌ 在本伺服器中查無案件編號 `#{案件編號}` 之紀錄。", ephemeral=True)
                    return

                action_text = MOD_ACTION_NAMES.get(case.action, case.action)
                dur_text = format_duration(case.duration_seconds) if case.duration_seconds else "即時 / 永久"
                ts = int(case.created_at.timestamp()) if case.created_at else 0
                time_str = f"<t:{ts}:F> (<t:{ts}:R>)" if ts else "未知時間"

                card = ZNCard(
                    title=f"管理處分案件 #{case.case_id} — {action_text}",
                    description=(
                        f"- **處分動作**：`{action_text}` (`{case.action}`)\n"
                        f"- **處置對象**：<@{case.target_user_id}> (`{case.target_user_id}`)\n"
                        f"- **執行管理員**：<@{case.moderator_id}>\n"
                        f"- **時長規格**：`{dur_text}`\n"
                        f"- **成案時間**：{time_str}\n"
                        f"- **處分事由**：{case.reason}"
                    ),
                    status_pill=ZNStatusPill.MODERATION,
                    color=ZNColor.INFO,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            elif 成員:
                stmt = select(ModerationCase).where(
                    ModerationCase.guild_id == interaction.guild.id,
                    ModerationCase.target_user_id == 成員.id,
                ).order_by(desc(ModerationCase.created_at)).limit(10)
                res = await session.execute(stmt)
                cases = res.scalars().all()

                if not cases:
                    card = ZNCard(
                        title=f"{成員.display_name} — 無歷史處分案件",
                        description=f"成員 **{成員.display_name}** (`{成員.id}`) 在本伺服器無任何紀錄案件。",
                        status_pill=ZNStatusPill.SUCCESS,
                        color=ZNColor.SUCCESS,
                    )
                    await InteractionResponder.safe_send(interaction, card=card)
                    return

                lines: List[str] = []
                for c in cases:
                    action_text = MOD_ACTION_NAMES.get(c.action, c.action)
                    ts = int(c.created_at.timestamp()) if c.created_at else 0
                    t_str = f"<t:{ts}:f>" if ts else ""
                    lines.append(f"`#{c.case_id}` [{t_str}] **{action_text}** (管理員: <@{c.moderator_id}>) — {c.reason}")

                card = ZNCard(
                    title=f"成員懲處案件紀錄 — {成員.display_name} (近 {len(cases)} 筆)",
                    description="\n".join(lines),
                    status_pill=ZNStatusPill.MODERATION,
                    color=ZNColor.WARNING,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            else:
                stmt = select(ModerationCase).where(
                    ModerationCase.guild_id == interaction.guild.id,
                ).order_by(desc(ModerationCase.created_at)).limit(5)
                res = await session.execute(stmt)
                cases = res.scalars().all()

                if not cases:
                    card = ZNCard(
                        title="伺服器處分案件清單",
                        description="本伺服器目前無任何管理處分紀錄案件。",
                        status_pill=ZNStatusPill.SUCCESS,
                        color=ZNColor.SUCCESS,
                    )
                    await InteractionResponder.safe_send(interaction, card=card)
                    return

                lines = []
                for c in cases:
                    action_text = MOD_ACTION_NAMES.get(c.action, c.action)
                    ts = int(c.created_at.timestamp()) if c.created_at else 0
                    t_str = f"<t:{ts}:f>" if ts else ""
                    lines.append(f"`#{c.case_id}` [{t_str}] **{action_text}** 目標: <@{c.target_user_id}> (由 <@{c.moderator_id}>) — {c.reason}")

                card = ZNCard(
                    title=f"伺服器最新處分案件 (近 {len(cases)} 筆)",
                    description="\n".join(lines),
                    status_pill=ZNStatusPill.MODERATION,
                    color=ZNColor.INFO,
                )
                await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
