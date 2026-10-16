# -*- coding: utf-8 -*-
"""Flash Music — control bar with deterministic, overlap-free layout.

Transport group (fixed-size buttons, fixed spacing) is always exactly centred.
Volume block sits at the right: the slider shrinks first (down to SLIDER_MIN),
then hides, leaving only the volume icon.  minimumSizeHint() guarantees the
transport group + volume icon always fit.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget


class TransportBar(QFrame):
    MARGIN = 18
    SPACING = 20
    GAP = 16           # transport <-> volume block
    VOL_GAP = 8        # volume icon <-> slider
    SLIDER_MIN = 70
    SLIDER_MAX = 150
    HEIGHT = 84

    def __init__(self, buttons: Sequence[QWidget], vol_btn: QWidget, slider: QWidget,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("playerBar")
        self.setFixedHeight(self.HEIGHT)
        self.buttons = list(buttons)
        self.vol_btn = vol_btn
        self.slider = slider
        for w in self.buttons + [vol_btn, slider]:
            w.setParent(self)
            w.show()
        for w in self.buttons + [vol_btn]:
            w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._slider_h = max(22, slider.sizeHint().height())
        self.setMinimumWidth(self.minimumSizeHint().width())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # geometry helpers --------------------------------------------------------
    def transport_width(self) -> int:
        return sum(b.width() for b in self.buttons) + self.SPACING * (len(self.buttons) - 1)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        side = self.GAP + self.vol_btn.width()
        return QSize(2 * self.MARGIN + self.transport_width() + 2 * side, self.HEIGHT)

    def sizeHint(self) -> QSize:  # noqa: N802
        side = self.GAP + self.vol_btn.width() + self.VOL_GAP + self.SLIDER_MAX
        return QSize(2 * self.MARGIN + self.transport_width() + 2 * side, self.HEIGHT)

    def transport_rect(self) -> QRect:
        b0, b1 = self.buttons[0], self.buttons[-1]
        return QRect(b0.x(), 0, b1.x() + b1.width() - b0.x(), self.height())

    def layout_items(self) -> list[QWidget]:
        return self.buttons + [self.vol_btn, self.slider]

    # layout ------------------------------------------------------------------
    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.relayout()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.relayout()

    def relayout(self) -> None:
        W, H = self.width(), self.height()
        tw = self.transport_width()
        vw = self.vol_btn.width()
        x0 = (W - tw) // 2
        # only below minimum width: slide left rather than overlap the icon
        x0 = max(self.MARGIN, min(x0, W - self.MARGIN - vw - self.GAP - tw))
        x = x0
        for b in self.buttons:
            b.move(x, (H - b.height()) // 2)
            x += b.width() + self.SPACING
        right_start = x0 + tw + self.GAP
        avail = W - self.MARGIN - right_start - vw - self.VOL_GAP
        slider_w = min(self.SLIDER_MAX, avail)
        if slider_w >= self.SLIDER_MIN:
            sx = W - self.MARGIN - slider_w
            self.slider.setGeometry(sx, (H - self._slider_h) // 2, slider_w, self._slider_h)
            self.slider.setVisible(True)
            self.vol_btn.move(sx - self.VOL_GAP - vw, (H - self.vol_btn.height()) // 2)
        else:
            self.slider.setVisible(False)
            self.vol_btn.move(W - self.MARGIN - vw, (H - self.vol_btn.height()) // 2)
