#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZeroNexus 版本檢查與安全更新服務 (Version & Update Sentinel).

授權條款：Apache License 2.0
版權所有：Copyright 2026 Zero

安全原則：
1. 僅提供版本查詢與比對，嚴禁任何未授權的 push 操作。
2. 本地版本 >= 遠端版本時，判定為無新更新，不執行任何操作。
3. 遠端版本 > 本地版本時，提供新版本通知資訊。
"""

from __future__ import annotations

import asyncio
import re
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

# 專案路徑與官方最新版本端點
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_VERSION_FILE = PROJECT_ROOT / "version.txt"
REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/zero-hello/zeronexus-dcbot/main/version.txt"
)


def parse_version(version_str: str) -> tuple[int, ...]:
    """解析語意化版本字串（例如 'v1.0.0' 或 '1.2.3'）為整數元組。"""
    cleaned = re.sub(r"^[^\d]*", "", (version_str or "").strip())
    numbers = re.findall(r"\d+", cleaned)
    if not numbers:
        return (0, 0, 0)
    return tuple(map(int, numbers))


def get_local_version() -> str:
    """取得當前本地版本，優先讀取 settings.json 與 zeronexus.__version__，並與 version.txt 同步。"""
    try:
        from zeronexus import __version__
        current_v = f"v{__version__.lstrip('v')}"
        if not LOCAL_VERSION_FILE.exists() or LOCAL_VERSION_FILE.read_text(encoding="utf-8").strip() != current_v:
            try:
                LOCAL_VERSION_FILE.write_text(f"{current_v}\n", encoding="utf-8")
            except Exception:
                pass
        return current_v
    except Exception:
        pass

    if LOCAL_VERSION_FILE.exists():
        try:
            val = LOCAL_VERSION_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass
    return "v2.2.1"


def fetch_remote_version_sync() -> Optional[str]:
    """同步獲取官方遠端 GitHub 倉庫最新版本號。"""
    headers = {
        "User-Agent": "ZeroNexus-Updater/1.0",
        "Cache-Control": "no-cache",
    }
    req = urllib.request.Request(REMOTE_VERSION_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            if response.status == 200:
                content = response.read().decode("utf-8").strip()
                if content:
                    return content
    except Exception:
        return None
    return None


async def fetch_remote_version_async() -> Optional[str]:
    """非同步獲取官方遠端 GitHub 倉庫最新版本號（不阻塞事件循環）。"""
    return await asyncio.to_thread(fetch_remote_version_sync)


async def check_for_updates_async() -> Tuple[bool, str, Optional[str]]:
    """
    非同步檢查是否有新版本發布。
    
    回傳：
        (has_new_version, local_version, remote_version)
        - has_new_version: 僅在 remote_version 成功獲取且 remote > local 時為 True。
    """
    local_ver = get_local_version()
    remote_ver = await fetch_remote_version_async()
    if not remote_ver:
        return False, local_ver, None

    local_tuple = parse_version(local_ver)
    remote_tuple = parse_version(remote_ver)

    # 嚴格遵循鐵律：只有在 remote > local 時才視為有更新
    # local >= remote 時不作任何操作
    has_update = remote_tuple > local_tuple
    return has_update, local_ver, remote_ver
