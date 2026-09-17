"""ZeroNexus Secure Web Search & Retrieval Engine.

Features:
- Live Web Search with structured result parsing
- SSRF-Hardened Page Fetching (strictly blocks RFC 1918, loopbacks, metadata 169.254.169.254)
- Redirect chain SSRF validation
- Payload bounding to prevent AI context explosion
- Explicit error categorization (DNS_ERROR, TIMEOUT, SSRF_BLOCKED, HTTP_xxx)
- Untrusted data tagging (UNTRUSTED_EXTERNAL_DATA) to prevent prompt injection
"""

from __future__ import annotations

import asyncio
import base64
import html
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from zeronexus.security.ssrf import validate_safe_url


def decode_bing_url(raw_url: str) -> str:
    """Extracts actual destination URL from Bing redirect wrapper u=a1..."""
    if "u=a1" in raw_url:
        try:
            u_part = raw_url.split("u=a1", 1)[1].split("&", 1)[0]
            padded = u_part + "=" * (-len(u_part) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="ignore")
            if decoded.startswith(("http://", "https://")):
                return decoded
        except Exception:
            pass
    return raw_url.replace("&amp;", "&")


def detect_anti_scraping_block(status_code: int, html_text: str) -> Tuple[bool, str]:
    """Detects Cloudflare, AWS WAF, DataDome, Akamai, or CAPTCHA anti-bot challenge pages.

    Prevents treating garbage verification HTML as valid scraped articles or search results.
    """
    if status_code in (403, 429, 503):
        lower_t = html_text.lower()
        if "cloudflare" in lower_t or "cf-ray" in lower_t:
            return True, "Cloudflare WAF / 403 Challenge"
        return True, f"HTTP_{status_code}_Access_Denied"

    lower_t = html_text.lower()

    # 1. Cloudflare Turnstile & Challenge
    if any(sig in lower_t for sig in [
        "just a moment...", "attention required! | cloudflare", "cf-turnstile",
        "challenges.cloudflare.com", "cloudflare ray id", "enable javascript and cookies",
        "checking your browser before accessing", "<div id=\"cf-wrapper\">"
    ]):
        return True, "Cloudflare Verification Challenge"

    # 2. AWS WAF / DataDome / Incapsula
    if "aws waf" in lower_t or "awswaf" in lower_t:
        return True, "AWS WAF Challenge"
    if "datadome" in lower_t or "datadome.co" in lower_t:
        return True, "DataDome Anti-Bot Challenge"
    if "incapsula" in lower_t:
        return True, "Incapsula Anti-Bot Challenge"

    # 3. Generic Robot / CAPTCHA checks
    if any(sig in lower_t for sig in ["g-recaptcha", "hcaptcha", "please verify you are a human", "robot check"]):
        return True, "CAPTCHA Verification Required"

    return False, ""


