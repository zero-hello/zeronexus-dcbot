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
    # Top 3 Recommended & Default
    {
        "id": "gemini-3.1-flash-lite",
        "label": "Google Gemini 3.1 Flash Lite (系統預設・極速智慧)",
        "emoji": "💎",
        "tag": "系統預設・超低延遲・極致輕快聰敏",
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

    # Google Gemini Series (Official Active)
    {
        "id": "gemini-3.5-flash-lite",
        "label": "Google Gemini 3.5 Flash Lite (次世代旗艦・超高智能)",
        "emoji": "✨",
        "tag": "Google 次世代高效能架構・極致敏捷推論",
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
        "tag": "專為代碼編程與除錯深度最佳化",
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
