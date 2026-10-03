"""Focused mocked regressions for core lifecycle, quota and channel isolation."""

import asyncio
import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from zeronexus.ai_gateway.quota_service import QuotaService
from zeronexus.core.database import DatabaseManager
from zeronexus.engines.channel_inspector import ChannelInspectorEngine


@pytest.fixture
def quota_db(monkeypatch):
    module = importlib.import_module("zeronexus.ai_gateway.quota_service")
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None, all=lambda: []))
    session = SimpleNamespace(execute=AsyncMock(return_value=result), add=Mock(), flush=AsyncMock())

    @asynccontextmanager
    async def session_scope():
        yield session

    monkeypatch.setattr(module.db, "session", session_scope)
    monkeypatch.setattr(module.config.discord, "is_dev", lambda _: False)
    return session


async def _reserve(service, kind):
    if kind == "model":
        return (await service.reserve_model_quota(42, "test-model"))[1]
    method = service.reserve_image_quota if kind == "image" else service.reserve_quota
    return (await method(42, max_daily_override=1))[1]


async def _commit(service, kind, reservation):
    method = {
        "text": service.commit_quota,
        "image": service.commit_image_quota,
        "model": service.commit_model_quota,
    }[kind]
    await method(reservation)


async def _reset(service, kind, date=None):
    method = {
        "text": service.reset_user_quota,
        "image": service.reset_user_image_quota,
        "model": service.reset_user_model_quotas,
    }[kind]
    await method(42, date_str=date)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "image", "model"])
async def test_quota_lock_pruning_preserves_pending_database_operation(quota_db, kind):
    service = QuotaService()
    service.MAX_TRACKED_LOCKS = 1
    entered = asyncio.Event()
    unblock = asyncio.Event()
    result = quota_db.execute.return_value

    async def execute(statement):
        entered.set()
        await unblock.wait()
        return result

    quota_db.execute.side_effect = execute
    first = asyncio.create_task(_reserve(service, kind))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        # The first reserve owns a lock but has not created its reservation yet.
        service._get_user_lock(99)
        second = asyncio.create_task(_reserve(service, kind))
        await asyncio.sleep(0)
        assert quota_db.execute.await_count == 1, "same-user queries escaped serialization"
    finally:
        unblock.set()
        tasks = [task for task in (first, second) if task is not None]
        await asyncio.gather(*tasks)
    assert first.result() is not None
    if kind != "model":
        assert second.result() is None, "limit-one quota admitted a second reservation"


@pytest.mark.asyncio
async def test_quota_lock_pruning_preserves_awakened_waiter():
    service = QuotaService()
    service.MAX_TRACKED_LOCKS = 1
    lock = service._get_user_lock(42)
    await lock.acquire()
    waiter = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0)
    lock.release()
    # Lock is temporarily unlocked while its awakened waiter is still queued.
    service._get_user_lock(99)
    try:
        assert service._get_user_lock(42) is lock
    finally:
        await waiter
        lock.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved_kind,reset_kind", [
    ("text", "image"), ("model", "image"), ("image", "text"),
    ("text", "model"), ("image", "model"),
])
async def test_quota_reset_does_not_cancel_unrelated_usage(quota_db, reserved_kind, reset_kind):
    service = QuotaService()
    reservation = await _reserve(service, reserved_kind)
    await _reset(service, reset_kind)
    await _commit(service, reserved_kind, reservation)
    assert reservation.committed
    assert not reservation.released
    quota_db.add.assert_called_once()
    assert quota_db.add.call_args.args[0].used_count == 1
    quota_db.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "image", "model"])
async def test_historical_quota_reset_does_not_cancel_today(quota_db, kind):
    service = QuotaService()
    reservation = await _reserve(service, kind)
    await _reset(service, kind, "2000-01-01")
    await _commit(service, kind, reservation)
    assert reservation.committed and not reservation.released
    quota_db.add.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "image", "model"])
async def test_matching_quota_reset_still_invalidates_inflight_reservation(quota_db, kind):
    service = QuotaService()
    reservation = await _reserve(service, kind)
    await _reset(service, kind)
    await _commit(service, kind, reservation)
    assert reservation.released and not reservation.committed
    quota_db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_database_close_drains_disposal_and_propagates_cancellation(cancel_count):
    manager = DatabaseManager()
    started = asyncio.Event()
    finish = asyncio.Event()
    disposed = asyncio.Event()

    async def dispose():
        started.set()
        await finish.wait()
        disposed.set()

    engine = SimpleNamespace(dispose=AsyncMock(side_effect=dispose))
    manager.engine = engine
    manager.session_factory = Mock()
    manager._is_initialized = True
    closing = asyncio.create_task(manager.close())
    try:
        await asyncio.wait_for(started.wait(), 1)
        for _ in range(cancel_count):
            closing.cancel()
            await asyncio.sleep(0)
        assert not disposed.is_set()
    finally:
        finish.set()
        outcome = (await asyncio.gather(closing, return_exceptions=True))[0]
    assert isinstance(outcome, asyncio.CancelledError)
    assert disposed.is_set(), "caller cancellation interrupted pool disposal"
    assert manager.engine is None
    assert manager.session_factory is None
    assert not manager._is_initialized
    engine.dispose.assert_awaited_once()


def _thread_context(*, member=False, manage_threads=False, private=True):
    guild = SimpleNamespace(id=1)
    bot = SimpleNamespace(id=10, guild=guild)
    requester = SimpleNamespace(id=20, guild=guild)
    guild.me = bot
    channel = SimpleNamespace(
        guild=guild,
        name="private-thread",
        type=discord.ChannelType.private_thread if private else discord.ChannelType.public_thread,
        permissions_for=lambda who: SimpleNamespace(
            view_channel=True, read_message_history=True, manage_threads=manage_threads,
        ),
        get_member=lambda user_id: SimpleNamespace(id=user_id) if member else None,
        # Bot membership must not confer membership on a requester.
        me=SimpleNamespace(id=bot.id),
        history=Mock(),
    )
    return guild, requester, channel


@pytest.mark.asyncio
async def test_private_thread_nonmember_cannot_read_history():
    guild, requester, channel = _thread_context()
    messages, error = await ChannelInspectorEngine().fetch_channel_messages(
        channel, requester=requester, expected_guild=guild,
    )
    assert messages == [] and error and "私密討論串" in error
    channel.history.assert_not_called()


@pytest.mark.parametrize("member,manager,private", [(True, False, True), (False, True, True), (False, False, False)])
def test_thread_access_preserves_members_managers_and_public_threads(member, manager, private):
    guild, requester, channel = _thread_context(member=member, manage_threads=manager, private=private)
    assert ChannelInspectorEngine.authorize_channel_access(channel, requester, guild) is None


def test_private_thread_missing_membership_cache_fails_closed():
    guild, requester, channel = _thread_context()
    del channel.get_member
    assert ChannelInspectorEngine.authorize_channel_access(channel, requester, guild) is not None
