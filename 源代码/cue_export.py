# -*- coding: utf-8 -*-
"""Flash Music — lossless export.

* Lossless sources (FLAC / WAV / AIFF / APE / WavPack / ALAC) -> FLAC
  (ffmpeg -c:a flac, compression 5), original sample rate / bit depth /
  channels kept, CUE cuts sample-accurate (atrim on CUE frame boundaries).
* Lossy sources (MP3 / AAC / Ogg / Opus / WMA) are NOT up-converted: the
  original stream is copied (re-wrapped) in its own format, so nothing pretends
  to be lossless.
* Tags: TITLE / ARTIST / ALBUM / TRACKNUMBER / TOTALTRACKS (+ ALBUMARTIST /
  DATE / GENRE from the CUE header or source tags), cover embedded when a
  folder.jpg / cover.* / front.* sits next to the source.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional


ProgressCb = Callable[[int, int, str], None]  # current, total, message

LOSSLESS_EXT = {".flac", ".wav", ".aif", ".aiff", ".ape", ".wv", ".tta"}
LOSSY_EXT = {".mp3", ".aac", ".ogg", ".oga", ".opus", ".wma", ".m4a", ".mp4"}  # m4a probed
COPY_EXT = {".aac": ".m4a", ".oga": ".ogg", ".mp4": ".m4a"}
EXPORT_SUFFIX = "_FLAC"


@dataclass
class CueExportTrack:
    path: str
    title: str
    artist: str
    album: str
    start_ms: int
    end_ms: Optional[int]
    track_no: int
    albumartist: str = ""
    date: str = ""
    genre: str = ""


@dataclass
class ExportResult:
    path: Path
    mode: str  # "flac" (lossless encode) or "copy" (lossy stream copy)


def find_ffmpeg() -> Optional[str]:
    """Prefer system ffmpeg on PATH / common WinGet shim."""
    which = shutil.which("ffmpeg")
    if which:
        return which
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Links"
        / "ffmpeg.exe",
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = (name or "track").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "track"
    if len(name) > max_len:
        name = name[: max_len - 1].rstrip() + "…"
    return name


def is_cue_style_track(track) -> bool:
    return bool(getattr(track, "is_cue_track", False))


def collect_cue_export_groups(tracks: Iterable) -> list[list[CueExportTrack]]:
    """Group contiguous CUE tracks that share the same source audio file."""
    groups: dict[str, list[CueExportTrack]] = {}
    order: list[str] = []
    for t in tracks:
        if not is_cue_style_track(t):
            continue
        path = str(getattr(t, "path", "") or "")
        if not path or not Path(path).is_file():
            continue
        key = os.path.normcase(os.path.normpath(path))
        item = CueExportTrack(
            path=path,
            title=str(getattr(t, "title", "") or Path(path).stem),
            artist=str(getattr(t, "artist", "") or ""),
            album=str(getattr(t, "album", "") or ""),
            start_ms=int(getattr(t, "start_ms", 0) or 0),
            end_ms=(
                int(t.end_ms)
                if getattr(t, "end_ms", None) is not None
                else None
            ),
            track_no=0,
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    result: list[list[CueExportTrack]] = []
    for key in order:
        items = groups[key]
        items.sort(key=lambda x: x.start_ms)
        for i, it in enumerate(items, start=1):
            it.track_no = i
            if not it.album:
                it.album = Path(it.path).stem
        if len(items) >= 2 or (len(items) == 1 and items[0].end_ms is not None):
            result.append(items)
        elif len(items) == 1 and items[0].start_ms > 0:
            result.append(items)
    return result


def playlist_has_cue_export(tracks: Iterable) -> bool:
    return bool(collect_cue_export_groups(tracks))


def _ms_to_ffmpeg_time(ms: int) -> str:
    ms = max(0, int(ms))
    total_sec = ms / 1000.0
    return f"{total_sec:.3f}"


def _cue_header_meta(audio_path: str) -> dict:
    """PERFORMER / REM DATE / REM GENRE from the CUE header (before TRACK 01)."""
    meta: dict = {}
    try:
        from player_core import _decode_cue_bytes, _find_cue_for_audio

        cue = _find_cue_for_audio(Path(audio_path))
        if not cue:
            return meta
        text = _decode_cue_bytes(Path(cue).read_bytes())
    except Exception:
        return meta
    for raw in text.splitlines():
        line = raw.strip()
        up = line.upper()
        if up.startswith("TRACK "):
            break
        m = re.match(r'REM\s+(DATE|GENRE)\s+(.+)$', line, flags=re.IGNORECASE)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip().strip('"')
        elif up.startswith("PERFORMER "):
            meta["albumartist"] = line[10:].strip().strip('"')
    return meta


def _source_tags(path: str) -> dict:
    out: dict = {}
    try:
        from mutagen import File as MFile

        f = MFile(path, easy=True)
        tags = (f.tags or {}) if f is not None else {}
        for k in ("album", "albumartist", "date", "genre", "tracknumber"):
            v = tags.get(k)
            if v:
                out[k] = str(v[0])
    except Exception:
        pass
    return out


def find_cover(source_audio: str) -> Optional[Path]:
    folder = Path(source_audio).parent
    try:
        files = [p for p in folder.iterdir() if p.is_file()]
    except OSError:
        return None
    order = ("cover", "folder", "front", "albumart")
    best = None
    for p in files:
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        stem = p.stem.lower()
        for rank, name in enumerate(order):
            if stem == name or stem.startswith(name):
                if best is None or rank < best[0]:
                    best = (rank, p)
    return best[1] if best else None


def _audio_info(path: str) -> dict:
    """codec family, sample rate, bit depth, channels (mutagen, no ffprobe)."""
    info = {"lossless": None, "sr": 0, "bits": 0, "ch": 0}
    ext = Path(path).suffix.lower()
    try:
        from mutagen import File as MFile

        f = MFile(path)
        i = getattr(f, "info", None)
        if i is not None:
            info["sr"] = int(getattr(i, "sample_rate", 0) or 0)
            info["bits"] = int(getattr(i, "bits_per_sample", 0) or 0)
            info["ch"] = int(getattr(i, "channels", 0) or 0)
            codec = str(getattr(i, "codec", "") or "").lower()
            if ext in (".m4a", ".mp4"):
                info["lossless"] = codec.startswith("alac")
    except Exception:
        pass
    if info["lossless"] is None:
        info["lossless"] = ext in LOSSLESS_EXT
    return info


def is_lossy_source(path: str) -> bool:
    return not _audio_info(path)["lossless"]


def _write_tags(out: Path, tr: CueExportTrack, track_total: int, mode: str, cover: Optional[Path]) -> None:
    if mode == "flac":
        from mutagen.flac import FLAC, Picture

        f = FLAC(str(out))
        f.delete()  # fresh Vorbis comments
        f["TITLE"] = tr.title
        if tr.artist:
            f["ARTIST"] = tr.artist
        if tr.album:
            f["ALBUM"] = tr.album
        if tr.albumartist:
            f["ALBUMARTIST"] = tr.albumartist
        if tr.date:
            f["DATE"] = tr.date
        if tr.genre:
            f["GENRE"] = tr.genre
        if tr.track_no > 0:
            f["TRACKNUMBER"] = str(tr.track_no)
        if track_total > 0:
            f["TOTALTRACKS"] = str(track_total)
            f["TRACKTOTAL"] = str(track_total)
        if cover is not None:
            pic = Picture()
            pic.type = 3
            pic.mime = "image/png" if cover.suffix.lower() == ".png" else "image/jpeg"
            pic.desc = "Cover"
            pic.data = cover.read_bytes()
            f.clear_pictures()
            f.add_picture(pic)
        f.save()
        return
    # lossy stream copy: same-format tags via mutagen easy interface
    from mutagen import File as MFile

    f = MFile(str(out), easy=True)
    if f is None:
        return
    if f.tags is None:
        try:
            f.add_tags()
        except Exception:
            return
    f.tags["title"] = tr.title
    for key, val in (("artist", tr.artist), ("album", tr.album), ("albumartist", tr.albumartist),
                     ("date", tr.date), ("genre", tr.genre)):
        if val:
            try:
                f.tags[key] = val
            except Exception:
                pass
    if tr.track_no > 0:
        f.tags["tracknumber"] = f"{tr.track_no}/{track_total}" if track_total > 0 else str(tr.track_no)
    f.save()
    if cover is not None and out.suffix.lower() == ".mp3":
        try:
            from mutagen.id3 import APIC, ID3

            tags = ID3(str(out))
            tags.add(APIC(encoding=3, mime="image/png" if cover.suffix.lower() == ".png" else "image/jpeg",
                          type=3, desc="Cover", data=cover.read_bytes()))
            tags.save(str(out))
        except Exception:
            pass


def _unique_path(out_dir: Path, base: str, ext: str) -> Path:
    p = out_dir / f"{base}{ext}"
    n = 2
    while p.exists():
        p = out_dir / f"{base} ({n}){ext}"
        n += 1
    return p


def _ms_to_frames(ms: int) -> int:
    """CUE times are whole 1/75 s frames; ms were rounded, so this is exact."""
    return int(round(int(ms) * 75 / 1000.0))


def export_one_track(
    tr: CueExportTrack,
    out_dir: Path,
    ffmpeg_bin: str,
    track_total: int = 0,
    src: Optional[str] = None,
) -> ExportResult:
    """Export one track. Lossless source -> FLAC (sample-accurate cut, original
    rate/bit depth/channels). Lossy source -> stream copy in its own format."""
    out_dir.mkdir(parents=True, exist_ok=True)
    src = src or tr.path
    info = _audio_info(src)
    base = sanitize_filename(tr.title)
    if tr.track_no > 0:
        base = f"{tr.track_no:02d} - {base}"
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
           "-map", "0:a:0", "-map_metadata", "-1", "-vn"]
    if info["lossless"]:
        mode = "flac"
        out_path = _unique_path(out_dir, base, ".flac")
        sr = info["sr"]
        if (tr.start_ms > 0 or tr.end_ms is not None) and sr > 0:
            s = _ms_to_frames(tr.start_ms) * sr // 75
            trim = f"atrim=start_sample={s}"
            if tr.end_ms is not None and tr.end_ms > tr.start_ms:
                trim += f":end_sample={_ms_to_frames(tr.end_ms) * sr // 75}"
            cmd += ["-af", trim + ",asetpts=PTS-STARTPTS"]
        elif tr.start_ms > 0 or tr.end_ms is not None:  # unknown rate: ms cut
            cmd += ["-ss", _ms_to_ffmpeg_time(tr.start_ms)]
            if tr.end_ms is not None and tr.end_ms > tr.start_ms:
                cmd += ["-to", _ms_to_ffmpeg_time(tr.end_ms)]
        cmd += ["-c:a", "flac", "-compression_level", "5"]
        bits = info["bits"]
        if bits and bits <= 16:
            cmd += ["-sample_fmt", "s16"]
        elif bits:
            cmd += ["-sample_fmt", "s32", "-bits_per_raw_sample", str(min(bits, 24))]
    else:
        mode = "copy"
        ext = Path(src).suffix.lower()
        out_path = _unique_path(out_dir, base, COPY_EXT.get(ext, ext))
        if tr.start_ms > 0:
            cmd += ["-ss", _ms_to_ffmpeg_time(tr.start_ms)]
        if tr.end_ms is not None and tr.end_ms > tr.start_ms:
            cmd += ["-to", _ms_to_ffmpeg_time(tr.end_ms)]
        cmd += ["-c:a", "copy"]
    cmd.append(str(out_path))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=creationflags)
    if proc.returncode != 0 or not out_path.is_file():
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        try:
            out_path.unlink()
        except OSError:
            pass
        raise RuntimeError(f"ffmpeg 导出失败：{tr.title}\n{err}")
    _write_tags(out_path, tr, track_total, mode, find_cover(src))
    return ExportResult(out_path, mode)


def export_group(
    group: list[CueExportTrack],
    out_dir: Path,
    ffmpeg_bin: str,
    progress: Optional[ProgressCb] = None,
) -> list[ExportResult]:
    """Split one source file's CUE tracks (FLAC for lossless sources)."""
    total = len(group)
    written: list[ExportResult] = []
    src = group[0].path
    meta = _enrich_meta(src)
    for i, tr in enumerate(group):
        _apply_meta(tr, meta)
        if progress:
            progress(i, total, f"导出 {tr.track_no}/{total}: {tr.title}")
        written.append(export_one_track(tr, out_dir, ffmpeg_bin, track_total=total, src=src))
    if progress:
        progress(total, total, f"完成 · {total} 首")
    return written


