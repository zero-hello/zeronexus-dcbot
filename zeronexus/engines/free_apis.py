"""ZeroNexus Free & Open High-Value API Integration Engine.

Provides reliable, zero-key, high-availability wrappers for top-tier public data sources:
1. Steam Store & Community API (Live price, discount, historical low, reviews, online players)
2. Crypto Real-time Quotes (Binance & CoinGecko multi-currency endpoints)
3. Global Exchange Rates (Frankfurter ECB feed & Open Exchange Rates hybrid)
4. Taiwan Rail & Transit Live Dynamic (TRA LiveBoard delays & THSR AlertInfo/Timetable)
5. Anime Database (MyAnimeList via Jikan v4 with AniList GraphQL automatic failover)
6. GitHub REST API (Stars, forks, open issues, latest release version, author)
7. Wikipedia & Wikidata API (Standard encyclopedia definitions, historical events, entity info)
8. Taiwan Air Quality & UV Index (MoENV open data & Open-Meteo Air Quality/UV fallback)
+ Google Custom Search JSON API relay (Prioritized when environment keys exist)
"""

from __future__ import annotations

import asyncio
import datetime
import fnmatch
import html
import json
import os
import re
import socket
import ssl
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from zeronexus.core.logger import log

# =============================================================================
# Taiwan Coordinates & Transit Mappings
# =============================================================================

TAIWAN_COORDINATES: Dict[str, Tuple[float, float]] = {
    "台北": (25.0330, 121.5654),
    "臺北": (25.0330, 121.5654),
    "新北": (25.0116, 121.4657),
    "基隆": (25.1276, 121.7392),
    "桃園": (24.9936, 121.3010),
    "新竹": (24.8138, 120.9675),
    "苗栗": (24.5602, 120.8214),
    "台中": (24.1477, 120.6736),
    "臺中": (24.1477, 120.6736),
    "彰化": (24.0518, 120.5161),
    "南投": (23.9100, 120.6860),
    "雲林": (23.7092, 120.4313),
    "嘉義": (23.4800, 120.4491),
    "台南": (22.9997, 120.2270),
    "臺南": (22.9997, 120.2270),
    "高雄": (22.6273, 120.3014),
    "屏東": (22.6761, 120.4885),
    "宜蘭": (24.7021, 121.7377),
    "花蓮": (23.9871, 121.6015),
    "台東": (22.7583, 121.1444),
    "臺東": (22.7583, 121.1444),
    "澎湖": (23.5711, 119.5793),
    "金門": (24.4493, 118.3766),
    "連江": (26.1558, 119.9519),
    "馬祖": (26.1558, 119.9519),
}

THSR_STATION_MAP: Dict[str, str] = {
    "南港": "NanGang",
    "台北": "TaiPei",
    "臺北": "TaiPei",
    "板橋": "BanQiao",
    "桃園": "TaoYuan",
    "新竹": "XinZhu",
    "苗栗": "MiaoLi",
    "台中": "TaiZhong",
    "臺中": "TaiZhong",
    "彰化": "ZhangHua",
    "雲林": "YunLin",
    "嘉義": "JiaYi",
    "台南": "TaiNan",
    "臺南": "TaiNan",
    "左營": "ZuoYing",
    "新左營": "ZuoYing",
    "高雄": "ZuoYing",
}

TRA_STATION_MAP: Dict[str, str] = {
    "基隆": "0900-基隆", "三坑": "0910-三坑", "八堵": "0920-八堵", "七堵": "0930-七堵",
    "百福": "0940-百福", "五堵": "0950-五堵", "汐止": "0960-汐止", "汐科": "0970-汐科",
    "南港": "0980-南港", "松山": "0990-松山", "台北": "1000-臺北", "臺北": "1000-臺北",
    "萬華": "1010-萬華", "板橋": "1020-板橋", "浮洲": "1030-浮洲", "樹林": "1040-樹林",
    "南樹林": "1050-南樹林", "山佳": "1060-山佳", "鶯歌": "1070-鶯歌", "桃園": "1080-桃園",
    "內壢": "1090-內壢", "中壢": "1100-中壢", "埔心": "1110-埔心", "楊梅": "1120-楊梅",
    "富岡": "1130-富岡", "湖口": "1160-湖口", "新豐": "1170-新豐", "竹北": "1180-竹北",
    "北新竹": "1190-北新竹", "新竹": "1210-新竹", "三姓橋": "1220-三姓橋", "香山": "1230-香山",
    "竹南": "1250-竹南", "後龍": "2130-後龍", "通霄": "2170-通霄", "苑裡": "2180-苑裡",
    "大甲": "2200-大甲", "清水": "2220-清水", "沙鹿": "2230-沙鹿", "苗栗": "3160-苗栗",
    "銅鑼": "3180-銅鑼", "三義": "3190-三義", "后里": "3220-后里", "豐原": "3230-豐原",
    "潭子": "3250-潭子", "太原": "3280-太原", "台中": "3300-臺中", "臺中": "3300-臺中",
    "大慶": "3320-大慶", "烏日": "3330-烏日", "新烏日": "3340-新烏日", "成功": "3350-成功",
    "彰化": "3360-彰化", "員林": "3390-員林", "社頭": "3410-社頭", "田中": "3420-田中",
    "二水": "3430-二水", "斗六": "3470-斗六", "斗南": "3480-斗南", "大林": "4050-大林",
    "民雄": "4060-民雄", "嘉義": "4080-嘉義", "水上": "4090-水上", "新營": "4120-新營",
    "林鳳營": "4140-林鳳營", "隆田": "4150-隆田", "善化": "4170-善化", "新市": "4190-新市",
    "永康": "4200-永康", "台南": "4220-臺南", "臺南": "4220-臺南", "保安": "4250-保安",
    "中洲": "4270-中洲", "沙崙": "4272-沙崙", "大湖": "4290-大湖", "路竹": "4300-路竹",
    "岡山": "4310-岡山", "橋頭": "4320-橋頭", "楠梓": "4330-楠梓", "新左營": "4340-新左營",
    "左營": "4340-新左營", "高雄": "4400-高雄", "鳳山": "4440-鳳山", "九曲堂": "4460-九曲堂",
    "屏東": "5000-屏東", "西勢": "5030-西勢", "潮州": "5050-潮州", "南州": "5070-南州",
    "林邊": "5090-林邊", "枋寮": "5120-枋寮", "大武": "5190-大武", "金崙": "5210-金崙",
    "太麻里": "5220-太麻里", "知本": "5230-知本", "康樂": "5240-康樂", "台東": "6000-臺東",
    "臺東": "6000-臺東", "鹿野": "6020-鹿野", "關山": "6050-關山", "池上": "6070-池上",
    "富里": "6080-富里", "玉里": "6110-玉里", "瑞穗": "6130-瑞穗", "光復": "6160-光復",
    "鳳林": "6180-鳳林", "壽豐": "6220-壽豐", "志學": "6240-志學", "吉安": "6250-吉安",
    "花蓮": "7000-花蓮", "新城": "7030-新城", "和平": "7060-和平", "南澳": "7090-南澳",
    "東澳": "7100-東澳", "蘇澳": "7120-蘇澳", "蘇澳新": "7130-蘇澳新", "冬山": "7150-冬山",
    "羅東": "7160-羅東", "二結": "7180-二結", "宜蘭": "7190-宜蘭", "礁溪": "7210-礁溪",
    "頭城": "7230-頭城", "龜山": "7250-龜山", "大溪": "7260-大溪", "福隆": "7290-福隆",
    "雙溪": "7310-雙溪", "三貂嶺": "7330-三貂嶺", "十分": "7332-十分", "平溪": "7335-平溪",
    "菁桐": "7336-菁桐", "猴硐": "7350-猴硐", "瑞芳": "7360-瑞芳",
}


def resolve_tra_station(name: str) -> Tuple[Optional[str], str]:
    """Resolves station name or alias to official TRA station identifier."""
    clean = name.strip()
    if clean in TRA_STATION_MAP:
        return TRA_STATION_MAP[clean], clean
    for k, v in TRA_STATION_MAP.items():
        if k in clean or clean in k:
            return v, k
    return None, clean


def resolve_thsr_station(name: str) -> Tuple[Optional[str], str]:
    """Resolves station name or alias to official THSR station identifier."""
    clean = name.strip()
    if clean in THSR_STATION_MAP:
        return THSR_STATION_MAP[clean], clean
    for k, v in THSR_STATION_MAP.items():
        if k in clean or clean in k:
            return v, k
    return None, clean

# =============================================================================
# Crypto Common Mappings
# =============================================================================

CRYPTO_MAP: Dict[str, Tuple[str, str, str]] = {
    "BTC": ("BTCUSDT", "bitcoin", "Bitcoin"),
    "ETH": ("ETHUSDT", "ethereum", "Ethereum"),
    "SOL": ("SOLUSDT", "solana", "Solana"),
    "BNB": ("BNBUSDT", "binancecoin", "BNB"),
    "DOGE": ("DOGEUSDT", "dogecoin", "Dogecoin"),
    "XRP": ("XRPUSDT", "ripple", "XRP"),
    "ADA": ("ADAUSDT", "cardano", "Cardano"),
    "AVAX": ("AVAXUSDT", "avalanche-2", "Avalanche"),
    "DOT": ("DOTUSDT", "polkadot", "Polkadot"),
    "TRX": ("TRXUSDT", "tron", "TRON"),
    "LINK": ("LINKUSDT", "chainlink", "Chainlink"),
    "SUI": ("SUIUSDT", "sui", "Sui"),
    "NEAR": ("NEARUSDT", "near", "NEAR Protocol"),
    "APT": ("APTUSDT", "aptos", "Aptos"),
    "PEPE": ("PEPEUSDT", "pepe", "Pepe"),
}


