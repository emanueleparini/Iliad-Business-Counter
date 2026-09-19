"""Palette del widget, allineata al tema di Windows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    card: str
    card_hover: str
    text: str
    muted: str
    faint: str
    track: str
    divider: str
    ok: str
    warn: str
    over: str
    idle: str
    accent: str
    shadow: str

    def status(self, status: str) -> str:
        return {
            "ok": self.ok,
            "warn": self.warn,
            "over": self.over,
            "inactive": self.idle,
            "error": self.over,
        }.get(status, self.idle)


DARK = Palette(
    bg="#14161B",
    card="#1C1F26",
    card_hover="#232732",
    text="#E9EBEF",
    muted="#9BA1AC",
    faint="#6A7280",
    track="#2A2F3A",
    divider="#272B34",
    ok="#3DDC97",
    warn="#F5B841",
    over="#FF6B6B",
    idle="#5B6270",
    accent="#7AA2F7",
    shadow="#00000066",
)

LIGHT = Palette(
    bg="#FBFBFD",
    card="#FFFFFF",
    card_hover="#F2F4F8",
    text="#1B1F26",
    muted="#5C636E",
    faint="#8A919C",
    track="#E4E7EC",
    divider="#E8EBF0",
    ok="#12A474",
    warn="#C77A0A",
    over="#D64545",
    idle="#9AA1AC",
    accent="#2F5FD0",
    shadow="#0F172A22",
)


def windows_prefers_dark() -> bool:
    """Legge il tema app di Windows; in caso di dubbio sceglie scuro."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        with key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return True


def resolve(mode: str = "auto") -> Palette:
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    return DARK if windows_prefers_dark() else LIGHT