def _enrich_meta(src: str) -> dict:
    meta = _source_tags(src)
    meta.update({k: v for k, v in _cue_header_meta(src).items() if v})
    return meta


def _apply_meta(tr: CueExportTrack, meta: dict) -> None:
    tr.albumartist = tr.albumartist or meta.get("albumartist", "")
    tr.date = tr.date or meta.get("date", "")
    tr.genre = tr.genre or meta.get("genre", "")
    tr.album = tr.album or meta.get("album", "")


def _source_track_number(path: str) -> tuple[int, int]:
    """(track, total) from the source file's own tags, (0, 0) if unknown."""
    try:
        from mutagen import File as MFile

        f = MFile(path, easy=True)
        raw = (f.tags or {}).get("tracknumber") if f is not None else None
        if raw:
            s = str(raw[0])
            a, _, b = s.partition("/")
            return int(a or 0), int(b or 0)
    except Exception:
        pass
    return 0, 0


def build_export_items(selected: Iterable, all_tracks: Iterable) -> list[tuple[CueExportTrack, int]]:
    """Turn selected playlist Tracks into (CueExportTrack, track_total).
    CUE tracks are numbered by their position among same-file CUE tracks of
    the playlist; normal files use their own tag numbers."""
    all_tracks = list(all_tracks)
    groups: dict[str, list] = {}
    for t in all_tracks:
        if is_cue_style_track(t):
            key = os.path.normcase(os.path.normpath(str(t.path)))
            groups.setdefault(key, []).append(t)
    for g in groups.values():
        g.sort(key=lambda x: int(getattr(x, "start_ms", 0) or 0))
    out: list[tuple[CueExportTrack, int]] = []
    for t in selected:
        path = str(getattr(t, "path", "") or "")
        title = str(getattr(t, "title", "") or Path(path).stem)
        artist = str(getattr(t, "artist", "") or "")
        album = str(getattr(t, "album", "") or "")
        if is_cue_style_track(t):
            g = groups.get(os.path.normcase(os.path.normpath(path)), [t])
            starts = [int(getattr(x, "start_ms", 0) or 0) for x in g]
            st = int(getattr(t, "start_ms", 0) or 0)
            no = starts.index(st) + 1 if st in starts else 0
            total = len(g)
            album = album or Path(path).stem
        else:
            no, total = _source_track_number(path)
            if not album:
                try:
                    from mutagen import File as MFile

                    f = MFile(path, easy=True)
                    album = str(((f.tags or {}).get("album") or [""])[0]) if f is not None else ""
                except Exception:
                    album = ""
        item = CueExportTrack(
            path=path, title=title, artist=artist, album=album,
            start_ms=int(getattr(t, "start_ms", 0) or 0),
            end_ms=(int(t.end_ms) if getattr(t, "end_ms", None) is not None else None),
            track_no=no,
        )
        _apply_meta(item, _enrich_meta(path))
        out.append((item, total))
    return out


