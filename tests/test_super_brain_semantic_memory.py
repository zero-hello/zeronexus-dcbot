"""ZeroNexus 超級大腦 - 語意向量長期記憶與遺忘曲線自動化測試。"""

import time
import pytest
import numpy as np
from zeronexus.brain.semantic_memory import semantic_memory_retriever


class TestSuperBrainSemanticMemorySuite:
    """測試本地向量編碼、餘弦相似度與多維記憶排序。"""

    def test_vector_encoding_and_similarity(self) -> None:
        """測試向量產生與餘弦相似度計算。"""
        v1 = semantic_memory_retriever.encode_text("我最喜歡吃拉麵和壽司")
        v2 = semantic_memory_retriever.encode_text("日本料理日式拉麵超好吃")
        v3 = semantic_memory_retriever.encode_text("今天伺服器資料庫重啟更新完畢")

        assert v1 is not None
        assert v2 is not None
        assert v3 is not None

        sim_related = semantic_memory_retriever.compute_cosine_similarity(v1, v2)
        sim_unrelated = semantic_memory_retriever.compute_cosine_similarity(v1, v3)

        # 飲食相關文字之相似度應明顯大於無關之伺服器維護文本
        assert sim_related > sim_unrelated

    def test_ebbinghaus_recency_decay(self) -> None:
        """測試艾賓浩斯遺忘曲線時間衰減。"""
        now = time.time()
        # 1 小時前
        r_recent = semantic_memory_retriever.compute_ebbinghaus_recency(now - 3600)
        # 7 天前 (半衰期)
        r_week = semantic_memory_retriever.compute_ebbinghaus_recency(now - 7 * 86400)
        # 30 天前
        r_month = semantic_memory_retriever.compute_ebbinghaus_recency(now - 30 * 86400)

        assert r_recent > r_week > r_month
        assert pytest.approx(r_week, abs=0.05) == 0.5

    def test_rank_memories(self) -> None:
        """測試綜合記憶多維度召回排序。"""
        now = time.time()
        candidates = [
            {
                "content": "使用者提過他平時主要使用 Python 與 PyTorch 進行深度學習",
                "created_at": now - 3600,
                "importance": 4.5,
                "emotion_tag": "喜悅",
            },
            {
                "content": "昨天伺服器文字頻道進行了日常維護通知",
                "created_at": now - 7200,
                "importance": 1.0,
                "emotion_tag": "平靜",
            },
            {
                "content": "使用者喜歡寫人工智慧演算法與神經網路",
                "created_at": now - 86400,
                "importance": 4.0,
                "emotion_tag": "期待",
            },
        ]

        query = "Python 機器學習與模型開發"
        ranked = semantic_memory_retriever.rank_memories(query, candidates, top_k=2)
        assert len(ranked) == 2
        # 最前面一筆應為 Python 深度學習相關記憶
        top_item, top_score = ranked[0]
        assert "Python" in top_item["content"]
        assert top_score > 0.6
