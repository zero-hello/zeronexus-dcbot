import asyncio
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


@pytest.mark.asyncio
async def test_ai_cancel_callback_releases_reservations_without_blocking_button() -> None:
    from zeronexus.ui.views import AICancelView

    cancelled = asyncio.Event()

    async def callback():
        cancelled.set()

    view = AICancelView(author_id=10, author_name="tester", on_cancelled=callback)
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=10),
        response=SimpleNamespace(is_done=lambda: False, edit_message=AsyncMock()),
        message=None,
    )
    await view._on_cancel_click(interaction)
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    assert view.is_cancelled


def test_ai_opt_out_memory_flag_is_available_and_explicit() -> None:
    from zeronexus.modules.ai.cog import AICog

    command = AICog.ai_group.get_command("對話")
    assert command is not None
    option = next(parameter for parameter in command.parameters if parameter.name == "不使用記憶")
    assert option.required is False


def test_standalone_faq_and_search_commands_are_registered() -> None:
    from zeronexus.modules.standalone.cog import StandaloneCog

    command_names = {command.name for command in StandaloneCog.__cog_app_commands__}
    assert {"常見問題", "搜尋指令", "幫助"}.issubset(command_names)


def test_music_queue_management_commands_are_registered() -> None:
    from zeronexus.modules.music.cog import MusicCog

    names = {command.name for command in MusicCog.music_group.commands}
    assert {"隊列", "移除隊列", "清空隊列"}.issubset(names)


def test_gateway_quota_model_identity_matches_openrouter_and_native_models() -> None:
    from zeronexus.ai_gateway.gateway import AIGateway

    assert AIGateway.resolve_route_model("openrouter", "google/gemma-4-26b-a4b-it:free") == "google/gemma-4-26b-a4b-it:free"
    assert AIGateway.resolve_route_model("openrouter", "free-model") == "openrouter/free-model"
    assert AIGateway.resolve_route_model("deepseek", "deepseek/deepseek-chat") == "deepseek-chat"


def test_model_catalog_capability_and_cost_labels_are_user_facing() -> None:
    from zeronexus.ui.model_select_view import format_model_user_labels

    labels = format_model_user_labels({"text", "vision", "tools"}, is_free=False)
    assert "文字" in labels
    assert "圖片理解" in labels
    assert "即時工具" in labels
    assert "可能依供應商計費" in labels


@pytest.mark.asyncio
async def test_model_quota_reservation_reassignment_moves_inflight_counter(monkeypatch) -> None:
    import importlib
    from zeronexus.core import database

    quota_module = importlib.import_module("zeronexus.ai_gateway.quota_service")
    service = QuotaService()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))

    monkeypatch.setattr(database.db, "session", lambda: FakeSession())
    monkeypatch.setattr(quota_module.config.discord, "is_dev", lambda _: False)
    monkeypatch.setattr(service, "get_today_str", lambda: "2026-01-01")
    monkeypatch.setattr(service, "get_model_default_limit", lambda model: 3)

    allowed, reservation, _, _ = await service.reserve_model_quota(123, "model-a")
    assert allowed and reservation
    moved, _, _ = await service.reassign_model_reservation(reservation, "model-b")

    assert moved
    assert service._model_in_flight.get((123, "model-a"), 0) == 0
    assert service._model_in_flight[(123, "model-b")] == 1
