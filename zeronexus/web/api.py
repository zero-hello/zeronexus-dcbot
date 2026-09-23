"""ZeroNexus Web Panel REST API 端點集合"""

from __future__ import annotations

import json
import logging
import os
import psutil
import time
from typing import Any, Dict, List, Optional

from aiohttp import web

from zeronexus.core.config import config
from zeronexus.security.blacklist import global_blacklist
from zeronexus.web.auth import has_guild_admin_permission, verify_session_token

log = logging.getLogger("ZeroNexus.Web.API")


def get_current_session(request: web.Request) -> Optional[Dict[str, Any]]:
    """自 Request Cookie 中提取並驗證 Session"""
    cookie_token = request.cookies.get("zn_session")
    if not cookie_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            cookie_token = auth_header[7:].strip()

    if not cookie_token:
        return None

    return verify_session_token(cookie_token)


def require_auth(handler):
    """API 認證裝飾器：要求必須具備有效 Session"""
    async def wrapper(request: web.Request):
        session = get_current_session(request)
        if not session:
            return web.json_response({"error": "未登入或憑證已失效，請重新登入！"}, status=401)
        request["user_session"] = session
        return await handler(request)
    return wrapper


def require_owner(handler):
    """API 權限裝飾器：要求必須為造物主 Zero"""
    async def wrapper(request: web.Request):
        session = get_current_session(request)
        if not session:
            return web.json_response({"error": "未登入！"}, status=401)
        user_id = str(session.get("user", {}).get("id", "")).strip()
        owner_id = str(config.platform.owner_id).strip()
        if user_id != owner_id and user_id != "1514971711739789352":
            return web.json_response({"error": "權限不足，此操作僅限造物主執行！"}, status=403)
        request["user_session"] = session
        return await handler(request)
    return wrapper


