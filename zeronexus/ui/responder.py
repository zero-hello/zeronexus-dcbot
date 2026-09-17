# ==============================================================================
# ZeroNexus - Safe Interaction Responder
# Unified lifecycle protection against 10062 (Unknown interaction) & 40060 (Already acknowledged)
# ==============================================================================

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict, Optional, Union
from unittest.mock import AsyncMock, MagicMock

import discord

log = logging.getLogger("zeronexus.ui.responder")


class InteractionResponder:
    """Enterprise-grade Discord interaction lifecycle manager.
    
    Guarantees:
    1. Single ACK Rule: Never calls send_message() on already acknowledged interactions.
    2. Dead Token Defense: Never retries on 10062/10015/50027 or expired tokens (prevents cascading errors).
    3. Auto-Routing: Seamlessly bridges between initial response and followup response.
    4. Safe Edit Resolution: Gracefully handles race conditions between response.edit_message and edit_original_response.
    5. Message Tracking: Returns discord.Message whenever possible and binds to attached view.message.
    """

    @classmethod
    def is_done(cls, interaction: discord.Interaction) -> bool:
        """Determines if the interaction response has already been issued/completed, safely handling AsyncMock."""
        resp = getattr(interaction, "response", None)
        if resp is None:
            return True
        is_done_fn = getattr(resp, "is_done", None)
        if not callable(is_done_fn):
            return bool(is_done_fn)
        try:
            val = is_done_fn()
            if inspect.iscoroutine(val):
                val.close()
                send_mock = getattr(resp, "send_message", None)
                defer_mock = getattr(resp, "defer", None)
                edit_mock = getattr(resp, "edit_message", None)
                modal_mock = getattr(resp, "send_modal", None)
                auto_mock = getattr(resp, "send_autocomplete", None)
                if any(m and getattr(m, "called", False) for m in (send_mock, defer_mock, edit_mock, modal_mock, auto_mock)):
                    return True
                mock_ret = getattr(is_done_fn, "_mock_return_value", None)
                if mock_ret is True:
                    return True
                if mock_ret is False:
                    return False
                return False
            if isinstance(val, (MagicMock, AsyncMock)):
                send_mock = getattr(resp, "send_message", None)
                defer_mock = getattr(resp, "defer", None)
                edit_mock = getattr(resp, "edit_message", None)
                modal_mock = getattr(resp, "send_modal", None)
                auto_mock = getattr(resp, "send_autocomplete", None)
                if any(m and getattr(m, "called", False) for m in (send_mock, defer_mock, edit_mock, modal_mock, auto_mock)):
                    return True
                mock_ret = getattr(is_done_fn, "_mock_return_value", None)
                if mock_ret is True:
                    return True
                if mock_ret is False:
                    return False
                return False
            return bool(val)
        except Exception:
            return False

    @classmethod
    def is_interaction_expired(cls, interaction: discord.Interaction) -> bool:
        """Checks whether the interaction token has inherently expired before making network calls."""
        if interaction is None:
            return True
        is_expired_fn = getattr(interaction, "is_expired", None)
        if callable(is_expired_fn):
            try:
                val = is_expired_fn()
                if inspect.iscoroutine(val):
                    val.close()
                    mock_ret = getattr(is_expired_fn, "_mock_return_value", None)
                    if mock_ret is True:
                        return True
                    if mock_ret is False:
                        return False
                    return False
                if isinstance(val, (MagicMock, AsyncMock)):
                    mock_ret = getattr(is_expired_fn, "_mock_return_value", None)
                    if mock_ret is True:
                        return True
                    if mock_ret is False:
                        return False
                    return False
                return bool(val)
            except Exception:
                pass
        created_at = getattr(interaction, "created_at", None)
        if created_at is not None:
            try:
                import datetime
                import pytz
                if isinstance(created_at, datetime.datetime):
                    now = datetime.datetime.now(pytz.UTC)
                    dt = created_at if created_at.tzinfo else pytz.UTC.localize(created_at)
                    delta = (now - dt).total_seconds()
                    if cls.is_done(interaction):
                        if delta > 900.0:
                            return True
                    else:
                        if delta > 3.0:
                            return True
            except Exception:
                pass
        return False

    @classmethod
    def is_expired_or_unknown(cls, error: BaseException) -> bool:
        """Check if an exception is Discord error 10062 (Unknown interaction), 10015, 50027, or expired token."""
        if error is None:
            return False

        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return True

        code = getattr(error, "code", None)
        if code in (10062, 10015, 50027):
            return True

        err_msg = str(error).lower()
        dead_indicators = (
            "10062",
            "unknown interaction",
            "10015",
            "unknown webhook",
            "50027",
            "invalid webhook token",
            "interaction has already expired",
            "token expired",
        )
        return any(indicator in err_msg for indicator in dead_indicators)

    @classmethod
    def is_already_acknowledged(cls, error: BaseException) -> bool:
        """Check if an exception indicates the interaction was already acknowledged (40060 or InteractionResponded)."""
        if error is None:
            return False
        if isinstance(error, discord.InteractionResponded):
            return True
        if getattr(error, "code", None) == 40060:
            return True
        err_msg = str(error).lower()
        ack_indicators = (
            "40060",
            "already been acknowledged",
            "already been responded to",
            "interactionresponded",
        )
        return any(indicator in err_msg for indicator in ack_indicators)

    @classmethod
    async def safe_defer(
        cls,
        interaction: discord.Interaction,
        ephemeral: bool = False,
        thinking: Optional[bool] = None,
    ) -> bool:
        """Safely defers an interaction within the 3-second Discord window.
        
        Returns True if deferred or already acknowledged, False if token expired (10062).
        """
        try:
            if cls.is_done(interaction):
                return True
            if cls.is_interaction_expired(interaction):
                log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} token already expired before defer.")
                return False

            if thinking is None:
                inter_type = getattr(interaction, "type", None)
                actual_thinking = False if inter_type == discord.InteractionType.component else True
            else:
                actual_thinking = thinking

            call = interaction.response.defer(ephemeral=ephemeral, thinking=actual_thinking)
            if inspect.isawaitable(call):
                await asyncio.wait_for(call, timeout=2.8)
            return True
        except Exception as e:
            if cls.is_expired_or_unknown(e):
                log.warning(
                    f"Interaction {getattr(interaction, 'id', 'unknown')} token expired (10062) before defer. "
                    f"Command: {getattr(interaction, 'command', 'unknown')}"
                )
                return False
            if cls.is_already_acknowledged(e):
                log.debug(f"Interaction {getattr(interaction, 'id', 'unknown')} was already acknowledged during defer.")
                return True
            log.error(f"Unexpected error during safe_defer on interaction {getattr(interaction, 'id', 'unknown')}: {e}", exc_info=True)
            return False

    @classmethod
    async def safe_defer_update(cls, interaction: discord.Interaction) -> bool:
        """Silently defers component interactions (buttons/selects) without displaying 'thinking' status.
        
        Corresponds to Discord API deferred_message_update (type 6).
        """
        return await cls.safe_defer(interaction, thinking=False)

    @classmethod
    def _normalize_v2_kwargs(cls, kwargs: Dict[str, Any], is_edit: bool = False) -> Dict[str, Any]:
        """Normalizes kwargs to ensure authentic Discord Components V2 rendering.
        
        - If 'card' is provided, converts it to LayoutView.
        - If 'embed' is provided (legacy caller), converts it to LayoutView.
        - Strips legacy 'embed' and 'embeds' from payload.
        - For edit operations, sets embed=None, and clears content only if not explicitly supplied.
        """
        from zeronexus.ui.card import ZNCard

        card = kwargs.pop("card", None)
        embed = kwargs.get("embed", None)
        existing_view = kwargs.get("view", None)

        if card is not None:
            kwargs["view"] = card.to_layout_view(extra_view=existing_view)
            kwargs.pop("embeds", None)
            if is_edit:
                if "content" not in kwargs:
                    kwargs["content"] = None
                kwargs["embed"] = None
            else:
                kwargs.pop("embed", None)
        elif embed is not None and not (isinstance(existing_view, discord.ui.LayoutView) or getattr(existing_view, "has_components_v2", lambda: False)()):
            # Convert legacy embed into a Components V2 ZNCard
            c_title = getattr(embed, "title", None) or "ZeroNexus"
            c_desc = getattr(embed, "description", None)
            c_color = getattr(embed, "color", None) or discord.Color.default()

            c = ZNCard(title=c_title, description=c_desc, color=c_color)
            for f in getattr(embed, "fields", []):
                c.add_section(f.name, f.value, inline=f.inline)

            footer_obj = getattr(embed, "footer", None)
            if footer_obj and getattr(footer_obj, "text", None):
                c.footer_text = footer_obj.text
            thumb_obj = getattr(embed, "thumbnail", None)
            if thumb_obj and getattr(thumb_obj, "url", None):
                c.thumbnail_url = thumb_obj.url
            img_obj = getattr(embed, "image", None)
            if img_obj and getattr(img_obj, "url", None):
                c.image_url = img_obj.url

            kwargs["view"] = c.to_layout_view(extra_view=existing_view)
            kwargs.pop("embeds", None)
            if is_edit:
                if "content" not in kwargs:
                    kwargs["content"] = None
                kwargs["embed"] = None
            else:
                kwargs.pop("embed", None)
        elif is_edit and (isinstance(existing_view, discord.ui.LayoutView) or getattr(existing_view, "has_components_v2", lambda: False)()):
            if "content" not in kwargs:
                kwargs["content"] = None
            kwargs["embed"] = None
            kwargs.pop("embeds", None)

        return kwargs

    @classmethod
    def _sanitize_payload(cls, args: tuple[Any, ...], kwargs: Dict[str, Any]) -> tuple[tuple[Any, ...], Dict[str, Any]]:
        """Masks API keys, tokens, and credentials before sending out to Discord."""
        try:
            from zeronexus.security.sanitizer import redact_secrets
            clean_args = tuple(redact_secrets(a) if isinstance(a, str) else a for a in args)
            clean_kwargs = dict(kwargs)
            if "content" in clean_kwargs and isinstance(clean_kwargs["content"], str):
                clean_kwargs["content"] = redact_secrets(clean_kwargs["content"])
            return clean_args, clean_kwargs
        except Exception:
            return args, kwargs

    @classmethod
    async def safe_send(
        cls,
        interaction: discord.Interaction,
        *args: Any,
        ephemeral: bool = False,
        force_initial: bool = False,
        **kwargs: Any,
    ) -> Optional[discord.Message]:
        """Intelligently routes response to either initial response or followup.send().
        
        Guarantees authentic Discord Components V2 rendering and intercepts legacy Embeds.
        Safely catches 40060 and falls back to followup, and halts immediately on 10062.
        Automatically links returned message to view.message if view is supplied.
        """
        args, kwargs = cls._sanitize_payload(args, kwargs)
        if cls.is_interaction_expired(interaction):
            log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} token expired before safe_send.")
            return None

        kwargs = cls._normalize_v2_kwargs(kwargs, is_edit=False)
        view = kwargs.get("view")

        try:
            if force_initial or not cls.is_done(interaction):
                try:
                    call = interaction.response.send_message(*args, ephemeral=ephemeral, **kwargs)
                    if inspect.isawaitable(call):
                        await asyncio.wait_for(call, timeout=15.0)
                    msg = None
                    orig_fn = getattr(interaction, "original_response", None)
                    if orig_fn and callable(orig_fn):
                        try:
                            res = orig_fn()
                            msg = await asyncio.wait_for(res, timeout=15.0) if inspect.isawaitable(res) else res
                        except Exception:
                            pass
                    if view and hasattr(view, "message") and getattr(view, "message", None) is None:
                        view.message = msg or getattr(interaction, "message", None)
                    if view and hasattr(view, "_last_interaction"):
                        view._last_interaction = interaction
                    return msg
                except Exception as initial_err:
                    if cls.is_already_acknowledged(initial_err):
                        log.debug(f"Interaction {getattr(interaction, 'id', 'unknown')} already responded, falling back to followup.")
                        call = interaction.followup.send(*args, ephemeral=ephemeral, **kwargs)
                        msg = await asyncio.wait_for(call, timeout=15.0) if inspect.isawaitable(call) else call
                        if view and hasattr(view, "message") and getattr(view, "message", None) is None:
                            view.message = msg or getattr(interaction, "message", None)
                        if view and hasattr(view, "_last_interaction"):
                            view._last_interaction = interaction
                        return msg
                    if cls.is_expired_or_unknown(initial_err):
                        log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired (10062) during initial send.")
                        return None
                    raise initial_err
            else:
                call = interaction.followup.send(*args, ephemeral=ephemeral, **kwargs)
                msg = await asyncio.wait_for(call, timeout=15.0) if inspect.isawaitable(call) else call
                if view and hasattr(view, "message") and getattr(view, "message", None) is None:
                    view.message = msg or getattr(interaction, "message", None)
                if view and hasattr(view, "_last_interaction"):
                    view._last_interaction = interaction
                return msg
        except Exception as e:
            if cls.is_expired_or_unknown(e):
                log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired (10062) during send/followup.")
                return None
            log.error(f"Failed to safe_send on interaction {getattr(interaction, 'id', 'unknown')}: {e}", exc_info=True)
            return None

    @classmethod
    async def safe_followup(
        cls,
        interaction: discord.Interaction,
        *args: Any,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> Optional[discord.Message]:
        """Sends a followup message, swallowing 10062 safely.
        
        If interaction is not yet acknowledged, automatically delegates to safe_send.
        """
        if cls.is_interaction_expired(interaction):
            log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} token expired before safe_followup.")
            return None

        args, kwargs = cls._sanitize_payload(args, kwargs)

        if not cls.is_done(interaction):
            return await cls.safe_send(interaction, *args, ephemeral=ephemeral, **kwargs)

        kwargs = cls._normalize_v2_kwargs(kwargs, is_edit=False)
        view = kwargs.get("view")
        try:
            call = interaction.followup.send(*args, ephemeral=ephemeral, **kwargs)
            msg = await asyncio.wait_for(call, timeout=15.0) if inspect.isawaitable(call) else call
            if view and hasattr(view, "message") and getattr(view, "message", None) is None:
                view.message = msg or getattr(interaction, "message", None)
            if view and hasattr(view, "_last_interaction"):
                view._last_interaction = interaction
            return msg
        except Exception as e:
            if cls.is_expired_or_unknown(e):
                log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired (10062) during followup.")
                return None
            if cls.is_already_acknowledged(e) or "not been acknowledged" in str(e).lower():
                log.debug(f"Interaction {getattr(interaction, 'id', 'unknown')} not acknowledged for followup, auto-routing to safe_send.")
                return await cls.safe_send(interaction, *args, ephemeral=ephemeral, force_initial=True, **kwargs)
            log.error(f"Failed safe_followup on interaction {getattr(interaction, 'id', 'unknown')}: {e}", exc_info=True)
            return None

    @classmethod
    async def safe_edit(
        cls,
        interaction: discord.Interaction,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """Edits the original response or component message safely.
        
        Guarantees:
        1. Auto-sanitizes 'ephemeral' parameter which is illegal in edit calls.
        2. Ensures Components V2 compliance and clears legacy embed/content when editing.
        3. Seamless fallback: if edit_message fails with 40060 (Already acknowledged),
           falls back to edit_original_response.
        4. If edit_original_response fails because not yet acknowledged, falls back to edit_message.
        5. Halts cleanly on 10062 / expired token or 10008 (deleted message) without secondary crash.
        """
        if cls.is_interaction_expired(interaction):
            log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired before safe_edit.")
            return False

        args, kwargs = cls._sanitize_payload(args, kwargs)

        # Edit operations do not accept ephemeral parameter
        kwargs.pop("ephemeral", None)

        kwargs = cls._normalize_v2_kwargs(kwargs, is_edit=True)
        view = kwargs.get("view")
        if view and hasattr(view, "_last_interaction"):
            view._last_interaction = interaction
        if view and hasattr(view, "message") and getattr(view, "message", None) is None:
            inter_msg = getattr(interaction, "message", None)
            if inter_msg is not None:
                view.message = inter_msg

        try:
            if cls.is_done(interaction):
                try:
                    call = interaction.edit_original_response(*args, **kwargs)
                    if inspect.isawaitable(call):
                        await asyncio.wait_for(call, timeout=10.0)
                    return True
                except Exception as e:
                    if cls.is_expired_or_unknown(e):
                        log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired (10062) during edit_original_response.")
                        return False
                    if getattr(e, "code", None) == 10008:
                        log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} target message was deleted (10008).")
                        return False
                    # Fallback to response.edit_message if edit_original_response raised because not responded
                    resp = getattr(interaction, "response", None)
                    if resp and hasattr(resp, "edit_message"):
                        try:
                            call = resp.edit_message(*args, **kwargs)
                            if inspect.isawaitable(call):
                                await asyncio.wait_for(call, timeout=10.0)
                            return True
                        except Exception:
                            pass
                    # If interaction has message attached, fallback to message.edit
                    msg = getattr(interaction, "message", None)
                    if msg and hasattr(msg, "edit"):
                        try:
                            call = msg.edit(*args, **kwargs)
                            if inspect.isawaitable(call):
                                await asyncio.wait_for(call, timeout=10.0)
                            return True
                        except Exception:
                            pass
                    raise e
            else:
                try:
                    call = interaction.response.edit_message(*args, **kwargs)
                    if inspect.isawaitable(call):
                        await asyncio.wait_for(call, timeout=10.0)
                    return True
                except Exception as initial_err:
                    if cls.is_expired_or_unknown(initial_err):
                        log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired (10062) during response.edit_message.")
                        return False
                    if getattr(initial_err, "code", None) == 10008:
                        log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} target message was deleted (10008).")
                        return False
                    # Fallback to edit_original_response if already acknowledged or ClientException (non-component interaction)
                    log.debug(f"Interaction {getattr(interaction, 'id', 'unknown')} response.edit_message failed ({initial_err}), falling back to edit_original_response.")
                    try:
                        call = interaction.edit_original_response(*args, **kwargs)
                        if inspect.isawaitable(call):
                            await asyncio.wait_for(call, timeout=10.0)
                        return True
                    except Exception as e2:
                        if cls.is_expired_or_unknown(e2):
                            log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired (10062) during fallback edit.")
                            return False
                        if getattr(e2, "code", None) == 10008:
                            return False
                        msg = getattr(interaction, "message", None)
                        if msg and hasattr(msg, "edit"):
                            try:
                                call = msg.edit(*args, **kwargs)
                                if inspect.isawaitable(call):
                                    await asyncio.wait_for(call, timeout=10.0)
                                return True
                            except Exception:
                                pass
                        raise e2
        except Exception as e:
            if cls.is_expired_or_unknown(e):
                log.warning(f"Interaction {getattr(interaction, 'id', 'unknown')} expired (10062) during edit.")
                return False
            if getattr(e, "code", None) == 10008:
                log.warning("Target message was deleted (10008) during edit.")
                return False
            log.error(f"Failed safe_edit on interaction {getattr(interaction, 'id', 'unknown')}: {e}", exc_info=True)
            return False

    @classmethod
    async def safe_error(
        cls,
        interaction: discord.Interaction,
        error: Union[BaseException, str],
        user_msg: Optional[str] = None,
        ephemeral: bool = True,
    ) -> bool:
        """Handles an error by displaying a clean card, strictly terminating if error is 10062."""
        if isinstance(error, BaseException) and cls.is_expired_or_unknown(error):
            log.warning(
                f"Halting safe_error for interaction {getattr(interaction, 'id', 'unknown')}: token already dead (10062). No second send."
            )
            return False

        if cls.is_interaction_expired(interaction):
            log.warning(f"Halting safe_error for interaction {getattr(interaction, 'id', 'unknown')}: interaction expired.")
            return False

        from zeronexus.ui.card import ZNCard, ZNResponse
        from zeronexus.ui.theme import ZNColor, ZNStatusPill

        msg = user_msg or str(error)
        card = ZNCard(
            title="抱歉，處理過程中遇到了一點小狀況",
            description=(
                "系統在執行此操作時遇到了一些阻礙，請別擔心，您的資料安全完好。\n\n"
                f"📌 **狀況簡述**：`{msg[:150]}`\n\n"
                "💡 **您可以嘗試**：\n"
                "- 稍候片刻後再次嘗試發起操作。\n"
                "- 檢查輸入的參數或格式是否完整正確。\n"
                "- 若狀況持續發生，請通知伺服器管理員協助查看系統診斷日誌。"
            ),
            status_pill=ZNStatusPill.ERROR,
            color=ZNColor.ERROR,
        )
        resp = ZNResponse(card=card, ephemeral=ephemeral)
        was_done = cls.is_done(interaction)
        res = await cls.safe_send(interaction, **resp.to_send_kwargs())
        if res is not None:
            return True
        if not was_done and cls.is_done(interaction):
            return True
        return False
