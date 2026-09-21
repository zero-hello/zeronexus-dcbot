"""ZeroNexus 本地多層次神經模型陣列 (Hierarchical Neural Sensory Array)

架構特色：
1. 第 1 層 (L1): 微秒級幾何張量反射模型 (Fast Geometric Reflex Kernel)
   - 本地純幾何向量運算，14KB，耗時 < 1ms。精準捕捉在地生活詞彙與情緒慣用語。
2. 第 2 層 (L2): 本地深層語意嵌入特徵模型 (Deep Semantic ONNX Engine)
   - 採用量化 ONNX MiniLM 模型 (~23MB)，提取 384 維度密集特徵向量。
   - 透過高維語意餘弦相似度 (Cosine Similarity) 實現深層語意共鳴。
3. 第 3 層 (L3): 自主防衛與毒性哨兵模型 (Hostility & Threat Sentinel ONNX Engine)
   - 採用量化 ONNX 哨兵模型 (~105MB)，辨識 6 大攻擊與破防維度 (Toxic, Severe Toxic, Obscene, Threat, Insult, Identity Hate)。
   - 守護大腦自尊與心理界線，即時調控皮質醇防禦機制。
4. 集成融合中樞 (Ensemble Fusion Modulator):
   - 多模型權重動態調合，兼具微秒級反射之敏銳度與深層神經網路之細緻度。
"""

import os
import logging
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("ZeroNexus.Brain.NeuralArray")

# 嘗試載入 onnxruntime 與 tokenizers
try:
    import onnxruntime as ort
    from tokenizers import Tokenizer
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False
    log.warning("未檢測到 onnxruntime 或 tokenizers，多模型陣列將以純幾何反射核心運行。")


@dataclass
class FusedSensoryOutput:
    """多層次神經模型陣列集成感知輸出"""
    valence: float  # 愉悅度 (-1.0 ~ 1.0)
    arousal: float  # 喚醒激動度 (0.0 ~ 1.0)
    dominant_emotion: str  # 主導情緒
    secondary_emotion: str  # 次要情緒
    composite_sentiment: str  # 複合高級情感
    intensity: float  # 情緒總強度 (0.0 ~ 1.0)
    threat_level: float  # 敵意與威脅指數 (0.0 ~ 1.0)
    summary: str  # 感知摘要描述
    # 神經遞質脈衝
    delta_dopamine: float
    delta_serotonin: float
    delta_cortisol: float
    delta_oxytocin: float
    # 模型陣列診斷
    active_layers: List[str]


