"""單元測試：ZeroNexus Web Panel 控制面板與全域黑名單安全防護系統"""

import json
import os
import pytest
from zeronexus.security.blacklist import GlobalBlacklistManager
from zeronexus.web.auth import (
    create_session_cookie,
    verify_session_cookie,
    has_guild_admin_permission,
)
from zeronexus.core.config import config


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


def test_oauth2_session_signing_and_verification():
    secret = "test_super_secret_key_12345"
    user_payload = {
        "id": "123456789",
        "username": "ZeroTester",
        "avatar": "abc123hash",
        "is_creator": True,
    }

    # 建立簽名 Cookie
    cookie_str = create_session_cookie(user_payload, secret_key=secret)
    assert "." in cookie_str

    # 驗證通過
    verified_data = verify_session_cookie(cookie_str, secret_key=secret)
    assert verified_data is not None
    assert verified_data["id"] == "123456789"
    assert verified_data["username"] == "ZeroTester"
    assert verified_data["is_creator"] is True

    # 竄改簽名或內容時驗證失敗
    tampered_cookie = cookie_str[:-4] + "fake"
    assert verify_session_cookie(tampered_cookie, secret_key=secret) is None

    # 金鑰不符時驗證失敗
    assert verify_session_cookie(cookie_str, secret_key="wrong_secret") is None


def test_guild_admin_permission_bitwise():
    # 0x8 為 Administrator
    # 0x20 為 Manage Guild
    assert has_guild_admin_permission(8) is True
    assert has_guild_admin_permission(32) is True
    assert has_guild_admin_permission("8") is True
    assert has_guild_admin_permission("32") is True
    assert has_guild_admin_permission(8 | 32) is True
    assert has_guild_admin_permission(0x8000000008) is True

    # 一般成員權限 (例如僅有 Send Messages 0x800)
    assert has_guild_admin_permission(0x800) is False
    assert has_guild_admin_permission(0) is False
    assert has_guild_admin_permission("invalid") is False


def test_web_panel_config_settings_integration():
    web_conf = config.web_panel
    assert web_conf.port == 8080 or isinstance(web_conf.port, int)
    assert isinstance(web_conf.enabled, bool)
    assert isinstance(web_conf.host, str)
