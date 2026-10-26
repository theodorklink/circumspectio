#!/usr/bin/env python3
"""
Circumspectio – Wochenausgabe am Sonntag per Claude API, Versand über SendGrid.

Ablauf:
  1. Zeitfenster prüfen (Sonntag 7:00 Uhr Berlin, Sommer-/Winterzeit automatisch)
  2. Vorwochen-Ausgaben aus archiv/ laden, damit sich nichts doppelt
  3. Claude recherchiert per Websuche die zurückliegende Woche und liefert JSON
  4. Links prüfen (nur gefundene bzw. erreichbare URLs bleiben stehen)
  5. Diagramme (matplotlib) erzeugen, keine Fotos
  6. HTML rendern (Mail + vollständige HTML-Datei)
  7. Per SendGrid versenden, terminiert auf 7:00 Uhr, Ausgabe in archiv/ ablegen

Lokal testen ohne API-Kosten:
  python briefing.py --aus-json beispiel.json --dry-run
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
import matplotlib
import matplotlib.ticker  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
ARCHIV = ROOT / "archiv"
TZ = ZoneInfo("Europe/Berlin")


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = (os.getenv(name) or "").strip() or default
    if required and not value:
        sys.exit(f"Fehlende Umgebungsvariable / fehlendes Secret: {name}")
    return value


MODEL = env("CLAUDE_MODEL", "claude-sonnet-5-5")
EFFORT = env("CLAUDE_EFFORT", "high")          # "medium" ist günstiger
MAX_SEARCHES = int(env("MAX_SEARCHES", "40"))
MAX_TOKENS = int(env("MAX_TOKENS", "64000"))
SEND_HOUR = int(env("SEND_HOUR", "7"))
VORLAUF_H = 2                                   # Start zwei Stunden vor Versand
TITLE = env("NEWSLETTER_TITLE", "Circumspectio")
AUSGABE_START = env("AUSGABE_START", "2026-11-01")  # Sonntag der Wochenausgabe Nr. 1
VORWOCHEN = int(env("VORWOCHEN", "3"))           # so viele frühere Ausgaben gegen Doppelungen

BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
}

# Farben (auch für Diagramme)
INK = "#1B1B1B"
MUTED = "#5F6670"
RULE = "#D5D8DD"
ACCENT = "#1F3A5F"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


def datum_de(d: dt.datetime | dt.date) -> str:
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


def kurzdatum(d: dt.date) -> str:
    return f"{d.day}. {MONATE[d.month - 1]}"


def zeitraum(now: dt.datetime) -> tuple[dt.date, dt.date]:
    """Berichtswoche: Sonntag der Vorwoche bis heute."""
    return (now.date() - dt.timedelta(days=7), now.date())


# ---------------------------------------------------------------------------
# 1. Zeitfenster
# ---------------------------------------------------------------------------
def im_zeitfenster(now: dt.datetime) -> bool:
    """GitHub-Cron läuft in UTC. Der Workflow startet zweimal (für Sommer- und
    Winterzeit); hier wird der Lauf gewählt, der VORLAUF_H Stunden vor SEND_HOUR liegt."""
    if env("SOFORT", "false").lower() == "true":
        return True
    sched = env("CRON_SCHEDULE", "")
    if not sched:
        return True  # lokaler Lauf
    offset_h = int(now.utcoffset().total_seconds() // 3600)
    erwartet = (SEND_HOUR - VORLAUF_H - offset_h) % 24
    try:
        cron_stunde = int(sched.split()[1])
    except (IndexError, ValueError):
        return True
    if cron_stunde != erwartet:
        print(f"Übersprungen: Cron '{sched}' ist heute nicht zuständig (erwartet UTC-Stunde {erwartet}).")
        return False
    return True


# ---------------------------------------------------------------------------
# 2. Vorwochen (gegen Doppelungen)
# ---------------------------------------------------------------------------
def vorwochen_laden(now: dt.datetime) -> list[tuple[dt.date, dict]]:
    if not ARCHIV.exists():
        return []
    ausgaben = []
    for f in sorted(ARCHIV.glob("*.json"), reverse=True):
        try:
            datum = dt.date.fromisoformat(f.stem)
        except ValueError:
            continue
        if datum >= now.date():
            continue
        try:
            ausgaben.append((datum, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as e:
            print(f"Archiv {f.name} nicht lesbar: {e}")
        if len(ausgaben) >= VORWOCHEN:
            break
    return ausgaben


def erster_satz(text: str | None) -> str:
    text = (text or "").strip().split("\n")[0]
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text)[:300]


def vorwochen_text(ausgaben: list[tuple[dt.date, dict]]) -> str:
    if not ausgaben:
        return ("Es gibt noch keine frühere Wochenausgabe im Archiv. "
                "Die Regel gegen Doppelungen entfällt diesmal.")
    teile = ["Bereits behandelt in den letzten Ausgaben (nicht wiederholen, nur echte "
             "neue Entwicklungen aufgreifen, siehe Abschnitt „Keine Doppelungen“):"]
    for datum, d in ausgaben:
        z = [f"\n### Ausgabe vom {datum_de(datum)}"]
        if d.get("woche_in_einem_satz"):
            z.append(f"Die Woche in einem Satz: {d['woche_in_einem_satz']}")
        if d.get("leitartikel_titel"):
            z.append(f"Leitartikel: {d['leitartikel_titel']} – {erster_satz(d.get('leitartikel'))}")
        for a in d.get("analysen") or []:
            z.append(f"Analyse: {a.get('titel', '')} – {erster_satz(a.get('text'))} "
                     f"Worauf achten: {a.get('worauf_achten') or '–'}")
        for s in d.get("die_woche") or []:
            z.append(f"Meldung ({s.get('region', '')}): {s.get('titel', '')}")
        for n in d.get("nachgehakt") or []:
            z.append(f"Nachgehakt: {n.get('titel', '')}")
        for r in d.get("am_horizont") or []:
            z.append(f"Am Horizont: {r.get('titel', '')}")
        teile.append("\n".join(z))
    return "\n".join(teile)


# ---------------------------------------------------------------------------
# 3. Recherche mit Claude
# ---------------------------------------------------------------------------
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|ocid$|at_)", re.I)


def norm_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
    host = p.netloc.lower().removeprefix("www.")
    return urlunsplit(("https", host, p.path.rstrip("/"), query, ""))


def claude_aufruf(client, **kwargs):
    """Gestreamter Aufruf (nötig bei großen max_tokens), Effort und Thinking
    über extra_body, damit es mit jeder aktuellen SDK-Version funktioniert."""
    effort = kwargs.pop("effort", EFFORT)
    with client.messages.stream(
        model=MODEL,
        extra_body={"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}},
        **kwargs,
    ) as stream:
        return stream.get_final_message()


def recherchieren(now: dt.datetime, vorwochen: str) -> tuple[dict, set[str]]:
    import anthropic

    client = anthropic.Anthropic(timeout=1800.0, max_retries=3)  # ANTHROPIC_API_KEY aus Umgebung
    system = (ROOT / "prompt.md").read_text(encoding="utf-8")
    messages = [{
        "role": "user",
        "content": (f"Heute ist {datum_de(now)}, {now:%H:%M} Uhr in Berlin. "
                    f"Erstelle die Wochenausgabe für die Woche von {datum_de(zeitraum(now)[0])} "
                    f"bis heute früh. Recherchiere zuerst gründlich, dann gib das JSON aus.\n\n"
                    f"{vorwochen}"),
    }]
    tools = [{
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": MAX_SEARCHES,
        "user_location": {"type": "approximate", "country": "DE", "city": "Berlin",
                          "timezone": "Europe/Berlin"},
    }]

    texte: list[str] = []
    gesehen: set[str] = set()
    for runde in range(1, 9):
        msg = claude_aufruf(client, max_tokens=MAX_TOKENS, system=system,
                            messages=messages, tools=tools)
        for block in msg.content:
            if block.type == "web_search_tool_result" and isinstance(block.content, list):
                for treffer in block.content:
                    if getattr(treffer, "url", None):
                        gesehen.add(norm_url(treffer.url))
            elif block.type == "text":
                texte.append(block.text)
        u = msg.usage
        suchen = getattr(getattr(u, "server_tool_use", None), "web_search_requests", "?")
        print(f"Runde {runde}: stop={msg.stop_reason}, input={u.input_tokens}, "
              f"output={u.output_tokens}, suchen={suchen}")
        if msg.stop_reason == "pause_turn":       # lange Recherche: fortsetzen
            messages.append({"role": "assistant", "content": msg.content})
            continue
        if msg.stop_reason == "max_tokens":
            sys.exit("Antwort abgeschnitten (max_tokens). MAX_TOKENS erhöhen.")
        break

    print(f"{len(gesehen)} URLs in Suchergebnissen gesehen.")
    return json_extrahieren("".join(texte), client), gesehen


CITE_TAG = re.compile(r"</?(?:[\w-]+:)?cite\b[^>]*>", re.I)


def json_extrahieren(roh: str, client=None) -> dict:
    # Mit Websuche setzt Claude manchmal Quellenmarken wie <cite index='50-11'>…</cite>
    # in den Text. Die Quellen stehen ohnehin als Links im Briefing, also entfernen.
    roh = CITE_TAG.sub("", roh)
    m = re.search(r"<briefing_json>\s*(.*?)\s*</briefing_json>", roh, re.S)
    kandidat = m.group(1) if m else roh[roh.find("{"): roh.rfind("}") + 1]
    kandidat = re.sub(r"^```(?:json)?\s*|\s*```$", "", kandidat.strip())
    try:
        return json.loads(kandidat)
    except json.JSONDecodeError as e:
        print("JSON fehlerhaft, Reparaturversuch:", e)
        OUT.mkdir(exist_ok=True)
        (OUT / "roh_antwort.txt").write_text(roh, encoding="utf-8")
        if client is None:
            raise
    msg = claude_aufruf(
        client, effort="low", max_tokens=32000,
        messages=[{"role": "user", "content":
                   "Repariere das folgende JSON, sodass es gültig ist. Inhalt nicht verändern. "
                   "Antworte ausschließlich mit dem JSON.\n\n" + kandidat}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


# ---------------------------------------------------------------------------
# 4. Links prüfen
# ---------------------------------------------------------------------------
_link_cache: dict[str, bool] = {}


def link_ok(url, gesehen: set[str]) -> bool:
    if not url or not str(url).startswith("http"):
        return False
    n = norm_url(url)
    if n in gesehen:
        return True
    if n not in _link_cache:
        ok = False
        try:
            r = requests.get(url, headers=BROWSER_UA, timeout=15, allow_redirects=True, stream=True)
            ok = r.status_code < 400
            r.close()
        except requests.RequestException:
            pass
        _link_cache[n] = ok
        if not ok:
            print("Link verworfen:", url)
    return _link_cache[n]


def links_pruefen(d: dict, gesehen: set[str]) -> None:
    for liste in ("die_woche", "nachgehakt", "am_horizont"):
        for s in d.get(liste) or []:
            if not link_ok(s.get("link"), gesehen):
                s["link"] = None
    for h in d.get("analysen") or []:
        h["links"] = [l for l in (h.get("links") or []) if link_ok(l.get("url"), gesehen)]
    for liste in ("hoertipps", "zum_lesen"):
        d[liste] = [p for p in (d.get(liste) or []) if link_ok(p.get("url"), gesehen)]
    z = d.get("zitat_der_woche")
    if z and not link_ok(z.get("url"), gesehen):
        z["url"] = None


# ---------------------------------------------------------------------------
# 5. Diagramme
# ---------------------------------------------------------------------------
def zahl_de(v: float) -> str:
    s = f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s[:-2] if s.endswith(",0") else s


def diagramm_png(spec: dict) -> bytes | None:
    try:
        labels = [str(x) for x in spec.get("labels") or []][:12]
        werte = [float(v) for v in spec.get("werte") or []][:12]
    except (TypeError, ValueError):
        return None
    if len(labels) != len(werte) or len(werte) < 2:
        return None

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
        "font.size": 12,
        "axes.edgecolor": RULE,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
    })
    fig, ax = plt.subplots(figsize=(8, 3.9), dpi=150)
    if spec.get("typ") == "linie":
        ax.plot(labels, werte, color=ACCENT, linewidth=2.2, marker="o", markersize=4)
        ax.annotate(zahl_de(werte[-1]), (len(werte) - 1, werte[-1]), textcoords="offset points",
                    xytext=(6, 6), fontsize=11, color=ACCENT)
    else:
        balken = ax.bar(labels, werte, color=ACCENT, width=0.62)
        ax.bar_label(balken, labels=[zahl_de(v) for v in werte], padding=3, fontsize=10, color=INK)
    for seite in ("top", "right", "left"):
        ax.spines[seite].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.margins(y=0.15)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: zahl_de(v)))
    ax.grid(axis="y", color=RULE, linewidth=0.6)
    ax.set_axisbelow(True)
    if spec.get("einheit"):
        ax.set_ylabel(spec["einheit"])
    if max(len(l) for l in labels) > 8:
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    ax.set_title(spec.get("titel", ""), loc="left", fontsize=15, color=INK, pad=12)
    if spec.get("quelle"):
        fig.text(0.01, 0.01, f"Quelle: {spec['quelle']}", fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def medien_erzeugen(d: dict) -> dict[str, dict]:
    """Nur Logo und Diagramme mit belegten Zahlen. Fotos gibt es keine mehr."""
    medien: dict[str, dict] = {}
    for cid, datei in (("logo", "logo.png"), ("zeichen", "zeichen.png")):
        pfad = ROOT / "assets" / datei
        if pfad.exists():
            medien[cid] = {"data": pfad.read_bytes(), "mime": "image/png", "datei": datei}
    for i, h in enumerate(d.get("analysen") or [], start=1):
        if h.get("diagramm"):
            png = diagramm_png(h["diagramm"])
            if png:
                cid = f"grafik{i}"
                medien[cid] = {"data": png, "mime": "image/png", "datei": f"{cid}.png"}
                h["diagramm_cid"] = cid
    return medien


# ---------------------------------------------------------------------------
# 6. Rendern
# ---------------------------------------------------------------------------
REGIONEN = ["Deutschland", "Europa", "Welt"]


def gruppieren(meldungen: list[dict]) -> list[tuple[str, list[dict]]]:
    gruppen: dict[str, list[dict]] = {}
    for s in meldungen or []:
        gruppen.setdefault((s.get("region") or "Welt").strip(), []).append(s)
    reihenfolge = sorted(gruppen, key=lambda r: REGIONEN.index(r) if r in REGIONEN else 99)
    return [(r, gruppen[r]) for r in reihenfolge]


def absaetze(text, style: str = "") -> Markup:
    if not text:
        return Markup("")
    teile = [t.strip() for t in re.split(r"\n\s*\n", str(text)) if t.strip()]
    return Markup("".join(f'<p style="{escape(style)}">{escape(t)}</p>' for t in teile))


def roemisch(n: int) -> str:
    s = ""
    for wert, zeichen in [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]:
        while n >= wert:
            s, n = s + zeichen, n - wert
    return s


def lesezeit(d: dict) -> int:
    def woerter(x):
        if isinstance(x, str):
            return len(x.split())
        if isinstance(x, dict):
            return sum(woerter(v) for k, v in x.items() if k not in ("url", "link", "werte", "labels"))
        if isinstance(x, list):
            return sum(woerter(v) for v in x)
        return 0
    return max(1, round(woerter(d) / 220))


def ausgabe_nr(now: dt.datetime) -> int:
    try:
        start = dt.date.fromisoformat(AUSGABE_START)
    except ValueError:
        return 1
    return max(1, (now.date() - start).days // 7 + 1)


def rendern(d: dict, medien: dict, now: dt.datetime, modus: str) -> str:
    jinja = Environment(loader=FileSystemLoader(ROOT),
                        autoescape=select_autoescape(["html", "j2"]))
    jinja.filters["absaetze"] = absaetze
    jinja.filters["roemisch"] = roemisch

    def src(cid: str) -> str:
        if modus == "cid":
            return f"cid:{cid}"
        m = medien[cid]
        return f"data:{m['mime']};base64,{base64.b64encode(m['data']).decode()}"

    for r in d.get("am_horizont") or []:
        try:
            r["signal"] = min(3, max(1, int(r.get("signal") or 1)))
        except (TypeError, ValueError):
            r["signal"] = 1

    von, bis = zeitraum(now)
    return jinja.get_template("template.html.j2").render(
        d=d, gruppen=gruppieren(d.get("die_woche")), titel=TITLE,
        datum=datum_de(now), uhrzeit=now.strftime("%H:%M"), modell=MODEL, src=src,
        medien=medien, nr=ausgabe_nr(now), lesezeit=lesezeit(d),
        zeitraum=f"{kurzdatum(von)} bis {kurzdatum(bis)} {bis.year}")


def klartext(d: dict, now: dt.datetime) -> str:
    z = [f"{TITLE} – Wochenausgabe, {datum_de(now)}", "", d.get("woche_in_einem_satz") or "", ""]
    if d.get("leitartikel"):
        z += [(d.get("leitartikel_titel") or "Die Woche im Zusammenhang").upper(), "",
              d["leitartikel"], ""]
    for h in d.get("analysen") or []:
        z += [h.get("titel", "").upper(), "", h.get("text", ""), ""]
        for a in h.get("akteure") or []:
            z.append(f"- {a.get('name', '')}: will {a.get('will', '')}")
        for v in h.get("von_allen_seiten") or []:
            z.append(f"- {v.get('sicht', '')}: {v.get('lesart', '')}")
        z += ["", "Hinter den Kulissen: " + (h.get("hinter_den_kulissen") or ""), ""]
    for region, items in gruppieren(d.get("die_woche")):
        z += [region.upper(), ""]
        for s in items:
            z += [f"- {s.get('titel', '')}", f"  {s.get('kurz', '')}"]
            if s.get("link"):
                z.append(f"  {s['link']}")
            z.append("")
    z.append("Die vollständige Ausgabe steht in der HTML-Ansicht.")
    return "\n".join(z)


# ---------------------------------------------------------------------------
# 7. Versand über SendGrid
# ---------------------------------------------------------------------------
def senden(html_mail: str, html_datei: str, text: str, medien: dict, now: dt.datetime) -> None:
    key = env("SENDGRID_API_KEY", required=True)
    absender = env("MAIL_FROM", required=True)
    empfaenger = [e.strip() for e in env("MAIL_TO", required=True).split(",") if e.strip()]
    host = env("SENDGRID_API_HOST", "https://api.sendgrid.com")  # EU-Konten: https://api.eu.sendgrid.com

    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    anhaenge = [{"content": b64(m["data"]), "type": m["mime"], "filename": m["datei"],
                 "disposition": "inline", "content_id": cid} for cid, m in medien.items()]
    if env("HTML_ANHANG", "true").lower() == "true":
        anhaenge.append({"content": b64(html_datei.encode("utf-8")), "type": "text/html",
                         "filename": f"circumspectio-{now:%Y-%m-%d}.html", "disposition": "attachment"})

    payload = {
        "personalizations": [{"to": [{"email": e}]} for e in empfaenger],
        "from": {"email": absender, "name": env("MAIL_FROM_NAME", TITLE)},
        "subject": f"{TITLE} Nr. {ausgabe_nr(now)} | Die Woche bis {datum_de(now)}",
        "content": [{"type": "text/plain", "value": text},
                    {"type": "text/html", "value": html_mail}],
        "attachments": anhaenge,
        # Ohne Tracking: Links führen direkt zu FAZ, FT usw. (Login bleibt erhalten)
        "tracking_settings": {"click_tracking": {"enable": False, "enable_text": False},
                              "open_tracking": {"enable": False}},
    }
    if env("SOFORT", "false").lower() != "true":
        ziel = now.replace(hour=SEND_HOUR, minute=0, second=0, microsecond=0)
        if (ziel - now).total_seconds() > 120:
            payload["send_at"] = int(ziel.timestamp())
            print(f"Versand terminiert auf {ziel:%H:%M} Uhr.")

    r = requests.post(f"{host}/v3/mail/send", json=payload, timeout=60,
                      headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 202:
        sys.exit(f"SendGrid-Fehler {r.status_code}: {r.text}")
    print(f"An {len(empfaenger)} Empfänger übergeben.")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument("--aus-json", help="Vorhandenes Briefing-JSON verwenden (keine API-Kosten)")
    ap.add_argument("--dry-run", action="store_true", help="Nur erzeugen, nicht senden")
    args = ap.parse_args()
    dry = args.dry_run or env("DRY_RUN", "false").lower() == "true"

    now = dt.datetime.now(TZ)
    OUT.mkdir(exist_ok=True)

    if args.aus_json:
        daten, gesehen = json.loads(Path(args.aus_json).read_text(encoding="utf-8")), None
    else:
        if not im_zeitfenster(now):
            return
        vorwochen = vorwochen_laden(now)
        print(f"{len(vorwochen)} frühere Ausgabe(n) als Abgleich gegen Doppelungen geladen.")
        daten, gesehen = recherchieren(now, vorwochen_text(vorwochen))
        (OUT / "briefing.json").write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")

    if gesehen is not None:
        links_pruefen(daten, gesehen)
    medien = medien_erzeugen(daten)
    html_mail = rendern(daten, medien, now, "cid")
    html_datei = rendern(daten, medien, now, "data")
    (OUT / "circumspectio.html").write_text(html_datei, encoding="utf-8")
    print(f"HTML erzeugt: {len(html_mail) // 1024} KB (Mail), {len(medien)} Grafiken.")

    if dry:
        print("Dry-Run: nichts versendet. Ergebnis in out/circumspectio.html")
        return
    senden(html_mail, html_datei, klartext(daten, now), medien, now)

    # Ausgabe ins Archiv, damit die nächste Woche weiß, was schon lief
    if not args.aus_json:
        ARCHIV.mkdir(exist_ok=True)
        (ARCHIV / f"{now:%Y-%m-%d}.json").write_text(
            json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Archiviert: archiv/{now:%Y-%m-%d}.json")


if __name__ == "__main__":
    main()