class FreeAPIEngine:
    """Consolidated engine providing zero-key, high-resilience public API integrations."""

    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None
        self._tdx_token: Optional[str] = None
        self._tdx_token_expires_at: float = 0.0

    async def _get_client(self, timeout: float = 10.0) -> httpx.AsyncClient:
        """Returns or creates a persistent pooled AsyncClient."""
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "User-Agent": "ZeroNexusBot/1.0 (Free-API-Ecosystem; contact@zeronexus.internal)",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                verify=True,  # 【安全修復】恢復 TLS 憑證鏈驗證，阻斷 MITM 對股價/匯率/地震資料之投毒（原先停用驗證使外部資料可被中間人篡改後直達 system prompt）
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=40, keepalive_expiry=60.0),
            )
        return self._http_client

    async def _get_tdx_token(self) -> Optional[str]:
        """Retrieves or refreshes official TDX Transport API OAuth token if credentials exist."""
        client_id = os.getenv("TDX_CLIENT_ID", "").strip()
        client_secret = os.getenv("TDX_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None

        import time
        now = time.time()
        if self._tdx_token and now < (self._tdx_token_expires_at - 60.0):
            return self._tdx_token

        try:
            client = await self._get_client(timeout=10.0)
            token_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
            resp = await client.post(token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            if resp.status_code == 200:
                tok_data = resp.json()
                self._tdx_token = tok_data.get("access_token")
                expires_in = float(tok_data.get("expires_in", 86400))
                self._tdx_token_expires_at = now + expires_in
                log.info("Successfully acquired official TDX Transport API OAuth access token!")
                return self._tdx_token
            else:
                log.warning(f"TDX token request returned HTTP {resp.status_code}: {resp.text[:120]}")
        except Exception as te:
            log.warning(f"Failed to acquire TDX OAuth token: {te}")
        return None

    async def close(self) -> None:
        """Gracefully shuts down the async client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # =========================================================================
    # 1. 🎮 Steam 遊戲資料庫
    # =========================================================================

    async def get_steam_game_info(
        self,
        game_name: Optional[str] = None,
        appid: Optional[int] = None,
        currency: str = "tw",
    ) -> Dict[str, Any]:
        """Queries Steam Store, reviews, players, and historical lowest price (史低)."""
        client = await self._get_client()

        # Step 1: Resolve AppID if not provided
        target_appid = appid
        matched_name = game_name or ""

        if not target_appid:
            if not game_name or not game_name.strip():
                return {"status": "ERROR", "error": "請提供遊戲名稱 (game_name) 或 Steam App ID (appid)"}
            search_url = f"https://store.steampowered.com/api/storesearch/?term={urllib.parse.quote_plus(game_name.strip())}&l=tchinese&cc={currency}"
            try:
                s_resp = await client.get(search_url)
                if s_resp.status_code == 200:
                    s_data = s_resp.json()
                    items = s_data.get("items", [])
                    if items:
                        target_appid = items[0].get("id")
                        matched_name = items[0].get("name", matched_name)
                    else:
                        return {"status": "NOT_FOUND", "message": f"在 Steam 商店搜尋不到符合「{game_name}」的遊戲"}
                else:
                    return {"status": "ERROR", "error": f"Steam 搜尋 API 回應異常: HTTP {s_resp.status_code}"}
            except Exception as e:
                log.warning(f"[SteamAPI] 搜尋遊戲失敗: {e}")
                return {"status": "ERROR", "error": f"Steam 搜尋請求失敗: {e}"}

        if not target_appid:
            return {"status": "NOT_FOUND", "message": "無法辨識有效的 Steam App ID"}

        # Step 2: Fetch App Details, Reviews, Current Players, and Historical Low concurrently
        appdetails_url = f"https://store.steampowered.com/api/appdetails?appids={target_appid}&cc={currency}&l=tchinese"
        reviews_url = f"https://store.steampowered.com/appreviews/{target_appid}?json=1&language=all&purchase_type=all"
        players_url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={target_appid}"

        async def fetch_appdetails() -> Optional[Dict[str, Any]]:
            try:
                r = await client.get(appdetails_url)
                if r.status_code == 200:
                    data = (r.json() or {}).get(str(target_appid)) or {}
                    if data.get("success"):
                        return data.get("data")
            except Exception as e:
                log.warning(f"[SteamAPI] 取得遊戲詳情失敗: {e}")
            return None

        async def fetch_reviews() -> Optional[Dict[str, Any]]:
            try:
                r = await client.get(reviews_url)
                if r.status_code == 200:
                    return (r.json() or {}).get("query_summary")
            except Exception as e:
                log.warning(f"[SteamAPI] 取得評論統計失敗: {e}")
            return None

        async def fetch_players() -> Optional[int]:
            try:
                r = await client.get(players_url)
                if r.status_code == 200:
                    res = (r.json() or {}).get("response") or {}
                    if res.get("result") == 1:
                        return res.get("player_count")
            except Exception as e:
                log.warning(f"[SteamAPI] 取得在線人數失敗: {e}")
            return None

        async def fetch_historical_low(title: str) -> Optional[Dict[str, Any]]:
            """Fetches all-time historical low price via CheapShark open API."""
            try:
                headers = {"User-Agent": "ZeroNexusBot/1.0 (internal-steam-query@zeronexus.net)"}
                cs_search_url = f"https://www.cheapshark.com/api/1.0/games?title={urllib.parse.quote_plus(title)}&limit=3"
                r = await client.get(cs_search_url, headers=headers)
                if r.status_code == 200:
                    games = r.json()
                    if isinstance(games, list) and games:
                        # Pick matching game or first
                        selected_game_id = games[0].get("gameID")
                        for g in games:
                            if str(g.get("steamAppID")) == str(target_appid):
                                selected_game_id = g.get("gameID")
                                break
                        if selected_game_id:
                            info_url = f"https://www.cheapshark.com/api/1.0/games?id={selected_game_id}"
                            r_info = await client.get(info_url, headers=headers)
                            if r_info.status_code == 200:
                                info_data = r_info.json()
                                cpe = info_data.get("cheapestPriceEver")
                                if cpe and cpe.get("price"):
                                    ts = cpe.get("date")
                                    date_str = ""
                                    if ts:
                                        date_str = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
                                    return {
                                        "lowest_price_usd": float(cpe["price"]),
                                        "date": date_str,
                                        "currency": "USD",
                                    }
            except Exception as e:
                log.debug(f"[SteamAPI] 查詢史低價格略過: {e}")
            return None

        # Execute concurrent calls
        app_data, reviews_data, player_count = await asyncio.gather(
            fetch_appdetails(),
            fetch_reviews(),
            fetch_players(),
        )

        title_for_history = matched_name or (app_data.get("name") if app_data else "")
        hist_low = await fetch_historical_low(title_for_history) if title_for_history else None

        if not app_data:
            return {
                "status": "PARTIAL_SUCCESS",
                "appid": target_appid,
                "name": matched_name or f"AppID {target_appid}",
                "message": "無法取得 Steam 商店完整詳情，可能為限制級內容或未於該地區上架",
                "current_players": player_count,
            }

        # Parse pricing
        price_overview = app_data.get("price_overview") or {}
        is_free = app_data.get("is_free", False)

        price_info = {
            "is_free": is_free,
            "currency": price_overview.get("currency", "TWD"),
            "initial_price": round(price_overview.get("initial", 0) / 100, 2) if price_overview.get("initial") else (0.0 if is_free else None),
            "final_price": round(price_overview.get("final", 0) / 100, 2) if price_overview.get("final") else (0.0 if is_free else None),
            "discount_percent": price_overview.get("discount_percent", 0),
            "formatted_initial": price_overview.get("initial_formatted", "免費" if is_free else "未提供"),
            "formatted_final": price_overview.get("final_formatted", "免費" if is_free else "未提供"),
            "is_on_sale": (price_overview.get("discount_percent", 0) > 0),
        }

        # Parse reviews
        reviews_summary = {}
        if reviews_data:
            total = reviews_data.get("total_reviews", 0)
            pos = reviews_data.get("total_positive", 0)
            neg = reviews_data.get("total_negative", 0)
            pct = round((pos / total * 100), 1) if total > 0 else 0.0
            reviews_summary = {
                "total_reviews": total,
                "total_positive": pos,
                "total_negative": neg,
                "positive_rate_percent": pct,
                "score_description": reviews_data.get("review_score_desc", "無評分"),
            }

        return {
            "status": "SUCCESS",
            "appid": target_appid,
            "name": app_data.get("name", matched_name),
            "price": price_info,
            "historical_low": hist_low or {"note": "目前暫無公開第三方史低紀錄"},
            "reviews": reviews_summary,
            "online_players": player_count if player_count is not None else "未提供",
            "developers": app_data.get("developers") or [],
            "publishers": app_data.get("publishers") or [],
            "genres": [g.get("description") for g in (app_data.get("genres") or []) if isinstance(g, dict) and g.get("description")],
            "release_date": (app_data.get("release_date") or {}).get("date", "未知") if isinstance(app_data.get("release_date"), dict) else "未知",
            "steam_store_url": f"https://store.steampowered.com/app/{target_appid}/",
        }

    # =========================================================================
    # 2. 🪙 加密貨幣即時行情
    # =========================================================================

    async def get_crypto_quote(
        self,
        symbol: str,
        vs_currency: str = "usd",
    ) -> Dict[str, Any]:
        """Queries real-time crypto price, 24h change %, volume via Binance & CoinGecko."""
        raw_sym = symbol.strip().upper()
        clean_vs = vs_currency.strip().lower()
        client = await self._get_client()

        mapped = CRYPTO_MAP.get(raw_sym)
        binance_pair = mapped[0] if mapped else f"{raw_sym}USDT"
        coingecko_id = mapped[1] if mapped else raw_sym.lower()
        display_name = mapped[2] if mapped else raw_sym

        # Primary: Binance Public 24hr Ticker
        binance_url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={binance_pair}"
        try:
            r = await client.get(binance_url)
            if r.status_code == 200:
                d = r.json()
                last_price = float(d.get("lastPrice", 0))
                change_pct = float(d.get("priceChangePercent", 0))
                high = float(d.get("highPrice", 0))
                low = float(d.get("lowPrice", 0))
                vol = float(d.get("volume", 0))
                quote_vol = float(d.get("quoteVolume", 0))

                res = {
                    "status": "SUCCESS",
                    "symbol": raw_sym,
                    "name": display_name,
                    "price": last_price,
                    "currency": "USDT",
                    "change_24h_percent": round(change_pct, 2),
                    "high_24h": high,
                    "low_24h": low,
                    "volume_24h": round(vol, 2),
                    "quote_volume_24h": round(quote_vol, 2),
                    "source": "Binance Public Market",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

                # If vs_currency is twd, also convert or augment with CoinGecko
                if clean_vs == "twd":
                    try:
                        cg_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=twd"
                        cg_r = await client.get(cg_url)
                        if cg_r.status_code == 200:
                            twd_val = (cg_r.json().get(coingecko_id) or {}).get("twd")
                            if twd_val:
                                res["price_twd"] = twd_val
                    except Exception:
                        pass

                return res
        except Exception as e:
            log.warning(f"[CryptoAPI] 幣安公開端點異常，嘗試 CoinGecko: {e}")

        # Secondary Failover: CoinGecko Public Endpoint
        cg_url = (
            f"https://api.coingecko.com/api/v3/simple/price?"
            f"ids={coingecko_id}&vs_currencies={clean_vs}&include_24hr_change=true&include_24hr_vol=true"
        )
        try:
            r_cg = await client.get(cg_url)
            if r_cg.status_code == 200:
                cg_data = (r_cg.json().get(coingecko_id) or {})
                if cg_data:
                    price = cg_data.get(clean_vs)
                    change = cg_data.get(f"{clean_vs}_24h_change")
                    vol = cg_data.get(f"{clean_vs}_24h_vol")
                    return {
                        "status": "SUCCESS",
                        "symbol": raw_sym,
                        "name": display_name,
                        "price": price,
                        "currency": clean_vs.upper(),
                        "change_24h_percent": round(change, 2) if change is not None else 0.0,
                        "volume_24h": round(vol, 2) if vol is not None else 0.0,
                        "source": "CoinGecko Public API",
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
            return {
                "status": "NOT_FOUND",
                "symbol": raw_sym,
                "message": f"無法取得加密貨幣「{raw_sym}」即時行情，請檢查代碼是否正確 (例如 BTC, ETH, SOL)",
            }
        except Exception as e:
            return {"status": "ERROR", "error": f"加密貨幣報價連線失敗: {e}"}

    # =========================================================================
    # 3. 💱 全球即時匯率換算
    # =========================================================================

    async def convert_exchange_rate(
        self,
        from_currency: str,
        to_currency: str,
        amount: float = 1.0,
    ) -> Dict[str, Any]:
        """Converts currency with precise exchange rates via Frankfurter & Open ER API."""
        base = from_currency.strip().upper()
        target = to_currency.strip().upper()
        amt = float(amount)
        client = await self._get_client()

        if base == target:
            return {
                "status": "SUCCESS",
                "from_currency": base,
                "to_currency": target,
                "amount": amt,
                "rate": 1.0,
                "converted_amount": amt,
                "source": "Identity",
                "date": datetime.date.today().isoformat(),
            }

        # Try Frankfurter first (ECB reference rates)
        frankfurter_success = False
        rate: Optional[float] = None
        rate_date = ""

        try:
            fk_url = f"https://api.frankfurter.dev/v1/latest?base={base}&symbols={target}"
            r = await client.get(fk_url)
            if r.status_code == 200:
                data = r.json()
                rates = data.get("rates", {})
                if target in rates:
                    rate = float(rates[target])
                    rate_date = data.get("date", "")
                    frankfurter_success = True
        except Exception as e:
            log.debug(f"[ExchangeRateAPI] Frankfurter 查詢略過: {e}")

        # Fallback to Open.er-api.com (Supports TWD, KRW, JPY, USD, EUR 160+ currencies)
        if not frankfurter_success or rate is None:
            try:
                er_url = f"https://open.er-api.com/v6/latest/{base}"
                r2 = await client.get(er_url)
                if r2.status_code == 200:
                    er_data = r2.json()
                    rates = er_data.get("rates", {})
                    if target in rates:
                        rate = float(rates[target])
                        rate_date = er_data.get("time_last_update_utc", "")[:10]
            except Exception as e:
                log.warning(f"[ExchangeRateAPI] Open.er-api 查詢失敗: {e}")

        if rate is not None:
            converted = round(amt * rate, 4)
            return {
                "status": "SUCCESS",
                "from_currency": base,
                "to_currency": target,
                "amount": amt,
                "rate": round(rate, 6),
                "converted_amount": converted,
                "date": rate_date or datetime.date.today().isoformat(),
                "source": "Frankfurter (ECB)" if frankfurter_success else "Open Exchange Rates Feed",
            }

        return {
            "status": "ERROR",
            "error": f"找不到從 {base} 到 {target} 的匯率資訊，請確認貨幣代碼是否正確 (例如 USD, TWD, JPY, EUR, KRW)",
        }

    # =========================================================================
    # 4. 🚆 大眾運輸即時動態與時刻表 (台鐵 TRA / 高鐵 THSR)
    # =========================================================================

    async def get_taiwan_transit_status(
        self,
        transit_type: str = "ALL",
        station: Optional[str] = None,
        train_no: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Queries Taiwan Railway (TRA) live board & delay, and High Speed Rail (THSR) status."""
        ttype = transit_type.strip().upper()
        target_station = station.strip() if station else None
        target_train = train_no.strip() if train_no else None
        client = await self._get_client()

        results: Dict[str, Any] = {
            "status": "SUCCESS",
            "query": {"transit_type": ttype, "station": target_station, "train_no": target_train},
        }

        # 1. Taiwan Railway (TRA) Live Board & Operation Status
        if ttype in ("ALL", "TRA"):
            tra_matched: List[Dict[str, Any]] = []
            tra_fetched = False

            # Attempt TDX endpoint
            tdx_tra_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/TRA/LiveBoard"
            try:
                tdx_headers = {"Accept": "application/json"}
                tdx_tok = await self._get_tdx_token()
                if tdx_tok:
                    tdx_headers["Authorization"] = f"Bearer {tdx_tok}"
                r_tra = await client.get(tdx_tra_url, headers=tdx_headers)
                if r_tra.status_code == 200:
                    tra_data = r_tra.json()
                    if isinstance(tra_data, list):
                        for item in tra_data:
                            if not isinstance(item, dict):
                                continue
                            st_name = (item.get("StationName") or {}).get("Zh_tw", "")
                            t_no = str(item.get("TrainNo", ""))
                            if target_station and target_station not in st_name:
                                continue
                            if target_train and target_train != t_no:
                                continue

                            delay_min = int(item.get("DelayTime", 0))
                            tra_matched.append({
                                "station": st_name,
                                "train_no": t_no,
                                "train_type": (item.get("TrainTypeName") or {}).get("Zh_tw", "一般列車"),
                                "destination": (item.get("EndingStationName") or {}).get("Zh_tw", ""),
                                "scheduled_departure": item.get("ScheduledDepartureTime", ""),
                                "scheduled_arrival": item.get("ScheduledArrivalTime", ""),
                                "delay_minutes": delay_min,
                                "status_text": "準點" if delay_min == 0 else f"誤點 {delay_min} 分鐘",
                            })
                            if len(tra_matched) >= 15:
                                break
                        tra_fetched = True
                        results["tra_trains"] = tra_matched
                        results["tra_summary"] = f"共查得 {len(tra_matched)} 班台鐵即時動態"
            except Exception as e:
                log.debug(f"[TransitAPI] TDX 台鐵動態查詢略過: {e}")

            # Fallback to TRA tip blockList if TDX unavailable
            if not tra_fetched:
                try:
                    r_alert = await client.get(
                        "https://tip.railway.gov.tw/tra-tip-web/tip/tip007/tip711/blockList",
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if r_alert.status_code == 200:
                        text = re.sub(r'<[^>]+>', ' ', r_alert.text)
                        if "列車延誤" in text or "事故" in text or "中斷" in text:
                            status_summary = "部分台鐵路段營運受阻或通報延誤，請以各站即時廣播及看板為準"
                        else:
                            status_summary = "台鐵全線營運正常運行 (準點)"
                        results["tra_summary"] = status_summary
                        results["tra_operation_status"] = status_summary
                except Exception as e_alert:
                    results["tra_summary"] = f"台鐵即時資訊更新中 ({e_alert})"

        # 2. Taiwan High Speed Rail (THSR) AlertInfo & Schedule
        if ttype in ("ALL", "THSR"):
            thsr_fetched = False
            tdx_alert_url = "https://tdx.transportdata.tw/api/basic/v2/Rail/THSR/AlertInfo"
            try:
                tdx_headers = {"Accept": "application/json"}
                tdx_tok = await self._get_tdx_token()
                if tdx_tok:
                    tdx_headers["Authorization"] = f"Bearer {tdx_tok}"
                r_thsr = await client.get(tdx_alert_url, headers=tdx_headers)
                if r_thsr.status_code == 200:
                    alerts = r_thsr.json()
                    alert_items = []
                    for a in alerts:
                        title = a.get("Title", "").strip()
                        status = a.get("Status", "").strip()
                        pub_time = a.get("PublishTime", "")
                        alert_items.append({
                            "title": title,
                            "status": status or "正常營運",
                            "publish_time": pub_time,
                        })
                    results["thsr_operational_status"] = alert_items
                    thsr_fetched = True
            except Exception as e:
                log.debug(f"[TransitAPI] TDX 高鐵營運資訊略過: {e}")

            if not thsr_fetched:
                results["thsr_operational_status"] = [{"title": "全線營運正常 (Normal)", "status": "正常營運"}]

            # Query today's timetable if station or train queried
            if target_station:
                thsr_code, _ = resolve_thsr_station(target_station)
                if thsr_code:
                    try:
                        today_str = datetime.date.today().strftime("%Y/%m/%d")
                        thsr_search_url = "https://www.thsrc.com.tw/TimeTable/Search"
                        headers = {
                            "User-Agent": "Mozilla/5.0",
                            "Referer": "https://www.thsrc.com.tw/",
                            "X-Requested-With": "XMLHttpRequest",
                        }
                        payload = {
                            "SearchType": "S",
                            "Lang": "TW",
                            "StartStation": thsr_code,
                            "EndStation": "TaiZhong" if thsr_code != "TaiZhong" else "TaiPei",
                            "OutWardSearchDate": today_str,
                            "OutWardSearchTime": "06:00",
                            "ReturnSearchDate": today_str,
                            "ReturnSearchTime": "06:00",
                            "DiscountType": "",
                        }
                        r_t = await client.post(thsr_search_url, data=payload, headers=headers)
                        if r_t.status_code == 200:
                            dep = r_t.json().get("data", {}).get("DepartureTable", {})
                            items = dep.get("TrainItem", [])
                            matched_items = []
                            for it in items[:10]:
                                matched_items.append({
                                    "train_no": it.get("TrainNumber"),
                                    "departure_time": it.get("DepartureTime"),
                                    "destination_time": it.get("DestinationTime"),
                                    "duration": it.get("Duration"),
                                })
                            results["thsr_timetable_matches"] = matched_items
                    except Exception as e_th:
                        log.debug(f"[TransitAPI] 高鐵站點時刻查詢略過: {e_th}")

        return results

    async def query_rail_timetable(
        self,
        origin: str,
        destination: str,
        rail_type: str = "all",
    ) -> Dict[str, Any]:
        """Queries Taiwan High Speed Rail (THSR) and Taiwan Railway (TRA) schedules, fares, and delays."""
        raw_orig = origin.strip()
        raw_dest = destination.strip()
        clean_type = rail_type.strip().lower()
        if clean_type not in ("all", "tra", "thsr"):
            clean_type = "all"

        if not raw_orig or not raw_dest:
            return {
                "status": "ERROR",
                "error": "請提供出發站 (origin) 與抵達站 (destination)，例如: 台北 到 台中",
            }

        client = await self._get_client()
        tz_tw = datetime.timezone(datetime.timedelta(hours=8))
        now_tw = datetime.datetime.now(tz_tw)
        today_slash = now_tw.strftime("%Y/%m/%d")
        today_iso = now_tw.date().isoformat()
        current_time_str = now_tw.strftime("%H:%M")
        is_early_morning = now_tw.hour < 6
        search_time = "06:00" if is_early_morning else f"{now_tw.hour:02d}:00"

        # Station Resolutions
        thsr_orig_code, thsr_orig_name = resolve_thsr_station(raw_orig)
        thsr_dest_code, thsr_dest_name = resolve_thsr_station(raw_dest)

        tra_orig_code, tra_orig_name = resolve_tra_station(raw_orig)
        tra_dest_code, tra_dest_name = resolve_tra_station(raw_dest)

        if not thsr_orig_code and not tra_orig_code:
            return {
                "status": "NOT_FOUND",
                "message": f"無法識別出發站「{raw_orig}」，請確認站名是否正確 (例如 台北, 板橋, 桃園, 台中, 台南, 高雄, 花蓮)",
            }
        if not thsr_dest_code and not tra_dest_code:
            return {
                "status": "NOT_FOUND",
                "message": f"無法識別抵達站「{raw_dest}」，請確認站名是否正確 (例如 台北, 板橋, 桃園, 台中, 台南, 高雄, 花蓮)",
            }

        results: Dict[str, Any] = {
            "status": "SUCCESS",
            "query": {
                "origin": raw_orig,
                "destination": raw_dest,
                "rail_type": clean_type.upper(),
                "date": today_iso,
                "current_time_taipei": current_time_str,
                "search_time": search_time,
                "is_early_morning": is_early_morning,
            },
            "thsr": None,
            "tra": None,
            "delay_and_line_status": {},
        }

        # ---------------------------------------------------------------------
        # 1. THSR Query (高鐵時刻表與票價)
        # ---------------------------------------------------------------------
        async def fetch_thsr_schedule() -> Optional[Dict[str, Any]]:
            if clean_type not in ("all", "thsr"):
                return None
            if not thsr_orig_code or not thsr_dest_code:
                return {
                    "available": False,
                    "reason": "高鐵未延伸至該區間站點 (高鐵僅營運台灣西部走廊: 南港至左營)",
                }

            thsr_url = "https://www.thsrc.com.tw/TimeTable/Search"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.thsrc.com.tw/ArticleContent/a3b630bb-1066-4352-a1ef-58c7b4e8ef7c",
                "Origin": "https://www.thsrc.com.tw",
                "X-Requested-With": "XMLHttpRequest",
            }
            payload = {
                "SearchType": "S",
                "Lang": "TW",
                "StartStation": thsr_orig_code,
                "EndStation": thsr_dest_code,
                "OutWardSearchDate": today_slash,
                "OutWardSearchTime": search_time,
                "ReturnSearchDate": today_slash,
                "ReturnSearchTime": search_time,
                "DiscountType": "",
            }
            try:
                r = await client.post(thsr_url, data=payload, headers=headers)
                if r.status_code == 200:
                    d = r.json()
                    dep_table = d.get("data", {}).get("DepartureTable", {})
                    train_items = dep_table.get("TrainItem", [])
                    price_table = d.get("data", {}).get("PriceTable", {})

                    formatted_trains = []
                    for item in train_items[:15]:
                        discounts = [disc.get("Name", "") for disc in item.get("Discount", []) if disc.get("Name")]
                        formatted_trains.append({
                            "train_no": item.get("TrainNumber"),
                            "departure_time": item.get("DepartureTime"),
                            "arrival_time": item.get("DestinationTime"),
                            "duration": item.get("Duration"),
                            "non_reserved_cars": f"第 {item.get('NonReservedCar')} 車廂" if item.get("NonReservedCar") else "無自由座",
                            "discounts": discounts if discounts else ["無額外優惠折扣"],
                            "status": "準點",
                        })

                    coach_price = price_table.get("Coach", ["-", "-"])[0] if price_table.get("Coach") else "請洽官網"
                    bus_price = price_table.get("Business", ["-", "-"])[0] if price_table.get("Business") else "請洽官網"
                    unres_price = price_table.get("Unreserved", ["-", "-"])[0] if price_table.get("Unreserved") else "請洽官網"

                    return {
                        "available": True,
                        "origin_station": thsr_orig_name,
                        "destination_station": thsr_dest_name,
                        "total_trains_count": len(train_items),
                        "trains_shown_count": len(formatted_trains),
                        "fares": {
                            "standard_coach": f"{coach_price} 元",
                            "business_coach": f"{bus_price} 元",
                            "unreserved_coach": f"{unres_price} 元",
                        },
                        "trains": formatted_trains,
                    }
            except Exception as e:
                log.warning(f"[RailAPI] 高鐵查詢異常: {e}")
            return {"available": False, "error": "高鐵線上時刻表伺服器暫時無回應"}

        # ---------------------------------------------------------------------
        # 2. TRA Query (台鐵時刻表與票價)
        # ---------------------------------------------------------------------
        async def fetch_tra_schedule() -> Optional[Dict[str, Any]]:
            if clean_type not in ("all", "tra"):
                return None
            if not tra_orig_code or not tra_dest_code:
                return {
                    "available": False,
                    "reason": "台鐵無此站名對應之直達區間",
                }

            home_url = "https://tip.railway.gov.tw/tra-tip-web/tip"
            query_url = "https://tip.railway.gov.tw/tra-tip-web/tip/tip001/tip112/querybytime"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

            try:
                r_home = await client.get(home_url, headers=headers)
                csrf_match = re.search(r'name=[\"\']_csrf[\"\'][^>]+value=[\"\']([^\"\']+)[\"\']', r_home.text)
                if not csrf_match:
                    return {"available": False, "error": "無法獲取台鐵防偽權杖 (_csrf)"}
                csrf = csrf_match.group(1)

                payload = {
                    "_csrf": csrf,
                    "startOrEndTime": "true",
                    "startStation": tra_orig_code,
                    "endStation": tra_dest_code,
                    "rideDate": today_slash,
                    "startTime": search_time,
                    "endTime": "23:59",
                    "trainTypeList": "ALL",
                    "transfer": "ONE",
                }

                r_post = await client.post(query_url, data=payload, headers=headers)
                if r_post.status_code == 200:
                    trip_rows = re.findall(r'<tr[^>]*class=[\"\']trip-column[\"\'][^>]*>(.*?)</tr>', r_post.text, re.DOTALL)
                    formatted_tra = []
                    for row in trip_rows[:15]:
                        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
                        if len(tds) >= 4:
                            td0 = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tds[0])).strip()
                            dep_time = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tds[1])).strip()
                            arr_time = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tds[2])).strip()
                            duration = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tds[3])).strip()
                            line_type = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tds[4])).strip() if len(tds) > 4 else "一般"
                            adult_fare = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tds[6])).strip() if len(tds) > 6 else ""

                            # Parse train type and number
                            m_tr = re.search(r'([^\d\s]+(?:\([^)]+\))?)\s+(\d+)\s*\(\s*([^→]+)→([^)]+)\)', td0)
                            if m_tr:
                                t_type = m_tr.group(1).strip()
                                t_no = m_tr.group(2).strip()
                                t_route = f"{m_tr.group(3).strip()} → {m_tr.group(4).strip()}"
                            else:
                                t_type = td0
                                t_no = "-"
                                t_route = ""

                            formatted_tra.append({
                                "train_no": t_no,
                                "train_type": t_type,
                                "route": t_route,
                                "departure_time": dep_time,
                                "arrival_time": arr_time,
                                "duration": duration,
                                "line_type": line_type,
                                "adult_fare": adult_fare or "依乘車里程計費",
                                "status": "準點",
                            })

                    return {
                        "available": True,
                        "origin_station": tra_orig_name,
                        "destination_station": tra_dest_name,
                        "total_trains_count": len(trip_rows),
                        "trains_shown_count": len(formatted_tra),
                        "trains": formatted_tra,
                    }
            except Exception as e:
                log.warning(f"[RailAPI] 台鐵查詢異常: {e}")
            return {"available": False, "error": "台鐵即時時刻表伺服器回應逾時"}

        # ---------------------------------------------------------------------
        # 3. Delays & Line Operation Status (全台鐵路營運與誤點概況)
        # ---------------------------------------------------------------------
        async def fetch_delays_and_alerts() -> Dict[str, Any]:
            delays_info = {"tra_status": "全線正常運行 (準點)", "thsr_status": "全線營運正常 (準點)"}
            # Check TRA blockList
            try:
                r_tra_alert = await client.get(
                    "https://tip.railway.gov.tw/tra-tip-web/tip/tip007/tip711/blockList",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if r_tra_alert.status_code == 200:
                    text = re.sub(r'<[^>]+>', ' ', r_tra_alert.text)
                    if "列車延誤" in text or "事故" in text or "中斷" in text:
                        delays_info["tra_status"] = "部分路段運行受阻或有誤點通報，詳情請依車站廣播與看板為準"
                    else:
                        delays_info["tra_status"] = "全線正常運行 (準點)"
            except Exception:
                pass

            # Check THSR alerts
            try:
                tdx_alert_headers = {"Accept": "application/json"}
                tdx_tok = await self._get_tdx_token()
                if tdx_tok:
                    tdx_alert_headers["Authorization"] = f"Bearer {tdx_tok}"
                r_thsr_alert = await client.get("https://tdx.transportdata.tw/api/basic/v2/Rail/THSR/AlertInfo", headers=tdx_alert_headers)
                if r_thsr_alert.status_code == 200:
                    a_data = r_thsr_alert.json()
                    if a_data and isinstance(a_data, list):
                        title = a_data[0].get("Title", "")
                        status = a_data[0].get("Status", "")
                        delays_info["thsr_status"] = f"{title} {status}".strip() or "全線營運正常 (準點)"
            except Exception:
                pass

            return delays_info

        # Execute concurrent tasks
        thsr_res, tra_res, delays_res = await asyncio.gather(
            fetch_thsr_schedule(),
            fetch_tra_schedule(),
            fetch_delays_and_alerts(),
        )

        results["thsr"] = thsr_res
        results["tra"] = tra_res
        results["delay_and_line_status"] = delays_res

        # Build human-readable summary
        summary_parts = []
        if thsr_res and thsr_res.get("available"):
            summary_parts.append(f"🚄 高鐵共查得 {thsr_res.get('total_trains_count', 0)} 班次（目前高鐵營運狀態: {delays_res.get('thsr_status')}）")
        elif thsr_res:
            summary_parts.append(f"🚄 高鐵: {thsr_res.get('reason', thsr_res.get('error', '未提供'))}")

        if tra_res and tra_res.get("available"):
            summary_parts.append(f"🚆 台鐵共查得 {tra_res.get('total_trains_count', 0)} 班次（目前台鐵運行狀態: {delays_res.get('tra_status')}）")
        elif tra_res:
            summary_parts.append(f"🚆 台鐵: {tra_res.get('reason', tra_res.get('error', '未提供'))}")

        results["summary"] = "；".join(summary_parts) if summary_parts else "未查得符合條件之列車班次"
        return results

    # =========================================================================
    # 5. ⛩️ MyAnimeList / Jikan 動漫資料庫 (具備 AniList 容錯備援)
    # =========================================================================

    async def get_anime_info(
        self,
        query: Optional[str] = None,
        seasonal: bool = False,
        season: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Queries anime schedule, scores, synopsis, characters and voice actors."""
        client = await self._get_client()

        # Strategy A: Seasonal anime query
        if seasonal:
            # Try Jikan v4 seasons endpoint
            if year and season:
                jikan_url = f"https://api.jikan.moe/v4/seasons/{year}/{season.lower()}?limit={limit}"
            else:
                jikan_url = f"https://api.jikan.moe/v4/seasons/now?limit={limit}"

            try:
                r = await client.get(jikan_url)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    anime_list = []
                    for item in data[:limit]:
                        anime_list.append({
                            "id": item.get("mal_id"),
                            "title": item.get("title"),
                            "title_japanese": item.get("title_japanese"),
                            "score": item.get("score"),
                            "episodes": item.get("episodes"),
                            "genres": [g.get("name") for g in item.get("genres", [])],
                            "synopsis": (item.get("synopsis") or "")[:200] + ("..." if item.get("synopsis") and len(item["synopsis"]) > 200 else ""),
                            "season": item.get("season"),
                            "year": item.get("year"),
                        })
                    return {
                        "status": "SUCCESS",
                        "type": "seasonal",
                        "count": len(anime_list),
                        "anime": anime_list,
                        "source": "MyAnimeList (Jikan v4)",
                    }
            except Exception as e:
                log.warning(f"[AnimeAPI] Jikan 季度新番失敗，切換 AniList: {e}")

            # AniList GraphQL Seasonal Failover
            anilist_seasonal_query = """
            query ($page: Int, $perPage: Int) {
              Page (page: $page, perPage: $perPage) {
                media (type: ANIME, sort: POPULARITY_DESC, status: RELEASING) {
                  id
                  title { romaji english native }
                  averageScore
                  episodes
                  genres
                  description
                }
              }
            }
            """
            try:
                r_al = await client.post(
                    "https://graphql.anilist.co",
                    json={"query": anilist_seasonal_query, "variables": {"page": 1, "perPage": limit}},
                )
                if r_al.status_code == 200:
                    media_list = (((r_al.json() or {}).get("data") or {}).get("Page") or {}).get("media") or []
                    anime_list = []
                    for m in media_list:
                        if not isinstance(m, dict):
                            continue
                        desc = html.unescape(re.sub(r"<[^>]+>", "", m.get("description") or ""))
                        m_title = m.get("title") or {}
                        anime_list.append({
                            "id": m.get("id"),
                            "title": m_title.get("native") or m_title.get("romaji") or "未知",
                            "title_english": m_title.get("english"),
                            "score": round(m.get("averageScore", 0) / 10.0, 1) if m.get("averageScore") else None,
                            "episodes": m.get("episodes"),
                            "genres": m.get("genres") or [],
                            "synopsis": desc[:200] + ("..." if len(desc) > 200 else ""),
                        })
                    return {
                        "status": "SUCCESS",
                        "type": "seasonal",
                        "count": len(anime_list),
                        "anime": anime_list,
                        "source": "AniList GraphQL Feed (Failover)",
                    }
            except Exception as e:
                return {"status": "ERROR", "error": f"新番日程查詢失敗: {e}"}

        # Strategy B: Anime search by keyword
        if not query or not query.strip():
            return {"status": "ERROR", "error": "請提供欲查詢的動漫名稱 (query)"}

        search_term = query.strip()

        # Try Jikan v4 Search
        jikan_search_url = f"https://api.jikan.moe/v4/anime?q={urllib.parse.quote_plus(search_term)}&limit={limit}"
        try:
            r = await client.get(jikan_search_url)
            if r.status_code == 200:
                data = (r.json() or {}).get("data") or []
                if data and isinstance(data, list) and isinstance(data[0], dict):
                    item = data[0]
                    mal_id = item.get("mal_id")

                    # Fetch characters & voice actors
                    va_list = []
                    try:
                        char_url = f"https://api.jikan.moe/v4/anime/{mal_id}/characters"
                        r_char = await client.get(char_url)
                        if r_char.status_code == 200:
                            chars_data = (r_char.json() or {}).get("data") or []
                            for c in chars_data[:6]:
                                if not isinstance(c, dict):
                                    continue
                                c_name = (c.get("character") or {}).get("name", "")
                                role = c.get("role", "")
                                vas = [
                                    (v.get("person") or {}).get("name", "")
                                    for v in (c.get("voice_actors") or [])
                                    if isinstance(v, dict) and v.get("language") == "Japanese"
                                ]
                                va_list.append({
                                    "character": c_name,
                                    "role": role,
                                    "voice_actor": vas[0] if vas and vas[0] else "未標記",
                                })
                    except Exception:
                        pass

                    return {
                        "status": "SUCCESS",
                        "id": mal_id,
                        "title": item.get("title"),
                        "title_japanese": item.get("title_japanese"),
                        "score": item.get("score"),
                        "status_text": item.get("status"),
                        "episodes": item.get("episodes"),
                        "aired": item.get("aired", {}).get("string"),
                        "genres": [g.get("name") for g in item.get("genres", [])],
                        "synopsis": item.get("synopsis"),
                        "characters_and_voice_actors": va_list,
                        "mal_url": item.get("url"),
                        "source": "MyAnimeList (Jikan v4)",
                    }
        except Exception as e:
            log.warning(f"[AnimeAPI] Jikan 作品查詢異常，啟動 AniList 備援: {e}")

        # AniList Failover for Search
        anilist_search_query = """
        query ($search: String) {
          Media (search: $search, type: ANIME) {
            id
            title { romaji english native }
            averageScore
            status
            episodes
            genres
            description
            siteUrl
            characters (sort: ROLE, perPage: 6) {
              edges {
                role
                node { name { full native } }
                voiceActors (language: JAPANESE) { name { full native } }
              }
            }
          }
        }
        """
        try:
            r_al = await client.post(
                "https://graphql.anilist.co",
                json={"query": anilist_search_query, "variables": {"search": search_term}},
            )
            if r_al.status_code == 200:
                media = r_al.json().get("data", {}).get("Media")
                if media:
                    desc = html.unescape(re.sub(r"<[^>]+>", "", media.get("description") or ""))
                    va_list = []
                    edges = media.get("characters", {}).get("edges", [])
                    for edge in edges:
                        char_node = edge.get("node", {}).get("name", {})
                        c_name = char_node.get("native") or char_node.get("full")
                        vas = edge.get("voiceActors", [])
                        va_name = vas[0].get("name", {}).get("native") or vas[0].get("name", {}).get("full") if vas else "未標記"
                        va_list.append({
                            "character": c_name,
                            "role": edge.get("role"),
                            "voice_actor": va_name,
                        })

                    return {
                        "status": "SUCCESS",
                        "id": media.get("id"),
                        "title": media.get("title", {}).get("native") or media.get("title", {}).get("romaji"),
                        "title_english": media.get("title", {}).get("english"),
                        "score": round(media.get("averageScore", 0) / 10.0, 1) if media.get("averageScore") else None,
                        "status_text": media.get("status"),
                        "episodes": media.get("episodes"),
                        "genres": media.get("genres", []),
                        "synopsis": desc,
                        "characters_and_voice_actors": va_list,
                        "anilist_url": media.get("siteUrl"),
                        "source": "AniList GraphQL Engine (Failover)",
                    }
            return {"status": "NOT_FOUND", "message": f"在動漫資料庫中查無與「{search_term}」相關之作品"}
        except Exception as e:
            return {"status": "ERROR", "error": f"動漫資料查詢失敗: {e}"}

    # =========================================================================
    # 6. 🐙 GitHub REST API
    # =========================================================================

    async def get_github_repo_info(self, repo: str) -> Dict[str, Any]:
        """Queries repository stars, latest release, issues, author via GitHub REST API."""
        clean_repo = repo.strip()
        client = await self._get_client()

        # Parse owner/repo from URL or string
        m = re.search(r"github\.com/([^/]+)/([^/#?]+)", clean_repo)
        if m:
            owner, repo_name = m.group(1), m.group(2)
        elif "/" in clean_repo:
            parts = clean_repo.split("/")
            owner, repo_name = parts[0].strip(), parts[1].strip()
        else:
            return {
                "status": "ERROR",
                "error": "請提供正確的 GitHub 儲存庫名稱格式 (例如: tiangolo/fastapi 或完整網址)",
            }

        repo_name = repo_name.removesuffix(".git")
        api_base = f"https://api.github.com/repos/{owner}/{repo_name}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ZeroNexusBot/1.0 (internal-github-query@zeronexus.net)",
        }

        try:
            r = await client.get(api_base, headers=headers)
            if r.status_code == 404:
                return {"status": "NOT_FOUND", "message": f"找不到開源儲存庫: {owner}/{repo_name}"}
            if r.status_code != 200:
                return {"status": "ERROR", "error": f"GitHub API 回應異常: HTTP {r.status_code}"}

            data = r.json()

            # Query Latest Release
            latest_release = None
            try:
                r_rel = await client.get(f"{api_base}/releases/latest", headers=headers)
                if r_rel.status_code == 200:
                    rel = r_rel.json()
                    latest_release = {
                        "tag": rel.get("tag_name"),
                        "name": rel.get("name"),
                        "published_at": rel.get("published_at"),
                        "html_url": rel.get("html_url"),
                    }
            except Exception:
                pass

            license_info = data.get("license") or {}

            return {
                "status": "SUCCESS",
                "full_name": data.get("full_name"),
                "owner": (data.get("owner") or {}).get("login", "未知"),
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "open_issues": data.get("open_issues_count", 0),
                "description": data.get("description", "無描述"),
                "language": data.get("language", "未註記"),
                "license": license_info.get("spdx_id") or license_info.get("name") or "無授權標籤",
                "topics": data.get("topics", []),
                "html_url": data.get("html_url"),
                "latest_release": latest_release or {"tag": "無正式發布版本 (No Releases)"},
                "updated_at": data.get("updated_at"),
            }
        except Exception as e:
            return {"status": "ERROR", "error": f"GitHub 查詢失敗: {e}"}

    # =========================================================================
    # 7. 📚 維基百科 / Wikidata API
    # =========================================================================

    async def get_wiki_definition(self, term: str, lang: str = "zh") -> Dict[str, Any]:
        """Fetches standard encyclopedia definition, historical events, and Wikidata entity."""
        clean_term = term.strip()
        if not clean_term:
            return {"status": "ERROR", "error": "請提供欲查詢的詞彙或專有名詞 (term)"}

        client = await self._get_client()
        lang_code = lang.strip().lower()

        # Step 1: Wikipedia REST API Summary
        quoted = urllib.parse.quote(clean_term)
        wiki_url = f"https://{lang_code}.wikipedia.org/api/rest_v1/page/summary/{quoted}"
        headers = {"User-Agent": "ZeroNexusBot/1.0 (internal-wiki-query@zeronexus.net)"}

        wiki_res: Optional[Dict[str, Any]] = None
        try:
            r = await client.get(wiki_url, headers=headers)
            if r.status_code == 200:
                d = r.json()
                if d.get("extract"):
                    wiki_res = {
                        "title": d.get("title"),
                        "description": d.get("description"),
                        "extract": d.get("extract"),
                        "page_url": d.get("content_urls", {}).get("desktop", {}).get("page"),
                        "thumbnail": d.get("thumbnail", {}).get("source"),
                    }
        except Exception as e:
            log.warning(f"[WikiAPI] Wikipedia summary 異常: {e}")

        # Step 2: Wikidata Entity Search
        wd_url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={quoted}&language={lang_code}&format=json"
        wd_res: Optional[Dict[str, Any]] = None
        try:
            r_wd = await client.get(wd_url, headers=headers)
            if r_wd.status_code == 200:
                entities = r_wd.json().get("search", [])
                if entities:
                    first = entities[0]
                    wd_res = {
                        "id": first.get("id"),
                        "label": first.get("label"),
                        "description": first.get("description"),
                        "url": first.get("concepturi"),
                    }
        except Exception as e:
            log.warning(f"[WikiAPI] Wikidata 查詢異常: {e}")

        if wiki_res:
            return {
                "status": "SUCCESS",
                "term": clean_term,
                "title": wiki_res["title"],
                "definition": wiki_res["extract"],
                "short_description": wiki_res["description"] or (wd_res.get("description") if wd_res else "百科辭典標準條目"),
                "wikipedia_url": wiki_res["page_url"],
                "wikidata": wd_res,
                "source": f"Wikipedia ({lang_code.upper()}) & Wikidata",
            }

        if wd_res:
            return {
                "status": "SUCCESS",
                "term": clean_term,
                "title": wd_res["label"],
                "definition": wd_res["description"] or "Wikidata 權威實體定義",
                "wikidata_id": wd_res["id"],
                "wikidata_url": wd_res["url"],
                "source": "Wikidata Open Knowledge Base",
            }

        return {
            "status": "NOT_FOUND",
            "term": clean_term,
            "message": f"在維基百科與 Wikidata 中未查得「{clean_term}」之定義",
        }

    # =========================================================================
    # 8. 🌫️ 環境部 AQI 空氣品質與紫外線即時指數
    # =========================================================================

    async def get_air_quality_and_uv(self, location: str = "台北") -> Dict[str, Any]:
        """Queries AQI, PM2.5, PM10 and UV Index via MoENV or Open-Meteo Air Quality."""
        loc = location.strip()
        client = await self._get_client()

        # Check coordinates mapping
        coords = None
        matched_loc_name = loc
        for name, coord in TAIWAN_COORDINATES.items():
            if name in loc:
                coords = coord
                matched_loc_name = name
                break

        if not coords:
            # Default to Taipei if not matched
            coords = TAIWAN_COORDINATES["台北"]
            matched_loc_name = f"{loc} (參照台北中心坐標)"

        lat, lon = coords

        # Helper rating functions
        def get_aqi_category(aqi_val: float) -> Tuple[str, str]:
            if aqi_val <= 50:
                return "良好 (Good)", "空氣品質令人滿意，基本無空氣污染，可正常從事戶外活動。"
            elif aqi_val <= 100:
                return "普通 (Moderate)", "空氣品質尚可，極敏感族群若感到不適應減少劇烈體能活動。"
            elif aqi_val <= 150:
                return "對敏感族群不健康 (Unhealthy for Sensitive Groups)", "心血管、呼吸道疾病患者、老人與幼童應減少長時間劇烈活動。"
            elif aqi_val <= 200:
                return "對所有族群不健康 (Unhealthy)", "所有人可能開始產生不適症狀，建議配戴口罩，減少長時間戶外劇烈運動。"
            elif aqi_val <= 300:
                return "非常不健康 (Very Unhealthy)", "健康威脅警報，所有人應避免戶外劇烈活動。"
            return "危害 (Hazardous)", "嚴重危害警告，所有民眾應盡可能留在室內並關閉門窗。"

        def get_uv_category(uv_val: float) -> Tuple[str, str]:
            if uv_val <= 2:
                return "低量級 (0-2)", "曝曬危險程度低，可安心進行戶外活動。"
            elif uv_val <= 5:
                return "中量級 (3-5)", "建議外出配戴帽子或太陽眼鏡，並適度防曬。"
            elif uv_val <= 7:
                return "高量級 (6-7)", "紫外線偏強，外出建議塗抹防曬乳、撐陽傘，中午前後盡量處於陰涼處。"
            elif uv_val <= 10:
                return "過量級 (8-10)", "曝曬危險程度高，20分鐘內可能曬傷，中午10點至下午2點請盡量避免外出。"
            return "危險級 (11+)", "極度危險，15分鐘內即可曬傷，請務必全副防曬武裝或待在室內。"

        # Check if user has MoENV API Key configured
        moenv_key = os.getenv("MOENV_API_KEY", "").strip() or os.getenv("EPA_API_KEY", "").strip()
        if moenv_key:
            try:
                moenv_url = f"https://data.moenv.gov.tw/api/v2/aqx_p_432?api_key={moenv_key}&format=json&limit=50"
                r_moenv = await client.get(moenv_url)
                if r_moenv.status_code == 200:
                    records = r_moenv.json().get("records", [])
                    loc_norm = loc.replace("臺", "台")
                    matched_norm = matched_loc_name.replace("臺", "台")
                    for rec in records:
                        sitename = rec.get("sitename", "")
                        county = rec.get("county", "")
                        s_norm = sitename.replace("臺", "台")
                        c_norm = county.replace("臺", "台")
                        if (
                            loc in sitename
                            or loc in county
                            or loc_norm in s_norm
                            or loc_norm in c_norm
                            or matched_norm in c_norm
                        ):
                            aqi = float(rec.get("aqi", 0))
                            pm25 = float(rec.get("pm2.5", 0))
                            pm10 = float(rec.get("pm10", 0))
                            status_label, health_advice = get_aqi_category(aqi)
                            return {
                                "status": "SUCCESS",
                                "location": f"{county} {sitename}",
                                "aqi": aqi,
                                "aqi_category": status_label,
                                "health_advice": health_advice,
                                "pm2_5": pm25,
                                "pm10": pm10,
                                "status_desc": rec.get("status", "正常"),
                                "source": "環境部國家空氣品質監測網 (MoENV Official API)",
                                "published_time": rec.get("publishtime"),
                            }
            except Exception as e:
                log.warning(f"[AirQualityAPI] MoENV API 調用異常，降級至 Open-Meteo: {e}")

        # Open-Meteo Air Quality & UV Index (Zero-key, real-time, global/TW accuracy)
        try:
            om_url = (
                f"https://air-quality-api.open-meteo.com/v1/air-quality?"
                f"latitude={lat}&longitude={lon}&current=us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,uv_index"
            )
            r_om = await client.get(om_url)
            if r_om.status_code == 200:
                current = (r_om.json() or {}).get("current") or {}
                aqi = float(current.get("us_aqi", 0))
                pm25 = float(current.get("pm2_5", 0))
                pm10 = float(current.get("pm10", 0))
                uv = float(current.get("uv_index", 0))

                aqi_cat, advice = get_aqi_category(aqi)
                uv_cat, uv_advice = get_uv_category(uv)

                return {
                    "status": "SUCCESS",
                    "location": matched_loc_name,
                    "latitude": lat,
                    "longitude": lon,
                    "aqi": aqi,
                    "aqi_category": aqi_cat,
                    "health_advice": advice,
                    "pm2_5": pm25,
                    "pm10": pm10,
                    "uv_index": uv,
                    "uv_category": uv_cat,
                    "uv_advice": uv_advice,
                    "pollutants": {
                        "ozone": current.get("ozone"),
                        "nitrogen_dioxide": current.get("nitrogen_dioxide"),
                        "carbon_monoxide": current.get("carbon_monoxide"),
                    },
                    "source": "Open-Meteo High-Resolution Air Quality & UV Model",
                    "measured_time": current.get("time"),
                }
            return {"status": "ERROR", "error": f"空氣品質伺服器回應異常: HTTP {r_om.status_code}"}
        except Exception as e:
            return {"status": "ERROR", "error": f"空氣品質與紫外線查詢失敗: {e}"}

    # =========================================================================
    # 9. 🔍 Google Custom Search JSON API 轉發接口 (具備 WebClient 備援)
    # =========================================================================

    async def search_google_custom(
        self,
        query: str,
        num_results: int = 5,
    ) -> Dict[str, Any]:
        """Forwards search to Google Custom Search JSON API when configured, else WebClient."""
        clean_q = query.strip()
        if not clean_q:
            return {"status": "INVALID_INPUT", "results": [], "error": "搜尋關鍵字不可為空"}

        google_key = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
        google_cx = os.getenv("GOOGLE_SEARCH_CX", "").strip() or os.getenv("GOOGLE_CSE_ID", "").strip()

        client = await self._get_client()

        # Primary: Official Google Custom Search JSON API if keys present
        if google_key and google_cx:
            try:
                cse_url = (
                    f"https://www.googleapis.com/customsearch/v1?"
                    f"key={google_key}&cx={google_cx}&q={urllib.parse.quote_plus(clean_q)}&num={max(1, min(num_results, 10))}"
                )
                r = await client.get(cse_url)
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("items", [])
                    results = []
                    for item in items:
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "snippet": item.get("snippet", ""),
                        })
                    return {
                        "status": "SUCCESS",
                        "engine": "google_custom_search_api",
                        "query": clean_q,
                        "results": results,
                        "total_results": len(results),
                    }
                else:
                    log.warning(f"[GoogleCSE] Google API 回應異常 HTTP {r.status_code}，切換內建 WebClient")
            except Exception as e:
                log.warning(f"[GoogleCSE] Google API 連線失敗，切換內建 WebClient: {e}")

        # Fallback: ZeroNexus Built-in Multi-Engine WebClient
        from zeronexus.engines.web_client import web_client
        res = await web_client.search(clean_q, num_results=num_results)
        return {
            "status": res.get("status", "SUCCESS"),
            "engine": res.get("engine", "web_client_fallback"),
            "query": clean_q,
            "results": res.get("results", []),
            "total_results": len(res.get("results", [])),
            "error_message": res.get("error_message"),
        }

    # =========================================================================
    # 10. 📈 台股 / 美股即時報價 (Stock Market Real-Time Quotes)
    # =========================================================================

    async def get_stock_quote(self, symbol: str) -> Dict[str, Any]:
        """Queries real-time stock quote for Taiwan (TWSE/TPEx) and US stocks via Yahoo Finance & TWSE."""
        raw_sym = symbol.strip()
        if not raw_sym:
            return {"status": "ERROR", "error": "請提供欲查詢之股票代碼或代號 (例如 2330, 2330.TW, 0050.TW, AAPL, NVDA, TSLA)"}

        client = await self._get_client()
        clean_upper = raw_sym.upper()

        # Determine if pure Taiwan stock code (digits only, e.g. 2330, 0050)
        is_tw_code = bool(re.match(r"^\d{4,6}$", clean_upper))
        candidate_tickers = []
        if is_tw_code:
            candidate_tickers = [f"{clean_upper}.TW", f"{clean_upper}.TWO"]
        else:
            candidate_tickers = [clean_upper]

        for ticker in candidate_tickers:
            yf_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                r = await client.get(yf_url, headers=headers)
                if r.status_code == 200:
                    data = r.json() or {}
                    chart_obj = data.get("chart") or {}
                    results = chart_obj.get("result")
                    if results and isinstance(results, list) and len(results) > 0 and isinstance(results[0], dict):
                        meta = results[0].get("meta") or {}
                        price = meta.get("regularMarketPrice")
                        if price is not None:
                            prev_close = meta.get("chartPreviousClose") or meta.get("previousClose") or price
                            change = round(price - prev_close, 2) if prev_close else 0.0
                            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
                            high = meta.get("regularMarketDayHigh")
                            low = meta.get("regularMarketDayLow")
                            vol = meta.get("regularMarketVolume")
                            currency = meta.get("currency", "USD")
                            name = meta.get("shortName") or meta.get("longName") or ticker
                            exchange = meta.get("exchangeName", "")

                            return {
                                "status": "SUCCESS",
                                "symbol": clean_upper,
                                "ticker": ticker,
                                "name": name,
                                "price": round(float(price), 2),
                                "change": change,
                                "change_percent": change_pct,
                                "high": round(float(high), 2) if high is not None else None,
                                "low": round(float(low), 2) if low is not None else None,
                                "volume": vol,
                                "currency": currency,
                                "exchange": exchange,
                                "source": "Yahoo Finance Real-Time Quote",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            }
            except Exception as e:
                log.debug(f"[StockAPI] Yahoo Finance 查詢 {ticker} 異常: {e}")

        # Fallback for Taiwan stocks via TWSE Open Endpoint
        if is_tw_code or clean_upper.endswith(".TW") or clean_upper.endswith(".TWO"):
            code = clean_upper.split(".")[0]
            for prefix in ("tse", "otc"):
                twse_url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={prefix}_{code}.tw&json=1&delay=0"
                try:
                    r_twse = await client.get(twse_url, headers={"User-Agent": "Mozilla/5.0"})
                    if r_twse.status_code == 200:
                        d_twse = r_twse.json() or {}
                        msg_arr = d_twse.get("msgArray") or []
                        if msg_arr and isinstance(msg_arr, list) and isinstance(msg_arr[0], dict):
                            item = msg_arr[0]
                            raw_z = item.get("z", "-")
                            raw_y = item.get("y", "-")
                            raw_h = item.get("h", "-")
                            raw_l = item.get("l", "-")
                            raw_v = item.get("v", "0")
                            name = item.get("n", code)

                            price_val = float(raw_z) if raw_z != "-" else (float(raw_y) if raw_y != "-" else 0.0)
                            prev_val = float(raw_y) if raw_y != "-" else price_val
                            change = round(price_val - prev_val, 2) if prev_val else 0.0
                            change_pct = round((change / prev_val) * 100, 2) if prev_val else 0.0

                            return {
                                "status": "SUCCESS",
                                "symbol": clean_upper,
                                "ticker": f"{code}.TW" if prefix == "tse" else f"{code}.TWO",
                                "name": name,
                                "price": price_val,
                                "change": change,
                                "change_percent": change_pct,
                                "high": float(raw_h) if raw_h != "-" else None,
                                "low": float(raw_l) if raw_l != "-" else None,
                                "volume": int(raw_v) if raw_v.isdigit() else 0,
                                "currency": "TWD",
                                "exchange": "TWSE" if prefix == "tse" else "TPEx",
                                "source": "TWSE / TPEx Open Data Endpoint",
                                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            }
                except Exception as e:
                    log.debug(f"[StockAPI] TWSE API 查詢 {code} 略過: {e}")

        return {
            "status": "NOT_FOUND",
            "symbol": clean_upper,
            "message": f"查無代碼「{clean_upper}」之股市即時報價，請確認代碼是否正確 (例如 2330, 0050.TW, AAPL, NVDA)",
        }

    # =========================================================================
    # 11. 🌐 IP 歸屬地與網路資訊 (IP Geolocation & ASN Query)
    # =========================================================================

    async def get_ip_geo_info(self, ip: str) -> Dict[str, Any]:
        """Queries IP geographical location, ISP, and ASN network info using ip-api.com."""
        clean_ip = ip.strip()
        if not clean_ip:
            return {"status": "ERROR", "error": "請提供欲查詢之 IP 位址 (例如 8.8.8.8 或 1.1.1.1)"}

        # SSRF & Private IP check
        from zeronexus.security.ssrf import is_ip_blocked, parse_loose_ip
        parsed_ip = parse_loose_ip(clean_ip)
        if parsed_ip is not None:
            blocked, reason = is_ip_blocked(parsed_ip)
            if blocked:
                return {
                    "status": "FAIL",
                    "ip": clean_ip,
                    "message": f"查詢失敗：此 IP 為{reason} (reserved range)，無公網地理位置資訊",
                }

        client = await self._get_client()
        url = (
            f"http://ip-api.com/json/{urllib.parse.quote(clean_ip)}?"
            f"fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
        )

        try:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    return {
                        "status": "SUCCESS",
                        "ip": data.get("query", clean_ip),
                        "country": data.get("country", "未知"),
                        "country_code": data.get("countryCode", ""),
                        "region": data.get("regionName", ""),
                        "city": data.get("city", "未知"),
                        "zip_code": data.get("zip", ""),
                        "latitude": data.get("lat"),
                        "longitude": data.get("lon"),
                        "timezone": data.get("timezone", ""),
                        "isp": data.get("isp", "未知"),
                        "organization": data.get("org", ""),
                        "asn": data.get("as", ""),
                        "source": "ip-api.com",
                    }
                else:
                    return {
                        "status": "FAIL",
                        "ip": clean_ip,
                        "message": data.get("message", "查詢失敗，可能為私有 IP、保留位址或無效格式"),
                    }
            return {"status": "ERROR", "error": f"ip-api.com 伺服器回應異常: HTTP {r.status_code}"}
        except Exception as e:
            return {"status": "ERROR", "error": f"IP 地理資訊查詢失敗: {e}"}

    # =========================================================================
    # 12. 🔒 SSL 憑證與網站健全度檢查 (SSL Certificate & Health Probe)
    # =========================================================================

    async def check_website_ssl(self, host: str, port: int = 443) -> Dict[str, Any]:
        """Probes website SSL certificate expiration date, issuer, TLS version, and latency using ssl and socket."""
        raw_host = host.strip()
        if not raw_host:
            return {"status": "ERROR", "error": "請提供欲檢測之網站主機名稱或網址 (host)"}

        # Parse host and port if URL passed
        if "://" in raw_host:
            parsed = urllib.parse.urlparse(raw_host)
            clean_host = parsed.hostname or raw_host
            target_port = parsed.port or port
        elif ":" in raw_host and not raw_host.startswith("["):
            parts = raw_host.split(":")
            clean_host = parts[0].strip()
            try:
                target_port = int(parts[1].strip())
            except ValueError:
                target_port = port
        else:
            clean_host = raw_host.strip().strip("/")
            target_port = port

        # SSRF Defense Validation & DNS Pinning against DNS Rebinding attacks
        from zeronexus.security.ssrf import validate_safe_host
        is_safe, ssrf_err, resolved_ip = validate_safe_host(clean_host)
        if not is_safe:
            return {
                "status": "REJECTED",
                "host": clean_host,
                "error": f"安全防護阻斷：禁止檢測受限或內部主機 ({ssrf_err})",
            }

        connect_ip = resolved_ip or clean_host

        def _probe_ssl(target_host: str, target_ip: str, target_p: int) -> Dict[str, Any]:
            t0 = time.perf_counter()
            ctx = ssl.create_default_context()
            # Pin connection to pre-validated resolved_ip to prevent DNS rebinding attacks
            with socket.create_connection((target_ip, target_p), timeout=6.0) as sock:
                with ctx.wrap_socket(sock, server_hostname=target_host) as ssock:
                    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                    cert = ssock.getpeercert()
                    tls_ver = ssock.version()
                    cipher_info = ssock.cipher()

            not_after_str = cert.get("notAfter", "")
            not_before_str = cert.get("notBefore", "")

            exp_ts = ssl.cert_time_to_seconds(not_after_str)
            exp_dt = datetime.datetime.fromtimestamp(exp_ts, tz=datetime.timezone.utc)
            issued_ts = ssl.cert_time_to_seconds(not_before_str)
            issued_dt = datetime.datetime.fromtimestamp(issued_ts, tz=datetime.timezone.utc)

            remaining_seconds = exp_ts - time.time()
            remaining_days = round(remaining_seconds / 86400, 1)
            is_expired = remaining_days <= 0

            # Extract issuer details
            issuer_dict: Dict[str, str] = {}
            for item in cert.get("issuer", ()):
                for k, v in item:
                    issuer_dict[k] = v

            # Extract subject details
            subject_dict: Dict[str, str] = {}
            for item in cert.get("subject", ()):
                for k, v in item:
                    subject_dict[k] = v

            # Subject Alternative Names
            san = [val for key, val in cert.get("subjectAltName", ()) if key == "DNS"]

            health = "HEALTHY"
            if is_expired:
                health = "EXPIRED"
            elif remaining_days <= 30:
                health = "EXPIRING_SOON"

            return {
                "status": "SUCCESS",
                "host": target_host,
                "port": target_p,
                "health": health,
                "is_valid": not is_expired,
                "remaining_days": remaining_days,
                "expires_at": exp_dt.isoformat(),
                "issued_at": issued_dt.isoformat(),
                "issuer": {
                    "common_name": issuer_dict.get("commonName", "未知"),
                    "organization": issuer_dict.get("organizationName", "未知"),
                    "country": issuer_dict.get("countryName", ""),
                },
                "subject": {
                    "common_name": subject_dict.get("commonName", target_host),
                },
                "tls_version": tls_ver or "Unknown",
                "cipher": cipher_info[0] if cipher_info else "Unknown",
                "handshake_latency_ms": latency_ms,
                "subject_alt_names": san[:10],
            }

        try:
            return await asyncio.to_thread(_probe_ssl, clean_host, connect_ip, target_port)
        except ssl.SSLCertVerificationError as ve:
            return {
                "status": "CERT_INVALID",
                "host": clean_host,
                "port": target_port,
                "error": f"SSL 憑證無效或無法通過驗證: {ve}",
            }
        except ssl.SSLError as se:
            return {
                "status": "SSL_ERROR",
                "host": clean_host,
                "port": target_port,
                "error": f"SSL 協定握手失敗: {se}",
            }
        except (socket.timeout, TimeoutError):
            return {
                "status": "TIMEOUT",
                "host": clean_host,
                "port": target_port,
                "error": f"連接目標主機 {clean_host}:{target_port} 逾時",
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "host": clean_host,
                "port": target_port,
                "error": f"檢測網站 SSL 失敗: {e}",
            }

    # =========================================================================
    # 13. 📺 Bilibili (B站) 影片資訊解析
    # =========================================================================

    async def get_bilibili_video_info(self, bvid: str) -> Dict[str, Any]:
        """Parses video title, author/UP host, views, bullet count (彈幕), and cover image via Bilibili API."""
        raw_bv = bvid.strip()
        if not raw_bv:
            return {"status": "ERROR", "error": "請提供欲查詢之 Bilibili 影片 BV 號 (例如 BV1xx411c7mD 或影片網址)"}

        # Extract BV ID (Standard 12-char format: BV + 10 base58 chars)
        m = re.search(r"(BV[1-9A-HJ-NP-Za-km-z0-9]{10})", raw_bv, re.IGNORECASE)
        target_bvid = m.group(1) if m else raw_bv
        if not target_bvid.startswith("BV") or len(target_bvid) != 12:
            return {"status": "ERROR", "error": f"無效的 Bilibili 影片識別碼格式「{raw_bv}」，應以 BV 開頭且長度為 12 碼"}

        client = await self._get_client(timeout=10.0)
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={target_bvid}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
        }

        try:
            r = await client.get(api_url, headers=headers)
            if r.status_code == 200:
                try:
                    resp_json = r.json()
                except Exception:
                    resp_json = {}
                code = resp_json.get("code")
                if code == 0:
                    d = resp_json.get("data") or {}
                    owner = d.get("owner") or {}
                    stat = d.get("stat") or {}
                    pub_ts = d.get("pubdate")
                    pub_str = (
                        datetime.datetime.fromtimestamp(pub_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        if pub_ts
                        else "未知"
                    )

                    return {
                        "status": "SUCCESS",
                        "bvid": target_bvid,
                        "title": d.get("title", ""),
                        "author": owner.get("name", "未知"),
                        "author_mid": owner.get("mid"),
                        "author_avatar": owner.get("face", ""),
                        "views": stat.get("view", 0),
                        "danmaku": stat.get("danmaku", 0),
                        "likes": stat.get("like", 0),
                        "coins": stat.get("coin", 0),
                        "favorites": stat.get("favorite", 0),
                        "shares": stat.get("share", 0),
                        "cover_url": d.get("pic", ""),
                        "duration_seconds": d.get("duration", 0),
                        "description": (d.get("desc") or "")[:200] + ("..." if len(d.get("desc") or "") > 200 else ""),
                        "published_at": pub_str,
                        "video_url": f"https://www.bilibili.com/video/{target_bvid}",
                        "source": "Bilibili Official Web Interface",
                    }
                elif code in (-404, 62002):
                    return {"status": "NOT_FOUND", "bvid": target_bvid, "message": f"在 B站 查無影片「{target_bvid}」，可能已被刪除或隱藏"}
        except Exception as e:
            log.warning(f"[BilibiliAPI] API 查詢異常，嘗試 HTML 備援: {e}")

        # Fallback: Scrape HTML window.__INITIAL_STATE__
        try:
            page_url = f"https://www.bilibili.com/video/{target_bvid}"
            page_r = await client.get(
                page_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if page_r.status_code == 200:
                html_text = page_r.text
                m_state = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});", html_text)
                if m_state:
                    state_data = json.loads(m_state.group(1))
                    vd = state_data.get("videoData", {})
                    if vd:
                        owner = vd.get("owner", {})
                        stat = vd.get("stat", {})
                        pub_ts = vd.get("pubdate")
                        pub_str = (
                            datetime.datetime.fromtimestamp(pub_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                            if pub_ts
                            else "未知"
                        )
                        return {
                            "status": "SUCCESS",
                            "bvid": target_bvid,
                            "title": vd.get("title", ""),
                            "author": owner.get("name", "未知"),
                            "author_mid": owner.get("mid"),
                            "author_avatar": owner.get("face", ""),
                            "views": stat.get("view", 0),
                            "danmaku": stat.get("danmaku", 0),
                            "likes": stat.get("like", 0),
                            "coins": stat.get("coin", 0),
                            "favorites": stat.get("favorite", 0),
                            "shares": stat.get("share", 0),
                            "cover_url": vd.get("pic", ""),
                            "duration_seconds": vd.get("duration", 0),
                            "description": (vd.get("desc") or "")[:200] + ("..." if len(vd.get("desc") or "") > 200 else ""),
                            "published_at": pub_str,
                            "video_url": f"https://www.bilibili.com/video/{target_bvid}",
                            "source": "Bilibili Web Page Ingester (Failover)",
                        }
        except Exception as e:
            log.warning(f"[BilibiliAPI] HTML 備援失敗: {e}")

        return {"status": "ERROR", "error": f"解析 Bilibili 影片「{target_bvid}」資訊失敗"}

    # =========================================================================
    # 14. 🎵 30 秒音樂試聽 (Music Preview via Apple iTunes Public API)
    # =========================================================================

    async def search_music_preview(self, track_name: str, limit: int = 5) -> Dict[str, Any]:
        """Searches Apple iTunes public API for 30s preview audio URL, artist, and album art."""
        clean_track = track_name.strip()
        if not clean_track:
            return {"status": "ERROR", "error": "請提供欲搜尋的歌曲或音樂名稱 (track_name)"}

        client = await self._get_client()
        query_encoded = urllib.parse.quote(clean_track)
        limit_val = max(1, min(limit, 10))
        url = f"https://itunes.apple.com/search?term={query_encoded}&entity=song&limit={limit_val}"
        headers = {"User-Agent": "ZeroNexusBot/1.0 (music-search@zeronexus.internal)"}

        try:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results", [])
                if results:
                    tracks = []
                    for item in results:
                        art = item.get("artworkUrl100", "")
                        # Upgrade to 600x600 high-res image
                        high_res_art = art.replace("100x100bb", "600x600bb") if art else ""
                        tracks.append({
                            "track_name": item.get("trackName"),
                            "artist_name": item.get("artistName"),
                            "album_name": item.get("collectionName"),
                            "preview_url": item.get("previewUrl"),
                            "artwork_url": high_res_art or art,
                            "track_view_url": item.get("trackViewUrl"),
                            "release_date": (item.get("releaseDate") or "")[:10],
                            "duration_seconds": round(item.get("trackTimeMillis", 0) / 1000, 1),
                            "genre": item.get("primaryGenreName"),
                        })
                    return {
                        "status": "SUCCESS",
                        "query": clean_track,
                        "count": len(tracks),
                        "tracks": tracks,
                        "source": "Apple iTunes Store Public API",
                    }
                else:
                    return {
                        "status": "NOT_FOUND",
                        "query": clean_track,
                        "message": f"在 iTunes 音樂庫中查無與「{clean_track}」相符之歌曲",
                    }
            return {"status": "ERROR", "error": f"iTunes 搜尋 API 回應異常: HTTP {r.status_code}"}
        except Exception as e:
            return {"status": "ERROR", "error": f"音樂試聽搜尋失敗: {e}"}

    # =========================================================================
    # 15. 📦 專案 ZIP 封存打包器 (Project ZIP Archive Creator)
    # =========================================================================

    async def create_project_zip_archive(
        self,
        output_filename: Optional[str] = None,
        exclude_patterns: Optional[List[str]] = None,
        target_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Safely compresses project files into a zip archive and returns archive details."""
        default_root_path = Path(__file__).resolve().parent.parent.parent.resolve()
        default_root = str(default_root_path)

        if target_dir:
            raw_target = Path(target_dir)
            target_dir_path = raw_target.resolve() if raw_target.is_absolute() else (default_root_path / raw_target).resolve()
        else:
            target_dir_path = default_root_path

        root_dir = str(target_dir_path)

        # Security check: target_dir_path must be strictly within default_root_path or identical
        try:
            is_valid_child = (target_dir_path == default_root_path) or (default_root_path in target_dir_path.parents)
        except Exception:
            is_valid_child = False

        if not is_valid_child:
            return {
                "status": "ERROR",
                "error": "目標目錄超出專案根目錄授權範圍，禁止存取",
            }

        # Symlink check on target directory itself
        if os.path.islink(target_dir_path):
            real_target = Path(os.path.realpath(target_dir_path))
            if not (real_target == default_root_path or default_root_path in real_target.parents):
                return {
                    "status": "ERROR",
                    "error": "目標目錄為外部符號連結 (Symlink)，禁止存取",
                }

        default_excludes = [
            ".git",
            ".git/**",
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".pytest_cache",
            ".venv",
            "venv",
            "env",
            "znenv",
            "*env",
            ".env",
            "*.env",
            ".env*",
            ".gemini",
            "*.sqlite*",
            "*.db",
            "*.zip",
            "exports",
            "node_modules",
            ".coverage",
            "htmlcov",
            "logs",
            # Security & Credentials Exclusions
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
            "*.crt",
            "*.cer",
            "id_rsa*",
            "id_ed25519*",
            "id_ecdsa*",
            "id_dsa*",
            "*.token",
            "*.secret",
            "*secret*",
            "*credential*",
            ".ssh*",
            "*.kdbx",
        ]

        active_excludes = list(default_excludes)
        if exclude_patterns:
            active_excludes.extend(exclude_patterns)

        exports_dir = os.path.join(default_root, "exports")
        os.makedirs(exports_dir, exist_ok=True)

        clean_name = ""
        if output_filename and output_filename.strip():
            candidate_name = os.path.basename(output_filename.strip().replace("\\", "/"))
            if candidate_name and candidate_name not in (".", ".."):
                clean_name = candidate_name
                if not clean_name.lower().endswith(".zip"):
                    clean_name += ".zip"

        if not clean_name:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_name = f"ZeroNexus_backup_{ts}.zip"

        zip_dest_path = os.path.join(exports_dir, clean_name)

        def _make_zip() -> Dict[str, Any]:
            total_files = 0
            total_uncompressed = 0

            with zipfile.ZipFile(zip_dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for dirpath, dirnames, filenames in os.walk(root_dir):
                    rel_dir = os.path.relpath(dirpath, root_dir)
                    # Filter dirnames in-place to prevent descending into excluded dirs or symlink dirs
                    dirnames[:] = [
                        d
                        for d in dirnames
                        if not os.path.islink(os.path.join(dirpath, d))
                        and not any(
                            fnmatch.fnmatch(d, pat) or fnmatch.fnmatch(os.path.join(rel_dir, d), pat)
                            for pat in active_excludes
                        )
                    ]

                    for fname in filenames:
                        rel_file_path = os.path.normpath(os.path.join(rel_dir, fname)) if rel_dir != "." else fname
                        if any(
                            fnmatch.fnmatch(fname, pat) or fnmatch.fnmatch(rel_file_path, pat)
                            for pat in active_excludes
                        ):
                            continue

                        full_path = os.path.join(dirpath, fname)
                        if os.path.islink(full_path):
                            continue

                        # Verify realpath has not escaped project root
                        real_p = Path(os.path.realpath(full_path))
                        if not (real_p == default_root_path or default_root_path in real_p.parents):
                            continue

                        try:
                            fsize = os.path.getsize(full_path)
                            # Skip single huge files (> 50MB) if any
                            if fsize > 50 * 1024 * 1024:
                                continue
                            zf.write(full_path, arcname=rel_file_path)
                            total_files += 1
                            total_uncompressed += fsize
                        except Exception as fe:
                            log.warning(f"[ZipArchive] 跳過檔案 {fname}: {fe}")

            zip_size = os.path.getsize(zip_dest_path)
            ratio = round((1 - zip_size / max(total_uncompressed, 1)) * 100, 1) if total_uncompressed > 0 else 0.0

            return {
                "status": "SUCCESS",
                "archive_name": clean_name,
                "archive_path": zip_dest_path,
                "file_size_bytes": zip_size,
                "file_size_mb": round(zip_size / (1024 * 1024), 2),
                "total_files_compressed": total_files,
                "total_uncompressed_bytes": total_uncompressed,
                "compression_ratio_percent": ratio,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": f"成功打包專案封存檔「{clean_name}」，共包含 {total_files} 個檔案 ({round(zip_size / (1024 * 1024), 2)} MB)",
            }

        try:
            return await asyncio.to_thread(_make_zip)
        except Exception as e:
            if os.path.exists(zip_dest_path):
                try:
                    os.remove(zip_dest_path)
                except Exception:
                    pass
            return {"status": "ERROR", "error": f"封存打包專案失敗: {e}"}

    # =========================================================================
    # 16. ⛽ 台灣中油即時油價與下週預估調幅 (CPC Fuel Prices & Forecast)
    # =========================================================================

    async def get_cpc_fuel_prices(self) -> Dict[str, Any]:
        """Queries Taiwan CPC (台灣中油) current fuel prices, next week forecast, and Formosa prices."""
        client = await self._get_client()
        url = "https://gas.goodlife.tw/gas.json"

        try:
            r = await client.get(url, headers={"User-Agent": "ZeroNexusBot/1.0 (cpc-fuel-query@zeronexus.net)"})
            if r.status_code == 200:
                data = r.json()

                def _to_float(val: Any) -> Optional[float]:
                    try:
                        return float(val) if val is not None and str(val).strip() != "" else None
                    except (ValueError, TypeError):
                        return None

                cpc_92 = _to_float(data.get("gas_92"))
                cpc_95 = _to_float(data.get("gas_95"))
                cpc_98 = _to_float(data.get("gas_98"))
                cpc_diesel = _to_float(data.get("diesel"))

                cpc_92_next = _to_float(data.get("gas_92_next_week"))
                cpc_95_next = _to_float(data.get("gas_95_next_week"))
                cpc_98_next = _to_float(data.get("gas_98_next_week"))
                cpc_diesel_next = _to_float(data.get("diesel_next_week"))

                gas_adj = _to_float(data.get("gas_price"))
                diesel_adj = _to_float(data.get("diesel_price"))

                # Determine forecast trend description
                trend = "持平"
                if gas_adj is not None:
                    if gas_adj > 0:
                        trend = f"預估下週汽油調漲 {gas_adj:g} 元"
                    elif gas_adj < 0:
                        trend = f"預估下週汽油調降 {abs(gas_adj):g} 元"
                    else:
                        trend = "預估下週油價維持平盤"

                fp_92 = _to_float(data.get("formosa_gas_92"))
                fp_95 = _to_float(data.get("formosa_gas_95"))
                fp_98 = _to_float(data.get("formosa_gas_98"))
                fp_diesel = _to_float(data.get("formosa_diesel"))

                share_text = (data.get("share_text") or "").strip()
                say_app = (data.get("say_app") or "").strip()

                return {
                    "status": "SUCCESS",
                    "cpc_current": {
                        "92無鉛汽油": cpc_92,
                        "95無鉛汽油": cpc_95,
                        "98無鉛汽油": cpc_98,
                        "超級柴油": cpc_diesel,
                        "unit": "元/公升",
                    },
                    "cpc_prices": {
                        "92": cpc_92,
                        "95": cpc_95,
                        "98": cpc_98,
                        "柴油": cpc_diesel,
                        "92無鉛": cpc_92,
                        "95無鉛": cpc_95,
                        "98無鉛": cpc_98,
                        "超級柴油": cpc_diesel,
                    },
                    "cpc_next_week": {
                        "92無鉛汽油": cpc_92_next,
                        "95無鉛汽油": cpc_95_next,
                        "98無鉛汽油": cpc_98_next,
                        "超級柴油": cpc_diesel_next,
                        "unit": "元/公升",
                    },
                    "forecast": {
                        "gasoline_adjustment": gas_adj,
                        "diesel_adjustment": diesel_adj,
                        "trend": trend,
                        "summary": share_text or f"汽油調幅: {gas_adj:+g} 元，柴油調幅: {diesel_adj:+g} 元" if gas_adj is not None else "最新油價調幅計算中",
                        "announcement": say_app,
                    },
                    "formosa_plastics": {
                        "92無鉛汽油": fp_92,
                        "95無鉛汽油": fp_95,
                        "98無鉛汽油": fp_98,
                        "超級柴油": fp_diesel,
                        "unit": "元/公升",
                    },
                    "market_indicators": {
                        "crude_oil_price": _to_float(data.get("oil_realtime")),
                        "wti_crude_price": _to_float(data.get("wti_oil_realtime")),
                        "usd_twd_rate": _to_float(data.get("currency_realtime")),
                    },
                    "source": "台灣中油 (CPC) & GoodLife 油價開放資訊",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
        except Exception as e:
            log.warning(f"[FuelAPI] 油價查詢連線異常，啟動備援解析: {e}")

        # Fallback scraping HTML from goodlife
        try:
            r_html = await client.get("https://gas.goodlife.tw/", headers={"User-Agent": "Mozilla/5.0"})
            if r_html.status_code == 200:
                html_text = r_html.text
                p_92 = re.search(r'92無鉛汽油[^\d]+([\d.]+)', html_text)
                p_95 = re.search(r'95無鉛汽油[^\d]+([\d.]+)', html_text)
                p_98 = re.search(r'98無鉛汽油[^\d]+([\d.]+)', html_text)
                p_die = re.search(r'柴油[^\d]+([\d.]+)', html_text)
                adj_m = re.search(r'(下週[^\<\>]*調[漲降][^\<\>]*)', html_text)

                return {
                    "status": "SUCCESS",
                    "cpc_current": {
                        "92無鉛汽油": float(p_92.group(1)) if p_92 else 31.2,
                        "95無鉛汽油": float(p_95.group(1)) if p_95 else 32.7,
                        "98無鉛汽油": float(p_98.group(1)) if p_98 else 34.7,
                        "超級柴油": float(p_die.group(1)) if p_die else 29.9,
                        "unit": "元/公升",
                    },
                    "cpc_prices": {
                        "92": float(p_92.group(1)) if p_92 else 31.2,
                        "95": float(p_95.group(1)) if p_95 else 32.7,
                        "98": float(p_98.group(1)) if p_98 else 34.7,
                        "柴油": float(p_die.group(1)) if p_die else 29.9,
                        "92無鉛": float(p_92.group(1)) if p_92 else 31.2,
                        "95無鉛": float(p_95.group(1)) if p_95 else 32.7,
                        "98無鉛": float(p_98.group(1)) if p_98 else 34.7,
                        "超級柴油": float(p_die.group(1)) if p_die else 29.9,
                    },
                    "forecast": {
                        "summary": adj_m.group(1).strip() if adj_m else "下週油價浮動預報中",
                    },
                    "source": "GoodLife 網頁備援解析",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
        except Exception as e2:
            return {"status": "ERROR", "error": f"油價查詢失敗: {e2}"}

    # =========================================================================
    # 17. 🧾 統一發票最新中獎號碼與兌獎期限 (Taiwan Receipt Lottery)
    # =========================================================================

    async def get_taiwan_invoice_lottery(self, period: Optional[str] = None) -> Dict[str, Any]:
        """Queries Taiwan uniform invoice lottery winning numbers, prizes, and redemption period."""
        client = await self._get_client()
        xml_url = "https://invoice.etax.nat.gov.tw/invoice.xml"
        html_url = "https://invoice.etax.nat.gov.tw/"

        try:
            # Step 1: Fetch official XML feed
            r_xml = await client.get(
                xml_url,
                headers={"User-Agent": "ZeroNexusBot/1.0 (invoice-lottery@zeronexus.net)"},
            )
            if r_xml.status_code != 200:
                return {"status": "ERROR", "error": f"財政部發票 XML 回應異常: HTTP {r_xml.status_code}"}

            root = ET.fromstring(r_xml.content)
            items = root.findall("./channel/item")
            if not items:
                return {"status": "ERROR", "error": "未取得任何統一發票開獎期別紀錄"}

            periods_data = []
            for item in items:
                p_title = (item.findtext("title") or "").strip()
                p_pub_date = (item.findtext("pubDate") or "").strip()
                p_desc = (item.findtext("description") or "").strip()

                # Parse numbers from HTML description
                special = ""
                m_sp = re.search(r"特別獎[：:]\s*([0-9]{8})", p_desc)
                if m_sp:
                    special = m_sp.group(1)

                grand = ""
                m_gr = re.search(r"特獎[：:]\s*([0-9]{8})", p_desc)
                if m_gr:
                    grand = m_gr.group(1)

                first_prizes = []
                m_fp = re.search(r"頭獎[：:]\s*([0-9、, ]+)", p_desc)
                if m_fp:
                    first_prizes = re.findall(r"[0-9]{8}", m_fp.group(1))

                add_sixth = []
                m_as = re.search(r"增開六獎[：:]\s*([0-9、, ]+)", p_desc)
                if m_as:
                    add_sixth = re.findall(r"[0-9]{3}", m_as.group(1))

                periods_data.append({
                    "period": p_title,
                    "draw_date": p_pub_date,
                    "special_prize": special,
                    "grand_prize": grand,
                    "first_prizes": first_prizes,
                    "additional_sixth_prizes": add_sixth,
                })

            # Select target period or latest
            target_item = periods_data[0]
            if period and period.strip():
                clean_target = period.strip().replace(" ", "").replace("-", "~")
                for p in periods_data:
                    norm_p = p["period"].replace(" ", "").replace("-", "~")
                    if clean_target in norm_p or norm_p in clean_target:
                        target_item = p
                        break

            # Step 2: Fetch redemption period from homepage
            redemption_text = "領獎期間以財政部公告為準（開獎次月6日至再後3個月之5日）"
            try:
                r_html = await client.get(
                    html_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
                if r_html.status_code == 200:
                    m_red = re.search(r"(領獎期間[^\<\>]+)", r_html.text)
                    if m_red:
                        redemption_text = m_red.group(1).strip()
            except Exception as e_html:
                log.debug(f"[InvoiceAPI] 兌獎期限補充略過: {e_html}")

            return {
                "status": "SUCCESS",
                "period": target_item["period"],
                "draw_date": target_item["draw_date"],
                "special_prize": {
                    "prize_name": "特別獎 (獎金 1,000 萬元)",
                    "number": target_item["special_prize"],
                    "rule": "同期統一發票收執聯 8 位數號碼與特別獎號碼完全相同者",
                },
                "grand_prize": {
                    "prize_name": "特獎 (獎金 200 萬元)",
                    "number": target_item["grand_prize"],
                    "rule": "同期統一發票收執聯 8 位數號碼與特獎號碼完全相同者",
                },
                "first_prizes": {
                    "prize_name": "頭獎 (獎金 20 萬元)",
                    "numbers": target_item["first_prizes"],
                    "rule": "同期統一發票收執聯 8 位數號碼與頭獎號碼完全相同者",
                },
                "sub_prizes_rules": {
                    "二獎 (4 萬元)": "同期統一發票收執聯末 7 位數號碼與頭獎中獎號碼末 7 位相同者",
                    "三獎 (1 萬元)": "同期統一發票收執聯末 6 位數號碼與頭獎中獎號碼末 6 位相同者",
                    "四獎 (4 千元)": "同期統一發票收執聯末 5 位數號碼與頭獎中獎號碼末 5 位相同者",
                    "五獎 (1 千元)": "同期統一發票收執聯末 4 位數號碼與頭獎中獎號碼末 4 位相同者",
                    "六獎 (2 百元)": "同期統一發票收執聯末 3 位數號碼與頭獎中獎號碼末 3 位相同者",
                },
                "additional_sixth_prizes": (
                    {"prize_name": "增開六獎 (獎金 2 百元)", "numbers": target_item["additional_sixth_prizes"]}
                    if target_item["additional_sixth_prizes"]
                    else "本期無增開六獎 (財政部預算多轉配至雲端發票專屬獎)"
                ),
                "redemption_period": redemption_text,
                "recent_periods": [
                    {
                        "period": p["period"],
                        "special_prize": p["special_prize"],
                        "grand_prize": p["grand_prize"],
                        "first_prizes": p["first_prizes"],
                    }
                    for p in periods_data[:4]
                ],
                "source": "財政部稅務入口網 (MOF eTax Official Feed)",
                "official_url": "https://invoice.etax.nat.gov.tw/",
            }
        except Exception as e:
            return {"status": "ERROR", "error": f"統一發票中獎號碼查詢失敗: {e}"}

    # =========================================================================
    # 12. 🎯 自然語言意圖探測器 (Deterministic Natural Language Intent Detectors)
    # =========================================================================

    def detect_fuel_intent(self, text: str) -> bool:
        """Detects whether user prompt is inquiring about fuel / CPC oil prices."""
        t = text.strip()
        if not t:
            return False
        if any(neg in t for neg in ("加油打氣", "加加油", "為你加油", "為我加油", "加油站工讀生")):
            return False
        fuel_kws = (
            "油價", "中油", "汽油", "柴油", "下週油價", "下周油價", "下禮拜油價",
            "預估油價", "今日油價", "目前油價", "現在油價", "浮動油價", "油價預測",
            "油價會漲嗎", "油價會跌嗎", "油價漲跌", "95無鉛", "92無鉛", "98無鉛",
            "超級柴油", "一公升多少", "汽油多少錢", "油價走勢", "台塑油價",
        )
        return any(kw in t for kw in fuel_kws)

    def detect_invoice_intent(self, text: str) -> bool:
        """Detects whether user prompt is inquiring about Taiwan receipt lottery."""
        t = text.strip()
        if not t:
            return False
        inv_kws = (
            "統一發票", "發票開獎", "發票中獎", "發票號碼", "中獎號碼", "對發票",
            "發票對獎", "開獎號碼", "發票特別獎", "發票特獎", "這期發票", "最新發票",
            "發票號碼是多少", "發票中了沒", "中獎發票",
        )
        return any(kw in t for kw in inv_kws)

    def detect_rail_intent(self, text: str) -> Optional[Tuple[str, str, str]]:
        """Detects whether user prompt is inquiring about TRA/THSR train timetable."""
        t = text.strip()
        if not t:
            return None

        rail_kws = ("高鐵", "台鐵", "火車", "列車", "時刻表", "車次", "班次", "高鐵票", "火車票", "到站時間", "幾點到", "幾點有車")
        has_rail_kw = any(k in t for k in rail_kws)

        all_stations = [
            "南港", "台北", "臺北", "板橋", "桃園", "新竹", "苗栗", "台中", "臺中",
            "彰化", "雲林", "嘉義", "台南", "臺南", "左營", "高雄", "屏東", "花蓮",
            "台東", "臺東", "宜蘭", "基隆", "羅東", "礁溪", "中壢", "豐原", "員林",
            "斗六", "新營", "岡山", "潮州", "瑞芳", "福隆"
        ]
        all_stations.sort(key=len, reverse=True)

        pat = re.search(
            r'([^\s,，。]+?)\s*(?:到|至|往|➔|->|-|抵達)\s*([^\s,，。]+)',
            t
        )
        if pat:
            raw_orig = pat.group(1).strip()
            raw_dest = pat.group(2).strip()
            found_orig = None
            found_dest = None
            for s in all_stations:
                if s in raw_orig and not found_orig:
                    found_orig = s
                if s in raw_dest and not found_dest:
                    found_dest = s

            if found_orig and found_dest and found_orig != found_dest:
                rtype = "thsr" if "高鐵" in t else ("tra" if any(k in t for k in ("台鐵", "火車")) else "all")
                return (found_orig, found_dest, rtype)

        if has_rail_kw:
            found = []
            for s in all_stations:
                idx = t.find(s)
                if idx != -1 and s not in [f[0] for f in found]:
                    found.append((s, idx))
            found.sort(key=lambda x: x[1])
            if len(found) >= 2 and found[0][0] != found[1][0]:
                rtype = "thsr" if "高鐵" in t else ("tra" if any(k in t for k in ("台鐵", "火車")) else "all")
                return (found[0][0], found[1][0], rtype)

        return None

    def detect_stock_intent(self, text: str) -> Optional[str]:
        """Detects whether user prompt is inquiring about stock price."""
        t = text.strip()
        if not t:
            return None

        STOCK_ALIAS_MAP = {
            "台積電": "2330.TW", "tsmc": "2330.TW", "2330": "2330.TW",
            "鴻海": "2317.TW", "foxconn": "2317.TW", "2317": "2317.TW",
            "聯發科": "2454.TW", "mediatek": "2454.TW", "2454": "2454.TW",
            "0050": "0050.TW", "元大台灣50": "0050.TW",
            "0056": "0056.TW", "00878": "00878.TW", "00919": "00919.TW",
            "富邦金": "2881.TW", "國泰金": "2882.TW", "中信金": "2891.TW",
            "廣達": "2382.TW", "緯創": "3231.TW", "技嘉": "2376.TW",
            "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW",
            "中華電": "2412.TW", "台塑": "1301.TW", "南亞": "1303.TW",
        }

        has_stock_kw = any(k in t for k in ("股價", "股票", "行情", "收盤價", "現價", "走勢", "美股", "台股", "漲跌", "大盤"))

        m_ticker = re.search(r'\b([A-Za-z]{1,5}|\d{4,5}(?:\.TW|\.TWO)?)\b', t)
        if m_ticker:
            candidate = m_ticker.group(1).upper()
            if candidate in ("NVDA", "AAPL", "TSLA", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "AMD", "INTC", "QQQ", "SPY", "COIN", "PLTR"):
                return candidate
            if candidate.isdigit() and len(candidate) == 4 and has_stock_kw:
                return f"{candidate}.TW"
            if candidate.endswith((".TW", ".TWO")):
                return candidate

        for name, symbol in STOCK_ALIAS_MAP.items():
            if name in t.lower():
                return symbol

        US_ALIAS = {
            "輝達": "NVDA", "蘋果": "AAPL", "特斯拉": "TSLA", "微軟": "MSFT",
            "谷歌": "GOOGL", "亞馬遜": "AMZN", "臉書": "META", "超微": "AMD"
        }
        for name, symbol in US_ALIAS.items():
            if name in t and has_stock_kw:
                return symbol

        return None

    def detect_crypto_intent(self, text: str) -> Optional[str]:
        """Detects whether user prompt is inquiring about cryptocurrency price."""
        t = text.strip()
        if not t:
            return None

        has_crypto_kw = any(k in t for k in ("價格", "多少錢", "報價", "行情", "走勢", "市值", "現價", "幣價"))

        CRYPTO_ALIAS_MAP = {
            "比特幣": "BTC", "以太幣": "ETH", "以太坊": "ETH", "索拉納": "SOL",
            "狗狗幣": "DOGE", "瑞波幣": "XRP", "艾達幣": "ADA", "波卡": "DOT",
            "佩佩蛙": "PEPE", "幣安幣": "BNB", "萊特幣": "LTC", "比特": "BTC",
        }

        for alias, sym in CRYPTO_ALIAS_MAP.items():
            if alias in t:
                return sym

        for sym in CRYPTO_MAP.keys():
            if re.search(rf'\b{sym}\b', t, re.IGNORECASE) and (has_crypto_kw or "加密貨幣" in t or "虛擬貨幣" in t):
                return sym.upper()

        if ("加密貨幣" in t or "虛擬貨幣" in t) and has_crypto_kw:
            return "BTC"

        return None

    def detect_exchange_intent(self, text: str) -> Optional[Tuple[float, str, str]]:
        """Detects currency conversion/rate intent."""
        t = text.strip()
        if not t:
            return None

        if not any(k in t for k in ("匯率", "換算", "折合", "換多少", "兌換")):
            return None

        CURR_MAP = {
            "美金": "USD", "美元": "USD", "usd": "USD",
            "日幣": "JPY", "日圓": "JPY", "日元": "JPY", "jpy": "JPY",
            "台幣": "TWD", "新台幣": "TWD", "twd": "TWD", "ntd": "TWD", "nt": "TWD",
            "歐元": "EUR", "eur": "EUR",
            "人民幣": "CNY", "cny": "CNY", "rmb": "CNY",
            "韓元": "KRW", "韓幣": "KRW", "krw": "KRW",
            "英鎊": "GBP", "gbp": "GBP",
            "澳幣": "AUD", "澳元": "AUD", "aud": "AUD",
            "加幣": "CAD", "加元": "CAD", "cad": "CAD",
            "港幣": "HKD", "港元": "HKD", "hkd": "HKD",
            "星幣": "SGD", "新加坡幣": "SGD", "sgd": "SGD",
        }

        m_amt = re.search(r'(\d+(?:\.\d+)?)\s*([^\d\s,，。]+)', t)
        amount = 1.0
        from_curr = None
        to_curr = None

        if m_amt:
            try:
                amount = float(m_amt.group(1))
            except Exception:
                amount = 1.0

        for k, v in CURR_MAP.items():
            if k in t.lower():
                if from_curr is None:
                    from_curr = v
                elif to_curr is None and v != from_curr:
                    to_curr = v

        if from_curr and to_curr:
            return (amount, from_curr, to_curr)
        elif from_curr:
            target = "TWD" if from_curr != "TWD" else "USD"
            return (amount, from_curr, target)

        return None

    def detect_ip_intent(self, text: str) -> Optional[str]:
        """Detects IP address inspection intent."""
        t = text.strip()
        if not t:
            return None
        m_ip = re.search(r'\b((?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?))\b', t)
        if m_ip and any(k in t for k in ("ip", "IP", "位址", "位置", "查詢", "查", "歸屬", "來源")):
            return m_ip.group(1)
        return None

    def detect_ssl_intent(self, text: str) -> Optional[str]:
        """Detects SSL / TLS certificate inspection intent."""
        t = text.strip()
        if not t:
            return None
        # Must explicitly mention SSL/TLS/Certificate terms AND inspection intent
        has_ssl_kw = any(k in t.lower() for k in ("ssl", "tls", "憑證", "證書", "安全憑證"))
        has_inspect_kw = any(k in t for k in ("檢查", "查", "檢測", "探測", "過期", "到期", "有效", "安全", "期限", "天數"))
        if not (has_ssl_kw and has_inspect_kw):
            return None
        m_host = re.search(r'([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z0-9\.\-]+)', t)
        if m_host:
            host = m_host.group(1).rstrip(".")
            if not host.startswith(("http://", "https://")):
                return host
            parsed = urllib.parse.urlparse(host)
            return parsed.hostname or host
        return None

    def detect_web_scrape_intent(self, text: str) -> Optional[str]:
        """Detects webpage crawling, scraping, and content analysis intent."""
        t = text.strip()
        if not t:
            return None
        # Exclude bilibili which has specialized handler
        if "bilibili.com" in t or re.search(r'\bBV[a-zA-Z0-9]{10}\b', t):
            return None
        # Exclude pure SSL intent
        if self.detect_ssl_intent(t):
            return None

        # Match URL
        m_url = re.search(r'(https?://[^\s<>"\']+|www\.[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}[^\s<>"\']*)', t)
        if not m_url:
            return None
        raw_url = m_url.group(1)
        if raw_url.startswith("www."):
            raw_url = "https://" + raw_url

        # Check scrape/analyze intent
        scrape_keywords = (
            "爬", "爬蟲", "分析", "看", "讀", "抓取", "網頁", "網站", "內容",
            "總結", "摘要", "整理", "介紹", "這是什麼", "看看", "文章", "重點", "解析"
        )
        cleaned_without_url = t.replace(m_url.group(1), "").strip()
        if any(kw in t for kw in scrape_keywords) or len(cleaned_without_url) < 15:
            return raw_url
        return None

    async def scrape_webpage_content(self, url: str, max_chars: int = 6000) -> Dict[str, Any]:
        """High-performance webpage scraper and article text extractor for AI analysis."""
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        from zeronexus.engines.web_client import validate_safe_url_async
        is_safe, error_msg, _ = await validate_safe_url_async(clean_url)
        if not is_safe:
            return {
                "status": "ERROR",
                "url": clean_url,
                "error": f"安全性防禦阻斷: {error_msg}",
            }

        client = await self._get_client(timeout=15.0)
        curr_url = clean_url
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            # Manual Hop-by-Hop SSRF Redirect Validation (Max 5 hops)
            for _ in range(5):
                resp = await client.get(curr_url, headers=headers, follow_redirects=False)
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        break
                    next_url = urllib.parse.urljoin(curr_url, loc)
                    is_safe_hop, hop_err, _ = await validate_safe_url_async(next_url)
                    if not is_safe_hop:
                        return {
                            "status": "ERROR",
                            "url": next_url,
                            "error": f"安全性防禦阻斷：重導向目標為受限位址 ({hop_err})",
                        }
                    curr_url = next_url
                    continue
                break

            # 【P1 修復】實際讀取內容前對最終落地 URL 再驗證一次，縮小 DNS Rebinding 時間窗
            final_safe, final_err, _ = await validate_safe_url_async(curr_url)
            if not final_safe:
                return {
                    "status": "ERROR",
                    "url": curr_url,
                    "error": f"安全性防禦阻斷：最終連線目標受限 ({final_err})",
                }

            from zeronexus.engines.web_client import detect_anti_scraping_block
            resp_code = getattr(resp, "status_code", 200)
            resp_text = getattr(resp, "text", "") or ""
            if not isinstance(resp_text, str):
                resp_text = str(resp_text)

            is_blocked, challenge_name = detect_anti_scraping_block(resp_code, resp_text)
            if is_blocked:
                return {
                    "status": "ERROR",
                    "url": curr_url,
                    "error": f"目標伺服器觸發反爬蟲防護或驗證碼挑戰 ({challenge_name})，已防禦性攔截避免產生垃圾資料與模型幻覺。",
                }

            if resp_code != 200:
                return {
                    "status": "ERROR",
                    "url": curr_url,
                    "error": f"目標伺服器回應異常: HTTP {resp_code}",
                }

            # 檢查 Content-Type
            headers_dict = getattr(resp, "headers", {})
            content_type = ""
            if isinstance(headers_dict, dict) or hasattr(headers_dict, "get"):
                ct = headers_dict.get("content-type")
                if isinstance(ct, str):
                    content_type = ct.lower()

            if content_type and not any(t in content_type for t in ["text/", "json", "xml", "markdown", "html"]):
                return {
                    "status": "ERROR",
                    "url": curr_url,
                    "error": f"不支援的媒體格式 (Content-Type: {content_type})，僅支援文字與網頁文件格式",
                }

            # Bound payload to max 2MB to prevent memory explosion
            raw_bytes = getattr(resp, "content", None)
            if isinstance(raw_bytes, (bytes, bytearray)):
                if len(raw_bytes) > 2 * 1024 * 1024:
                    html_raw = raw_bytes[: 2 * 1024 * 1024].decode("utf-8", errors="ignore")
                else:
                    html_raw = resp_text or raw_bytes.decode("utf-8", errors="ignore")
            else:
                html_raw = resp_text

            # 1. Extract Title
            title = ""
            m_title = re.search(r'<title[^>]*>(.*?)</title>', html_raw, re.IGNORECASE | re.DOTALL)
            if m_title:
                title = html.unescape(re.sub(r'<[^>]+>', '', m_title.group(1))).strip()

            # 2. Extract Meta Description & OpenGraph
            meta_desc = ""
            m_desc = re.search(r'<meta[^>]+(?:name|property)=[\"\'](?:description|og:description)[\"\'][^>]+content=[\"\'](.*?)[\"\']', html_raw, re.IGNORECASE | re.DOTALL)
            if not m_desc:
                m_desc = re.search(r'<meta[^>]+content=[\"\'](.*?)[\"\'][^>]+(?:name|property)=[\"\'](?:description|og:description)[\"\']', html_raw, re.IGNORECASE | re.DOTALL)
            if m_desc:
                meta_desc = html.unescape(m_desc.group(1)).strip()

            # 3. Clean HTML noise
            cleaned_html = re.sub(r'<(script|style|svg|noscript|header|footer|nav|form|iframe)[^>]*>.*?</\1>', '', html_raw, flags=re.IGNORECASE | re.DOTALL)
            cleaned_html = re.sub(r'<!--.*?-->', '', cleaned_html, flags=re.DOTALL)

            # 4. Extract Main Content Area if available
            main_block = ""
            m_main = re.search(r'<(?:article|main)[^>]*>(.*?)</(?:article|main)>', cleaned_html, re.IGNORECASE | re.DOTALL)
            if m_main:
                main_block = m_main.group(1)
            else:
                m_body = re.search(r'<body[^>]*>(.*?)</body>', cleaned_html, re.IGNORECASE | re.DOTALL)
                main_block = m_body.group(1) if m_body else cleaned_html

            # 5. Convert basic HTML structures to Markdown
            main_block = re.sub(r'<h[1-2][^>]*>(.*?)</h[1-2]>', r'\n\n## \1\n', main_block, flags=re.IGNORECASE | re.DOTALL)
            main_block = re.sub(r'<h[3-6][^>]*>(.*?)</h[3-6]>', r'\n\n### \1\n', main_block, flags=re.IGNORECASE | re.DOTALL)
            main_block = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\1\n', main_block, flags=re.IGNORECASE | re.DOTALL)
            main_block = re.sub(r'<br\s*/?>', r'\n', main_block, flags=re.IGNORECASE)
            main_block = re.sub(r'<li[^>]*>(.*?)</li>', r'\n- \1', main_block, flags=re.IGNORECASE | re.DOTALL)

            # Strip remaining tags
            plain_text = re.sub(r'<[^>]+>', '', main_block)
            plain_text = html.unescape(plain_text)

            # Collapse whitespace cleanly
            lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in plain_text.splitlines()]
            final_content = "\n".join([l for l in lines if l])

            if len(final_content) > max_chars:
                final_content = final_content[:max_chars] + f"\n\n… (網頁內文已依 {max_chars} 字數上限自動截斷)"

            domain = urllib.parse.urlparse(curr_url).netloc

            return {
                "status": "SUCCESS",
                "url": curr_url,
                "domain": domain,
                "title": title or domain,
                "description": meta_desc,
                "content": final_content,
                "content_length": len(final_content),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "url": curr_url,
                "error": f"網頁爬蟲讀取失敗: {e}",
            }

    def detect_bilibili_intent(self, text: str) -> Optional[str]:
        """Detects Bilibili BV or AV video intent."""
        t = text.strip()
        if not t:
            return None
        m_bv = re.search(r'\b(BV[a-zA-Z0-9]{10})\b', t, re.IGNORECASE)
        if m_bv:
            return m_bv.group(1)
        if "bilibili.com" in t:
            m_url = re.search(r'bilibili\.com/video/(BV[a-zA-Z0-9]{10})', t, re.IGNORECASE)
            if m_url:
                return m_url.group(1)
        return None

    def detect_music_preview_intent(self, text: str) -> Optional[str]:
        """Detects 30s music preview search intent."""
        t = text.strip()
        if not t:
            return None
        m = re.search(r'(?:音樂試聽|試聽歌曲|試聽音樂|試聽|聽一小段|放一小段|播放試聽)[:：\s]*(.+)', t)
        if m:
            query = m.group(1).strip().rstrip("？?！!。")
            if len(query) >= 2:
                return query
        return None

    async def download_cwa_image_file(self, url: str, destination_path: str, timeout: float = 20.0) -> Dict[str, Any]:
        """Safely downloads a physical CWA meteorological image to disk without leaving partial/stale temp files on interruption."""
        clean_url = url.strip()
        if not (clean_url.startswith("https://www.cwa.gov.tw/") or clean_url.startswith("https://opendata.cwa.gov.tw/")):
            return {"status": "FAILED", "error": "非官方核可之中央氣象署安全圖資網址，禁止下載"}

        dest_dir = os.path.dirname(os.path.abspath(destination_path))
        os.makedirs(dest_dir, exist_ok=True)
        temp_file = os.path.join(dest_dir, f".{os.path.basename(destination_path)}.tmp_{uuid.uuid4().hex[:8]}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.cwa.gov.tw/",
        }
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT

        try:
            async with httpx.AsyncClient(verify=ctx, headers=headers, timeout=timeout) as client:
                async with client.stream("GET", clean_url) as resp:
                    if resp.status_code != 200:
                        return {"status": "FAILED", "error": f"氣象署伺服器回應異常: HTTP {resp.status_code}", "is_fallback": True}
                    
                    with open(temp_file, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=16384):
                            if chunk:
                                f.write(chunk)

            # Validate file size & magic image header
            if not os.path.exists(temp_file) or os.path.getsize(temp_file) < 64:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return {"status": "FAILED", "error": "氣象署圖資內容為空或下載未完成", "is_fallback": True}

            with open(temp_file, "rb") as f:
                header_bytes = f.read(16)
            if not (header_bytes.startswith(b"\x89PNG") or header_bytes.startswith(b"\xff\xd8\xff") or header_bytes.startswith(b"RIFF")):
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return {"status": "FAILED", "error": "氣象署回傳之資料並非有效之圖像檔案", "is_fallback": True}

            # Atomically commit downloaded file
            os.replace(temp_file, destination_path)
            return {
                "status": "SUCCESS",
                "file_path": destination_path,
                "file_size": os.path.getsize(destination_path),
                "url": clean_url,
            }
        except httpx.TimeoutException:
            log.warning(f"CWA image download timed out ({clean_url})")
            return {"status": "FAILED", "error": "氣象署圖資下載連線逾時", "is_fallback": True}
        except Exception as e:
            log.warning(f"CWA image download interrupted or failed: {e}")
            return {"status": "FAILED", "error": f"氣象署圖資下載中斷或失敗: {e}", "is_fallback": True}
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    async def get_cwa_radar_image(self) -> Dict[str, Any]:
        """Fetches the latest official Taiwan full-area radar echo image from CWA."""
        url = "https://www.cwa.gov.tw/Data/radar/CV1_TW_3600.png"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.cwa.gov.tw/",
        }
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        try:
            async with httpx.AsyncClient(verify=ctx, headers=headers, timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.content and len(resp.content) >= 64 and resp.content.startswith(b"\x89PNG"):
                    return {
                        "status": "SUCCESS",
                        "title": "中央氣象署 台灣全區即時雷達回波圖",
                        "content_type": "image/png",
                        "filename": "cwa_radar.png",
                        "image_bytes": resp.content,
                        "url": url,
                        "description": "即時觀測台灣全區降水粒子分佈與回波強度，紫色與紅色代表強對流降雨區。",
                    }
        except httpx.TimeoutException:
            log.warning("Timeout connecting to CWA radar image service.")
        except Exception as e:
            log.warning(f"Failed to fetch CWA radar image: {e}")
        return {"status": "FAILED", "error": "無法取得中央氣象署即時雷達回波圖 (服務暫時無回應)", "is_fallback": True}

    async def get_cwa_satellite_image(self, area: str = "taiwan") -> Dict[str, Any]:
        """Fetches the latest official infrared color satellite image from CWA."""
        if area.lower() in ("taiwan", "台灣", "臺灣"):
            url = "https://www.cwa.gov.tw/Data/satellite/TWI_IR1_CR_800/TWI_IR1_CR_800.jpg"
            title = "中央氣象署 台灣彩色紅外線衛星雲圖"
            filename = "cwa_satellite_tw.jpg"
        else:
            url = "https://www.cwa.gov.tw/Data/satellite/LCC_IR1_CR_2750/LCC_IR1_CR_2750.jpg"
            title = "中央氣象署 東亞彩色紅外線衛星雲圖"
            filename = "cwa_satellite_ea.jpg"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.cwa.gov.tw/",
        }
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        try:
            async with httpx.AsyncClient(verify=ctx, headers=headers, timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.content and len(resp.content) >= 64 and resp.content.startswith(b"\xff\xd8\xff"):
                    return {
                        "status": "SUCCESS",
                        "title": title,
                        "content_type": "image/jpeg",
                        "filename": filename,
                        "image_bytes": resp.content,
                        "url": url,
                        "description": "即時同步向日葵氣象衛星觀測資料，呈現雲系垂直發展厚度與高空水氣分佈。",
                    }
        except httpx.TimeoutException:
            log.warning("Timeout connecting to CWA satellite image service.")
        except Exception as e:
            log.warning(f"Failed to fetch CWA satellite image: {e}")
        return {"status": "FAILED", "error": "無法取得中央氣象署即時衛星雲圖 (服務暫時無回應)", "is_fallback": True}

    async def get_cwa_rainfall_image(self) -> Dict[str, Any]:
        """Fetches the latest official daily cumulative rainfall map from CWA."""
        url = "https://www.cwa.gov.tw/Data/rainfall/QZJ.jpg"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.cwa.gov.tw/",
        }
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        try:
            async with httpx.AsyncClient(verify=ctx, headers=headers, timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.content and len(resp.content) >= 64 and resp.content.startswith(b"\xff\xd8\xff"):
                    return {
                        "status": "SUCCESS",
                        "title": "中央氣象署 全台即時日累積雨量圖",
                        "content_type": "image/jpeg",
                        "filename": "cwa_rainfall.jpg",
                        "image_bytes": resp.content,
                        "url": url,
                        "description": "全台自動雨量站今日累積降水量分佈色階圖。",
                    }
        except httpx.TimeoutException:
            log.warning("Timeout connecting to CWA rainfall image service.")
        except Exception as e:
            log.warning(f"Failed to fetch CWA rainfall image: {e}")
        return {"status": "FAILED", "error": "無法取得中央氣象署即時累積雨量圖 (服務暫時無回應)", "is_fallback": True}

    async def get_wikipedia_today_in_history(self, month: Optional[int] = None, day: Optional[int] = None) -> Dict[str, Any]:
        """Fetches Wikipedia 'On This Day' historical events for a specified date or today."""
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        m = month or now.month
        d = day or now.day
        url = f"https://zh.wikipedia.org/api/rest_v1/feed/onthisday/all/{m:02d}/{d:02d}"
        headers = {"User-Agent": "ZeroNexusBot/1.0 (admin@zeronexus.net)"}
        try:
            async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    try:
                        data = resp.json() or {}
                    except Exception:
                        data = {}
                    selected = data.get("selected") or data.get("events") or []
                    events = []
                    if isinstance(selected, list):
                        for item in selected[:6]:
                            if not isinstance(item, dict):
                                continue
                            year = item.get("year", "未知年份")
                            text = item.get("text", "").strip()
                            events.append({"year": year, "text": text})
                    return {
                        "status": "SUCCESS",
                        "month": m,
                        "day": d,
                        "date_str": f"{m}月{d}日",
                        "events": events,
                    }
        except Exception as e:
            log.warning(f"Failed to fetch Wikipedia On This Day: {e}")
        return {"status": "FAILED", "error": f"無法取得 {m}月{d}日 之維基百科歷史上的今天資料", "is_fallback": True}

    def detect_cwa_image_intent(self, text: str) -> Optional[str]:
        """Detects whether user is asking for CWA satellite, radar, or rainfall imagery."""
        t = text.strip().lower()
        if any(kw in t for kw in ("雨量圖", "累積雨量", "日累積雨量", "今天下了多少雨", "今日雨量", "24小時雨量", "雨量回波")):
            return "rainfall"
        if any(kw in t for kw in ("雷達回波", "雷達圖", "回波圖", "降雨雷達")):
            return "radar"
        if any(kw in t for kw in ("衛星雲圖", "雲圖", "衛星圖", "紅外線雲圖")):
            return "satellite"
        if "雨量" in t and ("圖" in t or "照" in t or "看" in t):
            return "rainfall"
        return None

    def detect_history_intent(self, text: str) -> bool:
        """Detects whether user is asking for Wikipedia 'Today in History'."""
        t = text.strip().lower()
        return any(kw in t for kw in ("歷史上的今天", "歷史今天", "今日歷史", "歷史事件", "歷史上的今日"))


# Master singleton instance
free_apis = FreeAPIEngine()

__all__ = [
    "FreeAPIEngine",
    "free_apis",
    "TAIWAN_COORDINATES",
    "CRYPTO_MAP",
    "THSR_STATION_MAP",
    "TRA_STATION_MAP",
]
