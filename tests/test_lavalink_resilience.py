from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("wavelink")

from zeronexus.core.config import AudioNodeConfig, config
from zeronexus.lavalink.node_pool import NodePoolManager
from zeronexus.lavalink.probe import ProbeResult


@pytest.mark.asyncio
async def test_node_pool_does_not_connect_unhealthy_nodes() -> None:
    manager = NodePoolManager()
    node = AudioNodeConfig(
        host="unresolvable.example",
        port=443,
        password="test-password",
        secure=True,
        identifier="unhealthy-test-node",
    )
    old_nodes = config.music.nodes
    config.music.nodes = [node]

    try:
        with (
            patch("zeronexus.lavalink.node_pool.NodeProbe.probe_multiple", new=AsyncMock(return_value=[])),
            patch("zeronexus.lavalink.node_pool.wavelink.Pool.connect", new=AsyncMock()) as connect,
        ):
            await manager.initialize(object())
        connect.assert_not_awaited()
        assert manager._initialized
    finally:
        config.music.nodes = old_nodes
        from zeronexus.lavalink.node_pool import NodePoolManager as Manager

        Manager._instance = None


@pytest.mark.asyncio
async def test_scraped_public_nodes_are_probed_without_private_allowlist() -> None:
    manager = NodePoolManager()
    old_nodes = config.music.nodes
    old_discovery = config.music.auto_fetch_public_nodes
    config.music.nodes = []
    config.music.auto_fetch_public_nodes = True
    public_node = {
        "name": "public-test-node",
        "host": "public.example",
        "port": 443,
        "password": "public-password",
        "secure": True,
    }
    healthy_probe = ProbeResult(
        host="public.example",
        port=443,
        password="public-password",
        secure=True,
        identifier="public-test-node",
        is_online=True,
        is_v4=True,
        supports_youtube=True,
        latency_ms=10,
    )

    try:
        with (
            patch("zeronexus.lavalink.node_pool.PublicNodeScraper.discover_public_nodes", new=AsyncMock(return_value=[public_node])),
            patch("zeronexus.lavalink.node_pool.NodeProbe.probe_multiple", new=AsyncMock(side_effect=[[healthy_probe]])) as probe,
            patch(
                "zeronexus.lavalink.node_pool.wavelink.Node",
                side_effect=lambda **kwargs: SimpleNamespace(**kwargs),
            ),
            patch("zeronexus.lavalink.node_pool.wavelink.Pool.connect", new=AsyncMock()) as connect,
        ):
            await manager.initialize(object())

        assert probe.await_count == 1
        assert probe.await_args_list[0].args[0] == [public_node]
        connect.assert_awaited_once()
        assert manager._initialized
    finally:
        config.music.nodes = old_nodes
        config.music.auto_fetch_public_nodes = old_discovery
        from zeronexus.lavalink.node_pool import NodePoolManager as Manager

        Manager._instance = None
