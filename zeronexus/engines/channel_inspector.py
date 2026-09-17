"""ZeroNexus Discord 頻道情境洞察與情資分析引擎 (Channel Context Intelligence & Analytics Engine).

提供頻道即時歷史聊天記錄抓取、自然語言時間過濾、發言之王與活躍度統計、
以及頻道全方位情資掃描，為 AI 智慧體與社群管理員提供深度的上下文感知能力。
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
import pytz

from zeronexus.core.logger import log

# 臺灣標準時區 (Asia/Taipei)
TAIPEI_TZ = pytz.timezone("Asia/Taipei")


def parse_channel_time_filter(
    time_str: str,
    base_dt: Optional[datetime] = None,
) -> Tuple[Optional[datetime], Optional[str]]:
    """解析自然語言時間過濾條件，並轉化為帶有時區意識的 UTC datetime。

    支援範例：
    - "20:03", "20:03:00", "20點03分", "晚上8點03分", "20:03開始"
    - "今天 20:03", "昨天 21:00"
    - "30分鐘前", "1小時前", "2小時前", "1天前", "半小時前"
    - "2026-09-16 20:03"

    回傳：
        (target_utc_datetime, formatted_description)
    """
    if not time_str or not time_str.strip():
        return None, None

    clean = time_str.strip()
    # 循環去除前後常見前綴贅字與後綴贅字
    for _ in range(4):
        clean = re.sub(r"^(?:從|自|由|在|於|幫我|請幫我|請)", "", clean).strip()
        clean = re.sub(r"(?:開始|起|之後|以後|的所有訊息|的聊天記錄|的所有聊天|的所有對話|的訊息|訊息|對話)$", "", clean).strip()

    now_local = datetime.now(TAIPEI_TZ) if base_dt is None else base_dt.astimezone(TAIPEI_TZ)

    # 1. 相對時間比對 (例如: 30分鐘前, 1小時前, 2天前, 半小時前)
    if "半小時前" in clean or "半小時" in clean:
        target_local = now_local - timedelta(minutes=30)
        return target_local.astimezone(timezone.utc), "30 分鐘前"

    rel_m = re.search(r"(\d+)\s*(分鐘|分|小時|hr|h|天|日|秒|s)前?", clean, re.IGNORECASE)
    if rel_m:
        val = int(rel_m.group(1))
        unit = rel_m.group(2).lower()
        if unit in ("分鐘", "分"):
            target_local = now_local - timedelta(minutes=val)
            desc = f"{val} 分鐘前"
        elif unit in ("小時", "hr", "h"):
            target_local = now_local - timedelta(hours=val)
            desc = f"{val} 小時前"
        elif unit in ("天", "日"):
            target_local = now_local - timedelta(days=val)
            desc = f"{val} 天前"
        else:
            target_local = now_local - timedelta(seconds=val)
            desc = f"{val} 秒前"
        return target_local.astimezone(timezone.utc), desc

    # 2. 絕對日期 + 時間 (例如: 2026-09-16 20:03, 09/16 20:03)
    full_dt_m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?", clean)
    if full_dt_m:
        y, m, d, hh, mm = int(full_dt_m.group(1)), int(full_dt_m.group(2)), int(full_dt_m.group(3)), int(full_dt_m.group(4)), int(full_dt_m.group(5))
        ss = int(full_dt_m.group(6) or 0)
        dt_local = TAIPEI_TZ.localize(datetime(y, m, d, hh, mm, ss))
        return dt_local.astimezone(timezone.utc), dt_local.strftime("%Y-%m-%d %H:%M:%S")

    # 3. 今天/昨天 + 時間 (例如: 今天 20:03, 昨天 19:30)
    day_offset = 0
    if "昨天" in clean:
        day_offset = 1
    elif "前天" in clean:
        day_offset = 2

    # 中文上下午處理 (如: 下午 8:03, 晚上 8:03)
    pm_bonus = 0
    if any(p in clean for p in ("下午", "晚上", "pm", "PM")):
        pm_bonus = 12

    # 4. 時分比對 (例如: 20:03, 20:03:15, 20點03分)
    time_m = re.search(r"(\d{1,2})[:點時](\d{1,2})(?:[:分](\d{1,2}))?", clean)
    if time_m:
        hh = int(time_m.group(1))
        mm = int(time_m.group(2))
        ss = int(time_m.group(3) or 0)
        if pm_bonus and hh < 12:
            hh += pm_bonus

        ref_day = now_local.date() - timedelta(days=day_offset)
        target_local = TAIPEI_TZ.localize(datetime(ref_day.year, ref_day.month, ref_day.day, hh, mm, ss))

        # 若使用者未指定日期且算出的時間比現在還晚超過 30 分鐘，可能指的是昨天的這個時間
        if day_offset == 0 and (target_local - now_local).total_seconds() > 1800:
            target_local -= timedelta(days=1)
            desc_prefix = "昨天 "
        elif day_offset == 1:
            desc_prefix = "昨天 "
        elif day_offset == 2:
            desc_prefix = "前天 "
        else:
            desc_prefix = "今天 "

        return target_local.astimezone(timezone.utc), f"{desc_prefix}{hh:02d}:{mm:02d}:{ss:02d}"

    return None, None


class ChannelInspectorEngine:
    """Discord 頻道情資檢索與訊息分析核心引擎。"""

    MAX_FETCH_LIMIT: int = 300
    DEFAULT_FETCH_LIMIT: int = 100

    async def fetch_channel_messages(
        self,
        channel: Any,
        after: Optional[datetime] = None,
        limit: int = DEFAULT_FETCH_LIMIT,
        bot_user_id: Optional[int] = None,
    ) -> Tuple[List[Any], Optional[str]]:
        """非同步讀取頻道的歷史訊息，並進行權限檢查與邊界保護。

        回傳：
            (messages_list, error_message)
        """
        if not hasattr(channel, "history"):
            return [], "目標對象不支援歷史訊息讀取（非文字頻道或討論串）。"

        # 檢查權限
        guild = getattr(channel, "guild", None)
        if guild and hasattr(channel, "permissions_for"):
            me = getattr(guild, "me", None)
            if me:
                perms = channel.permissions_for(me)
                if not getattr(perms, "read_messages", True) or not getattr(perms, "read_message_history", True):
                    return [], f"機器人缺少在頻道 #{getattr(channel, 'name', '未知')} 讀取歷史訊息的權限 (Read Messages / Read Message History)。"

        fetch_limit = min(max(int(limit), 1), self.MAX_FETCH_LIMIT)

        try:
            messages: List[Any] = []
            if after is not None:
                # 依時間順序由舊到新讀取
                async for msg in channel.history(after=after, limit=fetch_limit, oldest_first=True):
                    messages.append(msg)
            else:
                # 讀取最新 N 則，並翻轉為時序排列
                async for msg in channel.history(limit=fetch_limit):
                    messages.append(msg)
                messages.reverse()

            return messages, None
        except discord.Forbidden:
            return [], "存取遭拒：機器人無權限檢視頻道訊息歷史。"
        except Exception as e:
            log.error(f"[ChannelInspector] 讀取頻道訊息歷史失敗：{e}", exc_info=True)
            return [], f"讀取頻道訊息時發生異常：{e}"

    def format_messages_to_transcript(
        self,
        messages: List[Any],
        bot_user_id: Optional[int] = None,
        max_chars: int = 8000,
    ) -> str:
        """將 Discord 訊息串流格式化為易於 LLM 理解的時間軸文字日誌。"""
        if not messages:
            return "（指定時間區間內沒有任何聊天訊息）"

        transcript_lines: List[str] = []
        cur_chars = 0

        for msg in messages:
            author = getattr(msg, "author", None)
            author_name = getattr(author, "display_name", None) or getattr(author, "name", "未知成員")
            is_bot = getattr(author, "bot", False)

            # 格式化時間 (轉為臺灣時區)
            created_at = getattr(msg, "created_at", None)
            if created_at:
                local_time = created_at.astimezone(TAIPEI_TZ).strftime("%H:%M:%S")
            else:
                local_time = "未知時間"

            # 訊息文字與附件處理
            clean_content = (getattr(msg, "clean_content", None) or getattr(msg, "content", "")).strip()

            attachment_tags = []
            attachments = getattr(msg, "attachments", []) or []
            for att in attachments:
                fname = getattr(att, "filename", "檔案")
                c_type = getattr(att, "content_type", "") or ""
                if "image" in c_type or fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    attachment_tags.append(f"[圖片: {fname}]")
                else:
                    attachment_tags.append(f"[附件: {fname}]")

            full_line_parts = []
            if clean_content:
                full_line_parts.append(clean_content)
            if attachment_tags:
                full_line_parts.append(" ".join(attachment_tags))

            line_text = " ".join(full_line_parts).strip()
            if not line_text:
                continue

            bot_tag = " [機器人]" if is_bot else ""
            line_formatted = f"[{local_time}] {author_name}{bot_tag}: {line_text}"

            if cur_chars + len(line_formatted) > max_chars:
                transcript_lines.append(f"\n... (其餘 {len(messages) - len(transcript_lines)} 則訊息因上下文篇幅已省略)")
                break

            transcript_lines.append(line_formatted)
            cur_chars += len(line_formatted)

        return "\n".join(transcript_lines)

    def compute_channel_activity_stats(
        self,
        messages: List[Any],
        channel_name: str = "本頻道",
    ) -> Dict[str, Any]:
        """計算頻道活躍度統計指標與發言排行榜。"""
        if not messages:
            return {
                "channel_name": channel_name,
                "total_messages": 0,
                "total_characters": 0,
                "unique_authors_count": 0,
                "top_speakers": [],
                "attachment_count": 0,
                "time_span": "無資料",
            }

        msg_counter: Counter[str] = Counter()
        char_counter: Counter[str] = Counter()
        author_id_map: Dict[str, int] = {}
        author_bot_map: Dict[str, bool] = {}
        total_chars = 0
        attachment_count = 0
        mentions_counter: Counter[str] = Counter()

        for msg in messages:
            author = getattr(msg, "author", None)
            if not author:
                continue
            name = getattr(author, "display_name", None) or getattr(author, "name", "未知成員")
            a_id = getattr(author, "id", 0)
            is_bot = getattr(author, "bot", False)

            msg_counter[name] += 1
            author_id_map[name] = a_id
            author_bot_map[name] = is_bot

            content = getattr(msg, "content", "") or ""
            c_len = len(content)
            char_counter[name] += c_len
            total_chars += c_len

            attachment_count += len(getattr(msg, "attachments", []) or [])

            # 提及統計
            for m in getattr(msg, "mentions", []) or []:
                m_name = getattr(m, "display_name", None) or getattr(m, "name", "")
                if m_name:
                    mentions_counter[m_name] += 1

        total_msgs = len(messages)
        top_speakers = []
        for rank, (name, count) in enumerate(msg_counter.most_common(10), 1):
            chars = char_counter.get(name, 0)
            pct = (count / total_msgs * 100.0) if total_msgs > 0 else 0.0
            top_speakers.append({
                "rank": rank,
                "name": name,
                "user_id": author_id_map.get(name, 0),
                "is_bot": author_bot_map.get(name, False),
                "message_count": count,
                "character_count": chars,
                "percentage": round(pct, 1),
            })

        t_start = getattr(messages[0], "created_at", None)
        t_end = getattr(messages[-1], "created_at", None)
        time_span = "無"
        if t_start and t_end:
            s_str = t_start.astimezone(TAIPEI_TZ).strftime("%H:%M")
            e_str = t_end.astimezone(TAIPEI_TZ).strftime("%H:%M")
            time_span = f"{s_str} ~ {e_str}"

        return {
            "channel_name": channel_name,
            "total_messages": total_msgs,
            "total_characters": total_chars,
            "unique_authors_count": len(msg_counter),
            "top_speakers": top_speakers,
            "attachment_count": attachment_count,
            "most_mentioned": mentions_counter.most_common(5),
            "time_span": time_span,
        }

    def get_channel_overview_details(self, channel: Any) -> Dict[str, Any]:
        """抓取頻道全方位元數據與討論串 (Threads) 活躍清單。"""
        ch_name = getattr(channel, "name", "未知頻道")
        topic = getattr(channel, "topic", None) or "未設定主題說明"
        slowmode = getattr(channel, "slowmode_delay", 0)
        is_nsfw = getattr(channel, "is_nsfw", lambda: False)() if callable(getattr(channel, "is_nsfw", None)) else bool(getattr(channel, "is_nsfw", False))
        created_at = getattr(channel, "created_at", None)
        created_str = created_at.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S") if created_at else "未知"

        # 活躍討論串
        threads_info = []
        threads = getattr(channel, "threads", []) or []
        for th in threads[:5]:
            th_name = getattr(th, "name", "未知討論串")
            th_msgs = getattr(th, "message_count", 0)
            threads_info.append(f"• #{th_name} ({th_msgs} 則訊息)")

        guild = getattr(channel, "guild", None)
        category = getattr(channel, "category", None)
        cat_name = getattr(category, "name", "無分類")

        return {
            "channel_id": getattr(channel, "id", 0),
            "channel_name": ch_name,
            "guild_name": getattr(guild, "name", "未知伺服器"),
            "category_name": cat_name,
            "topic": topic,
            "slowmode_delay": slowmode,
            "is_nsfw": is_nsfw,
            "created_at": created_str,
            "active_threads_count": len(threads),
            "active_threads_sample": threads_info,
        }


# Master singleton instance
channel_inspector = ChannelInspectorEngine()

__all__ = [
    "TAIPEI_TZ",
    "parse_channel_time_filter",
    "ChannelInspectorEngine",
    "channel_inspector",
]
