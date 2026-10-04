"""Garmin Connect: Login (mit Token-Cache) + normalisierte Aktivitaeten/Gesundheitsdaten."""

import os
from datetime import datetime, timedelta
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

from common import map_garmin_type

TOKEN_STORE = str(Path(__file__).parent / ".garmin_tokens")


def get_client() -> Garmin:
    try:
        api = Garmin()
        api.login(TOKEN_STORE)
        return api
    except Exception:
        pass

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Keine gueltigen Garmin-Tokens gefunden und GARMIN_EMAIL/GARMIN_PASSWORD "
            "fehlen in sync/.env."
        )

    api = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("Garmin MFA-Code: ").strip(),
    )
    try:
        api.login(TOKEN_STORE)
    except GarminConnectAuthenticationError as e:
        raise RuntimeError(f"Garmin-Login fehlgeschlagen: {e}")
    return api


def _normalize_activity(a: dict) -> dict:
    type_key = (a.get("activityType") or {}).get("typeKey", "")
    distance_m = a.get("distance") or 0
    duration_s = a.get("duration") or 0
    distance_km = distance_m / 1000
    duration_min = duration_s / 60
    avg_hr = a.get("averageHR")

    entry = {
        "source": "garmin",
        "sourceId": str(a.get("activityId")),
        "startTime": a.get("startTimeLocal"),
        "name": a.get("activityName") or "Aktivitaet",
        "type": map_garmin_type(type_key),
        "distanceKm": round(distance_km, 2),
        "durationMin": round(duration_min, 1),
        "avgHr": avg_hr,
        "elevationGainM": round(a.get("elevationGain") or 0),
    }
    if entry["type"] in ("lauf",) and distance_km > 0.3:
        entry["paceSecPerKm"] = duration_s / distance_km
    if entry["type"] == "rad" and duration_min > 0:
        entry["avgSpeedKmh"] = round(distance_km / (duration_min / 60), 1)
    return entry


