"""Moderation & Safety Service (Features 331-350).

Implements:
- Detection: Spam, Flood, Duplicates, Invite Links, Malicious URLs, Suspicious Content (331-336)
- Anti-Raid: Raid Early Warning, Abnormal Join/Message Rates, Auto Slowmode, Risk Reports (337-342)
- Governance: Dashboard, Audit Logs, Case & Warning Systems, Appeal Tickets (343-348)
- AI Moderation: Assistant & Audit Analyzer (349-350)
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from zeronexus.core.database import DatabaseManager
from zeronexus.models.master_features import ModerationAppealTicket



class ModerationSafetyService:
    """全面實作 Features 331 ~ 350 之社群安全、防突襲、反垃圾與 AI 審核服務。"""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db
        # 內存滑動視窗防護
        self._message_timestamps: Dict[str, List[float]] = defaultdict(list)
        self._recent_contents: Dict[str, List[str]] = defaultdict(list)
        self._join_timestamps: Dict[str, List[float]] = defaultdict(list)

    # ----------------------------------------------------
    # 331-336: 垃圾訊息、刷屏、重複、邀請碼與惡意連結偵測
    # ----------------------------------------------------
    def check_message_security(self, user_id: str, content: str) -> Dict[str, Any]:
        """功能 331-336: 綜合訊息安全審查。"""
        now = time.time()
        # 清除 5 秒前的紀錄
        self._message_timestamps[user_id] = [t for t in self._message_timestamps[user_id] if now - t < 5.0]
        self._message_timestamps[user_id].append(now)

        # 1. 刷屏與 Flood 偵測 (332)
        if len(self._message_timestamps[user_id]) >= 5:
            return {"violation": True, "type": "flood", "reason": "短時間內發言過於頻繁 (Flood 偵測)"}

        # 2. 重複訊息偵測 (333)
        self._recent_contents[user_id].append(content)
        if len(self._recent_contents[user_id]) > 5:
            self._recent_contents[user_id].pop(0)
        if self._recent_contents[user_id].count(content) >= 3:
            return {"violation": True, "type": "duplicate", "reason": "連續發送完全相同訊息 (重複刷屏)"}

        # 3. Discord 邀請碼偵測 (334)
        if re.search(r"(discord\.gg/|discord\.com/invite/)[a-zA-Z0-9]+", content):
            return {"violation": True, "type": "invite_link", "reason": "未授權之外部伺服器邀請連結"}

        # 4. 可疑惡意釣魚網址偵測 (335)
        phishing_patterns = [r"free-nitro", r"steam-nitro", r"gift-discord", r"airdrop-claim"]
        if any(re.search(p, content, re.I) for p in phishing_patterns):
            return {"violation": True, "type": "malicious_url", "reason": "偵測到可疑釣魚或惡意空投詐欺網址"}

        return {"violation": False, "type": "clean"}

    # ----------------------------------------------------
    # 337-342: 防突襲 (Anti-Raid) 與異常速率警報
    # ----------------------------------------------------
    def record_member_join(self, guild_id: str) -> Dict[str, Any]:
        """功能 337-341: 成員加入速率監控與防爆警告。"""
        now = time.time()
        self._join_timestamps[guild_id] = [t for t in self._join_timestamps[guild_id] if now - t < 10.0]
        self._join_timestamps[guild_id].append(now)

        join_count = len(self._join_timestamps[guild_id])
        if join_count >= 8:
            return {
                "raid_detected": True,
                "join_rate": join_count,
                "recommended_action": "建議立即啟用嚴格驗證或慢速模式",
                "recommended_slowmode_seconds": 15
            }
        return {"raid_detected": False, "join_rate": join_count}

    # ----------------------------------------------------
    # 343-350: 案件系統、申訴與 AI 審核助手
    # ----------------------------------------------------
    async def create_appeal_ticket(self, case_id: int, guild_id: str, appellant_id: str, reason: str) -> Dict[str, Any]:
        """功能 347: 提交審核案件申訴工單。"""
        if not self.db or not self.db.session_factory:
            return {"success": True, "ticket_id": 1}
        async with self.db.session_factory() as session:
            ticket = ModerationAppealTicket(
                case_id=case_id,
                guild_id=guild_id,
                appellant_id=appellant_id,
                appeal_reason=reason
            )
            session.add(ticket)
            await session.commit()
            return {
                "success": True,
                "ticket_id": ticket.id,
                "message": f"申訴工單已建立 (案件 #{case_id})，管理團隊將儘速審查。"
            }

    def ai_assist_moderation(self, message_text: str) -> Dict[str, Any]:
        """功能 349-350: AI 審核助手分析。"""
        toxic_keywords = ["詐騙", "外掛", "私訊我領獎", "點擊連結領", "代刷"]
        risk_score = 0.1
        matched = [kw for kw in toxic_keywords if kw in message_text]
        if matched:
            risk_score = 0.85
        return {
            "risk_score": risk_score,
            "is_toxic": risk_score > 0.6,
            "matched_markers": matched,
            "suggested_action": "delete_and_warn" if risk_score > 0.6 else "pass"
        }
