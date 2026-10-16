# -*- coding: utf-8 -*-
"""Flash Music — entry point."""

from __future__ import annotations

import sys


def _ensure_utf8_stdio() -> None:
    """Avoid GBK console crashes on Windows when printing Unicode."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def main() -> int:
    _ensure_utf8_stdio()
    from app import run_app

    return run_app()


if __name__ == "__main__":
    sys.exit(main())
