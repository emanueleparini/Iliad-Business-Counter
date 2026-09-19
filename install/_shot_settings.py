"""Anteprima del pannello impostazioni."""
import sys
from pathlib import Path
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from core import config as cfgmod
from widget import theme
from widget.settings import SettingsDialog

app = QApplication(sys.argv)
out = Path("recon/artifacts")
out.mkdir(parents=True, exist_ok=True)
for mode in ("dark", "light"):
    cfg = cfgmod.load()
    dlg = SettingsDialog(cfg, theme.resolve(mode))
    dlg.adjustSize()
    QApplication.processEvents()
    pm = QPixmap(dlg.size())
    dlg.render(pm)
    canvas = QPixmap(pm.width() + 40, pm.height() + 40)
    canvas.fill(QColor("#3A4252" if mode == "dark" else "#D7DCE5"))
    qp = QPainter(canvas)
    qp.drawPixmap(20, 20, pm)
    qp.end()
    canvas.save(str(out / f"settings-{mode}.png"))
    print(out / f"settings-{mode}.png")
