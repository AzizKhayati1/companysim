"""Runnable demo — same as `companysim demo` but importable standalone."""
from __future__ import annotations

from companysim.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["demo", "--headcount", "200", "--ticks", "30"]))
