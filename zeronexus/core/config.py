"""ZeroNexus Configuration Manager.

Handles dual-layer configuration:
- .env for environment secrets, tokens, and credentials
- settings.json for global non-sensitive defaults and platform settings
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"
SETTINGS_FILE = BASE_DIR / "settings.json"

# Load environment variables from .env
load_dotenv(dotenv_path=ENV_FILE)


def _safe_int(val: Any, default: int, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """Safely converts a value to integer with fallback and boundary validation."""
    try:
        if val is None or (isinstance(val, str) and not val.strip()):
            return default
        res = int(val)
        if min_val is not None and res < min_val:
            return default
        if max_val is not None and res > max_val:
            return default
        return res
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
    """Safely converts a value to float with fallback and boundary validation."""
    try:
        if val is None or (isinstance(val, str) and not val.strip()):
            return default
        res = float(val)
        if min_val is not None and res < min_val:
            return default
        if max_val is not None and res > max_val:
            return default
        return res
    except (ValueError, TypeError):
        return default


def _safe_bool(val: Any, default: bool) -> bool:
    """Safely converts a value to boolean with fallback."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "on", "t", "y"):
        return True
    if s in ("false", "0", "no", "off", "f", "n"):
        return False
    return default


def _safe_str(val: Any, default: str) -> str:
    """Safely converts a value to string with fallback."""
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def mask_secret(secret: str | None, prefix_len: int = 4, suffix_len: int = 4) -> str:
    """Mask a sensitive credential, e.g., 'MTU0••••5Dlk'.

    Never leaks the middle or full string.
    """
    if not secret:
        return "[NOT SET]"
    s = str(secret).strip()
    if not s:
        return "[NOT SET]"
    if len(s) <= 4:
        return "••••"
    if len(s) <= suffix_len + prefix_len:
        return "••••••••"
    prefix = s[:prefix_len] if prefix_len > 0 else ""
    suffix = s[-suffix_len:] if suffix_len > 0 else ""
    return f"{prefix}••••{suffix}"


@dataclass
class DiscordConfig:
    token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", "").strip())
    dev_users: Set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        raw_devs = os.getenv("DEV_USERS", "").strip()
        if raw_devs:
            for item in raw_devs.split(","):
                item = item.strip()
                if item.isdigit():
                    self.dev_users.add(int(item))

    def is_dev(self, user_id: int) -> bool:
        return user_id in self.dev_users


@dataclass
class DatabaseConfig:
    url: str = field(default_factory=lambda: _safe_str(os.getenv("DATABASE_URL"), "sqlite+aiosqlite:///data/zeronexus.db"))
    echo: bool = field(default_factory=lambda: _safe_bool(os.getenv("DATABASE_ECHO"), False))


@dataclass
class CacheConfig:
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "").strip())
    default_ttl_seconds: int = field(default_factory=lambda: _safe_int(os.getenv("CACHE_DEFAULT_TTL"), 300, min_val=0))
    max_memory_items: int = field(default_factory=lambda: _safe_int(os.getenv("CACHE_MAX_ITEMS"), 5000, min_val=1))


@dataclass
class AudioNodeConfig:
    host: str = "127.0.0.1"
    port: int = 2333
    password: str = "youshallnotpass"
    secure: bool = False
    identifier: str = "default"


