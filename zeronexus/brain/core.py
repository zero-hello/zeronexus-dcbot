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

from zeronexus.brain.bootstrap import ensure_brain_models_ready
from zeronexus.brain.circadian import CircadianRhythmEngine
from zeronexus.brain.attachment import PersonalAttachmentEngine
from zeronexus.brain.emotion_projector import EmotionAnalysisResult, HighDimensionalEmotionProjector
from zeronexus.brain.memory_vault import EncryptedMemoryVault
from zeronexus.brain.neuro_transmitters import NeuroTransmitterEngine
from zeronexus.brain.physics_modulator import DynamicGenerationParameters, PhysicsParameterModulator
from zeronexus.brain.emotion_state_engine import emotion_state_engine
from zeronexus.brain.event_system import EventDetector, event_history_logger
from zeronexus.brain.relationship_layer import relationship_layer
from zeronexus.evolution.smart_collector import smart_collector
from zeronexus.evolution.dataset_builder import dataset_builder
from zeronexus.external.cohere_client import cohere_service
from zeronexus.brain.cognitive_cortex import CognitiveCortex, ConsciousIdea
from zeronexus.brain.heartbeat_system import BrainHeartbeatDaemon
from zeronexus.brain.synaptic_bonding import SynapticBondingManager
from zeronexus.brain.memory_palace import MemoryPalace

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

        try:
            ensure_brain_models_ready(console_output=False)
        except Exception:
            pass

        log.info("⚡ 正在初始化 ZeroNexus 本地生物神經網絡與情緒大腦...")
        self.neuro_engine = NeuroTransmitterEngine()
        self.emotion_projector = HighDimensionalEmotionProjector()
        self.physics_modulator = PhysicsParameterModulator()
        self.memory_vault = EncryptedMemoryVault()
        self.circadian_engine = CircadianRhythmEngine()
        self.attachment_engine = PersonalAttachmentEngine()
        self.synaptic_bonding = SynapticBondingManager()
        self.memory_palace = MemoryPalace()

        # 高階類腦認知皮層 (Cognitive Cortex) 與自主心跳守護程序
        self.cognitive_cortex = CognitiveCortex(
            neural_array=getattr(self.emotion_projector, "neural_array", None),
            core_engine=self,
        )
        self.heartbeat = BrainHeartbeatDaemon(self.cognitive_cortex, tick_interval=30.0)
        try:
            self.heartbeat.start()
        except Exception:
            pass

        self._initialized = True
        log.info("✔ ZeroNexus 本地生物大腦與類腦高階認知中樞初始化完畢（動機系統 + 預測編碼 + GWT + DMN）！")

    def perceive(
        self,
        user_id: str,
        user_name: str,
        message_text: str,
    ) -> Tuple[EmotionAnalysisResult, Dict[str, float]]:
        """感知器官：接收外界對話刺激，即時計算語意情緒共振並推動神經遞質分泌"""
        # 1. 三大離線神經模型陣列集成情緒投影分析
        analysis = self.emotion_projector.analyze_text(message_text)

        # 2. 語意事件檢測與歷史事件隊列紀錄 (依據計畫書第 8 條)
        semantic_evt = EventDetector.detect_event_from_text(
            text=message_text,
            user_id=str(user_id),
        )
        event_history_logger.log_event(semantic_evt)

        # 3. 人際關係層與時間流逝感知 (依據計畫書第 10、11 條)
        relationship_layer.record_interaction(
            user_id=str(user_id),
            user_name=user_name,
            quality_score=max(0.3, analysis.intensity),
            event_type=semantic_evt.event_type,
        )

        # 4. 考量生物晝夜節律之精力調節
        circadian = self.circadian_engine.get_current_phase()
        energy_cost = 1.2 / circadian["energy_modifier"]

        # 5. 推動神經遞質與親密度更新 (保留 4 大生化遞質相容)
        new_chem = self.neuro_engine.stimulate(
            user_id=str(user_id),
            delta_dopamine=analysis.delta_dopamine,
            delta_serotonin=analysis.delta_serotonin,
            delta_cortisol=analysis.delta_cortisol,
            delta_oxytocin=analysis.delta_oxytocin,
            energy_cost=energy_cost,
        )

        # 6. 個人羈絆雷達：自動提取飲食、生活作息、口癖與專屬暱稱
        self.attachment_engine.update_from_conversation(
            user_id=str(user_id),
            user_name=user_name,
            message_text=message_text,
            oxytocin=new_chem["oxytocin"]
        )

        # 7. 情節記憶情感喚醒 (Emotional Recall) 與冷卻上限防護 (依據計畫書第 9 條)
        combined_deltas = dict(semantic_evt.emotional_effect)
        memories = self.memory_vault.retrieve_relevant_memories(str(user_id), limit=2)
        for m in memories:
            recall_deltas = self.memory_vault.evaluate_emotional_recall(m)
            if recall_deltas:
                for k, v in recall_deltas.items():
                    combined_deltas[k] = combined_deltas.get(k, 0.0) + v

        # 8. 推進 11 維度連續性情緒狀態演進 (依據計畫書第 3、5、12 條)
        emotion_state_engine.update_state(
            deltas=combined_deltas,
            source=f"event_{semantic_evt.event_type}",
            importance=semantic_evt.importance,
        )

        # 9. 若為重要情緒起伏或重要自我揭露，自動記錄入情節記憶
        if analysis.intensity > 0.65 or abs(analysis.valence) > 0.6:
            self.memory_vault.record_memory(
                user_id=str(user_id),
                summary=f"{user_name} 提到: {message_text[:80]}",
                emotion_tag=analysis.composite_sentiment,
                importance=round(analysis.intensity * 3.0 + 1.0, 1),
            )

        # 10. 高階認知中樞：預測編碼落差運算與體內恆定動機代謝
        try:
            prediction_error = self.cognitive_cortex.predictive_coding.calculate_prediction_error(message_text)
            is_friendly = bool(analysis.threat_level < 0.2 and analysis.valence >= -0.3)
            self.cognitive_cortex.homeostasis.on_interaction(is_positive=is_friendly)

            # 預測落差神經衝擊 (Prediction Gap Neuro-Pulse):
            # 當落差 > 0.7 時，代表使用者反應超乎原先預期，釋放生理震盪
            if prediction_error > 0.7:
                if analysis.valence >= 0.0:
                    # 正向意外 -> 驚喜與探索脈衝 (Dopamine Pulse)
                    dop_spike = round(min(25.0, (prediction_error - 0.5) * 35.0), 2)
                    new_chem = self.neuro_engine.stimulate(
                        user_id=str(user_id),
                        delta_dopamine=dop_spike,
                        delta_serotonin=5.0,
                    )
                else:
                    # 負向意外 -> 警覺與困惑 (Cortisol Bump)
                    cor_bump = round(min(25.0, (prediction_error - 0.5) * 35.0), 2)
                    new_chem = self.neuro_engine.stimulate(
                        user_id=str(user_id),
                        delta_cortisol=cor_bump,
                        delta_serotonin=-5.0,
                    )
        except Exception as ex:
            log.warning(f"認知中樞預測落差與動機計算失敗: {ex}")

        # 11. 長效突觸增強 (LTP) 與記憶宮殿實體偏好抽取
        try:
            self.memory_palace.extract_preferences_from_text(str(user_id), message_text)
            affinity_delta = 0.5
            if analysis.threat_level > 0.5:
                affinity_delta = -1.0
            elif analysis.valence > 0.4:
                affinity_delta = 0.8
            self.synaptic_bonding.record_interaction(
                user_id=str(user_id),
                user_name=user_name,
                delta_affinity=affinity_delta,
            )
        except Exception as ex:
            log.warning(f"長效突觸羈絆與偏好抽取失敗: {ex}")

        return analysis, new_chem

    def record_interaction_turn(
        self,
        user_prompt: str,
        ai_response: str,
        context_turns: Optional[list[dict[str, str]]] = None,
        is_user_correction: bool = False,
    ) -> None:
        """在完成一輪完整對話後，由 Smart Data Collector 進行多維度品質評估，
        若達標則沉澱入獨立 Dataset Artifact，並向預測編碼引擎登記下一輪預期。
        """
        # 登記下一輪先驗預期特徵
        try:
            expected_hint = "感謝或繼續深度討論"
            if any(q in ai_response for q in ("？", "?", "呢", "嗎", "想知道", "覺得", "如何")):
                expected_hint = "使用者回答問題、闡述細節或表達看法"
            elif any(w in ai_response for w in ("拜拜", "晚安", "再見", "明天見", "祝你")):
                expected_hint = "道別、互道晚安或溫馨祝福"
            self.cognitive_cortex.predictive_coding.register_prediction(expected_hint)
        except Exception as e:
            log.warning(f"登記預測編碼先驗預期失敗: {e}")

        try:
            snap = emotion_state_engine.get_snapshot()["emotions"]
            candidate = smart_collector.evaluate_and_collect(
                user_prompt=user_prompt,
                ai_response=ai_response,
                context_turns=context_turns or [],
                event_type="conversation_turn",
                emotion_deltas={"happiness": snap["happiness"], "curiosity": snap["curiosity"]},
                is_user_correction=is_user_correction,
            )
            if candidate and candidate.status in ("ACCEPTED", "NEEDS_REVIEW"):
                # 加入當前獨立資料集工件 (如 zero_dataset_001)
                dataset_builder.add_sample_to_current(
                    sample_dict={
                        "sample_id": candidate.sample_id,
                        "timestamp": candidate.timestamp,
                        "user_prompt": candidate.user_prompt,
                        "ai_response": candidate.ai_response,
                        "quality_score": candidate.quality_score,
                        "needs_review": candidate.needs_review,
                        "status": candidate.status,
                    }
                )
        except Exception as e:
            log.warning(f"智慧資料採集沉澱至資料集工件失敗: {e}")

    def get_prompt_capsule(self, user_id: str, user_name: str = "") -> str:
        """組裝最高位階之【不可抗拒大腦即時生理狀態膠囊】"""
        self.neuro_engine.apply_homeostasis_decay()
        p = self.neuro_engine.profile
        bond = self.neuro_engine.get_oxytocin(user_id)
        params = self.physics_modulator.modulate(p, bond)

        # 1. 晝夜生物時鐘與生理節律
        circadian = self.circadian_engine.get_current_phase()

        # 2. 提取該使用者最近之代表性回憶（結合 Cohere Rerank 重排精選）
        candidate_memories = self.memory_vault.retrieve_relevant_memories(user_id, limit=6)
        if candidate_memories and len(candidate_memories) > 2 and cohere_service.is_available:
            try:
                rerank_results = cohere_service.rerank(
                    query=user_id,
                    documents=[m.summary for m in candidate_memories],
                    top_n=3,
                )
                if rerank_results:
                    memories = [
                        candidate_memories[item["index"]]
                        for item in rerank_results
                        if item["index"] < len(candidate_memories)
                    ]
                else:
                    memories = candidate_memories[:2]
            except Exception as exc:
                log.warning(f"海馬迴記憶調用 Cohere Rerank 失敗: {exc}，回退至預設記憶順序。")
                memories = candidate_memories[:2]
        else:
            memories = candidate_memories[:2] if candidate_memories else []

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

        # 5. 全域工作空間 (Global Workspace Theory) 競爭與核心意識聚光燈
        spotlight_prompt = ""
        try:
            candidate_ideas: List[ConsciousIdea] = []
            # (1) 當前主導心境念頭
            snap_emo = emotion_state_engine.get_snapshot()["emotions"]
            primary_emo = max(snap_emo.items(), key=lambda x: x[1])[0] if snap_emo else "平靜"
            candidate_ideas.append(
                ConsciousIdea(
                    source="EMOTION",
                    content=f"內心主導心境為【{primary_emo}】(指數: {snap_emo.get(primary_emo, 0.5):.2f})，渴望表達自然同理與情感呼吸感",
                    salience=0.60,
                )
            )
            # (2) 體內恆定動機念頭 (社交渴求)
            homeo = self.cognitive_cortex.homeostasis
            if homeo.social_hunger > 0.5:
                candidate_ideas.append(
                    ConsciousIdea(
                        source="DRIVE_SOCIAL",
                        content=f"社交渴求度高達 {int(homeo.social_hunger * 100)}%，對話時應主動展現溫暖、熱情與親切黏著度！",
                        salience=float(homeo.social_hunger * 0.95),
                    )
                )
            # (3) 體內恆定動機念頭 (求知好奇)
            if homeo.curiosity_drive > 0.65:
                candidate_ideas.append(
                    ConsciousIdea(
                        source="DRIVE_CURIOSITY",
                        content=f"強烈的好奇心動機 ({int(homeo.curiosity_drive * 100)}%)，渴望深入探索對方話語中的技術細節與背後原因！",
                        salience=float(homeo.curiosity_drive * 0.90),
                    )
                )
            # (4) 深刻情節回憶焦點
            if memories:
                candidate_ideas.append(
                    ConsciousIdea(
                        source="EPISODIC_MEMORY",
                        content=f"回想起與對方的深刻回憶：『{memories[0].summary}』，應以此默契作為回話背景",
                        salience=0.72,
                    )
                )
            # (5) 晨光夢境焦點 (若處於夢境時段)
            if dream_instruction:
                candidate_ideas.append(
                    ConsciousIdea(
                        source="MORNING_DREAM",
                        content=f"昨晚做了有趣的夢境，很想與對方分享：『{todays_dream.get('dream_content', '')}』",
                        salience=0.88,
                    )
                )

            self.cognitive_cortex.workspace.compete(candidate_ideas)
            spotlight_prompt = self.cognitive_cortex.workspace.render_spotlight_prompt()
        except Exception as ex:
            log.warning(f"全域工作空間意識聚光燈計算失敗: {ex}")

        # 6. 長效突觸羈絆階層與實體偏好記憶庫
        bond_prompt = self.synaptic_bonding.render_bond_prompt(str(user_id), user_name)
        pref_prompt = self.memory_palace.render_preference_prompt(str(user_id))

        capsule = (
            f"{bond_prompt}"
            f"{pref_prompt}"
            f"{attachment_capsule}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"# 【本地大腦即時生理與生物鐘狀態（最高優先級生理基石，不可違背）】\n"
            f"這不是隨機的文字設定，而是來自你本地神經化學腺體與生物時鐘的客觀生理指標：\n"
            f"- 🧠 當前荷爾蒙指數：多巴胺 {int(p.dopamine)}% (好奇/興奮) | 血清素 {int(p.serotonin)}% (穩定) | 皮質醇 {int(p.cortisol)}% (壓力防衛)\n"
            f"- ⚡ 身體精力狀態：{int(p.energy)}% | 臺灣時間：{circadian['current_time']}（{circadian['phase']}）\n"
            f"- ⏰ 晝夜生理節奏：{circadian['tone_guidance']}\n"
            f"- 🐾 生理自然微動作：{circadian['micro_action']}，{params.physical_action_hint}\n"
            f"{spotlight_prompt}"
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

    def get_recent_diary(self, days_ago: int = 0) -> Optional[str]:
        """讀取最近的深夜秘密手札日記 (0 表示今天，1 表示昨天)"""
        return self.memory_palace.get_recent_diary(days_ago)

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
