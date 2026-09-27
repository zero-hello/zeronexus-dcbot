from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("wavelink")

from zeronexus.core.config import AudioNodeConfig, config
from zeronexus.lavalink.node_pool import NodePoolManager


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