@dataclass
class AIProviderConfig:
    gemini_keys: List[str] = field(default_factory=list)
    gemini_model: str = "gemini-3.1-flash-lite"

    deepseek_keys: List[str] = field(default_factory=list)
    deepseek_model: str = "deepseek-chat"

    openrouter_keys: List[str] = field(default_factory=list)
    openrouter_key_1: str = ""
    openrouter_key_2: str = ""
    openrouter_fallback_key: str = field(default_factory=lambda: _safe_str(os.getenv("OPENROUTER_FALLBACK_KEY"), ""))
    openrouter_model: str = "google/gemini-3.1-flash-lite"

    huggingface_token: str = ""
    huggingface_model: str = "Qwen/Qwen2.5-72B-Instruct"
    huggingface_keys: List[str] = field(default_factory=list)

    # 專屬分離模型設定 (可於 .env 中獨立指定)
    normal_text_model: str = "gemini-3.1-flash-lite"
    normal_vision_model: str = "gemini-3.1-flash-lite"
    normal_gen_image_model: str = "gemini-2.5-flash-image"

    # Manus API 配置
    manus_keys: List[str] = field(default_factory=list)
    manus_model: str = "manus"
    manus_base_url: str = "https://api.manus.ai/v1"

    # Cohere API 配置
    cohere_keys: List[str] = field(default_factory=list)
    cohere_model: str = "command-r-plus-08-2024"

    # Mistral AI API 配置
    mistral_keys: List[str] = field(default_factory=list)
    mistral_model: str = "codestral-latest"

    # Groq LPU API 配置
    groq_keys: List[str] = field(default_factory=list)
    groq_model: str = "qwen/qwen3.8-27b"

    # 全域 AI 網關偏好與備援順序
    default_model: str = "gemini-3.1-flash-lite"
    enabled_providers: List[str] = field(default_factory=lambda: [
        "gemini", "deepseek", "openrouter", "groq", "mistral", "cohere", "manus", "huggingface"
    ])
    fallback_providers: List[str] = field(default_factory=lambda: [
        "gemini", "groq", "deepseek", "mistral", "openrouter", "cohere", "manus", "huggingface"
    ])

    daily_limit_per_user: int = 80
    short_term_memory_limit: int = 400
    memory_ttl_seconds: int = 1800
    default_persona: str = "normal_persona"
    request_timeout_seconds: int = 60
    max_tokens: int = 4096
    temperature: float = 0.7
    show_thinking: bool = True
    gemini_safety_settings: Dict[str, str] = field(default_factory=lambda: {
        "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
        "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
        "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
        "HARM_CATEGORY_CIVIC_INTEGRITY": "BLOCK_NONE",
    })

    def __post_init__(self) -> None:
        def parse_keys(plural_var: str, singular_var: str = "") -> List[str]:
            raw = os.getenv(plural_var, "").strip()
            if not raw and singular_var:
                raw = os.getenv(singular_var, "").strip()
            if not raw:
                return []
            return [k.strip() for k in raw.split(",") if k.strip()]

        self.gemini_keys = parse_keys("GEMINI_API_KEYS", "GEMINI_API_KEY")
        self.gemini_model = os.getenv("GEMINI_MODEL", self.gemini_model).strip() or self.gemini_model

        self.deepseek_keys = parse_keys("DEEPSEEK_API_KEYS", "DEEPSEEK_API_KEY")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", self.deepseek_model).strip() or self.deepseek_model

        # OpenRouter dual keys and fallbacks
        self.openrouter_key_1 = os.getenv("OPENROUTER_API_KEY_1", "").strip()
        self.openrouter_key_2 = os.getenv("OPENROUTER_API_KEY_2", "").strip()
        self.openrouter_fallback_key = (
            os.getenv("OPENROUTER_FALLBACK_API_KEY", self.openrouter_fallback_key).strip()
            or self.openrouter_fallback_key
        )
        or_keys = parse_keys("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY")
        
        # Merge keys ensuring priority order without duplicates
        all_or_keys: List[str] = []
        if self.openrouter_key_1 and self.openrouter_key_1 not in all_or_keys:
            all_or_keys.append(self.openrouter_key_1)
        if self.openrouter_key_2 and self.openrouter_key_2 not in all_or_keys:
            all_or_keys.append(self.openrouter_key_2)
        for k in or_keys:
            if k not in all_or_keys:
                all_or_keys.append(k)
        if self.openrouter_fallback_key and self.openrouter_fallback_key not in all_or_keys:
            all_or_keys.append(self.openrouter_fallback_key)
        self.openrouter_keys = all_or_keys
        if not self.openrouter_key_1 and self.openrouter_keys:
            self.openrouter_key_1 = self.openrouter_keys[0]
        if not self.openrouter_key_2 and len(self.openrouter_keys) > 1:
            self.openrouter_key_2 = self.openrouter_keys[1]

        self.openrouter_model = os.getenv("OPENROUTER_MODEL", self.openrouter_model).strip() or self.openrouter_model

        # Hugging Face token and model
        hf_token = os.getenv("HUGGINGFACE_TOKEN", "").strip()
        if not hf_token:
            hf_token = os.getenv("HUGGINGFACE_API_KEY", "").strip()
        if not hf_token:
            hf_token = os.getenv("HF_TOKEN", "").strip()
        self.huggingface_token = hf_token
        self.huggingface_model = os.getenv("HUGGINGFACE_MODEL", self.huggingface_model).strip() or self.huggingface_model
        hf_keys = parse_keys("HUGGINGFACE_TOKENS", "HUGGINGFACE_TOKEN")
        if not hf_keys and hf_token:
            hf_keys = [hf_token]
        self.huggingface_keys = hf_keys

        raw_ttl = os.getenv("MEMORY_TTL_SECONDS", "").strip()
        if raw_ttl.isdigit():
            self.memory_ttl_seconds = int(raw_ttl)

        # 載入專屬分離模型
        self.normal_text_model = os.getenv("NORMAL_TEXT_MODEL", self.normal_text_model).strip() or self.normal_text_model
        self.normal_vision_model = os.getenv("NORMAL_VISION_MODEL", self.normal_vision_model).strip() or self.normal_vision_model
        self.normal_gen_image_model = os.getenv("NORMAL_GEN_IMAGE_MODEL", self.normal_gen_image_model).strip() or self.normal_gen_image_model
        if self.normal_text_model:
            self.gemini_model = self.normal_text_model

        # 載入 Manus API 配置
        self.manus_keys = parse_keys("MANUS_API_KEYS", "MANUS_API_KEY")
        self.manus_model = os.getenv("MANUS_MODEL", self.manus_model).strip() or self.manus_model
        self.manus_base_url = os.getenv("MANUS_BASE_URL", self.manus_base_url).strip() or self.manus_base_url

        # 載入 Cohere API 配置
        self.cohere_keys = parse_keys("COHERE_API_KEYS", "COHERE_API_KEY")
        self.cohere_model = os.getenv("COHERE_MODEL", self.cohere_model).strip() or self.cohere_model

        # 載入 Mistral API 配置
        self.mistral_keys = parse_keys("MISTRAL_API_KEYS", "MISTRAL_API_KEY")
        self.mistral_model = os.getenv("MISTRAL_MODEL", self.mistral_model).strip() or self.mistral_model

        # 載入 Groq API 配置
        self.groq_keys = parse_keys("GROQ_API_KEYS", "GROQ_API_KEY")
        self.groq_model = os.getenv("GROQ_MODEL", self.groq_model).strip() or self.groq_model


