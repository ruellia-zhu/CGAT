"""Frozen-app entry point (PyInstaller cannot launch `python -m app`)."""
from __future__ import annotations

import multiprocessing
import sys

from app.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv))
