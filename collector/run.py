"""
Collector: interroga l'API iliad, scrive data/latest.json e lo storico.

    python -m collector.run                # un giro solo, con riepilogo a schermo
    python -m collector.run --watch        # gira all'infinito all'intervallo di config
    python -m collector.run --json         # stampa lo snapshot grezzo
    python -m collector.run --import-session   # riusa il cookie del browser di recon
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import keyring

from core import config as cfgmod
from core import store
from core.api import SERVICE, AuthError, IliadClient
from core.cycle import fmt_days_left, fmt_gb
from core.snapshot import build

_COOKIE_SLOT = "__session_cookie__"

# La console di Windows e' cp1252 e soffoca su barre di avanzamento ed euro.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

BAR_W = 22
GLYPH = {"ok": "●", "warn": "◐", "over": "●",
         "inactive": "○", "error": "✕", "unknown": "○"}


def import_recon_session() -> int:
    """Bootstrap comodo: prende ACC_SESSID dal profilo usato per la ricognizione."""
    state = Path(__file__).resolve().parent.parent / "recon/artifacts/storage_state.json"
    if not state.exists():
        print("Nessuno storage_state.json: esegui prima recon/recon.py.")
        return 1
    data = json.loads(state.read_text(encoding="utf-8"))
    for c in data.get("cookies", []):
        if c.get("name") == "ACC_SESSID":
            keyring.set_password(SERVICE, _COOKIE_SLOT, c["value"])
            print("Cookie di sessione importato nel Credential Manager.")
            print("Nota: scade in fretta. Per l'uso continuativo servono le")
            print("credenziali: python -m core.setup_credentials")
            return 0
    print("ACC_SESSID non trovato nello storage_state.")
    return 1


def bar(pct: float | None, width: int = BAR_W) -> str:
    if pct is None:
        return "·" * width
    filled = max(0, min(width, round(pct * width)))
    return "█" * filled + "░" * (width - filled)


def render(snap: dict) -> str:
    out: list[str] = []
    company = snap.get("company") or "—"
    when = snap.get("generated_at", "")[:16].replace("T", " ")
    out.append(f"\n  {company}   ·   {when}")
    out.append("  " + "─" * 56)

    if snap.get("error"):
        out.append(f"  ERRORE: {snap['error']}")
        return "\n".join(out)

    for sim in snap["sims"]:
        label = sim.get("label") or sim["uuid"][:8]
        glyph = GLYPH.get(sim.get("status", "unknown"), "·")
        head = f"  {glyph} {label}  {sim.get('msisdn_short','')}"
        plan = sim.get("plan_name") or ""
        out.append(f"{head:<34}{plan}")

        if sim.get("status") == "inactive":
            out.append(f"      SIM non attiva ({sim.get('note','')})")
            out.append("")
            continue
        if sim.get("error"):
            out.append(f"      errore: {sim['error']}")
            out.append("")
            continue

        d = sim.get("data") or {}
        used, limit, pct = d.get("used"), d.get("limit"), d.get("pct")
        pct_txt = f"{pct * 100:.0f}%" if pct is not None else "—"
        out.append(f"      {bar(pct)}  {fmt_gb(used)} / {fmt_gb(limit)} GB  ({pct_txt})")

        cyc, pr = sim.get("cycle"), sim.get("projection")
        if cyc:
            end = datetime.fromisoformat(cyc["end"]).strftime("%d/%m")
            out.append(f"      rinnovo tra {fmt_days_left(cyc['days_left'])} "
                       f"({end}) · ciclo di {cyc['days_total']} giorni")
        if pr:
            per_day = pr.get("per_day_gb")
            budget = pr.get("budget_per_day_gb")
            proj = pr.get("projected_gb")
            line = f"      ritmo {fmt_gb(per_day)} GB/g"
            if budget:
                line += f" (sostenibile {fmt_gb(budget)})"
            out.append(line)

            if proj is not None and limit:
                verdict = "sfora" if proj > limit else "rientra"
                out.append(f"      previsione fine ciclo {fmt_gb(proj)} GB → {verdict}")
            if pr.get("safe_per_day_gb") is not None:
                out.append(f"      da ora puoi usarne {fmt_gb(pr['safe_per_day_gb'])} GB/g")
            if pr.get("exhaustion_date"):
                ex = datetime.fromisoformat(pr["exhaustion_date"]).strftime("%d/%m")
                out.append(f"      a questo ritmo finisci i GB il {ex}")

        eu = sim.get("data_eu") or {}
        if eu.get("used"):
            out.append(f"      roaming UE {fmt_gb(eu['used'])} / {fmt_gb(eu.get('limit'))} GB")
        if sim.get("extra_cost_eur"):
            out.append(f"      costi extra soglia: {sim['extra_cost_eur']:.2f} €")
        out.append("")

    return "\n".join(out)


def fetch_once(cfg, client: IliadClient) -> dict:
    snap = build(client, cfg)
    store.write_latest(snap)
    n = store.record(snap)
    snap["_recorded"] = n
    return snap


def main(argv: list[str]) -> int:
    if "--import-session" in argv:
        return import_recon_session()

    cfg = cfgmod.load()
    client = IliadClient(cfg.base_url)

    as_json = "--json" in argv
    watch = "--watch" in argv

    while True:
        try:
            snap = fetch_once(cfg, client)
        except AuthError as exc:
            print(f"Autenticazione fallita: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"Errore: {exc}", file=sys.stderr)
            if not watch:
                return 1
            snap = None

        if snap is not None:
            print(json.dumps(snap, ensure_ascii=False, indent=2) if as_json
                  else render(snap))

        if not watch:
            return 0

        minutes = cfg.refresh_minutes
        if snap:
            soon = [s for s in snap.get("sims", [])
                    if (s.get("cycle") or {}).get("days_left", 99) <= 2]
            if soon:
                minutes = cfg.refresh_minutes_near_renewal
        nxt = datetime.now(ZoneInfo(cfg.timezone))
        print(f"  prossimo aggiornamento fra {minutes} min "
              f"(ora {nxt.strftime('%H:%M')})\n")
        time.sleep(minutes * 60)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
