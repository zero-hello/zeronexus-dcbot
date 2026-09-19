"""ZeroNexus 500 Feature Master Specification Database Models.

Provides complete persistence models for:
- AI Knowledge Base & Knowledge Graph
- Automation Workflows & Execution History
- Community Polls, Proposals, Suggestions & Events
- Social Achievements, Titles, Badges & Daily Missions
- Productivity Tasks, Habits & Personal Work Logs
- Moderation Appeals & System Audit Logs
"""

from __future__ import annotations

import time
from typing import Optional
from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from zeronexus.core.database import Base


# ==========================================
# 1. AI 知識庫與知識圖譜 (AI Knowledge Base & Graph)
# ==========================================

class KnowledgeBaseItem(Base):
    """知識庫儲存實體，支援個人/伺服器/頻道隔離與版本控制。"""
    __tablename__ = "zn_knowledge_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32), default="guild", index=True)  # guild, channel, personal, global
    guild_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    
    title: Mapped[str] = mapped_column(String(256), index=True)
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="general", index=True)
    tags: Mapped[str] = mapped_column(String(256), default="")  # 逗號分隔標籤
    
    source_type: Mapped[str] = mapped_column(String(32), default="manual")  # manual, url, doc, faq, extracted
    source_uri: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class KnowledgeGraphEdge(Base):
    """知識圖譜實體關聯拓撲邊。"""
    __tablename__ = "zn_knowledge_graph_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("zn_knowledge_items.id", ondelete="CASCADE"), index=True)
    target_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("zn_knowledge_items.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(64), default="relates_to")  # defines, depends_on, conflicts_with
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


# ==========================================
# 2. 自動化工作流 (Automation Workflows)
# ==========================================

class AutomatedWorkflowModel(Base):
    """伺服器自動化工作流定義實體。"""
    __tablename__ = "zn_automated_workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(64), index=True)
    creator_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(256), default="")
    
    # 觸發器類型與條件 (JSON 字串)
    trigger_type: Mapped[str] = mapped_column(String(64), index=True)  # message, reaction, join, time, webhook, ai_intent
    trigger_config_json: Mapped[str] = mapped_column(Text, default="{}")
    
    # 條件判斷與動作序列 (JSON 字串)
    conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    actions_json: Mapped[str] = mapped_column(Text, default="[]")
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    execution_count: Mapped[int] = mapped_column(Integer, default=0)
    last_triggered_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class WorkflowExecutionRecord(Base):
    """工作流執行歷史與審計記錄。"""
    __tablename__ = "zn_workflow_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("zn_automated_workflows.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="success")  # success, failed, skipped
    triggered_by: Mapped[str] = mapped_column(String(128))
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executed_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


# ==========================================
# 3. 社群互動 (Community Polls, Proposals, Suggestions & Events)
# ==========================================

class CommunityPollModel(Base):
    """投票系統實體。"""
    __tablename__ = "zn_community_polls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(64), index=True)
    channel_id: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    creator_id: Mapped[str] = mapped_column(String(64))
    
    title: Mapped[str] = mapped_column(String(256))
    options_json: Mapped[str] = mapped_column(Text)  # ["選項1", "選項2"]
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    is_multichoice: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ranked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    
    closes_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class CommunityPollVoteRecord(Base):
    """投票紀錄實體。"""
    __tablename__ = "zn_community_poll_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    poll_id: Mapped[int] = mapped_column(Integer, ForeignKey("zn_community_polls.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    option_index: Mapped[int] = mapped_column(Integer)
    rank_order: Mapped[int] = mapped_column(Integer, default=0)
    voted_at: Mapped[float] = mapped_column(Float, default=time.time)


