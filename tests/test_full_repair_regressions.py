from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zeronexus.ai_gateway.quota_service import QuotaReservation, QuotaService
from zeronexus.core.stats import StatsTracker
from zeronexus.engines.cwa_location import cwa_location_resolver
from zeronexus.modules.music.dashboard import NowPlayingView


def test_stats_image_generation_api_and_false_attempt() -> None:
    tracker = StatsTracker()
    tracker.record_image_generation(True)
    tracker.record_image_generation(False)
    assert tracker.images_generated == 1
    assert tracker.summary()["usage"]["images_generated"] == 1


def test_empty_location_query_does_not_become_taiwan_overview() -> None:
    result = cwa_location_resolver.resolve("")
    assert not result.is_overview
    assert not result.is_matched


@pytest.mark.asyncio
async def test_quota_commit_after_day_rollover_releases_without_charging(monkeypatch) -> None:
    service = QuotaService()
    reservation = QuotaReservation(123, "2026-01-01", "r1", 80, False, 1)
    service._active_reservations["r1"] = reservation
    service._in_flight[123] = 1
    monkeypatch.setattr(service, "get_today_str", lambda: "2026-01-02")

    await service.commit_quota(reservation)

    assert reservation.released
    assert not reservation.committed
    assert "r1" not in service._active_reservations
    assert service._in_flight[123] == 0


@pytest.mark.asyncio
async def test_guild_daily_quota_override_is_used(monkeypatch) -> None:
    from zeronexus.models.guild import GuildSettings
    from zeronexus.core import database
    import importlib
    quota_module = importlib.import_module("zeronexus.ai_gateway.quota_service")

    service = QuotaService()
    original_session = database.db.session

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, model, guild_id):
            assert model is GuildSettings
            assert guild_id == 42
            return SimpleNamespace(ai_daily_limit=17)

        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))

    monkeypatch.setattr(database.db, "session", lambda: FakeSession())
    monkeypatch.setattr(quota_module.config.discord, "is_dev", lambda _: False)
    try:
        allowed, reservation, used, limit = await service.reserve_quota(54321, guild_id=42)
    finally:
        monkeypatch.setattr(database.db, "session", original_session)

    assert allowed and reservation
    assert used == 1
    assert limit == 17


@pytest.mark.asyncio
async def test_music_dashboard_rejects_other_guild_and_other_voice_channel(monkeypatch) -> None:
    import zeronexus.modules.music.dashboard as dashboard_module

    player = SimpleNamespace(channel=SimpleNamespace(id=10), queue=SimpleNamespace(mode=None))
    view = NowPlayingView(player, 100, guild_id=1, text_channel_id=20)
    send = AsyncMock()
    monkeypatch.setattr(dashboard_module.InteractionResponder, "safe_send", send)
    other_guild = SimpleNamespace(guild_id=2, user=SimpleNamespace(id=5, voice=SimpleNamespace(channel=SimpleNamespace(id=10))))
    assert not await view.interaction_check(other_guild)
    wrong_voice = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=5, voice=SimpleNamespace(channel=SimpleNamespace(id=11))))
    assert not await view.interaction_check(wrong_voice)
    send.assert_awaited()
