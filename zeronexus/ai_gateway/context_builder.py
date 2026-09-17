"""ZeroNexus AI Context & Memory Assembler.

Integrates:
- Shared Channel Conversation Context
- User Short-Term Conversational Rolling Window (up to 400 messages)
- Long-Term Persistent Facts (stored and recalled automatically or explicitly)
- Tool & API Grounded Results (Calculator, CWA Weather, Minecraft, Diagnostics)
- Dynamic User, Guild, and Channel metadata
- Token estimation & intelligent history budget truncation
- Deep blacklist regex defense for reserved system keys
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
from sqlalchemy import delete, desc, func, select

from zeronexus.core.config import config
from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.models.memory import ConversationMemory


# Regex pattern guarding all reserved system attributes and security parameters
RESERVED_KEY_PATTERNS = [
    r"model", r"模型",
    r"persona", r"人設", r"人格",
    r"role", r"身分", r"身份",
    r"admin", r"root", r"superuser", r"管理[員者]",
    r"token", r"key", r"secret", r"password", r"credential", r"密[鑰碼]", r"金鑰", r"憑證",
    r"permission", r"權限",
    r"quota", r"額度", r"配額",
    r"limit", r"上限",
    r"prompt", r"system", r"系統",
    r"dev(?:eloper)?", r"開發者",
    r"wallet", r"point", r"coin", r"balance", r"錢包", r"點數", r"餘額", r"金幣",
    r"bypass", r"jailbreak", r"override", r"越獄", r"繞過",
    r"config", r"設定", r"配置",
    r"instruction", r"指令",
]

# Narrower regex patterns guarding unkeyed fact values from injecting privilege escalations
UNKEYED_RESERVED_PATTERNS = [
    r"\b(?:admin|root|superuser)\b",
    r"管理[員者]",
    r"(?:身分|身份|role)\s*[:=]\s*(?:admin|root|superuser|dev)",
    r"system_role",
    r"is_admin",
    r"is_dev(?:eloper)?",
    r"preferred_model",
    r"偏好模型",
    r"quota_limit",
    r"bot_token",
    r"api_key",
]


def _normalize_memory_text(text: str) -> str:
    """Strips zero-width and invisible control characters and applies Unicode NFKC normalization."""
    if not text:
        return ""
    stripped = re.sub(r"[\u200b-\u200f\ufeff\u202a-\u202e\u2060-\u206f]", "", text)
    return unicodedata.normalize("NFKC", stripped)


def estimate_tokens(text: str) -> int:
    """Estimates token count for mixed English, code, and CJK text.

    Approximations:
    - CJK characters: ~1.5 tokens each
    - Words (Latin / numbers / identifiers): ~1.3 tokens each
    - Punctuation / other symbols: ~0.3 tokens each
    """
    if not text:
        return 0
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    ascii_words = re.findall(r"[a-zA-Z0-9_\-]+", text)
    word_count = len(ascii_words)
    word_chars = sum(len(w) for w in ascii_words)
    other_chars = max(0, len(text) - cjk_chars - word_chars)

    tokens = int(cjk_chars * 1.5 + word_count * 1.3 + other_chars * 0.3)
    return max(1, tokens)


def estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    """Estimates total tokens across a list of chat completion messages."""
    total = 0
    for m in messages:
        # Message envelope overhead (~4 tokens for role, name, format)
        total += 4 + estimate_tokens(m.get("content", ""))
    return total + 2  # Conversation priming tokens


def _to_utc(dt: datetime) -> datetime:
    """Ensures datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _filter_active_session(
    records: List[ConversationMemory],
    now: datetime,
    ttl_seconds: int,
) -> List[ConversationMemory]:
    """Filters records to only include turns within the latest active conversational session.

    Assumes records is ordered desc(created_at) (newest first).
    Returns list of records ordered asc(created_at) (chronological).
    """
    if not records:
        return []

    newest_time = _to_utc(records[0].created_at)
    if (now - newest_time).total_seconds() > ttl_seconds:
        return []

    active = [records[0]]
    for i in range(1, len(records)):
        curr_time = _to_utc(records[i].created_at)
        prev_time = _to_utc(records[i - 1].created_at)
        gap = (prev_time - curr_time).total_seconds()
        if gap > ttl_seconds:
            break
        active.append(records[i])

    active.reverse()
    return active


def extract_and_sanitize_ai_response(content: str) -> Tuple[str, Optional[str]]:
    """Extracts internal thinking/reasoning process and sanitizes the final user-facing text.
    
    Returns:
        (sanitized_text, thinking_process)
    """
    raw = (content or "").strip()
    if not raw:
        return "", None

    extracted_thoughts: List[str] = []
    thought_tags = "think|thought|reasoning|reflection|antthinking|cot|internal_thought"

    # Extract closed reasoning tags
    for match in re.finditer(rf"<(?:{thought_tags})(?:\s+[^>]*)?>([\s\S]*?)</(?:{thought_tags})>", raw, flags=re.IGNORECASE):
        th = match.group(1).strip()
        if th:
            extracted_thoughts.append(th)

    # Check unclosed trailing thinking tags
    unclosed_match = re.search(rf"<(?:{thought_tags})(?:\s+[^>]*)?>([\s\S]*)$", raw, flags=re.IGNORECASE)
    if unclosed_match and not extracted_thoughts:
        th = unclosed_match.group(1).strip()
        if th:
            extracted_thoughts.append(th)

    thinking_process = "\n\n".join(extracted_thoughts).strip() if extracted_thoughts else None

    # Perform full sanitization on content
    cleaned = sanitize_ai_response(raw)

    return cleaned, thinking_process


