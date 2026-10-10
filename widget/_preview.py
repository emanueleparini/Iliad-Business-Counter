"""
Anteprima del widget senza mostrarlo: renderizza su PNG con i dati veri.
Serve per rivedere la grafica velocemente.

    .venv\\Scripts\\python.exe -m widget._preview
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from core import config as cfgmod
from core import store
from widget import theme
from widget.app import IliadWidget

OUT = Path(__file__).resolve().parent.parent / "recon/artifacts"


def shot(cfg, mode: str, snap: dict, name: str) -> Path:
    cfg.widget["theme"] = mode
    cfg.widget["window_layer"] = "normal"
    win = IliadWidget(cfg)
    win.timer.stop()
    win.apply_snapshot(snap, from_cache=True)
    win.adjustSize()
    win.resize(win.width(), win.sizeHint().height())
    QApplication.processEvents()

    pm = QPixmap(win.size())
    pm.fill(QColor(0, 0, 0, 0))
    win.render(pm)

    # sfondo a scacchi chiaro/scuro per vedere il contrasto reale
    canvas = QPixmap(pm.width() + 48, pm.height() + 48)
    canvas.fill(QColor("#3A4252" if mode == "dark" else "#D7DCE5"))
    qp = QPainter(canvas)
    qp.drawPixmap(24, 24, pm)
    qp.end()

    path = OUT / name
    canvas.save(str(path))
    win.tray.hide()
    win.close()
    return path


def main() -> int:
    snap = store.read_latest()
    if not snap:
        print("Nessun data/latest.json: esegui prima il collector.")
        return 1

    app = QApplication(sys.argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for mode in ("dark", "light"):
        cfg = cfgmod.load()
        p = shot(cfg, mode, snap, f"widget-{mode}.png")
        print(f"  {p}")
    QTimer.singleShot(0, app.quit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
