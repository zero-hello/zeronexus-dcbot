"""ZeroNexus Web Panel Discord OAuth2 與身份授權中樞"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from zeronexus.core.config import config

log = logging.getLogger("ZeroNexus.Web.Auth")

DISCORD_OAUTH2_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH2_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_ME_URL = "https://discord.com/api/users/@me"
DISCORD_API_ME_GUILDS_URL = "https://discord.com/api/users/@me/guilds"

# Discord 權限位元常數
PERMISSION_ADMINISTRATOR = 0x8
PERMISSION_MANAGE_GUILD = 0x20


def has_guild_admin_permission(permissions: int | str) -> bool:
    """檢查權限位元是否具備管理員 (Administrator) 或管理伺服器 (Manage Guild) 權限"""
    try:
        perm_int = int(permissions)
        if (perm_int & PERMISSION_ADMINISTRATOR) == PERMISSION_ADMINISTRATOR:
            return True
        if (perm_int & PERMISSION_MANAGE_GUILD) == PERMISSION_MANAGE_GUILD:
            return True
        return False
    except (ValueError, TypeError):
        return False


def get_oauth2_login_url(state: str = "") -> str:
    """產生官方 Discord OAuth2 授權跳轉連結"""
    client_id = config.web_panel.client_id or config.discord.client_id
    redirect_uri = config.web_panel.redirect_uri

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify guilds",
        "prompt": "consent",
    }
    if state:
        params["state"] = state

    return f"{DISCORD_OAUTH2_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_token(code: str) -> Optional[Dict[str, Any]]:
    """以 Authorization Code 換取 Discord Access Token"""
    client_id = config.web_panel.client_id or config.discord.client_id
    client_secret = config.web_panel.client_secret

    if not client_id or not client_secret:
        log.warning("未設定 DISCORD_CLIENT_ID 或 DISCORD_CLIENT_SECRET，無法完成 OAuth2 認證！")
        return None

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.web_panel.redirect_uri,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(DISCORD_OAUTH2_TOKEN_URL, data=data, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            else:
                log.warning(f"OAuth2 換取 Token 失敗 (HTTP {resp.status_code}): {resp.text}")
                return None
        except Exception as e:
            log.error(f"OAuth2 Token 請求網路異常: {e}")
            return None


async def fetch_user_profile(access_token: str) -> Optional[Dict[str, Any]]:
    """向 Discord API 抓取登入使用者資訊 (@me)"""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(DISCORD_API_ME_URL, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            log.error(f"抓取 Discord 使用者資料失敗: {e}")
            return None


async def fetch_user_guilds(access_token: str) -> List[Dict[str, Any]]:
    """向 Discord API 抓取使用者所在伺服器清單與權限 (@me/guilds)"""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(DISCORD_API_ME_GUILDS_URL, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else []
            return []
        except Exception as e:
            log.error(f"抓取 Discord 伺服器清單失敗: {e}")
            return []


# ==============================================================================
# 安全 Session 簽名與驗證 (HMAC-SHA256 Signed Cookie)
# ==============================================================================
def create_session_token(payload: Dict[str, Any], secret_key: Optional[str] = None) -> str:
    """將 Session 載荷加密簽名為防偽字串"""
    sec_str = secret_key or config.web_panel.session_secret
    secret = sec_str.encode("utf-8")
    payload_copy = dict(payload)
    payload_copy["_ts"] = int(time.time())

    raw_json = json.dumps(payload_copy, ensure_ascii=False).encode("utf-8")
    b64_data = base64.urlsafe_b64encode(raw_json).decode("utf-8")

    signature = hmac.new(secret, b64_data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_data}.{signature}"


def verify_session_token(token_str: str, secret_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """驗證並解析 Session 字串"""
    if not token_str or "." not in token_str:
        return None

    try:
        b64_data, signature = token_str.rsplit(".", 1)
        sec_str = secret_key or config.web_panel.session_secret
        secret = sec_str.encode("utf-8")
        expected_sig = hmac.new(secret, b64_data.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            log.warning("Session 簽名驗證失敗，可能遭到偽造！")
            return None

        raw_json = base64.urlsafe_b64decode(b64_data.encode("utf-8")).decode("utf-8")
        payload = json.loads(raw_json)

        # 檢查時效 (預設 7 天)
        max_age_sec = config.web_panel.session_max_age_days * 86400
        created_at = payload.get("_ts", 0)
        if time.time() - created_at > max_age_sec:
            log.debug("Session 已逾期，需重新登入。")
            return None

        return payload
    except Exception as e:
        log.debug(f"解析 Session 失敗: {e}")
        return None


# 方便外部引用的語義化別名
create_session_cookie = create_session_token
verify_session_cookie = verify_session_token