def default_track_output_dir(source_audio: str, is_cue: bool) -> Path:
    """Next to the source: <album-file-stem>_FLAC for CUE images,
    <folder-name>_FLAC for normal files."""
    src = Path(source_audio)
    if is_cue:
        return default_output_dir(source_audio)
    return src.parent / f"{sanitize_filename(src.parent.name or 'Music')}{EXPORT_SUFFIX}"


def export_tracks(
    items: list[tuple[CueExportTrack, int]],
    out_dir: Optional[Path],
    progress: Optional[ProgressCb] = None,
) -> list[ExportResult]:
    """Export selected tracks. out_dir None => default folder next to each source."""
    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        raise FileNotFoundError(
            "未找到 ffmpeg。请安装并把 ffmpeg 加入 PATH 后重试。\n"
            "可用 winget：winget install Gyan.FFmpeg"
        )
    written: list[ExportResult] = []
    n = len(items)
    for i, (tr, total) in enumerate(items):
        if progress:
            progress(i, n, f"导出 {i + 1}/{n}: {tr.title}")
        target = Path(out_dir) if out_dir else default_track_output_dir(
            tr.path, tr.start_ms > 0 or tr.end_ms is not None)
        written.append(export_one_track(tr, target, ffmpeg_bin, track_total=total))
    if progress:
        progress(n, n, f"完成 · {n} 首")
    return written


