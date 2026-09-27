"""Read-only Discord tools limited to the invoking guild and visible channels."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


def _error(message: str) -> Dict[str, Any]:
    return {"error": message}


def _context_error(guild: Any, user: Any) -> Optional[str]:
    if guild is None or user is None:
        return "需要目前 Discord 伺服器與提問者上下文；不支援跨伺服器查詢。"
    user_guild = getattr(user, "guild", None)
    if user_guild is not None and getattr(user_guild, "id", None) != getattr(guild, "id", None):
        return "提問者不屬於目前互動伺服器。"
    if user_guild is None and getattr(guild, "get_member", lambda _: None)(getattr(user, "id", None)) is None:
        return "無法確認提問者是目前伺服器成員，已拒絕讀取。"
    return None


def _resolve_channel(guild: Any, channel_id: Optional[int], channel: Any) -> Any:
    if channel_id is None:
        return channel
    try:
        return guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return None


def _channel_access_error(channel: Any, user: Any, guild: Any) -> Optional[str]:
    from zeronexus.engines.channel_inspector import channel_inspector

    return channel_inspector.authorize_channel_access(channel, user, guild)


def _visible_member_ids(guild: Any, user: Any) -> set[int]:
    visible = {getattr(user, "id", None)}
    bot_member = getattr(guild, "me", None)
    for channel in getattr(guild, "text_channels", []):
        try:
            if channel.permissions_for(user).view_channel and bot_member and channel.permissions_for(bot_member).view_channel:
                visible.update(member.id for member in getattr(channel, "members", []))
        except Exception:
            continue
    return visible


def _member_visible_in_guild_channels(member: Any, guild: Any, user: Any) -> bool:
    return getattr(member, "id", None) in _visible_member_ids(guild, user)


def get_discord_read_tool_specs() -> List[Dict[str, Any]]:
    """Return distinct bounded read-only utilities for current-guild information."""
    specs: List[Dict[str, Any]] = []

    async def h_server_overview(guild: Any = None, user: Any = None, bot: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        visible_channels = 0
        bot_member = getattr(guild, "me", None)
        for channel in getattr(guild, "channels", []):
            try:
                visible_channels += bool(channel.permissions_for(user).view_channel and bot_member and channel.permissions_for(bot_member).view_channel)
            except Exception:
                continue
        return {
            "guild_id": guild.id,
            "guild_name": guild.name,
            "description": getattr(guild, "description", None),
            "created_at": getattr(guild, "created_at", None).isoformat() if getattr(guild, "created_at", None) else None,
            "visible_channel_count": visible_channels,
        }

    async def h_visible_channels(guild: Any = None, user: Any = None, include_voice: bool = True, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        channels = []
        for ch in getattr(guild, "channels", []):
            if not hasattr(ch, "permissions_for"):
                continue
            try:
                if not ch.permissions_for(user).view_channel:
                    continue
            except Exception:
                continue
            try:
                bot_member = getattr(guild, "me", None)
                if bot_member is None or not ch.permissions_for(bot_member).view_channel:
                    continue
            except Exception:
                continue
            ch_type = str(getattr(ch, "type", "unknown"))
            if not include_voice and "voice" in ch_type:
                continue
            channels.append({"id": ch.id, "name": ch.name, "type": ch_type, "category": getattr(getattr(ch, "category", None), "name", None)})
        return {"guild_name": guild.name, "count": len(channels), "channels": channels[:100]}

    async def h_visible_members(guild: Any = None, user: Any = None, limit: int = 100, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        limit = max(1, min(int(limit), 100))
        visible_member_ids = {getattr(user, "id", None)}
        for ch in getattr(guild, "text_channels", []):
            try:
                if ch.permissions_for(user).view_channel and ch.permissions_for(guild.me).view_channel:
                    visible_member_ids.update(m.id for m in getattr(ch, "members", []))
            except Exception:
                continue
        members = [m for m in getattr(guild, "members", []) if m.id in visible_member_ids][:limit]
        return {"guild_name": guild.name, "count_returned": len(members), "members": [
            {"id": m.id, "display_name": getattr(m, "display_name", m.name), "bot": bool(m.bot), "joined_at": m.joined_at.isoformat() if getattr(m, "joined_at", None) else None}
            for m in members
        ]}

    async def h_search_visible_member(query: str, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        query = str(query).strip().casefold()
        if not query or len(query) > 80:
            return _error("請提供 1–80 字元的成員名稱關鍵字。")
        visible_member_ids = {getattr(user, "id", None)}
        for ch in getattr(guild, "text_channels", []):
            try:
                if ch.permissions_for(user).view_channel and ch.permissions_for(guild.me).view_channel:
                    visible_member_ids.update(m.id for m in getattr(ch, "members", []))
            except Exception:
                continue
        visible_members = [m for m in getattr(guild, "members", []) if m.id in visible_member_ids]
        found = [m for m in visible_members if query in getattr(m, "display_name", m.name).casefold() or query in m.name.casefold()]
        return {"count": len(found[:25]), "members": [{"id": m.id, "display_name": getattr(m, "display_name", m.name), "bot": bool(m.bot)} for m in found[:25]]}

    async def h_list_roles(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        visible_ids = _visible_member_ids(guild, user)
        roles = [r for r in getattr(guild, "roles", []) if any(m.id in visible_ids for m in getattr(r, "members", [])) or getattr(r, "is_default", lambda: False)()]
        roles.sort(key=lambda r: getattr(r, "position", 0), reverse=True)
        return {"count": len(roles), "roles": [{"id": r.id, "name": r.name, "position": r.position, "managed": bool(r.managed), "visible_members_count": sum(1 for m in getattr(r, "members", []) if m.id in visible_ids)} for r in roles[:100]]}

    async def h_member_roles(member_id: int, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        member = guild.get_member(int(member_id)) if hasattr(guild, "get_member") else None
        if member is None:
            return _error("找不到目前伺服器的該成員；不會查詢其他伺服器。")
        if member.id != getattr(user, "id", None) and not _member_visible_in_guild_channels(member, guild, user):
            return _error("目標成員不在提問者可見的頻道，拒絕讀取其資料。")
        return {"member_id": member.id, "display_name": getattr(member, "display_name", member.name), "roles": [r.name for r in getattr(member, "roles", [])]}

    async def h_channel_overview(channel_id: Optional[int] = None, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        access_error = channel_inspector.authorize_channel_access(target, user, guild)
        if access_error:
            return _error(access_error)
        overview = channel_inspector.get_channel_overview_details(target)
        overview.pop("is_nsfw", None)
        return overview

    async def h_channel_messages(channel_id: Optional[int] = None, limit: int = 50, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        return {"channel_name": target.name, "message_count": len(msgs), "transcript": channel_inspector.format_messages_to_transcript(msgs, max_chars=6000)}

    async def h_search_channel_messages(query: str, channel_id: Optional[int] = None, limit: int = 100, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        query = str(query).strip()
        if not query or len(query) > 120:
            return _error("搜尋詞需為 1–120 字元。")
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        matches = [m for m in msgs if query.casefold() in (getattr(m, "clean_content", None) or getattr(m, "content", "")).casefold()]
        return {"channel_name": target.name, "query": query, "matches": [{"author": getattr(getattr(m, "author", None), "display_name", "unknown"), "created_at": m.created_at.isoformat(), "content": (getattr(m, "clean_content", None) or m.content)[:700]} for m in matches[-25:]], "count": len(matches)}

    async def h_channel_activity(channel_id: Optional[int] = None, limit: int = 150, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 200)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        return channel_inspector.compute_channel_activity_stats(msgs, channel_name=target.name)

    async def h_visible_threads(channel_id: Optional[int] = None, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        access_error = channel_inspector.authorize_channel_access(target, user, guild)
        if access_error:
            return _error(access_error)
        threads = list(getattr(target, "threads", []) or [])
        return {"channel_name": target.name, "count": len(threads), "threads": [{"id": t.id, "name": t.name, "archived": bool(getattr(t, "archived", False)), "message_count": getattr(t, "message_count", None)} for t in threads[:50]]}

    async def h_list_emojis(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        emojis = list(getattr(guild, "emojis", []))
        return {"count": len(emojis), "emojis": [{"name": e.name, "id": e.id, "animated": bool(e.animated), "available": bool(e.available)} for e in emojis[:100]]}

    async def h_list_stickers(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        stickers = list(getattr(guild, "stickers", []))
        return {"count": len(stickers), "stickers": [{"name": s.name, "id": s.id, "description": getattr(s, "description", None), "format": str(getattr(s, "format", "unknown"))} for s in stickers[:100]]}

    async def h_channel_word_frequency(channel_id: Optional[int] = None, limit: int = 100, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 200)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        import re
        stop = {"這個", "那個", "我們", "你們", "他們", "就是", "然後", "可以", "不是", "沒有", "一下", "什麼", "一個", "真的"}
        words = Counter(w.casefold() for m in msgs for w in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{3,}", getattr(m, "clean_content", None) or getattr(m, "content", "")) if w.casefold() not in stop)
        return {"channel_name": target.name, "sampled_messages": len(msgs), "top_terms": [{"term": word, "count": count} for word, count in words.most_common(30)]}

    async def h_channel_links(channel_id: Optional[int] = None, limit: int = 80, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        import re
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        links = []
        for msg in msgs:
            text = getattr(msg, "content", "") or ""
            for url in re.findall(r"https?://[^\s<>]+", text):
                links.append({"author": getattr(getattr(msg, "author", None), "display_name", "unknown"), "url": url[:500], "created_at": msg.created_at.isoformat()})
        return {"channel_name": target.name, "count": len(links), "links": links[-50:]}

    async def h_channel_attachment_summary(channel_id: Optional[int] = None, limit: int = 80, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        files = []
        for msg in msgs:
            for att in getattr(msg, "attachments", []) or []:
                files.append({"author": getattr(getattr(msg, "author", None), "display_name", "unknown"), "filename": str(getattr(att, "filename", "file"))[:160], "content_type": getattr(att, "content_type", None), "size": getattr(att, "size", None), "created_at": msg.created_at.isoformat()})
        return {"channel_name": target.name, "attachment_count": len(files), "attachments": files[-50:]}

    async def h_channel_question_messages(question: str, channel_id: Optional[int] = None, limit: int = 100, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        q_words = {w.casefold() for w in str(question).split() if len(w) >= 2}
        ranked = []
        for msg in msgs:
            text = getattr(msg, "clean_content", None) or getattr(msg, "content", "")
            score = sum(1 for word in q_words if word in text.casefold())
            if score:
                ranked.append((score, msg, text))
        ranked.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return {"channel_name": target.name, "question": str(question)[:200], "matches": [{"score": score, "author": getattr(getattr(msg, "author", None), "display_name", "unknown"), "created_at": msg.created_at.isoformat(), "content": text[:700]} for score, msg, text in ranked[:15]]}

    async def h_channel_daily_activity(date_text: str = "", channel_id: Optional[int] = None, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        from datetime import date as date_type
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector, TAIPEI_TZ
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        try:
            day = date_type.fromisoformat(date_text) if date_text else datetime.now(TAIPEI_TZ).date()
        except ValueError:
            return _error("日期請使用 YYYY-MM-DD 格式。")
        start = TAIPEI_TZ.localize(datetime.combine(day, datetime.min.time())).astimezone(timezone.utc)
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, after=start, limit=200, requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        counts = Counter(m.created_at.astimezone(TAIPEI_TZ).hour for m in msgs)
        return {"channel_name": target.name, "date": day.isoformat(), "messages": len(msgs), "hourly_counts": [{"hour_taipei": h, "messages": counts.get(h, 0)} for h in range(24)]}

    async def h_channel_questions(channel_id: Optional[int] = None, limit: int = 100, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        import re
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        found = []
        for m in msgs:
            text = (getattr(m, "clean_content", None) or getattr(m, "content", "")).strip()
            if "?" in text or "？" in text or re.search(r"(嗎|怎麼|如何|為什麼|哪裡|誰是|幾點|多少)[？?]?$", text):
                found.append({"author": getattr(getattr(m, "author", None), "display_name", "unknown"), "created_at": m.created_at.isoformat(), "question": text[:700]})
        return {"channel_name": target.name, "questions": found[-30:], "count": len(found)}

    async def h_channel_mentions(channel_id: Optional[int] = None, limit: int = 100, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        counts = Counter(getattr(m, "display_name", getattr(m, "name", "unknown")) for msg in msgs for m in getattr(msg, "mentions", []) or [])
        return {"channel_name": target.name, "mentioned_members": [{"display_name": name, "mentions": count} for name, count in counts.most_common(30)]}

    async def h_role_summary(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        roles = list(getattr(guild, "roles", []))
        return {"guild_name": guild.name, "role_count": len(roles), "roles": [{"name": r.name, "visible_members_count": sum(1 for m in getattr(r, "members", []) if m.id in visible_ids), "position": getattr(r, "position", 0), "managed": bool(getattr(r, "managed", False))} for r in sorted(roles, key=lambda r: getattr(r, "position", 0), reverse=True)[:100]]}

    async def h_member_presence_summary(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        visible_ids = _visible_member_ids(guild, user)
        members = [m for m in getattr(guild, "members", []) if m.id in visible_ids]
        status_counts = Counter(str(getattr(m, "status", "unknown")) for m in members if not getattr(m, "bot", False))
        return {"guild_name": guild.name, "visible_cached_non_bot_members": sum(status_counts.values()), "status_counts": dict(status_counts)}

    async def h_channel_permissions(channel_id: Optional[int] = None, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        target = _resolve_channel(guild, channel_id, channel)
        if target is None or not hasattr(target, "permissions_for"):
            return _error("找不到目前伺服器的頻道。")
        access_error = _channel_access_error(target, user, guild)
        if access_error:
            return _error(access_error)
        bot_member = getattr(guild, "me", None)
        bot_perms = target.permissions_for(bot_member)
        user_perms = target.permissions_for(user if getattr(user, "guild", None) else guild.get_member(user.id))
        visible = ("view_channel", "read_message_history", "send_messages", "manage_messages", "embed_links", "attach_files")
        return {"channel_name": target.name, "requester": {p: bool(getattr(user_perms, p, False)) for p in visible}, "bot": {p: bool(getattr(bot_perms, p, False)) for p in visible}}

    async def h_find_channels_by_topic(query: str, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        q = str(query).casefold().strip()
        if not q or len(q) > 100:
            return _error("搜尋字需為 1–100 字元。")
        found = []
        for ch in getattr(guild, "text_channels", []):
            try:
                if not ch.permissions_for(user).view_channel:
                    continue
            except Exception:
                continue
            topic = getattr(ch, "topic", None) or ""
            if q in ch.name.casefold() or q in topic.casefold():
                found.append({"id": ch.id, "name": ch.name, "topic": topic[:300]})
        return {"query": q, "channels": found[:30], "count": len(found)}

    async def h_search_role_names(query: str, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        q = str(query).casefold().strip()
        visible_ids = _visible_member_ids(guild, user)
        roles = [r for r in getattr(guild, "roles", []) if q in r.name.casefold() and any(m.id in visible_ids for m in getattr(r, "members", []))]
        return {"query": q, "roles": [{"id": r.id, "name": r.name, "position": getattr(r, "position", 0)} for r in roles[:40]], "count": len(roles)}

    async def h_channel_message_counts(channel_id: Optional[int] = None, limit: int = 200, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 200)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        return {"channel_name": target.name, "sample_size": len(msgs), "messages_with_text": sum(bool((getattr(m, "clean_content", None) or getattr(m, "content", "")).strip()) for m in msgs), "messages_with_attachments": sum(bool(getattr(m, "attachments", [])) for m in msgs), "total_characters": sum(len(getattr(m, "content", "") or "") for m in msgs)}

    async def h_channel_media_counts(channel_id: Optional[int] = None, limit: int = 150, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 150)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        counts = Counter()
        for m in msgs:
            for attachment in getattr(m, "attachments", []) or []:
                ctype = (getattr(attachment, "content_type", "") or "").split("/", 1)[0] or "unknown"
                counts[ctype] += 1
        return {"channel_name": target.name, "sample_size": len(msgs), "attachments_by_type": dict(counts), "total_attachments": sum(counts.values())}

    async def h_recent_channel_participants(channel_id: Optional[int] = None, limit: int = 150, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 150)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        counts = Counter((m.author.id, getattr(m.author, "display_name", m.author.name)) for m in msgs if getattr(m, "author", None) and not getattr(m.author, "bot", False))
        return {"channel_name": target.name, "sample_size": len(msgs), "participants": [{"member_id": mid, "display_name": name, "message_count": count} for (mid, name), count in counts.most_common(40)]}

    async def h_channel_first_last_message(channel_id: Optional[int] = None, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        access_error = channel_inspector.authorize_channel_access(target, user, guild)
        if access_error:
            return _error(access_error)
        try:
            newest = [m async for m in target.history(limit=1)]
            oldest = [m async for m in target.history(limit=1, oldest_first=True)]
        except Exception as exc:
            return _error(f"讀取頻道首末訊息失敗：{type(exc).__name__}")
        def pack(m: Any) -> Optional[Dict[str, Any]]:
            return {"author": getattr(m.author, "display_name", m.author.name), "created_at": m.created_at.isoformat(), "content": (getattr(m, "clean_content", None) or m.content)[:500]} if m else None
        return {"channel_name": target.name, "oldest_sample": pack(oldest[0] if oldest else None), "newest_sample": pack(newest[0] if newest else None)}

    async def h_visible_categories(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        cats = []
        for c in getattr(guild, "categories", []):
            children = []
            for ch in getattr(c, "channels", []):
                try:
                    if ch.permissions_for(user).view_channel:
                        children.append({"id": ch.id, "name": ch.name, "type": str(ch.type)})
                except Exception:
                    continue
            if children:
                cats.append({"id": c.id, "name": c.name, "visible_channels": children[:50]})
        return {"guild_name": guild.name, "categories": cats[:50]}

    async def h_server_boost_info(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        return {"guild_name": guild.name, "premium_tier": int(getattr(guild, "premium_tier", 0)), "premium_subscription_count": getattr(guild, "premium_subscription_count", None)}

    async def h_server_features(guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        return {"guild_name": guild.name, "features": [str(f) for f in getattr(guild, "features", [])], "verification_level": str(getattr(guild, "verification_level", "unknown")), "explicit_content_filter": str(getattr(guild, "explicit_content_filter", "unknown")), "default_notifications": str(getattr(guild, "default_notifications", "unknown"))}

    async def h_member_join_age(member_id: int, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        member = guild.get_member(int(member_id)) if hasattr(guild, "get_member") else None
        if not member:
            return _error("找不到目前伺服器的該成員。")
        joined = getattr(member, "joined_at", None)
        return {"member_id": member.id, "display_name": getattr(member, "display_name", member.name), "joined_at": joined.isoformat() if joined else None, "days_in_server": max(0, (datetime.now(timezone.utc) - joined).days) if joined else None}

    async def h_channel_reactions(channel_id: Optional[int] = None, limit: int = 100, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        counts = Counter(str(reaction.emoji) for m in msgs for reaction in getattr(m, "reactions", []) or [])
        return {"channel_name": target.name, "sample_size": len(msgs), "top_reactions": [{"emoji": emoji, "count": count} for emoji, count in counts.most_common(30)]}

    async def h_member_message_search(member_id: int, query: str, channel_id: Optional[int] = None, limit: int = 100, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        target = _resolve_channel(guild, channel_id, channel)
        member = guild.get_member(int(member_id)) if hasattr(guild, "get_member") else None
        if target is None or member is None:
            return _error("頻道或成員不存在於目前伺服器。")
        if member.id != getattr(user, "id", None) and member not in getattr(target, "members", []):
            return _error("目標成員不在指定可見頻道，拒絕搜尋其訊息。")
        from zeronexus.engines.channel_inspector import channel_inspector
        msgs, fetch_error = await channel_inspector.fetch_channel_messages(target, limit=max(1, min(int(limit), 100)), requester=user, expected_guild=guild)
        if fetch_error:
            return _error(fetch_error)
        q = str(query).casefold().strip()
        found = [m for m in msgs if m.author.id == member.id and q in (getattr(m, "clean_content", None) or m.content).casefold()]
        return {"channel_name": target.name, "member": getattr(member, "display_name", member.name), "matches": [{"created_at": m.created_at.isoformat(), "content": (getattr(m, "clean_content", None) or m.content)[:600]} for m in found[-20:]]}

    async def h_member_channel_presence(member_id: int, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        member = guild.get_member(int(member_id)) if hasattr(guild, "get_member") else None
        if not member:
            return _error("找不到目前伺服器的該成員。")
        if member.id != getattr(user, "id", None):
            return {"error": "為保護成員隱私，只允許查詢提問者自己的語音頻道狀態。"}
        visible = []
        voice_channel = getattr(getattr(member, "voice", None), "channel", None)
        if voice_channel:
            try:
                if voice_channel.permissions_for(user).view_channel:
                    visible.append({"channel_id": voice_channel.id, "channel_name": voice_channel.name, "kind": "voice"})
            except Exception:
                pass
        return {"member": getattr(member, "display_name", member.name), "visible_channel_presence": visible}

    async def h_channel_slowmode(channel_id: Optional[int] = None, channel: Any = None, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        from zeronexus.engines.channel_inspector import channel_inspector
        target = _resolve_channel(guild, channel_id, channel)
        if target is None:
            return _error("找不到目前伺服器的頻道。")
        access_error = channel_inspector.authorize_channel_access(target, user, guild)
        if access_error:
            return _error(access_error)
        return {"channel_name": target.name, "slowmode_seconds": int(getattr(target, "slowmode_delay", 0)), "topic": (getattr(target, "topic", None) or "")[:500]}

    async def h_recent_thread_messages(channel_id: int, limit: int = 30, guild: Any = None, user: Any = None, **_: Any) -> Dict[str, Any]:
        err = _context_error(guild, user)
        if err:
            return _error(err)
        parent = _resolve_channel(guild, channel_id, None)
        if parent is None:
            return _error("找不到目前伺服器的討論串母頻道。")
        from zeronexus.engines.channel_inspector import channel_inspector
        access_error = channel_inspector.authorize_channel_access(parent, user, guild)
        if access_error:
            return _error(access_error)
        threads = list(getattr(parent, "threads", []) or [])[:20]
        out = []
        for thread in threads:
            if not hasattr(thread, "history"):
                continue
            access_error = channel_inspector.authorize_channel_access(thread, user, guild)
            if access_error:
                continue
            try:
                msgs = [m async for m in thread.history(limit=max(1, min(int(limit), 30)))]
                out.append({"thread_name": thread.name, "messages": [{"author": getattr(m.author, "display_name", m.author.name), "content": (getattr(m, "clean_content", None) or m.content)[:400]} for m in reversed(msgs)]})
            except Exception:
                continue
        return {"parent_channel": parent.name, "threads": out}

    def schema(name: str, category: str, description: str, properties: Dict[str, Any], handler: Any, required: Optional[List[str]] = None) -> None:
        specs.append({
            "name": name,
            "category": category,
            "description": description,
            "parameters_desc": ", ".join(properties) or "無參數；從目前 Discord 互動注入伺服器及使用者上下文",
            "parameters_schema": {"type": "object", "properties": properties, "required": required or []},
            "handler": handler,
            "trigger_keywords": [word for word in name.replace("_", " ").split() if len(word) > 2],
            "scope": "current_guild_visible_channels_only",
            "read_only": True,
        })

    integer = lambda desc, default=None: {"type": "integer", "description": desc, **({"default": default} if default is not None else {})}
    string = lambda desc: {"type": "string", "description": desc}
    schema("guild_visible_overview", "Discord 可見資料", "讀取目前伺服器名稱、描述、建立時間及提問者可見頻道數；只限本伺服器", {}, h_server_overview)
    schema("guild_visible_channels", "Discord 可見資料", "列出提問者與 Bot 在目前伺服器都可見的頻道名稱、類型與分類", {"include_voice": {"type": "boolean", "default": True}}, h_visible_channels)
    schema("guild_visible_members", "Discord 可見資料", "列出目前伺服器中出現在提問者可見頻道的成員公開顯示資料，最多 100 人", {"limit": integer("最多回傳成員數，上限 100", 100)}, h_visible_members)
    schema("guild_search_visible_member", "Discord 可見資料", "在提問者可見頻道所屬成員中搜尋顯示名稱", {"query": string("成員名稱關鍵字")}, h_search_visible_member, ["query"])
    schema("guild_visible_member_roles", "Discord 可見資料", "查詢目前伺服器可見頻道成員的顯示名稱與身分組名稱", {"member_id": integer("目前伺服器可見頻道成員 ID")}, h_member_roles, ["member_id"])
    schema("guild_visible_roles", "Discord 可見資料", "列出目前伺服器與提問者可見成員相關的身分組及可見人數", {}, h_list_roles)
    schema("guild_list_emojis", "Discord 可見資料", "列出目前伺服器可用表情符號", {}, h_list_emojis)
    schema("guild_list_stickers", "Discord 可見資料", "列出目前伺服器貼圖名稱與描述", {}, h_list_stickers)
    schema("guild_channel_overview", "Discord 頻道分析", "讀取目前伺服器內且提問者可見頻道的設定與討論串總覽", {"channel_id": integer("目前伺服器的頻道 ID；省略表示目前頻道")}, h_channel_overview)
    schema("guild_read_channel_messages", "Discord 頻道分析", "讀取提問者可見的目前伺服器頻道最近訊息，最多 100 則", {"channel_id": integer("目前伺服器的頻道 ID；省略表示目前頻道"), "limit": integer("讀取數量，上限 100", 50)}, h_channel_messages)
    schema("guild_search_channel_messages", "Discord 頻道分析", "搜尋目前伺服器中提問者可見頻道的近期訊息文字", {"query": string("搜尋關鍵字"), "channel_id": integer("目前伺服器的可見頻道 ID"), "limit": integer("搜尋樣本量，上限 100", 100)}, h_search_channel_messages, ["query"])
    schema("guild_channel_activity_report", "Discord 頻道分析", "統計提問者可見頻道的發言量、參與成員與活躍度", {"channel_id": integer("目前伺服器的可見頻道 ID"), "limit": integer("分析訊息數，上限 200", 150)}, h_channel_activity)
    schema("guild_list_channel_threads", "Discord 頻道分析", "列出目前伺服器提問者可見頻道的討論串", {"channel_id": integer("目前伺服器的可見頻道 ID")}, h_visible_threads)
    schema("discord_channel_topic_terms", "Discord 頻道分析", "分析可見頻道近期訊息中常見主題詞頻，不回傳完整訊息內容", {"channel_id": integer("目前伺服器的可見頻道 ID"), "limit": integer("樣本訊息數，上限 200", 100)}, h_channel_word_frequency)
    schema("guild_extract_channel_links", "Discord 頻道分析", "彙總提問者可見頻道最近訊息中的網址與發送者", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 100", 80)}, h_channel_links)
    schema("guild_channel_attachment_summary", "Discord 頻道分析", "統計目前伺服器可見頻道最近附件的名稱、類型及大小，不下載附件", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 100", 80)}, h_channel_attachment_summary)
    schema("guild_find_relevant_channel_messages", "Discord 頻道分析", "以關鍵詞相關度搜尋目前伺服器可見頻道的近期訊息", {"question": string("要搜尋的問題或關鍵字"), "channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 100", 100)}, h_channel_question_messages, ["question"])
    schema("guild_channel_daily_activity", "Discord 頻道分析", "按台北日期統計可見頻道每小時訊息量", {"date_text": string("YYYY-MM-DD；省略使用今天"), "channel_id": integer("可見頻道 ID")}, h_channel_daily_activity)
    schema("guild_extract_channel_questions", "Discord 頻道分析", "從目前伺服器可見頻道近期訊息擷取疑問句", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 100", 100)}, h_channel_questions)
    schema("guild_channel_member_mentions", "Discord 頻道分析", "統計可見頻道近期訊息中被提及最多的成員", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 100", 100)}, h_channel_mentions)
    schema("guild_search_server_roles", "Discord 可見資料", "搜尋目前伺服器中與提問者可見成員相關的身分組名稱", {"query": string("身分組搜尋詞")}, h_search_role_names, ["query"])
    schema("guild_channel_message_counts", "Discord 頻道分析", "對可見頻道近期訊息統計文字、附件與字元數", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 200", 200)}, h_channel_message_counts)
    schema("guild_channel_media_counts", "Discord 頻道分析", "統計可見頻道近期附件 MIME 類型分布，不下載檔案", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 150", 150)}, h_channel_media_counts)
    schema("guild_recent_channel_participants", "Discord 頻道分析", "彙總可見頻道近期非機器人參與者發言數", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 150", 150)}, h_recent_channel_participants)
    schema("guild_channel_first_last_message", "Discord 頻道分析", "讀取可見頻道最早及最新一則訊息作為時間範圍參考", {"channel_id": integer("可見頻道 ID")}, h_channel_first_last_message)
    schema("guild_visible_channel_categories", "Discord 可見資料", "列出目前伺服器分類及提問者可見的分類頻道", {}, h_visible_categories)
    schema("guild_boost_overview", "Discord 可見資料", "查詢目前伺服器公開的 Boost 等級與容量資訊", {}, h_server_boost_info)
    schema("guild_feature_flags", "Discord 可見資料", "查詢目前伺服器公開功能標記與驗證設定", {}, h_server_features)
    schema("guild_visible_member_join_age", "Discord 可見資料", "查詢目前伺服器且在提問者可見頻道中的成員加入時間", {"member_id": integer("目前伺服器可見成員 ID")}, h_member_join_age, ["member_id"])
    schema("guild_channel_reaction_summary", "Discord 頻道分析", "統計可見頻道近期訊息中常見的反應表情", {"channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 100", 100)}, h_channel_reactions)
    schema("guild_search_member_channel_messages", "Discord 頻道分析", "搜尋目前伺服器指定可見成員在可見頻道中的近期訊息", {"member_id": integer("目前伺服器可見成員 ID"), "query": string("搜尋文字"), "channel_id": integer("可見頻道 ID"), "limit": integer("樣本數，上限 100", 100)}, h_member_message_search, ["member_id", "query"])
    schema("guild_my_visible_voice_channel", "Discord 可見資料", "只查詢提問者本人目前所在且可見的語音頻道", {"member_id": integer("提問者自己的成員 ID")}, h_member_channel_presence, ["member_id"])
    schema("guild_channel_read_settings", "Discord 頻道分析", "查看可見頻道慢速模式與主題說明", {"channel_id": integer("可見頻道 ID")}, h_channel_slowmode)
    schema("guild_read_recent_thread_messages", "Discord 頻道分析", "讀取可見母頻道中最多 20 個討論串的近期訊息，每串最多 30 則", {"channel_id": integer("目前伺服器的母頻道 ID"), "limit": integer("每串訊息數，上限 30", 20)}, h_recent_thread_messages, ["channel_id"])
    schema("discord_member_roles_summary", "Discord 可見資料", "統計提問者可見範圍中各身分組成員人數與分布", {}, h_role_summary)
    schema("discord_member_presence_summary", "Discord 可見資料", "彙總目前伺服器快取非機器人線上狀態分布，不查其他伺服器", {}, h_member_presence_summary)
    schema("discord_check_channel_permissions", "Discord 可見資料", "顯示提問者及 Bot 對目前伺服器可見頻道的常用權限", {"channel_id": integer("可見頻道 ID")}, h_channel_permissions)
    schema("guild_search_channels_by_topic", "Discord 可見資料", "搜尋提問者可見頻道名稱或主題文字", {"query": string("名稱或主題關鍵字")}, h_find_channels_by_topic, ["query"])
    return specs
