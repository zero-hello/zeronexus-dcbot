"""紅隊測試：SSRF 防護與 DNS Rebinding (TOCTOU) 防禦。

驗證：
1. 內網保留位址（RFC1918 / loopback / link-local / metadata）全數阻斷
2. 變形 IP 表示法（十六進位/八進位/整數/前導零）無法繞過
3. 非同步驗證介面存在且語意一致（validate_safe_url_async / validate_safe_host_async）
4. 重導向逐跳 + 最終落地雙重驗證已接入 web_client 與 free_apis
5. 同步驗證函式不得被 await（tool_catalog 曾因 await tuple 崩潰）
"""

from __future__ import annotations

import inspect

import pytest

from zeronexus.security.ssrf import (
    is_ip_blocked,
    parse_loose_ip,
    validate_safe_host,
    validate_safe_host_async,
    validate_safe_url,
    validate_safe_url_async,
)


class TestInternalNetworkBlocking:
    """測試 1：內網保留位址全數阻斷。"""

    @pytest.mark.parametrize(
        "ip_str",
        [
            "127.0.0.1",           # IPv4 loopback
            "10.0.0.5",            # RFC1918 10/8
            "172.16.0.1",          # RFC1918 172.16/12
            "192.168.1.1",         # RFC1918 192.168/16
            "169.254.169.254",     # AWS/GCP cloud metadata
            "100.64.0.1",          # CGNAT
            "::1",                 # IPv6 loopback
            "fe80::1",             # IPv6 link-local
            "::ffff:127.0.0.1",    # IPv4-mapped IPv6 loopback
            "0.0.0.0",             # unspecified
        ],
    )
    def test_blocked_ips(self, ip_str: str) -> None:
        import ipaddress

        ip = ipaddress.ip_address(ip_str)
        blocked, reason = is_ip_blocked(ip)
        assert blocked, f"內網/保留位址 {ip_str} 必須被阻斷（原因: {reason}）"

    @pytest.mark.parametrize("host", ["localhost", "metadata.google.internal", "metadata", "instance-data"])
    def test_blocked_hostnames(self, host: str) -> None:
        is_safe, reason, _ = validate_safe_host(host)
        assert not is_safe, f"受限主機名稱 {host} 必須被阻斷"


class TestDeformedIPBypass:
    """測試 2：變形 IP 表示法無法繞過。"""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2130706433", "127.0.0.1"),       # 整數
            ("0x7f000001", "127.0.0.1"),       # 十六進位整數
            ("127.1", "127.0.0.1"),            # 兩段式
            ("0x7f.0.0.1", "127.0.0.1"),       # 混合基底
            ("127.000.000.001", "127.0.0.1"),  # 前導零（點分段）
        ],
    )
    def test_loose_ip_parsed_then_blocked(self, raw: str, expected: str) -> None:
        ip = parse_loose_ip(raw)
        assert ip is not None, f"變形表示法 {raw} 必須被解析識別"
        assert str(ip) == expected
        blocked, _ = is_ip_blocked(ip)
        assert blocked, f"變形表示法 {raw} → {expected} 必須被阻斷"

    def test_leading_zero_octal_blocked_fail_closed(self) -> None:
        """前導零八進位整數（017700000001 = 127.0.0.1）必須以 fail-closed 阻斷。

        引擎對無法辨識之變形表示法回傳 None 轉交 DNS 解析，而 '017700000001'
        不可能解析為公網 IP，因此驗證結果必然為「不安全」——阻斷方向正確。
        """
        is_safe, _, _ = validate_safe_host("017700000001")
        assert not is_safe, "前導零八進位 loopback 表示法必須被阻斷（fail-closed）"

    def test_url_with_deformed_ip_blocked(self) -> None:
        is_safe, _, _ = validate_safe_url("http://2130706433/admin")
        assert not is_safe, "整數型 loopback URL 必須被阻斷"


