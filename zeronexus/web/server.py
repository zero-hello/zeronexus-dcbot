"""ZeroNexus Web Panel HTTP Server 主控服務 (aiohttp.web)"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from zeronexus.core.config import config
from zeronexus.web.api import WebAPIHandler
from zeronexus.web.auth import (
    create_session_token,
    exchange_code_for_token,
    fetch_user_guilds,
    fetch_user_profile,
    get_oauth2_login_url,
)

log = logging.getLogger("ZeroNexus.Web.Server")
STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebPanelServer:
    """Web Panel 總控伺服器，非同步常駐在 bot event loop 內運行"""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.api_handler = WebAPIHandler(bot=self.bot)
        self._setup_routes()

    def _setup_routes(self) -> None:
        """註冊 Web 路由與 API 端點"""
        # 前端單頁應用入口
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/dashboard", self._handle_index)
        self.app.router.add_get("/guild/{guild_id}", self._handle_index)
        self.app.router.add_get("/admin", self._handle_index)

        # 靜態資源
        if STATIC_DIR.exists():
            self.app.router.add_static("/static", str(STATIC_DIR))

        # OAuth2 登入與回呼
        self.app.router.add_get("/login", self._handle_login)
        self.app.router.add_get("/auth/login", self._handle_login)
        self.app.router.add_get("/auth/callback", self._handle_auth_callback)
        self.app.router.add_get("/auth/logout", self._handle_logout)

        # REST API 路由
        self.app.router.add_get("/api/me", self.api_handler.handle_get_me)
        self.app.router.add_get("/api/guilds", self.api_handler.handle_get_guilds)
        self.app.router.add_get("/api/guilds/{guild_id}/settings", self.api_handler.handle_get_guild_settings)
        self.app.router.add_post("/api/guilds/{guild_id}/settings", self.api_handler.handle_post_guild_settings)

        # 造物主專屬 API
        self.app.router.add_get("/api/admin/blacklist", self.api_handler.handle_get_blacklist)
        self.app.router.add_post("/api/admin/blacklist", self.api_handler.handle_post_blacklist)
        self.app.router.add_delete("/api/admin/blacklist/{user_id}", self.api_handler.handle_delete_blacklist)
        self.app.router.add_get("/api/admin/system", self.api_handler.handle_get_system_status)
        self.app.router.add_get("/api/admin/diaries", self.api_handler.handle_get_diaries)

    async def _handle_index(self, request: web.Request) -> web.Response:
        """回傳 SPA 首頁 index.html"""
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return web.FileResponse(index_file)
        return web.Response(text="ZeroNexus Web Panel is active. index.html not found.", content_type="text/plain")

    async def _handle_login(self, request: web.Request) -> web.Response:
        """引導至官方 Discord OAuth2 授權頁面"""
        auth_url = get_oauth2_login_url()
        return web.HTTPFound(auth_url)

    async def _handle_auth_callback(self, request: web.Request) -> web.Response:
        """處理 Discord OAuth2 回呼並簽發 Session Cookie"""
        code = request.query.get("code")
        error = request.query.get("error")

        if error or not code:
            log.warning(f"OAuth2 授權遭到拒絕或取消: {error}")
            return web.HTTPFound("/?error=auth_denied")

        token_data = await exchange_code_for_token(code)
        if not token_data or "access_token" not in token_data:
            return web.HTTPFound("/?error=token_exchange_failed")

        access_token = token_data["access_token"]
        user_profile = await fetch_user_profile(access_token)
        if not user_profile:
            return web.HTTPFound("/?error=fetch_profile_failed")

        user_guilds = await fetch_user_guilds(access_token)

        # 封裝 Session Token
        session_token = create_session_token({
            "user": user_profile,
            "guilds": user_guilds,
            "access_token": access_token,
        })

        response = web.HTTPFound("/")
        max_age = config.web_panel.session_max_age_days * 86400
        response.set_cookie(
            name="zn_session",
            value=session_token,
            max_age=max_age,
            path="/",
            httponly=True,
            samesite="Lax",
        )
        log.info(f"✨ 使用者 {user_profile.get('username')} ({user_profile.get('id')}) 成功透過 Discord OAuth2 登入 Web Panel！")
        return response

    async def _handle_logout(self, request: web.Request) -> web.Response:
        """登出並清除 Session Cookie"""
        response = web.HTTPFound("/")
        response.del_cookie(name="zn_session", path="/")
        return response

    async def start(self) -> None:
        """啟動 Web Panel HTTP 伺服器"""
        if not config.web_panel.enabled:
            log.info("Web Panel 設定為停用，略過啟動。")
            return

        host = config.web_panel.host
        port = config.web_panel.port

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host=host, port=port)
        await self.site.start()
        log.info(f"🌐 ZeroNexus Web Panel 伺服器已就緒：http://{host}:{port} (已綁定連接埠 {port})")

    async def stop(self) -> None:
        """優雅關閉 Web Panel HTTP 伺服器"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        log.info("🛑 ZeroNexus Web Panel 已安全停止。")
