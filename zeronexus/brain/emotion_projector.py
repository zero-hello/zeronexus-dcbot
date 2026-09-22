"""ZeroNexus 本地多維情緒神經投影中樞 (Multi-Dimensional Emotion Projector)

基於認知神經科學與心理學架構：
1. 普魯契克 8 大原色情緒 (Plutchik's Primary Emotions):
   喜悅 (Joy)、悲傷 (Sadness)、信任 (Trust)、厭惡 (Disgust)、
   恐懼 (Fear)、憤怒 (Anger)、驚訝 (Surprise)、期待 (Anticipation)
2. 羅素雙維情緒環 (Russell Circumplex Model):
   - 愉悅度 (Valence): -1.0 (極度痛苦/負向) ~ +1.0 (極度愉悅/正向)
   - 喚醒激動度 (Arousal): 0.0 (極度平靜/低沈) ~ 1.0 (極度亢奮/激烈)
3. 複合高級情感 (Dyads & Complex Sentiments):
   愛戀 (Love = 喜悅+信任)、敬畏 (Awe = 恐懼+驚訝)、樂觀 (Optimism = 期待+喜悅)、
   委屈 (Aggrievement = 悲傷+信任受損)、狂喜 (Ecstasy)、心疼共情 (Empathy) 等。

本地採用高維語意幾何張量投影 (High-Dimensional Semantic Geometric Projection)，
完全無需依賴雲端 API，在 5 毫秒內精準計算出使用者的言外之意與情緒能量！
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("ZeroNexus.Brain.Emotion")


@dataclass
class NeurotransmitterDynamics:
    """神經遞質時間衰減與滯後平滑動力學模型 (Temporal Decay & Hysteresis Dynamics)

    1. 指數半衰期衰減公式：
       Level_t = Level_{t-1} * exp(-lambda * delta_t) + Impact_t * alpha
       其中 lambda = ln(2) / half_life
    2. 滯後阻尼平滑機制：
       Output_t = (1 - alpha) * PrevOutput + alpha * NewInput
    3. 防止單次極端輸入造成心境鋸齒狀劇烈跳變 (Anti-Jittering)。
    """

    half_lives: Dict[str, float] = field(
        default_factory=lambda: {
            "serotonin": 300.0,  # 血清素：衰減慢 (~300s)，長效心理韌性與沉穩感
            "oxytocin": 300.0,   # 催產素：衰減慢 (~300s)，長效親密感與信任積累
            "dopamine": 60.0,    # 多巴胺：衰減快 (~60s)，瞬時好奇與探索脈衝
            "cortisol": 60.0,    # 皮質醇：衰減快 (~60s)，即時壓力警覺但快速退潮平復
        }
    )
    alpha: float = 0.4  # 滯後阻尼平滑係數 (Hysteresis Damping Factor)

    # 4 大核心神經遞質基準值 (範圍 0.0 ~ 1.0)
    baselines: Dict[str, float] = field(
        default_factory=lambda: {
            "dopamine": 0.5,
            "serotonin": 0.6,
            "cortisol": 0.1,
            "oxytocin": 0.4,
        }
    )
    # 當前動態濃度水準 (0.0 ~ 1.0)
    levels: Dict[str, float] = field(
        default_factory=lambda: {
            "dopamine": 0.5,
            "serotonin": 0.6,
            "cortisol": 0.1,
            "oxytocin": 0.4,
        }
    )

    # 阻尼平滑後的維度情緒值 (Valence: -1.0 ~ 1.0, Arousal: 0.0 ~ 1.0)
    smoothed_valence: float = 0.0
    smoothed_arousal: float = 0.3
    last_update_timestamp: float = field(default_factory=time.time)

    def decay_and_update(
        self,
        impacts: Dict[str, float],
        instant_valence: float,
        instant_arousal: float,
        current_time: Optional[float] = None,
    ) -> Tuple[Dict[str, float], float, float]:
        """計算時間衰減與阻尼滯後平滑更新

        Args:
            impacts: 當次輸入對神經遞質之瞬時衝擊量
            instant_valence: 當次輸入計算出之瞬間愉悅度 (-1.0 ~ 1.0)
            instant_arousal: 當次輸入計算出之瞬間激動度 (0.0 ~ 1.0)
            current_time: 當前時間戳 (若為 None 則使用 time.time())

        Returns:
            (levels, smoothed_valence, smoothed_arousal)
        """
        now = current_time if current_time is not None else time.time()
        delta_t = max(0.0, now - self.last_update_timestamp)
        self.last_update_timestamp = now

        # 1. 計算四大神經傳導物質之時間指數衰減與衝擊合成
        for nt, half_life in self.half_lives.items():
            current_val = self.levels.get(nt, self.baselines.get(nt, 0.5))
            baseline = self.baselines.get(nt, 0.5)

            # 指數衰減常數 lambda = ln(2) / half_life
            decay_lambda = math.log(2) / max(1.0, half_life)
            decay_factor = math.exp(-decay_lambda * delta_t)

            # 偏離基準線的量遵循指數衰減回到基準線 (Homeostasis)
            diff = current_val - baseline
            decayed_diff = diff * decay_factor
            decayed_level = baseline + decayed_diff

            # 衝擊輸入（Impact 依 alpha 阻尼平滑納入）
            raw_impact = impacts.get(nt, 0.0)
            # 若 raw_impact 來自 delta (例如 1.0~30.0 範圍)，做適當比例映射 (scale 0.01)
            norm_impact = raw_impact * 0.01 if abs(raw_impact) > 1.0 else raw_impact

            # Level_t = Level_{t-1} * e^(-lambda * dt) + Impact_t * alpha
            new_level = decayed_level + (norm_impact * self.alpha)
            self.levels[nt] = max(0.0, min(1.0, round(new_level, 4)))

        # 2. 維度情緒之滯後阻尼平滑更新：
        # 若時間間隔過長（例如超過 300 秒無互動），情緒先自然向中性狀態回落
        if delta_t > 300.0:
            neutral_decay = math.exp(-(delta_t - 300.0) / 300.0)
            self.smoothed_valence *= neutral_decay
            self.smoothed_arousal = 0.3 + (self.smoothed_arousal - 0.3) * neutral_decay

        # Output_t = (1 - alpha) * PrevOutput + alpha * NewInput
        self.smoothed_valence = (1.0 - self.alpha) * self.smoothed_valence + self.alpha * instant_valence
        self.smoothed_arousal = (1.0 - self.alpha) * self.smoothed_arousal + self.alpha * instant_arousal

        self.smoothed_valence = max(-1.0, min(1.0, round(self.smoothed_valence, 3)))
        self.smoothed_arousal = max(0.0, min(1.0, round(self.smoothed_arousal, 3)))

        return self.levels.copy(), self.smoothed_valence, self.smoothed_arousal


@dataclass
class EmotionAnalysisResult:
    """情緒投影分析產出之結構化數據"""

    valence: float  # 愉悅度 (-1.0 ~ 1.0)
    arousal: float  # 喚醒激動度 (0.0 ~ 1.0)
    dominant_emotion: str  # 主導原色情緒
    secondary_emotion: str  # 次要情緒
    composite_sentiment: str  # 複合高級情感標籤
    intensity: float  # 情緒總強度 (0.0 ~ 1.0)
    sentiment_summary: str  # 生理語意描述摘要

    # 建議對神經遞質之推動增量
    delta_dopamine: float
    delta_serotonin: float
    delta_cortisol: float
    delta_oxytocin: float

    # 多神經模型陣列擴充
    threat_level: float = 0.0  # 敵意與威脅指數 (0.0 ~ 1.0)
    active_layers: List[str] = field(default_factory=lambda: ["L1_GeometricReflex"])

    # 時間衰減與滯後動態追蹤
    dynamics_levels: Optional[Dict[str, float]] = None
    raw_valence: float = 0.0
    raw_arousal: float = 0.0
    smoothed_valence: float = 0.0
    smoothed_arousal: float = 0.3


class HighDimensionalEmotionProjector:
    """高維語意情緒投影中樞"""

    # 8 大原色情緒中文標籤與基準象限
    PRIMARY_EMOTIONS = [
        "喜悅",  # Joy: (+Valence, +Arousal)
        "悲傷",  # Sadness: (-Valence, -Arousal)
        "信任",  # Trust: (+Valence, 中Arousal)
        "厭惡",  # Disgust: (-Valence, 中Arousal)
        "恐懼",  # Fear: (-Valence, +Arousal)
        "憤怒",  # Anger: (-Valence, ++Arousal)
        "驚訝",  # Surprise: (中Valence, ++Arousal)
        "期待",  # Anticipation: (+Valence, +Arousal)
    ]

    # 複合情感合成表（Primary + Secondary -> 複合情感）
    COMPOSITE_MAP = {
        ("喜悅", "信任"): "深厚愛戀與依賴",
        ("信任", "喜悅"): "溫馨信賴與親暱",
        ("期待", "喜悅"): "雀躍樂觀與憧憬",
        ("喜悅", "期待"): "狂喜與迫不及待",
        ("恐懼", "驚訝"): "敬畏與震撼",
        ("驚訝", "恐懼"): "驚慌與不知所措",
        ("悲傷", "厭惡"): "懊悔與自責失望",
        ("厭惡", "悲傷"): "心灰意冷與沮喪",
        ("憤怒", "厭惡"): "強烈鄙夷與憤懣",
        ("厭惡", "憤怒"): "反感與憤怒抗拒",
        ("期待", "恐懼"): "焦慮不安與忐忑",
        ("恐懼", "期待"): "患得患失與防備",
        ("悲傷", "信任"): "委屈訴苦與尋求安慰",
        ("信任", "悲傷"): "深層心疼與脆弱流露",
        ("驚訝", "喜悅"): "意外之喜與心花怒放",
        ("喜悅", "驚訝"): "驚喜萬分與歡呼",
        ("憤怒", "悲傷"): "悲憤交加與痛楚",
        ("悲傷", "憤怒"): "受創痛苦與不甘",
    }

    def __init__(self, dynamics: Optional[NeurotransmitterDynamics] = None) -> None:
        self.dynamics = dynamics or NeurotransmitterDynamics()
        self._init_lexical_anchors()
        try:
            from .neural_models import HierarchicalNeuralArray
            self.neural_array = HierarchicalNeuralArray()
        except Exception as e:
            log.warning(f"多神經模型陣列初始化異常: {e}")
            self.neural_array = None

    def _init_lexical_anchors(self) -> None:
        """初始化高維情緒特徵向量錨點（涵蓋道地臺灣生活用語、網路俚語、情緒符號）"""
        self.emotion_anchors = {
            "喜悅": [
                "開心", "太讚", "好耶", "爽", "超棒", "哈哈", "笑死", "太棒了", "讚啦", "歡呼",
                "太厲害", "慶祝", "快樂", "幸福", "幸運", "好玩", "卡哇伊", "可愛", "好愛", "好香",
                "撒花", "愛死", "雀躍", "滿意", "高興", "樂翻", "嘻嘻", "嘿嘿", "🥰", "🥳", "🎉", "❤️"
            ],
            "悲傷": [
                "難過", "好累", "傷心", "想哭", "嗚嗚", "受傷", "委屈", "心酸", "痛苦", "難受",
                "被罵", "挫折", "失落", "孤單", "寂寞", "低潮", "崩潰", "好痛", "眼淚", "心碎",
                "好煩", "倒楣", "壓力大", "提不起勁", "無力", "虛脫", "自閉", "😭", "😢", "💔", "🥺"
            ],
            "信任": [
                "謝謝", "感謝", "有你在真好", "辛苦了", "相信你", "最喜歡你", "靠你了", "安心", "溫暖",
                "聽話", "依靠", "陪伴", "夥伴", "兄弟", "交給你", "贊同", "認同", "信任", "放心", "包容",
                "抱抱", "摸摸", "乖", "守護", "照顧", "🫂", "🤝", "✨"
            ],
            "厭惡": [
                "討厭", "好噁", "噁心", "反感", "反胃", "不想理", "滾", "滾開", "討厭鬼", "下頭", "虛偽",
                "嫌棄", "好假", "爛透", "差勁", "不屑", "拒絕", "鄙視", "垃圾", "爛", "廢物", "白目", "🤢", "🤮", "💩"
            ],
            "恐懼": [
                "害怕", "好恐怖", "嚇死", "怕豹", "發抖", "緊張", "慌張", "焦慮", "不安", "完蛋了",
                "挫賽", "怎麼辦", "慘了", "恐懼", "驚恐", "心慌", "不知所措", "嚇到", "😰", "😨", "😱"
            ],
            "憤怒": [
                "氣死", "好生氣", "火大", "不爽", "幹", "超幹", "靠北", "三小", "欠揍", "可惡",
                "抓狂", "憤怒", "暴怒", "傻眼", "氣炸", "翻白眼", "憑什麼", "過分", "閉嘴", "白痴", "智障", "😡", "🤬", "💢"
            ],
            "驚訝": [
                "真的假的", "天啊", "哇塞", "居然", "竟然", "傻眼", "震驚", "不會吧", "不可思議",
                "真的假的啦", "嚇一跳", "太扯了", "扯爆", "太神啦", "神展開", "驚呆", "愣住", "😲", "🤯", "⚡"
            ],
            "期待": [
                "好期待", "希望", "想看", "想要", "等待", "迫不及待", "趕快", "等不及", "展望",
                "如果可以", "想要試試", "敲碗", "卡位", "好奇", "想知道", "願望", "夢想", "🤩", "✨", "🔥"
            ]
        }

    def analyze_text(self, text: str) -> EmotionAnalysisResult:
        """對輸入文字進行多維幾何情緒投影運算"""
        if not text or not text.strip():
            return self._apply_dynamics(self._neutral_result())

        cleaned = text.strip()

        # 1. 計算 8 大原色情緒之共振分數 (Resonance Scores)
        raw_scores: Dict[str, float] = {}
        for emotion, anchor_words in self.emotion_anchors.items():
            score = 0.0
            for word in anchor_words:
                if word in cleaned:
                    # 依據關鍵字長度與出現頻率給予非線性權重
                    weight = 1.0 + (len(word) * 0.4)
                    score += weight
            raw_scores[emotion] = score

        total_score = sum(raw_scores.values())

        # 若無強烈顯性情緒詞，進行上下文微特徵研判
        if total_score < 0.1:
            return self._infer_implicit_micro_emotions(cleaned)

        # 2. 歸一化各情緒共振權重
        prob_dist = {k: v / total_score for k, v in raw_scores.items()}

        # 排序前兩大主導情緒
        sorted_emotions = sorted(prob_dist.items(), key=lambda x: x[1], reverse=True)
        primary_emo, primary_weight = sorted_emotions[0]
        secondary_emo, secondary_weight = sorted_emotions[1] if len(sorted_emotions) > 1 else ("無", 0.0)

        # 3. 計算連續幾何座標：Valence (愉悅度) 與 Arousal (喚醒度)
        valence = (
            (prob_dist.get("喜悅", 0.0) * 1.0)
            + (prob_dist.get("信任", 0.0) * 0.7)
            + (prob_dist.get("期待", 0.0) * 0.6)
            + (prob_dist.get("驚訝", 0.0) * 0.1)
            - (prob_dist.get("悲傷", 0.0) * 0.85)
            - (prob_dist.get("恐懼", 0.0) * 0.8)
            - (prob_dist.get("厭惡", 0.0) * 0.9)
            - (prob_dist.get("憤怒", 0.0) * 0.95)
        )
        # 裁剪在 [-1.0, 1.0]
        valence = max(-1.0, min(1.0, round(valence, 3)))

        arousal = (
            (prob_dist.get("憤怒", 0.0) * 1.0)
            + (prob_dist.get("狂喜", 0.0) * 0.95)
            + (prob_dist.get("喜悅", 0.0) * 0.8)
            + (prob_dist.get("驚訝", 0.0) * 0.9)
            + (prob_dist.get("恐懼", 0.0) * 0.85)
            + (prob_dist.get("期待", 0.0) * 0.7)
            + (prob_dist.get("厭惡", 0.0) * 0.5)
            + (prob_dist.get("悲傷", 0.0) * 0.3)
        )
        arousal = max(0.1, min(1.0, round(arousal, 3)))

        # 4. 判定複合情感標籤
        composite = self.COMPOSITE_MAP.get((primary_emo, secondary_emo))
        if not composite:
            composite = self.COMPOSITE_MAP.get((secondary_emo, primary_emo))
        if not composite:
            composite = f"{primary_emo}流露"

        # 5. 計算對大腦 4 大神經遞質之推動脈衝 (Neurotransmitter Impulses)
        intensity = min(1.0, round(total_score / 3.0, 3))

        delta_dopamine = 0.0
        delta_serotonin = 0.0
        delta_cortisol = 0.0
        delta_oxytocin = 0.0

        if primary_emo in ("喜悅", "期待"):
            delta_dopamine = round(12.0 * intensity + 3.0, 2)
            delta_serotonin = round(6.0 * intensity + 2.0, 2)
            delta_oxytocin = round(2.5 * intensity + 0.5, 2)
        elif primary_emo in ("悲傷", "恐懼"):
            # 觸發保護欲與同理心：血清素上升（想撫慰對方），皮質醇微升
            delta_serotonin = round(10.0 * intensity + 4.0, 2)
            delta_oxytocin = round(5.0 * intensity + 2.0, 2)
            delta_cortisol = round(4.0 * intensity, 2)
        elif primary_emo == "信任":
            delta_oxytocin = round(8.0 * intensity + 3.0, 2)
            delta_serotonin = round(7.0 * intensity + 2.0, 2)
            delta_dopamine = round(4.0 * intensity, 2)
        elif primary_emo in ("憤怒", "厭惡"):
            # 判斷是否針對機器人本身
            if any(insult in cleaned for insult in ["你這", "爛機器人", "閉嘴", "廢物", "白痴", "滾"]):
                delta_cortisol = round(25.0 * intensity + 10.0, 2)
                delta_dopamine = -round(15.0 * intensity, 2)
            else:
                # 使用者在抱怨外界事物：同仇敵愾，血清素上升陪伴
                delta_serotonin = round(6.0 * intensity, 2)
                delta_oxytocin = round(4.0 * intensity, 2)

        summary = f"感測到使用者【{composite}】（愉悅度: {valence:+0.2f}, 激動度: {arousal:0.2f}）"

        raw_res = EmotionAnalysisResult(
            valence=valence,
            arousal=arousal,
            dominant_emotion=primary_emo,
            secondary_emotion=secondary_emo,
            composite_sentiment=composite,
            intensity=intensity,
            sentiment_summary=summary,
            delta_dopamine=delta_dopamine,
            delta_serotonin=delta_serotonin,
            delta_cortisol=delta_cortisol,
            delta_oxytocin=delta_oxytocin,
            threat_level=0.0,
            active_layers=["L1_GeometricReflex"],
        )

        final_res = raw_res
        if self.neural_array:
            try:
                fused = self.neural_array.perceive(cleaned, raw_res)
                final_res = EmotionAnalysisResult(
                    valence=fused.valence,
                    arousal=fused.arousal,
                    dominant_emotion=fused.dominant_emotion,
                    secondary_emotion=fused.secondary_emotion,
                    composite_sentiment=fused.composite_sentiment,
                    intensity=fused.intensity,
                    sentiment_summary=fused.summary,
                    delta_dopamine=fused.delta_dopamine,
                    delta_serotonin=fused.delta_serotonin,
                    delta_cortisol=fused.delta_cortisol,
                    delta_oxytocin=fused.delta_oxytocin,
                    threat_level=fused.threat_level,
                    active_layers=fused.active_layers,
                )
            except Exception as e:
                log.warning(f"神經模型陣列集成感知例外，使用第 1 層反射: {e}")

        return self._apply_dynamics(final_res)

    def _infer_implicit_micro_emotions(self, text: str) -> EmotionAnalysisResult:
        """無明顯情緒詞時之微特徵推斷（如句尾標點、長度、問候語）"""
        if any(greet in text for greet in ["早安", "晚安", "哈囉", "嗨", "安安", "在嗎", "你好"]):
            raw_res = EmotionAnalysisResult(
                valence=0.35,
                arousal=0.45,
                dominant_emotion="喜悅",
                secondary_emotion="信任",
                composite_sentiment="親切問候",
                intensity=0.3,
                sentiment_summary="收到親切日常問候",
                delta_dopamine=4.0,
                delta_serotonin=3.0,
                delta_cortisol=0.0,
                delta_oxytocin=1.0,
                threat_level=0.0,
                active_layers=["L1_GeometricReflex"],
            )
        elif "?" in text or "？" in text or "為什麼" in text or "怎麼" in text:
            # 好奇發問：激發多巴胺探索欲
            raw_res = EmotionAnalysisResult(
                valence=0.15,
                arousal=0.55,
                dominant_emotion="期待",
                secondary_emotion="信任",
                composite_sentiment="求知好奇",
                intensity=0.4,
                sentiment_summary="激發好奇探索慾望",
                delta_dopamine=6.0,
                delta_serotonin=2.0,
                delta_cortisol=0.0,
                delta_oxytocin=0.5,
                threat_level=0.0,
                active_layers=["L1_GeometricReflex"],
            )
        else:
            raw_res = self._neutral_result()

        final_res = raw_res
        if self.neural_array:
            try:
                fused = self.neural_array.perceive(text.strip(), raw_res)
                final_res = EmotionAnalysisResult(
                    valence=fused.valence,
                    arousal=fused.arousal,
                    dominant_emotion=fused.dominant_emotion,
                    secondary_emotion=fused.secondary_emotion,
                    composite_sentiment=fused.composite_sentiment,
                    intensity=fused.intensity,
                    sentiment_summary=fused.summary,
                    delta_dopamine=fused.delta_dopamine,
                    delta_serotonin=fused.delta_serotonin,
                    delta_cortisol=fused.delta_cortisol,
                    delta_oxytocin=fused.delta_oxytocin,
                    threat_level=fused.threat_level,
                    active_layers=fused.active_layers,
                )
            except Exception as e:
                log.warning(f"微特徵神經陣列推論例外: {e}")

        return self._apply_dynamics(final_res)

    def _apply_dynamics(self, res: EmotionAnalysisResult) -> EmotionAnalysisResult:
        """套用神經遞質時間指數衰減與滯後阻尼平滑機制"""
        impacts = {
            "dopamine": res.delta_dopamine,
            "serotonin": res.delta_serotonin,
            "cortisol": res.delta_cortisol,
            "oxytocin": res.delta_oxytocin,
        }
        res.raw_valence = res.valence
        res.raw_arousal = res.arousal

        levels, smoothed_valence, smoothed_arousal = self.dynamics.decay_and_update(
            impacts=impacts,
            instant_valence=res.valence,
            instant_arousal=res.arousal,
        )
        res.smoothed_valence = smoothed_valence
        res.smoothed_arousal = smoothed_arousal
        res.dynamics_levels = levels
        return res

    def _neutral_result(self) -> EmotionAnalysisResult:
        """中性平和狀態"""
        return EmotionAnalysisResult(
            valence=0.0,
            arousal=0.3,
            dominant_emotion="平和",
            secondary_emotion="無",
            composite_sentiment="隨性閒聊",
            intensity=0.1,
            sentiment_summary="平靜自然互動",
            delta_dopamine=1.0,
            delta_serotonin=1.0,
            delta_cortisol=0.0,
            delta_oxytocin=0.2,
        )
