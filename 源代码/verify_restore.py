# -*- coding: utf-8 -*-
"""End-to-end check: playlist survives close (title-bar ✕) + relaunch.

Usage:
    python verify_restore.py <music folder> [--exe path\\to\\FlashMusic.exe]

Uses an isolated config dir (FLASHMUSIC_CONFIG_DIR) so the real
%LOCALAPPDATA%\\FlashMusic\\config.json is never touched.
Run 1: launch, load the folder, click the title-bar ✕ (same code path).
Run 2: relaunch with no input, report how many tracks were restored.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd: list[str], env_extra: dict, report: Path, timeout: int = 60) -> dict:
    env = dict(os.environ)
    env.update(env_extra)
    env["FLASHMUSIC_TEST_REPORT"] = str(report)
    if report.exists():
        report.unlink()
    proc = subprocess.run(cmd, env=env, timeout=timeout, capture_output=True)
    if not report.exists():
        raise SystemExit(f"no report (exit={proc.returncode}): {proc.stderr[-800:]!r}")
    data = json.loads(report.read_text(encoding="utf-8"))
    data["exit_code"] = proc.returncode
    return data


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    folder = args[0]
    cmd = [sys.executable, str(HERE / "main.py")]
    if "--exe" in args:
        cmd = [args[args.index("--exe") + 1]]
    work = Path(tempfile.mkdtemp(prefix="fm_verify_"))
    cfg_dir = work / "cfg"
    base = {"FLASHMUSIC_CONFIG_DIR": str(cfg_dir)}

    r1 = run(cmd, {**base, "FLASHMUSIC_TEST_ADD": folder}, work / "r1.json")
    saved = json.loads((cfg_dir / "config.json").read_text(encoding="utf-8"))
    r2 = run(cmd, base, work / "r2.json")
    r3 = run(cmd, base, work / "r3.json")  # restore -> close -> restore again

    print("cmd          :", " ".join(cmd))
    print("run1 loaded  :", r1["restored_tracks"], "tracks, exit", r1["exit_code"])
    print("saved config :", len(saved.get("playlist", [])), "entries")
    print("run2 restored:", r2["restored_tracks"], "tracks / rows", r2["list_rows"], "exit", r2["exit_code"])
    print("run3 restored:", r3["restored_tracks"], "tracks (second relaunch)")
    print("fluid        :", r2.get("fluid_backend"), r2.get("fluid_fallback_reason") or "")
    ok = r1["restored_tracks"] > 0 and r2["restored_tracks"] == r1["restored_tracks"] == r3["restored_tracks"] \
        and r2["list_rows"] == r1["restored_tracks"]
    print("RESULT       :", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
