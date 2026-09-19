"""ZeroNexus Lavalink Multi-Node Pool Manager.

管理多節點連線池、動態容錯轉移 (Failover)、公共節點探測與伺服器音量持久化。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from discord.ext import commands
import wavelink

from zeronexus.core.config import config
from zeronexus.core.logger import log
from zeronexus.lavalink.probe import NodeProbe
from zeronexus.lavalink.scraper import PublicNodeScraper

VOLUME_STORE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "music_volumes.json"


class NodePoolManager:
    """ZeroNexus 多節點連線池管理器。"""

    _instance: Optional[NodePoolManager] = None

    def __init__(self, bot: Optional[commands.Bot] = None) -> None:
        self.bot = bot
        self._guild_volumes: Dict[int, int] = {}
        self._load_volumes()
        self._lock = asyncio.Lock()
        self._initialized = False

    @classmethod
    def get_instance(cls, bot: Optional[commands.Bot] = None) -> NodePoolManager:
        if cls._instance is None:
            cls._instance = cls(bot)
        elif bot is not None and cls._instance.bot is None:
            cls._instance.bot = bot
        return cls._instance

    def _load_volumes(self) -> None:
        """從硬碟讀取各伺服器設定之音量。"""
        try:
            if VOLUME_STORE_PATH.exists():
                data = json.loads(VOLUME_STORE_PATH.read_text(encoding="utf-8"))
                self._guild_volumes = {int(k): int(v) for k, v in data.items()}
        except Exception as ex:
            log.debug(f"[NodePoolManager] 載入音量紀錄失敗: {ex}")

    def _save_volumes(self) -> None:
        """持久化儲存各伺服器音量至硬碟。"""
        try:
            VOLUME_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {str(k): v for k, v in self._guild_volumes.items()}
            VOLUME_STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as ex:
            log.debug(f"[NodePoolManager] 寫入音量紀錄失敗: {ex}")

    def get_guild_volume(self, guild_id: int) -> int:
        """取得指定伺服器的音量（預設 100%）。"""
        return self._guild_volumes.get(guild_id, config.music.default_volume)

    def set_guild_volume(self, guild_id: int, volume: int) -> None:
        """更新並持久化儲存指定伺服器的音量。"""
        clamped = max(0, min(config.music.max_volume, volume))
        self._guild_volumes[guild_id] = clamped
        self._save_volumes()

    async def initialize(self, bot: commands.Bot) -> None:
        """初始化 Lavalink 節點池並連線。"""
        async with self._lock:
            if self._initialized:
                return
            self.bot = bot

            # 1. 取得靜態節點
            seed_nodes: List[Dict[str, Any]] = []
            for n in config.music.nodes:
                seed_nodes.append({
                    "name": n.identifier or n.host,
                    "host": n.host,
                    "port": n.port,
                    "password": n.password,
                    "secure": n.secure,
                })

            # 2. 若啟用公共節點自動探測，自清單探測在線節點
            candidate_nodes = list(seed_nodes)
            if config.music.auto_fetch_public_nodes:
                try:
                    scraped = await PublicNodeScraper.discover_public_nodes()
                    candidate_nodes.extend(scraped)
                except Exception as ex:
                    log.warning(f"[NodePoolManager] 公共節點抓取失敗: {ex}")

            # 3. 執行探針篩選可用且支援 YouTube 的前 3~5 名節點
            log.info(f"[NodePoolManager] 正在探測 {len(candidate_nodes)} 個候選節點...")
            probe_results = await NodeProbe.probe_multiple(candidate_nodes, concurrency=10, timeout_seconds=4.0)

            valid_probes = [p for p in probe_results if p.is_online and p.is_v4]
            # 優先以「支援 YouTube」與「延遲最低」排序
            valid_probes.sort(key=lambda p: (not p.supports_youtube, p.latency_ms))

            if not valid_probes:
                log.warning("[NodePoolManager] 探測無可用公共節點，回退至預設靜態配置。")
                valid_probes = [
                    NodeProbe.probe_node(
                        host=n.host,
                        port=n.port,
                        password=n.password,
                        secure=n.secure,
                        identifier=n.identifier,
                    )
                    for n in config.music.nodes
                ]
                valid_probes = await asyncio.gather(*valid_probes)

            selected = [p for p in valid_probes if p.is_online][:4]
            if not selected and valid_probes:
                selected = valid_probes[:2]

            seen_identifiers = set()
            seen_endpoints = set()
            wavelink_nodes: List[wavelink.Node] = []
            for sp in selected:
                ep = (sp.host.lower(), sp.port)
                if ep in seen_endpoints:
                    continue
                seen_endpoints.add(ep)

                base_ident = sp.identifier or f"{sp.host}:{sp.port}"
                ident = base_ident
                counter = 1
                while ident in seen_identifiers:
                    ident = f"{base_ident}-{counter}"
                    counter += 1
                seen_identifiers.add(ident)

                proto = "https" if sp.secure else "http"
                uri = f"{proto}://{sp.host}:{sp.port}"
                node = wavelink.Node(
                    identifier=ident,
                    uri=uri,
                    password=sp.password,
                    inactive_player_timeout=config.music.auto_leave_seconds,
                )
                wavelink_nodes.append(node)
                yt_tag = " [YouTube ✅]" if sp.supports_youtube else " [YouTube ❌]"
                log.info(f"[NodePoolManager] 裝載節點: {node.identifier} ({node.uri}) 延遲: {sp.latency_ms}ms{yt_tag}")

            if wavelink_nodes:
                try:
                    await wavelink.Pool.connect(nodes=wavelink_nodes, client=bot, cache_capacity=100)
                    self._initialized = True
                    log.info(f"[NodePoolManager] 成功連線至 {len(wavelink_nodes)} 個 Lavalink 節點！")
                except Exception as ex:
                    log.error(f"[NodePoolManager] Wavelink 節點池連線發生例外: {ex}")
            else:
                log.error("[NodePoolManager] 找不到任何可用的 Lavalink 節點！")

    @classmethod
    async def handle_node_disconnect(cls, node: wavelink.Node) -> None:
        """當節點中斷連線時之容錯處理與日誌紀錄。"""
        log.warning(f"[NodePoolManager] 節點斷線: {node.identifier} ({node.uri})，Pool 正在自動遷移活躍播放器。")
