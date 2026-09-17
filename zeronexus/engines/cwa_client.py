"""Taiwan Central Weather Administration (CWA) Official API Client.

Features:
- Real-time station observations across Taiwan (O-A0001-001 / O-A0003-001)
- Live weather forecasts across all 22 Taiwan counties/cities (F-C0032-001)
- Significant felt earthquake reports & rapid alerts (E-A0015-001 / E-A0016-001)
- Hazard warnings, typhoon alerts, and heavy rain bulletins (W-C0033-001)
- Deterministic location & station resolver (CWALocationResolver)
- Structured logging with request_id and tool_call_id tracing
- Built-in caching with TTL to avoid rate limit bans
- Degraded state handling when CWA_API_KEY is not configured (zero fake data)
- Security: API key secret masking, untrusted external data tagging
"""

from __future__ import annotations

import asyncio
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import httpx

from zeronexus.core.cache import cache
from zeronexus.core.config import config
from zeronexus.core.logger import log
from zeronexus.security.sanitizer import redact_secrets

CWA_API_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
DATA_TAG_UNTRUSTED = "UNTRUSTED_EXTERNAL_DATA"


def _build_cwa_ssl_context() -> ssl.SSLContext:
    """Builds an SSL context strictly verifying Taiwan Government Open Data certificates.
    Taiwan CWA intermediate certificates omit the modern X.509 Subject Key Identifier extension.
    In Python 3.14 / OpenSSL 3.x, VERIFY_X509_STRICT is enabled by default which rejects chains
    missing SKI. By clearing only the VERIFY_X509_STRICT flag, certificate validity, CA chain,
    and server hostname remain fully verified (CERT_REQUIRED & check_hostname=True) without
    introducing insecure CERT_NONE (CWE-295).
    """
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


CWA_SENTINEL_STRINGS = {
    "-99", "-99.0", "-99.00", "-990", "-990.0", "-990.00",
    "-999", "-999.0", "-999.00", "-9999", "-9999.0",
    "none", "null", "n/a", "", "nan"
}


def is_cwa_sentinel(val: Any) -> bool:
    """Checks whether a raw value from CWA API represents an offline / missing sensor sentinel."""
    if val is None:
        return True
    val_str = str(val).strip().lower()
    if val_str in CWA_SENTINEL_STRINGS:
        return True
    try:
        f = float(val_str)
        if f in (-99.0, -990.0, -999.0, -9999.0):
            return True
    except (ValueError, TypeError):
        pass
    return False


def clean_cwa_sensor_val(raw_val: Any, unit: str = "", default: str = "N/A") -> str:
    """Sanitizes CWA sensor values, replacing sentinels (-99, -990.0, etc.) with normalized default."""
    if is_cwa_sentinel(raw_val):
        return default
    val_str = str(raw_val).strip()
    return f"{val_str}{unit}"


from zeronexus.engines.cwa_location import (
    COUNTY_ALIASES,
    COUNTY_PRIMARY_STATION,
    DISTRICT_STATION_MAP,
    TAIWAN_COUNTIES,
    CWALocationResolver,
    CWALocationResult,
    cwa_location_resolver,
)

__all__ = [
    "CWA_API_BASE",
    "DATA_TAG_UNTRUSTED",
    "CWA_SENTINEL_STRINGS",
    "is_cwa_sentinel",
    "clean_cwa_sensor_val",
    "cwa_client",
    "COUNTY_ALIASES",
    "COUNTY_PRIMARY_STATION",
    "DISTRICT_STATION_MAP",
    "TAIWAN_COUNTIES",
    "CWALocationResolver",
    "CWALocationResult",
    "cwa_location_resolver",
    "_build_cwa_ssl_context",
]


