"""ZeroNexus Minecraft Query Engine.

Real-time inspection of Java & Bedrock Minecraft servers and player identities:
- Server List Ping (Java) & RakNet (Bedrock) via mcstatus
- Online players, max players, ping latency, version, and formatted MOTD
- Player skin, 3D body render, avatar, and Mojang official UUID resolution
- 30-second TTL caching to protect target servers from query floods
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

import httpx
from mcstatus import BedrockServer, JavaServer

from zeronexus.core.cache import cache


def strip_minecraft_color_codes(motd_raw: str) -> str:
    """Removes Minecraft section sign color codes like §a, §l, etc."""
    if not motd_raw:
        return ""
    return re.sub(r"§[0-9a-fk-or]", "", motd_raw).strip()


class MinecraftQueryEngine:
    """Asynchronous Minecraft protocol query engine."""

    def __init__(self) -> None:
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=10.0)
        return self._http

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    async def query_java_server(self, host: str, port: int = 25565) -> Dict[str, Any]:
        """Queries a Java Edition server using Server List Ping."""
        if not (1 <= port <= 65535):
            raise ValueError(f"無效連接埠：{port} (必須介於 1 至 65535 之間)")

        clean_host = host.strip().lower()
        if not clean_host:
            raise ValueError("目標主機不可為空")

        # 1. SSRF pre-check before executing any DNS / SRV network probes
        from zeronexus.security.ssrf import validate_safe_host
        is_safe, reason, _ = validate_safe_host(clean_host)
        if not is_safe:
            raise ValueError(f"目標伺服器位址不安全：{reason}")

        cache_key = f"mc:java:{clean_host}:{port}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        # 2. Asynchronous SRV & A record resolution with strict timeout
        try:
            if port == 25565:
                try:
                    server = await asyncio.wait_for(JavaServer.async_lookup(clean_host, timeout=3.0), timeout=5.0)
                except Exception:
                    server = await asyncio.wait_for(JavaServer.async_lookup(f"{clean_host}:{port}", timeout=3.0), timeout=5.0)
            else:
                server = await asyncio.wait_for(JavaServer.async_lookup(f"{clean_host}:{port}", timeout=3.0), timeout=5.0)
        except asyncio.TimeoutError as te:
            raise TimeoutError(f"Minecraft 伺服器 SRV/A 記錄解析逾時：{clean_host}") from te

        # 3. Post-resolution SSRF validation (prevent malicious SRV pointing to internal IP/metadata)
        target_to_check = getattr(server.address, "host", clean_host)
        is_safe, reason, _ = validate_safe_host(target_to_check)
        if not is_safe:
            raise ValueError(f"目標伺服器位址不安全：{reason}")

        # 4. Non-blocking status socket communication with 6.0s timeout
        status = await asyncio.wait_for(server.async_status(), timeout=6.0)
        resolved_port = getattr(server.address, "port", port) or port

        # Clean MOTD
        raw_motd = status.description
        if isinstance(raw_motd, dict):
            raw_motd = raw_motd.get("text", str(raw_motd))
        clean_motd = strip_minecraft_color_codes(str(raw_motd))

        players_sample: List[str] = []
        if status.players.sample:
            players_sample = [p.name for p in status.players.sample]

        result = {
            "edition": "Java Edition",
            "host": host,
            "port": resolved_port,
            "online": True,
            "version": status.version.name,
            "protocol": status.version.protocol,
            "latency_ms": round(status.latency, 2),
            "players_online": status.players.online,
            "players_max": status.players.max,
            "players_sample": players_sample,
            "motd": clean_motd or "無 MOTD 說明",
            "icon": status.icon,
        }
        await cache.set(cache_key, result, ttl=30)
        return result

    async def query_bedrock_server(self, host: str, port: int = 19132) -> Dict[str, Any]:
        """Queries a Bedrock Edition server using RakNet ping."""
        if not (1 <= port <= 65535):
            raise ValueError(f"無效連接埠：{port} (必須介於 1 至 65535 之間)")

        clean_host = host.strip().lower()
        if not clean_host:
            raise ValueError("目標主機不可為空")

        # 1. SSRF pre-check before lookup
        from zeronexus.security.ssrf import validate_safe_host
        is_safe, reason, _ = validate_safe_host(clean_host)
        if not is_safe:
            raise ValueError(f"目標伺服器位址不安全：{reason}")

        cache_key = f"mc:bedrock:{clean_host}:{port}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        # 2. Bedrock lookup with timeout
        try:
            server = await asyncio.wait_for(
                asyncio.to_thread(BedrockServer.lookup, f"{clean_host}:{port}", 3.0),
                timeout=5.0,
            )
        except asyncio.TimeoutError as te:
            raise TimeoutError(f"Minecraft 基岩版伺服器位址解析逾時：{clean_host}") from te

        # 3. Post-lookup SSRF check
        target_to_check = getattr(server.address, "host", clean_host)
        is_safe, reason, _ = validate_safe_host(target_to_check)
        if not is_safe:
            raise ValueError(f"目標伺服器位址不安全：{reason}")

        # 4. Non-blocking RakNet async status query
        status = await asyncio.wait_for(server.async_status(), timeout=6.0)

        clean_motd = strip_minecraft_color_codes(str(status.motd))

        result = {
            "edition": "Bedrock Edition",
            "host": host,
            "port": port,
            "online": True,
            "version": status.version.version,
            "protocol": status.version.protocol,
            "latency_ms": round(status.latency, 2),
            "players_online": status.players.online,
            "players_max": status.players.max,
            "motd": clean_motd or "無 MOTD 說明",
            "gamemode": getattr(status, "gamemode", "Survival"),
        }
        await cache.set(cache_key, result, ttl=30)
        return result

    async def get_player_info(self, username_or_uuid: str) -> Dict[str, Any]:
        """Resolves Mojang UUID and avatar / skin renders for a player username or UUID."""
        raw_input = username_or_uuid.strip()
        if not raw_input:
            raise ValueError("玩家名稱或 UUID 不可為空。")

        # Check if input is a valid UUID (with or without dashes)
        is_uuid_dashes = bool(re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", raw_input))
        is_uuid_raw = bool(re.match(r"^[0-9a-fA-F]{32}$", raw_input))
        is_uuid = is_uuid_dashes or is_uuid_raw

        if not is_uuid and not re.match(r"^[a-zA-Z0-9_]{1,16}$", raw_input):
            raise ValueError(f"不合法的 Minecraft 玩家名稱或 UUID「{username_or_uuid}」（僅支援 1-16 位英數字與底線，或標準 32/36 位 UUID）。")

        cache_key = f"mc:player:{raw_input.lower().replace('-', '')}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        http = await self._get_http()
        player_name = None
        raw_uuid = None
        last_err: Optional[Exception] = None

        if is_uuid:
            clean_uuid = raw_input.replace("-", "").lower()
            # 1. Try Mojang session server
            try:
                url = f"https://sessionserver.mojang.com/session/minecraft/profile/{clean_uuid}"
                resp = await http.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    player_name = data.get("name")
                    raw_uuid = data.get("id", clean_uuid)
                elif resp.status_code == 429:
                    last_err = RuntimeError("Mojang 伺服器回傳頻率受限 (HTTP 429)")
            except (httpx.TimeoutException, asyncio.TimeoutError) as te:
                last_err = TimeoutError(f"連線至 Mojang 官方驗證伺服器逾時：{te}")
            except (httpx.NetworkError, ConnectionError) as ne:
                last_err = ConnectionError(f"無法連線至 Mojang 官方身分伺服器：{ne}")
            except Exception as ex:
                last_err = ex

            # 2. Fallback to PlayerDB if Mojang failed
            if not player_name:
                try:
                    pdb_url = f"https://playerdb.co/api/player/minecraft/{clean_uuid}"
                    resp = await http.get(pdb_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("success"):
                            p = data.get("data", {}).get("player", {})
                            player_name = p.get("username")
                            raw_uuid = p.get("raw_id", clean_uuid)
                    elif resp.status_code == 429 and last_err is None:
                        last_err = RuntimeError("PlayerDB 伺服器回傳頻率受限 (HTTP 429)")
                except (httpx.TimeoutException, asyncio.TimeoutError) as te:
                    if last_err is None:
                        last_err = TimeoutError(f"連線至 PlayerDB 備援伺服器逾時：{te}")
                except (httpx.NetworkError, ConnectionError) as ne:
                    if last_err is None:
                        last_err = ConnectionError(f"無法連線至 PlayerDB 備援伺服器：{ne}")
                except Exception:
                    pass

            if not player_name or not raw_uuid:
                if isinstance(last_err, (TimeoutError, ConnectionError, RuntimeError)):
                    raise last_err
                raise ValueError(f"查無 UUID 為「{raw_input}」的 Minecraft 正版玩家檔案。")

        else:
            clean_name = raw_input
            # 1. Try Mojang username profile
            try:
                url = f"https://api.mojang.com/users/profiles/minecraft/{clean_name}"
                resp = await http.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_uuid = data.get("id")
                    player_name = data.get("name")
                elif resp.status_code == 429:
                    last_err = RuntimeError("Mojang 伺服器回傳頻率受限 (HTTP 429)")
            except (httpx.TimeoutException, asyncio.TimeoutError) as te:
                last_err = TimeoutError(f"連線至 Mojang 官方伺服器逾時：{te}")
            except (httpx.NetworkError, ConnectionError) as ne:
                last_err = ConnectionError(f"無法連線至 Mojang 官方伺服器：{ne}")
            except Exception as ex:
                last_err = ex

            # 2. Fallback to PlayerDB if Mojang failed or rate limited
            if not raw_uuid or not player_name:
                try:
                    pdb_url = f"https://playerdb.co/api/player/minecraft/{clean_name}"
                    resp = await http.get(pdb_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("success"):
                            p = data.get("data", {}).get("player", {})
                            raw_uuid = p.get("raw_id")
                            player_name = p.get("username")
                    elif resp.status_code == 429 and last_err is None:
                        last_err = RuntimeError("PlayerDB 伺服器回傳頻率受限 (HTTP 429)")
                except (httpx.TimeoutException, asyncio.TimeoutError) as te:
                    if last_err is None:
                        last_err = TimeoutError(f"連線至 PlayerDB 備援伺服器逾時：{te}")
                except (httpx.NetworkError, ConnectionError) as ne:
                    if last_err is None:
                        last_err = ConnectionError(f"無法連線至 PlayerDB 備援伺服器：{ne}")
                except Exception:
                    pass

            if not raw_uuid or not player_name:
                if isinstance(last_err, (TimeoutError, ConnectionError, RuntimeError)):
                    raise last_err
                raise ValueError(f"找不到 Minecraft 正版玩家「{clean_name}」之 Mojang 檔案。")

        formatted_uuid = f"{raw_uuid[:8]}-{raw_uuid[8:12]}-{raw_uuid[12:16]}-{raw_uuid[16:20]}-{raw_uuid[20:]}"

        result = {
            "name": player_name,
            "raw_uuid": raw_uuid,
            "formatted_uuid": formatted_uuid,
            "avatar_url": f"https://mc-heads.net/avatar/{raw_uuid}/128",
            "skin_3d_url": f"https://mc-heads.net/body/{raw_uuid}/right",
            "skin_download_url": f"https://crafatar.com/skins/{raw_uuid}",
        }
        await cache.set(cache_key, result, ttl=3600)
        return result

    async def get_player_history(self, username_or_uuid: str) -> Dict[str, Any]:
        """Queries historical name changes for a player using PlayerDB archives."""
        info = await self.get_player_info(username_or_uuid)
        cache_key = f"mc:history:{info['raw_uuid']}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        http = await self._get_http()
        history: List[Dict[str, Any]] = []
        try:
            resp = await http.get(f"https://playerdb.co/api/player/minecraft/{info['raw_uuid']}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    meta = data.get("data", {}).get("player", {}).get("meta", {})
                    name_history = meta.get("name_history", [])
                    if isinstance(name_history, list):
                        for entry in name_history:
                            if isinstance(entry, dict) and "name" in entry:
                                history.append({
                                    "name": entry["name"],
                                    "changed_at": entry.get("changedToAt"),
                                })
            elif resp.status_code == 429:
                raise RuntimeError("PlayerDB 歷史紀錄伺服器頻率受限 (HTTP 429)")
        except (httpx.TimeoutException, asyncio.TimeoutError) as te:
            raise TimeoutError(f"連線至 PlayerDB 歷史紀錄伺服器逾時：{te}") from te
        except (httpx.NetworkError, ConnectionError) as ne:
            raise ConnectionError(f"無法連線至 PlayerDB 歷史紀錄伺服器：{ne}") from ne
        except Exception:
            pass

        result = {
            "player": info,
            "history": history,
        }
        await cache.set(cache_key, result, ttl=3600)
        return result


# Singleton Minecraft engine
mc_query = MinecraftQueryEngine()


def classify_minecraft_error(e: Exception) -> tuple[str, str]:
    """Classifies Minecraft probe exceptions into granular diagnostic reports.
    Returns (title_suffix, detailed_explanation).
    """
    import asyncio
    import socket

    err_str = str(e).lower()
    if "不安全" in str(e) or "ssrf" in err_str or "private" in err_str:
        return (
            "安全防護限制",
            "基於系統安全考量，此伺服器位址無法進行探測。\n\n"
            "🛡️ **原因說明**：系統已嚴格限制對本機網路、內網 IP 或受保護之網路節點進行探測。\n"
            "💡 **您可以嘗試**：請確認輸入的是公開對外開放的 Minecraft 伺服器網址或公網 IP。"
        )
    if (
        isinstance(e, socket.gaierror)
        or "errno -2" in err_str
        or "errno -5" in err_str
        or "getaddrinfo failed" in err_str
        or "name or service not known" in err_str
    ):
        return (
            "網域名稱解析失敗",
            "系統無法透過 DNS 解析您輸入的主機名稱。\n\n"
            "📌 **可能原因**：域名拼寫錯誤、該網域尚未註冊或 DNS 記錄尚未生效（此情況非伺服器關機離線）。\n"
            "💡 **您可以嘗試**：\n"
            "• 仔細檢查伺服器位址拼寫是否正確（例如確認是否有贅字或漏字）\n"
            "• 若伺服器使用數字 IP，請直接輸入完整 IP 位址再次嘗試"
        )
    if isinstance(e, (TimeoutError, asyncio.TimeoutError)) or "timed out" in err_str or "timeout" in err_str:
        return (
            "連線逾時",
            "目標伺服器未在時限內回應探測封包。\n\n"
            "📌 **可能原因**：伺服器目前可能處於離線維護狀態、正在重啟，或是伺服器防火牆限制了探測請求。\n"
            "💡 **您可以嘗試**：\n"
            "• 請向伺服器管理員確認伺服器是否正在開機運行中\n"
            "• 稍候數分鐘後重新執行查詢"
        )
    if isinstance(e, ConnectionRefusedError) or "connection refused" in err_str:
        return (
            "連線被拒絕",
            "目標主機正常在線，但通訊埠拒絕了連線請求。\n\n"
            "📌 **可能原因**：Minecraft 伺服器程式尚未啟動完畢，或者您指定的連接埠 (Port) 不正確。\n"
            "💡 **您可以嘗試**：\n"
            "• 檢查輸入的連接埠是否與伺服器實際開放的 Port 相符（Java 版預設為 25565，基岩版預設為 19132）\n"
            "• 確認該主機上的 Minecraft 伺服器服務是否已完全啟動"
        )
    if (
        isinstance(e, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError))
        or "connection reset" in err_str
        or "network is unreachable" in err_str
        or "no route to host" in err_str
        or "network down" in err_str
        or "connection aborted" in err_str
    ):
        return (
            "網路連線中斷",
            "與目標伺服器的網路通訊連線已被中斷。\n\n"
            "📌 **可能原因**：目標伺服器重置了連線、本地或外部網路路由不可達，或防火牆主動切斷連線。\n"
            "💡 **您可以嘗試**：請確認伺服器網路環境是否穩定，或稍候數分鐘再次嘗試。"
        )
    return (
        "伺服器探測未完成",
        "在與目標伺服器進行通訊時遇到非預期的連線狀況。\n\n"
        "💡 **您可以嘗試**：\n"
        "• 請確認伺服器主機位址與連接埠是否正確\n"
        "• 稍候片刻再次嘗試查詢"
    )


def classify_player_error(e: Exception, player_identifier: str) -> tuple[str, str]:
    """Classifies player lookup exceptions into clear, warm Traditional Chinese diagnostic reports.
    Returns (title_suffix, detailed_explanation).
    """
    import asyncio
    import httpx

    err_str = str(e).lower()
    if "不安全" in str(e) or "ssrf" in err_str:
        return (
            "安全防護限制",
            "基於系統安全考量，此玩家名稱或查詢參數無法被檢索。\n\n"
            "🛡️ **原因說明**：輸入內容未通過安全檢查。\n"
            "💡 **您可以嘗試**：請確認輸入的是合法的 Mojang 正版玩家名稱或標準 UUID。"
        )
    if (
        isinstance(e, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException))
        or "timeout" in err_str
        or "timed out" in err_str
        or "逾時" in str(e)
    ):
        return (
            "連線逾時 (Mojang 官方伺服器回應緩慢)",
            f"在向 Mojang / PlayerDB 官方服務檢索玩家 **`{player_identifier}`** 資料時發生連線逾時。\n\n"
            "📌 **可能原因**：Mojang 官方身分驗證伺服器目前回應過慢、網路壅塞或外部 API 暫時性延遲。\n"
            "💡 **您可以嘗試**：\n"
            "• 請稍候數分鐘後再次執行指令\n"
            "• 若持續逾時，可至 Mojang 官方狀態頁確認驗證伺服器是否正常運作"
        )
    if (
        isinstance(e, (ConnectionError, httpx.NetworkError))
        or "connect" in err_str
        or "斷線" in str(e)
        or "network" in err_str
        or "無法連線" in str(e)
    ):
        return (
            "網路連線異常",
            "無法建立與 Mojang / PlayerDB 身分驗證伺服器的網路連線。\n\n"
            "📌 **可能原因**：對外網路連線中斷，或目標 API 伺服器暫時無法連通。\n"
            "💡 **您可以嘗試**：請檢查網路連線狀態或稍候重試。"
        )
    if "429" in err_str or "rate limit" in err_str or "頻率" in str(e):
        return (
            "查詢頻率受限 (Rate Limit)",
            "Mojang / PlayerDB 官方 API 查詢頻率已達上限。\n\n"
            "📌 **可能原因**：官方針對玩家外觀與 UUID 查詢設有頻率限制。\n"
            "💡 **您可以嘗試**：請稍候 1 至 2 分鐘後再次查詢。"
        )
    if "不合法" in str(e) or "格式" in str(e):
        return (
            "輸入格式不符規範",
            f"{e}\n\n"
            "💡 **格式提示**：正版 Minecraft ID 需為 1-16 碼英數字與底線，UUID 需為 32 碼純十六進位或 36 碼含連字號格式。"
        )
    return (
        "找不到玩家資料",
        f"在 Mojang 官方資料庫中查無玩家 **`{player_identifier}`** 的正版帳號資料。\n\n"
        "💡 **您可以嘗試**：\n"
        "• 請仔細確認玩家 ID 英文大小寫與拼寫是否正確\n"
        "• 確認該玩家是否已購買並啟用 Minecraft 正版帳號\n"
        "• 若剛於遊戲內更換皮膚或更名，官方快取可能需要數分鐘同步"
    )


