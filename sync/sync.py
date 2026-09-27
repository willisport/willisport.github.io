"""
Baut data/training-data.json aus Garmin + Strava + Renpho + data/plan-template.json.

Aufruf:
    python sync.py

Gedacht zum wiederholten Ausfuehren (z. B. per Windows-Aufgabenplanung alle
15-30 Minuten). Einzelne Quellen duerfen fehlschlagen, ohne den ganzen Lauf
abzubrechen - dann werden die zuletzt bekannten Werte fuer diesen Abschnitt
beibehalten.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(Path(__file__).parent / ".env")

import garmin_source
import renpho_source
import crypto_utils
from plan_match import activities_on_date, unit_matches_activity
from common import weekday_de, monday_of, iso_date, fmt_short, month_name_de

PLAN_PATH = ROOT / "data" / "plan-template.json"
OUTPUT_PATH = ROOT / "data" / "training-data.json"
ENCRYPTED_OUTPUT_PATH = ROOT / "data" / "training-data.enc.json"

LOCAL_TZ = ZoneInfo("Europe/Berlin")  # GitHub-Actions-Runner laufen in UTC - ohne das
# faellt "heute" naeher an Mitternacht (v.a. 22-24 Uhr deutscher Zeit) faelschlich noch
# auf gestern, weil UTC dann noch den Vortag zeigt.
WINDOW_WEEKS = 9  # 8 Wochen Performance-Verlauf + aktuelle Woche
MACRO_GOAL_DATE = datetime(2027, 8, 31)  # Zielmonat des Ultramarathons - Makro-Uebersicht laeuft bis hierhin
GITHUB_REPO_FULL = "willisport/willisport.github.io"
NEXT_WEEK_PATTERN = re.compile(r"n[aä]chste[nrm]?\s*woche", re.IGNORECASE)


def cleanup_stale_requests(this_monday: datetime) -> None:
    """Schliesst automatisch alte offene 'anfrage'-Issues aus vergangenen Wochen.
    Erwaehnt eine Anfrage "naechste Woche", bekommt sie eine Gnadenwoche (bleibt
    offen, bis diese naechste Woche selbst zur aktuellen wird) und wird erst danach
    mit aufgeraeumt - so verschwindet z. B. "naechste Woche Dienstag laufen?" nicht,
    bevor diese Woche ueberhaupt angefangen hat."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "willis-dashboard-sync",
    }
    # this_monday traegt noch die aktuelle Uhrzeit von datetime.now() in sich - auf
    # Mitternacht kappen, sonst wirkt ein Issue von heute frueh faelschlich "aelter"
    # als der Vergleichswert und wird sofort zugemacht (realer Vorfall, siehe git log).
    monday_date = datetime(this_monday.year, this_monday.month, this_monday.day)

    list_url = f"https://api.github.com/repos/{GITHUB_REPO_FULL}/issues?labels=anfrage&state=open&per_page=100"
    try:
        with urllib.request.urlopen(urllib.request.Request(list_url, headers=headers), timeout=15) as resp:
            issues = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [warn] Anfragen-Aufraeumen: Issues konnten nicht geladen werden: {e}")
        return

    for issue in issues:
        created_at = issue.get("created_at")
        if not created_at:
            continue
        created_date = datetime.strptime(created_at[:10], "%Y-%m-%d")
        if created_date >= monday_date:
            continue  # gehoert zur aktuellen Woche, nicht anfassen

        text = f"{issue.get('title', '')} {issue.get('body', '') or ''}"
        created_last_week = created_date >= monday_date - timedelta(days=7)
        if created_last_week and NEXT_WEEK_PATTERN.search(text):
            continue  # Gnadenwoche

        number = issue.get("number")
        close_url = f"https://api.github.com/repos/{GITHUB_REPO_FULL}/issues/{number}"
        try:
            close_req = urllib.request.Request(
                close_url, method="PATCH", headers=headers,
                data=json.dumps({"state": "closed"}).encode("utf-8"),
            )
            urllib.request.urlopen(close_req, timeout=15)
            print(f"  Anfrage #{number} automatisch geschlossen (alte Woche)")
        except Exception as e:
            print(f"  [warn] Anfrage #{number} konnte nicht geschlossen werden: {e}")


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def week_type_and_label(plan: dict, monday: datetime):
    rotation = plan["rotation"]
    cycle_start = datetime.strptime(rotation["cycleStartMonday"], "%Y-%m-%d")
    pattern = rotation["pattern"]
    weeks_since = (monday - cycle_start).days // 7
    idx = weeks_since % len(pattern)
    week_type = pattern[idx]
    if week_type == "aufbau":
        aufbau_count = pattern.count("aufbau")
        label = f"Woche {idx + 1} von {aufbau_count} · Aufbau"
    else:
        label = "Recovery-Woche"
    return week_type, label


