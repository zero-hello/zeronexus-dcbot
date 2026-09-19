"""ZeroNexus Database Models."""

from zeronexus.models.guild import GuildSettings, EarthquakeNotificationRecord
from zeronexus.models.user import UserProfile, AIQuotaRecord, AIImageQuotaRecord, EconomyWallet, UserAffinityRecord
from zeronexus.models.memory import ConversationMemory
from zeronexus.models.persona import CustomPersonaModel
from zeronexus.models.moderation import ModerationCase, WarningRecord
from zeronexus.models.ticket import TicketConfig, TicketRecord
from zeronexus.models.master_features import (
    KnowledgeBaseItem,
    KnowledgeGraphEdge,
    AutomatedWorkflowModel,
    WorkflowExecutionRecord,
    CommunityPollModel,
    CommunityPollVoteRecord,
    CommunityProposalModel,
    CommunitySuggestionModel,
    CommunityEventModel,
    UserAchievementRecord,
    UserTitleBadgeModel,
    UserDailyMissionRecord,
    ProductivityTaskModel,
    HabitTrackerRecord,
    PersonalWorkLogModel,
    ModerationAppealTicket,
)

__all__ = [
    "GuildSettings",
    "EarthquakeNotificationRecord",
    "UserProfile",
    "AIQuotaRecord",
    "AIImageQuotaRecord",
    "EconomyWallet",
    "UserAffinityRecord",
    "ConversationMemory",
    "CustomPersonaModel",
    "ModerationCase",
    "WarningRecord",
    "TicketConfig",
    "TicketRecord",
    "KnowledgeBaseItem",
    "KnowledgeGraphEdge",
    "AutomatedWorkflowModel",
    "WorkflowExecutionRecord",
    "CommunityPollModel",
    "CommunityPollVoteRecord",
    "CommunityProposalModel",
    "CommunitySuggestionModel",
    "CommunityEventModel",
    "UserAchievementRecord",
    "UserTitleBadgeModel",
    "UserDailyMissionRecord",
    "ProductivityTaskModel",
    "HabitTrackerRecord",
    "PersonalWorkLogModel",
    "ModerationAppealTicket",
]

