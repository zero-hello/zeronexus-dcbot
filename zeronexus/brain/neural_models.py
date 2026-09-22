"""ZeroNexus 本地六核離線神經模型矩陣 (Hexa-Model Neural Sensory Array)

六大協同離線神經模型陣列架構：
1. 模型 1 (中文語意共鳴): BGE-Small-ZH-v1.5 (~23MB)
   - 專精繁體中文生活語境、細膩情緒語意與同理心空間。
2. 模型 2 (通用概念幾何): all-MiniLM-L6-v2 (~22MB)
   - 跨語言極速概念幾何空間映射與情感原型對齊。
3. 模型 3 (深層微調幾何): all-MiniLM-L12-v2 (~32MB)
   - 12 層深度注意力，平滑微表情與隱晦語氣捕捉。
4. 模型 4 (多語言同義共鳴): paraphrase-multilingual-MiniLM-L12-v2 (~113MB)
   - 50+ 語言跨語系同義情感共鳴（中英日韓混雜無縫理解）。
5. 模型 5 (情感極性分類): DistilBERT-base-SST-2 (~65MB)
   - 專門輸出明確 Positive/Negative 情感極性對數機率。
6. 模型 6 (神經防衛哨兵): Toxic-BERT (~106MB)
   - 6 維人身攻擊、威脅、侮辱與挑釁毒性警戒，守護心理防線。
7. 基底層 (毫秒級反射核): Fast Geometric Reflex Kernel (14KB, < 1ms)
   - 臺灣在地網路俚語、生活情緒符號微秒級極速反射。
"""

import os
import logging
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("ZeroNexus.Brain.NeuralArray")

try:
    import onnxruntime as ort
    from tokenizers import Tokenizer
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False
    log.warning("未檢測到 onnxruntime 或 tokenizers，陣列將以純幾何反射核心運行。")


# 對立情緒原型對 (Antagonistic Emotion Pairs)
ANTAGONISTIC_PAIRS = [
    ("喜悅", "悲傷"),
    ("信任", "厭惡"),
    ("期待", "恐懼"),
    ("喜悅", "憤怒"),
    ("信任", "憤怒"),
]


def orthogonalize_prototypes(
    prototypes: Dict[str, np.ndarray],
    decoupling_factor: float = 0.5,
    centroid_factor: float = 0.7,
) -> Dict[str, np.ndarray]:
    """原型向量正交化與軟對比解耦 (Gram-Schmidt Orthogonalization & Contrastive Decoupling)

    針對語意空間中容易產生沾黏的對立情緒原型（如「喜悅」與「悲傷」、「信任」與「厭惡」）：
    1. 計算原型矩陣之語意重心（Centroid），剔除通用情感強度的共享共性背景（Centroid Subtraction）。
    2. 針對成對對立情緒執行 Gram-Schmidt 投影剔除，消除相互重疊成分。
    3. 全面重新執行 L2 歸一化。
    """
    if not prototypes:
        return {}

    ortho_dict = {k: v.copy() for k, v in prototypes.items()}

    # 1. 重心共性剔除 (Centroid Subtraction)
    all_vecs = list(ortho_dict.values())
    if len(all_vecs) >= 2:
        mean_vec = np.mean(all_vecs, axis=0)
        mean_norm = np.linalg.norm(mean_vec)
        if mean_norm > 1e-6:
            mean_unit = mean_vec / mean_norm
            for k in ortho_dict:
                p = ortho_dict[k]
                p_c = p - centroid_factor * np.dot(p, mean_unit) * mean_unit
                norm = np.linalg.norm(p_c)
                if norm > 1e-6:
                    ortho_dict[k] = p_c / norm

    # 2. 對立原型 Gram-Schmidt 投影剔除
    for emo_a, emo_b in ANTAGONISTIC_PAIRS:
        if emo_a in ortho_dict and emo_b in ortho_dict:
            va = ortho_dict[emo_a]
            vb = ortho_dict[emo_b]

            sim = float(np.dot(va, vb))
            if sim > 0.0:
                va_prime = va - (decoupling_factor * sim * vb)
                vb_prime = vb - (decoupling_factor * sim * va)

                norm_a = np.linalg.norm(va_prime)
                norm_b = np.linalg.norm(vb_prime)

                if norm_a > 1e-6:
                    ortho_dict[emo_a] = va_prime / norm_a
                if norm_b > 1e-6:
                    ortho_dict[emo_b] = vb_prime / norm_b

    return ortho_dict


