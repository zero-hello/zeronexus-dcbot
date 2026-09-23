"""ZeroNexus 超級大腦 - 仿生情緒、神經物理調製與羈絆測試。"""

import pytest
from zeronexus.brain.neuro_transmitters import NeuroChemicalProfile
from zeronexus.brain.physics_modulator import PhysicsParameterModulator
from zeronexus.brain.core import bio_brain


class TestSuperBrainEmpathySuite:
    """測試物理參數生成、情緒語氣指引與 Prompt 生理膠囊。"""

    def test_physics_modulation_dopamine_pulse(self) -> None:
        """測試多巴胺激增時的溫度與採樣多樣性提升。"""
        # 高多巴胺狀態
        p_high_dop = NeuroChemicalProfile(dopamine=90.0, serotonin=60.0, cortisol=10.0, energy=85.0)
        params = PhysicsParameterModulator.modulate(p_high_dop, user_bond=50.0)

        assert params.temperature >= 0.9
        assert params.top_p >= 0.95
        assert "多巴胺湧動" in params.emotional_tone_guidance

    def test_physics_modulation_cortisol_defense(self) -> None:
        """測試高皮質醇壓力防衛時的收斂性。"""
        p_stress = NeuroChemicalProfile(dopamine=30.0, serotonin=40.0, cortisol=75.0, energy=50.0)
        params = PhysicsParameterModulator.modulate(p_stress, user_bond=20.0)

        assert params.temperature < 0.7
        assert params.top_p <= 0.8
        assert "神經皮質醇偏高" in params.emotional_tone_guidance

    def test_prompt_capsule_includes_emotional_tone(self) -> None:
        """測試大腦輸出之生理膠囊包含情緒語氣呼吸感。"""
        capsule = bio_brain.get_prompt_capsule(user_id="test_user_999", user_name="小零")
        assert "當前神經情緒語氣呼吸感" in capsule
        assert "荷爾蒙指數" in capsule