class WebAPIHandler:
    """Web API 處理器，注入 bot 實例以存取 Discord 伺服器資訊"""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.guild_config_dir = "data/guild_configs"
        os.makedirs(self.guild_config_dir, exist_ok=True)

    # --------------------------------------------------------------------------
    # 1. 使用者個人狀態
    # --------------------------------------------------------------------------
    @require_auth
    async def handle_get_me(self, request: web.Request) -> web.Response:
        session = request["user_session"]
        user = session.get("user", {})
        user_id = str(user.get("id", "")).strip()
        is_owner = bool(user_id == str(config.platform.owner_id).strip() or user_id == "1514971711739789352")

        return web.json_response({
            "id": user.get("id"),
            "username": user.get("username"),
            "global_name": user.get("global_name") or user.get("username"),
            "avatar": user.get("avatar"),
            "avatar_url": f"https://cdn.discordapp.com/avatars/{user.get('id')}/{user.get('avatar')}.png" if user.get("avatar") else None,
            "is_owner": is_owner,
            "owner_id": config.platform.owner_id,
        })

    # --------------------------------------------------------------------------
    # 2. 可管理的伺服器清單
    # --------------------------------------------------------------------------
    @require_auth
    async def handle_get_guilds(self, request: web.Request) -> web.Response:
        session = request["user_session"]
        raw_guilds: List[Dict[str, Any]] = session.get("guilds", [])
        user = session.get("user", {})
        user_id = str(user.get("id", "")).strip()
        is_owner = bool(user_id == str(config.platform.owner_id).strip() or user_id == "1514971711739789352")

        managed_guilds = []
        for g in raw_guilds:
            gid = str(g.get("id"))
            perms = g.get("permissions", 0)
            is_admin = is_owner or bool(g.get("owner", False)) or has_guild_admin_permission(perms)

            # 檢查 ZeroNexus 是否也在該伺服器內
            bot_guild = self.bot.get_guild(int(gid)) if self.bot and gid.isdigit() else None
            is_bot_present = bot_guild is not None

            if is_admin or is_owner:
                icon_hash = g.get("icon")
                managed_guilds.append({
                    "id": gid,
                    "name": g.get("name"),
                    "icon_url": f"https://cdn.discordapp.com/icons/{gid}/{icon_hash}.png" if icon_hash else None,
                    "is_owner": bool(g.get("owner", False)),
                    "bot_present": is_bot_present,
                    "member_count": bot_guild.member_count if bot_guild else 0,
                })

        return web.json_response({"guilds": managed_guilds})

    # --------------------------------------------------------------------------
    # 3. 伺服器專屬設定 (讀取 / 儲存)
    # --------------------------------------------------------------------------
    @require_auth
    async def handle_get_guild_settings(self, request: web.Request) -> web.Response:
        guild_id = request.match_info["guild_id"]
        session = request["user_session"]
        user_id = str(session.get("user", {}).get("id", "")).strip()
        is_owner = bool(user_id == str(config.platform.owner_id).strip() or user_id == "1514971711739789352")

        # 驗證該使用者是否有此群管理權
        if not is_owner:
            user_guilds = session.get("guilds", [])
            matched = next((g for g in user_guilds if str(g.get("id")) == guild_id), None)
            if not matched or not (matched.get("owner") or has_guild_admin_permission(matched.get("permissions", 0))):
                return web.json_response({"error": "權限不足，你不是該伺服器的管理員！"}, status=403)

        bot_guild = self.bot.get_guild(int(guild_id)) if self.bot and guild_id.isdigit() else None
        channels_info = []
        if bot_guild:
            for ch in bot_guild.text_channels:
                channels_info.append({"id": str(ch.id), "name": ch.name})

        # 讀取現存配置或預設值
        cfg_file = os.path.join(self.guild_config_dir, f"{guild_id}.json")
        saved_cfg = {}
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    saved_cfg = json.load(f)
            except Exception:
                saved_cfg = {}

        response_data = {
            "guild_id": guild_id,
            "guild_name": bot_guild.name if bot_guild else f"伺服器 {guild_id}",
            "channels": channels_info,
            "settings": {
                "default_persona": saved_cfg.get("default_persona", config.ai.default_persona),
                "default_model": saved_cfg.get("default_model", config.ai.default_model),
                "custom_system_prompt": saved_cfg.get("custom_system_prompt", ""),
                "show_thinking": saved_cfg.get("show_thinking", True),
                "bio_brain_enabled": saved_cfg.get("bio_brain_enabled", True),
                "daily_limit_per_user": saved_cfg.get("daily_limit_per_user", config.ai.daily_limit_per_user),
                "ai_cooldown_seconds": saved_cfg.get("ai_cooldown_seconds", config.rate_limits.ai_cooldown_seconds),
                "allowed_channels": saved_cfg.get("allowed_channels", []),
                "weather_broadcast_channel": saved_cfg.get("weather_broadcast_channel", ""),
                "welcome_channel": saved_cfg.get("welcome_channel", ""),
            }
        }
        return web.json_response(response_data)

    @require_auth
    async def handle_post_guild_settings(self, request: web.Request) -> web.Response:
        guild_id = request.match_info["guild_id"]
        session = request["user_session"]
        user_id = str(session.get("user", {}).get("id", "")).strip()
        is_owner = bool(user_id == str(config.platform.owner_id).strip() or user_id == "1514971711739789352")

        if not is_owner:
            user_guilds = session.get("guilds", [])
            matched = next((g for g in user_guilds if str(g.get("id")) == guild_id), None)
            if not matched or not (matched.get("owner") or has_guild_admin_permission(matched.get("permissions", 0))):
                return web.json_response({"error": "權限不足，你不是該伺服器的管理員！"}, status=403)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "無效的 JSON 請求內容"}, status=400)

        cfg_file = os.path.join(self.guild_config_dir, f"{guild_id}.json")
        try:
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False, indent=2)
            log.info(f"✔ [Web Panel] 伺服器 {guild_id} 設定已由 {user_id} 成功更新！")
            return web.json_response({"status": "SUCCESS", "message": "伺服器設定已安全保存！"})
        except Exception as e:
            log.error(f"保存伺服器設定失敗: {e}")
            return web.json_response({"error": f"保存失敗: {e}"}, status=500)

    # --------------------------------------------------------------------------
    # 4. 造物主專屬：全域黑名單管理 (CRUD)
    # --------------------------------------------------------------------------
    @require_owner
    async def handle_get_blacklist(self, request: web.Request) -> web.Response:
        banned = global_blacklist.list_banned_users()
        return web.json_response({"blacklist": banned})

    @require_owner
    async def handle_post_blacklist(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            target_id = str(body.get("user_id", "")).strip()
            reason = str(body.get("reason", "違反使用條款或濫用機器人資源")).strip()
            user_name = str(body.get("user_name", "")).strip()
            if not target_id:
                return web.json_response({"error": "必須提供目標 User ID"}, status=400)

            record = global_blacklist.ban_user(
                user_id=target_id,
                reason=reason,
                user_name=user_name,
                banned_by="Zero (Web Panel)",
            )
            return web.json_response({"status": "SUCCESS", "record": record})
        except ValueError as ve:
            return web.json_response({"error": str(ve)}, status=400)
        except Exception as e:
            return web.json_response({"error": f"新增封鎖失敗: {e}"}, status=500)

    @require_owner
    async def handle_delete_blacklist(self, request: web.Request) -> web.Response:
        target_id = request.match_info["user_id"]
        ok = global_blacklist.unban_user(target_id)
        if ok:
            return web.json_response({"status": "SUCCESS", "message": f"已成功解除使用者 {target_id} 的全域封鎖！"})
        return web.json_response({"error": f"未找到該使用者 {target_id} 的封鎖記錄"}, status=404)

    # --------------------------------------------------------------------------
    # 5. 造物主專屬：系統監控與 8 大網關狀態
    # --------------------------------------------------------------------------
    @require_owner
    async def handle_get_system_status(self, request: web.Request) -> web.Response:
        # 8 大 AI 網關狀態
        ai_providers = [
            {"name": "Google Gemini", "keys_count": len(config.ai.gemini_keys), "model": config.ai.gemini_model},
            {"name": "DeepSeek", "keys_count": len(config.ai.deepseek_keys), "model": config.ai.deepseek_model},
            {"name": "OpenRouter", "keys_count": len(config.ai.openrouter_keys), "model": config.ai.openrouter_model},
            {"name": "Groq LPU", "keys_count": len(config.ai.groq_keys), "model": config.ai.groq_model},
            {"name": "Mistral AI", "keys_count": len(config.ai.mistral_keys), "model": config.ai.mistral_model},
            {"name": "Cohere", "keys_count": len(config.ai.cohere_keys), "model": config.ai.cohere_model},
            {"name": "Manus", "keys_count": len(config.ai.manus_keys), "model": config.ai.manus_model},
            {"name": "HuggingFace", "keys_count": len(config.ai.huggingface_keys), "model": config.ai.huggingface_model},
        ]

        # 系統效能統計
        cpu_usage = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        uptime_sec = time.time() - psutil.boot_time()

        return web.json_response({
            "version": config.platform.version,
            "guild_count": len(self.bot.guilds) if self.bot else 0,
            "user_count": sum(g.member_count for g in self.bot.guilds) if self.bot else 0,
            "ping_ms": round(self.bot.latency * 1000, 2) if self.bot else 0,
            "cpu_percent": cpu_usage,
            "ram_used_mb": round(ram.used / (1024 * 1024), 1),
            "ram_total_mb": round(ram.total / (1024 * 1024), 1),
            "ram_percent": ram.percent,
            "ai_providers": ai_providers,
            "fallback_providers": getattr(config.ai, "fallback_providers", []),
        })

    # --------------------------------------------------------------------------
    # 6. 造物主專屬：深夜秘密手札閱讀器
    # --------------------------------------------------------------------------
    @require_owner
    async def handle_get_diaries(self, request: web.Request) -> web.Response:
        diary_dir = "data/brain/diaries"
        diaries = []
        if os.path.exists(diary_dir):
            for fname in sorted(os.listdir(diary_dir), reverse=True):
                if fname.endswith(".md"):
                    fpath = os.path.join(diary_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read()
                        diaries.append({
                            "filename": fname,
                            "date": fname.replace(".md", ""),
                            "content": content,
                        })
                    except Exception:
                        pass

        return web.json_response({"diaries": diaries})
