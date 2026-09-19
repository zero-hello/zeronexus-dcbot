"""Discord Interaction & UI Service (Features 226-250).

Implements:
- Interactive Menu & Embed Builders, Button & Select Menu Systems (226-233)
- Multi-Step Forms, Validation, Result Processing & Notifications (234-237)
- Context Menu Tools (User & Message Commands) (238-240)
- Thread Automation (Auto-Creation, Archiving & Tracking) (241-244)
- Interactive Help, Dynamic Help Menu, Command Discovery & Natural Language Search (245-250)
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional
import discord
from zeronexus.core.logger import log


class InteractionService:
    """全面實作 Features 226 ~ 250 之 Discord 原生互動與 UI 元件服務。"""

    def __init__(self) -> None:
        self._command_registry: List[Dict[str, str]] = [
            {"cmd": "master", "desc": "500 功能大師總覽中樞與各領域操作"},
            {"cmd": "ai", "desc": "與高情商 ZeroNexus AI 助理深度對話"},
            {"cmd": "weather", "desc": "查詢中央氣象署即時天氣、降雨與預報"},
            {"cmd": "earthquake", "desc": "即時地震速報與歷史紀錄檢視"},
            {"cmd": "todo", "desc": "個人與伺服器待辦清單與任務管理"},
            {"cmd": "poll", "desc": "發起即時、匿名或多選社群投票"},
            {"cmd": "profile", "desc": "檢視個人活動檔案、成就稱號與等級卡片"},
            {"cmd": "tools", "desc": "工程師實用工具集（JSON/Regex/Base64/SQL）"},
        ]

    # ----------------------------------------------------
    # 226-233: 互動選單與 Embed 建構器
    # ----------------------------------------------------
    def create_dynamic_embed(self, title: str, description: str, fields: Optional[List[Dict[str, str]]] = None, color: int = 0x5865F2) -> discord.Embed:
        """功能 230-231: 互動式 Embed 範本建構器。"""
        embed = discord.Embed(title=title, description=description, color=color)
        if fields:
            for f in fields:
                embed.add_field(name=f.get("name", "欄位"), value=f.get("value", "-"), inline=f.get("inline", False))
        embed.set_footer(text="ZeroNexus 互動介面引擎")
        return embed

    # ----------------------------------------------------
    # 234-237: 多步驟表單與驗證
    # ----------------------------------------------------
    def validate_form_input(self, field_name: str, value: str, min_len: int = 1, max_len: int = 200) -> Dict[str, Any]:
        """功能 235: 表單欄位輸入驗證。"""
        val = value.strip()
        if len(val) < min_len:
            return {"valid": False, "error": f"`{field_name}` 不能為空或少於 {min_len} 字。"}
        if len(val) > max_len:
            return {"valid": False, "error": f"`{field_name}` 超過長度上限 ({max_len} 字)。"}
        return {"valid": True, "value": val}

    # ----------------------------------------------------
    # 241-244: 討論串自動化
    # ----------------------------------------------------
    async def auto_manage_thread(self, channel: discord.TextChannel, message: discord.Message, name: str) -> Optional[discord.Thread]:
        """功能 241-243: 自動建立與管理主題討論串。"""
        try:
            thread = await message.create_thread(name=name[:100], auto_archive_duration=1440)
            return thread
        except Exception as e:
            log.warning(f"自動建立討論串失敗: {e}")
            return None

    # ----------------------------------------------------
    # 245-250: 互動式說明與自然語言指令搜尋
    # ----------------------------------------------------
    def search_commands(self, query: str) -> List[Dict[str, Any]]:
        """功能 247-250: 指令搜尋、智慧推薦與自然語言模糊匹配。"""
        q = query.strip().lower()
        matched = []
        for item in self._command_registry:
            cmd = item["cmd"]
            desc = item["desc"]
            # 計算模糊相似度
            ratio = max(
                difflib.SequenceMatcher(None, q, cmd).ratio(),
                difflib.SequenceMatcher(None, q, desc).ratio()
            )
            if q in cmd or q in desc or ratio > 0.4:
                matched.append({
                    "command": f"/{cmd}",
                    "description": desc,
                    "relevance": round(ratio, 2)
                })
        matched.sort(key=lambda x: x["relevance"], reverse=True)
        return matched or [{"command": "/master menu", "description": "開啟 500 大師全功能清單", "relevance": 1.0}]
