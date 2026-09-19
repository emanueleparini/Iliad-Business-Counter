"""
Avvio automatico all'accesso a Windows, tramite collegamento nella cartella
Esecuzione automatica.

    python -m install.autostart --install
    python -m install.autostart --remove
    python -m install.autostart            # stato

Dai sorgenti punta a pythonw.exe del venv, installato punta all'exe:
in nessuno dei due casi compare una finestra di console.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "iliad counter.lnk"

# Installato (PyInstaller) il collegamento punta all'exe; dai sorgenti punta a
# pythonw.exe del venv, cosi' non compare nessuna finestra di console.
FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    ROOT = Path(sys.executable).resolve().parent
    TARGET = Path(sys.executable).resolve()
    ARGS = ""
    ICON = TARGET
else:
    ROOT = Path(__file__).resolve().parent.parent
    TARGET = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    ARGS = "-m widget.app"
    ICON = ROOT / "assets" / "iliad.ico"


def startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / (
        r"Microsoft\Windows\Start Menu\Programs\Startup"
    )


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


CREATE_NO_WINDOW = 0x08000000


def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def _make_shortcut(lnk: Path) -> bool:
    script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{lnk}')
$s.TargetPath = '{TARGET}'
$s.Arguments = '{ARGS}'
$s.WorkingDirectory = '{ROOT}'
$s.Description = 'Contatori iliad business'
$s.IconLocation = '{ICON}'
$s.WindowStyle = 7
$s.Save()
"""
    res = _powershell(script)
    return res.returncode == 0 and lnk.exists()


def is_enabled() -> bool:
    return shortcut_path().exists()


def desktop_shortcut() -> Path:
    return Path(os.environ["USERPROFILE"]) / "Desktop" / SHORTCUT_NAME


def create_desktop_shortcut() -> Path | None:
    lnk = desktop_shortcut()
    return lnk if _make_shortcut(lnk) else None


def set_enabled(enabled: bool) -> bool:
    """Per il pannello impostazioni: torna lo stato effettivo dopo l'operazione."""
    if enabled:
        if not TARGET.exists():
            return False
        _make_shortcut(shortcut_path())
    else:
        shortcut_path().unlink(missing_ok=True)
    return is_enabled()


def install() -> int:
    if not TARGET.exists():
        print(f"Eseguibile non trovato in {TARGET}")
        if not FROZEN:
            print("Crea prima il venv: python -m venv .venv")
        return 1

    lnk = shortcut_path()
    if not _make_shortcut(lnk):
        print("Creazione del collegamento fallita.")
        return 1
    print(f"Avvio automatico attivo.\n  {lnk}")
    return 0


def remove() -> int:
    lnk = shortcut_path()
    if not lnk.exists():
        print("Avvio automatico gia' disattivato.")
        return 0
    lnk.unlink()
    print("Avvio automatico disattivato.")
    return 0


def status() -> int:
    lnk = shortcut_path()
    print(f"Avvio automatico: {'ATTIVO' if lnk.exists() else 'non attivo'}")
    print(f"  collegamento: {lnk}")
    print(f"  eseguibile:   {TARGET} {'' if TARGET.exists() else '(MANCANTE)'}")
    print("\n  --install per attivarlo, --remove per toglierlo")
    return 0


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("Questo script serve solo su Windows.")
        return 1
    if "--install" in argv:
        return install()
    if "--remove" in argv:
        return remove()
    if "--desktop" in argv:
        lnk = create_desktop_shortcut()
        print(f"Icona sul desktop: {lnk}" if lnk else "Creazione icona fallita.")
        return 0 if lnk else 1
    return status()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
