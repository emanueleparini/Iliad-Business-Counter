# -*- mode: python ; coding: utf-8 -*-
"""
Build dell'eseguibile Windows.

    pyinstaller --noconfirm packaging/iliad-counter.spec

Produce dist/iliad-counter/ (cartella con exe + runtime Qt), che l'installer
Inno Setup impacchetta in un setup unico.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "iliad_counter.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # il template del config viaggia dentro il bundle: al primo avvio diventa
    # %LOCALAPPDATA%\iliad counter\config.toml
    datas=[
        (str(ROOT / "config.example.toml"), "."),
        # l'icona serve anche a runtime: finestre, notifiche, pannello
        (str(ROOT / "assets" / "iliad.ico"), "assets"),
    ],
    hiddenimports=[
        # keyring sceglie il backend a runtime via entry point: PyInstaller
        # non lo vede da solo
        "keyring.backends.Windows",
        "win32ctypes.core",
        "win32ctypes.core.ctypes",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "playwright",          # serve solo alla ricognizione del portale
        "tkinter",
        "unittest",
        "pydoc",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtWebSockets",
        "PySide6.QtTest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="iliad-counter",
    debug=False,
    strip=False,
    upx=False,
    console=False,               # nessuna finestra di console
    icon=str(ROOT / "assets" / "iliad.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="iliad-counter",
)
