"""ZeroNexus Google Official API Suite.

Integrates 5 high-value Google Cloud APIs with generous/free tiers:
1. Google Safe Browsing API v4: Real-time phishing and malware detection with LRU cache.
2. YouTube Data API v3: Rich video details, search, channel metadata, ISO8601 duration parser.
3. Google Fact Check Tools API: Global & Taiwan verified fact check claims and debunking reports.
4. Google PageSpeed Insights API: Lighthouse 0-100 score, Core Web Vitals (FCP, LCP, CLS, TBT).
5. Google Books API: Global book volume search, ISBN, authors, publisher, ratings, covers.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

log = logging.getLogger("zeronexus.google_suite")

# URL extraction regex for chat message scanning
URL_PATTERN = re.compile(
    r"(?:https?://|www\.)[a-zA-Z0-9.\-_~:/?#\[\]@!$&\'()*+,;=%]+",
    re.IGNORECASE,
)


def extract_urls(text: str) -> List[str]:
    """Extracts unique HTTP/HTTPS URLs from raw text."""
    if not text:
        return []
    matches = URL_PATTERN.findall(text)
    clean_urls = []
    seen = set()
    for m in matches:
        u = m.strip()
        if not u.startswith(("http://", "https://")):
            u = f"https://{u}"
        # Strip trailing common punctuation that might be caught
        u = u.rstrip(".,;!?'\")>]}，。！？；：）】」』")
        if u and u not in seen:
            seen.add(u)
            clean_urls.append(u)
    return clean_urls


def parse_iso8601_duration(duration_str: str) -> Tuple[int, str]:
    """Converts ISO 8601 duration (e.g. PT1H2M34S, PT5M12S) to (seconds, formatted_string)."""
    if not duration_str or not duration_str.startswith("P"):
        return 0, "00:00"
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration_str)
    if not m:
        return 0, duration_str
    h = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    total_seconds = h * 3600 + minutes * 60 + s
    if h > 0:
        formatted = f"{h:02d}:{minutes:02d}:{s:02d}"
    else:
        formatted = f"{minutes:02d}:{s:02d}"
    return total_seconds, formatted


from urllib.parse import urlparse

# Universally trusted domains whitelist to eliminate false positives and reduce API latency
TRUSTED_DOMAINS = {
    # Video & Media
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "twitch.tv", "www.twitch.tv",
    "spotify.com", "open.spotify.com",
    "tenor.com", "media.tenor.com", "giphy.com",
    # Discord ecosystem
    "discord.com", "discord.gg", "discordapp.com", "discordapp.net", "cdn.discordapp.com",
    # Google services
    "google.com", "www.google.com", "google.com.tw", "googleapis.com", "gstatic.com",
    # Dev & Open Source
    "github.com", "raw.githubusercontent.com", "github.io", "gitlab.com",
    # Gaming
    "steamcommunity.com", "steampowered.com", "store.steampowered.com",
    "gamer.com.tw", "forum.gamer.com.tw",
    # Social Media
    "twitter.com", "x.com", "t.co",
    "instagram.com", "facebook.com", "fb.me", "reddit.com", "www.reddit.com",
    # Reference & Forums
    "wikipedia.org", "zh.wikipedia.org", "en.wikipedia.org", "wikimedia.org",
    "ptt.cc", "www.ptt.cc",
}


def is_trusted_domain(url: str) -> bool:
    """Checks if a URL belongs to well-known trusted platforms or official government/educational domains."""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        for td in TRUSTED_DOMAINS:
            if hostname == td or hostname.endswith(f".{td}"):
                return True
        # Government and Academic official TLDs
        if hostname.endswith(".gov.tw") or hostname.endswith(".edu.tw") or hostname.endswith(".gov") or hostname.endswith(".edu"):
            return True
    except Exception:
        pass
    return False


# =============================================================================
# 1. Google Safe Browsing API Client
# =============================================================================
class GoogleSafeBrowsingClient:
    """Client for Google Safe Browsing v4 threatMatches endpoint."""

    ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

    THREAT_NAMES = {
        "MALWARE": "惡意軟體 / 木馬病毒 (Malware)",
        "SOCIAL_ENGINEERING": "社交工程釣魚詐騙 (Phishing / Social Engineering)",
        "UNWANTED_SOFTWARE": "有害非預期軟體 (Unwanted Software)",
        "POTENTIALLY_HARMFUL_APPLICATION": "潛在危害應用程式 (Harmful Application)",
        "THREAT_TYPE_UNSPECIFIED": "未知危險威脅 (Unspecified Threat)",
    }

    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[bool, str, float]] = {}  # url -> (is_threat, threat_type, expire_ts)
        self._cache_ttl_clean = 900.0  # 15 mins for clean URLs
        self._cache_ttl_threat = 3600.0  # 1 hour for malicious URLs

    def _get_api_key(self) -> str:
        return (
            os.getenv("GOOGLE_SAFE_BROWSING_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        )

    async def check_urls(self, urls: List[str]) -> Dict[str, Dict[str, Any]]:
        """Checks multiple URLs against Google Safe Browsing.

        Returns a dictionary mapping each URL to its threat status.
        Safe and whitelisted URLs are guaranteed to be marked clean with 0 notifications.
        """
        results: Dict[str, Dict[str, Any]] = {}
        if not urls:
            return results

        now = time.time()
        uncached_urls: List[str] = []

        for u in urls:
            # 1. Immediate whitelist check (avoid unnecessary API calls & false positives)
            if is_trusted_domain(u):
                results[u] = {
                    "url": u,
                    "is_threat": False,
                    "threat_type": "NONE",
                    "threat_desc": "官方/社群認證白名單",
                    "cached": True,
                }
                continue

            # 2. In-memory LRU cache check
            if u in self._cache:
                is_threat, threat_type, expire_ts = self._cache[u]
                if now < expire_ts:
                    results[u] = {
                        "url": u,
                        "is_threat": is_threat,
                        "threat_type": threat_type,
                        "threat_desc": self.THREAT_NAMES.get(threat_type, threat_type),
                        "cached": True,
                    }
                    continue
            uncached_urls.append(u)

        if not uncached_urls:
            return results

        api_key = self._get_api_key()
        if not api_key:
            # Without API key, mark as clean with note
            for u in uncached_urls:
                results[u] = {
                    "url": u,
                    "is_threat": False,
                    "threat_type": "NONE",
                    "threat_desc": "未設定 Safe Browsing API Key",
                    "cached": False,
                }
            return results

        payload = {
            "client": {"clientId": "ZeroNexusBot", "clientVersion": "3.0.0"},
            "threatInfo": {
                "threatTypes": [
                    "MALWARE",
                    "SOCIAL_ENGINEERING",
                    "UNWANTED_SOFTWARE",
                    "POTENTIALLY_HARMFUL_APPLICATION",
                ],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": u} for u in uncached_urls],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(
                    f"{self.ENDPOINT}?key={api_key}",
                    json=payload,
                )
                if res.status_code == 200:
                    data = res.json()
                    matches = data.get("matches", [])
                    matched_threats: Dict[str, str] = {}
                    for m in matches:
                        entry = m.get("threat", {}).get("url", "")
                        ttype = m.get("threatType", "THREAT_TYPE_UNSPECIFIED")
                        if entry:
                            matched_threats[entry] = ttype

                    for u in uncached_urls:
                        if u in matched_threats:
                            ttype = matched_threats[u]
                            self._cache[u] = (True, ttype, now + self._cache_ttl_threat)
                            results[u] = {
                                "url": u,
                                "is_threat": True,
                                "threat_type": ttype,
                                "threat_desc": self.THREAT_NAMES.get(ttype, ttype),
                                "cached": False,
                            }
                        else:
                            self._cache[u] = (False, "NONE", now + self._cache_ttl_clean)
                            results[u] = {
                                "url": u,
                                "is_threat": False,
                                "threat_type": "NONE",
                                "threat_desc": "安全無威脅 (Safe)",
                                "cached": False,
                            }
                else:
                    log.warning(f"[SafeBrowsing] HTTP {res.status_code}: {res.text[:120]}")
                    for u in uncached_urls:
                        results[u] = {
                            "url": u,
                            "is_threat": False,
                            "threat_type": "ERROR",
                            "threat_desc": f"Safe Browsing 檢測失敗 (HTTP {res.status_code})",
                            "cached": False,
                        }
        except Exception as e:
            log.warning(f"[SafeBrowsing] 呼叫異常: {e}")
            for u in uncached_urls:
                results[u] = {
                    "url": u,
                    "is_threat": False,
                    "threat_type": "ERROR",
                    "threat_desc": f"檢測連線異常: {e}",
                    "cached": False,
                }

        return results

    async def check_url(self, url: str) -> Dict[str, Any]:
        """Convenience method to check a single URL."""
        res_map = await self.check_urls([url])
        return res_map.get(url, {
            "url": url,
            "is_threat": False,
            "threat_type": "NONE",
            "threat_desc": "無資料",
            "cached": False,
        })


# =============================================================================
# 2. YouTube Data API Client
# =============================================================================
class YouTubeDataClient:
    """Client for YouTube Data API v3 (Videos and Search)."""

    VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
    SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"

    def _get_api_key(self) -> str:
        return os.getenv("YOUTUBE_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()

    @staticmethod
    def extract_video_id(url_or_id: str) -> Optional[str]:
        """Extracts 11-character YouTube video ID from various URL formats."""
        if not url_or_id:
            return None
        raw = url_or_id.strip()
        if len(raw) == 11 and re.match(r"^[a-zA-Z0-9_-]{11}$", raw):
            return raw
        # Match standard youtube urls
        patterns = [
            r"(?:v=|\/embed\/|\/live\/|\/shorts\/|youtu\.be\/|\/v\/)([a-zA-Z0-9_-]{11})",
            r"^([a-zA-Z0-9_-]{11})$",
        ]
        for p in patterns:
            m = re.search(p, raw)
            if m:
                return m.group(1)
        return None

    async def get_video_details(self, url_or_id: str) -> Dict[str, Any]:
        """Fetches full video details using YouTube Data API v3."""
        video_id = self.extract_video_id(url_or_id)
        if not video_id:
            return {"status": "INVALID_ID", "error": "無法從輸入中辨識合法的 YouTube 影片 ID"}

        api_key = self._get_api_key()
        if not api_key:
            return {
                "status": "NO_API_KEY",
                "video_id": video_id,
                "title": f"YouTube 影片 ({video_id})",
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "channel_title": "YouTube 創作者",
                "view_count": 0,
                "view_count_formatted": "未知",
                "like_count": 0,
                "duration": "未知",
                "duration_seconds": 0,
                "description": "",
                "published_at": "",
            }

        params = {
            "part": "snippet,contentDetails,statistics",
            "id": video_id,
            "key": api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(self.VIDEOS_ENDPOINT, params=params)
                if res.status_code == 200:
                    data = res.json()
                    items = data.get("items", [])
                    if not items:
                        return {"status": "NOT_FOUND", "video_id": video_id, "error": "找不到此 YouTube 影片或影片為私人/已刪除"}

                    item = items[0]
                    snippet = item.get("snippet", {})
                    content_details = item.get("contentDetails", {})
                    statistics = item.get("statistics", {})

                    # Format thumbnails (maxres -> standard -> high -> medium -> default)
                    thumbs = snippet.get("thumbnails", {})
                    thumbnail_url = (
                        thumbs.get("maxres", {}).get("url")
                        or thumbs.get("standard", {}).get("url")
                        or thumbs.get("high", {}).get("url")
                        or thumbs.get("medium", {}).get("url")
                        or thumbs.get("default", {}).get("url")
                        or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                    )

                    # Duration
                    raw_duration = content_details.get("duration", "")
                    dur_sec, dur_fmt = parse_iso8601_duration(raw_duration)

                    # Stats
                    views = int(statistics.get("viewCount", 0))
                    likes = int(statistics.get("likeCount", 0))

                    def _fmt_num(n: int) -> str:
                        if n >= 100_000_000:
                            return f"{n / 100_000_000:.1f} 億"
                        if n >= 10_000:
                            return f"{n / 10_000:.1f} 萬"
                        return f"{n:,}"

                    return {
                        "status": "SUCCESS",
                        "video_id": video_id,
                        "title": snippet.get("title", ""),
                        "channel_title": snippet.get("channelTitle", ""),
                        "channel_id": snippet.get("channelId", ""),
                        "description": snippet.get("description", ""),
                        "published_at": snippet.get("publishedAt", ""),
                        "duration": dur_fmt,
                        "duration_seconds": dur_sec,
                        "view_count": views,
                        "view_count_formatted": _fmt_num(views),
                        "like_count": likes,
                        "like_count_formatted": _fmt_num(likes),
                        "thumbnail_url": thumbnail_url,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                    }
                else:
                    return {"status": "HTTP_ERROR", "code": res.status_code, "error": f"YouTube API 回應錯誤 HTTP {res.status_code}"}
        except Exception as e:
            return {"status": "NETWORK_ERROR", "error": f"連線 YouTube API 失敗: {e}"}

    async def search_videos(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Searches YouTube for videos matching the query."""
        clean_q = query.strip()
        if not clean_q:
            return {"status": "INVALID_QUERY", "results": [], "error": "搜尋關鍵字不可為空"}

        api_key = self._get_api_key()
        if not api_key:
            return {"status": "NO_API_KEY", "results": [], "error": "未設定 YOUTUBE_API_KEY"}

        params = {
            "part": "snippet",
            "type": "video",
            "q": clean_q,
            "maxResults": max(1, min(max_results, 10)),
            "key": api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(self.SEARCH_ENDPOINT, params=params)
                if res.status_code == 200:
                    data = res.json()
                    items = data.get("items", [])
                    results = []
                    for it in items:
                        vid = it.get("id", {}).get("videoId", "")
                        snip = it.get("snippet", {})
                        if vid:
                            thumbs = snip.get("thumbnails", {})
                            thumb = (
                                thumbs.get("high", {}).get("url")
                                or thumbs.get("medium", {}).get("url")
                                or thumbs.get("default", {}).get("url")
                            )
                            results.append({
                                "video_id": vid,
                                "title": snip.get("title", ""),
                                "channel_title": snip.get("channelTitle", ""),
                                "published_at": snip.get("publishedAt", ""),
                                "thumbnail_url": thumb,
                                "url": f"https://www.youtube.com/watch?v={vid}",
                            })
                    return {
                        "status": "SUCCESS",
                        "query": clean_q,
                        "results": results,
                        "total_results": len(results),
                    }
                return {"status": "HTTP_ERROR", "code": res.status_code, "results": [], "error": f"HTTP {res.status_code}"}
        except Exception as e:
            return {"status": "NETWORK_ERROR", "results": [], "error": str(e)}


# =============================================================================
# 3. Google Fact Check Tools API Client
# =============================================================================
class GoogleFactCheckClient:
    """Client for Google Fact Check Tools API."""

    ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

    def _get_api_key(self) -> str:
        return (
            os.getenv("GOOGLE_FACT_CHECK_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        )

    async def search_claims(self, query: str, language_code: str = "zh-TW") -> Dict[str, Any]:
        """Searches fact check claims verified by credible fact-checking organizations."""
        clean_q = query.strip()
        if not clean_q:
            return {"status": "INVALID_QUERY", "claims": [], "error": "查核關鍵字不可為空"}

        api_key = self._get_api_key()
        if not api_key:
            return {"status": "NO_API_KEY", "claims": [], "error": "未設定 GOOGLE_FACT_CHECK_API_KEY"}

        params = {
            "query": clean_q,
            "languageCode": language_code,
            "key": api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=7.0) as client:
                res = await client.get(self.ENDPOINT, params=params)
                # If zh-TW returns no items, try global search without languageCode
                data = res.json() if res.status_code == 200 else {}
                claims_raw = data.get("claims", [])

                if not claims_raw and language_code:
                    res_global = await client.get(self.ENDPOINT, params={"query": clean_q, "key": api_key})
                    if res_global.status_code == 200:
                        claims_raw = res_global.json().get("claims", [])

                claims = []
                for c in claims_raw:
                    claim_text = c.get("text", "")
                    claimant = c.get("claimant", "網路謠言 / 社群訊息")
                    reviews = c.get("claimReview", [])
                    review_info = {}
                    if reviews:
                        r0 = reviews[0]
                        publisher = r0.get("publisher", {}).get("name", "認證事實查核機構")
                        rating = r0.get("textualRating", "尚無明確評級")
                        title = r0.get("title", "")
                        url = r0.get("url", "")
                        review_info = {
                            "publisher": publisher,
                            "rating": rating,
                            "title": title,
                            "url": url,
                        }
                    claims.append({
                        "claim": claim_text,
                        "claimant": claimant,
                        "claim_date": c.get("claimDate", ""),
                        "review": review_info,
                    })

                return {
                    "status": "SUCCESS",
                    "query": clean_q,
                    "claims": claims,
                    "total_claims": len(claims),
                }
        except Exception as e:
            return {"status": "NETWORK_ERROR", "claims": [], "error": str(e)}


# =============================================================================
# 4. Google PageSpeed Insights API Client
# =============================================================================
class GooglePageSpeedClient:
    """Client for Google PageSpeed Insights API v5."""

    ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    def _get_api_key(self) -> str:
        return (
            os.getenv("GOOGLE_PAGESPEED_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        )

    async def analyze_url(self, url: str, strategy: str = "mobile") -> Dict[str, Any]:
        """Runs a Lighthouse performance audit on the target URL."""
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"https://{clean_url}"

        api_key = self._get_api_key()
        strat = "desktop" if strategy.lower() == "desktop" else "mobile"

        params = {
            "url": clean_url,
            "strategy": strat,
            "category": "PERFORMANCE",
        }
        if api_key:
            params["key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.get(self.ENDPOINT, params=params)
                if res.status_code == 200:
                    data = res.json()
                    lh = data.get("lighthouseResult", {})
                    categories = lh.get("categories", {})
                    perf_score = int((categories.get("performance", {}).get("score") or 0) * 100)

                    audits = lh.get("audits", {})
                    fcp = audits.get("first-contentful-paint", {}).get("displayValue", "N/A")
                    lcp = audits.get("largest-contentful-paint", {}).get("displayValue", "N/A")
                    cls_val = audits.get("cumulative-layout-shift", {}).get("displayValue", "N/A")
                    tbt = audits.get("total-blocking-time", {}).get("displayValue", "N/A")
                    speed_index = audits.get("speed-index", {}).get("displayValue", "N/A")

                    return {
                        "status": "SUCCESS",
                        "url": clean_url,
                        "strategy": strat,
                        "performance_score": perf_score,
                        "first_contentful_paint": fcp,
                        "largest_contentful_paint": lcp,
                        "cumulative_layout_shift": cls_val,
                        "total_blocking_time": tbt,
                        "speed_index": speed_index,
                        "fetch_time": lh.get("fetchTime", ""),
                    }
                else:
                    return {
                        "status": "HTTP_ERROR",
                        "code": res.status_code,
                        "error": f"PageSpeed API 回應 HTTP {res.status_code}: {res.text[:120]}",
                    }
        except Exception as e:
            return {"status": "NETWORK_ERROR", "error": f"PageSpeed 測速連線異常: {e}"}


# =============================================================================
# 5. Google Books API Client
# =============================================================================
class GoogleBooksClient:
    """Client for Google Books API."""

    ENDPOINT = "https://www.googleapis.com/books/v1/volumes"

    def _get_api_key(self) -> str:
        return (
            os.getenv("GOOGLE_BOOKS_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        )

    async def search_books(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Searches for books by title, author, or ISBN."""
        clean_q = query.strip()
        if not clean_q:
            return {"status": "INVALID_QUERY", "books": [], "error": "書籍搜尋詞不可為空"}

        api_key = self._get_api_key()
        params: Dict[str, Any] = {
            "q": clean_q,
            "maxResults": max(1, min(max_results, 10)),
        }
        if api_key:
            params["key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=7.0) as client:
                res = await client.get(self.ENDPOINT, params=params)
                if res.status_code == 200:
                    data = res.json()
                    items = data.get("items", [])
                    books = []
                    for it in items:
                        vol = it.get("volumeInfo", {})
                        thumbs = vol.get("imageLinks", {})
                        thumb = (
                            thumbs.get("thumbnail")
                            or thumbs.get("smallThumbnail")
                            or ""
                        )
                        if thumb.startswith("http://"):
                            thumb = f"https://{thumb[7:]}"

                        isbns = []
                        for ident in vol.get("industryIdentifiers", []):
                            isbns.append(f"{ident.get('type')}: {ident.get('identifier')}")

                        books.append({
                            "title": vol.get("title", "未知書名"),
                            "authors": vol.get("authors", ["未知作者"]),
                            "publisher": vol.get("publisher", "未知出版社"),
                            "published_date": vol.get("publishedDate", ""),
                            "description": vol.get("description", "")[:280],
                            "page_count": vol.get("pageCount", 0),
                            "categories": vol.get("categories", []),
                            "average_rating": vol.get("averageRating", 0.0),
                            "thumbnail_url": thumb,
                            "preview_link": vol.get("previewLink", ""),
                            "info_link": vol.get("infoLink", ""),
                            "isbns": isbns,
                        })
                    return {
                        "status": "SUCCESS",
                        "query": clean_q,
                        "books": books,
                        "total_books": len(books),
                    }
                return {"status": "HTTP_ERROR", "code": res.status_code, "books": [], "error": f"HTTP {res.status_code}"}
        except Exception as e:
            return {"status": "NETWORK_ERROR", "books": [], "error": str(e)}


# =============================================================================
# Composite Engine Singleton
# =============================================================================
class GoogleSuiteEngine:
    """Consolidated Google API Suite Engine for ZeroNexus."""

    def __init__(self) -> None:
        self.safe_browsing = GoogleSafeBrowsingClient()
        self.youtube = YouTubeDataClient()
        self.fact_check = GoogleFactCheckClient()
        self.pagespeed = GooglePageSpeedClient()
        self.books = GoogleBooksClient()

    @staticmethod
    def extract_urls(text: str) -> List[str]:
        return extract_urls(text)


google_suite = GoogleSuiteEngine()
