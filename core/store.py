"""
Persistenza: snapshot corrente su JSON + storico su SQLite.

Lo storico serve a due cose che l'API non da': la curva del consumo dentro il
ciclo e il consumo giorno per giorno (l'API espone solo il totale corrente).
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import DATA_DIR

LATEST = DATA_DIR / "latest.json"
DB = DATA_DIR / "history.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts          TEXT NOT NULL,          -- ISO 8601 con fuso
    sim_uuid    TEXT NOT NULL,
    cycle_start TEXT,                   -- YYYY-MM-DD: separa i cicli
    used_gb     REAL,
    limit_gb    REAL,
    status      TEXT,
    PRIMARY KEY (ts, sim_uuid)
);
CREATE INDEX IF NOT EXISTS idx_samples_sim_cycle
    ON samples (sim_uuid, cycle_start, ts);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    return conn


def write_latest(snap: dict[str, Any]) -> None:
    """Scrittura atomica: il widget non deve mai leggere un JSON a meta'."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, LATEST)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_latest() -> dict[str, Any] | None:
    if not LATEST.exists():
        return None
    try:
        return json.loads(LATEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def record(snap: dict[str, Any]) -> int:
    """Aggiunge un campione per ogni SIM con dati validi. Torna quanti ne ha scritti."""
    ts = snap.get("generated_at") or datetime.now().isoformat(timespec="seconds")
    rows = []
    for sim in snap.get("sims", []):
        data = sim.get("data") or {}
        if data.get("used") is None:
            continue
        cycle = (sim.get("cycle") or {}).get("start")
        rows.append((ts, sim["uuid"], cycle, data.get("used"),
                     data.get("limit"), sim.get("status")))
    if not rows:
        return 0
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO samples "
            "(ts, sim_uuid, cycle_start, used_gb, limit_gb, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def series(sim_uuid: str, cycle_start: str | None = None,
           limit: int = 500) -> list[tuple[str, float]]:
    """Campioni (ts, used_gb) del ciclo indicato, in ordine cronologico."""
    q = "SELECT ts, used_gb FROM samples WHERE sim_uuid = ?"
    args: list[Any] = [sim_uuid]
    if cycle_start:
        q += " AND cycle_start = ?"
        args.append(cycle_start)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with _connect() as conn:
        rows = conn.execute(q, args).fetchall()
    return [(ts, gb) for ts, gb in reversed(rows) if gb is not None]


def daily_usage(sim_uuid: str, cycle_start: str) -> list[tuple[str, float]]:
    """
    Consumo per giorno, ricavato dai delta del totale progressivo.

    Il contatore si azzera a ogni rinnovo, per questo i campioni sono separati
    per ciclo: un delta negativo qui significherebbe dati sporchi, e viene
    scartato invece di produrre un giorno a consumo negativo.
    """
    pts = series(sim_uuid, cycle_start, limit=5000)
    if not pts:
        return []

    last_of_day: dict[str, float] = {}
    for ts, gb in pts:
        last_of_day[ts[:10]] = gb

    out: list[tuple[str, float]] = []
    prev = 0.0
    for day in sorted(last_of_day):
        cur = last_of_day[day]
        delta = cur - prev
        out.append((day, round(delta, 3) if delta >= 0 else 0.0))
        prev = max(prev, cur)
    return out


def prune(keep_days: int = 400) -> int:
    """Lo storico serve, ma non in eterno."""
    cutoff = (datetime.now().astimezone()
              .replace(microsecond=0).isoformat())[:10]
    cutoff_date = (datetime.fromisoformat(cutoff).toordinal() - keep_days)
    cutoff_iso = datetime.fromordinal(cutoff_date).date().isoformat()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff_iso,))
        return cur.rowcount
