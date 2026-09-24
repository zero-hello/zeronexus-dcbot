"""ZeroNexus Interactive Model Selection Menu (Components V2 Compatible).

Provides an authoritative, beautifully categorized Discord Select Menu matching
the user's reference design with emojis, rich tags, and real-time per-model balances.
"""

from __future__ import annotations

from typing import Dict, List, Optional
import discord

from zeronexus.ai_gateway.quota_service import quota_service
from zeronexus.ai_gateway.model_switch_service import model_switch_service
from zeronexus.ui.responder import InteractionResponder


# Model catalog entries designed to match user expectations & reference image
MODEL_SELECT_ENTRIES: List[Dict[str, str]] = [
    # Top Recommended & Default
    {
        "id": "gemini-3.1-flash-lite",
        "label": "Google Gemini 3.1 Flash Lite (系統預設・極速智慧)",
        "emoji": "💎",
        "tag": "系統預設・超低延遲・極致輕快聰敏",
    },
    {
        "id": "qwen2.5-0.5b-instruct-q8_0",
        "label": "Qwen 2.5 0.5B GGUF (本地端自主運算・0延遲0額度)",
        "emoji": "⚡",
        "tag": "本地離線推論 (需主機支援 AVX2，託管伺服器請選雲端模型)",
    },
    {
        "id": "deepseek/deepseek-v4-flash-vision-exp",
        "label": "DeepSeek - V4 Flash Vision Exp (實驗旗艦・視覺推理)",
        "emoji": "👁️",
        "tag": "多模態視覺・極速實驗推理・強大感知",
    },
    {
        "id": "qwen/qwen-2.5-72b-instruct",
        "label": "OpenRouter - Qwen 2.5 72B (開源最強中文旗艦)",
        "emoji": "🇨🇳",
        "tag": "阿里通義千問・繁中特化最強旗艦",
    },

    # Manus AI Agent (Autonomous Agent)
    {
        "id": "manus",
        "label": "Manus - AI 自主 Agent (深度規劃與全自動執行)",
        "emoji": "🤖",
        "tag": "自主代理・多步規劃・每日限額 30 句・用完即止",
    },

    # Cohere Command Series (Official Active Flagships)
    {
        "id": "command-r-plus-08-2024",
        "label": "Cohere - Command R+ (企業級長文本與強大 RAG 旗艦)",
        "emoji": "🌐",
        "tag": "多語言長文本・企業級檢索增強與邏輯推理",
    },
    {
        "id": "command-r-08-2024",
        "label": "Cohere - Command R (平衡型極速多語言推理旗艦)",
        "emoji": "🏎️",
        "tag": "低延遲・多語言優化・高性價比 RAG 推理",
    },

    # Groq LPU Ultra-Fast Series (極速超低延遲)
    {
        "id": "qwen/qwen3.8-27b",
        "label": "Groq - Qwen 3.8 27B (超光速 LPU・繁中極速對話)",
        "emoji": "⚡",
        "tag": "數百 TPS 超低延遲・通義千問高智能對話旗艦",
    },
    {
        "id": "openai/gpt-oss-120b",
        "label": "Groq - GPT-OSS 120B (超光速 LPU・千億開源頂級旗艦)",
        "emoji": "🏎️",
        "tag": "數百 TPS 超光速推論・千億級開源大模型頂級推理",
    },

    # Mistral AI Series (歐洲開源先鋒頂尖旗艦)
    {
        "id": "codestral-latest",
        "label": "Mistral - Codestral (專業程式碼與高智慧對話旗艦)",
        "emoji": "💻",
        "tag": "精準程式碼生成・專業除錯與架構推導",
    },
    {
        "id": "ministral-8b-latest",
        "label": "Mistral - Ministral 8B (超快反應・小巧精準旗艦)",
        "emoji": "🌪️",
        "tag": "128k 上下文・高智商邊緣特化模型與敏銳互動",
    },

    # Google Gemini Series (Official Active Flagships)
    {
        "id": "gemini-3.7-flash",
        "label": "Google Gemini 3.7 Flash (最新混合推理旗艦・動態思維鏈)",
        "emoji": "🔮",
        "tag": "首款混合架構・動態思考推理與極致多工兼備",
    },
    {
        "id": "gemini-3.8-flash",
        "label": "Google Gemini 3.8 Flash (次世代實驗極速旗艦)",
        "emoji": "🚀",
        "tag": "次世代極致低延遲架構・前沿推論突破",
    },
    {
        "id": "gemini-3.5-flash-lite",
        "label": "Google Gemini 3.5 Flash Lite (次世代高智能・極致敏捷)",
        "emoji": "✨",
        "tag": "Google 次世代高效能架構・極致敏捷推論",
    },
    {
        "id": "gemini-flash-latest",
        "label": "Google Gemini Flash Latest (官方動態最新 Flash)",
        "emoji": "🌟",
        "tag": "Google 官方即時跟進更新最新 Flash 穩定版本",
    },
    {
        "id": "gemini-pro-latest",
        "label": "Google Gemini Pro Latest (官方動態最新 Pro)",
        "emoji": "👑",
        "tag": "Google 官方即時跟進更新最新 Pro 旗艦版本",
    },

    # DeepSeek Series
    {
        "id": "deepseek-v4.1-flash",
        "label": "DeepSeek - V4.1 Flash (原生極速對話・低延遲)",
        "emoji": "⚡",
        "tag": "官方原生節點・極速對話與敏捷思考",
    },
    {
        "id": "deepseek-chat",
        "label": "DeepSeek - V3 旗艦 (671B 頂尖對話)",
        "emoji": "💬",
        "tag": "官方原生節點・超高性價比",
    },
    {
        "id": "deepseek-reasoner",
        "label": "DeepSeek - R1 深度推理 (頂級思維鏈)",
        "emoji": "🔬",
        "tag": "頂尖開源深度思考推理鏈",
    },

    # Qwen Series
    {
        "id": "qwen/qwq-32b",
        "label": "OpenRouter - Qwen QwQ 32B (推理思維鏈)",
        "emoji": "🧩",
        "tag": "數學、程式與演算法深度推導",
    },
    {
        "id": "qwen/qwen-2.5-coder-32b-instruct",
        "label": "OpenRouter - Qwen 2.5 Coder 32B (程式專業特化)",
        "emoji": "💻",
        "tag": "專為程式開發與除錯深度最佳化",
    },

    # OpenRouter Free Rotation
    {
        "id": "openrouter/free",
        "label": "OpenRouter (自動選模: 智慧輪替)",
        "emoji": "🌐",
        "tag": "智慧自動容錯輪替・高可用性",
    },
]


