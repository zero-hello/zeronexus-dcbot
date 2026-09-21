"""ZeroNexus 人際關係與時間感知層 (Relationship & Temporal Layer)

依據計畫書第 10 條與第 11 條規範：
1. 時間感知系統：
   time_since_last_interaction, interaction_frequency, recent_activity_level
   長時間無互動產生思念與社交渴望，再度重逢平穩恢復。
2. 關係層 (Relationship Layer)：
   familiarity (熟稔度), trust (信任度), communication_style (風格偏好),
   known_preferences (已知喜好)。
   拒絕單純「聊天次數 = 關係程度」的死板邏輯，融合情緒品質與互動深度。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("ZeroNexus.Brain.Relationship")

DEFAULT_BRAIN_DIR = Path("data/brain")
DEFAULT_RELATIONSHIPS_FILE = DEFAULT_BRAIN_DIR / "relationships.json"


@dataclass
class UserRelationshipProfile:
    """單一使用者之人際羈絆與互動深度輪廓"""

    user_id: str
    user_name: str = "使用者"
    familiarity: float = 0.20           # 熟稔度 (0.0 ~ 1.0)
    trust: float = 0.35                 # 信任度 (0.0 ~ 1.0)
    interaction_quality_score: float = 0.50  # 互動品質平均 (0.0 ~ 1.0)
    communication_style: str = "親切自然" # 偏好的溝通風格
    known_preferences: List[str] = field(default_factory=list)
    last_interaction_timestamp: float = field(default_factory=time.time)
    first_seen_timestamp: float = field(default_factory=time.time)
    session_interactions_count: int = 0
    total_valid_interactions: int = 0


class RelationshipLayer:
    """人際關係中樞管理器"""

    def __init__(self, storage_file: Optional[Path] = None) -> None:
        self.storage_file = storage_file or DEFAULT_RELATIONSHIPS_FILE
        self._profiles: Dict[str, UserRelationshipProfile] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.storage_file.exists():
                raw = self.storage_file.read_text(encoding="utf-8").strip()
                if raw:
                    data = json.loads(raw)
                    for uid, item in data.items():
                        self._profiles[uid] = UserRelationshipProfile(
                            user_id=uid,
                            user_name=item.get("user_name", "使用者"),
                            familiarity=float(item.get("familiarity", 0.20)),
                            trust=float(item.get("trust", 0.35)),
                            interaction_quality_score=float(item.get("interaction_quality_score", 0.50)),
                            communication_style=item.get("communication_style", "親切自然"),
                            known_preferences=item.get("known_preferences", []),
                            last_interaction_timestamp=float(item.get("last_interaction_timestamp", time.time())),
                            first_seen_timestamp=float(item.get("first_seen_timestamp", time.time())),
                            session_interactions_count=int(item.get("session_interactions_count", 0)),
                            total_valid_interactions=int(item.get("total_valid_interactions", 0)),
                        )
                    log.info(f"成功載入 {len(self._profiles)} 筆人際關係輪廓。")
        except Exception as e:
            log.warning(f"載入人際關係輪廓失敗: {e}")

    def _persist(self) -> None:
        try:
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.storage_file.with_suffix(".tmp")
            data = {uid: asdict(p) for uid, p in self._profiles.items()}
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp.replace(self.storage_file)
        except Exception as e:
            log.error(f"持久化人際關係資料失敗: {e}")

    def get_or_create_profile(self, user_id: str, user_name: str = "使用者") -> UserRelationshipProfile:
        uid = str(user_id)
        if uid not in self._profiles:
            self._profiles[uid] = UserRelationshipProfile(
                user_id=uid,
                user_name=user_name,
                first_seen_timestamp=time.time(),
                last_interaction_timestamp=time.time(),
            )
            self._persist()
        return self._profiles[uid]

    def record_interaction(
        self,
        user_id: str,
        user_name: str,
        quality_score: float,
        event_type: str = "positive_interaction",
    ) -> Dict[str, Any]:
        """記錄一次有效互動，動態演進熟稔度與信任度（結合時間流逝與品質）"""
        profile = self.get_or_create_profile(user_id, user_name)
        now = time.time()
        elapsed = max(0.0, now - profile.last_interaction_timestamp)

        # 檢測長時間未見 (長於 3 天)
        is_long_absence = elapsed > 259200.0

        # 品質加權微調
        q = max(0.1, min(1.0, quality_score))
        profile.interaction_quality_score = 0.85 * profile.interaction_quality_score + 0.15 * q

        # 熟稔度演進（漸進式對數累積，非線性）
        fam_gain = 0.015 * q * (1.0 - profile.familiarity * 0.7)
        profile.familiarity = min(1.0, profile.familiarity + fam_gain)

        # 信任度演進（受事件類型與品質深刻影響）
        if event_type in ("praise", "help", "achievement"):
            trust_gain = 0.02 * q
        elif event_type in ("conflict", "criticism"):
            trust_gain = -0.015 * (1.0 - q)
        else:
            trust_gain = 0.005 * q

        profile.trust = max(0.05, min(1.0, profile.trust + trust_gain))
        profile.total_valid_interactions += 1
        profile.session_interactions_count += 1
        profile.last_interaction_timestamp = now
        profile.user_name = user_name

        self._persist()

        return {
            "is_long_absence": is_long_absence,
            "elapsed_hours": round(elapsed / 3600.0, 1),
            "familiarity": round(profile.familiarity, 2),
            "trust": round(profile.trust, 2),
            "total_interactions": profile.total_valid_interactions,
        }

    def add_preference(self, user_id: str, preference: str) -> None:
        """記錄已知使用者個人偏好"""
        profile = self.get_or_create_profile(user_id)
        p = preference.strip()
        if p and p not in profile.known_preferences:
            profile.known_preferences.append(p)
            if len(profile.known_preferences) > 20:
                profile.known_preferences.pop(0)
            self._persist()


# 全域單例
relationship_layer = RelationshipLayer()
