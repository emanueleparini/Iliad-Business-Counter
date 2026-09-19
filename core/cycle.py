"""
Matematica del ciclo di fatturazione e proiezione dei consumi.

Nessuna dipendenza dal portale: qui si ragiona solo su date e numeri, cosi'
questa parte resta valida anche se domani iliad cambia il sito da cima a fondo.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

Status = Literal["ok", "warn", "over", "unknown"]


def _clamp_day(year: int, month: int, day: int) -> date:
    """Il giorno 31 in un mese da 30 diventa il 30: il rinnovo non salta un mese."""
    return date(year, month, min(day, monthrange(year, month)[1]))


def _shift_month(d: date, months: int) -> tuple[int, int]:
    total = d.year * 12 + (d.month - 1) + months
    return total // 12, total % 12 + 1


def cycle_bounds(renewal_day: int, today: date) -> tuple[date, date]:
    """
    Inizio (incluso) e fine (escluso) del ciclo corrente.

    Il ciclo che si rinnova il 4 e osservato il 19 settembre va dal 4 settembre
    al 4 ottobre. Osservato il 2 settembre, va dal 4 agosto al 4 settembre.
    """
    if not 1 <= renewal_day <= 31:
        raise ValueError(f"renewal_day fuori range: {renewal_day}")

    this_month = _clamp_day(today.year, today.month, renewal_day)
    if today >= this_month:
        start = this_month
        end = _clamp_day(*_shift_month(today, 1), renewal_day)
    else:
        start = _clamp_day(*_shift_month(today, -1), renewal_day)
        end = this_month
    return start, end


@dataclass(frozen=True)
class CycleState:
    start: date
    end: date
    days_total: int
    days_elapsed: float      # frazionario: a meta' giornata vale 0.5
    days_left: float
    progress: float          # 0..1, quanto ciclo e' passato


def cycle_state(renewal_day: int, now: datetime) -> CycleState:
    start, end = cycle_bounds(renewal_day, now.date())
    days_total = (end - start).days
    elapsed = (now - datetime.combine(start, datetime.min.time(),
                                      tzinfo=now.tzinfo)).total_seconds() / 86_400
    elapsed = max(0.0, min(float(days_total), elapsed))
    return CycleState(
        start=start,
        end=end,
        days_total=days_total,
        days_elapsed=elapsed,
        days_left=days_total - elapsed,
        progress=elapsed / days_total if days_total else 0.0,
    )


@dataclass(frozen=True)
class Projection:
    used_gb: float
    allowance_gb: float | None
    used_pct: float | None       # 0..1
    per_day_gb: float            # ritmo medio finora
    budget_per_day_gb: float | None   # ritmo sostenibile per arrivare a fine ciclo
    projected_gb: float          # consumo stimato a fine ciclo, al ritmo attuale
    projected_pct: float | None
    remaining_gb: float | None
    safe_per_day_gb: float | None     # quanto puoi consumare/giorno da qui in poi
    exhaustion_date: date | None      # quando finiresti i GB, al ritmo attuale
    status: Status


def project(
    used_gb: float,
    allowance_gb: float | None,
    cyc: CycleState,
    *,
    warn_ratio: float = 1.0,
    over_ratio: float = 1.15,
) -> Projection:
    """
    Proiezione lineare del consumo a fine ciclo.

    `warn_ratio` / `over_ratio` sono rapporti fra consumo proiettato e soglia:
    sopra 1.0 si e' in rotta per sforare, sopra 1.15 lo sforamento e' netto.
    """
    # Sotto le 6 ore di ciclo il ritmo medio e' rumore puro: non proiettare.
    reliable = cyc.days_elapsed >= 0.25
    per_day = used_gb / cyc.days_elapsed if reliable and cyc.days_elapsed else 0.0
    projected = per_day * cyc.days_total if reliable else used_gb

    used_pct = projected_pct = remaining = safe_per_day = budget_per_day = None
    exhaustion: date | None = None
    status: Status = "unknown"

    if allowance_gb and allowance_gb > 0:
        used_pct = used_gb / allowance_gb
        projected_pct = projected / allowance_gb
        remaining = max(0.0, allowance_gb - used_gb)
        budget_per_day = allowance_gb / cyc.days_total if cyc.days_total else None
        safe_per_day = remaining / cyc.days_left if cyc.days_left > 0 else None

        if used_gb >= allowance_gb:
            status = "over"
        elif not reliable:
            status = "ok"
        elif projected_pct >= over_ratio:
            status = "over"
        elif projected_pct >= warn_ratio:
            status = "warn"
        else:
            status = "ok"

        if reliable and per_day > 0 and remaining > 0:
            days_to_zero = remaining / per_day
            if days_to_zero <= cyc.days_left:
                exhaustion = cyc.start + timedelta(
                    days=int(cyc.days_elapsed + days_to_zero)
                )

    return Projection(
        used_gb=used_gb,
        allowance_gb=allowance_gb,
        used_pct=used_pct,
        per_day_gb=per_day,
        budget_per_day_gb=budget_per_day,
        projected_gb=projected,
        projected_pct=projected_pct,
        remaining_gb=remaining,
        safe_per_day_gb=safe_per_day,
        exhaustion_date=exhaustion,
        status=status,
    )


def fmt_gb(x: float | None) -> str:
    if x is None:
        return "—"
    if x >= 100:
        return f"{x:,.0f}".replace(",", ".")
    if x >= 10:
        return f"{x:.1f}".replace(".", ",")
    return f"{x:.2f}".replace(".", ",")


def fmt_days_left(days: float) -> str:
    d = int(days)
    if d <= 0:
        h = max(0, int(days * 24))
        return f"{h} h" if h else "oggi"
    return "1 giorno" if d == 1 else f"{d} giorni"


def cycle_state_from_dates(start: date, end: date, now: datetime) -> CycleState:
    """
    Variante preferita: il portale espone le date reali del periodo
    (reference_period.offer_start_date / offer_end_date), quindi non serve
    dedurle dal giorno di rinnovo configurato.
    """
    days_total = (end - start).days
    if days_total <= 0:
        raise ValueError(f"periodo non valido: {start} -> {end}")
    elapsed = (now - datetime.combine(start, datetime.min.time(),
                                      tzinfo=now.tzinfo)).total_seconds() / 86_400
    elapsed = max(0.0, min(float(days_total), elapsed))
    return CycleState(
        start=start,
        end=end,
        days_total=days_total,
        days_elapsed=elapsed,
        days_left=days_total - elapsed,
        progress=elapsed / days_total,
    )