class HierarchicalNeuralArray:
    """三層協同本地離線神經模型陣列"""

    def __init__(self, models_dir: Optional[str] = None) -> None:
        if models_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.models_dir = os.path.join(base_dir, "data", "brain", "models")
        else:
            self.models_dir = models_dir

        self.semantic_session = None
        self.semantic_tokenizer = None
        self.sentinel_session = None
        self.sentinel_tokenizer = None

        self._proto_embeddings: Dict[str, np.ndarray] = {}
        self._init_neural_engines()

    def _init_neural_engines(self) -> None:
        """初始化第 2 層與第 3 層 ONNX 神經推論引擎"""
        if not HAS_ONNX:
            return

        # 1. 載入第 2 層：語意特徵嵌入模型
        sem_model_path = os.path.join(self.models_dir, "semantic_extractor", "onnx", "model_quantized.onnx")
        sem_tok_path = os.path.join(self.models_dir, "semantic_extractor", "tokenizer.json")

        if os.path.exists(sem_model_path) and os.path.exists(sem_tok_path):
            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.inter_op_num_threads = 1
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self.semantic_session = ort.InferenceSession(sem_model_path, sess_options=opts, providers=["CPUExecutionProvider"])
                self.semantic_tokenizer = Tokenizer.from_file(sem_tok_path)
                self.semantic_tokenizer.enable_padding(length=128)
                self.semantic_tokenizer.enable_truncation(max_length=128)
                log.info("✓ 第 2 層【深層語意嵌入神經引擎】載入成功")
                self._precompute_emotion_prototypes()
            except Exception as e:
                log.warning(f"第 2 層語意模型載入失敗: {e}")

        # 2. 載入第 3 層：防衛與毒性哨兵模型
        sen_model_path = os.path.join(self.models_dir, "hostility_sentinel", "onnx", "model_quantized.onnx")
        sen_tok_path = os.path.join(self.models_dir, "hostility_sentinel", "tokenizer.json")

        if os.path.exists(sen_model_path) and os.path.exists(sen_tok_path):
            try:
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.inter_op_num_threads = 1
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self.sentinel_session = ort.InferenceSession(sen_model_path, sess_options=opts, providers=["CPUExecutionProvider"])
                self.sentinel_tokenizer = Tokenizer.from_file(sen_tok_path)
                self.sentinel_tokenizer.enable_padding(length=128)
                self.sentinel_tokenizer.enable_truncation(max_length=128)
                log.info("✓ 第 3 層【防衛與毒性哨兵神經引擎】載入成功")
            except Exception as e:
                log.warning(f"第 3 層哨兵模型載入失敗: {e}")

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """提取 384 維語意特徵向量並進行 Mean Pooling 與 L2 歸一化"""
        if not self.semantic_session or not self.semantic_tokenizer:
            return None
        try:
            enc = self.semantic_tokenizer.encode(text)
            inputs = {
                "input_ids": np.array([enc.ids], dtype=np.int64),
                "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
                "token_type_ids": np.array([enc.type_ids], dtype=np.int64),
            }
            outputs = self.semantic_session.run(None, inputs)
            # outputs[0] 形狀: (1, seq_len, 384)
            last_hidden_state = outputs[0][0]
            mask = np.array(enc.attention_mask)[:, None]
            # Mean Pooling
            sum_embeddings = np.sum(last_hidden_state * mask, axis=0)
            sum_mask = np.clip(mask.sum(axis=0), a_min=1e-9, a_max=None)
            mean_pooled = sum_embeddings / sum_mask
            # L2 歸一化
            norm = np.linalg.norm(mean_pooled)
            if norm > 0:
                mean_pooled = mean_pooled / norm
            return mean_pooled
        except Exception as e:
            log.debug(f"語意特徵提取例外: {e}")
            return None

    def _precompute_emotion_prototypes(self) -> None:
        """預先計算情感原型向量，避免每次對話重複計算"""
        prototypes = {
            "喜悅": "我真的好開心好感動，太棒了，好幸福喔！",
            "悲傷": "我好難過好疲憊，覺得心裡好酸好失落想哭。",
            "信任": "謝謝你一直以來的陪伴與支持，有你在真安心。",
            "厭惡": "好噁心好討厭，這種虛偽做作令人反胃。",
            "恐懼": "我好害怕，好焦慮不知所措，完蛋了怎麼辦。",
            "憤怒": "真的太令人生氣了，莫名其妙，火大至極！",
            "驚訝": "哇塞天啊，居然是真的嗎？完全不可思議！",
            "期待": "好期待未來的發展，迫不及待想要一起體驗！",
        }
        for emo, text in prototypes.items():
            emb = self._get_embedding(text)
            if emb is not None:
                self._proto_embeddings[emo] = emb

    def _predict_sentinel_threat(self, text: str) -> Tuple[float, Dict[str, float]]:
        """第 3 層哨兵：計算 6 維惡意攻擊機率並輸出綜合威脅指數"""
        if not self.sentinel_session or not self.sentinel_tokenizer:
            return 0.0, {}
        try:
            enc = self.sentinel_tokenizer.encode(text)
            inputs = {
                "input_ids": np.array([enc.ids], dtype=np.int64),
                "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
                "token_type_ids": np.array([enc.type_ids], dtype=np.int64),
            }
            outputs = self.sentinel_session.run(None, inputs)
            # outputs[0] 形狀: (1, 6)
            logits = outputs[0][0]
            # Sigmoid 轉為機率
            probs = 1.0 / (1.0 + np.exp(-logits))
            labels = ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]
            detail = {labels[i]: float(probs[i]) for i in range(len(labels))}

            # 綜合威脅指數：以 toxic, severe_toxic, insult, threat 為主力加權
            threat_score = (
                detail.get("toxic", 0.0) * 0.4
                + detail.get("severe_toxic", 0.0) * 0.8
                + detail.get("threat", 0.0) * 0.9
                + detail.get("insult", 0.0) * 0.5
                + detail.get("obscene", 0.0) * 0.3
            )
            threat_score = max(0.0, min(1.0, round(threat_score, 3)))
            return threat_score, detail
        except Exception as e:
            log.debug(f"哨兵推論例外: {e}")
            return 0.0, {}

    def perceive(self, text: str, reflex_output) -> FusedSensoryOutput:
        """多模型集成融合感知中樞

        參數:
            text: 使用者輸入文本
            reflex_output: 第 1 層反射幾何投影結果 (EmotionAnalysisResult)
        """
        active_layers = ["L1_GeometricReflex"]
        cleaned = text.strip()

        # 1. 取得第 1 層反射數值
        val = reflex_output.valence
        aro = reflex_output.arousal
        dom_emo = reflex_output.dominant_emotion
        sec_emo = reflex_output.secondary_emotion
        comp_sent = reflex_output.composite_sentiment
        intensity = reflex_output.intensity

        delta_dop = reflex_output.delta_dopamine
        delta_ser = reflex_output.delta_serotonin
        delta_cor = reflex_output.delta_cortisol
        delta_oxy = reflex_output.delta_oxytocin

        # 2. 執行第 2 層：深層語意嵌入與原型餘弦相似度共鳴
        semantic_scores: Dict[str, float] = {}
        if self.semantic_session and self._proto_embeddings:
            active_layers.append("L2_SemanticONNX")
            user_emb = self._get_embedding(cleaned)
            if user_emb is not None:
                for emo, proto_emb in self._proto_embeddings.items():
                    sim = float(np.dot(user_emb, proto_emb))
                    semantic_scores[emo] = max(0.0, sim)

                # 若語意餘弦相似度有極顯著的情感原型，進行連續幾何座標平滑校正
                if semantic_scores:
                    top_sem_emo = max(semantic_scores.items(), key=lambda x: x[1])
                    if top_sem_emo[1] > 0.45:
                        # 進行 30% 深層語意引力拉拽 (Semantic Gravitational Pull)
                        if top_sem_emo[0] in ("喜悅", "期待", "信任"):
                            val = round(val * 0.7 + 0.3 * top_sem_emo[1], 3)
                        elif top_sem_emo[0] in ("悲傷", "恐懼", "厭惡", "憤怒"):
                            val = round(val * 0.7 - 0.3 * top_sem_emo[1], 3)

        # 3. 執行第 3 層：防衛與毒性哨兵偵測
        threat_level = 0.0
        if self.sentinel_session:
            active_layers.append("L3_HostilitySentinelONNX")
            threat_level, threat_detail = self._predict_sentinel_threat(cleaned)

            # 若第 3 層哨兵偵測到高威脅或惡意挑釁
            if threat_level > 0.3:
                # 激發皮質醇自尊防護，壓抑多巴胺
                sentinel_cor = round(threat_level * 35.0, 2)
                delta_cor = max(delta_cor, sentinel_cor)
                delta_dop = min(delta_dop, -round(threat_level * 15.0, 2))
                val = min(val, -0.6)
                aro = max(aro, 0.8)
                comp_sent = "防備警惕與受創抗拒"
                dom_emo = "憤怒"
                sec_emo = "厭惡"

        # 4. 生成多模型集成感知摘要
        summary = (
            f"神經模型陣列感知【{comp_sent}】(愉悅度: {val:+0.2f}, 激動度: {aro:0.2f}, "
            f"威脅指標: {threat_level:0.2f} | 啟動層: {','.join(active_layers)})"
        )

        return FusedSensoryOutput(
            valence=val,
            arousal=aro,
            dominant_emotion=dom_emo,
            secondary_emotion=sec_emo,
            composite_sentiment=comp_sent,
            intensity=intensity,
            threat_level=threat_level,
            summary=summary,
            delta_dopamine=delta_dop,
            delta_serotonin=delta_ser,
            delta_cortisol=delta_cor,
            delta_oxytocin=delta_oxy,
            active_layers=active_layers,
        )