class ModelSelectDropdown(discord.ui.Select):
    """Dropdown component populated with rich model options and dynamic quota descriptions."""

    def __init__(
        self,
        options: List[discord.SelectOption],
        user_id: int,
        guild_id: Optional[int] = None,
        is_server: bool = False,
    ) -> None:
        super().__init__(
            placeholder="🔍 請選擇您想切換的 AI 模型...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="zn_model_select_dropdown",
        )
        self.user_id = user_id
        self.guild_id = guild_id
        self.is_server = is_server

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handles selection of a model and applies the switch."""
        selected_model_id = self.values[0]
        await InteractionResponder.safe_defer(interaction, ephemeral=True)

        res = await model_switch_service.switch_model(
            user_id=self.user_id,
            guild_id=self.guild_id,
            target_query=selected_model_id,
            is_server_level=self.is_server,
        )

        card = res.to_card()
        # Append per-model quota info to card
        quota_info = await quota_service.get_user_model_quota(self.user_id, selected_model_id)
        if quota_info["is_dev"]:
            q_desc = "今日額度：無上限 (開發者特權)"
        else:
            q_desc = f"今日該模型額度剩餘：`{quota_info['remaining']}/{quota_info['limit']}` 次"
        card.add_section("📊 模型額度資訊", q_desc)

        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)


class ModelSelectView(discord.ui.View):
    """View container holding the interactive model dropdown."""

    def __init__(self, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)

    @classmethod
    async def create(
        cls,
        user_id: int,
        guild_id: Optional[int] = None,
        is_server: bool = False,
        current_model_id: Optional[str] = None,
    ) -> ModelSelectView:
        """Factory method to construct options with real-time per-model balances asynchronously."""
        view = cls()
        options: List[discord.SelectOption] = []

        for entry in MODEL_SELECT_ENTRIES:
            desc = await quota_service.format_model_quota_desc(
                user_id=user_id,
                model_id=entry["id"],
                tag=entry["tag"],
            )
            is_default = (current_model_id == entry["id"])
            opt = discord.SelectOption(
                label=entry["label"][:100],
                value=entry["id"],
                description=desc[:100],
                emoji=entry["emoji"],
                default=is_default,
            )
            options.append(opt)

        dropdown = ModelSelectDropdown(
            options=options,
            user_id=user_id,
            guild_id=guild_id,
            is_server=is_server,
        )
        view.add_item(dropdown)
        return view
