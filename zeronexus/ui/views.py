"""ZeroNexus Interactive Discord Components V2 Views."""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, List, Optional, Union

import discord

from zeronexus.ui.components import DebounceGuard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor

log = logging.getLogger("zeronexus.ui.views")


class ZNConfirmView(discord.ui.View):
    """Two-button safety confirmation modal view with author protection, double-click lock, and 60s timeout."""

    def __init__(
        self,
        author_id: int,
        confirm_label: str = "確認執行",
        cancel_label: str = "取消操作",
        is_dangerous: bool = True,
        timeout: float = 60.0,
        debounce_interval: float = 0.35,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed: Optional[bool] = None
        self.message: Optional[discord.Message] = None
        self._last_interaction: Optional[discord.Interaction] = None
        self.guard = DebounceGuard(cooldown=debounce_interval)
        self._lock = self.guard._lock  # Backward compatibility alias

        confirm_style = discord.ButtonStyle.danger if is_dangerous else discord.ButtonStyle.primary
        self.confirm_button = discord.ui.Button(
            label=confirm_label,
            style=confirm_style,
            custom_id="zn_confirm_action",
        )
        self.confirm_button.callback = self._on_confirm
        self.add_item(self.confirm_button)

        self.cancel_button = discord.ui.Button(
            label=cancel_label,
            style=discord.ButtonStyle.secondary,
            custom_id="zn_cancel_action",
        )
        self.cancel_button.callback = self._on_cancel
        self.add_item(self.cancel_button)

    def _disable_all(self) -> None:
        """Universal component disabling across all interactive items."""
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(
                interaction,
                "👋 這是一項專屬的操作確認，只有發起此指令的夥伴才可以點擊喔！",
                ephemeral=True,
            )
            return False
        return True

    async def _on_confirm(self, interaction: discord.Interaction) -> None:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if InteractionResponder.is_interaction_expired(interaction):
            return

        if self.confirmed is not None or self.guard.is_locked:
            await InteractionResponder.safe_defer(interaction)
            return

        can_proceed = await self.guard.check_and_acquire(interaction)
        if not can_proceed:
            return

        try:
            if self.confirmed is not None:
                await InteractionResponder.safe_defer(interaction)
                return

            self.confirmed = True
            self._disable_all()
            await InteractionResponder.safe_edit(interaction, view=self)
            self.stop()
        finally:
            self.guard.release()

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if InteractionResponder.is_interaction_expired(interaction):
            return

        if self.confirmed is not None or self.guard.is_locked:
            await InteractionResponder.safe_defer(interaction)
            return

        can_proceed = await self.guard.check_and_acquire(interaction)
        if not can_proceed:
            return

        try:
            if self.confirmed is not None:
                await InteractionResponder.safe_defer(interaction)
                return

            self.confirmed = False
            self._disable_all()
            from zeronexus.ui.card import ZNCard
            card = ZNCard(
                title="已為您取消操作",
                description="👌 本次操作已安全中止，未對伺服器進行任何變更，敬請放心！隨時歡迎再次使用。",
                status_pill="⚪",
                color=ZNColor.DARK,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=None)
            self.stop()
        finally:
            self.guard.release()

    async def on_timeout(self) -> None:
        self.timed_out = True
        self._disable_all()
        self.stop()
        from zeronexus.ui.card import ZNCard
        timeout_card = ZNCard(
            title="操作已逾時",
            description="⏱️ 操作已逾時（60 秒），已安全自動取消，未對伺服器進行任何變更。",
            status_pill="⚪",
            color=ZNColor.DARK,
        )
        if self.message:
            try:
                await self.message.edit(embed=timeout_card.to_embed(), view=self)
                return
            except Exception:
                pass
        if self._last_interaction:
            await InteractionResponder.safe_edit(self._last_interaction, card=timeout_card, view=self)


class ZNPaginatedView(discord.ui.LayoutView):
    """Reusable multi-page navigator using native Discord Components V2 with anti-concurrency lock and debouncing."""

    def __init__(
        self,
        pages: List[Any],
        author_id: int,
        timeout: float = 120.0,
        debounce_interval: float = 0.35,
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages or []
        self.author_id = author_id
        self.current_page: int = 0
        self.message: Optional[discord.Message] = None
        self._last_interaction: Optional[discord.Interaction] = None
        self.guard = DebounceGuard(cooldown=debounce_interval)
        self._lock = self.guard._lock  # Backward compatibility alias

        self.prev_button = discord.ui.Button(
            label="◀️ 上一頁",
            style=discord.ButtonStyle.secondary,
            custom_id="zn_page_prev",
        )
        self.prev_button.callback = self._on_prev

        total_pages = max(1, len(self.pages))
        self.indicator_button = discord.ui.Button(
            label=f"1 / {total_pages}" if self.pages else "0 / 0",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            custom_id="zn_page_indicator",
        )

        self.next_button = discord.ui.Button(
            label="下一頁 ▶️",
            style=discord.ButtonStyle.secondary,
            custom_id="zn_page_next",
        )
        self.next_button.callback = self._on_next

        self._update_components()

    def _update_button_states(self) -> None:
        """Updates pagination button states based on current_page and total pages."""
        if not self.pages:
            self.prev_button.disabled = True
            self.next_button.disabled = True
            self.indicator_button.label = "0 / 0"
        else:
            if self.current_page >= len(self.pages):
                self.current_page = max(0, len(self.pages) - 1)
            elif self.current_page < 0:
                self.current_page = 0
            self.prev_button.disabled = (self.current_page <= 0)
            self.next_button.disabled = (self.current_page >= len(self.pages) - 1)
            self.indicator_button.label = f"{self.current_page + 1} / {len(self.pages)}"

    def _disable_all(self) -> None:
        """Universal component disabling across all interactive items."""
        for child in self.walk_children():
            if hasattr(child, "disabled"):
                child.disabled = True
        for child in self.children:
            child.disabled = True

    def _update_components(self) -> None:
        """Reconstructs the Components V2 Container and ActionRow for the active page."""
        self.clear_items()
        from zeronexus.ui.card import ZNCard, strip_markdown_headings

        self._update_button_states()

        if not self.pages:
            c = discord.ui.Container(accent_color=ZNColor.DARK)
            c.disabled = False
            c.add_item(discord.ui.TextDisplay("### 📭 目前暫無內容\n此處目前沒有可供瀏覽的分頁資料。"))
            nav_row = discord.ui.ActionRow(self.prev_button, self.indicator_button, self.next_button)
            c.add_item(nav_row)
            self.add_item(c)
            return

        page = self.pages[self.current_page]

        if isinstance(page, ZNCard):
            accent = page.color
            pill = getattr(page.status_pill, "value", str(page.status_pill)) if page.status_pill else ""
            clean_title = strip_markdown_headings(page.title)
            header_text = f"### {pill} {clean_title}".strip() if pill else f"### {clean_title}"

            c = discord.ui.Container(accent_color=accent)
            if page.thumbnail_url:
                sec_items: List[Union[str, discord.ui.Item]] = [discord.ui.TextDisplay(header_text)]
                if page.subtitle:
                    sec_items.append(discord.ui.TextDisplay(f"*{strip_markdown_headings(page.subtitle)}*"))
                c.add_item(discord.ui.Section(*sec_items, accessory=discord.ui.Thumbnail(page.thumbnail_url)))
            else:
                c.add_item(discord.ui.TextDisplay(header_text))
                if page.subtitle:
                    c.add_item(discord.ui.TextDisplay(f"*{strip_markdown_headings(page.subtitle)}*"))
            c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))

            if page.description:
                c.add_item(discord.ui.TextDisplay(page.description))
            for sec in page.sections:
                c.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
                c.add_item(discord.ui.TextDisplay(f"**{sec.name}**\n{sec.value}"))
            if page.footer_text:
                c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
                c.add_item(discord.ui.TextDisplay(f"-# {page.footer_text}"))
        elif isinstance(page, discord.Embed):
            accent = page.color or discord.Color.blue()
            c = discord.ui.Container(accent_color=accent)
            has_thumb = bool(getattr(page, "thumbnail", None) and getattr(page.thumbnail, "url", None))
            header_title = f"### {strip_markdown_headings(page.title)}" if page.title else "### ZeroNexus"
            if has_thumb:
                c.add_item(discord.ui.Section(discord.ui.TextDisplay(header_title), accessory=discord.ui.Thumbnail(page.thumbnail.url)))
            else:
                c.add_item(discord.ui.TextDisplay(header_title))
            c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            if page.description:
                c.add_item(discord.ui.TextDisplay(page.description))
            for f in getattr(page, "fields", []):
                c.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
                c.add_item(discord.ui.TextDisplay(f"**{f.name}**\n{f.value}"))
            if getattr(page, "footer", None) and getattr(page.footer, "text", None):
                c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
                c.add_item(discord.ui.TextDisplay(f"-# {page.footer.text}"))
        else:
            c = discord.ui.Container(accent_color=discord.Color.blue())
            c.add_item(discord.ui.TextDisplay(f"### 頁面 {self.current_page + 1}"))
            c.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            c.add_item(discord.ui.TextDisplay(str(page)))

        c.disabled = False

        # Attach buttons into Container via ActionRow
        nav_row = discord.ui.ActionRow(self.prev_button, self.indicator_button, self.next_button)
        c.add_item(nav_row)

        self.add_item(c)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(
                interaction,
                "👋 這是其他成員瀏覽中的專屬分頁面板，若您也想查看，歡迎親自發起指令探索喔！",
                ephemeral=True,
            )
            return False
        return True

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if InteractionResponder.is_interaction_expired(interaction):
            return

        if self.guard.is_locked:
            await InteractionResponder.safe_defer(interaction)
            return

        can_proceed = await self.guard.check_and_acquire(interaction)
        if not can_proceed:
            return

        try:
            if not self.pages:
                await InteractionResponder.safe_defer(interaction)
                return

            if self.current_page > 0:
                old_page = self.current_page
                self.current_page -= 1
                self._update_components()
                success = await InteractionResponder.safe_edit(
                    interaction,
                    view=self,
                )
                if not success:
                    # Rollback state on edit failure
                    self.current_page = old_page
                    self._update_components()
            else:
                await InteractionResponder.safe_defer(interaction)
        finally:
            self.guard.release()

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if InteractionResponder.is_interaction_expired(interaction):
            return

        if self.guard.is_locked:
            await InteractionResponder.safe_defer(interaction)
            return

        can_proceed = await self.guard.check_and_acquire(interaction)
        if not can_proceed:
            return

        try:
            if not self.pages:
                await InteractionResponder.safe_defer(interaction)
                return

            if self.current_page < len(self.pages) - 1:
                old_page = self.current_page
                self.current_page += 1
                self._update_components()
                success = await InteractionResponder.safe_edit(
                    interaction,
                    view=self,
                )
                if not success:
                    # Rollback state on edit failure
                    self.current_page = old_page
                    self._update_components()
            else:
                await InteractionResponder.safe_defer(interaction)
        finally:
            self.guard.release()

    async def on_timeout(self) -> None:
        self._disable_all()
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
                return
            except Exception:
                pass
        if self._last_interaction:
            await InteractionResponder.safe_edit(self._last_interaction, view=self)


