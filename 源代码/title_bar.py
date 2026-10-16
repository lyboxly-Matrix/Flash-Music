# -*- coding: utf-8 -*-
"""Flash Music — frameless dark title bar (drag / min / max / close)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class TitleBar(QWidget):
    """Custom title bar matching #0b1220 neon chrome."""

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(44)
        self._drag_pos: Optional[QPoint] = None
        self._window = parent

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(4)

        self.lbl_brand = QLabel("⚡ Flash Music")
        self.lbl_brand.setObjectName("titleBarBrand")
        self.lbl_brand.setToolTip("Flash Music")
        lay.addWidget(self.lbl_brand)

        self.menu_bar = QMenuBar(self)
        self.menu_bar.setObjectName("titleMenuBar")
        self.menu_bar.setNativeMenuBar(False)
        self.menu_bar.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        lay.addWidget(self.menu_bar)

        lay.addStretch(1)

        self.btn_min = QPushButton("─")
        self.btn_min.setObjectName("winBtn")
        self.btn_min.setToolTip("最小化")
        self.btn_min.setFixedSize(40, 28)
        self.btn_min.clicked.connect(self.minimize_requested.emit)

        self.btn_max = QPushButton("□")
        self.btn_max.setObjectName("winBtn")
        self.btn_max.setToolTip("最大化")
        self.btn_max.setFixedSize(40, 28)
        self.btn_max.clicked.connect(self.maximize_requested.emit)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("winBtnClose")
        self.btn_close.setToolTip("关闭")
        self.btn_close.setFixedSize(40, 28)
        self.btn_close.clicked.connect(self.close_requested.emit)

        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addWidget(self.btn_close)

    def set_maximized_state(self, maximized: bool) -> None:
        if maximized:
            self.btn_max.setText("❐")
            self.btn_max.setToolTip("还原")
        else:
            self.btn_max.setText("□")
            self.btn_max.setToolTip("最大化")

    def _host(self) -> Optional[QWidget]:
        w = self.window()
        return w if w is not None else self._window

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            # Don't start drag from menu / window buttons
            child = self.childAt(event.position().toPoint())
            if isinstance(child, (QPushButton, QMenuBar)) or (
                child is not None and child.parent() is self.menu_bar
            ):
                super().mousePressEvent(event)
                return
            host = self._host()
            if host is not None and not host.isMaximized():
                self._drag_pos = (
                    event.globalPosition().toPoint() - host.frameGeometry().topLeft()
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._drag_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            host = self._host()
            if host is not None and not host.isMaximized():
                host.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, (QPushButton, QMenuBar)):
                self.maximize_requested.emit()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)