def parse_pace_to_sec(pace_str: str) -> float:
    m, s = pace_str.split(":")
    return int(m) * 60 + int(s)


def estimate_week_hours(plan: dict, week_type: str):
    """Grobe Stunden-Schaetzung je Sportart aus den km-Zielen (fuer das
    Wochenplan-Balkendiagramm) - Kraft/EMOM/Core-Zeit ist im Wochenmuster
    ohnehin fix, unabhaengig vom Aufbau/Recovery-Typ."""
    targets = plan["targetsByType"][week_type]
    profile = plan["profile"]
    zone2_avg_sec = (parse_pace_to_sec(profile["zone2PaceFastMinKm"]) + parse_pace_to_sec(profile["zone2PaceSlowMinKm"])) / 2
    run_hours = targets["runVolumeKm"] * zone2_avg_sec / 3600
    bike_avg_kmh = (profile["bikeAvgSpeedLowKmh"] + profile["bikeAvgSpeedHighKmh"]) / 2
    bike_hours = targets["bikeVolumeKm"] / bike_avg_kmh if bike_avg_kmh > 0 else 0
    strength_min = sum(
        u.get("plannedDurationMin", 0)
        for day in plan["weekPattern"]
        for u in day["units"]
        if u["type"] in ("kraft", "emom", "core")
    )
    return round(run_hours, 1), round(bike_hours, 1), round(strength_min / 60, 1)


def build_week_days(plan: dict, wk_monday: datetime, activities: list, today: datetime, steps_by_date: dict) -> list:
    week_override = plan.get("weekOverrides", {}).get(iso_date(wk_monday), {})
    day_overrides = week_override.get("days", {})
    return [
        build_day(
            plan["weekPattern"][i], wk_monday + timedelta(days=i), activities, today, steps_by_date,
            day_override=day_overrides.get(plan["weekPattern"][i]["weekday"]),
        )
        for i in range(7)
    ]


def build_upcoming_plan(
    plan: dict, this_monday: datetime, activities: list, today: datetime, steps_by_date: dict,
    weeks_ahead: int = 6, detail_weeks: int = 8,
) -> list:
    """detail_weeks: fuer die ersten paar Wochen wird zusaetzlich die volle
    Tag-fuer-Tag-Aufschluesselung mitgeliefert (Vorschau zum Vorausplanen im
    Frontend) - weiter in der Zukunft waere das nur unnoetig viel Datenvolumen
    fuer eine ohnehin repetitive, noch nicht relevante Wochenstruktur."""
    week_overrides = plan.get("weekOverrides", {})
    out = []
    for i in range(weeks_ahead):
        wk_monday = this_monday + timedelta(weeks=i)
        week_type, _ = week_type_and_label(plan, wk_monday)
        run_h, bike_h, strength_h = estimate_week_hours(plan, week_type)
        override = week_overrides.get(iso_date(wk_monday))
        out.append({
            "label": fmt_short(iso_date(wk_monday)),
            "weekType": week_type,
            "isCurrent": i == 0,
            "runHours": run_h,
            "bikeHours": bike_h,
            "strengthHours": strength_h,
            **({"note": override["note"]} if override and override.get("note") else {}),
            **({"days": build_week_days(plan, wk_monday, activities, today, steps_by_date)} if i < detail_weeks else {}),
        })
    return out


