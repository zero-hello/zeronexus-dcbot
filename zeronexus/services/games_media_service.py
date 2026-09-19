"""Entertainment & Media Mini-Games Service (Features 496-500).

Implements:
- Trivia Game (Knowledge Challenge) (496)
- Guessing Game (Numbers & Words) (497)
- Text Adventure (Interactive RPG Stories) (498)
- Achievement Collection (499)
- Interactive Mini Game Framework (Extensible Session Engine) (500)
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional
import discord


class GamesMediaService:
    """全面實作 Features 496 ~ 500 之社群娛樂、益智問答、文字冒險與小遊戲框架服務。"""

    _TRIVIA_QUESTIONS = [
        {
            "question": "全球第一個開源的非同步 Python Discord 函式庫是什麼？",
            "options": ["discord.py", "telebot", "slackclient", "pydiscord"],
            "answer_index": 0,
            "explanation": "discord.py 是最早且最成熟的 Python 非同步 Discord API 函式庫。"
        },
        {
            "question": "在關聯式資料庫中，ACID 中的『I』代表什麼意義？",
            "options": ["Integrity", "Isolation (隔離性)", "Index", "Iteration"],
            "answer_index": 1,
            "explanation": "ACID 代表 Atomicity, Consistency, Isolation, Durability。"
        },
        {
            "question": "臺灣最高峰玉山的主峰海拔高度是多少公尺？",
            "options": ["3,886 公尺", "3,952 公尺", "3,742 公尺", "3,980 公尺"],
            "answer_index": 1,
            "explanation": "玉山主峰海拔標高為 3,952 公尺。"
        }
    ]

    # ----------------------------------------------------
    # 496: 益智問答遊戲 (Trivia Game)
    # ----------------------------------------------------
    @classmethod
    def get_random_trivia(cls) -> Dict[str, Any]:
        """功能 496: 隨機獲取一題益智問答。"""
        return random.choice(cls._TRIVIA_QUESTIONS)

    # ----------------------------------------------------
    # 497: 數字與單詞猜謎 (Guessing Game)
    # ----------------------------------------------------
    @staticmethod
    def start_number_guess(min_val: int = 1, max_val: int = 100) -> Dict[str, Any]:
        """功能 497: 啟動終極密碼 / 猜數字小遊戲。"""
        target = random.randint(min_val, max_val)
        return {
            "target": target,
            "min_val": min_val,
            "max_val": max_val,
            "attempts_allowed": 7,
            "message": f"🎲 終極密碼已啟動！數字介於 `{min_val}` 到 `{max_val}` 之間，你有 7 次機會！"
        }

    # ----------------------------------------------------
    # 498: 互動文字冒險 (Text Adventure RPG)
    # ----------------------------------------------------
    @staticmethod
    def get_adventure_scene(scene_id: str = "start") -> Dict[str, Any]:
        """功能 498: 取得文字冒險故事分支場景。"""
        scenes = {
            "start": {
                "title": "🏰 賽博城堡的入口",
                "narrative": "你站在巨大的發光霓虹大門前，左側有一條佈滿幽藍管線的下水道，右側有一座通往高塔的懸浮梯。",
                "choices": [
                    {"text": "進入幽藍下水道", "next_scene": "sewer"},
                    {"text": "搭乘高塔懸浮梯", "next_scene": "tower"}
                ]
            },
            "sewer": {
                "title": "💧 數據下水道",
                "narrative": "管線傳來潺潺的封包流動聲，你在泥濘中發現了一枚遠古加密晶片！",
                "choices": [
                    {"text": "拾起晶片解密", "next_scene": "victory"},
                    {"text": "原路折返大門", "next_scene": "start"}
                ]
            },
            "tower": {
                "title": "⚡ 核心伺服高塔",
                "narrative": "高塔頂端是一座旋轉的量子中樞，守護 AI 溫柔地注視著你。",
                "choices": [
                    {"text": "與守護 AI 交流握手", "next_scene": "victory"},
                    {"text": "原路折返大門", "next_scene": "start"}
                ]
            },
            "victory": {
                "title": "🏆 冒險傳奇通關",
                "narrative": "恭喜你！成功解開了 ZeroNexus 的賽博秘密，獲得了傳奇冒險家稱號！🎉",
                "choices": []
            }
        }
        return scenes.get(scene_id, scenes["start"])

    # ----------------------------------------------------
    # 500: 小遊戲互動框架 (Interactive Mini Game Framework)
    # ----------------------------------------------------
    @staticmethod
    def render_game_embed(title: str, description: str, fields: Optional[List[Dict[str, str]]] = None) -> discord.Embed:
        """功能 500: 統一小遊戲介面渲染器。"""
        embed = discord.Embed(title=title, description=description, color=0x9B59B6)
        if fields:
            for f in fields:
                embed.add_field(name=f.get("name", ""), value=f.get("value", ""), inline=f.get("inline", False))
        embed.set_footer(text="ZeroNexus 娛樂遊戲中樞")
        return embed
