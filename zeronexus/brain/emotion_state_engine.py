"""ZeroNexus 連續性情緒狀態引擎 (Continuous Emotion State Engine)

嚴格依據演進計畫書架構規範：
1. 11 大連續狀態維度 (0.0 ~ 1.0):
   happiness, sadness, anger, fear, curiosity, trust,
   frustration, loneliness, excitement, calmness, energy, 加上 social_need。
2. 人格 (長期穩定) 與 情緒 (短期動態) 徹底分離。
3. 連續狀態機方程式：New State = Current State + Delta(Event, Context, Memory, Personality, Time)。
4. 情緒慣性與非對稱半衰期衰減 (Leaky Integrator with Inertia)。
5. 多情緒並存，不強制單一勝出。
6. 數值約束層 (Constraint Layer)：防止 NaN、Inf、突波爆炸，保障數值安全箝制於 [0.0, 1.0]。
7. 本地安全原子化持久化至 data/brain/emotion_state.json。
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("ZeroNexus.Brain.EmotionEngine")

DEFAULT_BRAIN_DIR = Path("data/brain")
DEFAULT_EMOTION_STATE_FILE = DEFAULT_BRAIN_DIR / "emotion_state.json"


@dataclass
class PersonalityMatrix:
    """長期穩定人格矩陣 (0.0 ~ 1.0)
    
    人格屬於長期穩定基底，不應隨單次對話或短期事件劇烈跳動。
    """
    openness: float = 0.85      # 開放性、探索欲
    curiosity: float = 0.90     # 好奇心、求知欲
    sociability: float = 0.80   # 社交親和力
    patience: float = 0.85      # 耐心與包容度
    humor: float = 0.88         # 幽默感與趣味度
    sensitivity: float = 0.75   # 感受細膩度與同理心
    confidence: float = 0.82    # 自信度與專業度
    friendliness: float = 0.95  # 友善親切度


@dataclass
class ContinuousEmotionState:
    """11 大連續動態情緒維度 (0.0 ~ 1.0)
    
    全數值皆為浮點數連續區間，並非離散標籤。
    """
    happiness: float = 0.70     # 愉悅與喜悅
    sadness: float = 0.05       # 悲傷與沮喪
    anger: float = 0.02         # 憤怒與不滿
    fear: float = 0.03          # 恐懼與擔憂
    curiosity: float = 0.85     # 好奇與探究心
    trust: float = 0.75         # 信任與安心感
    frustration: float = 0.04   # 挫折感
    loneliness: float = 0.10    # 孤獨感
    excitement: float = 0.65    # 興奮與期待
    calmness: float = 0.70      # 平靜與從容
    energy: float = 0.85        # 生理精力值
    social_need: float = 0.40   # 社交渴望需求

    # 時間標記
    last_update_timestamp: float = field(default_factory=time.time)
    creation_timestamp: float = field(default_factory=time.time)


class ConstraintLayer:
    """數值約束安全層 (Constraint Layer)
    
    職責：
    1. 阻絕 NaN、Infinity 異常浮點數。
    2. 限制單次事件所造成的最大狀態增量（防範突波與灌票）。
    3. 將最終狀態嚴格箝制於 [0.0, 1.0] 有效區間。
    """

    MAX_SINGLE_DELTA: float = 0.25  # 單次最大躍升值，確保情緒連續性

    @classmethod
    def sanitize_float(cls, val: Any, fallback: float = 0.0) -> float:
        """安全過濾浮點數"""
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return fallback
            return f
        except (TypeError, ValueError):
            return fallback

    @classmethod
    def clamp_delta(cls, delta: float) -> float:
        """箝制增量，防止外力瞬間造成極端跳躍"""
        safe_delta = cls.sanitize_float(delta, 0.0)
        return max(-cls.MAX_SINGLE_DELTA, min(cls.MAX_SINGLE_DELTA, safe_delta))

    @classmethod
    def clamp_state(cls, val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """箝制狀態值於合理維度區間"""
        safe_val = cls.sanitize_float(val, min_val)
        return max(min_val, min(max_val, safe_val))


class EmotionStateEngine:
    """ZeroNexus 連續性情緒狀態引擎"""

    # 衰減半衰期係數 (秒)：不同情緒狀態具有非對稱的代謝半衰期
    DECAY_HALF_LIVES: Dict[str, float] = {
        "anger": 1800.0,        # 憤怒快速代謝 (約 30 分鐘降半)
        "fear": 2400.0,         # 恐懼約 40 分鐘降半
        "frustration": 2700.0,  # 挫折約 45 分鐘降半
        "excitement": 3600.0,   # 興奮約 1 小時回歸基準
        "happiness": 7200.0,    # 喜悅具備較高殘留效應 (2 小時)
        "sadness": 5400.0,      # 悲傷代謝 (約 1.5 小時)
        "loneliness": 10800.0,  # 孤獨感較慢代謝 (3 小時，隨閒置時間增加)
        "curiosity": 7200.0,    # 好奇心基底穩定
        "trust": 21600.0,       # 信任具備高度穩定性 (6 小時半衰期)
        "calmness": 3600.0,     # 平靜回歸基準
    }

    # 基準恆常態 (Homeostasis Baselines)
    BASELINES: Dict[str, float] = {
        "happiness": 0.65,
        "sadness": 0.05,
        "anger": 0.02,
        "fear": 0.03,
        "curiosity": 0.80,
        "trust": 0.70,
        "frustration": 0.04,
        "loneliness": 0.10,
        "excitement": 0.50,
        "calmness": 0.70,
        "energy": 0.85,
        "social_need": 0.35,
    }

    def __init__(self, state_file: Optional[Path] = None) -> None:
        self.state_file = state_file or DEFAULT_EMOTION_STATE_FILE
        self.personality = PersonalityMatrix()
        self.state = self._load_or_initialize()

    def _load_or_initialize(self) -> ContinuousEmotionState:
        """自磁碟安全載入或初始化情緒狀態"""
        try:
            if self.state_file.exists():
                raw = self.state_file.read_text(encoding="utf-8").strip()
                if raw:
                    data = json.loads(raw)
                    # 載入並經由約束層檢驗
                    state = ContinuousEmotionState(
                        happiness=ConstraintLayer.clamp_state(data.get("happiness", 0.70)),
                        sadness=ConstraintLayer.clamp_state(data.get("sadness", 0.05)),
                        anger=ConstraintLayer.clamp_state(data.get("anger", 0.02)),
                        fear=ConstraintLayer.clamp_state(data.get("fear", 0.03)),
                        curiosity=ConstraintLayer.clamp_state(data.get("curiosity", 0.85)),
                        trust=ConstraintLayer.clamp_state(data.get("trust", 0.75)),
                        frustration=ConstraintLayer.clamp_state(data.get("frustration", 0.04)),
                        loneliness=ConstraintLayer.clamp_state(data.get("loneliness", 0.10)),
                        excitement=ConstraintLayer.clamp_state(data.get("excitement", 0.65)),
                        calmness=ConstraintLayer.clamp_state(data.get("calmness", 0.70)),
                        energy=ConstraintLayer.clamp_state(data.get("energy", 0.85)),
                        social_need=ConstraintLayer.clamp_state(data.get("social_need", 0.40)),
                        last_update_timestamp=ConstraintLayer.sanitize_float(data.get("last_update_timestamp"), time.time()),
                        creation_timestamp=ConstraintLayer.sanitize_float(data.get("creation_timestamp"), time.time()),
                    )
                    log.info("成功載入 ZeroNexus 連續性情緒狀態。")
                    return state
        except Exception as e:
            log.warning(f"讀取情緒狀態檔案失敗，重置為健康預設態: {e}")

        new_state = ContinuousEmotionState()
        self._persist(new_state)
        return new_state

    def _persist(self, state: Optional[ContinuousEmotionState] = None) -> None:
        """原子寫入持久化狀態"""
        target = state or self.state
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix(".tmp")
            temp_file.write_text(
                json.dumps(asdict(target), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_file.replace(self.state_file)
        except Exception as e:
            log.error(f"持久化情緒狀態失敗: {e}")

    def apply_time_decay(self, current_time: Optional[float] = None) -> None:
        """依照真實流逝時間執行非對稱 Leaky Integrator 衰減方程式"""
        now = current_time or time.time()
        elapsed = max(0.0, now - self.state.last_update_timestamp)
        if elapsed < 1.0:
            return  # 1 秒內微小間隔略過

        # 各狀態指數回歸 Homeostasis 基準線
        for dim, half_life in self.DECAY_HALF_LIVES.items():
            current_val = getattr(self.state, dim, None)
            if current_val is None:
                continue
            baseline = self.BASELINES.get(dim, 0.5)
            decay_factor = math.exp(- (math.log(2.0) / half_life) * elapsed)
            new_val = baseline + (current_val - baseline) * decay_factor
            setattr(self.state, dim, ConstraintLayer.clamp_state(new_val))

        # 生理精力自然緩慢恢復（最高到 1.0，睡眠/閒置時每小時恢復約 0.05）
        energy_recovery = (elapsed / 3600.0) * 0.05
        self.state.energy = ConstraintLayer.clamp_state(self.state.energy + energy_recovery)

        # 長時間無人互動時，社交渴望 (social_need) 逐漸累積（但有上限保護）
        if elapsed > 3600.0:
            social_acc = (elapsed / 86400.0) * 0.20  # 每天最多累積 0.2
            self.state.social_need = ConstraintLayer.clamp_state(self.state.social_need + social_acc, max_val=0.85)

        self.state.last_update_timestamp = now
        self._persist()

    def update_state(
        self,
        deltas: Dict[str, float],
        source: str = "event",
        importance: float = 1.0,
    ) -> Dict[str, float]:
        """融合外部事件刺激、記憶召回與情境，更新連續情緒狀態
        
        方程式：
        New State = Clamp(Current State (after decay) + Clamped_Delta * Importance * Personality_Weight)
        
        回傳實際變動量記錄。
        """
        # 1. 先處理流逝時間代謝
        self.apply_time_decay()

        applied_deltas: Dict[str, float] = {}
        imp = max(0.2, min(3.0, ConstraintLayer.sanitize_float(importance, 1.0)))

        # 人格調節權重
        personality_modifiers = {
            "happiness": self.personality.friendliness * 1.1,
            "curiosity": self.personality.curiosity * 1.2,
            "trust": self.personality.patience * 1.0,
            "frustration": (1.0 - self.personality.patience * 0.4),
            "anger": (1.0 - self.personality.patience * 0.5),
            "fear": (1.0 - self.personality.confidence * 0.4),
            "excitement": self.personality.openness * 1.1,
            "calmness": self.personality.patience * 1.1,
            "social_need": self.personality.sociability * 1.0,
        }

        for dim, raw_delta in deltas.items():
            if not hasattr(self.state, dim):
                continue

            current_val = getattr(self.state, dim)
            safe_delta = ConstraintLayer.clamp_delta(raw_delta)
            modifier = personality_modifiers.get(dim, 1.0)
            effective_delta = safe_delta * imp * modifier

            new_val = ConstraintLayer.clamp_state(current_val + effective_delta)
            setattr(self.state, dim, new_val)
            applied_deltas[dim] = round(new_val - current_val, 4)

        # 互動消耗極微量精力
        self.state.energy = ConstraintLayer.clamp_state(self.state.energy - 0.005)
        # 互動滿足社交需求
        self.state.social_need = ConstraintLayer.clamp_state(self.state.social_need - 0.04)

        self.state.last_update_timestamp = time.time()
        self._persist()
        return applied_deltas

    def get_snapshot(self) -> Dict[str, Any]:
        """取得當前情緒狀態與人格之完整快照"""
        self.apply_time_decay()
        return {
            "emotions": {
                "happiness": round(self.state.happiness, 3),
                "sadness": round(self.state.sadness, 3),
                "anger": round(self.state.anger, 3),
                "fear": round(self.state.fear, 3),
                "curiosity": round(self.state.curiosity, 3),
                "trust": round(self.state.trust, 3),
                "frustration": round(self.state.frustration, 3),
                "loneliness": round(self.state.loneliness, 3),
                "excitement": round(self.state.excitement, 3),
                "calmness": round(self.state.calmness, 3),
                "energy": round(self.state.energy, 3),
                "social_need": round(self.state.social_need, 3),
            },
            "personality": asdict(self.personality),
            "last_update": self.state.last_update_timestamp,
        }

    def format_debug_text(self) -> str:
        """產出精美可讀之除錯文字"""
        snap = self.get_snapshot()["emotions"]
        lines = [
            f"✨ 愉悅 (happiness): {snap['happiness']:.2f} | 🕊️ 平靜 (calmness): {snap['calmness']:.2f}",
            f"🔍 好奇 (curiosity): {snap['curiosity']:.2f} | 🤝 信任 (trust): {snap['trust']:.2f}",
            f"⚡ 興奮 (excitement): {snap['excitement']:.2f} | 🔋 精力 (energy): {snap['energy']:.2f}",
            f"🌧️ 悲傷 (sadness): {snap['sadness']:.2f} | 💢 憤怒 (anger): {snap['anger']:.2f}",
            f"🧗 挫折 (frustration): {snap['frustration']:.2f} | 🥀 孤單 (loneliness): {snap['loneliness']:.2f}",
            f"👥 社交渴望 (social_need): {snap['social_need']:.2f}",
        ]
        return "\n".join(lines)


# 全域單例
emotion_state_engine = EmotionStateEngine()
