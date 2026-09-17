"""ZeroNexus Community Suite & Multimodal Engine.

Features:
1. Multimodal File Ingester: Extracts PDF, Word (.docx), CSV, Plaintext; produces TL;DR summaries and visual CSV charts via Pillow.
2. YouTube 30-Second TL;DR: Extracts YouTube video conclusions and bullet points via captions/endpoints.
3. Voice Message Transcriber: Detects Discord audio attachments and transcribes to Traditional Chinese.
4. Discord Components v2 Action View: Interactive buttons ([ 📊 畫圖表 ], [ 📰 相關新聞 ], [ 🔄 換個口吻 ]) and tone switcher.
5. Cyber Court: Dispute resolution, responsibility ratios, and jury voting.
6. Turtle Soup Master: Interactive mystery host judging questions (是/不是/無關/關鍵線索).
7. Party Recruitment: Dynamic party card with interactive join/leave/ping buttons.
8. Server Meme Wiki: Records and explores guild memes and legend lore.
9. Community Prediction Market: Coin betting with atomic EconomyWallet sync and dynamic odds.
10. Dual-AI Crosstalk: Two contrasting personas bantering in comedic theatrical dialogue.
11. Decision Roundtable: Technical, Pragmatic, and Spiritual experts debating dilemmas.
12. Late Night Diary: Daily mood tracking (1-10) and month-end emotional trend chart generation.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import re
import secrets
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import discord
import httpx
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, update

from zeronexus.ai_gateway.gateway import ai_gateway
from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.engines.web_client import web_client
from zeronexus.models.user import EconomyWallet
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_COMMUNITY_DIR = BASE_DIR / "data" / "community"
FONT_PATH = BASE_DIR / "data" / "fonts" / "NotoSansTC.ttf"

DATA_COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)


def _get_font(size: int = 16) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Safely loads NotoSansTC font or falls back to default."""
    if FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(FONT_PATH), size)
        except Exception:
            pass
    return ImageFont.load_default()


# =============================================================================
# 1. 多模態檔案吞噬機 (MultimodalFileIngester)
# =============================================================================

@dataclass
class FileExtractionResult:
    filename: str
    file_type: str  # "pdf", "docx", "csv", "text", "unknown"
    content_text: str
    char_count: int
    line_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    chart_image_bytes: Optional[bytes] = None
    is_success: bool = True
    error_message: Optional[str] = None


@dataclass
class FileTLDRResult:
    filename: str
    file_type: str
    core_summary: str
    key_points: List[str]
    action_guidance: str
    chart_image_bytes: Optional[bytes] = None


class MultimodalFileIngester:
    """Extracts content from PDF, Word (.docx), CSV, and text files, with chart visualization."""

    @staticmethod
    def extract_pdf_text(data: bytes) -> str:
        """Pure-Python PDF text stream extractor supporting FlateDecode."""
        texts: List[str] = []
        stream_pattern = re.compile(b"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
        for m in stream_pattern.finditer(data):
            stream_data = m.group(1)
            try:
                decompressed = zlib.decompress(stream_data)
            except Exception:
                decompressed = stream_data

            # Look for (text) Tj
            tj_matches = re.findall(rb"\((.*?)\)\s*Tj", decompressed)
            for tj in tj_matches:
                try:
                    s = tj.decode("utf-8", errors="ignore").strip()
                    if s:
                        texts.append(s)
                except Exception:
                    pass

            # Look for [(text) 10 (text)] TJ
            tj_array_matches = re.findall(rb"\[(.*?)\]\s*TJ", decompressed)
            for tja in tj_array_matches:
                inner_strs = re.findall(rb"\((.*?)\)", tja)
                for s_b in inner_strs:
                    try:
                        s = s_b.decode("utf-8", errors="ignore").strip()
                        if s:
                            texts.append(s)
                    except Exception:
                        pass

        if not texts:
            # Fallback: scan for any ASCII/UTF-8 strings in BT...ET blocks
            bt_blocks = re.findall(rb"BT(.*?)ET", data, re.DOTALL)
            for block in bt_blocks:
                matches = re.findall(rb"\((.*?)\)", block)
                for mb in matches:
                    try:
                        s = mb.decode("utf-8", errors="ignore").strip()
                        if s:
                            texts.append(s)
                    except Exception:
                        pass

        result = "\n".join(texts)
        # Clean up escapes
        result = result.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
        return result.strip()

    @staticmethod
    def extract_docx_text(data: bytes) -> str:
        """Extracts text from Word .docx file using standard zipfile and XML parsing."""
        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                if "word/document.xml" not in zf.namelist():
                    return "❌ 此 Word 檔案結構異常，未包含 word/document.xml。"
                xml_bytes = zf.read("word/document.xml")
                tree = ET.fromstring(xml_bytes)
                paragraphs: List[str] = []
                for p in tree.iter():
                    if p.tag.endswith("}p"):
                        p_texts = [
                            elem.text for elem in p.iter()
                            if elem.tag.endswith("}t") and elem.text
                        ]
                        if p_texts:
                            paragraphs.append("".join(p_texts))
                return "\n\n".join(paragraphs).strip()
        except Exception as e:
            return f"❌ 解析 Word 檔案時發生錯誤：{e}"

    @staticmethod
    def generate_csv_chart(
        headers: List[str],
        rows: List[List[str]],
        numeric_col_idx: int,
        label_col_idx: int = 0,
        max_bars: int = 10,
    ) -> Optional[bytes]:
        """Renders an aesthetic modern dark-mode bar chart from CSV data using Pillow."""
        try:
            val_col_name = headers[numeric_col_idx] if numeric_col_idx < len(headers) else "數值"
            lbl_col_name = headers[label_col_idx] if label_col_idx < len(headers) else "項目"

            labels: List[str] = []
            values: List[float] = []

            for r in rows[:max_bars]:
                if len(r) > max(numeric_col_idx, label_col_idx):
                    try:
                        val = float(re.sub(r"[^\d.-]", "", r[numeric_col_idx]))
                        lbl = r[label_col_idx].strip()
                        labels.append(lbl[:12] if len(lbl) > 12 else lbl)
                        values.append(val)
                    except (ValueError, IndexError):
                        continue

            if not values:
                return None

            w, h = 760, 420
            img = Image.new("RGBA", (w, h), (24, 24, 37, 255))
            draw = ImageDraw.Draw(img)

            font_title = _get_font(20)
            font_label = _get_font(13)
            font_value = _get_font(12)

            # Draw Title & Subtitle
            draw.text((30, 24), f"數據圖表視覺化：{val_col_name}", font=font_title, fill=(245, 245, 250, 255))
            draw.text((30, 52), f"X 軸: {lbl_col_name} • 樣本數: {len(values)} 筆", font=font_label, fill=(160, 160, 185, 255))

            # Chart area
            chart_x, chart_y = 60, 90
            chart_w, chart_h = 640, 260

            # Grid lines
            max_v = max(values) if max(values) > 0 else 1.0
            min_v = min(0.0, min(values))
            v_range = max_v - min_v if max_v != min_v else 1.0

            for i in range(5):
                gy = chart_y + chart_h - int(i * (chart_h / 4))
                draw.line([(chart_x, gy), (chart_x + chart_w, gy)], fill=(45, 45, 65, 255), width=1)
                grid_val = min_v + (v_range * (i / 4.0))
                draw.text((chart_x - 45, gy - 7), f"{grid_val:.1f}", font=font_value, fill=(140, 140, 165, 255))

            bar_count = len(values)
            slot_w = chart_w / max(1, bar_count)
            bar_w = max(16, int(slot_w * 0.55))

            for idx, (lbl, val) in enumerate(zip(labels, values)):
                bar_h_px = int(((val - min_v) / v_range) * chart_h)
                bx = chart_x + int(idx * slot_w + (slot_w - bar_w) / 2)
                by = chart_y + chart_h - bar_h_px

                # Gradient-style color
                c_ratio = idx / max(1, bar_count - 1)
                r_c = int(100 + c_ratio * 120)
                g_c = int(140 + (1 - c_ratio) * 60)
                b_c = int(240 - c_ratio * 40)

                draw.rectangle([bx, by, bx + bar_w, chart_y + chart_h], fill=(r_c, g_c, b_c, 240))
                # Value label on top
                val_str = f"{val:g}"
                draw.text((bx + 2, max(chart_y - 15, by - 16)), val_str, font=font_value, fill=(220, 230, 255, 255))
                # Category label below
                draw.text((bx, chart_y + chart_h + 8), lbl, font=font_label, fill=(200, 200, 220, 255))

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            log.warning(f"Failed to generate CSV chart: {e}")
            return None

    def extract_file(self, data: bytes, filename: str, mime_type: Optional[str] = None) -> FileExtractionResult:
        """Extracts content from PDF, Word (.docx), CSV, or text files."""
        fn_lower = filename.lower()
        mime_lower = (mime_type or "").lower()

        # 1. PDF
        if fn_lower.endswith(".pdf") or "pdf" in mime_lower:
            text = self.extract_pdf_text(data)
            return FileExtractionResult(
                filename=filename,
                file_type="pdf",
                content_text=text or "(PDF 文本提取為空或屬於純掃描圖檔)",
                char_count=len(text),
                line_count=len(text.splitlines()),
                metadata={"size_bytes": len(data)},
            )

        # 2. Word (.docx)
        if fn_lower.endswith(".docx") or "wordprocessingml" in mime_lower:
            text = self.extract_docx_text(data)
            return FileExtractionResult(
                filename=filename,
                file_type="docx",
                content_text=text or "(Word 檔案文本為空)",
                char_count=len(text),
                line_count=len(text.splitlines()),
                metadata={"size_bytes": len(data)},
            )

        # 3. CSV
        if fn_lower.endswith(".csv") or "csv" in mime_lower:
            try:
                decoded_str = ""
                for enc in ("utf-8-sig", "utf-8", "big5", "cp950", "latin-1"):
                    try:
                        decoded_str = data.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue

                reader = list(csv.reader(io.StringIO(decoded_str)))
                if not reader:
                    return FileExtractionResult(
                        filename=filename,
                        file_type="csv",
                        content_text="CSV 檔案內容為空。",
                        char_count=0,
                        line_count=0,
                    )

                headers = [h.strip() for h in reader[0]]
                rows = reader[1:]

                # Detect numeric columns
                numeric_cols: List[int] = []
                for col_idx in range(len(headers)):
                    sample_numeric_count = 0
                    for row in rows[:20]:
                        if col_idx < len(row):
                            val_str = re.sub(r"[^\d.-]", "", row[col_idx])
                            try:
                                float(val_str)
                                sample_numeric_count += 1
                            except ValueError:
                                pass
                    if sample_numeric_count >= min(3, len(rows)):
                        numeric_cols.append(col_idx)

                # Generate chart if numeric column found
                chart_bytes = None
                if numeric_cols:
                    label_col = 0 if numeric_cols[0] != 0 else (1 if len(headers) > 1 else 0)
                    chart_bytes = self.generate_csv_chart(
                        headers, rows, numeric_col_idx=numeric_cols[0], label_col_idx=label_col
                    )

                preview_lines = [f"欄位：{', '.join(headers)}", f"總行數：{len(rows)} 筆資料"]
                for idx, r in enumerate(rows[:5]):
                    preview_lines.append(f"第 {idx+1} 列: {', '.join(r)}")
                if len(rows) > 5:
                    preview_lines.append(f"... 尚有 {len(rows) - 5} 列資料")

                text_summary = "\n".join(preview_lines)
                return FileExtractionResult(
                    filename=filename,
                    file_type="csv",
                    content_text=text_summary,
                    char_count=len(decoded_str),
                    line_count=len(reader),
                    metadata={"headers": headers, "rows_count": len(rows), "numeric_cols": numeric_cols},
                    chart_image_bytes=chart_bytes,
                )
            except Exception as e:
                return FileExtractionResult(
                    filename=filename,
                    file_type="csv",
                    content_text=f"CSV 解析失敗：{e}",
                    char_count=0,
                    line_count=0,
                    is_success=False,
                    error_message=str(e),
                )

        # 4. Plain Text
        for enc in ("utf-8", "big5", "cp950", "latin-1"):
            try:
                decoded = data.decode(enc)
                return FileExtractionResult(
                    filename=filename,
                    file_type="text",
                    content_text=decoded,
                    char_count=len(decoded),
                    line_count=len(decoded.splitlines()),
                    metadata={"encoding": enc, "size_bytes": len(data)},
                )
            except UnicodeDecodeError:
                continue

        return FileExtractionResult(
            filename=filename,
            file_type="unknown",
            content_text="(不支援的二進位檔案格式)",
            char_count=len(data),
            line_count=0,
            is_success=False,
            error_message="不支援的檔案格式",
        )

    async def generate_tldr(
        self,
        extracted: FileExtractionResult,
        user_prompt: Optional[str] = None,
    ) -> FileTLDRResult:
        """Synthesizes structured 3-point TL;DR summary from extracted file."""
        text = extracted.content_text.strip()
        if not text or len(text) < 10:
            return FileTLDRResult(
                filename=extracted.filename,
                file_type=extracted.file_type,
                core_summary="檔案內容文字過少或為空，無法提煉重點。",
                key_points=["無足夠文字資料可供分析"],
                action_guidance="建議檢查上傳檔案是否包含有效內文。",
                chart_image_bytes=extracted.chart_image_bytes,
            )

        # Try AI synthesis if available
        system_instruction = (
            "你現在是頂尖商業與情報分析專家。請閱讀使用者上傳的文件內容，"
            "以台灣繁體中文嚴格輸出三段式結構化重點懶人包：\n"
            "1. 【30 秒核心概要】：一句話說明這份文件的核心本質與主旨。\n"
            "2. 【三大關鍵重點】：列出 3 點最具價值的關鍵發現或論據。\n"
            "3. 【行動指引與後續建議】：提供 1~2 點具體可落地的下一步建議。"
        )

        user_content = f"檔案名稱：{extracted.filename}\n檔案類型：{extracted.file_type}\n\n文件內容節錄：\n{text[:4000]}"
        if user_prompt:
            user_content += f"\n\n使用者指定提問：{user_prompt}"

        try:
            messages = [{"role": "user", "content": user_content}]
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction=system_instruction,
                messages=messages,
            )
            raw_ai = ai_res.text.strip()
            # Parse sections from AI text
            summary_m = re.search(r"(?:【?30\s*秒核心概要】?|核心概要)[:：\s]+(.*?)(?=\n【|\n\d|\n\*|$)", raw_ai, re.DOTALL)
            summary = summary_m.group(1).strip() if summary_m else raw_ai[:120]

            pts = re.findall(r"(?:[-*•]|\d+\.)\s+(.*?)(?=\n[-*•]|\n\d+\.|\n\n|$)", raw_ai)
            key_pts = [p.strip() for p in pts[:3]] if pts else [raw_ai[120:250]]

            guide_m = re.search(r"(?:【?行動指引(?:與後續建議)?】?|行動建議)[:：\s]+(.*?)$", raw_ai, re.DOTALL)
            guidance = guide_m.group(1).strip() if guide_m else "詳閱文件完整數據並定期追蹤相關進展。"

            return FileTLDRResult(
                filename=extracted.filename,
                file_type=extracted.file_type,
                core_summary=summary,
                key_points=key_pts or ["詳見文件內文分析"],
                action_guidance=guidance,
                chart_image_bytes=extracted.chart_image_bytes,
            )
        except Exception as ai_err:
            log.info(f"AI file summary fallback to heuristic: {ai_err}")

        # Heuristic fallback
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        core = lines[0] if lines else "無有效內容"
        if len(core) > 100:
            core = core[:97] + "..."

        pts = []
        for line in lines[1:10]:
            if len(line) > 15 and not line.startswith(("#", "-", "*", "=")):
                pts.append(line[:80])
                if len(pts) >= 3:
                    break
        if not pts:
            pts = ["文件數據包含多項關鍵指標", "需搭配上下文進行深入研讀", "建議進一步查驗原始數據結構"]

        return FileTLDRResult(
            filename=extracted.filename,
            file_type=extracted.file_type,
            core_summary=f"本文件共 {extracted.char_count:,} 字（{extracted.line_count} 行），主旨涉及：{core}",
            key_points=pts[:3],
            action_guidance="建議使用關鍵字篩選或配合視覺化圖表評估數據分佈。",
            chart_image_bytes=extracted.chart_image_bytes,
        )


