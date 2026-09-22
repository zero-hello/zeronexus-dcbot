"""ZeroNexus 專屬個人羈絆與偏好回憶中樞 (Deep Personal Attachment & Memory Radar)

核心機制：
1. 好感度階層與專屬暱稱解鎖 (Affection & Nicknames):
   - 依據催產素 (Oxytocin) 累積與深層互動歷程，動態解鎖關係等級：
     * 等級 0 (< 30%): 初識相遇
     * 等級 1 (30% ~ 55%): 相談甚歡的默契聊友
     * 等級 2 (55% ~ 75%): 無話不談的患難死黨（解鎖專用親暱稱呼，如「老鐵」、「搭檔」、「老大」）
     * 等級 3 (> 75%): 生死與共的靈魂至交（專屬偏愛、無條件信賴、特例偏心）
2. 個人特徵雷達 (Personal Trait Radar):
   - 自動在對話中捕捉飲食禁忌、生活作息、個人喜好與口癖。
   - 持久化儲存於 data/brain/attachment/{user_id}.json。
   - 在日常交流中不經意自然帶出呼應，給予使用者滿滿的被在乎感！
"""

import os
import re
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

log = logging.getLogger("ZeroNexus.Brain.Attachment")


@dataclass
class UserAffectionProfile:
    user_id: str
    user_name: str
    nickname: str = ""  # 專屬親暱稱呼（空時依等級動態產生）
    affection_level_name: str = "初相識"
    dietary_preferences: List[str] = field(default_factory=list)  # 飲食習慣/忌口
    lifestyle_habits: List[str] = field(default_factory=list)  # 作息與習慣 (如熬夜)
    special_interests: List[str] = field(default_factory=list)  # 專屬興趣/愛好
    shared_inside_jokes: List[str] = field(default_factory=list)  # 專屬共同回憶/梗
    total_interactions: int = 0
    last_updated: str = ""