def build_day(plan_day: dict, date: datetime, activities: list, today: datetime, steps_by_date: dict, day_override: dict = None) -> dict:
    date_str = iso_date(date)
    day_acts = activities_on_date(activities, date_str)
    plan_day = {**plan_day, **(day_override or {})}
    units = []
    for pu in plan_day["units"]:
        matched = next((a for a in day_acts if unit_matches_activity(pu, a)), None)
        detail = pu.get("detail", "")
        if matched:
            status = "done"
            # Bei Lauf/Rad die tatsaechlich gefahrene/gelaufene Distanz zeigen statt der
            # geplanten - sonst steht nach einem spontanen Halbmarathon weiter "12 km" da.
            if pu["type"] in ("lauf", "rad") and matched.get("distanceKm"):
                dist = matched["distanceKm"]
                dist_str = f"{dist:.1f}".rstrip("0").rstrip(".") + " km"
                hr_str = f" · Ø {round(matched['avgHr'])} bpm" if matched.get("avgHr") else ""
                dur_str = f" · {round(matched['durationMin'])} min" if matched.get("durationMin") else ""
                detail = f"{dist_str}{dur_str}{hr_str} (geplant: {detail})"
        elif date.date() < today.date():
            status = "skipped"
        else:
            status = "planned"
        units.append({
            "name": pu["name"], "type": pu["type"], "tag": pu["tag"],
            "status": status, "detail": detail,
            **({"keySession": True} if pu.get("keySession") else {}),
            **({"plannedDurationMin": pu["plannedDurationMin"]} if pu.get("plannedDurationMin") else {}),
            **({"planLabel": pu["planLabel"]} if pu.get("planLabel") else {}),
            **({"exercises": pu["exercises"]} if pu.get("exercises") else {}),
        })
    out = {"date": date_str, "weekday": plan_day["weekday"], "focus": plan_day["focus"], "units": units}
    if plan_day.get("fallbackNote"):
        out["fallbackNote"] = plan_day["fallbackNote"]
    day_steps = steps_by_date.get(date_str)
    if day_steps:
        out["steps"] = day_steps.get("steps")
        out["stepGoal"] = day_steps.get("stepGoal")
    return out


def hr_weighted_share(acts: list, low: float, high: float) -> float:
    total, in_zone = 0.0, 0.0
    for a in acts:
        if a["type"] not in ("lauf", "rad") or not a.get("avgHr"):
            continue
        dur = a.get("durationMin") or 0
        total += dur
        if low <= a["avgHr"] <= high:
            in_zone += dur
    return round((in_zone / total) * 100, 0) if total > 0 else 0


def hr_hard_share(acts: list, high: float) -> float:
    total, hard = 0.0, 0.0
    for a in acts:
        if a["type"] not in ("lauf", "rad") or not a.get("avgHr"):
            continue
        dur = a.get("durationMin") or 0
        total += dur
        if a["avgHr"] > high + 5:
            hard += dur
    return round((hard / total) * 100, 0) if total > 0 else 0


def weight_on_or_before(weights: list, date_str: str, fallback=None):
    candidates = [w for w in weights if w["date"] <= date_str]
    return candidates[-1]["weightKg"] if candidates else fallback


def value_on_or_before(series: list, date_str: str, fallback=None):
    """series: [{date, value}] - liefert den letzten Wert an/vor date_str."""
    candidates = [e for e in series if e["date"] <= date_str]
    return candidates[-1]["value"] if candidates else fallback


