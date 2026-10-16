# -*- coding: utf-8 -*-
"""Flash Music — persist settings under user config dir."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


APP_NAME = "FlashMusic"
CONFIG_VERSION = 1


def config_dir() -> Path:
    override = os.environ.get("FLASHMUSIC_CONFIG_DIR")
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_NAME
    else:
        path = Path.home() / ".flash_music"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def default_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "playlist": [],
        "volume": 0.7,
        "last_index": 0,
        "position_ms": 0,  # relative ms within current track
        "shuffle": False,
        "repeat": "off",  # off | one | all
        "last_folder": "",
        "recent_paths": [],  # last 3 opened folders/files
        "last_export_dir": "",  # remembered MP3 export folder
        "geometry": None,  # [x, y, w, h]
        "window_state": None,  # base64 or omit
    }


def load_config() -> dict[str, Any]:
    path = config_path()
    data = default_config()
    raw = None
    # main file first, then the last-known-good backup (survives torn writes)
    for candidate in (path, path.with_suffix(".json.bak")):
        if not candidate.is_file():
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                raw = loaded
                break
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    if raw is None:
        return data
    data.update(raw)
    # sanitize
    if not isinstance(data.get("playlist"), list):
        data["playlist"] = []
    cleaned_pl: list = []
    for p in data["playlist"]:
        if isinstance(p, str) and p.strip():
            cleaned_pl.append(p.strip())
        elif isinstance(p, dict) and isinstance(p.get("path"), str) and p["path"].strip():
            cleaned_pl.append(p)
    data["playlist"] = cleaned_pl
    try:
        vol = float(data.get("volume", 0.7))
        data["volume"] = max(0.0, min(1.0, vol))
    except (TypeError, ValueError):
        data["volume"] = 0.7
    if data.get("repeat") not in ("off", "one", "all"):
        data["repeat"] = "off"
    recent = data.get("recent_paths") or []
    if not isinstance(recent, list):
        recent = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for p in recent:
        if not isinstance(p, str) or not p.strip():
            continue
        key = p.strip()
        low = key.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(key)
        if len(cleaned) >= 3:
            break
    data["recent_paths"] = cleaned
    data["shuffle"] = bool(data.get("shuffle", False))
    try:
        data["last_index"] = max(0, int(data.get("last_index", 0)))
    except (TypeError, ValueError):
        data["last_index"] = 0
    try:
        data["position_ms"] = max(0, int(data.get("position_ms", 0)))
    except (TypeError, ValueError):
        data["position_ms"] = 0
    return data


def save_config(data: dict[str, Any]) -> None:
    path = config_path()
    out = default_config()
    out.update(data)
    out["version"] = CONFIG_VERSION
    # Atomic write: tmp file + fsync + os.replace, so a kill / crash mid-write
    # can never leave a truncated config.json (which would load as empty).
    tmp = path.with_suffix(".json.tmp")
    try:
        text = json.dumps(out, ensure_ascii=False, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.is_file():
            try:
                os.replace(path, path.with_suffix(".json.bak"))
            except OSError:
                pass
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        try:
            tmp.unlink()
        except OSError:
            pass
