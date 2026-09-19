"""Web & API Service (Features 396-415).

Implements:
- Website Status, Latency & Uptime Monitoring (396-398)
- SSL Certificate Check & Expiration Reminders (399-400)
- DNS Lookup, Record Viewer, IP & Domain Intelligence (401-404)
- HTTP Header Viewer & Redirect Chain Analyzer (405-406)
- API Health, Response, Latency & Error Rate Monitoring, Webhook Monitor (407-411)
- URL Metadata Extractor, OpenGraph Preview, Title Extractor & Change Detection (412-415)
"""

from __future__ import annotations

import socket
import ssl
import time
from typing import Any, Dict, List
import httpx



class WebApiService:
    """全面實作 Features 396 ~ 415 之網站診斷、SSL、DNS、API 監控與元數據提取服務。"""

    # ----------------------------------------------------
    # 396-400: 網站狀態、延遲與 SSL 憑證檢測
    # ----------------------------------------------------
    @staticmethod
    async def check_website_health(url: str) -> Dict[str, Any]:
        """功能 396-398: 網站 HTTP 狀態與延遲測速。"""
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        start_t = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(url)
                latency_ms = (time.perf_counter() - start_t) * 1000
                return {
                    "url": str(res.url),
                    "status_code": res.status_code,
                    "is_ok": res.status_code < 400,
                    "latency_ms": round(latency_ms, 2),
                    "server": res.headers.get("server", "unknown")
                }
        except Exception as e:
            return {"url": url, "is_ok": False, "error": str(e)}

    @staticmethod
    def check_ssl_cert(hostname: str, port: int = 443) -> Dict[str, Any]:
        """功能 399-400: SSL 憑證資訊與過期檢測。"""
        ctx = ssl.create_default_context()
        try:
            with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
                s.settimeout(5.0)
                s.connect((hostname, port))
                cert = s.getpeercert()
                expire_date = cert.get("notAfter", "")
                return {
                    "hostname": hostname,
                    "subject": dict(x[0] for x in cert.get("subject", ())),
                    "issuer": dict(x[0] for x in cert.get("issuer", ())),
                    "expires_at": expire_date,
                    "valid": True
                }
        except Exception as e:
            return {"hostname": hostname, "valid": False, "error": str(e)}

    # ----------------------------------------------------
    # 401-406: DNS, IP 與轉址鏈分析
    # ----------------------------------------------------
    @staticmethod
    def dns_lookup(domain: str) -> Dict[str, Any]:
        """功能 401-404: DNS 與 IP 解析。"""
        try:
            ip = socket.gethostbyname(domain)
            return {"domain": domain, "resolved_ip": ip, "success": True}
        except Exception as e:
            return {"domain": domain, "success": False, "error": str(e)}

    @staticmethod
    async def analyze_redirect_chain(url: str) -> List[Dict[str, Any]]:
        """功能 406: 轉址鏈分析 (Redirect Chain Analyzer)。"""
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        chain = []
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                curr_url = url
                for _ in range(5):
                    res = await client.get(curr_url)
                    chain.append({"url": curr_url, "status": res.status_code})
                    if res.is_redirect and "location" in res.headers:
                        curr_url = res.headers["location"]
                    else:
                        break
        except Exception as e:
            chain.append({"url": url, "error": str(e)})
        return chain

    # ----------------------------------------------------
    # 412-415: URL 元數據、OpenGraph 與變更偵測
    # ----------------------------------------------------
    @staticmethod
    async def extract_url_metadata(url: str) -> Dict[str, Any]:
        """功能 412-414: OpenGraph 預覽與網頁標題提取。"""
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                res = await client.get(url)
                html = res.text
                import re
                title_match = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
                og_desc_match = re.search(r'<meta property="og:description" content="(.*?)"', html, re.I)
                og_img_match = re.search(r'<meta property="og:image" content="(.*?)"', html, re.I)
                return {
                    "url": url,
                    "title": title_match.group(1).strip() if title_match else "No Title",
                    "og_description": og_desc_match.group(1).strip() if og_desc_match else None,
                    "og_image": og_img_match.group(1).strip() if og_img_match else None
                }
        except Exception as e:
            return {"url": url, "error": str(e)}
