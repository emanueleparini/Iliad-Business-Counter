"""
Conversione dei contatori iliad, che arrivano come stringhe gia' formattate
("233.0GB", "Illimitati", "0 min", "300m", "0.00 EUR").

Convenzione di ritorno:
    float   -> valore noto
    inf     -> illimitato
    None    -> non disponibile / non interpretabile
"""

from __future__ import annotations

import math
import re

UNLIMITED = math.inf

# GB decimali: iliad dichiara "300GB" per un piano da 300 GB commerciali.
_DATA_UNITS_GB = {
    "B": 1e-9,
    "KB": 1e-6,
    "MB": 1e-3,
    "GB": 1.0,
    "TB": 1000.0,
}

_UNLIMITED_WORDS = {"illimitati", "illimitato", "illimitata", "unlimited", "∞"}

_NUM_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*([a-zA-Z]*)")


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_data_gb(value) -> float | None:
    """'233.0GB' -> 233.0 | '500MB' -> 0.5 | 'Illimitati' -> inf | None -> None"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None
    if s.lower() in _UNLIMITED_WORDS:
        return UNLIMITED

    m = _NUM_RE.search(s)
    if not m:
        return None
    num = _to_float(m.group(1))
    if num is None:
        return None

    unit = m.group(2).upper()
    # senza unita' esplicita iliad intende GB nei contatori dati
    factor = _DATA_UNITS_GB.get(unit, 1.0 if not unit else None)
    if factor is None:
        return None
    return num * factor


def parse_minutes(value) -> float | None:
    """'0 min' -> 0.0 | '300m' -> 300.0 | 'Illimitati' -> inf"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None
    if s.lower() in _UNLIMITED_WORDS:
        return UNLIMITED

    m = _NUM_RE.search(s)
    if not m:
        return None
    num = _to_float(m.group(1))
    if num is None:
        return None
    # 'h' compare raramente, ma se arriva va convertita
    return num * 60.0 if m.group(2).lower().startswith("h") else num


def parse_count(value) -> float | None:
    """Contatori interi (SMS). 'Illimitati' -> inf"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    if s.lower() in _UNLIMITED_WORDS:
        return UNLIMITED
    m = _NUM_RE.search(s)
    return _to_float(m.group(1)) if m else None


def parse_euro(value) -> float | None:
    """'0.00€' -> 0.0 | '12,50 EUR' -> 12.5"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("€", "").replace("EUR", "").strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    return _to_float(m.group(1)) if m else None


def is_unlimited(x: float | None) -> bool:
    return x is not None and math.isinf(x)


def fmt_limit(x: float | None, suffix: str = "") -> str:
    """Per la UI: distingue illimitato da sconosciuto."""
    if x is None:
        return "—"
    if math.isinf(x):
        return "∞"
    if x == int(x):
        return f"{int(x)}{suffix}"
    return f"{x:.1f}".replace(".", ",") + suffix
