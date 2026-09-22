"""單元測試：情緒神經中樞三大升級（時間衰減動力學、原型正交化與餘弦校準、微調管線）"""

import math
import numpy as np
import pytest
from zeronexus.brain.emotion_projector import (
    EmotionAnalysisResult,
    HighDimensionalEmotionProjector,
    NeurotransmitterDynamics,
)
from zeronexus.brain.neural_models import (
    calibrate_prototype_projections,
    orthogonalize_prototypes,
)
from scripts.train_emotion_embedding import (
    BUILTIN_EMOTION_TRIPLETS,
    run_dry_run_validation,
)


class TestNeurotransmitterDynamics:
    """測試神經遞質時間衰減與滯後平滑動力學"""

    def test_decay_towards_baseline(self):
        """測試隨時間經過，偏離的神經遞質依指數規律回歸基準線"""
        dynamics = NeurotransmitterDynamics()
        # 人為設定較高的多巴胺水準
        dynamics.levels["dopamine"] = 0.90
        base_dopamine = dynamics.baselines["dopamine"]  # 0.5

        t0 = 1000.0
        dynamics.last_update_timestamp = t0

        # 經過 60 秒 (多巴胺半衰期為 60s)
        # 衰減公式：diff * 0.5 = 0.40 * 0.5 = 0.20 -> level 應接近 0.5 + 0.20 = 0.70
        levels, s_val, s_aro = dynamics.decay_and_update(
            impacts={},
            instant_valence=0.0,
            instant_arousal=0.3,
            current_time=t0 + 60.0,
        )

        assert abs(levels["dopamine"] - 0.70) < 0.05
        assert levels["dopamine"] < 0.90
        assert levels["dopamine"] > base_dopamine

    def test_hysteresis_damping(self):
        """測試滯後阻尼機制防止極端鋸齒狀跳變"""
        dynamics = NeurotransmitterDynamics(alpha=0.4)
        dynamics.smoothed_valence = 0.0
        dynamics.last_update_timestamp = 1000.0

        # 輸入極端正向 (+1.0)
        _, s_val1, _ = dynamics.decay_and_update(
            impacts={},
            instant_valence=1.0,
            instant_arousal=0.5,
            current_time=1001.0,
        )
        # 預期：0.0 * 0.6 + 1.0 * 0.4 = 0.4
        assert abs(s_val1 - 0.4) < 0.05

        # 下一秒立刻輸入極端負向 (-1.0)
        _, s_val2, _ = dynamics.decay_and_update(
            impacts={},
            instant_valence=-1.0,
            instant_arousal=0.5,
            current_time=1002.0,
        )
        # 預期：0.4 * 0.6 + (-1.0) * 0.4 = 0.24 - 0.4 = -0.16
        # 絕不直接跳到 -1.0
        assert abs(s_val2 - (-0.16)) < 0.05
        assert s_val2 > -0.5  # 驗證阻尼平滑效果顯著


class TestOrthogonalizationAndCalibration:
    """測試原型向量正交化與餘弦校準"""

    def test_orthogonalize_antagonistic_pairs(self):
        """測試對立情緒（喜悅 vs 悲傷）正交化後相似度顯著降低"""
        dim = 64
        rng = np.random.RandomState(42)

        # 構造兩個高度相似的對立原型向量（存在嚴重的語意空間沾黏）
        shared = rng.randn(dim)
        v_joy = shared + rng.randn(dim) * 0.2
        v_sad = shared + rng.randn(dim) * 0.2

        v_joy /= np.linalg.norm(v_joy)
        v_sad /= np.linalg.norm(v_sad)

        initial_sim = float(np.dot(v_joy, v_sad))
        assert initial_sim > 0.7  # 初始沾黏度極高

        prototypes = {"喜悅": v_joy, "悲傷": v_sad}
        ortho_protos = orthogonalize_prototypes(prototypes, decoupling_factor=0.9)

        ortho_sim = float(np.dot(ortho_protos["喜悅"], ortho_protos["悲傷"]))
        # 正交化後相似度應大幅下降
        assert ortho_sim < initial_sim
        assert ortho_sim < 0.2

    def test_calibrate_prototype_projections(self):
        """測試溫度縮放與閾值過濾凸顯主導情緒、壓制微弱雜訊"""
        raw_scores = {
            "喜悅": 0.58,
            "期待": 0.32,
            "悲傷": 0.12,  # 低於 0.15 閾值
            "厭惡": 0.08,  # 低於 0.15 閾值
        }

        calibrated = calibrate_prototype_projections(
            raw_scores,
            temperature=0.07,
            threshold=0.15,
        )

        # 低於 0.15 者應被完全過濾置零
        assert calibrated["悲傷"] == 0.0
        assert calibrated["厭惡"] == 0.0

        # 主導情緒「喜悅」與次要情緒「期待」的比值在校準後應被大幅拉開
        raw_ratio = raw_scores["喜悅"] / raw_scores["期待"]
        calibrated_ratio = calibrated["喜悅"] / (calibrated["期待"] + 1e-9)
        assert calibrated_ratio > raw_ratio
        assert calibrated["喜悅"] > 0.4


class TestEmotionProjectorIntegration:
    """測試情緒投影器完整整合流程"""

    def test_analyze_text_with_dynamics(self):
        """測試 analyze_text 回傳物件包含動態濃度與平滑數值"""
        projector = HighDimensionalEmotionProjector()
        res1 = projector.analyze_text("太棒了今天超開心的！好耶！")

        assert isinstance(res1, EmotionAnalysisResult)
        assert res1.dominant_emotion == "喜悅"
        assert res1.dynamics_levels is not None
        assert "dopamine" in res1.dynamics_levels
        assert "serotonin" in res1.dynamics_levels
        assert res1.valence > 0.0
        assert res1.raw_valence > 0.0

        # 連續輸入一句負向語句，驗證平滑未發生瞬間極端翻轉
        res2 = projector.analyze_text("好累好想哭喔...")
        assert res2.dominant_emotion == "悲傷"
        assert res2.raw_valence < 0.0
        # 平滑後的 valence 受前一次正向情緒影響，不至於驟降至極端負值
        assert res2.smoothed_valence > res2.raw_valence


class TestTrainingScriptDryRun:
    """測試微調腳本資料結構與驗證邏輯"""

    def test_builtin_triplets_validity(self):
        """驗證內建三元組涵蓋 8 大原色情緒且無缺漏欄位"""
        assert len(BUILTIN_EMOTION_TRIPLETS) >= 16
        emotions_covered = {t["emotion"] for t in BUILTIN_EMOTION_TRIPLETS}
        expected_emotions = {"喜悅", "悲傷", "信任", "厭惡", "恐懼", "憤怒", "驚訝", "期待"}
        assert expected_emotions.issubset(emotions_covered)

        for item in BUILTIN_EMOTION_TRIPLETS:
            assert len(item["anchor"].strip()) > 0
            assert len(item["positive"].strip()) > 0
            assert len(item["negative"].strip()) > 0

    def test_dry_run_executes_cleanly(self, capsys):
        """驗證 dry-run 函式能正常執行無異常"""
        run_dry_run_validation(BUILTIN_EMOTION_TRIPLETS, "/tmp/test_emotion_models")
        captured = capsys.readouterr()
        assert "總三元組樣本數" in captured.out
        assert "喜悅" in captured.out
