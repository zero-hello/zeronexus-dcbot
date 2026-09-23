"""ZeroNexus 超級大腦 - MCTS 認知推理推導自動化測試。"""

import pytest
from zeronexus.intelligence.thought_search_mcts import thought_search_engine
from zeronexus.intelligence.deep_thinking_controller import deep_thinking_controller


class TestSuperBrainMCTSSuite:
    """測試蒙地卡羅思維樹深度推導。"""

    def test_high_complexity_detection(self) -> None:
        """測試高複雜度命題自動辨識。"""
        assert thought_search_engine.is_high_complexity_problem("請比較 Python 與 Rust 在並發設計上的優缺點與 Trade-off")
        assert thought_search_engine.is_high_complexity_problem("為什麼這裡會發生記憶體洩漏與死鎖？背後原理是什麼")
        assert thought_search_engine.is_high_complexity_problem("請證明根號2是無理數並給出推導步驟")
        # 簡單日常問候不應被判斷為高複雜度
        assert not thought_search_engine.is_high_complexity_problem("哈囉你好")
        assert not thought_search_engine.is_high_complexity_problem("早安！")

    def test_mcts_search_and_skeleton(self) -> None:
        """測試 MCTS 搜尋路徑生成與骨架輸出。"""
        problem = "如何設計一個高併發的分散式快取架構？"
        path, confidence = thought_search_engine.search_optimal_reasoning_path(problem)
        assert len(path) > 0
        assert 0.0 <= confidence <= 1.0

        # 驗證步驟結構
        first_step = path[0]
        assert "step" in first_step
        assert "action" in first_step
        assert "coherence" in first_step

        # 驗證思維導引骨架格式
        skeleton = thought_search_engine.generate_deliberation_skeleton(problem)
        assert skeleton is not None
        assert "【ZeroNexus 認知中樞蒙地卡羅思維推導導引" in skeleton
        assert "核心命題探勘置信度" in skeleton

    def test_deep_thinking_controller_deliberate(self) -> None:
        """測試深度思考控制器的自適應推導。"""
        complex_q = "請分析微服務架構在跨資料庫交易時的一致性演算法與最佳實踐"
        skeleton = deep_thinking_controller.deliberate_query(complex_q)
        assert skeleton is not None
        assert "推導要求" in skeleton

        simple_q = "安安"
        assert deep_thinking_controller.deliberate_query(simple_q) is None
