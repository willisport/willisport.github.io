"""Aktien-News fuer Willi per Telegram - laeuft in GitHub Actions (kostenlos, kein PC, kein Claude, keine Bezahldienste).

Quellen (alle ohne Key): Google-News-RSS (Schlagzeilen) und Yahoo-Finance-Chart-Endpunkt (Tagesaenderung).
Es werden KEINE Bestaende, Betraege oder Konto-Daten gespeichert - nur die Namen/Ticker der Beobachtungsliste.

Modi:
  auto    Standard im Workflow: sendet Zusammenfassung (digest) zu den eingestellten Uhrzeiten und
          Alarme (alert), wenn etwas Krasses passiert (grosse Kursbewegung oder Schluesselwoerter wie
          Ruecktritt, Untersuchung, Klage, Sanktionen ...). Jeder Alarm hoechstens einmal.
  digest  sendet sofort die Zusammenfassung
  alert   prueft sofort auf Alarme und sendet sie
  test    wie auto, aber nur auf dem Bildschirm (kein Telegram, kein State)

Beobachtungsliste: env STOCK_WATCHLIST (JSON-Liste) oder DEFAULT_WATCHLIST unten.
Keine Anlageberatung - die Nachrichten sind Informationen, keine Kauf-/Verkaufsempfehlungen.
"""

import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "stocks-state.json")
BERLIN = ZoneInfo("Europe/Berlin")

# name: Anzeigename, query: Suchbegriff fuer die News, ticker: Yahoo-Symbol fuer den Kurs
DEFAULT_WATCHLIST = [
    {"name": "Nvidia", "query": "Nvidia Aktie", "ticker": "NVDA"},
    {"name": "IonQ", "query": "IonQ Aktie", "ticker": "IONQ"},
    {"name": "Microsoft", "query": "Microsoft Aktie", "ticker": "MSFT"},
    {"name": "Xiaomi", "query": "Xiaomi Aktie", "ticker": "1810.HK"},
]

DIGEST_TIMES = ("08:00", "22:15")      # Berliner Zeit
ALERT_WINDOW = (8, 23)                 # Alarme nur von 08:00 bis 23:00 Berliner Zeit
LATE_WINDOW_MIN = 120                  # verspaetete Laeufe werden bis zu 2 h nachgeholt
MOVE_ALERT_PCT = 5.0                   # Tagesbewegung, ab der ein Alarm kommt
NEWS_MAX_AGE_H = 30                    # nur Schlagzeilen der letzten 30 Stunden
MAX_NEWS_ALERTS_PER_DAY = 2            # je Wert und Tag hoechstens so viele Schlagzeilen-Alarme
HEADLINES_PER_STOCK = 3

# Schluesselwoerter, bei denen eine Schlagzeile als "krass" gilt (klein geschrieben)
ALERT_WORDS = [
    "rücktritt", "zurückgetreten", "entlassen", "untersuchung", "ermittlung", "klage", "razzia",
    "sanktion", "exportverbot", "exportbeschränkung", "verbot", "insolvenz", "pleite", "betrug",
    "übernahme", "fusion", "prognose gesenkt", "prognose angehoben", "gewinnwarnung", "kurssturz",
    "absturz", "kursrutsch", "handelsstopp", "rückruf",
    "resign", "steps down", "fired", "investigation", "lawsuit", "sued", "export ban", "sanction",
    "bankruptcy", "fraud", "acquisition", "merger", "guidance", "plunge", "crash", "halted", "recall",
]

# Kleine Merkhilfen: worauf achten, je nach Art der Meldung
TIPS = [
    (("rücktritt", "zurückgetreten", "entlassen", "resign", "steps down", "fired"),
     "Chefwechsel: Wer folgt? Unsicherheit bewegt den Kurs oft stark - erst Fakten, dann entscheiden."),
    (("untersuchung", "ermittlung", "investigation", "klage", "lawsuit", "sued", "razzia", "betrug", "fraud"),
     "Rechtliche Risiken: Ausgang offen, kann lange dauern. Offizielle Mitteilung der Firma prüfen."),
    (("sanktion", "export", "verbot", "ban"),
     "Politik/Handel: Betrifft oft das China-Geschäft. Welcher Umsatzanteil hängt dran?"),
    (("prognose", "guidance", "gewinnwarnung"),
     "Ausblick zählt oft mehr als die Zahlen selbst. Besser/schlechter als erwartet?"),
    (("übernahme", "fusion", "acquisition", "merger"),
     "Zukauf: Wie wird bezahlt (Geld oder neue Aktien = Verwässerung)? Schulden?"),
    (("kurssturz", "absturz", "kursrutsch", "plunge", "crash"),
     "Großer Kursrückgang: Ursache klären - firmenspezifisch oder ganzer Markt? Kein Panikverkauf/-kauf."),
    (("insolvenz", "pleite", "bankruptcy"),
     "Insolvenz: Totalverlust-Risiko, bei Hebelprodukten sofort prüfen."),
]
DISCLAIMER = "ℹ️ Info, keine Anlageberatung. Kurse können verzögert sein - Live-Kurs in der App prüfen."


