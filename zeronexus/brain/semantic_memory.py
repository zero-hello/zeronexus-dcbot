"""ZeroNexus 本地語意向量記憶檢索器 (Semantic Vector Memory Retriever)

架構特色：
1. 結合離線中文 BGE / MiniLM 神經模型，實現毫秒級本地向量化（無需外部 API 額度）。
2. 多維度綜合相關度評分 (Composite Memory Relevance Scoring)：
   Score = 0.50 * 語意相似度 + 0.25 * 時間新鮮度 (艾賓浩斯遺忘曲線) + 0.15 * 重要性 + 0.10 * 情緒共鳴
3. 支援記憶關聯度重排與 Top-K 智慧召回。
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger("ZeroNexus.Brain.SemanticMemory")


@dataclass
class MemoryVectorItem:
    """單一記憶條目的向量特徵與元數據"""
    memory_id: str
    user_id: str
    text: str
    embedding: Optional[np.ndarray] = None
    created_at: float = field(default_factory=time.time)
    importance: float = 1.0  # 1.0 ~ 5.0
    emotion_tag: str = "平靜"
    metadata: Dict[str, Any] = field(default_factory=dict)


class SemanticMemoryRetriever:
    """本地語意向量記憶檢索與關聯回想引擎"""

    _instance: Optional["SemanticMemoryRetriever"] = None

    def __new__(cls) -> "SemanticMemoryRetriever":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._vector_cache: Dict[str, MemoryVectorItem] = {}
        return cls._instance

    def __init__(self) -> None:
        pass

    def _get_encoder(self):
        """動態取得本地神經模型陣列編碼器"""
        try:
            from zeronexus.brain.core import bio_brain
            if hasattr(bio_brain, "emotion_projector") and hasattr(bio_brain.emotion_projector, "neural_array"):
                return bio_brain.emotion_projector.neural_array
        except Exception:
            pass
        return None

    def encode_text(self, text: str) -> Optional[np.ndarray]:
        """將文本轉換為單位歸一化向量"""
        if not text or not text.strip():
            return None
        encoder = self._get_encoder()
        if encoder and hasattr(encoder, "encode_text"):
            try:
                emb = encoder.encode_text(text)
                if emb is not None:
                    return emb
            except Exception as e:
                log.warning(f"本地模型向量編碼失敗: {e}")

        # 備援：簡易特徵雜湊虛擬向量 (保持計算連續性與防崩潰)
        return self._fallback_hash_embedding(text)

    def _fallback_hash_embedding(self, text: str, dim: int = 128) -> np.ndarray:
        """輕量備援向量產生器：以字元 n-gram 進行雜湊映射"""
        vec = np.zeros(dim, dtype=np.float32)
        words = text.lower().strip()
        for i in range(len(words) - 1):
            gram = words[i : i + 2]
            idx = abs(hash(gram)) % dim
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 1e-6 else vec

    def compute_cosine_similarity(self, vec_a: Optional[np.ndarray], vec_b: Optional[np.ndarray]) -> float:
        """計算兩向量之餘弦相似度 [0.0 ~ 1.0]"""
        if vec_a is None or vec_b is None:
            return 0.0
        dot = float(np.dot(vec_a, vec_b))
        return max(0.0, min(1.0, (dot + 1.0) / 2.0))

    def compute_ebbinghaus_recency(self, created_at_ts: float, half_life_days: float = 7.0) -> float:
        """艾賓浩斯遺忘曲線時間加權：越近期回憶權重越高"""
        now = time.time()
        elapsed_seconds = max(0.0, now - created_at_ts)
        elapsed_days = elapsed_seconds / 86400.0
        # 衰減公式：2^(-t / half_life)
        return float(math.pow(2.0, -elapsed_days / half_life_days))

    def rank_memories(
        self,
        query: str,
        memories: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        對候選記憶條目進行多維度綜合語意評分並排序。

        候選記憶 dict 結構預期支援：
        - content 或 summary: 記憶文本
        - created_at: datetime 或 timestamp
        - importance: 重要度數值
        - emotion_tag: 情緒標籤
        """
        if not memories or not query.strip():
            return [(m, 0.5) for m in memories[:top_k]]

        query_vec = self.encode_text(query)
        scored: List[Tuple[Dict[str, Any], float]] = []

        for m in memories:
            text = m.get("content") or m.get("summary") or ""
            if not text:
                continue

            # 1. 語意相似度
            mem_vec = self.encode_text(text)
            sim_score = self.compute_cosine_similarity(query_vec, mem_vec)

            # 2. 時間衰減權重
            raw_time = m.get("created_at")
            if isinstance(raw_time, datetime):
                ts = raw_time.replace(tzinfo=timezone.utc).timestamp()
            elif isinstance(raw_time, (int, float)):
                ts = float(raw_time)
            else:
                ts = time.time()
            recency_score = self.compute_ebbinghaus_recency(ts)

            # 3. 重要性加權 (歸一化至 0.0 ~ 1.0)
            raw_imp = float(m.get("importance") or 1.0)
            imp_score = min(1.0, max(0.0, raw_imp / 5.0))

            # 4. 情緒標籤共振 (若有明顯情緒加成)
            emo = m.get("emotion_tag") or ""
            emo_score = 0.8 if (emo and emo != "平靜") else 0.4

            # 綜合相關性分數
            composite_score = (
                0.50 * sim_score
                + 0.25 * recency_score
                + 0.15 * imp_score
                + 0.10 * emo_score
            )
            scored.append((m, round(composite_score, 4)))

        # 依照綜合得分由大到小排序
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# 全域單例檢索器
semantic_memory_retriever = SemanticMemoryRetriever()
