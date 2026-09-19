"""
Pannello impostazioni del widget: credenziali, avvio automatico, frequenza.

Tutto quello che prima si faceva da riga di comando si fa qui dentro.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

import keyring

from core import config as cfgmod
from core.api import SERVICE, IliadClient, save_credentials
from install import autostart
from widget.theme import Palette

_USERNAME_SLOT = "__username__"


class _LoginSignals(QObject):
    ok = Signal(str)        # nome azienda
    fail = Signal(str)


class LoginTest(QRunnable):
    """Verifica le credenziali prima di salvarle, senza bloccare la finestra."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        super().__init__()
        self.base_url, self.username, self.password = base_url, username, password
        self.signals = _LoginSignals()

    def run(self) -> None:
        try:
            client = IliadClient(self.base_url)
            me = client.login(self.username, self.password)
            companies = me.get("companies") or []
            self.signals.ok.emit(companies[0].get("legalName", "") if companies else "")
        except Exception as exc:
            self.signals.fail.emit(str(exc))


class SettingsDialog(QDialog):
    credentials_saved = Signal()
    refresh_changed = Signal(int)

    def __init__(self, cfg, palette: Palette) -> None:
        # senza parent: il widget principale non puo' ricevere il fuoco,
        # questa finestra invece deve poterlo prendere per far digitare
        super().__init__(None)
        self.cfg = cfg
        self.p = palette
        self.pool = QThreadPool.globalInstance()

        self.setWindowTitle("iliad counter — Impostazioni")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setFixedWidth(380)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # -- accesso ------------------------------------------------------
        root.addWidget(self._section("Accesso all'area personale"))

        self.user = QLineEdit(self)
        self.user.setPlaceholderText("ID utente (il codice numerico)")
        self.pwd = QLineEdit(self)
        self.pwd.setPlaceholderText("Password")
        self.pwd.setEchoMode(QLineEdit.Password)
        self.pwd.returnPressed.connect(self._save_credentials)
        root.addWidget(self.user)
        root.addWidget(self.pwd)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        self.status.setObjectName("status")
        root.addWidget(self.status)

        self.btn_save = QPushButton("Verifica e salva", self)
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self._save_credentials)
        root.addWidget(self.btn_save)

        root.addWidget(self._divider())

        # -- avvio --------------------------------------------------------
        root.addWidget(self._section("Avvio"))

        self.chk_autostart = QCheckBox("Avvia con Windows", self)
        self.chk_autostart.setChecked(autostart.is_enabled())
        self.chk_autostart.toggled.connect(self._toggle_autostart)
        root.addWidget(self.chk_autostart)

        self.chk_desktop = QPushButton("Crea icona sul desktop", self)
        self.chk_desktop.clicked.connect(self._make_desktop_icon)
        root.addWidget(self.chk_desktop)

        root.addWidget(self._divider())

        # -- frequenza ----------------------------------------------------
        root.addWidget(self._section("Aggiornamento"))

        freq = QHBoxLayout()
        freq.addWidget(QLabel("Aggiorna ogni", self))
        self.spin = QSpinBox(self)
        self.spin.setRange(5, 720)
        self.spin.setSingleStep(5)
        self.spin.setSuffix(" min")
        self.spin.setValue(int(cfg.refresh_minutes))
        self.spin.valueChanged.connect(self._change_refresh)
        freq.addWidget(self.spin)
        freq.addStretch(1)
        root.addLayout(freq)

        btn_close = QPushButton("Chiudi", self)
        btn_close.clicked.connect(self.accept)
        root.addWidget(btn_close)

        self._apply_style()
        self._load_existing()

    # -- helper visivi ----------------------------------------------------

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text, self)
        lab.setObjectName("section")
        return lab

    def _divider(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("divider")
        return line

    def _apply_style(self) -> None:
        p = self.p
        self.setStyleSheet(f"""
            QDialog {{ background: {p.bg}; }}
            QLabel {{ color: {p.text}; font-size: 12px; }}
            #section {{ color: {p.accent}; font-size: 11px; font-weight: 700; }}
            #status {{ color: {p.muted}; font-size: 11px; }}
            #divider {{ color: {p.divider}; }}
            QLineEdit, QSpinBox {{
                background: {p.card}; color: {p.text}; border: 1px solid {p.divider};
                border-radius: 6px; padding: 7px 9px; font-size: 12px;
            }}
            QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {p.accent}; }}
            QCheckBox {{ color: {p.text}; font-size: 12px; }}
            QPushButton {{
                background: {p.card}; color: {p.text}; border: 1px solid {p.divider};
                border-radius: 6px; padding: 7px 12px; font-size: 12px;
            }}
            QPushButton:hover {{ background: {p.card_hover}; }}
            #primaryBtn {{ background: {p.accent}; color: #FFFFFF;
                           border: none; font-weight: 600; }}
            #primaryBtn:hover {{ background: {p.accent}; }}
        """)

    # -- logica -----------------------------------------------------------

    def _load_existing(self) -> None:
        saved = keyring.get_password(SERVICE, _USERNAME_SLOT)
        if saved:
            self.user.setText(saved)
            self.pwd.setPlaceholderText("Password (già salvata — lascia vuoto)")
            self._say(f"Credenziali salvate per l'utente {saved}.", ok=True)
        else:
            self._say("Inserisci ID utente e password per iniziare.")
            self.user.setFocus()

    def _say(self, text: str, ok: bool | None = None) -> None:
        color = self.p.muted if ok is None else (self.p.ok if ok else self.p.over)
        self.status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.status.setText(text)

    def _save_credentials(self) -> None:
        username = self.user.text().strip()
        password = self.pwd.text()
        if not username:
            self._say("Serve l'ID utente.", ok=False)
            return
        if not password:
            self._say("Serve la password.", ok=False)
            return

        self.btn_save.setEnabled(False)
        self._say("Verifico l'accesso…")

        task = LoginTest(self.cfg.base_url, username, password)
        task.signals.ok.connect(lambda company: self._on_login_ok(
            username, password, company))
        task.signals.fail.connect(self._on_login_fail)
        self.pool.start(task)

    def _on_login_ok(self, username: str, password: str, company: str) -> None:
        save_credentials(username, password)
        self.btn_save.setEnabled(True)
        self.pwd.clear()
        self.pwd.setPlaceholderText("Password (già salvata — lascia vuoto)")
        self._say(f"Accesso riuscito{' — ' + company if company else ''}. "
                  "Credenziali salvate nel Credential Manager.", ok=True)
        self.credentials_saved.emit()

    def _on_login_fail(self, message: str) -> None:
        self.btn_save.setEnabled(True)
        self._say(f"Accesso fallito: {message}", ok=False)

    def _toggle_autostart(self, checked: bool) -> None:
        actual = autostart.set_enabled(checked)
        if actual != checked:
            self.chk_autostart.blockSignals(True)
            self.chk_autostart.setChecked(actual)
            self.chk_autostart.blockSignals(False)
            self._say("Non riesco a creare il collegamento di avvio.", ok=False)
        else:
            self._say("Partirà con Windows." if actual
                      else "Non partirà più da solo.", ok=True)

    def _make_desktop_icon(self) -> None:
        lnk = autostart.create_desktop_shortcut()
        self._say(f"Icona creata: {lnk.name}" if lnk
                  else "Creazione icona fallita.", ok=bool(lnk))

    def _change_refresh(self, minutes: int) -> None:
        if cfgmod.set_refresh_minutes(minutes):
            self.cfg.refresh_minutes = minutes
            self.refresh_changed.emit(minutes)
        else:
            self._say("Non riesco a scrivere config.toml.", ok=False)
