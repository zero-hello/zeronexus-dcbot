"""ZeroNexus Multi-Tier Permission Engine.

Evaluation Hierarchy:
Discord Native Permissions -> ZeroNexus Permissions -> Role Hierarchy -> Action Checks
Ensures developers are verified strictly via configuration and prevents unauthorized elevation.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional, Tuple

import discord

from zeronexus.core.config import config


class ZNPermissionLevel(IntEnum):
    """ZeroNexus Permission Tier Rankings."""
    EVERYONE = 0
    TRUSTED = 1
    MODERATOR = 2
    ADMINISTRATOR = 3
    GUILD_OWNER = 4
    DEVELOPER = 5


class PermissionEngine:
    """Central evaluator for authorization across commands, modules, and administrative actions."""

    @staticmethod
    def is_developer(user_id: int) -> bool:
        """Verifies whether the given user ID is an authorized ZeroNexus developer."""
        return config.discord.is_dev(user_id)

    @classmethod
    def resolve_level(
        cls,
        user: discord.User | discord.Member,
        guild: Optional[discord.Guild] = None,
    ) -> ZNPermissionLevel:
        """Determines the highest effective permission level for an actor."""
        # 1. Developer priority check
        if cls.is_developer(user.id):
            return ZNPermissionLevel.DEVELOPER

        # If in DMs and not developer
        if not guild or not isinstance(user, discord.Member):
            return ZNPermissionLevel.EVERYONE

        # 2. Guild Owner check
        if guild.owner_id == user.id:
            return ZNPermissionLevel.GUILD_OWNER

        # 3. Administrator check
        if user.guild_permissions.administrator:
            return ZNPermissionLevel.ADMINISTRATOR

        # 4. Moderator check
        if (
            user.guild_permissions.manage_guild
            or user.guild_permissions.kick_members
            or user.guild_permissions.ban_members
            or user.guild_permissions.moderate_members
        ):
            return ZNPermissionLevel.MODERATOR

        # 5. Trusted check (Manage messages or roles)
        if user.guild_permissions.manage_messages or user.guild_permissions.manage_roles:
            return ZNPermissionLevel.TRUSTED

        return ZNPermissionLevel.EVERYONE

    @classmethod
    def check_hierarchy(
        cls,
        executor: discord.Member,
        target: discord.Member,
        bot: Optional[discord.Member] = None,
    ) -> Tuple[bool, str]:
        """Validates Discord role hierarchy before executing administrative punishments (kick, ban, timeout).

        Prevents:
        - Self-action
        - Acting on Guild Owner
        - Acting on users with higher or equal top roles
        - Bot acting on users with higher or equal roles than the bot itself
        """
        if executor.id == target.id:
            return False, "您不能對自己執行此管理處分。"

        guild = getattr(executor, "guild", None) or getattr(target, "guild", None)
        if not guild:
            return False, "無法在缺乏伺服器環境下進行身分組階層比對。"

        # Owner cannot be acted upon under any circumstances
        if target.id == guild.owner_id:
            return False, "無法對伺服器擁有者執行此管理動作。"

        # Cannot act on the bot itself
        bot_member = bot or getattr(guild, "me", None)
        if bot_member and target.id == bot_member.id:
            return False, "無法對機器人自身執行此管理處分。"

        # Bot role hierarchy check must always run because Discord API strictly forbids
        # bots from modifying members with equal or higher top roles than the bot.
        target_role = getattr(target, "top_role", None)
        target_pos = getattr(target_role, "position", 0) if target_role else 0
        target_name = getattr(target, "display_name", getattr(target, "name", str(target.id)))

        if bot_member:
            bot_role = getattr(bot_member, "top_role", None)
            bot_pos = getattr(bot_role, "position", 0) if bot_role else 0
            if target_role and target_pos >= bot_pos:
                return False, f"ZeroNexus 的身分組順位低於或等於目標成員「{target_name}」，無法執行處分。"

        # Developer target protection: non-owners cannot moderate developers via the bot
        if cls.is_developer(target.id) and not cls.is_developer(executor.id) and executor.id != guild.owner_id:
            return False, f"目標成員「{target_name}」為 ZeroNexus 開發團隊成員，您無權處置。"

        # Administrator target protection: non-administrators cannot moderate administrators
        target_is_admin = getattr(getattr(target, "guild_permissions", None), "administrator", False)
        exec_is_admin = getattr(getattr(executor, "guild_permissions", None), "administrator", False)
        if target_is_admin and not exec_is_admin and not cls.is_developer(executor.id) and executor.id != guild.owner_id:
            return False, f"目標成員「{target_name}」擁有管理員 (Administrator) 權限，您無權處置。"

        # Developer override for emergency server rescue (bypasses executor role check)
        if cls.is_developer(executor.id):
            return True, ""

        # Executor role hierarchy check
        if executor.id != guild.owner_id:
            exec_role = getattr(executor, "top_role", None)
            exec_pos = getattr(exec_role, "position", 0) if exec_role else 0
            if target_role and target_pos >= exec_pos:
                return False, f"目標成員「{target_name}」的身分組順位高於或等於您的最高身分組，您無權處置。"

        return True, ""


# Singleton instance
permissions = PermissionEngine()
