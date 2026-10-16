# -*- coding: utf-8 -*-
"""Flash Music — GPU stable-fluids visualizer (audio reactive).

Pipeline (per frame, OpenGL 3.3 core, RGBA16F ping-pong targets), modelled on
the classic "WebGL Fluid Simulation" approach:
    splats -> curl -> vorticity confinement -> divergence -> pressure (Jacobi)
    -> gradient subtract -> advect velocity -> advect dye -> bloom -> display

Audio drives splats: bass onsets -> big strong colour bursts, mids -> medium
swirls, highs -> small fast curls; when paused a slow idle drift keeps going.
If OpenGL 3.3 is unavailable the widget falls back to a low-res numpy fluid.
"""

from __future__ import annotations

import math
import os
import random
import time
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import QStackedLayout, QWidget

try:  # GPU path
    from PySide6.QtGui import QSurfaceFormat, QVector2D, QVector3D
    from PySide6.QtOpenGL import (
        QOpenGLFramebufferObject,
        QOpenGLFramebufferObjectFormat,
        QOpenGLShader,
        QOpenGLShaderProgram,
        QOpenGLVertexArrayObject,
    )
    from PySide6.QtOpenGLWidgets import QOpenGLWidget

    _GL_IMPORT_OK = True
except Exception:  # pragma: no cover
    _GL_IMPORT_OK = False

try:  # CPU fallback
    import numpy as np

    _NP_OK = True
except Exception:  # pragma: no cover
    _NP_OK = False


# ---------------------------------------------------------------------------
# palette + audio driver (shared by GPU and CPU renderers)
# ---------------------------------------------------------------------------

_PALETTE = [
    (0.00, 1.00, 0.92),  # neon cyan
    (0.12, 1.00, 0.38),  # neon green
    (0.55, 0.22, 1.00),  # electric purple
    (1.00, 0.16, 0.78),  # magenta
    (0.10, 0.62, 1.00),  # ice blue
    (0.75, 0.25, 1.00),  # violet
]

# simulation constants (Pavel-style units)
SIM_RES = 128
DYE_RES = 768
PRESSURE_ITER = 20
PRESSURE_KEEP = 0.8
VEL_DISSIPATION = 0.2
DYE_DISSIPATION = 0.62
BLOOM_ITER = 7
BLOOM_RES = 256
BLOOM_THRESHOLD = 0.7
BLOOM_KNEE = 0.7
BLOOM_INTENSITY = 1.0
BG = (0.010, 0.014, 0.032)
COLOR_GAIN = 1.0


class _Splat:
    __slots__ = ("x", "y", "dx", "dy", "color", "radius")

    def __init__(self, x, y, dx, dy, color, radius):
        self.x, self.y, self.dx, self.dy = x, y, dx, dy
        self.color, self.radius = color, radius