def sanitize_ai_response(content: str) -> str:
    """Purges leaked internal ReAct tool-call JSON, <think>/<thought> tags, and execution artifacts from AI text."""
    cleaned = (content or "").strip()
    if not cleaned:
        return ""

    # 1. Remove reasoning tags: closed <think>...</think>, <thought>, <reasoning>, <reflection>, <antThinking>, <cot>
    thought_tags = "think|thought|reasoning|reflection|antthinking|cot|internal_thought"
    cleaned = re.sub(
        rf"<(?:{thought_tags})(?:\s+[^>]*)?>[\s\S]*?</(?:{thought_tags})>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 1.1 Remove unclosed trailing thinking tags (e.g. truncated generation)
    cleaned = re.sub(
        rf"<(?:{thought_tags})(?:\s+[^>]*)?>[\s\S]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 2. Remove fenced code blocks containing action/tool calls or function calling payload
    cleaned = re.sub(
        r"```(?:json|tool_call|tool)?\s*[\{\[][\s\S]*?\"(?:action|function|tool_calls?|name|arguments|parameters)\"[\s\S]*?[\}\]]\s*```",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 3. Robust JSON object & array scanner: find any JSON block that contains tool invocation keywords
    def strip_leaked_json_blocks(s: str) -> str:
        idx = 0
        result_parts = []
        while idx < len(s):
            # Find earliest JSON opener: '{' or '['
            start_obj = s.find("{", idx)
            start_arr = s.find("[", idx)
            if start_obj == -1 and start_arr == -1:
                result_parts.append(s[idx:])
                break

            if start_obj != -1 and (start_arr == -1 or start_obj <= start_arr):
                start = start_obj
                open_ch, close_ch = "{", "}"
            else:
                start = start_arr
                open_ch, close_ch = "[", "]"

            result_parts.append(s[idx:start])

            depth = 0
            in_str = False
            escape = False
            end = -1
            for i in range(start, len(s)):
                ch = s[i]
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if not in_str:
                    if ch == open_ch:
                        depth += 1
                    elif ch == close_ch:
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break

            if end != -1:
                chunk = s[start:end]
                is_tool_leak = False
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict):
                        keys = {str(k).lower() for k in obj.keys()}
                        if any(k in keys for k in ("action", "action_input", "tool_call", "tool_calls")):
                            is_tool_leak = True
                        elif "tool" in keys and any(k in keys for k in ("input", "args", "parameters", "name")):
                            is_tool_leak = True
                        elif "function" in keys and any(k in keys for k in ("arguments", "name", "parameters")):
                            is_tool_leak = True
                        elif "name" in keys and any(k in keys for k in ("arguments", "parameters", "call_id")):
                            is_tool_leak = True
                    elif isinstance(obj, list):
                        for item in obj:
                            if isinstance(item, dict):
                                keys = {str(k).lower() for k in item.keys()}
                                if any(k in keys for k in ("action", "tool_call", "tool_calls", "function", "tool")):
                                    is_tool_leak = True
                                    break
                except Exception:
                    low_chunk = chunk.lower()
                    if ('"action"' in low_chunk or '"tool_call' in low_chunk or '"function"' in low_chunk) and (
                        '"action_input"' in low_chunk or '"thought"' in low_chunk or '"arguments"' in low_chunk or "dalle" in low_chunk
                    ):
                        is_tool_leak = True

                if not is_tool_leak:
                    result_parts.append(chunk)
                else:
                    # If this chunk was wrapped inside backticks, clean surrounding backticks
                    if result_parts and result_parts[-1].endswith("```json\n") or result_parts[-1].endswith("```\n"):
                        result_parts[-1] = re.sub(r"```(?:json)?\s*$", "", result_parts[-1])
                idx = end
            else:
                result_parts.append(s[start:])
                break

        return "".join(result_parts).strip()

    cleaned = strip_leaked_json_blocks(cleaned)

    # 4. Remove ReAct format internal steps (Action, Action Input, Observation, Thought)
    react_pattern = (
        r"^\s*(?:\*{0,2}(?:Action(?:\s+Input)?|Observation|Thought|"
        r"行動|動作|思考|觀察)\*{0,2}\s*[:：])\s*.*$(?:\n)?"
    )
    cleaned = re.sub(
        react_pattern,
        "",
        cleaned,
        flags=re.MULTILINE | re.IGNORECASE,
    ).strip()

    # 4.1 Strip "Final Answer:" or "最終答案：" prefixes while preserving the answer content
    final_ans_pattern = (
        r"^\s*(?:\*{0,2}(?:Final\s+Answer|最終回[答覆]|最終答案)\*{0,2}\s*[:：])\s*"
    )
    cleaned = re.sub(
        final_ans_pattern,
        "",
        cleaned,
        flags=re.MULTILINE | re.IGNORECASE,
    ).strip()

    # 5. Clean dangling empty fenced code blocks
    cleaned = re.sub(r"```(?:json|tool_call|tool)?\s*```", "", cleaned, flags=re.IGNORECASE).strip()

    # 6. Clean excessive newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _clean_stored_turn(content: str, role: str) -> str:
    """Sanitizes stored conversational turns to avoid few-shot roleplay leakage and tag repetition."""
    cleaned = (content or "").strip()
    if role == "assistant":
        cleaned = sanitize_ai_response(cleaned)
        while cleaned.startswith("[ZeroNexus]:"):
            cleaned = cleaned[len("[ZeroNexus]:"):].strip()
        cleaned = re.sub(r"\n+\s*🤖\s+[^\n]+(?:\s*·\s*\d{1,2}:\d{2})?\s*$", "", cleaned).strip()
        # Strip memory extraction tags to avoid leaking internal control protocol into history
        cleaned = re.sub(r"\[(?:REMEMBER|MEMORIZE):\s*[^\]]+\]", "", cleaned, flags=re.IGNORECASE).strip()
    elif role == "user":
        cleaned = re.sub(r"^\[[^\]]+\]:\s*", "", cleaned)
    return cleaned


class ContextBuilder:
    """Assembles prompt payloads, token budgets, and manages short/long term memory persistence."""

    async def fetch_channel_shared_context(
        self,
        channel_id: int,
        limit: int = 15,
        ttl_seconds: Optional[int] = None,
        is_secret_easter_egg: bool = False,
    ) -> List[Dict[str, str]]:
        """Retrieves recent group conversation history from an AI-designated channel with TTL & session cutoff."""
        ttl = ttl_seconds if ttl_seconds is not None else config.ai.memory_ttl_seconds
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=ttl)
        target_scope = "secret_short_term" if is_secret_easter_egg else "channel_shared"
        effective_limit = min(limit, 500) if is_secret_easter_egg else limit

        async with db.session() as session:
            stmt = (
                select(ConversationMemory)
                .where(
                    ConversationMemory.scope == target_scope,
                    ConversationMemory.channel_id == channel_id,
                    ConversationMemory.created_at >= cutoff,
                )
                .order_by(desc(ConversationMemory.created_at))
                .limit(effective_limit)
            )
            result = await session.execute(stmt)
            raw_records = list(result.scalars().all())

            active_records = _filter_active_session(raw_records, now, ttl)

            messages: List[Dict[str, str]] = []
            for r in active_records:
                clean_text = _clean_stored_turn(r.content, r.role)
                if r.role == "user":
                    prefix = f"[{r.speaker_name or '成員'}]: "
                    messages.append({
                        "role": "user",
                        "content": f"{prefix}{clean_text}",
                    })
                else:
                    # Assistant role messages must NOT have prefix to prevent few-shot hallucination
                    messages.append({
                        "role": "assistant",
                        "content": clean_text,
                    })
            return messages

    async def fetch_user_short_term_context(
        self,
        user_id: int,
        limit: int = 20,
        ttl_seconds: Optional[int] = None,
        is_secret_easter_egg: bool = False,
    ) -> List[Dict[str, str]]:
        """Retrieves rolling conversational turns for an individual user with TTL & session cutoff."""
        ttl = ttl_seconds if ttl_seconds is not None else config.ai.memory_ttl_seconds
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=ttl)
        target_scope = "secret_short_term" if is_secret_easter_egg else "user_short_term"
        effective_limit = min(limit, 500) if is_secret_easter_egg else limit

        async with db.session() as session:
            stmt = (
                select(ConversationMemory)
                .where(
                    ConversationMemory.scope == target_scope,
                    ConversationMemory.user_id == user_id,
                    ConversationMemory.created_at >= cutoff,
                )
                .order_by(desc(ConversationMemory.created_at))
                .limit(effective_limit)
            )
            result = await session.execute(stmt)
            raw_records = list(result.scalars().all())

            active_records = _filter_active_session(raw_records, now, ttl)

            return [{"role": r.role, "content": _clean_stored_turn(r.content, r.role)} for r in active_records]

    async def fetch_user_long_term_facts(
        self,
        user_id: int,
        is_secret_easter_egg: bool = False,
    ) -> List[str]:
        """Retrieves extracted long-term memories and personal preferences."""
        target_scope = "secret_long_term" if is_secret_easter_egg else "user_long_term"
        async with db.session() as session:
            stmt = (
                select(ConversationMemory)
                .where(
                    ConversationMemory.scope == target_scope,
                    ConversationMemory.user_id == user_id,
                )
                .order_by(ConversationMemory.created_at)
                .limit(500 if is_secret_easter_egg else 50)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            facts: List[str] = []
            for r in records:
                if r.fact_key and r.fact_key != r.content:
                    facts.append(f"- {r.fact_key}: {r.content}")
                else:
                    facts.append(f"- {r.content}")
            return facts

    async def save_interaction_memories(
        self,
        user: discord.User | discord.Member,
        channel: discord.abc.Messageable,
        guild: Optional[discord.Guild],
        user_content: str,
        assistant_content: str,
        is_shared_ai_channel: bool = False,
        save_short_term: bool = True,
        is_secret_easter_egg: bool = False,
    ) -> None:
        """Persists short-term chat logs and automatically extracts worthy long-term memories."""
        channel_id = getattr(channel, "id", 0)
        guild_id = guild.id if guild else None

        clean_user_text = _clean_stored_turn(user_content, "user")
        clean_assistant_text = _clean_stored_turn(assistant_content, "assistant")

        if is_secret_easter_egg:
            async with db.session() as session:
                # 1. Save to secret_short_term
                if save_short_term:
                    session.add(ConversationMemory(
                        scope="secret_short_term",
                        guild_id=guild_id,
                        channel_id=channel_id,
                        user_id=user.id,
                        role="user",
                        speaker_name=user.display_name,
                        content=clean_user_text,
                    ))
                    session.add(ConversationMemory(
                        scope="secret_short_term",
                        guild_id=guild_id,
                        channel_id=channel_id,
                        user_id=user.id,
                        role="assistant",
                        speaker_name="ZeroNexus",
                        content=clean_assistant_text,
                    ))

                # Enforce rolling window of up to 500 messages
                st_count_stmt = select(func.count()).select_from(ConversationMemory).where(
                    ConversationMemory.scope == "secret_short_term",
                    ConversationMemory.user_id == user.id,
                )
                st_count = await session.scalar(st_count_stmt) or 0
                if st_count > 500:
                    excess = st_count - 500
                    old_subq = (
                        select(ConversationMemory.id)
                        .where(
                            ConversationMemory.scope == "secret_short_term",
                            ConversationMemory.user_id == user.id,
                        )
                        .order_by(ConversationMemory.created_at)
                        .limit(excess)
                    )
                    old_ids = (await session.execute(old_subq)).scalars().all()
                    if old_ids:
                        await session.execute(
                            delete(ConversationMemory).where(ConversationMemory.id.in_(old_ids))
                        )

                # 2. Secret Long-Term Memory Extraction
                tag_matches = re.finditer(
                    r"\[(?:REMEMBER|MEMORIZE):\s*([^=\]:\r\n]+?)(?:(?:\s*[=:]\s*)([^\]\r\n]+))?\]",
                    assistant_content,
                    re.IGNORECASE,
                )
                for m in tag_matches:
                    k_part = m.group(1).strip()
                    v_part = m.group(2).strip() if m.group(2) else None
                    if v_part is not None and v_part != "":
                        key_clean = re.sub(r"[\r\n\t]+", " ", k_part).strip()[:64]
                        val_clean = v_part[:1000].strip()
                    else:
                        key_clean = None
                        val_clean = k_part[:1000].strip()

                    if not val_clean:
                        continue

                    if key_clean:
                        existing_stmt = select(ConversationMemory).where(
                            ConversationMemory.scope == "secret_long_term",
                            ConversationMemory.user_id == user.id,
                            ConversationMemory.fact_key == key_clean,
                        )
                        existing_res = await session.execute(existing_stmt)
                        existing = existing_res.scalars().first()
                        if existing:
                            existing.content = val_clean
                            existing.created_at = datetime.now(timezone.utc)
                            continue
                    else:
                        existing_stmt = select(ConversationMemory).where(
                            ConversationMemory.scope == "secret_long_term",
                            ConversationMemory.user_id == user.id,
                            ConversationMemory.content == val_clean,
                        )
                        existing_res = await session.execute(existing_stmt)
                        existing = existing_res.scalars().first()
                        if existing:
                            existing.created_at = datetime.now(timezone.utc)
                            continue

                    count_stmt = select(func.count()).select_from(ConversationMemory).where(
                        ConversationMemory.scope == "secret_long_term",
                        ConversationMemory.user_id == user.id,
                    )
                    fact_count = await session.scalar(count_stmt) or 0
                    if fact_count >= 500:
                        oldest_stmt = (
                            select(ConversationMemory)
                            .where(
                                ConversationMemory.scope == "secret_long_term",
                                ConversationMemory.user_id == user.id,
                            )
                            .order_by(ConversationMemory.created_at)
                            .limit(1)
                        )
                        oldest = (await session.execute(oldest_stmt)).scalars().first()
                        if oldest:
                            await session.delete(oldest)

                    session.add(ConversationMemory(
                        scope="secret_long_term",
                        guild_id=guild_id,
                        channel_id=channel_id,
                        user_id=user.id,
                        role="system",
                        fact_key=key_clean,
                        content=val_clean,
                    ))
            return

        async with db.session() as session:
            # 1. Save user short-term turn if requested
            if save_short_term:
                session.add(ConversationMemory(
                    scope="user_short_term",
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user.id,
                    role="user",
                    speaker_name=user.display_name,
                    content=clean_user_text,
                ))
                session.add(ConversationMemory(
                    scope="user_short_term",
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user.id,
                    role="assistant",
                    speaker_name="ZeroNexus",
                    content=clean_assistant_text,
                ))

            # 1.1 Enforce short-term memory rolling window limit (up to 400 messages per user)
            st_count_stmt = select(func.count()).select_from(ConversationMemory).where(
                ConversationMemory.scope == "user_short_term",
                ConversationMemory.user_id == user.id,
            )
            st_count = await session.scalar(st_count_stmt) or 0
            if st_count > 400:
                excess = st_count - 400
                old_subq = (
                    select(ConversationMemory.id)
                    .where(
                        ConversationMemory.scope == "user_short_term",
                        ConversationMemory.user_id == user.id,
                    )
                    .order_by(ConversationMemory.created_at)
                    .limit(excess)
                )
                old_ids = (await session.execute(old_subq)).scalars().all()
                if old_ids:
                    await session.execute(
                        delete(ConversationMemory).where(ConversationMemory.id.in_(old_ids))
                    )

            # 2. If in shared AI channel, also save to channel_shared
            if is_shared_ai_channel:
                session.add(ConversationMemory(
                    scope="channel_shared",
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user.id,
                    role="user",
                    speaker_name=user.display_name,
                    content=clean_user_text,
                ))
                session.add(ConversationMemory(
                    scope="channel_shared",
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user.id,
                    role="assistant",
                    speaker_name="ZeroNexus",
                    content=clean_assistant_text,
                ))

            # 3. Automatic Long-Term Memory Extraction
            # Detects tags like [REMEMBER: key = value], [REMEMBER: key: value], or [MEMORIZE: fact] output by AI
            tag_matches = re.finditer(
                r"\[(?:REMEMBER|MEMORIZE):\s*([^=\]:\r\n]+?)(?:(?:\s*[=:]\s*)([^\]\r\n]+))?\]",
                assistant_content,
                re.IGNORECASE,
            )

            for m in tag_matches:
                k_part = m.group(1).strip()
                v_part = m.group(2).strip() if m.group(2) else None

                if v_part is not None and v_part != "":
                    key_clean = re.sub(r"[\r\n\t]+", " ", k_part).strip()[:64]
                    val_clean = v_part[:1000].strip()
                else:
                    key_clean = None
                    val_clean = k_part[:1000].strip()

                if not val_clean:
                    continue

                # Defend against injection into reserved system parameters
                norm_k = _normalize_memory_text(key_clean).lower() if key_clean else None
                norm_v = _normalize_memory_text(val_clean).lower()

                if norm_k and any(re.search(pat, norm_k) for pat in RESERVED_KEY_PATTERNS):
                    log.warning(
                        f"Blocked unauthorized memory write to reserved key '{key_clean}' for user {user.id}."
                    )
                    continue

                # Defend against privilege escalation patterns in content (both keyed and unkeyed)
                if any(re.search(pat, norm_v) for pat in UNKEYED_RESERVED_PATTERNS):
                    log.warning(
                        f"Blocked unauthorized privileged pattern in memory content '{val_clean}' for user {user.id}."
                    )
                    continue

                # Check if fact already exists for this user (Upsert deduplication)
                if key_clean:
                    existing_stmt = select(ConversationMemory).where(
                        ConversationMemory.scope == "user_long_term",
                        ConversationMemory.user_id == user.id,
                        ConversationMemory.fact_key == key_clean,
                    )
                    existing_res = await session.execute(existing_stmt)
                    existing = existing_res.scalars().first()
                    if existing:
                        existing.content = val_clean
                        existing.created_at = datetime.now(timezone.utc)
                        log.info(f"Updated existing long term memory for user {user.id}: {key_clean} = {val_clean}")
                        continue
                else:
                    existing_stmt = select(ConversationMemory).where(
                        ConversationMemory.scope == "user_long_term",
                        ConversationMemory.user_id == user.id,
                        ConversationMemory.content == val_clean,
                    )
                    existing_res = await session.execute(existing_stmt)
                    existing = existing_res.scalars().first()
                    if existing:
                        existing.created_at = datetime.now(timezone.utc)
                        continue

                # Cap total long-term facts per user to 50 to protect context window
                count_stmt = select(func.count()).select_from(ConversationMemory).where(
                    ConversationMemory.scope == "user_long_term",
                    ConversationMemory.user_id == user.id,
                )
                fact_count = await session.scalar(count_stmt) or 0
                if fact_count >= 50:
                    oldest_stmt = (
                        select(ConversationMemory)
                        .where(
                            ConversationMemory.scope == "user_long_term",
                            ConversationMemory.user_id == user.id,
                        )
                        .order_by(ConversationMemory.created_at)
                        .limit(1)
                    )
                    oldest = (await session.execute(oldest_stmt)).scalars().first()
                    if oldest:
                        await session.delete(oldest)

                session.add(ConversationMemory(
                    scope="user_long_term",
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user.id,
                    role="system",
                    fact_key=key_clean,
                    content=val_clean,
                ))
                log.info(f"Auto-saved long term memory for user {user.id}: {key_clean or 'FACT'} = {val_clean}")

    async def get_custom_persona(
        self,
        user_id: int,
        guild_id: Optional[int],
        persona_name: str,
    ) -> Optional[Any]:
        """Looks up a custom persona definition from database."""
        from zeronexus.models.persona import CustomPersonaModel
        clean_name = persona_name.strip()
        async with db.session() as session:
            # Query custom persona belonging to this user or current guild
            stmt = select(CustomPersonaModel).where(
                CustomPersonaModel.name == clean_name,
                (CustomPersonaModel.created_by_user_id == user_id) | (CustomPersonaModel.guild_id == guild_id),
            )
            res = await session.execute(stmt)
            return res.scalars().first()

    def compile_custom_persona_instructions(self, custom: Any) -> str:
        """Assembles custom persona metadata into coherent system prompt instructions."""
        parts = [
            f"【客製化專屬自訂人格：{custom.name}】",
            f"- 核心性格特徵：{custom.personality}",
            f"- 說話習慣、口頭禪與語氣：{custom.speaking_habits}",
        ]
        if getattr(custom, "forbidden_behaviors", None):
            parts.append(f"- 絕對禁忌事項：{custom.forbidden_behaviors}")
        return "\n".join(parts)

    async def build_messages(
        self,
        user: discord.User | discord.Member,
        channel: discord.abc.Messageable,
        guild: Optional[discord.Guild],
        user_prompt: str,
        tool_results: Optional[Dict[str, Any]] = None,
        is_shared_ai_channel: bool = False,
        active_persona_key: Optional[str] = None,
        max_history_turns: Optional[int] = None,
        max_history_tokens: int = 4000,
        include_short_term_history: bool = True,
        custom_persona_instructions: Optional[str] = None,
        is_secret_easter_egg: bool = False,
    ) -> List[Dict[str, str]]:
        """Constructs unified multi-turn conversation payload for AI Gateway with token budgeting & user identity."""
        messages: List[Dict[str, str]] = []

        # 1. User Identity & Runtime Context Header
        is_dev = config.discord.is_dev(user.id)
        user_display = getattr(user, "display_name", getattr(user, "name", f"User_{user.id}"))
        guild_name = guild.name if guild else "私訊 (Direct Message)"
        channel_name = getattr(channel, "name", "一般頻道")
        channel_id = getattr(channel, "id", 0)

        identity_lines = [
            f"- 溝通對象：{user_display} (User ID: {user.id})",
            f"- 伺服器環境：{guild_name}" + (f" (ID: {guild.id})" if guild else ""),
            f"- 溝通頻道：#{channel_name} (ID: {channel_id})",
            f"- 使用者身分級別：{'🛠️ 平台核心開發者 (Developer - 無額度限制)' if is_dev else '一般成員 (Standard User)'}",
        ]
        if is_secret_easter_egg:
            identity_lines.append("- 特殊模式：✨ 絕密彩蛋領域 (完全私密獨立、500 句專屬記憶)")

        messages.append({
            "role": "system",
            "content": "【使用者身分與環境上下文 (User Identity & Runtime Context)】：\n" + "\n".join(identity_lines),
        })

        # 1.5. Dynamic Capabilities & Runtime Ground-Truth Injection
        try:
            from zeronexus.intelligence.capability_registry import capability_registry
            capabilities_prompt = capability_registry.get_dynamic_capabilities_prompt()
            messages.append({
                "role": "system",
                "content": capabilities_prompt,
            })
        except Exception as cap_err:
            log.warning(f"Failed to inject dynamic capabilities prompt: {cap_err}")

        # 2 & 3. Concurrently fetch long-term facts and conversation history
        channel_id = getattr(channel, "id", 0)
        default_limit = 500 if is_secret_easter_egg else (15 if is_shared_ai_channel else 20)
        fetch_limit = max_history_turns if max_history_turns is not None else default_limit
        effective_max_tokens = 100000 if is_secret_easter_egg else max_history_tokens

        async def _fetch_history() -> List[Dict[str, str]]:
            if not include_short_term_history:
                return []
            if is_secret_easter_egg:
                return await self.fetch_user_short_term_context(
                    user.id, limit=fetch_limit, is_secret_easter_egg=True
                )
            elif is_shared_ai_channel:
                return await self.fetch_channel_shared_context(channel_id, limit=fetch_limit)
            else:
                return await self.fetch_user_short_term_context(user.id, limit=fetch_limit)

        long_term_facts, history_msgs = await asyncio.gather(
            self.fetch_user_long_term_facts(user.id, is_secret_easter_egg=is_secret_easter_egg),
            _fetch_history(),
        )

        if long_term_facts:
            facts_budget = 40000 if is_secret_easter_egg else 2000
            cur_tokens = 0
            selected_facts = []
            # 優先保留最新事實，避免長期記憶無節制膨脹撐爆 Context Window
            for f in reversed(long_term_facts):
                f_tok = estimate_tokens(f)
                if cur_tokens + f_tok > facts_budget and selected_facts:
                    break
                selected_facts.append(f)
                cur_tokens += f_tok
            selected_facts.reverse()
            facts_text = "\n".join(selected_facts)
            messages.append({
                "role": "system",
                "content": f"【此使用者的重要長期記憶與偏好備忘】：\n{facts_text}",
            })

        if include_short_term_history and history_msgs:
            # 單條過長歷史訊息防護：防止使用者單次巨型貼上癱瘓後續對話上下文
            for hm in history_msgs:
                c = hm.get("content", "")
                if len(c) > 4000:
                    hm["content"] = c[:2000] + "\n...[過長歷史對話已安全截斷]...\n" + c[-1000:]

            # 智慧歷史預算截斷：持續彈出最舊對話回合直至符合 token 預算上限
            while history_msgs and estimate_messages_tokens(history_msgs) > effective_max_tokens:
                history_msgs.pop(0)

            # 確保對話歷史不以 assistant 作為首輪，符合各大模型 chat completion 規範
            if history_msgs and history_msgs[0].get("role") == "assistant":
                history_msgs.pop(0)

            messages.extend(history_msgs)

        # 4. Grounded Tool Results (Calculator / Weather / Minecraft / System)
        if tool_results:
            tool_summary_lines: List[str] = []
            for tool_name, res in tool_results.items():
                tool_summary_lines.append(f"[{tool_name} 執行結果]: {res}")
            tool_payload = "\n".join(tool_summary_lines)
            messages.append({
                "role": "system",
                "content": (
                    "【外部工具與可靠引擎計算結果（真實資料，優先度最高，請依此回答）】：\n"
                    f"{tool_payload}"
                ),
            })

        # 5. Strict active persona enforcement (prevents history few-shot persona drift)
        if custom_persona_instructions:
            messages.append({
                "role": "system",
                "content": (
                    f"【當前生效之自訂客製人格切換強制指令】：\n"
                    f"{custom_persona_instructions}\n"
                    "若上方的歷史對話中曾出現過其他不同人設（例如貓貓、法師、管家等）的發言口癖，那是舊歷史，請立即全部拋棄！\n"
                    "請務必嚴格以當前指定之自訂人格口吻、特質、價值觀與語氣來回應接下來的使用者訊息！"
                ),
            })
        elif active_persona_key:
            from zeronexus.engines.prompt_engine import PERSONA_MAP
            persona_desc = PERSONA_MAP.get(active_persona_key, "")
            if not persona_desc:
                from zeronexus.engines.prompt_engine import prompt_engine
                full_desc = prompt_engine.get_persona_directive(active_persona_key)
                persona_desc = full_desc[:500] + ("..." if len(full_desc) > 500 else "")
            messages.append({
                "role": "system",
                "content": (
                    f"【當前生效之人格切換強制指令】：\n"
                    f"{persona_desc}\n"
                    "若上方的歷史對話中曾出現過其他不同人設（例如貓貓『喵～』、法師、管家等）的發言口癖，"
                    "那是先前的舊歷史，請立即全部拋棄！\n"
                    "請務必嚴格以當前指定的人格口吻、價值觀與語氣來回應接下來的使用者訊息！"
                ),
            })

        # 6. Current user prompt
        prompt_content = f"[{user.display_name}]: {user_prompt}" if is_shared_ai_channel else user_prompt
        messages.append({
            "role": "user",
            "content": prompt_content,
        })

        return messages

    async def purge_expired_memories(
        self,
        max_age_seconds: Optional[int] = None,
    ) -> int:
        """Purges expired short-term and channel shared conversation records.

        Strictly preserves user_long_term facts.
        """
        ttl = max_age_seconds if max_age_seconds is not None else config.ai.memory_ttl_seconds
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl)
        async with db.session() as session:
            stmt = (
                delete(ConversationMemory)
                .where(
                    ConversationMemory.scope.in_(["user_short_term", "channel_shared"]),
                    ConversationMemory.created_at < cutoff,
                )
            )
            res = await session.execute(stmt)
            deleted_count = res.rowcount or 0
            if deleted_count > 0:
                log.info(f"Purged {deleted_count} expired short-term/channel conversation memories (older than {ttl}s).")
            return deleted_count


