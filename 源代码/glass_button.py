# -*- coding: utf-8 -*-
"""Flash Music — Apple-style liquid-glass transport buttons.

* Vector icons drawn with QPainterPath (SF Symbols-like), crisp at any DPI.
* Secondary buttons: no box at rest; on hover a frosted glass blob grows from
  the cursor with a springy overshoot and a gently wobbling (gooey) edge, a
  specular highlight follows the mouse, the icon springs up ~1.08.
* Press: squish to ~0.92 + ripple.  Leave: blob melts back.
* Primary (play/pause): gradient glass orb with top sheen + soft outer glow.
A per-button timer runs only while something is animating (GPU/CPU light).
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

ICON = QColor(241, 245, 249, 235)
ICON_HOVER = QColor(255, 255, 255)
ACCENT = QColor(103, 232, 249)  # cyan-300
ACCENT2 = QColor(167, 139, 250)  # violet-400

_EMOJI = {"▶": "play", "⏸": "pause", "⏮": "backward", "⏭": "forward",
          "🔀": "shuffle", "🔁": "repeat", "🔂": "repeat1",
          "🔇": "vol_mute", "🔈": "vol1", "🔉": "vol2", "🔊": "vol3"}


# --------------------------------------------------------------------------
# icons (24x24 design grid)
# --------------------------------------------------------------------------

def _tri(path: QPainterPath, pts) -> None:
    path.moveTo(*pts[0])
    for p in pts[1:]:
        path.lineTo(*p)
    path.closeSubpath()


def icon_paths(name: str) -> tuple[QPainterPath, QPainterPath]:
    """Return (fill_path, stroke_path) in 24x24 units."""
    fill, stroke = QPainterPath(), QPainterPath()
    if name == "play":
        _tri(fill, [(8.0, 4.8), (19.6, 12.0), (8.0, 19.2)])
    elif name == "pause":
        fill.addRoundedRect(QRectF(6.0, 4.8, 4.2, 14.4), 1.3, 1.3)
        fill.addRoundedRect(QRectF(13.8, 4.8, 4.2, 14.4), 1.3, 1.3)
    elif name == "backward":
        _tri(fill, [(11.6, 6.6), (3.6, 12.0), (11.6, 17.4)])
        _tri(fill, [(20.4, 6.6), (12.4, 12.0), (20.4, 17.4)])
    elif name == "forward":
        _tri(fill, [(12.4, 6.6), (20.4, 12.0), (12.4, 17.4)])
        _tri(fill, [(3.6, 6.6), (11.6, 12.0), (3.6, 17.4)])
    elif name == "shuffle":
        stroke.moveTo(3.5, 7.5); stroke.lineTo(6.8, 7.5)
        stroke.cubicTo(11.0, 7.5, 12.5, 16.5, 16.8, 16.5); stroke.lineTo(20.0, 16.5)
        stroke.moveTo(3.5, 16.5); stroke.lineTo(6.8, 16.5)
        stroke.cubicTo(11.0, 16.5, 12.5, 7.5, 16.8, 7.5); stroke.lineTo(20.0, 7.5)
        for y in (7.5, 16.5):
            stroke.moveTo(17.4, y - 2.8); stroke.lineTo(20.2, y); stroke.lineTo(17.4, y + 2.8)
    elif name in ("repeat", "repeat1"):
        stroke.moveTo(4.5, 12.5); stroke.lineTo(4.5, 10.0)
        stroke.quadTo(4.5, 7.0, 7.5, 7.0); stroke.lineTo(19.0, 7.0)
        stroke.moveTo(16.4, 4.4); stroke.lineTo(19.2, 7.0); stroke.lineTo(16.4, 9.6)
        stroke.moveTo(19.5, 11.5); stroke.lineTo(19.5, 14.0)
        stroke.quadTo(19.5, 17.0, 16.5, 17.0); stroke.lineTo(5.0, 17.0)
        stroke.moveTo(7.6, 14.4); stroke.lineTo(4.8, 17.0); stroke.lineTo(7.6, 19.6)
        if name == "repeat1":
            stroke.moveTo(10.9, 10.9); stroke.lineTo(12.2, 9.9); stroke.lineTo(12.2, 14.3)
    elif name.startswith("vol"):
        fill.moveTo(3.5, 9.4); fill.lineTo(7.0, 9.4); fill.lineTo(11.4, 5.6)
        fill.lineTo(11.4, 18.4); fill.lineTo(7.0, 14.6); fill.lineTo(3.5, 14.6)
        fill.closeSubpath()
        if name == "vol_mute":
            stroke.moveTo(15.0, 9.5); stroke.lineTo(20.0, 14.5)
            stroke.moveTo(20.0, 9.5); stroke.lineTo(15.0, 14.5)
        else:
            level = {"vol1": 1, "vol2": 2, "vol3": 3}.get(name, 3)
            for i in range(level):
                r = 3.4 + i * 3.0
                rect = QRectF(11.4 - r, 12.0 - r, 2 * r, 2 * r)
                stroke.arcMoveTo(rect, 42)
                stroke.arcTo(rect, 42, -84)
    return fill, stroke


def draw_icon(p: QPainter, name: str, center: QPointF, size: float, color: QColor) -> None:
    fill, stroke = icon_paths(name)
    p.save()
    p.translate(center)
    s = size / 24.0
    p.scale(s, s)
    p.translate(-12.0, -12.0)
    if not fill.isEmpty():
        pen = QPen(color, 2.2)  # same-colour stroke => rounded corners
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(color)
        p.drawPath(fill)
    if not stroke.isEmpty():
        pen = QPen(color, 1.9)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(stroke)
    p.restore()


# --------------------------------------------------------------------------
# spring helper
# --------------------------------------------------------------------------

class _Spring:
    __slots__ = ("x", "v", "target", "k", "c")

    def __init__(self, x: float = 0.0, k: float = 240.0, c: float = 15.0) -> None:
        self.x = x
        self.v = 0.0
        self.target = x
        self.k, self.c = k, c

    def step(self, dt: float) -> None:
        a = self.k * (self.target - self.x) - self.c * self.v
        self.v += a * dt
        self.x += self.v * dt

    @property
    def settled(self) -> bool:
        return abs(self.target - self.x) < 0.002 and abs(self.v) < 0.01


# --------------------------------------------------------------------------
# button
# --------------------------------------------------------------------------

class GlassButton(QAbstractButton):
    """Icon-only liquid glass button. primary=True gives the play orb."""

    def __init__(self, icon: str, primary: bool = False, diameter: int = 46,
                 icon_size: float = 22.0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self.primary = primary
        self.diameter = diameter
        self.icon_size = icon_size
        pad = 6 if primary else 3  # play 64x64, secondary 44x44, volume 36x36
        self.setFixedSize(diameter + 2 * pad, diameter + 2 * pad)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._blob = _Spring(0.0, k=230.0, c=13.0)    # hover glass size 0..1
        self._iconk = _Spring(1.0, k=320.0, c=16.0)   # icon scale
        self._press = _Spring(1.0, k=420.0, c=20.0)   # squish
        self._origin = QPointF(self.width() / 2, self.height() / 2)
        self._mouse = QPointF(self._origin)
        self._hl = QPointF(self._origin)              # smoothed highlight
        self._ripple = -1.0                            # 0..1 progress, <0 off
        self._ripple_at = QPointF(self._origin)
        self._t = 0.0
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.toggled.connect(lambda _c: self.update())

    # ---- API ----
    def set_icon(self, name: str) -> None:
        if name != self._icon:
            self._icon = name
            self.update()

    def icon_name(self) -> str:
        return self._icon

    def setText(self, text: str) -> None:  # noqa: N802 — emoji compat
        super().setText(text)
        if text in _EMOJI:
            self.set_icon(_EMOJI[text])

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.size()

    # ---- animation ----
    def _kick(self) -> None:
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(max(now - self._last, 0.001), 1 / 30)
        self._last = now
        self.advance(dt)
        busy = not (self._blob.settled and self._iconk.settled and self._press.settled) \
            or self._ripple >= 0 or self.underMouse()
        self.update()
        if not busy:
            self._timer.stop()

    def advance(self, dt: float) -> None:
        self._t += dt
        for s in (self._blob, self._iconk, self._press):
            s.step(dt)
        k = min(1.0, dt * 14.0)
        self._hl = QPointF(self._hl.x() + (self._mouse.x() - self._hl.x()) * k,
                           self._hl.y() + (self._mouse.y() - self._hl.y()) * k)
        if self._ripple >= 0:
            self._ripple += dt / 0.45
            if self._ripple >= 1.0:
                self._ripple = -1.0

    def reset_hover(self) -> None:
        """Drop any hover/press state immediately (used by tests)."""
        for s, v in ((self._blob, 0.0), (self._iconk, 1.0), (self._press, 1.0)):
            s.x = s.target = v
            s.v = 0.0
        self._ripple = -1.0
        self.update()

    # ---- events ----
    def enterEvent(self, e) -> None:  # noqa: N802
        pos = e.position() if hasattr(e, "position") else QPointF(self.width() / 2, self.height() / 2)
        self._origin = QPointF(pos)
        self._mouse = QPointF(pos)
        self._hl = QPointF(pos)
        if self._blob.x < 0.05:
            self._blob.x = 0.0
        self._blob.target = 1.0
        self._iconk.target = 1.08
        self._kick()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._blob.target = 0.0
        self._iconk.target = 1.0
        self._press.target = 1.0
        self._mouse = QPointF(self.width() / 2, self.height() / 2)
        self._kick()
        super().leaveEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        self._mouse = QPointF(e.position())
        self._kick()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press.target = 0.92
            self._ripple = 0.0
            self._ripple_at = QPointF(e.position())
            self._kick()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._press.target = 1.0
        self._press.v += 2.5  # springy rebound
        self._kick()
        super().mouseReleaseEvent(e)

    # ---- painting ----
    def _blob_path(self, c: QPointF, r: float, wobble: float) -> QPainterPath:
        path = QPainterPath()
        n = 56
        t = self._t
        for i in range(n + 1):
            th = i / n * math.tau
            k = 1.0 + wobble * (0.055 * math.sin(3 * th + t * 5.0)
                                + 0.035 * math.sin(5 * th - t * 3.7)
                                + 0.02 * math.sin(2 * th + t * 2.3))
            x = c.x() + math.cos(th) * r * k
            y = c.y() + math.sin(th) * r * k
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        return path

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        squish = self._press.x
        if self.primary:
            self._paint_primary(p, center, squish)
        else:
            self._paint_secondary(p, center, squish)
        p.end()

    def _paint_secondary(self, p: QPainter, center: QPointF, squish: float) -> None:
        b = max(0.0, self._blob.x)
        R = self.diameter / 2.0
        if b > 0.01:
            # blob centre travels from the entry point to the button centre
            m = min(1.0, b)
            c = QPointF(self._origin.x() + (center.x() - self._origin.x()) * m,
                        self._origin.y() + (center.y() - self._origin.y()) * m)
            # gooey edge strongest while the spring is moving
            wobble = min(1.0, 0.12 + abs(self._blob.v) * 0.3)
            r = R * (0.6 + 0.4 * b) * b ** 0.5 * squish
            path = self._blob_path(c, r, wobble)
            alpha = min(1.0, b)
            g = QRadialGradient(c.x(), c.y() - r * 0.35, r * 1.3)
            g.setColorAt(0.0, QColor(255, 255, 255, int(62 * alpha)))
            g.setColorAt(0.6, QColor(186, 230, 253, int(30 * alpha)))
            g.setColorAt(1.0, QColor(148, 163, 255, int(14 * alpha)))
            p.setPen(QPen(QColor(255, 255, 255, int(80 * alpha)), 1.0))
            p.setBrush(g)
            p.drawPath(path)
            # specular highlight follows the mouse, clipped to the blob
            p.save()
            p.setClipPath(path)
            hl = QRadialGradient(self._hl, r * 0.9)
            hl.setColorAt(0.0, QColor(255, 255, 255, int(70 * alpha)))
            hl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(hl)
            p.drawEllipse(self._hl, r * 0.9, r * 0.9)
            # top sheen
            sheen = QLinearGradient(0, c.y() - r, 0, c.y())
            sheen.setColorAt(0.0, QColor(255, 255, 255, int(40 * alpha)))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(sheen)
            p.drawEllipse(QPointF(c.x(), c.y() - r * 0.45), r * 0.75, r * 0.5)
            p.restore()
        self._paint_ripple(p, R * squish)
        on = self.isCheckable() and self.isChecked()
        col = QColor(ACCENT) if on else (ICON_HOVER if b > 0.3 else ICON)
        size = self.icon_size * self._iconk.x * squish
        draw_icon(p, self._icon, center, size, col)
        if on:  # Apple-style state dot
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ACCENT)
            p.drawEllipse(QPointF(center.x(), center.y() + R - 3.0), 2.2, 2.2)

    def _paint_primary(self, p: QPainter, center: QPointF, squish: float) -> None:
        b = max(0.0, self._blob.x)
        R = self.diameter / 2.0 * squish * (1.0 + 0.06 * b)
        # soft outer glow
        gr = min(self.width(), self.height()) / 2.0 - 0.5  # stay inside widget
        glow = QRadialGradient(center.x(), center.y() + 1, gr)
        glow.setColorAt(0.0, QColor(129, 140, 248, int(90 + 50 * b)))
        glow.setColorAt(R / gr * 0.92, QColor(129, 140, 248, int(70 + 50 * b)))
        glow.setColorAt(1.0, QColor(129, 140, 248, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(center, gr, gr)
        # gradient glass orb (wobbles slightly while springing)
        orb = self._blob_path(center, R, min(0.22, abs(self._blob.v) * 0.05 + abs(self._press.v) * 0.03))
        g = QLinearGradient(center.x() - R, center.y() - R, center.x() + R, center.y() + R)
        g.setColorAt(0.0, QColor(34, 211, 238))
        g.setColorAt(0.5, QColor(99, 102, 241))
        g.setColorAt(1.0, QColor(168, 85, 247))
        p.setBrush(g)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.0))
        p.drawPath(orb)
        p.save()
        p.setClipPath(orb)
        # specular top sheen
        sheen = QLinearGradient(0, center.y() - R, 0, center.y() + R * 0.1)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 120))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(sheen)
        p.drawEllipse(QPointF(center.x(), center.y() - R * 0.42), R * 0.78, R * 0.55)
        # inner shade at bottom
        shade = QLinearGradient(0, center.y() + R * 0.2, 0, center.y() + R)
        shade.setColorAt(0.0, QColor(30, 10, 60, 0))
        shade.setColorAt(1.0, QColor(30, 10, 60, 70))
        p.setBrush(shade)
        p.drawRect(QRectF(center.x() - R, center.y(), 2 * R, R))
        # mouse-following highlight on hover
        if b > 0.02:
            hl = QRadialGradient(self._hl, R * 0.8)
            hl.setColorAt(0.0, QColor(255, 255, 255, int(70 * min(1.0, b))))
            hl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(hl)
            p.drawEllipse(self._hl, R * 0.8, R * 0.8)
        p.restore()
        self._paint_ripple(p, R)
        size = self.icon_size * self._iconk.x * squish
        off = 1.2 if self._icon == "play" else 0.0  # optical centring
        draw_icon(p, self._icon, QPointF(center.x() + off, center.y()), size, QColor(255, 255, 255))

    def _paint_ripple(self, p: QPainter, R: float) -> None:
        if self._ripple < 0:
            return
        k = self._ripple
        p.setPen(QPen(QColor(255, 255, 255, int(110 * (1 - k))), 1.6))
        p.setBrush(QColor(255, 255, 255, int(28 * (1 - k))))
        p.drawEllipse(self._ripple_at, R * (0.3 + 0.9 * k), R * (0.3 + 0.9 * k))
