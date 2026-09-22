"""ZeroNexus Model Registry and Lifecycle Architecture.

Provides strict separation between:
1. User-visible Display Name (e.g., 'Gemini 3.8 Flash')
2. Real upstream API Model ID (e.g., 'gemini-3.8-flash', 'google/gemini-2.5-flash')
3. Provider Adapter routing ('gemini', 'openrouter', 'deepseek', etc.)
4. Lifecycle status (ACTIVE, BETA, DEPRECATED, RETIRED, UNAVAILABLE)
5. Capability metadata (text, vision, reasoning, tools)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class ModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BETA = "BETA"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    UNAVAILABLE = "UNAVAILABLE"


class ModelSwitchOutcome(str, Enum):
    SWITCH_SUCCESS = "SWITCH_SUCCESS"              # 驗證可用，偏好設定成功更新
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"            # 查無此模型，不猜測、不切換
    MODEL_RETIRED = "MODEL_RETIRED"                # 模型已退役，推薦現代替代品，不切換
    MODEL_DEPRECATED = "MODEL_DEPRECATED"          # 模型已棄用
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"        # 模型目前無可用金鑰或冷卻中，不切換
    MODEL_NOT_AUTHORIZED = "MODEL_NOT_AUTHORIZED"  # 無權限或付費額度用罄，不切換
    PROVIDER_OFFLINE = "PROVIDER_OFFLINE"          # 提供者整體故障，不切換
    AMBIGUOUS_QUERY = "AMBIGUOUS_QUERY"            # 輸入有多個可能，要求澄清，不切換
    RANDOM_SELECTION = "RANDOM_SELECTION"          # 使用者要求隨便，系統挑選當前可用模型
    FALLBACK_ACTIVE = "FALLBACK_ACTIVE"            # 執行時降級，分開告知


@dataclass
class ModelMetadata:
    """Introspective metadata of a registered model."""
    model_id: str
    display_name: str
    provider: str
    vendor: str
    status: ModelStatus = ModelStatus.ACTIVE
    context_window: int = 128000
    capabilities: Set[str] = field(default_factory=lambda: {"text"})
    is_free: bool = False
    requires_paid_tier: bool = False
    description: str = ""
    replacement_model_id: Optional[str] = None


@dataclass
class ModelAvailabilityResult:
    """Detailed result of real-time model availability verification."""
    is_available: bool
    status: ModelSwitchOutcome
    reason: str
    provider: Optional[str] = None
    model_id: Optional[str] = None
    display_name: Optional[str] = None
    fallback_suggested: Optional[str] = None


@dataclass
class ModelSwitchResult:
    """Result of attempting a model switch operation."""
    outcome: ModelSwitchOutcome
    success: bool
    requested_model: str
    canonical_model_id: Optional[str] = None
    display_name: Optional[str] = None
    reason: str = ""
    candidates: List[ModelMetadata] = field(default_factory=list)


@dataclass
class ResolutionResult:
    """Result of resolving user input string to a model."""
    success: bool
    model: Optional[ModelMetadata] = None
    status: str = "NOT_FOUND"  # EXACT_MATCH, AMBIGUOUS, RETIRED, NOT_FOUND, RANDOM
    candidates: List[ModelMetadata] = field(default_factory=list)
    message: str = ""


class ModelRegistry:
    """Central registry and lifecycle engine for all AI models."""

    def __init__(self) -> None:
        self._models: Dict[str, ModelMetadata] = {}
        self._seed_default_models()

    def _seed_default_models(self) -> None:
        """Seeds canonical models across major vendors with accurate lifecycles."""
        defaults: List[ModelMetadata] = [
            # Top 3 Recommended Flagships (Strictly at the very top of the list)
            # Rank 1 (Default): gemini-3.1-flash-lite
            ModelMetadata(
                model_id="gemini-3.1-flash-lite",
                display_name="Gemini 3.1 Flash Lite",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                is_free=True,
                description="Google 最新高性價比輕量旗艦，具備原生百萬上下文與極致超低延遲（系統全域預設 Rank 1）。",
            ),
            # Rank 2: deepseek/deepseek-v4-flash-vision-exp
            ModelMetadata(
                model_id="deepseek/deepseek-v4-flash-vision-exp",
                display_name="DeepSeek V4 Flash",
                provider="openrouter",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "vision", "reasoning"},
                description="多模態視覺與極速推理實驗旗艦（Rank 2 推薦，V4 Flash / V4.1）。",
            ),
            # Rank 3: qwen/qwen-2.5-72b-instruct
            ModelMetadata(
                model_id="qwen/qwen-2.5-72b-instruct",
                display_name="Qwen 2.5 72B Instruct",
                provider="openrouter",
                vendor="qwen",
                status=ModelStatus.ACTIVE,
                context_window=32768,
                capabilities={"text", "tools", "reasoning"},
                description="阿里通義千問頂級開源旗艦（Rank 3 推薦），具備卓越繁體中文、數學與程式碼綜合能力。",
            ),

            # DeepSeek Series (Recommended: deepseek-v4.1-flash, deepseek-chat, deepseek-r1)
            ModelMetadata(
                model_id="deepseek-v4.1-flash",
                display_name="DeepSeek V4.1 Flash",
                provider="deepseek",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "vision", "reasoning"},
                description="DeepSeek 原生極速推理與多模態旗艦 (V4.1 Flash)。",
            ),
            ModelMetadata(
                model_id="deepseek/deepseek-v4-flash",
                display_name="DeepSeek V4 Flash",
                provider="openrouter",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "vision", "reasoning"},
                description="極速推理與多模態旗艦 (V4 Flash / V4.1)。",
            ),
            ModelMetadata(
                model_id="deepseek-chat",
                display_name="DeepSeek V3",
                provider="deepseek",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=65536,
                capabilities={"text", "tools"},
                description="綜合性旗艦對話模型（DeepSeek 官方原生節點）。",
            ),
            ModelMetadata(
                model_id="deepseek-reasoner",
                display_name="DeepSeek R1",
                provider="deepseek",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=65536,
                capabilities={"text", "reasoning"},
                description="頂尖開源深度思考推理模型（DeepSeek 官方原生節點）。",
            ),
            ModelMetadata(
                model_id="deepseek/deepseek-chat",
                display_name="DeepSeek V3",
                provider="openrouter",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=65536,
                capabilities={"text", "tools"},
                description="綜合性旗艦對話模型，擅長流暢對話與繁體中文寫作。",
            ),
            ModelMetadata(
                model_id="deepseek/deepseek-r1",
                display_name="DeepSeek R1",
                provider="openrouter",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=65536,
                capabilities={"text", "reasoning"},
                description="頂尖開源深度思考推理模型，專精數學與演算法證明。",
            ),
            ModelMetadata(
                model_id="deepseek/deepseek-chat:free",
                display_name="DeepSeek V3 (Free)",
                provider="openrouter",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=65536,
                is_free=True,
                capabilities={"text", "tools"},
                description="DeepSeek V3 免費額度端點。",
            ),
            ModelMetadata(
                model_id="huggingface/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
                display_name="DeepSeek R1 Distill Qwen 32B",
                provider="huggingface",
                vendor="deepseek",
                status=ModelStatus.ACTIVE,
                context_window=65536,
                capabilities={"text", "reasoning"},
                is_free=True,
                description="DeepSeek R1 蒸餾強化推理模型（Hugging Face 官方路由）。",
            ),

            # Google Gemini Series (Native Google API & OpenRouter Routes)
            ModelMetadata(
                model_id="gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                is_free=True,
                description="Google 現役主力極速多模態旗艦，兼具百萬上下文、卓越推理與極低延遲。",
            ),
            ModelMetadata(
                model_id="gemini-2.5-pro",
                display_name="Gemini 2.5 Pro",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 旗艦級思考模型，擅長深度分析、複雜架構設計與程式碼審查。",
            ),
            ModelMetadata(
                model_id="gemini-2.5-flash-lite",
                display_name="Gemini 2.5 Flash Lite",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools"},
                is_free=True,
                description="Google 超輕量極速多模態模型，專為高頻對話與敏捷互動設計。",
            ),
            ModelMetadata(
                model_id="gemini-3.5-flash-lite",
                display_name="Gemini 3.5 Flash Lite",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                is_free=True,
                description="Google 次世代極速輕量旗艦，具備百萬上下文與高敏捷度推論。",
            ),
            ModelMetadata(
                model_id="gemini-3.7-flash",
                display_name="Gemini 3.7 Flash",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 高性能多模態模型，具備混合思維鏈與複雜邏輯求解能力。",
            ),
            ModelMetadata(
                model_id="gemini-3.8-flash",
                display_name="Gemini 3.8 Flash",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 最新一代極速多模態旗艦，具備原生百萬上下文與頂級推理速度。",
            ),
            ModelMetadata(
                model_id="gemini-flash-latest",
                display_name="Gemini Flash Latest",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                is_free=True,
                description="Google 官方自動動態追蹤指向最新的穩定版 Flash 旗艦。",
            ),
            ModelMetadata(
                model_id="gemini-pro-latest",
                display_name="Gemini Pro Latest",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 官方自動動態追蹤指向最新的 Pro 思考推理旗艦。",
            ),
            ModelMetadata(
                model_id="gemini-2.5-flash-image",
                display_name="Gemini 2.5 Flash Image",
                provider="gemini",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=65536,
                capabilities={"text", "vision", "image_generation"},
                description="Google 多模態圖像生成與視覺創作核心模型。",
            ),
            ModelMetadata(
                model_id="google/gemini-3.1-flash-lite",
                display_name="Gemini 3.1 Flash Lite",
                provider="openrouter",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 最新高性價比輕量旗艦 (OpenRouter 路由)。",
            ),
            ModelMetadata(
                model_id="google/gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                provider="openrouter",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools"},
                description="Google 成熟穩定版極速多模態模型 (OpenRouter 路由)。",
            ),
            ModelMetadata(
                model_id="google/gemini-2.5-pro",
                display_name="Gemini 2.5 Pro",
                provider="openrouter",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 旗艦級思考模型 (OpenRouter 路由)。",
            ),
            ModelMetadata(
                model_id="google/gemini-3.7-flash",
                display_name="Gemini 3.7 Flash",
                provider="openrouter",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 混合推理多模態旗艦 (OpenRouter 路由)。",
            ),
            ModelMetadata(
                model_id="google/gemini-3.8-flash",
                display_name="Gemini 3.8 Flash",
                provider="openrouter",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                capabilities={"text", "vision", "tools", "reasoning"},
                description="Google 最新一代極速多模態旗艦 (OpenRouter 路由)。",
            ),
            ModelMetadata(
                model_id="google/gemini-2.0-flash-exp:free",
                display_name="Gemini 2.0 Flash (Free)",
                provider="openrouter",
                vendor="google",
                status=ModelStatus.ACTIVE,
                context_window=1048576,
                is_free=True,
                capabilities={"text", "vision"},
                description="Google 免費百萬上下文極速模型 (OpenRouter 免費節點)。",
            ),

            # Manus AI Series
            ModelMetadata(
                model_id="manus",
                display_name="Manus AI Agent",
                provider="manus",
                vendor="manus",
                status=ModelStatus.ACTIVE,
                context_window=128000,
                capabilities={"text", "reasoning", "tools", "vision"},
                description="Manus 自主通用 AI Agent，專為複雜多步驟推理與自動化任務設計。",
            ),

            # Cohere Command Series
            ModelMetadata(
                model_id="command-r-plus-08-2024",
                display_name="Command R+ (08-2024)",
                provider="cohere",
                vendor="cohere",
                status=ModelStatus.ACTIVE,
                context_window=128000,
                capabilities={"text", "reasoning", "tools"},
                description="Cohere 頂級旗艦多語言模型，具備 128k 上下文與卓越的檢索增強生成 (RAG) 能力。",
            ),
            ModelMetadata(
                model_id="command-r-08-2024",
                display_name="Command R (08-2024)",
                provider="cohere",
                vendor="cohere",
                status=ModelStatus.ACTIVE,
                context_window=128000,
                capabilities={"text", "reasoning", "tools"},
                description="Cohere 高性價比平衡旗艦，專為高輸送量多語言對話與工作流程設計。",
            ),

            # Mistral AI Series
            ModelMetadata(
                model_id="mistral-large-latest",
                display_name="Mistral Large 2 (Latest)",
                provider="mistral",
                vendor="mistral",
                status=ModelStatus.RETIRED,
                replacement_model_id="codestral-latest",
                context_window=128000,
                capabilities={"text", "reasoning", "tools"},
                description="目前 API 金鑰訂閱等級無法存取此模型，系統自動平滑升級為 Codestral。",
            ),
            ModelMetadata(
                model_id="mistral-small-latest",
                display_name="Mistral Small (Latest)",
                provider="mistral",
                vendor="mistral",
                status=ModelStatus.ACTIVE,
                context_window=32768,
                capabilities={"text", "reasoning"},
                description="Mistral AI 高效能輕量旗艦，兼具極速低延遲與強大推理素質。",
            ),
            ModelMetadata(
                model_id="ministral-8b-latest",
                display_name="Mistral - Ministral 8B (精準極速)",
                provider="mistral",
                vendor="mistral",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "reasoning"},
                description="Mistral 專為邊緣端與極速互動打造的高智商小模型，反應迅捷敏銳。",
            ),
            ModelMetadata(
                model_id="codestral-latest",
                display_name="Codestral (Latest)",
                provider="mistral",
                vendor="mistral",
                status=ModelStatus.ACTIVE,
                context_window=32768,
                capabilities={"text", "tools", "reasoning"},
                description="Mistral 專為程式碼開發特化之頂尖程式碼生成與技術推導模型。",
            ),

            # Groq LPU Ultra-Fast Series
            ModelMetadata(
                model_id="qwen/qwen3.8-27b",
                display_name="Groq - Qwen 3.8 27B (LPU 極速推理)",
                provider="groq",
                vendor="groq",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "reasoning", "tools"},
                description="阿里通義千問 3.8 27B 於 Groq LPU 實現超低延遲極致推演，中文理解與對話反應極快。",
            ),
            ModelMetadata(
                model_id="openai/gpt-oss-120b",
                display_name="Groq - GPT-OSS 120B (超大參開源旗艦)",
                provider="groq",
                vendor="groq",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "reasoning"},
                description="開源千億參旗艦模型於 Groq LPU 極速推理節點，具備頂尖知識儲備與深度邏輯分析。",
            ),
            ModelMetadata(
                model_id="openai/gpt-oss-20b",
                display_name="Groq - GPT-OSS 20B (極速即時推理)",
                provider="groq",
                vendor="groq",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "reasoning"},
                description="輕量化千億架構蒸餾開源模型於 Groq LPU，超低延遲毫秒級回應。",
            ),
            ModelMetadata(
                model_id="llama-3.3-70b-versatile",
                display_name="Groq - Llama 3.3 70B (超高速 LPU)",
                provider="groq",
                vendor="groq",
                status=ModelStatus.RETIRED,
                replacement_model_id="openai/gpt-oss-120b",
                context_window=128000,
                capabilities={"text", "reasoning", "tools"},
                description="Groq 上該模型無存取權或已調整，系統自動平滑升級為 GPT-OSS 120B。",
            ),
            ModelMetadata(
                model_id="deepseek-r1-distill-llama-70b",
                display_name="Groq - DeepSeek R1 70B (深度推理)",
                provider="groq",
                vendor="groq",
                status=ModelStatus.RETIRED,
                replacement_model_id="openai/gpt-oss-120b",
                context_window=131072,
                capabilities={"text", "reasoning"},
                description="Groq 官方已停止支援 (Decommissioned)，系統自動平滑升級為 GPT-OSS 120B。",
            ),
            ModelMetadata(
                model_id="llama-3.1-8b-instant",
                display_name="Groq - Llama 3.1 8B (即時極速)",
                provider="groq",
                vendor="groq",
                status=ModelStatus.RETIRED,
                replacement_model_id="openai/gpt-oss-20b",
                context_window=128000,
                capabilities={"text"},
                description="系統自動平滑升級為 GPT-OSS 20B。",
            ),

            # Retired / Deprecated Gemini Models
            ModelMetadata(
                model_id="gemini-2.0-flash",
                display_name="Gemini 2.0 Flash",
                provider="gemini",
                vendor="google",
                status=ModelStatus.RETIRED,
                replacement_model_id="gemini-3.8-flash",
                description="Google 舊版模型，已進入退役 (Retired) 狀態。",
            ),
            ModelMetadata(
                model_id="google/gemini-2.0-flash-001",
                display_name="Gemini 2.0 Flash",
                provider="openrouter",
                vendor="google",
                status=ModelStatus.RETIRED,
                replacement_model_id="gemini-3.8-flash",
                description="Google 舊版模型，已進入退役 (Retired) 狀態。",
            ),
            ModelMetadata(
                model_id="gemini-1.5-flash",
                display_name="Gemini 1.5 Flash",
                provider="gemini",
                vendor="google",
                status=ModelStatus.RETIRED,
                replacement_model_id="gemini-3.8-flash",
            ),
            ModelMetadata(
                model_id="gemini-1.5-pro",
                display_name="Gemini 1.5 Pro",
                provider="gemini",
                vendor="google",
                status=ModelStatus.RETIRED,
                replacement_model_id="gemini-2.5-pro",
            ),

            # Qwen Series
            ModelMetadata(
                model_id="qwen/qwq-32b",
                display_name="QwQ 32B (推理特化)",
                provider="openrouter",
                vendor="qwen",
                status=ModelStatus.ACTIVE,
                context_window=32768,
                capabilities={"text", "reasoning"},
                description="阿里開源推理特化模型，專精複雜思考鏈與競賽級代碼邏輯推導。",
            ),
            ModelMetadata(
                model_id="qwen/qwen-2.5-coder-32b-instruct",
                display_name="Qwen 2.5 Coder 32B",
                provider="openrouter",
                vendor="qwen",
                status=ModelStatus.ACTIVE,
                context_window=32768,
                capabilities={"text", "tools"},
                description="專為程式碼生成、重構與代碼除錯打造的專業程式模型。",
            ),
            ModelMetadata(
                model_id="qwen/qwen-2.5-72b-instruct:free",
                display_name="Qwen 2.5 72B (Free)",
                provider="openrouter",
                vendor="qwen",
                status=ModelStatus.ACTIVE,
                context_window=32768,
                is_free=True,
                capabilities={"text", "tools", "reasoning"},
                description="通義千問 72B 免費版，繁中對話與通用理解頂級水準。",
            ),
            ModelMetadata(
                model_id="huggingface/Qwen/Qwen2.5-72B-Instruct",
                display_name="Qwen 2.5 72B Instruct",
                provider="huggingface",
                vendor="qwen",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "tools", "reasoning"},
                is_free=True,
                description="阿里通義千問頂級開源旗艦，具備卓越中文與程式碼能力（Hugging Face 官方路由）。",
            ),
            # OpenRouter Free Fallback & Smart Rotation
            ModelMetadata(
                model_id="openrouter/free",
                display_name="OpenRouter Free Rotation (智慧輪替)",
                provider="openrouter",
                vendor="openrouter",
                status=ModelStatus.ACTIVE,
                context_window=131072,
                capabilities={"text", "tools"},
                is_free=True,
                description="OpenRouter 官方免費用戶端智慧容錯輪替模型，提供最高可用性保障。",
            ),
        ]

        for m in defaults:
            self.register(m)

    def register(self, metadata: ModelMetadata) -> None:
        """Registers or updates a model in the registry."""
        self._models[metadata.model_id.lower()] = metadata

    def get(self, model_id: str) -> Optional[ModelMetadata]:
        """Looks up a model by its exact model ID."""
        if not model_id or not isinstance(model_id, str):
            return None
        clean_id = model_id.strip().lower()
        if not clean_id:
            return None
        res = self._models.get(clean_id)
        if not res and clean_id.startswith("huggingface/"):
            res = self._models.get(clean_id.replace("huggingface/", "", 1))
        return res

    def get_display_name(self, model_id: Optional[str]) -> str:
        """Returns clean human-readable display name for a model ID."""
        if not model_id or not isinstance(model_id, str) or not model_id.strip():
            return "系統預設模型"
        clean_id = model_id.strip()
        meta = self.get(clean_id)
        if meta:
            return meta.display_name
        # Check catalog if available
        try:
            from zeronexus.ai_gateway.model_catalog import model_catalog
            cat_m = next((m for m in getattr(model_catalog, "_all_models", []) if m.get("id", "").lower() == clean_id.lower()), None)
            if cat_m and cat_m.get("name"):
                return cat_m["name"]
        except Exception:
            pass
        # Fallback: prettify raw ID
        clean = clean_id.split("/")[-1].replace(":free", " (Free)").replace("-", " ").title()
        return clean

    def format_footer(self, model_id: Optional[str], provider: Optional[str] = None) -> str:
        """Renders clean, distraction-free footer format: 🤖 {display_name} · {provider_title}."""
        if not model_id or not isinstance(model_id, str) or not model_id.strip():
            return "🤖 系統預設模型 · AI"
        clean_id = model_id.strip()
        meta = self.get(clean_id)
        display_name = meta.display_name if meta else self.get_display_name(clean_id)
        
        prov = provider or (
            meta.provider
            if meta
            else ("openrouter" if "/" in clean_id else ("gemini" if clean_id.startswith("gemini-") else ("deepseek" if clean_id.startswith("deepseek-") else "AI")))
        )
        prov_map = {
            "gemini": "Google",
            "openrouter": "OpenRouter",
            "deepseek": "DeepSeek",
            "huggingface": "Hugging Face",
        }
        prov_title = prov_map.get(prov.lower(), prov.title())
        return f"🤖 {display_name} · {prov_title}"

    def _order_with_top_recommended(self, models: List[ModelMetadata]) -> List[ModelMetadata]:
        """Ensures the top 3 recommended models are strictly at the very top of the list:
        1. Rank 1 (Default): gemini-3.1-flash-lite
        2. Rank 2: deepseek/deepseek-v4-flash-vision-exp
        3. Rank 3: qwen/qwen-2.5-72b-instruct
        """
        top_ids = [
            "gemini-3.1-flash-lite",
            "deepseek/deepseek-v4-flash-vision-exp",
            "qwen/qwen-2.5-72b-instruct",
        ]
        top_models = []
        other_models = []
        model_map = {m.model_id.lower(): m for m in models}

        for tid in top_ids:
            if tid.lower() in model_map:
                top_models.append(model_map[tid.lower()])

        top_id_set = {tid.lower() for tid in top_ids}
        for m in models:
            if m.model_id.lower() not in top_id_set:
                other_models.append(m)

        return top_models + other_models

    def list_active_models(
        self,
        vendor: Optional[str] = None,
        is_free: Optional[bool] = None,
    ) -> List[ModelMetadata]:
        """Returns active models strictly filtered to ONLY: qwen, deepseek, gemini."""
        allowed_vendors = {"qwen", "deepseek", "gemini", "google", "manus", "cohere", "mistral", "groq"}
        res = []
        for m in self._models.values():
            if m.status not in (ModelStatus.ACTIVE, ModelStatus.BETA):
                continue
            v = m.vendor.lower()
            if v not in allowed_vendors:
                continue
            if vendor:
                v_target = vendor.lower()
                if v_target in ("gemini", "google") and v in ("gemini", "google"):
                    pass
                elif v != v_target:
                    continue
            if is_free is not None and m.is_free != is_free:
                continue
            res.append(m)
        return self._order_with_top_recommended(res)

    def list_available_models(self) -> List[str]:
        """相容性別名：返回所有活躍可用的模型 ID 清單。"""
        return [m.model_id for m in self.list_active_models()]

    def check_model_availability(
        self,
        model_id: str,
        key_pools: Optional[Dict[str, Any]] = None,
    ) -> ModelAvailabilityResult:
        """Determines if a model is currently available and verified for real API requests."""
        if not model_id or not isinstance(model_id, str) or not model_id.strip():
            return ModelAvailabilityResult(
                is_available=False,
                status=ModelSwitchOutcome.MODEL_NOT_FOUND,
                reason="未提供有效的模型名稱。",
                provider=None,
                model_id=None,
                display_name="未知模型",
            )
        clean_id = model_id.strip()
        meta = self.get(clean_id)
        provider = meta.provider if meta else ("huggingface" if (clean_id.startswith("huggingface/") or clean_id.startswith("meta-llama/") or clean_id.startswith("Qwen/") or clean_id.startswith("mistralai/")) else ("openrouter" if "/" in clean_id else ("gemini" if clean_id.startswith("gemini-") else ("deepseek" if clean_id.startswith("deepseek-") else "openrouter"))))
        display_name = meta.display_name if meta else self.get_display_name(clean_id)

        # 1. Model existence check
        in_catalog = False
        is_catalog_free = False
        if not meta:
            if "/" in clean_id or clean_id.startswith("gemini-") or "deepseek" in clean_id:
                try:
                    from zeronexus.ai_gateway.model_catalog import model_catalog
                    cat_item = next((m for m in getattr(model_catalog, "_all_models", []) if m.get("id", "").lower() == clean_id.lower()), None)
                    if cat_item:
                        in_catalog = True
                        is_catalog_free = cat_item.get("is_free", False)
                except Exception:
                    pass

            if not in_catalog and not clean_id.startswith("gemini-") and not clean_id.startswith("deepseek-"):
                return ModelAvailabilityResult(
                    is_available=False,
                    status=ModelSwitchOutcome.MODEL_NOT_FOUND,
                    reason=f"系統未收錄模型「{clean_id}」。",
                    provider=provider,
                    model_id=clean_id,
                    display_name=display_name,
                )

        # 2. Lifecycle check
        if meta:
            if meta.status == ModelStatus.RETIRED:
                repl = self.get(meta.replacement_model_id) if meta.replacement_model_id else None
                return ModelAvailabilityResult(
                    is_available=False,
                    status=ModelSwitchOutcome.MODEL_RETIRED,
                    reason=f"模型 `{meta.display_name}` 已正式退役 (Retired)。",
                    provider=provider,
                    model_id=model_id,
                    display_name=display_name,
                    fallback_suggested=repl.model_id if repl else "gemini-3.8-flash",
                )
            if meta.status == ModelStatus.UNAVAILABLE:
                return ModelAvailabilityResult(
                    is_available=False,
                    status=ModelSwitchOutcome.MODEL_UNAVAILABLE,
                    reason=f"模型 `{meta.display_name}` 目前標記為不可用。",
                    provider=provider,
                    model_id=model_id,
                    display_name=display_name,
                )

        # 3. Provider and KeyPool check
        if key_pools is None:
            try:
                from zeronexus.ai_gateway.gateway import ai_gateway
                key_pools = ai_gateway.key_pools
            except Exception:
                key_pools = None

        if key_pools is not None:
            # 智慧跨提供者自動路由（如 DeepSeek 優先原生，若無原生金鑰則自動走 OpenRouter 代理）
            if provider == "deepseek":
                deepseek_active = provider in key_pools and getattr(key_pools[provider], "has_active_keys", False)
                if not deepseek_active:
                    or_pool = key_pools.get("openrouter")
                    if or_pool and getattr(or_pool, "has_active_keys", False):
                        provider = "openrouter"

            if provider not in key_pools:
                prov_title = {"gemini": "Google", "openrouter": "OpenRouter", "deepseek": "DeepSeek", "huggingface": "Hugging Face"}.get(provider, provider.title())
                return ModelAvailabilityResult(
                    is_available=False,
                    status=ModelSwitchOutcome.PROVIDER_OFFLINE,
                    reason=f"{prov_title} 提供者目前未配置 API 金鑰或金鑰全處於冷卻中",
                    provider=provider,
                    model_id=model_id,
                    display_name=display_name,
                )
            pool = key_pools[provider]
            if not pool.has_active_keys:
                if provider == "openrouter" and meta and meta.provider == "deepseek":
                    err_reason = "DeepSeek 與 OpenRouter 提供者目前皆未配置可用 API 金鑰或金鑰全處於冷卻中"
                else:
                    prov_title = {"gemini": "Google", "openrouter": "OpenRouter", "deepseek": "DeepSeek", "huggingface": "Hugging Face"}.get(provider, provider.title())
                    err_reason = f"{prov_title} 提供者目前未配置 API 金鑰或金鑰全處於冷卻中"
                return ModelAvailabilityResult(
                    is_available=False,
                    status=ModelSwitchOutcome.PROVIDER_OFFLINE,
                    reason=err_reason,
                    provider=provider,
                    model_id=model_id,
                    display_name=display_name,
                )

            # Determine if this model requires paid tier
            requires_paid = False
            if provider == "openrouter":
                if meta:
                    requires_paid = not getattr(meta, "is_free", False)
                elif in_catalog:
                    requires_paid = not is_catalog_free
                else:
                    requires_paid = not (":free" in model_id.lower())
            elif meta:
                requires_paid = meta.requires_paid_tier

            # Special check for OpenRouter paid models
            if provider == "openrouter" and requires_paid:
                has_paid_keys = False
                has_key_info = False
                keys_info = pool.get_status_summary() if hasattr(pool, "get_status_summary") else []
                if keys_info and isinstance(keys_info, list):
                    has_key_info = True
                    has_paid_keys = any(
                        k.get("state") == "🟢 正常" and k.get("has_paid_quota", True)
                        for k in keys_info
                    )
                elif hasattr(pool, "_keys") and isinstance(pool._keys, list):
                    has_key_info = True
                    has_paid_keys = any(k.is_available and getattr(k, "has_paid_quota", True) for k in pool._keys)
                elif hasattr(pool, "has_active_paid_keys"):
                    val = pool.has_active_paid_keys()
                    if isinstance(val, bool):
                        has_key_info = True
                        has_paid_keys = val

                if not has_paid_keys and has_key_info:
                    return ModelAvailabilityResult(
                        is_available=False,
                        status=ModelSwitchOutcome.MODEL_NOT_AUTHORIZED,
                        reason="OpenRouter 金鑰無可用付費額度或已達每週預算上限 (403)",
                        provider=provider,
                        model_id=model_id,
                        display_name=display_name,
                    )

        return ModelAvailabilityResult(
            is_available=True,
            status=ModelSwitchOutcome.SWITCH_SUCCESS,
            reason="模型可用且通過前置校驗。",
            provider=provider,
            model_id=model_id,
            display_name=display_name,
        )

    def get_active_default_model(self) -> str:
        """Returns canonical default active model ID."""
        return "gemini-3.1-flash-lite"


    def get_available_models(
        self,
        key_pools: Optional[Dict[str, Any]] = None,
        vendor: Optional[str] = None,
    ) -> List[ModelMetadata]:
        """Returns list of currently active models strictly filtered to ONLY qwen, deepseek, gemini,
        with top 3 recommended models (gemini-3.1-flash-lite, deepseek/deepseek-v4-flash-vision-exp, qwen/qwen-2.5-72b-instruct)
        at the very top of the list."""
        allowed_vendors = {"qwen", "deepseek", "gemini", "google", "manus", "cohere", "mistral", "groq"}
        result = []
        for m in self._models.values():
            if m.status not in (ModelStatus.ACTIVE, ModelStatus.BETA):
                continue
            v = m.vendor.lower()
            if v not in allowed_vendors:
                continue
            if vendor:
                v_target = vendor.lower()
                if v_target in ("gemini", "google") and v in ("gemini", "google"):
                    pass
                elif v != v_target:
                    continue
            avail = self.check_model_availability(m.model_id, key_pools=key_pools)
            if avail.is_available:
                result.append(m)
        return self._order_with_top_recommended(result)

    def pick_random_available_model(
        self,
        key_pools: Optional[Dict[str, Any]] = None,
    ) -> Optional[ModelMetadata]:
        """Selects a random currently available model from the active pool."""
        avail_models = self.get_available_models(key_pools=key_pools)
        if not avail_models:
            return None
        import random
        # Prefer free models if available or first available
        free_models = [m for m in avail_models if m.is_free]
        if free_models:
            return random.choice(free_models)
        return random.choice(avail_models)

    def resolve(self, query: str, current_model_id: Optional[str] = None) -> ResolutionResult:
        """Unambiguously resolves user input to an active model or returns status with candidates."""
        if not query or not isinstance(query, str) or not query.strip():
            return ResolutionResult(success=False, status="NOT_FOUND", message="請輸入欲查詢或切換的模型名稱。")
        q = query.strip().lower()

        # 0. Check random / arbitrary selection intent
        if q in ("隨便", "都可以", "任選", "任意", "隨便挑", "隨便選", "隨便一個", "random", "隨機"):
            return ResolutionResult(
                success=True,
                status="RANDOM",
                message="使用者要求由系統挑選當前可用模型。",
            )

        # 0.5 Check ordinal or context-less deictic references
        if q in ("那個", "這個", "第1個", "第2個", "第3個", "第一個", "第二個", "第三個", "第1款", "第2款", "第3款"):
            return ResolutionResult(
                success=False,
                status="AMBIGUOUS",
                message="請明確指明欲切換的模型名稱（例如：Gemini 3.8 Flash、GPT-4o 或 DeepSeek V3）。",
            )

        # 0.8 Check explicit unknown versions that should never be guessed (e.g., 3.6)
        if re.search(r"\b(?:3\.6|3\.4|2\.4|2\.3|2\.2|2\.1)\b", q):
            return ResolutionResult(
                success=False,
                status="NOT_FOUND",
                message=f"查無相符之模型版本「{query}」，系統不會任意猜測其他版本。",
            )

        # 1. Exact model_id match (優先最高)
        if q in self._models:
            m = self._models[q]
            if m.status == ModelStatus.RETIRED:
                repl = self.get(m.replacement_model_id) if m.replacement_model_id else None
                repl_name = repl.display_name if repl else "Gemini 3.8 Flash"
                return ResolutionResult(
                    success=False,
                    model=m,
                    status="RETIRED",
                    candidates=[repl] if repl else [],
                    message=f"模型 `{m.display_name}` 已退役 (Retired)。推薦使用新一代 **{repl_name}**。",
                )
            return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # 2. Exact display_name match (prefer native provider if multiple, e.g. gemini, deepseek)
        matches = [m for m in self._models.values() if m.display_name.lower() == q]
        if matches:
            m = next((cand for cand in matches if cand.provider in ("gemini", "deepseek", "groq", "mistral")), matches[0])
            if m.status == ModelStatus.RETIRED:
                repl = self.get(m.replacement_model_id) if m.replacement_model_id else None
                repl_name = repl.display_name if repl else "Gemini 3.8 Flash"
                return ResolutionResult(
                    success=False,
                    model=m,
                    status="RETIRED",
                    candidates=[repl] if repl else [],
                    message=f"模型 `{m.display_name}` 已退役 (Retired)。推薦使用新一代 **{repl_name}**。",
                )
            return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # 0.9 Guard: explicitly reject non-supported model families (僅在未註冊時生效)
        if any(b in q for b in ["o3", "o1", "claude", "claud", "sonnet", "haiku", "anthropic", "glm", "kimi", "moonshot", "grok"]):
            cands = [self.get("gemini-3.1-flash-lite"), self.get("deepseek/deepseek-v4-flash-vision-exp"), self.get("qwen/qwen-2.5-72b-instruct")]
            return ResolutionResult(
                success=False,
                status="NOT_FOUND",
                candidates=[c for c in cands if c],
                message=f"ZeroNexus 目前暫不支援「{query}」。推薦使用：Gemini 3.1 Flash Lite、DeepSeek V4 Flash 或 Groq。",
            )

        # Clean potential conversational prefix for direct registry calls
        clean_q = re.sub(
            r"^(?:那你|那麼|那|那我|我就|那就|我想|我要|我想要|請你|請|麻煩你|麻煩|幫我|替我|給我|可以幫我|能否幫我|可否幫我|能否|可以|\s+)*"
            r"(?:切換(?:模型)?(?:成|為|到|至)?|更換(?:模型)?(?:成|為|到|至)?|換成(?:模型)?|換到(?:模型)?|換用(?:模型)?|換為(?:模型)?|換模型|換(?![行業言作算錢衣服季氣檔道臉心洗])|切成|切到|切至|切為|改用(?:模型)?|改為(?:模型)?|改成(?:模型)?|改到(?:模型)?|改至(?:模型)?|轉用(?:模型)?|轉成(?:模型)?|轉到(?:模型)?|選用(?:模型)?|啟用(?:模型)?|使用(?:模型)?)\s*",
            "",
            q,
        ).strip()

        # 3. Explicit Version-Specific Matching (Resolves user's core pain points)
        # Check if user asked for "3.8"
        if re.search(r"^(?:(?:google|gemini)[-_ ]?)?3\.8(?:[-_ ]?flash)?$", clean_q) or clean_q in ("3.8", "3.8 flash", "gemini 3.8", "gemini 3.8 flash"):
            # Target gemini-3.8-flash
            m = self.get("gemini-3.8-flash")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Check if user asked for "3.7"
        if re.search(r"^(?:(?:google|gemini)[-_ ]?)?3\.7(?:[-_ ]?flash)?$", clean_q) or clean_q in ("3.7", "3.7 flash", "gemini 3.7", "gemini 3.7 flash"):
            m = self.get("gemini-3.7-flash")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Check if user asked for "3.1"
        if re.search(r"^(?:(?:google|gemini)[-_ ]?)?3\.1(?:[-_ ]?flash(?:[-_ ]?lite)?)?$", clean_q) or clean_q in ("3.1", "3.1 flash", "gemini 3.1", "gemini 3.1 flash lite"):
            m = self.get("gemini-3.1-flash-lite")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Check if user asked for "3.5"
        if re.search(r"^(?:(?:google|gemini)[-_ ]?)?3\.5(?:[-_ ]?flash(?:[-_ ]?lite)?)?$", clean_q) or clean_q in ("3.5", "3.5 flash", "gemini 3.5", "gemini 3.5 flash", "gemini 3.5 flash lite"):
            m = self.get("gemini-3.5-flash-lite")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Check if user asked for "2.0" (Notice: Retired!)
        if re.search(r"^(?:(?:google|gemini)[-_ ]?)?2\.0(?:[-_ ]?flash(?:[-_ ]?exp)?)?$", clean_q) or clean_q in ("2.0", "gemini 2.0", "2.0 flash"):
            repl = self.get("gemini-3.1-flash-lite")
            return ResolutionResult(
                success=False,
                status="RETIRED",
                candidates=[repl] if repl else [],
                message="Gemini 2.0 系列已正式退役 (Retired)。系統已為您推薦最新一代 **Gemini 3.1 Flash Lite**。",
            )

        # Check for free rotation / openrouter free
        if clean_q in ("free", "openrouter/free", "免費", "自動選模", "智慧輪替") or "openrouter/free" in clean_q:
            m = self.get("openrouter/free")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Check if user asked for "2.5"
        if re.search(r"^(?:(?:google|gemini)[-_ ]?)?2\.5(?:[-_ ]?(?:flash|pro|lite)(?:[-_ ]?lite)?)?$", clean_q) or clean_q in ("2.5", "2.5 flash", "2.5 pro", "2.5 lite", "gemini 2.5", "gemini 2.5 flash", "gemini 2.5 pro"):
            if "pro" in clean_q:
                m = self.get("gemini-2.5-pro") or self.get("google/gemini-2.5-pro")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if "lite" in clean_q:
                m = self.get("gemini-2.5-flash-lite") or self.get("google/gemini-2.5-flash-lite")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            m = self.get("gemini-2.5-flash") or self.get("google/gemini-2.5-flash") or self.get("gemini-3.1-flash-lite")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Check for DeepSeek variants (v4 flash, v4.1 flash, vision exp, r1, v3)
        if any(k in clean_q for k in ("deepseek", "deepseel", "deepsek", "v4", "4.1", "r1")):
            if re.search(r"\bv4\b|\bv4\.?1\b|\bflash\b", clean_q) and ("v4" in clean_q or "4.1" in clean_q):
                m = self.get("deepseek/deepseek-v4-flash-vision-exp") or self.get("deepseek-v4.1-flash") or self.get("deepseek/deepseek-v4-flash")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if re.search(r"^(?:deepseek[-_ ]?)?r1$", clean_q) or clean_q == "r1":
                m = self.get("deepseek/deepseek-r1") or self.get("deepseek-reasoner")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            m = self.get("deepseek/deepseek-chat") or self.get("deepseek-chat")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        if re.search(r"^(?:deepseek[-_ ]?)?r1$", clean_q) or clean_q == "r1":
            m = self.get("deepseek/deepseek-r1") or self.get("deepseek-reasoner")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Check for Qwen variants
        if "qwen" in q or "qwq" in q or "通義" in q or "千問" in q:
            if "coder" in q:
                m = self.get("qwen/qwen-2.5-coder-32b-instruct")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if "qwq" in q:
                m = self.get("qwen/qwq-32b")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            m = self.get("qwen/qwen-2.5-72b-instruct")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # 4. Contextual Gemini Handling
        if "gemini" in q or "谷歌" in q or "google" in q:
            if any(img_k in q for img_k in ("image", "視覺", "生圖", "繪圖", "畫圖")):
                m = self.get("gemini-2.5-flash-image") or self.get("google/gemini-2.5-flash-image")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if "pro-latest" in q or "pro latest" in q:
                m = self.get("gemini-pro-latest")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if "flash-latest" in q or "flash latest" in q:
                m = self.get("gemini-flash-latest")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if re.search(r"\b3\.8\b", q):
                m = self.get("gemini-3.8-flash") or self.get("google/gemini-3.8-flash")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if re.search(r"\b3\.7\b", q):
                m = self.get("gemini-3.7-flash") or self.get("google/gemini-3.7-flash")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if re.search(r"\b3\.5\b", q) or "3.5" in q:
                m = self.get("gemini-3.5-flash-lite") or self.get("google/gemini-3.5-flash-lite")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if re.search(r"\b3\.1\b", q) or "3.1" in q:
                m = self.get("gemini-3.1-flash-lite") or self.get("google/gemini-3.1-flash-lite")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if "pro" in q:
                m = self.get("gemini-2.5-pro") or self.get("gemini-pro-latest") or self.get("google/gemini-2.5-pro")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if "flash" in q and "lite" not in q:
                m = self.get("gemini-2.5-flash") or self.get("gemini-flash-latest") or self.get("google/gemini-2.5-flash")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            if "lite" in q:
                m = self.get("gemini-3.1-flash-lite") or self.get("gemini-2.5-flash-lite")
                if m:
                    return ResolutionResult(success=True, model=m, status="EXACT_MATCH")
            m = self.get("gemini-3.1-flash-lite")
            if m:
                return ResolutionResult(success=True, model=m, status="EXACT_MATCH")

        # Guard: explicitly reject non-supported model families
        if any(b in q for b in ["gpt", "openai", "o3", "o1", "claude", "claud", "sonnet", "haiku", "anthropic", "llama", "meta", "mistral", "mixtral", "codestral", "glm", "kimi", "moonshot", "grok"]):
            cands = [self.get("gemini-3.1-flash-lite"), self.get("deepseek/deepseek-v4-flash-vision-exp"), self.get("qwen/qwen-2.5-72b-instruct")]
            return ResolutionResult(
                success=False,
                status="NOT_FOUND",
                candidates=[c for c in cands if c],
                message=f"ZeroNexus 目前嚴格僅支援 Qwen、DeepSeek 與 Gemini 三大系列模型，不支援「{query}」。推薦使用：Gemini 3.1 Flash Lite、DeepSeek V4 Flash 或 Qwen 2.5 72B。",
            )

        # 5. Active candidate filtering
        active_models = [m for m in self._models.values() if m.status in (ModelStatus.ACTIVE, ModelStatus.BETA)]
        candidates = [m for m in active_models if q in m.display_name.lower() or q in m.model_id.lower()]
        
        # Deduplicate candidates with identical display name, preferring native provider
        unique_cands: Dict[str, ModelMetadata] = {}
        for c in candidates:
            dn = c.display_name.lower()
            if dn not in unique_cands or (unique_cands[dn].provider != "gemini" and c.provider == "gemini"):
                unique_cands[dn] = c
        filtered_cands = list(unique_cands.values())

        if len(filtered_cands) == 1:
            return ResolutionResult(success=True, model=filtered_cands[0], status="EXACT_MATCH")
        elif len(filtered_cands) > 1:
            return ResolutionResult(
                success=False,
                status="AMBIGUOUS",
                candidates=filtered_cands[:5],
                message=f"找到多個相符模型，請指明具體型號：{', '.join([c.display_name for c in filtered_cands[:4]])}",
            )

        cands = [self.get("gemini-3.1-flash-lite"), self.get("deepseek/deepseek-v4-flash-vision-exp"), self.get("qwen/qwen-2.5-72b-instruct")]
        return ResolutionResult(
            success=False,
            status="NOT_FOUND",
            candidates=[c for c in cands if c],
            message=f"查無相符模型「{query}」。ZeroNexus 支援 Qwen、DeepSeek 與 Gemini 三大系列，您可以嘗試切換至 Gemini 3.1 Flash Lite、DeepSeek V4 Flash 或 Qwen 2.5 72B。",
        )


# Global singleton
model_registry = ModelRegistry()
