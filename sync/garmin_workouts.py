"""Garmin-Workouts aus dem Trainingsplan.

Fuer die besonderen Laeufe (VO2max-Intervalle, Backyard-Simulation, langer Lauf) werden strukturierte
Workouts in Garmin Connect angelegt und im Garmin-Kalender auf den Tag gelegt. Die Uhr zeigt sie nach dem
naechsten Sync unter "Training" an und fuehrt durch die Intervalle (Pace-/Pulsziel, Pausen).

Der Workout-Name wird beim Ausfuehren zum Namen der Aktivitaet - bei Garmin und damit auch bei Strava,
wenn Garmin die Einheit dorthin weiterleitet ("Intervalle 6x2 min ALL OUT" statt "Berlin Laufen").

Die Bausteine werden automatisch mit dem Plan abgeglichen: aendert sich eine Einheit, wird das Workout
ersetzt; faellt sie weg, wird es aus dem Kalender genommen. Nichts davon darf den Sync abbrechen.
"""

import hashlib
import json
import re
from datetime import date, timedelta

KEY_UNITS = ("VO2max-Intervalle", "Backyard-Simulation", "Langer Lauf")
DAYS_AHEAD = 14

SPORT_RUN = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
COND = {
    "lap": {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True},
    "time": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
    "distance": {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True},
    "iterations": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
}
STEP = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    "rest": {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
}


def pace_target(pace_lo_sec, pace_hi_sec):
    """Pace-Bereich in s/km -> Garmin-Ziel (Garmin rechnet in m/s, aufsteigend)."""
    slow, fast = max(pace_lo_sec, pace_hi_sec), min(pace_lo_sec, pace_hi_sec)
    return {"targetType": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6},
            "targetValueOne": round(1000.0 / slow, 4), "targetValueTwo": round(1000.0 / fast, 4)}


def hr_target(lo, hi):
    return {"targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4},
            "targetValueOne": float(lo), "targetValueTwo": float(hi)}


def step(order, kind, cond, value=None, target=None, desc=None):
    s = {"type": "ExecutableStepDTO", "stepOrder": order, "stepType": STEP[kind], "endCondition": COND[cond]}
    if value is not None:
        s["endConditionValue"] = float(value)
    s.update(target or {"targetType": NO_TARGET})
    if desc:
        s["description"] = desc
    return s


def repeat(order, iterations, children):
    for k, c in enumerate(children):
        c["childStepId"] = 1
    return {"type": "RepeatGroupDTO", "stepOrder": order, "stepType": STEP["repeat"], "numberOfIterations": iterations,
            "workoutSteps": children, "endCondition": COND["iterations"], "endConditionValue": float(iterations),
            "smartRepeat": False, "childStepId": 1}


def workout(name, steps, seconds, description=""):
    return {"workoutName": name[:80], "description": description[:500], "sportType": SPORT_RUN, "estimatedDurationInSecs": int(seconds),
            "workoutSegments": [{"segmentOrder": 1, "sportType": SPORT_RUN, "workoutSteps": steps}]}


def _num(txt):
    return float(str(txt).replace(",", "."))