def default_output_dir(source_audio: str) -> Path:
    src = Path(source_audio)
    album = sanitize_filename(src.stem)
    return src.parent / f"{album}{EXPORT_SUFFIX}"


def export_all_cue_groups(
    tracks: Iterable,
    out_dir: Optional[Path] = None,
    progress: Optional[ProgressCb] = None,
) -> tuple[list[ExportResult], str]:
    """Export all CUE groups. Returns (files, ffmpeg_path)."""
    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        raise FileNotFoundError(
            "未找到 ffmpeg。请安装并把 ffmpeg 加入 PATH 后重试。\n"
            "可用 winget：winget install Gyan.FFmpeg"
        )
    groups = collect_cue_export_groups(tracks)
    if not groups:
        raise ValueError("当前播放列表没有可导出的 CUE 分轨")

    all_files: list[ExportResult] = []
    # progress across all tracks
    flat_total = sum(len(g) for g in groups)
    done = 0

    def _cb(cur: int, total: int, msg: str) -> None:
        if progress:
            progress(done + cur, flat_total, msg)

    for g in groups:
        target = out_dir
        if target is None:
            target = default_output_dir(g[0].path)
        else:
            # if user picked one folder and multiple source files, subfolder per album
            if len(groups) > 1:
                target = Path(out_dir) / sanitize_filename(Path(g[0].path).stem)
        files = export_group(g, Path(target), ffmpeg_bin, progress=_cb)
        all_files.extend(files)
        done += len(g)
    return all_files, ffmpeg_bin