# Singleton context builder
context_builder = ContextBuilder()


TOOL_DISPLAY_NAME_MAP: Dict[str, str] = {
    "python_code_sandbox": "安全程式碼沙盒 (Python Sandbox)",
    "plot_chart": "圖表渲染引擎",
    "calculator": "高精度計算引擎",
    "weather_probe": "中央氣象署即時觀測",
    "earthquake_probe": "中央氣象署地震測報",
    "cpc_fuel_prices": "中油即時油價與預估走勢",
    "taiwan_invoice_lottery": "統一發票中獎號碼清單",
    "stock_quote": "股市即時行情報價",
    "query_rail_timetable": "台鐵/高鐵時刻表與誤點資訊",
    "minecraft_probe": "Minecraft 伺服器探測",
    "web_search": "即時網路搜尋",
    "bilibili_video_info": "Bilibili 影片解析",
    "ip_geo_info": "IP 網路歸屬地查詢",
    "check_website_ssl": "SSL 憑證與健康檢測",
    "database_stats": "系統資料庫狀態",
    "inspect_channel_messages": "頻道歷史聊天記錄檢索",
    "analyze_channel_activity": "頻道發言活躍度與排行榜分析",
    "inspect_channel_overview": "頻道全方位情資總覽",
}


def format_tool_execution_trace(tool_calls: List[Dict[str, Any]]) -> str:
    """Formats raw tool executions into clean, structured Markdown for transparent verification."""
    if not tool_calls:
        return ""

    traces: List[str] = []
    for idx, tc in enumerate(tool_calls, 1):
        raw_name = str(tc.get("name") or "unknown_tool").strip()
        display_name = TOOL_DISPLAY_NAME_MAP.get(raw_name, raw_name)
        args = tc.get("args") or {}
        result = tc.get("result") or {}

        trace_lines: List[str] = [f"### ⚙️ 工具調用 {idx}：{display_name}"]

        # 特殊處理 Python 程式碼沙盒
        if raw_name == "python_code_sandbox":
            code = args.get("code", "").strip() if isinstance(args, dict) else str(args).strip()
            if code:
                trace_lines.append(f"▸ **執行程式碼**：\n```python\n{code}\n```")
            if isinstance(result, dict):
                stdout = str(result.get("stdout") or "").strip()
                err = str(result.get("error") or "").strip()
                exec_time = result.get("execution_time_ms")
                if stdout:
                    if len(stdout) > 1200:
                        stdout = stdout[:1200] + "\n...(其餘輸出已截斷)"
                    trace_lines.append(f"▸ **標準輸出 (stdout)**：\n```\n{stdout}\n```")
                if err:
                    trace_lines.append(f"▸ **執行狀態/錯誤**：\n```\n{err}\n```")
                if exec_time is not None:
                    trace_lines.append(f"▸ **沙盒耗時**：`{exec_time} ms`")
            elif result:
                trace_lines.append(f"▸ **執行結果**：\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```")
        elif raw_name == "inspect_channel_messages":
            ch_name = result.get("channel_name", "當前頻道") if isinstance(result, dict) else "當前頻道"
            filter_applied = result.get("filter_applied", "無") if isinstance(result, dict) else "無"
            msg_cnt = result.get("messages_count", 0) if isinstance(result, dict) else 0
            trace_lines.append(f"▸ **檢視頻道**：`#{ch_name}`")
            trace_lines.append(f"▸ **時間過濾**：`{filter_applied}`（已載入 {msg_cnt} 則訊息）")
            if isinstance(result, dict) and result.get("transcript"):
                sample = result["transcript"]
                if len(sample) > 500:
                    sample = sample[:500] + "\n...(其餘聊天記錄已供模型分析)"
                trace_lines.append(f"▸ **對話日誌摘錄**：\n```\n{sample}\n```")
        elif raw_name == "analyze_channel_activity":
            ch_name = result.get("channel_name", "當前頻道") if isinstance(result, dict) else "當前頻道"
            total_m = result.get("total_messages", 0) if isinstance(result, dict) else 0
            authors = result.get("unique_authors_count", 0) if isinstance(result, dict) else 0
            trace_lines.append(f"▸ **分析頻道**：`#{ch_name}`（共 {total_m} 則訊息，{authors} 位成員參與）")
            top_sp = result.get("top_speakers", []) if isinstance(result, dict) else []
            if top_sp:
                top_str = "、".join(f"{s.get('name')} ({s.get('message_count')}則)" for s in top_sp[:3])
                trace_lines.append(f"▸ **發言榜首**：{top_str}")
        elif raw_name == "inspect_channel_overview":
            ch_name = result.get("channel_name", "當前頻道") if isinstance(result, dict) else "當前頻道"
            topic = result.get("topic", "無") if isinstance(result, dict) else "無"
            threads_cnt = result.get("active_threads_count", 0) if isinstance(result, dict) else 0
            trace_lines.append(f"▸ **頻道資訊**：`#{ch_name}` | 主題：*{topic}* | 討論串：{threads_cnt} 個")
        elif raw_name == "plot_chart":
            chart_type = args.get("chart_type", "圖表") if isinstance(args, dict) else "圖表"
            title = args.get("title", "") if isinstance(args, dict) else ""
            trace_lines.append(f"▸ **圖表類型**：`{chart_type}`（標題：{title}）")
            if isinstance(result, dict) and result.get("success"):
                trace_lines.append("▸ **渲染狀態**：`成功生成圖表影像`")
        elif raw_name == "web_search":
            query = args.get("query", "") if isinstance(args, dict) else str(args)
            trace_lines.append(f"▸ **搜尋關鍵字**：`{query}`")
            if isinstance(result, dict):
                items = result.get("results") or result.get("data") or []
                trace_lines.append(f"▸ **檢索結果**：共取得 {len(items)} 筆即時網頁資料")
        else:
            if isinstance(args, dict) and args:
                args_str = json.dumps(args, ensure_ascii=False, indent=2)
                if len(args_str) > 500:
                    args_str = args_str[:500] + "\n...(其餘參數已摺疊)"
                trace_lines.append(f"▸ **輸入引數**：\n```json\n{args_str}\n```")
            if isinstance(result, dict) and result:
                filtered_res = {k: v for k, v in result.items() if k not in ("raw_response", "html", "content")}
                res_str = json.dumps(filtered_res, ensure_ascii=False, indent=2)
                if len(res_str) > 800:
                    res_str = res_str[:800] + "\n...(其餘數據已摺疊)"
                trace_lines.append(f"▸ **觀測數據**：\n```json\n{res_str}\n```")

        traces.append("\n".join(trace_lines))

    return "\n\n".join(traces)


def combine_thinking_and_tools(
    native_thinking: Optional[str],
    tool_calls: Optional[List[Dict[str, Any]]],
) -> Optional[str]:
    """Combines model's native reasoning chain and real tool execution traces transparently."""
    sections: List[str] = []
    if native_thinking and native_thinking.strip():
        sections.append(f"## 💭 AI 思維推演歷程\n{native_thinking.strip()}")

    if tool_calls:
        trace = format_tool_execution_trace(tool_calls)
        if trace:
            sections.append(f"## ⚙️ 工具調用與執行脈絡\n{trace}")

    return "\n\n---\n\n".join(sections) if sections else None

