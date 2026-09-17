"""ZeroNexus Command Guard Interceptor.

Protects command invocation with:
1. Module Isolation Guard: Blocks invocation if parent module is DISABLED / DEGRADED, replying with diagnostic card.
2. Permission Tier Guard: Verifies Discord & ZeroNexus authority levels.
3. Cooldown Guard: Enforces sliding window rate limits.
4. Exception Guard: Catches unhandled errors, logs safely, and returns humanized ZNResponse without secret leaks.
5. Interaction Lifecycle Guard: Integrates InteractionResponder to defend against 10062 & 40060 errors.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Set, Tuple, Union

import discord
from discord import app_commands

from zeronexus.core.logger import log
from zeronexus.core.stats import stats
from zeronexus.modules.state import ModuleState
from zeronexus.security.permissions import PermissionEngine, ZNPermissionLevel
from zeronexus.security.ratelimit import rate_limiter
from zeronexus.ui.card import ZNCard, ZNResponse
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill

__all__ = [
    "command_guard",
    "GLOBAL_DEVELOPER_COMMANDS",
    "app_commands",
    "Dict",
    "List",
    "Literal",
    "Optional",
    "Tuple",
    "Union",
]


GLOBAL_DEVELOPER_COMMANDS: Set[str] = {
    # Full command names / qualified slash command paths
    "系統 模組啟用",
    "系統 模組停用",
    "系統 模組重啟",
    "系統 快取清空",
    "系統 系統日誌",
    "系統 排程觸發",
    "系統 重新連線",
    "系統 評估",
    "系統 資料庫整理",
    # Underlying function and command names
    "module_enable",
    "module_disable",
    "module_reload",
    "cache_clear",
    "logs_command",
    "scheduler_trigger",
    "reconnect_command",
    "eval_command",
    "db_vacuum",
    "module_enable_command",
    "module_disable_command",
    "module_reload_command",
    "cache_clear_command",
    "scheduler_trigger_command",
}


def command_guard(
    module_name: str,
    required_level: ZNPermissionLevel = ZNPermissionLevel.EVERYONE,
    cooldown_seconds: float = 2.0,
) -> Callable[..., Any]:
    """Decorator wrapping Discord Slash Command callbacks with health, permission, cooldown, and lifecycle checks."""
    def decorator(func: Callable[..., Coroutine[Any, Any, None]]) -> Callable[..., Coroutine[Any, Any, None]]:
        @functools.wraps(func)
        async def wrapper(self: Any, interaction: discord.Interaction, *args: Any, **kwargs: Any) -> None:
            cmd_name = interaction.command.name if interaction.command else func.__name__
            full_name = f"{interaction.command.qualified_name}" if interaction.command else cmd_name
            start_ts = time.perf_counter()
            log.info(f"[Command] /{full_name} invoked by {interaction.user} (id={interaction.user.id}) in guild={interaction.guild_id}")

            # Enforce strict DEVELOPER threshold for global lifecycle and maintenance commands
            effective_level = required_level
            if (
                full_name in GLOBAL_DEVELOPER_COMMANDS
                or cmd_name in GLOBAL_DEVELOPER_COMMANDS
                or func.__name__ in GLOBAL_DEVELOPER_COMMANDS
            ):
                effective_level = max(required_level, ZNPermissionLevel.DEVELOPER)

            # 1. Module Health Guard
            from zeronexus.modules.manager import module_manager
            mod = module_manager.get_module(module_name)
            if mod and mod.state in (ModuleState.DISABLED, ModuleState.DEGRADED):
                log.warning(f"Command '{full_name}' blocked because module '{module_name}' is in {mod.state.value} state")
                card = ZNCard(
                    title=f"模組暫時休眠中 ({mod.display_name})",
                    description=(
                        f"該指令所屬的「**{mod.display_name}**」目前正處於保護性維護狀態（`{mod.state.value}`）。\n\n"
                        f"📌 **當前狀況**：`{mod.error_reason or '外部連線維護中或處於安全保護狀態'}`\n"
                        "🛡️ **系統防護**：ZeroNexus 已啟動安全隔離機制，伺服器其他所有功能均正常運作，不受影響。\n\n"
                        f"💡 **建議您可以**：稍候片刻再次嘗試；若您是伺服器管理員，可使用 `/系統 模組重啟 模組名稱:{module_name}` 嘗試重新載入。"
                    ),
                    status_pill=ZNStatusPill.ERROR if mod.state == ModuleState.DISABLED else ZNStatusPill.WARNING,
                    color=ZNColor.ERROR if mod.state == ModuleState.DISABLED else ZNColor.WARNING,
                )
                resp = ZNResponse(card=card, ephemeral=True)
                await InteractionResponder.safe_send(interaction, **resp.to_send_kwargs())
                return

            # 2. Permission Tier Guard & Guild Context Check
            # Moderation/admin commands cannot run in DMs; developers are exempt for remote maintenance
            if (
                effective_level >= ZNPermissionLevel.MODERATOR
                and interaction.guild is None
                and not PermissionEngine.is_developer(interaction.user.id)
            ):
                card = ZNCard(
                    title="此指令限在伺服器內執行",
                    description=(
                        "🌱 為了確保伺服器管理安全與權限審核，此層級的管理指令必須在 Discord 伺服器文字頻道內進行，無法在私訊中使用喔！\n\n"
                        "💡 **建議您可以**：回到伺服器中的指定頻道再次輸入此指令。"
                    ),
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                resp = ZNResponse(card=card, ephemeral=True)
                await InteractionResponder.safe_send(interaction, **resp.to_send_kwargs())
                return

            user_level = PermissionEngine.resolve_level(interaction.user, interaction.guild)
            if user_level < effective_level:
                log.warning(f"Command '{full_name}' blocked: user {interaction.user.id} has level {user_level.name} < required {effective_level.name}")
                perm_names = {
                    ZNPermissionLevel.EVERYONE: "一般社群成員 (EVERYONE)",
                    ZNPermissionLevel.MODERATOR: "伺服器管理人員 / 協管員 (MODERATOR)",
                    ZNPermissionLevel.ADMINISTRATOR: "伺服器管理員 (ADMINISTRATOR)",
                    ZNPermissionLevel.DEVELOPER: "ZeroNexus 核心開發團隊 (DEVELOPER)",
                }
                req_text = perm_names.get(effective_level, effective_level.name)
                cur_text = perm_names.get(user_level, user_level.name)
                card = ZNCard(
                    title="權限不足以執行",
                    description=(
                        "抱歉，執行此指令需要更高的授權階層：\n\n"
                        f"- 🔒 **所需權限**：`{req_text}`\n"
                        f"- 👤 **您的身分**：`{cur_text}`\n\n"
                        "💡 **建議您可以**：若您認為這是一項誤判，請聯繫伺服器擁有者或管理員確認您的身分組權限配置。"
                    ),
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                resp = ZNResponse(card=card, ephemeral=True)
                await InteractionResponder.safe_send(interaction, **resp.to_send_kwargs())
                return

            # 3. Rate Limit / Cooldown Guard
            is_limited, retry_after = rate_limiter.check_command_cooldown(
                user_id=interaction.user.id,
                command_name=full_name,
                cooldown_seconds=cooldown_seconds,
            )
            if is_limited:
                card = ZNCard(
                    title="指令冷卻中，請稍候片刻",
                    description=(
                        f"🍃 為了維護頻道流暢度與系統平穩，請稍作休息 **{retry_after} 秒** 後再次使用。\n\n"
                        "💡 **貼心提醒**：連續快速點擊可能導致冷卻時間重置，請放慢節奏喔！"
                    ),
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                resp = ZNResponse(card=card, ephemeral=True)
                await InteractionResponder.safe_send(interaction, **resp.to_send_kwargs())
                return

            # 4. Execution & Exception Guard
            try:
                await func(self, interaction, *args, **kwargs)
                latency = (time.perf_counter() - start_ts) * 1000
                stats.record_command(full_name, latency, success=True)
                stats.record_module_call(module_name)
            except Exception as e:
                latency = (time.perf_counter() - start_ts) * 1000
                stats.record_command(full_name, latency, success=False)
                from zeronexus.security.sanitizer import redact_secrets
                clean_err = redact_secrets(str(e))
                stats.record_error(f"command:{full_name}", clean_err)
                log.error(f"Unhandled error in command '{full_name}': {clean_err}", exc_info=True)

                # Critical Dead Token Defense:
                # If error is 10062 (Unknown interaction), DO NOT call send_message again!
                if InteractionResponder.is_expired_or_unknown(e):
                    log.warning(f"Interaction for command '{full_name}' expired with 10062. Halting without second send.")
                    return

                error_card = ZNCard(
                    title="處理指令時遇到了一點狀況",
                    description=(
                        "很抱歉，這項指令在執行期間遇到了未預期的問題，請別擔心，您的資料安全完好。\n\n"
                        f"📌 **狀況簡述**：`{clean_err[:120]}`\n\n"
                        "💡 **您可以嘗試**：\n"
                        "1. 稍候片刻再次嘗試發起該指令。\n"
                        "2. 檢查輸入的參數與選項是否符合提示格式。\n"
                        "3. 若問題持續發生，請通知伺服器管理團隊協助查看系統狀態。"
                    ),
                    status_pill=ZNStatusPill.ERROR,
                    color=ZNColor.ERROR,
                )
                err_resp = ZNResponse(card=error_card, ephemeral=True)
                await InteractionResponder.safe_send(interaction, **err_resp.to_send_kwargs())

        return wrapper
    return decorator
