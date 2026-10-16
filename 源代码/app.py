# -*- coding: utf-8 -*-
"""Flash Music — main window UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QCursor,
    QFont,
    QKeySequence,
    QLinearGradient,
    QMouseEvent,
    QPainter,
)
from PySide6.QtWidgets import (
    QListView,
    QMenu,
    QGridLayout,
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from config import load_config, save_config
from player_core import PlayerCore, Track
from theme import app_stylesheet
from title_bar import TitleBar
from cue_export import (
    build_export_items,
    default_output_dir,
    default_track_output_dir,
    export_all_cue_groups,
    export_tracks,
    find_ffmpeg,
    playlist_has_cue_export,
)
from toast import Toast, vector_icon
from fluid_visual import FluidVisual
from glass_button import GlassButton
from transport_bar import TransportBar



def _glow(widget: QWidget, color: QColor, blur: int = 28, y: int = 6) -> None:
    """Soft luxury glow behind glass panels / play control."""
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    fx.setOffset(0, y)
    fx.setColor(color)
    widget.setGraphicsEffect(fx)


def format_ms(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_sec = ms // 1000
    m, s = divmod(total_sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"



class PlaylistView(QListWidget):
    """Playlist list whose rows are always exactly viewport-wide."""

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._relayout_rows()

    def viewportEvent(self, e) -> bool:  # noqa: N802
        # vertical scrollbar showing/hiding resizes only the viewport
        if e.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._relayout_rows)
        return super().viewportEvent(e)

    def _relayout_rows(self) -> None:
        # uniformItemSizes caches the first row's size; drop the cache so the
        # new viewport width is picked up, then lay the rows out again.
        self.setUniformItemSizes(False)
        self.setUniformItemSizes(True)
        self.doItemsLayout()


class PlaylistDelegate(QStyledItemDelegate):
    """Two-line playlist rows: title + artist, fixed height, elide per line."""

    ROW_H = 54  # includes the 2px gap painted inside the row (view spacing = 0)
    PAD_X = 12
    PAD_Y = 8
    RIGHT_GUTTER = 4  # breathing room next to the slim scrollbar

    def sizeHint(self, option, index):  # noqa: N802
        # Width follows the viewport (never the text) so rows always fit the
        # sidebar and no horizontal scrollbar can appear; text is elided in paint.
        view = self.parent()
        w = view.viewport().width() if isinstance(view, QListWidget) else 0
        return QSize(max(1, w), self.ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect.adjusted(4, 2, -4 - self.RIGHT_GUTTER, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # glass row background
        if selected:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0.0, QColor("#06b6d4"))
            grad.setColorAt(1.0, QColor("#8b5cf6"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawRoundedRect(rect, 12, 12)
            title_color = QColor("#ffffff")
            meta_color = QColor("#e2e8f0")
        else:
            if hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(30, 41, 59, 160))
                painter.drawRoundedRect(rect, 12, 12)
            title_color = QColor("#e8eef8")
            meta_color = QColor("#8b9bb8")

        title = index.data(Qt.ItemDataRole.DisplayRole) or ""
        artist = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        num = index.data(Qt.ItemDataRole.UserRole + 2)
        if num is not None:
            title = f"{num}.  {title}"

        text_rect = rect.adjusted(self.PAD_X, self.PAD_Y, -self.PAD_X, -self.PAD_Y)
        title_font = QFont(option.font)
        title_font.setPointSize(max(9, title_font.pointSize()))
        title_font.setBold(selected)
        meta_font = QFont(option.font)
        meta_font.setPointSize(max(8, title_font.pointSize() - 1))

        # title line
        painter.setFont(title_font)
        painter.setPen(title_color)
        title_h = text_rect.height() // 2 if artist else text_rect.height()
        title_area = QRect(text_rect.left(), text_rect.top(), text_rect.width(), title_h)
        fm_title = painter.fontMetrics()
        elided_title = fm_title.elidedText(
            title, Qt.TextElideMode.ElideRight, title_area.width()
        )
        painter.drawText(
            title_area,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided_title,
        )

        if artist:
            painter.setFont(meta_font)
            painter.setPen(meta_color)
            meta_area = QRect(
                text_rect.left(),
                text_rect.top() + title_h,
                text_rect.width(),
                text_rect.height() - title_h,
            )
            fm_meta = painter.fontMetrics()
            elided_artist = fm_meta.elidedText(
                str(artist), Qt.TextElideMode.ElideRight, meta_area.width()
            )
            painter.drawText(
                meta_area,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                elided_artist,
            )

        painter.restore()



class CueExportWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(int, str, int)  # count, out_dir, lossy stream-copied
    failed = Signal(str)

    def __init__(self, tracks, out_dir: str | None, parent=None) -> None:
        super().__init__(parent)
        self._tracks = list(tracks)
        self._out_dir = out_dir

    def run(self) -> None:  # noqa: N802
        try:
            from pathlib import Path

            out = Path(self._out_dir) if self._out_dir else None

            def cb(cur: int, total: int, msg: str) -> None:
                self.progress.emit(cur, total, msg)

            res, _ff = export_all_cue_groups(self._tracks, out_dir=out, progress=cb)
            root = str(res[0].path.parent) if res else (self._out_dir or "")
            self.finished_ok.emit(len(res), root, sum(1 for r in res if r.mode == "copy"))
        except Exception as e:
            self.failed.emit(str(e))


class TrackExportWorker(QThread):
    """Exports selected tracks (CUE slices or whole files) off the UI thread."""

    progress = Signal(int, int, str)
    finished_ok = Signal(int, str, int)  # count, folder, lossy stream-copied
    failed = Signal(str)

    def __init__(self, items, out_dir: str | None, parent=None) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._out_dir = out_dir

    def run(self) -> None:  # noqa: N802
        try:
            from pathlib import Path

            res = export_tracks(
                self._items,
                Path(self._out_dir) if self._out_dir else None,
                progress=lambda c, n, m: self.progress.emit(c, n, m),
            )
            self.finished_ok.emit(len(res), str(res[0].path.parent) if res else "",
                                  sum(1 for r in res if r.mode == "copy"))
        except Exception as e:
            self.failed.emit(str(e))


class ElideLabel(QLabel):
    """Single-line label that elides with … instead of clipping/wrapping."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full = text
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(40)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._apply()

    def text_full(self) -> str:
        return self._full

    def _apply(self) -> None:
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, max(10, self.width() - 2)))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._apply()

    def changeEvent(self, e) -> None:  # noqa: N802
        super().changeEvent(e)
        from PySide6.QtCore import QEvent
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._apply()