@dataclass
class ExternalAPIConfig:
    cwa_api_key: str = field(default_factory=lambda: os.getenv("CWA_API_KEY", "").strip())
    cohere_api_key: str = field(default_factory=lambda: os.getenv("COHERE_API_KEY", "").strip())


@dataclass
class MusicConfig:
    audio_node_host: str = field(default_factory=lambda: _safe_str(os.getenv("audio_node_host"), "127.0.0.1"))
    audio_node_port: int = field(default_factory=lambda: _safe_int(os.getenv("audio_node_port"), 2333, min_val=1, max_val=65535))
    audio_node_password: str = field(default_factory=lambda: _safe_str(os.getenv("audio_node_password"), "youshallnotpass"))
    audio_node_secure: bool = field(default_factory=lambda: _safe_bool(os.getenv("audio_node_secure"), False))
    audio_node_identifier: str = field(default_factory=lambda: _safe_str(os.getenv("audio_node_identifier"), "local-node"))
    nodes: List[AudioNodeConfig] = field(default_factory=list)
    public_discovery_enabled: bool = True
    auto_fetch_public_nodes: bool = True
    public_discovery_url_ssl: str = "https://raw.githubusercontent.com/DarrenOfficial/lavalink-list/master/docs/SSL/Lavalink-SSL.md"
    public_discovery_url_non_ssl: str = "https://raw.githubusercontent.com/DarrenOfficial/lavalink-list/master/docs/NoSSL/Lavalink-NonSSL.md"
    default_volume: int = 100
    max_volume: int = 300
    max_queue_size: int = 500
    auto_leave_seconds: int = 180
    reconnect_retries: int = 5

    def __post_init__(self) -> None:
        self.public_discovery_enabled = _safe_bool(os.getenv("AUDIO_NODE_PUBLIC_DISCOVERY"), self.public_discovery_enabled)
        self.public_discovery_url_ssl = os.getenv("AUDIO_NODE_PUBLIC_DISCOVERY_URL_SSL", self.public_discovery_url_ssl).strip() or self.public_discovery_url_ssl
        self.public_discovery_url_non_ssl = os.getenv("AUDIO_NODE_PUBLIC_DISCOVERY_URL_NON_SSL", self.public_discovery_url_non_ssl).strip() or self.public_discovery_url_non_ssl

        # Build node pool starting with primary configured node
        primary_node = AudioNodeConfig(
            host=self.audio_node_host,
            port=self.audio_node_port,
            password=self.audio_node_password,
            secure=self.audio_node_secure,
            identifier=self.audio_node_identifier,
        )
        nodes_list = [primary_node]

        # Scan for additional env nodes: AUDIO_NODE_1_*, AUDIO_NODE_2_*, etc.
        for i in range(1, 10):
            prefix = f"AUDIO_NODE_{i}_"
            host = os.getenv(f"{prefix}HOST", "").strip()
            if not host:
                continue
            port = _safe_int(os.getenv(f"{prefix}PORT"), 2333, min_val=1, max_val=65535)
            password = _safe_str(os.getenv(f"{prefix}PASSWORD"), self.audio_node_password)
            secure = _safe_bool(os.getenv(f"{prefix}SECURE"), False)
            identifier = _safe_str(os.getenv(f"{prefix}IDENTIFIER"), f"node-{i}")
            nodes_list.append(
                AudioNodeConfig(
                    host=host,
                    port=port,
                    password=password,
                    secure=secure,
                    identifier=identifier,
                )
            )

        self.nodes = nodes_list


