"""ZeroNexus SSRF (Server-Side Request Forgery) Defense Engine.

Validates external destination hosts, URLs, and IP ranges to prevent:
- Loopback attacks (127.0.0.1, localhost, ::1)
- Private network scanning (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Link-Local and Cloud Metadata access (169.254.169.254, metadata.google.internal)
- Protocol smuggling via non-HTTP schemes
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlparse

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "metadata.internal",
    "metadata.tencentyun.com",
    "instance-data",
    "instance-data.ec2.internal",
}


class SSRFBlockedError(ValueError):
    """Raised when a URL or host target is blocked by SSRF defense rules."""
    pass


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> Tuple[bool, str]:
    """Checks whether an IP address belongs to internal, loopback, or metadata ranges."""
    # Check for IPv4 mapped in IPv6 (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if ip.is_loopback:
        return True, f"本機迴路位址 (Loopback: {ip})"
    if ip.is_private:
        return True, f"內部私有位址 (Private: {ip})"
    if ip.is_link_local:
        return True, f"鏈結區域位址/雲端中繼站 (Link-Local: {ip})"
    if ip.is_reserved:
        return True, f"保留區段位址 (Reserved: {ip})"
    if ip.is_multicast:
        return True, f"多播位址 (Multicast: {ip})"
    if ip.is_unspecified:
        return True, f"未指定位址 (Unspecified: {ip})"

    # Extra defense for AWS / GCP metadata & CGNAT
    if str(ip) in ("169.254.169.254", "100.100.100.200"):
        return True, f"雲端中繼資料位址 (Cloud Metadata: {ip})"

    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True, f"內部共享網段/雲端中繼位址 (CGNAT/Cloud: {ip})"

    return False, ""


def parse_loose_ip(host_str: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Parses standard and deformed IP notations into an ipaddress object.

    Supports:
    - Standard IPv4 / IPv6 notation
    - Single integer decimal, octal, hex (e.g. 2130706433, 017700000001, 0x7f000001)
    - Dotted decimal, octal, hex with 1, 2, 3, or 4 parts (e.g. 0x7f.0.0.1, 0177.0.0.1, 127.1, 0xa9.0xfe.0xa9.0xfe)
    - Dotted numbers with leading zeroes (e.g. 127.000.000.001)
    """
    clean = host_str.strip().lower()
    if clean.startswith("[") and clean.endswith("]"):
        clean = clean[1:-1]

    # 1. Direct standard parsing or single integer
    try:
        if clean.startswith(("0x", "0o")) or clean.isdigit():
            val = int(clean, 0)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        return ipaddress.ip_address(clean)
    except ValueError:
        pass

    # 2. Dotted notation with variable parts (1 to 4) and bases (hex, octal, dec)
    parts = clean.split(".")
    if 2 <= len(parts) <= 4:
        parsed_parts: List[int] = []
        for p in parts:
            p_strip = p.strip()
            try:
                if p_strip.startswith("0x"):
                    val = int(p_strip, 16)
                elif p_strip.startswith("0o"):
                    val = int(p_strip, 8)
                elif p_strip.startswith("0") and len(p_strip) > 1 and p_strip.isdigit():
                    val = int(p_strip, 8)
                elif p_strip.isdigit():
                    val = int(p_strip, 10)
                else:
                    return None
                parsed_parts.append(val)
            except ValueError:
                return None

        if len(parsed_parts) == 4:
            if all(0 <= x <= 255 for x in parsed_parts):
                ip_int = (parsed_parts[0] << 24) | (parsed_parts[1] << 16) | (parsed_parts[2] << 8) | parsed_parts[3]
                return ipaddress.IPv4Address(ip_int)
        elif len(parsed_parts) == 3:
            if 0 <= parsed_parts[0] <= 255 and 0 <= parsed_parts[1] <= 255 and 0 <= parsed_parts[2] <= 0xFFFF:
                ip_int = (parsed_parts[0] << 24) | (parsed_parts[1] << 16) | parsed_parts[2]
                return ipaddress.IPv4Address(ip_int)
        elif len(parsed_parts) == 2:
            if 0 <= parsed_parts[0] <= 255 and 0 <= parsed_parts[1] <= 0xFFFFFF:
                ip_int = (parsed_parts[0] << 24) | parsed_parts[1]
                return ipaddress.IPv4Address(ip_int)

    return None