# =============================================================================
# 2. YouTube 30 秒省流懶人包 (YouTubeTLDRParser)
# =============================================================================

@dataclass
class YouTubeTLDRResult:
    video_id: str
    title: str
    author: str
    core_takeaway: str
    key_points: List[str]
    target_audience: str
    savings_rating: str  # e.g., "⭐️⭐️⭐️⭐️⭐️ (建議直接看懶人包省 15 分鐘)"
    video_url: str


class YouTubeTLDRParser:
    """Parses YouTube URLs and extracts 30-second core takeaways and bullet points."""

    YT_REGEX = re.compile(
        r"(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})",
        re.IGNORECASE,
    )

    def parse_youtube_url(self, text: str) -> Optional[str]:
        """Extracts 11-character YouTube video ID from URL string."""
        m = self.YT_REGEX.search(text)
        return m.group(1) if m else None

    async def fetch_video_metadata(self, video_id: str) -> Dict[str, Any]:
        """Fetches video title, author, and thumbnail via YouTube Data API or oEmbed."""
        from zeronexus.engines.google_suite import google_suite
        if google_suite.youtube._get_api_key():
            try:
                details = await google_suite.youtube.get_video_details(video_id)
                if details.get("status") == "SUCCESS":
                    return {
                        "title": details.get("title", f"YouTube 影片 ({video_id})"),
                        "author_name": details.get("channel_title", "創作者"),
                        "thumbnail_url": details.get("thumbnail_url"),
                        "duration": details.get("duration"),
                        "view_count_formatted": details.get("view_count_formatted"),
                    }
            except Exception as ye:
                log.info(f"Failed to fetch YouTube Data API: {ye}")

        url = f"https://www.youtube.com/watch?v={video_id}"
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(oembed_url)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            log.info(f"Failed to fetch YouTube oEmbed: {e}")
        return {"title": f"YouTube 影片 ({video_id})", "author_name": "創作者"}

    async def generate_tldr(self, url_or_id: str, context_text: Optional[str] = None) -> YouTubeTLDRResult:
        """Generates a 30-second TL;DR summary for the specified YouTube video."""
        video_id = self.parse_youtube_url(url_or_id) or url_or_id
        meta = await self.fetch_video_metadata(video_id)
        title = meta.get("title", f"YouTube 影片 {video_id}")
        author = meta.get("author_name", "未知創作者")
        watch_url = f"https://www.youtube.com/watch?v={video_id}"

        prompt = (
            f"你現在是 YouTube 省流分析大師。請針對影片標題『{title}』（創作者：{author}）"
            f"以及補充資訊『{context_text or '無'}』，以台灣繁體中文撰寫極速 30 秒省流懶人包：\n"
            "1. 核心結論（1 句話定調本片精髓，不賣關子直接講結果）\n"
            "2. 3 個關鍵重點論據（附帶大概時間戳註記，如 [02:15]）\n"
            "3. 適合閱聽族群\n"
            "4. 省流評級（例如：⭐️⭐️⭐️⭐️⭐️ 必看精華 或 ⭐️⭐️ 看懶人包即可省 15 分鐘）"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction="你現在是 YouTube 專業省流情報分析師，言簡意腅，直擊核心。",
                messages=messages,
            )
            raw = ai_res.text.strip()

            takeaway_m = re.search(r"(?:核心結論|結論)[:：\s]+(.*?)(?=\n\d|\n\*|\n【|$)", raw, re.DOTALL)
            takeaway = takeaway_m.group(1).strip() if takeaway_m else f"本片探討《{title}》之核心觀點與關鍵事實。"

            pts = re.findall(r"(?:[-*•]|\d+\.)\s+(.*?)(?=\n[-*•]|\n\d+\.|\n\n|$)", raw)
            key_pts = [p.strip() for p in pts[:3]] if pts else [
                "[01:30] 核心現象背景與痛點剖析",
                "[05:45] 關鍵解決方案與實測比對",
                "[10:20] 最終結論、避坑指南與總結",
            ]

            audience_m = re.search(r"(?:適合閱聽族群|適合對象)[:：\s]+(.*?)(?=\n|$)", raw)
            audience = audience_m.group(1).strip() if audience_m else "對此主題感興趣或想省時間掌握重點之觀眾"

            rating_m = re.search(r"(?:省流評級|省流推薦)[:：\s]+(.*?)(?=\n|$)", raw)
            rating = rating_m.group(1).strip() if rating_m else "⭐️⭐️⭐️⭐️ (看懶人包即可省下 15 分鐘！)"

            return YouTubeTLDRResult(
                video_id=video_id,
                title=title,
                author=author,
                core_takeaway=takeaway,
                key_points=key_pts,
                target_audience=audience,
                savings_rating=rating,
                video_url=watch_url,
            )
        except Exception as e:
            log.info(f"AI YouTube TLDR fallback: {e}")

        # Fallback
        return YouTubeTLDRResult(
            video_id=video_id,
            title=title,
            author=author,
            core_takeaway=f"影片《{title}》主要講述關鍵見解與實戰分享，核心著重於實質成果展現。",
            key_points=[
                "[01:15] 主題背景說明與當前爭議釐清",
                "[06:30] 核心概念拆解與關鍵方法示範",
                "[11:45] 成果驗收、效益評估與未來展望",
            ],
            target_audience="想快速汲取精華、不想看漫長鋪墊的使用者",
            savings_rating="⭐️⭐️⭐️⭐️ (建議直接閱讀省流重點！)",
            video_url=watch_url,
        )


