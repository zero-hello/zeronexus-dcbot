"""ZeroNexus Ticket Command Module Cog.

6 Fully Implemented Commands under /客服單:
- 設定, 面板, 關閉, 鎖定, 接單, 狀態
"""

from __future__ import annotations

from typing import Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.core.logger import log
from zeronexus.engines.ticket_system import (
    TicketLaunchView,
    ticket_manager,
)
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


# =============================================================================
# Tickets Module Lifecycle
# =============================================================================

class TicketsModule(BaseModule):
    """ZeroNexus Enterprise Ticket System Domain Module."""

    def __init__(self) -> None:
        super().__init__(
            name="tickets",
            display_name="客服單系統",
            description="企業級一對一私密諮詢客服單、身分組權限隔離、工作人員接單認領、即時逐字稿存檔",
        )

    async def initialize(self, bot: Any) -> None:
        """Registers command metadata."""
        commands_list: List[tuple[str, str, ZNPermissionLevel, str]] = [
            ("設定", "配置客服單支援身分組、工單分類頻道與結案紀錄頻道", ZNPermissionLevel.ADMINISTRATOR, "客服單"),
            ("面板", "在指定頻道發送圖文並茂的客服單引導面板與開單按鈕", ZNPermissionLevel.ADMINISTRATOR, "客服單"),
            ("關閉", "關閉當前客服單頻道並自動匯出備份紀錄", ZNPermissionLevel.EVERYONE, "客服單"),
            ("鎖定", "切換當前客服單頻道的開單成員發言權限", ZNPermissionLevel.MODERATOR, "客服單"),
            ("接單", "客服專員正式認領此客服單並進行專責協助", ZNPermissionLevel.MODERATOR, "客服單"),
            ("狀態", "檢視本伺服器客服單系統配置與累積統計", ZNPermissionLevel.MODERATOR, "客服單"),
        ]

        for name, desc, perm, group in commands_list:
            full_name = f"/{group} {name}"
            self.register_command_meta(
                CommandMetadata(
                    name=name,
                    full_name=full_name,
                    description=desc,
                    group_name=group,
                    module_name=self.name,
                    permission_level=perm,
                    implemented=True,
                )
            )

    async def shutdown(self) -> None:
        """Cleans up ticket system module resources."""
        pass


# =============================================================================
# Ticket Slash Commands Cog
# =============================================================================