class AudioDriver:
    """Turns playback state + band energies into fluid splats."""

    def __init__(self) -> None:
        self.rng = random.Random(11)
        self.playing = False
        self.t = 0.0
        self.bass = self.mid = self.high = self.level = 0.0
        self._tb = self._tm = self._th = self._tl = 0.0
        self.bass_avg = 0.2
        self._last_real = 0.0
        self._cool = 0.0
        self._acc_mid = self._acc_high = self._acc_idle = 0.0
        self._stream_i = 0
        self._phase = [self.rng.uniform(0, 6.28) for _ in range(6)]
        self.curl = 30.0
        self._boot = True

    # inputs ---------------------------------------------------------------
    def set_playing(self, playing: bool) -> None:
        self.playing = bool(playing)

    def set_bands(self, bass: float, mid: float, high: float, level: float) -> None:
        self._tb, self._tm, self._th, self._tl = bass, mid, high, level
        self._last_real = time.monotonic()

    def set_level(self, level: float) -> None:
        if time.monotonic() - self._last_real > 0.5:  # no FFT data -> derive
            self._tl = level
            self._tb, self._tm, self._th = level, level * 0.8, level * 0.6

    # helpers --------------------------------------------------------------
    _ANCHORS = [(0.18, 0.38), (0.42, 0.64), (0.66, 0.36), (0.85, 0.62), (0.30, 0.72), (0.74, 0.25)]

    def _emitter(self, i: int) -> tuple[float, float, float, float]:
        # each emitter orbits its own anchor, spreading plumes over the card
        ax, ay = self._ANCHORS[i % len(self._ANCHORS)]
        p = self._phase[i % len(self._phase)]
        t = self.t
        w1, w2 = 0.23 + 0.04 * i, 0.17 + 0.035 * i
        x = ax + 0.12 * math.sin(t * w1 + p)
        y = ay + 0.14 * math.sin(t * w2 + p * 1.7)
        vx = 0.12 * w1 * math.cos(t * w1 + p)
        vy = 0.14 * w2 * math.cos(t * w2 + p * 1.7)
        return x, y, vx, vy

    def _color(self, i: int, gain: float) -> tuple[float, float, float]:
        # each emitter owns a hue (distinct plumes), slowly rotating
        shift = int(self.t / 20.0)
        base = _PALETTE[(i + shift) % len(_PALETTE)]
        mix = _PALETTE[(i + 1 + shift) % len(_PALETTE)]
        k = self.rng.random() * 0.25
        gain *= COLOR_GAIN
        return tuple((base[c] * (1 - k) + mix[c] * k) * gain for c in range(3))

    def _fake(self) -> None:
        t = self.t
        beat = max(0.0, math.sin(t * math.tau * 1.9)) ** 10
        self._tb = 0.25 + 0.75 * beat
        self._tm = 0.35 + 0.3 * math.sin(t * 2.3) ** 2
        self._th = 0.25 + 0.35 * abs(math.sin(t * 5.1 + 1.0))
        self._tl = 0.4 + 0.3 * beat

    # main -----------------------------------------------------------------
    def step(self, dt: float) -> list[_Splat]:
        self.t += dt
        rng = self.rng
        out: list[_Splat] = []
        if self._boot:  # seed a few blooms so the first frame is not empty
            self._boot = False
            for i in range(5):
                x, y, _, _ = self._emitter(i)
                a = rng.uniform(0, math.tau)
                out.append(_Splat(x, y, math.cos(a) * 900, math.sin(a) * 900,
                                  self._color(i, 2.6), 0.22))
        if self.playing and time.monotonic() - self._last_real > 1.0:
            self._fake()
        if not self.playing:
            self._tb = self._tm = self._th = self._tl = 0.0

        def follow(cur, tgt, up=18.0, down=5.0):
            k = up if tgt > cur else down
            return cur + (tgt - cur) * min(1.0, k * dt)

        self.bass = follow(self.bass, self._tb, 30.0, 6.0)
        self.mid = follow(self.mid, self._tm)
        self.high = follow(self.high, self._th, 25.0, 8.0)
        self.level = follow(self.level, self._tl)
        self._cool = max(0.0, self._cool - dt)

        if self.playing:
            self.curl = 42.0 + 30.0 * self.bass
            self._since_burst = getattr(self, "_since_burst", 0.0) + dt
            onset = self._tb - self.bass_avg
            self.bass_avg += (self._tb - self.bass_avg) * min(1.0, 1.6 * dt)
            hit = onset > 0.12 and self._tb > 0.3 and self._cool <= 0
            # quiet music: still a plume every ~1.4 s, scaled by loudness
            lull = self._since_burst > 0.75
            if hit or lull:
                strength = max(self._tb, 0.45) if hit else 0.45 + 0.45 * self.level
                self._cool = 0.22
                self._since_burst = 0.0
                n = 1 if strength < 0.75 else 2
                for _ in range(n):
                    i = rng.randrange(6)
                    x, y, vx, vy = self._emitter(i)
                    a = math.atan2(vy, vx) + rng.uniform(-1.0, 1.0)
                    f = 3200 + 5200 * strength
                    # bright core: dense dye -> near-white after tonemap
                    out.append(_Splat(
                        x + rng.uniform(-0.04, 0.04), y + rng.uniform(-0.04, 0.04),
                        math.cos(a) * f, math.sin(a) * f,
                        self._color(i, 2.2 + 3.0 * strength), 0.2 + 0.24 * strength,
                    ))
            # mids -> occasional medium swirls (mostly motion, little dye)
            self._acc_mid += dt * (0.4 + 2.6 * self.mid)
            while self._acc_mid >= 1.0 and len(out) < 6:
                self._acc_mid -= 1.0
                i = rng.randrange(6)
                x, y, vx, vy = self._emitter(i)
                a = rng.uniform(0, math.tau)
                f = 1800 + 3000 * self.mid
                out.append(_Splat(
                    x + rng.uniform(-0.15, 0.15), y + rng.uniform(-0.15, 0.15),
                    math.cos(a) * f, math.sin(a) * f,
                    self._color(i, 0.35 + 0.5 * self.mid), 0.07 + 0.05 * self.mid,
                ))
            # highs -> tiny fast curls (velocity only, a hint of dye)
            self._acc_high += dt * (6.0 * self.high)
            while self._acc_high >= 1.0 and len(out) < 8:
                self._acc_high -= 1.0
                i = rng.randrange(6)
                x, y, _, _ = self._emitter(i)
                a = rng.uniform(0, math.tau)
                f = 2600 + 3400 * self.high
                out.append(_Splat(
                    x + rng.uniform(-0.25, 0.25), y + rng.uniform(-0.25, 0.25),
                    math.cos(a) * f, math.sin(a) * f,
                    self._color(i, 0.12), 0.02 + 0.02 * self.high,
                ))
        else:
            # idle: one soft plume every ~2 s, slow drift
            self.curl = 30.0
            self._acc_idle += dt * 0.5
            while self._acc_idle >= 1.0:
                self._acc_idle -= 1.0
                i = rng.randrange(6)
                x, y, vx, vy = self._emitter(i)
                a = math.atan2(vy, vx) + rng.uniform(-0.6, 0.6)
                out.append(_Splat(x, y, math.cos(a) * 900, math.sin(a) * 900,
                                  self._color(i, 2.4), 0.3))
        return out