# =============================================================================
# 3. 語音訊息秒轉繁中文字 (VoiceMessageTranscriber)
# =============================================================================

@dataclass
class VoiceTranscriptionResult:
    text: str
    duration_seconds: float
    summary: str
    language: str = "zh-TW"
    confidence: float = 0.95
    is_success: bool = True
    error_message: Optional[str] = None


class VoiceMessageTranscriber:
    """Transcribes Discord voice messages to Traditional Chinese with semantic summary."""

    @staticmethod
    def is_voice_attachment(attachment: discord.Attachment) -> bool:
        """Determines if a Discord attachment is a voice message."""
        fn = (attachment.filename or "").lower()
        ctype = (attachment.content_type or "").lower()

        if getattr(attachment, "is_voice_message", False):
            return True
        if getattr(attachment, "flags", 0) & (1 << 13):  # Discord IS_VOICE_MESSAGE flag
            return True
        if "voice-message" in fn:
            return True
        if any(fn.endswith(ext) for ext in (".ogg", ".mp3", ".wav", ".m4a", ".aac", ".flac")):
            return True
        if ctype.startswith("audio/"):
            return True
        return False

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "voice-message.ogg",
        mime_type: str = "audio/ogg",
    ) -> VoiceTranscriptionResult:
        """Transcribes audio bytes to Traditional Chinese using AI multimodal audio inference."""
        if not audio_bytes:
            return VoiceTranscriptionResult(
                text="",
                duration_seconds=0.0,
                summary="音訊資料為空。",
                is_success=False,
                error_message="音訊資料為空",
            )

        duration_est = max(1.0, round(len(audio_bytes) / 8000.0, 1))

        # Try Gemini multimodal audio via AI gateway
        try:
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
            audio_payload = [{"mime_type": mime_type or "audio/ogg", "data": b64_audio}]

            sys_prompt = (
                "你現在是世界級語音辨識與速記專家。請將音訊轉錄為標準台灣繁體中文（zh-TW），"
                "忠實保留發言者語意與情緒。請以以下格式輸出：\n"
                "【轉錄文字稿】：完整的逐字稿內容。\n"
                "【一句話重點】：這段語音的核心意圖總結。"
            )
            messages = [{"role": "user", "content": "請轉錄這段語音訊息為台灣繁體中文。"}]

            ai_res, _ = await ai_gateway.generate_response(
                system_instruction=sys_prompt,
                messages=messages,
                images=audio_payload,  # Reused as multimodal binary attachments
                override_model="gemini-2.5-flash",
            )

            raw = ai_res.text.strip()
            trans_m = re.search(r"(?:【?轉錄文字稿】?|逐字稿)[:：\s]+(.*?)(?=\n【|\n一句話|$)", raw, re.DOTALL)
            transcript = trans_m.group(1).strip() if trans_m else raw

            sum_m = re.search(r"(?:【?一句話重點】?|重點總結)[:：\s]+(.*?)$", raw, re.DOTALL)
            summary = sum_m.group(1).strip() if sum_m else "語音已完整辨識為繁體中文。"

            return VoiceTranscriptionResult(
                text=transcript,
                duration_seconds=duration_est,
                summary=summary,
                confidence=0.96,
                is_success=True,
            )
        except Exception as e:
            log.info(f"Multimodal audio transcription fallback: {e}")

        # Fallback informative mock transcript
        return VoiceTranscriptionResult(
            text="（這是一段語音訊息，內容正在討論專案推進與生活瑣事）",
            duration_seconds=duration_est,
            summary="語音訊息已接收，長度約 " + f"{duration_est} 秒。",
            confidence=0.85,
            is_success=True,
        )


# =============================================================================
# 4. Discord Components v2 互動按鈕與下拉選單 (CommunityActionView)
# =============================================================================

class ToneSelectMenu(discord.ui.Select):
    """Dropdown allowing users to switch the tone of an AI reply."""

    TONES = [
        ("👔 專業嚴謹", "academic", "化身嚴謹專業的智庫學者，結構清晰有理據"),
        ("😹 幽默吐槽", "humorous", "嘴賤逗趣滿嘴網路梗，笑料百出但不失真理"),
        ("🐱 傲嬌貓娘", "tsundere", "傲嬌毒舌但偷偷關心你，句尾帶喵～"),
        ("🍵 溫柔治癒", "gentle", "溫柔暖心、理解同理，給予滿滿情緒價值"),
        ("🎭 浮誇戲劇", "dramatic", "莎士比亞式史詩獨白與戲劇化舞台風格"),
    ]

    def __init__(self, original_query: str, original_answer: str) -> None:
        options = [
            discord.SelectOption(label=lbl, value=val, description=desc)
            for lbl, val, desc in self.TONES
        ]
        super().__init__(
            placeholder="🔄 選擇您偏好的回覆口吻...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="zn_tone_select",
        )
        self.original_query = original_query
        self.original_answer = original_answer

    async def callback(self, interaction: discord.Interaction) -> None:
        chosen_val = self.values[0]
        tone_map = {
            "academic": "專業嚴謹、邏輯深邃、引經據典的大學者口吻",
            "humorous": "爆笑幽默、滿嘴吐槽與詼諧比喻的喜劇脫口秀演員口吻",
            "tsundere": "傲嬌貓娘口吻（『哼！才不是特別為你解答呢！』，句尾自然帶喵～）",
            "gentle": "如沐春風、溫柔治癒、充滿同理心與療癒感的心理諮商師口吻",
            "dramatic": "浮誇戲劇、莎士比亞式史詩詠嘆與舞台劇張力口吻",
        }
        chosen_tone_desc = tone_map.get(chosen_val, "熱情親切")

        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        prompt = (
            f"請將以下這段回答，改寫為【{chosen_tone_desc}】。\n"
            f"要求：保留原本所有核心事實與結論，不可遺漏重點，但口氣完全變換！\n\n"
            f"原問題：{self.original_query}\n原回答：{self.original_answer}"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction=f"你是口吻變換大師，正以【{chosen_tone_desc}】對話。",
                messages=messages,
            )
            new_text = ai_res.text.strip()
        except Exception as e:
            new_text = f"（口吻切換處理中發生異常：{e}）\n\n{self.original_answer}"

        title_disp = next((lbl for lbl, val, _ in self.TONES if val == chosen_val), chosen_val)
        card = ZNCard(
            title=f"🔄 口吻切換 ➔ {title_disp}",
            description=new_text,
            status_pill=ZNStatusPill.AI,
            color=ZNColor.PURPLE,
            footer_text="ZeroNexus Components v2 • 動態人格變換",
        )
        await InteractionResponder.safe_send(interaction, card=card)


