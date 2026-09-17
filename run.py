#!/usr/bin/env python3
"""ZeroNexus Launcher Shortcut."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    main_script = Path(__file__).resolve().parent / "main.py"
    runpy.run_path(str(main_script), run_name="__main__")
