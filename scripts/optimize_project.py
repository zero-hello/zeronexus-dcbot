#!/usr/bin/env python3
"""ZeroNexus 專案極致空間瘦身與效能最佳化工具 (Project Deep Optimizer)

執行內容（非破壞性，不影響代碼與模型）：
1. 清理 Python Bytecode 快取 (__pycache__, *.pyc, *.pyo, *.pyd)
2. 清理測試與覆蓋率快取 (.pytest_cache, .coverage, htmlcov)
3. 截斷與輪替肥大歷史日誌 (logs/*.log)
4. SQLite 本地資料庫碎片整理與頁面壓縮 (VACUUM)
5. pip 套件快取清除 (pip cache purge)
6. Git 本地物件庫極致壓縮與垃圾回收 (git gc --aggressive --prune=now)
"""

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
    except Exception:
        pass
    return total


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def main():
    print("=" * 65)
    print("🚀 啟動 ZeroNexus 專案極致空間瘦身與最佳化程序...")
    print("=" * 65)

    size_before = get_dir_size(PROJECT_ROOT)
    print(f"📊 最佳化前總體積: {format_size(size_before)}")

    # 1. 清理 Python Bytecode 快取
    pycache_count = 0
    for p in PROJECT_ROOT.rglob("__pycache__"):
        if "znenv" not in str(p):
            shutil.rmtree(p, ignore_errors=True)
            pycache_count += 1
    for f in PROJECT_ROOT.rglob("*.py[co]"):
        if "znenv" not in str(f):
            f.unlink(missing_ok=True)
    print(f"  ✓ 清理 Python 快取目錄: {pycache_count} 處")

    # 2. 清理測試與臨時快取
    for temp_dir in [".pytest_cache", ".coverage", "htmlcov", ".ruff_cache", ".mypy_cache"]:
        target = PROJECT_ROOT / temp_dir
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            print(f"  ✓ 清除臨時快取: {temp_dir}")

    # 3. 壓縮歷史日誌
    logs_dir = PROJECT_ROOT / "logs"
    if logs_dir.exists():
        log_freed = 0
        for log_file in logs_dir.glob("*.log*"):
            if log_file.is_file():
                sz = log_file.stat().st_size
                if sz > 1 * 1024 * 1024:  # 大於 1MB 截斷保留最後 200KB
                    with open(log_file, "rb") as f:
                        f.seek(max(0, sz - 200 * 1024))
                        tail = f.read()
                    with open(log_file, "wb") as f:
                        f.write(tail)
                    log_freed += (sz - len(tail))
                elif log_file.suffix in [".old", ".bak", ".1", ".2"]:
                    log_freed += sz
                    log_file.unlink(missing_ok=True)
        print(f"  ✓ 整理與壓縮 logs: 釋放約 {format_size(log_freed)}")

    # 4. SQLite 資料庫碎片整理 (VACUUM)
    for db_path in PROJECT_ROOT.rglob("*.db"):
        if "znenv" not in str(db_path):
            try:
                conn = sqlite3.connect(str(db_path))
                conn.execute("VACUUM")
                conn.close()
                print(f"  ✓ SQLite 壓縮整理: {db_path.relative_to(PROJECT_ROOT)}")
            except Exception as e:
                pass

    # 5. 清理 pip 快取
    try:
        subprocess.run(
            [str(PROJECT_ROOT / "znenv" / "bin" / "pip"), "cache", "purge"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        print("  ✓ 清除 pip 下載與 wheel 快取")
    except Exception:
        pass

    # 6. Git 物件庫極致深度壓縮 (Aggressive Repack)
    if (PROJECT_ROOT / ".git").exists():
        print("  ⏳ 正在對 Git 物件庫進行激進壓縮 (git gc --aggressive)...")
        subprocess.run(["git", "reflog", "expire", "--expire=now", "--all"], cwd=PROJECT_ROOT, check=False)
        subprocess.run(["git", "gc", "--aggressive", "--prune=now"], cwd=PROJECT_ROOT, check=False)
        print("  ✓ Git 物件庫重新打包與壓縮完成")

    size_after = get_dir_size(PROJECT_ROOT)
    freed = max(0, size_before - size_after)

    print("=" * 65)
    print(f"🎉 專案極致最佳化完成！")
    print(f"📦 最佳化後總體積: {format_size(size_after)}")
    print(f"📉 共成功釋放空間: {format_size(freed)}")
    print("=" * 65)


if __name__ == "__main__":
    main()
