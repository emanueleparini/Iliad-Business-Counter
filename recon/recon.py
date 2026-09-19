"""
Ricognizione del portale iliad business.

Apre un Chromium VISIBILE su business.iliad.it/account/.
Tu fai il login a mano e navighi (consumi SIM 1, consumi SIM 2, ...).
Lo script registra, in locale e basta:

  - tutte le chiamate di rete XHR/fetch verso iliad (URL, metodo, stato, corpo JSON)
  - uno snapshot HTML + testo + screenshot di ogni pagina visitata
  - lo stato della sessione (cookie) per riusarlo poi senza rifare il login

Quando hai finito, CHIUDI LA FINESTRA DEL BROWSER: lo script salva tutto e
genera un report riassuntivo redatto (password/token mai scritti nel report).

Uso:
    .venv\\Scripts\\python.exe recon\\recon.py
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
ART = ROOT / "artifacts"
PROFILE = ROOT / "browser-profile"
START_URL = "https://business.iliad.it/account/login/"

# Scorciatoie facoltative nell'overlay: se vuoi saltare diretto alla pagina di
# una SIM, incolla qui l'URL che leggi nella barra del browser. Lasciare vuoto
# va benissimo: alle SIM ci arrivi comunque navigando a mano.
#   ("SIM 1", "https://business.iliad.it/account/gestione-sim/<uuid-della-tua-sim>"),
SIM_URLS: list[tuple[str, str]] = []

NET_LOG = ART / "network.jsonl"
MARKS_LOG = ART / "marks.jsonl"
STATE_FILE = ART / "storage_state.json"
REPORT = ART / "REPORT.md"

# chiavi il cui VALORE non deve mai finire su disco/report
SECRET_KEY_RE = re.compile(
    r"(pass|pwd|secret|token|authorization|bearer|otp|pin|cvv|iban|session)", re.I
)
# header da non registrare mai per intero
SECRET_HEADERS = {"authorization", "cookie", "set-cookie", "x-auth-token", "x-api-key"}

MAX_BODY = 400_000  # byte: oltre, si tronca


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(obj, depth: int = 0):
    """Sostituisce i valori delle chiavi sensibili, tenendo il nome della chiave."""
    if depth > 12:
        return "<too-deep>"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and SECRET_KEY_RE.search(k):
                out[k] = f"<redacted len={len(str(v))}>"
            else:
                out[k] = redact(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [redact(v, depth + 1) for v in obj[:200]]
    return obj


def redact_text(text: str) -> str:
    """Redazione grezza per corpi non-JSON (form urlencoded, ecc.)."""
    return re.sub(
        r"((?:pass|pwd|secret|token|otp|pin)[a-z_]*=)([^&\s]+)",
        r"\1<redacted>",
        text,
        flags=re.I,
    )


def safe_headers(headers: dict) -> dict:
    return {
        k: ("<redacted>" if k.lower() in SECRET_HEADERS else v)
        for k, v in headers.items()
    }


def slug(url: str, n: int) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", url.split("://", 1)[-1])[:70].strip("-")
    return f"{n:03d}-{s}"


# ---------------------------------------------------------------- overlay UI

OVERLAY_JS = r"""
(() => {
  if (window.__reconBarReady) return;
  window.__reconBarReady = true;
  const build = () => {
    if (!document.body || document.getElementById('__recon_bar')) return;
    const bar = document.createElement('div');
    bar.id = '__recon_bar';
    bar.style.cssText = `position:fixed;z-index:2147483647;right:12px;bottom:12px;
      background:#111827ee;color:#f9fafb;font:12px/1.4 system-ui,sans-serif;
      padding:10px;border-radius:10px;box-shadow:0 8px 24px #0006;width:230px`;
    bar.innerHTML = `<div style="font-weight:600;margin-bottom:6px">recon iliad</div>`;
    const mk = (label) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.style.cssText = `display:block;width:100%;margin:3px 0;padding:6px;
        border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer;font:12px system-ui`;
      b.onclick = () => { window.__reconMark(label); b.style.background = '#16a34a'; };
      return b;
    };
    ['login fatto', 'elenco SIM', 'consumi SIM 1', 'consumi SIM 2'].forEach(l => bar.appendChild(mk(l)));
    (window.__reconSimUrls || []).forEach(([name, url]) => {
      const b = document.createElement('button');
      b.textContent = '→ ' + name;
      b.style.cssText = `display:block;width:100%;margin:3px 0;padding:6px;border:0;border-radius:6px;
        background:#7c3aed;color:#fff;cursor:pointer;font:12px system-ui`;
      b.onclick = () => { window.__reconMark('vado a ' + name); location.href = url; };
      bar.appendChild(b);
    });
    const inp = document.createElement('input');
    inp.placeholder = 'nota + Invio';
    inp.style.cssText = `width:100%;margin-top:6px;padding:5px;border-radius:6px;border:1px solid #374151;
      background:#1f2937;color:#f9fafb;font:12px system-ui;box-sizing:border-box`;
    inp.onkeydown = (e) => {
      if (e.key === 'Enter' && inp.value.trim()) { window.__reconMark(inp.value.trim()); inp.value = ''; }
      e.stopPropagation();
    };
    bar.appendChild(inp);
    document.body.appendChild(bar);
  };
  build();
  document.addEventListener('DOMContentLoaded', build);
  setInterval(build, 1500);
})();
"""


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    for f in (NET_LOG, MARKS_LOG):
        f.write_text("", encoding="utf-8")

    net_count = 0
    pages_seen: dict[int, str] = {}
    snap_n = 0

    def write_jsonl(path: Path, obj: dict) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=False,
            locale="it-IT",
            timezone_id="Europe/Rome",
            viewport={"width": 1440, "height": 950},
            args=["--disable-blink-features=AutomationControlled"],
        )

        def on_mark(label: str) -> None:
            page_url = ctx.pages[0].url if ctx.pages else ""
            write_jsonl(MARKS_LOG, {"ts": now(), "label": label, "url": page_url,
                                    "net_index": net_count})
            print(f"  [mark] {label}")

        ctx.expose_binding("__reconMark", lambda source, label: on_mark(label))
        ctx.add_init_script(
            f"window.__reconSimUrls = {json.dumps(SIM_URLS)};" + OVERLAY_JS
        )

        def on_response(resp) -> None:
            nonlocal net_count
            try:
                req = resp.request
                url = resp.url
                if "iliad" not in url:
                    return
                if req.resource_type not in ("xhr", "fetch", "document", "other"):
                    return

                ctype = (resp.headers.get("content-type") or "").lower()
                entry = {
                    "i": net_count,
                    "ts": now(),
                    "method": req.method,
                    "url": url,
                    "status": resp.status,
                    "resource_type": req.resource_type,
                    "content_type": ctype,
                    "req_headers": safe_headers(req.headers),
                }

                post = req.post_data
                if post:
                    try:
                        entry["req_body"] = redact(json.loads(post))
                    except Exception:
                        entry["req_body"] = redact_text(post[:4000])

                if "json" in ctype:
                    try:
                        entry["res_body"] = redact(resp.json())
                    except Exception:
                        entry["res_body"] = "<json non leggibile>"
                elif "html" in ctype or "text" in ctype:
                    entry["res_len"] = int(resp.headers.get("content-length") or 0)

                write_jsonl(NET_LOG, entry)
                net_count += 1
            except Exception:
                pass

        ctx.on("response", on_response)

        def snapshot(page) -> None:
            nonlocal snap_n
            try:
                snap_n += 1
                base = ART / slug(page.url, snap_n)
                page.wait_for_timeout(1500)
                (base.with_suffix(".html")).write_text(page.content(), encoding="utf-8")
                txt = page.evaluate("() => document.body ? document.body.innerText : ''")
                (base.with_suffix(".txt")).write_text(
                    f"URL: {page.url}\n\n{txt}", encoding="utf-8"
                )
                page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
                print(f"  [snap] {page.url[:90]}")
            except Exception:
                pass

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("=" * 68)
        print(" RICOGNIZIONE ILIAD BUSINESS")
        print("=" * 68)
        print(" 1. Fai il login nella finestra che si e' aperta.")
        print(" 2. Usa i bottoni viola del pannellino per aprire le due SIM,")
        print("    e apri ogni scheda/tab dei consumi che vedi.")
        print(" 3. Usa i bottoni del pannellino in basso a destra per annotare.")
        print(" 4. Quando hai finito CHIUDI IL BROWSER: salvo tutto e faccio il report.")
        print("=" * 68)
        print(" (password e token NON vengono mai scritti nei file di log)")
        print()

        try:
            page.goto(START_URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"  [!] apertura {START_URL} fallita: {exc}")

        # loop: snapshot a ogni cambio URL, finche' ci sono pagine aperte
        ticks = 0
        try:
            while ctx.pages:
                for pg in list(ctx.pages):
                    try:
                        url = pg.url
                    except Exception:
                        continue
                    key = id(pg)
                    if url and url != "about:blank" and pages_seen.get(key) != url:
                        pages_seen[key] = url
                        snapshot(pg)
                if ctx.pages:
                    try:
                        ctx.pages[0].wait_for_timeout(1200)
                    except Exception:
                        break
                ticks += 1
                if ticks % 15 == 0:
                    try:
                        ctx.storage_state(path=str(STATE_FILE))
                    except Exception:
                        pass
        except KeyboardInterrupt:
            print("\n  interrotto a mano")
        except Exception:
            pass

        try:
            ctx.storage_state(path=str(STATE_FILE))
        except Exception:
            pass  # browser gia' chiuso: vale l'ultimo salvataggio periodico
        if STATE_FILE.exists():
            print("  sessione salvata -> " + str(STATE_FILE))
        else:
            print("  [!] sessione non salvata (profilo browser comunque riusabile)")

        try:
            ctx.close()
        except Exception:
            pass

    build_report(net_count)
    print(f"  report -> {REPORT}")
    return 0


# ---------------------------------------------------------------- report

PHONE_RE = re.compile(r"\b3\d{8,9}\b")
CF_RE = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b")


def mask_pii(s: str) -> str:
    s = PHONE_RE.sub(lambda m: "***" + m.group(0)[-4:], s)
    s = CF_RE.sub("<CF>", s)
    return s


def shape(obj, depth: int = 0) -> str:
    """Descrive la forma di un JSON senza stamparlo tutto."""
    pad = "  " * depth
    if depth > 4:
        return pad + "..."
    if isinstance(obj, dict):
        lines = []
        for k, v in list(obj.items())[:40]:
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(shape(v, depth + 1))
            else:
                val = mask_pii(str(v))[:80]
                lines.append(f"{pad}{k}: {val}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return pad + "[]"
        return f"{pad}[{len(obj)} elementi] primo:\n" + shape(obj[0], depth + 1)
    return pad + mask_pii(str(obj))[:80]


def build_report(_n: int) -> None:
    entries = []
    if NET_LOG.exists():
        for line in NET_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass

    marks = []
    if MARKS_LOG.exists():
        for line in MARKS_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    marks.append(json.loads(line))
                except Exception:
                    pass

    out = ["# Ricognizione iliad business", "", f"Generato: {now()}", ""]

    out += ["## Annotazioni", ""]
    if marks:
        for m in marks:
            out.append(f"- `{m['net_index']:>4}` **{m['label']}** — {mask_pii(m['url'])}")
    else:
        out.append("_nessuna_")
    out += ["", "## Endpoint JSON trovati", ""]

    json_entries = [e for e in entries if "res_body" in e]
    if not json_entries:
        out.append("_Nessun endpoint JSON: il portale rende i dati server-side, "
                   "si va di parsing HTML._")
    else:
        out.append("| # | metodo | stato | URL |")
        out.append("|---|---|---|---|")
        for e in json_entries:
            out.append(f"| {e['i']} | {e['method']} | {e['status']} | "
                       f"`{mask_pii(e['url'])[:120]}` |")
        out += ["", "### Forma delle risposte", ""]
        for e in json_entries:
            out += [f"#### [{e['i']}] {e['method']} {mask_pii(e['url'])[:140]}", "",
                    "```", shape(e["res_body"])[:4000], "```", ""]

    out += ["## Navigazioni (documenti)", ""]
    for e in entries:
        if e.get("resource_type") == "document":
            out.append(f"- `{e['status']}` {e['method']} {mask_pii(e['url'])[:140]}")

    out += ["", "## Richieste POST (flusso di login)", ""]
    for e in entries:
        if e["method"] == "POST":
            out += [f"- `{e['status']}` {mask_pii(e['url'])[:140]}"]
            if "req_body" in e:
                body = json.dumps(e["req_body"], ensure_ascii=False)[:600] \
                    if isinstance(e["req_body"], (dict, list)) else str(e["req_body"])[:600]
                out.append(f"  - body: `{mask_pii(body)}`")

    snaps = sorted(ART.glob("*.txt"))
    out += ["", "## Snapshot salvati", ""]
    for s in snaps:
        out.append(f"- `{s.name}` ({s.stat().st_size} byte)")

    REPORT.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
