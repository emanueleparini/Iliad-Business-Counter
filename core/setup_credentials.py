"""
Salva le credenziali iliad in Windows Credential Manager (cifrate con DPAPI,
leggibili solo dal tuo account Windows) e verifica subito che funzionino.

    .venv\\Scripts\\python.exe -m core.setup_credentials

Nessuna password viene mai scritta in un file del progetto.
"""

from __future__ import annotations

import sys
from getpass import getpass

from core.api import AuthError, IliadClient, clear_credentials, save_credentials


def main() -> int:
    if "--clear" in sys.argv:
        clear_credentials()
        print("Credenziali rimosse dal Credential Manager.")
        return 0

    print("Credenziali area personale iliad business")
    print("(l'ID utente e' il codice numerico, non l'email)\n")

    username = input("ID utente: ").strip()
    if not username:
        print("ID utente obbligatorio.")
        return 1

    password = getpass("Password (non viene mostrata): ")
    if not password:
        print("Password obbligatoria.")
        return 1

    print("\nVerifico l'accesso...")
    client = IliadClient()
    try:
        me = client.login(username, password)
    except AuthError as exc:
        print(f"  {exc}")
        print("  Nulla e' stato salvato.")
        return 1
    except Exception as exc:
        print(f"  Errore inatteso: {exc}")
        return 1

    save_credentials(username, password)

    company = (me.get("companies") or [{}])[0].get("legalName", "?")
    print(f"  Accesso riuscito: {me.get('firstName','')} — {company}")

    try:
        lines = client.lines()
        print(f"  SIM trovate: {len(lines)}")
        for ln in lines:
            flag = "attiva" if ln.is_active else ln.state
            print(f"    - {ln.short_msisdn}  {ln.plan_name or '?':<22} [{flag}]")
    except Exception as exc:
        print(f"  (elenco SIM non recuperato: {exc})")

    print("\nCredenziali salvate. Il collector ora puo' girare da solo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