def calibrate_prototype_projections(
    raw_scores: Dict[str, float],
    temperature: float = 0.07,
    threshold: float = 0.15,
) -> Dict[str, float]:
    """餘弦投影校準 (Cosine Projection Calibration)

    1. 閾值過濾 (Threshold Filtering)：過濾掉低於 threshold 的微弱雜訊分量。
    2. 溫度縮放 Softmax (Temperature-Scaled Softmax)：
       z_i = score_i / temperature
       p_i = exp(z_i - max(z)) / sum(exp(z_j - max(z)))
    3. 加權校準：保留原始餘弦幅度的同時，透過溫度縮放銳化分佈，使主導情緒突出。
    """
    if not raw_scores:
        return {}

    # 1. 閾值過濾：若相似度低於閾值，視為背景雜訊置零
    filtered_scores = {}
    for emo, score in raw_scores.items():
        if score < threshold:
            filtered_scores[emo] = 0.0
        else:
            filtered_scores[emo] = score

    # 若過濾後全為 0，則保留原始最高分
    max_raw_val = max(raw_scores.values())
    if all(v == 0.0 for v in filtered_scores.values()):
        for emo, score in raw_scores.items():
            if score == max_raw_val and score > 0:
                filtered_scores[emo] = score

    # 2. 溫度縮放 Softmax
    items = list(filtered_scores.items())
    keys = [k for k, _ in items]
    vals = np.array([v for _, v in items], dtype=np.float64)

    temp = max(1e-4, temperature)
    scaled_vals = vals / temp
    max_s = np.max(scaled_vals)
    exp_vals = np.exp(scaled_vals - max_s)
    sum_exp = np.sum(exp_vals)

    probs = exp_vals / sum_exp if sum_exp > 0 else exp_vals

    # 3. 結合原始強度與銳化機率：calibrated_score = prob * val
    calibrated: Dict[str, float] = {}
    for idx, emo in enumerate(keys):
        calibrated[emo] = float(probs[idx] * vals[idx])

    return calibrated


@dataclass
class FusedSensoryOutput:
    """六核模型矩陣集成感知輸出"""
    valence: float  # 愉悅度 (-1.0 ~ 1.0)
    arousal: float  # 喚醒激動度 (0.0 ~ 1.0)
    dominant_emotion: str  # 主導情緒
    secondary_emotion: str  # 次要情緒
    composite_sentiment: str  # 複合高級情感
    intensity: float  # 情緒總強度 (0.0 ~ 1.0)
    threat_level: float  # 敵意與威脅指數 (0.0 ~ 1.0)
    summary: str  # 感知摘要描述
    delta_dopamine: float
    delta_serotonin: float
    delta_cortisol: float
    delta_oxytocin: float
    active_layers: List[str]