class TicketsCog(commands.Cog, name="客服單系統"):
    """Enterprise Support Ticket System Commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ticket_group = app_commands.Group(name="客服單", description="伺服器專屬客服單與技術諮詢系統")

    # -------------------------------------------------------------------------
    # 1. 設定 (/客服單 設定)
    # -------------------------------------------------------------------------
    @ticket_group.command(name="設定", description="配置客服單支援身分組、工單分類頻道與結案紀錄頻道")
    @app_commands.describe(
        客服身分組="負責處理工單的客服或工作人員身分組",
        分類頻道="新客服單頻道將建立於此 Discord 類別下",
        紀錄頻道="工單結案時自動推送對話歷史記錄與逐字稿的頻道",
    )
    @command_guard("tickets", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def setup_command(
        self,
        interaction: discord.Interaction,
        客服身分組: Optional[discord.Role] = None,
        分類頻道: Optional[discord.CategoryChannel] = None,
        紀錄頻道: Optional[discord.TextChannel] = None,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在伺服器內使用。", ephemeral=True)
            return

        cfg = await ticket_manager.update_config(
            guild_id=interaction.guild.id,
            support_role_id=客服身分組.id if 客服身分組 else None,
            category_id=分類頻道.id if 分類頻道 else None,
            log_channel_id=紀錄頻道.id if 紀錄頻道 else None,
        )

        role_str = 客服身分組.mention if 客服身分組 else (f"<@&{cfg.support_role_id}>" if cfg.support_role_id else "未配置")
        cat_str = 分類頻道.name if 分類頻道 else (interaction.guild.get_channel(cfg.category_id).name if cfg.category_id and interaction.guild.get_channel(cfg.category_id) else "未配置 (預設最外層)")
        log_str = 紀錄頻道.mention if 紀錄頻道 else (f"<#{cfg.log_channel_id}>" if cfg.log_channel_id else "未配置 (不傳送存檔)")

        card = ZNCard(
            title="✅ 客服單系統設定已更新",
            description=(
                f"已成功儲存 **{interaction.guild.name}** 之客服單配置：\n\n"
                f"- 🛡️ **客服管理身分組**：{role_str}\n"
                f"- 📁 **工單建立分類**：`{cat_str}`\n"
                f"- 📜 **結案紀錄頻道**：{log_str}\n\n"
                f"💡 **下一步**：您可以在希望展示的頻道輸入 `/客服單 面板` 發送引導面板！"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    # -------------------------------------------------------------------------
    # 2. 面板 (/客服單 面板)
    # -------------------------------------------------------------------------
    @ticket_group.command(name="面板", description="在指定頻道發送精緻的客戶服務中心開單引導面板")
    @app_commands.describe(目標頻道="欲發送面板之頻道 (預設為當前頻道)")
    @command_guard("tickets", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def panel_command(
        self,
        interaction: discord.Interaction,
        目標頻道: Optional[discord.TextChannel] = None,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在伺服器內使用。", ephemeral=True)
            return

        target_ch = 目標頻道 or interaction.channel
        if not isinstance(target_ch, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 目標頻道必須是標準文字頻道。", ephemeral=True)
            return

        panel_card = ticket_manager.build_panel_card(interaction.guild.name)
        launch_view = TicketLaunchView()

        try:
            await target_ch.send(embed=panel_card.to_embed(), view=launch_view)
            await ticket_manager.update_config(guild_id=interaction.guild.id, panel_channel_id=target_ch.id)
            await InteractionResponder.safe_send(
                interaction,
                f"✅ 客服單開單引導面板已成功發送至 {target_ch.mention}！",
                ephemeral=True,
            )
        except Exception as ex:
            await InteractionResponder.safe_send(
                interaction,
                f"❌ 無法在 {target_ch.mention} 發送面板：{ex}",
                ephemeral=True,
            )

    # -------------------------------------------------------------------------
    # 3. 關閉 (/客服單 關閉)
    # -------------------------------------------------------------------------
    @ticket_group.command(name="關閉", description="結案並關閉當前客服單頻道")
    @command_guard("tickets")
    async def close_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在客服單頻道內使用。", ephemeral=True)
            return

        rec = await ticket_manager.get_ticket_by_channel(interaction.channel.id)
        if not rec:
            await InteractionResponder.safe_send(interaction, "❌ 當前頻道不是有效的進行中客服單頻道。", ephemeral=True)
            return

        is_staff = await ticket_manager.is_staff(interaction.guild, interaction.user)
        is_owner = (interaction.user.id == rec.user_id)
        if not is_staff and not is_owner:
            await InteractionResponder.safe_send(interaction, "❌ 僅有開單成員或客服專員可以關閉此工單。", ephemeral=True)
            return

        # Prevent duplicate closing race condition
        if not await ticket_manager.start_closing(interaction.channel.id):
            await InteractionResponder.safe_send(
                interaction,
                "⚠️ 此客服單已在結案關閉流程中，請稍候！",
                ephemeral=True,
            )
            return

        warn_card = ZNCard(
            title="⚠️ 客服單即將結案",
            description="本頻道將在 **5 秒鐘後** 匯出對話逐字稿並自動刪除，感謝您的諮詢！",
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=warn_card)
        import asyncio
        await asyncio.sleep(5.0)
        await ticket_manager.close_ticket(interaction.channel, closed_by=interaction.user)

    # -------------------------------------------------------------------------
    # 4. 鎖定 (/客服單 鎖定)
    # -------------------------------------------------------------------------
    @ticket_group.command(name="鎖定", description="切換當前客服單頻道中開單成員的發言權限")
    @command_guard("tickets", required_level=ZNPermissionLevel.MODERATOR)
    async def lock_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在客服單頻道內使用。", ephemeral=True)
            return

        rec = await ticket_manager.get_ticket_by_channel(interaction.channel.id)
        if not rec:
            await InteractionResponder.safe_send(interaction, "❌ 當前頻道不是有效的客服單頻道。", ephemeral=True)
            return

        member = interaction.guild.get_member(rec.user_id)
        if not member:
            await InteractionResponder.safe_send(interaction, "❌ 查無此客服單的原開單成員（可能已離開伺服器）。", ephemeral=True)
            return

        ow = interaction.channel.overwrites_for(member)
        is_locked = (ow.send_messages is False)
        ow.send_messages = not is_locked
        try:
            await interaction.channel.set_permissions(member, overwrite=ow)
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ 機器人缺乏頻道管理權限，無法變更權限覆寫。", ephemeral=True)
            return
        except Exception as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 變更頻道權限時發生錯誤：{ex}", ephemeral=True)
            return

        action_text = "🔓 已解除頻道鎖定" if not is_locked else "🔒 已鎖定頻道"
        desc = f"開單成員 {member.mention} 現在{'可以正常' if not is_locked else '暫時無法'}發言。"
        card = ZNCard(
            title=action_text,
            description=desc,
            status_pill=ZNStatusPill.SUCCESS if not is_locked else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if not is_locked else ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 5. 接單 (/客服單 接單)
    # -------------------------------------------------------------------------
    @ticket_group.command(name="接單", description="客服人員認領並負責此客服單")
    @command_guard("tickets", required_level=ZNPermissionLevel.MODERATOR)
    async def claim_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在客服單頻道內使用。", ephemeral=True)
            return

        rec = await ticket_manager.get_ticket_by_channel(interaction.channel.id)
        if not rec:
            await InteractionResponder.safe_send(interaction, "❌ 當前頻道不是有效的客服單頻道。", ephemeral=True)
            return

        # Atomically claim ticket to prevent concurrent race condition
        success, current_claimer = await ticket_manager.claim_ticket(rec.id, interaction.user.id)
        if not success:
            claimer = interaction.guild.get_member(current_claimer) if current_claimer else None
            c_name = claimer.display_name if claimer else (f"<@{current_claimer}>" if current_claimer else "其他專員")
            await InteractionResponder.safe_send(interaction, f"ℹ️ 慢了一步！此客服單已由 **{c_name}** 接單負責。", ephemeral=True)
            return

        card = ZNCard(
            title="🙋 客服專員已接單",
            description=f"此客服單已由 {interaction.user.mention} 專責接單，將全程為您解答！",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 6. 狀態 (/客服單 狀態)
    # -------------------------------------------------------------------------
    @ticket_group.command(name="狀態", description="檢視本伺服器客服單系統配置與運作狀態")
    @command_guard("tickets", required_level=ZNPermissionLevel.MODERATOR)
    async def status_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此指令僅限在伺服器內使用。", ephemeral=True)
            return

        cfg = await ticket_manager.get_or_create_config(interaction.guild.id)
        role_str = f"<@&{cfg.support_role_id}>" if cfg.support_role_id else "未配置"
        cat_ch = interaction.guild.get_channel(cfg.category_id) if cfg.category_id else None
        cat_str = cat_ch.name if cat_ch else "未配置"
        log_ch = interaction.guild.get_channel(cfg.log_channel_id) if cfg.log_channel_id else None
        log_str = log_ch.mention if log_ch else "未配置"

        card = ZNCard(
            title=f"🎫 {interaction.guild.name} • 客服單系統狀態",
            description=(
                f"- 🛡️ **客服管理身分組**：{role_str}\n"
                f"- 📁 **工單建立分類**：`{cat_str}`\n"
                f"- 📜 **結案存檔頻道**：{log_str}\n"
                f"- 🔢 **累積受理工單**：`{cfg.ticket_counter}` 張\n\n"
                f"系統運作正常，所有開單按鈕與頻道控制 View 皆具備持久化 (Persistent) 支援！"
            ),
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    # -------------------------------------------------------------------------
    # Event Listener: 手動刪除頻道自癒處理
    # -------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Detects manual channel deletion by admins and cleans up hanging ticket DB records."""
        if not isinstance(channel, discord.TextChannel):
            return
        cleaned = await ticket_manager.mark_channel_deleted(channel.id)
        if cleaned:
            log.info(f"偵測到客服單頻道 #{channel.name} ({channel.id}) 已被手動刪除，自動完成資料庫結案歸檔 (工單 #{cleaned.id})。")


async def setup(bot: commands.Bot) -> None:
    """Extension cog setup callback."""
    await bot.add_cog(TicketsCog(bot))
