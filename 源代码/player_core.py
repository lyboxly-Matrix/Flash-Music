# -*- coding: utf-8 -*-
"""Flash Music — playlist + QMediaPlayer core (incl. CUE sheet tracks)."""

from __future__ import annotations

import os
import random
import logging
import logging.handlers
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import (
    QAudioBuffer,
    QAudioBufferOutput,
    QAudioFormat,
    QMediaDevices,
    QMediaPlayer,
)

from mf_backend import MFAudioOutput, MFPlayer


AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac", ".wma"}


def natural_key(text: str) -> list:
    """Natural sort key: 'track 2' before 'track 10'."""
    parts = re.split(r"(\d+)", text.lower())
    result: list = []
    for p in parts:
        if p.isdigit():
            result.append(int(p))
        else:
            result.append(p)
    return result


def cue_time_to_ms(mm_ss_ff: str) -> int:
    """CUE INDEX time MM:SS:FF (FF = 1/75s frames) -> milliseconds."""
    parts = mm_ss_ff.strip().split(":")
    if len(parts) != 3:
        return 0
    try:
        minutes = int(parts[0])
        seconds = int(parts[1])
        frames = int(parts[2])
    except ValueError:
        return 0
    return int(round((minutes * 60 + seconds) * 1000 + frames * 1000 / 75))


def _decode_cue_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _cue_unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def parse_cue_file(cue_path: str) -> list[dict[str, Any]]:
    """Parse a .cue sheet into track dicts with path/title/artist/start_ms."""
    path = Path(cue_path)
    if not path.is_file():
        return []
    try:
        text = _decode_cue_bytes(path.read_bytes())
    except OSError:
        return []

    album_title = ""
    album_artist = ""
    current_file: Optional[Path] = None
    tracks: list[dict[str, Any]] = []
    pending: Optional[dict[str, Any]] = None

    def flush_pending() -> None:
        nonlocal pending
        if pending and pending.get("path") and pending.get("start_ms") is not None:
            tracks.append(pending)
        pending = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("REM "):
            continue

        if upper.startswith("PERFORMER "):
            val = _cue_unquote(line[10:].strip())
            if pending is None:
                album_artist = val
            else:
                pending["artist"] = val
            continue

        if upper.startswith("TITLE "):
            val = _cue_unquote(line[6:].strip())
            if pending is None:
                album_title = val
            else:
                pending["title"] = val
            continue

        if upper.startswith("FILE "):
            flush_pending()
            m = re.match(r"FILE\s+(.+?)\s+\S+\s*$", line, flags=re.IGNORECASE)
            if not m:
                current_file = None
                continue
            fname = _cue_unquote(m.group(1).strip())
            candidate = (path.parent / fname).resolve()
            if not candidate.is_file():
                alt = path.parent / Path(fname).name
                candidate = alt.resolve() if alt.is_file() else candidate
            current_file = candidate if candidate.is_file() else None
            continue

        if upper.startswith("TRACK "):
            flush_pending()
            pending = {
                "path": str(current_file) if current_file else "",
                "title": "",
                "artist": album_artist,
                "start_ms": None,
                "end_ms": None,
                "album": album_title,
            }
            continue

        if pending is not None and upper.startswith("INDEX "):
            m = re.match(r"INDEX\s+(\d+)\s+(\d+:\d+:\d+)", line, flags=re.IGNORECASE)
            if not m:
                continue
            idx_no = int(m.group(1))
            ms = cue_time_to_ms(m.group(2))
            if idx_no == 1 or pending.get("start_ms") is None:
                pending["start_ms"] = ms
            continue

    flush_pending()

    for i, t in enumerate(tracks):
        if not t.get("title"):
            t["title"] = f"Track {i + 1}"
        if not t.get("artist"):
            t["artist"] = album_artist
        end = None
        for j in range(i + 1, len(tracks)):
            if tracks[j].get("path") == t.get("path"):
                end = tracks[j].get("start_ms")
                break
        t["end_ms"] = end

    return [
        t
        for t in tracks
        if t.get("path") and Path(t["path"]).is_file() and t.get("start_ms") is not None
    ]