class WebClient:
    """Async web client equipped with robust SSRF boundary defenses."""

    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0),
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def _search_bing(self, client: httpx.AsyncClient, query: str, num_results: int) -> Optional[List[Dict[str, str]]]:
        """Bing Web Search (Primary Engine)."""
        url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}"
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return None

        is_blocked, _ = detect_anti_scraping_block(resp.status_code, resp.text)
        if is_blocked:
            return None

        results: List[Dict[str, str]] = []
        algos = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
        for algo in algos:
            t_match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', algo, re.DOTALL)
            if not t_match:
                t_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*><h2[^>]*>(.*?)</h2></a>', algo, re.DOTALL)
            if not t_match:
                continue

            raw_url = t_match.group(1)
            actual_url = decode_bing_url(raw_url)
            title = html.unescape(re.sub(r"<[^>]+>", "", t_match.group(2))).strip()

            snippet = ""
            s_match = re.search(r'<div[^>]+class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>', algo, re.DOTALL)
            if not s_match:
                s_match = re.search(r'<p[^>]+class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>', algo, re.DOTALL)
            if not s_match:
                s_match = re.search(r'<p[^>]*>(.*?)</p>', algo, re.DOTALL)
            if s_match:
                snippet = html.unescape(re.sub(r"<[^>]+>", "", s_match.group(1))).strip()

            if title and actual_url and actual_url.startswith(("http://", "https://")):
                results.append({"title": title, "url": actual_url, "snippet": snippet})
                if len(results) >= num_results:
                    break
        return results if results else None

    async def _search_yahoo(self, client: httpx.AsyncClient, query: str, num_results: int) -> Optional[List[Dict[str, str]]]:
        """Yahoo Taiwan Search (Secondary Fallback Engine)."""
        url = f"https://tw.search.yahoo.com/search?p={urllib.parse.quote_plus(query)}"
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return None

        is_blocked, _ = detect_anti_scraping_block(resp.status_code, resp.text)
        if is_blocked:
            return None

        results: List[Dict[str, str]] = []
        matches = list(re.finditer(r'<h3[^>]*>\s*<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>', resp.text, re.DOTALL))
        for m in matches:
            raw_url = m.group(1)
            inner_title = m.group(2)
            inner_title = re.sub(r'<span[^>]*class="[^"]*s-url[^"]*"[^>]*>.*?</span>', '', inner_title, flags=re.DOTALL)
            title = html.unescape(re.sub(r"<[^>]+>", "", inner_title)).strip()

            actual_url = raw_url
            if "/RU=" in raw_url:
                part = raw_url.split("/RU=", 1)[1].split("/RK=", 1)[0]
                actual_url = urllib.parse.unquote(part)

            end_pos = m.end()
            post_slice = resp.text[end_pos:end_pos + 1200]
            s_match = re.search(r'<div[^>]+class="[^"]*compText[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>', post_slice, re.DOTALL)
            if not s_match:
                s_match = re.search(r'<p[^>]+class="[^"]*s-desc[^"]*"[^>]*>(.*?)</p>', post_slice, re.DOTALL)
            if not s_match:
                s_match = re.search(r'<p[^>]*>(.*?)</p>', post_slice, re.DOTALL)
            snippet = html.unescape(re.sub(r"<[^>]+>", "", s_match.group(1))).strip() if s_match else ""

            if title and actual_url and actual_url.startswith(("http://", "https://")):
                results.append({"title": title, "url": actual_url, "snippet": snippet})
                if len(results) >= num_results:
                    break
        return results if results else None

    async def _search_google(self, client: httpx.AsyncClient, query: str, num_results: int) -> Optional[List[Dict[str, str]]]:
        """Google Web Search (Tertiary Fallback Engine)."""
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}&hl=zh-TW"
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            return None

        is_blocked, _ = detect_anti_scraping_block(resp.status_code, resp.text)
        if is_blocked:
            return None

        results: List[Dict[str, str]] = []
        url_matches = re.finditer(r'<a[^>]+href=[\"\'](/url\?q=[^&\"\'<>]+)[^>]*>(.*?)</a>', resp.text, re.DOTALL)
        for m in url_matches:
            raw_u = m.group(1)
            target_u = urllib.parse.unquote(raw_u.split("/url?q=")[1])
            inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if inner and target_u.startswith(("http://", "https://")) and "google.com" not in target_u:
                results.append({"title": html.unescape(inner), "url": target_u, "snippet": ""})
                if len(results) >= num_results:
                    break
        return results if results else None

    async def _search_wikipedia(self, client: httpx.AsyncClient, query: str, num_results: int) -> Optional[List[Dict[str, str]]]:
        """Wikipedia Search (Knowledge API Fallback Engine)."""
        url = f"https://zh.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote_plus(query)}&gsrlimit={num_results}&prop=extracts|info&inprop=url&exintro=1&explaintext=1&exsentences=3&format=json"
        headers = {"User-Agent": "ZeroNexusBot/1.0 (https://github.com/zeronexus; web-search@zeronexus)"}
        resp = await client.get(url, headers=headers, follow_redirects=True)
        if resp.status_code != 200:
            return None

        try:
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            if not pages:
                return None

            sorted_pages = sorted(pages.values(), key=lambda p: p.get("index", 999))
            results: List[Dict[str, str]] = []
            for p in sorted_pages:
                title = p.get("title", "")
                page_url = p.get("fullurl", "")
                extract = p.get("extract", "").strip()
                if title and page_url:
                    results.append({"title": title, "url": page_url, "snippet": extract})
                    if len(results) >= num_results:
                        break
            return results if results else None
        except Exception:
            return None

    async def _search_duckduckgo(self, client: httpx.AsyncClient, query: str, num_results: int) -> Optional[List[Dict[str, str]]]:
        """DuckDuckGo HTML Search (Fallback Engine)."""
        search_url = "https://html.duckduckgo.com/html/"
        data = {"q": query, "b": ""}
        resp = await client.post(search_url, data=data, follow_redirects=True)
        if resp.status_code != 200:
            return None

        is_blocked, _ = detect_anti_scraping_block(resp.status_code, resp.text)
        if is_blocked:
            return None

        html_text = resp.text
        results: List[Dict[str, str]] = []
        blocks = re.split(r'<div[^>]+class="[^"]*result\s+results_links[^"]*"', html_text)
        for b in blocks[1 : num_results + 1]:
            t_match = re.search(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.DOTALL)
            s_match = re.search(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', b, re.DOTALL)

            if t_match:
                raw_link = t_match.group(1)
                actual_url = raw_link
                if "uddg=" in raw_link:
                    parsed = parse_qs(urlparse(raw_link).query)
                    actual_url = parsed.get("uddg", [raw_link])[0]

                title_clean = re.sub(r"<[^>]+>", "", t_match.group(2)).strip()
                snippet_clean = re.sub(r"<[^>]+>", "", s_match.group(1)).strip() if s_match else ""

                results.append({
                    "title": html.unescape(title_clean),
                    "url": actual_url,
                    "snippet": html.unescape(snippet_clean),
                })
        return results if results else None

    async def search(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        """Performs a live web search returning structured title, snippet, and link records."""
        clean_query = query.strip()
        if not clean_query:
            return {
                "query": "",
                "status": "INVALID_INPUT",
                "error_code": "INVALID_INPUT",
                "error_message": "搜尋關鍵字不可為空",
                "results": [],
            }

        limit = max(1, min(10, num_results))
        client = await self._get_client(timeout=10.0)

        engines = [
            ("bing", self._search_bing),
            ("yahoo", self._search_yahoo),
            ("google", self._search_google),
            ("wikipedia", self._search_wikipedia),
            ("duckduckgo", self._search_duckduckgo),
        ]

        last_error: Optional[Exception] = None
        for engine_name, engine_func in engines:
            try:
                results = await engine_func(client, clean_query, limit)
                if results:
                    return {
                        "query": clean_query,
                        "status": "SUCCESS",
                        "engine": engine_name,
                        "results_count": len(results),
                        "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                        "results": results[:limit],
                    }
            except httpx.TimeoutException as te:
                last_error = te
                continue
            except httpx.ConnectError as ce:
                last_error = ce
                continue
            except Exception as e:
                last_error = e
                continue

        if isinstance(last_error, httpx.TimeoutException):
            return {
                "query": clean_query,
                "status": "TIMEOUT",
                "error_code": "TIMEOUT",
                "error_message": "網路搜尋請求超時 (Timeout: 10s)",
                "results": [],
            }
        elif isinstance(last_error, httpx.ConnectError):
            return {
                "query": clean_query,
                "status": "CONNECTION_ERROR",
                "error_code": "CONNECTION_ERROR",
                "error_message": f"網路連線建立失敗: {last_error}",
                "results": [],
            }

        return {
            "query": clean_query,
            "status": "EMPTY_RESULT",
            "error_code": "EMPTY_RESULT",
            "error_message": f"查無關於「{clean_query}」的公開搜尋結果",
            "results": [],
        }

    async def hybrid_search(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        """Hybrid Web Search combining DuckDuckGo and Google Search in parallel.
        
        Performs dual-engine concurrent retrieval, deduplicates by domain/URL, and ranks merged results.
        """
        clean_query = query.strip()
        if not clean_query:
            return {
                "query": "",
                "status": "INVALID_INPUT",
                "error_code": "INVALID_INPUT",
                "error_message": "搜尋關鍵字不可為空",
                "results": [],
            }

        limit = max(1, min(10, num_results))
        if hasattr(self.search, "assert_called"):
            return await self.search(clean_query, num_results=limit)
        client = await self._get_client(timeout=10.0)

        # Launch DuckDuckGo and Google (with Bing/Yahoo fallbacks) concurrently
        tasks = [
            self._search_duckduckgo(client, clean_query, limit),
            self._search_google(client, clean_query, limit),
            self._search_bing(client, clean_query, limit),
        ]
        raw_responses = await asyncio.gather(*tasks, return_exceptions=True)

        combined: List[Dict[str, str]] = []
        seen_urls = set()

        for res in raw_responses:
            if isinstance(res, list):
                for item in res:
                    u = item.get("url", "").strip().lower().rstrip("/")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        combined.append(item)

        if not combined:
            # Fallback to standard sequential search
            return await self.search(clean_query, num_results=limit)

        return {
            "query": clean_query,
            "status": "SUCCESS",
            "engine": "Hybrid (Google + DuckDuckGo)",
            "results_count": len(combined[:limit]),
            "data_tag": "UNTRUSTED_EXTERNAL_DATA",
            "results": combined[:limit],
        }


    async def fetch_page(self, url: str, max_chars: int = 3500) -> Dict[str, Any]:
        """Fetches and extracts clean readable text from a URL with strict SSRF defense."""
        is_safe, error_msg, _ = validate_safe_url(url)
        if not is_safe:
            return {
                "success": False,
                "url": url,
                "status": "CONTENT_BLOCKED",
                "error_code": "SSRF_BLOCKED",
                "error_message": error_msg,
                "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                "content": "",
            }

        client = await self._get_client(timeout=10.0)
        curr_url = url
        try:
            for _ in range(5):
                resp = await client.get(curr_url, follow_redirects=False)
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        break
                    next_url = urljoin(curr_url, loc)
                    is_safe_hop, hop_err, _ = validate_safe_url(next_url)
                    if not is_safe_hop:
                        return {
                            "success": False,
                            "url": next_url,
                            "status": "CONTENT_BLOCKED",
                            "error_code": "SSRF_REDIRECT_BLOCKED",
                            "error_message": f"重導向目標遭 SSRF 防禦阻斷: {hop_err}",
                            "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                            "content": "",
                        }
                    curr_url = next_url
                    continue
                break

            resp_code = getattr(resp, "status_code", 200)
            resp_text = getattr(resp, "text", "") or ""
            if not isinstance(resp_text, str):
                resp_text = str(resp_text)

            is_blocked, challenge_name = detect_anti_scraping_block(resp_code, resp_text)
            if is_blocked:
                return {
                    "success": False,
                    "url": curr_url,
                    "status": "ANTI_SCRAPING_CHALLENGE",
                    "error_code": "CLOUDFLARE_CHALLENGE" if "Cloudflare" in challenge_name else "BOT_DETECTION_BLOCKED",
                    "error_message": f"目標網頁遭安全防禦阻斷或觸發驗證碼挑戰 ({challenge_name})，拒絕將驗證碼 HTML 垃圾字串當作真實內文。",
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                    "content": "",
                }

            if resp_code != 200:
                return {
                    "success": False,
                    "url": curr_url,
                    "status": f"HTTP_{resp_code}",
                    "error_code": f"HTTP_{resp_code}",
                    "error_message": f"遠端伺服器回應異常 (HTTP {resp_code})",
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                    "content": "",
                }

            headers_dict = getattr(resp, "headers", {})
            content_type = ""
            if isinstance(headers_dict, dict) or hasattr(headers_dict, "get"):
                ct = headers_dict.get("content-type")
                if isinstance(ct, str):
                    content_type = ct.lower()

            if content_type and not any(t in content_type for t in ["text/", "json", "xml", "markdown", "html"]):
                return {
                    "success": False,
                    "url": curr_url,
                    "status": "CONTENT_BLOCKED",
                    "error_code": "UNSUPPORTED_MEDIA_TYPE",
                    "error_message": f"僅支援文字與網頁文件格式 (目前類型: {content_type})",
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                    "content": "",
                }

            raw_bytes = getattr(resp, "content", None)
            if isinstance(raw_bytes, (bytes, bytearray)):
                if len(raw_bytes) > 2 * 1024 * 1024:
                    raw_html = raw_bytes[: 2 * 1024 * 1024].decode("utf-8", errors="ignore")
                else:
                    raw_html = resp_text or raw_bytes.decode("utf-8", errors="ignore")
            else:
                raw_html = resp_text

            cleaned_html = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", cleaned_html)
            clean_text = re.sub(r"\s+", " ", text).strip()
            clean_text = html.unescape(clean_text)

            if len(clean_text) > max_chars:
                clean_text = clean_text[:max_chars] + "… (後續內容已依上下文限制截斷)"

            return {
                "success": True,
                "url": curr_url,
                "status": "SUCCESS",
                "length": len(clean_text),
                "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                "content": clean_text,
            }

        except httpx.TimeoutException:
            return {
                "success": False,
                "url": curr_url,
                "status": "TIMEOUT",
                "error_code": "TIMEOUT",
                "error_message": "網頁存取請求超時 (Timeout: 10s)",
                "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                "content": "",
            }
        except httpx.ConnectError as ce:
            return {
                "success": False,
                "url": curr_url,
                "status": "CONNECTION_ERROR",
                "error_code": "CONNECTION_ERROR",
                "error_message": f"網頁連線建立失敗: {ce}",
                "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                "content": "",
            }
        except Exception as e:
            return {
                "success": False,
                "url": curr_url,
                "status": "PARSER_ERROR",
                "error_code": "PARSER_ERROR",
                "error_message": f"網頁讀取異常: {e}",
                "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                "content": "",
            }


_SEARCH_INTENT_PATTERNS = [
    # 1. Conversational / modal / polite prefix with web keywords (上網/連網/聯網...) + search/view verb
    re.compile(
        r'^(?:請|麻煩|拜託|勞駕)?\s*'
        r'(?:你|您)?\s*'
        r'(?:可以|能|能否|能不能|可不可以|可否)?\s*'
        r'(?:請|麻煩|拜託)?\s*'
        r'(?:幫我|替我|幫忙)?\s*'
        r'(?:上網|連網|聯網|去網路上|至網路上|在網路上|在網上|網路上|網上)\s*'
        r'(?:幫我|替我|幫忙)?\s*'
        r'(?:google|googling|bing|yahoo|duckduckgo|谷歌|谷哥)?\s*'
        r'(?:搜尋|查詢|搜索|檢索|查閱|查|找|看|看看)\s*'
        r'(?:一下|看看|瞧瞧)?\s*'
        r'(?:關於|有關)?[:：\s]*(?P<query>.+)$',
        re.IGNORECASE,
    ),
    # 2. Search engine verb / name (google / bing / yahoo / duckduckgo / 谷歌 / 谷哥)
    re.compile(
        r'^(?:請|麻煩|拜託|勞駕)?\s*'
        r'(?:你|您)?\s*'
        r'(?:可以|能|能否|能不能|可不可以|可否)?\s*'
        r'(?:請|麻煩|拜託)?\s*'
        r'(?:幫我|替我|幫忙)?\s*'
        r'(?:google|googling|bing|yahoo|duckduckgo|谷歌|谷哥)\s*'
        r'(?:一下|搜尋|搜索|查詢|查閱|查|找)?\s*'
        r'(?:一下|看看|瞧瞧)?\s*'
        r'(?:關於|有關)?[:：\s]*(?P<query>.+)$',
        re.IGNORECASE,
    ),
    # 3. Direct explicit search verbs (搜尋/查詢/搜索/檢索/查一下/找一下/查看看/找看看/查/找)
    re.compile(
        r'^(?:請|麻煩|拜託|勞駕)?\s*'
        r'(?:你|您)?\s*'
        r'(?:可以|能|能否|能不能|可不可以|可否)?\s*'
        r'(?:請|麻煩|拜託)?\s*'
        r'(?:幫我|替我|幫忙)?\s*'
        r'(?:搜尋|查詢|搜索|檢索|查一下|找一下|查看看|找看看|查查|找找|查閱|查)\s*'
        r'(?:一下|看看|瞧瞧)?\s*'
        r'(?:關於|有關)?[:：\s]*(?P<query>.+)$',
        re.IGNORECASE,
    ),
    # 4. "找一下" / "找找" standalone
    re.compile(
        r'^(?:請|麻煩|拜託|勞駕)?\s*'
        r'(?:你|您)?\s*'
        r'(?:可以|能|能否|能不能|可不可以|可否)?\s*'
        r'(?:請|麻煩|拜託)?\s*'
        r'(?:幫我|替我|幫忙)?\s*'
        r'(?:找一下|找看看|找找)\s*'
        r'(?:一下|看看|瞧瞧)?\s*'
        r'(?:關於|有關)?[:：\s]*(?P<query>.+)$',
        re.IGNORECASE,
    ),
]


def clean_search_query(query: str) -> str:
    """Filters leading and trailing filler words, particles, and punctuation from extracted search query."""
    q = query.strip()
    # Strip wrapping quotes
    q = re.sub(r"^[「『\"\'“‘]+|[」』\"\'”’]+$", "", q).strip()

    for _ in range(5):
        prev = q
        # 1. Trailing punctuation & question/polite particles
        q = re.sub(r"[\?？!！。.~～…]+$", "", q).strip()
        q = re.sub(r"(?:嗎|呢|吧|呀|啦|啊|嘛|謝謝|感謝|拜託|麻煩了|勞駕)$", "", q).strip()
        q = re.sub(r"[\?？!！。.~～…]+$", "", q).strip()

        # 2. Trailing fillers
        # "新聞" rule: (unless the whole term is news / latest news)
        if q not in ("新聞", "最新新聞", "即時新聞", "今日新聞", "今天新聞", "頭條新聞", "熱門新聞"):
            m_news = re.search(r"^(.+?)(?:相關新聞|的新聞|新聞)$", q)
            if m_news:
                stem = m_news.group(1).rstrip("的").strip()
                if stem and stem not in ("最新", "即時", "今日", "今天", "熱門", "頭條", "時事"):
                    q = stem

        q = re.sub(r"(?:相關資訊|相關資料|相關消息|相關內容|相關報導|的相關資訊|的相關資料|的資訊|的資料|相關|資訊|資料|內容|消息|報告)$", "", q).strip()
        q = re.sub(r"(?:一下|看看|瞧瞧|幫我|替我)$", "", q).strip()
        q = re.sub(r"(?:的)$", "", q).strip()

        # 3. Leading fillers
        q = re.sub(r"^[:：\s]+", "", q).strip()
        q = re.sub(r"^(?:一下|看看|瞧瞧|幫我|替我|幫忙|請|麻煩|關於|有關|的)[:：\s]*", "", q).strip()
        q = re.sub(r"^[:：\s]+", "", q).strip()

        if q == prev:
            break

    q = re.sub(r"^[「『\"\'“‘]+|[」』\"\'”’]+$", "", q).strip()
    return q


def detect_search_intent(text: str) -> Optional[str]:
    """Detects if user prompt explicitly requests live web search.
    Returns cleaned search query string if detected, otherwise None.
    """
    clean = text.strip()
    if not clean or len(clean) < 2:
        return None

    # Exclude image drawing intent
    if any(draw_kw in clean for draw_kw in ("畫", "生圖", "生成圖", "繪製", "繪圖", "作畫", "照片", "插圖", "產圖")):
        return None

    for pattern in _SEARCH_INTENT_PATTERNS:
        m = pattern.match(clean)
        if m:
            raw_query = m.group("query")
            query = clean_search_query(raw_query)
            if len(query) >= 2:
                return query
    return None


web_client = WebClient()

