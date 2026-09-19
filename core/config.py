"""Lettura di config.toml con valori di default sensati."""

from __future__ import annotations

import os
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Due modi di girare:
#   - dai sorgenti: tutto accanto al progetto, comodo da guardare e modificare
#   - installato (PyInstaller): i sorgenti sono di sola lettura, quindi config
#     e dati vanno nella cartella dell'utente
FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    ROOT = Path(sys.executable).resolve().parent
    USER_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "iliad counter"
    BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    ROOT = Path(__file__).resolve().parent.parent
    USER_DIR = ROOT
    BUNDLE = ROOT

CONFIG_PATH = USER_DIR / "config.toml"
DATA_DIR = USER_DIR / "data"
TEMPLATE_PATH = BUNDLE / "config.example.toml"


def ensure_config(path: Path | None = None) -> Path:
    """Al primo avvio il config personale nasce dal template versionato."""
    p = path or CONFIG_PATH
    if not p.exists() and TEMPLATE_PATH.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATE_PATH, p)
        except OSError:
            pass
    return p


@dataclass
class SimConfig:
    id: str
    label: str
    uuid: str
    enabled: bool = True
    renewal_day: int | None = None      # solo fallback: il portale ha la data vera
    data_allowance_gb: float = 0.0      # solo fallback


@dataclass
class Config:
    refresh_minutes: int = 60
    refresh_minutes_near_renewal: int = 30
    timezone: str = "Europe/Rome"
    base_url: str = "https://business.iliad.it"
    widget: dict = field(default_factory=dict)
    alerts: dict = field(default_factory=dict)
    sims: list[SimConfig] = field(default_factory=list)

    def sim_by_uuid(self, uuid: str) -> SimConfig | None:
        return next((s for s in self.sims if s.uuid == uuid), None)


def load(path: Path | None = None) -> Config:
    p = ensure_config(path)
    raw = tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    general = raw.get("general", {})
    portal = raw.get("portal", {})

    sims = [
        SimConfig(
            id=s.get("id") or f"sim{i + 1}",
            label=s.get("label") or f"SIM {i + 1}",
            uuid=s["uuid"],
            enabled=s.get("enabled", True),
            renewal_day=s.get("renewal_day"),
            data_allowance_gb=float(s.get("data_allowance_gb") or 0),
        )
        for i, s in enumerate(raw.get("sim", []))
        if s.get("uuid")
    ]

    return Config(
        refresh_minutes=int(general.get("refresh_minutes", 60)),
        refresh_minutes_near_renewal=int(
            general.get("refresh_minutes_near_renewal", 30)
        ),
        timezone=general.get("timezone", "Europe/Rome"),
        base_url=portal.get("base_url", "https://business.iliad.it"),
        widget=raw.get("widget", {}),
        alerts=raw.get("alerts", {}),
        sims=sims,
    )


def set_refresh_minutes(minutes: int, path: Path | None = None) -> bool:
    """
    Aggiorna una sola chiave lasciando intatti commenti e formattazione:
    config.toml e' un file che l'utente legge e modifica a mano.
    """
    p = ensure_config(path)
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    in_general = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            in_general = stripped == "[general]"
            continue
        if not in_general or not stripped.startswith("refresh_minutes"):
            continue
        if stripped.startswith("refresh_minutes_near"):
            continue
        lines[i] = f"refresh_minutes = {int(minutes)}"
        break
    else:
        return False

    try:
        p.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
        return True
    except OSError:
        return False