@dataclass
class RateLimitConfig:
    default_command_cooldown_seconds: float = 2.0
    ai_cooldown_seconds: float = 5.0
    max_global_requests_per_second: int = 30


@dataclass
class PlatformSettings:
    name: str = "ZeroNexus"
    codename: str = "ZN"
    version: str = "2.5.1"
    owner_id: str = "1514971711739789352"
    default_prefix: str = "zn!"
    default_locale: str = "zh-TW"
    default_timezone: str = "Asia/Taipei"
    presence_rotation_interval: int = 60
    presence_activities: List[str] = field(default_factory=lambda: [
        "正在遊玩：研究人類行為",
        "正在遊玩：等待下一個問題",
        "正在遊玩：偷偷整理伺服器",
        "正在遊玩：檢查伺服器有沒有爆炸",
        "正在遊玩：假裝很忙",
        "正在遊玩：維護這個世界",
        "正在遊玩：不知道自己在忙什麼",
        "正在遊玩：等待下一個指令",
    ])
    self_check_on_startup: bool = True


class Config:
    """Master Unified Configuration for ZeroNexus."""

    def __init__(self) -> None:
        self.base_dir = BASE_DIR
        self.discord = DiscordConfig()
        self.database = DatabaseConfig()
        self.cache = CacheConfig()
        self.ai = AIProviderConfig()
        self.external = ExternalAPIConfig()
        self.music = MusicConfig()
        self.platform = PlatformSettings()
        self.rate_limits = RateLimitConfig()

        self._load_settings_json()

    def reload(self) -> None:
        """Reloads configuration from .env and settings.json with default fallbacks."""
        load_dotenv(dotenv_path=ENV_FILE, override=True)
        self.discord = DiscordConfig()
        self.database = DatabaseConfig()
        self.cache = CacheConfig()
        self.ai = AIProviderConfig()
        self.external = ExternalAPIConfig()
        self.music = MusicConfig()
        self.platform = PlatformSettings()
        self.rate_limits = RateLimitConfig()
        self._load_settings_json()

    def _load_settings_json(self) -> None:
        if not SETTINGS_FILE.exists():
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            if not isinstance(data, dict):
                print(f"[WARN] settings.json must contain a JSON object, got {type(data).__name__}")
                return

            if "platform_name" in data:
                self.platform.name = _safe_str(data["platform_name"], self.platform.name)
            if "codename" in data:
                self.platform.codename = _safe_str(data["codename"], self.platform.codename)
            if "version" in data:
                self.platform.version = _safe_str(data["version"], self.platform.version)
            if "owner_id" in data:
                self.platform.owner_id = _safe_str(data["owner_id"], self.platform.owner_id)
            if "default_prefix" in data:
                self.platform.default_prefix = _safe_str(data["default_prefix"], self.platform.default_prefix)
            if "default_locale" in data:
                self.platform.default_locale = _safe_str(data["default_locale"], self.platform.default_locale)
            if "default_timezone" in data:
                self.platform.default_timezone = _safe_str(data["default_timezone"], self.platform.default_timezone)

            ai_settings = data.get("ai")
            if isinstance(ai_settings, dict):
                if "daily_limit_per_user" in ai_settings:
                    self.ai.daily_limit_per_user = _safe_int(ai_settings["daily_limit_per_user"], self.ai.daily_limit_per_user, min_val=1)
                if "short_term_memory_limit" in ai_settings:
                    self.ai.short_term_memory_limit = _safe_int(ai_settings["short_term_memory_limit"], self.ai.short_term_memory_limit, min_val=1)
                if "memory_ttl_seconds" in ai_settings:
                    self.ai.memory_ttl_seconds = _safe_int(ai_settings["memory_ttl_seconds"], self.ai.memory_ttl_seconds, min_val=0)
                if "default_persona" in ai_settings:
                    self.ai.default_persona = _safe_str(ai_settings["default_persona"], self.ai.default_persona)
                if "request_timeout_seconds" in ai_settings:
                    self.ai.request_timeout_seconds = _safe_int(ai_settings["request_timeout_seconds"], self.ai.request_timeout_seconds, min_val=1)
                if "max_tokens" in ai_settings:
                    self.ai.max_tokens = _safe_int(ai_settings["max_tokens"], self.ai.max_tokens, min_val=1)
                if "temperature" in ai_settings:
                    self.ai.temperature = _safe_float(ai_settings["temperature"], self.ai.temperature, min_val=0.0, max_val=2.0)
                if "show_thinking" in ai_settings:
                    self.ai.show_thinking = _safe_bool(ai_settings["show_thinking"], self.ai.show_thinking)
                if "default_model" in ai_settings:
                    self.ai.default_model = _safe_str(ai_settings["default_model"], self.ai.default_model)
                if "enabled_providers" in ai_settings and isinstance(ai_settings["enabled_providers"], list):
                    self.ai.enabled_providers = [str(p).strip().lower() for p in ai_settings["enabled_providers"] if str(p).strip()]
                if "fallback_providers" in ai_settings and isinstance(ai_settings["fallback_providers"], list):
                    self.ai.fallback_providers = [str(p).strip().lower() for p in ai_settings["fallback_providers"] if str(p).strip()]
                if "gemini_safety_settings" in ai_settings and isinstance(ai_settings["gemini_safety_settings"], dict):
                    self.ai.gemini_safety_settings = {
                        str(k): str(v) for k, v in ai_settings["gemini_safety_settings"].items()
                    }

            music_settings = data.get("lavalink") or data.get("music")
            if isinstance(music_settings, dict):
                if "default_volume" in music_settings:
                    self.music.default_volume = _safe_int(music_settings["default_volume"], self.music.default_volume, min_val=0, max_val=300)
                if "max_volume" in music_settings:
                    self.music.max_volume = _safe_int(music_settings["max_volume"], self.music.max_volume, min_val=100, max_val=500)
                if "max_queue_size" in music_settings:
                    self.music.max_queue_size = _safe_int(music_settings["max_queue_size"], self.music.max_queue_size, min_val=1)
                if "auto_leave_seconds" in music_settings:
                    self.music.auto_leave_seconds = _safe_int(music_settings["auto_leave_seconds"], self.music.auto_leave_seconds, min_val=0)
                if "afk_timeout_seconds" in music_settings:
                    self.music.auto_leave_seconds = _safe_int(music_settings["afk_timeout_seconds"], self.music.auto_leave_seconds, min_val=0)
                if "reconnect_retries" in music_settings:
                    self.music.reconnect_retries = _safe_int(music_settings["reconnect_retries"], self.music.reconnect_retries, min_val=0)
                if "auto_fetch_public_nodes" in music_settings:
                    self.music.auto_fetch_public_nodes = _safe_bool(music_settings["auto_fetch_public_nodes"], self.music.auto_fetch_public_nodes)
                if "nodes" in music_settings and isinstance(music_settings["nodes"], list):
                    parsed_nodes: List[AudioNodeConfig] = []
                    for n in music_settings["nodes"]:
                        if isinstance(n, dict) and "host" in n:
                            parsed_nodes.append(
                                AudioNodeConfig(
                                    host=str(n["host"]).strip(),
                                    port=_safe_int(n.get("port"), 2333),
                                    password=str(n.get("password", "youshallnotpass")).strip(),
                                    secure=_safe_bool(n.get("secure"), False),
                                    identifier=str(n.get("name") or n.get("identifier") or n["host"]).strip(),
                                )
                            )
                    if parsed_nodes:
                        self.music.nodes = parsed_nodes

            cache_settings = data.get("cache")
            if isinstance(cache_settings, dict):
                if "default_ttl_seconds" in cache_settings:
                    self.cache.default_ttl_seconds = _safe_int(cache_settings["default_ttl_seconds"], self.cache.default_ttl_seconds, min_val=0)
                if "max_memory_items" in cache_settings:
                    self.cache.max_memory_items = _safe_int(cache_settings["max_memory_items"], self.cache.max_memory_items, min_val=1)

            rate_limits = data.get("rate_limits")
            if isinstance(rate_limits, dict):
                if "default_command_cooldown_seconds" in rate_limits:
                    self.rate_limits.default_command_cooldown_seconds = _safe_float(rate_limits["default_command_cooldown_seconds"], self.rate_limits.default_command_cooldown_seconds, min_val=0.0)
                if "ai_cooldown_seconds" in rate_limits:
                    self.rate_limits.ai_cooldown_seconds = _safe_float(rate_limits["ai_cooldown_seconds"], self.rate_limits.ai_cooldown_seconds, min_val=0.0)
                if "max_global_requests_per_second" in rate_limits:
                    self.rate_limits.max_global_requests_per_second = _safe_int(rate_limits["max_global_requests_per_second"], self.rate_limits.max_global_requests_per_second, min_val=1)

            presence_settings = data.get("presence")
            if isinstance(presence_settings, dict):
                if "rotation_interval_seconds" in presence_settings:
                    self.platform.presence_rotation_interval = _safe_int(presence_settings["rotation_interval_seconds"], self.platform.presence_rotation_interval, min_val=1)
                if "activities" in presence_settings and isinstance(presence_settings["activities"], list):
                    clean_activities = [str(a) for a in presence_settings["activities"] if str(a).strip()]
                    if clean_activities:
                        self.platform.presence_activities = clean_activities

            diag_settings = data.get("diagnostics")
            if isinstance(diag_settings, dict):
                if "self_check_on_startup" in diag_settings:
                    self.platform.self_check_on_startup = _safe_bool(diag_settings["self_check_on_startup"], self.platform.self_check_on_startup)

        except Exception as e:
            # Fallback to default if settings.json fails
            print(f"[WARN] Failed to parse settings.json: {e}")

    def collect_all_secrets(self) -> Set[str]:
        """Returns all loaded secrets to allow global redaction in logger."""
        from urllib.parse import urlparse
        secrets: Set[str] = set()
        if self.discord.token:
            secrets.add(self.discord.token)

        env_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if env_token:
            secrets.add(env_token)

        for k in self.ai.gemini_keys:
            secrets.add(k)
        for k in self.ai.deepseek_keys:
            secrets.add(k)
        for k in self.ai.openrouter_keys:
            secrets.add(k)

        for var in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "CWA_API_KEY"):
            val = os.getenv(var, "").strip()
            if val:
                secrets.add(val)

        if self.external.cwa_api_key:
            secrets.add(self.external.cwa_api_key)
        if self.music.audio_node_password:
            secrets.add(self.music.audio_node_password)

        # Database URL password extraction
        for db_val in (self.database.url, os.getenv("DATABASE_URL", "")):
            if db_val and "://" in db_val and "@" in db_val:
                try:
                    p = urlparse(db_val)
                    if p.password:
                        secrets.add(p.password)
                except Exception:
                    pass

        # Redis URL password extraction
        for redis_val in (self.cache.redis_url, os.getenv("REDIS_URL", "")):
            if redis_val and "://" in redis_val and "@" in redis_val:
                try:
                    p = urlparse(redis_val)
                    if p.password:
                        secrets.add(p.password)
                except Exception:
                    pass

        return {s for s in secrets if len(s) >= 4}


# Singleton instance
config = Config()
