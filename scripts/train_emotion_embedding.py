#!/usr/bin/env python3
"""Compatibility entry point for :mod:`scripts.train_emotion_embedding`."""

from importlib import import_module
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_impl = import_module("scripts.brain.train_emotion_embedding")
for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

if __name__ == "__main__":
    _impl.main()