def read_metadata(path: str) -> tuple[str, str]:
    """Return (title, artist). Falls back to filename if mutagen missing/fails."""
    name = Path(path).stem
    try:
        from mutagen import File as MutagenFile  # type: ignore

        audio = MutagenFile(path, easy=True)
        if audio is None:
            return name, ""
        title = ""
        artist = ""
        if hasattr(audio, "tags") and audio.tags:
            t = audio.tags.get("title")
            a = audio.tags.get("artist")
            if t:
                title = str(t[0]) if isinstance(t, list) else str(t)
            if a:
                artist = str(a[0]) if isinstance(a, list) else str(a)
        if not title:
            title = name
        return title, artist
    except Exception:
        return name, ""


@dataclass
class Track:
    path: str
    title: str = ""
    artist: str = ""
    start_ms: int = 0
    end_ms: Optional[int] = None
    album: str = ""

    def __post_init__(self) -> None:
        self.start_ms = int(self.start_ms or 0)
        if self.end_ms is not None:
            self.end_ms = int(self.end_ms)
        if not self.title:
            t, a = read_metadata(self.path)
            self.title = t
            if not self.artist:
                self.artist = a

    @property
    def is_cue_track(self) -> bool:
        return self.start_ms > 0 or self.end_ms is not None

    @property
    def display(self) -> str:
        if self.artist:
            return f"{self.title} — {self.artist}"
        return self.title

    def sort_key(self) -> tuple:
        return (
            natural_key(str(Path(self.path).parent)),
            natural_key(Path(self.path).name),
            int(self.start_ms or 0),
            natural_key(self.artist or ""),
            natural_key(self.title or Path(self.path).stem),
        )

    def identity_key(self) -> tuple:
        return (os.path.normcase(os.path.normpath(self.path)), int(self.start_ms or 0))

    def to_config(self) -> dict[str, Any]:
        d: dict[str, Any] = {"path": self.path}
        if self.is_cue_track:
            d["start_ms"] = self.start_ms
            if self.end_ms is not None:
                d["end_ms"] = self.end_ms
            d["title"] = self.title
            d["artist"] = self.artist
            if self.album:
                d["album"] = self.album
        return d

    @staticmethod
    def from_config(entry: Any) -> Optional["Track"]:
        if isinstance(entry, str):
            if Path(entry).is_file():
                return Track(path=entry)
            return None
        if isinstance(entry, dict) and entry.get("path"):
            p = str(entry["path"])
            if not Path(p).is_file():
                return None
            return Track(
                path=p,
                title=str(entry.get("title") or ""),
                artist=str(entry.get("artist") or ""),
                start_ms=int(entry.get("start_ms") or 0),
                end_ms=(int(entry["end_ms"]) if entry.get("end_ms") is not None else None),
                album=str(entry.get("album") or ""),
            )
        return None


def _find_cue_for_audio(audio_path: Path) -> Optional[Path]:
    folder = audio_path.parent
    stem_cue = audio_path.with_suffix(".cue")
    if stem_cue.is_file():
        return stem_cue
    try:
        cues = list(folder.glob("*.cue"))
    except OSError:
        return None
    audio_name = audio_path.name.lower()
    for cue in cues:
        try:
            text = _decode_cue_bytes(cue.read_bytes()).lower()
        except OSError:
            continue
        if audio_name in text or audio_path.stem.lower() in text:
            return cue
    return None


