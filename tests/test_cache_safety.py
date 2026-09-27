import asyncio
import json
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from zeronexus.core.cache import CacheManager


@pytest.mark.asyncio
async def test_redis_cache_uses_json_without_pickle() -> None:
    manager = CacheManager()
    manager._use_redis = True
    manager._redis = AsyncMock()
    manager._redis.get.return_value = json.dumps({"status": "ok"}).encode()

    assert await manager.get("health") == {"status": "ok"}

    await manager.set("health", {"status": "ready"}, ttl=60)
    written = manager._redis.setex.await_args.args[2]
    assert json.loads(written) == {"status": "ready"}


@pytest.mark.asyncio
async def test_close_cancels_cleanup_task_and_can_reinitialize() -> None:
    manager = CacheManager()
    await manager.initialize()
    cleanup_task = manager._cleanup_task
    assert cleanup_task is not None

    await manager.close()

    assert cleanup_task.cancelled()
    assert manager._cleanup_task is None
    await manager.initialize()
    assert manager._cleanup_task is not None
    await manager.close()


@pytest.mark.asyncio
async def test_redis_pickle_payload_is_rejected() -> None:
    manager = CacheManager()
    manager._use_redis = True
    manager._redis = AsyncMock()
    manager._redis.get.return_value = b"\x80\x04N."

    with patch.object(manager._memory, "get", new=AsyncMock(return_value=None)) as memory_get:
        assert await manager.get("legacy") is None
        memory_get.assert_awaited_once_with("legacy")
