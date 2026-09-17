"""ZeroNexus Single-Instance Process Lock.

Guarantees that only ONE bot process runs at any given time per host/container.
Uses dual-layer protection:
1. OS-level File Lock (`fcntl.flock` on `data/zeronexus.lock`)
2. Local TCP Socket Lock (binds to port 48199 to block cross-container / cross-directory execution)

Prevents duplicate Discord Gateway connections, duplicate logging, and duplicate
AI API calls that trigger rate limit cooldowns.
"""

from __future__ import annotations

import atexit
import os
import socket
import sys
from pathlib import Path
from typing import Optional

try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

DEFAULT_LOCK_PORT = 48199


class SingleInstanceLock:
    """Acquires exclusive OS file and socket locks to ensure only one instance runs."""

    def __init__(self, lock_file: Optional[Path] = None, port: int = DEFAULT_LOCK_PORT) -> None:
        if lock_file is None:
            # Default to data/zeronexus.lock relative to project root
            project_root = Path(__file__).resolve().parent.parent.parent
            self.lock_file = project_root / "data" / "zeronexus.lock"
        else:
            self.lock_file = lock_file

        self.port = port
        self._file_obj = None
        self._sock: Optional[socket.socket] = None
        self._is_locked = False

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    def acquire(self) -> bool:
        """Attempts to acquire exclusive file and socket locks.

        Returns True if acquired successfully, False if another instance is already running.
        """
        if self._is_locked:
            return True

        # 1. Socket lock (protects across separate containers, directories, and processes)
        if self.port > 0:
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                self._sock.bind(("0.0.0.0", self.port))
                self._sock.listen(1)
            except OSError:
                print("=" * 70, file=sys.stderr)
                print("🛑 【ZeroNexus 單實例保護攔截】", file=sys.stderr)
                print(f"檢測到已有另一個 ZeroNexus 實例正在運行中（Port {self.port} 已被佔用）！", file=sys.stderr)
                print("為防止 Discord Gateway 雙重登入、終端機日誌重複印出、以及連續請求引發 AI 金鑰冷卻，", file=sys.stderr)
                print("本程序已自動安全中止啟動。", file=sys.stderr)
                print("=" * 70, file=sys.stderr)
                self._sock = None
                return False

        # 2. File lock (protects filesystem level)
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._file_obj = open(self.lock_file, "a+", encoding="utf-8")
        except Exception as e:
            print(f"[WARN] [ZeroNexus] 無法建立實例鎖定檔案 ({self.lock_file}): {e}")
            self._is_locked = True
            atexit.register(self.release)
            return True

        if HAS_FCNTL:
            try:
                fcntl.flock(self._file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, IOError):
                # Read existing PID if possible
                existing_pid = "未知"
                try:
                    self._file_obj.seek(0)
                    content = self._file_obj.read().strip()
                    if content:
                        existing_pid = content
                except Exception:
                    pass

                print("=" * 70, file=sys.stderr)
                print("🛑 【ZeroNexus 單實例保護攔截】", file=sys.stderr)
                print(f"檢測到已有另一個 ZeroNexus 實例正在運行中（PID: {existing_pid}）！", file=sys.stderr)
                print("為防止 Discord Gateway 雙重登入、終端機日誌重複印出、以及連續請求引發 AI 金鑰冷卻，", file=sys.stderr)
                print("本程序已自動安全中止啟動。", file=sys.stderr)
                print("=" * 70, file=sys.stderr)

                try:
                    self._file_obj.close()
                except Exception:
                    pass
                self._file_obj = None

                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                    self._sock = None
                return False

        # Lock acquired: write current PID
        try:
            self._file_obj.seek(0)
            self._file_obj.truncate()
            self._file_obj.write(f"{os.getpid()}\n")
            self._file_obj.flush()
        except Exception:
            pass

        self._is_locked = True
        atexit.register(self.release)
        return True

    def release(self) -> None:
        """Releases the file lock and socket cleanly."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._file_obj is not None:
            if HAS_FCNTL:
                try:
                    fcntl.flock(self._file_obj.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

            try:
                self._file_obj.close()
            except Exception:
                pass
            self._file_obj = None

        self._is_locked = False

        # Attempt to remove lock file
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except Exception:
            pass

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            sys.exit(0)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


# Global lock instance for the main application
process_lock = SingleInstanceLock()
