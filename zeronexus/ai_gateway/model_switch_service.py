# ==============================================================================
# ZeroNexus - Enterprise Model Switch & State Decoupling Service
# Enforces the 7 System Invariants, Per-User Locking, and Two-Phase Commit (2PC)
# ==============================================================================

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from zeronexus.core.database import db
from zeronexus.models.user import UserProfile
from zeronexus.models.guild import GuildSettings
from zeronexus.ai_gateway.model_catalog import model_catalog
from zeronexus.ai_gateway.model_registry import ModelSwitchOutcome, model_registry
from zeronexus.ui.card import ZNCard
from zeronexus.ui.theme import ZNColor, ZNStatusPill

log = logging.getLogger("zeronexus.ai_gateway.model_switch_service")


class SwitchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    RESET_TO_DEFAULT = "RESET_TO_DEFAULT"
    FAILED_UNAVAILABLE = "FAILED_UNAVAILABLE"
    FAILED_NOT_FOUND = "FAILED_NOT_FOUND"
    FAILED_PERMISSION = "FAILED_PERMISSION"
    FAILED_PROBE = "FAILED_PROBE"


@dataclass
class ModelSwitchResult:
    """Explicit decoupling of all 6 model dimensions.
    1. requested_model: raw user query or intent
    2. resolved_model: canonical model ID matched by registry/catalog
    3. available_model: model ID verified available by preflight check
    4. preferred_model: persisted database preference (committed only on SUCCESS)
    5. selected_model: model selected for dispatch
    6. actual_model: actual model producing inference (Footer source of truth)
    """
    status: SwitchStatus
    user_id: int
    guild_id: Optional[int]
    requested_model: str
    resolved_model: Optional[str] = None
    available_model: Optional[str] = None
    preferred_model: Optional[str] = None
    selected_model: Optional[str] = None
    actual_model: Optional[str] = None
    display_name: Optional[str] = None
    is_server_level: bool = False
    error_reason: Optional[str] = None
    previous_preference: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status in (SwitchStatus.SUCCESS, SwitchStatus.RESET_TO_DEFAULT)

    @property
    def active_model(self) -> Optional[str]:
        """Backwards-compatible alias for currently active model ID."""
        return self.resolved_model if self.is_success else self.previous_preference

    @property
    def canonical_model_id(self) -> Optional[str]:
        """Backwards-compatible alias for resolved canonical model ID."""
        return self.resolved_model

    def to_card(self) -> ZNCard:
        """Deterministic card generation - strictly code-driven, never AI-simulated."""
        if self.status == SwitchStatus.RESET_TO_DEFAULT:
            scope_str = "伺服器預設" if self.is_server_level else "個人偏好"
            return ZNCard(
                title=f"已恢復系統預設模型 ({scope_str})",
                description=(
                    f"已清除自訂偏好，系統已平滑恢復使用預設模型：\n"
                    f"**預設模型**：`{self.active_model}`\n\n"
                    f"隨時向 ZeroNexus 發言即可開始對話！"
                ),
                status_pill=ZNStatusPill.AI,
                color=ZNColor.SUCCESS,
            )

        if self.status == SwitchStatus.SUCCESS:
            scope_str = "伺服器預設" if self.is_server_level else "個人偏好"
            mid_low = (self.resolved_model or "").lower()

            # Identify model family & brand badge
            brand_badge = "🌐 旗艦核心"
            family_emoji = "✨"
            highlight = "高智慧自然語言與多工推論"
            color = ZNColor.AI

            if "gemini" in mid_low:
                brand_badge = "💎 Google Gemini 次世代生態"
                family_emoji = "💎"
                highlight = "原生百萬超長上下文・全模態極速理解・Google 頂尖架構"
                color = ZNColor.PRIMARY
            elif "deepseek-reasoner" in mid_low or "r1" in mid_low:
                brand_badge = "🔬 DeepSeek 深度思考推理鏈"
                family_emoji = "🔬"
                highlight = "強化學習深度推理・數學演算法邏輯鏈・思維過程透明化"
                color = ZNColor.DARK
            elif "v4-flash-vision" in mid_low or "v4.1" in mid_low or "v4-flash" in mid_low or "v4" in mid_low:
                brand_badge = "👁️ DeepSeek V4 多模態實驗旗艦"
                family_emoji = "👁️"
                highlight = "最新實驗視覺架構・極速圖文關聯感知・尖端探索"
                color = ZNColor.AI
            elif "deepseek" in mid_low:
                brand_badge = "💬 DeepSeek 旗艦對話節點"
                family_emoji = "💬"
                highlight = "671B 總參數 MoE 架構・頂尖程式碼與繁中對話能力"
                color = ZNColor.PRIMARY
            elif "qwen" in mid_low:
                brand_badge = "🇨🇳 阿里通義千問頂級繁中架構"
                family_emoji = "🇨🇳"
                highlight = "開源中文領域最強旗艦・超強繁體語料適配與工具呼叫"
                color = ZNColor.WARNING
            elif "grok" in mid_low:
                brand_badge = "⚡ xAI Grok 馬斯克旗艦生態"
                family_emoji = "⚡"
                highlight = "即時真實視野・敏捷幽默與深度思辨"
                color = ZNColor.WARNING
            elif "gpt-4o" in mid_low:
                brand_badge = "🚀 OpenAI GPT-4o 頂級多模態"
                family_emoji = "🚀"
                highlight = "全能多模態理解・頂尖通用推理與結構化生成"
                color = ZNColor.SUCCESS

            prev_str = f"`{self.previous_preference}`" if self.previous_preference else "系統預設"

            return ZNCard(
                title=f"{family_emoji} AI 模型切換成功 ➔ {scope_str}",
                subtitle=brand_badge,
                description=(
                    f"已成功為您啟用 **{self.display_name or self.resolved_model}**！\n\n"
                    f"📌 **模型規格**：`{self.resolved_model}`\n"
                    f"🌟 **架構亮點**：{highlight}\n"
                    f"🔄 **切換歷程**：{prev_str} ➔ `{self.resolved_model}`\n\n"
                    f"✨ 後續所有對話與推論將即刻由 **{self.display_name or self.resolved_model}** 竭誠為您服務！"
                ),
                status_pill=ZNStatusPill.AI,
                color=color,
            )

        # Failure states
        target = self.display_name or self.requested_model
        return ZNCard(
            title="無法切換至指定模型",
            description=(
                f"目前無法使用 **{target}**。\n\n"
                f"📌 **不可用原因**：{self.error_reason or '該模型目前節點忙碌或提供者暫時離線'}\n"
                f"🛡️ **狀態保護**：系統已自動維持原偏好設定 (`{self.previous_preference or '系統預設'}`)，請放心。\n\n"
                f"💡 **您可以嘗試**：\n"
                f"• 使用 `/人工智慧 模型目錄` 挑選其他穩定運行的模型\n"
                f"• 輸入「換回預設」或使用自動推薦的旗艦模型"
            ),
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )


