"""
Immagini del README, renderizzate dal codice vero del widget ma con dati
inventati: il repository e' pubblico, le SIM reali non devono finirci.

    .venv\\Scripts\\python.exe -m widget._readme_shots

Escono in docs/img/. Da rilanciare quando cambia la grafica.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

from core import config as cfgmod
from widget import theme
from widget.app import IliadWidget, make_gauge_icon
from widget.cards import RingGauge

OUT = Path(__file__).resolve().parent.parent / "docs" / "img"
DPR = 2          # immagini nitide anche su schermi ad alta densita'
FONT = "Segoe UI"


# --- dati demo ---------------------------------------------------------------

def demo_snapshot() -> dict:
    today = date.today()
    start = today - timedelta(days=14)
    end = start + timedelta(days=30)

    def sim(label, short, used, limit, per_day, status, exhaustion=None):
        days_left = (end - today).days
        remaining = max(0.0, limit - used)
        return {
            "uuid": label, "label": label, "msisdn_short": short,
            "plan_name": "iliad business", "active": True, "status": status,
            "data": {"used": used, "limit": limit, "unlimited": False,
                     "pct": used / limit},
            "cycle": {"start": start.isoformat(), "end": end.isoformat(),
                      "days_left": days_left, "progress": 14 / 30},
            "projection": {
                "per_day_gb": per_day,
                "safe_per_day_gb": remaining / max(1, days_left),
                "projected_gb": used + per_day * days_left,
                "exhaustion_date": exhaustion,
            },
        }

    boom = (today + timedelta(days=4)).isoformat() + "T12:00:00"
    return {
        "generated_at": f"{today.isoformat()}T10:42:00",
        "company": "Azienda Demo S.r.l.",
        "sims": [
            sim("Mario", "··· 0142", 61.4, 150, 4.4, "ok"),
            sim("Ufficio", "··· 7781", 98.2, 150, 7.0, "warn"),
            sim("Router 4G", "··· 3306", 131.0, 150, 9.4, "over", boom),
        ],
    }


# --- utilita' ----------------------------------------------------------------

def canvas(w: int, h: int) -> QPixmap:
    pm = QPixmap(w * DPR, h * DPR)
    pm.setDevicePixelRatio(DPR)
    pm.fill(Qt.transparent)
    return pm


def painter(pm: QPixmap) -> QPainter:
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setRenderHint(QPainter.TextAntialiasing)
    qp.setRenderHint(QPainter.SmoothPixmapTransform)
    return qp


def font(px: float, weight=QFont.Normal) -> QFont:
    f = QFont(FONT)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    return f


def grab(widget: QWidget) -> QPixmap:
    widget.adjustSize()
    QApplication.processEvents()
    pm = canvas(widget.width(), widget.height())
    widget.render(pm)
    return pm


def soft_shadow(qp: QPainter, rect: QRectF, radius: float, spread: int = 18,
                alpha: int = 70) -> None:
    """Ombra morbida a strati: niente effetti grafici, solo rettangoli."""
    qp.save()
    qp.setPen(Qt.NoPen)
    for i in range(spread, 0, -1):
        a = int(alpha * (1 - i / spread) ** 2 / 4)
        qp.setBrush(QColor(0, 0, 0, a))
        r = rect.adjusted(-i, -i + 6, i, i + 6)
        qp.drawRoundedRect(r, radius + i, radius + i)
    qp.restore()


def render_widget(mode: str) -> QPixmap:
    cfg = cfgmod.load()
    cfg.widget["theme"] = mode
    cfg.widget["window_layer"] = "normal"
    win = IliadWidget(cfg)
    win.timer.stop()
    win.tray.hide()
    win.apply_snapshot(demo_snapshot(), from_cache=False)
    win.footer.setText("aggiornato alle 10:42")
    pm = grab(win)
    win.close()
    return pm


def wallpaper(qp: QPainter, rect: QRectF) -> None:
    """Uno sfondo alla Windows 11: blu profondo con due bagliori."""
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0, QColor("#0B1A3A"))
    g.setColorAt(1, QColor("#1B0F33"))
    qp.fillRect(rect, g)
    for cx, cy, r, color in ((0.25, 0.35, 0.55, "#2F6BFF"),
                             (0.80, 0.20, 0.45, "#8A4DFF"),
                             (0.60, 0.95, 0.50, "#00B3A4")):
        rg = QRadialGradient(QPointF(rect.width() * cx, rect.height() * cy),
                             rect.width() * r)
        c = QColor(color)
        c.setAlpha(110)
        rg.setColorAt(0, c)
        c.setAlpha(0)
        rg.setColorAt(1, c)
        qp.fillRect(rect, rg)


# --- immagini ----------------------------------------------------------------

def hero() -> QPixmap:
    """Il pannello aperto dalla tray, sopra una barra di Windows 11."""
    W, H, BAR = 1000, 600, 48
    pm = canvas(W, H)
    qp = painter(pm)
    wallpaper(qp, QRectF(0, 0, W, H))

    # barra delle applicazioni
    bar = QRectF(0, H - BAR, W, BAR)
    qp.fillRect(bar, QColor(28, 28, 32, 235))
    qp.setPen(QPen(QColor(255, 255, 255, 30), 1))
    qp.drawLine(bar.topLeft(), bar.topRight())

    # icone al centro: Start e qualche app generica
    x0 = W / 2 - 4 * 44 / 2
    qp.setPen(Qt.NoPen)
    for i in range(4):
        cx = x0 + i * 44 + 22
        if i == 0:
            for dx in (-6, 1):
                for dy in (-6, 1):
                    qp.setBrush(QColor("#4CC2FF"))
                    qp.drawRoundedRect(QRectF(cx + dx - 1, bar.center().y() + dy - 1,
                                              6, 6), 1, 1)
        else:
            colors = ("#F7C948", "#4C8DFF", "#3DDC97")
            qp.setBrush(QColor(colors[i - 1]))
            qp.drawRoundedRect(QRectF(cx - 10, bar.center().y() - 10, 20, 20), 5, 5)

    # area di notifica: freccetta, la nostra icona (evidenziata), orologio
    clock_x = W - 92
    qp.setPen(QColor("#FFFFFF"))
    qp.setFont(font(12))
    qp.drawText(QRectF(clock_x, bar.top() + 6, 80, 18), Qt.AlignRight, "10:42")
    qp.drawText(QRectF(clock_x - 10, bar.top() + 24, 90, 18), Qt.AlignRight,
                date.today().strftime("%d/%m/%Y"))

    icon_c = QPointF(clock_x - 24, bar.center().y())
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor(255, 255, 255, 28))
    qp.drawRoundedRect(QRectF(icon_c.x() - 17, icon_c.y() - 17, 34, 34), 5, 5)
    snap = demo_snapshot()
    worst = theme.DARK.status("over")
    top = max(s["data"]["pct"] for s in snap["sims"])
    gauge = make_gauge_icon(top, worst, theme.DARK.track).pixmap(40, 40)
    qp.drawPixmap(QRectF(icon_c.x() - 10, icon_c.y() - 10, 20, 20), gauge,
                  QRectF(gauge.rect()))
    qp.setPen(QColor(255, 255, 255, 200))
    qp.setFont(font(13))
    qp.drawText(QRectF(icon_c.x() - 52, bar.top(), 20, BAR), Qt.AlignCenter, "⌃")

    # il pannello, come lo mette _place_popup: sopra la barra, vicino all'icona
    panel = render_widget("dark")
    pw, ph = panel.width() / DPR, panel.height() / DPR
    px = min(W - pw - 12, icon_c.x() - pw / 2)
    py = H - BAR - ph - 12
    soft_shadow(qp, QRectF(px, py, pw, ph), 14)
    qp.drawPixmap(QPointF(px, py), panel)

    # didascalia a sinistra
    qp.setPen(QColor("#FFFFFF"))
    qp.setFont(font(34, QFont.Bold))
    qp.drawText(QRectF(56, 150, 480, 50), Qt.AlignLeft, "Un clic sulla tray,")
    qp.drawText(QRectF(56, 194, 480, 50), Qt.AlignLeft, "e sai dove sei.")
    qp.setPen(QColor(255, 255, 255, 190))
    qp.setFont(font(16))
    qp.drawText(QRectF(56, 256, 420, 120), Qt.AlignLeft | Qt.TextWordWrap,
                "L'icona mostra la percentuale della SIM più consumata. "
                "Il pannello si apre in primo piano sopra la barra e si "
                "richiude con un altro clic.")
    qp.end()
    return pm


def themes() -> QPixmap:
    dark, light = render_widget("dark"), render_widget("light")
    dw, dh = dark.width() / DPR, dark.height() / DPR
    lw, lh = light.width() / DPR, light.height() / DPR
    pad, gap = 40, 40
    W, H = int(pad * 2 + dw + gap + lw), int(pad * 2 + max(dh, lh))
    pm = canvas(W, H)
    qp = painter(pm)
    # meta' scura, meta' chiara, con una diagonale morbida
    qp.fillRect(QRectF(0, 0, W, H), QColor("#1E2533"))
    path = QPainterPath()
    path.moveTo(W * 0.56, 0)
    path.lineTo(W, 0)
    path.lineTo(W, H)
    path.lineTo(W * 0.44, H)
    path.closeSubpath()
    qp.fillPath(path, QColor("#E6EAF1"))
    for pix, x, w, h in ((dark, pad, dw, dh), (light, pad + dw + gap, lw, lh)):
        y = pad + (max(dh, lh) - h) / 2
        soft_shadow(qp, QRectF(x, y, w, h), 14, alpha=60)
        qp.drawPixmap(QPointF(x, y), pix)
    qp.end()
    return pm


def tray_states() -> QPixmap:
    p = theme.DARK
    states = ((0.23, p.ok, "ok", "sotto il ritmo"),
              (0.87, p.warn, "attenzione", "in rotta per sforare"),
              (1.10, p.over, "esaurito", "pacchetto finito"),
              (None, p.accent, "in attesa", "nessun dato ancora"))
    cell, W, H = 170, 170 * 4 + 40, 200
    pm = canvas(W, H)
    qp = painter(pm)
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor("#14161B"))
    qp.drawRoundedRect(QRectF(0, 0, W, H), 18, 18)
    for i, (pct, color, title, sub) in enumerate(states):
        cx = 20 + i * cell + cell / 2
        icon = make_gauge_icon(pct, color, p.track).pixmap(128, 128)
        qp.drawPixmap(QRectF(cx - 32, 30, 64, 64), icon, QRectF(icon.rect()))
        # e la stessa icona alla taglia vera della tray
        qp.drawPixmap(QRectF(cx - 8, 104, 16, 16), icon, QRectF(icon.rect()))
        qp.setPen(QColor(color))
        qp.setFont(font(15, QFont.DemiBold))
        qp.drawText(QRectF(cx - cell / 2, 132, cell, 22), Qt.AlignCenter, title)
        qp.setPen(QColor(p.muted))
        qp.setFont(font(12))
        qp.drawText(QRectF(cx - cell / 2, 156, cell, 20), Qt.AlignCenter, sub)
    qp.end()
    return pm


def ring_explained() -> QPixmap:
    p = theme.DARK
    ring = RingGauge(p)
    ring.set_values(0.62, 0.47, p.warn, "62%")
    scale = 3.2
    W, H = 760, 300
    pm = canvas(W, H)
    qp = painter(pm)
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor(p.bg))
    qp.drawRoundedRect(QRectF(0, 0, W, H), 18, 18)

    size = 62 * scale
    rx, ry = 70, (H - size) / 2
    qp.save()
    qp.translate(rx, ry)
    qp.scale(scale, scale)
    # senza lo sfondo della finestra: l'anello va sul fondo della scheda
    ring.render(qp, QPoint(0, 0), renderFlags=QWidget.DrawChildren)
    qp.restore()

    center = QPointF(rx + size / 2, ry + size / 2)
    radius = size / 2 - 7 * scale

    def note(anchor: QPointF, y: float, color: str, title: str, body: str):
        x = rx + size + 70
        qp.setPen(QPen(QColor(color), 2))
        qp.drawLine(anchor, QPointF(x - 14, y + 11))
        qp.setBrush(QColor(color))
        qp.drawEllipse(anchor, 4, 4)
        qp.setPen(QColor(color))
        qp.setFont(font(17, QFont.DemiBold))
        qp.drawText(QRectF(x, y, 400, 24), Qt.AlignLeft, title)
        qp.setPen(QColor(p.muted))
        qp.setFont(font(14))
        qp.drawText(QRectF(x, y + 26, 400, 44), Qt.AlignLeft | Qt.TextWordWrap, body)

    note(QPointF(center.x() + radius * 0.95, center.y() + radius * 0.3), 46,
         p.warn, "L'arco: quanto hai consumato",
         "62% dei GB del ciclo. Il colore segue lo stato.")
    note(QPointF(center.x() + radius * 0.2, center.y() + radius * 1.0), 176,
         p.text, "La tacca: quanto ciclo è passato",
         "47% dei giorni. Arco oltre la tacca = consumi più in fretta del mese.")
    qp.end()
    return pm


def settings_shot() -> QPixmap:
    from widget.settings import SettingsDialog

    dlg = SettingsDialog(cfgmod.load(), theme.DARK)
    dlg.user.setText("12345678")          # demo: mai l'ID vero
    dlg.pwd.setText("password-demo")
    dlg.status.setText("Accesso verificato · Azienda Demo S.r.l.")
    dlg.combo_layer.blockSignals(True)     # la novita' in vetrina
    dlg.combo_layer.setCurrentIndex(dlg.combo_layer.findData("tray"))
    dlg._describe_layer()
    pix = grab(dlg)
    w, h = pix.width() / DPR, pix.height() / DPR
    pad = 28
    pm = canvas(int(w + pad * 2), int(h + pad * 2))
    qp = painter(pm)
    wallpaper(qp, QRectF(0, 0, w + pad * 2, h + pad * 2))
    soft_shadow(qp, QRectF(pad, pad, w, h), 8)
    qp.drawPixmap(QPointF(pad, pad), pix)
    qp.end()
    dlg.close()
    return pm


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont(FONT, 9))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in (("hero.png", hero), ("themes.png", themes),
                       ("tray-states.png", tray_states),
                       ("ring.png", ring_explained),
                       ("settings.png", settings_shot)):
        path = OUT / name
        make().save(str(path))
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
