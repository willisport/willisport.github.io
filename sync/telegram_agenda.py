"""Telegram-Nachrichten fuer Willi - laeuft in GitHub Actions (kostenlos, kein PC, kein Claude):

  * morgens (Standard 05:30): was heute ansteht
  * abends  (Standard 20:00): was morgen ansteht
  * Wochenrueckblick (Standard Sonntag 20:00): Soll/Ist, naechste Woche, Vorschlag, Wettkampf-Countdown, Schuhe

Die Uhrzeiten stellt Willi auf der Website ein (Dienstplan -> Einstellungen -> Telegram); sie stehen
verschluesselt in den Overrides (__plan.settings.telegram). Der Sync-Workflow laeuft alle 10 Minuten und
ruft `python telegram_agenda.py auto` auf: gesendet wird, sobald die Uhrzeit (Berliner Zeit, Sommer-/
Winterzeit automatisch) erreicht ist und fuer diesen Tag noch nichts ging (data/telegram-state.json).
Verspaetet sich GitHub, wird bis zu 3 Stunden nachgeholt.

Liest den vom Planer erzeugten Langzeitplan (data/plan.enc.json) bzw. die Tagesdaten
(data/training-data.enc.json), entschluesselt mit DATA_ENCRYPTION_KEY.
Manuell: python telegram_agenda.py morning|evening|weekly (sendet sofort, ohne Statusdatei).
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import mail_check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN_PATH = os.path.join(ROOT, "data", "plan-template.json")
GENERATED_PLAN_PATH = os.path.join(ROOT, "data", "plan.enc.json")
DATA_PATH = os.path.join(ROOT, "data", "training-data.enc.json")
OVERRIDES_PATH = os.path.join(ROOT, "data", "overrides.enc.json")
STATE_PATH = os.path.join(ROOT, "data", "telegram-state.json")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
BERLIN = ZoneInfo("Europe/Berlin")
LATE_WINDOW_MIN = 180   # so lange nach der Wunschzeit wird noch nachgeholt

DEFAULT_CFG = {
    "morning": {"on": True, "time": "05:30"},
    "evening": {"on": True, "time": "20:00"},
    "weekly": {"on": True, "day": 6, "time": "20:00"},   # day: 0 = Montag ... 6 = Sonntag
}

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


def _decrypt_file(path):
    key = os.environ.get("DATA_ENCRYPTION_KEY")
    if not key or not os.path.exists(path):
        return None
    try:
        import crypto_utils
        with open(path, encoding="utf-8") as f:
            return crypto_utils.decrypt_json(crypto_utils.unb64(key), json.load(f))
    except Exception as e:
        print(f"{os.path.basename(path)} nicht lesbar:", e)
        return None


def load_generated_plan():
    """Entschluesselter Langzeitplan oder None (kein Key / Datei fehlt / kaputt)."""
    return _decrypt_file(GENERATED_PLAN_PATH)


def load_training_data():
    return _decrypt_file(DATA_PATH)


def load_config(overrides=None):
    """Telegram-Zeiten aus den Overrides (Website-Einstellungen), mit Standardwerten aufgefuellt."""
    if overrides is None:
        overrides = _decrypt_file(OVERRIDES_PATH) or {}
    raw = (((overrides.get("__plan") or {}).get("settings") or {}).get("telegram")) or {}
    cfg = {}
    for slot, default in DEFAULT_CFG.items():
        merged = {**default, **(raw.get(slot) or {})}
        if not _valid_time(merged.get("time")):
            merged["time"] = default["time"]
        if slot == "weekly" and merged.get("day") not in range(7):
            merged["day"] = default["day"]
        cfg[slot] = merged
    return cfg


def _valid_time(t):
    try:
        h, m = str(t).split(":")
        return 0 <= int(h) < 24 and 0 <= int(m) < 60
    except Exception:
        return False


def day_for_date(plan, d, generated=None):
    wd = WEEKDAYS[d.weekday()]
    if generated:
        week = generated.get("weeks", {}).get(monday_of(d).strftime("%Y-%m-%d"))
        if week and wd in week.get("days", {}):
            return week["days"][wd]
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


# ---------------------------------------------------------------------------
# Tages-Nachrichten
# ---------------------------------------------------------------------------

def build_daily(mode, now, plan, generated, with_extras=True):
    """mode: 'morning' (heute) oder 'evening' (morgen). now: Berliner Datum/Zeit."""
    target = now + (timedelta(days=1) if mode == "evening" else timedelta(days=0))
    day = day_for_date(plan, target, generated)
    prefix = "☀️ Guten Morgen! Heute steht an:\n\n" if mode == "morning" else "🌙 Für morgen:\n\n"
    parts = [prefix + format_message(target, day)]
    if with_extras:
        parts.append(get_weather(target))
        mail = get_mail_summary()
        if mail:
            parts.append(mail)
    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Wochenrueckblick
# ---------------------------------------------------------------------------

def de_num(x, digits=1):
    s = f"{x:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{x:.0f}"
    return s.replace(".", ",")


def fmt_h(min_):
    return f"{int(min_) // 60} h {int(min_) % 60:02d} min"


def pct(a, b):
    return f" ({round(a / b * 100)} %)" if b else ""


def weeks_until(d_iso, today):
    try:
        return max(0, (date.fromisoformat(d_iso[:10]) - today).days // 7), max(0, (date.fromisoformat(d_iso[:10]) - today).days)
    except Exception:
        return None, None


def format_weekly(data, generated, today):
    """Wochenrueckblick (Soll/Ist), Vorschau naechste Woche, Vorschlag, Countdown, Schuhe."""
    wk = data["week"]
    t, a = wk.get("targets") or {}, wk.get("actuals") or {}
    mon = date.fromisoformat(wk["startDate"])
    kw = mon.isocalendar()[1]
    lines = [f"📊 Wochenrückblick KW {kw} ({mon.strftime('%d.%m.')}–{(mon + timedelta(days=6)).strftime('%d.%m.')})", ""]
    lines.append(f"🏃 Laufen: {de_num(a.get('runVolumeKm', 0))} / {de_num(t.get('runVolumeKm', 0))} km{pct(a.get('runVolumeKm', 0), t.get('runVolumeKm', 0))}")
    lines.append(f"🚴 Rad: {de_num(a.get('bikeVolumeKm', 0), 0)} / {de_num(t.get('bikeVolumeKm', 0), 0)} km{pct(a.get('bikeVolumeKm', 0), t.get('bikeVolumeKm', 0))}")
    lines.append(f"⏱ Zeit: {fmt_h(a.get('timeMin', 0))} / {fmt_h(t.get('timeMin', 0))}{pct(a.get('timeMin', 0), t.get('timeMin', 0))}")

    must = [(d["weekday"], u) for d in wk.get("days", []) for u in d.get("units", []) if u.get("tag") == "pflicht"]
    done = [1 for _, u in must if u.get("status") == "done"]
    if must:
        lines.append(f"✅ Pflichteinheiten: {len(done)} von {len(must)} erledigt")
        missed = [f"{wd[:2]} {u['name']}" for wd, u in must if u.get("status") != "done"]
        if missed:
            lines.append("   offen: " + ", ".join(missed[:5]) + ("…" if len(missed) > 5 else ""))

    nxt_mon = (mon + timedelta(days=7)).strftime("%Y-%m-%d")
    nxt = ((generated or {}).get("weeks") or {}).get(nxt_mon)
    if nxt:
        meta = nxt.get("meta") or {}
        tg = meta.get("targets") or {}
        lines += ["", f"➡️ Nächste Woche ({date.fromisoformat(nxt_mon).strftime('%d.%m.')}): {meta.get('label', '')}",
                  f"   Ziel: Lauf {de_num(tg.get('runVolumeKm', 0))} km · Rad {de_num(tg.get('bikeVolumeKm', 0), 0)} km · {fmt_h(tg.get('timeMin', 0))}"]
        keys = []
        for wd in WEEKDAYS:
            for u in (nxt.get("days", {}).get(wd) or {}).get("units", []):
                if u.get("keySession"):
                    short = u["detail"].split(" · ")[0][:40]
                    keys.append(f"{wd[:2]} {u['name']} ({short})")
        if keys:
            lines.append("   Schlüssel: " + "; ".join(keys))
        if nxt.get("note"):
            lines.append("   ⚠️ " + nxt["note"])

    ps = data.get("planState") or {}
    hint = ps.get("hint")
    if hint:
        lines += ["", "💡 " + hint.get("text", "")]
    inj_note = None
    if (ps.get("sick") or {}).get("from") and not (ps.get("sick") or {}).get("to"):
        inj_note = "Du bist als krank eingetragen – Plan pausiert."
    if inj_note:
        lines += ["", "🤒 " + inj_note]

    st = ps.get("settings") or {}
    if st.get("raceDate"):
        w_left, d_left = weeks_until(st["raceDate"], today)
        if d_left is not None:
            lines += ["", f"🏁 {st.get('raceName') or 'Wettkampf'}{' ' + de_num(st['raceDistanceKm'], 0) + ' km' if st.get('raceDistanceKm') else ''}: noch {w_left} Wochen ({d_left} Tage)"]

    for shoe in ps.get("shoes") or []:
        if shoe.get("retired"):
            continue
        warn = " ⚠️ Richtwert fast erreicht – auf Gefühl/Sohle achten" if shoe.get("retireKm") and shoe["km"] >= 0.9 * shoe["retireKm"] else ""
        lines.append(f"👟 {shoe['name']}: {de_num(shoe['km'])} / {de_num(shoe.get('retireKm', 0), 0)} km{warn}")

    tg = (ps.get("metrics") or {}).get("targets") or {}
    if tg.get("ftpStale"):
        lines.append("🔧 Dein FTP-Wert ist alt – bald einen neuen Test fahren und in der Performance-Seite eintragen.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Zeitsteuerung (auto)
# ---------------------------------------------------------------------------

def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def due_slots(cfg, now, state):
    """Welche Nachrichten sind jetzt faellig? (Berliner Zeit `now`; je Slot einmal pro Tag.)"""
    out = []
    today = now.date().isoformat()
    for slot in ("morning", "evening", "weekly"):
        c = cfg[slot]
        if not c.get("on"):
            continue
        if slot == "weekly" and now.weekday() != c["day"]:
            continue
        h, m = (int(x) for x in c["time"].split(":"))
        sched = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if sched <= now < sched + timedelta(minutes=LATE_WINDOW_MIN) and state.get(slot) != today:
            out.append(slot)
    return out


def run_auto(now=None, send_fn=None, cfg=None):
    now = now or datetime.now(BERLIN)
    send_fn = send_fn or send
    cfg = cfg or load_config()
    state = load_state()
    slots = due_slots(cfg, now, state)
    if not slots:
        print("Telegram: nichts faellig")
        return []
    plan, generated, data = load_plan(), load_generated_plan(), None
    sent = []
    for slot in slots:
        try:
            if slot == "weekly":
                data = data or load_training_data()
                if not data:
                    print("Telegram: Wochenrueckblick uebersprungen (keine Daten)")
                    continue
                text = format_weekly(data, generated, now.date())
            else:
                text = build_daily(slot, now, plan, generated)
            send_fn(text)
            state[slot] = now.date().isoformat()
            sent.append(slot)
            print("gesendet:", slot)
        except Exception as e:
            print(f"Telegram: {slot} fehlgeschlagen ({type(e).__name__}: {e}) - naechster Lauf versucht es erneut")
    if sent:
        save_state(state)
    return sent


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode == "auto":
        run_auto()
        return
    now = datetime.now(BERLIN)
    if mode == "weekly":
        data = load_training_data()
        if not data:
            print("keine Daten")
            return
        send(format_weekly(data, load_generated_plan(), now.date()))
    else:
        send(build_daily(mode, now, load_plan(), load_generated_plan()))
    print("gesendet:", mode)


if __name__ == "__main__":
    main()
