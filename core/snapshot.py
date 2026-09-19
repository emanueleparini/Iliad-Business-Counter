"""
Da risposte grezze dell'API a uno snapshot pronto per il widget.

Lo snapshot e' un dizionario JSON-serializzabile: il widget non sa nulla di
iliad, legge solo questo. Se domani cambia l'API, cambia solo questo file.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.api import IliadClient, Line
from core.config import Config, SimConfig
from core.cycle import CycleState, cycle_state, cycle_state_from_dates, project
from core.parse import parse_count, parse_data_gb, parse_euro, parse_minutes

SCHEMA_VERSION = 1


def _date(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _num(x: float | None) -> float | None:
    """inf non e' JSON valido: diventa None con un flag a parte."""
    if x is None or math.isinf(x) or math.isnan(x):
        return None
    return round(x, 4)


def _bucket(used_raw, limit_raw, parser) -> dict:
    used = parser(used_raw)
    limit = parser(limit_raw)
    unlimited = limit is not None and math.isinf(limit)
    pct = None
    if used is not None and limit and not unlimited and limit > 0:
        pct = round(used / limit, 4)
    return {
        "used": _num(used),
        "limit": _num(limit),
        "unlimited": unlimited,
        "pct": pct,
    }


def _resolve_cycle(counters: dict, info: dict, cfg: SimConfig | None,
                   now: datetime) -> tuple[CycleState | None, str]:
    """
    Le date del periodo arrivano dal portale; si ricade sul giorno di rinnovo
    configurato solo se l'API non le espone.
    """
    ref = counters.get("reference_period") or {}
    start, end = _date(ref.get("offer_start_date")), _date(ref.get("offer_end_date"))
    if start and end and end > start:
        return cycle_state_from_dates(start, end, now), "portale"

    renewal = _date(info.get("renewalDate"))
    if renewal:
        try:
            return cycle_state(renewal.day, now), "renewalDate"
        except ValueError:
            pass

    if cfg and cfg.renewal_day:
        try:
            return cycle_state(cfg.renewal_day, now), "config"
        except ValueError:
            pass
    return None, "sconosciuto"


def build_sim(client: IliadClient, line: Line, cfg: SimConfig | None,
              now: datetime) -> dict:
    """Uno snapshot per SIM. Non solleva: gli errori finiscono nel campo `error`."""
    entry: dict[str, Any] = {
        "uuid": line.uuid,
        "id": cfg.id if cfg else line.uuid[:8],
        "label": (cfg.label if cfg else None) or line.name or line.short_msisdn,
        "msisdn_short": line.short_msisdn,
        "plan_name": line.plan_name,
        "state": line.state,
        "active": line.is_active,
        "activatable": line.activatable,
        "error": None,
    }

    if not line.is_active:
        # SIM non attiva: nessun contatore da leggere, e va detto chiaramente.
        entry["status"] = "inactive"
        entry["note"] = "da attivare" if line.activatable else line.state
        return entry

    try:
        counters = client.line_counters(line.uuid)
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)
        return entry

    try:
        info = client.line_info(line.uuid)
    except Exception:
        info = {}

    nat = counters.get("national_data") or {}
    abroad = counters.get("abroad_data") or {}

    data = _bucket(nat.get("counter_data_nat"),
                   nat.get("counter_data_nat_limit"), parse_data_gb)

    # soglia dal portale, con override manuale solo se il portale tace
    limit_gb = data["limit"]
    if not limit_gb and cfg and cfg.data_allowance_gb > 0:
        limit_gb = cfg.data_allowance_gb
        data["limit"] = limit_gb
        if data["used"] is not None and limit_gb:
            data["pct"] = round(data["used"] / limit_gb, 4)

    cyc, cycle_source = _resolve_cycle(counters, info, cfg, now)

    entry["data"] = data
    entry["voice_nat"] = _bucket(nat.get("counter_voice_nat"),
                                 nat.get("counter_voice_nat_limit"), parse_minutes)
    entry["voice_int"] = _bucket(nat.get("counter_voice_int"),
                                 nat.get("counter_voice_int_limit"), parse_minutes)
    entry["sms_nat"] = _bucket(nat.get("counter_sms_nat"),
                               nat.get("counter_sms_nat_limit"), parse_count)
    entry["data_eu"] = _bucket(abroad.get("counter_data_europe"),
                               abroad.get("counter_data_europe_limit"), parse_data_gb)
    entry["data_world"] = _bucket(abroad.get("counter_data_no_europe"),
                                  abroad.get("counter_data_no_europe_limit"),
                                  parse_data_gb)

    extra = sum(
        v for v in (
            parse_euro(nat.get("counter_voice_over_threshold")),
            parse_euro(nat.get("counter_sms_over_threshold")),
            parse_euro(nat.get("counter_data_over_threshold")),
            parse_euro(abroad.get("counter_voice_over_threshold")),
            parse_euro(abroad.get("counter_sms_over_threshold")),
            parse_euro(abroad.get("counter_data_over_threshold")),
        ) if v
    )
    entry["extra_cost_eur"] = round(extra, 2)
    entry["credit_eur"] = parse_euro(counters.get("credit")) or 0.0

    if cyc:
        entry["cycle"] = {
            "start": cyc.start.isoformat(),
            "end": cyc.end.isoformat(),
            "days_total": cyc.days_total,
            "days_elapsed": round(cyc.days_elapsed, 3),
            "days_left": round(cyc.days_left, 3),
            "progress": round(cyc.progress, 4),
            "source": cycle_source,
        }
        used = data["used"] or 0.0
        pr = project(used, limit_gb, cyc)
        entry["projection"] = {
            "per_day_gb": _num(pr.per_day_gb),
            "budget_per_day_gb": _num(pr.budget_per_day_gb),
            "projected_gb": _num(pr.projected_gb),
            "projected_pct": _num(pr.projected_pct),
            "remaining_gb": _num(pr.remaining_gb),
            "safe_per_day_gb": _num(pr.safe_per_day_gb),
            "exhaustion_date": pr.exhaustion_date.isoformat()
            if pr.exhaustion_date else None,
        }
        entry["status"] = pr.status
    else:
        entry["cycle"] = None
        entry["projection"] = None
        entry["status"] = "unknown"

    return entry


def build(client: IliadClient, config: Config,
          now: datetime | None = None) -> dict:
    """Snapshot completo. Le SIM in config danno etichette e ordine."""
    tz = ZoneInfo(config.timezone)
    now = now or datetime.now(tz)

    snap: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "ok": False,
        "error": None,
        "company": None,
        "sims": [],
    }

    try:
        me = client.me(refresh=True)
    except Exception as exc:
        snap["error"] = f"Accesso fallito: {exc}"
        return snap

    companies = me.get("companies") or []
    snap["company"] = companies[0].get("legalName") if companies else None

    try:
        lines = client.lines()
    except Exception as exc:
        snap["error"] = f"Elenco SIM non disponibile: {exc}"
        return snap

    # ordine: prima quelle elencate in config, poi eventuali SIM nuove
    order = {s.uuid: i for i, s in enumerate(config.sims)}
    lines.sort(key=lambda ln: (order.get(ln.uuid, 10_000), ln.msisdn or ""))

    for line in lines:
        cfg = config.sim_by_uuid(line.uuid)
        if cfg and not cfg.enabled and not line.is_active:
            # disattivata in config e inattiva davvero: la mostriamo comunque,
            # ma senza tentare chiamate inutili
            pass
        snap["sims"].append(build_sim(client, line, cfg, now))

    snap["ok"] = any(s.get("error") is None for s in snap["sims"])
    return snap