def build_workout(unit):
    """Strukturiertes Garmin-Workout aus einer geplanten Einheit (oder None, wenn nichts Sinnvolles herauszulesen ist)."""
    name, detail = unit.get("name"), unit.get("detail") or ""
    if name == "VO2max-Intervalle":
        m = re.search(r"(\d+)×(\d+) min ALL OUT", detail)
        if not m:
            return None
        reps, mins = int(m.group(1)), int(m.group(2))
        rest = re.search(r"je (\d+) min locker traben", detail)
        rest_min = int(rest.group(1)) if rest else min(mins, 3)
        pace = re.search(r"Ziel-Pace (\d+):(\d+)–(\d+):(\d+)", detail)
        target = pace_target(int(pace.group(1)) * 60 + int(pace.group(2)), int(pace.group(3)) * 60 + int(pace.group(4))) if pace else None
        steps = [
            step(1, "warmup", "time", 15 * 60, desc="15 min locker einlaufen"),
            repeat(2, reps, [
                step(3, "interval", "time", mins * 60, target, desc=f"{mins} min ALL OUT"),
                step(4, "recovery", "time", rest_min * 60, desc="locker traben"),
            ]),
            step(5, "cooldown", "time", 10 * 60, desc="10 min auslaufen"),
        ]
        seconds = (15 + reps * (mins + rest_min) + 10) * 60
        return workout(f"Intervalle {reps}×{mins} min ALL OUT", steps, seconds, detail)
    if name == "Backyard-Simulation":
        m = re.search(r"(\d+) Runden à (\d+(?:[.,]\d+)?) km", detail)
        if not m:
            return None
        laps, km = int(m.group(1)), _num(m.group(2))
        steps, order = [], 1
        for lap in range(laps):
            steps.append(step(order, "interval", "distance", km * 1000, hr_target(130, 140), desc=f"Runde {lap + 1} von {laps}: locker, Zone 2"))
            order += 1
            if lap < laps - 1:
                steps.append(step(order, "rest", "lap", None, desc="Pause: essen und trinken – Lap-Taste zur vollen Stunde"))
                order += 1
        seconds = laps * km * 6.2 * 60 + (laps - 1) * 20 * 60
        return workout(f"Backyard-Simulation {laps}×{km:g} km", steps, seconds, detail)
    if name == "Langer Lauf":
        m = re.search(r"^(\d+(?:[.,]\d+)?) km", detail)
        if not m:
            return None
        km = _num(m.group(1))
        return workout(f"Langer Lauf {km:g} km", [step(1, "interval", "distance", km * 1000, hr_target(130, 140), desc="locker, Zone 2")],
                       km * 6.2 * 60, detail)
    return None


def wanted_workouts(weeks, today, days_ahead=DAYS_AHEAD):
    """{ 'YYYY-MM-DD|Name': (workout_json, hash) } fuer die naechsten Tage aus dem vollen Wochenplan."""
    out = {}
    wd_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    last = today + timedelta(days=days_ahead)
    for monday, wk in weeks.items():
        mon = date.fromisoformat(monday)
        for i, wd in enumerate(wd_names):
            d = mon + timedelta(days=i)
            if d < today or d > last:
                continue
            for u in (wk.get("days", {}).get(wd, {}).get("units") or []):
                if u.get("name") not in KEY_UNITS:
                    continue
                w = build_workout(u)
                if w:
                    out[f"{d.isoformat()}|{u['name']}"] = (w, hashlib.sha1(json.dumps(w, sort_keys=True).encode("utf-8")).hexdigest()[:12])
    return out


def _first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return None


def sync_workouts(api, wanted, state, log=print):
    """Gleicht Garmin Connect mit dem Plan ab. state: {'items': {key: {hash, workoutId, scheduleId}}}. Gibt den neuen state zurueck."""
    items = dict((state or {}).get("items") or {})
    for key in list(items):
        if key not in wanted:                                   # Einheit entfaellt -> aus dem Kalender nehmen
            info = items.pop(key)
            _remove(api, info, log)
    for key, (w, h) in wanted.items():
        cur = items.get(key)
        if cur and cur.get("hash") == h:
            continue
        if cur:                                                  # Einheit hat sich geaendert -> neu anlegen
            _remove(api, cur, log)
            items.pop(key, None)
        day = key.split("|")[0]
        try:
            res = api.upload_workout(w)
            wid = _first(res, "workoutId", "workout_id")
            sched = api.schedule_workout(wid, day)
            items[key] = {"hash": h, "workoutId": wid, "scheduleId": _first(sched, "workoutScheduleId", "scheduledWorkoutId", "id")}
            log(f"  Garmin-Workout angelegt: {day} {w['workoutName']}")
        except Exception as e:  # noqa: BLE001 - darf den Sync nie abbrechen
            log(f"  [warn] Garmin-Workout {key} fehlgeschlagen: {type(e).__name__}: {e}")
    return {"items": items}


def _remove(api, info, log):
    try:
        if info.get("scheduleId") is not None:
            api.unschedule_workout(info["scheduleId"])
    except Exception as e:  # noqa: BLE001
        log(f"  [warn] Workout konnte nicht aus dem Kalender genommen werden: {e}")
    try:
        if info.get("workoutId") is not None:
            api.delete_workout(info["workoutId"])
    except Exception as e:  # noqa: BLE001
        log(f"  [warn] Workout konnte nicht geloescht werden: {e}")
