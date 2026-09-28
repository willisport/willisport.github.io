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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN_PATH = os.path.join(ROOT, "data", "plan-template.json")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


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
    send(prefix + format_message(target, day))
    print("gesendet:", mode, target.strftime("%Y-%m-%d"))


if __name__ == "__main__":
    main()
