"""ZeroNexus 本地生物大腦與情緒神經系統單元測試"""

import os
import shutil
import time
import unittest
from pathlib import Path

from zeronexus.brain import bio_brain
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

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_neuro_transmitters_and_homeostasis(self):
        """測試神經遞質更新與代謝衰減"""
        engine = NeuroTransmitterEngine(state_file=self.state_file)
        init_dopamine = engine.profile.dopamine

        # 刺激增加多巴胺
        engine.stimulate(user_id="user123", delta_dopamine=20.0, delta_oxytocin=5.0)
        self.assertGreater(engine.profile.dopamine, init_dopamine)
        self.assertGreater(engine.get_oxytocin("user123"), 25.0)

        # 模擬時間代謝衰減
        engine.profile.last_update_timestamp -= 3600  # 模擬經過 1 小時
        engine.apply_homeostasis_decay()
        # 多巴胺應向基準線 55.0 回落
        self.assertLess(engine.profile.dopamine, init_dopamine + 20.0)

    def test_high_dimensional_emotion_projector(self):
        """測試語意情緒幾何投影"""
        projector = HighDimensionalEmotionProjector()

        # 測試正面喜悅輸入
        res_joy = projector.analyze_text("今天發票中一千萬好爽啊哈哈哈哈太棒了！")
        self.assertEqual(res_joy.dominant_emotion, "喜悅")
        self.assertGreater(res_joy.valence, 0.5)
        self.assertGreater(res_joy.delta_dopamine, 0.0)

        # 測試委屈受挫輸入
        res_sad = projector.analyze_text("今天在學校被大家排擠罵了，心情好難過好委屈嗚嗚😭")
        self.assertEqual(res_sad.dominant_emotion, "悲傷")
        self.assertLess(res_sad.valence, -0.3)
        self.assertGreater(res_sad.delta_serotonin, 0.0)  # 觸發撫慰同理心

        # 測試惡意攻擊輸入
        res_attack = projector.analyze_text("你這爛機器人閉嘴啦白痴！")
        self.assertGreater(res_attack.delta_cortisol, 10.0)  # 皮質醇飆升

    def test_physics_parameter_modulation(self):
        """測試物理參數動態調製"""
        engine = NeuroTransmitterEngine(state_file=self.state_file)
        
        # 興奮狀態
        engine.profile.dopamine = 95.0
        engine.profile.energy = 90.0
        params_excited = PhysicsParameterModulator.modulate(engine.profile, user_bond=85.0)
        self.assertGreaterEqual(params_excited.temperature, 0.9)
        self.assertGreaterEqual(params_excited.top_p, 0.95)

        # 疲憊低精力狀態
        engine.profile.energy = 15.0
        engine.profile.dopamine = 40.0
        params_tired = PhysicsParameterModulator.modulate(engine.profile, user_bond=30.0)
        self.assertLessEqual(params_tired.max_tokens, 500)

    def test_memory_vault_encryption(self):
        """測試情節記憶儲存與心智日記 AES 加密解密"""
        vault = EncryptedMemoryVault(
            db_path=self.db_file,
            diary_dir=self.diary_dir,
            secret_key="TestSecretKey123!",
        )

        # 1. 寫入情節記憶
        ok = vault.record_memory(
            user_id="user_test",
            summary="Zero 提到他最喜歡喝冰美式咖啡",
            emotion_tag="喜悅",
            importance=4.0,
        )
        self.assertTrue(ok)
        mems = vault.retrieve_relevant_memories("user_test")
        self.assertEqual(len(mems), 1)
        self.assertIn("冰美式咖啡", mems[0].summary)

        # 2. 測試日記 AES-256 加密存儲與讀取
        diary_content = "2026-09-21: 今天和 Zero 聊了很多關於大腦的設計，我覺得他是一個很有熱忱的人。"
        saved = vault.save_conscious_diary("2026-09-21", diary_content)
        self.assertTrue(saved)

        # 檔案必須存在且不可為明文
        enc_file = self.diary_dir / "2026-09-21.enc"
        self.assertTrue(enc_file.exists())
        self.assertNotIn("冰美式咖啡".encode("utf-8"), enc_file.read_bytes())

        # 解密還原
        decrypted = vault.read_conscious_diary("2026-09-21")
        self.assertEqual(decrypted, diary_content)


if __name__ == "__main__":
    unittest.main()
