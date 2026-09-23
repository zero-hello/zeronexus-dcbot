"""OpenRouter Dynamic Model Catalog and Intelligent Discovery Service.

Manages dynamic discovery, background caching, vendor classification,
and natural language model intent mapping for ZeroNexus.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from zeronexus.ai_gateway.model_registry import ModelSwitchOutcome, model_registry
from zeronexus.core.logger import log

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_FILE = BASE_DIR / "data" / "openrouter_models_cache.json"

# Target supported vendor prefixes and categories (嚴格限定僅 Qwen, DeepSeek, Google Gemini)
TARGET_VENDORS = {
    "google": "Google Gemini 系列",
    "deepseek": "DeepSeek 系列",
    "qwen": "通義千問 Qwen 系列",
    "free": "免費體驗專區",
}

# Common brand, codename, and shorthand typos mapping
TYPO_MAP: Dict[str, str] = {
    # DeepSeek
    "deepseel": "deepseek",
    "deepsek": "deepseek",
    "deepseeek": "deepseek",
    "depseek": "deepseek",
    "deepsk": "deepseek",
    "deepseekk": "deepseek",
    "v4.1": "v4-flash",
    "v4.1-flash": "v4-flash",
    "v4.1 flash": "v4-flash",
    # Gemini / Google
    "gemin": "gemini",
    "gemini2": "gemini",
    "gemini3": "gemini",
    "gemn": "gemini",
    "gogole": "google",
    "googl": "google",
    # Qwen
    "qwem": "qwen",
    "qwenn": "qwen",
    "qwen2": "qwen",
    "qwen3": "qwen",
    "qwaen": "qwen",
}

KNOWN_BRANDS: List[str] = [
    "deepseek", "gemini", "qwen", "google",
]


FEATURE_KEYWORDS: List[str] = [
    "v4", "v3.2", "v3.1", "v3", "v2.5", "v2", "v1", "r1",
    "flash", "pro", "mini", "max", "large", "small", "lite",
    "exp", "vision", "chat", "instruct", "70b", "72b", "8b", "32b",
    "3.7", "3.5", "3.3", "3.1", "2.5", "2.0", "4.5", "5.1", "4o", "o3", "o1",
]

NEGATIVE_INTENT_PATTERN = re.compile(
    r"(?:"
    r"(?:不要|先不要|暫時不要|別|不用|請勿|切勿|絕不|千萬別|千萬不要|不可以|禁止|不需要|不可|未要|勿)"
    r"|(?:\b(?:don't|dont|do\s+not|never|not|cannot|no\s+need\s+to)\b)"
    r")",
    re.IGNORECASE,
)

INQUIRY_PATTERN = re.compile(
    r"(?:"
    r"[?？]"
    r"|(?:嗎|嘛|呢|吧[\?？]?)$"
    r"|(?:好用|厲害|強|當機|壞掉|故障|更新|改版|升級|聰明|笨)(?:嗎|嘛|呢|吧)"
    r"|(?:好用嗎|厲害嗎|強嗎|當機了嗎|怎麼樣|怎様|如何|怎做|怎麼做|怎用|怎麼用|如何用|如何使用)"
    r"|(?:是|為)(?:什麼|甚麼|哪種|何種|哪款|哪個)(?:模型|東西|版本)?"
    r"|(?:什麼|甚麼|啥)是"
    r"|要怎麼做"
    r"|(?:可以|能|能否|可否)?(?:使用|用)(?:什麼|甚麼)(?:工具)?"
    r"|有(?:哪些|什麼|甚麼|何種)(?:模型|工具|推薦|差別|不同|限制)?"
    r"|(?:什麼|甚麼)工具"
    r"|支援(?:什麼|甚麼|哪些)"
    r"|(?:可以|能|請)?介紹(?:一下|下)?(?:這個|那個|這款|那款|當前|目前)?模型"
    r"|(?:你知道|聽說|了解|曉得|覺得).+(?:嗎|嘛|呢|如何|怎樣|好用)"
    r"|評價如何|表現如何"
    r"|推薦嗎|推薦哪"
    r"|好不好|好不好用|行不行|行嗎|可以嗎|能切換嗎|可以切換嗎|能換嗎|可以換嗎"
    r"|差別在哪|不同在哪|有何差別|有何不同|哪個好|哪款好|誰比較強|誰比較好"
    r"|\bwhat\s+(?:is|are|model|models|tools)\b"
    r"|\bhow\s+(?:to|do|can|is)\b"
    r"|\bwhich\s+(?:is|one|model)\b"
    r"|\bwhy\b"
    r")",
    re.IGNORECASE,
)

# 日常任務伴隨詞（若前綴為「使用」或「use」，且後續包含這些任務詞，則判定為日常對話而非模型切換）
TASK_ACTION_PATTERN = re.compile(
    r"(?:\b(?:to\s+write|to\s+code|to\s+summarize|to\s+translate|to\s+generate)\b|"
    r"(?:幫我|幫忙|替我|寫|做|算|計算|翻譯|分析|處理|問|查|查詢|搜尋|搜尋一下|畫|畫一張|生成|產生|總結|潤色|修改|優化|重構|測試|閱讀|看|解釋|說明|教我|製作))",
    re.IGNORECASE,
)

SWITCH_PREFIX_PATTERN = re.compile(
    r"^(?:那你|那麼|那|那我|我就|那就|我想|我要|我想要|請你|請|麻煩你|麻煩|幫我|替我|給我|可以幫我|能否幫我|可否幫我|能否|可以|\s+)*"
    r"(?:"
    r"切換(?:模型|到模型|為模型|成模型|至模型)?(?:成|為|到|至)?"
    r"|切換"
    r"|更換(?:模型)?(?:成|為|到|至)?"
    r"|換成(?:模型)?|換到(?:模型)?|換做(?:模型)?|換用(?:模型)?|換為(?:模型)?|換模型(?:為|成|到|至)?|換模型|換(?![行業言作算錢衣服季氣檔道臉心洗法路車手班位胎機輪個點句好話])"
    r"|切成|切到|切至|切為"
    r"|改用(?:模型)?|改為(?:模型)?|改成(?:模型)?|改到(?:模型)?|改至(?:模型)?|改用模型"
    r"|轉用(?:模型)?|轉成(?:模型)?|轉到(?:模型)?|轉至(?:模型)?"
    r"|選用模型|啟用模型|使用模型"
    r"|switch\s*(?:to\s*)?(?:model\s*)?|change\s*(?:to\s*)?(?:model\s*)?|use\s+model\b"
    r"|(?:使用|use)\s*"
    r")\s*",
    re.IGNORECASE,
)

SWITCH_SUFFIX_PATTERN = re.compile(
    r"(?:\s*(?:的)?(?:那個|那款|那台|那支|那種|這款|這台|這個|這支|這種))?"
    r"(?:\s*(?:的)?(?:模型|版本|型號))?"
    r"(?:\s*(?:的)?(?:那個|那款|這款|這個))?"
    r"(?:\s*[吧啦囉喔哦呢阿啊唄耶呀]+)?"
    r"[\s!！?？~～.]*$",
    re.IGNORECASE,
)

SWITCH_INTENT_PATTERN = re.compile(
    r"^(?:那你|那麼|那|那我|我就|那就|我想|我要|我想要|請你|請|麻煩你|麻煩|幫我|替我|給我|可以幫我|能否幫我|可否幫我|能否|可以|\s+)*"
    r"(?:"
    r"切換(?:模型|到模型|為模型|成模型|至模型)?(?:成|為|到|至)?"
    r"|切換"
    r"|更換(?:模型)?(?:成|為|到|至)?"
    r"|換成(?:模型)?|換到(?:模型)?|換做(?:模型)?|換用(?:模型)?|換為(?:模型)?|換模型(?:為|成|到|至)?|換模型|換(?![行業言作算錢衣服季氣檔道臉心洗法路車手班位胎機輪個點句好話])"
    r"|切成|切到|切至|切為"
    r"|改用(?:模型)?|改為(?:模型)?|改成(?:模型)?|改到(?:模型)?|改至(?:模型)?|改用模型"
    r"|轉用(?:模型)?|轉成(?:模型)?|轉到(?:模型)?|轉至(?:模型)?"
    r"|選用模型|啟用模型|使用模型"
    r"|switch\s*(?:to\s*)?(?:model\s*)?|change\s*(?:to\s*)?(?:model\s*)?|use\s+model\b"
    r"|(?:使用|use)\s*"
    r")\s*"
    r"(.+)$",
    re.IGNORECASE,
)

PREFIX_HEURISTICS: List[Tuple[str, str]] = [
    (r"^(?:deepseek[-_ ]?v4[-_ ]?flash[-_ ]?vision[-_ ]?exp|deepseek[-_ ]?v4[-_ ]?flash|deepseek[-_ ]?v4\.?1[-_ ]?flash|deepseek[-_ ]?v4\.?1|v4\.?1[-_ ]?flash|v4\.?1|deepseek[-_ ]?v4)", "deepseek/deepseek-v4-flash-vision-exp"),
    (r"^(?:deepseek[-_ ]?v4[-_ ]?pro)", "deepseek/deepseek-v4-pro-0813"),
    (r"^(?:deepseek[-_ ]?r1|r1\b)", "deepseek/deepseek-r1"),
    (r"^deepseek[-_ ]?(?:v3|chat)?", "deepseek/deepseek-chat"),
    (r"^gemini[-_ ]?3\.?8[-_ ]?flash\b", "gemini-3.8-flash"),
    (r"^gemini[-_ ]?3\.?8\b", "gemini-3.8-flash"),
    (r"^3\.8\b", "gemini-3.8-flash"),
    (r"^gemini[-_ ]?3\.?7[-_ ]?flash\b", "gemini-3.7-flash"),
    (r"^gemini[-_ ]?3\.?7\b", "gemini-3.7-flash"),
    (r"^gemini[-_ ]?3\.?1[-_ ]?flash[-_ ]?lite\b", "gemini-3.1-flash-lite"),
    (r"^gemini[-_ ]?3\.?1\b", "gemini-3.1-flash-lite"),
    (r"^gemini[-_ ]?2\.?5[-_ ]?flash[-_ ]?lite\b", "google/gemini-2.5-flash-lite"),
    (r"^gemini[-_ ]?2\.?5[-_ ]?pro\b", "google/gemini-2.5-pro"),
    (r"^gemini[-_ ]?pro\b", "google/gemini-2.5-pro"),
    (r"^gemini[-_ ]?2\.?5[-_ ]?flash\b", "google/gemini-2.5-flash"),
    (r"^gemini\b", "google/gemini-2.5-flash"),
    (r"^flash\b", "google/gemini-2.5-flash"),
    (r"^qwen[-_ ]?(?:2\.?5[-_ ]?)?72b\b", "qwen/qwen-2.5-72b-instruct"),
    (r"^qwen[-_ ]?2\.?5\b", "qwen/qwen-2.5-72b-instruct"),
    (r"^(?:qwq|qwen)[-_ ]?(?:2\.?5[-_ ]?)?32b\b", "qwen/qwq-32b"),
    (r"^qwq\b", "qwen/qwq-32b"),
    (r"^qwen\b", "qwen/qwen-2.5-72b-instruct"),
]

# Curated core representative models per vendor (嚴格限定僅 Qwen, DeepSeek, Google Gemini)
FEATURED_MODELS_BY_VENDOR: Dict[str, List[Dict[str, str]]] = {
    "google": [
        {
            "id": "gemini-3.1-flash-lite",
            "name": "Gemini 3.1 Flash Lite (系統預設 Rank 1)",
            "features": "Google 官方超高速輕量旗艦，百萬超長上下文、極速反應（系統全域預設 Rank 1）。",
        },
        {
            "id": "gemini-3.5-flash-lite",
            "name": "Gemini 3.5 Flash Lite",
            "features": "Google 次世代高效能架構，極致敏捷推論與高階語意理解。",
        },
        {
            "id": "google/gemini-2.5-flash",
            "name": "Gemini 2.5 Flash (OpenRouter)",
            "features": "百萬級上下文支援，極速反應與優質多模態能力 (OpenRouter 路由)。",
        },
    ],
    "deepseek": [
        {
            "id": "deepseek/deepseek-v4-flash-vision-exp",
            "name": "DeepSeek V4 Flash (Vision Exp / V4.1 - Rank 2)",
            "features": "最新多模態視覺與極速推理旗艦（Rank 2 推薦），兼具長上下文理解與程式編程能力。",
        },
        {
            "id": "deepseek-v4.1-flash",
            "name": "DeepSeek V4.1 Flash (原生)",
            "features": "DeepSeek 官方原生極速推理與多模態旗艦 (V4.1 Flash)。",
        },
        {
            "id": "deepseek-chat",
            "name": "DeepSeek V3 (Chat)",
            "features": "綜合性旗艦對話模型，擅長流暢對話、繁體中文寫作與知識問答。",
        },
        {
            "id": "deepseek-reasoner",
            "name": "DeepSeek R1 (Reasoner)",
            "features": "頂尖開源深度思考推理模型，專精數學定理推導、演算法分析與複雜邏輯鏈。",
        },
        {
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek V3",
            "features": "綜合性旗艦對話模型，擅長流暢對話與繁體中文寫作 (OpenRouter 路由)。",
        },
        {
            "id": "deepseek/deepseek-r1",
            "name": "DeepSeek R1",
            "features": "頂尖開源深度思考推理模型，專精數學與演算法證明 (OpenRouter 路由)。",
        },
    ],
    "qwen": [
        {
            "id": "qwen/qwen-2.5-72b-instruct",
            "name": "Qwen 2.5 72B Instruct (Rank 3)",
            "features": "阿里通義千問頂級開源旗艦（Rank 3 推薦），具備卓越繁體中文、數學與程式碼綜合表現。",
        },
        {
            "id": "qwen/qwq-32b",
            "name": "QwQ 32B (推理特化)",
            "features": "開源推理特化模型，專精複雜思考鏈、競賽數學與程式邏輯。",
        },
        {
            "id": "qwen/qwen-2.5-coder-32b-instruct",
            "name": "Qwen 2.5 Coder 32B",
            "features": "專為程式碼生成、重構與程式除錯打造的專業程式模型。",
        },
        {
            "id": "qwen/qwen-2.5-72b-instruct:free",
            "name": "Qwen 2.5 72B (Free)",
            "features": "通義千問 72B 免費版，繁中對話與通用理解頂級水準。",
        },
    ],
}


@dataclass
class SwitchRequest:
    """Structured result of natural language model switching parsing."""
    is_switch_intent: bool
    raw_model_query: str = ""
    cleaned_model_query: str = ""
    matched_model: Optional[str] = None
    extra_query: str = ""
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    outcome: ModelSwitchOutcome = ModelSwitchOutcome.SWITCH_SUCCESS
    is_random_intent: bool = False
    rejection_reason: str = ""

DEFAULT_FALLBACK_MODELS = {
    "google": [
        {"id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite", "context": 1048576},
        {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite", "context": 1048576},
        {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "context": 1048576},
    ],
    "deepseek": [
        {"id": "deepseek/deepseek-v4-flash-vision-exp", "name": "DeepSeek V4 Flash", "context": 131072},
        {"id": "deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash", "context": 131072},
        {"id": "deepseek-chat", "name": "DeepSeek V3", "context": 65536},
        {"id": "deepseek-reasoner", "name": "DeepSeek R1 (深度思考推論)", "context": 65536},
        {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3", "context": 65536},
        {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 (深度思考推論)", "context": 65536},
    ],
    "qwen": [
        {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B Instruct", "context": 32768},
        {"id": "qwen/qwq-32b", "name": "QwQ 32B (推理特化)", "context": 32768},
        {"id": "qwen/qwen-2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B", "context": 32768},
        {"id": "qwen/qwen-2.5-72b-instruct:free", "name": "Qwen 2.5 72B (Free)", "context": 32768},
    ],
    "free": [
        {"id": "deepseek/deepseek-chat:free", "name": "DeepSeek V3 (Free)", "context": 65536},
        {"id": "google/gemini-2.0-flash-exp:free", "name": "Gemini 2.0 Flash (Free)", "context": 1048576},
        {"id": "qwen/qwen-2.5-72b-instruct:free", "name": "Qwen 2.5 72B (Free)", "context": 32768},
    ],
}


class ModelCatalogService:
    """Dynamic discovery, caching, and natural language categorization of AI models."""

    def __init__(self) -> None:
        self._categories: Dict[str, List[Dict[str, Any]]] = dict(DEFAULT_FALLBACK_MODELS)
        self._all_models: List[Dict[str, Any]] = []
        self._last_refresh_time: float = 0.0
        self._refresh_lock = asyncio.Lock()
        self._load_local_cache()

    def _sort_with_top_recommended(self, models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ensures the top 3 recommended models are strictly at the very top of the list:
        1. Rank 1 (Default): gemini-3.1-flash-lite
        2. Rank 2: deepseek/deepseek-v4-flash-vision-exp
        3. Rank 3: qwen/qwen-2.5-72b-instruct
        """
        top_defaults = [
            {"id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite", "context": 1048576, "is_free": False, "category": "google"},
            {"id": "deepseek/deepseek-v4-flash-vision-exp", "name": "DeepSeek V4 Flash", "context": 131072, "is_free": False, "category": "deepseek"},
            {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B Instruct", "context": 32768, "is_free": False, "category": "qwen"},
        ]
        model_by_id = {m.get("id", "").lower(): m for m in models}
        top_models = []
        top_id_set = set()

        for d in top_defaults:
            tid = d["id"].lower()
            top_id_set.add(tid)
            if tid in model_by_id:
                top_models.append(model_by_id[tid])
            elif tid == "gemini-3.1-flash-lite" and "google/gemini-3.1-flash-lite" in model_by_id:
                top_models.append(model_by_id["google/gemini-3.1-flash-lite"])
                top_id_set.add("google/gemini-3.1-flash-lite")
            else:
                top_models.append(dict(d))

        other_models = [m for m in models if m.get("id", "").lower() not in top_id_set]
        return top_models + other_models

    def _load_local_cache(self) -> None:
        """Loads and categorizes models from local openrouter_models_cache.json if present."""
        if not CACHE_FILE.exists():
            self._flatten_catalog()
            return
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            data = payload.get("data", [])
            if data:
                self._populate_catalog(data)
                log.info(f"ModelCatalog loaded {len(self._all_models)} models from local cache: {CACHE_FILE}")
            else:
                self._flatten_catalog()
        except Exception as e:
            log.warning(f"Failed to load local models cache from {CACHE_FILE}: {e}")
            self._flatten_catalog()

    def _flatten_catalog(self) -> None:
        """Flattens category dict into a searchable list."""
        seen = set()
        flat = []
        for cat, m_list in self._categories.items():
            for m in m_list:
                if m["id"] not in seen:
                    seen.add(m["id"])
                    flat.append({**m, "category": cat})
        self._all_models = self._sort_with_top_recommended(flat)

    def _detect_category(self, mid: str) -> Optional[str]:
        """Maps a model ID to its canonical vendor category (Strictly Qwen, DeepSeek, Google Gemini)."""
        mid_lower = mid.lower()
        if "deepseek" in mid_lower:
            return "deepseek"
        if "google" in mid_lower or "gemini" in mid_lower:
            return "google"
        if "qwen" in mid_lower or "qwq" in mid_lower:
            return "qwen"
        return None

    def _populate_catalog(self, data: List[Dict[str, Any]]) -> None:
        """Parses model data, categorizes vendors, and registers all models into catalog.
        Strictly restricts catalog to only Qwen, DeepSeek, and Google Gemini families.
        """
        new_categories: Dict[str, List[Dict[str, Any]]] = {k: [] for k in TARGET_VENDORS.keys()}
        all_models_map: Dict[str, Dict[str, Any]] = {}

        for item in data:
            mid = item.get("id", "")
            if not mid:
                continue
            cat = self._detect_category(mid)
            if not cat:
                # 嚴格排除非 Qwen, DeepSeek, Google Gemini 系列之所有模型
                continue

            name = item.get("name", mid)
            ctx = item.get("context_length", 4096)
            pricing = item.get("pricing", {})
            prompt_price = float(pricing.get("prompt", 0) or 0)
            completion_price = float(pricing.get("completion", 0) or 0)
            is_free = ":free" in mid or (prompt_price == 0 and completion_price == 0)

            entry = {"id": mid, "name": name, "context": ctx, "is_free": is_free}

            if is_free:
                new_categories["free"].append(entry)
            new_categories[cat].append(entry)
            all_models_map[mid] = {**entry, "category": cat}

        # Ensure fallback presence if upstream or cache returned empty for any vendor
        for k, fallback_list in DEFAULT_FALLBACK_MODELS.items():
            if not new_categories.get(k):
                new_categories[k] = fallback_list
                for fb in fallback_list:
                    if fb["id"] not in all_models_map:
                        all_models_map[fb["id"]] = {**fb, "category": k}

        # Ensure top 3 recommended models are always explicitly present
        top_seed_models = [
            {"id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite", "context": 1048576, "is_free": False, "category": "google"},
            {"id": "deepseek/deepseek-v4-flash-vision-exp", "name": "DeepSeek V4 Flash", "context": 131072, "is_free": False, "category": "deepseek"},
            {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B Instruct", "context": 32768, "is_free": False, "category": "qwen"},
        ]
        for seed in top_seed_models:
            if seed["id"] not in all_models_map:
                all_models_map[seed["id"]] = seed
                if seed["category"] in new_categories:
                    new_categories[seed["category"]].append(seed)

        self._categories = new_categories
        self._all_models = self._sort_with_top_recommended(list(all_models_map.values()))

    async def refresh_catalog(self, api_key: Optional[str] = None, force: bool = False) -> bool:
        """Fetches upstream models from OpenRouter API and dynamically updates catalog."""
        # Refresh interval: 6 hours (21600 seconds)
        now = time.time()
        if not force and (now - self._last_refresh_time < 21600) and self._all_models:
            return True

        async with self._refresh_lock:
            try:
                headers = {"HTTP-Referer": "https://zeronexus.platform", "X-Title": "ZeroNexusTest"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
                    if resp.status_code != 200:
                        log.warning(f"OpenRouter models endpoint returned HTTP {resp.status_code}. Using cached models.")
                        return False

                    data = resp.json().get("data", [])
                    if not data:
                        return False

                    # Non-blocking write back to local cache file upon successful refresh
                    def _write_cache() -> None:
                        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                        with open(CACHE_FILE, "w", encoding="utf-8") as cf:
                            json.dump({"data": data}, cf, ensure_ascii=False)

                    try:
                        await asyncio.to_thread(_write_cache)
                        log.info(f"Synchronized {len(data)} OpenRouter models to local cache: {CACHE_FILE}")
                    except Exception as ce:
                        log.warning(f"Failed to write openrouter_models_cache.json: {ce}")

                    self._populate_catalog(data)
                    self._last_refresh_time = now
                    log.info(f"ModelCatalog successfully updated. Cached {len(self._all_models)} active models across {len(self._categories)} categories.")
                    return True

            except Exception as e:
                log.warning(f"Failed to fetch upstream OpenRouter models: {e}. Preserving current catalog.")
                return False

    def get_catalog(self) -> Dict[str, Dict[str, Any]]:
        """Returns all cached and supported models mapped by model ID."""
        catalog_map: Dict[str, Dict[str, Any]] = {}
        for m in self._all_models:
            mid = m.get("id")
            if not mid:
                continue
            cat = m.get("category", "")
            provider_name = TARGET_VENDORS.get(cat, cat.title() if cat else "AI Provider")
            entry = dict(m)
            entry.setdefault("provider", provider_name)
            catalog_map[mid] = entry
        return catalog_map

    def list_categories(self) -> Dict[str, str]:
        """Returns key to display name mapping of all supported categories."""
        return dict(TARGET_VENDORS)

    def get_models_in_category(self, category_key: str) -> List[Dict[str, Any]]:
        """Returns models belonging to a specific category key."""
        cat = category_key.lower().strip()
        # Aliases
        alias_map = {
            "gemini": "google",
            "免費": "free",
        }
        cat = alias_map.get(cat, cat)
        return self._categories.get(cat, [])

    def clean_natural_query(self, text: str) -> str:
        """Strips conversational switching prefixes, suffixes, and applies typo correction."""
        if not text or not isinstance(text, str):
            return ""
        t = SWITCH_PREFIX_PATTERN.sub("", text)
        t = SWITCH_SUFFIX_PATTERN.sub("", t).strip()
        tokens = re.split(r"([a-zA-Z0-9\.\+]+)", t)
        res = []
        for tok in tokens:
            tl = tok.lower()
            if tl in TYPO_MAP:
                res.append(TYPO_MAP[tl])
            elif tl.isalpha():
                matched_brand = None
                for b in KNOWN_BRANDS:
                    if len(tl) >= 4 and difflib.SequenceMatcher(None, tl, b).ratio() >= 0.85:
                        matched_brand = b
                        break
                res.append(matched_brand if matched_brand else tok)
            else:
                res.append(tok)
        return "".join(res).strip()

    def detect_vendor(self, text: Optional[str]) -> Optional[str]:
        """Detects if text asks about or mentions a specific vendor category (Strictly Qwen, DeepSeek, Google Gemini, Free)."""
        if not text or not isinstance(text, str):
            return None
        t = text.lower()
        if any(k in t for k in ["deepseek", "深度求索"]):
            return "deepseek"
        if any(k in t for k in ["gemini", "谷歌", "google"]):
            return "google"
        if any(k in t for k in ["qwen", "qwq", "通義", "千問"]):
            return "qwen"
        if any(k in t for k in ["free", "免費", "不用錢"]):
            return "free"
        return None

    def find_category_by_name(self, text: str) -> Optional[str]:
        """Detects if user is asking about a specific model brand or category."""
        return self.detect_vendor(text)

    def score_model(self, m: Dict[str, Any], query: str) -> float:
        """Calculates multi-dimensional weighted alignment score for a candidate model."""
        mid = m.get("id", "").lower()
        mname = m.get("name", "").lower()
        mcat = m.get("category", "")
        q_vendor = self.detect_vendor(query)
        q_tokens = [w for w in re.split(r"[\s/_-]+", query.lower()) if w]
        mid_tokens = set(re.split(r"[\s/_-]+", mid))
        mname_tokens = set(re.split(r"[\s/_-]+", mname))
        all_tokens = mid_tokens | mname_tokens

        matched_cnt = 0
        for t in q_tokens:
            if t in all_tokens:
                matched_cnt += 1
            elif any(t in tok for tok in all_tokens):
                matched_cnt += 1

        has_vendor_match = bool(
            q_vendor and (
                q_vendor in mid
                or mcat == q_vendor
                or (q_vendor == "openai" and ("gpt" in mid or "/o3" in mid or "/o1" in mid))
            )
        )

        # Disqualify models if completely zero token overlap and zero vendor match
        if matched_cnt == 0 and not has_vendor_match:
            return -1000.0

        score = 0.0

        # Dimension 1: Vendor match (Highest weight to prevent cross-vendor hijacking)
        if q_vendor:
            if has_vendor_match:
                score += 150.0
            else:
                score -= 300.0

        # Dimension 2: Feature / Version keywords match
        for kw in FEATURE_KEYWORDS:
            if kw in q_tokens:
                if kw in all_tokens or (len(kw) > 2 and kw in mid):
                    score += 40.0
                else:
                    score -= 10.0

        # Version conflict penalties
        if "v4" in q_tokens and ("v3" in all_tokens or "v3.1" in all_tokens or "v3.2" in all_tokens):
            score -= 50.0
        if "flash" in q_tokens and "pro" in all_tokens and "flash" not in all_tokens:
            score -= 30.0
        if "pro" in q_tokens and "flash" in all_tokens and "pro" not in all_tokens:
            score -= 30.0

        # Dimension 3: Token overlap
        for t in q_tokens:
            if t in all_tokens:
                score += 25.0
            elif any(t in tok for tok in all_tokens):
                score += 15.0
        if q_tokens:
            score += (matched_cnt / len(q_tokens)) * 30.0

        # Dimension 4: Character / String sequence similarity
        mid_ratio = difflib.SequenceMatcher(None, query, mid).ratio()
        mname_ratio = difflib.SequenceMatcher(None, query, mname).ratio()
        score += max(mid_ratio, mname_ratio) * 20.0

        # Dimension 5: Exact string bonus
        if query == mid or query == mname:
            score += 200.0
        elif query in mid or query in mname:
            score += 20.0

        # Dimension 6: Batch and alias penalties
        if ":batch" in mid and ":batch" not in query:
            score -= 150.0
        if mid.startswith("~"):
            score -= 15.0

        # Dimension 7: Recency bonus (bounded to +15 max)
        created = m.get("created", 0)
        if created:
            score += min(15.0, max(0.0, (created - 1.7e9) / 1e7 * 1.5))

        return score

    CANONICAL_MAPPING = [
        (r"^(?:deepseek[-_ ]?v4[-_ ]?flash[-_ ]?vision[-_ ]?exp|deepseek[-_ ]?v4[-_ ]?flash|deepseek[-_ ]?v4\.?1[-_ ]?flash|deepseek[-_ ]?v4\.?1|v4\.?1[-_ ]?flash|v4\.?1|v4-flash[-_ ]?flash|v4-flash|deepseek[-_ ]?v4)$", "deepseek/deepseek-v4-flash-vision-exp"),
        (r"^(?:deepseek[-_ ]?v4[-_ ]?pro)$", "deepseek/deepseek-v4-pro-0813"),
        (r"^(?:r1|deepseek[-_ ]?r1)$", "deepseek/deepseek-r1"),
        (r"^(?:deepseek[-_ ]?(?:v3|chat)?|deepseek)$", "deepseek/deepseek-chat"),
        (r"^(?:gemini[-_ ]?3\.?8[-_ ]?flash|gemini[-_ ]?3\.?8|3\.8)$", "gemini-3.8-flash"),
        (r"^(?:gemini[-_ ]?3\.?7[-_ ]?flash|gemini[-_ ]?3\.?7|3\.7)$", "gemini-3.7-flash"),
        (r"^(?:gemini[-_ ]?3\.?1[-_ ]?flash[-_ ]?lite|gemini[-_ ]?3\.?1)$", "gemini-3.1-flash-lite"),
        (r"^(?:gemini[-_ ]?2\.?5[-_ ]?flash[-_ ]?lite)$", "google/gemini-2.5-flash-lite"),
        (r"^(?:gemini[-_ ]?2\.?5[-_ ]?pro|gemini[-_ ]?pro)$", "google/gemini-2.5-pro"),
        (r"^(?:gemini[-_ ]?2\.?5[-_ ]?flash|gemini|flash)$", "google/gemini-2.5-flash"),
        (r"^(?:qwen[-_ ]?(?:2\.?5[-_ ]?)?72b|qwen[-_ ]?2\.?5|qwen)$", "qwen/qwen-2.5-72b-instruct"),
        (r"^(?:(?:qwq|qwen)[-_ ]?(?:2\.?5[-_ ]?)?32b|qwq)$", "qwen/qwq-32b"),
        (r"^(?:qwen[-_ ]?coder)$", "qwen/qwen-2.5-coder-32b-instruct"),
    ]

    def find_canonical_or_exact(self, query: str) -> Optional[str]:
        """Matches query strictly against exact cached model IDs/names or canonical heuristics."""
        if not query or not isinstance(query, str):
            return None
        cleaned = self.clean_natural_query(query)
        q = cleaned.strip().lower()
        if not q:
            return None

        # Guard: explicitly reject non-supported model families
        if any(b in q for b in ["gpt", "openai", "o3", "o1", "claude", "claud", "sonnet", "haiku", "anthropic", "llama", "meta", "mistral", "mixtral", "codestral", "glm", "kimi", "moonshot", "grok"]):
            return None

        # 1. Canonical heuristics for common shorthand & OpenRouter mappings
        for pattern, model_id in self.CANONICAL_MAPPING:
            if re.search(pattern, q):
                return model_id

        # 2. Delegate to ModelRegistry resolution
        reg_res = model_registry.resolve(q)
        if reg_res.success and reg_res.model:
            return reg_res.model.model_id

        # 3. Exact match against cached models
        for m in self._all_models:
            if m["id"].lower() == q or m["name"].lower() == q:
                return m["id"]

        return None

    def find_model(self, query: str, threshold: float = 60.0) -> Optional[str]:
        """Fuzzy and multi-dimensional matches a user's text query to a valid model ID."""
        if not query or not isinstance(query, str):
            return None
        cleaned = self.clean_natural_query(query)
        q = cleaned.strip().lower()
        if not q:
            return None

        # Guard: explicitly reject non-supported model families
        if any(b in q for b in ["gpt", "openai", "o3", "o1", "claude", "claud", "sonnet", "haiku", "anthropic", "llama", "meta", "mistral", "mixtral", "codestral", "glm", "kimi", "moonshot", "grok"]):
            return None

        # Guard: never guess or fuzzy match unknown explicit versions (e.g., 3.6, 2.2)
        if re.search(r"\b(?:3\.6|3\.4|2\.4|2\.3|2\.2|2\.1)\b", q):
            return None

        canonical = self.find_canonical_or_exact(query)
        if canonical:
            return canonical

        # 3. Multi-dimensional weighted scoring over all 430+ cached models
        if self._all_models:
            best_model = max(self._all_models, key=lambda m: self.score_model(m, q))
            if self.score_model(best_model, q) >= threshold:
                return best_model["id"]

        return None

    def get_similar_models(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Returns 2~3 closest models when user input is unrecognized."""
        q = self.clean_natural_query(query).lower()
        candidates = [m for m in self._all_models if ":batch" not in m.get("id", "")]
        if not candidates:
            candidates = self._all_models

        # If a specific brand was mentioned, filter candidates by that brand
        detected_vendor = self.detect_vendor(q)
        if detected_vendor:
            vendor_candidates = [
                m for m in candidates
                if m.get("category") == detected_vendor or detected_vendor in m.get("id", "").lower()
            ]
            if vendor_candidates:
                scored = sorted(vendor_candidates, key=lambda m: self.score_model(m, q), reverse=True)
                return scored[:limit]

        # Score across all candidates
        scored = sorted(candidates, key=lambda m: self.score_model(m, q), reverse=True)
        if scored and self.score_model(scored[0], q) > 0:
            return scored[:limit]

        # Fallback to flagship defaults (Strictly Qwen, DeepSeek, Gemini)
        flagship_ids = [
            "gemini-3.1-flash-lite",
            "deepseek/deepseek-v4-flash-vision-exp",
            "qwen/qwen-2.5-72b-instruct",
        ]
        defaults = [m for m in candidates if m["id"] in flagship_ids]
        defaults.sort(key=lambda m: flagship_ids.index(m["id"]) if m["id"] in flagship_ids else 99)
        if defaults:
            return defaults[:limit]
        return candidates[:limit]

    def is_pure_version_shorthand(self, text: str) -> bool:
        """判斷文字是否為純版本型號縮寫或帶指示代名詞的明確選型（例如 '3.8', 'v4.1 flash', 'r1', 'deepseek v4 flash 的那個'）。
        
        實體與動作嚴格分離：
        AI 品牌或模型族系名稱（如 ChatGPT, Gemini, DeepSeek, Qwen, Claude, GPT 等）
        絕對不視為純版本縮寫，不可在無切換動作動詞時直接觸發切換！
        """
        if not text or not isinstance(text, str):
            return False
        clean_suffix = SWITCH_SUFFIX_PATTERN.sub("", text).strip()
        cleaned = self.clean_natural_query(clean_suffix).strip().lower()
        if not cleaned:
            return False

        # 排除所有單純的 AI 品牌與族系實體名詞（避免實體提及被誤判為切換指令）
        if cleaned in ("gemini", "deepseek", "qwen", "chatgpt", "gpt", "claude", "openai", "llama", "meta", "google", "anthropic"):
            return False

        # 排除包含中文常見動詞或聊天的語句（避免「Gemini 寫程式很強」等進入純型號匹配）
        if re.search(r"[\u4e00-\u9fa5]", cleaned):
            return False

        # 必須包含具體型號版本標識（例如 3.8, v4, v3, 2.5, r1, qwq, 72b 等）
        has_version = bool(re.search(r"(?:\b(?:v\d+|\d+\.\d+|r1|qwq|\d+b)\b|v4-flash)", cleaned))
        if not has_version:
            return False

        # 必須完全相符於純版本模式或 CANONICAL_MAPPING
        if re.fullmatch(r"^(?:(?:v)?\d+(?:\.\d+)?(?:[-_ ]?(?:flash|pro|lite|chat|vision|exp|instruct))*|v4-flash[-_ ]?flash|r1|qwq)$", cleaned):
            return True

        for pattern, _ in self.CANONICAL_MAPPING:
            if re.fullmatch(pattern, cleaned):
                return True

        return False

    def is_explicit_model_name(self, text: str) -> bool:
        """Checks if text strictly and explicitly represents a known model name or canonical ID."""
        if not text or not isinstance(text, str):
            return False
        cleaned = self.clean_natural_query(text).strip()
        q = cleaned.lower()
        if not q:
            return False

        # 1. Exact canonical mapping match
        for pattern, _ in self.CANONICAL_MAPPING:
            if re.fullmatch(pattern, q):
                return True

        # 2. Exact match against cached catalog model ID or display name
        for m in self._all_models:
            if m["id"].lower() == q or m["name"].lower() == q:
                return True

        # 3. Model registry exact match or registered ID
        reg_m = model_registry.get(q)
        if reg_m:
            return True
        for m in getattr(model_registry, "_models", {}).values():
            if m.display_name.lower() == q:
                return True

        # 4. Canonical version-only shorthands (e.g. 3.8, 3.7, 3.1, 2.5, 2.0, r1, flash, qwq)
        if q in ("3.8", "3.7", "3.1", "2.5", "2.0", "r1", "flash", "qwq", "qwen", "gemini", "deepseek", "v4.1 flash", "v4-flash flash"):
            return True

        return False

    def is_model_query(self, query: str) -> bool:
        """Determines if a natural language query specifically targets or mentions a model.
        
        Prevents conversational verbs followed by non-model text (e.g. '繁體中文',
        'python 寫一個爬蟲', '3.8 版本寫了一段程式碼') from triggering model switching.
        """
        if not query or not isinstance(query, str):
            return False
        raw_q = query.strip().lower()
        if not raw_q:
            return False

        # 0. 嚴格否定守衛：日常片語與常見字詞絕對不是模型查詢，徹底杜絕正則偽陽性
        if any(raw_q.startswith(phrase) or raw_q == phrase for phrase in (
            "快點", "深思", "深思熟慮", "換個角度", "換個方式", "換句話說", "換個主題", "換個話題",
            "換個姿勢", "換個心情", "換個算法", "換個寫法", "換個說法", "換個做法"
        )):
            return False

        # 0.1 Flash 日常軟硬體名詞排除（非 AI 模型切換）
        if "flash" in raw_q and any(term in raw_q for term in (
            "flash player", "flash drive", "flash memory", "flash sale", "flash animation",
            "flash light", "flash card", "flash 隨身碟", "flash 記憶體", "flash 動畫", "flash 播放器", "flash 模式"
        )):
            return False

        # 0.2 Known deictic / random intents before suffix cleaning
        if raw_q in ("那個", "這個", "第1個", "第2個", "第3個", "第一個", "第二個", "第三個", "第1款", "第2款", "第3款", "隨便", "都可以", "任選", "任意", "隨便挑", "隨便選", "隨便一個", "random", "隨機"):
            return True

        clean_target = self.clean_natural_query(query).strip()
        q = clean_target.lower()
        if not q:
            return False

        # 1. Matches an active or cached model ID or display name or canonical mapping
        if self.find_canonical_or_exact(clean_target) or self.is_explicit_model_name(clean_target):
            return True

        # 2. Known deictic / random intents
        if q in ("那個", "這個", "第1個", "第2個", "第3個", "第一個", "第二個", "第三個", "第1款", "第2款", "第3款", "隨便", "都可以", "任選", "任意", "隨便挑", "隨便選", "隨便一個", "random", "隨機"):
            return True

        # 3. Explicit non-supported model families (GPT, Claude, LLaMA, etc.)
        if any(b in q for b in ["gpt", "openai", "o3", "o1", "claude", "claud", "sonnet", "haiku", "anthropic", "llama", "meta", "mistral", "mixtral", "codestral", "glm", "kimi", "moonshot", "grok"]):
            return True

        # 4. Explicit model keywords: contains "模型" or "model"
        if re.search(r"(?:模型|model)", clean_target, re.IGNORECASE):
            return True

        # 5. Known explicit version numbers that should not be guessed (e.g., 3.6, 2.0, etc.)
        if re.search(r"\b(?:3\.6|3\.4|2\.4|2\.3|2\.2|2\.1|2\.0)\b", q):
            return True

        # 6. Mentions known AI brands or brand typos
        if any(k in q for k in ["deepseek", "deepseel", "gemini", "gemin", "qwen", "qwq", "qwem", "google", "manus"]):
            return True

        # 7. Exact version patterns (e.g., '3.8', 'v4.1', '2.5')
        if re.fullmatch(r"^(?:gemini[-_ ]?|deepseek[-_ ]?|qwen[-_ ]?|v)?\d+\.\d+(?:[-_ ]?(?:flash|pro|chat|lite))?$", q):
            return True

        return False

    def parse_switch_request(self, text: str) -> Optional[SwitchRequest]:
        """Parses natural language switching intent, extracts model and extra instructions."""
        if not text or not isinstance(text, str):
            return None
        t = text.strip()
        if not t:
            return None

        # 0. Check if the sentence is an inquiry or question (Rule c)
        if INQUIRY_PATTERN.search(t):
            return None

        # 1. Check explicit delimiter split: ， , ； ; \n or (然後, 順便, 並且, 接著, 另外, 還有, 同時, 順道)
        split_match = re.split(r"[\n，,；;。]|(?:\s+(?:然後|順便|並且|接著|另外|還有|同時|順道))", t, maxsplit=1)
        if len(split_match) == 2:
            cand_str = split_match[0].strip()
            extra = split_match[1].strip()

            # 否定句與疑問句守衛：若第一段即為否定句或疑問句，絕非切換指令！
            if NEGATIVE_INTENT_PATTERN.search(cand_str) or INQUIRY_PATTERN.search(cand_str):
                return None

            cand_intent = SWITCH_INTENT_PATTERN.match(cand_str)
            has_cand_switch_verb = bool(cand_intent)

            # 強動作動詞約束：在標點分割下，第一段必須明確包含切換動作動詞！
            # 實體與動作嚴格分離：絕對禁止因為第一段僅僅是模型名稱（如「Gemini，幫我寫 code」）就判定為模型切換！
            if has_cand_switch_verb:
                # 任務型動詞過濾：若第一段動詞為通用「使用/use」（非「使用模型/use model」），且伴隨日常任務動詞，則不視為模型切換
                cand_pref = SWITCH_PREFIX_PATTERN.match(cand_str)
                cand_pref_str = cand_pref.group(0).strip().lower() if cand_pref else ""
                cand_rest = cand_str[cand_pref.end():].strip() if cand_pref else ""
                is_use_only = any(v in cand_pref_str for v in ("使用", "use")) and not any(v in cand_pref_str for v in ("使用模型", "use model"))
                if is_use_only and TASK_ACTION_PATTERN.search(cand_rest):
                    return None

                clean_cand = SWITCH_PREFIX_PATTERN.sub("", cand_str).strip()
                cleaned = self.clean_natural_query(clean_cand)

                # 若具有切換動詞，但受詞並非模型查詢，絕不切換
                if not self.is_model_query(clean_cand):
                    return None

                raw_res = model_registry.resolve(clean_cand)
                reg_res = raw_res if raw_res.status in ("AMBIGUOUS", "RANDOM") else model_registry.resolve(cleaned)
                if reg_res.status == "RETIRED":
                    return SwitchRequest(
                        is_switch_intent=True,
                        raw_model_query=cand_str,
                        cleaned_model_query=cleaned,
                        matched_model=None,
                        extra_query=extra,
                        outcome=ModelSwitchOutcome.MODEL_RETIRED,
                        rejection_reason=reg_res.message,
                        suggestions=[{"id": c.model_id, "name": c.display_name, "features": c.description} for c in reg_res.candidates],
                    )
                if reg_res.status == "RANDOM":
                    picked = model_registry.pick_random_available_model()
                    return SwitchRequest(
                        is_switch_intent=True,
                        raw_model_query=cand_str,
                        cleaned_model_query=cleaned,
                        matched_model=picked.model_id if picked else None,
                        extra_query=extra,
                        outcome=ModelSwitchOutcome.RANDOM_SELECTION if picked else ModelSwitchOutcome.PROVIDER_OFFLINE,
                        is_random_intent=True,
                        rejection_reason="" if picked else "目前系統中無可用之 AI 模型。",
                    )
                if reg_res.status == "AMBIGUOUS":
                    return SwitchRequest(
                        is_switch_intent=True,
                        raw_model_query=cand_str,
                        cleaned_model_query=cleaned,
                        matched_model=None,
                        extra_query=extra,
                        outcome=ModelSwitchOutcome.AMBIGUOUS_QUERY,
                        rejection_reason=reg_res.message,
                        suggestions=[{"id": c.model_id, "name": c.display_name, "features": c.description} for c in reg_res.candidates],
                    )
                if reg_res.status == "NOT_FOUND" and ("系統不會任意猜測其他版本" in reg_res.message or "ZeroNexus 目前嚴格僅支援" in reg_res.message):
                    return SwitchRequest(
                        is_switch_intent=True,
                        raw_model_query=cand_str,
                        cleaned_model_query=cleaned,
                        matched_model=None,
                        extra_query=extra,
                        outcome=ModelSwitchOutcome.MODEL_NOT_FOUND,
                        rejection_reason=reg_res.message,
                        suggestions=[{"id": c.model_id, "name": c.display_name, "features": c.description} for c in reg_res.candidates],
                    )

                canonical = self.find_canonical_or_exact(cleaned)
                if canonical:
                    matched = canonical
                else:
                    tokens = cleaned.split()
                    sub_found = False
                    if not extra and len(tokens) > 1:
                        for i in range(len(tokens) - 1, 0, -1):
                            sub_q = " ".join(tokens[:i])
                            sub_lower = sub_q.lower().strip()
                            remaining_suffix = " ".join(tokens[i:]).lower().strip()
                            # 嚴格防禦：若 sub_q 為 "flash"，且剩餘字串為日常硬體/軟體名詞，絕不進行子字串模型匹配！
                            if sub_lower == "flash" and any(rw in remaining_suffix for rw in ("player", "drive", "memory", "sale", "animation", "light", "card", "mob", "隨身碟", "記憶體", "動畫", "特賣", "播放器", "模式", "手電筒")):
                                continue
                            sub_canon = self.find_canonical_or_exact(sub_q)
                            if sub_canon:
                                matched = sub_canon
                                cleaned = sub_q
                                extra = " ".join(tokens[i:]).strip()
                                sub_found = True
                                break
                    if not sub_found:
                        matched = self.find_model(cleaned)

                if matched:
                    return SwitchRequest(
                        is_switch_intent=True,
                        raw_model_query=cand_str,
                        cleaned_model_query=cleaned,
                        matched_model=matched,
                        extra_query=extra,
                        outcome=ModelSwitchOutcome.SWITCH_SUCCESS,
                        suggestions=[],
                    )

                if has_cand_switch_verb and self.is_model_query(clean_cand):
                    return SwitchRequest(
                        is_switch_intent=True,
                        raw_model_query=cand_str,
                        cleaned_model_query=cleaned,
                        matched_model=None,
                        extra_query=extra,
                        outcome=ModelSwitchOutcome.MODEL_NOT_FOUND,
                        rejection_reason=f"查無相符之模型「{cleaned}」。",
                        suggestions=self.get_similar_models(cleaned, limit=3),
                    )

        # 2. Whole sentence evaluation
        # 否定句與疑問句嚴格防禦：若整句命中否定或疑問模式，絕對不觸發模型切換！
        if NEGATIVE_INTENT_PATTERN.search(t) or INQUIRY_PATTERN.search(t):
            return None

        m_intent = SWITCH_INTENT_PATTERN.match(t)
        has_switch_verb = bool(m_intent)

        # 任務型動詞過濾：若動詞前綴包含「使用」或「use」（非「使用模型」），且伴隨日常任務詞（如「幫我寫程式」），直接判定為一般對話！
        if has_switch_verb:
            m_pref = SWITCH_PREFIX_PATTERN.match(t)
            pref_str = m_pref.group(0).strip().lower() if m_pref else ""
            rest_after_pref = t[m_pref.end():].strip() if m_pref else ""
            is_use_only = any(v in pref_str for v in ("使用", "use")) and not any(v in pref_str for v in ("使用模型", "use model"))
            if is_use_only and TASK_ACTION_PATTERN.search(rest_after_pref):
                return None

        clean_no_prefix = SWITCH_PREFIX_PATTERN.sub("", t).strip()
        clean_full = self.clean_natural_query(clean_no_prefix)

        # 實體與動作嚴格隔離：
        if has_switch_verb:
            # 具有明確切換動詞，但受詞並非模型實體（例如「切換成繁體中文」）-> 絕不可切換！
            if not self.is_model_query(clean_no_prefix):
                return None
        else:
            # 完全沒有切換動詞時：
            # 實體與動作嚴格分離：句子包含模型名稱（如「ChatGPT」、「Gemini」）僅為實體提及（Entity Mention），絕對不能直接觸發模型切換！
            # 必須有強動作動詞約束，僅允許特定純版本號簡寫（如「3.8」、「v4.1 flash」、「r1」）相容：
            if not self.is_pure_version_shorthand(clean_no_prefix):
                return None

        # 2.5 Resolve through model_registry lifecycle & guards
        raw_res = model_registry.resolve(clean_no_prefix)
        reg_res = raw_res if raw_res.status in ("AMBIGUOUS", "RANDOM") else model_registry.resolve(clean_full)
        if reg_res.status == "RETIRED":
            return SwitchRequest(
                is_switch_intent=True,
                raw_model_query=clean_no_prefix,
                cleaned_model_query=clean_full,
                matched_model=None,
                extra_query="",
                outcome=ModelSwitchOutcome.MODEL_RETIRED,
                rejection_reason=reg_res.message,
                suggestions=[{"id": c.model_id, "name": c.display_name, "features": c.description} for c in reg_res.candidates],
            )
        if reg_res.status == "RANDOM":
            picked = model_registry.pick_random_available_model()
            return SwitchRequest(
                is_switch_intent=True,
                raw_model_query=clean_no_prefix,
                cleaned_model_query=clean_full,
                matched_model=picked.model_id if picked else None,
                extra_query="",
                outcome=ModelSwitchOutcome.RANDOM_SELECTION if picked else ModelSwitchOutcome.PROVIDER_OFFLINE,
                is_random_intent=True,
                rejection_reason="" if picked else "目前系統中無可用之 AI 模型。",
            )
        if reg_res.status == "AMBIGUOUS":
            return SwitchRequest(
                is_switch_intent=True,
                raw_model_query=clean_no_prefix,
                cleaned_model_query=clean_full,
                matched_model=None,
                extra_query="",
                outcome=ModelSwitchOutcome.AMBIGUOUS_QUERY,
                rejection_reason=reg_res.message,
                suggestions=[{"id": c.model_id, "name": c.display_name, "features": c.description} for c in reg_res.candidates],
            )
        if reg_res.status == "NOT_FOUND" and ("系統不會任意猜測其他版本" in reg_res.message or "ZeroNexus 目前嚴格僅支援" in reg_res.message):
            return SwitchRequest(
                is_switch_intent=True,
                raw_model_query=clean_no_prefix,
                cleaned_model_query=clean_full,
                matched_model=None,
                extra_query="",
                outcome=ModelSwitchOutcome.MODEL_NOT_FOUND,
                rejection_reason=reg_res.message,
                suggestions=[{"id": c.model_id, "name": c.display_name, "features": c.description} for c in reg_res.candidates],
            )

        # 3. Exact catalog match against id or name followed by space/punctuation
        for m in self._all_models:
            mid = m["id"].lower()
            mname = m["name"].lower()
            q_clean = clean_full.lower()
            if q_clean == mid or q_clean == mname:
                return SwitchRequest(
                    is_switch_intent=True,
                    raw_model_query=clean_no_prefix,
                    cleaned_model_query=clean_full,
                    matched_model=m["id"],
                    extra_query="",
                    outcome=ModelSwitchOutcome.SWITCH_SUCCESS,
                    suggestions=[],
                )
            for target in (mid, mname):
                if q_clean.startswith(target + " ") or q_clean.startswith(target + "，") or q_clean.startswith(target + ","):
                    extra_part = clean_no_prefix[len(target):].lstrip(" ，,；;").strip()
                    return SwitchRequest(
                        is_switch_intent=True,
                        raw_model_query=clean_no_prefix[:len(target)],
                        cleaned_model_query=target,
                        matched_model=m["id"],
                        extra_query=extra_part,
                        outcome=ModelSwitchOutcome.SWITCH_SUCCESS,
                        suggestions=[],
                    )

        # 4. Ordered prefix heuristics
        for pat, mid in PREFIX_HEURISTICS:
            m = re.search(pat, clean_full.lower())
            if m:
                end_idx = m.end()
                extra_part = clean_no_prefix[end_idx:].lstrip(" ，,；;").strip()
                extra_clean = SWITCH_SUFFIX_PATTERN.sub("", extra_part).strip()
                # 實體動作分離守衛：若無明確切換動詞且有自然語言後綴，絕對不是切換指令
                if not has_switch_verb and extra_clean:
                    continue
                # 實體動作分離守衛：若無明確切換動詞且非純版本代號，絕對不可觸發切換
                if not has_switch_verb and not self.is_pure_version_shorthand(clean_no_prefix):
                    continue
                return SwitchRequest(
                    is_switch_intent=True,
                    raw_model_query=clean_no_prefix[:end_idx],
                    cleaned_model_query=clean_full[:end_idx].strip(),
                    matched_model=mid,
                    extra_query="" if not extra_clean else extra_part,
                    outcome=ModelSwitchOutcome.SWITCH_SUCCESS,
                    suggestions=[],
                )

        # 5. Fuzzy / scoring on cleaned query
        cleaned_target = self.clean_natural_query(clean_no_prefix)
        # 若無切換動作動詞且非純版本代號，絕不進行模糊比對
        if not has_switch_verb and not self.is_pure_version_shorthand(clean_no_prefix):
            return None
        matched = self.find_model(cleaned_target)
        if matched:
            return SwitchRequest(
                is_switch_intent=True,
                raw_model_query=clean_no_prefix,
                cleaned_model_query=cleaned_target,
                matched_model=matched,
                extra_query="",
                outcome=ModelSwitchOutcome.SWITCH_SUCCESS,
                suggestions=[],
            )

        # 6. If it had switch verbs and was a model query, but no match:
        if has_switch_verb and self.is_model_query(clean_no_prefix):
            return SwitchRequest(
                is_switch_intent=True,
                raw_model_query=clean_no_prefix,
                cleaned_model_query=cleaned_target,
                matched_model=None,
                extra_query="",
                outcome=ModelSwitchOutcome.MODEL_NOT_FOUND,
                rejection_reason=f"查無相符之模型「{cleaned_target}」。",
                suggestions=self.get_similar_models(cleaned_target, limit=3),
            )

        return None

    def find_model_with_extra(self, text: str) -> Tuple[Optional[str], str]:
        """Extracts matched model ID and any subsequent user query instructions."""
        req = self.parse_switch_request(text)
        if req and req.matched_model:
            return req.matched_model, req.extra_query

        # Fallback to direct check only if explicit model name
        t = text.strip()
        split_match = re.split(r"[\n，,；;。]|(?:\s+(?:然後|順便|並且|接著))", t, maxsplit=1)
        if len(split_match) == 2:
            cand = split_match[0].strip()
            if self.is_explicit_model_name(cand):
                m = self.find_model(cand)
                if m:
                    return m, split_match[1].strip()

        if self.is_explicit_model_name(t):
            m = self.find_model(t)
            if m:
                return m, ""

        return None, ""

    def get_natural_knowledge_context(self, category: Optional[str] = None) -> str:
        """Returns a fluid, conversational knowledge block injected into system instructions."""
        cat_key = self.detect_vendor(category) if category else None

        if cat_key and cat_key in FEATURED_MODELS_BY_VENDOR:
            vendor_display = TARGET_VENDORS.get(cat_key, cat_key.title())
            featured = FEATURED_MODELS_BY_VENDOR[cat_key]
            lines = [
                f"【使用者正在詢問 {vendor_display} 的模型推薦】",
                f"ZeroNexus 為您精選 {vendor_display} 核心代表性模型如下：",
            ]
            for idx, m in enumerate(featured, 1):
                lines.append(f"{idx}. **{m['name']}** (`{m['id']}`)：{m['features']}")

            sample_name = featured[0]["name"]
            lines.extend([
                "",
                "【切換指引與回答準則】：",
                f"1. 請以真人朋友/當前人設的自然熱情口吻向使用者介紹上述 {len(featured)} 款核心代表性模型的亮點與適用場景。",
                f"2. 務必明確提示使用者：只要說「切換至 [名稱]」（例如「切換至 {sample_name}」）即可直接切換使用！",
                "3. **嚴格禁止使用生硬的 Markdown 表格、固定模板欄位或枯燥程式碼清單拋出資訊**，請使用通順流暢的台灣繁體中文對話。",
            ])
            return "\n".join(lines)

        # General platform catalog overview
        lines = [
            "【平台 AI 模型動態目錄（請以真人助理口吻介紹，切勿輸出死板表格）】",
            "ZeroNexus 支援豐富的模型生態，各系列精選代表如下：",
        ]
        for cat_k, cat_name in TARGET_VENDORS.items():
            featured = FEATURED_MODELS_BY_VENDOR.get(cat_k, [])
            sample_names = [f["name"] for f in featured[:3]]
            if not sample_names:
                models = self._categories.get(cat_k, [])
                sample_names = [m["name"] for m in models[:3]]
            lines.append(f"- **{cat_name}**：包含 {', '.join(sample_names)} 等。")

        lines.extend([
            "",
            "【回答模型相關問題的核心準則】：",
            "1. 當使用者以口語詢問「有哪些模型」、「有什麼模型」時，如同真人朋友般熱情親切地介紹上述主要品牌系列，並引導詢問對方偏好哪一種風格或任務。",
            "2. 當使用者詢問特定系列時，自然列舉該系列的特色與精選代表模型。",
            "3. 務必主動提醒使用者：只要說「切換至 [名稱]」（例如「切換至 Gemini 3.1 Flash Lite」或「換成 DeepSeek V4 Flash」）即可立即切換！",
            "4. **嚴格禁止使用生硬的 Markdown 表格、固定模板欄位或枯燥程式碼清單拋出資訊**，請使用通順流暢的台灣繁體中文對話。",
        ])
        return "\n".join(lines)


# Singleton
ModelCatalog = ModelCatalogService
model_catalog = ModelCatalogService()
