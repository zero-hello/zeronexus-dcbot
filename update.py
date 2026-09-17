#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZeroNexus 安全用戶端自動更新器 (Safe Client Updater).

授權條款：Apache License 2.0
版權所有：Copyright 2026 Zero

安全架構聲明：
1. 本更新器為單向拉取工具 (Pull-Only)，專供使用者或伺服器主機同步官方最新版本。
2. 【最高安全防線】：本地版本若大於或等於遠端版本，絕對不執行任何操作（嚴禁任何上推行為）！
3. 僅在遠端官方版本嚴格高於本地版本時，才執行安全拉取 (git pull origin main)。
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from pathlib import Path

# 專案目錄與官方版本資訊來源
PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_VERSION_FILE = PROJECT_ROOT / "version.txt"
REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/zero-hello/zeronexus-dcbot/main/version.txt"
)


def parse_version(version_str: str) -> tuple[int, ...]:
    """解析語意化版本字串（例如 'v1.0.0' 或 '1.2.3'）為整數元組。"""
    cleaned = re.sub(r"^[^\d]*", "", version_str.strip())
    numbers = re.findall(r"\d+", cleaned)
    if not numbers:
        return (0, 0, 0)
    return tuple(map(int, numbers))


def read_local_version() -> str:
    """讀取本地 version.txt。"""
    if LOCAL_VERSION_FILE.exists():
        try:
            return LOCAL_VERSION_FILE.read_text(encoding="utf-8").strip()
        except Exception as e:
            print(f"[WARN] 讀取本地 version.txt 失敗: {e}")
    return "v1.0.0"


def fetch_remote_version() -> str | None:
    """向官方 GitHub 倉庫查詢最新版本號。"""
    headers = {
        "User-Agent": "ZeroNexus-Updater/1.0",
        "Cache-Control": "no-cache",
    }
    req = urllib.request.Request(REMOTE_VERSION_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                content = response.read().decode("utf-8").strip()
                return content
    except Exception as e:
        print(f"[提示] 無法連線至官方遠端版本端點 ({e})，可能尚未發布或網路連線異常。")
        return None
    return None


def run_command(cmd: list[str]) -> bool:
    """執行本機安全指令。"""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            print(result.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        print(f"[錯誤] 執行指令失敗 ({' '.join(cmd)}):")
        if e.stderr:
            print(e.stderr.strip())
        return False


def main() -> None:
    print("=" * 60)
    print("  ZeroNexus 安全用戶端更新器 (Safe Client Updater)")
    print("=" * 60)

    # 1. 取得本地版本
    local_ver_str = read_local_version()
    local_ver_tuple = parse_version(local_ver_str)
    print(f"📌 當前本地版本: {local_ver_str}")

    # 2. 取得遠端版本
    print("🔍 正在檢查遠端官方最新發布版本...")
    remote_ver_str = fetch_remote_version()

    if not remote_ver_str:
        print("ℹ️ 無法獲取遠端版本資訊，安全退出，不執行任何變更。")
        sys.exit(0)

    remote_ver_tuple = parse_version(remote_ver_str)
    print(f"🌐 遠端最新版本: {remote_ver_str}")

    # 3. 嚴密版本比對公理：本地 >= 遠端 ➔ 絕對不做任何操作！
    if local_ver_tuple >= remote_ver_tuple:
        print("\n✅ 當前本地版本已是最新（或高於遠端版本），無需更新。")
        print("🛡️ 安全防護機制：未觸發更新條件，系統已安全退出。")
        sys.exit(0)

    # 4. 僅當遠端版本嚴格高於本地版本時，引導更新
    print(f"\n🚀 偵測到新版本可用: {remote_ver_str}（本地版本: {local_ver_str}）")
    print("📦 正在從官方倉庫拉取最新程式碼...")

    # 檢查是否在 git 倉庫中
    git_dir = PROJECT_ROOT / ".git"
    if not git_dir.exists():
        print("[錯誤] 本專案目錄不是 Git 倉庫，無法自動拉取更新。請直接至 GitHub 下載最新壓縮檔。")
        sys.exit(1)

    # 執行安全拉取 (git pull origin main)
    success = run_command(["git", "pull", "origin", "main"])
    if success:
        print("\n🎉 ZeroNexus 核心代碼已成功更新至最新版本！")
        print("💡 建議重新啟動機器人以套用最新功能變更：python3 main.py")
    else:
        print("\n⚠️ 拉取更新時發生錯誤，請檢查是否有本地檔案衝突或網路連線問題。")
        sys.exit(1)


if __name__ == "__main__":
    main()
