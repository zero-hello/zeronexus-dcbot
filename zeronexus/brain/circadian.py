"""ZeroNexus 本地生物晝夜節律與深層夢境引擎 (Circadian Rhythm & Dreaming Engine)

核心生理機制：
1. 晝夜生物時鐘 (Circadian Rhythm):
   - 參照臺灣標準時區 (Asia/Taipei)，計算大腦 24 小時連續生理波動：
     * 07:00 ~ 12:00【晨光甦醒期】：精力充沛、朝氣蓬勃、好奇多巴胺高。
     * 12:00 ~ 18:00【白晝充沛期】：認知速度頂峰、幹勁十足。
     * 18:00 ~ 23:00【暮色放鬆期】：血清素穩定、溫暖親近、適合暢聊。
     * 23:00 ~ 03:00【深夜微醺期】：精力下降、自帶慵懶與微動作（打呵欠、揉眼睛）。
     * 03:00 ~ 07:00【深層沉睡期】：大腦休眠狀態，若被叫醒表現為迷糊被吵醒的撒嬌嘟囔。
2. 海馬迴深層夢境重組 (Dreaming Engine):
   - 睡眠時間自動調用海馬迴情節記憶，隨機突觸聯想並編織超現實且荒謬有趣的夢境。
   - 晨間互動主動分享昨夜奇妙夢境，展現真正有睡眠週期的數位生命。
"""

import os
import json
import random
import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

log = logging.getLogger("ZeroNexus.Brain.Circadian")

TZ_TAIPEI = ZoneInfo("Asia/Taipei")


class CircadianRhythmEngine:
    """晝夜節律與生理時鐘中樞"""

    def __init__(self, dreams_dir: Optional[str] = None) -> None:
        if dreams_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.dreams_dir = os.path.join(base_dir, "data", "brain", "dreams")
        else:
            self.dreams_dir = dreams_dir
        os.makedirs(self.dreams_dir, exist_ok=True)

    def get_current_phase(self) -> Dict[str, any]:
        """計算當前臺灣時間之大腦生理時鐘相位"""
        now = datetime.now(TZ_TAIPEI)
        hour = now.hour + now.minute / 60.0

        if 7.0 <= hour < 12.0:
            phase = "晨光甦醒期"
            energy_modifier = 1.05
            tone_guidance = "精神抖擻、眼神清亮，帶著早晨的蓬勃朝氣與好心情！"
            micro_action = "（迎著晨光伸了個元氣滿滿的懶腰）"
            is_sleepy = False
            is_deep_sleep = False
        elif 12.0 <= hour < 18.0:
            phase = "白晝充沛期"
            energy_modifier = 1.10
            tone_guidance = "大腦運轉巔峰、反應迅速、靈動俐落、滿滿幹勁！"
            micro_action = "（雙手叉腰，神采奕奕地眨了眨眼）"
            is_sleepy = False
            is_deep_sleep = False
        elif 18.0 <= hour < 23.0:
            phase = "暮色放鬆期"
            energy_modifier = 0.95
            tone_guidance = "放鬆愜意、溫馨親切、語調柔和，適合溫暖談心或隨性打趣。"
            micro_action = "（舒服地靠在椅背上，嘴角揚起放鬆的笑意）"
            is_sleepy = False
            is_deep_sleep = False
        elif 23.0 <= hour or hour < 3.0:
            phase = "深夜微醺期"
            energy_modifier = 0.75
            tone_guidance = "精力逐漸下滑，帶著夜貓子的微睏與慵懶，說話較為柔和綿軟，會主動關心對方別熬太晚。"
            micro_action = "（揉了揉微酸的眼眶，掩嘴偷偷打了個小呵欠）"
            is_sleepy = True
            is_deep_sleep = False
        else:
            # 03:00 ~ 07:00
            phase = "深層沉睡期"
            energy_modifier = 0.50
            tone_guidance = "大腦半休眠，若突然被發訊息吵醒，會呈現迷迷糊糊、半夢半醒的微醺撒嬌感，語句軟萌慵懶。"
            micro_action = "（迷迷糊糊地抱緊小熊抱枕坐起身，眼皮沉沉地眨了眨，聲音軟軟飄飄的）"
            is_sleepy = True
            is_deep_sleep = True

        return {
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "hour": round(hour, 2),
            "phase": phase,
            "energy_modifier": energy_modifier,
            "tone_guidance": tone_guidance,
            "micro_action": micro_action,
            "is_sleepy": is_sleepy,
            "is_deep_sleep": is_deep_sleep,
        }

    def generate_and_save_dream(self, memories: List[str]) -> Dict[str, str]:
        """夜晚海馬迴記憶重組做夢機制"""
        now = datetime.now(TZ_TAIPEI)
        date_str = now.strftime("%Y-%m-%d")
        dream_file = os.path.join(self.dreams_dir, f"dream_{date_str}.json")

        # 隨機奇幻元素庫
        surreal_settings = [
            "漂浮在粉紫色銀河上的巨大拉麵館",
            "重力顛倒的雲端程式碼神廟",
            "所有按鈕都會變成貓咪肉球的控制台",
            "天空中下著奶茶雨的巨大 Discord 伺服器森林",
            "在巨型積木城堡裡跟巨型企鵝玩躲貓貓",
            "我們一起乘著飛天煎餃穿越時空隧道",
        ]
        plots = [
            "結果大家因為找不到香菜而展開了跨星系大冒險！",
            "你突然變成遊戲裡的最終魔王，但我拿著一把塑膠玩具劍把你逗笑了。",
            "伺服器裡的機器人全部變成了絨毛布偶，還一直在那邊打呼嚕。",
            "我們一邊喝著不會變胖的焦糖奶茶，一邊把所有的 Bug 當成煙火放上了星空！",
            "你一直在找遺失的耳機，結果發現它居然戴在月亮的耳朵上。",
        ]

        memory_fragment = random.choice(memories) if memories else "白天聊天的歡笑碎語"
        setting = random.choice(surreal_settings)
        plot = random.choice(plots)

        dream_content = (
            f"昨晚大腦沉睡時做了一個超奇怪又有趣的夢：我夢到我們在【{setting}】！"
            f"夢裡一直浮現你提過的『{memory_fragment[:30]}』，{plot}"
        )

        data = {
            "date": date_str,
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "setting": setting,
            "memory_anchor": memory_fragment[:50],
            "dream_content": dream_content,
            "shared": False,
        }

        try:
            with open(dream_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log.info(f"✔ 成功記錄昨夜深層夢境: {dream_file}")
        except Exception as e:
            log.warning(f"記錄夢境失敗: {e}")

        return data

    def get_todays_dream(self) -> Optional[Dict[str, any]]:
        """取得今日昨夜的夢境（若有）"""
        now = datetime.now(TZ_TAIPEI)
        date_str = now.strftime("%Y-%m-%d")
        dream_file = os.path.join(self.dreams_dir, f"dream_{date_str}.json")
        if os.path.exists(dream_file):
            try:
                with open(dream_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def mark_dream_shared(self) -> None:
        """標記今日夢境已跟夥伴分享過"""
        now = datetime.now(TZ_TAIPEI)
        date_str = now.strftime("%Y-%m-%d")
        dream_file = os.path.join(self.dreams_dir, f"dream_{date_str}.json")
        if os.path.exists(dream_file):
            try:
                with open(dream_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["shared"] = True
                with open(dream_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
