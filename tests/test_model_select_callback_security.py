from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from zeronexus.ui.model_select_view import ModelSelectDropdown
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ai_gateway.model_switch_service import model_switch_service


@pytest.mark.asyncio
async def test_public_model_dropdown_rejects_another_user(monkeypatch):
    dropdown = ModelSelectDropdown(options=[], user_id=100)
    interaction = SimpleNamespace(user=SimpleNamespace(id=200))
    send = AsyncMock()
    switch = AsyncMock()
    monkeypatch.setattr(InteractionResponder, "safe_send", send)
    monkeypatch.setattr(model_switch_service, "switch_model", switch)

    await dropdown.callback(interaction)

    send.assert_awaited_once()
    switch.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_model_dropdown_rechecks_current_admin_permission(monkeypatch):
    from zeronexus.security.permissions import PermissionEngine, ZNPermissionLevel

    user = SimpleNamespace(id=100)
    guild = SimpleNamespace(id=5)
    interaction = SimpleNamespace(user=user, guild=guild, guild_id=5)
    dropdown = ModelSelectDropdown(options=[], user_id=100, guild_id=5, is_server=True)
    send = AsyncMock()
    switch = AsyncMock()
    monkeypatch.setattr(PermissionEngine, "resolve_level", lambda _user, _guild: ZNPermissionLevel.EVERYONE)
    monkeypatch.setattr(InteractionResponder, "safe_send", send)
    monkeypatch.setattr(model_switch_service, "switch_model", switch)

    await dropdown.callback(interaction)

    send.assert_awaited_once()
    switch.assert_not_awaited()
