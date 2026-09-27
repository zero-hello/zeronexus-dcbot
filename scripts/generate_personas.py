#!/usr/bin/env python3
"""Compatibility entry point for :mod:`scripts.generate_personas`."""

from importlib import import_module
import sys

_impl = import_module("scripts.prompts.generate_personas")
for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

if __name__ == "__main__":
    _impl.main()