class TestAsyncInterfaces:
    """測試 3：非同步驗證介面存在且語意一致。"""

    @pytest.mark.asyncio
    async def test_async_host_validation_consistent(self) -> None:
        """非同步與同步驗證結果必須一致。"""
        sync_safe, _, sync_ip = validate_safe_host("127.0.0.1")
        async_safe, _, async_ip = await validate_safe_host_async("127.0.0.1")
        assert sync_safe == async_safe == False
        assert sync_ip == async_ip

    @pytest.mark.asyncio
    async def test_async_url_blocks_internal(self) -> None:
        is_safe, _, _ = await validate_safe_url_async("http://192.168.1.1/router")
        assert not is_safe

    @pytest.mark.asyncio
    async def test_async_url_accepts_public(self) -> None:
        is_safe, _, normalized = await validate_safe_url_async("https://www.google.com")
        assert is_safe
        assert normalized == "https://www.google.com"

    def test_async_functions_are_coroutines(self) -> None:
        assert inspect.iscoroutinefunction(validate_safe_host_async)
        assert inspect.iscoroutinefunction(validate_safe_url_async)

    def test_sync_functions_are_not_coroutines(self) -> None:
        """同步函式不得被誤標為協程（防止 tool_catalog await tuple 之回歸）。"""
        assert not inspect.iscoroutinefunction(validate_safe_host)
        assert not inspect.iscoroutinefunction(validate_safe_url)


class TestDoubleValidationIntegrated:
    """測試 4：重導向逐跳 + 最終落地雙重驗證已接入。

    注意：zeronexus.engines 與 zeronexus.lavalink 之 __init__ 會級聯 import wavelink 等重依賴，
    故此處以 importlib 直接載入子模組檔案，隔離套件 __init__ 之依賴鏈。
    """

    @staticmethod
    def _load_module(name: str, rel_path: str):
        import importlib.util
        import sys
        from pathlib import Path

        if name in sys.modules:
            return sys.modules[name]
        file_path = Path(__file__).resolve().parent.parent / rel_path
        spec = importlib.util.spec_from_file_location(name, file_path)
        assert spec and spec.loader, f"無法載入 {rel_path}"
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def test_web_client_uses_async_validation(self) -> None:
        wc = self._load_module("zn_rt_web_client", "zeronexus/engines/web_client.py")
        src = inspect.getsource(wc.WebClient.fetch_page)
        assert "validate_safe_url_async" in src, "fetch_page 必須使用非同步 SSRF 驗證"
        assert src.count("validate_safe_url_async") >= 2, (
            "fetch_page 必須具備「首跳 + 最終落地」雙重驗證以縮小 DNS Rebinding 時間窗"
        )

    def test_free_apis_scrape_uses_async_validation(self) -> None:
        fa = self._load_module("zn_rt_free_apis", "zeronexus/engines/free_apis.py")
        src = inspect.getsource(fa.FreeAPIEngine.scrape_webpage_content)
        assert "validate_safe_url_async" in src, "scrape_webpage_content 必須使用非同步 SSRF 驗證"
        assert src.count("validate_safe_url_async") >= 2, (
            "scrape_webpage_content 必須具備「首跳 + 最終落地」雙重驗證"
        )

    def test_tool_catalog_no_await_on_sync_validation(self) -> None:
        """同步驗證函式不得被 await（await tuple 會拋 TypeError 導致工具崩潰）。"""
        with open(
            __import__("pathlib").Path(__file__).resolve().parent.parent / "zeronexus" / "agent" / "tool_catalog.py",
            encoding="utf-8",
        ) as f:
            src = f.read()
        assert "await validate_safe_host(" not in src, "await 同步 validate_safe_host 會拋 TypeError"
        assert "await validate_safe_url(" not in src, "await 同步 validate_safe_url 會拋 TypeError"


class TestTLSVerificationRestored:
    """測試 5：TLS 憑證驗證已恢復。

    同樣以原始碼字串檢查隔離重依賴，避免 import 鏈觸發 wavelink 缺失。
    """

    @staticmethod
    def _read_source(rel_path: str) -> str:
        from pathlib import Path

        file_path = Path(__file__).resolve().parent.parent / rel_path
        return file_path.read_text(encoding="utf-8")

    def test_free_apis_no_verify_false(self) -> None:
        src = self._read_source("zeronexus/engines/free_apis.py")
        assert "verify=False" not in src, "free_apis 全域停用 TLS 驗證將構成資料投毒面"
        assert "verify=True" in src, "free_apis 必須明確啟用 TLS 憑證驗證"

    def test_lavalink_scraper_no_ssl_false(self) -> None:
        src = self._read_source("zeronexus/lavalink/scraper.py")
        # 僅檢查連線器參數層級：TCPConnector 之 ssl= 必須未停用；
        # is_ssl=False 為「節點清單分類旗標」（標記 NoSSL 來源清單），並非 TLS 驗證停用
        connector_lines = [
            line.strip()
            for line in src.splitlines()
            if "TCPConnector" in line
        ]
        assert connector_lines, "scraper 必須使用 TCPConnector 建立連線"
        for line in connector_lines:
            assert not (
                "ssl=False" in line or "ssl = False" in line
            ), f"TCPConnector 不得停用 TLS 驗證: {line}"
