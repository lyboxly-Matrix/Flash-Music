# -*- coding: utf-8 -*-
"""Windows Media Foundation playback (WinRT Windows.Media.Playback.MediaPlayer, the engine
behind the Windows Media Player app) behind a QMediaPlayer/QAudioOutput-shaped API used by
player_core (Flash Music's only playback backend).

Why: the MF MediaPlayer, with no explicit AudioDevice, follows the system default render
device and rebuilds its audio stream itself when the endpoint/stream is invalidated (e.g. a
Bluetooth speaker after a browser used it).

Visualizer: MF exposes no PCM tap, so the current file is decoded once in parallel with
QAudioDecoder (decode only, no audio device) into 11025 Hz mono int16. While playing, slices
at the current position are delivered as QAudioBuffer through the attached
QAudioBufferOutput, exactly like the FFmpeg backend does.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal, Qt
from PySide6.QtMultimedia import (
    QAudioBuffer, QAudioDecoder, QAudioFormat, QMediaDevices, QMediaPlayer,
)

from winrt.windows.foundation import Uri
from winrt.windows.media.core import MediaSource
from winrt.windows.media.playback import MediaPlayer, MediaPlaybackState

PS = QMediaPlayer.PlaybackState
MS = QMediaPlayer.MediaStatus

VIS_RATE = 11025
VIS_WINDOW = 2048


class MFAudioOutput(QObject):
    """QAudioOutput look-alike. The device always follows the system default."""

    def __init__(self, player: "MFPlayer", parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._p = player

    def volume(self) -> float:
        return float(self._p._mp.volume)

    def setVolume(self, v: float) -> None:
        self._p._mp.volume = max(0.0, min(1.0, float(v)))

    def isMuted(self) -> bool:
        return bool(self._p._mp.is_muted)

    def setMuted(self, m: bool) -> None:
        self._p._mp.is_muted = bool(m)

    def device(self):
        return QMediaDevices.defaultAudioOutput()

    def setDevice(self, _dev) -> None:  # MF follows the default endpoint on its own
        return


class MFPlayer(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)

    _sigOpened = Signal(int, int)        # generation, duration ms
    _sigEnded = Signal(int)
    _sigFailed = Signal(int, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._mp = MediaPlayer()
        self._mp.auto_play = False
        self._gen = 0
        self._source = QUrl()
        self._state = PS.StoppedState
        self._status = MS.NoMedia
        self._duration = 0
        self._last_pos = -1
        self._pending_pos: Optional[int] = None
        self._want_play = False
        self._buf_out = None
        self._pcm = bytearray()
        self._pcm_gen = -1
        self._decoder: Optional[QAudioDecoder] = None
        self._pcm_done = False

        self._sigOpened.connect(self._on_opened, Qt.ConnectionType.QueuedConnection)
        self._sigEnded.connect(self._on_ended, Qt.ConnectionType.QueuedConnection)
        self._sigFailed.connect(self._on_failed, Qt.ConnectionType.QueuedConnection)
        self._mp.add_media_opened(lambda s, a: self._sigOpened.emit(self._gen, self._natural_ms()))
        self._mp.add_media_ended(lambda s, a: self._sigEnded.emit(self._gen))
        self._mp.add_media_failed(lambda s, a: self._sigFailed.emit(self._gen, f"{a.error}: {a.error_message}"))

        self._tick = QTimer(self)
        self._tick.setInterval(40)
        self._tick.timeout.connect(self._on_tick)

    # ---- QMediaPlayer API used by player_core
    def setAudioOutput(self, _out) -> None:
        return

    def setAudioBufferOutput(self, out) -> None:
        self._buf_out = out

    def source(self) -> QUrl:
        return QUrl(self._source)

    def setSource(self, url: QUrl) -> None:
        self._gen += 1
        self._source = QUrl(url)
        self._duration = 0
        self._last_pos = -1
        self._pending_pos = None
        self._want_play = False
        self._set_state(PS.StoppedState)
        self._tick.stop()
        self._stop_decoder()
        self._pcm = bytearray()
        self._pcm_done = False
        if url.isEmpty():
            self._mp.source = None
            self._set_status(MS.NoMedia)
            return
        self._set_status(MS.LoadingMedia)
        self._mp.source = MediaSource.create_from_uri(Uri(url.toString(QUrl.ComponentFormattingOption.FullyEncoded)))
        self._start_decoder(url.toLocalFile())

    def play(self) -> None:
        if self._source.isEmpty():
            return
        if self._status in (MS.LoadingMedia, MS.NoMedia):
            self._want_play = True
            self._set_state(PS.PlayingState)
            return
        if self._status == MS.EndOfMedia:
            self._seek_now(0)
        self._mp.play()
        self._set_state(PS.PlayingState)
        self._set_status(MS.BufferedMedia)
        self._tick.start()

    def pause(self) -> None:
        self._want_play = False
        self._mp.pause()
        self._set_state(PS.PausedState)
        self._tick.stop()

    def stop(self) -> None:
        self._want_play = False
        self._mp.pause()
        if self._status not in (MS.NoMedia, MS.LoadingMedia):
            self._seek_now(0)
            self._set_status(MS.LoadedMedia)
        self._set_state(PS.StoppedState)
        self._tick.stop()
        self._emit_pos(0)

    def setPosition(self, ms: int) -> None:
        ms = max(0, int(ms))
        if self._status in (MS.LoadingMedia, MS.NoMedia):
            self._pending_pos = ms
            return
        self._seek_now(ms)
        self._emit_pos(ms)

    def position(self) -> int:
        if self._status in (MS.LoadingMedia, MS.NoMedia):
            return int(self._pending_pos or 0)
        try:
            return int(self._mp.playback_session.position.total_seconds() * 1000)
        except Exception:
            return max(0, self._last_pos)

    def duration(self) -> int:
        return int(self._duration)

    def playbackState(self):
        return self._state

    def mediaStatus(self):
        return self._status

    # ---- internals
    def _natural_ms(self) -> int:
        try:
            return int(self._mp.playback_session.natural_duration.total_seconds() * 1000)
        except Exception:
            return 0

    def _seek_now(self, ms: int) -> None:
        try:
            self._mp.playback_session.position = timedelta(milliseconds=int(ms))
        except Exception:
            pass

    def _set_state(self, st) -> None:
        if st != self._state:
            self._state = st
            self.playbackStateChanged.emit(st)

    def _set_status(self, st) -> None:
        if st != self._status:
            self._status = st
            self.mediaStatusChanged.emit(st)

    def _emit_pos(self, ms: int) -> None:
        if ms != self._last_pos:
            self._last_pos = ms
            self.positionChanged.emit(int(ms))

    def _on_opened(self, gen: int, dur: int) -> None:
        if gen != self._gen:
            return
        self._duration = dur
        self.durationChanged.emit(int(dur))
        if self._pending_pos is not None:
            self._seek_now(self._pending_pos)
            self._emit_pos(self._pending_pos)
            self._pending_pos = None
        want = self._want_play
        self._set_status(MS.LoadedMedia)
        if want and self._gen == gen and self._state == PS.PlayingState:
            self._want_play = False
            self.play()

    def _on_ended(self, gen: int) -> None:
        if gen != self._gen or self._status == MS.EndOfMedia:
            return
        self._tick.stop()
        self._emit_pos(self._duration)
        self._set_state(PS.StoppedState)
        self._set_status(MS.EndOfMedia)

    def _on_failed(self, gen: int, msg: str) -> None:
        if gen != self._gen:
            return
        self._tick.stop()
        self._set_status(MS.InvalidMedia)
        self._set_state(PS.StoppedState)
        self.errorOccurred.emit(QMediaPlayer.Error.ResourceError, msg)

    def _on_tick(self) -> None:
        pos = self.position()
        self._emit_pos(pos)
        self._feed_visual(pos)
        # MF's FLAC source never signals end-of-stream after a seek during playback and its
        # clock keeps running on silence; end the track ourselves once past the real length.
        real = len(self._pcm) * 1000 // (2 * VIS_RATE) if self._pcm_done else 0
        limit = max(real, self._duration) + (400 if real else 1500)
        if self._duration > 0 and pos > limit:
            self._mp.pause()
            self._on_ended(self._gen)

    # ---- visualizer PCM (parallel decode, no audio device)
    def _start_decoder(self, path: str) -> None:
        if self._buf_out is None or not path:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(VIS_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        dec = QAudioDecoder(self)
        dec.setAudioFormat(fmt)
        gen = self._gen
        dec.bufferReady.connect(lambda: self._on_pcm(dec, gen))
        dec.finished.connect(lambda: self._pcm_finished(gen))
        dec.setSource(QUrl.fromLocalFile(path))
        self._decoder = dec
        self._pcm_gen = gen
        dec.start()

    def _on_pcm(self, dec: QAudioDecoder, gen: int) -> None:
        buf = dec.read()
        if gen != self._gen or not buf.isValid():
            return
        start = int(buf.startTime() * VIS_RATE // 1_000_000) * 2
        data = bytes(buf.constData()) if hasattr(buf, "constData") else bytes(buf.data())
        if len(self._pcm) < start:
            self._pcm.extend(b"\0" * (start - len(self._pcm)))
        self._pcm[start:start + len(data)] = data

    def _pcm_finished(self, gen: int) -> None:
        if gen == self._gen:
            self._pcm_done = True

    def _stop_decoder(self) -> None:
        dec, self._decoder = self._decoder, None
        if dec is not None:
            try:
                dec.stop()
            except Exception:
                pass
            dec.deleteLater()

    def _feed_visual(self, pos_ms: int) -> None:
        out = self._buf_out
        if out is None:
            return
        end = int(pos_ms * VIS_RATE // 1000) * 2
        begin = end - VIS_WINDOW * 2
        if begin < 0 or end > len(self._pcm):
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(VIS_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        buf = QAudioBuffer(QByteArray(bytes(self._pcm[begin:end])), fmt, pos_ms * 1000)
        out.audioBufferReceived.emit(buf)
