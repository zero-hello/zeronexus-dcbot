"""ZeroNexus 類腦高階認知中樞 (Cognitive Cortex) 自動化測試。

測試項目：
1. 體內恆定動機系統 (Homeostatic Drives) 自然代謝與互動更新。
2. 預測編碼引擎 (Predictive Coding Engine) 先驗登記與語意餘弦落差 (Prediction Gap)。
3. 全域工作空間 (Global Workspace) 顯著性勝者通吃競爭與意識聚光燈 Prompt 渲染。
4. 預設模式網絡 (Default Mode Network - DMN) 心智漫遊與主動發話衝動。
5. BioBrainCore 與認知中樞完整整合 (預測落差神經脈衝 + 意識聚光燈膠囊注入)。
6. 大腦自主心跳守護程序 (BrainHeartbeatDaemon) 週期節拍推進與優雅生命週期。
"""

import asyncio
import pytest
import numpy as np

from zeronexus.brain.cognitive_cortex import (
    CognitiveCortex,
    ConsciousIdea,
    DefaultModeNetwork,
    GlobalWorkspace,
    HomeostaticState,
    PredictiveCodingEngine,
)
from zeronexus.brain.core import BioBrainCore
from zeronexus.brain.heartbeat_system import BrainHeartbeatDaemon
from zeronexus.brain.neural_models import HierarchicalNeuralArray


