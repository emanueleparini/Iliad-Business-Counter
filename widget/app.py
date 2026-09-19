"""
Widget desktop dei contatori iliad.

    .venv\\Scripts\\pythonw.exe -m widget.app

Finestra senza bordi, agganciata al desktop (mai in primo piano), con icona
nella tray. Aggiorna da sola all'intervallo di config.toml; click su una
scheda = aggiornamento immediato.
"""

from __future__ import annotations

import ctypes
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core import config as cfgmod
from core import store
from core.api import IliadClient, has_credentials
from widget import theme
from widget.cards import RoundedPanel, SimCard
from widget.settings import SettingsDialog

STATE_FILE = cfgmod.DATA_DIR / "widget_state.json"

# --- Win32 -----------------------------------------------------------------
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x08000000, 0x00000080


def sink_to_desktop(win: QWidget, no_activate: bool = True) -> None:
    """
    Manda la finestra in fondo allo Z-order e le toglie il diritto di attivarsi:
    resta sul desktop come i Memo, senza mai coprire cio' su cui stai lavorando.
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(win.winId())
        user32 = ctypes.windll.user32
        if no_activate:
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            style = get_long(hwnd, GWL_EXSTYLE)
            set_long(hwnd, GWL_EXSTYLE,
                     style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except (OSError, AttributeError, ValueError):
        pass  # su una versione di Windows ostile il widget resta comunque usabile


# --- fetch in background ---------------------------------------------------


class _FetchSignals(QObject):
    done = Signal(dict)
    failed = Signal(str)


class FetchTask(QRunnable):
    """Un giro di raccolta fuori dal thread della UI."""

    def __init__(self, cfg) -> None:
        super().__init__()
        self.cfg = cfg
        self.signals = _FetchSignals()

    def run(self) -> None:
        try:
            from core.snapshot import build

            client = IliadClient(self.cfg.base_url)
            snap = build(client, self.cfg)
            store.write_latest(snap)
            store.record(snap)
            self.signals.done.emit(snap)
        except Exception as exc:                      # la UI non deve morire mai
            self.signals.failed.emit(str(exc))


# --- icona -----------------------------------------------------------------


def make_icon(color: str, size: int = 64) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setBrush(QColor(color))
    qp.setPen(Qt.NoPen)
    qp.drawEllipse(4, 4, size - 8, size - 8)
    qp.setPen(QColor("#FFFFFF"))
    f = QFont()
    f.setPointSizeF(size * 0.42)
    f.setWeight(QFont.Bold)
    qp.setFont(f)
    qp.drawText(pm.rect(), Qt.AlignCenter, "i")
    qp.end()
    return QIcon(pm)


# --- finestra --------------------------------------------------------------


class IliadWidget(QWidget):
    def __init__(self, cfg) -> None:
        super().__init__()
        self.cfg = cfg
        self.p = theme.resolve(cfg.widget.get("theme", "auto"))
        self.pool = QThreadPool.globalInstance()
        self.cards: dict[str, SimCard] = {}
        self._drag: QPoint | None = None
        self._notified: set[str] = set()
        self._settings: SettingsDialog | None = None
        self._busy = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnBottomHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("iliad counter")

        self._build_ui()
        self._restore_geometry()
        self._apply_style()
        self._build_tray()

        # primo disegno con l'ultimo dato salvato: nessuna finestra vuota
        cached = store.read_latest()
        if cached:
            self.apply_snapshot(cached, from_cache=True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(max(5, cfg.refresh_minutes) * 60_000)

        if has_credentials():
            QTimer.singleShot(1200, self.refresh)
        else:
            # prima accensione: interrogare il portale a vuoto non serve a nulla
            self.footer.setText("configura l'accesso per iniziare")
            QTimer.singleShot(400, self.open_settings)

    # -- costruzione ------------------------------------------------------

    def _build_ui(self) -> None:
        width = int(self.cfg.widget.get("width", 320))
        self.setFixedWidth(width)

        self.panel = RoundedPanel(self.p, parent=self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.brand = QLabel("iliad", self.panel)
        self.brand.setObjectName("brand")
        self.company = QLabel("", self.panel)
        self.company.setObjectName("company")
        self.btn_refresh = QPushButton("⟳", self.panel)
        self.btn_refresh.setObjectName("iconBtn")
        self.btn_refresh.setFixedSize(22, 22)
        self.btn_refresh.setToolTip("Aggiorna ora")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_menu = QPushButton("⋯", self.panel)
        self.btn_menu.setObjectName("iconBtn")
        self.btn_menu.setFixedSize(22, 22)
        self.btn_menu.clicked.connect(self._show_menu)

        head.addWidget(self.brand)
        head.addWidget(self.company, 1)
        head.addWidget(self.btn_refresh)
        head.addWidget(self.btn_menu)
        root.addLayout(head)

        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(7)
        root.addLayout(self.cards_box)

        self.footer = QLabel("in attesa di dati…", self.panel)
        self.footer.setObjectName("footer")
        root.addWidget(self.footer)

    def _apply_style(self) -> None:
        p = self.p
        self.setStyleSheet(f"""
            QLabel {{ color: {p.text}; }}
            #brand {{ color: {p.accent}; font-size: 12px; font-weight: 700;
                      letter-spacing: 0.4px; }}
            #company {{ color: {p.faint}; font-size: 10px; }}
            #footer {{ color: {p.faint}; font-size: 10px; padding-top: 2px; }}
            #iconBtn {{ color: {p.muted}; background: transparent; border: none;
                        font-size: 13px; border-radius: 11px; }}
            #iconBtn:hover {{ background: {p.card_hover}; color: {p.text}; }}
            #simCard {{ background: {p.card}; border-radius: 10px; }}
            #simCard:hover {{ background: {p.card_hover}; }}
            #cardTitle {{ font-size: 11.5px; font-weight: 600; color: {p.muted}; }}
            #cardSub {{ color: {p.faint}; font-size: 10px; }}
            #cardPrimary {{ font-size: 15px; font-weight: 700; padding-top: 1px; padding-bottom: 2px; }}
            #cardDetail {{ color: {p.muted}; font-size: 10px; }}
            #cardAlert {{ font-size: 10px; font-weight: 600; padding-top: 2px; }}
        """)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon(self.p.accent), self)
        self.tray.setToolTip("iliad counter")
        menu = QMenu()
        for label, slot in (
            ("Impostazioni…", self.open_settings),
            ("Aggiorna ora", self.refresh),
            ("Mostra / nascondi", self._toggle_visible),
            ("Riporta in vista", self._recenter),
        ):
            act = QAction(label, self)
            act.triggered.connect(slot)
            menu.addAction(act)
        menu.addSeparator()
        quit_act = QAction("Esci", self)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._toggle_visible()
            if reason == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()

    def _show_menu(self) -> None:
        self.btn_menu.setMenu(None)
        self.tray.contextMenu().exec(
            self.btn_menu.mapToGlobal(QPoint(0, self.btn_menu.height()))
        )

    def open_settings(self) -> None:
        if self._settings is None:
            dlg = SettingsDialog(self.cfg, self.p)
            dlg.setWindowIcon(make_icon(self.p.accent))
            dlg.credentials_saved.connect(self.refresh)
            dlg.refresh_changed.connect(
                lambda m: self.timer.setInterval(max(5, m) * 60_000)
            )
            self._settings = dlg
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    # -- dati -------------------------------------------------------------

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.btn_refresh.setEnabled(False)
        self.footer.setText("aggiornamento in corso…")
        task = FetchTask(self.cfg)
        task.signals.done.connect(self.apply_snapshot)
        task.signals.failed.connect(self._on_failed)
        self.pool.start(task)

    def _on_failed(self, message: str) -> None:
        self._busy = False
        self.btn_refresh.setEnabled(True)
        cached = store.read_latest()
        when = ""
        if cached:
            when = f" · ultimo dato {cached.get('generated_at','')[11:16]}"
        short = message if len(message) < 48 else message[:45] + "…"
        self.footer.setText(f"non aggiornato: {short}{when}")

    def apply_snapshot(self, snap: dict, from_cache: bool = False) -> None:
        self._busy = False
        self.btn_refresh.setEnabled(True)

        self.company.setText(snap.get("company") or "")

        if snap.get("error"):
            self.footer.setText(str(snap["error"])[:60])

        for sim in snap.get("sims", []):
            uuid = sim["uuid"]
            card = self.cards.get(uuid)
            if card is None:
                card = SimCard(self.p, self.panel)
                card.clicked.connect(self.refresh)
                self.cards[uuid] = card
                self.cards_box.addWidget(card)
            card.update_from(sim)

        when = snap.get("generated_at", "")
        stamp = when[11:16] if len(when) > 15 else "—"
        worst = self._worst_status(snap)
        self.tray.setIcon(make_icon(self.p.status(worst)))
        self.tray.setToolTip(self._tray_text(snap))
        self.footer.setText(
            f"{'dato salvato' if from_cache else 'aggiornato'} alle {stamp}"
        )

        self.adjustSize()
        self.panel.adjustSize()
        if self.cfg.widget.get("pin_to_desktop", True):
            sink_to_desktop(self)
        if not from_cache:
            self._maybe_notify(snap)

    @staticmethod
    def _worst_status(snap: dict) -> str:
        order = ["over", "warn", "ok", "unknown", "inactive"]
        found = [s.get("status", "unknown") for s in snap.get("sims", [])]
        for st in order:
            if st in found:
                return st
        return "unknown"

    @staticmethod
    def _tray_text(snap: dict) -> str:
        rows = ["iliad counter"]
        for sim in snap.get("sims", []):
            d = sim.get("data") or {}
            if d.get("used") is None:
                continue
            from core.cycle import fmt_gb
            rows.append(f"{sim.get('label')}: {fmt_gb(d['used'])}/"
                        f"{fmt_gb(d.get('limit'))} GB")
        return "\n".join(rows)

    def _maybe_notify(self, snap: dict) -> None:
        """Una notifica per soglia e per ciclo: nessuno vuole essere assillato."""
        thresholds = self.cfg.alerts.get("usage_pct", [80, 95])
        warn_overrun = self.cfg.alerts.get("notify_on_overrun_projection", True)

        for sim in snap.get("sims", []):
            d = sim.get("data") or {}
            pct = d.get("pct")
            cycle = (sim.get("cycle") or {}).get("start", "?")
            label = sim.get("label", "SIM")

            if pct is not None:
                for t in sorted(thresholds):
                    key = f"{sim['uuid']}:{cycle}:{t}"
                    if pct * 100 >= t and key not in self._notified:
                        self._notified.add(key)
                        self.tray.showMessage(
                            f"{label}: {t}% dei dati",
                            f"{pct * 100:.0f}% del pacchetto consumato.",
                            QSystemTrayIcon.Warning, 8000,
                        )

            if warn_overrun and sim.get("status") == "over":
                key = f"{sim['uuid']}:{cycle}:overrun"
                pr = sim.get("projection") or {}
                if pr.get("exhaustion_date") and key not in self._notified:
                    self._notified.add(key)
                    day = datetime.fromisoformat(
                        pr["exhaustion_date"]).strftime("%d/%m")
                    self.tray.showMessage(
                        f"{label}: giga in esaurimento",
                        f"A questo ritmo finisci i dati il {day}, "
                        f"prima del rinnovo.",
                        QSystemTrayIcon.Warning, 10000,
                    )

    # -- finestra ---------------------------------------------------------

    def _toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            if self.cfg.widget.get("pin_to_desktop", True):
                sink_to_desktop(self)

    def _recenter(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 40, screen.top() + 40)
        self.show()
        self._save_geometry()

    def _restore_geometry(self) -> None:
        pos = None
        if STATE_FILE.exists():
            try:
                pos = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("pos")
            except (json.JSONDecodeError, OSError):
                pos = None
        if not pos:
            pos = [int(self.cfg.widget.get("x", 60)),
                   int(self.cfg.widget.get("y", 60))]

        self.move(pos[0], pos[1])
        # se lo schermo e' cambiato, la posizione salvata puo' essere fuori campo
        screens = QApplication.screens()
        if not any(s.availableGeometry().contains(QPoint(pos[0] + 20, pos[1] + 20))
                   for s in screens):
            self._recenter()

    def _save_geometry(self) -> None:
        try:
            cfgmod.DATA_DIR.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps({"pos": [self.x(), self.y()]}), encoding="utf-8"
            )
        except OSError:
            pass

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._save_geometry()
            if self.cfg.widget.get("pin_to_desktop", True):
                sink_to_desktop(self)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.tray.contextMenu().exec(event.globalPos())


def main() -> int:
    cfg = cfgmod.load()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # vive nella tray anche da nascosta

    win = IliadWidget(cfg)
    win.show()
    if cfg.widget.get("pin_to_desktop", True):
        QTimer.singleShot(200, lambda: sink_to_desktop(win))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
