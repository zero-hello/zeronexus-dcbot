"""Taiwan Central Weather Administration (CWA) Intent Detection and Tool Grounding Service.

Provides:
- Deterministic natural language intent classification for observations, rainfall, forecast, earthquake, typhoon, hazard warnings.
- Execution of appropriate CWA endpoints with correlated request_id and tool_call_id tracing.
- Structured external data formatting for AI context injection.
- Strict provenance and separation between real-time observations and future forecasts.
- Security: Untrusted external data boundary enforcement, secret redaction.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from zeronexus.core.logger import log
from zeronexus.engines.cwa_client import (
    CWALocationResult,
    cwa_client,
    cwa_location_resolver,
)
from zeronexus.security.sanitizer import redact_secrets


class CWAIntentType(str, Enum):
    """Classified intent for CWA requests."""
    REALTIME_WEATHER = "realtime_weather"
    RAINFALL = "rainfall"
    FORECAST = "forecast"
    TAIWAN_OVERVIEW = "taiwan_overview"
    EARTHQUAKE = "earthquake"
    TYPHOON = "typhoon"
    HAZARD_WARNING = "hazard_warning"


@dataclass
class CWAIntent:
    """Parsed CWA intent container."""
    intent_type: CWAIntentType
    raw_query: str = ""
    location: Optional[CWALocationResult] = None
    query: str = ""

    def __post_init__(self) -> None:
        if not self.query and self.raw_query:
            self.query = self.raw_query
        elif not self.raw_query and self.query:
            self.raw_query = self.query

    @property
    def target_location(self) -> Optional[str]:
        """Resolves friendly location string from parsed CWALocationResult or query."""
        if self.location:
            return self.location.station_name or self.location.county_name or self.location.query
        return self.query or self.raw_query or None


class CWAService:
    """Service layer coordinating CWA intent classification and AI tool grounding."""

    def __init__(self) -> None:
        self.resolver = cwa_location_resolver

    def detect_intent(self, text: str) -> Optional[CWAIntent]:
        """Detects whether user prompt requires CWA official real-time meteorological or seismic grounding."""
        raw = text.strip()

        # 1. Check for Earthquake intent
        # Examples: "最近有地震嗎", "剛剛有地震嗎", "地震速報", "今天有地震嗎", "花蓮地震"
        if "地震" in raw or "有搖" in raw or "地牛" in raw:
            eq_triggers = [
                "有地震", "地震嗎", "剛才", "剛剛", "剛有", "剛發生", "最近",
                "今天", "昨晚", "發生地震", "地震速報", "地震報告", "震央",
                "震度", "規模", "有搖", "很大嗎", "地震消息", "地牛", "地震"
            ]
            if any(t in raw for t in eq_triggers) or raw in ["地震", "查地震", "最新地震", "最近地震"]:
                loc_res = self.resolver.resolve(raw)
                return CWAIntent(
                    intent_type=CWAIntentType.EARTHQUAKE,
                    raw_query=raw,
                    location=loc_res if loc_res.is_matched else None,
                )

        # 2. Check for Typhoon intent
        # Examples: "現在有颱風嗎", "颱風警報", "颱風動態", "有颱風嗎"
        if "颱風" in raw:
            ty_triggers = ["有颱風", "颱風嗎", "現在有", "最近有", "颱風警報", "颱風動態", "發布", "發佈", "颱風"]
            if any(t in raw for t in ty_triggers):
                loc_res = self.resolver.resolve(raw)
                return CWAIntent(
                    intent_type=CWAIntentType.TYPHOON,
                    raw_query=raw,
                    location=loc_res if loc_res.is_matched else None,
                )

        # 3. Check for Rainfall intent
        # Examples: "現在台北雨量", "今天下了多少雨", "時雨量", "累積雨量", "降雨量"
        if any(rk in raw for rk in ["雨量", "降雨量", "累積雨量", "下多少雨", "時雨量", "日雨量"]):
            loc_res = self.resolver.resolve(raw)
            return CWAIntent(
                intent_type=CWAIntentType.RAINFALL,
                raw_query=raw,
                location=loc_res if loc_res.is_matched else None,
            )

        # 4. Check for Hazard / Severe Weather Warnings
        # Examples: "有豪雨特報嗎", "強風特報", "天氣警報", "大雨特報"
        hazard_keywords = ["特報", "警報", "豪雨", "大雨", "暴雨", "強風", "陸警", "海警"]
        if any(hk in raw for hk in hazard_keywords):
            loc_res = self.resolver.resolve(raw)
            return CWAIntent(
                intent_type=CWAIntentType.HAZARD_WARNING,
                raw_query=raw,
                location=loc_res if loc_res.is_matched else None,
            )

        # 5. Check for Taiwan Overview
        # Examples: "現在台灣天氣如何", "全台天氣", "台灣氣溫", "全台灣天氣如何"
        overview_triggers = ["台灣", "臺灣", "全台", "全臺灣", "全島", "全省", "各地"]
        weather_words = ["天氣", "氣象", "氣候", "氣溫", "溫度", "下雨", "降雨", "狀況", "概況", "如何", "怎樣"]
        if any(ot in raw for ot in overview_triggers) and any(ww in raw for ww in weather_words):
            return CWAIntent(
                intent_type=CWAIntentType.TAIWAN_OVERVIEW,
                raw_query=raw,
                location=CWALocationResult(query=raw, is_overview=True, is_matched=True),
            )

        # 6. Resolve location from prompt
        loc_res = self.resolver.resolve(raw)

        # 7. Check for Real-time Weather / Temperature vs Forecast
        realtime_triggers = [
            "現在", "目前", "即時", "幾度", "溫度", "氣溫", "體感", "多冷",
            "多熱", "現在幾度", "目前幾度", "外面幾度", "今天幾度", "幾度了",
            "現在溫度", "現在天氣", "即時天氣", "外面冷不冷", "外面熱不熱"
        ]

        forecast_triggers = [
            "天氣", "預報", "會下雨嗎", "下雨機率", "降雨機率", "降雨", "帶傘",
            "出門", "出去", "出遊", "晴天", "陰天", "明天", "後天", "週末", "這週", "今天天氣",
            "氣象", "天氣怎樣", "天氣如何", "適不適合", "適合嗎", "適不適合出去", "適不適合出門",
            "適合出去嗎", "適合出門嗎", "能不能出門", "能不能出去", "可以出門嗎", "可以出去嗎",
            "要出門", "想出門", "想出去", "能出門嗎", "能出去嗎", "洗衣服", "曬衣服", "穿什麼", "穿外套"
        ]

        if loc_res.is_matched:
            if any(rt in raw for rt in realtime_triggers):
                return CWAIntent(
                    intent_type=CWAIntentType.REALTIME_WEATHER,
                    raw_query=raw,
                    location=loc_res,
                )
            if any(ft in raw for ft in forecast_triggers):
                return CWAIntent(
                    intent_type=CWAIntentType.FORECAST,
                    raw_query=raw,
                    location=loc_res,
                )
            if "天氣" in raw or "溫度" in raw or "氣溫" in raw or "幾度" in raw:
                return CWAIntent(
                    intent_type=CWAIntentType.REALTIME_WEATHER,
                    raw_query=raw,
                    location=loc_res,
                )

        # No location matched, but user directly asks general weather/temperature without location (default to Taipei)
        if any(rt in raw for rt in ["現在幾度", "目前幾度", "外面幾度", "今天幾度", "現在外面幾度"]):
            default_loc = CWALocationResult(query="臺北市", county_name="臺北市", station_name="臺北", is_matched=True)
            return CWAIntent(
                intent_type=CWAIntentType.REALTIME_WEATHER,
                raw_query=raw,
                location=default_loc,
            )

        return None

    async def execute_cwa_tool(
        self,
        intent: CWAIntent,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes the appropriate CWA endpoint, produces grounded text for AI injection, and returns payload."""
        tool_call_id = f"call_cwa_{uuid.uuid4().hex[:8]}"
        log.info(
            f"[CWA_TOOL_REQUEST] 正在調度執行氣象署工具：{intent.intent_type.value} [工具呼叫碼={tool_call_id} 請求識別碼={request_id}]"
        )

        try:
            if intent.intent_type == CWAIntentType.REALTIME_WEATHER:
                loc = intent.location or CWALocationResult(query="臺北市", county_name="臺北市", station_name="臺北", is_matched=True)
                station = loc.station_name or "臺北"
                county = loc.county_name or "臺北市"

                obs_data = await cwa_client.get_realtime_observation(
                    station_or_district=station,
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                )

                forecast_text = ""
                try:
                    fc_data = await cwa_client.get_weather_forecast(
                        county_query=county,
                        request_id=request_id,
                        tool_call_id=tool_call_id,
                    )
                    forecast_text = (
                        f"\n【{fc_data['county']} 未來 36 小時天氣預報參考（請注意：此為預測非觀測）】：\n"
                        f"- 預報現象：{fc_data['phenomenon']}\n"
                        f"- 預測氣溫區間：{fc_data['min_temp']} ~ {fc_data['max_temp']}\n"
                        f"- 降雨機率：{fc_data['rain_prob']}\n"
                        f"- 舒適度指標：{fc_data['comfort']}"
                    )
                except Exception as fe:
                    log.debug(f"Companion forecast fetch ignored: {fe}")

                grounding = (
                    f"【交通部中央氣象署 (CWA) 官方即時觀測真值（優先度最高，請依此回答當前氣溫）】：\n"
                    f"- 觀測測站：{obs_data['station_name']}（{obs_data['county']} {obs_data['town']}，站號：{obs_data['station_id']}）\n"
                    f"- 即時當前氣溫（實測）：{obs_data['temperature']}°C\n"
                    f"- 即時實測天氣現象：{obs_data['weather']}\n"
                    f"- 即時相對濕度：{obs_data['relative_humidity']}\n"
                    f"- 當前降雨量：{obs_data['precipitation']}\n"
                    f"- 今日已記錄最高溫 / 最低溫：{obs_data['daily_high']} / {obs_data['daily_low']}\n"
                    f"- 大氣壓力：{obs_data['air_pressure']}\n"
                    f"- 風速與風向：{obs_data['wind_speed']}（風向角 {obs_data['wind_direction']}）\n"
                    f"- 官方觀測時間戳記：{obs_data['observed_at']}\n"
                    f"- 官方資料來源：中央氣象署自動氣象站實測 (O-A0001-001)\n"
                    f"{forecast_text}\n"
                    f"【特別遵守原則】：\n"
                    f"1. 請務必明確向使用者陳述目前即時氣溫為 {obs_data['temperature']}°C，切勿宣稱無法取得氣象署即時資料。\n"
                    f"2. 嚴格區分「即時觀測」（{obs_data['temperature']}°C）與「未來預報區間」，絕不可將兩者混淆。"
                )

                log.info(f"[CWA_TOOL_SUCCESS] 即時天氣觀測工具執行成功 [工具呼叫碼={tool_call_id}]")
                return {
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "intent_type": intent.intent_type.value,
                    "location": county,
                    "station": station,
                    "grounding_prompt": grounding,
                    "raw_data": obs_data,
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                }

            elif intent.intent_type == CWAIntentType.RAINFALL:
                loc = intent.location or CWALocationResult(query="臺北市", county_name="臺北市", station_name="臺北", is_matched=True)
                station = loc.station_name or "臺北"
                county = loc.county_name or "臺北市"

                rf_data = await cwa_client.get_rainfall_observation(
                    station_or_district=station,
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                )

                grounding = (
                    f"【交通部中央氣象署 (CWA) 官方自動雨量站實測資料（真值）】：\n"
                    f"- 觀測測站：{rf_data['station_name']}（{rf_data['county']} {rf_data['town']}，站號：{rf_data['station_id']}）\n"
                    f"- 即時雨量 (Now)：{rf_data['now_precip']}\n"
                    f"- 過去 10 分鐘累積雨量：{rf_data['past10m_precip']}\n"
                    f"- 過去 1 小時累積雨量：{rf_data['past1hr_precip']}\n"
                    f"- 過去 3 小時累積雨量：{rf_data['past3hr_precip']}\n"
                    f"- 過去 24 小時累積雨量：{rf_data['past24hr_precip']}\n"
                    f"- 觀測時間：{rf_data['observed_at']}\n"
                    f"- 官方資料來源：中央氣象署自動雨量站 (O-A0002-001)\n"
                    f"【嚴格準則】：請向使用者客觀說明該測站的各時段實際累積雨量，絕不臆測。"
                )

                log.info(f"[CWA_TOOL_SUCCESS] 雨量觀測工具執行成功 [工具呼叫碼={tool_call_id}]")
                return {
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "intent_type": intent.intent_type.value,
                    "location": county,
                    "station": station,
                    "grounding_prompt": grounding,
                    "raw_data": rf_data,
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                }

            elif intent.intent_type == CWAIntentType.FORECAST:
                loc = intent.location or CWALocationResult(query="臺北市", county_name="臺北市", station_name="臺北", is_matched=True)
                county = loc.county_name or "臺北市"
                station = loc.station_name or "臺北"

                fc_data = await cwa_client.get_weather_forecast(
                    county_query=county,
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                )

                grounding = (
                    f"【交通部中央氣象署 (CWA) 官方 36 小時天氣預報（預測真值）】：\n"
                    f"- 預報目標：{fc_data['county']}\n"
                    f"- 天氣現象：{fc_data['phenomenon']}\n"
                    f"- 預測氣溫區間：{fc_data['min_temp']} ~ {fc_data['max_temp']}\n"
                    f"- 降雨機率：{fc_data['rain_prob']}\n"
                    f"- 舒適度評估：{fc_data['comfort']}\n"
                    f"- 官方資料來源：中央氣象署 36 小時天氣預報 (F-C0032-001)\n"
                    f"【嚴格準則】：此資料為中央氣象署官方氣象預報，請以此官方預報親切向使用者說明未來天氣趨勢、降雨機率與出門穿著建議。"
                )

                log.info(f"[CWA_TOOL_SUCCESS] 天氣預報工具執行成功 [工具呼叫碼={tool_call_id}]")
                return {
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "intent_type": intent.intent_type.value,
                    "location": county,
                    "grounding_prompt": grounding,
                    "raw_data": fc_data,
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                }

            elif intent.intent_type == CWAIntentType.TAIWAN_OVERVIEW:
                overview = await cwa_client.get_all_counties_overview()
                summary_lines = []
                for item in overview[:12]:
                    summary_lines.append(
                        f"- {item['county']}: {item['wx']}, 氣溫 {item['min_temp']}~{item['max_temp']}, 降雨機率 {item['rain_prob']}"
                    )
                summary_block = "\n".join(summary_lines)

                grounding = (
                    f"【交通部中央氣象署 (CWA) 全台 22 縣市官方天氣概況（真實真值）】：\n"
                    f"{summary_block}\n"
                    f"- 其餘縣市亦皆由中央氣象署即時同步監測中。\n"
                    f"- 資料來源：中央氣象署 (F-C0032-001)\n"
                    f"【嚴格準則】：請以此官方全台概況為真值，親切為使用者摘要台灣各地天氣趨勢。"
                )

                log.info(f"[CWA_TOOL_SUCCESS] 全台天氣概況工具執行成功 [工具呼叫碼={tool_call_id}]")
                return {
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "intent_type": intent.intent_type.value,
                    "grounding_prompt": grounding,
                    "raw_data": {"counties_count": len(overview)},
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                }

            elif intent.intent_type == CWAIntentType.EARTHQUAKE:
                # Check if specific report number was queried e.g. 115060 or 第 60 號
                query_text = getattr(intent, "raw_query", "") or getattr(intent, "query", "") or ""
                eq_num_match = re.search(r"(?:第\s*|編號\s*|報告\s*)?(\d{2,6})(?:\s*號)?", query_text)
                specific_eq_no = eq_num_match.group(1) if eq_num_match else None

                eq_data = None
                if specific_eq_no:
                    try:
                        eq_data = await cwa_client.get_earthquake_by_no(
                            specific_eq_no,
                            request_id=request_id,
                            tool_call_id=tool_call_id,
                        )
                    except Exception as eq_err:
                        log.debug(f"查詢指定地震編號 {specific_eq_no} 略過：{eq_err}")

                if not eq_data:
                    eq_data = await cwa_client.get_latest_earthquake(
                        request_id=request_id,
                        tool_call_id=tool_call_id,
                    )

                shaking_summary = []
                for s in eq_data.get("shaking_areas", [])[:5]:
                    shaking_summary.append(f"- {s['area']}：最大震度 {s['intensity']}")
                shaking_text = "\n".join(shaking_summary) if shaking_summary else eq_data.get("intensity_summary", "")

                grounding = (
                    f"【交通部中央氣象署 (CWA) 顯著有感地震報告（真實官方資料）】：\n"
                    f"- 報告編號：第 {eq_data['earthquake_no']} 號（{eq_data['report_type']}）\n"
                    f"- 發震時間：{eq_data['origin_time']}\n"
                    f"- 芮氏規模：M {eq_data['magnitude']}\n"
                    f"- 震源深度：{eq_data['depth']}\n"
                    f"- 震央座標：北緯 {eq_data.get('latitude', 'N/A')}° / 東經 {eq_data.get('longitude', 'N/A')}°\n"
                    f"- 震央位置：{eq_data['location']}\n"
                    f"- 全台最大震度：{eq_data.get('max_intensity', '未知')}\n"
                    f"- 主要顯著震區：\n{shaking_text}\n"
                    f"- 官方詳細報告連結：{eq_data['web_url']}\n"
                    f"- 資料來源：中央氣象署地震測報中心 (E-A0015-001)\n"
                    f"【嚴格準則】：以上資料均來自氣象署官方地震報告。請向使用者精準說明發震時間、規模、震央及震度，並提醒注意餘震與自身安全。"
                )

                log.info(f"[CWA_TOOL_SUCCESS] 地震報告工具執行成功 [工具呼叫碼={tool_call_id}]")
                return {
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "intent_type": intent.intent_type.value,
                    "grounding_prompt": grounding,
                    "raw_data": eq_data,
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                }

            elif intent.intent_type == CWAIntentType.TYPHOON:
                ty_data = await cwa_client.get_typhoon_warning(
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                )
                haz_data = {}
                try:
                    haz_data = await cwa_client.get_hazard_warnings(
                        request_id=request_id,
                        tool_call_id=tool_call_id,
                    )
                except Exception as he:
                    log.debug(f"Companion hazard warnings fetch ignored for typhoon: {he}")

                if ty_data.get("is_active"):
                    sec_lines = [f"- **{k}**：{v}" for k, v in ty_data.get("sections", {}).items()]
                    sec_block = "\n".join(sec_lines)
                    grounding = (
                        f"【交通部中央氣象署 (CWA) 現行發布之官方颱風警報（真實真值）】：\n"
                        f"- 警報標題：{ty_data['headline']}\n"
                        f"- 發布時間：{ty_data.get('effective', '')}\n"
                        f"- 颱風動態與詳細分析：\n{sec_block}\n"
                        f"- 資料來源：中央氣象署颱風警報單 (W-C0034-001)\n"
                        f"【嚴格準則】：目前官方發布颱風警報中，請以此權威資料向使用者說明颱風位置與警戒區域，並呼籲嚴加防範。"
                    )
                else:
                    haz_summary = ""
                    if haz_data.get("total_warnings", 0) > 0:
                        haz_summary = f"\n（註：目前全台另發布有 {haz_data.get('total_warnings')} 項氣象特報，例如強風或大雨特報，詳見官方災防通知。）"
                    grounding = (
                        f"【交通部中央氣象署 (CWA) 官方颱風動態與警報狀態（真實官方資料）】：\n"
                        f"目前中央氣象署【未發布任何現行之海上或陸上颱風警報】。\n"
                        f"- 官方最新狀態：{ty_data.get('status_description', '前次颱風警報已解除，目前無發布中之颱風警報')}\n"
                        f"- 資料來源：中央氣象署颱風警報開放資料庫 (W-C0034-001){haz_summary}\n"
                        f"【嚴格準則】：請客觀告知使用者目前中央氣象署並無發布中的颱風警報，切勿自行編造虛構颱風。"
                    )

                log.info(f"[CWA_TOOL_SUCCESS] 颱風警報工具執行成功 [工具呼叫碼={tool_call_id}]")
                return {
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "intent_type": intent.intent_type.value,
                    "grounding_prompt": grounding,
                    "raw_data": ty_data,
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                }

            elif intent.intent_type == CWAIntentType.HAZARD_WARNING:
                county = intent.location.county_name if intent.location else None
                haz_data = await cwa_client.get_hazard_warnings(
                    county=county,
                    request_id=request_id,
                    tool_call_id=tool_call_id,
                )

                if county and "has_warning" in haz_data:
                    if haz_data["has_warning"]:
                        w_lines = [
                            f"- {w['phenomena']}{w['significance']}（有效時間：{w['start_time']} 至 {w['end_time']}）"
                            for w in haz_data.get("warnings", [])
                        ]
                        w_text = "\n".join(w_lines)
                        grounding = (
                            f"【交通部中央氣象署 (CWA) 官方警特報資訊 — {county}（真實真值）】：\n"
                            f"目前中央氣象署針對 {county} 發布以下警特報：\n"
                            f"{w_text}\n"
                            f"- 資料來源：中央氣象署 (W-C0033-001)\n"
                            f"【嚴格準則】：請以此官方警報資訊提醒使用者注意安全防範。"
                        )
                    else:
                        grounding = (
                            f"【交通部中央氣象署 (CWA) 官方警特報資訊 — {county}（真實真值）】：\n"
                            f"目前中央氣象署針對 {county}【未發布】任何颱風、豪大雨或強風特報，天氣相對穩定。\n"
                            f"（目前全台累計發布 {haz_data.get('total_national_warnings', 0)} 處警特報）\n"
                            f"- 資料來源：中央氣象署 (W-C0033-001)"
                        )
                else:
                    total_w = haz_data.get("total_warnings", 0)
                    active_counties = haz_data.get("active_counties", [])
                    if total_w > 0:
                        warn_summaries = []
                        for w in haz_data.get("warnings", [])[:8]:
                            warn_summaries.append(f"- {w['county']}：{w['phenomena']}{w['significance']}")
                        warn_text = "\n".join(warn_summaries)
                        grounding = (
                            f"【交通部中央氣象署 (CWA) 全台官方警特報概況（真實真值）】：\n"
                            f"目前中央氣象署在全台共發布 {total_w} 項警特報，受影響縣市包括：{', '.join(active_counties[:10])}。\n"
                            f"主要警特報清單：\n"
                            f"{warn_text}\n"
                            f"- 資料來源：中央氣象署 (W-C0033-001)\n"
                            f"【嚴格準則】：請向使用者客觀說明官方警特報現況，提醒注意防風防雨。"
                        )
                    else:
                        grounding = (
                            "【交通部中央氣象署 (CWA) 全台官方警特報概況（真實真值）】：\n"
                            "目前中央氣象署全台【無任何現存之颱風警報或豪雨特報】，全台天氣與海面無顯著突發警報。\n"
                            "- 資料來源：中央氣象署 (W-C0033-001)\n"
                            "【嚴格準則】：請向使用者說明目前官方無颱風或重大災害警報。"
                        )

                log.info(f"[CWA_TOOL_SUCCESS] 災害警特報工具執行成功 [工具呼叫碼={tool_call_id}]")
                return {
                    "tool_call_id": tool_call_id,
                    "request_id": request_id,
                    "intent_type": intent.intent_type.value,
                    "grounding_prompt": grounding,
                    "raw_data": haz_data,
                    "data_tag": "UNTRUSTED_EXTERNAL_DATA",
                }

            return {
                "tool_call_id": tool_call_id,
                "request_id": request_id,
                "intent_type": "unknown",
                "grounding_prompt": "",
                "raw_data": {},
                "data_tag": "UNTRUSTED_EXTERNAL_DATA",
            }

        except Exception as e:
            safe_err = redact_secrets(str(e))
            log.error(f"[CWA_TOOL_FAILED] 氣象署工具調度執行失敗 ({intent.intent_type.value})：{safe_err}")
            fallback_grounding = (
                f"【中央氣象署 (CWA) 官方資料查詢提示】：\n"
                f"系統嘗試連線中央氣象署開放資料平臺查詢即時資料，但目前出現連線或授權異常（{safe_err}）。\n"
                f"請以您當前人設親切告知使用者氣象署 API 暫時連線異常，並建議使用者稍後再次查詢。"
            )
            return {
                "tool_call_id": tool_call_id,
                "request_id": request_id,
                "intent_type": intent.intent_type.value,
                "grounding_prompt": fallback_grounding,
                "raw_data": {"error": safe_err},
                "data_tag": "UNTRUSTED_EXTERNAL_DATA",
            }


# Singleton service instance
cwa_service = CWAService()