class CWAClient:
    """Asynchronous client interacting with the CWA Open Data Platform."""

    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._last_earthquake_no: Optional[int] = None
        self._last_weather_states: Dict[str, str] = {}

    @property
    def ssl_context(self) -> ssl.SSLContext:
        """Returns the hardened SSLContext adhering to CWE-295."""
        if self._ssl_context is None:
            self._ssl_context = _build_cwa_ssl_context()
        return self._ssl_context

    async def _get_client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if (
            self._http_client is None
            or self._http_client.is_closed
            or self._loop is not loop
        ):
            self._loop = loop
            self._ssl_context = _build_cwa_ssl_context()
            limits = httpx.Limits(
                max_keepalive_connections=5,
                max_connections=15,
                keepalive_expiry=15.0,
            )
            timeout = httpx.Timeout(25.0, connect=10.0, read=20.0)
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                verify=self._ssl_context,
            )
        return self._http_client

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def normalize_county_name(self, query: str) -> Optional[str]:
        cleaned = query.strip()
        return COUNTY_ALIASES.get(cleaned)

    async def _request_cwa(
        self,
        dataset_id: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        max_retries: int = 2,
        backoff_base: float = 0.1,
        silent: bool = False,
    ) -> Dict[str, Any]:
        """Centralized HTTP GET request runner for CWA API with comprehensive fault tolerance, retry & backoff."""
        api_key = config.external.cwa_api_key
        if not api_key:
            raise RuntimeError(
                f"未配置 CWA_API_KEY。請於 .env 設定交通部中央氣象署開放資料平臺授權碼以存取 {dataset_id}。"
            )

        client = await self._get_client()
        url = f"{CWA_API_BASE}/{dataset_id}"
        headers = {"Authorization": api_key}

        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            t0 = time.perf_counter()
            log_req = log.debug if silent else log.info
            log_req(
                f"[CWA_連線請求] 正在向中央氣象署請求資料集 {dataset_id}（第 {attempt+1}/{max_retries+1} 次嘗試）"
                f" [請求識別碼={request_id} 工具呼叫碼={tool_call_id}]"
            )

            try:
                resp = await client.get(url, headers=headers, params=params)
            except httpx.TimeoutException as te:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                last_error = TimeoutError(f"CWA API 連線逾時 ({dataset_id}): 氣象署平臺未在時限內回應 (25s)")
                if attempt < max_retries:
                    log.warning(
                        f"[CWA_連線逾時] 中央氣象署 API 回應逾時 ({dataset_id}，第 {attempt+1} 次嘗試，耗時 {latency_ms} 毫秒)，將進行重試 [請求識別碼={request_id}]：{te}"
                    )
                    retry_wait = max(backoff_base, 0.5) * (2 ** attempt)
                    await asyncio.sleep(retry_wait)
                    continue
                log.error(
                    f"[CWA_連線逾時] 中央氣象署 API 嘗試已達上限 ({dataset_id}，總共嘗試 {attempt+1} 次，耗時 {latency_ms} 毫秒) [請求識別碼={request_id}]：{te}"
                )
                raise last_error from te
            except (httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError) as ne:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                # 網路斷線自癒：關閉舊連線並清除 Client 參照，使後續請求能建立全新連線池
                if self._http_client is not None and not self._http_client.is_closed:
                    try:
                        await self._http_client.aclose()
                    except Exception:
                        pass
                self._http_client = None
                client = await self._get_client()

                last_error = ConnectionError(f"CWA API 連線失敗 ({dataset_id}): 無法建立網路連線 ({type(ne).__name__})")
                if attempt < max_retries:
                    log.warning(
                        f"[CWA_網路異常] 中央氣象署 API 連線中斷 ({dataset_id}，第 {attempt+1} 次嘗試，耗時 {latency_ms} 毫秒)，已自癒重設連線池並準備重試 [請求識別碼={request_id}]：{ne}"
                    )
                    retry_wait = max(backoff_base, 0.5) * (2 ** attempt)
                    await asyncio.sleep(retry_wait)
                    continue
                log.error(
                    f"[CWA_網路異常] 中央氣象署 API 連線嘗試已達上限 ({dataset_id}，耗時 {latency_ms} 毫秒) [請求識別碼={request_id}]：{ne}"
                )
                raise last_error from ne
            except Exception as e:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                log.error(
                    f"[CWA_連線異常] 中央氣象署 API 請求發生未預期異常 ({dataset_id}，耗時 {latency_ms} 毫秒) [請求識別碼={request_id}]：{e}"
                )
                raise RuntimeError(f"CWA API 連線異常 ({dataset_id}): {redact_secrets(str(e))}") from e

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            log_resp = log.debug if silent else log.info
            log_resp(
                f"[CWA_回應完成] 中央氣象署 API 回應完成 ({dataset_id}，狀態碼 {resp.status_code}，耗時 {latency_ms} 毫秒) "
                f"[請求識別碼={request_id} 工具呼叫碼={tool_call_id}]"
            )

            # HTTP 狀態碼檢驗與快速失敗
            if resp.status_code == 400:
                raise ValueError(f"CWA API 請求參數錯誤 (HTTP 400): {redact_secrets(resp.text[:200])}")
            if resp.status_code in (401, 403):
                raise PermissionError(
                    f"CWA API 授權失敗 (HTTP {resp.status_code}): 請確認 CWA_API_KEY 授權碼是否正確有效。"
                )

            # 暫時性頻率限制 (HTTP 429) 或伺服端錯誤 (5xx) 採階梯退避重試
            if resp.status_code == 429:
                last_error = RuntimeError(
                    "CWA API 觸發頻率限制 (HTTP 429 Too Many Requests): 已達氣象署頻率限制，請稍候重試。"
                )
                if attempt < max_retries:
                    retry_after_header = resp.headers.get("Retry-After")
                    header_wait = 0.0
                    if retry_after_header:
                        try:
                            header_wait = float(retry_after_header)
                        except (ValueError, TypeError):
                            pass
                    retry_wait = max(header_wait, max(backoff_base, 1.0) * (2 ** attempt))
                    log.warning(f"[CWA_頻率限制] 遭遇 HTTP 429 限流，將於 {retry_wait:.2f} 秒後進行第 {attempt+2} 次重試...")
                    await asyncio.sleep(retry_wait)
                    continue
                raise last_error

            if resp.status_code >= 500:
                last_error = RuntimeError(
                    f"CWA API 伺服器異常 (HTTP {resp.status_code}): 氣象署伺服端暫時無法處理請求。"
                )
                if attempt < max_retries:
                    retry_wait = max(backoff_base, 0.5) * (2 ** attempt)
                    log.warning(f"[CWA_伺服端異常] 遭遇 HTTP {resp.status_code} 錯誤，將於 {retry_wait:.2f} 秒後進行第 {attempt+2} 次重試...")
                    await asyncio.sleep(retry_wait)
                    continue
                raise last_error

            if resp.status_code != 200:
                raise RuntimeError(
                    f"CWA API 回應異常 (HTTP {resp.status_code}): {redact_secrets(resp.text[:200])}"
                )

            try:
                data = resp.json()
            except Exception as je:
                raise ValueError(f"解析氣象署回傳 JSON 失敗: {je}") from je

            if not isinstance(data, dict):
                raise ValueError(f"氣象署回傳資料格式異常: 預期 JSON 物件，取得 {type(data).__name__}")

            return data

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"CWA API 連線異常 ({dataset_id})")

    # -------------------------------------------------------------------------
    # 1. Real-time Station Observations (O-A0001-001 / O-A0003-001)
    # -------------------------------------------------------------------------
    async def get_realtime_observation(
        self,
        station_or_district: str = "臺北",
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches real-time observation from CWA Automatic (O-A0001-001) or Bureau (O-A0003-001) Station."""
        resolved = cwa_location_resolver.resolve(station_or_district)
        station_name = resolved.station_name or "臺北"
        county_name = resolved.county_name or "臺北市"

        cache_key = f"cwa:obs:{station_name}"
        cached = await cache.get(cache_key)
        if cached:
            cached_copy = dict(cached)
            cached_copy["cache_hit"] = True
            return cached_copy

        stations: List[Dict[str, Any]] = []

        # 1. Primary: O-A0001-001 (Automatic Meteorological Station observations)
        data = await self._request_cwa(
            "O-A0001-001",
            params={"StationName": station_name},
            request_id=request_id,
            tool_call_id=tool_call_id,
        )
        records = data.get("records")
        if isinstance(records, dict):
            stations = records.get("Station") or []

        # 2. Fallback to Bureau Station (O-A0003-001) if not found (only when 200 returned empty stations)
        if not stations:
            data_bureau = await self._request_cwa(
                "O-A0003-001",
                params={"StationName": station_name},
                request_id=request_id,
                tool_call_id=tool_call_id,
            )
            records_bureau = data_bureau.get("records")
            if isinstance(records_bureau, dict):
                stations = records_bureau.get("Station") or []

        # 3. Last fallback: county primary station if query was a sub-district
        if not stations:
            primary_st = COUNTY_PRIMARY_STATION.get(county_name)
            if primary_st and primary_st != station_name:
                data_prim = await self._request_cwa(
                    "O-A0001-001",
                    params={"StationName": primary_st},
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                )
                records_prim = data_prim.get("records")
                if isinstance(records_prim, dict):
                    stations = records_prim.get("Station") or []
                    if stations:
                        station_name = primary_st

        if not stations:
            raise ValueError(f"找不到氣象站「{station_name}」的即時觀測資料。")

        try:
            st_data = stations[0]
            we = st_data.get("WeatherElement") if isinstance(st_data, dict) else {}
            if not isinstance(we, dict):
                we = {}
            geo = st_data.get("GeoInfo") if isinstance(st_data, dict) else {}
            if not isinstance(geo, dict):
                geo = {}
            obs_time_info = st_data.get("ObsTime") if isinstance(st_data, dict) else {}
            obs_time = (
                obs_time_info.get("DateTime")
                if isinstance(obs_time_info, dict)
                else datetime.now(timezone.utc).isoformat()
            )

            raw_temp = we.get("AirTemperature")
            clean_temp = clean_cwa_sensor_val(raw_temp, default="N/A")

            # Daily extremes
            daily_high = "N/A"
            daily_low = "N/A"
            extreme = we.get("DailyExtreme")
            if isinstance(extreme, dict):
                high_info = extreme.get("DailyHigh")
                if isinstance(high_info, dict):
                    temp_info = high_info.get("TemperatureInfo")
                    if isinstance(temp_info, dict):
                        daily_high = clean_cwa_sensor_val(temp_info.get("AirTemperature"), unit="°C", default="N/A")
                low_info = extreme.get("DailyLow")
                if isinstance(low_info, dict):
                    temp_info = low_info.get("TemperatureInfo")
                    if isinstance(temp_info, dict):
                        daily_low = clean_cwa_sensor_val(temp_info.get("AirTemperature"), unit="°C", default="N/A")

            now_elem = we.get("Now")
            raw_precip = now_elem.get("Precipitation") if isinstance(now_elem, dict) else "0.0"
            clean_precip = clean_cwa_sensor_val(raw_precip, unit=" mm", default="0.0 mm")

            raw_humidity = we.get("RelativeHumidity")
            clean_humidity = clean_cwa_sensor_val(raw_humidity, unit="%", default="N/A")

            raw_pressure = we.get("AirPressure")
            clean_pressure = clean_cwa_sensor_val(raw_pressure, unit=" hPa", default="N/A")

            raw_wind_speed = we.get("WindSpeed")
            clean_wind_speed = clean_cwa_sensor_val(raw_wind_speed, unit=" m/s", default="N/A")

            raw_wind_dir = we.get("WindDirection")
            clean_wind_dir = clean_cwa_sensor_val(raw_wind_dir, unit="°", default="N/A")

            raw_weather = str(we.get("Weather", "") or "").strip()
            if not raw_weather or is_cwa_sentinel(raw_weather):
                weather_phenomenon = "多雲"
            else:
                weather_phenomenon = raw_weather

            result = {
                "station_name": st_data.get("StationName", station_name),
                "station_id": st_data.get("StationId", "N/A"),
                "county": geo.get("CountyName", county_name),
                "town": geo.get("TownName", ""),
                "temperature": clean_temp,
                "weather": weather_phenomenon,
                "humidity": clean_humidity,
                "relative_humidity": clean_humidity,
                "precipitation": clean_precip,
                "daily_precipitation": clean_precip,
                "air_pressure": clean_pressure,
                "wind_speed": clean_wind_speed,
                "wind_direction": clean_wind_dir,
                "daily_high": daily_high,
                "daily_low": daily_low,
                "observed_at": obs_time,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "cache_hit": False,
                "data_tag": DATA_TAG_UNTRUSTED,
                "data_type": "REALTIME_OBSERVATION",
                "source_dataset": "O-A0001-001",
                "source": "中央氣象署 (CWA)",
                # Compatibility keys
                "temp": clean_temp,
                "wx": weather_phenomenon,
                "phenomenon": weather_phenomenon,
            }

            log.info(
                f"[CWA_觀測解析成功] 測站「{station_name}」即時觀測資料解析成功：氣溫 {result['temperature']}°C、"
                f"天氣「{result['weather']}」[請求識別碼={request_id} 工具呼叫碼={tool_call_id}]"
            )

            # 快取 5 分鐘
            await cache.set(cache_key, result, ttl=300)
            return result
        except Exception as e:
            log.error(f"[CWA_觀測解析失敗] 無法解析測站觀測資料：{e}")
            raise ValueError(f"解析氣象署即時觀測資料失敗: {e}")

    # -------------------------------------------------------------------------
    # 2. 36-hour Forecast (F-C0032-001)
    # -------------------------------------------------------------------------
    async def get_weather_forecast(
        self,
        county_query: str = "臺北市",
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches 36-hour weather forecast for the specified Taiwan county."""
        resolved = cwa_location_resolver.resolve(county_query)
        county_name = resolved.county_name or self.normalize_county_name(county_query)
        if not county_name:
            raise ValueError(f"找不到縣市「{county_query}」。支援台灣 22 縣市（如台北、新北、台中、高雄、花蓮等）。")

        cache_key = f"cwa:weather:{county_name}"
        cached = await cache.get(cache_key)
        if cached:
            cached_copy = dict(cached)
            cached_copy["cache_hit"] = True
            return cached_copy

        data = await self._request_cwa(
            "F-C0032-001",
            params={"locationName": county_name},
            request_id=request_id,
            tool_call_id=tool_call_id,
        )

        try:
            records = data.get("records")
            locations = records.get("location") if isinstance(records, dict) else []
            if not locations or not isinstance(locations, list):
                raise ValueError(f"解析氣象署回傳資料格式失敗: 查無「{county_name}」之預報 location 資料")

            location = locations[0]
            elements = {}
            for elem in location.get("weatherElement", []):
                if isinstance(elem, dict):
                    elem_name = elem.get("elementName")
                    time_list = elem.get("time", [])
                    if time_list and isinstance(time_list[0], dict):
                        param = time_list[0].get("parameter", {})
                        if isinstance(param, dict) and "parameterName" in param:
                            elements[elem_name] = param["parameterName"]

            wx_raw = elements.get("Wx", "未知")
            wx_clean = "未知" if is_cwa_sentinel(wx_raw) else str(wx_raw)
            pop_raw = elements.get("PoP", "0")
            pop_clean = "0" if is_cwa_sentinel(pop_raw) else str(pop_raw)
            min_raw = elements.get("MinT", "N/A")
            min_clean = "N/A" if is_cwa_sentinel(min_raw) else str(min_raw)
            max_raw = elements.get("MaxT", "N/A")
            max_clean = "N/A" if is_cwa_sentinel(max_raw) else str(max_raw)
            ci_raw = elements.get("CI", "舒適")
            ci_clean = "舒適" if is_cwa_sentinel(ci_raw) else str(ci_raw)

            result = {
                "county": location.get("locationName", county_name),
                "phenomenon": wx_clean,
                "rain_prob": f"{pop_clean}%",
                "min_temp": f"{min_clean}°C" if min_clean != "N/A" else "N/A",
                "max_temp": f"{max_clean}°C" if max_clean != "N/A" else "N/A",
                "comfort": ci_clean,
                "source": "中央氣象署 (CWA)",
                "data_tag": DATA_TAG_UNTRUSTED,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "cache_hit": False,
                # Compatibility keys
                "wx": wx_clean,
                "pop": pop_clean,
                "min_t": min_clean,
                "max_t": max_clean,
                "ci": ci_clean,
                "temp": max_clean if max_clean != "N/A" else (min_clean if min_clean != "N/A" else "25"),
            }
            # Cache for 10 minutes
            await cache.set(cache_key, result, ttl=600)
            return result
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"解析氣象署回傳資料格式失敗: {e}") from e

    async def get_county_forecast(self, county_query: str = "臺北市") -> Dict[str, Any]:
        """Alias for get_weather_forecast."""
        return await self.get_weather_forecast(county_query)

    async def get_all_counties_overview(self) -> List[Dict[str, Any]]:
        """Fetches weather overview for all 22 Taiwan counties."""
        cache_key = "cwa:weather:all_overview"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        data = await self._request_cwa(
            "F-C0032-001",
        )

        try:
            records = data.get("records")
            locations = records.get("location") if isinstance(records, dict) else []
            if not locations or not isinstance(locations, list):
                raise ValueError("解析氣象署全台資料失敗: records.location 為空")

            overview: List[Dict[str, Any]] = []
            for loc in locations:
                if not isinstance(loc, dict):
                    continue
                elements = {}
                for elem in loc.get("weatherElement", []):
                    if isinstance(elem, dict):
                        elem_name = elem.get("elementName")
                        time_list = elem.get("time", [])
                        if time_list and isinstance(time_list[0], dict):
                            param = time_list[0].get("parameter", {})
                            if isinstance(param, dict) and "parameterName" in param:
                                elements[elem_name] = param["parameterName"]

                wx_raw = elements.get("Wx", "晴時多雲")
                wx_clean = "晴時多雲" if is_cwa_sentinel(wx_raw) else str(wx_raw)
                pop_raw = elements.get("PoP", "0")
                pop_clean = "0" if is_cwa_sentinel(pop_raw) else str(pop_raw)
                min_raw = elements.get("MinT", "20")
                min_clean = "20" if is_cwa_sentinel(min_raw) else str(min_raw)
                max_raw = elements.get("MaxT", "28")
                max_clean = "28" if is_cwa_sentinel(max_raw) else str(max_raw)
                ci_raw = elements.get("CI", "舒適")
                ci_clean = "舒適" if is_cwa_sentinel(ci_raw) else str(ci_raw)

                overview.append({
                    "county": loc.get("locationName", "未知"),
                    "wx": wx_clean,
                    "phenomenon": wx_clean,
                    "pop": pop_clean,
                    "rain_prob": f"{pop_clean}%",
                    "min_t": min_clean,
                    "max_t": max_clean,
                    "min_temp": f"{min_clean}°C",
                    "max_temp": f"{max_clean}°C",
                    "temp": max_clean,
                    "ci": ci_clean,
                    "comfort": ci_clean,
                    "source": "中央氣象署 (CWA)",
                    "data_tag": DATA_TAG_UNTRUSTED,
                })
            # Cache for 10 minutes
            await cache.set(cache_key, overview, ttl=600)
            return overview
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"解析氣象署全台資料失敗: {e}") from e

    # -------------------------------------------------------------------------
    # 3. Earthquake Reports (E-A0015-001)
    # -------------------------------------------------------------------------
    async def get_latest_earthquake(
        self,
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        silent: bool = False,
    ) -> Dict[str, Any]:
        """Fetches the latest official felt earthquake report from CWA."""
        cache_key = "cwa:earthquake:latest"
        cached = await cache.get(cache_key)
        if cached:
            cached_copy = dict(cached)
            cached_copy["cache_hit"] = True
            return cached_copy

        data = await self._request_cwa(
            "E-A0015-001",
            params={"limit": 1},
            request_id=request_id,
            tool_call_id=tool_call_id,
            silent=silent,
        )

        try:
            records = data.get("records")
            eq_list = records.get("Earthquake") if isinstance(records, dict) else []
            if not eq_list or not isinstance(eq_list, list):
                result = {
                    "report_id": "0",
                    "earthquake_no": 0,
                    "report_type": "顯著有感地震報告",
                    "origin_time": "無最新報告",
                    "magnitude": 0.0,
                    "depth": "0 公里",
                    "depth_km": 0.0,
                    "location": "無近期顯著有感地震",
                    "latitude": None,
                    "longitude": None,
                    "max_intensity": "未知",
                    "shaking_areas": [],
                    "intensity_summary": "目前中央氣象署資料庫無顯著有感地震報告",
                    "web_url": "https://www.cwa.gov.tw/V8/C/E/index.html",
                    "shakemap_url": None,
                    "source": "中央氣象署 (CWA)",
                    "data_tag": DATA_TAG_UNTRUSTED,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "cache_hit": False,
                }
                await cache.set(cache_key, result, ttl=60)
                return result

            latest = eq_list[0]
            result = self._parse_earthquake_record(latest)
            # Cache for 60 seconds
            await cache.set(cache_key, result, ttl=60)
            self._last_earthquake_no = result.get("earthquake_no", 0)
            return result
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"解析氣象署地震資料失敗: {e}") from e

    def _parse_earthquake_record(self, latest: dict) -> Dict[str, Any]:
        """Robustly parses a single CWA earthquake record with sentinel value filtering."""
        earthquake_info = latest.get("EarthquakeInfo") if isinstance(latest, dict) else {}
        if not isinstance(earthquake_info, dict):
            earthquake_info = {}
        eq_no = latest.get("EarthquakeNo", 0)

        # Epicenter coordinates
        epicenter = earthquake_info.get("Epicenter") if isinstance(earthquake_info, dict) else {}
        if not isinstance(epicenter, dict):
            epicenter = {}
        lat_raw = epicenter.get("EpicenterLatitude")
        lon_raw = epicenter.get("EpicenterLongitude")
        depth_raw = earthquake_info.get("FocalDepth", 0)

        try:
            lat = float(lat_raw) if lat_raw is not None and not is_cwa_sentinel(lat_raw) else None
            if lat is not None and lat < 0:
                lat = None
        except (ValueError, TypeError):
            lat = None

        try:
            lon = float(lon_raw) if lon_raw is not None and not is_cwa_sentinel(lon_raw) else None
            if lon is not None and lon < 0:
                lon = None
        except (ValueError, TypeError):
            lon = None

        try:
            if is_cwa_sentinel(depth_raw) or (isinstance(depth_raw, (int, float)) and depth_raw < 0):
                depth_km = 0.0
                depth_str = "未知"
            else:
                depth_km = max(0.0, float(depth_raw))
                depth_str = f"{depth_raw} 公里"
        except (ValueError, TypeError):
            depth_km = 0.0
            depth_str = "未知"

        # Magnitude
        mag_elem = earthquake_info.get("EarthquakeMagnitude")
        mag_val = 0.0
        if isinstance(mag_elem, dict):
            try:
                raw_mv = mag_elem.get("MagnitudeValue", 0.0)
                if not is_cwa_sentinel(raw_mv):
                    mag_val = max(0.0, float(raw_mv))
                else:
                    mag_val = 0.0
            except (ValueError, TypeError):
                mag_val = 0.0

        # Intensity shaking areas breakdown
        shaking_areas: List[Dict[str, str]] = []
        intensity_info = latest.get("Intensity") if isinstance(latest, dict) else {}
        raw_shaking = intensity_info.get("ShakingArea", []) if isinstance(intensity_info, dict) else []
        if isinstance(raw_shaking, list):
            for area in raw_shaking:
                if isinstance(area, dict):
                    shaking_areas.append({
                        "area": area.get("AreaDesc", ""),
                        "intensity": area.get("AreaIntensity", ""),
                    })
        max_intensity = shaking_areas[0]["intensity"] if shaking_areas else "未知"

        return {
            "report_id": str(eq_no),
            "earthquake_no": eq_no,
            "report_type": "顯著有感地震報告",
            "origin_time": earthquake_info.get("OriginTime", "未知時間"),
            "magnitude": mag_val,
            "depth": depth_str,
            "depth_km": depth_km,
            "location": epicenter.get("Location", "臺灣周邊海域或陸地"),
            "latitude": lat,
            "longitude": lon,
            "max_intensity": max_intensity,
            "shaking_areas": shaking_areas,
            "intensity_summary": latest.get("ReportContent", "各地最大震度請參閱官方報告"),
            "web_url": latest.get("Web", "https://www.cwa.gov.tw/V8/C/E/index.html"),
            "shakemap_url": latest.get("ReportImageURI"),
            "source": "中央氣象署 (CWA)",
            "data_tag": DATA_TAG_UNTRUSTED,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cache_hit": False,
        }

    async def get_earthquake_by_no(
        self,
        report_no: Union[int, str],
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Queries CWA felt earthquake reports for a specific report number (e.g. 115060 or 060)."""
        clean_no = str(report_no).strip()
        cache_key = f"cwa:earthquake:no:{clean_no}"
        cached = await cache.get(cache_key)
        if cached:
            cached_copy = dict(cached)
            cached_copy["cache_hit"] = True
            return cached_copy

        # Check major felt earthquakes first (E-A0015-001)
        data = await self._request_cwa("E-A0015-001", request_id=request_id, tool_call_id=tool_call_id)
        records = data.get("records", {})
        eq_list = records.get("Earthquake", []) if isinstance(records, dict) else []

        target_int = None
        try:
            target_int = int(clean_no)
        except ValueError:
            pass

        matched_record = None
        for eq in eq_list:
            if not isinstance(eq, dict):
                continue
            cur_no = eq.get("EarthquakeNo")
            # Exact match on integer or string ends
            if cur_no == target_int:
                matched_record = eq
                break
            if str(cur_no) == clean_no or str(cur_no).endswith(clean_no):
                matched_record = eq
                break

        # Fallback to local felt earthquakes (E-A0016-001) if not found
        if not matched_record:
            try:
                data_small = await self._request_cwa("E-A0016-001", request_id=request_id, tool_call_id=tool_call_id)
                records_small = data_small.get("records", {})
                eq_small_list = records_small.get("Earthquake", []) if isinstance(records_small, dict) else []
                for eq in eq_small_list:
                    if not isinstance(eq, dict):
                        continue
                    cur_no = eq.get("EarthquakeNo")
                    if cur_no == target_int or str(cur_no) == clean_no or str(cur_no).endswith(clean_no):
                        matched_record = eq
                        break
            except Exception as se:
                log.debug(f"Secondary check E-A0016-001 for earthquake {clean_no} failed: {se}")

        if not matched_record:
            return None

        result = self._parse_earthquake_record(matched_record)
        await cache.set(cache_key, result, ttl=300)
        return result

    async def get_earthquake_history(
        self,
        limit: int = 5,
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches historical felt earthquakes from CWA up to limit."""
        fetch_limit = max(1, min(limit, 20))
        data = await self._request_cwa(
            "E-A0015-001",
            params={"limit": fetch_limit},
            request_id=request_id,
            tool_call_id=tool_call_id,
        )
        records = data.get("records", {})
        eq_list = records.get("Earthquake", []) if isinstance(records, dict) else []
        history: List[Dict[str, Any]] = []
        for eq in eq_list[:limit]:
            if isinstance(eq, dict):
                history.append(self._parse_earthquake_record(eq))
        return history


    # -------------------------------------------------------------------------
    # 4. Hazard Warnings & Typhoon Alerts (W-C0033-001)
    # -------------------------------------------------------------------------
    async def get_hazard_warnings(
        self,
        county: Optional[str] = None,
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches active weather hazard alerts and warnings from CWA (W-C0033-001)."""
        cache_key = "cwa:hazards:latest"
        cached = await cache.get(cache_key)
        all_hazards: Optional[Dict[str, Any]] = None

        if cached:
            all_hazards = dict(cached)
            all_hazards["cache_hit"] = True
        else:
            data = await self._request_cwa(
                "W-C0033-001",
                request_id=request_id,
                tool_call_id=tool_call_id,
            )

            try:
                records = data.get("records")
                locations = records.get("location") if isinstance(records, dict) else []
                if not isinstance(locations, list):
                    locations = []

                active_warnings: List[Dict[str, Any]] = []
                active_counties: List[str] = []

                for loc in locations:
                    if not isinstance(loc, dict):
                        continue
                    loc_name = loc.get("locationName", "")
                    hazard_cond = loc.get("hazardConditions")
                    hazards = hazard_cond.get("hazards", []) if isinstance(hazard_cond, dict) else []
                    if not isinstance(hazards, list):
                        hazards = []
                    for h in hazards:
                        if not isinstance(h, dict):
                            continue
                        info = h.get("info") if isinstance(h, dict) else {}
                        if not isinstance(info, dict):
                            info = {}
                        vtime = h.get("validTime") if isinstance(h, dict) else {}
                        if not isinstance(vtime, dict):
                            vtime = {}
                        phenomena = info.get("phenomena", "天氣警報")
                        significance = info.get("significance", "特報")
                        active_warnings.append({
                            "county": loc_name,
                            "phenomena": phenomena,
                            "significance": significance,
                            "start_time": vtime.get("startTime", ""),
                            "end_time": vtime.get("endTime", ""),
                        })
                        if loc_name and loc_name not in active_counties:
                            active_counties.append(loc_name)

                all_hazards = {
                    "hazard_type": "WEATHER_HAZARD",
                    "total_warnings": len(active_warnings),
                    "active_warnings_count": len(active_warnings),
                    "active_counties": active_counties,
                    "warnings": active_warnings,
                    "source_dataset": "W-C0033-001",
                    "source": "中央氣象署 (CWA)",
                    "data_tag": DATA_TAG_UNTRUSTED,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "cache_hit": False,
                }
                # Cache for 5 minutes
                await cache.set(cache_key, all_hazards, ttl=300)
            except Exception as e:
                if isinstance(e, ValueError):
                    raise
                raise ValueError(f"解析氣象署警特報資料失敗: {e}") from e

        # Filter for specific county if requested
        if county and all_hazards:
            norm_county = self.normalize_county_name(county) or county
            county_warnings = [w for w in all_hazards.get("warnings", []) if w["county"] == norm_county]
            return {
                "county": norm_county,
                "has_warning": len(county_warnings) > 0,
                "warnings": county_warnings,
                "total_national_warnings": all_hazards.get("total_warnings", 0),
                "source": "中央氣象署 (CWA)",
                "data_tag": DATA_TAG_UNTRUSTED,
                "fetched_at": all_hazards.get("fetched_at"),
                "cache_hit": all_hazards.get("cache_hit", False),
            }

        return all_hazards

    # -------------------------------------------------------------------------
    # 5. Rainfall Observations (O-A0002-001)
    # -------------------------------------------------------------------------
    async def get_rainfall_observation(
        self,
        station_or_district: str = "臺北",
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches real-time rainfall observations from CWA Automatic Rainfall Stations (O-A0002-001)."""
        resolved = cwa_location_resolver.resolve(station_or_district)
        station_name = resolved.station_name or "臺北"
        county_name = resolved.county_name or "臺北市"

        cache_key = f"cwa:rainfall:{station_name}"
        cached = await cache.get(cache_key)
        if cached:
            cached_copy = dict(cached)
            cached_copy["cache_hit"] = True
            return cached_copy

        stations: List[Dict[str, Any]] = []

        data = await self._request_cwa(
            "O-A0002-001",
            params={"StationName": station_name},
            request_id=request_id,
            tool_call_id=tool_call_id,
        )
        records = data.get("records")
        if isinstance(records, dict):
            stations = records.get("Station") or []

        # Fallback to county primary station only if 200 returned empty
        if not stations:
            primary_st = COUNTY_PRIMARY_STATION.get(county_name)
            if primary_st and primary_st != station_name:
                data_prim = await self._request_cwa(
                    "O-A0002-001",
                    params={"StationName": primary_st},
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                )
                records_prim = data_prim.get("records")
                if isinstance(records_prim, dict):
                    stations_prim = records_prim.get("Station") or []
                    if stations_prim:
                        stations = stations_prim
                        station_name = primary_st

        if not stations:
            # Fallback to general observation (O-A0001-001) for precipitation
            obs = await self.get_realtime_observation(station_name, request_id=request_id, tool_call_id=tool_call_id)
            result = {
                "station_name": obs.get("station_name", station_name),
                "station_id": obs.get("station_id", "N/A"),
                "county": obs.get("county", county_name),
                "town": obs.get("town", ""),
                "now_precip": obs.get("precipitation", "0.0 mm"),
                "precipitation_now": obs.get("precipitation", "0.0 mm"),
                "past10m_precip": "N/A",
                "past1hr_precip": obs.get("precipitation", "0.0 mm"),
                "precipitation_past_1hr": obs.get("precipitation", "0.0 mm"),
                "past3hr_precip": "N/A",
                "past6hr_precip": "N/A",
                "past12hr_precip": "N/A",
                "past24hr_precip": "N/A",
                "precipitation_past_24hr": "N/A",
                "past2days_precip": "N/A",
                "past3days_precip": "N/A",
                "observed_at": obs.get("observed_at", datetime.now(timezone.utc).isoformat()),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "cache_hit": False,
                "data_tag": DATA_TAG_UNTRUSTED,
                "data_type": "RAINFALL_OBSERVATION",
                "source_dataset": "O-A0001-001",
                "source": "中央氣象署 (CWA) 自動氣象站觀測 (O-A0001-001)",
            }
            await cache.set(cache_key, result, ttl=300)
            return result

        try:
            st = stations[0]
            rf = st.get("RainfallElement") if isinstance(st, dict) else {}
            if not isinstance(rf, dict):
                rf = {}
            geo = st.get("GeoInfo") if isinstance(st, dict) else {}
            if not isinstance(geo, dict):
                geo = {}
            obs_time_info = st.get("ObsTime") if isinstance(st, dict) else {}
            obs_time = (
                obs_time_info.get("DateTime")
                if isinstance(obs_time_info, dict)
                else datetime.now(timezone.utc).isoformat()
            )

            def _get_p(field: str) -> str:
                val = rf.get(field)
                if isinstance(val, dict):
                    raw_val = val.get("Precipitation", "0.0")
                elif val is not None:
                    raw_val = val
                else:
                    raw_val = "0.0"
                return clean_cwa_sensor_val(raw_val, unit=" mm", default="0.0 mm")

            result = {
                "station_name": st.get("StationName", station_name),
                "station_id": st.get("StationId", "N/A"),
                "county": geo.get("CountyName", county_name),
                "town": geo.get("TownName", ""),
                "data_type": "RAINFALL_OBSERVATION",
                "source_dataset": "O-A0002-001",
                "now_precip": _get_p("Now"),
                "precipitation_now": _get_p("Now"),
                "past10m_precip": _get_p("Past10Min"),
                "past1hr_precip": _get_p("Past1hr"),
                "precipitation_past_1hr": _get_p("Past1hr"),
                "past3hr_precip": _get_p("Past3hr"),
                "past6hr_precip": _get_p("Past6Hr"),
                "past12hr_precip": _get_p("Past12hr"),
                "past24hr_precip": _get_p("Past24hr"),
                "precipitation_past_24hr": _get_p("Past24hr"),
                "past2days_precip": _get_p("Past2days"),
                "past3days_precip": _get_p("Past3days"),
                "observed_at": obs_time,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "cache_hit": False,
                "data_tag": DATA_TAG_UNTRUSTED,
                "source": "中央氣象署 (CWA) 自動雨量站實測 (O-A0002-001)",
            }
            await cache.set(cache_key, result, ttl=300)
            return result
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"解析氣象署雨量觀測資料失敗: {e}") from e

    # -------------------------------------------------------------------------
    # 6. Typhoon Warning Bulletins (W-C0034-001)
    # -------------------------------------------------------------------------
    async def get_typhoon_warning(
        self,
        request_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches official Typhoon Warning bulletin from CWA (W-C0034-001)."""
        cache_key = "cwa:typhoon:latest"
        cached = await cache.get(cache_key)
        if cached:
            cached_copy = dict(cached)
            cached_copy["cache_hit"] = True
            return cached_copy

        data = await self._request_cwa(
            "W-C0034-001",
            request_id=request_id,
            tool_call_id=tool_call_id,
        )

        try:
            records = data.get("records")
            info_list = records.get("info") if isinstance(records, dict) else []
            if not info_list or not isinstance(info_list, list):
                result = {
                    "status": "NONE",
                    "is_active": False,
                    "has_active_warning": False,
                    "is_lifted": False,
                    "headline": "無現行發布之颱風警報",
                    "typhoon_name": "無",
                    "status_description": "目前中央氣象署資料庫中無發布中之颱風警報資料。",
                    "bulletin": "目前無發布中之颱風警報",
                    "sections": {},
                    "source_dataset": "W-C0034-001",
                    "source": "中央氣象署 (CWA) 颱風警報 (W-C0034-001)",
                    "data_tag": DATA_TAG_UNTRUSTED,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "cache_hit": False,
                }
                await cache.set(cache_key, result, ttl=180)
                return result

            latest_info = info_list[0] if isinstance(info_list[0], dict) else {}
            headline = str(latest_info.get("headline", "") or "")
            urgency = str(latest_info.get("urgency", "") or "")
            effective = str(latest_info.get("effective", "") or "")
            expires = str(latest_info.get("expires", "") or "")

            # Check if active or already lifted/past
            is_lifted = "解除" in headline or urgency == "Past"
            sections_dict = {}
            desc = latest_info.get("description")
            raw_sections = desc.get("section", []) if isinstance(desc, dict) else []
            if isinstance(raw_sections, list):
                for sec in raw_sections:
                    if isinstance(sec, dict):
                        sections_dict[sec.get("title", "")] = sec.get("value", "")

            status_desc = f"前次警報已解除（{headline}）" if is_lifted else f"現行發布中警報：{headline}"

            result = {
                "status": "ACTIVE" if not is_lifted else "LIFTED",
                "is_active": not is_lifted,
                "has_active_warning": not is_lifted,
                "is_lifted": is_lifted,
                "headline": headline,
                "urgency": urgency,
                "effective": effective,
                "expires": expires,
                "bulletin": status_desc,
                "status_description": status_desc,
                "sections": sections_dict,
                "source_dataset": "W-C0034-001",
                "source": "中央氣象署 (CWA) 颱風警報 (W-C0034-001)",
                "data_tag": DATA_TAG_UNTRUSTED,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "cache_hit": False,
            }
            await cache.set(cache_key, result, ttl=180)
            return result
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"解析氣象署颱風警報資料失敗: {e}") from e

    async def check_new_earthquake_for_broadcast(self) -> Optional[Dict[str, Any]]:
        """Polls CWA for new significant earthquakes. Returns record if newly detected."""
        if not config.external.cwa_api_key:
            return None
        try:
            latest = await self.get_latest_earthquake()
            eq_no = latest.get("earthquake_no", 0)
            if self._last_earthquake_no is not None and eq_no > self._last_earthquake_no:
                self._last_earthquake_no = eq_no
                return latest
            self._last_earthquake_no = eq_no
            return None
        except Exception as e:
            log.debug(f"輪詢地震推播時發生暫時性異常：{e}")
            return None

    async def check_new_weather_for_broadcast(self, county: str = "臺北市") -> Optional[Dict[str, Any]]:
        """Polls CWA for weather forecast updates or significant weather changes for a county."""
        if not config.external.cwa_api_key:
            return None
        norm_county = self.normalize_county_name(county)
        try:
            forecast = await self.get_weather_forecast(norm_county)
            state_key = f"{forecast.get('phenomenon', '')}_{forecast.get('min_temp', '')}_{forecast.get('max_temp', '')}_{forecast.get('rain_prob', '')}"
            if not hasattr(self, "_last_weather_states"):
                self._last_weather_states: Dict[str, str] = {}

            last_state = self._last_weather_states.get(norm_county)
            if last_state is not None and last_state != state_key:
                self._last_weather_states[norm_county] = state_key
                return forecast
            self._last_weather_states[norm_county] = state_key
            return None
        except Exception as e:
            log.debug(f"輪詢「{norm_county}」天氣推播時發生暫時性異常：{e}")
            return None

    async def health_check(self) -> Dict[str, Any]:
        """Probes CWA API connectivity."""
        if not config.external.cwa_api_key:
            return {
                "status": "YELLOW",
                "icon": "🟡",
                "name": "中央氣象署 API (CWA)",
                "details": "未設定金鑰 (待於環境變數配置中央氣象署授權碼)",
            }
        start = time.perf_counter()
        try:
            client = await self._get_client()
            url = f"{CWA_API_BASE}/F-C0032-001"
            headers = {"Authorization": config.external.cwa_api_key}
            resp = await client.get(url, headers=headers, params={"limit": 1})
            latency = (time.perf_counter() - start) * 1000
            if resp.status_code == 200:
                return {
                    "status": "GREEN",
                    "icon": "🟢",
                    "name": "中央氣象署 API (CWA)",
                    "latency_ms": round(latency, 2),
                    "details": "官方氣象資料連線正常",
                }
            return {
                "status": "RED",
                "icon": "🔴",
                "name": "中央氣象署 API (CWA)",
                "latency_ms": round(latency, 2),
                "details": f"伺服器回應異常 (HTTP {resp.status_code})",
            }
        except Exception as e:
            return {
                "status": "RED",
                "icon": "🔴",
                "name": "中央氣象署 API (CWA)",
                "details": f"連線異常：{redact_secrets(str(e))}",
            }


# Singleton CWA instance
cwa_client = CWAClient()
