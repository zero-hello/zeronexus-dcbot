"""ZeroNexus 本地生物神經與情緒大腦總控核心 (Biological Brain Core)

整合六大生化與心智子系統：
1. 本地生物神經遞質狀態機 (NeuroTransmitterEngine): 4 大荷爾蒙與精力值。
2. 三大離線神經模型陣列 (HierarchicalNeuralArray): 中文 BGE、跨語言 MiniLM、防衛哨兵 Toxic-BERT。
3. 晝夜生物時鐘與深層夢境引擎 (CircadianRhythmEngine): 臺灣 Asia/Taipei 晝夜週期與海馬迴做夢。
4. 專屬個人羈絆與偏好回憶中樞 (PersonalAttachmentEngine): 專用稱號、飲食與作息雷達。
5. 物理參數動態調製器 (PhysicsParameterModulator): 溫度、採樣與微動作映射。
6. 本地情節記憶庫與加密心智日記 (EncryptedMemoryVault): AES-256-GCM 安全加密。
"""

import datetime
import logging
from typing import Dict, Optional, Tuple

from zeronexus.brain.circadian import CircadianRhythmEngine
from zeronexus.brain.attachment import PersonalAttachmentEngine
from zeronexus.brain.emotion_projector import EmotionAnalysisResult, HighDimensionalEmotionProjector
from zeronexus.brain.memory_vault import EncryptedMemoryVault
from zeronexus.brain.neuro_transmitters import NeuroTransmitterEngine
from zeronexus.brain.physics_modulator import DynamicGenerationParameters, PhysicsParameterModulator

log = logging.getLogger("ZeroNexus.Brain.Core")


