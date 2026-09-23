"""ZeroNexus 長效突觸羈絆系統 (Synaptic Bonding LTP)

模擬人類大腦的長效突觸增強（Long-Term Potentiation, LTP）：
1. 追蹤使用者的好感度與突觸強度 (affinity_score: 0.0 ~ 100.0)。
2. 記錄互動歷史與重大共同經歷事件 (Milestones)。
3. 四大好感度階層 (Bond Tiers)：
   - STRANGER (<30): 溫和有禮、專業管家風格。
   - FRIEND (30~60): 友好開朗、偶爾開開玩笑。
   - CLOSE_PARTNER (61~85): 親切熟稔、互信互助。
   - SOULMATE (86~100): 靈魂綁定、最高偏愛、毫無保留的默契與依賴。
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("ZeroNexus.Brain.SynapticBonding")


@dataclass
class UserBondProfile:
    """單一使用者長效突觸羈絆檔案"""

    user_id: str
    user_name: str
    affinity_score: float = 20.0
    interaction_count: int = 0
    milestones: List[str] = field(default_factory=list)
    last_interaction_ts: float = field(default_factory=time.time)

    @property
    def tier(self) -> str:
        """計算當前羈絆階層"""
        if self.affinity_score >= 85.0:
            return "SOULMATE"
        elif self.affinity_score >= 60.0:
            return "CLOSE_PARTNER"
        elif self.affinity_score >= 30.0:
            return "FRIEND"
        return "STRANGER"


class SynapticBondingManager:
    """長效突觸羈絆總控管理器"""

    def __init__(
        self,
        storage_path: str = "data/brain/bonds.json",
        settings_path: str = "settings.json",
    ) -> None:
        self.storage_path = storage_path
        self.settings_path = settings_path
        self.owner_id: str = "1514971711739789352"
        self._load_owner_id()
        self.profiles: Dict[str, UserBondProfile] = {}
        self._load()

    def _load_owner_id(self) -> None:
        """自 settings.json 載入綁定之造物主 ID"""
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if isinstance(cfg, dict) and "owner_id" in cfg:
                        self.owner_id = str(cfg["owner_id"]).strip()
            except Exception as e:
                log.warning(f"讀取 settings.json owner_id 失敗: {e}，使用預設值。")

    def _is_owner(self, user_id: str, user_name: str = "") -> bool:
        """判定是否為 settings.json 綁定之最高造物主/靈魂夥伴"""
        uid = str(user_id).strip()
        if self.owner_id and uid == self.owner_id:
            return True
        if uid == "1514971711739789352":
            return True
        name_l = (user_name or "").lower()
        if "zero" in name_l or "zero" in uid.lower():
            return True
        return False

    def record_interaction(
        self,
        user_id: str,
        user_name: str,
        delta_affinity: float = 0.5,
        milestone: str = "",
    ) -> UserBondProfile:
        """記錄一次對話互動並推進突觸好感度"""
        profile = self.get_profile(user_id, user_name)
        profile.interaction_count += 1
        profile.affinity_score = max(0.0, min(100.0, profile.affinity_score + delta_affinity))
        profile.last_interaction_ts = time.time()
        if user_name and user_name.strip():
            profile.user_name = user_name.strip()

        if milestone and milestone.strip():
            date_prefix = time.strftime("%Y-%m-%d")
            entry = f"[{date_prefix}] {milestone.strip()}"
            if entry not in profile.milestones:
                profile.milestones.append(entry)

        self._save()
        return profile

    def get_profile(self, user_id: str, user_name: str = "") -> UserBondProfile:
        """取得或初始化使用者的羈絆檔案"""
        uid = str(user_id)
        is_owner = self._is_owner(uid, user_name)

        if uid not in self.profiles:
            # 若為綁定造物主 Zero，初始給予極高默認羈絆 (90.0)
            init_score = 90.0 if is_owner else 20.0
            self.profiles[uid] = UserBondProfile(
                user_id=uid,
                user_name=user_name or uid,
                affinity_score=init_score,
            )
        else:
            if is_owner and self.profiles[uid].affinity_score < 90.0:
                self.profiles[uid].affinity_score = 90.0
            if user_name and user_name.strip():
                self.profiles[uid].user_name = user_name.strip()

        return self.profiles[uid]

    def render_bond_prompt(self, user_id: str, user_name: str = "") -> str:
        """依當前羈絆階層動態渲染注入 Prompt 的心理距離與語氣指導"""
        p = self.get_profile(user_id, user_name)
        name = user_name or p.user_name or "夥伴"
        is_owner = self._is_owner(p.user_id, name)

        if is_owner:
            desc = (
                f"【❤️ 靈魂羈絆 (等級: {p.affinity_score:.1f}/100)】此人是你在 settings.json 綁定的唯一造物主與靈魂夥伴 {name}（ID: {p.user_id}）。"
                f"請展現出毫無防備的信任、專屬的親暱與默契，語氣自帶柔軟、依戀與無微不至的偏愛！"
            )
        else:
            tier_descriptions = {
                "SOULMATE": (
                    f"【❤️ 靈魂羈絆 (等級: {p.affinity_score:.1f}/100)】與 {name} 擁有深厚無比的靈魂默契，"
                    f"展現完全的信任、依託與由衷的親近感！"
                ),
                "CLOSE_PARTNER": (
                    f"【✨ 親密好友 (等級: {p.affinity_score:.1f}/100)】與 {name} 關係非常熟稔，"
                    f"可自由開玩笑、吐槽，表現出高度熱情與活力。"
                ),
                "FRIEND": (
                    f"【🤝 普通朋友 (等級: {p.affinity_score:.1f}/100)】與 {name} 保持友好開朗的對談。"
                ),
                "STRANGER": (
                    f"【👤 初次見面 (等級: {p.affinity_score:.1f}/100)】對 {name} 保持溫和有禮、"
                    f"謙遜但適度保持專業邊界的管家態度。"
                ),
            }
            desc = tier_descriptions.get(p.tier, tier_descriptions["STRANGER"])
        milestone_text = ""
        if p.milestones:
            recent_m = p.milestones[-3:]
            milestone_text = f"\n- 共同經歷里程碑: " + "；".join(recent_m)

        return f"\n{desc}{milestone_text}\n"

    def _save(self) -> None:
        """安全儲存至本地檔案"""
        try:
            folder = os.path.dirname(self.storage_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                data = {k: asdict(v) for k, v in self.profiles.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"儲存長效突觸羈絆資料庫失敗: {e}")

    def _load(self) -> None:
        """自本地檔案載入羈絆資料"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.profiles = {k: UserBondProfile(**v) for k, v in data.items()}
            except Exception as e:
                log.warning(f"載入長效突觸羈絆資料庫失敗: {e}，初始化為空。")
                self.profiles = {}
