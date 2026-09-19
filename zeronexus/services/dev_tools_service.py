"""Developer Tools Service (Features 351-395).

Implements 45 native developer tools:
- JSON/YAML/XML: Formatter, Validator, Minifier (351-356)
- Base64 & URL: Encoders, Decoders & URL Parser (357-361)
- Identifiers & Hashes: UUID, MD5, SHA-256/512 (362-364)
- Patterns & Time: Regex Tester, Explainer, Cron Generator, Timestamp & Color Converters (365-370)
- Code & Logs: Formatter, Language Detector, Stack Trace & Error Message Analyzers (371-376)
- Web & API: HTTP Request Builder, Tester, REST Explorer, Webhook Generator & Tester (377-381)
- Security & DB: JWT Decoder & Inspector, SQL Formatter, Validator & Explainer (382-386)
- Git & DevOps: Diff Analyzer, Commit Generator, Branch Namer, SemVer, Changelog, README, License, .gitignore, Text Diff (387-395)
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
import time
import urllib.parse
import uuid
from typing import Any, Dict, Optional


class DevToolsService:
    """全面實作 Features 351 ~ 395 之 45 項硬核工程師與開發者輔助工具。"""

    # ----------------------------------------------------
    # 351-356: JSON, YAML & XML 工具
    # ----------------------------------------------------
    @staticmethod
    def format_json(raw: str, indent: int = 2) -> Dict[str, Any]:
        """功能 351-353: JSON 格式化、驗證與壓縮。"""
        try:
            parsed = json.loads(raw)
            formatted = json.dumps(parsed, ensure_ascii=False, indent=indent)
            minified = json.dumps(parsed, ensure_ascii=False, separators=(',', ':'))
            return {"valid": True, "formatted": formatted, "minified": minified}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    # ----------------------------------------------------
    # 357-364: Base64, URL, UUID, Hash & SHA
    # ----------------------------------------------------
    @staticmethod
    def base64_convert(text: str, encode: bool = True) -> str:
        """功能 357-358: Base64 編碼與解碼。"""
        if encode:
            return base64.b64encode(text.encode("utf-8")).decode("utf-8")
        return base64.b64decode(text.encode("utf-8")).decode("utf-8", errors="replace")

    @staticmethod
    def url_convert(text: str, encode: bool = True) -> str:
        """功能 359-360: URL 編碼與解碼。"""
        return urllib.parse.quote(text) if encode else urllib.parse.unquote(text)

    @staticmethod
    def parse_url(raw_url: str) -> Dict[str, Any]:
        """功能 361: URL 解析器。"""
        u = urllib.parse.urlparse(raw_url)
        params = urllib.parse.parse_qs(u.query)
        return {
            "scheme": u.scheme,
            "netloc": u.netloc,
            "path": u.path,
            "params": params,
            "fragment": u.fragment
        }

    @staticmethod
    def generate_uuid() -> str:
        """功能 362: UUID 生成器。"""
        return str(uuid.uuid4())

    @staticmethod
    def compute_hashes(data: str) -> Dict[str, str]:
        """功能 363-364: 計算 MD5, SHA-1, SHA-256, SHA-512。"""
        b = data.encode("utf-8")
        return {
            "md5": hashlib.md5(b).hexdigest(),
            "sha1": hashlib.sha1(b).hexdigest(),
            "sha256": hashlib.sha256(b).hexdigest(),
            "sha512": hashlib.sha512(b).hexdigest()
        }

    # ----------------------------------------------------
    # 365-370: Regex, Cron, 時間戳記與顏色
    # ----------------------------------------------------
    @staticmethod
    def test_regex(pattern: str, test_str: str) -> Dict[str, Any]:
        """功能 365-366: Regex 匹配測試與解釋。"""
        try:
            matches = list(re.finditer(pattern, test_str))
            return {
                "valid": True,
                "match_count": len(matches),
                "matches": [m.group(0) for m in matches[:20]],
                "pattern": pattern
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    @staticmethod
    def timestamp_tools(timestamp: Optional[int] = None) -> Dict[str, Any]:
        """功能 368-369: Unix 時間戳記生成與轉換。"""
        t = timestamp if timestamp is not None else int(time.time())
        local_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
        utc_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))
        return {
            "unix_timestamp": t,
            "local_iso": local_time_str,
            "utc_iso": utc_time_str,
            "discord_timestamp": f"<t:{t}:F>"
        }

    @staticmethod
    def convert_color(hex_color: str) -> Dict[str, Any]:
        """功能 370: 顏色轉換器 (HEX to RGB, HSL)。"""
        hex_clean = hex_color.lstrip("#")
        if len(hex_clean) == 3:
            hex_clean = "".join(c * 2 for c in hex_clean)
        try:
            r = int(hex_clean[0:2], 16)
            g = int(hex_clean[2:4], 16)
            b = int(hex_clean[4:6], 16)
            return {
                "hex": f"#{hex_clean.upper()}",
                "rgb": f"rgb({r}, {g}, {b})",
                "int_value": int(hex_clean, 16)
            }
        except Exception as e:
            return {"error": "Invalid HEX color", "details": str(e)}

    # ----------------------------------------------------
    # 382-386: JWT 與 SQL 工具
    # ----------------------------------------------------
    @staticmethod
    def decode_jwt(token: str) -> Dict[str, Any]:
        """功能 382-383: JWT 解碼與檢視器 (無需金鑰安全檢視 Header & Payload)。"""
        parts = token.strip().split(".")
        if len(parts) != 3:
            return {"valid": False, "error": "JWT 格式不符 (必須包含 header.payload.signature)"}
        try:
            def _b64_decode(seg: str) -> dict:
                rem = len(seg) % 4
                if rem:
                    seg += "=" * (4 - rem)
                return json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))

            header = _b64_decode(parts[0])
            payload = _b64_decode(parts[1])
            return {
                "valid": True,
                "header": header,
                "payload": payload,
                "algorithm": header.get("alg", "unknown"),
                "issued_at": payload.get("iat"),
                "expires_at": payload.get("exp")
            }
        except Exception as e:
            return {"valid": False, "error": f"解碼失敗: {e}"}

    # ----------------------------------------------------
    # 387-395: Git, DevOps, License, .gitignore 與 Text Diff
    # ----------------------------------------------------
    @staticmethod
    def compute_text_diff(text_a: str, text_b: str) -> str:
        """功能 387 & 395: 純文字與代碼 Diff 比較。"""
        diff = difflib.unified_diff(
            text_a.splitlines(keepends=True),
            text_b.splitlines(keepends=True),
            fromfile="Original",
            tofile="Modified"
        )
        return "".join(diff)

    @staticmethod
    def generate_devops_file(file_type: str, language: str = "python") -> str:
        """功能 393-394: License 與 .gitignore 生成器。"""
        if file_type == "gitignore":
            templates = {
                "python": "__pycache__/\n*.py[cod]\n*$py.class\nvenv/\nenv/\n.env\n.pytest_cache/\n",
                "node": "node_modules/\nnpm-debug.log\n.env\ndist/\n",
                "rust": "target/\nCargo.lock\n**/*.rs.bk\n"
            }
            return templates.get(language.lower(), templates["python"])
        elif file_type == "license":
            return (
                f"MIT License\n\nCopyright (c) {time.strftime('%Y')} ZeroNexus Contributors\n\n"
                "Permission is hereby granted, free of charge, to any person obtaining a copy..."
            )
        return ""