# ---------------------------------------------------------------------------
# GPU renderer
# ---------------------------------------------------------------------------

GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_LINEAR = 0x2601
GL_CLAMP_TO_EDGE = 0x812F
GL_TEXTURE0 = 0x84C0
GL_TRIANGLE_STRIP = 0x0005
GL_BLEND = 0x0BE2
GL_ONE = 1
GL_FRAMEBUFFER = 0x8D40
GL_COLOR_BUFFER_BIT = 0x4000
GL_RGBA16F = 0x881A

_VERT = """#version 330 core
out vec2 vUv; out vec2 vL; out vec2 vR; out vec2 vT; out vec2 vB;
uniform vec2 texelSize;
void main() {
    vec2 pos = vec2((gl_VertexID & 1) == 0 ? -1.0 : 1.0,
                    (gl_VertexID & 2) == 0 ? -1.0 : 1.0);
    vUv = pos * 0.5 + 0.5;
    vL = vUv - vec2(texelSize.x, 0.0);
    vR = vUv + vec2(texelSize.x, 0.0);
    vT = vUv + vec2(0.0, texelSize.y);
    vB = vUv - vec2(0.0, texelSize.y);
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_HDR = """#version 330 core
in vec2 vUv; in vec2 vL; in vec2 vR; in vec2 vT; in vec2 vB;
out vec4 fragColor;
uniform vec2 texelSize;
"""

_FRAG = {
    "copy": """uniform sampler2D uTexture;
void main(){ fragColor = texture(uTexture, vUv); }""",
    "clear": """uniform sampler2D uTexture; uniform float value;
void main(){ fragColor = value * texture(uTexture, vUv); }""",
    "splat": """uniform sampler2D uTarget; uniform float aspectRatio;
uniform vec3 color; uniform vec2 point; uniform float radius;
void main(){
    vec2 p = vUv - point; p.x *= aspectRatio;
    vec3 s = exp(-dot(p, p) / radius) * color;
    fragColor = vec4(texture(uTarget, vUv).xyz + s, 1.0);
}""",
    "advect": """uniform sampler2D uVelocity; uniform sampler2D uSource;
uniform float dt; uniform float dissipation;
void main(){
    vec2 coord = vUv - dt * texture(uVelocity, vUv).xy * texelSize;
    fragColor = texture(uSource, coord) / (1.0 + dissipation * dt);
}""",
    "divergence": """uniform sampler2D uVelocity;
void main(){
    float L = texture(uVelocity, vL).x; float R = texture(uVelocity, vR).x;
    float T = texture(uVelocity, vT).y; float B = texture(uVelocity, vB).y;
    vec2 C = texture(uVelocity, vUv).xy;
    if (vL.x < 0.0) L = -C.x; if (vR.x > 1.0) R = -C.x;
    if (vT.y > 1.0) T = -C.y; if (vB.y < 0.0) B = -C.y;
    fragColor = vec4(0.5 * (R - L + T - B), 0.0, 0.0, 1.0);
}""",
    "curl": """uniform sampler2D uVelocity;
void main(){
    float L = texture(uVelocity, vL).y; float R = texture(uVelocity, vR).y;
    float T = texture(uVelocity, vT).x; float B = texture(uVelocity, vB).x;
    fragColor = vec4(0.5 * (R - L - T + B), 0.0, 0.0, 1.0);
}""",
    "vorticity": """uniform sampler2D uVelocity; uniform sampler2D uCurl;
