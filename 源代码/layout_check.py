# -*- coding: utf-8 -*-
"""Control-bar overlap check at several window sizes (isolated config).

Usage:  python layout_check.py [--shot-min path.png]
Exit code 0 = no intersecting / out-of-bounds controls at any size.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["FLASHMUSIC_CONFIG_DIR"] = tempfile.mkdtemp(prefix="fm_layout_cfg_")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QListWidgetItem  # noqa: E402


def main() -> int:
    qapp = QApplication.instance() or QApplication(sys.argv)
    import app as appmod

    win = appmod.MainWindow()
    win.show()
    # Fill the playlist with deliberately long rows (view-only, nothing played).
    lst = win.playlist
    for i in range(40):
        it = QListWidgetItem("Very Long Title " * 6 + f"#{i}")
        it.setData(Qt.ItemDataRole.UserRole, i)
        it.setData(Qt.ItemDataRole.UserRole + 1, "An Extremely Long Artist Name " * 3)
        it.setData(Qt.ItemDataRole.UserRole + 2, i + 1)
        lst.addItem(it)

    def settle() -> None:
        for _ in range(8):
            qapp.processEvents()

    def check(label: str) -> dict:
        settle()
        bar = win.player_bar
        items = [w for w in bar.layout_items() if w.isVisible()]
        names = {id(w): n for w, n in zip(bar.layout_items(),
                 ["shuffle", "prev", "play", "next", "repeat", "volume", "slider"])}
        problems = []
        for i, a in enumerate(items):
            ra = a.geometry()
            if not bar.rect().contains(ra):
                problems.append(f"{names[id(a)]} outside bar {ra.getRect()}")
            for b in items[i + 1:]:
                if ra.intersects(b.geometry()):
                    problems.append(f"{names[id(a)]} overlaps {names[id(b)]}")
        tc = bar.transport_rect().center().x()
        if abs(tc - bar.width() / 2) > 1.5:
            problems.append(f"transport off-centre {tc} vs {bar.width() / 2}")
        if bar.width() < bar.minimumSizeHint().width():
            problems.append(f"bar {bar.width()} < min {bar.minimumSizeHint().width()}")
        for b in bar.buttons:
            if b.size() != b.minimumSize():
                problems.append("button resized")
        # playlist: no horizontal scrollbar, every row exactly viewport-wide
        lst = win.playlist
        if lst.horizontalScrollBar().isVisible():
            problems.append("playlist horizontal scrollbar visible")
        if lst.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
            problems.append("playlist h-policy not AlwaysOff")
        vw = lst.viewport().width()
        for r in (0, lst.count() // 2, lst.count() - 1):
            rw = lst.visualItemRect(lst.item(r)).width()
            if rw != vw:
                problems.append(f"row {r} width {rw} != viewport {vw}")
        for area in win.findChildren(QAbstractScrollArea):
            if area.isVisible() and area.horizontalScrollBar().isVisible():
                problems.append(f"h-scrollbar visible in {area.objectName() or type(area).__name__}")
        return {
            "case": label,
            "window": [win.width(), win.height()],
            "sidebar": win.sidebar.width(),
            "bar": bar.width(),
            "slider": bar.slider.width() if bar.slider.isVisible() else 0,
            "playlist_viewport": win.playlist.viewport().width(),
            "row_w": win.playlist.visualItemRect(win.playlist.item(0)).width(),
            "problems": problems,
        }

    results = []
    for w, h in [(1000, 680), (1100, 720), (1200, 780), (1600, 900), (500, 400)]:
        win.showNormal()
        win.resize(w, h)
        results.append(check(f"{w}x{h}"))
    win.showMaximized()
    results.append(check("maximized"))
    win.showNormal()
    win.resize(1000, 680)
    settle()
    if "--shot-min" in sys.argv:
        out = sys.argv[sys.argv.index("--shot-min") + 1]
        win.grab().save(out)
    if "--shot-sidebar" in sys.argv:  # default + min size sidebar crops
        base = sys.argv[sys.argv.index("--shot-sidebar") + 1]
        for (w, h), tag in (((1200, 780), "default"), ((1000, 680), "min")):
            win.resize(w, h)
            settle()
            win.grab(win.sidebar.rect().translated(win.sidebar.mapTo(win, win.sidebar.rect().topLeft()))).save(f"{base}_{tag}.png")
    win.close()
    ok = all(not r["problems"] for r in results)
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    print("LAYOUT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
