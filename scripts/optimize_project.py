#!/usr/bin/env python3
"""Compatibility entry point for :mod:`scripts.optimize_project`."""

from importlib import import_module
import sys

_impl = import_module("scripts.maintenance.optimize_project")
for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

if __name__ == "__main__":
    _impl.main()