class ModelSwitchService:
    """Manages transactional model switching and preference lifecycle."""

    _locks: Dict[str, asyncio.Lock] = {}
    _lock_mgr = asyncio.Lock()

    @classmethod
    async def _get_lock(cls, key: str) -> asyncio.Lock:
        async with cls._lock_mgr:
            if key not in cls._locks:
                cls._locks[key] = asyncio.Lock()
            return cls._locks[key]

    @classmethod
    async def _get_user_lock(cls, user_id: int) -> asyncio.Lock:
        return await cls._get_lock(f"user:{user_id}")

    @classmethod
    def is_default_reset_query(cls, text: str) -> bool:
        """偵測自然語言是否為明確請求重設/切換回預設模型。
        
        嚴格實體與動作隔離：
        1. 排除否定句（例如「不要換回預設」）
        2. 排除疑問句（例如「預設模型好用嗎？」、「預設模型是什麼？」）
        3. 排除單純名詞提及（例如「預設模型效能很好」），必須有明確切換/重設動作動詞。
        """
        if not text or not isinstance(text, str):
            return False
        clean = text.strip().lower().replace(" ", "")
        if not clean:
            return False

        # 1. 否定句過濾：若包含否定詞，絕對不可判定為重設意圖
        if any(neg in clean for neg in ("不要", "先不要", "別", "不用", "請勿", "切勿", "不可以", "禁止", "不需要", "dont", "not")):
            return False

        # 2. 疑問句過濾：若包含問號或疑問詞，視為一般對話或詢問，不可觸發重設
        if any(q in clean for q in ("?", "？", "嗎", "嘛", "呢", "好用嗎", "是什麼", "甚麼是", "怎麼樣", "如何", "怎做", "怎麼做", "什麼")):
            return False

        # 3. 完全符合純關鍵字
        if clean in ("預設", "default", "none", "reset", "系統預設"):
            return True

        # 4. 明確動作動詞組合（排除單純名詞「預設模型」與過於寬鬆的「default」子字串匹配）
        reset_action_keywords = [
            "換回預設", "切換回預設", "切換為預設", "切換成預設", "切回預設",
            "恢復預設", "改回預設", "改用預設", "換成預設", "切到預設",
            "重設模型", "重置模型", "重設為預設", "重置為預設",
            "恢復系統預設", "換回系統預設", "使用預設模型", "切換到預設",
            "恢復預設模型", "重設預設模型", "切換回預設模型", "換回預設模型",
            "resetmodel", "resetdefault", "switchtodefault",
        ]
        return any(k in clean for k in reset_action_keywords)

    @classmethod
    def is_switch_intent(cls, text: str) -> bool:
        """偵測自然語言是否為真實且合法的模型切換意圖。
        
        實體與動作嚴格分離規範：
        1. 句子僅提及模型名稱（例如「ChatGPT」、「Gemini」）屬於實體提及（Entity Mention），
           絕對不可直接判定為模型切換！
        2. 強動作動詞約束：切換請求必須明確具備切換動作動詞（例如「切換到」、「換成」、「改用」、
           「切換模型為」、「switch to」等），並搭配目標模型。
        3. 否定句與疑問句過濾：含有否定語氣（「不要切換」、「不要用」）或疑問探詢（「好用嗎」、
           「是什麼」、「怎麼樣」、「？」、「嗎」）者，一律走正常對話通道，不可觸發切換。
        """
        if not text or not isinstance(text, str):
            return False
        # 若為重設預設模型，屬於切換意圖之一
        if cls.is_default_reset_query(text):
            return True
        req = model_catalog.parse_switch_request(text)
        return bool(req and req.is_switch_intent)

    @classmethod
    async def switch_model(
        cls,
        user_id: int,
        guild_id: Optional[int],
        target_query: str,
        is_server_level: bool = False,
    ) -> ModelSwitchResult:
        """Executes a 2-Phase Commit model switch with invariant checks."""
        if is_server_level and not guild_id:
            return ModelSwitchResult(
                status=SwitchStatus.FAILED_PERMISSION,
                user_id=user_id,
                guild_id=None,
                requested_model=target_query,
                resolved_model=None,
                available_model=None,
                preferred_model=None,
                selected_model=None,
                actual_model=None,
                display_name=target_query,
                is_server_level=True,
                error_reason="伺服器預設模型僅能在伺服器群組內設定。",
            )

        lock_key = f"guild:{guild_id}" if (is_server_level and guild_id) else f"user:{user_id}"
        lock = await cls._get_lock(lock_key)
        async with lock:
            # 1. Fetch current preference
            prev_pref: Optional[str] = None
            async with db.session() as s:
                if is_server_level and guild_id:
                    g = await s.get(GuildSettings, guild_id)
                    prev_pref = g.ai_model if g else None
                else:
                    u = await s.get(UserProfile, user_id)
                    prev_pref = u.preferred_model if u else None

            # 2. Check if resetting to default
            if cls.is_default_reset_query(target_query) or target_query.strip().lower() in ("default", "none", "reset", "系統預設"):
                async with db.session() as s:
                    if is_server_level and guild_id:
                        g = await s.get(GuildSettings, guild_id)
                        if g:
                            g.ai_model = None
                            await s.commit()
                    else:
                        u = await s.get(UserProfile, user_id)
                        if u:
                            u.preferred_model = None
                            await s.commit()

                def_model = model_registry.get_active_default_model()
                log.info(f"Model preference reset to default ({def_model}) for user={user_id} guild={guild_id}")
                return ModelSwitchResult(
                    status=SwitchStatus.RESET_TO_DEFAULT,
                    user_id=user_id,
                    guild_id=guild_id,
                    requested_model=target_query,
                    resolved_model=def_model,
                    available_model=def_model,
                    preferred_model=None,
                    selected_model=def_model,
                    actual_model=def_model,
                    display_name=def_model,
                    is_server_level=is_server_level,
                    previous_preference=prev_pref,
                )

            # 3. Resolve target model ID (Check ModelRegistry resolution rules first)
            reg_res = model_registry.resolve(target_query)
            if reg_res.status == "RETIRED":
                return ModelSwitchResult(
                    status=SwitchStatus.FAILED_UNAVAILABLE,
                    user_id=user_id,
                    guild_id=guild_id,
                    requested_model=target_query,
                    resolved_model=reg_res.model.model_id if reg_res.model else None,
                    available_model=None,
                    preferred_model=prev_pref,
                    selected_model=prev_pref,
                    actual_model=prev_pref,
                    display_name=reg_res.model.display_name if reg_res.model else target_query,
                    is_server_level=is_server_level,
                    previous_preference=prev_pref,
                    error_reason=reg_res.message,
                )
            if reg_res.status == "AMBIGUOUS":
                return ModelSwitchResult(
                    status=SwitchStatus.FAILED_NOT_FOUND,
                    user_id=user_id,
                    guild_id=guild_id,
                    requested_model=target_query,
                    resolved_model=None,
                    available_model=None,
                    preferred_model=prev_pref,
                    selected_model=prev_pref,
                    actual_model=prev_pref,
                    display_name=target_query,
                    is_server_level=is_server_level,
                    previous_preference=prev_pref,
                    error_reason=reg_res.message,
                )
            if reg_res.status == "NOT_FOUND" and (
                "系統不會任意猜測其他版本" in reg_res.message
                or "ZeroNexus 目前嚴格僅支援" in reg_res.message
            ):
                return ModelSwitchResult(
                    status=SwitchStatus.FAILED_NOT_FOUND,
                    user_id=user_id,
                    guild_id=guild_id,
                    requested_model=target_query,
                    resolved_model=None,
                    available_model=None,
                    preferred_model=prev_pref,
                    selected_model=prev_pref,
                    actual_model=prev_pref,
                    display_name=target_query,
                    is_server_level=is_server_level,
                    previous_preference=prev_pref,
                    error_reason=reg_res.message,
                )
            if reg_res.status == "RANDOM":
                picked = model_registry.pick_random_available_model()
                if not picked:
                    return ModelSwitchResult(
                        status=SwitchStatus.FAILED_UNAVAILABLE,
                        user_id=user_id,
                        guild_id=guild_id,
                        requested_model=target_query,
                        resolved_model=None,
                        available_model=None,
                        preferred_model=prev_pref,
                        selected_model=prev_pref,
                        actual_model=prev_pref,
                        display_name=target_query,
                        is_server_level=is_server_level,
                        previous_preference=prev_pref,
                        error_reason="目前系統中無可用之 AI 模型。",
                    )
                matched = picked.model_id
            elif reg_res.success and reg_res.model:
                matched = reg_res.model.model_id
            else:
                matched = model_catalog.find_model(target_query)

            if not matched:
                return ModelSwitchResult(
                    status=SwitchStatus.FAILED_NOT_FOUND,
                    user_id=user_id,
                    guild_id=guild_id,
                    requested_model=target_query,
                    resolved_model=None,
                    available_model=None,
                    preferred_model=prev_pref,
                    selected_model=prev_pref,
                    actual_model=prev_pref,
                    display_name=target_query,
                    is_server_level=is_server_level,
                    previous_preference=prev_pref,
                    error_reason=f"在 430+ 款支援模型中找不到與「`{target_query}`」相符的模型名稱。您可以輸入「列出熱門模型」瀏覽清單。",
                )

            model_id = matched
            disp_name = model_registry.get_display_name(model_id)
            all_mods = getattr(model_catalog, "_all_models", [])
            if isinstance(all_mods, list):
                for m in all_mods:
                    if isinstance(m, dict) and m.get("id") == model_id:
                        disp_name = m.get("name", disp_name)
                        break
            elif isinstance(all_mods, dict):
                m = all_mods.get(model_id, {})
                if isinstance(m, dict) and "name" in m:
                    disp_name = m["name"]

            # 4. Check model availability & probe upstream quota (2PC Pre-commit Probe)
            avail_res = model_registry.check_model_availability(model_id)
            if inspect.isawaitable(avail_res):
                avail_res = await avail_res
            if not avail_res.is_available:
                log.warning(
                    f"Model switch rejected for user={user_id}: {model_id} unavailable ({avail_res.reason})"
                )
                fail_status = (
                    SwitchStatus.FAILED_NOT_FOUND
                    if avail_res.status == ModelSwitchOutcome.MODEL_NOT_FOUND
                    else SwitchStatus.FAILED_UNAVAILABLE
                )
                return ModelSwitchResult(
                    status=fail_status,
                    user_id=user_id,
                    guild_id=guild_id,
                    requested_model=target_query,
                    resolved_model=model_id,
                    available_model=None,
                    preferred_model=prev_pref,
                    selected_model=prev_pref,
                    actual_model=prev_pref,
                    display_name=disp_name,
                    is_server_level=is_server_level,
                    previous_preference=prev_pref,
                    error_reason=f"模型 `{disp_name}` 暫時無法使用：{avail_res.reason}。系統已阻斷切換，未更動您的偏好。",
                )

            # 5. Commit phase (Only reached if pre-commit checks pass - Invariant 1 & 2)
            async with db.session() as s:
                if is_server_level and guild_id:
                    g = await s.get(GuildSettings, guild_id)
                    if not g:
                        g = GuildSettings(guild_id=guild_id)
                        s.add(g)
                    g.ai_model = model_id
                    await s.commit()
                else:
                    u = await s.get(UserProfile, user_id)
                    if not u:
                        u = UserProfile(user_id=user_id)
                        s.add(u)
                    u.preferred_model = model_id
                    await s.commit()

            log.info(
                f"Model preference successfully committed: {model_id} for user={user_id} (server={is_server_level})"
            )
            return ModelSwitchResult(
                status=SwitchStatus.SUCCESS,
                user_id=user_id,
                guild_id=guild_id,
                requested_model=target_query,
                resolved_model=model_id,
                available_model=model_id,
                preferred_model=model_id,
                selected_model=model_id,
                actual_model=model_id,
                display_name=disp_name,
                is_server_level=is_server_level,
                previous_preference=prev_pref,
            )


model_switch_service = ModelSwitchService()
