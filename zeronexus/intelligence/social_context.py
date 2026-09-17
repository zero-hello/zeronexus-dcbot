"""
ZeroNexus - 社群語境圖譜解析器 (Social Context Graph & Threading)
依據 Zero Intelligence 規格第 20、144、204、205、206、211 條規範落實。

核心職責：
1. 嚴格解析多人頻道語境（Shared Channel Context），區分 Alice、Bob、Charlie 輪流發言之脈絡。
2. 精確分類互動型態：DIRECT_MENTION、REPLIED_TO_BOT、BOT_NAME_MENTIONED、CROSS_CHAT、DM_CONVERSATION。
3. 規範化使用者輸入：移除 Discord 機器人標註（<@!bot_id>），保留純淨指令與提問。
4. 追蹤引用回覆鏈 (Reference Chain)，建立清楚的多人對話脈絡，防止機器人插話錯亂或將第三方對話誤判為指示。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import re
import datetime
import logging

logger = logging.getLogger("zeronexus.intelligence.social_context")


class InteractionType(str, Enum):
    """使用者互動意圖類型"""
    DIRECT_MENTION = "DIRECT_MENTION"          # 直接 @機器人
    REPLIED_TO_BOT = "REPLIED_TO_BOT"          # 引用回覆機器人的發言
    BOT_NAME_MENTIONED = "BOT_NAME_MENTIONED"  # 訊息內文明確提及 ZeroNexus 但非 @
    CROSS_CHAT = "CROSS_CHAT"                  # 成員彼此之間的閒聊對話
    DM_CONVERSATION = "DM_CONVERSATION"        # 一對一私訊


@dataclass
class SpeakerInfo:
    """發言者社群身分"""
    user_id: int
    name: str
    display_name: str
    is_bot: bool = False
    is_server_owner: bool = False
    is_admin: bool = False
    roles: List[str] = field(default_factory=list)


@dataclass
class ConversationMessage:
    """社群頻道對話單元"""
    message_id: int
    speaker: SpeakerInfo
    content: str
    timestamp: datetime.datetime
    referenced_message_id: Optional[int] = None
    referenced_speaker_name: Optional[str] = None
    referenced_content: Optional[str] = None


class SocialContextGraph:
    """社群語境圖譜管理器"""

    def __init__(self, bot_id: int = 0, bot_names: Optional[List[str]] = None):
        self.bot_id = bot_id
        self.bot_names = bot_names or ["ZeroNexus", "zeronexus", "Zero", "ZN"]

    def analyze_interaction_type(
        self,
        content: str,
        is_dm: bool,
        is_mentioned: bool,
        reference_message_author_id: Optional[int] = None,
    ) -> InteractionType:
        """
        判斷當前訊息之社群互動形態。
        """
        if is_dm:
            return InteractionType.DM_CONVERSATION

        if reference_message_author_id and self.bot_id and reference_message_author_id == self.bot_id:
            return InteractionType.REPLIED_TO_BOT

        if is_mentioned:
            return InteractionType.DIRECT_MENTION

        content_lower = content.lower()
        for bname in self.bot_names:
            if bname.lower() in content_lower:
                return InteractionType.BOT_NAME_MENTIONED

        return InteractionType.CROSS_CHAT

    def normalize_message_content(self, raw_content: str, bot_id: Optional[int] = None) -> str:
        """
        規範化使用者輸入：移除機器人的 Mention 標籤 (<@bot_id>、<@!bot_id>)，
        保留純淨指令內容。
        """
        if not raw_content:
            return ""

        cleaned = raw_content
        target_id = bot_id or self.bot_id
        if target_id:
            # 移除特定機器人的 <@123456> 或 <@!123456>
            cleaned = re.sub(rf"<@!?{target_id}>\s*", "", cleaned)
        else:
            # 未指定特定 ID 時，預設移除行首之通用 Mention
            cleaned = re.sub(r"^\s*<@!?\d+>\s*", "", cleaned)

        # 移除行首開頭的 "@ZeroNexus" 或 "ZeroNexus:"
        for bname in self.bot_names:
            pattern = rf"^\s*@{re.escape(bname)}[:,\s]*"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        return cleaned.strip()

    def build_channel_dialogue_context(
        self,
        messages: List[ConversationMessage],
        max_messages: int = 15
    ) -> str:
        """
        將多人頻道的訊息序列組織為結構化社群語境區塊。
        
        依據規格第 144 條：保留發言者名稱、身分與引用對象，
        讓 AI 明白這是多人對話而非單一人格重複說話。
        """
        if not messages:
            return ""

        recent = messages[-max_messages:]
        lines = ["【多人頻道對話流 (Shared Channel Context)】"]

        for msg in recent:
            sp = msg.speaker
            role_tag = " (管理員)" if sp.is_admin else (" (伺服器擁有者)" if sp.is_server_owner else "")
            bot_tag = " (Bot)" if sp.is_bot else ""
            display = f"{sp.display_name}{role_tag}{bot_tag}"

            ref_str = ""
            if msg.referenced_speaker_name:
                snippet = (msg.referenced_content or "")[:30].replace("\n", " ")
                ref_str = f" [回覆 @{msg.referenced_speaker_name}: \"{snippet}...\"]"

            time_str = msg.timestamp.strftime("%H:%M:%S")
            lines.append(f"[{time_str}] {display}{ref_str}: {msg.content}")

        lines.append("【對話指引：請留意上述不同成員的發言脈絡，切勿混淆發言人身分】\n")
        return "\n".join(lines)


# 全域單例
social_context_graph = SocialContextGraph()
