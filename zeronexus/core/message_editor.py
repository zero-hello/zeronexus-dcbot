"""Discord 狀態訊息安全編輯器 (Safe Status Message Editor).

將 bot.py 中的 _safe_edit_status_message 方法提取為獨立模組，
負責處理 Discord 訊息編輯的各種邊界情況與異常恢復。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import discord

from zeronexus.core.logger import log
from zeronexus.ui.card import ZNCard


async def safe_edit_status_message(
    status_msg: Optional[discord.Message],
    channel: Optional[discord.abc.Messageable] = None,
    **kwargs: Any,
) -> Optional[discord.Message]:
    """安全地編輯狀態訊息，具備完整的異常處理與自動降級機制。

    保護機制：
    - Discord 400 Bad Request (error code 50035): Invalid Form Body
    - 跨型編輯拒絕（Components V2 <-> Embed）
    - discord.NotFound: 訊息已被刪除
    - discord.Forbidden: 權限不足
    """
    from zeronexus.ui.card import ZNCard

    fallback_card: Optional[ZNCard] = kwargs.pop("card", None)
    current_view: Optional[Any] = kwargs.get("view")

    if current_view is not None and (
        isinstance(current_view, discord.ui.LayoutView)
        or (hasattr(current_view, "has_components_v2") and current_view.has_components_v2())
    ):
        if fallback_card is None and hasattr(current_view, "card") and isinstance(current_view.card, ZNCard):
            fallback_card = current_view.card
        kwargs.pop("embed", None)
        kwargs.pop("embeds", None)
    elif fallback_card is not None:
        layout_view = fallback_card.to_layout_view(extra_view=current_view)
        kwargs["view"] = layout_view
        kwargs.pop("embed", None)
        kwargs.pop("embeds", None)

    if not status_msg:
        if channel and hasattr(channel, "send") and ("view" in kwargs or "embed" in kwargs or "content" in kwargs):
            try:
                return await channel.send(**kwargs)
            except Exception as send_err:
                log.warning(f"Failed to send message to channel in safe_edit: {send_err}")
                if fallback_card:
                    try:
                        fb_kwargs = {"embed": fallback_card.to_embed()}
                        if "attachments" in kwargs:
                            fb_kwargs["attachments"] = kwargs["attachments"]
                        return await channel.send(**fb_kwargs)
                    except Exception:
                        pass
                return None
        return None

    try:
        return await status_msg.edit(**kwargs)
    except discord.NotFound:
        log.info(f"Target status message {status_msg.id} was deleted. Attempting fallback send to channel.")
        if channel and hasattr(channel, "send"):
            try:
                return await channel.send(**kwargs)
            except Exception as fb_err:
                if fallback_card:
                    try:
                        fb_kwargs = {"embed": fallback_card.to_embed()}
                        if "attachments" in kwargs:
                            fb_kwargs["attachments"] = kwargs["attachments"]
                        return await channel.send(**fb_kwargs)
                    except Exception:
                        pass
                log.warning(f"Fallback channel send also failed: {fb_err}")
        return None
    except discord.HTTPException as he:
        log.warning(f"HTTPException editing status message {status_msg.id}: {he}")

        he_text = str(he)
        is_v2_issue = (
            "IS_COMPONENTS_V2" in he_text
            or "embeds" in he_text
            or getattr(he, "code", 0) == 50035
            or getattr(he, "status", 0) == 400
        )
        is_using_v2 = isinstance(kwargs.get("view"), discord.ui.LayoutView) or (
            hasattr(kwargs.get("view"), "has_components_v2") and kwargs["view"].has_components_v2()
        )

        if (is_v2_issue or is_using_v2) and (fallback_card or "embed" in kwargs):
            log.info(f"Triggering automatic Embed fallback for status message {status_msg.id}")
            try:
                fb_kwargs: Dict[str, Any] = {}
                if fallback_card:
                    fb_kwargs["embed"] = fallback_card.to_embed()
                elif "embed" in kwargs:
                    fb_kwargs["embed"] = kwargs["embed"]

                if "content" in kwargs and kwargs["content"]:
                    fb_kwargs["content"] = kwargs["content"]
                if "attachments" in kwargs:
                    fb_kwargs["attachments"] = kwargs["attachments"]

                v = kwargs.get("view")
                extra_v = getattr(v, "extra_view", None) if v else None
                if extra_v and isinstance(extra_v, discord.ui.View):
                    fb_kwargs["view"] = extra_v
                elif v:
                    standard_view = discord.ui.View(timeout=180.0)
                    def _collect_items(comp: Any) -> None:
                        for child in getattr(comp, "children", []):
                            if isinstance(child, (discord.ui.Button, discord.ui.Select)) and child not in standard_view.children:
                                standard_view.add_item(child)
                            elif hasattr(child, "children"):
                                _collect_items(child)
                    _collect_items(v)
                    if len(standard_view.children) > 0:
                        fb_kwargs["view"] = standard_view
                    else:
                        fb_kwargs["view"] = None
                else:
                    fb_kwargs["view"] = None

                return await status_msg.edit(**fb_kwargs)
            except Exception as fb_edit_err:
                log.warning(f"Fallback Embed edit also failed: {fb_edit_err}")

        if "attachments" in kwargs:
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("attachments", None)
            try:
                return await status_msg.edit(**retry_kwargs)
            except Exception:
                pass
        return None
    except Exception as e:
        log.warning(f"Unexpected error editing status message {status_msg.id}: {e}")
        return None