class MainWindow(QMainWindow):
    _RESIZE_MARGIN = 6

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("⚡ Flash Music")
        self.setMinimumSize(1000, 680)
        self.resize(1200, 780)
        # Frameless dark chrome — custom title bar matches #0b1220
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setMouseTracking(True)

        self._cfg = load_config()
        self._player = PlayerCore(self)
        self._seeking = False
        self._last_folder = self._cfg.get("last_folder") or ""
        self._recent_paths: list[str] = list(self._cfg.get("recent_paths") or [])[:3]
        self._recent_menu = None
        self._last_export_dir: str = str(self._cfg.get("last_export_dir") or "")
        self._track_export_worker = None
        self._recent_btns: list = []
        self._resize_edge: str | None = None
        self._resize_origin = QPoint()
        self._resize_geo = None

        self._ready = False
        self._playlist_dirty = False  # user changed playlist this session
        self._restored_entries: list = list(self._cfg.get("playlist") or [])
        self._state_saved = False
        self._build_ui()
        self._connect_signals()
        self._apply_config()
        self._refresh_recent_ui()
        self.setStyleSheet(app_stylesheet())
        self._ready = True
        self.title_bar.set_maximized_state(self.isMaximized())

        # periodic save while playing (position survives crashes / kills)
        self._autosave = QTimer(self)
        self._autosave.setInterval(5000)
        self._autosave.timeout.connect(self._autosave_tick)
        self._autosave.start()
        self._setup_test_hooks()

    # ---- UI ----

    def _build_ui(self) -> None:
        chrome = QWidget()
        chrome.setObjectName("chromeRoot")
        self.setCentralWidget(chrome)
        chrome_lay = QVBoxLayout(chrome)
        chrome_lay.setContentsMargins(1, 1, 1, 1)
        chrome_lay.setSpacing(0)

        self.title_bar = TitleBar(self)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_maximize)
        self.title_bar.close_requested.connect(self.close)
        chrome_lay.addWidget(self.title_bar)

        body = QWidget()
        body.setMouseTracking(True)
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- sidebar ---
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(360)
        self.sidebar = sidebar
        side_lay = QVBoxLayout(sidebar)
        side_lay.setContentsMargins(14, 18, 14, 14)
        side_lay.setSpacing(10)

        # Brand lives only in title bar — sidebar shows playlist context
        heading = QLabel("播放列表")
        heading.setObjectName("sidebarHeading")
        side_lay.addWidget(heading)

        self.lbl_playlist_count = QLabel("0 首 · 本地播放")
        self.lbl_playlist_count.setObjectName("subtitleLabel")
        side_lay.addWidget(self.lbl_playlist_count)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_open_folder = QPushButton("📁 打开文件夹")
        self.btn_open_folder.setObjectName("primaryBtn")
        self.btn_add_files = QPushButton("➕ 添加")
        self.btn_add_files.setObjectName("ghostBtn")
        btn_row.addWidget(self.btn_open_folder)
        btn_row.addWidget(self.btn_add_files)
        side_lay.addLayout(btn_row)

        self.btn_clear = QPushButton("🗑 清空列表")
        self.btn_clear.setObjectName("ghostBtn")
        side_lay.addWidget(self.btn_clear)

        self.btn_export_cue = QPushButton("💿 导出分轨 FLAC（无损）")
        self.btn_export_cue.setObjectName("primaryBtn")
        self.btn_export_cue.setToolTip(
            "将 CUE + 整轨音频按采样精确切成每曲 FLAC（无损，保留原采样率/位深/声道），"
            "写入标题/艺术家/专辑/音轨号等标签并嵌入封面。需要系统已安装 ffmpeg。"
        )
        self.btn_export_cue.setVisible(False)
        side_lay.addWidget(self.btn_export_cue)

        # 最近打开：仅菜单（文件 → 最近打开），避免挤掉播放列表
        self._recent_btns = []
        self._export_worker = None

        self.playlist = PlaylistView()
        self.playlist.setObjectName("playlist")
        self.playlist.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.playlist.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist.setAlternatingRowColors(False)
        self.playlist.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.playlist.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.playlist.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.playlist.setResizeMode(QListView.ResizeMode.Adjust)
        self.playlist.setCornerWidget(None)
        self.playlist.setWordWrap(False)
        self.playlist.setUniformItemSizes(True)
        self.playlist.setSpacing(0)
        self.playlist.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.playlist.setMinimumHeight(180)
        self.playlist.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.playlist.setItemDelegate(PlaylistDelegate(self.playlist))
        side_lay.addWidget(self.playlist, stretch=1)

        root.addWidget(sidebar)

        # --- main area: strict vertical stack, no overlap ---
        main = QWidget()
        main.setObjectName("mainPanel")
        main_lay = QVBoxLayout(main)
        main_lay.setContentsMargins(20, 18, 20, 16)
        main_lay.setSpacing(14)

        # (1) compact now-playing header
        now_frame = QFrame()
        now_frame.setObjectName("glassCard")
        now_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        now_lay = QVBoxLayout(now_frame)
        now_lay.setContentsMargins(20, 14, 20, 14)
        now_lay.setSpacing(4)

        hint = QLabel("正在播放")
        hint.setObjectName("subtitleLabel")
        now_lay.addWidget(hint)

        self.lbl_now = ElideLabel("尚未选择曲目")
        self.lbl_now.setObjectName("nowPlaying")
        now_lay.addWidget(self.lbl_now)

        self.lbl_meta = ElideLabel("")
        self.lbl_meta.setObjectName("nowMeta")
        now_lay.addWidget(self.lbl_meta)
        main_lay.addWidget(now_frame)

        # (2) fluid visualization card — takes all remaining height
        fluid_card = QFrame()
        fluid_card.setObjectName("fluidCard")
        fluid_lay = QVBoxLayout(fluid_card)
        fluid_lay.setContentsMargins(6, 6, 6, 6)
        self.fluid = FluidVisual()
        self.fluid.setMinimumHeight(200)
        fluid_lay.addWidget(self.fluid)
        main_lay.addWidget(fluid_card, stretch=1)

        # (3) progress row
        prog_w = QWidget()
        prog_w.setObjectName("progressRow")
        prog_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        prog_row = QHBoxLayout(prog_w)
        prog_row.setContentsMargins(6, 0, 6, 0)
        prog_row.setSpacing(12)
        self.lbl_pos = QLabel("0:00")
        self.lbl_pos.setObjectName("timeLabel")
        self.lbl_pos.setMinimumWidth(48)
        self.slider_pos = QSlider(Qt.Orientation.Horizontal)
        self.slider_pos.setRange(0, 0)
        self.slider_pos.setEnabled(False)
        self.lbl_dur = QLabel("0:00")
        self.lbl_dur.setObjectName("timeLabel")
        self.lbl_dur.setMinimumWidth(48)
        self.lbl_dur.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_row.addWidget(self.lbl_pos)
        prog_row.addWidget(self.slider_pos, stretch=1)
        prog_row.addWidget(self.lbl_dur)
        main_lay.addWidget(prog_w)

        # (4) control bar
        self.btn_shuffle = GlassButton("shuffle", diameter=38, icon_size=20)
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.setToolTip("随机播放")

        self.btn_prev = GlassButton("backward", diameter=38, icon_size=23)
        self.btn_prev.setToolTip("上一首")

        self.btn_play = GlassButton("play", primary=True, diameter=52, icon_size=24)
        self.btn_play.setToolTip("播放 / 暂停")

        self.btn_next = GlassButton("forward", diameter=38, icon_size=23)
        self.btn_next.setToolTip("下一首")

        self.btn_repeat = GlassButton("repeat", diameter=38, icon_size=20)
        self.btn_repeat.setCheckable(True)
        self.btn_repeat.setToolTip("循环：关")
        self._repeat_cycle = ["off", "all", "one"]
        self._repeat_icons = {"off": "🔁", "all": "🔁", "one": "🔂"}
        self._repeat_tips = {
            "off": "循环：关",
            "all": "循环：全部",
            "one": "循环：单曲",
        }

        self.lbl_vol_icon = GlassButton("vol3", diameter=30, icon_size=19)
        self.lbl_vol_icon.setToolTip("静音 / 取消静音")
        self.lbl_vol_icon.clicked.connect(self._toggle_mute)
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setObjectName("volumeSlider")
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(70)
        self.slider_vol.setToolTip("音量")

        bar = TransportBar(
            [self.btn_shuffle, self.btn_prev, self.btn_play, self.btn_next, self.btn_repeat],
            self.lbl_vol_icon,
            self.slider_vol,
        )
        self.player_bar = bar

        main_lay.addWidget(bar)

        root.addWidget(main, stretch=1)
        chrome_lay.addWidget(body, stretch=1)

        # Hide native menu strip; menus live in custom title bar
        self.menuBar().hide()
        self._build_menu()

        # status
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪 · 本地播放，不上传任何文件")
        self.toast = Toast(self)

    def _build_menu(self) -> None:
        menubar = self.title_bar.menu_bar
        file_menu = menubar.addMenu("文件")

        act_folder = QAction("打开文件夹…", self)
        act_folder.setShortcut(QKeySequence("Ctrl+O"))
        act_folder.triggered.connect(self.open_folder)
        file_menu.addAction(act_folder)

        act_files = QAction("添加文件…", self)
        act_files.setShortcut(QKeySequence("Ctrl+Shift+O"))
        act_files.triggered.connect(self.add_files)
        file_menu.addAction(act_files)

        file_menu.addSeparator()

        act_clear = QAction("清空播放列表", self)
        act_clear.triggered.connect(self.clear_playlist)
        file_menu.addAction(act_clear)

        file_menu.addSeparator()

        self._recent_menu = file_menu.addMenu("最近打开")
        self._rebuild_recent_menu()

        file_menu.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        play_menu = menubar.addMenu("播放")
        act_play = QAction("播放 / 暂停", self)
        act_play.setShortcut(QKeySequence(Qt.Key.Key_Space))
        act_play.triggered.connect(self._player.toggle_play)
        play_menu.addAction(act_play)

        act_next = QAction("下一首", self)
        act_next.setShortcut(QKeySequence("Ctrl+Right"))
        act_next.triggered.connect(self._player.next)
        play_menu.addAction(act_next)

        act_prev = QAction("上一首", self)
        act_prev.setShortcut(QKeySequence("Ctrl+Left"))
        act_prev.triggered.connect(self._player.previous)
        play_menu.addAction(act_prev)

        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于 Flash Music", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _connect_signals(self) -> None:
        self.btn_open_folder.clicked.connect(self.open_folder)
        self.btn_add_files.clicked.connect(self.add_files)
        self.btn_clear.clicked.connect(self.clear_playlist)
        self.btn_export_cue.clicked.connect(self.export_cue_mp3)
        self.btn_play.clicked.connect(self._player.toggle_play)
        self.btn_next.clicked.connect(self._player.next)
        self.btn_prev.clicked.connect(self._player.previous)
        self.btn_shuffle.toggled.connect(self._on_shuffle_toggled)
        self.btn_repeat.clicked.connect(self._cycle_repeat)

        self.playlist.itemDoubleClicked.connect(self._on_item_activated)
        self.playlist.itemClicked.connect(self._on_item_clicked)
        self.playlist.customContextMenuRequested.connect(self._on_playlist_context)

        self.slider_pos.sliderPressed.connect(self._on_seek_press)
        self.slider_pos.sliderReleased.connect(self._on_seek_release)
        self.slider_pos.sliderMoved.connect(self._on_seek_moved)

        self.slider_vol.valueChanged.connect(self._on_vol_changed)

        self._player.track_changed.connect(self._on_track_changed)
        self._player.position_changed.connect(self._on_position)
        self._player.duration_changed.connect(self._on_duration)
        self._player.state_changed.connect(self._on_play_state)
        self._player.playlist_changed.connect(self._refresh_playlist)
        self._player.playlist_changed.connect(self._persist_playlist_soft)
        self._player.error_occurred.connect(self._on_error)
        self._player.level_changed.connect(self._on_audio_level)
        self._player.bands_changed.connect(self.fluid.set_bands)
        self._player.track_changed.connect(lambda _i: self._persist_playlist_soft(False))

    def _apply_config(self) -> None:
        vol = float(self._cfg.get("volume", 0.7))
        self.slider_vol.blockSignals(True)
        self.slider_vol.setValue(int(round(vol * 100)))
        self.slider_vol.blockSignals(False)
        self._player.set_volume(vol)
        self._update_vol_icon(vol)

        shuffle = bool(self._cfg.get("shuffle", False))
        self.btn_shuffle.blockSignals(True)
        self.btn_shuffle.setChecked(shuffle)
        self.btn_shuffle.blockSignals(False)
        self._player.set_shuffle(shuffle)

        repeat = self._cfg.get("repeat") or "off"
        self._player.set_repeat(repeat)
        self._update_repeat_ui(repeat)

        geo = self._cfg.get("geometry")
        if isinstance(geo, list) and len(geo) == 4:
            try:
                x, y, w, h = (int(v) for v in geo)
                if w < 1000 or h < 680:  # saved from the old cramped layout
                    w, h = 1200, 780
                self.setGeometry(x, y, w, h)
            except (TypeError, ValueError):
                pass

        entries = self._cfg.get("playlist") or []
        if entries:
            tracks = []
            for entry in entries:
                t = Track.from_config(entry)
                if t is not None:
                    tracks.append(t)
            if tracks:
                idx = int(self._cfg.get("last_index", 0))
                pos = int(self._cfg.get("position_ms", 0) or 0)
                self._player.set_tracks(tracks, start_index=idx, resume_ms=pos)
                msg = f"已恢复播放列表 · {len(tracks)} 首"
                if pos > 0:
                    msg += f" · 进度 {pos // 1000}s"
                self.status.showMessage(msg, 5000)

    # ---- actions ----

    @Slot()
    def open_folder(self) -> None:
        start = self._last_folder or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择音乐文件夹", start)
        if not folder:
            return
        self._last_folder = folder
        self._remember_path(folder)
        # Replace playlist so one album folder = one clear list (incl. CUE tracks)
        n = self._player.replace_with_paths([folder], optimize=True)
        if n == 0:
            self.status.showMessage("未找到支持的音频文件（含 CUE 分轨）", 4000)
        else:
            self.status.showMessage(f"✨ 已载入播放列表 · {n} 首（含 CUE 分轨）", 5000)

    @Slot()
    def add_files(self) -> None:
        start = self._last_folder or str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "添加音频文件",
            start,
            "音频文件 (*.mp3 *.flac *.wav *.m4a *.ogg *.aac *.wma);;所有文件 (*.*)",
        )
        if not files:
            return
        parent = str(Path(files[0]).parent)
        self._last_folder = parent
        # Remember each selected file (newest first), capped at 3 total recent
        for f in reversed(files):
            self._remember_path(f)
        n = self._player.add_paths(files, optimize=True)
        self.status.showMessage(f"✨ 已添加并优化 · 新增 {n} 首", 4000)

    @Slot()
    def clear_playlist(self) -> None:
        if not self._player.tracks:
            return
        reply = QMessageBox.question(
            self,
            "清空播放列表",
            "确定清空当前播放列表？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._player.clear_playlist()
            self.status.showMessage("播放列表已清空", 3000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 Flash Music",
            "<h3>⚡ Flash Music</h3>"
            "<p>简洁的本地音乐播放器</p>"
            "<p>• 播放列表 · 随机 / 循环<br>"
            "• 导入时自动优化（元数据排序 + 去重）<br>"
            "• 完全本地，不上传任何文件</p>"
            "<p style='color:#94a3b8'>Python · PySide6 · Qt Multimedia</p>",
        )

    # ---- playlist UI ----

    @Slot()
    def _refresh_playlist(self) -> None:
        self.playlist.blockSignals(True)
        self.playlist.clear()
        tracks = self._player.tracks
        for i, track in enumerate(tracks):
            item = QListWidgetItem(track.title or Path(track.path).stem)
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setData(Qt.ItemDataRole.UserRole + 1, track.artist or "")
            item.setData(Qt.ItemDataRole.UserRole + 2, i + 1)
            tip_lines = [track.display, track.path]
            if track.is_cue_track:
                tip_lines.append(f"CUE {track.start_ms}ms" + (f" → {track.end_ms}ms" if track.end_ms is not None else ""))
            item.setToolTip("\n".join(tip_lines))
            self.playlist.addItem(item)
        self.playlist.blockSignals(False)
        n = len(tracks)
        self.lbl_playlist_count.setText(f"{n} 首 · 本地播放")
        self._update_export_button()
        idx = self._player.current_index
        if 0 <= idx < self.playlist.count():
            self.playlist.setCurrentRow(idx)
            self.playlist.scrollToItem(self.playlist.item(idx))

    @Slot(object)
    def _on_item_activated(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(idx, int):
            self._player.play_index(idx, autoplay=True)

    @Slot(object)
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        # single click also jumps (simple UX) — but not while multi-selecting
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(idx, int) and idx != self._player.current_index:
            self._player.play_index(idx, autoplay=True)

    # ---- player feedback ----

    @Slot(int)
    def _on_track_changed(self, index: int) -> None:
        track = self._player.current_track
        if track is None:
            self.lbl_now.setText("尚未选择曲目")
            self.lbl_meta.setText("")
            self.lbl_now.setToolTip("")
            self.lbl_meta.setToolTip("")
            self.slider_pos.setEnabled(False)
            return
        self.lbl_now.setText(track.title)
        meta_parts = [p for p in (track.artist, getattr(track, "album", "")) if p]
        self.lbl_meta.setText(" · ".join(meta_parts) or Path(track.path).name)
        tip = f"{track.title}\n{' · '.join(meta_parts)}\n{track.path}".replace("\n\n", "\n")
        self.lbl_now.setToolTip(tip)
        self.lbl_meta.setToolTip(tip)
        if 0 <= index < self.playlist.count():
            self.playlist.blockSignals(True)
            self.playlist.setCurrentRow(index)
            self.playlist.scrollToItem(self.playlist.item(index))
            self.playlist.blockSignals(False)

    @Slot(int)
    def _on_position(self, pos: int) -> None:
        if self._seeking:
            return
        self.slider_pos.blockSignals(True)
        self.slider_pos.setValue(pos)
        self.slider_pos.blockSignals(False)
        self.lbl_pos.setText(format_ms(pos))

    @Slot(int)
    def _on_duration(self, dur: int) -> None:
        self.slider_pos.setRange(0, max(0, dur))
        self.slider_pos.setEnabled(dur > 0)
        self.lbl_dur.setText(format_ms(dur))

    @Slot(str)
    def _on_play_state(self, state: str) -> None:
        if state == "playing":
            self.btn_play.setText("⏸")
            if hasattr(self, "fluid"):
                self.fluid.set_playing(True)
        else:
            self.btn_play.setText("▶")
            if hasattr(self, "fluid"):
                self.fluid.set_playing(False)

    @Slot(float)
    def _on_audio_level(self, level: float) -> None:
        if hasattr(self, "fluid"):
            self.fluid.set_level(level)

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self.status.showMessage(f"⚠ {msg}", 8000)
        track = self._player.current_track
        detail = f"{msg}"
        if track:
            detail += f"\n\n文件：{track.path}\n\n提示：若 MP3 无法播放，请确认系统已安装媒体编解码器，或参阅 README 中的 ffmpeg 说明。"
        # non-blocking status is enough; avoid modal spam on every bad file

    # ---- seek / volume ----

    @Slot()
    def _on_seek_press(self) -> None:
        self._seeking = True

    @Slot()
    def _on_seek_release(self) -> None:
        self._player.seek(self.slider_pos.value())
        self._seeking = False

    @Slot(int)
    def _on_seek_moved(self, value: int) -> None:
        self.lbl_pos.setText(format_ms(value))

    @Slot(int)
    def _on_vol_changed(self, value: int) -> None:
        vol = value / 100.0
        self._player.set_volume(vol)
        self._update_vol_icon(vol)

    def _toggle_mute(self) -> None:
        cur = self.slider_vol.value()
        if cur > 0:
            self._unmute_value = cur
            self.slider_vol.setValue(0)
        else:
            self.slider_vol.setValue(int(getattr(self, "_unmute_value", 70) or 70))

    def _update_vol_icon(self, vol: float) -> None:
        if vol <= 0.001:
            self.lbl_vol_icon.setText("🔇")
        elif vol < 0.4:
            self.lbl_vol_icon.setText("🔉")
        else:
            self.lbl_vol_icon.setText("🔊")

    @Slot(bool)
    def _on_shuffle_toggled(self, checked: bool) -> None:
        self._player.set_shuffle(checked)
        tip = "随机：开" if checked else "随机：关"
        self.btn_shuffle.setToolTip(tip)
        self.status.showMessage(tip, 2000)

    @Slot()
    def _cycle_repeat(self) -> None:
        cur = self._player.repeat
        try:
            i = self._repeat_cycle.index(cur)
        except ValueError:
            i = 0
        nxt = self._repeat_cycle[(i + 1) % len(self._repeat_cycle)]
        self._player.set_repeat(nxt)
        self._update_repeat_ui(nxt)
        self.status.showMessage(self._repeat_tips[nxt], 2000)

    def _update_repeat_ui(self, mode: str) -> None:
        self.btn_repeat.setText(self._repeat_icons.get(mode, "🔁"))
        self.btn_repeat.setToolTip(self._repeat_tips.get(mode, "循环"))
        self.btn_repeat.setChecked(mode != "off")

    # ---- window chrome (frameless) ----

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.title_bar.set_maximized_state(self.isMaximized())

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.set_maximized_state(self.isMaximized())

    def _hit_resize_edge(self, pos: QPoint) -> str | None:
        if self.isMaximized():
            return None
        m = self._RESIZE_MARGIN
        r = self.rect()
        left = pos.x() <= m
        right = pos.x() >= r.width() - m
        top = pos.y() <= m
        bottom = pos.y() >= r.height() - m
        if top and left:
            return "tl"
        if top and right:
            return "tr"
        if bottom and left:
            return "bl"
        if bottom and right:
            return "br"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"
        return None

    def _cursor_for_edge(self, edge: str | None) -> Qt.CursorShape:
        mapping = {
            "l": Qt.CursorShape.SizeHorCursor,
            "r": Qt.CursorShape.SizeHorCursor,
            "t": Qt.CursorShape.SizeVerCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
        }
        return mapping.get(edge, Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._hit_resize_edge(event.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_origin = event.globalPosition().toPoint()
                self._resize_geo = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._resize_edge and self._resize_geo is not None:
            delta = event.globalPosition().toPoint() - self._resize_origin
            geo = self._resize_geo
            x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
            min_w, min_h = self.minimumWidth(), self.minimumHeight()
            edge = self._resize_edge
            if "r" in edge:
                w = max(min_w, geo.width() + delta.x())
            if "b" in edge:
                h = max(min_h, geo.height() + delta.y())
            if "l" in edge:
                new_w = max(min_w, geo.width() - delta.x())
                x = geo.x() + (geo.width() - new_w)
                w = new_w
            if "t" in edge:
                new_h = max(min_h, geo.height() - delta.y())
                y = geo.y() + (geo.height() - new_h)
                h = new_h
            self.setGeometry(x, y, w, h)
            event.accept()
            return
        edge = self._hit_resize_edge(pos)
        self.setCursor(self._cursor_for_edge(edge))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._resize_edge = None
        self._resize_geo = None
        super().mouseReleaseEvent(event)



    def _update_export_button(self) -> None:
        if not hasattr(self, "btn_export_cue"):
            return
        has = playlist_has_cue_export(self._player.tracks)
        busy = self._export_worker is not None and self._export_worker.isRunning()
        self.btn_export_cue.setVisible(has)
        self.btn_export_cue.setEnabled(has and not busy)

    def _ask_export_dir(self, what: str, fallback: str) -> tuple[bool, str | None]:
        """Confirm dialog: 导出 / 选择文件夹… / 取消. Returns (go, out_dir);
        out_dir None means the default folder next to each source."""
        remembered = self._last_export_dir if self._last_export_dir and Path(self._last_export_dir).is_dir() else ""
        shown = remembered or fallback
        box = QMessageBox(self)
        box.setWindowTitle("导出 FLAC（无损）")
        box.setText(
            f"将{what}导出为 FLAC 无损（保留原采样率 / 位深 / 声道），"
            f"写入标题 / 艺术家 / 专辑 / 音轨号等标签并嵌入封面。\n"
            f"有损来源（MP3 / AAC / OGG）不会伪装成无损，将按原格式直接拷贝音频流。\n\n"
            f"输出文件夹：\n{shown}"
        )
        b_ok = box.addButton("导出", QMessageBox.ButtonRole.AcceptRole)
        b_pick = box.addButton("选择文件夹…", QMessageBox.ButtonRole.ActionRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_pick:
            d = QFileDialog.getExistingDirectory(self, "选择导出文件夹", remembered or str(Path(fallback).parent))
            if not d:
                return False, None
            self._last_export_dir = d
            self._persist_playlist_soft(False)
            return True, d
        if clicked is b_ok:
            return True, (remembered or None)
        return False, None

    @staticmethod
    def _export_summary(count: int, lossy: int) -> str:
        flac = count - lossy
        parts = []
        if flac:
            parts.append(f"{flac} 首 FLAC 无损")
        if lossy:
            parts.append(f"{lossy} 首有损来源已按原格式拷贝（无法变成无损）")
        return "已导出 " + "，".join(parts or ["0 首"])

    @Slot()
    def export_cue_mp3(self) -> None:  # name kept for signal wiring; exports FLAC
        if self._export_worker is not None and self._export_worker.isRunning():
            return
        tracks = self._player.tracks
        if not playlist_has_cue_export(tracks):
            self.toast.show_error("导出分轨", "当前列表没有检测到 CUE 分轨。")
            return
        if not find_ffmpeg():
            self.toast.show_error("需要 ffmpeg", "未找到系统 ffmpeg。请安装后重试：winget install Gyan.FFmpeg")
            return
        cue_tracks = [tr for tr in tracks if tr.is_cue_track]
        go, out_dir = self._ask_export_dir("当前 CUE 专辑的全部分轨", str(default_output_dir(cue_tracks[0].path)))
        if not go:
            return
        self.btn_export_cue.setEnabled(False)
        self.toast.show_progress("导出分轨 FLAC（无损）", "准备导出…", 0, len(cue_tracks))
        self._export_worker = CueExportWorker(tracks, out_dir, self)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished_ok.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.start()

    @Slot(int, int, str)
    def _on_export_progress(self, cur: int, total: int, msg: str) -> None:
        self.toast.show_progress("导出分轨 FLAC（无损）", msg, cur, total)

    @Slot(int, str, int)
    def _on_export_finished(self, count: int, out_dir: str, lossy: int) -> None:
        self._export_worker = None
        self._update_export_button()
        self._last_export_result = {"count": count, "folder": out_dir, "lossy": lossy}
        self.toast.show_done("导出完成", f"{self._export_summary(count, lossy)}\n{out_dir}", out_dir)
        self.status.showMessage(f"✅ {self._export_summary(count, lossy)} → {out_dir}", 8000)

    @Slot(str)
    def _on_export_failed(self, err: str) -> None:
        self._export_worker = None
        self._update_export_button()
        self._last_export_result = {"error": err}
        self.toast.show_error("导出失败", err)

    # ---- playlist context menu / per-track export ----

    def _selected_rows(self) -> list[int]:
        rows = sorted({self.playlist.row(it) for it in self.playlist.selectedItems()})
        return [r for r in rows if 0 <= r < len(self._player.tracks)]

    def _build_playlist_menu(self, rows: list[int]) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("ctxMenu")
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        n = len(rows)
        act_play = menu.addAction(vector_icon("play"), "播放")
        act_play.setEnabled(n >= 1)
        act_play.triggered.connect(lambda: self._player.play_index(rows[0], autoplay=True))
        menu.addSeparator()
        label = "导出为 FLAC（无损）" if n <= 1 else f"导出所选 {n} 首为 FLAC（无损）"
        act_exp = menu.addAction(vector_icon("export"), label)
        act_exp.setEnabled(n >= 1)
        act_exp.triggered.connect(lambda: self._export_rows(rows))
        return menu

    @Slot(QPoint)
    def _on_playlist_context(self, pos: QPoint) -> None:
        item = self.playlist.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.playlist.clearSelection()
            item.setSelected(True)
        rows = self._selected_rows()
        if not rows:
            return
        self._build_playlist_menu(rows).exec(self.playlist.viewport().mapToGlobal(pos))

    def _export_rows(self, rows: list[int], out_dir: str | None = None, ask: bool = True) -> None:
        if self._track_export_worker is not None and self._track_export_worker.isRunning():
            self.toast.show_error("正在导出", "上一个导出任务还没结束，请稍候。")
            return
        tracks = self._player.tracks
        sel = [tracks[r] for r in rows if 0 <= r < len(tracks)]
        if not sel:
            return
        if not find_ffmpeg():
            self.toast.show_error("需要 ffmpeg", "未找到系统 ffmpeg。请安装后重试：winget install Gyan.FFmpeg")
            return
        if ask:
            what = f"《{sel[0].title}》" if len(sel) == 1 else f"所选 {len(sel)} 首"
            go, out_dir = self._ask_export_dir(
                what, str(default_track_output_dir(sel[0].path, sel[0].is_cue_track)))
            if not go:
                return
        items = build_export_items(sel, tracks)
        self.toast.show_progress("导出 FLAC（无损）", f"准备导出 {len(items)} 首…", 0, len(items))
        w = TrackExportWorker(items, out_dir, self)
        w.progress.connect(lambda c, n, m: self.toast.show_progress("导出 FLAC（无损）", m, c, n))
        w.finished_ok.connect(self._on_track_export_done)
        w.failed.connect(self._on_track_export_failed)
        self._track_export_worker = w
        w.start()

    @Slot(int, str, int)
    def _on_track_export_done(self, count: int, folder: str, lossy: int) -> None:
        self._track_export_worker = None
        self._last_export_result = {"count": count, "folder": folder, "lossy": lossy}
        self.toast.show_done("导出完成", f"{self._export_summary(count, lossy)}\n{folder}", folder)
        self.status.showMessage(f"✅ {self._export_summary(count, lossy)} → {folder}", 8000)

    @Slot(str)
    def _on_track_export_failed(self, err: str) -> None:
        self._track_export_worker = None
        self._last_export_result = {"error": err}
        self.toast.show_error("导出失败", err)

    # ---- recent paths ----

    def _remember_path(self, path: str) -> None:
        path = str(path or "").strip()
        if not path:
            return
        key = path.lower()
        self._recent_paths = [p for p in self._recent_paths if p.lower() != key]
        self._recent_paths.insert(0, path)
        self._recent_paths = self._recent_paths[:3]
        self._refresh_recent_ui()

    def _recent_label(self, path: str) -> str:
        p = Path(path)
        name = p.name or path
        if p.is_dir() or (not p.suffix and p.exists() and p.is_dir()):
            icon = "📁"
        else:
            icon = "🎵"
        if len(name) > 28:
            name = name[:14] + "…" + name[-10:]
        return f"{icon}  {name}"

    def _refresh_recent_ui(self) -> None:
        # Sidebar list must stay dominant; recent lives in File menu only.
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        menu = getattr(self, "_recent_menu", None)
        if menu is None:
            return
        menu.clear()
        paths = list(self._recent_paths)[:3]
        if not paths:
            act = QAction("（暂无）", self)
            act.setEnabled(False)
            menu.addAction(act)
            return
        for path in paths:
            act = QAction(self._recent_label(path), self)
            act.setToolTip(path)
            act.triggered.connect(
                lambda checked=False, p=path: self._open_recent_path(p)
            )
            menu.addAction(act)
        menu.addSeparator()
        act_clear = QAction("清除最近记录", self)
        act_clear.triggered.connect(self._clear_recent)
        menu.addAction(act_clear)

    def _open_recent_path(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            self.status.showMessage(f"⚠ 路径不存在：{path}", 5000)
            # drop missing entry
            self._recent_paths = [x for x in self._recent_paths if x.lower() != path.lower()]
            self._refresh_recent_ui()
            return
        self._remember_path(str(p))
        if p.is_dir():
            self._last_folder = str(p)
            n = self._player.replace_with_paths([str(p)], optimize=True)
            if n == 0:
                self.status.showMessage("未找到支持的音频文件（含 CUE 分轨）", 4000)
            else:
                self.status.showMessage(f"✨ 已载入最近文件夹 · {n} 首", 5000)
        elif p.is_file():
            self._last_folder = str(p.parent)
            n = self._player.add_paths([str(p)], optimize=True)
            self.status.showMessage(f"✨ 已添加最近文件 · 新增 {n} 首", 4000)
        else:
            self.status.showMessage(f"⚠ 无法打开：{path}", 4000)

    @Slot()
    def _clear_recent(self) -> None:
        self._recent_paths = []
        self._refresh_recent_ui()
        self.status.showMessage("已清除最近打开记录", 2500)

    # ---- persist ----


    def _playlist_for_save(self) -> list:
        """Never let a partially failed restore (e.g. drive not mounted yet)
        wipe the saved playlist: until the user edits the list this session,
        keep the original entries if the live list is shorter."""
        live = self._player.paths()
        if not self._playlist_dirty and len(live) < len(self._restored_entries):
            return list(self._restored_entries)
        return live

    def _autosave_tick(self) -> None:
        if self._ready and self._player.is_playing:
            self._save_state()

    def _persist_playlist_soft(self, user_change: bool = True) -> None:
        """Write playlist/index soon after changes (keeps restore fresh)."""
        if not getattr(self, "_ready", False):
            return
        if user_change is not False:
            self._playlist_dirty = True
        try:
            cfg = load_config()
            cfg["playlist"] = self._playlist_for_save()
            cfg["last_index"] = max(0, self._player.current_index)
            # keep existing position_ms unless we have a meaningful playback position
            pos = max(0, int(self._player.position or 0))
            if pos > 0:
                cfg["position_ms"] = pos
            cfg["recent_paths"] = list(self._recent_paths)[:3]
            cfg["last_folder"] = self._last_folder
            cfg["last_export_dir"] = self._last_export_dir
            save_config(cfg)
        except Exception:
            pass

    def _save_state(self) -> None:
        geo = self.geometry()
        data = {
            "playlist": self._playlist_for_save(),
            "volume": self._player.volume,
            "last_index": max(0, self._player.current_index),
            "position_ms": max(0, int(self._player.position or 0)),
            "shuffle": self._player.shuffle,
            "repeat": self._player.repeat,
            "last_folder": self._last_folder,
            "recent_paths": list(self._recent_paths)[:3],
            "last_export_dir": self._last_export_dir,
            "geometry": [geo.x(), geo.y(), geo.width(), geo.height()],
        }
        save_config(data)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        # responsive split: sidebar 290..360 px so the right panel always has
        # room for the transport group + volume block
        if getattr(self, "toast", None) is not None:
            self.toast.reposition()
        sb = getattr(self, "sidebar", None)
        if sb is not None:
            w = max(290, min(360, int(self.width() * 0.3)))
            if sb.width() != w:
                sb.setFixedWidth(w)

    def save_on_exit(self) -> None:
        """Idempotent final save (closeEvent and QApplication.aboutToQuit)."""
        if self._state_saved:
            return
        self._state_saved = True
        try:
            self._save_state()
        except Exception:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.save_on_exit()
        self._player.stop()
        event.accept()

    # ---- test hooks (only active when env vars are set) ----

    def _setup_test_hooks(self) -> None:
        import os

        report = os.environ.get("FLASHMUSIC_TEST_REPORT")
        if not report:
            return
        size = os.environ.get("FLASHMUSIC_TEST_SIZE")
        if size:
            try:
                sw, sh = (int(v) for v in size.lower().split("x"))
                QTimer.singleShot(300, lambda: self.resize(sw, sh))
            except ValueError:
                pass
        add = os.environ.get("FLASHMUSIC_TEST_ADD")
        shot = os.environ.get("FLASHMUSIC_TEST_SHOT")
        if add:
            QTimer.singleShot(800, lambda: self._player.replace_with_paths([add], optimize=True))
        if shot:
            def _play_muted() -> None:
                self._player.set_volume(0.0)
                self._player.play()
            QTimer.singleShot(1000, _play_muted)
        delay = 9000 if shot else 2500
        exp_dir = os.environ.get("FLASHMUSIC_TEST_EXPORT_DIR")
        if exp_dir:
            rows = [int(x) for x in (os.environ.get("FLASHMUSIC_TEST_EXPORT_ROWS") or "0").split(",")]
            QTimer.singleShot(1500, lambda: self._export_rows(rows, out_dir=exp_dir, ask=False))
        ctx_shot = os.environ.get("FLASHMUSIC_TEST_CTXMENU")
        if ctx_shot:
            QTimer.singleShot(delay - 1800, lambda: self._test_open_menu())
            QTimer.singleShot(delay - 900, lambda: self._test_grab_menu(ctx_shot))
        QTimer.singleShot(delay, lambda: self._test_report(report, shot))

    def _test_button_shots(self, out_dir: str) -> dict:
        """Grab control bar at rest and mid hover-animation (real paint path)."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QEnterEvent
        import os as _os

        from PySide6.QtCore import QPoint, QRect
        pbar = self.player_bar
        region = QRect(pbar.mapTo(self, QPoint(0, 0)), pbar.size()).adjusted(-8, -8, 8, 8)

        class _Win:  # grab window region => real dark backdrop behind the bar
            def __init__(s, w): s.w = w
            def grab(s): return s.w.grab(region)

        bar = _Win(self)
        res = {}
        for b in (self.btn_shuffle, self.btn_prev, self.btn_play, self.btn_next,
                  self.btn_repeat, self.lbl_vol_icon):
            b.reset_hover()  # real cursor may sit over the bar when window opens
        rest = _os.path.join(out_dir, "btn_rest.png")
        res["rest"] = bool(bar.grab().save(rest))

        def hover(btn, frames: int, local: QPointF) -> None:
            glob = QPointF(btn.mapToGlobal(local.toPoint()))
            QApplication.sendEvent(btn, QEnterEvent(local, local, glob))
            for _ in range(frames):
                btn.advance(1 / 60)

        nb = self.btn_next
        hover(nb, 7, QPointF(nb.width() * 0.25, nb.height() * 0.35))  # ~117 ms: overshoot
        res["blob_scale_next"] = round(nb._blob.x, 3)
        res["hover"] = bool(bar.grab().save(_os.path.join(out_dir, "btn_hover.png")))
        pb = self.btn_play
        hover(pb, 20, QPointF(pb.width() * 0.4, pb.height() * 0.38))
        res["hover_play"] = bool(bar.grab().save(_os.path.join(out_dir, "btn_hover_play.png")))
        return res

    def _test_open_menu(self) -> None:
        """Select rows 2-3 and pop the real context menu (non-blocking)."""
        self.playlist.clearSelection()
        for r in (1, 2):
            if r < self.playlist.count():
                self.playlist.item(r).setSelected(True)
        it = self.playlist.item(2) or self.playlist.item(0)
        self.playlist.scrollToItem(self.playlist.item(0), QAbstractItemView.ScrollHint.PositionAtTop)
        rect = self.playlist.visualItemRect(it)
        pos = QPoint(rect.left() + 120, rect.center().y())
        self._test_menu = self._build_playlist_menu(self._selected_rows())
        self._test_menu.popup(self.playlist.viewport().mapToGlobal(pos))
        acts = [a for a in self._test_menu.actions() if not a.isSeparator()]
        if len(acts) > 1:
            self._test_menu.setActiveAction(acts[1])  # hover state on export

    def _test_grab_menu(self, path: str) -> None:
        scr = self.screen()
        g = self.frameGeometry()
        img = scr.grabWindow(0, g.x() - scr.geometry().x(), g.y() - scr.geometry().y(), g.width(), g.height())
        img.save(path)
        m = getattr(self, "_test_menu", None)
        if m is not None:
            self._test_ctx_labels = [a.text() for a in m.actions() if not a.isSeparator()]
            m.close()

    def _test_report(self, report: str, shot: str | None) -> None:
        import json

        info = {
            "restored_tracks": len(self._player.tracks),
            "list_rows": self.playlist.count(),
            "index": self._player.current_index,
            "position_ms": int(self._player.position or 0),
            "fluid_backend": getattr(self.fluid, "backend", "?"),
            "fluid_fps": round(float(getattr(self.fluid, "fps", 0.0)), 1),
            "fluid_fallback_reason": getattr(self.fluid, "fallback_reason", ""),
            "playing": bool(self._player.is_playing),
        }
        try:
            bar = self.player_bar
            g = bar.transport_rect().center()
            pb = self.btn_play.mapTo(bar, self.btn_play.rect().center())
            info["bar_center_x"] = bar.width() / 2
            info["transport_center_x"] = g.x()
            info["play_center_x"] = pb.x()
            info["window"] = [self.width(), self.height()]
        except Exception as exc:
            info["center_err"] = str(exc)
        if shot:
            try:
                info["shot_saved"] = bool(self.fluid.grab_image().save(shot))
                self.grab().save(shot.replace(".png", "_window.png"))
            except Exception as exc:
                info["shot_error"] = str(exc)
        import os as _os
        info["export_result"] = getattr(self, "_last_export_result", None)
        info["ctx_menu_labels"] = getattr(self, "_test_ctx_labels", None)
        btn_dir = _os.environ.get("FLASHMUSIC_TEST_BTNSHOT")
        if btn_dir:
            info["btn_shots"] = self._test_button_shots(btn_dir)
        with open(report, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
        # exact same path as the title-bar ✕
        self.title_bar.btn_close.click()


def run_app() -> int:
    import sys

    # High-DPI friendly defaults
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Flash Music")
    app.setOrganizationName("FlashMusic")
    app.setStyle("Fusion")

    # single instance: a second launch just raises the existing window, so two
    # instances can never overwrite each other's saved playlist on exit
    import hashlib
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from config import config_dir

    key = "FlashMusic-" + hashlib.md5(str(config_dir()).lower().encode("utf-8")).hexdigest()[:12]
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    win = MainWindow()
    app.aboutToQuit.connect(win.save_on_exit)

    def _activate() -> None:
        while server.hasPendingConnections():
            c = server.nextPendingConnection()
            c.readAll()
            c.disconnectFromServer()
        if win.isMinimized():
            win.showNormal()
        win.show()
        win.raise_()
        win.activateWindow()

    server.newConnection.connect(_activate)
    win._single_server = server
    win.show()
    return app.exec()
