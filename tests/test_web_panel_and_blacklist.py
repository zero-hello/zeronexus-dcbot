"""單元測試：ZeroNexus 全域黑名單安全防護系統"""

import json
import os
import pytest
from zeronexus.security.blacklist import GlobalBlacklistManager


def test_global_blacklist_crud_and_persistence(tmp_path):
    storage_path = str(tmp_path / "global_blacklist_test.json")
    mgr = GlobalBlacklistManager(storage_path=storage_path)

    # 1. 預設未被封鎖
    assert mgr.is_banned("user_1001") is False
    assert mgr.get_ban_info("user_1001") is None

    # 2. 封鎖特定使用者
    record = mgr.ban_user(
        user_id="1001",
        reason="惡意發布違規垃圾訊息",
        banned_by="Zero",
        user_name="SpamBot",
    )
    assert record["user_id"] == "1001"
    assert mgr.is_banned("1001") is True
    assert mgr.is_banned(1001) is True  # 支援 int 與 str 自動相容

    info = mgr.get_ban_info("1001")
    assert info is not None
    assert info["reason"] == "惡意發布違規垃圾訊息"
    assert info["banned_by"] == "Zero"
    assert info["user_name"] == "SpamBot"

    # 3. 驗證資料持久化與重新載入
    mgr_reloaded = GlobalBlacklistManager(storage_path=storage_path)
    assert mgr_reloaded.is_banned("1001") is True
    banned_list = mgr_reloaded.list_banned_users()
    assert len(banned_list) == 1
    assert banned_list[0]["user_id"] == "1001"

    # 4. 解除封鎖
    unban_success = mgr_reloaded.unban_user("1001")
    assert unban_success is True
    assert mgr_reloaded.is_banned("1001") is False
    assert len(mgr_reloaded.list_banned_users()) == 0


def test_creator_cannot_be_blacklisted(tmp_path):
    storage_path = str(tmp_path / "blacklist_creator_test.json")
    mgr = GlobalBlacklistManager(storage_path=storage_path)

    # 造物主專屬 ID 與 settings.json 中的 owner_id 具備絕對不可封鎖之金身防護
    creator_id = "1514971711739789352"
    with pytest.raises(ValueError, match="不可封鎖造物主 Zero"):
        mgr.ban_user(creator_id, reason="測試無效封鎖")
    assert mgr.is_banned(creator_id) is False

    # 若為 int 型別造物主 ID 亦同
    with pytest.raises(ValueError, match="不可封鎖造物主 Zero"):
        mgr.ban_user(1514971711739789352, reason="測試無效封鎖")
    assert mgr.is_banned(1514971711739789352) is False


@pytest.mark.asyncio
async def test_tree_interaction_check_blacklist(monkeypatch):
    import warnings
    from unittest.mock import MagicMock, AsyncMock
    import discord
    from discord import app_commands
    from zeronexus.security.blacklist import global_blacklist

    # 模擬 discord.Client 與 CommandTree
    client = MagicMock()
    client._connection._command_tree = None
    tree = app_commands.CommandTree(client)

    # 實作與 bot.py setup_hook 中完全相同的 interaction_check 邏輯
    async def global_tree_interaction_check(interaction: discord.Interaction) -> bool:
        if global_blacklist.is_banned(interaction.user.id):
            return False
        return True

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        tree.interaction_check = global_tree_interaction_check

        # 模擬正常使用者的 interaction
        normal_interaction = MagicMock(spec=discord.Interaction)
        normal_interaction.user = MagicMock()
        normal_interaction.user.id = 999999999
        allowed = await tree.interaction_check(normal_interaction)
        assert allowed is True

        # 模擬被封鎖使用者的 interaction
        monkeypatch.setattr(global_blacklist, "is_banned", lambda uid: uid == 888888888)
        banned_interaction = MagicMock(spec=discord.Interaction)
        banned_interaction.user = MagicMock()
        banned_interaction.user.id = 888888888
        blocked = await tree.interaction_check(banned_interaction)
        assert blocked is False

        # 驗證沒有觸發任何 coroutine never awaited 的 RuntimeWarning
        runtime_warnings = [w for w in recorded_warnings if issubclass(w.category, RuntimeWarning)]
        assert len(runtime_warnings) == 0

