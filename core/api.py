"""
Client HTTP per l'API di business.iliad.it.

Il portale e' una SPA Vue su API Platform (Symfony). L'autenticazione e' un
POST JSON su /api/login che risponde con un cookie di sessione HttpOnly
(ACC_SESSID); da li' in poi non serve alcun header Authorization.

Quindi a regime NON serve un browser: bastano richieste HTTP.
Credenziali e cookie stanno in Windows Credential Manager (DPAPI), mai su disco
in chiaro.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import keyring
import requests

SERVICE = "iliad-counter"
_USERNAME_SLOT = "__username__"
_COOKIE_SLOT = "__session_cookie__"

BASE_URL = "https://business.iliad.it"
SESSION_COOKIE = "ACC_SESSID"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
TIMEOUT = 20


class IliadError(RuntimeError):
    pass


class AuthError(IliadError):
    pass


# ------------------------------------------------------------ credenziali


def save_credentials(username: str, password: str) -> None:
    keyring.set_password(SERVICE, _USERNAME_SLOT, username)
    keyring.set_password(SERVICE, username, password)


def load_credentials() -> tuple[str, str]:
    username = keyring.get_password(SERVICE, _USERNAME_SLOT)
    if not username:
        raise AuthError(
            "Credenziali non configurate: aprile dalle impostazioni del widget."
        )
    password = keyring.get_password(SERVICE, username)
    if not password:
        raise AuthError(f"Password mancante per l'utente {username}.")
    return username, password


def has_credentials() -> bool:
    username = keyring.get_password(SERVICE, _USERNAME_SLOT)
    return bool(username and keyring.get_password(SERVICE, username))


def clear_credentials() -> None:
    username = keyring.get_password(SERVICE, _USERNAME_SLOT)
    for slot in filter(None, (username, _USERNAME_SLOT, _COOKIE_SLOT)):
        try:
            keyring.delete_password(SERVICE, slot)
        except keyring.errors.PasswordDeleteError:
            pass


# ------------------------------------------------------------------ client


@dataclass
class Line:
    uuid: str
    msisdn: str | None
    plan_name: str | None
    state: str          # active | inactive | suspended | ...
    name: str | None
    iccid: str | None
    activatable: bool

    @property
    def is_active(self) -> bool:
        return self.state == "active"

    @property
    def short_msisdn(self) -> str:
        if not self.msisdn:
            return "—"
        return "…" + self.msisdn[-4:]

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "Line":
        return cls(
            uuid=d.get("uuid") or str(d.get("@id", "")).rsplit("/", 1)[-1],
            msisdn=d.get("msisdn"),
            plan_name=d.get("planName"),
            state=d.get("state") or "unknown",
            name=d.get("name"),
            iccid=d.get("iccid"),
            activatable=bool(d.get("activatable")),
        )


class IliadClient:
    """Sessione riusabile. Rifa' il login da sola quando il cookie scade."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "it-IT",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/account/",
        })
        self._me: dict[str, Any] | None = None
        self._restore_cookie()

    # -- gestione sessione ------------------------------------------------

    def _restore_cookie(self) -> None:
        value = keyring.get_password(SERVICE, _COOKIE_SLOT)
        if value:
            self.s.cookies.set(SESSION_COOKIE, value, domain="business.iliad.it")

    def _persist_cookie(self) -> None:
        value = self.s.cookies.get(SESSION_COOKIE, domain="business.iliad.it")
        if value:
            keyring.set_password(SERVICE, _COOKIE_SLOT, value)

    def login(self, username: str | None = None, password: str | None = None) -> dict:
        if username is None or password is None:
            username, password = load_credentials()
        r = self.s.post(
            f"{self.base_url}/api/login",
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        if r.status_code in (400, 401, 403):
            raise AuthError(f"Login rifiutato (HTTP {r.status_code}): credenziali errate?")
        if not r.ok:
            raise IliadError(f"Login fallito: HTTP {r.status_code}")
        self._persist_cookie()
        self._me = r.json()
        return self._me

    # -- richieste --------------------------------------------------------

    def get(self, path: str, *, params: dict | None = None,
            _retried: bool = False) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(3):
            try:
                r = self.s.get(url, params=params, timeout=TIMEOUT)
                break
            except requests.RequestException as exc:      # rete assente, DNS, ecc.
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise IliadError(f"Rete non raggiungibile: {last_exc}")

        if r.status_code == 401:
            if _retried:
                raise AuthError("Sessione non valida anche dopo il re-login.")
            self.login()                                  # cookie scaduto
            return self.get(path, params=params, _retried=True)

        if r.status_code == 404:
            raise IliadError(f"Endpoint non trovato: {path}")
        if not r.ok:
            raise IliadError(f"HTTP {r.status_code} su {path}")

        try:
            return r.json()
        except json.JSONDecodeError as exc:
            raise IliadError(f"Risposta non JSON da {path}: {exc}") from exc

    # -- endpoint ---------------------------------------------------------

    def me(self, refresh: bool = False) -> dict:
        if self._me is None or refresh:
            self._me = self.get("/api/me")
        return self._me

    def company_id(self) -> str:
        me = self.me()
        company = me.get("company") or ""
        if company:
            return str(company).rsplit("/", 1)[-1]
        companies = me.get("companies") or []
        if companies:
            return str(companies[0].get("@id", "")).rsplit("/", 1)[-1]
        raise IliadError("Nessuna azienda associata all'utente.")

    def lines(self, company_id: str | None = None) -> list[Line]:
        cid = company_id or self.company_id()
        data = self.get(
            f"/api/companies/{cid}/lines",
            params={"page": 1, "itemsPerPage": 50, "exists[deletedAt]": "false"},
        )
        return [Line.from_api(m) for m in data.get("hydra:member", [])]

    def line(self, uuid: str) -> dict:
        return self.get(f"/api/lines/{uuid}")

    def line_info(self, uuid: str) -> dict:
        """msisdn, iccid, is_activated, renewalDate (e i PUK, che ignoriamo)."""
        return self.get(f"/api/lines/{uuid}/info")

    def line_counters(self, uuid: str) -> dict:
        """Il cuore: consumi nazionali/estero + periodo di riferimento."""
        return self.get(f"/api/lines/{uuid}/counters")