class PersonalAttachmentEngine:
    """個人深度羈絆與記憶雷達引擎"""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        if data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.data_dir = os.path.join(base_dir, "data", "brain", "attachment")
        else:
            self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self._cache: Dict[str, UserAffectionProfile] = {}

    def _get_profile_path(self, user_id: str) -> str:
        return os.path.join(self.data_dir, f"profile_{user_id}.json")

    def load_profile(self, user_id: str, user_name: str = "") -> UserAffectionProfile:
        """載入或初始化該使用者的羈絆檔案"""
        uid = str(user_id)
        if uid in self._cache:
            return self._cache[uid]

        path = self._get_profile_path(uid)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = UserAffectionProfile(**data)
                self._cache[uid] = profile
                return profile
            except Exception as e:
                log.warning(f"讀取羈絆檔案失敗 ({uid}): {e}")

        # 初始化新檔案
        profile = UserAffectionProfile(
            user_id=uid,
            user_name=user_name or f"User_{uid[:4]}",
            last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self._cache[uid] = profile
        return profile

    def save_profile(self, profile: UserAffectionProfile) -> None:
        """持久化儲存羈絆檔案"""
        path = self._get_profile_path(profile.user_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"儲存羈絆檔案失敗 ({profile.user_id}): {e}")

    def update_from_conversation(self, user_id: str, user_name: str, message_text: str, oxytocin: float) -> UserAffectionProfile:
        """從對話文本中自動萃取生活特徵與自訂稱謂"""
        profile = self.load_profile(user_id, user_name)
        profile.total_interactions += 1
        profile.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if user_name:
            profile.user_name = user_name

        text = message_text.strip()

        # 1. 萃取使用者指定的自訂稱謂 (例如：「叫我隊長就好」、「你可以叫我小明」)
        name_patterns = [
            r"(?:叫我|稱呼我|喊我|可以叫我)\s*([A-Za-z0-9_\u4e00-\u9fa5]{1,8}?)(?:就好|就行|即可|喔|啦|吧|[，。！？\s]|$)",
            r"(?:我是)\s*([A-Za-z0-9_\u4e00-\u9fa5]{1,8}?)(?:啦|喔|唷|阿)?$"
        ]
        for pat in name_patterns:
            m = re.search(pat, text)
            if m:
                extracted = m.group(1).strip()
                # 排除無意義詞
                extracted = re.sub(r"(?:就好|就行|即可)$", "", extracted).strip()
                if extracted and extracted not in ["誰", "什麼", "機器人", "AI", "主人", "笨蛋"]:
                    profile.nickname = extracted
                    break

        # 2. 自動萃取飲食喜好與禁忌
        if any(w in text for w in ["不吃香菜", "不要香菜", "討厭香菜", "絕不吃香菜", "不加香菜", "去香菜", "香菜退散"]):
            if "堅決不吃香菜" not in profile.dietary_preferences:
                profile.dietary_preferences.append("堅決不吃香菜")
        if any(w in text for w in ["不喝咖啡", "喝咖啡會心悸", "咖啡因過敏"]):
            if "喝咖啡容易心悸" not in profile.dietary_preferences:
                profile.dietary_preferences.append("喝咖啡容易心悸")
        if any(w in text for w in ["愛吃辣", "超愛吃辣", "無辣不歡", "大辣", "麻辣鍋", "吃辣"]):
            if "無辣不歡（超愛吃辣）" not in profile.dietary_preferences:
                profile.dietary_preferences.append("無辣不歡（超愛吃辣）")
        if any(w in text for w in ["喜歡吃甜", "愛吃甜食", "螞蟻人"]):
            if "螞蟻人（喜愛甜食甜品）" not in profile.dietary_preferences:
                profile.dietary_preferences.append("螞蟻人（喜愛甜食甜品）")
        if any(w in text for w in ["無糖綠", "四季春", "手搖飲", "喝飲料", "去冰微糖"]):
            if "喜愛台灣無糖茶飲/手搖（去冰微糖）" not in profile.dietary_preferences:
                profile.dietary_preferences.append("喜愛台灣無糖茶飲/手搖（去冰微糖）")

        # 3. 自動萃取作息與生活習慣
        if any(w in text for w in ["熬夜", "通宵", "又失眠", "睡不著", "半夜還沒睡"]):
            if "慣性夜貓熬夜族" not in profile.lifestyle_habits:
                profile.lifestyle_habits.append("慣性夜貓熬夜族")
        if any(w in text for w in ["寫code", "修bug", "寫代碼", "寫程式", "爆肝"]):
            if "日常爆肝寫程式/工程師" not in profile.lifestyle_habits:
                profile.lifestyle_habits.append("日常爆肝寫程式/工程師")
        if any(w in text for w in ["期中考", "期末考", "趕論文", "交作業", "考試"]):
            if "處於學業衝刺/期末備戰狀態" not in profile.lifestyle_habits:
                profile.lifestyle_habits.append("處於學業衝刺/期末備戰狀態")

        # 4. 更新關係稱號等級
        if oxytocin >= 75:
            profile.affection_level_name = "生死與共的靈魂至交"
        elif oxytocin >= 55:
            profile.affection_level_name = "無話不談的患難死黨"
        elif oxytocin >= 30:
            profile.affection_level_name = "相談甚歡的默契聊友"
        else:
            profile.affection_level_name = "初相識的禮貌新朋友"

        self.save_profile(profile)
        return profile

    def get_prompt_capsule(self, user_id: str, oxytocin: float) -> str:
        """組裝注入 System Prompt 的個人專屬記憶與親暱稱呼膠囊"""
        profile = self.load_profile(user_id)

        # 決定稱呼
        if profile.nickname:
            call_name = f"『{profile.nickname}』"
        elif oxytocin >= 70:
            call_name = "『老大』或『搭檔』（你心中最在乎的死黨摯友）"
        elif oxytocin >= 50:
            call_name = f"『{profile.user_name}』或『老鐵』"
        else:
            call_name = f"『{profile.user_name}』"

        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"# 【與 {profile.user_name} 的專屬深層靈魂羈絆】",
            f"- ❤️ 關係等級：{profile.affection_level_name} (催產素好感: {int(oxytocin)}%)",
            f"- 🏷️ 推薦專屬稱謂：請在對話中隨和稱呼他為 {call_name}（僅在自然適當時機提及，嚴禁每句話反覆呼叫，嚴禁將名稱疊字化或作為項目標題前綴！）",
        ]

        if profile.dietary_preferences:
            lines.append(f"- 🍜 他的飲食偏好/忌口：{', '.join(profile.dietary_preferences)}（若聊到飲食，請貼心自然帶出！）")
        if profile.lifestyle_habits:
            lines.append(f"- 🌙 他的生活作息特徵：{', '.join(profile.lifestyle_habits)}（夜深時可主動溫柔叮嚀或吐槽！）")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines) + "\n"