def validate_safe_host(host: str) -> Tuple[bool, str, Optional[str]]:
    """Validates that a hostname or IP string resolves exclusively to safe public IPs.

    Returns:
        (is_safe, error_message, primary_resolved_ip)
    """
    clean_host = host.strip().lower()
    if not clean_host:
        return False, "目標主機不可為空", None

    # Strip IPv6 enclosing brackets if present
    if clean_host.startswith("[") and clean_host.endswith("]"):
        clean_host = clean_host[1:-1]

    if (
        clean_host in BLOCKED_HOSTNAMES
        or clean_host == "metadata"
        or clean_host.startswith("metadata.")
        or clean_host.endswith(".localhost")
        or clean_host.endswith(".local")
        or clean_host.endswith(".internal")
    ):
        return False, f"禁止存取受限內部主機名稱 ({clean_host})", None

    # Check if direct IP (standard string, hex, octal, integer, or dotted mixed notation)
    direct_ip = parse_loose_ip(clean_host)
    if direct_ip is not None:
        blocked, reason = is_ip_blocked(direct_ip)
        if blocked:
            return False, f"SSRF 防護阻斷：{reason}", None
        return True, "驗證通過", str(direct_ip)

    # Resolve hostname to all addresses (with retry for transient DNS hiccups)
    resolved_infos = None
    for attempt in range(3):
        try:
            resolved_infos = socket.getaddrinfo(clean_host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            if resolved_infos:
                break
        except socket.gaierror as e:
            if attempt < 2:
                resolved_infos = None
                try:
                    asyncio.get_running_loop()
                    asyncio.sleep(0.25)
                except RuntimeError:
                    pass
                continue
            return False, f"DNS 解析失敗：{e}", None
        except Exception as e:
            return False, f"主機解析異常：{e}", None

    if not resolved_infos:
        return False, "無法取得目標主機之 IP 位址", None

    primary_ip: Optional[str] = None
    for item in resolved_infos:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        if primary_ip is None:
            primary_ip = ip_str
        try:
            parsed_ip = ipaddress.ip_address(ip_str)
            blocked, reason = is_ip_blocked(parsed_ip)
            if blocked:
                return False, f"SSRF 防護阻斷：主機解析至 {reason}", None
        except ValueError:
            return False, f"無法識別解析之 IP 位址 ({ip_str})", None

    return True, "驗證通過", primary_ip


async def validate_safe_host_async(host: str) -> Tuple[bool, str, Optional[str]]:
    """非同步主機驗證：同步 DNS 解析移轉至執行緒池承載，事件迴圈零阻塞。

    【效能修復】同步 socket.getaddrinfo() 於 DNS 無回應時最壞可阻塞事件迴圈約 15 秒，
    凍結整個 Bot；非同步呼叫端應優先使用本函式。

    Returns:
        (is_safe, error_message, primary_resolved_ip)
    """
    clean_host = host.strip().lower()
    if not clean_host:
        return False, "目標主機不可為空", None

    if clean_host.startswith("[") and clean_host.endswith("]"):
        clean_host = clean_host[1:-1]

    if (
        clean_host in BLOCKED_HOSTNAMES
        or clean_host == "metadata"
        or clean_host.startswith("metadata.")
        or clean_host.endswith(".localhost")
        or clean_host.endswith(".local")
        or clean_host.endswith(".internal")
    ):
        return False, f"禁止存取受限內部主機名稱 ({clean_host})", None

    direct_ip = parse_loose_ip(clean_host)
    if direct_ip is not None:
        blocked, reason = is_ip_blocked(direct_ip)
        if blocked:
            return False, f"SSRF 防護阻斷：{reason}", None
        return True, "驗證通過", str(direct_ip)

    resolved_infos = None
    for attempt in range(3):
        try:
            # 同步 DNS 查詢交由執行緒池承載，事件迴圈零阻塞
            resolved_infos = await asyncio.to_thread(
                socket.getaddrinfo, clean_host, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
            if resolved_infos:
                break
        except socket.gaierror as e:
            if attempt < 2:
                await asyncio.sleep(0.25)  # 非同步讓渡，不阻塞其他協程
                continue
            return False, f"DNS 解析失敗：{e}", None
        except Exception as e:
            return False, f"主機解析異常：{e}", None

    if not resolved_infos:
        return False, "無法取得目標主機之 IP 位址", None

    primary_ip: Optional[str] = None
    for item in resolved_infos:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        if primary_ip is None:
            primary_ip = ip_str
        try:
            parsed_ip = ipaddress.ip_address(ip_str)
            blocked, reason = is_ip_blocked(parsed_ip)
            if blocked:
                return False, f"SSRF 防護阻斷：主機解析至 {reason}", None
        except ValueError:
            return False, f"無法識別解析之 IP 位址 ({ip_str})", None

    return True, "驗證通過", primary_ip


async def validate_safe_url_async(url: str) -> Tuple[bool, str, Optional[str]]:
    """非同步 URL 驗證：基於 validate_safe_host_async，供非同步請求鏈路使用。

    Returns:
        (is_safe, error_message, normalized_url)
    """
    clean_url = url.strip()
    if not clean_url:
        return False, "目標網址不可為空", None

    unquoted = unquote(clean_url)
    if (
        any(c in clean_url for c in ("\r", "\n", "\t"))
        or any(c in unquoted for c in ("\r", "\n", "\t", "\x00"))
        or bool(re.search(r"%0[adAD9]|%00", clean_url, re.IGNORECASE))
    ):
        return False, "網址包含非法控制字元 (CRLF/換行/Tab)", None

    try:
        parsed = urlparse(clean_url)
    except Exception as e:
        return False, f"網址解析失敗：{e}", None

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"不支援的協定「{parsed.scheme}」，僅允許 HTTP/HTTPS", None

    hostname = parsed.hostname
    if not hostname:
        return False, "網址缺少有效主機名稱", None

    try:
        port = parsed.port
    except ValueError as e:
        return False, f"無效連接埠：{e}", None

    if port is not None:
        if not (1 <= port <= 65535):
            return False, f"無效連接埠：{port}", None

    safe, reason, _ = await validate_safe_host_async(hostname)
    if not safe:
        return False, reason, None

    return True, "驗證通過", clean_url


def validate_safe_url(url: str) -> Tuple[bool, str, Optional[str]]:
    """Validates an HTTP/HTTPS URL against SSRF and illegal targets.

    Returns:
        (is_safe, error_message, normalized_url)
    """
    clean_url = url.strip()
    if not clean_url:
        return False, "目標網址不可為空", None

    # Reject carriage return, newline, or tab (both literal and URL-encoded) to prevent CRLF injection / HTTP request smuggling
    unquoted = unquote(clean_url)
    if (
        any(c in clean_url for c in ("\r", "\n", "\t"))
        or any(c in unquoted for c in ("\r", "\n", "\t", "\x00"))
        or bool(re.search(r"%0[adAD9]|%00", clean_url, re.IGNORECASE))
    ):
        return False, "網址包含非法控制字元 (CRLF/換行/Tab)", None

    try:
        parsed = urlparse(clean_url)
    except Exception as e:
        return False, f"網址解析失敗：{e}", None

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"不支援的協定「{parsed.scheme}」，僅允許 HTTP/HTTPS", None

    hostname = parsed.hostname
    if not hostname:
        return False, "網址缺少有效主機名稱", None

    # Port boundary check
    try:
        port = parsed.port
    except ValueError as e:
        return False, f"無效連接埠：{e}", None

    if port is not None:
        if not (1 <= port <= 65535):
            return False, f"無效連接埠：{port}", None

    safe, reason, _ = validate_safe_host(hostname)
    if not safe:
        return False, reason, None

    return True, "驗證通過", clean_url
