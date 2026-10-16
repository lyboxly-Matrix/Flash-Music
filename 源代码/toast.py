# -*- coding: utf-8 -*-
"""Flash Music — non-blocking glass toast (progress + action button)."""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def vector_icon(name: str, size: int = 18, color: QColor = QColor(226, 232, 240), dpr: float = 2.0) -> QIcon:
    """Small SF-Symbols-like menu icons drawn with QPainterPath."""
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size / 24.0
    p.scale(s, s)
    pen = QPen(color, 1.9)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    if name == "export":  # arrow down into tray
        path.moveTo(12, 3.5); path.lineTo(12, 14.5)
        path.moveTo(7.5, 10.2); path.lineTo(12, 14.7); path.lineTo(16.5, 10.2)
        path.moveTo(4.5, 14.5); path.lineTo(4.5, 18); path.quadTo(4.5, 20.5, 7, 20.5)
        path.lineTo(17, 20.5); path.quadTo(19.5, 20.5, 19.5, 18); path.lineTo(19.5, 14.5)
        p.drawPath(path)
    elif name == "play":
        path.moveTo(8, 5); path.lineTo(19, 12); path.lineTo(8, 19); path.closeSubpath()
        p.setBrush(color)
        p.drawPath(path)
    elif name == "remove":
        path.moveTo(6, 6); path.lineTo(18, 18); path.moveTo(18, 6); path.lineTo(6, 18)
        p.drawPath(path)
    elif name == "folder":
        path.moveTo(3.5, 7.5); path.quadTo(3.5, 5.5, 5.5, 5.5); path.lineTo(9.5, 5.5)
        path.lineTo(11.5, 7.5); path.lineTo(18.5, 7.5); path.quadTo(20.5, 7.5, 20.5, 9.5)
        path.lineTo(20.5, 17); path.quadTo(20.5, 19, 18.5, 19); path.lineTo(5.5, 19)
        path.quadTo(3.5, 19, 3.5, 17); path.closeSubpath()
        p.drawPath(path)
    p.end()
    return QIcon(pm)


def open_folder(path: str) -> None:
    if not path:
        return
    if sys.platform == "win32":
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return
        except OSError:
            pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class Toast(QFrame):
    """Bottom-right floating glass card. Never modal, never steals focus."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.title = QLabel("")
        self.title.setObjectName("toastTitle")
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("toastClose")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.dismiss)
        row.addWidget(self.icon)
        row.addWidget(self.title, 1)
        row.addWidget(self.close_btn)
        lay.addLayout(row)
        self.msg = QLabel("")
        self.msg.setObjectName("toastMsg")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        self.bar = QProgressBar()
        self.bar.setObjectName("toastBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        lay.addWidget(self.bar)
        self.action = QPushButton("打开文件夹")
        self.action.setObjectName("toastAction")
        self.action.setIcon(vector_icon("folder", 16, QColor(255, 255, 255)))
        self.action.setIconSize(QSize(16, 16))
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.clicked.connect(lambda: open_folder(self._folder))
        lay.addWidget(self.action, 0, Qt.AlignmentFlag.AlignRight)
        self._folder = ""
        # NB: opaque + no QGraphicsEffect — translucent children composited over
        # the QOpenGLWidget fluid render with broken alpha on Windows.
        self.setAutoFillBackground(False)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)
        self.hide()

    def _place(self) -> None:
        par = self.parentWidget()
        if par is None:
            return
        self.adjustSize()
        self.move(QPoint(par.width() - self.width() - 28, par.height() - self.height() - 150))
        self.raise_()

    def _fade_in(self) -> None:
        if not self.isVisible():
            self.show()
        self._place()

    def show_progress(self, title: str, msg: str, cur: int, total: int) -> None:
        self._hide_timer.stop()
        self.icon.setPixmap(vector_icon("export", 20, QColor(103, 232, 249)).pixmap(20, 20))
        self.title.setText(title)
        self.msg.setText(msg)
        self.bar.setVisible(True)
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(max(0, cur))
        self.action.setVisible(False)
        self._fade_in()

    def show_done(self, title: str, msg: str, folder: str = "", timeout_ms: int = 9000) -> None:
        self.icon.setPixmap(vector_icon("folder", 20, QColor(134, 239, 172)).pixmap(20, 20))
        self.title.setText(title)
        self.msg.setText(msg)
        self.bar.setVisible(False)
        self._folder = folder
        self.action.setVisible(bool(folder))
        self._fade_in()
        self._hide_timer.start(timeout_ms)

    def show_error(self, title: str, msg: str) -> None:
        self.icon.setPixmap(vector_icon("remove", 20, QColor(248, 113, 113)).pixmap(20, 20))
        self.title.setText(title)
        self.msg.setText(msg[:400])
        self.bar.setVisible(False)
        self.action.setVisible(False)
        self._fade_in()
        self._hide_timer.start(15000)

    def dismiss(self) -> None:
        self._hide_timer.stop()
        self.hide()

    def reposition(self) -> None:
        if self.isVisible():
            self._place()
