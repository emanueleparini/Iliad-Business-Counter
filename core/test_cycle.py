"""Test della matematica dei cicli. Eseguire: python -m core.test_cycle"""

from __future__ import annotations

from datetime import date, datetime, timezone

from core.cycle import cycle_bounds, cycle_state, fmt_days_left, fmt_gb, project

ROME = timezone.utc  # i test non dipendono dal fuso, basta che sia coerente
FAILED: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILED.append(f"{name}: atteso {want!r}, ottenuto {got!r}")
    else:
        print(f"  ok  {name}")


def approx(name: str, got: float, want: float, tol: float = 1e-6) -> None:
    if got is None or abs(got - want) > tol:
        FAILED.append(f"{name}: atteso ~{want}, ottenuto {got!r}")
    else:
        print(f"  ok  {name}")


print("cycle_bounds")
# rinnovo il 4, siamo al 19 settembre -> ciclo 4 set / 4 ott
check("dopo il rinnovo", cycle_bounds(4, date(2026, 9, 19)),
      (date(2026, 9, 4), date(2026, 10, 4)))
# rinnovo il 19, siamo al 19 settembre -> il giorno stesso apre il ciclo nuovo
check("il giorno del rinnovo", cycle_bounds(19, date(2026, 9, 19)),
      (date(2026, 9, 19), date(2026, 10, 19)))
# rinnovo il 19, siamo al 2 settembre -> ciclo ancora quello di agosto
check("prima del rinnovo", cycle_bounds(19, date(2026, 9, 2)),
      (date(2026, 8, 19), date(2026, 9, 19)))
# passaggio d'anno
check("dicembre -> gennaio", cycle_bounds(4, date(2026, 12, 20)),
      (date(2026, 12, 4), date(2027, 1, 4)))
check("gennaio -> dicembre", cycle_bounds(20, date(2027, 1, 3)),
      (date(2026, 12, 20), date(2027, 1, 20)))
# giorno 31 in mesi corti: non deve saltare il mese
check("31 in febbraio", cycle_bounds(31, date(2027, 2, 15)),
      (date(2027, 1, 31), date(2027, 2, 28)))
check("31 -> aprile da 30", cycle_bounds(31, date(2027, 3, 31)),
      (date(2027, 3, 31), date(2027, 4, 30)))
# anno bisestile
check("29 febbraio bisestile", cycle_bounds(29, date(2028, 2, 29)),
      (date(2028, 2, 29), date(2028, 3, 29)))

print("\ncycle_state")
st = cycle_state(4, datetime(2026, 9, 19, 12, 0, tzinfo=ROME))
check("giorni totali", st.days_total, 30)
approx("giorni trascorsi", st.days_elapsed, 15.5)
approx("giorni rimasti", st.days_left, 14.5)
approx("avanzamento", st.progress, 15.5 / 30)

print("\nproject")
# a meta' ciclo con meta' pacchetto consumato: perfettamente in linea
st = cycle_state(4, datetime(2026, 9, 19, 0, 0, tzinfo=ROME))
p = project(75.0, 150.0, st)
approx("ritmo medio", p.per_day_gb, 75.0 / 15)
approx("proiezione", p.projected_gb, 150.0)
check("stato in linea", p.status, "warn")  # esattamente al limite: gia' avviso

# ritmo doppio: sforamento netto
p = project(120.0, 150.0, st)
check("stato sforamento", p.status, "over")
approx("proiezione doppia", p.projected_gb, 240.0)
check("data esaurimento", p.exhaustion_date, date(2026, 9, 22))

# ritmo tranquillo
p = project(40.0, 150.0, st)
check("stato ok", p.status, "ok")
check("nessun esaurimento previsto", p.exhaustion_date, None)
approx("consumo sicuro/giorno", p.safe_per_day_gb, 110.0 / 15)

# pacchetto gia' finito
p = project(150.0, 150.0, st)
check("pacchetto esaurito", p.status, "over")
approx("residuo a zero", p.remaining_gb, 0.0)

# soglia sconosciuta (SIM non ancora attiva o portale muto)
p = project(10.0, None, st)
check("senza soglia", p.status, "unknown")
check("percentuale assente", p.used_pct, None)

# inizio ciclo: ritmo non ancora significativo, niente proiezioni assurde
st0 = cycle_state(4, datetime(2026, 9, 4, 1, 0, tzinfo=ROME))
p = project(2.0, 150.0, st0)
check("inizio ciclo non proietta", p.projected_gb, 2.0)
check("inizio ciclo stato ok", p.status, "ok")

print("\nformattazione")
check("gb grandi", fmt_gb(150.0), "150")
check("gb medi", fmt_gb(62.42), "62,4")
check("gb piccoli", fmt_gb(4.237), "4,24")
check("gb assenti", fmt_gb(None), "—")
check("giorni", fmt_days_left(9.4), "9 giorni")
check("un giorno", fmt_days_left(1.2), "1 giorno")
check("ore", fmt_days_left(0.5), "12 h")

print()
if FAILED:
    print(f"FALLITI {len(FAILED)}:")
    for f in FAILED:
        print("  -", f)
    raise SystemExit(1)
print("tutti i test passati")
