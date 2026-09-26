"""ZeroNexus Public Lavalink Node Scraper.

從 DarrenOfficial 與 Serenetia 等公開即時節點來源提取公開 Lavalink 節點資訊。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import aiohttp

from zeronexus.core.logger import log


class PublicNodeScraper:
    """公開 Lavalink 節點抓取器。"""

    DARREN_SSL_URL = "https://raw.githubusercontent.com/DarrenOfficial/lavalink-list/master/docs/SSL/Lavalink-SSL.md"
    DARREN_NON_SSL_URL = "https://raw.githubusercontent.com/DarrenOfficial/lavalink-list/master/docs/NoSSL/Lavalink-NonSSL.md"

    NODE_PATTERN = re.compile(
        r"Host\s*:\s*([^\s\n]+)[\s\S]*?"
        r"Port\s*:\s*(\d+)[\s\S]*?"
        r"Password\s*:\s*\"?([^\n\"]+)\"?",
        re.IGNORECASE,
    )

    @classmethod
    async def fetch_nodes_from_url(cls, url: str, is_ssl: bool = True) -> List[Dict[str, Any]]:
        """自指定 Markdown 網址解析節點配置。"""
        nodes: List[Dict[str, Any]] = []
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            # 【安全修復】恢復 TLS 憑證驗證：此處抓取之節點清單會使 Bot 主動外連，
            # 關閉驗證將構成 MITM 供應鏈投毒面（攻擊者可注入惡意節點位址）
            connector = aiohttp.TCPConnector()
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(url, headers={"User-Agent": "ZeroNexus-Scraper/1.2.0"}) as resp:
                    if resp.status != 200:
                        return []
                    text = await resp.text()

            matches = cls.NODE_PATTERN.findall(text)
            for host, port, pwd in matches:
                clean_host = host.strip()
                clean_pwd = pwd.strip().strip('"')
                if not clean_host:
                    continue
                nodes.append({
                    "name": f"{clean_host}:{port}",
                    "host": clean_host,
                    "port": int(port),
                    "password": clean_pwd,
                    "secure": is_ssl,
                })
        except Exception as ex:
            log.debug(f"[LavalinkScraper] Failed to fetch nodes from {url}: {ex}")
        return nodes

    @classmethod
    async def discover_public_nodes(cls) -> List[Dict[str, Any]]:
        """動態彙整三大公開來源之節點清單。"""
        ssl_nodes = await cls.fetch_nodes_from_url(cls.DARREN_SSL_URL, is_ssl=True)
        non_ssl_nodes = await cls.fetch_nodes_from_url(cls.DARREN_NON_SSL_URL, is_ssl=False)

        # 加入 Serenetia 與經典熱門公用節點兜底備選
        fallback_seeds = [
            {"name": "Serenetia-V4-SSL", "host": "lavalinkv4.serenetia.com", "port": 443, "password": "https://seretia.link/discord", "secure": True},
            {"name": "MilloHost-V4-SSL", "host": "lava-v4.millohost.my.id", "port": 443, "password": "youshallnotpass", "secure": True},
            {"name": "TriniumHost-V4-SSL", "host": "lavalink-v4.triniumhost.com", "port": 443, "password": "free", "secure": True},
        ]

        seen_hosts = set()
        unique_nodes: List[Dict[str, Any]] = []

        # 優先放入種子節點
        for n in fallback_seeds + ssl_nodes + non_ssl_nodes:
            key = (n["host"], n["port"])
            if key not in seen_hosts:
                seen_hosts.add(key)
                unique_nodes.append(n)

        log.info(f"[LavalinkScraper] 成功採集到 {len(unique_nodes)} 個候選公共節點。")
        return unique_nodes