def detect_overload(trend: list):
    """Einfache Regel-Erkennung: schlaegt an, wenn mindestens zwei von drei
    Warnsignalen (schlechter Schlaf, unausgeglichenes HRV, erhoehter
    Ruhepuls) an mehreren der letzten Tage gleichzeitig auftreten - soll
    bewusst nicht bei jeder einzelnen schlechten Nacht schon anschlagen."""
    recent = [r for r in trend[-3:] if r]
    if len(recent) < 2:
        return None

    poor_sleep_days = sum(1 for r in recent if r.get("sleepScore") is not None and r["sleepScore"] < 55)
    unbalanced_hrv_days = sum(1 for r in recent if r.get("hrvStatus") in ("UNBALANCED", "LOW"))

    rhr_values = [r["restingHr"] for r in trend if r.get("restingHr") is not None]
    rhr_elevated = False
    if len(rhr_values) >= 4:
        baseline = sum(rhr_values[:-2]) / len(rhr_values[:-2])
        recent_avg = sum(rhr_values[-2:]) / 2
        rhr_elevated = recent_avg > baseline + 3

    reasons = []
    if poor_sleep_days >= 2:
        reasons.append(f"Schlaf-Score an {poor_sleep_days} der letzten {len(recent)} Tage niedrig")
    if unbalanced_hrv_days >= 2:
        reasons.append("HRV mehrere Tage unausgeglichen")
    if rhr_elevated:
        reasons.append("Ruhepuls zuletzt erhoeht")

    if len(reasons) >= 2:
        return {"reasons": reasons}
    return None


def load_trend_note(load_vs_avg_pct: int):
    """Kurzer Hinweis, wenn die Wochenbelastung deutlich schneller steigt als der
    4-Wochen-Schnitt - haeufigste Ursache fuer Ueberlastungsverletzungen ist ein
    zu schneller Umfangssprung, nicht der absolute Umfang."""
    if load_vs_avg_pct >= 100:
        return {"level": "high", "text": f"Belastung {load_vs_avg_pct}% über dem 4-Wochen-Schnitt – großer Sprung, lieber im Auge behalten und bei Bedarf einen Gang runterschalten."}
    if load_vs_avg_pct >= 50:
        return {"level": "medium", "text": f"Belastung {load_vs_avg_pct}% über dem 4-Wochen-Schnitt – Umfang steigt zügig, auf Beine/Erholung achten."}
    return None


def pflicht_completion_pct(week_days: list, today: datetime):
    """Anteil der Pflicht-Einheiten, die tatsaechlich erledigt wurden - nur Tage bis
    heute zaehlen mit, noch bevorstehende Tage der Woche sollen die Quote nicht
    kuenstlich verwaessern."""
    today_str = iso_date(today)
    total, done = 0, 0
    for d in week_days:
        if d["date"] > today_str:
            continue
        for u in d["units"]:
            if u["tag"] != "pflicht":
                continue
            total += 1
            if u["status"] == "done":
                done += 1
    return round(done / total * 100) if total > 0 else None


def weight_avg_in_week(weights: list, monday_str: str, sunday_str: str, fallback=None):
    vals = [w["weightKg"] for w in weights if monday_str <= w["date"] <= sunday_str]
    return round(sum(vals) / len(vals), 1) if vals else fallback


