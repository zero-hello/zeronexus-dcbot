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
