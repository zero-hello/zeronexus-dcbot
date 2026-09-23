"""ZeroNexus Enterprise Ticket & Support Desk Engine.

Built with Discord Components V2, Persistent Views, Modal Inputs,
Fine-Grained Permission Isolation, Staff Claiming, and Transcript Archiving.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
from sqlalchemy import select, update

from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.models.ticket import TicketConfig, TicketRecord
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


# =============================================================================
# Ticket Category Definitions
# =============================================================================

TICKET_CATEGORIES = {
    "tech": {
        "label": "技術支援與Bug回報",
        "emoji": "🛠️",
        "description": "系統異常、程式問題、機器人Bug或故障回報",
        "style": discord.ButtonStyle.primary,
    },
    "report": {
        "label": "違規檢舉與申訴",
        "emoji": "🚨",
        "description": "成員違規檢舉、頻道糾紛、禁言或處置申訴",
        "style": discord.ButtonStyle.danger,
    },
    "general": {
        "label": "一般諮詢與合作",
        "emoji": "💬",
        "description": "社群規則、身分組權益、專案合作或建議反饋",
        "style": discord.ButtonStyle.secondary,
    },
    "billing": {
        "label": "贊助與售後服務",
        "emoji": "💰",
        "description": "贊助支持、福利兌換、商城購買或帳務諮詢",
        "style": discord.ButtonStyle.success,
    },
}


# =============================================================================
# Modal: Ticket Creation Form
# =============================================================================

class TicketCreateModal(discord.ui.Modal):
    """Interactive Modal for creating a ticket with subject and details."""

    def __init__(self, category_key: str, category_info: Dict[str, Any]) -> None:
        title = f"{category_info['emoji']} 建立客服單 — {category_info['label'][:15]}"
        super().__init__(title=title[:45])
        self.category_key = category_key
        self.category_info = category_info

        self.subject_input = discord.ui.TextInput(
            label="問題主旨 (請簡述您的核心問題)",
            placeholder="例如：指令 /mc 無法連線、檢舉惡意刷頻成員...",
            min_length=2,
            max_length=80,
            required=True,
        )
        self.add_item(self.subject_input)

        self.details_input = discord.ui.TextInput(
            label="詳細情況與問題背景 (越詳細處理越快)",
            placeholder="請描述發生時間、相關成員、錯誤訊息或操作步驟。截圖可於開單後在頻道內上傳。",
            style=discord.TextStyle.paragraph,
            min_length=10,
            max_length=1000,
            required=True,
        )
        self.add_item(self.details_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此功能僅限在伺服器內使用。", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=True)

        # Pre-check active ticket within current guild to prevent race duplicate submission
        active_ticket = await ticket_manager.get_user_active_ticket(
            interaction.guild.id,
            interaction.user.id,
            guild=interaction.guild,
        )
        if active_ticket:
            await interaction.followup.send(
                "⚠️ 您在當前伺服器已有一張進行中的客服單，請先完成諮詢或關閉後再建立新單！",
                ephemeral=True,
            )
            return

        subject = self.subject_input.value.strip()
        details = self.details_input.value.strip()

        created_channel, ticket_rec, err = await ticket_manager.create_ticket_channel(
            guild=interaction.guild,
            user=interaction.user,
            category_key=self.category_key,
            subject=subject,
            details=details,
        )

        if err or not created_channel or not ticket_rec:
            await interaction.followup.send(f"❌ 建立客服單失敗：{err or '未知原因'}", ephemeral=True)
            return

        success_card = ZNCard(
            title="🎫 客服單已成功建立！",
            description=(
                f"您的專屬工單頻道已建立完成：{created_channel.mention}\n\n"
                f"- **工單編號**：`#{ticket_rec.id}`\n"
                f"- **諮詢類別**：{self.category_info['emoji']} **{self.category_info['label']}**\n"
                f"- **問題主旨**：`{subject}`\n\n"
                f"線上客服專員已收到通知，請點擊上方頻道連結前往對話！"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=success_card, ephemeral=True)


# =============================================================================
# View: Ticket Launch Panel View (Components V2)
# =============================================================================

class TicketLaunchView(discord.ui.View):
    """Persistent panel view allowing users to click category buttons to open tickets."""

    def __init__(self) -> None:
        super().__init__(timeout=None)
        for key, info in TICKET_CATEGORIES.items():
            btn = discord.ui.Button(
                label=info["label"],
                emoji=info["emoji"],
                style=info["style"],
                custom_id=f"zn_ticket_btn:{key}",
            )
            btn.callback = self._make_callback(key, info)
            self.add_item(btn)

    def _make_callback(self, cat_key: str, cat_info: Dict[str, Any]):
        async def callback(interaction: discord.Interaction) -> None:
            if not interaction.guild:
                await InteractionResponder.safe_send(interaction, "❌ 此功能僅限在伺服器內使用。", ephemeral=True)
                return

            # Check if user already has an active ticket in this guild (with auto self-healing if channel was deleted)
            active_ticket = await ticket_manager.get_user_active_ticket(
                interaction.guild.id,
                interaction.user.id,
                guild=interaction.guild,
            )
            if active_ticket:
                ch = interaction.guild.get_channel(active_ticket.channel_id)
                ch_text = ch.mention if ch else f"`#{active_ticket.channel_id}`"
                await interaction.response.send_message(
                    f"⚠️ 您在當前伺服器已有一張進行中的客服單：{ch_text}！\n請先在該客服單完成諮詢或關閉後，再建立新的客服單。",
                    ephemeral=True,
                )
                return

            modal = TicketCreateModal(category_key=cat_key, category_info=cat_info)
            await interaction.response.send_modal(modal)

        return callback


# =============================================================================
# View: Ticket Channel Controls View (Components V2)
# =============================================================================

class TicketChannelControlView(discord.ui.View):
    """Persistent control bar inside the ticket channel for staff & user operations."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="鎖定/解鎖頻道",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="zn_tctrl:lock",
    )
    async def lock_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 無法在此頻道執行此操作。", ephemeral=True)
            return

        is_staff = await ticket_manager.is_staff(interaction.guild, interaction.user)
        if not is_staff:
            await interaction.response.send_message("❌ 僅有客服團隊或管理員可以鎖定/解鎖頻道。", ephemeral=True)
            return

        ticket_rec = await ticket_manager.get_ticket_by_channel(interaction.channel.id)
        if not ticket_rec:
            await interaction.response.send_message("❌ 查無當前頻道的客服單紀錄。", ephemeral=True)
            return

        member = interaction.guild.get_member(ticket_rec.user_id)
        if not member:
            await interaction.response.send_message("❌ 找不到此客服單的原開單成員（可能已離開伺服器）。", ephemeral=True)
            return

        current_ow = interaction.channel.overwrites_for(member)
        is_locked = (current_ow.send_messages is False)

        new_send = not is_locked
        current_ow.send_messages = new_send
        try:
            await interaction.channel.set_permissions(member, overwrite=current_ow)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 機器人缺乏頻道管理權限，無法變更權限覆寫。", ephemeral=True)
            return
        except Exception as ex:
            await interaction.response.send_message(f"❌ 變更頻道權限時發生錯誤：{ex}", ephemeral=True)
            return

        action_name = "🔓 已解除頻道鎖定" if new_send else "🔒 已鎖定頻道"
        desc = f"開單成員 {member.mention} 現在{'可以' if new_send else '暫時無法'}在此頻道發送訊息。"
        card = ZNCard(
            title=action_name,
            description=desc,
            status_pill=ZNStatusPill.SUCCESS if new_send else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if new_send else ZNColor.WARNING,
        )
        await interaction.response.send_message(embed=card.to_embed())

    @discord.ui.button(
        label="客服接單 (Claim)",
        emoji="🙋",
        style=discord.ButtonStyle.primary,
        custom_id="zn_tctrl:claim",
    )
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 無法在此頻道執行此操作。", ephemeral=True)
            return

        is_staff = await ticket_manager.is_staff(interaction.guild, interaction.user)
        if not is_staff:
            await interaction.response.send_message("❌ 僅有客服團隊或管理員可以認領接單。", ephemeral=True)
            return

        ticket_rec = await ticket_manager.get_ticket_by_channel(interaction.channel.id)
        if not ticket_rec:
            await interaction.response.send_message("❌ 查無當前頻道的客服單紀錄。", ephemeral=True)
            return

        # Atomically claim the ticket to eliminate concurrency race condition
        success, current_claimer = await ticket_manager.claim_ticket(ticket_rec.id, interaction.user.id)
        if not success:
            claimer = interaction.guild.get_member(current_claimer) if current_claimer else None
            claimer_name = claimer.display_name if claimer else (f"<@{current_claimer}>" if current_claimer else "其他專員")
            await interaction.response.send_message(
                f"ℹ️ 慢了一步！此客服單已由 **{claimer_name}** 接單協助中。",
                ephemeral=True,
            )
            return

        card = ZNCard(
            title="🙋 客服專員已接單",
            description=f"本張客服單已由 {interaction.user.mention} 專責接單處理，將全程協助您解決問題！",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await interaction.response.send_message(embed=card.to_embed())

    @discord.ui.button(
        label="匯出對話紀錄",
        emoji="📜",
        style=discord.ButtonStyle.secondary,
        custom_id="zn_tctrl:transcript",
    )
    async def transcript_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 無法在此頻道執行此操作。", ephemeral=True)
            return

        ticket_rec = await ticket_manager.get_ticket_by_channel(interaction.channel.id)
        if not ticket_rec:
            await interaction.response.send_message("❌ 查無當前頻道的客服單紀錄。", ephemeral=True)
            return

        # Strict permission boundary: only ticket owner or authorized staff can export transcripts
        is_staff = await ticket_manager.is_staff(interaction.guild, interaction.user)
        is_owner = (interaction.user.id == ticket_rec.user_id)
        if not is_staff and not is_owner:
            await interaction.response.send_message(
                "❌ 權限不足：僅有開單成員本人或客服專員可以匯出此工單的對話逐字稿。",
                ephemeral=True,
            )
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        transcript_bytes, filename = await ticket_manager.generate_transcript(interaction.channel)
        file = discord.File(io.BytesIO(transcript_bytes), filename=filename)

        card = ZNCard(
            title="📜 客服單對話逐字稿匯出完成",
            description=f"已成功打包 {interaction.channel.mention} 之完整對話紀錄：",
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        await interaction.followup.send(embed=card.to_embed(), file=file)

    @discord.ui.button(
        label="關閉客服單",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="zn_tctrl:close",
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await InteractionResponder.safe_send(interaction, "❌ 無法在此頻道執行此操作。", ephemeral=True)
            return

        ticket_rec = await ticket_manager.get_ticket_by_channel(interaction.channel.id)
        if not ticket_rec:
            await interaction.response.send_message("❌ 查無當前頻道的客服單紀錄。", ephemeral=True)
            return

        is_staff = await ticket_manager.is_staff(interaction.guild, interaction.user)
        is_owner = (interaction.user.id == ticket_rec.user_id)

        if not is_staff and not is_owner:
            await interaction.response.send_message("❌ 僅有開單者或客服專員可以關閉此工單。", ephemeral=True)
            return

        # Prevent duplicate closing race condition
        if not await ticket_manager.start_closing(interaction.channel.id):
            await interaction.response.send_message(
                "⚠️ 此客服單已在結案關閉流程中，請稍候！",
                ephemeral=True,
            )
            return

        # Confirm close
        close_card = ZNCard(
            title="⚠️ 確認關閉客服單",
            description="本頻道將在 **5 秒鐘後** 進行對話存檔備份並自動刪除。\n感謝您的諮詢！",
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        await interaction.response.send_message(embed=close_card.to_embed())

        await asyncio.sleep(5.0)
        await ticket_manager.close_ticket(interaction.channel, closed_by=interaction.user)


# =============================================================================
# Ticket Manager Core Service
# =============================================================================

class TicketManager:
    """Core domain service for managing ticket configs, channels, and records."""

    def __init__(self) -> None:
        self._create_locks: Dict[Tuple[int, int], asyncio.Lock] = {}
        self._closing_channels: set[int] = set()
        self._state_lock: asyncio.Lock = asyncio.Lock()

    async def _get_create_lock(self, guild_id: int, user_id: int) -> asyncio.Lock:
        async with self._state_lock:
            key = (guild_id, user_id)
            if key not in self._create_locks:
                self._create_locks[key] = asyncio.Lock()
            return self._create_locks[key]

    async def is_closing(self, channel_id: int) -> bool:
        async with self._state_lock:
            return channel_id in self._closing_channels

    async def start_closing(self, channel_id: int) -> bool:
        async with self._state_lock:
            if channel_id in self._closing_channels:
                return False
            self._closing_channels.add(channel_id)
            return True

    async def stop_closing(self, channel_id: int) -> None:
        async with self._state_lock:
            self._closing_channels.discard(channel_id)

    async def get_or_create_config(self, guild_id: int) -> TicketConfig:
        async with db.session() as session:
            stmt = select(TicketConfig).where(TicketConfig.guild_id == guild_id)
            res = await session.execute(stmt)
            cfg = res.scalars().first()
            if not cfg:
                cfg = TicketConfig(guild_id=guild_id)
                session.add(cfg)
                await session.commit()
                await session.refresh(cfg)
            return cfg

    async def update_config(
        self,
        guild_id: int,
        support_role_id: Optional[int] = None,
        category_id: Optional[int] = None,
        log_channel_id: Optional[int] = None,
        panel_channel_id: Optional[int] = None,
    ) -> TicketConfig:
        async with db.session() as session:
            stmt = select(TicketConfig).where(TicketConfig.guild_id == guild_id)
            res = await session.execute(stmt)
            cfg = res.scalars().first()
            if not cfg:
                cfg = TicketConfig(guild_id=guild_id)
                session.add(cfg)

            if support_role_id is not None:
                cfg.support_role_id = support_role_id
            if category_id is not None:
                cfg.category_id = category_id
            if log_channel_id is not None:
                cfg.log_channel_id = log_channel_id
            if panel_channel_id is not None:
                cfg.panel_channel_id = panel_channel_id

            await session.commit()
            await session.refresh(cfg)
            return cfg

    async def is_staff(self, guild: discord.Guild, user: discord.User | discord.Member) -> bool:
        """Determines if a user/member has staff privileges in the ticket system."""
        member = user if isinstance(user, discord.Member) else guild.get_member(user.id)
        if not member:
            try:
                member = await guild.fetch_member(user.id)
            except Exception:
                return False

        if getattr(getattr(member, "guild_permissions", None), "administrator", False):
            return True
        if getattr(getattr(member, "guild_permissions", None), "manage_guild", False):
            return True

        cfg = await self.get_or_create_config(guild.id)
        if cfg.support_role_id and hasattr(member, "roles") and any(r.id == cfg.support_role_id for r in member.roles):
            return True
        return False

    async def get_user_active_ticket(
        self,
        guild_id: int,
        user_id: int,
        guild: Optional[discord.Guild] = None,
    ) -> Optional[TicketRecord]:
        """Retrieves active ticket for a user. If guild is provided and channel was deleted, auto self-heals DB."""
        async with db.session() as session:
            stmt = (
                select(TicketRecord)
                .where(
                    TicketRecord.guild_id == guild_id,
                    TicketRecord.user_id == user_id,
                    TicketRecord.status.in_(["OPEN", "CLAIMED"]),
                )
                .order_by(TicketRecord.id.desc())
            )
            res = await session.execute(stmt)
            ticket = res.scalars().first()

        if ticket and guild:
            # Check if channel still exists in Discord cache or API
            ch = guild.get_channel(ticket.channel_id)
            if ch is None:
                channel_alive = False
                try:
                    await guild.fetch_channel(ticket.channel_id)
                    channel_alive = True
                except (discord.NotFound, discord.Forbidden):
                    channel_alive = False
                except Exception as ex:
                    log.warning(f"Error fetching channel {ticket.channel_id} during self-heal check: {ex}")
                    channel_alive = True

                if not channel_alive:
                    log.warning(f"自癒修復：工單 #{ticket.id} 對應之頻道 {ticket.channel_id} 已手動刪除，自動結案。")
                    async with db.session() as session:
                        up_stmt = (
                            update(TicketRecord)
                            .where(TicketRecord.id == ticket.id)
                            .values(
                                status="CLOSED",
                                closed_at=datetime.now(timezone.utc),
                                details=ticket.details + "\n[系統自癒：頻道已被手動刪除，自動結案]",
                            )
                        )
                        await session.execute(up_stmt)
                        await session.commit()
                    return None

        return ticket

    async def get_ticket_by_channel(self, channel_id: int) -> Optional[TicketRecord]:
        async with db.session() as session:
            stmt = select(TicketRecord).where(TicketRecord.channel_id == channel_id)
            res = await session.execute(stmt)
            return res.scalars().first()

    async def mark_channel_deleted(self, channel_id: int) -> Optional[TicketRecord]:
        """Marks a ticket as CLOSED if its Discord channel was deleted manually."""
        async with db.session() as session:
            stmt = select(TicketRecord).where(
                TicketRecord.channel_id == channel_id,
                TicketRecord.status.in_(["OPEN", "CLAIMED"]),
            )
            res = await session.execute(stmt)
            rec = res.scalars().first()
            if rec:
                up_stmt = (
                    update(TicketRecord)
                    .where(TicketRecord.id == rec.id)
                    .values(
                        status="CLOSED",
                        closed_at=datetime.now(timezone.utc),
                        details=rec.details + "\n[系統事件：Discord 頻道已被手動刪除，自動結案存檔]",
                    )
                )
                await session.execute(up_stmt)
                await session.commit()
                await session.refresh(rec)
                return rec
        return None

    async def claim_ticket(self, ticket_id: int, staff_id: int) -> Tuple[bool, Optional[int]]:
        """Atomically claims a ticket using conditional update to prevent race conditions."""
        async with db.session() as session:
            stmt = (
                update(TicketRecord)
                .where(
                    TicketRecord.id == ticket_id,
                    TicketRecord.claimed_by_id.is_(None),
                    TicketRecord.status == "OPEN",
                )
                .values(status="CLAIMED", claimed_by_id=staff_id)
            )
            res = await session.execute(stmt)
            if res.rowcount and res.rowcount > 0:
                await session.commit()
                return True, staff_id

            # Atomic claim failed: check who claimed it
            await session.rollback()
            check_stmt = select(TicketRecord).where(TicketRecord.id == ticket_id)
            check_res = await session.execute(check_stmt)
            current_rec = check_res.scalars().first()
            current_claimer = current_rec.claimed_by_id if current_rec else None
            return False, current_claimer

    def build_panel_card(self, guild_name: str) -> ZNCard:
        """Constructs the authoritative, beautifully formatted Ticket Panel card."""
        desc = (
            f"歡迎來到 **{guild_name}** 客戶服務與專屬諮詢中心！\n\n"
            f"點擊下方對應諮詢類別的按鈕，即可建立由工作人員一對一服務的**專屬私密頻道**。\n\n"
            f"📋 **諮詢類別說明**：\n"
            f"• 🛠️ **技術支援與Bug回報**：機器人運行異常、程式錯誤或技術疑難。\n"
            f"• 🚨 **違規檢舉與申訴**：回報騷擾、惡意洗版、伺服器規章違規或禁言處置申訴。\n"
            f"• 💬 **一般諮詢與合作**：社群活動、身分組權益、商業合作或功能建議。\n"
            f"• 💰 **贊助與售後服務**：贊助福利發放、特權開通或帳務諮詢。\n\n"
            f"💡 **開單須知**：\n"
            f"1. 每位成員同時僅能開啟一張進行中的客服單。\n"
            f"2. 請在開單表單中簡要說明問題，開單後可直接在頻道內傳送截圖或檔案。\n"
            f"3. 請保持彼此尊重與禮貌，客服專員將於上線後以最快速度為您解答！"
        )
        return ZNCard(
            title=f"🎫 {guild_name} • 客戶服務中心",
            description=desc,
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
            footer_text="ZeroNexus Components V2 • 智慧客服單系統",
        )

    async def create_ticket_channel(
        self,
        guild: discord.Guild,
        user: discord.Member,
        category_key: str,
        subject: str,
        details: str,
    ) -> Tuple[Optional[discord.TextChannel], Optional[TicketRecord], Optional[str]]:
        """Creates an isolated text channel with proper overwrites and records it in DB with mutex protection."""
        user_lock = await self._get_create_lock(guild.id, user.id)
        async with user_lock:
            # Double-check active ticket within mutex to eliminate creation race conditions
            existing = await self.get_user_active_ticket(guild.id, user.id, guild=guild)
            if existing:
                return None, None, "您在當前伺服器已有一張進行中的客服單，無法重複建立！"

            cfg = await self.get_or_create_config(guild.id)

            # Atomically increment counter
            async with db.session() as session:
                stmt = (
                    update(TicketConfig)
                    .where(TicketConfig.guild_id == guild.id)
                    .values(ticket_counter=TicketConfig.ticket_counter + 1)
                )
                await session.execute(stmt)
                await session.commit()

            cfg = await self.get_or_create_config(guild.id)
            ticket_num = cfg.ticket_counter

            cat_info = TICKET_CATEGORIES.get(category_key, TICKET_CATEGORIES["general"])
            clean_user = "".join(c for c in user.name.lower() if c.isalnum() or c in "-_")[:10]
            channel_name = f"ticket-{ticket_num:03d}-{clean_user}"

            # Setup isolated permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    manage_channels=True,
                    manage_messages=True,
                    read_message_history=True,
                ),
            }

            support_role = guild.get_role(cfg.support_role_id) if cfg.support_role_id else None
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                )

            parent_category = guild.get_channel(cfg.category_id) if cfg.category_id else None
            if not isinstance(parent_category, discord.CategoryChannel):
                parent_category = None

            try:
                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=parent_category,
                    overwrites=overwrites,
                    topic=f"ZeroNexus 客服單 #{ticket_num} | 開單者: {user} ({user.id}) | 類別: {cat_info['label']}",
                )
            except Exception as ex:
                log.error(f"Failed to create ticket channel: {ex}")
                return None, None, f"Discord 權限不足或無法建立頻道: {ex}"

            # Persist ticket record
            async with db.session() as session:
                rec = TicketRecord(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    user_id=user.id,
                    category=cat_info["label"],
                    subject=subject,
                    details=details,
                    status="OPEN",
                )
                session.add(rec)
                await session.commit()
                await session.refresh(rec)

            # Send welcome message inside ticket channel
            role_mention = support_role.mention if support_role else "@線上客服"
            welcome_card = ZNCard(
                title=f"{cat_info['emoji']} 客服單 #{ticket_num:03d} — {cat_info['label']}",
                description=(
                    f"您好 {user.mention}！您的專屬客服單已建立完成。\n\n"
                    f"📌 **問題主旨**：`{subject}`\n"
                    f"📝 **詳細說明**：\n> {details}\n\n"
                    f"線上客服團隊 {role_mention} 已收到通知，將盡速為您提供協助。\n"
                    f"在等待期間，您可以直接在此頻道補充更多截圖、日誌或詳細情境！\n\n"
                    f"下方附帶快捷管理工具，供開單者與客服專員使用："
                ),
                status_pill=ZNStatusPill.PROCESSING,
                color=ZNColor.PRIMARY,
                footer_text=f"ZeroNexus 工單系統 • 開單時間：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            )
            ctrl_view = TicketChannelControlView()
            await channel.send(
                content=f"{user.mention} {role_mention}",
                embed=welcome_card.to_embed(),
                view=ctrl_view,
            )

            return channel, rec, None

    async def generate_transcript(self, channel: discord.TextChannel) -> Tuple[bytes, str]:
        """Generates a clean, readable Markdown transcript from channel message history."""
        messages: List[discord.Message] = []
        try:
            async for msg in channel.history(limit=500, oldest_first=True):
                messages.append(msg)
        except Exception as he:
            log.warning(f"Could not read message history for transcript in channel {channel.id}: {he}")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        filename = f"transcript_{channel.name}_{now_str}.md"

        lines = [
            f"# ZeroNexus 客服單歷史逐字稿 — #{channel.name}",
            f"- **伺服器**：{channel.guild.name} (`{channel.guild.id}`)",
            f"- **頻道**：{channel.name} (`{channel.id}`)",
            f"- **匯出時間**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"- **總訊息數**：{len(messages)} 則",
            "=" * 70,
            "",
        ]

        for m in messages:
            ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author_tag = f"{m.author.display_name} ({m.author})"
            bot_tag = " [BOT]" if m.author.bot else ""
            lines.append(f"[{ts}] {author_tag}{bot_tag}:")
            if m.content:
                lines.append(f"  {m.content}")
            for a in m.attachments:
                lines.append(f"  📎 附件：{a.filename} ({a.url})")
            for e in m.embeds:
                if e.title or e.description:
                    lines.append(f"  📑 內嵌卡片：{e.title or ''} - {e.description or ''}")
            lines.append("")

        content_bytes = "\n".join(lines).encode("utf-8")
        return content_bytes, filename

    async def close_ticket(
        self,
        channel: discord.TextChannel,
        closed_by: discord.Member | discord.User,
    ) -> bool:
        """Generates transcript, logs to log channel, marks DB record CLOSED, and deletes channel."""
        try:
            rec = await self.get_ticket_by_channel(channel.id)
            cfg = await self.get_or_create_config(channel.guild.id)

            transcript_bytes, filename = b"", ""
            try:
                transcript_bytes, filename = await self.generate_transcript(channel)
            except Exception as tr_err:
                log.warning(f"Failed to generate transcript for channel {channel.name}: {tr_err}")

            # Dispatch to log channel if configured
            if cfg.log_channel_id and transcript_bytes:
                log_ch = channel.guild.get_channel(cfg.log_channel_id)
                if isinstance(log_ch, discord.TextChannel):
                    try:
                        file = discord.File(io.BytesIO(transcript_bytes), filename=filename)
                        log_card = ZNCard(
                            title=f"📦 客服單結案存檔 — #{channel.name}",
                            description=(
                                f"- **工單編號**：`#{rec.id if rec else '未知'}`\n"
                                f"- **諮詢類別**：{rec.category if rec else '一般諮詢'}\n"
                                f"- **開單成員**：<@{rec.user_id if rec else 0}>\n"
                                f"- **結案人員**：{getattr(closed_by, 'mention', str(closed_by))}\n"
                                f"- **結案時間**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            ),
                            status_pill=ZNStatusPill.SUCCESS,
                            color=ZNColor.DARK,
                        )
                        await log_ch.send(embed=log_card.to_embed(), file=file)
                    except Exception as le:
                        log.warning(f"Failed to send ticket transcript to log channel: {le}")

            # Update database record
            if rec:
                async with db.session() as session:
                    stmt = (
                        update(TicketRecord)
                        .where(TicketRecord.id == rec.id)
                        .values(
                            status="CLOSED",
                            closed_at=datetime.now(timezone.utc),
                            closed_by_id=closed_by.id,
                        )
                    )
                    await session.execute(stmt)
                    await session.commit()

            # Delete channel safely
            try:
                await channel.delete(reason=f"ZeroNexus 客服單結案，由 {closed_by} 執行關閉")
                return True
            except discord.NotFound:
                log.info(f"Ticket channel {channel.id} was already deleted on Discord.")
                return True
            except Exception as de:
                log.error(f"Failed to delete ticket channel: {de}")
                return False
        finally:
            await self.stop_closing(channel.id)


ticket_manager = TicketManager()