uniform float curl; uniform float dt;
void main(){
    float L = texture(uCurl, vL).x; float R = texture(uCurl, vR).x;
    float T = texture(uCurl, vT).x; float B = texture(uCurl, vB).x;
    float C = texture(uCurl, vUv).x;
    vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
    force /= length(force) + 0.0001;
    force *= curl * C; force.y *= -1.0;
    vec2 vel = texture(uVelocity, vUv).xy + force * dt;
    fragColor = vec4(clamp(vel, -1000.0, 1000.0), 0.0, 1.0);
}""",
    "pressure": """uniform sampler2D uPressure; uniform sampler2D uDivergence;
void main(){
    float L = texture(uPressure, vL).x; float R = texture(uPressure, vR).x;
    float T = texture(uPressure, vT).x; float B = texture(uPressure, vB).x;
    float d = texture(uDivergence, vUv).x;
    fragColor = vec4((L + R + B + T - d) * 0.25, 0.0, 0.0, 1.0);
}""",
    "gradient": """uniform sampler2D uPressure; uniform sampler2D uVelocity;
void main(){
    float L = texture(uPressure, vL).x; float R = texture(uPressure, vR).x;
    float T = texture(uPressure, vT).x; float B = texture(uPressure, vB).x;
    vec2 vel = texture(uVelocity, vUv).xy - vec2(R - L, T - B);
    fragColor = vec4(vel, 0.0, 1.0);
}""",
    "prefilter": """uniform sampler2D uTexture; uniform vec3 curve; uniform float threshold;
void main(){
    vec3 c = texture(uTexture, vUv).rgb;
    float br = max(c.r, max(c.g, c.b));
    float rq = clamp(br - curve.x, 0.0, curve.y);
    rq = curve.z * rq * rq;
    c *= max(rq, br - threshold) / max(br, 0.0001);
    fragColor = vec4(c, 0.0);
}""",
    "blur": """uniform sampler2D uTexture;
void main(){
    vec4 s = texture(uTexture, vL) + texture(uTexture, vR)
           + texture(uTexture, vT) + texture(uTexture, vB);
    fragColor = s * 0.25;
}""",
    "display": """uniform sampler2D uTexture; uniform sampler2D uBloom;