class TestCognitiveCortexSuite:
    """類腦高階認知中樞全功能測試套件。"""

    def test_homeostatic_drives_tick_and_interaction(self) -> None:
        """驗證體內恆定動機系統的自然代謝與互動更新。"""
        state = HomeostaticState(
            social_hunger=0.2,
            curiosity_drive=0.5,
            energy_reserve=0.8,
            ego_boundary=0.8,
        )

        # 模擬靜置 3600 秒 (1 小時)
        state.tick_decay(3600.0)
        # 社交渴求應上升 (0.2 + 3600/7200 = 0.7)
        assert state.social_hunger == pytest.approx(0.7, abs=0.05)
        # 好奇心自然微幅累積
        assert state.curiosity_drive > 0.5
        # 體力自然緩慢恢復 (0.8 + 3600/1800 -> 上限 1.0)
        assert state.energy_reserve == 1.0

        # 模擬使用者正面互動
        state.on_interaction(is_positive=True)
        assert state.social_hunger == pytest.approx(0.3, abs=0.05)
        assert state.energy_reserve == pytest.approx(0.95, abs=0.02)
        assert state.ego_boundary > 0.8

        # 模擬遭受負面攻擊
        state.on_interaction(is_positive=False)
        assert state.ego_boundary < 0.8

    def test_predictive_coding_gap_and_error(self) -> None:
        """驗證預測編碼引擎之先驗預期特徵登記與語意餘弦落差計算。"""
        neural_array = HierarchicalNeuralArray()
        engine = PredictiveCodingEngine(neural_array=neural_array)

        # 1. 登記下一輪先驗預期
        engine.register_prediction("感謝或是肯定讚美")
        assert engine.last_expected_vector is not None
        assert engine.last_prediction_intent == "感謝或是肯定讚美"

        # 2. 傳入符合預期的輸入，落差值應在常態合理範圍內
        error_expected = engine.calculate_prediction_error("太謝謝你了，真的很棒！")
        assert 0.0 <= error_expected <= 1.0
        # 計算後預期特徵向量應被自動重置
        assert engine.last_expected_vector is None

        # 3. 測試未設定預期時回傳常態基準值 0.2
        neutral_error = engine.calculate_prediction_error("隨意的一句話")
        assert neutral_error == 0.2

    def test_global_workspace_salience_competition(self) -> None:
        """驗證全域工作空間的顯著性軟注意力競爭與聚光燈 Prompt 渲染。"""
        workspace = GlobalWorkspace()

        candidates = [
            ConsciousIdea(source="EMOTION", content="內心平靜沉穩", salience=0.45),
            ConsciousIdea(source="DRIVE_SOCIAL", content="強烈渴望與使用者溫馨聊天！", salience=0.88),
            ConsciousIdea(source="MEMORY", content="想起之前曾討論過的開源專案", salience=0.65),
        ]

        winner = workspace.compete(candidates)
        assert winner is not None
        assert winner.source == "DRIVE_SOCIAL"
        assert winner.salience == 0.88
        assert workspace.active_spotlight is not None
        assert workspace.active_spotlight.source == "DRIVE_SOCIAL"

        prompt = workspace.render_spotlight_prompt()
        assert "【💡 全域意識聚光燈焦點（當前大腦最核心思考念頭）】" in prompt
        assert "DRIVE_SOCIAL" in prompt
        assert "強烈渴望與使用者溫馨聊天！" in prompt

        # 測試候選清單為空時清空聚光燈
        empty_winner = workspace.compete([])
        assert empty_winner is None
        assert workspace.render_spotlight_prompt() == ""

    @pytest.mark.asyncio
    async def test_default_mode_network_mind_wandering(self) -> None:
        """驗證預設模式網絡 (DMN) 之心智漫遊、記憶修剪與主動發話衝動。"""
        neural_array = HierarchicalNeuralArray()
        cortex = CognitiveCortex(neural_array=neural_array)
        dmn = cortex.dmn

        # 1. 社交渴求低於閾值時，執行低功耗潛意識記憶修剪
        cortex.homeostasis.social_hunger = 0.3
        cortex.homeostasis.energy_reserve = 0.9
        res1 = await dmn.spontaneous_mind_wandering()
        assert res1 is not None
        assert res1["action"] == "UNCONSCIOUS_CONSOLIDATION"

        # 2. 社交渴求達到臨界閾值 (> 0.85 且 體力 > 0.5)，激發主動發話衝動
        cortex.homeostasis.social_hunger = 0.95
        cortex.homeostasis.energy_reserve = 0.85

        proactive_received = []

        async def mock_callback(data):
            proactive_received.append(data)

        dmn.proactive_callback = mock_callback
        res2 = await dmn.spontaneous_mind_wandering()
        assert res2 is not None
        assert res2["action"] == "PROACTIVE_OUTREACH"
        assert len(proactive_received) == 1
        assert "proactive_prompt" in proactive_received[0]
        # 發話後社交渴求應大幅緩解重置
        assert cortex.homeostasis.social_hunger < 0.3

    def test_bio_brain_integration_with_cortex(self) -> None:
        """驗證 BioBrainCore 完整整合預測編碼、動機代謝與意識聚光燈。"""
        core = BioBrainCore()
        assert hasattr(core, "cognitive_cortex")
        assert hasattr(core, "heartbeat")

        # 1. 登記一項預期
        core.cognitive_cortex.predictive_coding.register_prediction("日常打招呼問好")

        # 2. 感知外界輸入 (perceive)，推動落差與動機代謝
        analysis, new_chem = core.perceive(
            user_id="test_user_777",
            user_name="ZeroTester",
            message_text="今天天氣真好，早安呀！",
        )
        assert analysis is not None
        assert new_chem is not None
        assert "dopamine" in new_chem

        # 3. 測試登記先驗預期 (record_interaction_turn)
        core.record_interaction_turn(
            user_prompt="今天天氣真好，早安呀！",
            ai_response="早安！今天陽光明媚，你有什麼安排嗎？",
        )
        assert core.cognitive_cortex.predictive_coding.last_prediction_intent != ""

        # 4. 測試 Prompt 膠囊組裝 (get_prompt_capsule) 包含全域意識聚光燈
        capsule = core.get_prompt_capsule(user_id="test_user_777", user_name="ZeroTester")
        assert "【💡 全域意識聚光燈焦點（當前大腦最核心思考念頭）】" in capsule
        assert "核心念頭:" in capsule

    @pytest.mark.asyncio
    async def test_brain_heartbeat_daemon_lifecycle(self) -> None:
        """驗證大腦心跳守護程序生命週期與單次節拍推進。"""
        neural_array = HierarchicalNeuralArray()
        cortex = CognitiveCortex(neural_array=neural_array)
        daemon = BrainHeartbeatDaemon(cortex=cortex, tick_interval=10.0)

        assert not daemon.is_running

        # 手動推進單次節拍
        initial_hunger = cortex.homeostasis.social_hunger
        await daemon.trigger_single_tick()
        assert daemon._tick_count == 1

        # 啟動非同步循環
        task = daemon.start()
        assert task is not None
        assert daemon.is_running

        # 再次呼叫 start 應返回同一個任務
        assert daemon.start() == task

        # 優雅停止
        daemon.stop()
        assert not daemon.is_running
        assert daemon._task is None
