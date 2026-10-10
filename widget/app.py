"""
Widget desktop dei contatori iliad.

    .venv\\Scripts\\pythonw.exe -m widget.app

Finestra senza bordi con icona nella tray. Il livello si sceglie: sul
desktop (sotto tutto), normale, sempre in primo piano, oppure solo nella tray
(l'icona mostra il consumo, un clic apre il pannello sopra la barra). Aggiorna
da sola all'intervallo di config.toml; click su una scheda = aggiornamento
immediato.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRectF,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
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
# l'icona ha fondo scuro fisso, quindi anche la traccia resta quella scura
DARK_TRACK = theme.DARK.track

# --- Win32 -----------------------------------------------------------------
HWND_TOPMOST, HWND_NOTOPMOST, HWND_BOTTOM = -1, -2, 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x08000000, 0x00000080

# Quattro modi di stare sullo schermo. "desktop" e' il comportamento storico;
# "tray" vive nell'icona e si apre a comando come un pannello di sistema.
LAYERS = ("desktop", "normal", "top", "tray")
LAYER_LABELS = {
    "desktop": "Sul desktop (sotto tutto)",
    "normal": "Finestra normale",
    "top": "Sempre in primo piano",
    "tray": "Nella tray (si apre col clic)",
}
_INSERT_AFTER = {"desktop": HWND_BOTTOM, "normal": HWND_NOTOPMOST,
                 "top": HWND_TOPMOST, "tray": HWND_TOPMOST}


def read_layer(widget_cfg: dict) -> str:
    """Legge window_layer; sui config vecchi ricade su pin_to_desktop."""
    layer = str(widget_cfg.get("window_layer", "")).strip().lower()
    if layer in LAYERS:
        return layer
    return "desktop" if widget_cfg.get("pin_to_desktop", True) else "normal"


def layer_flags(layer: str) -> Qt.WindowFlags:
    flags = Qt.FramelessWindowHint | Qt.Tool
    if layer == "desktop":
        return flags | Qt.WindowStaysOnBottomHint
    if layer in ("top", "tray"):
        return flags | Qt.WindowStaysOnTopHint
    return flags


def _user32():
    """Le funzioni Win32 con le firme giuste: su 64 bit i default troncano."""
    user32 = ctypes.windll.user32
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get_long.restype = ctypes.c_ssize_t
    get_long.argtypes = [ctypes.c_ssize_t, ctypes.c_int]
    set_long.restype = ctypes.c_ssize_t
    set_long.argtypes = [ctypes.c_ssize_t, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowPos.argtypes = [ctypes.c_ssize_t, ctypes.c_ssize_t,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_uint]
    return user32, get_long, set_long


def apply_layer(win: QWidget, layer: str) -> None:
    """
    Mette la finestra al livello scelto.

    Sul desktop le si toglie anche il diritto di attivarsi, cosi' resta come i
    Memo senza mai coprire cio' su cui stai lavorando; negli altri due livelli
    quel diritto le serve, altrimenti non potrebbe nemmeno prendere un clic.
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(win.winId())
        user32, get_long, set_long = _user32()

        style = get_long(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW
        if layer == "desktop":
            style |= WS_EX_NOACTIVATE
        else:
            style &= ~WS_EX_NOACTIVATE
        set_long(hwnd, GWL_EXSTYLE, style)

        user32.SetWindowPos(hwnd, _INSERT_AFTER.get(layer, HWND_NOTOPMOST),
                            0, 0, 0, 0,
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

ICON_FILE = cfgmod.BUNDLE / "assets" / "iliad.ico"
APP_ID = "iliad.counter.widget"


def make_icon(color: str, size: int = 64) -> QIcon:
    """Pallino colorato per la tray: il colore dice lo stato peggiore."""
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


def make_gauge_icon(pct: float | None, color: str, track: str) -> QIcon:
    """
    Icona della tray con l'indicatore: anello di consumo nel colore dello
    stato e la percentuale al centro. Ogni taglia e' disegnata a parte, perche'
    a 16 px un'immagine rimpicciolita non si legge.
    """
    if pct is None:
        return make_icon(color)
    icon = QIcon()
    value = max(0.0, pct)
    text = "!" if value >= 1.0 else f"{value * 100:.0f}"
    for size in (16, 20, 24, 32, 40, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setRenderHint(QPainter.TextAntialiasing)

        thick = max(1.6, size * 0.11)
        rect = QRectF(thick / 2, thick / 2, size - thick, size - thick)
        qp.setPen(Qt.NoPen)
        qp.setBrush(QColor("#14161B"))
        qp.drawEllipse(QRectF(0, 0, size, size))
        qp.setBrush(Qt.NoBrush)
        qp.setPen(QPen(QColor(track), thick, Qt.SolidLine, Qt.FlatCap))
        qp.drawArc(rect, 0, 360 * 16)
        span = min(1.0, value)
        if span > 0.004:
            qp.setPen(QPen(QColor(color), thick, Qt.SolidLine, Qt.FlatCap))
            qp.drawArc(rect, 90 * 16, -int(span * 360 * 16))

        f = QFont()
        f.setPixelSize(max(8, round(size * (0.66 if len(text) == 1 else 0.56))))
        f.setWeight(QFont.Bold)
        if size < 24:
            f.setLetterSpacing(QFont.AbsoluteSpacing, -0.5)
        qp.setFont(f)
        qp.setPen(QColor("#FFFFFF"))
        qp.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, text)
        qp.end()
        icon.addPixmap(pm)
    return icon


def promote_tray_icon() -> None:
    """
    Windows 11 nasconde le icone nuove sotto la freccetta. Chi sceglie la
    modalita' tray la vuole in vista: si segna come promossa la voce che
    Explorer ha gia' creato per questo eseguibile. Solo su scelta esplicita,
    mai a ogni avvio: se poi la si nasconde a mano, resta nascosta.
    """
    if sys.platform != "win32":
        return
    try:
        import winreg

        exe = str(Path(sys.executable).resolve()).lower()
        root = r"Control Panel\NotifyIconSettings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as base:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                access = winreg.KEY_READ | winreg.KEY_SET_VALUE
                with winreg.OpenKey(base, name, 0, access) as key:
                    try:
                        path, _ = winreg.QueryValueEx(key, "ExecutablePath")
                    except OSError:
                        continue
                    # Explorer a volte scrive la cartella come GUID:
                    # {F1B32785-...}\iliad counter\iliad-counter.exe
                    path = str(path).lower()
                    if path == exe or (path.startswith("{") and "}" in path
                                       and exe.endswith(path.split("}", 1)[1])):
                        winreg.SetValueEx(key, "IsPromoted", 0,
                                          winreg.REG_DWORD, 1)
    except OSError:
        pass  # Windows 10 o registro diverso: l'icona resta dove Windows vuole


def app_icon(fallback: str = "#7AA2F7") -> QIcon:
    """L'icona dell'applicazione: assets/iliad.ico, disegnata se manca."""
    if ICON_FILE.exists():
        icon = QIcon(str(ICON_FILE))
        if not icon.isNull():
            return icon
    return make_icon(fallback)


def register_app_id() -> None:
    """
    Senza AppUserModelID Windows attribuisce finestre, notifiche e collegamento
    al processo python.exe, e l'icona che si vede e' la sua.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (OSError, AttributeError):
        pass


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
        self.layer = read_layer(cfg.widget)
        self._layer_actions: dict[str, QAction] = {}
        self._popup_closed_at = 0.0

        self.setWindowFlags(layer_flags(self.layer))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowIcon(app_icon(self.p.accent))
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
        # solo in modalita' tray: il pannello si chiude come si e' aperto
        self.btn_close = QPushButton("✕", self.panel)
        self.btn_close.setObjectName("iconBtn")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setToolTip("Chiudi (resta nella tray)")
        self.btn_close.clicked.connect(self._hide_popup)
        self.btn_close.setVisible(self.layer == "tray")

        head.addWidget(self.brand)
        head.addWidget(self.company, 1)
        head.addWidget(self.btn_refresh)
        head.addWidget(self.btn_menu)
        head.addWidget(self.btn_close)
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

        # il livello si cambia da qui senza aprire le impostazioni
        pos_menu = menu.addMenu("Posizione")
        group = QActionGroup(self)
        group.setExclusive(True)
        for key in LAYERS:
            act = QAction(LAYER_LABELS[key], self)
            act.setCheckable(True)
            act.setChecked(key == self.layer)
            act.triggered.connect(lambda _checked, k=key: self.set_layer(k))
            group.addAction(act)
            pos_menu.addAction(act)
            self._layer_actions[key] = act

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
        if self.layer == "tray":
            self.tray.setToolTip("iliad counter · clic per aprire")

    def _show_menu(self) -> None:
        self.btn_menu.setMenu(None)
        self.tray.contextMenu().exec(
            self.btn_menu.mapToGlobal(QPoint(0, self.btn_menu.height()))
        )

    def open_settings(self) -> None:
        if self._settings is None:
            dlg = SettingsDialog(self.cfg, self.p)
            dlg.setWindowIcon(app_icon(self.p.accent))
            dlg.credentials_saved.connect(self.refresh)
            dlg.refresh_changed.connect(
                lambda m: self.timer.setInterval(max(5, m) * 60_000)
            )
            dlg.layer_changed.connect(self.set_layer)
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
        self.tray.setIcon(make_gauge_icon(self._top_pct(snap),
                                          self.p.status(worst), DARK_TRACK))
        self.tray.setToolTip(self._tray_text(snap))
        self.footer.setText(
            f"{'dato salvato' if from_cache else 'aggiornato'} alle {stamp}"
        )

        self.adjustSize()
        self.panel.adjustSize()
        if self.layer == "tray":
            if self.isVisible():
                self._place_popup()   # e' cresciuto: non deve finire sotto la barra
        else:
            self._reassert_layer()
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
    def _top_pct(snap: dict) -> float | None:
        """La SIM piu' consumata decide il numero sull'icona."""
        found = [(s.get("data") or {}).get("pct") for s in snap.get("sims", [])]
        found = [p for p in found if p is not None]
        return max(found) if found else None

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

    def set_layer(self, layer: str, persist: bool = True) -> None:
        """
        Cambia livello a caldo. Qt ricrea la finestra quando cambiano i flag,
        quindi posizione e visibilita' vanno rimesse a mano e lo stile Win32
        riapplicato al nuovo handle.
        """
        if layer not in LAYERS or layer == self.layer:
            return
        leaving_tray = self.layer == "tray"
        self.layer = layer
        was_visible = self.isVisible()
        pos = self.pos()

        self.setWindowFlags(layer_flags(layer))
        self.btn_close.setVisible(layer == "tray")
        if layer == "tray":
            # da qui in poi vive nell'icona: niente pannello finche' non lo chiedi
            self.hide()
            promote_tray_icon()
        elif leaving_tray:
            # torna dove l'avevi lasciato prima di passare alla tray
            self._restore_geometry()
            self.show()
        else:
            self.move(pos)
            if was_visible:
                self.show()

        act = self._layer_actions.get(layer)
        if act is not None and not act.isChecked():
            act.setChecked(True)

        self.cfg.widget["window_layer"] = layer
        self.cfg.widget["pin_to_desktop"] = layer == "desktop"
        if persist:
            cfgmod.set_widget_key("window_layer", layer)
            # allineata anche la chiave vecchia: un config che si contraddice
            # e' peggio di un config con una chiave in piu'
            cfgmod.set_widget_key("pin_to_desktop", layer == "desktop")

        QTimer.singleShot(0, lambda: apply_layer(self, self.layer))

    def _reassert_layer(self) -> None:
        """
        Dopo un aggiornamento o un trascinamento il livello va riaffermato, ma
        solo dove serve: su "normal" un SetWindowPos la tirerebbe davanti alle
        altre finestre a ogni giro.
        """
        if self.layer != "normal":
            apply_layer(self, self.layer)

    def _toggle_visible(self) -> None:
        if self.layer == "tray":
            self._toggle_popup()
        elif self.isVisible():
            self.hide()
        else:
            self.show()
            apply_layer(self, self.layer)

    # -- pannello della tray ------------------------------------------------

    def _toggle_popup(self) -> None:
        if self.isVisible():
            self._hide_popup()
        # il clic sull'icona ha appena tolto il fuoco al pannello e l'ha
        # chiuso: senza questa pausa lo riaprirebbe subito
        elif time.monotonic() - self._popup_closed_at > 0.35:
            self._show_popup()

    def _show_popup(self) -> None:
        self._place_popup()
        self.show()
        self.raise_()
        self.activateWindow()
        apply_layer(self, self.layer)

    def _hide_popup(self) -> None:
        if self.isVisible():
            self._popup_closed_at = time.monotonic()
            self.hide()

    def _place_popup(self) -> None:
        """Sopra la barra delle applicazioni, vicino all'icona, come i flyout."""
        self.adjustSize()
        geo = self.tray.geometry()
        anchor = geo.center() if geo.isValid() and not geo.isEmpty() else QCursor.pos()
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        full, avail = screen.geometry(), screen.availableGeometry()
        w, h, m = self.width(), self.height(), 12

        x = anchor.x() - w // 2
        y = avail.bottom() - h - m
        if avail.top() > full.top():            # barra in alto
            y = avail.top() + m
        if avail.left() > full.left():          # barra a sinistra
            x, y = avail.left() + m, anchor.y() - h // 2
        elif avail.right() < full.right():      # barra a destra
            x, y = avail.right() - w - m, anchor.y() - h // 2

        x = max(avail.left() + m, min(x, avail.right() - w - m))
        y = max(avail.top() + m, min(y, avail.bottom() - h - m))
        self.move(x, y)

    def _maybe_autoclose(self) -> None:
        """Clic altrove = pannello chiuso, ma non mentre e' aperto il suo menu."""
        if (self.layer == "tray" and self.isVisible()
                and not self.isActiveWindow()
                and QApplication.activePopupWidget() is None):
            self._hide_popup()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            QTimer.singleShot(120, self._maybe_autoclose)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.layer == "tray" and event.key() == Qt.Key_Escape:
            self._hide_popup()
        else:
            super().keyPressEvent(event)

    def _recenter(self) -> None:
        if self.layer == "tray":
            self._show_popup()
            return
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 40, screen.top() + 40)
        self.show()
        apply_layer(self, self.layer)
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
        # il pannello della tray ha il suo posto fisso: non si trascina
        if event.button() == Qt.LeftButton and self.layer != "tray":
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag = None
            self._save_geometry()
            self._reassert_layer()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.tray.contextMenu().exec(event.globalPos())


def main() -> int:
    cfg = cfgmod.load()
    register_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("iliad counter")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)   # vive nella tray anche da nascosta

    win = IliadWidget(cfg)
    if win.layer != "tray":         # in tray si parte solo con l'icona
        win.show()
        QTimer.singleShot(200, lambda: apply_layer(win, win.layer))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
