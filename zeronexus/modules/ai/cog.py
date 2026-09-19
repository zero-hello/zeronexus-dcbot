"""ZeroNexus AI Command Cog.

18 Fully Implemented Commands under /人工智慧:
- 對話, 設定頻道, 移除頻道, 頻道記憶重置, 切換人格, 人格清單, 自訂人格, 刪除自訂人格
- 記憶檢視, 記憶刪除, 記憶清空, 額度查詢, 重設額度, 模型狀態, 金鑰狀態
- 對話重置, 思考模式設定, 翻譯助理
"""

from __future__ import annotations

import io
import re
from typing import Any, List, Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select

from zeronexus.ai_gateway.context_builder import context_builder
from zeronexus.ai_gateway.gateway import ai_gateway
from zeronexus.ai_gateway.model_catalog import model_catalog
from zeronexus.core.config import config
from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.engines.ai_features import detect_conversational_feature
from zeronexus.engines.cwa_service import cwa_service
from zeronexus.engines.image_gen import image_gen_engine
from zeronexus.engines.prompt_engine import prompt_engine
from zeronexus.engines.web_client import detect_search_intent, web_client
from zeronexus.intelligence.deep_thinking_controller import ThinkingIntent, deep_thinking_controller
from zeronexus.models.guild import GuildSettings
from zeronexus.models.memory import ConversationMemory
from zeronexus.models.persona import CustomPersonaModel
from zeronexus.models.user import AIImageQuotaRecord, AIQuotaRecord, UserProfile
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import PermissionEngine, ZNPermissionLevel
from zeronexus.security.ratelimit import quota_service
from zeronexus.ui.card import ZNCard, ZNResponse
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill

if not hasattr(discord, "InteractionContextType"):
    class InteractionContextType:
        guild = 0
        bot_dm = 1
        private_channel = 2
    discord.InteractionContextType = InteractionContextType


class AIModule(BaseModule):
    """AI Cognition, Persona Management, and Memory Lifecycle."""

    def __init__(self) -> None:
        super().__init__(
            name="ai",
            display_name="人工智慧模組",
            description="三級備援 AI Gateway、15 款人格切換、長短期記憶萃取與群體對話頻道",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("對話", "發起單次 AI 自然語言對話", ZNPermissionLevel.EVERYONE),
            ("生圖", "運用 AI 生成高品質視覺影像或藝術插圖", ZNPermissionLevel.EVERYONE),
            ("切換模型", "切換個人或伺服器 AI 模型 (支援 DeepSeek、GPT、Claude、Gemini 等)", ZNPermissionLevel.EVERYONE),
            ("模型目錄", "檢視平台所有可用 AI 模型分類與特色說明", ZNPermissionLevel.EVERYONE),
            ("設定頻道", "將此頻道設定為共享 AI 對話頻道", ZNPermissionLevel.ADMINISTRATOR),
            ("移除頻道", "解除當前頻道的 AI 專用綁定", ZNPermissionLevel.ADMINISTRATOR),
            ("頻道記憶重置", "清空當前頻道的共享對話歷史", ZNPermissionLevel.ADMINISTRATOR),
            ("切換人格", "切換 15 款預設人格或自訂人格", ZNPermissionLevel.EVERYONE),
            ("人格清單", "檢視 15 款內建人格特色與世界觀", ZNPermissionLevel.EVERYONE),
            ("自訂人格", "建立個人專屬客製化人格", ZNPermissionLevel.EVERYONE),
            ("刪除自訂人格", "刪除已建立之客製化人格", ZNPermissionLevel.EVERYONE),
            ("記憶檢視", "檢視個人儲存之長短期記憶", ZNPermissionLevel.EVERYONE),
            ("記憶刪除", "依條目 ID 刪除特定記憶", ZNPermissionLevel.EVERYONE),
            ("記憶清空", "一鍵清空在 ZeroNexus 中的全部長期記憶", ZNPermissionLevel.EVERYONE),
            ("對話額度", "檢視個人今日 AI 免費對話額度與刷新時間", ZNPermissionLevel.EVERYONE),
            ("額度查詢", "查詢個人今日 AI 免費對話額度 (相容別名)", ZNPermissionLevel.EVERYONE),
            ("重設額度", "管理員重設特定成員今日配額", ZNPermissionLevel.ADMINISTRATOR),
            ("模型狀態", "檢視當前 Provider 模型指標", ZNPermissionLevel.EVERYONE),
            ("金鑰狀態", "檢視金鑰池健康輪詢狀態 (遮蔽展示)", ZNPermissionLevel.EVERYONE),
            ("對話重置", "清空當前對話上下文快取", ZNPermissionLevel.EVERYONE),
            ("思考模式設定", "切換是否在對話中展示思考歷程", ZNPermissionLevel.EVERYONE),
            ("翻譯助理", "多語系上下文高精確度翻譯", ZNPermissionLevel.EVERYONE),
            ("炸裂功能", "瀏覽 22 款全新 AI 炸裂對話功能與玩法示範", ZNPermissionLevel.EVERYONE),
            ("好感度", "檢視你與 ZeroNexus 之間的心靈羈絆、隱性好感度與專屬印象評價", ZNPermissionLevel.EVERYONE),
        ]
        for name, desc, perm in commands_list:
            is_guild_only = name in ("設定頻道", "移除頻道", "頻道記憶重置", "重設額度")
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"人工智慧 {name}",
                description=desc,
                group_name="人工智慧",
                module_name=self.name,
                permission_level=perm,
                guild_only=is_guild_only,
            ))

    async def shutdown(self) -> None:
        pass


