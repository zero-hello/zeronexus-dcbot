"""ZeroNexus Lavalink Node Probe Engine.

非同步探測節點健康狀態、連線延遲、Lavalink 版本以及 YouTube 音訊來源支援狀態。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp



@dataclass
class ProbeResult:
    """節點探測評估結果。"""
    host: str
    port: int
    password: str
    secure: bool
    identifier: str = ""
    is_online: bool = False
    latency_ms: float = 9999.0
    version_semver: str = ""
    is_v4: bool = False
    plugins: List[str] = field(default_factory=list)
    supports_youtube: bool = False
    has_yt_sosor: bool = False
    error_message: Optional[str] = None


class NodeProbe:
    """Lavalink 節點非同步探針。"""

    YOUTUBE_PLUGIN_KEYWORDS = {"youtube", "yt-sosor", "dunctebot", "youtube-plugin"}

    @classmethod
    async def probe_node(
        cls,
        host: str,
        port: int,
        password: str,
        secure: bool = False,
        identifier: str = "",
        timeout_seconds: float = 4.0,
    ) -> ProbeResult:
        """非同步探測單一 Lavalink 節點之在線狀態、延遲與功能插件。"""
        protocol = "https" if secure else "http"
        base_url = f"{protocol}://{host}:{port}"
        info_url = f"{base_url}/v4/info"
        ident = identifier or f"{host}:{port}"

        result = ProbeResult(
            host=host,
            port=port,
            password=password,
            secure=secure,
            identifier=ident,
        )

        headers = {
            "Authorization": password,
            "User-Agent": "ZeroNexus-Music/1.2.0 (AudioProbe)",
        }

        start_time = time.perf_counter()
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(info_url, headers=headers) as resp:
                    elapsed = (time.perf_counter() - start_time) * 1000.0
                    result.latency_ms = round(elapsed, 1)

                    if resp.status == 200:
                        data = await resp.json()
                        result.is_online = True
                        result.is_v4 = True
                        ver_info = data.get("version", {})
                        result.version_semver = str(ver_info.get("semver", "v4-unknown"))

                        raw_plugins = data.get("plugins", [])
                        plugin_names = [p.get("name", "") for p in raw_plugins if isinstance(p, dict)]
                        result.plugins = plugin_names

                        # 檢查插件清單是否包含 YouTube 相關插件與 yt-sosor
                        for p_name in plugin_names:
                            low = p_name.lower()
                            if "yt-sosor" in low:
                                result.has_yt_sosor = True
                            if any(k in low for k in cls.YOUTUBE_PLUGIN_KEYWORDS):
                                result.supports_youtube = True

                        # 額外發送一次極輕量載入探測驗證 YouTube 實質支援
                        if result.supports_youtube:
                            try:
                                test_yt_url = f"{base_url}/v4/loadtracks?identifier=ytsearch:Never%20Gonna%20Give%20You%20Up"
                                async with session.get(test_yt_url, headers=headers) as yt_resp:
                                    if yt_resp.status == 200:
                                        yt_data = await yt_resp.json()
                                        load_type = yt_data.get("loadType", "")
                                        if load_type in ("track", "playlist", "search"):
                                            result.supports_youtube = True
                                        elif load_type == "error":
                                            result.supports_youtube = False
                            except Exception:
                                pass
                    elif resp.status in (401, 403):
                        result.error_message = f"驗證授權失敗 (HTTP {resp.status})"
                    else:
                        # 探測是否為 v3 節點 (v3 具有 /version 端點)
                        v3_url = f"{base_url}/version"
                        async with session.get(v3_url, headers=headers) as v3_resp:
                            if v3_resp.status == 200:
                                result.is_online = True
                                result.is_v4 = False
                                result.version_semver = (await v3_resp.text()).strip()
                            else:
                                result.error_message = f"HTTP {resp.status}"
        except asyncio.TimeoutError:
            result.error_message = "連線超時"
        except Exception as ex:
            result.error_message = str(ex)
        finally:
            if not connector.closed:
                await connector.close()

        return result

    @classmethod
    async def probe_multiple(
        cls,
        nodes: List[Dict[str, Any]],
        concurrency: int = 10,
        timeout_seconds: float = 4.0,
    ) -> List[ProbeResult]:
        """併發批量探測多個節點。"""
        semaphore = asyncio.Semaphore(concurrency)

        async def _worker(node_dict: Dict[str, Any]) -> ProbeResult:
            async with semaphore:
                return await cls.probe_node(
                    host=str(node_dict.get("host", "")).strip(),
                    port=int(node_dict.get("port", 2333)),
                    password=str(node_dict.get("password", "youshallnotpass")).strip(),
                    secure=bool(node_dict.get("secure", False)),
                    identifier=str(node_dict.get("name") or node_dict.get("identifier") or node_dict.get("host", "")),
                    timeout_seconds=timeout_seconds,
                )

        tasks = [_worker(n) for n in nodes if n.get("host")]
        if not tasks:
            return []
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)
