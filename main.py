#!/usr/bin/env python3
"""ZeroNexus Root Launch Script.

Direct execution:
    python3 main.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 1. Ensure project root directory is on Python path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 2. Intelligent venv auto-detection:
# If executed directly with system Python without activating venv,
# automatically hand over to `znenv` so all dependencies work out of the box.
VENV_DIR = PROJECT_ROOT / "znenv"
VENV_PYTHON = VENV_DIR / "bin" / "python3"
if VENV_PYTHON.exists() and sys.prefix != str(VENV_DIR):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])

from zeronexus.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ZeroNexus] 系統已依使用者指示正常關閉。")
        sys.exit(0)
