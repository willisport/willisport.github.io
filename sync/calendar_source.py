"""Termine aus Willis Google-Kalender holen - ueber die private iCal-Adresse
("Geheime Adresse im iCal-Format" in den Kalender-Einstellungen), als Secret
CALENDAR_ICS_URL im Repo hinterlegt. Kostenlos, kein Claude noetig.

Nur LESEN: Termine, die Willi im Google-Kalender (auch am Handy) einträgt, landen
automatisch im Plan. Eigene Trainings-/Arbeitseintraege werden uebersprungen
(sonst waeren sie doppelt, weil die Schichten aus dem Dienstplan kommen).
Keine Netzwerkfehler duerfen den Sync abbrechen - dann laeuft der Plan ohne."""

from __future__ import annotations

import re
import urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

SKIP_TITLE = re.compile(r"^(arbeit|training|fahrt|rückfahrt|rueckfahrt|kraft|rad\b|lauf\b|emom|core|zone)", re.I)
SKIP_PREFIX = ("vorläufig", "vorlaeufig", "datum offen")
SCHOOL = re.compile(r"schul|seminar|ausbildung|unterricht|prüfung|pruefung|klausur|vorlesung|lehrgang|webinar|\buni\b|bwl|ihk", re.I)
ONLINE = re.compile(r"online|digital|zoom|teams|webinar|video", re.I)


def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "basis-sync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _unfold(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text)


def _prop(body: str, name: str):
    m = re.search(rf"^{name}((?:;[^:\n]*)?):(.*)$", body, re.M | re.I)
    return (m.group(1) or "", m.group(2).strip()) if m else None


def _to_local(value: str, params: str):
    """-> (date, 'HH:MM' | None) in Berliner Zeit."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?(Z)?$", value)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not m.group(4):
        return date(y, mo, d), None
    hh, mm, ss = int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)
    if m.group(7):
        dt = datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc).astimezone(BERLIN)
    else:
        tz = re.search(r"TZID=([^;:]+)", params or "", re.I)
        try:
            zone = ZoneInfo(tz.group(1)) if tz else BERLIN
        except Exception:
            zone = BERLIN
        dt = datetime(y, mo, d, hh, mm, ss, tzinfo=zone).astimezone(BERLIN)
    return dt.date(), dt.strftime("%H:%M")


def _unescape(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\N", " ")).strip()


def parse_ics(text: str, from_date: date | None = None) -> list[dict]:
    out = []
    for block in _unfold(text).split("BEGIN:VEVENT")[1:]:
        body = block.split("END:VEVENT")[0]
        ds, de, su, lo, uid = (_prop(body, k) for k in ("DTSTART", "DTEND", "SUMMARY", "LOCATION", "UID"))
        if not ds or not su:
            continue
        if re.search(r"^STATUS:CANCELLED", body, re.M | re.I):
            continue
        title = _unescape(su[1])
        low = title.lower()
        if SKIP_TITLE.match(low) or low.startswith(SKIP_PREFIX):
            continue
        start = _to_local(ds[1], ds[0])
        if not start or start[1] is None:      # ganztaegige Eintraege (Geburtstage, Feiertage) ignorieren
            continue
        end = _to_local(de[1], de[0]) if de else None
        d0 = start[0]
        if from_date and d0 < from_date:
            continue
        loc = _unescape(lo[1]) if lo else ""
        online = bool(ONLINE.search(f"{title} {loc}"))
        e_end = end[1] if end and end[0] == d0 else None
        out.append({
            "id": "g-" + re.sub(r"[^A-Za-z0-9]", "", (uid[1] if uid else f"{d0}{start[1]}{title}"))[:24] + f"-{d0:%m%d}",
            "date": d0.isoformat(), "title": title[:90], "kind": "schule" if SCHOOL.search(title) else "termin",
            "start": start[1], "end": e_end, "travelMin": 0 if online else None, "note": loc[:40], "source": "ics",
        })
    out.sort(key=lambda e: (e["date"], e["start"]))
    return out


def load_events(url: str | None, from_date: date | None = None, fetch=None) -> list[dict]:
    """Gibt [] zurueck, wenn keine URL gesetzt ist oder der Abruf scheitert."""
    if not url:
        return []
    try:
        return parse_ics((fetch or fetch_text)(url), from_date)
    except Exception as e:
        print(f"  [warn] Kalender nicht lesbar ({type(e).__name__}) - Plan laeuft ohne Google-Termine")
        return []


def merge_into_inputs(inputs: dict, ics_events: list[dict]) -> int:
    """Haengt Kalendertermine an die Plan-Eingaben an (Duplikate zu manuell erfassten
    Terminen - gleicher Tag + Startzeit - werden uebersprungen). Gibt die Anzahl zurueck."""
    existing = {(e.get("date"), e.get("start")) for e in inputs.get("events") or []}
    added = [e for e in ics_events if (e["date"], e["start"]) not in existing]
    inputs["events"] = list(inputs.get("events") or []) + added
    return len(added)