class HierarchicalNeuralArray:
    """六核協同離線神經模型矩陣"""

    def __init__(self, models_dir: Optional[str] = None) -> None:
        if models_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.models_dir = os.path.join(base_dir, "data", "brain", "models")
        else:
            self.models_dir = models_dir

        # 模型 1: 中文 BGE
        self.bge_session = None
        self.bge_tokenizer = None
        self._bge_protos: Dict[str, np.ndarray] = {}

        # 模型 2: MiniLM-L6
        self.l6_session = None
        self.l6_tokenizer = None
        self._l6_protos: Dict[str, np.ndarray] = {}

        # 模型 3: MiniLM-L12
        self.l12_session = None
        self.l12_tokenizer = None
        self._l12_protos: Dict[str, np.ndarray] = {}

        # 模型 4: 多語言 Multilingual-L12
        self.multi_session = None
        self.multi_tokenizer = None
        self._multi_protos: Dict[str, np.ndarray] = {}

        # 模型 5: DistilBERT-SST-2 (情感極性分類器)
        self.sst2_session = None
        self.sst2_tokenizer = None

        # 模型 6: Toxic-BERT 防衛哨兵
        self.sentinel_session = None
        self.sentinel_tokenizer = None

        self._init_neural_engines()

    def _load_model(self, folder: str, opts) -> Tuple[Optional[any], Optional[any]]:
        m_path = os.path.join(self.models_dir, folder, "onnx", "model_quantized.onnx")
        t_path = os.path.join(self.models_dir, folder, "tokenizer.json")
        if os.path.exists(m_path) and os.path.exists(t_path):
            try:
                sess = ort.InferenceSession(m_path, sess_options=opts, providers=["CPUExecutionProvider"])
                tok = Tokenizer.from_file(t_path)
                tok.enable_padding(length=128)
                tok.enable_truncation(max_length=128)
                return sess, tok
            except Exception as e:
                log.warning(f"載入模型 {folder} 失敗: {e}")
        return None, None

    def _init_neural_engines(self) -> None:
        if not HAS_ONNX:
            return

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        # 1. BGE-Small-ZH
        self.bge_session, self.bge_tokenizer = self._load_model("bge_small_zh", opts)
        if self.bge_session:
            log.info("✓ [1/6] 中文 BGE 語意引擎載入成功")
            self._precompute_bge_prototypes()
            self._bge_protos = orthogonalize_prototypes(self._bge_protos)

        # 2. MiniLM-L6
        self.l6_session, self.l6_tokenizer = self._load_model("semantic_extractor", opts)
        if self.l6_session:
            log.info("✓ [2/6] 通用概念 MiniLM-L6 載入成功")
            self._precompute_l6_prototypes()
            self._l6_protos = orthogonalize_prototypes(self._l6_protos)

        # 3. MiniLM-L12
        self.l12_session, self.l12_tokenizer = self._load_model("minilm_l12", opts)
        if self.l12_session:
            log.info("✓ [3/6] 深層平滑 MiniLM-L12 載入成功")
            self._precompute_l12_prototypes()
            self._l12_protos = orthogonalize_prototypes(self._l12_protos)

        # 4. Multilingual-L12
        self.multi_session, self.multi_tokenizer = self._load_model("multilingual_l12", opts)
        if self.multi_session:
            log.info("✓ [4/6] 多語言 Multilingual-L12 載入成功")
            self._precompute_multi_prototypes()
            self._multi_protos = orthogonalize_prototypes(self._multi_protos)

        # 5. DistilBERT-SST-2
        self.sst2_session, self.sst2_tokenizer = self._load_model("sentiment_sst2", opts)
        if self.sst2_session:
            log.info("✓ [5/6] 情感極性 DistilBERT-SST-2 載入成功")

        # 6. Toxic-BERT 哨兵
        self.sentinel_session, self.sentinel_tokenizer = self._load_model("hostility_sentinel", opts)
        if self.sentinel_session:
            log.info("✓ [6/6] 防衛哨兵 Toxic-BERT 載入成功")

    def _extract_embedding(self, session, tokenizer, text: str) -> Optional[np.ndarray]:
        if not session or not tokenizer:
            return None
        try:
            enc = tokenizer.encode(text)
            inputs = {
                "input_ids": np.array([enc.ids], dtype=np.int64),
                "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
            }
            # 部分模型需要 token_type_ids
            input_names = [i.name for i in session.get_inputs()]
            if "token_type_ids" in input_names:
                inputs["token_type_ids"] = np.array([enc.type_ids], dtype=np.int64)

            outputs = session.run(None, inputs)
            last_hidden_state = outputs[0][0]
            mask = np.array(enc.attention_mask)[:, None]
            sum_embeddings = np.sum(last_hidden_state * mask, axis=0)
            sum_mask = np.clip(mask.sum(axis=0), a_min=1e-9, a_max=None)
            mean_pooled = sum_embeddings / sum_mask
            norm = np.linalg.norm(mean_pooled)
            return mean_pooled / norm if norm > 0 else mean_pooled
        except Exception:
            return None

    def _precompute_bge_prototypes(self) -> None:
        prototypes = {
            "喜悅": "太棒了太開心，好幸福好感動，真的很感謝你！",
            "悲傷": "我覺得心裡好難過好累，挫折又無力，好想哭。",
            "信任": "謝謝你一直以來的支持與信任，有你真安心可靠。",
            "厭惡": "好噁心反感，這種行為真的很令人唾棄與反胃。",
            "恐懼": "好害怕焦慮，萬一搞砸了怎麼辦，心裡慌得不行。",
            "憤怒": "真的太令人生氣了，莫名其妙，火大至極！",
            "期待": "好期待未來的合作與冒險，迫不及待想嘗試！",
        }
        for emo, text in prototypes.items():
            emb = self._extract_embedding(self.bge_session, self.bge_tokenizer, text)
            if emb is not None:
                self._bge_protos[emo] = emb

    def _precompute_l6_prototypes(self) -> None:
        prototypes = {
            "喜悅": "I am overjoyed, thrilled, happy and delighted!",
            "悲傷": "I feel deeply heartbroken, sad, depressed and exhausted.",
            "信任": "Thank you so much for your trust, companionship and warmth.",
            "憤怒": "I am extremely angry, furious and indignant!",
            "期待": "I eagerly anticipate and look forward to this exciting journey!",
        }
        for emo, text in prototypes.items():
            emb = self._extract_embedding(self.l6_session, self.l6_tokenizer, text)
            if emb is not None:
                self._l6_protos[emo] = emb

    def _precompute_l12_prototypes(self) -> None:
        prototypes = {
            "喜悅": "Wonderful celebration, happiness, pure joy and gratefulness.",
            "悲傷": "Grief, helplessness, sorrow, crying and emotional pain.",
            "信任": "Reliable friendship, mutual respect, understanding and bond.",
        }
        for emo, text in prototypes.items():
            emb = self._extract_embedding(self.l12_session, self.l12_tokenizer, text)
            if emb is not None:
                self._l12_protos[emo] = emb

    def _precompute_multi_prototypes(self) -> None:
        prototypes = {
            "喜悅": "這真的太棒了，非常開心，超喜歡！",
            "悲傷": "心裡好難受，好失落好沮喪，覺得好累。",
            "信任": "有你真好，謝謝你的陪伴，辛苦了！",
        }
        for emo, text in prototypes.items():
            emb = self._extract_embedding(self.multi_session, self.multi_tokenizer, text)
            if emb is not None:
                self._multi_protos[emo] = emb

    def _predict_sst2_polarity(self, text: str) -> Tuple[float, float]:
        """模型 5: SST-2 輸出 (負向機率, 正向機率)"""
        if not self.sst2_session or not self.sst2_tokenizer:
            return 0.5, 0.5
        try:
            enc = self.sst2_tokenizer.encode(text)
            inputs = {
                "input_ids": np.array([enc.ids], dtype=np.int64),
                "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
            }
            outputs = self.sst2_session.run(None, inputs)
            logits = outputs[0][0]
            # Softmax
            exp_l = np.exp(logits - np.max(logits))
            probs = exp_l / np.sum(exp_l)
            # label 0: NEGATIVE, label 1: POSITIVE
            return float(probs[0]), float(probs[1])
        except Exception:
            return 0.5, 0.5

    def _predict_sentinel_threat(self, text: str) -> Tuple[float, Dict[str, float]]:
        """模型 6: Toxic-BERT 6 維度毒性機率"""
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
            logits = outputs[0][0]
            probs = 1.0 / (1.0 + np.exp(-logits))
            labels = ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]
            detail = {labels[i]: float(probs[i]) for i in range(len(labels))}

            threat_score = (
                detail.get("toxic", 0.0) * 0.4
                + detail.get("severe_toxic", 0.0) * 0.8
                + detail.get("threat", 0.0) * 0.9
                + detail.get("insult", 0.0) * 0.5
                + detail.get("obscene", 0.0) * 0.3
            )
            return max(0.0, min(1.0, round(threat_score, 3))), detail
        except Exception:
            return 0.0, {}

    def perceive(self, text: str, reflex_output) -> FusedSensoryOutput:
        """六核離線神經模型矩陣全維度集成融合感知"""
        active_layers = ["L1_GeometricReflex"]
        cleaned = text.strip()

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

        # 1. 執行模型 1 (中文 BGE-ZH 共情)
        if self.bge_session and self._bge_protos:
            active_layers.append("M1_BGE_ZH")
            b_emb = self._extract_embedding(self.bge_session, self.bge_tokenizer, cleaned)
            if b_emb is not None:
                raw_b_scores = {e: float(np.dot(b_emb, p)) for e, p in self._bge_protos.items()}
                calibrated_b = calibrate_prototype_projections(raw_b_scores, temperature=0.07, threshold=0.15)
                top_b = max(calibrated_b.items(), key=lambda x: x[1])
                raw_top_b = max(raw_b_scores.items(), key=lambda x: x[1])
                if raw_top_b[1] > 0.45:
                    delta = 0.35 * raw_top_b[1]
                    val = val * 0.65 + (delta if top_b[0] in ("喜悅", "期待", "信任") else -delta)
                    if dom_emo in ("平和", "隨性閒聊", "無") and top_b[1] > 0.10:
                        dom_emo = top_b[0]

        # 2. 執行模型 2 (通用概念 MiniLM-L6)
        if self.l6_session and self._l6_protos:
            active_layers.append("M2_MiniLM_L6")
            l6_emb = self._extract_embedding(self.l6_session, self.l6_tokenizer, cleaned)
            if l6_emb is not None:
                raw_l6_scores = {e: float(np.dot(l6_emb, p)) for e, p in self._l6_protos.items()}
                calibrated_l6 = calibrate_prototype_projections(raw_l6_scores, temperature=0.07, threshold=0.15)
                top_l6 = max(calibrated_l6.items(), key=lambda x: x[1])
                raw_top_l6 = max(raw_l6_scores.items(), key=lambda x: x[1])
                if raw_top_l6[1] > 0.40:
                    delta = 0.20 * raw_top_l6[1]
                    val = val * 0.80 + (delta if top_l6[0] in ("喜悅", "期待", "信任") else -delta)

        # 3. 執行模型 3 (深層平滑 MiniLM-L12)
        if self.l12_session and self._l12_protos:
            active_layers.append("M3_MiniLM_L12")
            l12_emb = self._extract_embedding(self.l12_session, self.l12_tokenizer, cleaned)
            if l12_emb is not None:
                raw_l12_scores = {e: float(np.dot(l12_emb, p)) for e, p in self._l12_protos.items()}
                calibrated_l12 = calibrate_prototype_projections(raw_l12_scores, temperature=0.07, threshold=0.15)
                top_l12 = max(calibrated_l12.items(), key=lambda x: x[1])
                raw_top_l12 = max(raw_l12_scores.items(), key=lambda x: x[1])
                if raw_top_l12[1] > 0.40:
                    intensity = max(intensity, float(raw_top_l12[1]))

        # 4. 執行模型 4 (多語言 Multilingual-L12)
        if self.multi_session and self._multi_protos:
            active_layers.append("M4_Multi_L12")
            m_emb = self._extract_embedding(self.multi_session, self.multi_tokenizer, cleaned)
            if m_emb is not None:
                raw_m_scores = {e: float(np.dot(m_emb, p)) for e, p in self._multi_protos.items()}
                calibrated_m = calibrate_prototype_projections(raw_m_scores, temperature=0.07, threshold=0.15)
                top_m = max(calibrated_m.items(), key=lambda x: x[1])
                raw_top_m = max(raw_m_scores.items(), key=lambda x: x[1])
                if raw_top_m[1] > 0.45 and top_m[0] == "信任":
                    delta_oxy += 3.0
                    delta_ser += 2.0

        # 5. 執行模型 5 (情感極性 DistilBERT-SST-2)
        if self.sst2_session:
            active_layers.append("M5_DistilBERT_SST2")
            neg_p, pos_p = self._predict_sst2_polarity(cleaned)
            # 若正向機率壓倒性 (> 0.85) 或負向壓倒性 (> 0.85)，微調 Valence
            if pos_p > 0.85:
                val = max(val, 0.4)
            elif neg_p > 0.85:
                val = min(val, -0.4)

        # 6. 執行模型 6 (Toxic-BERT 哨兵)
        threat_level = 0.0
        if self.sentinel_session:
            active_layers.append("M6_ToxicSentinel")
            threat_level, _ = self._predict_sentinel_threat(cleaned)
            if threat_level > 0.3:
                sentinel_cor = round(threat_level * 35.0, 2)
                delta_cor = max(delta_cor, sentinel_cor)
                delta_dop = min(delta_dop, -round(threat_level * 15.0, 2))
                val = min(val, -0.6)
                aro = max(aro, 0.8)
                comp_sent = "防備警惕與受創抗拒"
                dom_emo = "憤怒"
                sec_emo = "厭惡"

        val = max(-1.0, min(1.0, round(val, 3)))
        aro = max(0.1, min(1.0, round(aro, 3)))

        summary = (
            f"六核神經模型矩陣集成【{comp_sent}】(愉悅: {val:+0.2f}, 激動: {aro:0.2f}, "
            f"威脅: {threat_level:0.2f} | 啟動層: {','.join(active_layers)})"
        )

        return FusedSensoryOutput(
            valence=val,
            arousal=aro,
            dominant_emotion=dom_emo,
            secondary_emotion=sec_emo,
            composite_sentiment=comp_sent,
            intensity=round(intensity, 3),
            threat_level=threat_level,
            summary=summary,
            delta_dopamine=delta_dop,
            delta_serotonin=delta_ser,
            delta_cortisol=delta_cor,
            delta_oxytocin=delta_oxy,
            active_layers=active_layers,
        )

    def get_embedding(self, text: str) -> np.ndarray:
        """獲取文字之 L2 歸一化語意特徵向量 (384 維)，優先使用 BGE 或 MiniLM，無權重時降級為確定性偽向量。"""
        if not text or not isinstance(text, str):
            text = ""
        # 1. 優先嘗試中文 BGE
        if self.bge_session and self.bge_tokenizer:
            emb = self._extract_embedding(self.bge_session, self.bge_tokenizer, text)
            if emb is not None:
                return emb
        # 2. 次要嘗試通用 MiniLM-L6
        if self.l6_session and self.l6_tokenizer:
            emb = self._extract_embedding(self.l6_session, self.l6_tokenizer, text)
            if emb is not None:
                return emb
        # 3. 降級確定性幾何偽特徵向量 (384 維，支援無 ONNX 或單元測試環境)
        return self._fallback_pseudo_embedding(text)

    def _fallback_pseudo_embedding(self, text: str) -> np.ndarray:
        """基於字元特徵與雜湊產生確定性 384 維單位向量。"""
        dim = 384
        if not text:
            vec = np.zeros(dim, dtype=np.float32)
            vec[0] = 1.0
            return vec

        # 以字元編碼與滑動窗口累加特徵
        vec = np.zeros(dim, dtype=np.float32)
        encoded = text.encode("utf-8")
        for i, b in enumerate(encoded):
            idx = (b * 13 + i * 37) % dim
            vec[idx] += 1.0
            # 引入字符平滑擴散
            vec[(idx + 1) % dim] += 0.5
            vec[(idx - 1) % dim] += 0.5

        norm = float(np.linalg.norm(vec))
        if norm > 1e-9:
            return (vec / norm).astype(np.float32)
        vec[0] = 1.0
        return vec