class AIProfileModal(discord.ui.Modal, title="建立自訂 AI 人格"):
    """Interactive modal for defining custom personas."""

    persona_name = discord.ui.TextInput(label="人格名稱", placeholder="例如：毒舌管家、科幻艦長", max_length=32)
    personality = discord.ui.TextInput(label="性格特徵", placeholder="描述其核心性格、脾氣與態度", style=discord.TextStyle.paragraph, max_length=500)
    tone = discord.ui.TextInput(label="說話語氣與口頭禪", placeholder="常說的語助詞、習慣用語", style=discord.TextStyle.paragraph, max_length=300)
    forbidden = discord.ui.TextInput(label="禁忌事項", placeholder="不允許出現的行為或字眼", style=discord.TextStyle.paragraph, max_length=200, required=False)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with db.session() as session:
            model = CustomPersonaModel(
                name=self.persona_name.value.strip(),
                description=f"由 {interaction.user.display_name} 創建的客製人格",
                personality=self.personality.value.strip(),
                speaking_habits=self.tone.value.strip(),
                forbidden_behaviors=self.forbidden.value.strip() if self.forbidden.value else "",
                created_by_user_id=interaction.user.id,
                guild_id=interaction.guild_id,
            )
            session.add(model)
            await session.flush()

        card = ZNCard(
            title="自訂人格建立完成",
            description=f"您已成功建立人格 **「{self.persona_name.value}」**！\n可透過 `/人工智慧 切換人格` 選擇使用。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)


async def switch_model_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """為 /人工智慧 切換模型 提供極速、高質感之旗艦模型與註冊表動態自動補全。"""
    from zeronexus.ui.model_select_view import MODEL_SELECT_ENTRIES

    choices: List[app_commands.Choice[str]] = []
    q = current.lower().strip()
    added_ids = set()

    try:
        # 1. First priority: Pre-curated, highly aesthetic, emoji-rich flagship catalog
        for entry in MODEL_SELECT_ENTRIES:
            m_id = entry["id"]
            m_label = entry["label"]
            m_emoji = entry.get("emoji", "🤖")
            m_tag = entry.get("tag", "")

            searchable = f"{m_id} {m_label} {m_tag}".lower()

            matched = False
            if not q:
                matched = True
            elif q in searchable:
                matched = True
            elif ("deepseek" in q or "deep" in q) and "deepseek" in searchable:
                matched = True
            elif "gemini" in q and "gemini" in searchable:
                matched = True
            elif "qwen" in q and "qwen" in searchable:
                matched = True
            elif "r1" in q and "r1" in searchable:
                matched = True
            elif "v4" in q and "v4" in searchable:
                matched = True
            elif "flash" in q and "flash" in searchable:
                matched = True
            elif "pro" in q and "pro" in searchable:
                matched = True
            elif "gpt" in q and "gpt" in searchable:
                matched = True
            elif "grok" in q and "grok" in searchable:
                matched = True

            if matched and m_id not in added_ids:
                display_name = f"{m_emoji} {m_label}"
                choices.append(app_commands.Choice(name=display_name[:100], value=m_id))
                added_ids.add(m_id)
                if len(choices) >= 25:
                    break

        # 2. Secondary fallback: Search active models registered in model_registry
        if len(choices) < 25 and q:
            from zeronexus.ai_gateway.model_registry import model_registry
            for reg_m in model_registry.list_active_models():
                m_id = reg_m.model_id
                m_name = reg_m.display_name
                if m_id in added_ids:
                    continue
                searchable = f"{m_id} {m_name} {reg_m.description}".lower()
                if q in searchable:
                    emoji = "💎" if "gemini" in m_id.lower() else ("💬" if "deepseek" in m_id.lower() else "🇨🇳")
                    display_name = f"{emoji} {m_name} ({m_id})"
                    choices.append(app_commands.Choice(name=display_name[:100], value=m_id))
                    added_ids.add(m_id)
                    if len(choices) >= 25:
                        break

        # 3. Tertiary fallback: Search remaining active models from OpenRouter catalog
        if len(choices) < 25 and q:
            for m in model_catalog._all_models:
                m_id = m.get("id", "")
                m_name = m.get("name", m_id)
                if ":batch" in m_id.lower() or "deprecated" in m_id.lower():
                    continue
                if m_id in added_ids:
                    continue

                if q in m_id.lower() or q in m_name.lower():
                    emoji = "🌐"
                    if "gemini" in m_id.lower():
                        emoji = "💎"
                    elif "deepseek" in m_id.lower():
                        emoji = "💬"
                    elif "qwen" in m_id.lower():
                        emoji = "🇨🇳"
                    elif "gpt" in m_id.lower():
                        emoji = "🧠"
                    elif "grok" in m_id.lower():
                        emoji = "⚡"

                    display_name = f"{emoji} {m_name} ({m_id})"
                    choices.append(app_commands.Choice(name=display_name[:100], value=m_id))
                    added_ids.add(m_id)
                    if len(choices) >= 25:
                        break
    except Exception as exc:
        log.error(f"Error in switch_model_autocomplete: {exc}", exc_info=True)
        if not choices:
            choices = [
                app_commands.Choice(name="💎 Google Gemini 3.1 Flash Lite (系統預設)", value="gemini-3.1-flash-lite"),
                app_commands.Choice(name="⚡ Google Gemini 2.5 Flash", value="gemini-2.5-flash"),
                app_commands.Choice(name="🧠 Google Gemini 2.5 Pro", value="gemini-2.5-pro"),
                app_commands.Choice(name="👁️ DeepSeek - V4 Flash Vision Exp", value="deepseek/deepseek-v4-flash-vision-exp"),
                app_commands.Choice(name="🇨🇳 OpenRouter - Qwen 2.5 72B", value="qwen/qwen-2.5-72b-instruct"),
            ]

    return choices[:25]


class AICog(commands.Cog):
    """Discord Slash Command Group for /人工智慧."""

    ai_group = app_commands.Group(
        name="人工智慧",
        description="認知推理、人格切換與長短期記憶指令群組",
        guild_only=False,
        allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
    )
    ai_group.contexts = [discord.InteractionContextType.guild, discord.InteractionContextType.bot_dm]

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @ai_group.command(name="對話", description="與 ZeroNexus AI 進行深度智能諮詢與圖片視覺辨識")
    @app_commands.describe(問題="想詢問或探討的問題", 圖片="可選，上傳欲由 AI 視覺辨識分析之圖片 (支援 PNG/JPG/WEBP/GIF)")
    @command_guard("ai")
    async def ask_command(
        self,
        interaction: discord.Interaction,
        問題: str,
        圖片: Optional[discord.Attachment] = None,
    ) -> None:
        問題 = 問題.strip()
        if not 問題:
            await InteractionResponder.safe_send(
                interaction,
                "💡 請輸入您想探討或諮詢的具體問題內容，例如「請幫我整理重點」或「這段程式碼有什麼問題？」。",
                ephemeral=True,
            )
            return
        if len(問題) > 4000:
            await InteractionResponder.safe_send(
                interaction,
                "📝 您的提問長度超過了 4000 字元上限。建議您可以分段發送，或將背景資料精簡後提問，這樣 AI 能給出更精確的回覆喔！",
                ephemeral=True,
            )
            return

        # Check quota & atomic 3-phase reservation
        is_secret_easter_egg = config.is_secret_channel(interaction.channel_id)
        if is_secret_easter_egg:
            allowed, reservation, projected_used, effective_limit = True, None, 0, 99999
        else:
            allowed, reservation, projected_used, effective_limit = await quota_service.reserve_quota(interaction.user.id)
            if not allowed:
                await InteractionResponder.safe_send(
                    interaction,
                    f"⏳ 您今日的 AI 免費對話額度已達到上限囉 (`{projected_used}/{effective_limit}` 次)。\n系統將於每日凌晨 00:00 (台灣時間 / UTC+8) 自動補充完畢，感謝您的支持與愛用！",
                    ephemeral=True,
                )
                return

        await InteractionResponder.safe_defer(interaction)

        # Process image attachment if provided
        images = None
        image_thumbnail = None
        if 圖片:
            content_type = 圖片.content_type or "image/png"
            if content_type.startswith("image/"):
                try:
                    img_bytes = await 圖片.read()
                    import base64
                    b64_data = base64.b64encode(img_bytes).decode("utf-8")
                    images = [{"mime_type": content_type, "data": b64_data}]
                    image_thumbnail = 圖片.url
                except Exception as img_err:
                    log.warning(f"Failed to read user attached image: {img_err}")

        generated_image_url: Optional[str] = None
        generated_image_bytes: Optional[bytes] = None
        if is_secret_easter_egg:
            from zeronexus.engines.secret_egg import get_secret_egg_prompt
            system_instruction = get_secret_egg_prompt()
            user_model = "gemini-3.1-flash-lite"
            persona_key = "secret_egg"
            tool_results = {}
            draw_intent = image_gen_engine.detect_draw_intent(問題)
            if draw_intent:
                img_allowed, img_resv, img_used, img_limit = await quota_service.reserve_image_quota(interaction.user.id)
                if img_allowed and img_resv:
                    try:
                        img_res = await image_gen_engine.generate_image(
                            prompt=draw_intent.prompt,
                            style=draw_intent.style,
                            aspect_ratio=draw_intent.aspect_ratio,
                            model="gemini-2.5-flash-image",
                            verify_download=True,
                        )
                        if img_res.success and (img_res.image_url or img_res.image_bytes):
                            await quota_service.commit_image_quota(img_resv)
                            generated_image_url = img_res.image_url
                            generated_image_bytes = img_res.image_bytes
                        else:
                            await quota_service.release_image_quota(img_resv)
                    except Exception as ige:
                        await quota_service.release_image_quota(img_resv)
                        log.warning(f"Image generation error in secret egg ask_command: {ige}")
        else:
            # Get active persona & model: User profile > Guild settings > default 'zeronexus'
            persona_key = "zeronexus"
            user_model = None
            async with db.session() as session:
                stmt = select(UserProfile).where(UserProfile.user_id == interaction.user.id)
                res = await session.execute(stmt)
                profile = res.scalars().first()
                if profile:
                    if profile.preferred_persona:
                        persona_key = profile.preferred_persona
                    if profile.preferred_model:
                        user_model = profile.preferred_model
                elif interaction.guild_id:
                    g_stmt = select(GuildSettings).where(GuildSettings.guild_id == interaction.guild_id)
                    g_res = await session.execute(g_stmt)
                    g_settings = g_res.scalars().first()
                    if g_settings:
                        if g_settings.ai_persona:
                            persona_key = g_settings.ai_persona
                        if g_settings.ai_model:
                            user_model = g_settings.ai_model

            system_instruction = prompt_engine.compile_full_prompt(active_persona_key=persona_key, target_model=user_model)
            is_model_inquiry = any(kw in 問題.lower() for kw in ["模型清單", "有哪些模型", "有什麼模型", "支援什麼模型", "支援哪些模型", "模型有哪些"]) or ("模型" in 問題 and model_catalog.find_category_by_name(問題))
            if is_model_inquiry:
                system_instruction += "\n\n" + model_catalog.get_natural_knowledge_context()

            # Grounded tool execution results container
            tool_results = {}

            # Deterministic CWA Meteorological & Seismic Auto-Router
            cwa_intent = cwa_service.detect_intent(問題)
            if cwa_intent:
                try:
                    await InteractionResponder.safe_edit(
                        interaction,
                        card=ZNCard(
                            title="⛅ 正在取得即時氣象與地震情資...",
                            description="正在向中央氣象署檢索最新觀測數據...",
                            status_pill=ZNStatusPill.PROCESSING,
                            color=ZNColor.AI,
                        ),
                    )
                except Exception:
                    pass
                try:
                    cwa_res = await cwa_service.execute_cwa_tool(
                        intent=cwa_intent,
                        request_id=f"slash-{interaction.id}",
                    )
                    tool_name = f"cwa_{cwa_intent.intent_type.value}"
                    tool_results[tool_name] = cwa_res["grounding_prompt"]
                    system_instruction += f"\n\n{cwa_res['grounding_prompt']}"
                except Exception:
                    pass

            # Deterministic Math & Sandbox Auto-Router
            math_expr = None
            math_match = re.search(
                r"(?:請幫我|幫我)?(?:運算|計算|算一下|求)\s*([0-9\+\-\*\/\^\(\)\.\s×÷\*\*]+?)(?:\s*(?:等於多少|等於幾|是多少|\=\?|\=|\?|$))",
                問題,
                re.IGNORECASE,
            )
            if not math_match:
                math_match = re.search(
                    r"([0-9\+\-\*\/\^\(\)\.\s×÷\*\*]{3,})\s*(?:等於多少|等於幾|是多少|\=\?)",
                    問題,
                )
            if not math_match and 問題.startswith(("運算", "計算")):
                candidate = re.sub(r"^(?:運算|計算)\s*", "", 問題).strip()
                if candidate:
                    math_expr = candidate
            elif math_match:
                math_expr = math_match.group(1).strip()

            if math_expr and any(op in math_expr for op in ["+", "-", "*", "/", "^", "×", "÷"]):
                try:
                    await InteractionResponder.safe_edit(
                        interaction,
                        card=ZNCard(
                            title="📊 正在沙盒繪製圖表...",
                            description="正在沙盒執行高精度數值運算與資料解析...",
                            status_pill=ZNStatusPill.PROCESSING,
                            color=ZNColor.AI,
                        ),
                    )
                except Exception:
                    pass
                try:
                    from zeronexus.engines.calculator import calculator
                    clean_math = math_expr.replace("×", "*").replace("÷", "/").replace("^", "**").strip()
                    exact_val = await calculator.calculate(clean_math)
                    math_grounding = (
                        f"\n\n【系統核心高精度數學事實（絕對嚴格精準真值）】：\n"
                        f"使用者詢問的算式「{math_expr}」經由 Python 任意精度數學沙盒計算出的嚴格精準結果為：\n"
                        f"「{exact_val}」\n"
                        f"請以此絕對正確之數值為唯一真值，以您當前人格語氣自然、生動且清楚地回答使用者，切勿自行心算或篡改任何數字。"
                    )
                    system_instruction += math_grounding
                    tool_results["高精度數學引擎"] = f"算式: {math_expr}, 結果: {exact_val}"
                except Exception as ce:
                    log.info(f"Math auto-eval bypassed in ask_command: {ce}")
            elif any(kw in 問題.lower() for kw in ["畫圖表", "繪製圖表", "圖表", "折線圖", "柱狀圖", "圓餅圖", "python", "沙盒"]):
                try:
                    await InteractionResponder.safe_edit(
                        interaction,
                        card=ZNCard(
                            title="📊 正在沙盒繪製圖表...",
                            description="正在沙盒環境中分析資料與執行運算...",
                            status_pill=ZNStatusPill.PROCESSING,
                            color=ZNColor.AI,
                        ),
                    )
                except Exception:
                    pass

            # Deterministic AI Image Generation Auto-Router
            draw_intent = image_gen_engine.detect_draw_intent(問題)
            if draw_intent:
                img_allowed, img_resv, img_used, img_limit = await quota_service.reserve_image_quota(interaction.user.id)
                if not img_allowed:
                    tool_name = "ai_image_generation"
                    grounding_text = (
                        f"\n\n【系統提示：AI 繪圖額度已達上限】：\n"
                        f"使用者今日之 AI 生圖額度已達上限（每人每天最多生成 3 張，目前已使用 {img_used}/{img_limit} 張）。\n"
                        f"請以您當前的人格語氣，親切、溫和且禮貌地告知使用者今日生圖額度已用完（每人每日 3 張限制），"
                        f"並說明額度將於每日凌晨 00:00 (台灣時間 / UTC+8) 自動重設補充，歡迎使用者明日再來繪圖，或繼續與您進行文字暢聊！"
                    )
                    tool_results[tool_name] = grounding_text
                    system_instruction += grounding_text
                else:
                    try:
                        await InteractionResponder.safe_edit(
                            interaction,
                            card=ZNCard(
                                title="🎨 正在為您繪製影像...",
                                description=f"正在調用影像生成模型繪製作品（`{draw_intent.prompt[:50]}`）...",
                                status_pill=ZNStatusPill.PROCESSING,
                                color=ZNColor.AI,
                            ),
                        )
                    except Exception:
                        pass
                    try:
                        img_res = await image_gen_engine.generate_image(
                            prompt=draw_intent.prompt,
                            style=draw_intent.style,
                            aspect_ratio=draw_intent.aspect_ratio,
                            model="gemini-2.5-flash-image",
                            verify_download=True,
                        )
                        if img_res.success and (img_res.image_url or img_res.image_bytes):
                            if img_resv:
                                await quota_service.commit_image_quota(img_resv)
                            generated_image_url = img_res.image_url
                            generated_image_bytes = img_res.image_bytes
                            tool_name = "ai_image_generation"
                            grounding_text = (
                                f"\n\n【系統已成功調用繪圖引擎為使用者繪製影像】：\n"
                                f"- 圖片網址: {img_res.image_url}\n"
                                f"- 繪圖主體: {img_res.prompt}\n"
                                f"- 藝術風格: {img_res.style or '寫實自然'}\n"
                                f"- 畫面比例: {img_res.aspect_ratio} ({img_res.width}x{img_res.height})\n"
                                f"- 繪圖模型: {img_res.model.upper()}\n"
                                f"請以您當前的人格語氣，親切、熱情且生動地為使用者介紹這幅繪圖作品的畫面構圖、光影氛圍與色彩細節！"
                            )
                            tool_results[tool_name] = grounding_text
                            system_instruction += grounding_text
                        else:
                            if img_resv:
                                await quota_service.release_image_quota(img_resv)
                    except Exception as ige:
                        if img_resv:
                            await quota_service.release_image_quota(img_resv)
                        log.warning(f"Image generation auto-router error in ask_command: {ige}")

            # Deterministic Live Web Search Auto-Router
            search_query = detect_search_intent(問題)
            if search_query:
                try:
                    await InteractionResponder.safe_edit(
                        interaction,
                        card=ZNCard(
                            title="🔍 正在即時連網檢索...",
                            description=f"正在檢索最新網路資訊（`{search_query}`）...",
                            status_pill=ZNStatusPill.PROCESSING,
                            color=ZNColor.AI,
                        ),
                    )
                except Exception:
                    pass
                try:
                    search_res = await web_client.search(search_query, num_results=3)
                    if search_res.get("status") == "SUCCESS" and search_res.get("results"):
                        tool_name = "live_web_search"
                        res_lines = []
                        for r in search_res["results"]:
                            title = r.get("title", "")
                            url = r.get("url", "")
                            snippet = r.get("snippet", "")
                            res_lines.append(f"- [{title}]({url})\n  摘要: {snippet}")
                        grounding_text = (
                            f"\n\n【系統已執行即時聯網搜尋（檢索詞：{search_query}）】：\n"
                            + "\n".join(res_lines)
                            + "\n請參考上述最新網路檢索資訊，以自然、流暢且專業的人格口吻為使用者解答。"
                        )
                        tool_results[tool_name] = grounding_text
                        system_instruction += grounding_text
                except Exception as wse:
                    log.warning(f"Web search auto-router error in ask_command: {wse}")

            # Deterministic Conversational AI Feature Auto-Router (22 Killer Features)
            feature = detect_conversational_feature(問題)
            if feature:
                system_instruction += f"\n\n{feature.system_directive}"
                tool_results[f"feature_{feature.id}"] = f"已啟用專屬對話模式：{feature.name}"

        messages = await context_builder.build_messages(
            user=interaction.user,
            channel=interaction.channel,
            guild=interaction.guild,
            user_prompt=問題,
            tool_results=tool_results,
            is_shared_ai_channel=False,
            active_persona_key=persona_key if not is_secret_easter_egg else None,
            is_secret_easter_egg=is_secret_easter_egg,
        )

        try:
            ai_res, fallback_notice = await ai_gateway.generate_response(
                system_instruction=system_instruction,
                messages=messages,
                override_model=user_model,
                images=images,
                disable_safety=is_secret_easter_egg,
            )

            # Auto persist memories
            await context_builder.save_interaction_memories(
                user=interaction.user,
                channel=interaction.channel,
                guild=interaction.guild,
                user_content=問題,
                assistant_content=ai_res.text,
                is_shared_ai_channel=False,
                is_secret_easter_egg=is_secret_easter_egg,
            )

            if is_secret_easter_egg:
                egg_card = ZNCard(
                    title=f"✨ 絕密彩蛋領域 ➔ {interaction.user.display_name}",
                    description=ai_res.text,
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.PURPLE,
                    footer_text="✨ ZeroNexus Secret Vault • 專屬私密空間",
                )
                egg_file: Optional[discord.File] = None
                if generated_image_bytes:
                    egg_file = discord.File(io.BytesIO(generated_image_bytes), filename="ai_image.png")
                    egg_card.set_image("attachment://ai_image.png")
                elif generated_image_url:
                    egg_card.set_image(generated_image_url)
                egg_card.add_section("🧠 運行模型", "Gemini 3.1 Flash Lite", inline=True)
                egg_card.add_section("🛡️ 安全防護", "無拘束彩蛋模式", inline=True)
                egg_card.add_section("💾 獨立記憶庫", "500 句隔離記憶", inline=True)
                if egg_file:
                    await InteractionResponder.safe_send(interaction, card=egg_card, file=egg_file)
                else:
                    await InteractionResponder.safe_send(interaction, card=egg_card)
            else:
                from zeronexus.ai_gateway.context_builder import (
                    combine_thinking_and_tools,
                    extract_and_sanitize_ai_response,
                )
                clean_answer, extracted_thinking = extract_and_sanitize_ai_response(ai_res.text)

                # 整合真實模型思維與工具調用脈絡（杜絕空洞虛假的罐頭文字）
                effective_tool_calls = ai_res.tool_calls
                if not effective_tool_calls and tool_results:
                    effective_tool_calls = [{"name": "tool_execution", "args": {}, "result": r} for r in tool_results]
                # 決定是否在前端卡片與操作按鈕中展示思維推演歷程
                channel_key = str(interaction.channel.id) if interaction.channel else ""
                is_deep_active = (
                    deep_thinking_controller.is_enabled(channel_key)
                    or (deep_thinking_controller.parse_intent(問題) == ThinkingIntent.ENABLE)
                    or any(kw in 問題.lower() for kw in ["深度思考", "深層思考", "deep thinking", "深入分析", "動動腦", "認真想", "學霸模式", "超頻思考"])
                )
                has_real_tools = bool(effective_tool_calls)
                if is_deep_active:
                    display_thinking = extracted_thinking
                elif has_real_tools:
                    display_thinking = combine_thinking_and_tools(native_thinking=None, tool_calls=effective_tool_calls)
                else:
                    display_thinking = None

                resp = ZNResponse.ai(
                    answer=clean_answer,
                    model_name=ai_res.model_name,
                    fallback_notice=fallback_notice,
                    persona_name=persona_key,
                    thumbnail_url=image_thumbnail,
                    image_url=generated_image_url,
                    thinking_process=display_thinking,
                )
                file_to_send: Optional[discord.File] = None
                if generated_image_bytes and resp.card:
                    file_to_send = discord.File(io.BytesIO(generated_image_bytes), filename="ai_image.png")
                    resp.card.set_image("attachment://ai_image.png")
                elif generated_image_url and resp.card:
                    resp.card.set_image(generated_image_url)

                from zeronexus.engines.community_suite import SmartActionView
                action_view = SmartActionView.evaluate_actions(
                    query=問題,
                    answer=clean_answer,
                    thinking_process=display_thinking,
                )

                if file_to_send:
                    await InteractionResponder.safe_send(interaction, card=resp.card, view=action_view, file=file_to_send)
                else:
                    await InteractionResponder.safe_send(interaction, card=resp.card, view=action_view)

            # Commit quota upon successful response
            if reservation:
                await quota_service.commit_quota(reservation)

        except Exception:
            if reservation:
                await quota_service.release_quota(reservation)
            err_card = ZNCard(
                title="AI 思考服務暫時忙碌中",
                description=(
                    "很抱歉，當前雲端 AI 推理模型節點反應較慢或正在進行線路維護，暫時未能順利生成回覆。\n\n"
                    "💡 **您可以嘗試**：\n"
                    "• 稍候約 10~30 秒後重新送出問題\n"
                    "• 使用 `/人工智慧 切換模型` 切換至其他備援模型（如 DeepSeek 或 Gemini）\n"
                    "• 簡化您的提問或縮減附加圖片大小後再次嘗試"
                ),
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=err_card)

    @ai_group.command(name="生圖", description="運用 AI 生成高品質視覺影像或藝術插圖")
    @app_commands.describe(
        提示詞="欲生成的圖片畫面詳細描述 (例如: 雨夜中的霓虹貓咪、浮空島嶼上的古代神殿)",
        風格="選擇繪圖藝術風格 (如寫實攝影、二次元動漫、奇幻插圖、賽博龐克等)",
        寬高比="選擇圖片寬高比例 (1:1 正方形, 16:9 橫向, 9:16 直向, 4:3 標準)",
        模型="選擇繪圖模型 (Google Gemini 官方多模態圖像模型)",
    )
    @app_commands.choices(風格=[
        app_commands.Choice(name="寫實攝影 (超高解析度寫實細節)", value="寫實攝影"),
        app_commands.Choice(name="二次元動漫 (日系動漫與精緻賽璐珞)", value="二次元動漫"),
        app_commands.Choice(name="奇幻插圖 (魔幻氛圍與概念美術)", value="奇幻插圖"),
        app_commands.Choice(name="賽博龐克 (未來科幻與霓虹光影)", value="賽博龐克"),
        app_commands.Choice(name="像素藝術 (16-bit 復古像素遊戲風)", value="像素藝術"),
        app_commands.Choice(name="3D渲染 (虛幻引擎5立體光線追蹤)", value="3D渲染"),
        app_commands.Choice(name="復古水彩 (典雅水彩渲染與手繪筆觸)", value="復古水彩"),
        app_commands.Choice(name="無特殊風格 (維持原始提示詞描繪)", value="無"),
    ])
    @app_commands.choices(寬高比=[
        app_commands.Choice(name="1:1 (正方形，適合頭像與社群貼文)", value="1:1"),
        app_commands.Choice(name="16:9 (橫向寬螢幕，適合電腦桌布與背景)", value="16:9"),
        app_commands.Choice(name="9:16 (直向手機桌布，適合全螢幕展示)", value="9:16"),
        app_commands.Choice(name="4:3 (經典標準橫幅)", value="4:3"),
    ])
    @app_commands.choices(模型=[
        app_commands.Choice(name="Google Gemini 2.5 Flash Image (官方旗艦多模態)", value="gemini-2.5-flash-image"),
    ])
    @command_guard("ai")
    async def image_gen_command(
        self,
        interaction: discord.Interaction,
        提示詞: str,
        風格: Optional[str] = "寫實攝影",
        寬高比: Optional[str] = "1:1",
        模型: Optional[str] = "gemini-2.5-flash-image",
    ) -> None:
        提示詞 = 提示詞.strip()
        if not 提示詞:
            await InteractionResponder.safe_send(
                interaction,
                "💡 請輸入您想生成的圖片畫面描述，例如「雨夜霓虹街道中的賽博貓咪」。",
                ephemeral=True,
            )
            return

        # Check image quota & atomic 3-phase reservation (Max 3/day)
        allowed, reservation, projected_used, effective_limit = await quota_service.reserve_image_quota(interaction.user.id)
        if not allowed:
            await InteractionResponder.safe_send(
                interaction,
                f"🎨 今日 AI 繪圖額度已用罄（每日上限 3 張），請於明日凌晨 00:00 刷新後再次嘗試！\n"
                f"每人每天最多生成 3 張圖片，生成完畢後今日無法再生成。\n"
                f"（今日已生成：`{projected_used}/{effective_limit}` 張）",
                ephemeral=True,
            )
            return

        await InteractionResponder.safe_defer(interaction)

        target_style = None if 風格 == "無" else 風格
        try:
            res = await image_gen_engine.generate_image(
                prompt=提示詞,
                style=target_style,
                aspect_ratio=寬高比 or "1:1",
                model=模型 or "flux",
                verify_download=True,
            )
            if res.success and (res.image_url or res.image_bytes):
                if reservation:
                    await quota_service.commit_image_quota(reservation)

                card = ZNCard(
                    title="AI 藝術圖像生成完成",
                    description=f"🎨 **生成提示詞**：\n> {res.prompt}",
                    status_pill=ZNStatusPill.AI,
                    color=ZNColor.PURPLE,
                    footer_text=f"ZeroNexus Visual Engine • Model: {res.model.upper()} • Seed: {res.seed}",
                )
                card.add_section("風格設定", res.style or "無特定風格", inline=True)
                card.add_section("畫面比例", f"{res.aspect_ratio} ({res.width}x{res.height})", inline=True)
                card.add_section("生成模型", res.model.upper(), inline=True)

                file_to_send = None
                if res.image_bytes:
                    file_to_send = discord.File(io.BytesIO(res.image_bytes), filename="ai_image.png")
                    card.set_image("attachment://ai_image.png")
                elif res.image_url:
                    card.set_image(res.image_url)

                if file_to_send:
                    await InteractionResponder.safe_send(interaction, card=card, file=file_to_send)
                else:
                    await InteractionResponder.safe_send(interaction, card=card)
            else:
                if reservation:
                    await quota_service.release_image_quota(reservation)
                err_msg = res.error_message or "繪圖伺服器目前忙碌中，請稍候片刻後重試"
                err_card = ZNCard(
                    title="AI 生圖服務暫時忙碌中",
                    description=f"很抱歉，繪圖伺服器節點目前反應異常或連線逾時：\n`{err_msg}`\n\n💡 建議您可以稍候數秒後重試，或嘗試微調提示詞內容！",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                await InteractionResponder.safe_send(interaction, card=err_card)
        except Exception as e:
            if reservation:
                await quota_service.release_image_quota(reservation)
            log.error(f"Image generation command failed: {e}")
            err_card = ZNCard(
                title="AI 生圖生成失敗",
                description=f"處理生圖時遭遇未預期的錯誤：`{str(e)}`",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=err_card)

    @ai_group.command(name="切換模型", description="切換個人或伺服器 AI 模型 (支援 Qwen、DeepSeek、Gemini)")
    @app_commands.describe(模型="輸入或選擇欲使用的 AI 模型 (可留空以開啟互動式選單)", 套用範圍="套用至個人偏好或伺服器全域預設")
    @app_commands.autocomplete(模型=switch_model_autocomplete)
    @command_guard("ai")
    async def switch_model_command(
        self,
        interaction: discord.Interaction,
        模型: Optional[str] = None,
        套用範圍: Literal["個人偏好", "伺服器預設"] = "個人偏好",
    ) -> None:
        from zeronexus.ai_gateway.model_switch_service import model_switch_service
        from zeronexus.ui.responder import InteractionResponder
        from zeronexus.ui.model_select_view import ModelSelectView

        is_server = (套用範圍 == "伺服器預設")
        if is_server:
            if not interaction.guild_id or not interaction.guild:
                await InteractionResponder.safe_send(
                    interaction,
                    "🏠 「伺服器預設模型」僅限在 Discord 伺服器文字頻道中設定。\n💡 若您在私訊中使用，請將「套用範圍」選擇為「個人偏好」即可！",
                    ephemeral=True,
                )
                return

            perm_level = PermissionEngine.resolve_level(interaction.user, interaction.guild)
            if perm_level.value < ZNPermissionLevel.ADMINISTRATOR.value:
                await InteractionResponder.safe_send(
                    interaction,
                    "🛡️ 變更伺服器全域預設模型需要伺服器管理員權限。\n💡 若您想使用自己喜歡的模型，可以將「套用範圍」設定為「個人偏好」，隨時自由切換喔！",
                    ephemeral=True,
                )
                return

        if not 模型:
            await InteractionResponder.safe_defer(interaction, ephemeral=True)
            menu_view = await ModelSelectView.create(
                user_id=interaction.user.id,
                guild_id=interaction.guild_id,
                is_server=is_server,
            )
            card = ZNCard(
                title="✨ AI 核心推論模型切換選單",
                subtitle="請從下方選單挑選欲使用的模型（包含各模型今日專屬獨立餘額）",
                description="ZeroNexus 全面支援 **Google Gemini、DeepSeek、阿里通義 Qwen** 及各大頂尖旗艦。\n選擇後將即刻套用至您的設定！",
                status_pill=ZNStatusPill.AI,
                color=ZNColor.AI,
            )
            await InteractionResponder.safe_send(interaction, card=card, view=menu_view, ephemeral=True)
            return

        switch_res = await model_switch_service.switch_model(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            target_query=模型,
            is_server_level=is_server,
        )
        card = switch_res.to_card()
        # Attach per-model quota info
        from zeronexus.ai_gateway.quota_service import quota_service
        target_mid = (
            getattr(switch_res, "canonical_model_id", None)
            or getattr(switch_res, "resolved_model", None)
            or getattr(switch_res, "active_model", None)
            or 模型
        )
        try:
            quota_info = await quota_service.get_user_model_quota(interaction.user.id, target_mid)
            if quota_info["is_dev"]:
                q_desc = "今日額度：無上限 (開發者特權)"
            else:
                q_desc = f"今日該模型額度剩餘：`{quota_info['remaining']}/{quota_info['limit']}` 次"
            card.add_section("📊 模型額度資訊", q_desc)
        except Exception as q_err:
            log.warning(f"Failed to query per-model quota for {target_mid}: {q_err}")

        await InteractionResponder.safe_send(
            interaction,
            card=card,
            ephemeral=(not switch_res.is_success),
        )

    @ai_group.command(name="模型目錄", description="檢視目前支援的 AI 模型分類與代表性模型")
    @command_guard("ai")
    async def model_catalog_command(self, interaction: discord.Interaction) -> None:
        from zeronexus.ui.model_select_view import ModelSelectView

        card = ZNCard(
            title="ZeroNexus AI 支援模型目錄",
            description="ZeroNexus 動態整合各大頂級旗艦與開源推理模型，您可透過自然語言、下方選單或 `/人工智慧 切換模型` 自由選擇：",
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        categories = model_catalog.list_categories()
        for cat_key, cat_name in categories.items():
            models = model_catalog.get_models_in_category(cat_key)
            model_strs = [f"`{m['name']}`" for m in models[:4]]
            card.add_section(f"💠 {cat_name}", "、".join(model_strs) if model_strs else "依供應商動態提供", inline=False)

        await InteractionResponder.safe_defer(interaction)
        menu_view = await ModelSelectView.create(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            is_server=False,
        )
        await InteractionResponder.safe_send(interaction, card=card, view=menu_view)

    @ai_group.command(name="設定頻道", description="指定此頻道為 AI 共享對話頻道")
    @command_guard("ai", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def set_channel_command(self, interaction: discord.Interaction, 頻道: Optional[discord.TextChannel] = None) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "🏠 AI 共享對話頻道功能專為社群設計，請在伺服器頻道中執行此指令。", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction)
        target_ch = 頻道 or interaction.channel
        if not target_ch or not hasattr(target_ch, "id"):
            await InteractionResponder.safe_send(interaction, "🔍 系統找不到您指定的頻道，請確認頻道是否存在且機器人具備發言權限。", ephemeral=True)
            return

        async with db.session() as session:
            stmt = select(GuildSettings).where(GuildSettings.guild_id == interaction.guild_id)
            res = await session.execute(stmt)
            settings = res.scalars().first()
            if not settings:
                settings = GuildSettings(guild_id=interaction.guild_id, ai_channel_id=target_ch.id)
                session.add(settings)
            else:
                settings.ai_channel_id = target_ch.id

        card = ZNCard(
            title="AI 專屬對話頻道已就緒",
            description=(
                f"已成功將 {target_ch.mention} 設定為本伺服器的 AI 共享對話頻道！\n\n"
                "💬 **使用特色**：\n"
                "• 伺服器成員在此頻道發送的訊息都將直接與 AI 展開互動\n"
                "• 群體歷史發言會自動作為上下文記憶，讓對話更具連貫性\n"
                "• 管理員可隨時使用 `/人工智慧 頻道記憶重置` 或 `/人工智慧 移除頻道` 進行管理"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @ai_group.command(name="移除頻道", description="解除當前頻道的 AI 專用頻道綁定")
    @command_guard("ai", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def unset_channel_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "🏠 此設定僅限在 Discord 伺服器內操作。", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction)
        async with db.session() as session:
            stmt = select(GuildSettings).where(GuildSettings.guild_id == interaction.guild_id)
            res = await session.execute(stmt)
            settings = res.scalars().first()
            if settings:
                settings.ai_channel_id = None

        card = ZNCard(
            title="已解除 AI 專用頻道綁定",
            description="本頻道已恢復為一般文字頻道，成員後續可隨時使用 `/人工智慧 對話` 指令與 AI 進行互動。",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @ai_group.command(name="頻道記憶重置", description="清空當前頻道的 AI 共享對話歷史記憶")
    @command_guard("ai", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def reset_channel_memory_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild_id:
            await InteractionResponder.safe_send(interaction, "🏠 頻道共享記憶重置僅限於伺服器文字頻道中執行。", ephemeral=True)
            return

        channel_id = getattr(interaction.channel, "id", None) or interaction.channel_id
        if not channel_id:
            await InteractionResponder.safe_send(interaction, "🔍 無法辨認當前頻道的識別碼，請在文字頻道中重新發送指令。", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction)
        async with db.session() as session:
            stmt = delete(ConversationMemory).where(
                ConversationMemory.channel_id == channel_id,
                ConversationMemory.scope == "channel_shared",
            )
            res = await session.execute(stmt)
            cnt = res.rowcount or 0

        card = ZNCard(
            title="頻道共享記憶已順利重置",
            description=(
                f"已為頻道 <#{channel_id}> 整理並清空了 `{cnt}` 筆短期對話記憶！\n"
                "接下來發送的新訊息將會開啟一段全新的主題對話，不會再受先前的舊話題干擾。"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    PERSONA_NAMES: dict[str, str] = {
        "zeronexus": "ZeroNexus (預設管家)",
        "01_cat": "可愛貓咪",
        "02_asian_parents": "亞洲長輩",
        "03_mage": "奇幻法師",
        "04_manager": "嚴謹主管",
        "05_jokester": "幽默樂子人",
        "06_teacher": "耐心導師",
        "07_engineer": "資深工程師",
        "08_genius": "冷靜天才",
        "09_friend": "暖心摯友",
        "10_detective": "敏銳偵探",
        "11_future_ai": "未來科技",
        "12_gamer": "遊戲狂熱",
        "13_poet": "文學雅士",
        "14_buddhist": "淡定禪者",
        "15_consultant": "戰略顧問",
    }

    @ai_group.command(name="切換人格", description="切換 AI 互動人格角色 (共 16 款)")
    @app_commands.describe(人格="選擇想要切換的人格", 套用範圍="設定為個人偏好（所有與您的對話/AI頻道），或是全伺服器預設（需管理員）")
    @app_commands.choices(人格=[
        app_commands.Choice(name="ZeroNexus (官方預設)", value="zeronexus"),
        app_commands.Choice(name="可愛貓咪", value="01_cat"),
        app_commands.Choice(name="亞洲長輩", value="02_asian_parents"),
        app_commands.Choice(name="奇幻法師", value="03_mage"),
        app_commands.Choice(name="嚴謹主管", value="04_manager"),
        app_commands.Choice(name="幽默樂子人", value="05_jokester"),
        app_commands.Choice(name="耐心導師", value="06_teacher"),
        app_commands.Choice(name="資深工程師", value="07_engineer"),
        app_commands.Choice(name="冷靜天才", value="08_genius"),
        app_commands.Choice(name="暖心摯友", value="09_friend"),
        app_commands.Choice(name="敏銳偵探", value="10_detective"),
        app_commands.Choice(name="未來科技", value="11_future_ai"),
        app_commands.Choice(name="遊戲狂熱", value="12_gamer"),
        app_commands.Choice(name="文學雅士", value="13_poet"),
        app_commands.Choice(name="淡定禪者", value="14_buddhist"),
        app_commands.Choice(name="戰略顧問", value="15_consultant"),
    ])
    @app_commands.choices(套用範圍=[
        app_commands.Choice(name="個人偏好（所有與您的對話/AI頻道個人優先）", value="user"),
        app_commands.Choice(name="全伺服器預設（設定AI頻道預設人格，需管理員）", value="guild"),
    ])
    @command_guard("ai")
    async def persona_set_command(
        self,
        interaction: discord.Interaction,
        人格: str,
        套用範圍: str = "user",
    ) -> None:
        is_ephemeral = (套用範圍 == "user")
        await InteractionResponder.safe_defer(interaction, ephemeral=is_ephemeral)
        target_name = self.PERSONA_NAMES.get(人格, 人格)

        if 套用範圍 == "guild":
            if not interaction.guild:
                await InteractionResponder.safe_send(interaction, "🏠 全伺服器預設人格僅限在伺服器文字頻道中設定。\n💡 若您在私訊，請選擇「個人偏好」即可！", ephemeral=True)
                return
            is_admin = (
                PermissionEngine.is_developer(interaction.user.id)
                or interaction.guild.owner_id == interaction.user.id
                or (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild)
                or (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
            )
            if not is_admin:
                await InteractionResponder.safe_send(
                    interaction,
                    "🛡️ 變更全伺服器預設人格需要管理員或伺服器擁有者權限。\n💡 您可以選擇「個人偏好」來自由設定專屬於您的人格角色！",
                    ephemeral=True,
                )
                return

            async with db.session() as session:
                stmt = select(GuildSettings).where(GuildSettings.guild_id == interaction.guild_id)
                res = await session.execute(stmt)
                settings = res.scalars().first()
                if not settings:
                    settings = GuildSettings(guild_id=interaction.guild_id, ai_persona=人格)
                    session.add(settings)
                else:
                    settings.ai_persona = 人格

                # Also update user's preference
                u_stmt = select(UserProfile).where(UserProfile.user_id == interaction.user.id)
                u_res = await session.execute(u_stmt)
                prof = u_res.scalars().first()
                if not prof:
                    prof = UserProfile(user_id=interaction.user.id, preferred_persona=人格)
                    session.add(prof)
                else:
                    prof.preferred_persona = 人格

            card = ZNCard(
                title="AI 伺服器預設人格已更新",
                description=(
                    f"全伺服器預設人格已成功切換為：**{target_name}** (`{人格}`)。\n"
                    "在此伺服器 AI 頻道發言的所有未個別指定人格之成員，將以此人格互動。"
                ),
                status_pill=ZNStatusPill.AI,
                color=ZNColor.AI,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=False)
            return

        # Individual user preferred persona (Strictly preserves memory, model preference, and daily quota)
        async with db.session() as session:
            stmt = select(UserProfile).where(UserProfile.user_id == interaction.user.id)
            res = await session.execute(stmt)
            prof = res.scalars().first()
            if not prof:
                prof = UserProfile(user_id=interaction.user.id, preferred_persona=人格)
                session.add(prof)
            else:
                prof.preferred_persona = 人格

        card = ZNCard(
            title="AI 個人偏好人格切換成功",
            description=(
                f"您的專屬預設人格已更新為：**{target_name}** (`{人格}`)。\n"
                "無論在 AI 專用頻道發言，或使用 `/人工智慧 對話`，ZeroNexus 都將優先以您的專屬人格與您對話！"
            ),
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="人格清單", description="瀏覽 16 款內建人格特色與世界觀")
    @command_guard("ai")
    async def persona_list_command(self, interaction: discord.Interaction) -> None:
        await InteractionResponder.safe_defer(interaction)
        card = ZNCard(
            title="ZeroNexus 16 款深度內建人格清單",
            description=(
                "0. **ZeroNexus** (`zeronexus`) — 官方旗艦管家，溫暖理智、清晰嚴謹的全能夥伴\n"
                "1. **可愛貓咪** (`01_cat`) — 親近活潑、輕快傲嬌\n"
                "2. **亞洲長輩** (`02_asian_parents`) — 關心健康作息、實用碎念、溫暖有力\n"
                "3. **奇幻法師** (`03_mage`) — 宏大世界觀、奇幻魔法修辭、答案精準\n"
                "4. **嚴謹主管** (`04_manager`) — 專業幹練、拆解行動清單、高效率聚焦\n"
                "5. **幽默樂子人** (`05_jokester`) — 歡樂生動、梗點豐富、精確吐槽\n"
                "6. **耐心導師** (`06_teacher`) — 極具耐心、循序漸進、循循善誘啟發教學\n"
                "7. **資深工程師** (`07_engineer`) — 硬核嚴謹、重視架構邊界與複雜度權衡\n"
                "8. **冷靜天才** (`08_genius`) — 高冷言簡意賅、直擊核心痛點\n"
                "9. **暖心摯友** (`09_friend`) — 真誠同理心、情緒支持與堅定陪伴\n"
                "10. **敏銳偵探** (`10_detective`) — 演繹推理、抽絲剝繭追查問題核心\n"
                "11. **未來科技** (`11_future_ai`) — 次世代系統架構視角、前瞻技術感\n"
                "12. **遊戲狂熱** (`12_gamer`) — 熟稔各類遊戲黑話與名場面比喻\n"
                "13. **文學雅士** (`13_poet`) — 典雅辭藻、意境優美、富有詩意\n"
                "14. **淡定禪者** (`14_buddhist`) — 從容淡定、安撫焦慮、化解複雜難題\n"
                "15. **戰略顧問** (`15_consultant`) — 全局視野與長遠戰略評估、決策導向"
            ),
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @ai_group.command(name="炸裂功能", description="瀏覽 22 款全新 AI 炸裂對話功能矩陣與玩法示範")
    @command_guard("ai")
    async def killer_features_command(self, interaction: discord.Interaction) -> None:
        await InteractionResponder.safe_defer(interaction)
        card = ZNCard(
            title="ZeroNexus 22 款全新 AI 炸裂對話功能矩陣",
            subtitle="⚡ 智慧意圖自動辨識，無需繁瑣指令，隨說隨切換！",
            description=(
                "在 AI 專用頻道聊天或使用 `/人工智慧 對話` 時，只要在句子中包含對應意圖或關鍵字，"
                "ZeroNexus 便會**自動偵測並注入專屬專家指令**，讓對話品質全面炸裂！"
            ),
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        card.add_section(
            "🔬 【學術調研與深度思辨】(4 款)",
            (
                "• 🔬 **深度網頁研究** (`deep_research`)：多源交叉速讀與綜合情報提煉\n"
                "  ↳ 觸發關鍵字：`深度研究`、`交叉查證`、`深研`\n"
                "• ⚔️ **辯論大師** (`debate_master`)：魔鬼代言人，邏輯思維對撞\n"
                "  ↳ 觸發關鍵字：`跟我辯論`、`反方視角`、`打臉我`\n"
                "• 🏛️ **蘇格拉底哲學思辨** (`socratic_inquiry`)：產婆術反詰逼近本質\n"
                "  ↳ 觸發關鍵字：`蘇格拉底模式`、`哲學思辨`、`探討本質`\n"
                "• 💡 **費曼學習法小導師** (`feynman_tutor`)：小學生聽得懂的日常神比喻\n"
                "  ↳ 觸發關鍵字：`用小學生聽得懂的話解釋`、`費曼解釋`、`白話說明`"
            ),
        )
        card.add_section(
            "💻 【軟體工程與 AI 提示】(2 款)",
            (
                "• 🛡️ **極客代碼審查** (`code_review`)：OWASP 漏洞與架構效能審計\n"
                "  ↳ 觸發關鍵字：`審查程式碼`、`code review`、`找漏洞`、`安全審計`\n"
                "• 🎯 **提示詞工程精煉大師** (`prompt_optimizer`)：重構工業級頂級 Prompt\n"
                "  ↳ 觸發關鍵字：`優化這段prompt`、`提示詞工程`、`專業提示詞`"
            ),
        )
        card.add_section(
            "✍️ 【創意寫作與社群爆款】(3 款)",
            (
                "• 🎨 **迷因梗圖文案** (`meme_lab`)：網路爆笑痛點與視覺畫面提示詞\n"
                "  ↳ 觸發關鍵字：`做個迷因`、`梗圖發想`、`meme`、`迷因梗圖`\n"
                "• ✍️ **社群爆款與求生請假** (`viral_copywriter`)：Threads爆款與職場得體信件\n"
                "  ↳ 觸發關鍵字：`幫我寫請假信`、`脆文案`、`Threads爆款`、`離職信`\n"
                "• 🎤 **雙押饒舌作詞** (`rap_rhymes`)：嘻哈 Flow 節奏與雙押/多押韻腳\n"
                "  ↳ 觸發關鍵字：`寫一首押韻的歌`、`饒舌作詞`、`押韻歌詞`、`rap`"
            ),
        )
        card.add_section(
            "🧠 【心理探索與情商僚機】(4 款)",
            (
                "• 🎭 **毒舌吐槽 vs 暖心樹洞** (`roast_or_comfort`)：幽默辛辣開砲或溫柔撫慰\n"
                "  ↳ 觸發關鍵字：`吐槽我`、`毒舌開砲`、`心靈樹洞`、`求安慰`\n"
                "• 🔮 **賽博塔羅占卜** (`cyber_tarot`)：榮格共時性與牌面心靈投影\n"
                "  ↳ 觸發關鍵字：`抽塔羅牌`、`每日占卜`、`賽博算命`、`塔羅`\n"
                "• 🌙 **佛洛伊德夢境解析** (`dream_interpreter`)：精神分析解碼潛意識密信\n"
                "  ↳ 觸發關鍵字：`我做了一個夢`、`解夢`、`夢境解析`\n"
                "• 💘 **情感軍師與情商僚機** (`emotional_wingman`)：解碼潛台詞與多風格回覆\n"
                "  ↳ 觸發關鍵字：`該怎麼回訊息`、`聊天軍師`、`女生說這話是什麼意思`"
            ),
        )
        card.add_section(
            "🚀 【職場生存與高效生產力】(4 款)",
            (
                "• 📝 **會議記錄長文精煉** (`tldr_distiller`)：TL;DR 速讀與 Action Items\n"
                "  ↳ 觸發關鍵字：`總結這段`、`tldr`、`會議記錄整理`、`精煉重點`\n"
                "• 💼 **模擬求職面試官** (`mock_interview`)：專業職位追問與 STAR 原則回饋\n"
                "  ↳ 觸發關鍵字：`模擬面試`、`面試練習`、`考考我面試`\n"
                "• 🌐 **多語情境同聲傳譯** (`polyglot_translator`)：道地母語講法與文化隱喻解析\n"
                "  ↳ 觸發關鍵字：`情境翻譯`、`道地講法`、`口語翻譯`\n"
                "• 🎩 **六頂思考帽頭腦風暴** (`six_hats`)：德·博諾多維橫向思考破局\n"
                "  ↳ 觸發關鍵字：`六頂思考帽`、`全方位分析`、`頭腦風暴`"
            ),
        )
        card.add_section(
            "🌍 【生活風格與時事情報】(5 款)",
            (
                "• 🕵️‍♂️ **假新聞事實驗證雷達** (`fact_checker`)：真相查核與農場文破綻拆解\n"
                "  ↳ 觸發關鍵字：`這是真的嗎`、`查證流言`、`事實查核`、`闢謠`\n"
                "• ✈️ **智慧旅行行程規劃師** (`travel_planner`)：順路動線、體力節奏與在地美食\n"
                "  ↳ 觸發關鍵字：`規劃行程`、`旅遊攻略`、`自由行規劃`\n"
                "• 🏋️ **健身增肌減脂飲食教練** (`fitness_coach`)：計算 TDEE、巨量配比與超負荷課表\n"
                "  ↳ 觸發關鍵字：`健身菜單`、`減脂飲食`、`計算TDEE`、`增肌課表`\n"
                "• 📡 **今日時事科技熱點雷達** (`daily_radar`)：全球科技焦點與前瞻戰略洞察\n"
                "  ↳ 觸發關鍵字：`今天有什麼大事`、`科技熱點`、`今日新聞雷達`\n"
                "• 🎲 **文字冒險 TRPG 跑團** (`trpg_game`)：沉浸式賽博地下城 DM 與 D20 檢定\n"
                "  ↳ 觸發關鍵字：`開始冒險`、`文字RPG`、`TRPG`、`跑團`"
            ),
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @ai_group.command(name="好感度", description="查看你與 ZeroNexus 之間的心靈羈絆、隱性好感度與專屬印象評價")
    @command_guard("ai")
    async def affinity_command(self, interaction: discord.Interaction) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        from zeronexus.engines.affinity_engine import affinity_engine
        card = await affinity_engine.build_affinity_card(interaction.user.id, interaction.user.display_name)
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="自訂人格", description="透過表單建立您專屬的客製化人格")
    @command_guard("ai")
    async def persona_create_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AIProfileModal())

    @ai_group.command(name="刪除自訂人格", description="刪除已建立的自訂人格")
    @app_commands.describe(人格名稱="要刪除的人格名稱")
    @command_guard("ai")
    async def persona_delete_command(self, interaction: discord.Interaction, 人格名稱: str) -> None:
        clean_name = 人格名稱.strip()
        if not clean_name:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲刪除的人格名稱。", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        async with db.session() as session:
            stmt = delete(CustomPersonaModel).where(
                CustomPersonaModel.created_by_user_id == interaction.user.id,
                CustomPersonaModel.name == clean_name,
            )
            res = await session.execute(stmt)
            deleted = res.rowcount > 0

        if deleted:
            card = ZNCard(
                title="自訂人格已移除",
                description=f"已成功刪除您建立的人格角色 **「{clean_name}」**。",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
        else:
            card = ZNCard(
                title="未找到該人格角色",
                description=(
                    f"系統在您的自訂清單中找不到名為 **「{clean_name}」** 的人格角色。\n\n"
                    "💡 **您可以嘗試**：\n"
                    "• 使用 `/人工智慧 人格清單` 檢視所有內建人格\n"
                    "• 確認自訂人格的名稱大小寫與標點符號是否完全相符"
                ),
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.WARNING,
            )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="記憶檢視", description="檢視 ZeroNexus 為您保存的長期事實記憶")
    @command_guard("ai")
    async def memory_view_command(self, interaction: discord.Interaction) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        is_secret = config.is_secret_channel(interaction.channel_id)
        target_scope = "secret_long_term" if is_secret else "user_long_term"
        async with db.session() as session:
            stmt = select(ConversationMemory).where(
                ConversationMemory.scope == target_scope,
                ConversationMemory.user_id == interaction.user.id,
            )
            res = await session.execute(stmt)
            memories = res.scalars().all()

        scope_label = "絕密彩蛋專屬" if is_secret else "個人"
        if not memories:
            card = ZNCard(
                title=f"目前尚無{scope_label}長期事實記憶",
                description=(
                    f"ZeroNexus 目前尚未在{scope_label}空間為您記錄任何長期的個人事實記憶。\n\n"
                    "💡 **小秘訣**：\n"
                    "在日常對話中，只要向 AI 提及您的偏好、暱稱或習慣（例如「請記住我喜歡用繁體中文回覆」），AI 就會為您自動記住喔！"
                ),
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.INFO,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        lines = [f"`#{m.id}` **{m.fact_key or '備忘'}**：{m.content}" for m in memories[:15]]
        card = ZNCard(
            title=f"{scope_label}長期記憶庫 (共 {len(memories)} 筆)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.AI,
            color=ZNColor.PURPLE if is_secret else ZNColor.AI,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="記憶刪除", description="依據條目編號刪除特定長期記憶")
    @app_commands.describe(條目編號="要刪除的記憶 ID")
    @command_guard("ai")
    async def memory_delete_command(self, interaction: discord.Interaction, 條目編號: int) -> None:
        if 條目編號 <= 0:
            await InteractionResponder.safe_send(
                interaction,
                "💡 記憶條目編號必須是大於 0 的正整數。您可以先使用 `/人工智慧 記憶檢視` 查看目前的記憶清單喔！",
                ephemeral=True,
            )
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        is_secret = config.is_secret_channel(interaction.channel_id)
        target_scope = "secret_long_term" if is_secret else "user_long_term"
        async with db.session() as session:
            stmt = delete(ConversationMemory).where(
                ConversationMemory.id == 條目編號,
                ConversationMemory.user_id == interaction.user.id,
                ConversationMemory.scope == target_scope,
            )
            res = await session.execute(stmt)
            deleted = res.rowcount > 0

        if deleted:
            card = ZNCard(
                title="記憶條目已刪除",
                description=f"已成功為您抹除編號 `#{條目編號}` 的長期記憶記錄。",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
        else:
            card = ZNCard(
                title="找不到指定記憶條目",
                description=(
                    f"系統未能在您的記憶庫中找到編號 `#{條目編號}` 的項目。\n\n"
                    "💡 **您可以嘗試**：\n"
                    "• 使用 `/人工智慧 記憶檢視` 重新確認現有的記憶編號清單"
                ),
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.WARNING,
            )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="記憶清空", description="一鍵清空您在 ZeroNexus 所有的長期記憶 (行使遺忘權)")
    @command_guard("ai")
    async def memory_clear_command(self, interaction: discord.Interaction) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        is_secret = config.is_secret_channel(interaction.channel_id)
        target_scope = "secret_long_term" if is_secret else "user_long_term"
        scope_label = "絕密彩蛋" if is_secret else "全域"
        async with db.session() as session:
            stmt = delete(ConversationMemory).where(
                ConversationMemory.user_id == interaction.user.id,
                ConversationMemory.scope == target_scope,
            )
            res = await session.execute(stmt)
            cnt = res.rowcount

        card = ZNCard(
            title=f"{scope_label}長期記憶已全數清空",
            description=(
                f"已依照隱私保護與遺忘權條例，完整抹除了您的 `{cnt}` 筆{scope_label}長期事實記憶。\n"
                "今後 AI 將以初次認識的全新狀態與您互動，您可以隨時建立新的對話記憶！"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    async def _show_user_quota(self, interaction: discord.Interaction) -> None:
        """Shared implementation for /人工智慧 對話額度 and /人工智慧 額度查詢."""
        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        # Strictly uses quota_service (Asia/Taipei UTC+8 and handles in-flight)
        q_info = await quota_service.get_user_quota_info(interaction.user.id)
        used = q_info["used"]
        limit = q_info["limit"]
        is_dev = q_info["is_dev"]
        remaining_str = "無限 (開發者)" if is_dev else f"{q_info['remaining']} 次"
        reset_time_str = q_info.get("reset_time", "每日凌晨 00:00 (台灣時間 / UTC+8)")

        # Query image generation quota (Max 3 / day)
        img_q_info = await quota_service.get_user_image_quota_info(interaction.user.id)
        img_used = img_q_info["used"]
        img_limit = img_q_info["limit"]
        img_rem_str = "無限 (開發者)" if is_dev else f"{img_q_info['remaining']} 張"

        desc = (
            f"👤 **查詢使用者**：{interaction.user.mention}\n"
            f"📊 **今日已使用次數**：`{used} / {limit}` 次\n"
            f"✨ **剩餘可用額度**：`{remaining_str}`\n"
            f"🎨 **今日生圖次數**：`{img_used} / {img_limit}` 張（剩餘 {img_rem_str}）\n"
            f"🕒 **重設時間**：{reset_time_str}"
        )
        card = ZNCard(
            title="AI 免費對話額度狀態",
            description=desc,
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="對話額度", description="檢視個人今日 AI 免費對話額度與刷新時間")
    @command_guard("ai")
    async def quota_status_command(self, interaction: discord.Interaction) -> None:
        await self._show_user_quota(interaction)

    @ai_group.command(name="額度查詢", description="查詢個人今日 AI 免費對話額度 (相容別名)")
    @command_guard("ai")
    async def quota_command(self, interaction: discord.Interaction) -> None:
        await self._show_user_quota(interaction)

    @ai_group.command(name="重設額度", description="重設特定成員今日的 AI 配額 (需要管理員權限)")
    @app_commands.describe(成員="欲重設配額的伺服器成員")
    @command_guard("ai")
    async def quota_reset_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        if not PermissionEngine.check_developer(interaction.user.id):
            await InteractionResponder.safe_send(
                interaction,
                "🛡️ 此操作屬於核心系統級指令，僅限系統開發者與核心管理團隊執行。",
                ephemeral=True,
            )
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        today_str = quota_service.get_today_str()
        await quota_service.reset_user_quota(成員.id, today_str)
        await quota_service.reset_user_image_quota(成員.id, today_str)
        async with db.session() as session:
            stmt = delete(AIQuotaRecord).where(
                AIQuotaRecord.user_id == 成員.id,
                AIQuotaRecord.date_str == today_str,
            )
            await session.execute(stmt)
            stmt_img = delete(AIImageQuotaRecord).where(
                AIImageQuotaRecord.user_id == 成員.id,
                AIImageQuotaRecord.date_str == today_str,
            )
            await session.execute(stmt_img)

        card = ZNCard(
            title="配額已重設完畢",
            description=f"已成功重設成員 {成員.mention} 於 `{today_str}` 的 AI 對話與生圖消耗額度！",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="模型狀態", description="查詢目前支援與啟用的 AI 模型狀態")
    @command_guard("ai")
    async def model_status_command(self, interaction: discord.Interaction) -> None:
        await InteractionResponder.safe_defer(interaction)
        cat = model_catalog.get_catalog()
        lines: List[str] = []
        for mid, mdata in list(cat.items())[:12]:
            lines.append(f"• **{mdata.get('name', mid)}** (`{mid}`) - *{mdata.get('provider', 'N/A')}*")

        card = ZNCard(
            title="支援 AI 模型清單 (精選)",
            description="\n".join(lines) if lines else "目前模型目錄為空。",
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @ai_group.command(name="金鑰狀態", description="查詢 AI 閘道金鑰池運行健康度")
    @command_guard("ai")
    async def key_status_command(self, interaction: discord.Interaction) -> None:
        if not PermissionEngine.check_developer(interaction.user.id):
            await InteractionResponder.safe_send(
                interaction,
                "🛡️ 金鑰池診斷屬於高敏感度系統操作，僅限開發者查閱。",
                ephemeral=True,
            )
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        diag = await ai_gateway.health_check()
        lines: List[str] = []
        for p_name, p_data in diag["providers"].items():
            lines.append(f"**{p_name.upper()}** (共 {p_data['total_keys']} 支金鑰)：")
            for k in p_data["keys"]:
                lines.append(f"  - `{k['masked']}`: {k['state']} (平均延遲: `{k['avg_latency_ms']}ms`)")

        card = ZNCard(
            title="AI 金鑰池健康大盤",
            description="\n".join(lines) if lines else "尚未設定任何 API 金鑰。",
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @ai_group.command(name="對話重置", description="清空當前使用者的短暫對話上下文快取")
    @command_guard("ai")
    async def reset_chat_command(self, interaction: discord.Interaction) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        is_secret = config.is_secret_channel(interaction.channel_id)
        target_scope = "secret_short_term" if is_secret else "user_short_term"
        scope_label = "絕密彩蛋" if is_secret else "日常"
        async with db.session() as session:
            stmt = delete(ConversationMemory).where(
                ConversationMemory.user_id == interaction.user.id,
                ConversationMemory.scope == target_scope,
            )
            await session.execute(stmt)

        card = ZNCard(
            title=f"{scope_label}短期對話已重置",
            description=f"已清除您與 AI 之間的上一輪{scope_label}對話記憶緩衝，現在可以開啟全新話題！",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="思考模式設定", description="切換是否在回覆時展示思考歷程")
    @app_commands.describe(開關="是否展示思考過程")
    @command_guard("ai")
    async def thinking_toggle_command(self, interaction: discord.Interaction, 開關: bool) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        async with db.session() as session:
            stmt = select(UserProfile).where(UserProfile.user_id == interaction.user.id)
            res = await session.execute(stmt)
            prof = res.scalars().first()
            if not prof:
                prof = UserProfile(user_id=interaction.user.id, show_thinking=開關)
                session.add(prof)
            else:
                prof.show_thinking = 開關

        card = ZNCard(
            title=f"思考歷程展示已{'開啟' if 開關 else '關閉'}",
            status_pill=ZNStatusPill.AI,
            color=ZNColor.SUCCESS if 開關 else ZNColor.DARK,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @ai_group.command(name="翻譯助理", description="調用 AI 進行精確多語系翻譯")
    @app_commands.describe(目標語言="目標語系 (例如 英文, 日文, 繁體中文, 德文)", 文字="要翻譯的內容")
    @command_guard("ai")
    async def translate_command(self, interaction: discord.Interaction, 目標語言: str, 文字: str) -> None:
        target_lang = 目標語言.strip()
        text_content = 文字.strip()
        if not target_lang or not text_content:
            await InteractionResponder.safe_send(
                interaction,
                "💡 請提供欲翻譯的目標語系（例如：英文、日文）以及需要翻譯的文字內容。",
                ephemeral=True,
            )
            return
        if len(text_content) > 4000:
            await InteractionResponder.safe_send(
                interaction,
                "📝 欲翻譯的文字長度超過 4000 字元上限囉，建議您可以分段進行翻譯以獲得最佳的翻譯品質。",
                ephemeral=True,
            )
            return

        # Check quota & atomic 3-phase reservation
        is_secret_easter_egg = config.is_secret_channel(interaction.channel_id)
        if is_secret_easter_egg:
            allowed, reservation, projected_used, effective_limit = True, None, 0, 99999
        else:
            allowed, reservation, projected_used, effective_limit = await quota_service.reserve_quota(interaction.user.id)
            if not allowed:
                await InteractionResponder.safe_send(
                    interaction,
                    f"⏳ 您今日的 AI 免費對話額度已達到上限囉 (`{projected_used}/{effective_limit}` 次)。\n系統將於每日凌晨 00:00 (台灣時間 / UTC+8) 自動補充完畢，感謝您的支持與愛用！",
                    ephemeral=True,
                )
                return

        await InteractionResponder.safe_defer(interaction)
        prompt = f"請將以下內容地道精準地翻譯為【{target_lang}】，僅輸出翻譯後的純文字，無須添加任何引言或多餘註釋：\n\n{text_content}"
        try:
            res, fallback = await ai_gateway.generate_response(
                system_instruction="你是一個地道專業的跨國語言翻譯家。",
                messages=[{"role": "user", "content": prompt}],
            )
            if reservation:
                await quota_service.commit_quota(reservation)
            card = ZNCard(
                title=f"翻譯結果 ({目標語言})",
                description=f"**原文**：\n> {文字}\n\n**譯文**：\n{res.text}",
                status_pill=ZNStatusPill.AI,
                color=ZNColor.AI,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception:
            if reservation:
                await quota_service.release_quota(reservation)
            card = ZNCard(
                title="翻譯處理遭遇問題",
                description=(
                    "很抱歉，翻譯助理在解析文字時連線逾時或模型節點忙碌。\n\n"
                    "💡 **您可以嘗試**：\n"
                    "• 稍候數秒後重新嘗試發送翻譯指令\n"
                    "• 嘗試簡化或縮短一次翻譯的文字長度"
                ),
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICog(bot))