def main():
    print(f"[{datetime.now().isoformat(timespec='seconds')}] Sync startet...")
    plan = load_json(PLAN_PATH)
    previous = load_json(OUTPUT_PATH) if OUTPUT_PATH.exists() else {}

    today = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    this_monday = monday_of(today)
    window_start = this_monday - timedelta(weeks=WINDOW_WEEKS - 1)

    try:
        cleanup_stale_requests(this_monday)
    except Exception as e:
        print(f"  [warn] Anfragen-Aufraeumen uebersprungen: {e}")

    # --- Garmin (einzige Aktivitaetsquelle + Gesundheitsdaten) ---
    try:
        api = garmin_source.get_client()
        activities = garmin_source.fetch_activities(api, window_start, today)
        sleep_today = garmin_source.fetch_daily_metrics(api, today)
        hrv_baseline = garmin_source.fetch_hrv_baseline(api, today)
        vo2max_history = garmin_source.fetch_vo2max_history(api, today, days=WINDOW_WEEKS * 7 + 60)
        vo2max = vo2max_history[-1]["value"] if vo2max_history else None
        steps_history = garmin_source.fetch_steps_history(api, window_start, today)
        recovery_trend = garmin_source.fetch_recovery_trend(api, today)
        race_predictions = garmin_source.fetch_race_predictions(api)
        print(f"  Garmin: {len(activities)} Aktivitaeten geladen")
    except Exception as e:
        print(f"[FEHLER] Garmin-Sync fehlgeschlagen, breche ab: {e}")
        sys.exit(1)

    # --- Renpho (Gewicht) ---
    # Jeder Login (auch ein wiederverwendeter, abgelaufener Token) kann die Renpho-App
    # auf dem Handy ausloggen (nur eine Sitzung pro Konto). Deshalb hier nur einmal
    # taeglich in einem festen Fenster versuchen statt bei jedem 10-Minuten-Sync -
    # an anderen Tagesstunden bleibt einfach der zuletzt bekannte Wert stehen.
    RENPHO_HOUR_UTC = 4  # ~6 Uhr Berlin (Sommerzeit) - kurz nach dem ueblichen Morgen-Wiegen
    weights = []
    if datetime.now(timezone.utc).hour == RENPHO_HOUR_UTC:
        try:
            weights = renpho_source.fetch_weight_history()
            print(f"  Renpho: {len(weights)} Gewichtsmessungen geladen")
        except Exception as e:
            print(f"  [warn] Renpho-Sync uebersprungen: {e}")
    else:
        print(f"  Renpho: ausserhalb des taeglichen Zeitfensters ({RENPHO_HOUR_UTC} Uhr UTC) uebersprungen, letzter Stand behalten")
    if not weights:
        prev_weight = (previous.get("today") or {}).get("body", {}).get("weightKg")
        if prev_weight:
            weights = [{"date": iso_date(today), "weightKg": prev_weight}]

    # --- Woche bauen ---
    week_type, week_label = week_type_and_label(plan, this_monday)
    targets = plan["targetsByType"][week_type]
    weeks_to_goal = max(1, (MACRO_GOAL_DATE - this_monday).days // 7)
    upcoming_plan = build_upcoming_plan(plan, this_monday, activities, today, steps_history, weeks_ahead=weeks_to_goal)

    week_override = plan.get("weekOverrides", {}).get(iso_date(this_monday), {})
    if week_override.get("note"):
        week_label = f"{week_label} · {week_override['note']}"
    week_days = build_week_days(plan, this_monday, activities, today, steps_history)
    week_start_str, week_end_str = iso_date(this_monday), iso_date(this_monday + timedelta(days=6))
    week_acts = [a for a in activities if week_start_str <= (a["startTime"] or "")[:10] <= week_end_str]

    run_volume_km = round(sum(a["distanceKm"] for a in week_acts if a["type"] == "lauf"), 1)
    bike_volume_km = round(sum(a["distanceKm"] for a in week_acts if a["type"] == "rad"), 1)
    volume_km = round(run_volume_km + bike_volume_km, 1)
    time_min = round(sum(a["durationMin"] for a in week_acts), 0)
    elevation_gain_m = round(sum(a.get("elevationGainM") or 0 for a in week_acts))

    prev_weeks_acts = [
        a for a in activities
        if iso_date(this_monday - timedelta(weeks=4)) <= (a["startTime"] or "")[:10] < week_start_str
    ]
    prev_time_min = sum(a["durationMin"] for a in prev_weeks_acts)
    prev_avg_time_min = prev_time_min / 4 if prev_weeks_acts else 0
    load_vs_avg = round(((time_min - prev_avg_time_min) / prev_avg_time_min) * 100) if prev_avg_time_min > 0 else (
        -100 if time_min == 0 else 0
    )

    week = {
        "label": week_label, "type": week_type,
        "startDate": week_start_str, "endDate": week_end_str,
        "targets": targets,
        "actuals": {
            "runVolumeKm": run_volume_km, "bikeVolumeKm": bike_volume_km, "timeMin": time_min,
            "zone2SharePct": hr_weighted_share(week_acts, plan["profile"]["zone2HrLow"], plan["profile"]["zone2HrHigh"]),
            "hardSharePct": hr_hard_share(week_acts, plan["profile"]["zone2HrHigh"]),
            "loadVsAvgPct": load_vs_avg,
            "loadTrendNote": load_trend_note(load_vs_avg),
            "elevationGainM": elevation_gain_m,
        },
        "days": week_days,
        "selfCoaching": plan["selfCoaching"],
    }

    # --- Heute ---
    today_idx = today.weekday()
    today_plan_units = week_days[today_idx]["units"]
    today_obj = {
        "date": iso_date(today), "weekday": weekday_de(today),
        "dayFocus": plan["weekPattern"][today_idx]["focus"],
        "units": today_plan_units,
        "sleep": {**sleep_today, "hrvBaseline": hrv_baseline},
        "body": {
            "weightKg": weight_on_or_before(weights, iso_date(today), fallback=(previous.get("today") or {}).get("body", {}).get("weightKg")),
            "vo2max": vo2max,
        },
        "steps": week_days[today_idx].get("steps"),
        "stepGoal": week_days[today_idx].get("stepGoal"),
        "overloadWarning": detect_overload(recovery_trend),
    }

    # --- Verlauf: Wochen-/Monatsvergleich + Log ---
    last_monday = this_monday - timedelta(weeks=1)
    last_week_acts = [
        a for a in activities
        if iso_date(last_monday) <= (a["startTime"] or "")[:10] <= iso_date(last_monday + timedelta(days=6))
    ]
    this_month_str = today.strftime("%Y-%m")
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    this_month_acts = [a for a in activities if (a["startTime"] or "").startswith(this_month_str)]
    last_month_acts = [
        a for a in activities
        if iso_date(last_month_start) <= (a["startTime"] or "")[:10] <= iso_date(last_month_end)
    ]

    history = {
        "weekCompare": {
            "thisWeek": {"label": f"{fmt_short(week_start_str)}–{fmt_short(week_end_str)}",
                         "distanceKm": volume_km, "sessions": len(week_acts)},
            "lastWeek": {"label": f"{fmt_short(iso_date(last_monday))}–{fmt_short(iso_date(last_monday + timedelta(days=6)))}",
                         "distanceKm": round(sum(a["distanceKm"] for a in last_week_acts if a["type"] in ("lauf", "rad")), 1),
                         "sessions": len(last_week_acts)},
        },
        "monthCompare": {
            "thisMonth": {"label": month_name_de(today), "distanceKm": round(sum(a["distanceKm"] for a in this_month_acts if a["type"] in ("lauf", "rad")), 1), "sessions": len(this_month_acts)},
            "lastMonth": {"label": month_name_de(last_month_end), "distanceKm": round(sum(a["distanceKm"] for a in last_month_acts if a["type"] in ("lauf", "rad")), 1), "sessions": len(last_month_acts)},
        },
        "log": [
            {
                "date": (a["startTime"] or "")[:10], "weekday": weekday_de(datetime.strptime((a["startTime"] or iso_date(today))[:10], "%Y-%m-%d")),
                "name": a["name"], "type": a["type"],
                "distanceKm": a["distanceKm"], "durationMin": round(a["durationMin"]),
                "note": f"Ø {round(a['avgHr'])} bpm" if a.get("avgHr") else "",
            }
            for a in activities[:20]
        ],
    }

    # --- Performance: letzte 8 Wochen + Session-Verlaeufe ---
    perf_weeks = []
    for w in range(WINDOW_WEEKS - 1, -1, -1):
        wk_monday = this_monday - timedelta(weeks=w)
        wk_sunday = wk_monday + timedelta(days=6)
        wk_acts = [a for a in activities if iso_date(wk_monday) <= (a["startTime"] or "")[:10] <= iso_date(wk_sunday)]
        z2_runs = [a for a in wk_acts if a["type"] == "lauf" and a.get("paceSecPerKm") and a.get("avgHr")
                   and plan["profile"]["zone2HrLow"] - 5 <= a["avgHr"] <= plan["profile"]["zone2HrHigh"] + 5]
        pace = round(sum(a["paceSecPerKm"] for a in z2_runs) / len(z2_runs)) if z2_runs else None
        wk_steps = [
            steps_history[d]["steps"]
            for i in range(7)
            for d in [iso_date(wk_monday + timedelta(days=i))]
            if d in steps_history and steps_history[d].get("steps") is not None
        ]
        wk_days_detail = build_week_days(plan, wk_monday, activities, today, steps_history)
        perf_weeks.append({
            "label": fmt_short(iso_date(wk_monday)),
            "vo2max": value_on_or_before(vo2max_history, iso_date(wk_sunday)),
            "zone2PaceSecPerKm": pace,
            "runVolumeKm": round(sum(a["distanceKm"] for a in wk_acts if a["type"] == "lauf"), 1),
            "bikeVolumeKm": round(sum(a["distanceKm"] for a in wk_acts if a["type"] == "rad"), 1),
            "weightKg": weight_avg_in_week(weights, iso_date(wk_monday), iso_date(wk_sunday)),
            "avgSteps": round(sum(wk_steps) / len(wk_steps)) if wk_steps else None,
            "completionPct": pflicht_completion_pct(wk_days_detail, today),
        })
    # Luecken bei vo2max/weightKg mit letztem bekannten Wert auffuellen
    last_v, last_w = None, None
    for pw in perf_weeks:
        if pw["vo2max"] is None:
            pw["vo2max"] = last_v
        else:
            last_v = pw["vo2max"]
        if pw["weightKg"] is None:
            pw["weightKg"] = last_w
        else:
            last_w = pw["weightKg"]

    run_pace_points = [
        {"date": (a["startTime"] or "")[:10], "paceSecPerKm": round(a["paceSecPerKm"])}
        for a in sorted(activities, key=lambda a: a["startTime"] or "")
        if a["type"] == "lauf" and a.get("paceSecPerKm")
        and (not a.get("avgHr") or a["avgHr"] <= plan["profile"]["zone2HrHigh"] + 8)
        and (a["startTime"] or "")[:10] >= iso_date(window_start)
    ]
    bike_speed_points = [
        {"date": (a["startTime"] or "")[:10], "avgSpeedKmh": a["avgSpeedKmh"]}
        for a in sorted(activities, key=lambda a: a["startTime"] or "")
        if a["type"] == "rad" and a.get("avgSpeedKmh") and (a["startTime"] or "")[:10] >= iso_date(window_start)
    ]

    performance = {
        "weeks": perf_weeks, "runPace": run_pace_points, "bikeSpeed": bike_speed_points,
        "racePredictions": race_predictions,
    }

    output = {
        "syncedAt": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "profile": {**plan["profile"], "vo2max": today_obj["body"]["vo2max"]},
        "today": today_obj,
        "week": week,
        "history": history,
        "performance": performance,
        "upcomingPlan": upcoming_plan,
    }

    save_json(OUTPUT_PATH, output)
    print(f"[{datetime.now().isoformat(timespec='seconds')}] Fertig -> {OUTPUT_PATH}")

    dek_b64 = os.environ.get("DATA_ENCRYPTION_KEY")
    if dek_b64:
        dek = crypto_utils.unb64(dek_b64)
        plaintext_bytes = json.dumps(output, ensure_ascii=False).encode("utf-8")
        encrypted = crypto_utils.encrypt_json_bytes(dek, plaintext_bytes)
        save_json(ENCRYPTED_OUTPUT_PATH, encrypted)
        print(f"  Verschluesselte Fassung -> {ENCRYPTED_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
