"""
Componenti grafici del widget.

L'idea portante dell'anello: l'arco mostra il consumo, una tacca sullo stesso
anello mostra quanto ciclo e' passato. Sulla stessa scala, quindi si legge in
un colpo d'occhio: arco oltre la tacca = stai correndo piu' del mese.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.cycle import fmt_days_left, fmt_gb
from widget.theme import Palette

RING = 62
RING_THICK = 7.0
PACE_THICK = 2.6


class RingGauge(QWidget):
    """Consumo come arco, avanzamento del ciclo come tacca sullo stesso anello."""

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.p = palette
        self.pct: float | None = None
        self.pace: float | None = None
        self.color = palette.idle
        self.center_text = "—"
        self.setFixedSize(RING, RING)

    def set_values(self, pct: float | None, pace: float | None,
                   color: str, center: str) -> None:
        self.pct, self.pace, self.color, self.center_text = pct, pace, color, center
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802  (API Qt)
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)

        pad = RING_THICK / 2 + 2.5
        outer = QRectF(pad, pad, RING - 2 * pad, RING - 2 * pad)

        qp.setPen(QPen(QColor(self.p.track), RING_THICK, Qt.SolidLine, Qt.FlatCap))
        qp.drawArc(outer, 0, 360 * 16)

        if self.pct is not None:
            span = max(0.0, min(1.0, self.pct))
            qp.setPen(QPen(QColor(self.color), RING_THICK, Qt.SolidLine, Qt.RoundCap))
            if span > 0.004:
                qp.drawArc(outer, 90 * 16, -int(span * 360 * 16))

        # tacca del ritmo: dove dovresti essere se consumassi in modo uniforme
        if self.pace is not None:
            self._draw_pace_tick(qp, outer.center(), outer.width() / 2)

        f = QFont(self.font())
        f.setPointSizeF(12.5)
        f.setWeight(QFont.DemiBold)
        qp.setFont(f)
        qp.setPen(QColor(self.p.text))
        qp.drawText(self.rect(), Qt.AlignCenter, self.center_text)
        qp.end()

    def _draw_pace_tick(self, qp: QPainter, center, radius: float) -> None:
        angle = math.radians(90.0 - max(0.0, min(1.0, self.pace)) * 360.0)
        dx, dy = math.cos(angle), -math.sin(angle)
        r_in = radius - RING_THICK / 2 - 1.5
        r_out = radius + RING_THICK / 2 + 1.5
        qp.setPen(QPen(QColor(self.p.text), PACE_THICK, Qt.SolidLine, Qt.RoundCap))
        qp.drawLine(
            QPointF(center.x() + dx * r_in, center.y() + dy * r_in),
            QPointF(center.x() + dx * r_out, center.y() + dy * r_out),
        )


class SimCard(QFrame):
    """Una scheda per SIM. Cliccando si chiede un aggiornamento."""

    clicked = Signal()

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.p = palette
        self.setObjectName("simCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.ring = RingGauge(palette, self)

        self.title = QLabel("—", self)
        self.title.setObjectName("cardTitle")
        self.subtitle = QLabel("", self)
        self.subtitle.setObjectName("cardSub")
        self.primary = QLabel("", self)
        self.primary.setObjectName("cardPrimary")
        self.detail = QLabel("", self)
        self.detail.setObjectName("cardDetail")
        self.detail2 = QLabel("", self)
        self.detail2.setObjectName("cardDetail")
        self.alert = QLabel("", self)
        self.alert.setObjectName("cardAlert")
        self.alert.setWordWrap(True)
        self.alert.hide()

        from PySide6.QtWidgets import QHBoxLayout

        text = QVBoxLayout()
        text.setSpacing(1)
        text.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.subtitle)
        text.addLayout(head)
        text.addWidget(self.primary)
        text.addWidget(self.detail)
        text.addWidget(self.detail2)
        text.addWidget(self.alert)

        row = QHBoxLayout(self)
        row.setContentsMargins(13, 11, 13, 11)
        row.setSpacing(12)
        row.addWidget(self.ring, 0, Qt.AlignTop)
        row.addLayout(text, 1)

    # -- contenuto --------------------------------------------------------

    def update_from(self, sim: dict) -> None:
        status = sim.get("status", "unknown")
        color = self.p.status(status)

        self.title.setText(sim.get("label") or "SIM")
        self.subtitle.setText(sim.get("msisdn_short") or "")
        self.alert.hide()
        self.alert.setStyleSheet(f"color: {color};")

        if status == "inactive":
            self.ring.set_values(None, None, self.p.idle, "—")
            self.primary.setText("non attiva")
            self.primary.setStyleSheet(f"color: {self.p.faint};")
            self.detail.setText(sim.get("plan_name") or "—")
            self.detail2.setText(sim.get("note") or "")
            return
        self.primary.setStyleSheet("")

        if sim.get("error"):
            self.ring.set_values(None, None, self.p.over, "!")
            self.primary.setText("dati non disponibili")
            self.detail.setText(str(sim["error"])[:70])
            self.detail2.clear()
            return

        d = sim.get("data") or {}
        used, limit, pct = d.get("used"), d.get("limit"), d.get("pct")
        cyc = sim.get("cycle") or {}
        pr = sim.get("projection") or {}

        self.ring.set_values(
            pct, cyc.get("progress"), color,
            f"{pct * 100:.0f}%" if pct is not None else "—",
        )

        self.primary.setText(f"{fmt_gb(used)} / {fmt_gb(limit)} GB")

        # riga 1: il ritmo. riga 2: il calendario. Righe fisse, mai a capo.
        pace_bits: list[str] = []
        if pr.get("per_day_gb") is not None:
            pace_bits.append(f"ritmo {fmt_gb(pr['per_day_gb'])} GB/g")
        if pr.get("safe_per_day_gb") is not None:
            pace_bits.append(f"puoi {fmt_gb(pr['safe_per_day_gb'])}")
        self.detail.setText("  ·  ".join(pace_bits))

        cal_bits: list[str] = []
        if cyc.get("end"):
            from datetime import date as _date
            cal_bits.append("rinnovo "
                            + _date.fromisoformat(cyc["end"]).strftime("%d/%m"))
        if cyc.get("days_left") is not None:
            cal_bits.append(f"fra {fmt_days_left(cyc['days_left'])}")
        self.detail2.setText("  ·  ".join(cal_bits))

        # il messaggio che conta davvero, solo quando c'e' qualcosa da dire
        msg = ""
        if pr.get("exhaustion_date"):
            from datetime import datetime as _dt
            day = _dt.fromisoformat(pr["exhaustion_date"]).strftime("%d/%m")
            msg = f"finisci i GB il {day}"
        elif status == "over" and used is not None and limit and used >= limit:
            msg = "pacchetto dati esaurito"
        elif status == "warn":
            msg = f"in rotta per {fmt_gb(pr.get('projected_gb'))} GB"
        if sim.get("extra_cost_eur"):
            extra = f"extra soglia {sim['extra_cost_eur']:.2f} €"
            msg = f"{msg} · {extra}" if msg else extra
        if msg:
            self.alert.setText(msg)
            self.alert.show()

    # -- interazione ------------------------------------------------------

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class RoundedPanel(QFrame):
    """Sfondo arrotondato con ombra dipinta a mano: niente bordi di sistema."""

    def __init__(self, palette: Palette, radius: int = 14,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.p = palette
        self.radius = radius

    def paintEvent(self, _event) -> None:  # noqa: N802
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                            self.radius, self.radius)
        qp.fillPath(path, QColor(self.p.bg))
        qp.setPen(QPen(QColor(self.p.divider), 1))
        qp.drawPath(path)
        qp.end()