uniform float bloomIntensity; uniform vec3 bg;
void main(){
    vec3 c = texture(uTexture, vUv).rgb;
    // ink shading: pseudo-normal from dye gradient gives the 3D smoke look
    vec3 lc = texture(uTexture, vL).rgb; vec3 rc = texture(uTexture, vR).rgb;
    vec3 tc = texture(uTexture, vT).rgb; vec3 bc = texture(uTexture, vB).rgb;
    float dx = length(rc) - length(lc); float dy = length(tc) - length(bc);
    vec3 n = normalize(vec3(dx, dy, length(texelSize)));
    float diffuse = clamp(dot(n, vec3(0.0, 0.0, 1.0)) + 0.7, 0.7, 1.0);
    c *= diffuse;
    vec3 bloom = texture(uBloom, vUv).rgb * bloomIntensity;
    bloom = pow(max(bloom, 0.0), vec3(1.0 / 1.6));
    // black point: faint residual dye sinks back to the dark background
    c = max(c - vec3(0.02), vec3(0.0));
    float lum = dot(c, vec3(0.299, 0.587, 0.114));
    c = max(mix(vec3(lum), c, 1.25), 0.0);
    // dense cores shift toward white (hot centre), then filmic tonemap
    c += vec3(max(lum - 1.0, 0.0) * 0.4);
    c = vec3(1.0) - exp(-c * 1.05);
    c += bloom;
    float a = clamp(max(c.r, max(c.g, c.b)), 0.0, 1.0);
    vec2 q = vUv - 0.5;
    float vig = 1.0 - 0.55 * dot(q, q);
    fragColor = vec4((bg * (1.0 - a) + c) * vig, 1.0);
}""",
}


if _GL_IMPORT_OK:

    class _Target:
        def __init__(self, f, w: int, h: int) -> None:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
            fmt.setTextureTarget(GL_TEXTURE_2D)
            fmt.setInternalTextureFormat(GL_RGBA16F)
            self.fbo = QOpenGLFramebufferObject(w, h, fmt)
            if not self.fbo.isValid():
                raise RuntimeError("RGBA16F framebuffer not supported")
            self.w, self.h = w, h
            self.tex = self.fbo.texture()
            self.texel = QVector2D(1.0 / w, 1.0 / h)
            f.glBindTexture(GL_TEXTURE_2D, self.tex)
            f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            f.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

    class _Double:
        def __init__(self, f, w: int, h: int) -> None:
            self.read = _Target(f, w, h)
            self.write = _Target(f, w, h)
            self.w, self.h, self.texel = w, h, self.read.texel

        def swap(self) -> None:
            self.read, self.write = self.write, self.read

    class _GLFluid(QOpenGLWidget):
        failed = Signal(str)

        def __init__(self, driver: AudioDriver, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            fmt.setSwapInterval(1)
            self.setFormat(fmt)
            self._driver = driver
            self._ok = False
            self._dirty = True
            self._last = time.perf_counter()
            self._progs: dict = {}
            self._timer = QTimer(self)
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._timer.timeout.connect(self.update)
            self._timer.start(16)
            self.fps = 0.0
            self._fps_n = 0
            self._fps_t = time.perf_counter()

        # -- GL setup --
        def initializeGL(self) -> None:  # noqa: N802
            try:
                ctx = self.context()
                if ctx is None or not ctx.isValid():
                    raise RuntimeError("no valid OpenGL context")
                ver = ctx.format().version()
                if tuple(ver) < (3, 3):
                    raise RuntimeError(f"OpenGL {ver} < 3.3")
                self.f = ctx.functions()
                self._vao = QOpenGLVertexArrayObject(self)
                if not self._vao.create():
                    raise RuntimeError("VAO create failed")
                for name, src in _FRAG.items():
                    p = QOpenGLShaderProgram(self)
                    if not p.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VERT):
                        raise RuntimeError(p.log())
                    if not p.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _HDR + src):
                        raise RuntimeError(f"{name}: {p.log()}")
                    if not p.link():
                        raise RuntimeError(f"{name}: {p.log()}")
                    self._progs[name] = p
                self._ok = True
            except Exception as exc:  # -> CPU fallback
                self._ok = False
                self._timer.stop()
                QTimer.singleShot(0, lambda e=str(exc): self.failed.emit(e))

        def resizeGL(self, w: int, h: int) -> None:  # noqa: N802
            self._dirty = True

        @staticmethod
        def _res(res: int, w: int, h: int) -> tuple[int, int]:
            aspect = max(w, 1) / max(h, 1)
            if aspect < 1:
                aspect = 1.0 / aspect
            lo, hi = res, int(round(res * aspect))
            return (hi, lo) if w > h else (lo, hi)

        def _init_targets(self) -> None:
            dpr = self.devicePixelRatioF()
            pw, ph = max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))
            f = self.f
            sw, sh = self._res(SIM_RES, pw, ph)
            dyer = min(DYE_RES, max(256, max(pw, ph)))
            dw, dh = self._res(dyer, pw, ph)
            self.vel = _Double(f, sw, sh)
            self.pressure = _Double(f, sw, sh)
            self.div = _Target(f, sw, sh)
            self.curlt = _Target(f, sw, sh)
            self.dye = _Double(f, dw, dh)
            bw, bh = self._res(BLOOM_RES, pw, ph)
            self.bloom = _Target(f, bw, bh)
            self.bloom_levels = []
            for i in range(BLOOM_ITER):
                w, h = bw >> (i + 1), bh >> (i + 1)
                if w < 2 or h < 2:
                    break
                self.bloom_levels.append(_Target(f, w, h))
            self._dirty = False

        # -- helpers --
        def _use(self, name: str, texel) -> "QOpenGLShaderProgram":
            p = self._progs[name]
            p.bind()
            p.setUniformValue("texelSize", texel)
            return p

        def _tex(self, p, uniform: str, unit: int, target) -> None:
            self.f.glActiveTexture(GL_TEXTURE0 + unit)
            self.f.glBindTexture(GL_TEXTURE_2D, target.tex)
            p.setUniformValue1i(uniform, unit)

        def _draw(self, target) -> None:
            f = self.f
            if target is None:
                dpr = self.devicePixelRatioF()
                f.glBindFramebuffer(GL_FRAMEBUFFER, self.defaultFramebufferObject())
                f.glViewport(0, 0, int(self.width() * dpr), int(self.height() * dpr))
            else:
                target.fbo.bind()
                f.glViewport(0, 0, target.w, target.h)
            f.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

        # -- simulation --
        def _splat(self, s: _Splat) -> None:
            aspect = max(1, self.width()) / max(1, self.height())
            r = s.radius / 100.0
            if aspect > 1:
                r *= aspect
            p = self._use("splat", self.vel.texel)
            self._tex(p, "uTarget", 0, self.vel.read)
            p.setUniformValue1f("aspectRatio", aspect)
            p.setUniformValue("point", QVector2D(s.x, s.y))
            p.setUniformValue("color", QVector3D(s.dx, s.dy, 0.0))
            p.setUniformValue1f("radius", r)
            self._draw(self.vel.write)
            self.vel.swap()
            p = self._use("splat", self.dye.texel)
            self._tex(p, "uTarget", 0, self.dye.read)
            p.setUniformValue("color", QVector3D(*s.color))
            self._draw(self.dye.write)
            self.dye.swap()

        def _step(self, dt: float) -> None:
            v, pr = self.vel, self.pressure
            p = self._use("curl", v.texel)
            self._tex(p, "uVelocity", 0, v.read)
            self._draw(self.curlt)

            p = self._use("vorticity", v.texel)
            self._tex(p, "uVelocity", 0, v.read)
            self._tex(p, "uCurl", 1, self.curlt)
            p.setUniformValue1f("curl", float(self._driver.curl))
            p.setUniformValue1f("dt", dt)
            self._draw(v.write)
            v.swap()

            p = self._use("divergence", v.texel)
            self._tex(p, "uVelocity", 0, v.read)
            self._draw(self.div)

            p = self._use("clear", v.texel)
            self._tex(p, "uTexture", 0, pr.read)
            p.setUniformValue1f("value", PRESSURE_KEEP)
            self._draw(pr.write)
            pr.swap()

            p = self._use("pressure", v.texel)
            self._tex(p, "uDivergence", 0, self.div)
            for _ in range(PRESSURE_ITER):
                self._tex(p, "uPressure", 1, pr.read)
                self._draw(pr.write)
                pr.swap()

            p = self._use("gradient", v.texel)
            self._tex(p, "uPressure", 0, pr.read)
            self._tex(p, "uVelocity", 1, v.read)
            self._draw(v.write)
            v.swap()

            p = self._use("advect", v.texel)
            self._tex(p, "uVelocity", 0, v.read)
            self._tex(p, "uSource", 1, v.read)
            p.setUniformValue1f("dt", dt)
            p.setUniformValue1f("dissipation", VEL_DISSIPATION)
            self._draw(v.write)
            v.swap()

            self._tex(p, "uVelocity", 0, v.read)
            self._tex(p, "uSource", 1, self.dye.read)
            p.setUniformValue1f("dissipation", DYE_DISSIPATION)
            self._draw(self.dye.write)
            self.dye.swap()

        def _bloom(self) -> None:
            f = self.f
            p = self._use("prefilter", self.bloom.texel)
            knee = BLOOM_THRESHOLD * BLOOM_KNEE + 0.0001
            p.setUniformValue("curve", QVector3D(BLOOM_THRESHOLD - knee, knee * 2.0, 0.25 / knee))
            p.setUniformValue1f("threshold", BLOOM_THRESHOLD)
            self._tex(p, "uTexture", 0, self.dye.read)
            self._draw(self.bloom)
            last = self.bloom
            p = self._progs["blur"]
            for dest in self.bloom_levels:
                p = self._use("blur", last.texel)
                self._tex(p, "uTexture", 0, last)
                self._draw(dest)
                last = dest
            f.glEnable(GL_BLEND)
            f.glBlendFunc(GL_ONE, GL_ONE)
            for dest in reversed(self.bloom_levels[:-1]):
                p = self._use("blur", last.texel)
                self._tex(p, "uTexture", 0, last)
                self._draw(dest)
                last = dest
            p = self._use("blur", last.texel)
            self._tex(p, "uTexture", 0, last)
            self._draw(self.bloom)
            f.glDisable(GL_BLEND)

        def paintGL(self) -> None:  # noqa: N802
            f = self.f if self._ok else self.context().functions()
            if not self._ok:
                f.glClearColor(*BG, 1.0)
                f.glClear(GL_COLOR_BUFFER_BIT)
                return
            try:
                if self._dirty:
                    self._init_targets()
                now = time.perf_counter()
                dt = min(max(now - self._last, 0.001), 1.0 / 30.0)
                self._last = now
                self._vao.bind()
                f.glDisable(GL_BLEND)
                for s in self._driver.step(dt):
                    self._splat(s)
                self._step(dt)
                self._bloom()
                p = self._use("display", self.dye.texel)
                self._tex(p, "uTexture", 0, self.dye.read)
                self._tex(p, "uBloom", 1, self.bloom)
                p.setUniformValue1f("bloomIntensity", BLOOM_INTENSITY)
                p.setUniformValue("bg", QVector3D(*BG))
                self._draw(None)
                self._vao.release()
                self._fps_n += 1
                if now - self._fps_t >= 1.0:
                    self.fps = self._fps_n / (now - self._fps_t)
                    self._fps_n, self._fps_t = 0, now
            except Exception as exc:
                self._ok = False
                self._timer.stop()
                QTimer.singleShot(0, lambda e=str(exc): self.failed.emit(e))


# ---------------------------------------------------------------------------
# CPU fallback (numpy, low-res stable fluids)
# ---------------------------------------------------------------------------


class CpuSim:
    """Pure-numpy low-res stable fluids (no Qt), used by the CPU fallback."""

    GRID = 72  # short side

    def __init__(self, driver: AudioDriver, w: int, h: int) -> None:
        self.driver = driver
        if w >= h:
            gh, gw = self.GRID, max(8, int(self.GRID * w / max(h, 1)))
        else:
            gw, gh = self.GRID, max(8, int(self.GRID * h / max(w, 1)))
        self.shape = (gh, gw)
        z = lambda: np.zeros((gh, gw), np.float32)  # noqa: E731
        self.u, self.v, self.p = z(), z(), z()
        self.dye = np.zeros((gh, gw, 3), np.float32)
        self.X, self.Y = np.meshgrid(np.arange(gw, dtype=np.float32),
                                     np.arange(gh, dtype=np.float32))

    def _advect(self, field, dt):
        # periodic (wrap-around) semi-Lagrangian advection, consistent with
        # the np.roll stencils below, so no dye leaks out of the domain
        gh, gw = self.shape
        x = np.mod(self.X - dt * self.u, gw)
        y = np.mod(self.Y - dt * self.v, gh)
        x0 = np.floor(x).astype(np.int32) % gw
        y0 = np.floor(y).astype(np.int32) % gh
        x1 = (x0 + 1) % gw
        y1 = (y0 + 1) % gh
        sx = x - np.floor(x)
        sy = y - np.floor(y)
        if field.ndim == 3:
            sx = sx[..., None]
            sy = sy[..., None]
        a = field[y0, x0]
        b = field[y0, x1]
        c = field[y1, x0]
        d = field[y1, x1]
        return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy

    def step(self, dt: float) -> "np.ndarray":
        gh, gw = self.shape
        scale = gh / SIM_RES  # GPU splat forces are in 128-cell units
        aspect = gw / gh
        for s in self.driver.step(dt):
            r = s.radius / 100.0 * (aspect if aspect > 1 else 1)
            px = (self.X / gw - s.x) * aspect
            py = (gh - 1 - self.Y) / gh - s.y
            g = np.exp(-(px * px + py * py) / r).astype(np.float32)
            self.u += g * (s.dx * scale)
            self.v -= g * (s.dy * scale)  # image rows grow downward
            self.dye += g[..., None] * np.asarray(s.color, np.float32)
        u, v = self.u, self.v
        # vorticity confinement (same form as the GPU shader)
        curl = 0.5 * ((np.roll(v, -1, 1) - np.roll(v, 1, 1)) - (np.roll(u, -1, 0) - np.roll(u, 1, 0)))
        ac = np.abs(curl)
        fy = 0.5 * (np.roll(ac, -1, 0) - np.roll(ac, 1, 0))
        fx = 0.5 * (np.roll(ac, -1, 1) - np.roll(ac, 1, 1))
        ln = np.sqrt(fx * fx + fy * fy) + 1e-4
        k = self.driver.curl * dt * curl
        self.u += (fy / ln) * k
        self.v -= (fx / ln) * k
        # projection
        div = 0.5 * ((np.roll(self.u, -1, 1) - np.roll(self.u, 1, 1))
                     + (np.roll(self.v, -1, 0) - np.roll(self.v, 1, 0)))
        p = self.p * PRESSURE_KEEP
        for _ in range(16):
            p = (np.roll(p, 1, 0) + np.roll(p, -1, 0) + np.roll(p, 1, 1) + np.roll(p, -1, 1) - div) * 0.25
        self.p = p
        self.u -= 0.5 * (np.roll(p, -1, 1) - np.roll(p, 1, 1))
        self.v -= 0.5 * (np.roll(p, -1, 0) - np.roll(p, 1, 0))
        self.u -= self.u.mean()  # no global drift in a periodic box
        self.v -= self.v.mean()
        # advection + dissipation
        nu = self._advect(self.u, dt)
        nv = self._advect(self.v, dt)
        kv = 1.0 / (1.0 + VEL_DISSIPATION * dt)
        lim = 600.0 * scale
        self.u = np.nan_to_num(np.clip(nu * kv, -lim, lim)).astype(np.float32)
        self.v = np.nan_to_num(np.clip(nv * kv, -lim, lim)).astype(np.float32)
        self.dye = np.nan_to_num(self._advect(self.dye, dt) / (1.0 + 1.6 * DYE_DISSIPATION * dt)).astype(np.float32)
        np.clip(self.dye, 0.0, 4.0, out=self.dye)
        c = self.dye
        lum = (c * np.array([0.299, 0.587, 0.114], np.float32)).sum(axis=2, keepdims=True)
        c = np.maximum(lum + (c - lum) * 1.25, 0.0)
        c = c + np.maximum(lum - 1.0, 0.0) * 0.4
        c = 1.0 - np.exp(-c * 1.05)
        a = np.clip(c.max(axis=2, keepdims=True), 0, 1)
        rgb = np.array(BG, np.float32) * (1 - a) + c
        return np.ascontiguousarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))


class _CpuFluid(QWidget):
    def __init__(self, driver: AudioDriver, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._driver = driver
        self._sim: Optional[CpuSim] = None
        self._img: Optional[QImage] = None
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self.fps = 0.0
        self._fps_n = 0
        self._fps_t = time.perf_counter()

    def _tick(self) -> None:
        if not _NP_OK:
            self.update()
            return
        if self._sim is None:
            self._sim = CpuSim(self._driver, self.width(), self.height())
        now = time.perf_counter()
        dt = min(max(now - self._last, 0.001), 1 / 20)
        self._last = now
        img8 = self._sim.step(dt)
        gh, gw = self._sim.shape
        self._img = QImage(img8.data, gw, gh, gw * 3, QImage.Format.Format_RGB888).copy()
        self._fps_n += 1
        if now - self._fps_t >= 1.0:
            self.fps = self._fps_n / (now - self._fps_t)
            self._fps_n, self._fps_t = 0, now
        self.update()

    def resizeEvent(self, e) -> None:  # noqa: N802
        if _NP_OK and self.width() > 0 and self.height() > 0:
            self._sim = CpuSim(self._driver, self.width(), self.height())
        super().resizeEvent(e)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor.fromRgbF(*BG))
        if self._img is not None:
            r = QRectF(self.rect())
            p.drawImage(r, self._img)
            small = self._img.scaled(max(2, self._img.width() // 6), max(2, self._img.height() // 6),
                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.setOpacity(0.45)
            p.drawImage(r, small)
        elif not _NP_OK:
            g = QRadialGradient(self.width() / 2, self.height() / 2, max(self.width(), self.height()) / 2)
            g.setColorAt(0, QColor(40, 220, 230, 90))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), g)
        p.end()


# ---------------------------------------------------------------------------
# public widget
# ---------------------------------------------------------------------------


class FluidVisual(QWidget):
    """Container picking GPU fluid, falling back to CPU fluid on failure."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("fluidVisual")
        self.setMinimumHeight(160)
        self._driver = AudioDriver()
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._gl = None
        self._cpu = None
        self.backend = "none"
        self.fallback_reason = ""
        force_cpu = os.environ.get("FLASHMUSIC_FLUID", "").lower() == "cpu"
        if _GL_IMPORT_OK and not force_cpu:
            try:
                self._gl = _GLFluid(self._driver, self)
                self._gl.failed.connect(self._fallback)
                self._stack.addWidget(self._gl)
                self.backend = "gpu"
            except Exception as exc:
                self._fallback(str(exc))
        else:
            self._fallback("forced" if force_cpu else "QtOpenGL unavailable")

    def _fallback(self, reason: str = "") -> None:
        self.fallback_reason = reason
        if self._gl is not None:
            self._stack.removeWidget(self._gl)
            self._gl.hide()
            self._gl.deleteLater()
            self._gl = None
        if self._cpu is None:
            self._cpu = _CpuFluid(self._driver, self)
            self._stack.addWidget(self._cpu)
        self._stack.setCurrentWidget(self._cpu)
        self.backend = "cpu"

    # API used by MainWindow
    def set_playing(self, playing: bool) -> None:
        self._driver.set_playing(playing)

    def set_level(self, level: float) -> None:
        self._driver.set_level(float(level))

    def set_bands(self, bass: float, mid: float, high: float, level: float) -> None:
        self._driver.set_bands(float(bass), float(mid), float(high), float(level))

    @property
    def fps(self) -> float:
        w = self._gl or self._cpu
        return float(getattr(w, "fps", 0.0))

    def grab_image(self) -> QImage:
        if self._gl is not None:
            return self._gl.grabFramebuffer()
        return self.grab().toImage()
