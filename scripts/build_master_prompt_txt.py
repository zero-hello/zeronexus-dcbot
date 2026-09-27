#!/usr/bin/env python3
"""Compatibility entry point for :mod:`scripts.build_master_prompt_txt`."""

from importlib import import_module
from pathlib import Path
from runpy import run_module
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if __name__ == "__main__":
    run_module("scripts.prompts.build_master_prompt_txt", run_name="__main__")
else:
    _impl = import_module("scripts.prompts.build_master_prompt_txt")
    for _name, _value in vars(_impl).items():
        if not _name.startswith("__"):
            globals()[_name] = _value
