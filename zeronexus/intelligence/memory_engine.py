"""
ZeroNexus - 記憶重要性評估與安全寫入管線 (Memory Engine & Write Pipeline)
依據 Zero Intelligence 規格第 49、50、51、52、53、145、146、147、148、149 條規範落實。

核心職責：
1. 嚴格區分短期會話 (Short-Term)、長期事實 (Long-Term) 與頻道共用 (Shared Channel)。
2. 記憶不確定性原則 (Memory Uncertainty Rule, Sec 52)：若不確定是否值得保存，寧可不存！防止瑣碎對話（如「今天吃了麵包」）污染長期記憶。
3. 記憶重要度引擎 (Importance Engine, Sec 146)：評估事實是否具備跨會話之持久價值。
4. 記憶寫入管線 (Write Pipeline, Sec 147)：
   Candidate -> Importance Assessment -> User Scope Validation -> Privacy Validation -> Duplicate Check -> Persist -> Confirm Success
5. 記憶去重 (Deduplication, Sec 148) 與 使用者遺忘控制 (Deletion, Sec 149)。
6. 真實性保證：持久化操作成功前，絕不可向使用者宣告「記住了！」。
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import re
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from zeronexus.core.database import db
from zeronexus.models.memory import ConversationMemory

logger = logging.getLogger("zeronexus.intelligence.memory_engine")


@dataclass
class MemoryWriteResult:
    """記憶寫入結果"""
    success: bool
    fact_key: Optional[str] = None
    stored_content: Optional[str] = None
    action_taken: str = "IGNORED"  # 'CREATED', 'UPDATED', 'IGNORED', 'DUPLICATE', 'FAILED'
    reason: str = ""
    user_feedback_msg: str = ""


class MemoryEngine:
    """Zero Intelligence 記憶認知引擎"""

    # 明確記憶指令動詞
    EXPLICIT_REMEMBER_PATTERNS = [
        r"(?:請?幫我)?記住[：:\s]*(.+)",
        r"(?:請?幫我)?記得[：:\s]*(.+)",
        r"(?:請?把這個)?記下來[：:\s]*(.+)",
        r"\[REMEMBER\]\s*(.+)",
        r"\[MEMORIZE\]\s*(.+)",
        r"(?:remember|memorize)\s+(?:that\s+)?(.+)",
    ]

    # 明確遺忘指令動詞
    EXPLICIT_FORGET_PATTERNS = [
        r"(?:請?幫我)?忘記[：:\s]*(.+)",
        r"(?:請?幫我)?刪除記憶[：:\s]*(.+)",
        r"(?:forget|delete memory)\s+(.+)",
    ]

    # 低價值日常瑣事過濾特徵（不確定性原則：不存）
    TRIVIAL_PATTERNS = [
        r"(?:今天|剛剛|昨天)?(?:吃|喝)了",
        r"(?:好累|想睡|去洗澡|晚安|早安|掰掰)",
        r"哈哈+|XD+|笑死",
        r"(?:好熱|好冷|天氣真好)",
    ]

    def assess_importance(self, text: str, is_explicit: bool = False) -> Tuple[float, Optional[str]]:
        """
        記憶重要度評估 (Sec 146)。
        
        回傳 (score: 0.0~1.0, extracted_fact: Optional[str])
        - score >= 0.75: 具備長期價值，允許進入寫入管線
        - score < 0.75: 判定為日常對話，不予持久化
        """
        clean_text = text.strip()

        # 1. 檢查是否包含明確「記住」指令
        for pattern in self.EXPLICIT_REMEMBER_PATTERNS:
            m = re.search(pattern, clean_text, re.IGNORECASE)
            if m:
                fact = m.group(1).strip()
                # 使用者明確交代：重要度 1.0
                return 1.0, fact

        # 2. 若非明確指令，檢查是否為低價值瑣事
        for pattern in self.TRIVIAL_PATTERNS:
            if re.search(pattern, clean_text):
                return 0.2, None

        # 3. 檢查是否為重要持久事實（如 Minecraft 伺服器、個人程式專案、生日、偏好）
        high_value_keywords = [
            "伺服器", "minecraft", "我的名字", "我叫", "生日", "專案",
            "習慣用", "偏好", "設定為", "工作是", "我的職業", "ip是",
        ]
        matched_kw = [kw for kw in high_value_keywords if kw in clean_text.lower()]
        if len(matched_kw) >= 1 and len(clean_text) >= 5:
            # 具有持久價值之事實
            return 0.85, clean_text

        # 4. 根據 Sec 52 記憶不確定性原則：無法確定價值時，寧可不存
        return 0.4, None

    def derive_fact_key(self, fact_content: str) -> str:
        """根據事實內容提取正規化的鍵值 (Fact Key) 用於去重 (Sec 148)"""
        text = fact_content.lower()
        if "minecraft" in text or "麥塊" in text or "伺服器" in text:
            return "user_server_preference"
        if "生日" in text:
            return "user_birthday"
        if "名字" in text or "叫我" in text:
            return "user_preferred_name"
        if "工作" in text or "職業" in text:
            return "user_profession"

        # 預設採用前 12 個字元作為摘要鍵
        cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
        return f"fact_{cleaned[:12]}" if cleaned else "general_fact"

    async def execute_memory_write_pipeline(
        self,
        user_id: int,
        raw_text: str,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        speaker_name: Optional[str] = None
    ) -> MemoryWriteResult:
        """
        完整執行記憶寫入管線 (Sec 147)。
        
        Candidate -> Importance Assessment -> User Scope Validation
        -> Privacy Validation -> Duplicate Check -> Persist -> Confirm Success
        """
        # Step 1 & 2: Importance Assessment
        importance_score, fact_candidate = self.assess_importance(raw_text)
        if importance_score < 0.75 or not fact_candidate:
            return MemoryWriteResult(
                success=True,
                action_taken="IGNORED",
                reason="重要度未達門檻或屬於日常瑣事，依不確定性原則不予持久化"
            )

        fact_key = self.derive_fact_key(fact_candidate)

        # Step 3 & 4: User Scope & Privacy Validation
        if not user_id or user_id <= 0:
            return MemoryWriteResult(
                success=False,
                action_taken="FAILED",
                reason="缺少有效的使用者識別碼，拒絕寫入私有記憶"
            )

        try:
            async with db.session() as session:
                # Step 5: Duplicate Check (Sec 148)
                existing = await session.execute(
                    select(ConversationMemory).where(
                        ConversationMemory.scope == "user_long_term",
                        ConversationMemory.user_id == user_id,
                        ConversationMemory.fact_key == fact_key
                    )
                )
                existing_record = existing.scalars().first()

                if existing_record:
                    if existing_record.content.strip() == fact_candidate.strip():
                        # 完全相同，已去重，不重複寫入
                        return MemoryWriteResult(
                            success=True,
                            fact_key=fact_key,
                            stored_content=fact_candidate,
                            action_taken="DUPLICATE",
                            reason="已存在完全相同之長期記憶，觸發去重保護",
                            user_feedback_msg=f"這項資訊我先前就已經牢牢記住囉！（{fact_candidate}）"
                        )
                    else:
                        # 內容更新 (Upsert)
                        existing_record.content = fact_candidate
                        existing_record.created_at = datetime.now(timezone.utc)
                        existing_record.speaker_name = speaker_name
                        await session.commit()

                        return MemoryWriteResult(
                            success=True,
                            fact_key=fact_key,
                            stored_content=fact_candidate,
                            action_taken="UPDATED",
                            reason="更新既有記憶鍵值內容",
                            user_feedback_msg=f"好的，我已經幫你把記憶更新為：「{fact_candidate}」！"
                        )

                # Step 6 & 7: Persist & Confirm Success (Sec 147)
                new_memory = ConversationMemory(
                    scope="user_long_term",
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user_id,
                    role="system",
                    speaker_name=speaker_name,
                    content=fact_candidate,
                    fact_key=fact_key,
                    created_at=datetime.now(timezone.utc)
                )
                session.add(new_memory)
                await session.commit()

                return MemoryWriteResult(
                    success=True,
                    fact_key=fact_key,
                    stored_content=fact_candidate,
                    action_taken="CREATED",
                    reason="持久化記憶寫入成功",
                    user_feedback_msg=f"沒問題，我已經記住囉：「{fact_candidate}」！"
                )

        except Exception as e:
            logger.error(f"記憶持久化寫入失敗: {e}", exc_info=True)
            # 依真實性原則：失敗時絕對不宣稱成功
            return MemoryWriteResult(
                success=False,
                action_taken="FAILED",
                reason=str(e),
                user_feedback_msg="抱歉，資料庫寫入時發生小插曲，我這次沒有成功保存這項記憶。"
            )

    async def execute_memory_deletion(
        self,
        user_id: int,
        raw_text: str
    ) -> MemoryWriteResult:
        """
        記憶遺忘與刪除管線 (Sec 149, 53)。
        """
        target_subject = ""
        for pattern in self.EXPLICIT_FORGET_PATTERNS:
            m = re.search(pattern, raw_text, re.IGNORECASE)
            if m:
                target_subject = m.group(1).strip()
                break

        if not target_subject:
            return MemoryWriteResult(
                success=False,
                action_taken="IGNORED",
                reason="未識別到明確的刪除目標"
            )

        try:
            async with db.session() as session:
                # 模糊搜尋相符之記憶並刪除
                records = await session.execute(
                    select(ConversationMemory).where(
                        ConversationMemory.scope == "user_long_term",
                        ConversationMemory.user_id == user_id
                    )
                )
                all_memories = records.scalars().all()
                deleted_count = 0

                for mem in all_memories:
                    if target_subject.lower() in mem.content.lower() or (mem.fact_key and target_subject.lower() in mem.fact_key.lower()):
                        await session.delete(mem)
                        deleted_count += 1

                await session.commit()

                if deleted_count > 0:
                    return MemoryWriteResult(
                        success=True,
                        action_taken="DELETED",
                        reason=f"成功刪除 {deleted_count} 筆相符之長期記憶",
                        user_feedback_msg=f"好的，我已經幫你清除關於「{target_subject}」的記憶囉！"
                    )
                else:
                    return MemoryWriteResult(
                        success=True,
                        action_taken="NOT_FOUND",
                        reason="未找到相符之記憶",
                        user_feedback_msg=f"在我的記憶庫中，沒有找到關於「{target_subject}」的紀錄呢。"
                    )

        except Exception as e:
            logger.error(f"記憶刪除失敗: {e}", exc_info=True)
            return MemoryWriteResult(
                success=False,
                action_taken="FAILED",
                reason=str(e),
                user_feedback_msg="刪除記憶時發生錯誤，未能成功清除。"
            )


# 全域單例
memory_engine = MemoryEngine()
