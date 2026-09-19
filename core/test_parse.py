"""Test dei parser dei contatori. Eseguire: python -m core.test_parse"""

from __future__ import annotations

import math

from core.parse import (
    UNLIMITED,
    fmt_limit,
    is_unlimited,
    parse_count,
    parse_data_gb,
    parse_euro,
    parse_minutes,
)

FAILED: list[str] = []


def check(name: str, got, want) -> None:
    same = (got is want) if want is None else (
        math.isinf(want) and got is not None and math.isinf(got)
        if isinstance(want, float) and math.isinf(want)
        else got == want
    )
    if same:
        print(f"  ok  {name}")
    else:
        FAILED.append(f"{name}: atteso {want!r}, ottenuto {got!r}")


print("dati")
# formati visti davvero sul portale
check("GB con decimale", parse_data_gb("233.0GB"), 233.0)
check("GB interi", parse_data_gb("300GB"), 300.0)
check("GB a zero", parse_data_gb("0.0GB"), 0.0)
check("roaming UE", parse_data_gb("22GB"), 22.0)
# varianti plausibili se iliad cambia formattazione
check("con spazio", parse_data_gb("12,5 GB"), 12.5)
check("megabyte", parse_data_gb("500MB"), 0.5)
check("kilobyte", parse_data_gb("250KB"), 0.00025)
check("terabyte", parse_data_gb("1TB"), 1000.0)
check("senza unita'", parse_data_gb("42"), 42.0)
check("numerico", parse_data_gb(7.5), 7.5)
check("illimitati", parse_data_gb("Illimitati"), UNLIMITED)
check("vuoto", parse_data_gb(""), None)
check("nullo", parse_data_gb(None), None)
check("spazzatura", parse_data_gb("n/d"), None)

print("\nminuti")
check("minuti nazionali", parse_minutes("0 min"), 0.0)
check("limite compatto", parse_minutes("300m"), 300.0)
check("illimitati", parse_minutes("Illimitati"), UNLIMITED)
check("ore convertite", parse_minutes("2h"), 120.0)

print("\nsms e costi")
check("sms numerico", parse_count(0), 0.0)
check("sms illimitati", parse_count("Illimitati"), UNLIMITED)
check("euro con simbolo", parse_euro("0.00€"), 0.0)
check("euro con virgola", parse_euro("12,50 EUR"), 12.5)
check("euro nullo", parse_euro(None), None)

print("\nutilita'")
check("illimitato riconosciuto", is_unlimited(UNLIMITED), True)
check("finito non illimitato", is_unlimited(300.0), False)
check("sconosciuto non illimitato", is_unlimited(None), False)
check("formato intero", fmt_limit(300.0, "GB"), "300GB")
check("formato infinito", fmt_limit(UNLIMITED), "∞")
check("formato assente", fmt_limit(None), "—")

print()
if FAILED:
    print(f"FALLITI {len(FAILED)}:")
    for f in FAILED:
        print("  -", f)
    raise SystemExit(1)
print("tutti i test passati")