def fetch_activities(api: Garmin, start: datetime, end: datetime) -> list:
    raw = api.get_activities_by_date(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    return [_normalize_activity(a) for a in raw]


def fetch_daily_metrics(api: Garmin, day: datetime) -> dict:
    """Schlaf, Body Battery, HRV, Ruhepuls fuer genau einen Tag."""
    date_str = day.strftime("%Y-%m-%d")
    out = {
        "totalMin": None, "deepMin": None, "lightMin": None, "remMin": None, "awakeMin": None,
        "restingHr": None, "hrv": None, "sleepScore": None, "bodyBattery": None, "stress": None,
    }

    try:
        sleep = api.get_sleep_data(date_str)
        dto = sleep.get("dailySleepDTO", {}) if sleep else {}
        if dto.get("sleepTimeSeconds") is not None:
            out["deepMin"] = round((dto.get("deepSleepSeconds") or 0) / 60)
            out["lightMin"] = round((dto.get("lightSleepSeconds") or 0) / 60)
            out["remMin"] = round((dto.get("remSleepSeconds") or 0) / 60)
            out["awakeMin"] = round((dto.get("awakeSleepSeconds") or 0) / 60)
            # totalMin = Summe der Segmente (nicht Garmins "sleepTimeSeconds", das
            # awake ausschliesst) - so ergeben die Balkensegmente im Frontend 100%.
            out["totalMin"] = out["deepMin"] + out["lightMin"] + out["remMin"] + out["awakeMin"]
        score = dto.get("sleepScores", {}).get("overall", {}).get("value")
        out["sleepScore"] = score
    except Exception as e:
        print(f"  [warn] Schlafdaten fuer {date_str} nicht verfuegbar: {e}")

    try:
        out["restingHr"] = api.get_stats(date_str).get("restingHeartRate")
    except Exception as e:
        print(f"  [warn] Ruhepuls fuer {date_str} nicht verfuegbar: {e}")

    try:
        bb = api.get_body_battery(date_str, date_str)
        if bb and isinstance(bb, list) and bb[0].get("bodyBatteryValuesArray"):
            vals = [v[1] for v in bb[0]["bodyBatteryValuesArray"] if v[1] is not None]
            if vals:
                out["bodyBattery"] = vals[-1]
    except Exception as e:
        print(f"  [warn] Body Battery fuer {date_str} nicht verfuegbar: {e}")

    try:
        hrv = api.get_hrv_data_range(date_str, date_str)
        summaries = (hrv or {}).get("hrvSummaries") or []
        if summaries:
            out["hrv"] = summaries[0].get("lastNightAvg")
    except Exception as e:
        print(f"  [warn] HRV fuer {date_str} nicht verfuegbar: {e}")

    try:
        stress = api.get_all_day_stress(date_str)
        out["stress"] = stress.get("avgStressLevel") if stress else None
        if out["stress"] is not None and out["stress"] < 0:
            out["stress"] = None  # Garmin nutzt -1/-2 fuer "keine Daten"
    except Exception as e:
        print(f"  [warn] Stresslevel fuer {date_str} nicht verfuegbar: {e}")

    return out


def fetch_recovery_trend(api: Garmin, end: datetime, days: int = 5) -> list:
    """Schlaf-Score, Ruhepuls, HRV-Status der letzten Tage - fuer die
    Ueberlastungs-Erkennung (mehrere schlechte Tage in Folge)."""
    start = end - timedelta(days=days - 1)
    try:
        rows = api.get_sleep_daily(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    except Exception as e:
        print(f"  [warn] Erholungsverlauf nicht verfuegbar: {e}")
        return []
    out = []
    for row in rows or []:
        vals = row.get("values") or {}
        out.append({
            "date": row.get("calendarDate"),
            "sleepScore": vals.get("sleepScore"),
            "restingHr": vals.get("restingHeartRate"),
            "hrvStatus": vals.get("hrvStatus"),
        })
    return sorted(out, key=lambda r: r["date"] or "")


def fetch_race_predictions(api: Garmin) -> dict:
    """Garmins geschaetzte Wettkampfzeiten (Sekunden) anhand aktueller Fitness."""
    try:
        r = api.get_race_predictions()
        return {
            "time5kSec": r.get("time5K"),
            "time10kSec": r.get("time10K"),
            "timeHalfMarathonSec": r.get("timeHalfMarathon"),
            "timeMarathonSec": r.get("timeMarathon"),
        }
    except Exception as e:
        print(f"  [warn] Rennprognose nicht verfuegbar: {e}")
        return {}


def fetch_training_metrics(api: Garmin) -> dict:
    """FTP (Rad) und Laktatschwellen-Puls (Lauf) aus Garmin - jeder Teil darf einzeln fehlen."""
    out = {}
    try:
        r = api.get_cycling_ftp()
        if isinstance(r, list):
            r = r[-1] if r else {}
        if r.get("functionalThresholdPower"):
            out["ftpW"] = int(r["functionalThresholdPower"])
            out["ftpDate"] = (r.get("calendarDate") or "")[:10]
            out["ftpStale"] = bool(r.get("isStale"))
    except Exception as e:
        print(f"  [warn] FTP nicht verfuegbar: {e}")
    try:
        r = api.get_lactate_threshold()
        hr = ((r or {}).get("speed_and_heart_rate") or {}).get("heartRate")
        if hr:
            out["ltHr"] = int(hr)
    except Exception as e:
        print(f"  [warn] Laktatschwelle nicht verfuegbar: {e}")
    return out


def fetch_steps_history(api: Garmin, start: datetime, end: datetime) -> dict:
    """Schritte + Tagesziel pro Tag fuer einen Zeitraum, keyed auf Datums-String."""
    out = {}
    try:
        rows = api.get_daily_steps(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        for row in rows or []:
            date_str = row.get("calendarDate")
            if date_str:
                out[date_str] = {
                    "steps": row.get("totalSteps"),
                    "stepGoal": row.get("stepGoal"),
                }
    except Exception as e:
        print(f"  [warn] Schrittdaten fuer Woche nicht verfuegbar: {e}")
    return out


def fetch_hrv_baseline(api: Garmin, end: datetime, days: int = 14):
    start = end - timedelta(days=days)
    try:
        hrv_range = api.get_hrv_data_range(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        summaries = (hrv_range or {}).get("hrvSummaries") or []
        values = [s.get("lastNightAvg") for s in summaries if s.get("lastNightAvg")]
        return round(sum(values) / len(values)) if values else None
    except Exception:
        return None


def fetch_vo2max_history(api: Garmin, end: datetime, days: int = 120) -> list:
    """Liefert [{date, value}] aufsteigend sortiert - Garmin aktualisiert VO2max
    nur alle paar Laeufe, die Liste hat also Luecken."""
    start = end - timedelta(days=days)
    try:
        metrics = api.get_max_metrics_range(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        out = []
        for m in metrics or []:
            generic = m.get("generic") or {}
            v = generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")
            date = generic.get("calendarDate")
            if v and date:
                out.append({"date": date, "value": v})
        out.sort(key=lambda e: e["date"])
        return out
    except Exception as e:
        print(f"  [warn] VO2max nicht verfuegbar: {e}")
        return []
