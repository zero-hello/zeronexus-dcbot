#!/usr/bin/env python3
"""Compatibility entry point for :mod:`scripts.verify_zero_intelligence_demo`."""

from importlib import import_module
from pathlib import Path
from runpy import run_module
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if __name__ == "__main__":
    run_module("scripts.intelligence.verify_zero_intelligence_demo", run_name="__main__")
else:
    _impl = import_module("scripts.intelligence.verify_zero_intelligence_demo")
    for _name, _value in vars(_impl).items():
        if not _name.startswith("__"):
            globals()[_name] = _value