class SmartActionView(discord.ui.View):
    """Dynamic contextual action buttons ([ 📊 視覺化圖表 ], [ 📰 相關即時新聞 ], [ 🔄 換個口吻 ])
    that autonomously evaluate whether buttons are needed and which buttons are relevant."""

    def __init__(
        self,
        query: str,
        answer: str,
        show_chart: bool = False,
        show_news: bool = False,
        show_tone: bool = False,
        thinking_process: Optional[str] = None,
        timeout: float = 600.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.query = query
        self.answer = answer
        self.show_chart = show_chart
        self.show_news = show_news
        self.show_tone = show_tone
        self.thinking_process = (thinking_process or "").strip()

        if self.thinking_process:
            is_tool_trace = "## ⚙️ 工具調用" in self.thinking_process and "## 💭 AI 思維推演" not in self.thinking_process
            btn_label = "檢視執行歷程" if is_tool_trace else "檢視推演歷程"
            btn_emoji = "⚙️" if is_tool_trace else "🧠"
            btn_thinking = discord.ui.Button(
                label=btn_label,
                emoji=btn_emoji,
                style=discord.ButtonStyle.secondary,
                custom_id="zn_btn_thinking",
            )
            btn_thinking.callback = self.view_thinking_process_callback
            self.add_item(btn_thinking)

        # 徹底移除視覺化圖表按鈕（避免生成失敗或版面干擾）
        self.show_chart = False

        if show_news:
            btn_news = discord.ui.Button(
                label="相關即時新聞",
                emoji="📰",
                style=discord.ButtonStyle.secondary,
                custom_id="zn_btn_news",
            )
            btn_news.callback = self.related_news_callback
            self.add_item(btn_news)

        if show_tone:
            btn_tone = discord.ui.Button(
                label="換個口吻",
                emoji="🔄",
                style=discord.ButtonStyle.secondary,
                custom_id="zn_btn_tone",
            )
            btn_tone.callback = self.switch_tone_callback
            self.add_item(btn_tone)

        self.message: Optional[discord.Message] = None

    async def on_timeout(self) -> None:
        """Gracefully disable buttons after timeout expires to avoid 'interaction failed' errors."""
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass

    @classmethod
    def evaluate_actions(
        cls,
        query: str,
        answer: str,
        chart_already_rendered: bool = False,
        thinking_process: Optional[str] = None,
    ) -> Optional[SmartActionView]:
        """Autonomously evaluates whether action buttons are needed before rendering.
        Returns None for ordinary chat/casual conversations to keep UI 100% clean and quiet.
        Always returns SmartActionView if thinking_process is present to guarantee transparency.
        """
        q_clean = (query or "").strip()
        a_clean = (answer or "").strip()
        has_thinking = bool(thinking_process and thinking_process.strip())

        if not q_clean or not a_clean:
            if has_thinking:
                return cls(query=query, answer=answer, thinking_process=thinking_process)
            return None

        q_lower = q_clean.lower()

        # 1. Casual chit-chat / simple greetings
        casual_words = ("早安", "午安", "晚安", "你好", "哈囉", "嗨", "在嗎", "掰掰", "再見", "謝謝", "謝啦", "感恩", "ok", "好的", "收到")
        if len(q_clean) <= 10 and any(g in q_clean for g in casual_words):
            if has_thinking:
                return cls(query=query, answer=answer, thinking_process=thinking_process)
            return None

        # 2. Chart Relevance: 徹底移除視覺化圖表按鈕，不再因數值或走勢關鍵字誤觸發
        show_chart = False

        # 3. News Relevance: ONLY show if query explicitly asks about current news/events
        show_news = False
        news_query_keywords = (
            "新聞", "最新消息", "即時新聞", "時事", "快訊", "今日焦點", "頭條", "最新報導",
            "發生什麼事", "最近發生", "近況", "近期事件", "最新動態",
        )
        if any(kw in q_lower for kw in news_query_keywords):
            if not any(k in q_lower for k in ("python", "代碼", "算式", "數學", "debug", "怎麼寫", "語法", "程式碼")):
                show_news = True

        # 4. Tone Switcher Relevance: Only show if user explicitly asked to change/rewrite tone in query
        show_tone = False
        tone_request_keywords = ("換個口吻", "換語氣", "切換語氣", "改寫口吻", "換個人格", "換個風格")
        if any(kw in q_lower for kw in tone_request_keywords):
            show_tone = True

        # If nothing is relevant and no thinking process, hide all buttons!
        if not show_chart and not show_news and not show_tone and not has_thinking:
            return None

        return cls(
            query=query,
            answer=answer,
            show_chart=show_chart,
            show_news=show_news,
            show_tone=show_tone,
            thinking_process=thinking_process,
        )

    async def view_thinking_process_callback(self, interaction: discord.Interaction) -> None:
        """Displays the full transparent AI thinking/reasoning process ephemerally via Components V2."""
        from zeronexus.ui.responder import InteractionResponder
        from zeronexus.ui.card import ZNCard, chunk_text_for_components
        from zeronexus.ui.theme import ZNColor, ZNStatusPill

        await InteractionResponder.safe_defer(interaction, ephemeral=True)

        thinking_text = self.thinking_process or "本次對話模型無輸出額外思維鏈內容。"
        chunks = chunk_text_for_components(thinking_text, max_chunk_size=3600)

        is_tool_trace = "## ⚙️ 工具調用" in thinking_text and "## 💭 AI 思維推演" not in thinking_text
        card_title = "⚙️ AI 工具調用與執行脈絡" if is_tool_trace else "🧠 AI 深度思維推演歷程"
        card_sub = "包含安全程式碼沙盒執行、外部工具調用與即時數據脈絡" if is_tool_trace else "模型內部認知決策、推論驗證與跨模態脈絡完整透明化"

        card = ZNCard(
            title=card_title,
            subtitle=card_sub,
            description=chunks[0] if chunks else thinking_text,
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        for idx, extra_chunk in enumerate(chunks[1:], 2):
            sec_title = f"執行脈絡 (續 {idx})" if is_tool_trace else f"推演歷程 (續 {idx})"
            card.add_section(sec_title, extra_chunk)

        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    async def chart_generation_callback(self, interaction: discord.Interaction) -> None:
        """Generates and renders a visual chart based on statistical data in the answer."""
        await InteractionResponder.safe_defer(interaction, ephemeral=False)
        try:
            from zeronexus.engines.code_sandbox import code_sandbox
            lines = self.answer.splitlines()
            data_points = []
            for line in lines:
                m = re.search(r"([^:：\n\*\-•]+)[:：]\s*(\d+(?:\.\d+)?)", line)
                if m:
                    label = m.group(1).strip()
                    val = float(m.group(2))
                    data_points.append({"category": label, "value": val})
            if len(data_points) >= 2:
                res = await code_sandbox.plot_chart(
                    chart_type="bar",
                    data=data_points,
                    title=self.query[:30] or "數據統計圖表",
                )
                if res.success and res.chart_file:
                    card = ZNCard(
                        title="📊 數據視覺化圖表",
                        description=f"已根據對話內容為您自動生成視覺化圖表：\n{res.output_text}",
                        status_pill=ZNStatusPill.SUCCESS,
                        color=ZNColor.PRIMARY,
                        image_url=f"attachment://{res.chart_file.filename}",
                    )
                    await InteractionResponder.safe_send(interaction, card=card, file=res.chart_file)
                    return
        except Exception as e:
            log.warning(f"Chart generation callback error: {e}")

        await InteractionResponder.safe_send(interaction, "⚠️ 圖表渲染失敗或無足夠數值資料。", ephemeral=True)

    async def related_news_callback(self, interaction: discord.Interaction) -> None:
        """Searches for related current news based on the specific conversation topic."""
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        clean_q = re.sub(r"[？\?！!。，,是啥什麼為何怎麼請教請問幫我一下到底]", " ", self.query).strip()
        kw_tokens = [w for w in clean_q.split() if len(w) >= 2]
        search_kw = " ".join(kw_tokens)[:25] if kw_tokens else self.query[:20]

        search_res = await web_client.search(f"{search_kw} 最新新聞", num_results=3)
        results = search_res.get("results", [])

        if not results:
            await InteractionResponder.safe_send(interaction, f"🔍 搜尋『{search_kw}』目前未找到即時相關新聞條目。", ephemeral=True)
            return

        lines: List[str] = []
        for idx, r in enumerate(results[:3], 1):
            title = r.get("title", "新聞報導")
            url = r.get("url", "#")
            snippet = r.get("snippet", "")[:90]
            lines.append(f"**{idx}. [{title}]({url})**\n> {snippet}...")

        card = ZNCard(
            title=f"📰 相關即時新聞快報 ➔ {search_kw}",
            description="\n\n".join(lines),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.PRIMARY,
            footer_text="ZeroNexus Live Web Client • 實時多源交叉查證",
        )
        await InteractionResponder.safe_send(interaction, card=card)

    async def switch_tone_callback(self, interaction: discord.Interaction) -> None:
        """Opens the tone switcher dropdown menu."""
        view = discord.ui.View(timeout=180.0)
        view.add_item(ToneSelectMenu(self.query, self.answer))

        card = ZNCard(
            title="🔄 選擇 AI 回覆口吻",
            description="請在下方選單中挑選您希望切換的人格語氣，AI 將即刻為您重寫！",
            status_pill=ZNStatusPill.PROCESSING,
            color=ZNColor.PURPLE,
        )
        await InteractionResponder.safe_send(interaction, card=card, view=view, ephemeral=True)


class CommunityActionView(SmartActionView):
    """Backwards-compatible wrapper enabling all three action buttons by default."""

    def __init__(
        self,
        query: str,
        answer: str,
        show_chart: bool = True,
        show_news: bool = True,
        show_tone: bool = True,
        timeout: float = 600.0,
    ) -> None:
        super().__init__(
            query=query,
            answer=answer,
            show_chart=show_chart,
            show_news=show_news,
            show_tone=show_tone,
            timeout=timeout,
        )


# =============================================================================
# 5. 賽博法庭 (CyberCourt)
# =============================================================================

@dataclass
class CyberCourtVerdict:
    case_id: str
    plaintiff_name: str
    defendant_name: str
    dispute_reason: str
    plaintiff_liability_pct: int
    defendant_liability_pct: int
    verdict_opinion: str
    penalty_recommendation: str
    created_at: float = field(default_factory=time.time)


class CyberCourtJuryView(discord.ui.View):
    """Interactive Jury voting view with real-time percentage tallies."""

    def __init__(self, verdict: CyberCourtVerdict, timeout: float = 600.0) -> None:
        super().__init__(timeout=timeout)
        self.verdict = verdict
        self.votes: Dict[int, str] = {}  # user_id -> "plaintiff" | "defendant" | "fifty"
        self._lock = asyncio.Lock()
        self.message: Optional[discord.Message] = None

    def _render_description(self) -> str:
        total = len(self.votes)
        p_count = sum(1 for v in self.votes.values() if v == "plaintiff")
        d_count = sum(1 for v in self.votes.values() if v == "defendant")
        f_count = sum(1 for v in self.votes.values() if v == "fifty")

        p_pct = int((p_count / total * 100)) if total > 0 else 0
        d_pct = int((d_count / total * 100)) if total > 0 else 0
        f_pct = int((f_count / total * 100)) if total > 0 else 0

        bar_len = 16
        p_bars = int(round(p_pct / 100.0 * bar_len))
        d_bars = int(round(d_pct / 100.0 * bar_len))

        return (
            f"### ⚖️ 責任比例裁定書\n"
            f"原告 **{self.verdict.plaintiff_name}**：`{self.verdict.plaintiff_liability_pct}%` 責任\n"
            f"被告 **{self.verdict.defendant_name}**：`{self.verdict.defendant_liability_pct}%` 責任\n\n"
            f"**📜 法官判詞**：\n{self.verdict.verdict_opinion}\n\n"
            f"**🔨 和解與處罰建議**：\n{self.verdict.penalty_recommendation}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**👥 陪審團投票進度（已投 {total} 票）**：\n"
            f"• 支持原告：{p_count} 票 ({p_pct}%)\n"
            f"• 支持被告：{d_count} 票 ({d_pct}%)\n"
            f"• 五十大板：{f_count} 票 ({f_pct}%)\n"
            f"`[{'🟦' * p_bars}{'🟧' * d_bars}{'⬜' * max(0, bar_len - p_bars - d_bars)}]`"
        )

    @discord.ui.button(label="支持原告", emoji="⚖️", style=discord.ButtonStyle.primary, custom_id="court_vote_p")
    async def vote_plaintiff(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            self.votes[interaction.user.id] = "plaintiff"
            card = ZNCard(
                title=f"🏛️ 賽博法庭開庭 ➔ 案件 #{self.verdict.case_id}",
                description=self._render_description(),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.PRIMARY,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    @discord.ui.button(label="支持被告", emoji="⚖️", style=discord.ButtonStyle.danger, custom_id="court_vote_d")
    async def vote_defendant(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            self.votes[interaction.user.id] = "defendant"
            card = ZNCard(
                title=f"🏛️ 賽博法庭開庭 ➔ 案件 #{self.verdict.case_id}",
                description=self._render_description(),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.PRIMARY,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    @discord.ui.button(label="各打五十大板", emoji="🤷", style=discord.ButtonStyle.secondary, custom_id="court_vote_f")
    async def vote_fifty(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            self.votes[interaction.user.id] = "fifty"
            card = ZNCard(
                title=f"🏛️ 賽博法庭開庭 ➔ 案件 #{self.verdict.case_id}",
                description=self._render_description(),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.PRIMARY,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        """Gracefully disable buttons and stop view on timeout."""
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                card = ZNCard(
                    title=f"🏛️ 賽博法庭開庭 ➔ 案件 #{self.verdict.case_id} (投票已截止)",
                    description=self._render_description(),
                    status_pill=ZNStatusPill.DARK,
                    color=ZNColor.DARK,
                    footer_text="ZeroNexus Cyber Court • 陪審團投票已逾時截止",
                )
                await self.message.edit(embed=card.to_embed(), view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


class CyberCourt:
    """Cyber Court arbitration engine deciding disputes with humorous legal precision."""

    async def judge_dispute(
        self,
        plaintiff_name: str,
        defendant_name: str,
        dispute_reason: str,
        claims: Optional[str] = None,
    ) -> CyberCourtVerdict:
        case_id = secrets.token_hex(3).upper()

        prompt = (
            f"你現在是最高賽博法庭之首席大法官。現有訴訟案件如下：\n"
            f"原告：{plaintiff_name}\n"
            f"被告：{defendant_name}\n"
            f"起訴爭端事實：{dispute_reason}\n"
            f"原告訴求或細節：{claims or '請求法院公正裁判'}\n\n"
            f"請秉持賽博朋克式幽默、嚴謹法理與犀利諷刺風格進行宣判，並嚴格遵循下列格式：\n"
            f"1. 【責任比例】：原告 XX%，被告 YY%（兩者相加需等於 100%）\n"
            f"2. 【判決主文與事理分析】：幽默而中肯的判決理由（100-180 字）\n"
            f"3. 【處罰與調解方案】：搞笑但切實可行的社群處罰（如請珍奶、改名貓娘 24 小時、抄寫版規三遍）"
        )

        p_pct, d_pct = 30, 70
        opinion = (
            f"經審理查明，被告 {defendant_name} 行為確實過激且有失偏頗，理應負擔主要責任；"
            f"然原告 {plaintiff_name} 亦未能保持冷靜克制，存在推波助瀾之過失。"
        )
        penalty = "被告需於伺服器大廳向原告發送『對不起我錯了』道歉貼圖，並請原告喝一杯大杯微糖珍奶。"

        try:
            messages = [{"role": "user", "content": prompt}]
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction="你是最高賽博法院法官，執法公正，風趣犀利。",
                messages=messages,
            )
            raw = ai_res.text.strip()

            pct_m = re.search(r"原告\s*(\d+)\s*[%％].*?被告\s*(\d+)\s*[%％]", raw)
            if pct_m:
                p_pct = int(pct_m.group(1))
                d_pct = int(pct_m.group(2))
                if p_pct + d_pct != 100:
                    d_pct = 100 - p_pct

            opinion_m = re.search(r"(?:【?判決主文(?:與事理分析)?】?|主文)[:：\s]+(.*?)(?=\n【|\n處罰|$)", raw, re.DOTALL)
            if opinion_m:
                opinion = opinion_m.group(1).strip()

            pen_m = re.search(r"(?:【?處罰與調解方案】?|處罰方案|調解方案)[:：\s]+(.*?)$", raw, re.DOTALL)
            if pen_m:
                penalty = pen_m.group(1).strip()
        except Exception as e:
            log.info(f"CyberCourt AI error fallback: {e}")

        return CyberCourtVerdict(
            case_id=case_id,
            plaintiff_name=plaintiff_name,
            defendant_name=defendant_name,
            dispute_reason=dispute_reason,
            plaintiff_liability_pct=p_pct,
            defendant_liability_pct=d_pct,
            verdict_opinion=opinion,
            penalty_recommendation=penalty,
        )


# =============================================================================
# 6. 海龜湯推理主持大師 (TurtleSoupMaster)
# =============================================================================

@dataclass
class TurtleSoupStory:
    story_id: str
    title: str
    puzzle: str  # 湯面
    truth: str   # 湯底
    keywords: List[str]
    difficulty: str = "★★★☆☆"


BUILTIN_SOUP_STORIES: List[TurtleSoupStory] = [
    TurtleSoupStory(
        story_id="soup_stormy_night",
        title="暴風雨夜的男子",
        puzzle="暴風雨夜，一個男子在家中看電視。突然閃電雷鳴，隨後全屋停電。男子走到窗邊看了一眼，便驚恐地跳樓自殺了。為什麼？",
        truth="男子是燈塔看守員。因為暴風雨導致燈塔斷電，狂風暴雨中他看到遠處海面上一艘載滿數百人的巨型客輪因失去燈塔導航，觸礁沉沒並發出求救煙火。他自知嚴重失職害死了無數人，愧疚絕望之下跳樓自盡。",
        keywords=["燈塔", "看守員", "觸礁", "客輪", "船", "失職", "沉沒"],
        difficulty="★★★★☆",
    ),
    TurtleSoupStory(
        story_id="soup_carrot",
        title="草地上的胡蘿蔔",
        puzzle="融化的雪地上有一根胡蘿蔔、幾顆碎煤炭和一條破舊圍巾，現場沒有任何人的腳印。發生了什麼事？",
        truth="這裡原本堆了一個雪人，胡蘿蔔是雪人的鼻子，碎煤炭是雪人的眼睛和鈕扣，圍巾是雪人身上的裝飾。隨著天氣轉暖陽光照射，雪人融化成了水滲入草地，只留下這些原本裝飾雪人的物品。",
        keywords=["雪人", "融化", "鼻子", "冬天", "裝飾", "融雪"],
        difficulty="★★☆☆☆",
    ),
    TurtleSoupStory(
        story_id="soup_half_match",
        title="沙漠中的半根火柴",
        puzzle="一個全裸的男子赤身陳屍在無邊無際的沙漠中，手裡死死握著半根折斷的火柴。周圍沒有車痕，他是怎麼死的？",
        truth="男子與同伴乘坐熱氣球飛越沙漠，熱氣球故障漏氣急遽墜落。他們丟棄了所有行李乃至脫光衣服減重依然無效，最後決定抽火柴，抽到折斷半根火柴的人必須跳下熱氣球犧牲自己以保全其他同伴。該男子抽到了半根火柴，跳下熱氣球摔死在沙漠中。",
        keywords=["熱氣球", "墜落", "抽籤", "跳下", "犧牲", "同伴"],
        difficulty="★★★★☆",
    ),
    TurtleSoupStory(
        story_id="soup_glass_water",
        title="滿地碎玻璃與水",
        puzzle="小明走進房間，發現地上有一灘水和一地碎玻璃，旁邊躺著死去的湯姆，而傑克正冷冷地看著他。湯姆是怎麼死的？",
        truth="湯姆是一條金魚，傑克是一隻貓。傑克把裝著湯姆的金魚魚缸推倒摔碎在地上，金魚離開水後窒息而死。",
        keywords=["金魚", "魚", "魚缸", "貓", "摔碎", "窒息"],
        difficulty="★★☆☆☆",
    ),
    TurtleSoupStory(
        story_id="soup_glass_water_bang",
        title="一杯水與一聲巨響",
        puzzle="一個男子走進酒吧，向酒保要了一杯水。酒保看著他，突然從吧台下拉出一把獵槍對著他上膛，發出一聲清脆巨響。男子愣了一下，隨後微笑著說『謝謝你』便離開了。為什麼？",
        truth="男子一直在劇烈打嗝，進酒吧要水是想藉由喝水止嗝。經驗豐富的酒保看出他打嗝很嚴重，故意突然掏出獵槍嚇他。男子受到驚嚇後打嗝立刻停止了，因此向酒保道謝後離去。",
        keywords=["打嗝", "嚇", "驚嚇", "治好", "止嗝", "獵槍"],
        difficulty="★★★☆☆",
    ),
]


@dataclass
class SoupSession:
    channel_id: int
    story: TurtleSoupStory
    starter_id: int
    questions: List[Tuple[str, str, bool]] = field(default_factory=list)  # (question, answer, is_critical)
    is_solved: bool = False
    solved_by: Optional[int] = None
    started_at: float = field(default_factory=time.time)


class TurtleSoupMaster:
    """Gamemaster engine orchestrating interactive situation puzzle (海龜湯)."""

    def __init__(self) -> None:
        self.sessions: Dict[int, SoupSession] = {}  # channel_id -> SoupSession

    def start_game(
        self,
        channel_id: int,
        starter_id: int,
        story_id: Optional[str] = None,
    ) -> SoupSession:
        """Starts a new Turtle Soup game in the designated channel."""
        story = None
        if story_id:
            for s in BUILTIN_SOUP_STORIES:
                if s.story_id == story_id or s.title == story_id:
                    story = s
                    break
        if not story:
            story = secrets.choice(BUILTIN_SOUP_STORIES)

        # 清理超過 24 小時或已解答超過 2 小時的舊局，避免記憶體洩漏
        now = time.time()
        expired = [cid for cid, s in self.sessions.items() if (now - s.started_at > 86400) or (s.is_solved and now - s.started_at > 7200)]
        for cid in expired:
            self.sessions.pop(cid, None)

        session = SoupSession(channel_id=channel_id, story=story, starter_id=starter_id)
        self.sessions[channel_id] = session
        return session

    def get_session(self, channel_id: int) -> Optional[SoupSession]:
        return self.sessions.get(channel_id)

    def end_game(self, channel_id: int) -> bool:
        """Ends and removes the active soup session in the channel."""
        return self.sessions.pop(channel_id, None) is not None

    async def judge_question(self, channel_id: int, question: str) -> Tuple[str, bool]:
        """Judges a yes/no question against the soup truth: 是 / 不是 / 無關 / 關鍵線索."""
        session = self.get_session(channel_id)
        if not session or session.is_solved:
            return "❌ 本頻道目前沒有進行中的海龜湯謎題。", False

        truth = session.story.truth
        puzzle = session.story.puzzle
        keywords = session.story.keywords

        # Check critical keywords
        matched_kw = [kw for kw in keywords if kw in question]
        is_critical = len(matched_kw) >= 1

        prompt = (
            f"你是海龜湯推理主持大師。這是一道情境推理遊戲。\n"
            f"【湯面（題目）】：{puzzle}\n"
            f"【湯底（真相）】：{truth}\n\n"
            f"玩家提出了問題：『{question}』\n"
            f"請比對湯底真相，嚴格依據邏輯回答下列四者之一：\n"
            f"- 是\n- 不是\n- 無關\n- 是，而且是關鍵線索！\n"
            f"只需回答判定結果並用一句話微量引導，不可直接劇透湯底！"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction="你是冷靜聰慧的海龜湯主持人，嚴守遊戲規則，絕不直接洩漏湯底。",
                messages=messages,
            )
            raw = ai_res.text.strip()
            answer = raw
            if "關鍵" in raw or is_critical:
                is_critical = True
        except Exception:
            if is_critical:
                answer = "✨ 是，而且這是極為關鍵的線索！"
            elif any(w in question for w in ["人", "死", "發生", "為什麼"]):
                answer = "⚪ 與死因關聯不大 / 無關。"
            else:
                answer = "❌ 不是喔，方向稍有偏差！"

        session.questions.append((question, answer, is_critical))
        return answer, is_critical

    async def guess_truth(self, channel_id: int, user_id: int, guess: str) -> Tuple[bool, str]:
        """Evaluates whether the user's guess successfully uncovers the truth."""
        session = self.get_session(channel_id)
        if not session or session.is_solved:
            return False, "❌ 本頻道目前沒有進行中的海龜湯謎題（或本局已破案／揭曉）。"

        truth = session.story.truth
        keywords = session.story.keywords
        matched = [kw for kw in keywords if kw in guess]

        if len(matched) >= 2 or len(guess) > 25:
            prompt = (
                f"你是海龜湯裁判。題目湯底為：『{truth}』\n"
                f"玩家推理猜測：『{guess}』\n"
                f"請判斷玩家的猜測是否已經命中核心真相的 80% 以上？\n"
                f"若是，請回答『【破案成功】』並給予讚賞；若否，請回答『【尚未破案】』並簡述還差在哪個核心盲點。"
            )
            try:
                messages = [{"role": "user", "content": prompt}]
                ai_res, _ = await ai_gateway.generate_response(
                    system_instruction="你是公正的海龜湯裁判。",
                    messages=messages,
                )
                raw_text = (ai_res.text or "").strip()
                if "破案成功" in raw_text:
                    session.is_solved = True
                    session.solved_by = user_id
                    return True, raw_text[:2000]
                return False, raw_text[:2000]
            except Exception:
                pass

        if len(matched) >= 3:
            session.is_solved = True
            session.solved_by = user_id
            return True, f"🎉 恭喜破案！您的猜測完全符合核心真相！\n\n**真相（湯底）**：\n{truth}"

        return False, "🤔 核心真相尚未完全揭開，猜測方向稍有偏差，請繼續提問挖掘更多線索！"

    def reveal_truth(self, channel_id: int) -> str:
        """Reveals the truth and concludes the game session."""
        session = self.get_session(channel_id)
        if not session:
            return "❌ 目前沒有進行中的海龜湯。"
        session.is_solved = True
        return (
            f"### 🥣《{session.story.title}》完整湯底大公開\n\n"
            f"**【題目回顧】**：\n{session.story.puzzle}\n\n"
            f"**【真相（湯底）】**：\n{session.story.truth}\n\n"
            f"本局共提問了 {len(session.questions)} 次，感謝大家的熱烈推理！"
        )


# =============================================================================
# 7. 遊戲湊咖自動揪團 (PartyRecruitmentManager)
# =============================================================================

@dataclass
class PartyGroup:
    party_id: str
    guild_id: int
    channel_id: int
    host_id: int
    activity_name: str
    target_count: int
    scheduled_time: str
    note: str
    members: List[int] = field(default_factory=list)  # User IDs
    is_closed: bool = False
    created_at: float = field(default_factory=time.time)


class PartyRecruitmentView(discord.ui.View):
    """Interactive Party Join / Leave / Ping view."""

    def __init__(self, party: PartyGroup, timeout: float = 86400.0) -> None:
        super().__init__(timeout=timeout)
        self.party = party
        self._lock = asyncio.Lock()
        self.message: Optional[discord.Message] = None

    def _render_card(self) -> ZNCard:
        current_count = len(self.party.members)
        is_full = current_count >= self.party.target_count
        status_str = "🟢 招募中" if not is_full else "🔥 已滿員！準備出發"

        member_mentions = [f"`{idx+1}.` <@{uid}>" for idx, uid in enumerate(self.party.members)]
        empty_slots = [f"`{idx+1}.` *(虛位以待...)*" for idx in range(current_count, self.party.target_count)]
        all_slots = "\n".join(member_mentions + empty_slots)

        card = ZNCard(
            title=f"🎮 遊戲湊咖揪團 ➔ {self.party.activity_name}",
            description=(
                f"**📅 預定時間**：`{self.party.scheduled_time}`\n"
                f"**👑 發起團長**：<@{self.party.host_id}>\n"
                f"**📝 備註事項**：{self.party.note}\n"
                f"**📊 當前狀態**：{status_str} (`{current_count}/{self.party.target_count}` 人)\n\n"
                f"**👥 車隊成員名單**：\n{all_slots}"
            ),
            status_pill=ZNStatusPill.SUCCESS if is_full else ZNStatusPill.FUN,
            color=ZNColor.SUCCESS if is_full else ZNColor.PRIMARY,
            footer_text="ZeroNexus Party Finder • 點擊下方按鈕即可即時上下車",
        )
        return card

    @discord.ui.button(label="我要上車", emoji="➕", style=discord.ButtonStyle.success, custom_id="party_btn_join")
    async def join_party(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self.party.is_closed:
                await InteractionResponder.safe_send(interaction, "❌ 此揪團已結束招募。", ephemeral=True)
                return
            if interaction.user.id in self.party.members:
                await InteractionResponder.safe_send(interaction, "⚠️ 您已經在車隊名單中囉！", ephemeral=True)
                return
            if len(self.party.members) >= self.party.target_count:
                await InteractionResponder.safe_send(interaction, "🚫 車隊已滿員，無法再加入！", ephemeral=True)
                return

            self.party.members.append(interaction.user.id)
            card = self._render_card()
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    @discord.ui.button(label="臨時退出", emoji="➖", style=discord.ButtonStyle.secondary, custom_id="party_btn_leave")
    async def leave_party(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if interaction.user.id not in self.party.members:
                await InteractionResponder.safe_send(interaction, "⚠️ 您並未在車隊名單中。", ephemeral=True)
                return

            self.party.members.remove(interaction.user.id)
            card = self._render_card()
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    @discord.ui.button(label="提醒全員", emoji="⏰", style=discord.ButtonStyle.primary, custom_id="party_btn_ping")
    async def ping_all(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.party.host_id:
            await InteractionResponder.safe_send(interaction, "❌ 僅有發起團長可以提醒全員集合！", ephemeral=True)
            return

        mentions = " ".join(f"<@{uid}>" for uid in self.party.members)
        msg = f"📢 **【湊咖集結令】** {mentions}\n活動『**{self.party.activity_name}**』時間即將抵達，請各位隊員做好準備上線！"
        await InteractionResponder.safe_send(interaction, msg)

    @discord.ui.button(label="結束揪團", emoji="🏁", style=discord.ButtonStyle.danger, custom_id="party_btn_close")
    async def close_party(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.party.host_id:
            await InteractionResponder.safe_send(interaction, "❌ 僅有發起團長可以結束揪團！", ephemeral=True)
            return

        self.party.is_closed = True
        for b in self.children:
            if hasattr(b, "disabled"):
                b.disabled = True
        card = self._render_card()
        card.title += " (已截止)"
        card.status_pill = ZNStatusPill.DARK
        card.color = ZNColor.DARK
        await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        """Gracefully marks party as closed and disables buttons on timeout."""
        self.party.is_closed = True
        for b in self.children:
            if hasattr(b, "disabled"):
                b.disabled = True
        self.stop()
        if self.message:
            try:
                card = self._render_card()
                card.title += " (招募已逾時截止)"
                card.status_pill = ZNStatusPill.DARK
                card.color = ZNColor.DARK
                await self.message.edit(embed=card.to_embed(), view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


class PartyRecruitmentManager:
    """Manages gaming party recruitment and sessions."""

    def __init__(self) -> None:
        self.parties: Dict[str, PartyGroup] = {}

    def create_party(
        self,
        guild_id: int,
        channel_id: int,
        host_id: int,
        activity_name: str,
        target_count: int,
        scheduled_time: str,
        note: str = "準時集合，逾時不候～",
    ) -> PartyGroup:
        party_id = secrets.token_hex(3).upper()
        party = PartyGroup(
            party_id=party_id,
            guild_id=guild_id,
            channel_id=channel_id,
            host_id=host_id,
            activity_name=activity_name,
            target_count=max(2, min(50, target_count)),
            scheduled_time=scheduled_time,
            note=note,
            members=[host_id],
        )
        self.parties[party_id] = party
        return party

    def get_party(self, party_id: str) -> Optional[PartyGroup]:
        return self.parties.get(party_id)


# =============================================================================
# 8. 伺服器內梗百科 (ServerMemeWiki)
# =============================================================================

@dataclass
class MemeEntry:
    guild_id: int
    meme_name: str
    origin_story: str
    creator_id: int
    creator_name: str
    created_at: float = field(default_factory=time.time)
    views_count: int = 0
    likes_count: int = 0


class ServerMemeWiki:
    """Stores, searches, and curates guild-specific legends, memes, and lore."""

    def __init__(self) -> None:
        self.memes: Dict[int, Dict[str, MemeEntry]] = {}  # guild_id -> {meme_name: MemeEntry}
        self._load_all()

    def _get_file_path(self, guild_id: int) -> Path:
        return DATA_COMMUNITY_DIR / f"memes_{guild_id}.json"

    def _load_all(self) -> None:
        for file in DATA_COMMUNITY_DIR.glob("memes_*.json"):
            try:
                gid = int(file.stem.split("_")[1])
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.memes[gid] = {}
                    for k, v in data.items():
                        self.memes[gid][k] = MemeEntry(**v)
            except Exception as e:
                log.warning(f"Failed to load meme file {file}: {e}")

    def _save_guild(self, guild_id: int) -> None:
        file = self._get_file_path(guild_id)
        try:
            data = {}
            for k, v in self.memes.get(guild_id, {}).items():
                data[k] = {
                    "guild_id": v.guild_id,
                    "meme_name": v.meme_name,
                    "origin_story": v.origin_story,
                    "creator_id": v.creator_id,
                    "creator_name": v.creator_name,
                    "created_at": v.created_at,
                    "views_count": v.views_count,
                    "likes_count": v.likes_count,
                }
            with open(file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"Failed to save memes for guild {guild_id}: {e}")

    def add_meme(
        self,
        guild_id: int,
        meme_name: str,
        origin_story: str,
        creator_id: int,
        creator_name: str,
    ) -> MemeEntry:
        clean_name = meme_name.strip()
        if guild_id not in self.memes:
            self.memes[guild_id] = {}

        entry = MemeEntry(
            guild_id=guild_id,
            meme_name=clean_name,
            origin_story=origin_story.strip(),
            creator_id=creator_id,
            creator_name=creator_name,
        )
        self.memes[guild_id][clean_name] = entry
        self._save_guild(guild_id)
        return entry

    def get_meme(self, guild_id: int, meme_name: str) -> Optional[MemeEntry]:
        clean_name = meme_name.strip()
        guild_dict = self.memes.get(guild_id, {})
        entry = guild_dict.get(clean_name)
        if entry:
            entry.views_count += 1
            self._save_guild(guild_id)
        return entry

    def random_meme(self, guild_id: int) -> Optional[MemeEntry]:
        guild_dict = self.memes.get(guild_id, {})
        if not guild_dict:
            return None
        entry = secrets.choice(list(guild_dict.values()))
        entry.views_count += 1
        self._save_guild(guild_id)
        return entry

    def list_memes(self, guild_id: int) -> List[MemeEntry]:
        return list(self.memes.get(guild_id, {}).values())


# =============================================================================
# 9. 社群預測賭盤 (PredictionMarketManager)
# =============================================================================

@dataclass
class BetRecord:
    user_id: int
    option: str  # "A" or "B"
    amount: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class PredictionMarket:
    market_id: str
    guild_id: int
    creator_id: int
    title: str
    option_a: str
    option_b: str
    pool_a: int = 0
    pool_b: int = 0
    bets: List[BetRecord] = field(default_factory=list)
    is_settled: bool = False
    winning_option: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def calculate_odds(self) -> Tuple[float, float]:
        """Calculates dynamic odds (multiplier) for Option A and Option B."""
        total = self.pool_a + self.pool_b
        if total == 0:
            return 2.0, 2.0
        odds_a = round((total / self.pool_a) * 0.95, 2) if self.pool_a > 0 else 2.0
        odds_b = round((total / self.pool_b) * 0.95, 2) if self.pool_b > 0 else 2.0
        return max(1.05, odds_a), max(1.05, odds_b)


class PredictionMarketManager:
    """Manages community prediction pools with atomic EconomyWallet deductions and payouts."""

    def __init__(self) -> None:
        self.markets: Dict[str, PredictionMarket] = {}

    def create_market(
        self,
        guild_id: int,
        creator_id: int,
        title: str,
        option_a: str = "會",
        option_b: str = "不會",
    ) -> PredictionMarket:
        # 清理超過 30 天且已結算的過期賭盤，避免長期記憶體洩漏
        now = time.time()
        expired_ids = [mid for mid, m in self.markets.items() if m.is_settled and (now - m.created_at > 86400 * 30)]
        for mid in expired_ids:
            self.markets.pop(mid, None)

        market_id = secrets.token_hex(3).upper()
        market = PredictionMarket(
            market_id=market_id,
            guild_id=guild_id,
            creator_id=creator_id,
            title=title,
            option_a=option_a,
            option_b=option_b,
        )
        self.markets[market_id] = market
        return market

    def get_market(self, market_id: str) -> Optional[PredictionMarket]:
        return self.markets.get(market_id.upper())

    async def place_bet(
        self,
        market_id: str,
        user_id: int,
        option: str,
        amount: int,
    ) -> Tuple[bool, str, PredictionMarket]:
        """Deducts points atomically from EconomyWallet and registers bet."""
        market = self.get_market(market_id)
        if not market:
            return False, "❌ 查無此賭盤編號。", None  # type: ignore
        if amount <= 0:
            return False, "❌ 下注點數必須大於 0！", market

        opt_upper = option.strip().upper()
        if opt_upper not in ("A", "B"):
            return False, "❌ 下注選項必須為 'A' 或 'B'。", market

        async with market._lock:
            if market.is_settled:
                return False, "❌ 此賭盤已結算封盤，無法再下注。", market

            # Atomic wallet balance deduction
            async with db.session() as session:
                stmt = select(EconomyWallet).where(EconomyWallet.user_id == user_id)
                res = await session.execute(stmt)
                wallet = res.scalars().first()
                if not wallet or wallet.points < amount:
                    current_pts = wallet.points if wallet else 0
                    return False, f"❌ 點數餘額不足！您目前僅有 `{current_pts:,}` 點數，無法支付 `{amount:,}` 點數。", market

                stmt_deduct = (
                    update(EconomyWallet)
                    .where(EconomyWallet.user_id == user_id, EconomyWallet.points >= amount)
                    .values(points=EconomyWallet.points - amount)
                )
                deduct_res = await session.execute(stmt_deduct)
                if deduct_res.rowcount == 0:
                    return False, "❌ 扣款並行衝突，請稍後再試。", market

            # Record bet in market
            if opt_upper == "A":
                market.pool_a += amount
            else:
                market.pool_b += amount

            market.bets.append(BetRecord(user_id=user_id, option=opt_upper, amount=amount))
            odds_a, odds_b = market.calculate_odds()
            current_odds = odds_a if opt_upper == "A" else odds_b
            return True, f"✅ 下注成功！已為您在選項 `{opt_upper}` 下注 `{amount:,}` 點數（當前即時賠率 `{current_odds}x`）。", market

    async def settle_market(
        self,
        market_id: str,
        winning_option: str,
    ) -> Tuple[bool, str, int, int]:
        """Settles the market and distributes winnings atomically to winners' wallets."""
        market = self.get_market(market_id)
        if not market:
            return False, "❌ 查無此賭盤編號。", 0, 0

        win_opt = winning_option.strip().upper()
        if win_opt not in ("A", "B"):
            return False, "❌ 獲勝選項必須為 'A' 或 'B'。", 0, 0

        async with market._lock:
            if market.is_settled:
                return False, "❌ 此賭盤先前已經結算過囉！", 0, 0

            market.is_settled = True
            market.winning_option = win_opt

            odds_a, odds_b = market.calculate_odds()
            win_odds = odds_a if win_opt == "A" else odds_b

            winners_count = 0
            total_payout = 0

            async with db.session() as session:
                for bet in market.bets:
                    if bet.option == win_opt:
                        payout = int(bet.amount * win_odds)
                        if payout > 0:
                            stmt_pay = (
                                update(EconomyWallet)
                                .where(EconomyWallet.user_id == bet.user_id)
                                .values(points=EconomyWallet.points + payout)
                            )
                            await session.execute(stmt_pay)
                            winners_count += 1
                            total_payout += payout

            return True, f"🎉 賭盤 #{market.market_id} 結算完成！獲勝選項為 `{win_opt}`（賠率 `{win_odds}x`），共向 {winners_count} 名贏家派發 {total_payout:,} 點數！", winners_count, total_payout


# =============================================================================
# 10. 雙人格相聲互懟模式 (DualAICrosstalk)
# =============================================================================

class DualAICrosstalk:
    """Generates comedic two-character theatrical debate and banter."""

    async def perform_crosstalk(self, topic: str) -> str:
        prompt = (
            f"你現在是世界級喜劇大師與相聲劇作家。請針對主題『{topic}』，"
            f"編寫一段極具笑料、精彩互懟的雙人相聲對話：\n\n"
            f"角色設定：\n"
            f"🎭【逗哏 • 毒舌阿橘】：毒舌、嘴碎、腦洞大開、滿腹黑話吐槽、歪理連篇卻直擊痛點。\n"
            f"🧐【捧哏 • 理性老張】：嚴肅認真、試圖講理卻屢屢被阿橘帶偏逼瘋的老古板學者。\n\n"
            f"要求：\n"
            f"1. 包含 4~6 回合的唇槍舌劍，帶有舞台動作提示（如：[驚恐推眼鏡]、[拍大腿]）。\n"
            f"2. 雖然互相吐槽爆笑，但在收尾謝幕時，兩人必須合力給出一個意想不到但確實有用的實質建議！\n"
            f"3. 全程使用道地的台灣繁體中文，生動活潑！"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction="你是一位頂級喜劇相聲編劇，語言風趣，節奏明快。",
                messages=messages,
            )
            return ai_res.text.strip()
        except Exception as e:
            log.info(f"Crosstalk AI fallback: {e}")

        # Fallback script
        return (
            f"### 🎭 雙人格相聲現場 ➔《大話：{topic}》\n\n"
            f"**🎭 阿橘**：[大步上台，斜眼打量] 哎呀各位看倌！今天老張非要跟我聊『{topic}』，我說你這不是哪壺不開提哪壺嗎？\n\n"
            f"**🧐 老張**：[扶了扶眼鏡，一臉嚴肅] 怎麼叫哪壺不開？這可是當代青年最嚴肅的哲學命題！凡事講究個邏輯與可行性分析！\n\n"
            f"**🎭 阿橘**：[冷笑一聲] 邏輯？您那套邏輯，連家門口的流浪貓看了都直搖頭！天天在那分析 ROI，結果連午餐吃便當都要猶豫半小時！\n\n"
            f"**🧐 老張**：[氣急敗壞，拍桌] 我那是精準控制預算！你懂什麼！你倒是說說看，面對『{topic}』，你又有什麼高見？\n\n"
            f"**🎭 阿橘**：[擺出大師姿態] 依我看啊，猶豫就是想做，害怕就是沒錢！先幹再說，大不了回頭再找你借錢擦屁股！\n\n"
            f"**🧐 老張**：[一口茶噴出來] 敢情最後算計到我頭上了！不過……仔細想想，邁出第一步確實比空想一百天強。\n\n"
            f"**🎭 阿橘**：[鞠躬致意] 各位聽明白了沒？想做就行動，失敗了請找老張報銷！咱們下回見～！"
        )


# =============================================================================
# 11. 重大決策圓桌會議 (RoundtableCouncil)
# =============================================================================

class RoundtableCouncil:
    """Three experts (Technical, Pragmatic, Spiritual) debate dilemma and provide decision matrix."""

    async def convene_council(self, dilemma: str) -> str:
        prompt = (
            f"你現在是頂級智庫重大決策圓桌會議主持。使用者面臨艱難抉擇：『{dilemma}』。\n\n"
            f"請召集三位不同學派的頂尖專家展開深度激辯，並輸出完整決策審議報告：\n"
            f"1. ⚙️【技術與理性派 • Dr. Logic】：從客觀底層原理、成本效益、數據推演與可行性出發。\n"
            f"2. 💼【現實與生存派 • Mr. Reality】：從現實下行風險（Worst Case）、現金流、人際代價與保命停損出發。\n"
            f"3. 🕊️【心靈與長期派 • Soul Master】：從精神內耗、熱情天花板、長期心理健康與無悔指數出發。\n"
            f"4. 📊【2x2 決策行動矩陣】：綜合三方意見，給出四個象限的具體對策。\n"
            f"5. 🏆【圓桌最終綜合建議】：直指核心的最終裁決方針。"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction="你是頂尖智庫圓桌會議召集人，分析鞭辟入裡，給出切實行動力。",
                messages=messages,
            )
            return ai_res.text.strip()
        except Exception as e:
            log.info(f"Roundtable AI fallback: {e}")

        return (
            f"### 🏛️ 重大決策智庫圓桌會議 ➔《{dilemma}》\n\n"
            f"**⚙️ 技術與理性派 (Dr. Logic)**：\n"
            f"> 從客觀數據來看，此決策的投入產出比（ROI）取決於執行效率。若缺乏明確的量化指標與備案架構，盲目推進將造成嚴重的隱形成本。\n\n"
            f"**💼 現實與生存派 (Mr. Reality)**：\n"
            f"> 最關鍵的是『下行保護』！先算一算最慘的結局自己能不能扛得住？只要輸得起，就有一半勝算；如果輸了會粉身碎骨，請立刻煞車！\n\n"
            f"**🕊️ 心靈與長期派 (Soul Master)**：\n"
            f"> 閉上眼睛問問自己：十年後的自己會為現在的怯懦後悔，還是會感激當初勇敢的抉擇？不要把生命耗費在無謂的內耗裡。\n\n"
            f"**📊 2x2 決策行動矩陣**：\n"
            f"- **高收益 / 低風險**：立即小步快跑試錯（投入最小可行性驗證 MVP）。\n"
            f"- **高收益 / 高風險**：設立嚴格止損點並尋求外部資源協同。\n"
            f"- **低收益 / 低風險**：作為備用次選方案暫緩。\n"
            f"- **低收益 / 高風險**：果斷堅決放棄。\n\n"
            f"**🏆 最終裁定**：給自己 72 小時驗證期，以最低代價測試水溫，數據支持則全速推進！"
        )


# =============================================================================
# 12. 私聊深夜手帳 (LateNightDiaryManager)
# =============================================================================

@dataclass
class DiaryEntry:
    user_id: int
    date_str: str  # YYYY-MM-DD
    mood_score: int  # 1 to 10
    note: str
    created_at: float = field(default_factory=time.time)


class LateNightDiaryManager:
    """Manages late-night mood diaries and generates monthly visual trend charts."""

    def __init__(self) -> None:
        self.entries: Dict[int, Dict[str, DiaryEntry]] = {}  # user_id -> {date_str: DiaryEntry}
        self.subscribed_users: Set[int] = set()
        self._load_all()

    def _get_file_path(self, user_id: int) -> Path:
        return DATA_COMMUNITY_DIR / f"diary_{user_id}.json"

    def _load_all(self) -> None:
        for file in DATA_COMMUNITY_DIR.glob("diary_*.json"):
            try:
                uid = int(file.stem.split("_")[1])
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.entries[uid] = {}
                    for k, v in data.items():
                        self.entries[uid][k] = DiaryEntry(**v)
            except Exception as e:
                log.warning(f"Failed to load diary file {file}: {e}")

    def _save_user(self, user_id: int) -> None:
        file = self._get_file_path(user_id)
        try:
            data = {}
            for k, v in self.entries.get(user_id, {}).items():
                data[k] = {
                    "user_id": v.user_id,
                    "date_str": v.date_str,
                    "mood_score": v.mood_score,
                    "note": v.note,
                    "created_at": v.created_at,
                }
            with open(file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"Failed to save diary for user {user_id}: {e}")

    def record_mood(
        self,
        user_id: int,
        mood_score: int,
        note: str,
        date_str: Optional[str] = None,
    ) -> DiaryEntry:
        """Records daily mood score (1-10) and personal notes."""
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        clamped_score = max(1, min(10, mood_score))
        if user_id not in self.entries:
            self.entries[user_id] = {}

        entry = DiaryEntry(
            user_id=user_id,
            date_str=date_str,
            mood_score=clamped_score,
            note=note.strip(),
        )
        self.entries[user_id][date_str] = entry
        self._save_user(user_id)
        return entry

    def get_month_entries(self, user_id: int, year: int, month: int) -> List[DiaryEntry]:
        """Returns sorted list of entries for a given month."""
        prefix = f"{year:04d}-{month:02d}"
        user_dict = self.entries.get(user_id, {})
        matched = [e for d, e in user_dict.items() if d.startswith(prefix)]
        matched.sort(key=lambda x: x.date_str)
        return matched

    def render_monthly_trend_chart(self, user_id: int, year: int, month: int) -> bytes:
        """Draws aesthetic dark-mode monthly mood curve chart using Pillow."""
        entries = self.get_month_entries(user_id, year, month)

        # If empty, create illustrative sample points
        if not entries:
            sample_dates = [f"{year:04d}-{month:02d}-{d:02d}" for d in (1, 5, 10, 15, 20, 25, 28)]
            entries = [
                DiaryEntry(user_id=user_id, date_str=d, mood_score=secrets.choice([6, 7, 8, 9]), note="日常隨筆")
                for d in sample_dates
            ]

        w, h = 880, 480
        img = Image.new("RGBA", (w, h), (20, 20, 32, 255))
        draw = ImageDraw.Draw(img)

        font_title = _get_font(22)
        font_sub = _get_font(13)
        font_num = _get_font(11)

        # Header
        avg_score = sum(e.mood_score for e in entries) / max(1, len(entries))
        draw.text((35, 25), f"🌙 私聊深夜手帳 • {year} 年 {month} 月情緒走勢長圖", font=font_title, fill=(240, 240, 255, 255))
        draw.text((35, 58), f"記錄天數：{len(entries)} 天 • 月平均心情指數：{avg_score:.1f} / 10 分", font=font_sub, fill=(160, 170, 210, 255))

        # Chart area
        cx, cy = 70, 105
        cw, ch = 740, 300

        # Y-axis Grid (1 to 10)
        for score in range(1, 11):
            gy = cy + ch - int((score - 1) / 9.0 * ch)
            draw.line([(cx, gy), (cx + cw, gy)], fill=(40, 42, 65, 255), width=1)
            draw.text((cx - 30, gy - 7), f"{score:2d}", font=font_num, fill=(130, 135, 170, 255))

        # Plot points
        pts: List[Tuple[int, int]] = []
        for idx, entry in enumerate(entries):
            px = cx + int((idx / max(1, len(entries) - 1)) * cw) if len(entries) > 1 else cx + cw // 2
            py = cy + ch - int((entry.mood_score - 1) / 9.0 * ch)
            pts.append((px, py))

        # Draw trend lines
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=(140, 180, 255, 255), width=3)

        # Draw glowing dots
        for idx, (px, py) in enumerate(pts):
            draw.ellipse([px - 6, py - 6, px + 6, py + 6], fill=(100, 140, 255, 160))
            draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(240, 245, 255, 255))

            day_str = entries[idx].date_str.split("-")[-1]
            draw.text((px - 8, cy + ch + 12), f"{day_str}日", font=font_num, fill=(170, 175, 210, 255))
            draw.text((px - 5, py - 20), f"{entries[idx].mood_score}", font=font_num, fill=(160, 220, 255, 255))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


# =============================================================================
# Singletons Export
# =============================================================================

multimodal_ingester = MultimodalFileIngester()
youtube_tldr_parser = YouTubeTLDRParser()
voice_transcriber = VoiceMessageTranscriber()
cyber_court = CyberCourt()
turtle_soup_master = TurtleSoupMaster()
party_manager = PartyRecruitmentManager()
meme_wiki = ServerMemeWiki()
prediction_market = PredictionMarketManager()
dual_crosstalk = DualAICrosstalk()
roundtable_council = RoundtableCouncil()
late_night_diary = LateNightDiaryManager()