class CommunityProposalModel(Base):
    """社群提案系統實體。"""
    __tablename__ = "zn_community_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(64), index=True)
    author_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="discussion")  # discussion, voting, approved, rejected
    
    upvotes: Mapped[int] = mapped_column(Integer, default=0)
    downvotes: Mapped[int] = mapped_column(Integer, default=0)
    thread_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class CommunitySuggestionModel(Base):
    """社群建議箱實體。"""
    __tablename__ = "zn_community_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(64), index=True)
    author_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 匿名則為 None
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="general")
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, reviewed, accepted, declined
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class CommunityEventModel(Base):
    """社群活動日曆與出席實體。"""
    __tablename__ = "zn_community_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(64), index=True)
    creator_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(256), default="Discord 語音/文字頻道")
    
    start_time: Mapped[float] = mapped_column(Float, index=True)
    end_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    attendees_json: Mapped[str] = mapped_column(Text, default="[]")  # user_id 陣列
    reminder_minutes: Mapped[int] = mapped_column(Integer, default=15)
    is_concluded: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


# ==========================================
# 4. 社交、成就與稱號 (Social, Achievements & Titles)
# ==========================================

class UserAchievementRecord(Base):
    """使用者成就紀錄實體。"""
    __tablename__ = "zn_user_achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    guild_id: Mapped[str] = mapped_column(String(64), index=True)
    achievement_code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(256))
    unlocked_at: Mapped[float] = mapped_column(Float, default=time.time)


class UserTitleBadgeModel(Base):
    """使用者自訂稱號與徽章實體。"""
    __tablename__ = "zn_user_titles_badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    item_type: Mapped[str] = mapped_column(String(16))  # title, badge
    code: Mapped[str] = mapped_column(String(64))
    display_text: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str] = mapped_column(String(16), default="🏅")
    is_equipped: Mapped[bool] = mapped_column(Boolean, default=False)
    acquired_at: Mapped[float] = mapped_column(Float, default=time.time)


class UserDailyMissionRecord(Base):
    """使用者每日任務進度實體。"""
    __tablename__ = "zn_user_daily_missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    date_str: Mapped[str] = mapped_column(String(16), index=True)  # YYYY-MM-DD
    mission_code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(128))
    target_count: Mapped[int] = mapped_column(Integer, default=1)
    current_count: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    xp_reward: Mapped[int] = mapped_column(Integer, default=50)


# ==========================================
# 5. 生產力與待辦 (Productivity & Tasks)
# ==========================================

class ProductivityTaskModel(Base):
    """生產力待辦事項實體。"""
    __tablename__ = "zn_productivity_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    guild_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(16), default="medium")  # low, medium, high, urgent
    category: Mapped[str] = mapped_column(String(64), default="personal")
    
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deadline_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recurring_rule: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # daily, weekly, monthly
    
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    completed_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class HabitTrackerRecord(Base):
    """個人習慣打卡實體。"""
    __tablename__ = "zn_habit_tracker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    habit_name: Mapped[str] = mapped_column(String(128))
    target_frequency: Mapped[str] = mapped_column(String(32), default="daily")
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    max_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_checkin_date: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # YYYY-MM-DD
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class PersonalWorkLogModel(Base):
    """個人工作日誌實體。"""
    __tablename__ = "zn_personal_work_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    log_date: Mapped[str] = mapped_column(String(16), index=True)  # YYYY-MM-DD
    content: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


# ==========================================
# 6. 安全審核申訴 (Moderation Appeals)
# ==========================================

class ModerationAppealTicket(Base):
    """審核案件申訴實體。"""
    __tablename__ = "zn_moderation_appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    guild_id: Mapped[str] = mapped_column(String(64), index=True)
    appellant_id: Mapped[str] = mapped_column(String(64), index=True)
    appeal_reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open, under_review, granted, rejected
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


# 建立複合索引以加速高頻查詢
Index("ix_zn_tasks_user_status", ProductivityTaskModel.user_id, ProductivityTaskModel.is_completed)
Index("ix_zn_knowledge_scope_guild", KnowledgeBaseItem.scope, KnowledgeBaseItem.guild_id)