def _uniq_paths(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        k = os.path.normcase(os.path.normpath(x))
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def collect_audio_files(paths: list[str]) -> list[Track]:
    """Expand folders/files into Track list (recursive + CUE expansion)."""
    found_audio: list[str] = []
    cue_files: list[str] = []

    for p in paths:
        path = Path(p)
        if path.is_file():
            suf = path.suffix.lower()
            if suf in AUDIO_EXTENSIONS:
                found_audio.append(str(path.resolve()))
            elif suf == ".cue":
                cue_files.append(str(path.resolve()))
        elif path.is_dir():
            for root, _dirs, files in os.walk(path):
                for name in files:
                    suf = Path(name).suffix.lower()
                    full = str(Path(root, name).resolve())
                    if suf in AUDIO_EXTENSIONS:
                        found_audio.append(full)
                    elif suf == ".cue":
                        cue_files.append(full)

    found_audio = _uniq_paths(found_audio)
    cue_files = _uniq_paths(cue_files)

    tracks: list[Track] = []
    covered_audio: set[str] = set()

    for cue in cue_files:
        parsed = parse_cue_file(cue)
        if not parsed:
            continue
        for item in parsed:
            t = Track(
                path=item["path"],
                title=item.get("title") or "",
                artist=item.get("artist") or "",
                start_ms=int(item.get("start_ms") or 0),
                end_ms=item.get("end_ms"),
                album=item.get("album") or "",
            )
            tracks.append(t)
            covered_audio.add(os.path.normcase(os.path.normpath(t.path)))

    for audio in found_audio:
        key = os.path.normcase(os.path.normpath(audio))
        if key in covered_audio:
            continue
        cue = _find_cue_for_audio(Path(audio))
        if cue is not None:
            parsed = parse_cue_file(str(cue))
            matched = [
                x
                for x in parsed
                if os.path.normcase(os.path.normpath(x["path"])) == key
            ]
            use = matched if matched else parsed
            if use:
                for item in use:
                    t = Track(
                        path=item["path"],
                        title=item.get("title") or "",
                        artist=item.get("artist") or "",
                        start_ms=int(item.get("start_ms") or 0),
                        end_ms=item.get("end_ms"),
                        album=item.get("album") or "",
                    )
                    tracks.append(t)
                    covered_audio.add(os.path.normcase(os.path.normpath(t.path)))
                continue
        tracks.append(Track(path=audio))

    return tracks


def auto_optimize(tracks: list[Track]) -> list[Track]:
    """Dedupe by (path, start_ms), sort sensibly (CUE order preserved per file)."""
    seen: set[tuple] = set()
    unique: list[Track] = []
    for t in tracks:
        if not os.path.isfile(t.path):
            continue
        key = t.identity_key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    unique.sort(key=lambda x: x.sort_key())
    return unique


class PlayerCore(QObject):
    """Owns QMediaPlayer + playlist state."""

    track_changed = Signal(int)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    state_changed = Signal(str)
    playlist_changed = Signal()
    error_occurred = Signal(str)
    volume_changed = Signal(float)
    level_changed = Signal(float)  # 0..1 RMS-ish from audio buffer / idle
    bands_changed = Signal(float, float, float, float)  # bass, mid, high, level (0..1)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._index: int = -1
        self._shuffle: bool = False
        self._repeat: str = "off"
        self._shuffle_order: list[int] = []
        self._shuffle_pos: int = -1
        self._pending_start: int = 0
        self._pending_resume: int = 0  # relative ms after start
        self._pending_autoplay: bool = False
        self._ignore_end_guard: bool = False

        self._level_ema = 0.0
        self._buffer_out = None
        self._player = None  # type: ignore[assignment]
        self._audio = None  # type: ignore[assignment]
        self._build_pipeline(volume=0.7, muted=False)

        self._alog(f"start: backend=Media Foundation (WinRT MediaPlayer) default={self._dev_str(QMediaDevices.defaultAudioOutput())}")

    # ------------------------------------------------------------------ audio diagnostics
    _alogger: Optional[logging.Logger] = None

    def _alog(self, msg: str) -> None:
        try:
            if PlayerCore._alogger is None:
                from config import config_dir  # honours FLASHMUSIC_CONFIG_DIR (tests never touch the real dir)
                lg = logging.getLogger("flashmusic.audio")
                lg.setLevel(logging.INFO)
                lg.propagate = False
                h = logging.handlers.RotatingFileHandler(
                    str(config_dir() / "audio.log"), maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
                h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
                lg.addHandler(h)
                PlayerCore._alogger = lg
            PlayerCore._alogger.info(msg)
        except Exception:
            pass

    @staticmethod
    def _dev_str(d) -> str:
        try:
            if d.isNull():
                return "<null>"
            return f"{d.description()} [{bytes(d.id()).decode('utf-8', 'replace')}]"
        except Exception:
            return "?"

    def _snapshot(self) -> str:
        if self._player is None or self._audio is None:
            return "pipeline=<none>"
        return (f"pos={self.position} abs={int(self._player.position())} state={self._player.playbackState().name} "
                f"status={self._player.mediaStatus().name} vol={self._audio.volume():.2f} muted={self._audio.isMuted()} "
                f"out={self._dev_str(QMediaDevices.defaultAudioOutput())}")

    # ------------------------------------------------------------------ playback pipeline
    def _build_pipeline(self, volume: float = 0.7, muted: bool = False) -> None:
        """Media Foundation player (follows the default output device and rebuilds its stream
        when an endpoint is invalidated, e.g. a Bluetooth speaker after a browser used it),
        plus a QAudioBufferOutput that mf_backend feeds for the visualizer."""
        self._player = MFPlayer(self)
        self._audio = MFAudioOutput(self._player, self)
        self._audio.setVolume(float(volume))
        self._audio.setMuted(bool(muted))
        self._player.setAudioOutput(self._audio)
        self._buffer_out = None
        try:
            self._setup_audio_probe()
        except Exception:
            self._buffer_out = None
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks)

    @property
    def track_count(self) -> int:
        return len(self._tracks)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def current_track(self) -> Optional[Track]:
        if 0 <= self._index < len(self._tracks):
            return self._tracks[self._index]
        return None

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def repeat(self) -> str:
        return self._repeat

    @property
    def volume(self) -> float:
        return float(self._audio.volume())

    @property
    def muted(self) -> bool:
        return bool(self._audio.isMuted())

    @property
    def position(self) -> int:
        track = self.current_track
        pos = int(self._player.position())
        if track:
            return max(0, pos - int(track.start_ms or 0))
        return pos

    @property
    def duration(self) -> int:
        track = self.current_track
        if track and track.end_ms is not None:
            return max(0, int(track.end_ms) - int(track.start_ms or 0))
        file_dur = int(self._player.duration())
        if track and track.start_ms:
            return max(0, file_dur - int(track.start_ms))
        return file_dur

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def set_tracks(
        self, tracks: list[Track], start_index: int = 0, resume_ms: int = 0
    ) -> None:
        self._tracks = list(tracks)
        self._rebuild_shuffle()
        self.playlist_changed.emit()
        if self._tracks:
            idx = max(0, min(start_index, len(self._tracks) - 1))
            self.play_index(idx, autoplay=False, resume_ms=max(0, int(resume_ms or 0)))
        else:
            self._index = -1
            self._player.stop()
            self._player.setSource(QUrl())
            self.track_changed.emit(-1)

    def add_paths(self, paths: list[str], optimize: bool = True) -> int:
        collected = collect_audio_files(paths)
        if not collected:
            return 0
        new_tracks = auto_optimize(collected) if optimize else collected

        existing = {t.identity_key() for t in self._tracks}
        added = 0
        for t in new_tracks:
            key = t.identity_key()
            if key not in existing:
                self._tracks.append(t)
                existing.add(key)
                added += 1

        if optimize and added:
            current = self.current_track
            current_key = current.identity_key() if current else None
            self._tracks.sort(key=lambda x: x.sort_key())
            if current_key:
                for i, t in enumerate(self._tracks):
                    if t.identity_key() == current_key:
                        self._index = i
                        break

        self._rebuild_shuffle()
        self.playlist_changed.emit()
        if self._index < 0 and self._tracks:
            self.play_index(0, autoplay=False)
        return added

    def replace_with_paths(self, paths: list[str], optimize: bool = True) -> int:
        self._player.stop()
        self._tracks.clear()
        self._index = -1
        self._shuffle_order.clear()
        self._shuffle_pos = -1
        n = self.add_paths(paths, optimize=optimize)
        if n == 0:
            self.playlist_changed.emit()
            self.track_changed.emit(-1)
        return n

    def clear_playlist(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self._tracks.clear()
        self._index = -1
        self._shuffle_order.clear()
        self._shuffle_pos = -1
        self.playlist_changed.emit()
        self.track_changed.emit(-1)
        self.state_changed.emit("stopped")

    def remove_index(self, index: int) -> None:
        if not (0 <= index < len(self._tracks)):
            return
        was_current = index == self._index
        del self._tracks[index]
        if self._index > index:
            self._index -= 1
        elif was_current:
            if not self._tracks:
                self.clear_playlist()
                return
            self._index = min(index, len(self._tracks) - 1)
            self._load_current(autoplay=self.is_playing)
        self._rebuild_shuffle()
        self.playlist_changed.emit()
        self.track_changed.emit(self._index)

    def play_index(
        self, index: int, autoplay: bool = True, resume_ms: int = 0
    ) -> None:
        if not (0 <= index < len(self._tracks)):
            return
        new_track = self._tracks[index]
        resume_ms = max(0, int(resume_ms or 0))
        old_path = ""
        if 0 <= self._index < len(self._tracks):
            old_path = self._tracks[self._index].path

        self._index = index
        if self._shuffle:
            try:
                self._shuffle_pos = self._shuffle_order.index(index)
            except ValueError:
                self._rebuild_shuffle()
                self._shuffle_pos = 0

        loaded = self._player.source().toLocalFile()
        same_file = bool(
            loaded
            and os.path.normcase(loaded) == os.path.normcase(new_track.path)
            and (
                not old_path
                or os.path.normcase(old_path) == os.path.normcase(new_track.path)
            )
        )
        if same_file and new_track.is_cue_track:
            self._ignore_end_guard = True
            self._player.setPosition(int(new_track.start_ms or 0) + resume_ms)
            self._emit_duration_for_current()
            self.track_changed.emit(self._index)
            if autoplay:
                self._player.play()
            self._ignore_end_guard = False
            return

        self._load_current(autoplay=autoplay, resume_ms=resume_ms)

    def play(self) -> None:
        if not self._tracks:
            return
        if self._index < 0:
            self.play_index(0, autoplay=True)
            return
        self._player.play()
        self._alog(f"resume: {self._snapshot()}")

    def pause(self) -> None:
        self._player.pause()
        self._alog(f"pause: {self._snapshot()}")

    def toggle_play(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._player.stop()

    def next(self) -> None:
        if not self._tracks:
            return
        if self._repeat == "one":
            track = self.current_track
            self._ignore_end_guard = True
            self._player.setPosition(int(track.start_ms or 0) if track else 0)
            self._player.play()
            self._ignore_end_guard = False
            return
        nxt = self._next_index()
        if nxt is None:
            self._player.stop()
            self.state_changed.emit("stopped")
            return
        self.play_index(nxt, autoplay=True)

    def previous(self) -> None:
        if not self._tracks:
            return
        if self.position > 3000:
            track = self.current_track
            self._ignore_end_guard = True
            self._player.setPosition(int(track.start_ms or 0) if track else 0)
            self._ignore_end_guard = False
            return
        prv = self._prev_index()
        if prv is None:
            track = self.current_track
            self._player.setPosition(int(track.start_ms or 0) if track else 0)
            return
        self.play_index(prv, autoplay=True)

    def seek(self, ms: int) -> None:
        track = self.current_track
        start = int(track.start_ms or 0) if track else 0
        abs_pos = start + max(0, int(ms))
        if track and track.end_ms is not None:
            abs_pos = min(abs_pos, int(track.end_ms))
        self._ignore_end_guard = True
        self._player.setPosition(abs_pos)
        self._ignore_end_guard = False

    def set_volume(self, vol: float) -> None:
        vol = max(0.0, min(1.0, float(vol)))
        self._audio.setVolume(vol)
        self.volume_changed.emit(vol)

    def set_shuffle(self, enabled: bool) -> None:
        self._shuffle = bool(enabled)
        self._rebuild_shuffle()

    def set_repeat(self, mode: str) -> None:
        if mode in ("off", "one", "all"):
            self._repeat = mode

    def paths(self) -> list[Any]:
        out: list[Any] = []
        for t in self._tracks:
            if t.is_cue_track:
                out.append(t.to_config())
            else:
                out.append(t.path)
        return out

    def _load_current(self, autoplay: bool = True, resume_ms: int = 0) -> None:
        track = self.current_track
        if not track:
            return
        url = QUrl.fromLocalFile(track.path)
        self._pending_start = int(track.start_ms or 0)
        self._pending_resume = max(0, int(resume_ms or 0))
        self._pending_autoplay = autoplay
        self._ignore_end_guard = True
        self._player.setSource(url)
        self.track_changed.emit(self._index)
        if self._pending_start == 0 and not track.is_cue_track and self._pending_resume == 0:
            if autoplay:
                self._player.play()
            self._pending_autoplay = False
            self._ignore_end_guard = False

    def _emit_duration_for_current(self) -> None:
        self.duration_changed.emit(self.duration)

    def _rebuild_shuffle(self) -> None:
        n = len(self._tracks)
        self._shuffle_order = list(range(n))
        random.shuffle(self._shuffle_order)
        if 0 <= self._index < n:
            if self._index in self._shuffle_order:
                self._shuffle_order.remove(self._index)
                self._shuffle_order.insert(0, self._index)
            self._shuffle_pos = 0
        else:
            self._shuffle_pos = -1

    def _next_index(self) -> Optional[int]:
        n = len(self._tracks)
        if n == 0:
            return None
        if self._shuffle:
            if self._shuffle_pos + 1 < len(self._shuffle_order):
                self._shuffle_pos += 1
                return self._shuffle_order[self._shuffle_pos]
            if self._repeat == "all":
                self._rebuild_shuffle()
                self._shuffle_pos = 0
                return self._shuffle_order[0] if self._shuffle_order else None
            return None
        nxt = self._index + 1
        if nxt < n:
            return nxt
        if self._repeat == "all":
            return 0
        return None

    def _prev_index(self) -> Optional[int]:
        n = len(self._tracks)
        if n == 0:
            return None
        if self._shuffle:
            if self._shuffle_pos > 0:
                self._shuffle_pos -= 1
                return self._shuffle_order[self._shuffle_pos]
            if self._repeat == "all" and self._shuffle_order:
                self._shuffle_pos = len(self._shuffle_order) - 1
                return self._shuffle_order[self._shuffle_pos]
            return None
        prv = self._index - 1
        if prv >= 0:
            return prv
        if self._repeat == "all":
            return n - 1
        return None


    def _setup_audio_probe(self) -> None:
        """Best-effort QAudioBufferOutput; safe no-op if backend rejects it."""
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(44100)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
            self._buffer_out = QAudioBufferOutput(fmt, self)
            self._buffer_out.audioBufferReceived.connect(self._on_audio_buffer)
            self._player.setAudioBufferOutput(self._buffer_out)
        except Exception:
            self._buffer_out = None

    @Slot(object)
    def _on_audio_buffer(self, buffer: object) -> None:
        try:
            if not isinstance(buffer, QAudioBuffer) or not buffer.isValid():
                return
            fmt = buffer.format()
            n = buffer.sampleCount()
            if n <= 0:
                return
            data = buffer.data()
            peak = 0.0
            rms = 0.0
            count = 0
            sample_fmt = fmt.sampleFormat()
            if sample_fmt == QAudioFormat.SampleFormat.Float:
                raw = bytes(data) if not isinstance(data, (bytes, bytearray, memoryview)) else data
                mv = memoryview(raw).cast("f")
                step = max(1, len(mv) // 512)
                for i in range(0, len(mv), step):
                    s = float(mv[i])
                    peak = max(peak, abs(s))
                    rms += s * s
                    count += 1
            elif sample_fmt == QAudioFormat.SampleFormat.Int16:
                raw = bytes(data) if not isinstance(data, (bytes, bytearray, memoryview)) else data
                mv = memoryview(raw).cast("h")
                step = max(1, len(mv) // 512)
                for i in range(0, len(mv), step):
                    s = float(mv[i]) / 32768.0
                    peak = max(peak, abs(s))
                    rms += s * s
                    count += 1
            else:
                return
            if count:
                rms = (rms / count) ** 0.5
            level = max(peak * 0.85, rms * 1.4)
            level = max(0.0, min(1.0, level))
            self._level_ema = self._level_ema * 0.65 + level * 0.35
            self.level_changed.emit(float(self._level_ema))
            self._emit_bands(raw, sample_fmt, fmt)
        except Exception:
            return

    def _emit_bands(self, raw: object, sample_fmt: object, fmt: object) -> None:
        """FFT -> bass / mid / high energy, adaptively normalised to 0..1."""
        try:
            import numpy as np
        except Exception:
            lv = float(getattr(self, "_level_ema", 0.0))
            self.bands_changed.emit(lv, lv * 0.7, lv * 0.5, lv)
            return
        try:
            if sample_fmt == QAudioFormat.SampleFormat.Float:
                arr = np.frombuffer(raw, dtype=np.float32)
            else:
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            ch = max(1, int(fmt.channelCount() or 2))
            sr = int(fmt.sampleRate() or 44100)
            frames = len(arr) // ch
            if frames < 256:
                return
            mono = arr[: frames * ch].reshape(frames, ch).mean(axis=1)
            n = 2048 if frames >= 2048 else (1024 if frames >= 1024 else 512)
            seg = mono[-n:] * np.hanning(n)
            spec = np.abs(np.fft.rfft(seg)) / n
            freqs = np.fft.rfftfreq(n, 1.0 / sr)
            bass = float(spec[(freqs >= 25) & (freqs < 250)].sum())
            mid = float(spec[(freqs >= 250) & (freqs < 2500)].sum())
            high = float(spec[(freqs >= 2500) & (freqs < 14000)].sum())
            peaks = getattr(self, "_band_peaks", None) or [0.02, 0.02, 0.01]
            out = []
            for i, v in enumerate((bass, mid, high)):
                peaks[i] = max(v, peaks[i] * 0.997, 1e-3)
                out.append(max(0.0, min(1.0, v / peaks[i])))
            self._band_peaks = peaks
            self.bands_changed.emit(out[0], out[1], out[2], float(self._level_ema))
        except Exception:
            return

    @Slot(int)
    def _on_position(self, pos: int) -> None:
        track = self.current_track
        if (
            not self._ignore_end_guard
            and track
            and track.end_ms is not None
            and pos >= int(track.end_ms)
        ):
            self.next()
            return
        start = int(track.start_ms or 0) if track else 0
        self.position_changed.emit(max(0, int(pos) - start))

    @Slot(int)
    def _on_duration(self, dur: int) -> None:
        track = self.current_track
        if track and track.end_ms is not None:
            self.duration_changed.emit(
                max(0, int(track.end_ms) - int(track.start_ms or 0))
            )
        elif track and track.start_ms:
            self.duration_changed.emit(max(0, int(dur) - int(track.start_ms)))
        else:
            self.duration_changed.emit(int(dur))

    @Slot(object)
    def _on_state(self, state: object) -> None:
        mapping = {
            QMediaPlayer.PlaybackState.PlayingState: "playing",
            QMediaPlayer.PlaybackState.PausedState: "paused",
            QMediaPlayer.PlaybackState.StoppedState: "stopped",
        }
        self.state_changed.emit(mapping.get(state, "stopped"))  # type: ignore[arg-type]

    @Slot(object)
    def _on_media_status(self, status: object) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            start = int(self._pending_start or 0)
            resume = int(self._pending_resume or 0)
            if start > 0 or resume > 0:
                self._player.setPosition(start + resume)
            self._pending_start = 0
            self._pending_resume = 0
            self._emit_duration_for_current()
            if self._pending_autoplay:
                self._player.play()
                self._pending_autoplay = False
            self._ignore_end_guard = False
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._repeat == "one":
                track = self.current_track
                self._player.setPosition(int(track.start_ms or 0) if track else 0)
                self._player.play()
            else:
                self.next()

    @Slot(object, str)
    def _on_error(self, _error: object, msg: str = "") -> None:
        self._alog(f"ERROR {_error} {msg}")
        self.error_occurred.emit(msg or "播放出错")