# ---------------------------------------------------------------------------
# Daten holen
# ---------------------------------------------------------------------------

def load_watchlist():
    raw = os.environ.get("STOCK_WATCHLIST")
    if raw:
        try:
            lst = json.loads(raw)
            if isinstance(lst, list) and lst:
                return [w for w in lst if isinstance(w, dict) and w.get("name") and w.get("query")]
        except Exception as e:
            print("STOCK_WATCHLIST ungueltig, nehme Standardliste:", e)
    return DEFAULT_WATCHLIST


def fetch_news(query, now_utc=None, max_age_h=NEWS_MAX_AGE_H):
    """Aktuelle Schlagzeilen (neueste zuerst) aus Google News. Liste von dict(title, source, link, time)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=de&gl=DE&ceid=DE:de"
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        source = (it.findtext("source") or "").strip()
        try:
            t = parsedate_to_datetime(it.findtext("pubDate"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if now_utc - t > timedelta(hours=max_age_h):
            continue
        # Google haengt " - Quelle" an den Titel
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        items.append({"title": title, "source": source, "link": link, "time": t})
    items.sort(key=lambda x: x["time"], reverse=True)
    return items


def fetch_move(ticker):
    """Aenderung zum Vortagesschluss in Prozent (oder None). Yahoo-Chart-Endpunkt, kostenlos."""
    if not ticker:
        return None
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(ticker)}",
            params={"interval": "1d", "range": "5d"},
            timeout=15, headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        price, prev = meta["regularMarketPrice"], meta["chartPreviousClose"]
        return {"price": price, "pct": (price - prev) / prev * 100, "currency": meta.get("currency", "")}
    except Exception as e:
        print(f"Kurs {ticker} nicht abrufbar: {type(e).__name__}")
        return None


# ---------------------------------------------------------------------------
# Auswerten und formatieren
# ---------------------------------------------------------------------------

def hit_words(title):
    low = title.lower()
    return [w for w in ALERT_WORDS if w in low]


def tip_for(title):
    low = title.lower()
    for words, tip in TIPS:
        if any(w in low for w in words):
            return tip
    return None


def de_pct(x):
    return f"{x:+.1f} %".replace(".", ",")


def format_digest(entries, now):
    lines = [f"📰 Aktien-Update {now.strftime('%d.%m. %H:%M')}", ""]
    for e in entries:
        mv = e["move"]
        head = f"• {e['name']}"
        if mv:
            arrow = "🔺" if mv["pct"] >= 0 else "🔻"
            head += f" {arrow} {de_pct(mv['pct'])} ({mv['price']:.2f} {mv['currency']})"
        lines.append(head)
        shown = e["news"][:HEADLINES_PER_STOCK]
        if not shown:
            lines.append("   keine neuen Meldungen")
        for n in shown:
            flag = "⚠️ " if hit_words(n["title"]) else ""
            lines.append(f"   {flag}{n['title'][:140]} ({n['source']})")
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)[:3900]


def alert_id(name, kind, text):
    return hashlib.sha1(f"{name}|{kind}|{text}".encode("utf-8")).hexdigest()[:16]


def find_alerts(entries, now, state):
    """Neue Alarme: grosse Tagesbewegung (einmal pro Tag/Richtung) oder Schluesselwort-Schlagzeile.
    Gegen Nachrichten-Flut: je Wert und Lauf nur die NEUESTE Schluesselwort-Schlagzeile, je Wert und Tag
    hoechstens MAX_NEWS_ALERTS_PER_DAY; die uebrigen werden still als gesehen markiert.
    Rueckgabe: (zu sendende Alarme [(id, text)], still gesehene ids)."""
    sent = set(state.get("alerts") or [])
    out, silent = [], []
    day = now.date().isoformat()
    counts = state.get("news_counts") or {}
    for e in entries:
        mv = e["move"]
        if mv and abs(mv["pct"]) >= MOVE_ALERT_PCT:
            direction = "up" if mv["pct"] > 0 else "down"
            aid = alert_id(e["name"], "move", f"{now.date()}|{direction}")
            if aid not in sent:
                emoji = "🚀" if mv["pct"] > 0 else "🚨"
                out.append((aid, f"{emoji} {e['name']}: {de_pct(mv['pct'])} heute ({mv['price']:.2f} {mv['currency']})\n"
                                 "→ Grund in den Nachrichten prüfen. Bei Hebelprodukten: Abstand zur Knock-out-Schwelle checken."))
        key = f"{day}|{e['name']}"
        picked = False
        for n in e["news"]:          # neueste zuerst
            if not hit_words(n["title"]):
                continue
            aid = alert_id(e["name"], "news", n["title"])
            if aid in sent:
                continue
            if picked or counts.get(key, 0) >= MAX_NEWS_ALERTS_PER_DAY:
                silent.append(aid)
                continue
            picked = True
            counts[key] = counts.get(key, 0) + 1
            tip = tip_for(n["title"])
            text = f"⚠️ {e['name']}: {n['title'][:200]} ({n['source']})"
            if tip:
                text += f"\n→ {tip}"
            out.append((aid, text))
    state["news_counts"] = {k: v for k, v in counts.items() if k.startswith(day)}
    return out, silent


# ---------------------------------------------------------------------------
# Zeitsteuerung, State, Telegram
# ---------------------------------------------------------------------------

def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    state["alerts"] = (state.get("alerts") or [])[-300:]
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def due_digests(now, state):
    out = []
    day = now.date().isoformat()
    if now.weekday() >= 5:    # Wochenende: keine Zusammenfassung, nur Alarme bei krassen Meldungen
        return out
    for t in DIGEST_TIMES:
        h, m = (int(x) for x in t.split(":"))
        sched = now.replace(hour=h, minute=m, second=0, microsecond=0)
        key = f"digest_{t}"
        if sched <= now < sched + timedelta(minutes=LATE_WINDOW_MIN) and state.get(key) != day:
            out.append(key)
    return out


def send(text):
    token, chat_id = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}, timeout=15)
    resp.raise_for_status()


def collect(watchlist):
    entries = []
    for w in watchlist:
        try:
            news = fetch_news(w["query"])
        except Exception as e:
            print(f"News {w['name']} nicht abrufbar: {type(e).__name__}: {e}")
            news = []
        entries.append({"name": w["name"], "news": news, "move": fetch_move(w.get("ticker"))})
    return entries


def run(mode="auto", now=None, send_fn=None, watchlist=None):
    now = now or datetime.now(BERLIN)
    dry = mode == "test"
    send_fn = (lambda t: print("----- Telegram (Test) -----\n" + t + "\n")) if dry else (send_fn or send)
    state = {} if dry else load_state()
    sent = []

    if mode in ("auto", "test"):
        digests = due_digests(now, state)
        if dry:
            digests = digests or ["digest_test"]
    else:
        digests = ["digest_manual"] if mode == "digest" else []
    in_alert_window = ALERT_WINDOW[0] <= now.hour < ALERT_WINDOW[1]
    want_alerts = mode in ("alert", "test") or (mode == "auto" and in_alert_window)
    if not digests and not want_alerts:
        print("Aktien: nichts faellig")
        return sent

    entries = collect(watchlist or load_watchlist())

    for key in digests:
        try:
            send_fn(format_digest(entries, now))
            state[key] = now.date().isoformat()
            sent.append(key)
        except Exception as e:
            print(f"Aktien: {key} fehlgeschlagen ({type(e).__name__}: {e})")
    if want_alerts:
        alerts, silent = find_alerts(entries, now, state)
        state["alerts"] = (state.get("alerts") or []) + silent
        for aid, text in alerts:
            try:
                send_fn(text + "\n\n" + DISCLAIMER)
                state["alerts"] = (state.get("alerts") or []) + [aid]
                sent.append("alert:" + aid)
            except Exception as e:
                print(f"Aktien: Alarm fehlgeschlagen ({type(e).__name__}: {e})")
    if (sent or want_alerts) and not dry:
        save_state(state)
    return sent


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    sent = run(mode)
    print("gesendet:", sent if sent else "nichts")


if __name__ == "__main__":
    main()
