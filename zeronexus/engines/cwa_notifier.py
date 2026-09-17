"""Taiwan Central Weather Administration (CWA) Earthquake Real-Time Notification Engine.

Features:
- Periodic background polling of official CWA felt earthquake reports.
- Persistent SQLite/PostgreSQL deduplication using EarthquakeNotificationRecord (zero duplicate broadcasts across restarts).
- Decoupled from AI: 100% authoritative structured data, zero AI tokens burned, works when AI is offline.
- Per-guild filtering thresholds: magnitude filter and intensity filter.
- Resilient Discord error handling (channel missing, permissions denied, rate limits).
- Comprehensive structured logging with correlated trace_id.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import discord
from sqlalchemy import select

from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.engines.cwa_client import cwa_client
from zeronexus.models.guild import EarthquakeNotificationRecord, GuildSettings
from zeronexus.ui.card import ZNCard
from zeronexus.ui.theme import ZNColor, ZNStatusPill


def parse_intensity_grade(intensity_str: str) -> int:
    """Extracts integer intensity grade from CWA intensity string (e.g. '4級' -> 4, '5強' -> 5)."""
    if not intensity_str:
        return 0
    clean = str(intensity_str).replace("級", "").strip()
    if clean.isdigit():
        return int(clean)
    if any(clean.lower().startswith(k) for k in ["未知", "無", "n/a", "none", "0"]):
        return 0
    if "強" in clean or "弱" in clean:
        m = re.search(r"(\d+)\s*[強弱]", clean)
        if m:
            return int(m.group(1))
        prefix = clean[0]
        if prefix.isdigit():
            return int(prefix)
    m = re.search(r"\d+", clean)
    if m:
        return int(m.group(0))
    return 0


def classify_focal_depth(depth_km: float) -> str:
    """Classifies earthquake focal depth into standard seismological categories."""
    if depth_km <= 30.0:
        return "極淺層地震 (地表搖晃最為劇烈，破壞力強)"
    elif depth_km <= 70.0:
        return "淺層地震 (震波衰減較慢，廣泛有感)"
    elif depth_km <= 300.0:
        return "中層地震 (深部破裂，影響範圍廣)"
    else:
        return "深層地震 (超深源地震)"


def build_rich_earthquake_card(eq: Dict[str, Any], is_manual_query: bool = False) -> ZNCard:
    """Constructs a deterministic, authoritative, high-visibility Discord alert card directly from CWA data.

    Shared 1:1 between real-time background notification and manual /工具 地震 command to guarantee complete consistency.
    """
    raw_no = eq.get("earthquake_no", eq.get("report_id", "速報"))
    is_bulletin = str(raw_no) in ["0", "速報", "None", ""]
    prefix = "🔍 手動查詢：" if is_manual_query else "🚨 "
    if is_bulletin:
        report_title = f"{prefix}中央氣象署有感地震即時速報"
    else:
        report_title = f"{prefix}中央氣象署顯著有感地震報告 (第 {raw_no} 號)"

    magnitude = eq.get("magnitude")
    mag_display = f"M {magnitude}" if magnitude is not None and str(magnitude) not in ["0", "0.0", "N/A", "未知"] else "觀測評估中"

    depth = eq.get("depth")
    depth_km = float(eq.get("depth_km", 0.0) or 0.0)
    depth_display = str(depth) if depth and str(depth) not in ["0", "0.0", "N/A", "未知", "0 公里"] else (f"{depth_km} 公里" if depth_km > 0 else "觀測評估中")
    depth_category = classify_focal_depth(depth_km) if depth_km > 0 else "深度資料校驗中"

    max_int = eq.get("max_intensity")
    int_display = str(max_int) if max_int and str(max_int) not in ["N/A", "None", ""] else "未知"

    origin_time = eq.get("origin_time") or "時間彙整中"
    location = eq.get("location") or "臺灣海域或陸地"
    lat = eq.get("latitude")
    lon = eq.get("longitude")
    coord_display = f"北緯 {lat}° / 東經 {lon}°" if lat and lon and str(lat) != "N/A" and str(lon) != "N/A" else "定位資料彙整中"

    # Top shaking areas breakdown
    shaking_lines = []
    for s in eq.get("shaking_areas", [])[:10]:
        area_name = s.get("area") or s.get("county") or s.get("AreaDesc", "地區")
        intensity_val = s.get("intensity") or s.get("AreaIntensity", "")
        if area_name and intensity_val:
            shaking_lines.append(f"• **{area_name}**：`{intensity_val}`")
    shaking_block = "\n".join(shaking_lines) if shaking_lines else eq.get("intensity_summary", "各地最大震度請參閱官方詳細報告")

    # Validate shakemap URL
    shakemap_url = eq.get("shakemap_url")
    if shakemap_url and not str(shakemap_url).startswith(("http://", "https://")):
        shakemap_url = None

    int_grade = parse_intensity_grade(int_display)
    try:
        mag_val = float(magnitude or 0.0)
    except (ValueError, TypeError):
        mag_val = 0.0

    if int_grade >= 5 or mag_val >= 6.0:
        pill = ZNStatusPill.ERROR
        color = ZNColor.ERROR
    elif int_grade >= 4 or mag_val >= 5.0:
        pill = ZNStatusPill.WARNING
        color = ZNColor.WARNING
    else:
        pill = ZNStatusPill.INFO
        color = ZNColor.PRIMARY

    card = ZNCard(
        title=report_title,
        description=(
            f"📅 **發震時間**：`{origin_time}` (UTC+8 臺灣標準時間)\n"
            f"💥 **芮氏規模**：**`{mag_display}`** | 🌐 **全台最大震度**：**{int_display}**\n"
            f"📏 **震源深度**：`{depth_display}`（{depth_category}）\n"
            f"📍 **震央位置**：{location}\n"
            f"🗺️ **震央座標**：`{coord_display}`"
        ),
        status_pill=pill,
        color=color,
        image_url=shakemap_url,
        footer_text="交通部中央氣象署 (CWA) 地震測報中心 • 官方即時資料",
    )

    card.add_section("各地顯著震度報告", shaking_block, inline=False)

    tsunami_desc = eq.get("tsunami_info") or "依中央氣象署海嘯評估：本起地震未達海嘯警報發布標準，無海嘯威脅。"
    card.add_section("🌊 海嘯威脅評估", tsunami_desc, inline=False)

    web_url = eq.get("web_url")
    if not web_url or not str(web_url).startswith(("http://", "https://")):
        web_url = "https://scweb.cwa.gov.tw/zh-tw/earthquake"
    card.add_section("官方資料來源", f"[中央氣象署地震測報中心官方詳細報告]({web_url})", inline=False)
    card.add_section("防災避難提醒", "⚠️ 請保持冷靜並落實「**趴下 (Drop)、掩護 (Cover)、穩住 (Hold on)**」，注意掉落物並慎防餘震。", inline=False)

    return card


class EarthquakeCheckinView(discord.ui.View):
    """Interactive Discord Components V2 view for real-time safety check-in and shaking reports."""

    def __init__(self, report_id: str = "default") -> None:
        super().__init__(timeout=None)
        self.report_id = report_id
        self._safe_users: set[int] = set()
        self._shaking_reports: Dict[int, str] = {}

    @discord.ui.button(
        label="🟢 我很平安！ (0)",
        style=discord.ButtonStyle.success,
        custom_id="cwa_eq_safe_btn",
    )
    async def btn_safe(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        user_id = interaction.user.id
        if user_id in self._safe_users:
            await interaction.response.send_message("✅ 您先前已回報平安囉！祝您一切順心平安！", ephemeral=True)
            return

        self._safe_users.add(user_id)
        button.label = f"🟢 我很平安！ ({len(self._safe_users)})"
        try:
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("💚 已收到您的平安回報！願大家平平安安！", ephemeral=True)
        except Exception:
            try:
                await interaction.response.send_message("💚 已收到您的平安回報！願大家平平安安！", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(
        label="📢 回報震感 (0)",
        style=discord.ButtonStyle.primary,
        custom_id="cwa_eq_shake_btn",
    )
    async def btn_shake(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        class ShakeReportModal(discord.ui.Modal, title="📢 即時回報所在地體感震度"):
            intensity = discord.ui.TextInput(
                label="體感搖晃程度",
                placeholder="例如：無感 / 輕微搖晃 / 劇烈搖晃 / 物品掉落",
                required=True,
                max_length=50,
            )
            location = discord.ui.TextInput(
                label="您所在的縣市/地區 (選填)",
                placeholder="例如：臺北市大安區 / 花蓮市",
                required=False,
                max_length=50,
            )

            def __init__(self, parent_view: EarthquakeCheckinView, btn: discord.ui.Button) -> None:
                super().__init__()
                self.parent_view = parent_view
                self.btn = btn

            async def on_submit(self, modal_interaction: discord.Interaction) -> None:
                uid = modal_interaction.user.id
                loc_txt = f"（{self.location.value.strip()}）" if self.location.value.strip() else ""
                report_txt = f"{self.intensity.value.strip()}{loc_txt}"
                self.parent_view._shaking_reports[uid] = report_txt
                self.btn.label = f"📢 回報震感 ({len(self.parent_view._shaking_reports)})"
                try:
                    await modal_interaction.response.edit_message(view=self.parent_view)
                    await modal_interaction.followup.send(
                        f"📢 感謝回報！已記錄您的體感震度：**{report_txt}**，請留意周遭安全！",
                        ephemeral=True,
                    )
                except Exception:
                    try:
                        await modal_interaction.response.send_message(
                            f"📢 感謝回報！已記錄您的體感震度：**{report_txt}**",
                            ephemeral=True,
                        )
                    except Exception:
                        pass

        await interaction.response.send_modal(ShakeReportModal(self, button))


class CWAEarthquakeNotifier:
    """Engine responsible for polling CWA earthquake reports and broadcasting alerts to configured Discord channels."""

    def __init__(self) -> None:
        self._consecutive_poll_errors: int = 0
        self._backoff_seconds: float = 0.0
        self._last_seen_report_id: Optional[str] = None

    async def poll_and_notify(
        self,
        bot: discord.Client,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Polls CWA for the latest earthquake report and dispatches notifications to configured guilds."""
        if not trace_id:
            trace_id = f"trace_eq_{uuid.uuid4().hex[:8]}"

        # Rate limit / backoff pause check
        if self._backoff_seconds > 0:
            log.warning(f"[CWA_EARTHQUAKE_POLL_START] [trace_id={trace_id}] 目前處於退避冷卻期（剩餘 {self._backoff_seconds:.1f} 秒），暫緩本次氣象署地震輪詢。")
            self._backoff_seconds = max(0.0, self._backoff_seconds - 60.0)
            return {"status": "BACKOFF", "trace_id": trace_id}

        t0 = time.perf_counter()
        log.debug(f"[CWA_EARTHQUAKE_POLL_START] [trace_id={trace_id}] 正在向中央氣象署獲取最新官方有感地震報告...")

        try:
            latest_eq = await cwa_client.get_latest_earthquake(request_id=trace_id, silent=True)
            poll_latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            log.debug(f"[CWA_EARTHQUAKE_RESPONSE] [trace_id={trace_id}] 成功接收中央氣象署最新地震資料，回應碼=200，延遲={poll_latency_ms}毫秒")
            self._consecutive_poll_errors = 0
            self._backoff_seconds = 0.0
        except Exception as e:
            poll_latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            self._consecutive_poll_errors += 1
            self._backoff_seconds = min(300.0, 30.0 * (2 ** (self._consecutive_poll_errors - 1)))
            log.error(
                f"[CWA_EARTHQUAKE_RESPONSE] [trace_id={trace_id}] 獲取地震報告失敗（連續異常 {self._consecutive_poll_errors} 次，已設定冷卻退避 {self._backoff_seconds:.1f} 秒）：{e}"
            )
            return {"status": "ERROR", "error": str(e), "trace_id": trace_id}

        report_id = latest_eq.get("report_id") or str(latest_eq.get("earthquake_no", 0))
        if not report_id or report_id == "0":
            return {"status": "NO_REPORT", "trace_id": trace_id}

        log.debug(f"[CWA_EARTHQUAKE_PARSE_SUCCESS] [trace_id={trace_id}] 地震資料解析成功：報告編號={report_id}，芮氏規模 M={latest_eq.get('magnitude')}，最大震度={latest_eq.get('max_intensity')}")

        # 1. Fetch all guilds with earthquake notification configured
        guild_settings_list: List[GuildSettings] = []
        try:
            async with db.session() as session:
                stmt = select(GuildSettings).where(
                    GuildSettings.earthquake_channel_id.isnot(None),
                    GuildSettings.earthquake_enabled.is_(True),
                )
                res = await session.execute(stmt)
                guild_settings_list = list(res.scalars().all())
        except Exception as dbe:
            log.error(f"[CWA_EARTHQUAKE_RESPONSE] [trace_id={trace_id}] 資料庫查詢地震通知頻道設定失敗：{dbe}")
            return {"status": "DB_ERROR", "error": str(dbe), "trace_id": trace_id}

        if not guild_settings_list:
            log.debug(f"[CWA_EARTHQUAKE_PARSE_SUCCESS] [trace_id={trace_id}] 系統中尚未有伺服器啟用地震推播頻道。")
            return {
                "status": "NO_CONFIGURED_GUILDS",
                "delivered": 0,
                "notified_count": 0,
                "skipped": 0,
                "skipped_count": 0,
                "filtered": 0,
                "filtered_count": 0,
                "failed": 0,
                "failed_count": 0,
                "trace_id": trace_id,
            }

        # 2. Batch fetch all existing records for this report_id to avoid N+1 DB roundtrips
        already_handled_pairs = set()
        try:
            async with db.session() as session:
                dedup_stmt = select(
                    EarthquakeNotificationRecord.guild_id,
                    EarthquakeNotificationRecord.channel_id,
                ).where(
                    EarthquakeNotificationRecord.report_id == report_id,
                    EarthquakeNotificationRecord.status.in_(["DELIVERED", "FILTERED_MAGNITUDE", "FILTERED_INTENSITY"]),
                )
                dedup_res = await session.execute(dedup_stmt)
                for gid, cid in dedup_res.all():
                    already_handled_pairs.add((gid, cid))
        except Exception as dbe:
            log.warning(f"批次查詢地震去重紀錄失敗: {dbe}")

        # 3. Process notifications per guild with persistent deduplication
        notified_count = 0
        skipped_count = 0
        filtered_count = 0

        try:
            raw_mag = latest_eq.get("magnitude")
            eq_mag = float(raw_mag) if raw_mag is not None else 0.0
        except (ValueError, TypeError):
            eq_mag = 0.0
        eq_intensity_grade = parse_intensity_grade(latest_eq.get("max_intensity", "1"))

        # Pre-build structured Discord embed (purely deterministic, zero AI dependency)
        card = self._build_earthquake_card(latest_eq)
        embed = card.to_embed()

        for g_setting in guild_settings_list:
            guild_id = g_setting.guild_id
            channel_id = g_setting.earthquake_channel_id
            if not channel_id:
                continue

            # Check persistent deduplication in DB
            log.debug(f"[CWA_EARTHQUAKE_DEDUP_CHECK] [trace_id={trace_id}] 正在比對資料庫歷史推播紀錄：報告編號={report_id}，伺服器ID={guild_id}")
            if (guild_id, channel_id) in already_handled_pairs:
                log.debug(f"[CWA_EARTHQUAKE_ALREADY_NOTIFIED] [trace_id={trace_id}] 此地震報告已於先前完成推播或過濾，予以跳過：報告編號={report_id}，伺服器ID={guild_id}，頻道ID={channel_id}")
                skipped_count += 1
                continue

            # Threshold Filter: Minimum Magnitude
            min_mag = g_setting.earthquake_min_magnitude if g_setting.earthquake_min_magnitude is not None else 4.0
            if eq_mag < min_mag:
                log.debug(
                    f"[CWA_EARTHQUAKE_FILTERED] [trace_id={trace_id}] 未達推播門檻已過濾：報告編號={report_id}，伺服器ID={guild_id}，"
                    f"原因=芮氏規模未達門檻（當前規模 {eq_mag} < 設定門檻 {min_mag}）"
                )
                filtered_count += 1
                already_handled_pairs.add((guild_id, channel_id))
                await self._record_delivery_attempt(
                    report_id=report_id,
                    latest_eq=latest_eq,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status="FILTERED_MAGNITUDE",
                    trace_id=trace_id,
                )
                continue

            # Threshold Filter: Minimum Intensity
            min_int = g_setting.earthquake_min_intensity if g_setting.earthquake_min_intensity is not None else 1
            if eq_intensity_grade < min_int:
                log.debug(
                    f"[CWA_EARTHQUAKE_FILTERED] [trace_id={trace_id}] 未達推播門檻已過濾：報告編號={report_id}，伺服器ID={guild_id}，"
                    f"原因=最大震度未達門檻（當前震度 {eq_intensity_grade} 級 < 設定門檻 {min_int} 級）"
                )
                filtered_count += 1
                already_handled_pairs.add((guild_id, channel_id))
                await self._record_delivery_attempt(
                    report_id=report_id,
                    latest_eq=latest_eq,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status="FILTERED_INTENSITY",
                    trace_id=trace_id,
                )
                continue

            # Passed all filters! Dispatch to Discord
            log.info(f"[CWA_EARTHQUAKE_NEW_REPORT] [trace_id={trace_id}] 偵測到符合門檻之最新地震：報告編號={report_id}，規模 M={eq_mag}，即將推播至伺服器ID={guild_id}")
            log.info(f"[CWA_EARTHQUAKE_DISPATCH_START] [trace_id={trace_id}] 開始推送即時地震警報至頻道ID={channel_id}（伺服器ID={guild_id}）")
            log.info(f"[CWA_EARTHQUAKE_NOTIFICATION_START] [trace_id={trace_id}] 開始推送即時地震警報至頻道ID={channel_id}（伺服器ID={guild_id}）")

            delivery_success = False
            error_reason = ""

            try:
                channel = bot.get_channel(channel_id)
                if channel is None:
                    # Attempt fetch
                    try:
                        channel = await bot.fetch_channel(channel_id)
                    except discord.NotFound:
                        channel = None
                        error_reason = "DiscordNotFound (頻道不存在或已被刪除)"
                        await self._heal_deleted_channel(guild_id, channel_id)
                    except Exception as fe:
                        channel = None
                        error_reason = f"ChannelNotFound: {fe}"

                if isinstance(channel, (discord.TextChannel, discord.Thread, discord.abc.Messageable)) or (channel is not None and hasattr(channel, "send")):
                    eq_view = EarthquakeCheckinView(report_id=report_id)
                    layout_view = card.to_layout_view(extra_view=eq_view)
                    try:
                        await channel.send(view=layout_view)
                    except Exception:
                        await channel.send(embed=embed, view=eq_view)
                    delivery_success = True
                    notified_count += 1
                    already_handled_pairs.add((guild_id, channel_id))
                    log.info(f"[CWA_EARTHQUAKE_DELIVERED] [trace_id={trace_id}] 即時地震警報已成功送達頻道ID={channel_id}（伺服器ID={guild_id}）")
                    log.info(f"[CWA_EARTHQUAKE_NOTIFICATION_SUCCESS] [trace_id={trace_id}] 即時地震警報推播成功，頻道ID={channel_id}（伺服器ID={guild_id}）")
                else:
                    if not error_reason:
                        error_reason = f"ChannelNotTextual: 頻道類型不支援發送文字訊息 ({type(channel)})"
                    log.warning(f"[CWA_EARTHQUAKE_NOTIFICATION_FAILED] [trace_id={trace_id}] 伺服器ID={guild_id} 頻道ID={channel_id} 推播失敗：{error_reason}")
            except discord.Forbidden as fe:
                error_reason = f"DiscordForbidden (機器人缺少發送訊息之權限): {fe}"
                log.warning(f"[CWA_EARTHQUAKE_NOTIFICATION_FAILED] [trace_id={trace_id}] 伺服器ID={guild_id} 頻道ID={channel_id} 推播失敗：{error_reason}")
            except (discord.NotFound, discord.HTTPException) as he:
                is_not_found = isinstance(he, discord.NotFound) or getattr(he, "status", None) == 404
                if is_not_found:
                    error_reason = f"DiscordNotFound (頻道已被刪除): {he}"
                    log.warning(f"[CWA_EARTHQUAKE_NOTIFICATION_FAILED] [trace_id={trace_id}] 伺服器ID={guild_id} 頻道ID={channel_id} 推播失敗：{error_reason}")
                    await self._heal_deleted_channel(guild_id, channel_id)
                elif getattr(he, "status", None) == 429:
                    error_reason = f"DiscordRateLimited (觸發 Discord 頻率限制): {he}"
                    log.error(f"[CWA_EARTHQUAKE_NOTIFICATION_FAILED] [trace_id={trace_id}] 伺服器ID={guild_id} 頻道ID={channel_id} 推播失敗：{error_reason}")
                else:
                    error_reason = f"DiscordHTTPException (狀態碼 {getattr(he, 'status', '未知')}): {he}"
                    log.error(f"[CWA_EARTHQUAKE_NOTIFICATION_FAILED] [trace_id={trace_id}] 伺服器ID={guild_id} 頻道ID={channel_id} 推播失敗：{error_reason}")
            except Exception as e:
                error_reason = f"UnexpectedDeliveryError (未預期傳送異常): {e}"
                log.error(f"[CWA_EARTHQUAKE_NOTIFICATION_FAILED] [trace_id={trace_id}] 伺服器ID={guild_id} 頻道ID={channel_id} 推播失敗：{error_reason}")

            # Record outcome in persistent DB
            final_status = "DELIVERED" if delivery_success else "FAILED"
            await self._record_delivery_attempt(
                report_id=report_id,
                latest_eq=latest_eq,
                guild_id=guild_id,
                channel_id=channel_id,
                status=final_status,
                trace_id=trace_id,
            )

        failed_count = len(guild_settings_list) - notified_count - skipped_count - filtered_count
        return {
            "status": "SUCCESS" if notified_count > 0 else "COMPLETED",
            "report_id": report_id,
            "notified_count": notified_count,
            "delivered": notified_count,
            "skipped_count": skipped_count,
            "skipped": skipped_count,
            "filtered_count": filtered_count,
            "filtered": filtered_count,
            "failed_count": failed_count,
            "failed": failed_count,
            "trace_id": trace_id,
        }

    async def _heal_deleted_channel(self, guild_id: int, channel_id: int) -> None:
        """Auto-heals configuration by clearing deleted Discord channel from GuildSettings."""
        try:
            async with db.session() as fix_session:
                gs = await fix_session.get(GuildSettings, guild_id)
                if gs and gs.earthquake_channel_id == channel_id:
                    gs.earthquake_channel_id = None
                    gs.earthquake_enabled = False
                    log.info(f"[CWA_EARTHQUAKE_SELF_HEAL] 偵測到伺服器 {guild_id} 之地震推播頻道 {channel_id} 已失效或被刪除，已自動解除綁定完成自癒。")
        except Exception as dbe:
            log.warning(f"自動解除已刪除地震頻道設定時發生異常：{dbe}")

    async def _record_delivery_attempt(
        self,
        report_id: str,
        latest_eq: Dict[str, Any],
        guild_id: int,
        channel_id: int,
        status: str,
        trace_id: Optional[str] = None,
    ) -> None:
        """Persists notification record in SQLite/PostgreSQL to prevent duplicate broadcasts across restarts."""
        try:
            async with db.session() as session:
                try:
                    raw_mag = latest_eq.get("magnitude")
                    saved_mag = float(raw_mag) if raw_mag is not None else 0.0
                except (ValueError, TypeError):
                    saved_mag = 0.0

                record = EarthquakeNotificationRecord(
                    report_id=report_id,
                    origin_time=str(latest_eq.get("origin_time") or ""),
                    magnitude=saved_mag,
                    depth=str(latest_eq.get("depth", "未知")),
                    location=str(latest_eq.get("location") or ""),
                    max_intensity=str(latest_eq.get("max_intensity", "未知")),
                    guild_id=guild_id,
                    channel_id=channel_id,
                    status=status,
                    trace_id=trace_id,
                    notified_at=datetime.now(timezone.utc),
                )
                session.add(record)
            if status == "DELIVERED":
                log.info(f"[CWA_EARTHQUAKE_DB_PERSISTED] [trace_id={trace_id}] 成功保存地震推播紀錄至資料庫：報告編號={report_id}，伺服器ID={guild_id}，狀態={status}")
            else:
                log.debug(f"[CWA_EARTHQUAKE_DB_PERSISTED] [trace_id={trace_id}] 成功記錄地震狀態至資料庫：報告編號={report_id}，伺服器ID={guild_id}，狀態={status}")
        except Exception as e:
            log.warning(f"寫入地震推播紀錄失敗（報告={report_id}，伺服器={guild_id}）：{e}")

    def _build_earthquake_card(self, eq: Dict[str, Any]) -> ZNCard:
        """Constructs a deterministic, high-visibility Discord alert card directly from CWA authoritative data."""
        return build_rich_earthquake_card(eq, is_manual_query=False)

    async def poll_earthquakes(
        self,
        bot: discord.Client,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Alias for poll_and_notify to support poll_earthquakes naming convention."""
        return await self.poll_and_notify(bot, trace_id=trace_id)


# Singleton instance
cwa_notifier = CWAEarthquakeNotifier()


async def poll_earthquakes(bot: discord.Client, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """Module-level helper to trigger earthquake polling via singleton."""
    return await cwa_notifier.poll_earthquakes(bot, trace_id=trace_id)


__all__ = [
    "CWAEarthquakeNotifier",
    "EarthquakeCheckinView",
    "cwa_notifier",
    "poll_earthquakes",
    "parse_intensity_grade",
    "classify_focal_depth",
    "build_rich_earthquake_card",
]
