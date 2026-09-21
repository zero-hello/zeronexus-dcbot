"""ZeroNexus 本地生物大腦、三大神經模型陣列與心智系統單元測試"""

import os
import shutil
import time
import unittest
from pathlib import Path

from zeronexus.brain import bio_brain
from zeronexus.brain.circadian import CircadianRhythmEngine
from zeronexus.brain.attachment import PersonalAttachmentEngine
from zeronexus.brain.emotion_projector import HighDimensionalEmotionProjector
from zeronexus.brain.memory_vault import EncryptedMemoryVault
from zeronexus.brain.neuro_transmitters import NeuroTransmitterEngine
from zeronexus.brain.physics_modulator import PhysicsParameterModulator


class TestBioBrainSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("data/brain_test")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.test_dir / "test_neuro.json"
        self.db_file = self.test_dir / "test_memories.db"
        self.diary_dir = self.test_dir / "test_diary"
        self.dreams_dir = self.test_dir / "test_dreams"
        self.attachment_dir = self.test_dir / "test_attachment"

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_neuro_transmitters_and_homeostasis(self):
        """測試神經遞質更新與代謝衰減"""
        engine = NeuroTransmitterEngine(state_file=self.state_file)
        init_dopamine = engine.profile.dopamine

        engine.stimulate(user_id="user123", delta_dopamine=20.0, delta_oxytocin=5.0)
        self.assertGreater(engine.profile.dopamine, init_dopamine)
        self.assertGreater(engine.get_oxytocin("user123"), 25.0)

        engine.profile.last_update_timestamp -= 3600
        engine.apply_homeostasis_decay()
        self.assertLess(engine.profile.dopamine, init_dopamine + 20.0)

    def test_high_dimensional_emotion_projector(self):
        """測試語意情緒幾何投影與三大模型陣列"""
        projector = HighDimensionalEmotionProjector()

        res_joy = projector.analyze_text("今天發票中一千萬好爽啊哈哈哈哈太棒了！")
        self.assertEqual(res_joy.dominant_emotion, "喜悅")
        self.assertGreater(res_joy.valence, 0.4)
        self.assertGreater(res_joy.delta_dopamine, 0.0)

        res_sad = projector.analyze_text("今天在學校被大家排擠罵了，心情好難過好委屈嗚嗚😭")
        self.assertEqual(res_sad.dominant_emotion, "悲傷")
        self.assertLess(res_sad.valence, -0.3)
        self.assertGreater(res_sad.delta_serotonin, 0.0)

        res_attack = projector.analyze_text("你這爛機器人閉嘴啦白痴！")
        self.assertGreater(res_attack.delta_cortisol, 10.0)

    def test_circadian_and_dreaming(self):
        """測試晝夜生物時鐘與夢境重組生成"""
        circadian = CircadianRhythmEngine(dreams_dir=str(self.dreams_dir))
        phase = circadian.get_current_phase()
        self.assertIn("phase", phase)
        self.assertIn("micro_action", phase)

        dream = circadian.generate_and_save_dream(["白天一起吃好吃的拉麵"])
        self.assertIn("拉麵", dream["dream_content"])
        self.assertIn("setting", dream)

    def test_personal_attachment_radar(self):
        """測試專屬稱呼與飲食生活偏好萃取"""
        attachment = PersonalAttachmentEngine(data_dir=str(self.attachment_dir))
        profile = attachment.update_from_conversation(
            user_id="u_999",
            user_name="Zero",
            message_text="今天吃了麻辣鍋，完全不加香菜，喝去冰微糖無糖綠！叫我隊長就好！",
            oxytocin=65.0
        )
        self.assertEqual(profile.nickname, "隊長")
        self.assertIn("堅決不吃香菜", profile.dietary_preferences)
        self.assertIn("無辣不歡（超愛吃辣）", profile.dietary_preferences)
        capsule = attachment.get_prompt_capsule("u_999", oxytocin=65.0)
        self.assertIn("隊長", capsule)
        self.assertIn("不吃香菜", capsule)

    def test_memory_vault_encryption(self):
        """測試情節記憶儲存與心智日記 AES 加密解密"""
        vault = EncryptedMemoryVault(
            db_path=self.db_file,
            diary_dir=self.diary_dir,
            secret_key="TestSecretKey123!",
        )

        ok = vault.record_memory(
            user_id="user_test",
            summary="Zero 提到他最喜歡喝冰美式咖啡",
            emotion_tag="喜悅",
            importance=4.0,
        )
        self.assertTrue(ok)
        mems = vault.retrieve_relevant_memories("user_test")
        self.assertEqual(len(mems), 1)

        diary_content = "2026-09-21: 今天和 Zero 聊了很多關於大腦的設計，很有熱忱。"
        saved = vault.save_conscious_diary("2026-09-21", diary_content)
        self.assertTrue(saved)

        decrypted = vault.read_conscious_diary("2026-09-21")
        self.assertEqual(decrypted, diary_content)


if __name__ == "__main__":
    unittest.main()
