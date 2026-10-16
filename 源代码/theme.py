# -*- coding: utf-8 -*-
"""Flash Music — liquid glass dark neon theme."""

from __future__ import annotations

# Palette
BG = "#0b1220"
BG_DEEP = "#070d18"
BG_RAISED = "#111827"
BG_SIDEBAR = "#0c1424"
SURFACE = "#151c2e"
SURFACE_HOVER = "#1c2540"
SURFACE_GLASS = "#161e32"
BORDER = "#243044"
BORDER_GLOW = "rgba(45, 212, 191, 68)"
TEXT = "#e8eef8"
TEXT_DIM = "#8b9bb8"
ACCENT_CYAN = "#06b6d4"
ACCENT_PURPLE = "#8b5cf6"
ACCENT_GLOW = "#22d3ee"
ACCENT_SOFT = "#67e8f9"
DANGER = "#f43f5e"
SUCCESS = "#34d399"

FONT_FAMILY = '"Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif'


def app_stylesheet() -> str:
    return f"""
    QWidget {{
        background-color: {BG};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}
    QMainWindow {{
        background-color: {BG_DEEP};
    }}
    QWidget#chromeRoot {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 {BG}, stop:0.5 {BG_DEEP}, stop:1 #0f172a
        );
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}
    QWidget#titleBar {{
        background-color: rgba(11, 18, 32, 230);
        border-bottom: 1px solid {BORDER};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
    }}
    QLabel#titleBarBrand {{
        color: {ACCENT_SOFT};
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.3px;
        padding-right: 10px;
    }}
    QMenuBar#titleMenuBar {{
        background-color: transparent;
        border: none;
        color: {TEXT};
        spacing: 2px;
        padding: 0;
    }}
    QMenuBar#titleMenuBar::item {{
        background: transparent;
        padding: 5px 12px;
        border-radius: 14px;
        margin: 2px 1px;
        color: {TEXT_DIM};
    }}
    QMenuBar#titleMenuBar::item:selected {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(6, 182, 212, 51), stop:1 rgba(139, 92, 246, 51)
        );
        color: {ACCENT_SOFT};
    }}
    QMenuBar#titleMenuBar::item:pressed {{
        background-color: rgba(139, 92, 246, 68);
        color: #ffffff;
    }}
    QMenuBar {{
        background-color: transparent;
        color: {TEXT};
        border: none;
    }}
    QMenuBar::item:selected {{
        background-color: {SURFACE_HOVER};
        color: {ACCENT_CYAN};
    }}
    QPushButton#winBtn {{
        background-color: transparent;
        border: none;
        border-radius: 10px;
        color: {TEXT_DIM};
        font-size: 12px;
        padding: 0;
        min-width: 40px;
        min-height: 28px;
    }}
    QPushButton#winBtn:hover {{
        background-color: rgba(30, 41, 59, 136);
        color: {TEXT};
        border: none;
    }}
    QPushButton#winBtnClose {{
        background-color: transparent;
        border: none;
        border-radius: 10px;
        color: {TEXT_DIM};
        font-size: 12px;
        padding: 0;
        min-width: 40px;
        min-height: 28px;
    }}
    QPushButton#winBtnClose:hover {{
        background-color: {DANGER};
        color: #ffffff;
        border: none;
    }}
    QFrame#sidebar {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 #0d1528, stop:1 #0a101c
        );
        border-right: 1px solid {BORDER};
    }}
    QLabel#sidebarHeading {{
        color: {TEXT};
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0.2px;
    }}
    QLabel#subtitleLabel {{
        color: {TEXT_DIM};
        font-size: 12px;
    }}
    QLabel#titleLabel {{
        font-size: 18px;
        font-weight: 700;
        color: {ACCENT_CYAN};
    }}
    QWidget#fluidVisual {{
        background-color: transparent;
        border: none;
    }}
    QFrame#fluidCard {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 #0d1424, stop:1 #120c24
        );
        border: 1px solid rgba(59, 130, 246, 51);
        border-radius: 18px;
    }}
    QFrame#glassCard QLabel, QFrame#playerBar QLabel, QFrame#fluidCard QLabel,
    QWidget#progressRow QLabel, QWidget#progressRow, QWidget#mainPanel,
    QWidget#transportGroup, QWidget#volumeBlock {{
        background: transparent;
        border: none;
    }}
    QLabel#volIcon {{
        font-size: 15px;
        color: {TEXT_DIM};
    }}
    QFrame#glassCard {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 #152036, stop:0.5 #121a2c, stop:1 #181030
        );
        border: 1px solid rgba(51, 65, 85, 136);
        border-radius: 18px;
    }}
    QFrame#playerBar {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(15, 23, 42, 238), stop:0.5 rgba(19, 27, 46, 238), stop:1 rgba(21, 16, 40, 238)
        );
        border: 1px solid rgba(51, 65, 85, 102);
        border-radius: 20px;
    }}
    QLabel#nowPlaying {{
        font-size: 20px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#nowMeta {{
        color: {TEXT_DIM};
        font-size: 13px;
    }}
    QLabel#timeLabel {{
        color: {TEXT_DIM};
        font-size: 11px;
        font-family: "Consolas", "Cascadia Mono", monospace;
    }}
    QListWidget#playlist {{
        background-color: transparent;
        border: none;
        outline: none;
        padding: 4px;
    }}
    QListWidget#playlist::item {{
        padding: 0px;
        margin: 0px;
        color: {TEXT};
        background-color: transparent;
        border: none;
    }}
    QListWidget#playlist::item:hover {{
        background-color: transparent;
    }}
    QListWidget#playlist::item:selected {{
        background-color: transparent;
        color: #ffffff;
    }}
    QPushButton {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 #1c2538, stop:1 #141b2b
        );
        color: {TEXT};
        border: 1px solid rgba(51, 65, 85, 170);
        border-radius: 16px;
        padding: 8px 16px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 #243049, stop:1 #1a2236
        );
        border-color: {ACCENT_CYAN};
        color: {ACCENT_SOFT};
    }}
    QPushButton:pressed {{
        background-color: {BG_DEEP};
        padding-top: 9px;
        padding-bottom: 7px;
    }}
    QPushButton:checked {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(6, 182, 212, 170), stop:1 rgba(139, 92, 246, 170)
        );
        border-color: {ACCENT_PURPLE};
        color: #ffffff;
    }}
    QPushButton#primaryBtn {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 {ACCENT_CYAN}, stop:0.45 #3b82f6, stop:1 {ACCENT_PURPLE}
        );
        border: 1px solid rgba(103, 232, 249, 102);
        color: #ffffff;
        font-weight: 600;
        padding: 9px 18px;
        border-radius: 18px;
    }}
    QPushButton#primaryBtn:hover {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 {ACCENT_GLOW}, stop:0.5 #818cf8, stop:1 #a78bfa
        );
        border-color: {ACCENT_SOFT};
    }}
    QPushButton#ghostBtn {{
        background-color: rgba(17, 24, 39, 136);
        border: 1px solid rgba(51, 65, 85, 136);
        border-radius: 16px;
        color: {TEXT_DIM};
    }}
    QPushButton#ghostBtn:hover {{
        color: {TEXT};
        border-color: {ACCENT_PURPLE};
        background-color: rgba(30, 27, 75, 85);
    }}
    QPushButton#iconBtn {{
        background-color: rgba(17, 24, 39, 102);
        border: 1px solid rgba(51, 65, 85, 85);
        border-radius: 22px;
        padding: 8px;
        min-width: 44px;
        min-height: 44px;
        font-size: 17px;
        color: {TEXT};
    }}
    QPushButton#iconBtn:hover {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(6, 182, 212, 51), stop:1 rgba(139, 92, 246, 51)
        );
        border-color: {ACCENT_CYAN};
        color: {ACCENT_SOFT};
    }}
    QPushButton#iconBtn:checked {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(6, 182, 212, 102), stop:1 rgba(139, 92, 246, 102)
        );
        border-color: {ACCENT_PURPLE};
        color: #ffffff;
    }}
    QPushButton#playBtn {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 {ACCENT_CYAN}, stop:0.5 #6366f1, stop:1 {ACCENT_PURPLE}
        );
        border: 2px solid rgba(165, 243, 252, 136);
        border-radius: 28px;
        min-width: 56px;
        min-height: 56px;
        max-width: 56px;
        max-height: 56px;
        font-size: 22px;
        color: #ffffff;
        font-weight: 700;
        padding: 0;
    }}
    QPushButton#playBtn:hover {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 {ACCENT_GLOW}, stop:0.5 #818cf8, stop:1 #c4b5fd
        );
        border-color: rgba(255, 255, 255, 170);
    }}
    QPushButton#playBtn:pressed {{
        background-color: {ACCENT_PURPLE};
    }}
    QSlider::groove:horizontal {{
        height: 8px;
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 #1e293b, stop:1 #312e81
        );
        border-radius: 4px;
        border: 1px solid rgba(51, 65, 85, 102);
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_CYAN}, stop:1 {ACCENT_PURPLE}
        );
        border-radius: 4px;
    }}
    QSlider::handle:horizontal {{
        background: qlineargradient(
            x1:0, y1:0, x2:0, y2:1,
            stop:0 #ffffff, stop:1 {ACCENT_SOFT}
        );
        border: 2px solid {ACCENT_CYAN};
        width: 16px;
        height: 16px;
        margin: -6px 0;
        border-radius: 9px;
    }}
    QSlider::handle:horizontal:hover {{
        background: #ffffff;
        border-color: {ACCENT_GLOW};
    }}
    QSlider#volumeSlider::groove:horizontal {{
        height: 5px;
    }}
    QSlider#volumeSlider::handle:horizontal {{
        width: 12px;
        height: 12px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QComboBox {{
        background-color: {SURFACE_GLASS};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 4px 10px;
        min-width: 80px;
    }}
    QComboBox:hover {{
        border-color: {ACCENT_CYAN};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_RAISED};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT_PURPLE};
        color: {TEXT};
        border-radius: 8px;
    }}

    QPushButton#recentBtn {{
        background-color: rgba(17, 24, 39, 153);
        border: 1px solid rgba(51, 65, 85, 119);
        border-radius: 14px;
        padding: 7px 12px;
        color: {TEXT_DIM};
        text-align: left;
        font-weight: 500;
    }}
    QPushButton#recentBtn:hover {{
        color: {ACCENT_SOFT};
        border-color: {ACCENT_CYAN};
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(6, 182, 212, 34), stop:1 rgba(139, 92, 246, 34)
        );
    }}
    QStatusBar {{
        background-color: transparent;
        color: {TEXT_DIM};
        border-top: 1px solid {BORDER};
        font-size: 11px;
        padding-left: 8px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 7px;
        margin: 6px 1px 6px 0px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(148, 163, 184, 60);
        border-radius: 3px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(167, 139, 250, 200);
    }}
    QScrollBar::handle:vertical:pressed {{
        background: rgba(103, 232, 249, 220);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        border: none;
        background: transparent;
    }}
    QAbstractScrollArea::corner {{
        background: transparent;
        border: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 2px 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 #334155, stop:1 #4c1d95
        );
        border-radius: 4px;
        min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {ACCENT_PURPLE};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}
    QMenu {{
        background-color: rgba(15, 23, 42, 238);
        border: 1px solid {BORDER};
        border-radius: 12px;
        color: {TEXT};
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 18px;
        border-radius: 8px;
    }}
    QMenu::item:selected {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_CYAN}, stop:1 {ACCENT_PURPLE}
        );
        color: #ffffff;
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 4px 10px;
    }}
    QMenu#ctxMenu {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(24, 34, 56, 242), stop:0.55 rgba(18, 26, 46, 242), stop:1 rgba(26, 18, 51, 242)
        );
        border: 1px solid rgba(103, 232, 249, 64);
        border-radius: 14px;
        padding: 6px;
        color: {TEXT};
    }}
    QMenu#ctxMenu::item {{
        padding: 9px 22px 9px 12px;
        border-radius: 9px;
        margin: 1px 2px;
        background: transparent;
    }}
    QMenu#ctxMenu::icon {{
        padding-left: 10px;
    }}
    QMenu#ctxMenu::item:selected {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(6, 182, 212, 85), stop:1 rgba(139, 92, 246, 85)
        );
        border: 1px solid rgba(255, 255, 255, 34);
        color: #ffffff;
    }}
    QMenu#ctxMenu::item:disabled {{
        color: {TEXT_DIM};
    }}
    QMenu#ctxMenu::separator {{
        height: 1px;
        background: rgba(255, 255, 255, 24);
        margin: 4px 12px;
    }}
    QFrame#toast {{
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 #1a2540, stop:1 #1d1438
        );
        border: 1px solid #2f5670;
        border-radius: 16px;
    }}
    QFrame#toast QLabel {{
        background: transparent;
        border: none;
    }}
    QLabel#toastTitle {{
        color: {TEXT};
        font-size: 13px;
        font-weight: 600;
    }}
    QLabel#toastMsg {{
        color: {TEXT_DIM};
        font-size: 12px;
    }}
    QProgressBar#toastBar {{
        background: #2a3350;
        border: none;
        border-radius: 3px;
    }}
    QProgressBar#toastBar::chunk {{
        border-radius: 3px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_CYAN}, stop:1 {ACCENT_PURPLE});
    }}
    QPushButton#toastAction {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #0891b2, stop:1 #7c3aed);
        border: 1px solid #5b7fa0;
        border-radius: 13px;
        color: #ffffff;
        padding: 5px 14px;
        font-size: 12px;
    }}
    QPushButton#toastClose {{
        background: transparent;
        border: none;
        color: {TEXT_DIM};
        padding: 0;
        min-width: 0;
        min-height: 0;
    }}
    QPushButton#toastClose:hover {{
        color: #ffffff;
    }}
    QToolTip {{
        background-color: #0f172a;
        color: {TEXT};
        border: 1px solid {ACCENT_CYAN};
        border-radius: 8px;
        padding: 6px 10px;
    }}
    """
