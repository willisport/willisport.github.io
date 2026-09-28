"""Schickt Willi per Telegram, was heute (morgens) bzw. morgen (abends) anliegt.

Liest nur data/plan-template.json (oeffentlich, keine Verschluesselung noetig) -
Fokus-Text pro Tag enthaelt bereits Arbeit/Fahrt/Schulung, dazu die geplanten
Trainingseinheiten. Laeuft in GitHub Actions, kein lokaler PC noetig.
"""

import json
import os
import sys
from datetime import datetime, timedelta

import requests

import mail_check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN_PATH = os.path.join(ROOT, "data", "plan-template.json")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Berlin-Adlershof - kein API-Key noetig (Open-Meteo ist komplett kostenlos).
WEATHER_LAT, WEATHER_LON = 52.435, 13.541
WEATHER_CODES = {
    0: "Klar", 1: "Meist klar", 2: "Teils bewölkt", 3: "Bewölkt",
    45: "Nebel", 48: "Nebel (Reif)", 51: "Leichter Nieselregen", 53: "Nieselregen", 55: "Starker Nieselregen",
    61: "Leichter Regen", 63: "Regen", 65: "Starker Regen", 71: "Leichter Schnee", 73: "Schnee", 75: "Starker Schnee",
    80: "Regenschauer", 81: "Regenschauer", 82: "Heftige Regenschauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Starkes Gewitter mit Hagel",
}


def get_weather(target_date):
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": WEATHER_LAT, "longitude": WEATHER_LON,
                "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,weathercode",
                "timezone": "Europe/Berlin",
            },
            timeout=10,
        )
        resp.raise_for_status()
        d = resp.json()["daily"]
        idx = d["time"].index(target_date.strftime("%Y-%m-%d"))
        code = d["weathercode"][idx]
        lo, hi = round(d["temperature_2m_min"][idx]), round(d["temperature_2m_max"][idx])
        rain = d["precipitation_probability_max"][idx]
        return f"🌤️ {WEATHER_CODES.get(code, 'Wetter')}, {lo}–{hi}°C, Regenwahrscheinlichkeit {rain} %"
    except Exception as e:
        return f"🌤️ Wetter nicht abrufbar ({e})"


def load_plan():
    with open(PLAN_PATH, encoding="utf-8") as f:
        return json.load(f)


def monday_of(d):
    return d - timedelta(days=d.weekday())


def day_for_date(plan, d):
    wd = WEEKDAYS[d.weekday()]
    mon = monday_of(d).strftime("%Y-%m-%d")
    override = plan.get("weekOverrides", {}).get(mon, {}).get("days", {}).get(wd)
    if override:
        return override
    return next(day for day in plan["weekPattern"] if day["weekday"] == wd)


def format_message(d, day):
    de_wd = WEEKDAYS[d.weekday()]
    header = f"{de_wd}, {d.strftime('%d.%m.%Y')}"
    lines = [f"📋 {header}", day.get("focus", ""), ""]

    icons = {"lauf": "🏃", "rad": "🚴", "kraft": "🏋️", "core": "🧘", "emom": "🔥"}
    for u in day.get("units", []):
        icon = icons.get(u.get("type"), "•")
        lines.append(f"{icon} {u['name']}: {u.get('detail', '')}")

    if not day.get("units"):
        lines.append("Kein Training geplant.")

    return "\n".join(lines).strip()


def get_mail_summary():
    lines = []
    for account, label in (("gmx", "GMX"), ("icloud", "iCloud")):
        try:
            rows = mail_check.scan_unread_important(account)
        except Exception:
            rows = None
        if rows is None:
            continue  # keine Zugangsdaten hinterlegt - Abschnitt einfach weglassen
        if rows:
            top = rows[0]
            extra = f" (u.a. {top['addr']}: {top['subject'][:60]})" if len(rows) else ""
            lines.append(f"📬 {label}: {len(rows)} wichtige ungelesen{extra}")
        else:
            lines.append(f"📬 {label}: nichts Wichtiges offen")
    return "\n".join(lines)


def send(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    resp.raise_for_status()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    plan = load_plan()
    target = datetime.now() + (timedelta(days=1) if mode == "evening" else timedelta(days=0))
    day = day_for_date(plan, target)

    prefix = "☀️ Guten Morgen! Heute steht an:\n\n" if mode == "morning" else "🌙 Für morgen:\n\n"
    body = format_message(target, day)
    weather = get_weather(target)
    mail = get_mail_summary()
    parts = [prefix + body, weather]
    if mail:
        parts.append(mail)
    send("\n\n".join(p for p in parts if p))
    print("gesendet:", mode, target.strftime("%Y-%m-%d"))


if __name__ == "__main__":
    main()
