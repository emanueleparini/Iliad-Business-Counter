"""
Punto di ingresso dell'eseguibile Windows.

Dai sorgenti si usa `python -m widget.app`; questo file serve a PyInstaller,
che ha bisogno di uno script vero da cui partire.
"""

from __future__ import annotations

from widget.app import main

if __name__ == "__main__":
    raise SystemExit(main())
