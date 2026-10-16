# -*- coding: utf-8 -*-
"""Flash Music — light self-check (no GUI window required for most checks)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def test_natural_sort() -> None:
    from player_core import natural_key

    names = ["track 10.mp3", "track 2.mp3", "track 1.mp3"]
    sorted_names = sorted(names, key=natural_key)
    assert sorted_names == ["track 1.mp3", "track 2.mp3", "track 10.mp3"], sorted_names
    print("OK  natural_key")


def test_auto_optimize_dedupe() -> None:
    from player_core import Track, auto_optimize, collect_audio_files

    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "a.mp3"
        p2 = Path(td) / "b.wav"
        p1.write_bytes(b"ID3")
        p2.write_bytes(b"RIFF")
        tracks = collect_audio_files([str(p1), str(p1), str(p2)])
        tracks = auto_optimize(tracks + tracks)
        assert len(tracks) == 2, len(tracks)
        assert all(isinstance(x, Track) for x in tracks)
        print("OK  auto_optimize dedupe")


def test_config_roundtrip() -> None:
    # NEVER touch the real %LOCALAPPDATA%\\FlashMusic\\config.json here:
    # an earlier version of this test saved an empty playlist into it,
    # wiping the user's last playlist every time selftest ran.
    td = tempfile.mkdtemp(prefix="fm_selftest_cfg_")
    old_env = os.environ.get("FLASHMUSIC_CONFIG_DIR")
    os.environ["FLASHMUSIC_CONFIG_DIR"] = td
    try:
        _config_roundtrip_body()
    finally:
        if old_env is None:
            os.environ.pop("FLASHMUSIC_CONFIG_DIR", None)
        else:
            os.environ["FLASHMUSIC_CONFIG_DIR"] = old_env


def _config_roundtrip_body() -> None:
    from config import config_dir, default_config, load_config, save_config

    d = config_dir()
    assert "fm_selftest_cfg_" in str(d), d
    assert d.is_dir()
    cfg = default_config()
    cfg["volume"] = 0.42
    cfg["playlist"] = []
    save_config(cfg)
    loaded = load_config()
    assert abs(float(loaded["volume"]) - 0.42) < 1e-6
    print(f"OK  config @ {d}")


def test_imports() -> None:
    import theme
    import config
    import player_core
    import app

    assert callable(theme.app_stylesheet)
    assert hasattr(player_core, "PlayerCore")
    assert hasattr(app, "MainWindow")
    print("OK  imports")


def test_cue_time_and_parse_helpers() -> None:
    from player_core import cue_time_to_ms, parse_cue_file, collect_audio_files

    assert cue_time_to_ms("00:00:33") == 440  # 33 frames @ 75fps
    assert cue_time_to_ms("03:03:30") == 3 * 60 * 1000 + 3 * 1000 + 400
    print("OK  cue_time_to_ms")


def test_pyside_multimedia() -> None:
    from PySide6.QtWidgets import QApplication
    from mf_backend import MFAudioOutput, MFPlayer

    app = QApplication.instance() or QApplication(sys.argv)
    player = MFPlayer()
    audio = MFAudioOutput(player)
    audio.setVolume(0.5)
    assert abs(audio.volume() - 0.5) < 0.01
    print("OK  Media Foundation player (WinRT MediaPlayer)")
    del player, audio
    _ = app


def test_export_single_normal_file() -> None:
    """Lossless source -> FLAC (rate/bits/channels kept, Vorbis tags);
    lossy source -> stream copy in its own format. Temp dir only."""
    import shutil
    import subprocess

    from cue_export import CueExportTrack, export_one_track, find_ffmpeg

    ff = find_ffmpeg()
    if not ff:
        print("SKIP export (no ffmpeg)")
        return
    td = Path(tempfile.mkdtemp(prefix="fm_selftest_export_"))
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        wav = td / "tone.wav"
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=3:sample_rate=48000", "-ac", "2",
                        "-c:a", "pcm_s24le", str(wav)], check=True, creationflags=cf)
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", "color=c=0x8b5cf6:s=64x64", "-frames:v", "1", str(td / "cover.jpg")],
                       check=True, creationflags=cf)
        tr = CueExportTrack(path=str(wav), title="Tone Test", artist="Flash", album="Selftest",
                            start_ms=1000, end_ms=2000, track_no=7)
        res = export_one_track(tr, td / "out", ff, track_total=9)
        from mutagen.flac import FLAC

        assert res.mode == "flac" and res.path.suffix == ".flac", res
        f = FLAC(str(res.path))
        assert f.info.sample_rate == 48000 and f.info.bits_per_sample == 24 and f.info.channels == 2, (
            f.info.sample_rate, f.info.bits_per_sample, f.info.channels)
        assert f.info.total_samples == 48000, f.info.total_samples  # sample-accurate 1.000 s cut
        assert f["TITLE"] == ["Tone Test"] and f["ARTIST"] == ["Flash"] and f["ALBUM"] == ["Selftest"]
        assert f["TRACKNUMBER"] == ["7"] and f["TOTALTRACKS"] == ["9"], dict(f)
        assert len(f.pictures) == 1 and f.pictures[0].type == 3, f.pictures  # cover.jpg embedded

        mp3 = td / "lossy.mp3"
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                        "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True, creationflags=cf)
        tr2 = CueExportTrack(path=str(mp3), title="Lossy", artist="Flash", album="Selftest",
                             start_ms=0, end_ms=None, track_no=1)
        res2 = export_one_track(tr2, td / "out", ff, track_total=1)
        assert res2.mode == "copy" and res2.path.suffix == ".mp3", res2
        from mutagen.mp3 import MP3

        assert abs(MP3(str(res2.path)).info.bitrate - 192000) < 8000  # not re-encoded
        print("OK  export: lossless -> FLAC 24/48k exact cut + tags + cover; lossy -> stream copy")
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_control_bar_layout() -> None:
    """Spawn layout_check.py (own QApplication, isolated config) and require
    no overlapping/out-of-bounds controls at min, 1000/1200/1600 and maximized."""
    import subprocess

    here = Path(__file__).resolve().parent
    r = subprocess.run([sys.executable, str(here / "layout_check.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr)[-1500:])
    print("OK  control bar layout (no overlap at all sizes)")


def main() -> int:
    os.chdir(Path(__file__).resolve().parent)
    if str(Path.cwd()) not in sys.path:
        sys.path.insert(0, str(Path.cwd()))

    tests = [
        test_imports,
        test_natural_sort,
        test_auto_optimize_dedupe,
        test_config_roundtrip,
        test_cue_time_and_parse_helpers,
        test_pyside_multimedia,
        test_export_single_normal_file,
        test_control_bar_layout,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    if failed:
        print(f"\n{failed} test(s) failed")
        return 1
    print("\nAll selftests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