class ZNSelectView(discord.ui.View):
    """Generic dropdown select menu view with custom callback handler and anti-concurrency lock."""

    def __init__(
        self,
        placeholder: str,
        options: List[discord.SelectOption],
        author_id: int,
        callback_handler: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
        timeout: float = 60.0,
        debounce_interval: float = 0.35,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.handler = callback_handler
        self.message: Optional[discord.Message] = None
        self._last_interaction: Optional[discord.Interaction] = None
        self.guard = DebounceGuard(cooldown=debounce_interval)
        self._lock = self.guard._lock  # Backward compatibility alias

        self.select_menu = discord.ui.Select(
            placeholder=placeholder,
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select_menu.callback = self._on_select
        self.add_item(self.select_menu)

    def _disable_all(self) -> None:
        """Universal component disabling across all interactive items."""
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(
                interaction,
                "👋 這個選單目前專屬於指令發起者操作，若您也想調整，歡迎親自發起指令喔！",
                ephemeral=True,
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if self.message is None and getattr(interaction, "message", None) is not None:
            self.message = interaction.message
        self._last_interaction = interaction

        if InteractionResponder.is_interaction_expired(interaction):
            return

        if self.guard.is_locked:
            await InteractionResponder.safe_defer(interaction)
            return

        can_proceed = await self.guard.check_and_acquire(interaction)
        if not can_proceed:
            return

        try:
            if not self.select_menu.values:
                await InteractionResponder.safe_defer(interaction)
                return

            selected_value = self.select_menu.values[0]
            try:
                await self.handler(interaction, selected_value)
            except Exception as e:
                log.error(f"Error in ZNSelectView handler: {e}", exc_info=True)
                await InteractionResponder.safe_error(interaction, e)
        finally:
            self.guard.release()

    async def on_timeout(self) -> None:
        self._disable_all()
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
                return
            except Exception:
                pass
        if self._last_interaction:
            await InteractionResponder.safe_edit(self._last_interaction, view=self)



class ZNModal(discord.ui.Modal):
    """Base modal class with automated error handling and dead token defense."""

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error(f"Unhandled error in modal '{self.title}': {error}", exc_info=True)
        await InteractionResponder.safe_error(interaction, error)
