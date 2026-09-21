"""ZeroNexus 本地三大離線神經模型陣列 (Tri-Model Neural Sensory Array)

三大協同模型架構：
1. 模型 1: 中文專屬高精確語意與同理心模型 (BGE-Small-ZH-v1.5 量化 ONNX ~23MB)
   - 專精繁體中文生活用語、語境細微差異、情緒高維向量投影。
2. 模型 2: 跨語言概念空間幾何模型 (MiniLM-L6 量化 ONNX ~22MB)
   - 專精跨語言概念空間對齊、多維語意餘弦相似度。
3. 模型 3: 神經防衛與自尊哨兵模型 (Toxic-BERT 量化 ONNX ~105MB)
   - 6 維人身攻擊、蓄意挑釁、毒性警戒 (Toxic, Threat, Insult, etc.)，守護心理防線。
4. 基底層: 微秒級高維幾何張量反射模型 (Fast Geometric Reflex Kernel, 14KB, < 1ms)
   - 臺灣在地網路俚語、生活情緒符號極速反射。
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
    log.warning("未檢測到 onnxruntime 或 tokenizers，多模型陣列將以純幾何反射核心運行。")


@dataclass
class FusedSensoryOutput:
    """三大模型陣列集成感知輸出"""
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
    """三大離線神經模型協同感知陣列"""

    def __init__(self, models_dir: Optional[str] = None) -> None:
        if models_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.models_dir = os.path.join(base_dir, "data", "brain", "models")
        else:
            self.models_dir = models_dir

        # 模型 1: 中文 BGE 模型
        self.bge_session = None
        self.bge_tokenizer = None
        self._bge_proto_embeddings: Dict[str, np.ndarray] = {}

        # 模型 2: 跨語言 MiniLM 模型
        self.semantic_session = None
        self.semantic_tokenizer = None
        self._sem_proto_embeddings: Dict[str, np.ndarray] = {}

        # 模型 3: Toxic-BERT 防衛哨兵
        self.sentinel_session = None
        self.sentinel_tokenizer = None

        self._init_neural_engines()

    def _init_neural_engines(self) -> None:
        if not HAS_ONNX:
            return

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        # 1. 載入模型 1：中文 BGE-small-zh
        bge_model_path = os.path.join(self.models_dir, "bge_small_zh", "onnx", "model_quantized.onnx")
        bge_tok_path = os.path.join(self.models_dir, "bge_small_zh", "tokenizer.json")
        if os.path.exists(bge_model_path) and os.path.exists(bge_tok_path):
            try:
                self.bge_session = ort.InferenceSession(bge_model_path, sess_options=opts, providers=["CPUExecutionProvider"])
                self.bge_tokenizer = Tokenizer.from_file(bge_tok_path)
                self.bge_tokenizer.enable_padding(length=128)
                self.bge_tokenizer.enable_truncation(max_length=128)
                log.info("✓ 模型 1【中文高精確 BGE-ZH 語意共情引擎】載入成功")
                self._precompute_bge_prototypes()
            except Exception as e:
                log.warning(f"BGE 模型載入失敗: {e}")

        # 2. 載入模型 2：跨語言 MiniLM-L6
        sem_model_path = os.path.join(self.models_dir, "semantic_extractor", "onnx", "model_quantized.onnx")
        sem_tok_path = os.path.join(self.models_dir, "semantic_extractor", "tokenizer.json")
        if os.path.exists(sem_model_path) and os.path.exists(sem_tok_path):
            try:
                self.semantic_session = ort.InferenceSession(sem_model_path, sess_options=opts, providers=["CPUExecutionProvider"])
                self.semantic_tokenizer = Tokenizer.from_file(sem_tok_path)
                self.semantic_tokenizer.enable_padding(length=128)
                self.semantic_tokenizer.enable_truncation(max_length=128)
                log.info("✓ 模型 2【跨語言概念空間 MiniLM 引擎】載入成功")
                self._precompute_sem_prototypes()
            except Exception as e:
                log.warning(f"MiniLM 模型載入失敗: {e}")

        # 3. 載入模型 3：Toxic-BERT 防衛哨兵
        sen_model_path = os.path.join(self.models_dir, "hostility_sentinel", "onnx", "model_quantized.onnx")
        sen_tok_path = os.path.join(self.models_dir, "hostility_sentinel", "tokenizer.json")
        if os.path.exists(sen_model_path) and os.path.exists(sen_tok_path):
            try:
                self.sentinel_session = ort.InferenceSession(sen_model_path, sess_options=opts, providers=["CPUExecutionProvider"])
                self.sentinel_tokenizer = Tokenizer.from_file(sen_tok_path)
                self.sentinel_tokenizer.enable_padding(length=128)
                self.sentinel_tokenizer.enable_truncation(max_length=128)
                log.info("✓ 模型 3【防衛與毒性哨兵 Toxic-BERT 引擎】載入成功")
            except Exception as e:
                log.warning(f"哨兵模型載入失敗: {e}")

    def _extract_embedding(self, session, tokenizer, text: str) -> Optional[np.ndarray]:
        if not session or not tokenizer:
            return None
        try:
            enc = tokenizer.encode(text)
            inputs = {
                "input_ids": np.array([enc.ids], dtype=np.int64),
                "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
                "token_type_ids": np.array([enc.type_ids], dtype=np.int64),
            }
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
                self._bge_proto_embeddings[emo] = emb

    def _precompute_sem_prototypes(self) -> None:
        prototypes = {
            "喜悅": "I am so happy, delighted, thrilled and joyful!",
            "悲傷": "I feel deeply sad, depressed, exhausted and heartbroken.",
            "信任": "Thank you so much for your trust, companionship and warmth.",
            "厭惡": "That is absolutely disgusting, vile, nauseating and despicable.",
            "恐懼": "I am so scared, terrified, anxious and stressed out.",
            "憤怒": "I am furious, enraged and extremely mad!",
            "期待": "I look forward to this with high anticipation and excitement!",
        }
        for emo, text in prototypes.items():
            emb = self._extract_embedding(self.semantic_session, self.semantic_tokenizer, text)
            if emb is not None:
                self._sem_proto_embeddings[emo] = emb

    def _predict_sentinel_threat(self, text: str) -> Tuple[float, Dict[str, float]]:
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
            threat_score = max(0.0, min(1.0, round(threat_score, 3)))
            return threat_score, detail
        except Exception:
            return 0.0, {}

    def perceive(self, text: str, reflex_output) -> FusedSensoryOutput:
        """三大離線神經模型集成融合感知"""
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

        # 1. 執行模型 1 (中文 BGE-ZH 高精確共情)
        if self.bge_session and self._bge_proto_embeddings:
            active_layers.append("M1_BGE_ZH")
            bge_emb = self._extract_embedding(self.bge_session, self.bge_tokenizer, cleaned)
            if bge_emb is not None:
                bge_scores = {emo: float(np.dot(bge_emb, proto)) for emo, proto in self._bge_proto_embeddings.items()}
                top_bge = max(bge_scores.items(), key=lambda x: x[1])
                if top_bge[1] > 0.50:
                    if top_bge[0] in ("喜悅", "期待", "信任"):
                        val = round(val * 0.6 + 0.4 * top_bge[1], 3)
                    elif top_bge[0] in ("悲傷", "恐懼", "厭惡", "憤怒"):
                        val = round(val * 0.6 - 0.4 * top_bge[1], 3)

        # 2. 執行模型 2 (跨語言 MiniLM 概念空間幾何)
        if self.semantic_session and self._sem_proto_embeddings:
            active_layers.append("M2_MiniLM")
            sem_emb = self._extract_embedding(self.semantic_session, self.semantic_tokenizer, cleaned)
            if sem_emb is not None:
                sem_scores = {emo: float(np.dot(sem_emb, proto)) for emo, proto in self._sem_proto_embeddings.items()}
                top_sem = max(sem_scores.items(), key=lambda x: x[1])
                if top_sem[1] > 0.45:
                    if top_sem[0] in ("喜悅", "期待", "信任"):
                        val = round(val * 0.8 + 0.2 * top_sem[1], 3)
                    elif top_sem[0] in ("悲傷", "恐懼", "厭惡", "憤怒"):
                        val = round(val * 0.8 - 0.2 * top_sem[1], 3)

        # 3. 執行模型 3 (Toxic-BERT 防衛哨兵)
        threat_level = 0.0
        if self.sentinel_session:
            active_layers.append("M3_HostilitySentinel")
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

        summary = (
            f"三大離線模型陣列集成【{comp_sent}】(愉悅: {val:+0.2f}, 激動: {aro:0.2f}, "
            f"威脅: {threat_level:0.2f} | 啟動層: {','.join(active_layers)})"
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