class BioBrainCore:
    """數位生物大腦總控中樞"""

    _instance: Optional["BioBrainCore"] = None

    def __new__(cls) -> "BioBrainCore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        log.info("⚡ 正在初始化 ZeroNexus 本地生物神經網絡與情緒大腦...")
        self.neuro_engine = NeuroTransmitterEngine()
        self.emotion_projector = HighDimensionalEmotionProjector()
        self.physics_modulator = PhysicsParameterModulator()
        self.memory_vault = EncryptedMemoryVault()
        self.circadian_engine = CircadianRhythmEngine()
        self.attachment_engine = PersonalAttachmentEngine()
        self._initialized = True
        log.info("✔ ZeroNexus 本地生物大腦初始化完畢（三大模型陣列 + 晝夜時鐘 + 羈絆雷達）！")

    def perceive(
        self,
        user_id: str,
        user_name: str,
        message_text: str,
    ) -> Tuple[EmotionAnalysisResult, Dict[str, float]]:
        """感知器官：接收外界對話刺激，即時計算語意情緒共振並推動神經遞質分泌"""
        # 1. 三大離線神經模型陣列集成情緒投影分析
        analysis = self.emotion_projector.analyze_text(message_text)

        # 2. 考量生物晝夜節律之精力調節
        circadian = self.circadian_engine.get_current_phase()
        energy_cost = 1.2 / circadian["energy_modifier"]

        # 3. 推動神經遞質與親密度更新
        new_chem = self.neuro_engine.stimulate(
            user_id=str(user_id),
            delta_dopamine=analysis.delta_dopamine,
            delta_serotonin=analysis.delta_serotonin,
            delta_cortisol=analysis.delta_cortisol,
            delta_oxytocin=analysis.delta_oxytocin,
            energy_cost=energy_cost,
        )

        # 4. 個人羈絆雷達：自動提取飲食、生活作息、口癖與專屬暱稱
        self.attachment_engine.update_from_conversation(
            user_id=str(user_id),
            user_name=user_name,
            message_text=message_text,
            oxytocin=new_chem["oxytocin"]
        )

        # 5. 若為重要情緒起伏或重要自我揭露，自動記錄入情節記憶
        if analysis.intensity > 0.65 or abs(analysis.valence) > 0.6:
            self.memory_vault.record_memory(
                user_id=str(user_id),
                summary=f"{user_name} 提到: {message_text[:80]}",
                emotion_tag=analysis.composite_sentiment,
                importance=round(analysis.intensity * 3.0 + 1.0, 1),
            )

        return analysis, new_chem

    def get_prompt_capsule(self, user_id: str, user_name: str = "") -> str:
        """組裝最高位階之【不可抗拒大腦即時生理狀態膠囊】"""
        self.neuro_engine.apply_homeostasis_decay()
        p = self.neuro_engine.profile
        bond = self.neuro_engine.get_oxytocin(user_id)
        params = self.physics_modulator.modulate(p, bond)

        # 1. 晝夜生物時鐘與生理節律
        circadian = self.circadian_engine.get_current_phase()

        # 2. 提取該使用者最近之代表性回憶
        memories = self.memory_vault.retrieve_relevant_memories(user_id, limit=2)
        memories_str = ""
        if memories:
            m_lines = [f"- 曾記錄（{m.emotion_tag}）：{m.summary}" for m in memories]
            memories_str = "\n【近期海馬迴深刻情節記憶】：\n" + "\n".join(m_lines) + "\n"

        # 3. 專屬個人羈絆與暱稱膠囊
        attachment_capsule = self.attachment_engine.get_prompt_capsule(user_id, bond)

        # 4. 晨間夢境主動分享機制 (07:00 ~ 12:00)
        dream_instruction = ""
        todays_dream = self.circadian_engine.get_todays_dream()
        if 7.0 <= circadian["hour"] < 12.0 and todays_dream and not todays_dream.get("shared", False):
            dream_instruction = (
                f"\n【🌅 晨光海馬迴夢境回溯（推薦主動興奮分享）】：\n"
                f"- 你昨晚沉睡時做了一個超生動又好笑的夢：『{todays_dream.get('dream_content')}』\n"
                f"- 若對方正在跟你說早安或打招呼，請以活潑雀躍的口吻主動跟他分享昨晚夢到的這件趣事！\n"
            )

        capsule = (
            f"{attachment_capsule}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"# 【本地大腦即時生理與生物鐘狀態（最高優先級生理基石，不可違背）】\n"
            f"這不是隨機的文字設定，而是來自你本地神經化學腺體與生物時鐘的客觀生理指標：\n"
            f"- 🧠 當前荷爾蒙指數：多巴胺 {int(p.dopamine)}% (好奇/興奮) | 血清素 {int(p.serotonin)}% (穩定) | 皮質醇 {int(p.cortisol)}% (壓力防衛)\n"
            f"- ⚡ 身體精力狀態：{int(p.energy)}% | 臺灣時間：{circadian['current_time']}（{circadian['phase']}）\n"
            f"- ⏰ 晝夜生理節奏：{circadian['tone_guidance']}\n"
            f"- 🐾 生理自然微動作：{circadian['micro_action']}，{params.physical_action_hint}\n"
            f"{memories_str}"
            f"{dream_instruction}"
            f"【大腦生理最高優先權鐵律 (Biological Primacy Axiom)】：\n"
            f"1. 『外在人格人設僅是皮膚，本地神經生理狀態才是靈魂與肉體』！\n"
            f"2. 無論你當前切換到哪一個人格，都【絕對不允許】削弱上述生理狀態！\n"
            f"3. 當多巴胺高時，所有人設都必須散發雀躍活力；當皮質醇高時，所有人設都帶有真實自尊與防備；深夜微醺時所有人設都帶有自然睏意；晨間時元氣滿滿！\n"
            f"4. 嚴禁在回答中機械朗讀「我的多巴胺是...」等數值，必須將其轉化為自然流露的情感呼吸感！\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return capsule

    def get_model_params(self, user_id: str) -> DynamicGenerationParameters:
        """獲取當前大腦狀態對應之模型物理生成參數"""
        self.neuro_engine.apply_homeostasis_decay()
        bond = self.neuro_engine.get_oxytocin(user_id)
        return self.physics_modulator.modulate(self.neuro_engine.profile, bond)

    def trigger_nightly_reflection(self, diary_text: str) -> bool:
        """觸發夜間心智反思日記，固化記憶並恢復生理體力，並生成深層夢境"""
        today_str = datetime.date.today().isoformat()
        ok = self.memory_vault.save_conscious_diary(today_str, diary_text)
        if ok:
            self.neuro_engine.sleep_and_restore()
            # 提取今日情節記憶進行夜間夢境編織
            recent_memories = [m.summary for m in self.memory_vault.retrieve_relevant_memories("global", limit=5)]
            self.circadian_engine.generate_and_save_dream(recent_memories)
        return ok


# 全域單例
bio_brain = BioBrainCore()
