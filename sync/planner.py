"""
Trainingsplaner: erzeugt aus Dienstplan-Schichten, Terminen, Krankheit und
Fortschrittsstand einen kompletten Wochenplan (bis Zielmonat) - deterministisch,
ohne KI, laeuft in GitHub Actions (sync.py) und braucht kein Claude-Abo.

Regeln (Willis "Master", siehe Memory/Notizen):
  * Rad Zone 2 fast jeden Morgen, moeglichst nuechtern (Start 45 min, wird Schritt fuer
    Schritt laenger bis 75 min)
      Rad-Start = Abfahrt - Raddauer - 30 min, nie vor 06:00; passt es nicht in
      den Morgen, wandert es nach Feierabend (dann nicht mehr nuechtern)
  * 2 Ruhetage (nur lockeres Rad + EMOM) - gewaehlt nach dem Dienstplan
  * 1x VO2max-Intervalle (Lauf), 1x Schwellentraining auf dem Rad (2 x 20 min am Ende),
    1x schweres Beintraining, 1x langer Lauf, 1-2x lockerer Zone-2-Lauf
    (3 Lauftage am Anfang, danach 4), 2x Core, 1x Arme/Schultern, EMOM als Bonus
  * Langes Rad ist standardmaessig AUS (Einstellung includeLongRide, per Coach/Einstellungen)
  * Aufbau: 3 Aufbauwochen + 1 Recovery-Woche, jede Aufbauwoche etwas mehr
    (Raddauer, langer Lauf, Intervalle, Schwelle), vor dem Wettkampf Taper
  * Krankheit: Pause, danach sanfter Wiedereinstieg, Fortschritt pausiert

Alle Zeiten sind lokale Minuten seit Mitternacht. Keine Netzwerk-/IO-Zugriffe.
"""

from __future__ import annotations

import copy
import math
from datetime import date, datetime, timedelta

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

PROGRAM_START_MONDAY = date(2026, 10, 5)   # erste Ausbildungs-Trainingswoche = Fortschritts-Schritt 0
ROTATION_ANCHOR_MONDAY = date(2026, 8, 24)  # gleicher Anker wie rotation.cycleStartMonday im Plan
BLOCK = 4                                    # 3 Aufbau + 1 Recovery

DEFAULT_SETTINGS = {
    "travelMin": 75,            # Fahrzeit je Strecke
    "departBufferMin": 15,      # Puffer vor Schichtbeginn
    "prepBufferMin": 30,        # Zeit zwischen Rad-Ende und Abfahrt
    "afterBufferMin": 30,       # Zeit zwischen Rueckkehr und erster Einheit
    "dayStartMin": 6 * 60,
    "dayEndMin": 21 * 60 + 30,
    "offdayBikeStartMin": 7 * 60,
    "longSessionStartMin": 9 * 60,
    "afternoonStartMin": 16 * 60 + 30,
    "raceDate": "2027-08-28",   # Annahme (Zielmonat August 2027) - in der Website aenderbar
    "raceName": "Ultramarathon",
    "raceDistanceKm": 100,
    "runScalePct": 100,         # Regler fuer den Laufumfang (Z2- und langer Lauf), 50-130 %
    "longRunMaxKm": 36,         # Obergrenze fuer den langen Lauf
    "includeLongRide": False,   # langes Rad: zum Start aus, per Coach wieder einschaltbar
    "includeLegStabi": False,   # aktuell wegen Knie raus, per Schalter wieder reinholbar
    "includeLegSupersets": False,
}

DEFAULT_LIBRARY = {
    "emom1": {"name": "EMOM Plan 1", "durationMin": 10,
              "detail": "10 min: jede Minute 10 Klimmzüge + 15 Liegestütze",
              "exercises": [{"name": "Klimmzüge", "sets": 10, "reps": "10 pro Minute", "rest": "Rest der Minute"},
                            {"name": "Liegestütze", "sets": 10, "reps": "15 pro Minute", "rest": "Rest der Minute"}]},
    "emom2": {"name": "EMOM Plan 2", "durationMin": 10,
              "detail": "10 min: jede Minute 10 Klimmzüge + 10 Dips",
              "exercises": [{"name": "Klimmzüge", "sets": 10, "reps": "10 pro Minute", "rest": "Rest der Minute"},
                            {"name": "Dips", "sets": 10, "reps": "10 pro Minute", "rest": "Rest der Minute"}]},
    "heavyLegs": {"name": "Schweres Beintraining", "durationMin": 65,
                  "detail": "Kniebeuge, Kreuzheben, Adduktoren (Innen-/Außenseite), Wadenheben, Beinbeuger · komplette Beinkette in einer Einheit",
                  "exercises": [{"name": "Kniebeuge", "sets": 2, "reps": "6–8", "rest": "3–4 min"},
                                {"name": "Kreuzheben", "sets": 2, "reps": "6–8", "rest": "3–4 min"},
                                {"name": "Adduktoren Innenseite", "sets": 2, "reps": "6–8", "rest": "3–4 min"},
                                {"name": "Adduktoren Außenseite", "sets": 2, "reps": "6–8", "rest": "3–4 min"},
                                {"name": "Wadenheben", "sets": 2, "reps": "6–8", "rest": "3–4 min"},
                                {"name": "Beinbeuger", "sets": 2, "reps": "6–8", "rest": "3–4 min"}]},
    "legStabi": {"name": "Bein-Stabi", "durationMin": 20,
                 "detail": "Einbeinstand, Copenhagen Plank, Ausfallschritte, seitliches Beinheben",
                 "exercises": [{"name": "Einbeinstand", "sets": 3, "reps": "30–45 s", "rest": "30 s"},
                               {"name": "Copenhagen Plank", "sets": 3, "reps": "20–30 s pro Seite", "rest": "30 s"},
                               {"name": "Ausfallschritte", "sets": 3, "reps": "10–12 pro Seite", "rest": "30 s"},
                               {"name": "Seitliches Beinheben", "sets": 3, "reps": "12–15 pro Seite", "rest": "30 s"}]},
    "legSupersets": {"name": "Bein-Supersätze", "durationMin": 15,
                     "detail": "Beinstrecker + Beinbeuger + Wadenheben als Superset, danach Schienbein + Core",
                     "exercises": [{"name": "Beinstrecker", "sets": 3, "reps": "20", "rest": "2 min"},
                                   {"name": "Beinbeuger", "sets": 3, "reps": "20", "rest": "2 min"},
                                   {"name": "Wadenheben", "sets": 3, "reps": "20", "rest": "2 min"},
                                   {"name": "Schienbein", "sets": 3, "reps": "20", "rest": "1 min"}]},
    "core": {"name": "Core", "durationMin": 15, "detail": "15 min",
             "exercises": [{"name": "Plank", "sets": 3, "reps": "45 s", "rest": "30 s"},
                           {"name": "Seitstütz", "sets": 3, "reps": "30 s pro Seite", "rest": "30 s"},
                           {"name": "Dead Bug", "sets": 3, "reps": "10 pro Seite", "rest": "30 s"}]},
    "armShoulders": {"name": "Arme/Schultern", "durationMin": 25,
                     "detail": "Schulterdrücken, Seitheben, hintere Schulter, Bizeps-/Trizepsdrücken · 3×10–12 Wdh.",
                     "exercises": [{"name": "Schulterdrücken", "sets": 3, "reps": "10–12", "rest": "60 s"},
                                   {"name": "Seitheben", "sets": 3, "reps": "10–12", "rest": "60 s"},
                                   {"name": "Hintere Schulter (Reverse Flys)", "sets": 3, "reps": "10–12", "rest": "60 s"},
                                   {"name": "Bizepscurls", "sets": 3, "reps": "10–12", "rest": "60 s"},
                                   {"name": "Trizepsdrücken", "sets": 3, "reps": "10–12", "rest": "60 s"}]},
}

BIKE_TYPES = ["cycling", "indoor_cycling", "virtual_ride"]


# ----------------------------------------------------------------------------
# Hilfsfunktionen: Zeit
# ----------------------------------------------------------------------------

def hm_to_min(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def min_to_hm(minutes: int) -> str:
    minutes = int(round(minutes)) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def round_up_15(minutes: float) -> int:
    return int(math.ceil(minutes / 15.0) * 15)


def parse_date(s) -> date:
    if isinstance(s, date):
        return s
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def merge_intervals(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


# ----------------------------------------------------------------------------
# Eingaben normalisieren
# ----------------------------------------------------------------------------

def normalize_inputs(raw: dict | None) -> dict:
    """Bringt die vom Browser gespeicherten Eingaben (overrides['__plan']) in eine
    feste Form und fuellt Standardwerte auf. Unbekannte/kaputte Teile werden
    ignoriert statt den ganzen Planlauf abzubrechen."""
    raw = raw or {}
    settings = {**DEFAULT_SETTINGS, **(raw.get("settings") or {})}

    shifts: dict[str, list] = {}
    for d, items in (raw.get("shifts") or {}).items():
        norm = []
        for it in items if isinstance(items, list) else [items]:
            try:
                hm_to_min(it["start"]); hm_to_min(it["end"])
                norm.append({"start": it["start"], "end": it["end"], "label": it.get("label") or "Arbeit"})
            except Exception:
                continue
        if norm:
            shifts[d] = norm

    events = []
    for ev in raw.get("events") or []:
        try:
            parse_date(ev["date"])
            e = {
                "id": ev.get("id") or f"{ev['date']}-{ev.get('title','')}",
                "date": ev["date"][:10],
                "title": ev.get("title") or "Termin",
                "kind": ev.get("kind") or "termin",
                "start": ev.get("start") or None,
                "end": ev.get("end") or None,
                "travelMin": ev.get("travelMin"),
                "note": ev.get("note") or "",
            }
            if e["start"]:
                hm_to_min(e["start"])
            if e["end"]:
                hm_to_min(e["end"])
            events.append(e)
        except Exception:
            continue

    day_status = {}
    for d, st in (raw.get("dayStatus") or {}).items():
        if isinstance(st, dict) and st.get("kind") in ("uni", "frei", "urlaub", "krank"):
            day_status[d] = st

    run_over = {}
    for d, ov in (raw.get("runOverrides") or {}).items():
        if not isinstance(ov, dict):
            continue
        clean = {}
        for k in ("longKm", "z2Km"):
            try:
                v = float(ov[k])
                if 0 < v < 100:
                    clean[k] = v
            except Exception:
                pass
        if clean:
            run_over[d[:10]] = clean

    sick = raw.get("sick") or {}
    prog = raw.get("progression") or {}
    return {
        "settings": settings,
        "shifts": shifts,
        "events": events,
        "dayStatus": day_status,
        "sick": {"from": sick.get("from"), "to": sick.get("to")},
        "progression": {"offsetWeeks": int(prog.get("offsetWeeks") or 0)},
        "library": merge_library(raw.get("library")),
        "deload": raw.get("deload") or {},
        "runOverrides": run_over,
    }


def merge_library(user_lib: dict | None, template_lib: dict | None = None) -> dict:
    lib = copy.deepcopy(DEFAULT_LIBRARY)
    for src in (template_lib, user_lib):
        for key, entry in (src or {}).items():
            if not isinstance(entry, dict):
                continue
            base = lib.get(key, {"name": key, "durationMin": 15, "detail": "", "exercises": []})
            base.update({k: v for k, v in entry.items() if v is not None})
            lib[key] = base
    return lib


# ----------------------------------------------------------------------------
# Tageskontext: was ist an diesem Tag belegt, welche Fenster sind frei?
# ----------------------------------------------------------------------------

class DayCtx:
    def __init__(self, d: date):
        self.date = d
        self.idx = d.weekday()
        self.weekday = WEEKDAYS_DE[self.idx]
        self.kind = "free"          # free | work | school | urlaub | krank
        self.busy: list[list[int]] = []
        self.agenda: list[dict] = []
        self.depart: int | None = None
        self.return_: int | None = None
        self.focus_prefix = ""
        self.sick_return_level = None   # None | "rest" | "easy" | float Faktor
        self.free: list[list[int]] = []

    # --- freie Fenster ---
    def compute_free(self, settings):
        ds, de = settings["dayStartMin"], settings["dayEndMin"]
        busy = merge_intervals([[max(s, 0), min(e, 24 * 60)] for s, e in self.busy])
        free, cursor = [], ds
        for s, e in busy:
            if s > cursor:
                free.append([cursor, min(s, de)])
            cursor = max(cursor, e)
        if cursor < de:
            free.append([cursor, de])
        self.free = [w for w in free if w[1] - w[0] >= 20]
        # Merke, ob ein Fenster direkt auf einen Block folgt (Rueckkehr) - dann Pufferzeit
        self.free_after_busy = {w[0]: any(abs(e - w[0]) <= 1 for _, e in busy) for w in self.free}

    def free_minutes(self):
        return sum(e - s for s, e in self.free)

    def largest_window(self):
        return max((e - s for s, e in self.free), default=0)

    # --- Belegung ---
    def allocate(self, start: int, dur: int):
        out = []
        end = start + dur
        for s, e in self.free:
            if end <= s or start >= e:
                out.append([s, e])
                continue
            if start - s >= 20:
                out.append([s, start])
            if e - end >= 20:
                out.append([end, e])
        self.free = out


def build_day_contexts(monday: date, inputs: dict, today: date) -> list[DayCtx]:
    st = inputs["settings"]
    travel_default = int(st["travelMin"])
    depart_buf = int(st["departBufferMin"])
    sick_from = parse_date(inputs["sick"]["from"]) if inputs["sick"].get("from") else None
    sick_to = parse_date(inputs["sick"]["to"]) if inputs["sick"].get("to") else None
    ongoing_until = None
    if sick_from and not sick_to:
        ongoing_until = max(today, sick_from) + timedelta(days=2)

    ctxs = []
    for i in range(7):
        d = monday + timedelta(days=i)
        ctx = DayCtx(d)
        ds = iso(d)

        for sh in inputs["shifts"].get(ds, []):
            s, e = hm_to_min(sh["start"]), hm_to_min(sh["end"])
            depart = s - travel_default - depart_buf
            ret = e + travel_default
            ctx.busy.append([depart, ret])
            if ctx.depart is None or depart < ctx.depart:
                ctx.depart = depart
            if ctx.return_ is None or ret > ctx.return_:
                ctx.return_ = ret
            ctx.kind = "work"
            ctx.agenda.append({"kind": "arbeit", "title": sh.get("label") or "Arbeit", "start": sh["start"], "end": sh["end"]})
            ctx.focus_prefix += f"Arbeit {sh['start']}–{sh['end']} · Abfahrt {min_to_hm(depart)} · zurück ca. {min_to_hm(ret)} (Fahrt je ca. {fmt_travel(travel_default)}) · "

        day_events = [ev for ev in inputs["events"] if ev["date"] == ds]
        for ev in day_events:
            kind = ev["kind"] if ev["kind"] in ("schule", "termin", "sonstiges") else "termin"
            if ev["start"]:
                s = hm_to_min(ev["start"])
                e = hm_to_min(ev["end"]) if ev["end"] else s + 60
                tr = ev["travelMin"]
                if tr is None:
                    tr = travel_default if kind == "schule" else 30
                pre = (tr + depart_buf) if tr else 0
                ctx.busy.append([s - pre, e + tr])
                if kind == "schule" and ctx.kind != "work":
                    ctx.kind = "school"
                if ctx.depart is None or s - pre < ctx.depart:
                    ctx.depart = s - pre
                if ctx.return_ is None or e + tr > ctx.return_:
                    ctx.return_ = e + tr
                label = {"schule": "Schule/Seminar"}.get(kind, "Termin")
                ctx.focus_prefix += f"{label} {ev['start']}–{min_to_hm(e)} ({shorten(ev['title'].replace('(', '').replace(')', ''))}) · "
            ctx.agenda.append({"kind": kind, "title": ev["title"], "start": ev["start"], "end": ev["end"], "note": ev.get("note") or ""})

        status = inputs["dayStatus"].get(ds)
        if status:
            k = status["kind"]
            if k == "uni" and not day_events:
                # Uni-/Schultag ohne genaue Zeit -> ganztaegig belegt (9-16 plus Fahrt)
                s, e = 9 * 60, 16 * 60
                ctx.busy.append([s - travel_default - depart_buf, e + travel_default])
                ctx.depart = s - travel_default - depart_buf if ctx.depart is None else min(ctx.depart, s - travel_default - depart_buf)
                ctx.return_ = e + travel_default if ctx.return_ is None else max(ctx.return_, e + travel_default)
                ctx.kind = "school"
                ctx.agenda.append({"kind": "schule", "title": "Uni/Schule (Zeit offen)", "start": None, "end": None, "note": "ca. 9–16 Uhr angenommen"})
                ctx.focus_prefix += "Uni/Schule (ca. 9–16 Uhr) · "
            elif k == "urlaub":
                ctx.kind = "urlaub"
                ctx.agenda.append({"kind": "urlaub", "title": "Urlaub", "start": None, "end": None})
            elif k == "frei" and not ctx.agenda:
                ctx.agenda.append({"kind": "frei", "title": "Frei", "start": None, "end": None})

        # Krankheit
        is_sick = False
        if sick_from:
            if sick_to is not None:
                is_sick = sick_from <= d <= sick_to
            else:
                is_sick = sick_from <= d <= ongoing_until
        if is_sick:
            ctx.kind = "krank"
            ctx.agenda.append({"kind": "krank", "title": "Krank", "start": None, "end": None})

        # Wiedereinstieg nach Krankheit
        if sick_to is not None and d > sick_to:
            delta = (d - sick_to).days
            if delta <= 3:
                ctx.sick_return_level = "easy"
            elif delta <= 7:
                ctx.sick_return_level = 0.5
            elif delta <= 14:
                ctx.sick_return_level = 0.7
            elif delta <= 21:
                ctx.sick_return_level = 0.85

        ctx.compute_free(st)
        ctxs.append(ctx)
    return ctxs


def shorten(text: str, limit: int = 26) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip(" ,(-") + "…"


def fmt_travel(minutes: int) -> str:
    h = minutes / 60
    return f"{h:.0f} h" if minutes % 60 == 0 else f"{h:.2f}".rstrip("0").rstrip(".") + " h"


# ----------------------------------------------------------------------------
# Fortschritt / Wochentyp
# ----------------------------------------------------------------------------

def week_index(monday: date) -> int:
    return (monday - ROTATION_ANCHOR_MONDAY).days // 7


def build_index(p: int) -> int:
    """Anzahl Aufbauwochen bis einschliesslich der letzten Aufbauwoche <= p (0-basiert)."""
    return 3 * (p // BLOCK) + min(p % BLOCK, 2)


def progression_step(p: int) -> int:
    base = build_index(week_index(PROGRAM_START_MONDAY))
    return max(0, build_index(p) - base)


def is_recovery(p: int) -> bool:
    return p % BLOCK == 3


def sick_pause_weeks(inputs: dict) -> int:
    sf, st_ = inputs["sick"].get("from"), inputs["sick"].get("to")
    if not (sf and st_):
        return 0
    days = (parse_date(st_) - parse_date(sf)).days + 1
    return max(0, math.ceil(days / 7))


def week_params(monday: date, inputs: dict, factor_override: float | None = None) -> dict:
    st = inputs["settings"]
    p = week_index(monday) + inputs["progression"]["offsetWeeks"]
    sick_to = parse_date(inputs["sick"]["to"]) if inputs["sick"].get("to") else None
    if sick_to and monday > sick_to:
        p -= sick_pause_weeks(inputs)
    recovery = is_recovery(p)
    s = progression_step(p)
    race_for_step = monday_of(parse_date(st["raceDate"]))
    if monday > race_for_step:
        s = min(s, 8)

    race = parse_date(st["raceDate"])
    race_monday = monday_of(race)
    weeks_to_race = (race_monday - monday).days // 7
    taper_factor, phase = 1.0, "aufbau"
    if weeks_to_race == 0:
        taper_factor, phase = 0.35, "wettkampf"
    elif weeks_to_race == 1:
        taper_factor, phase = 0.55, "taper"
    elif weeks_to_race == 2:
        taper_factor, phase = 0.75, "taper"
    elif weeks_to_race == 3:
        taper_factor, phase = 0.9, "taper"
    elif weeks_to_race < 0:
        k = -weeks_to_race   # 1 = erste Woche nach dem Wettkampf
        if k <= 4:
            taper_factor, phase = [0.3, 0.5, 0.7, 0.85][k - 1], "erholung"

    base_factor = 1.0
    if recovery and phase == "aufbau":
        phase = "recovery"
    deload = inputs["deload"].get(iso(monday))
    if deload and (deload is True or deload.get("active")):
        base_factor *= 0.85

    factor = base_factor * taper_factor * (0.7 if phase == "recovery" else 1.0)
    if factor_override is not None:
        factor = factor_override

    def half(x):
        return round(x * 2) / 2

    def num(key, default, lo, hi):
        try:
            return max(lo, min(hi, float(st.get(key, default))))
        except Exception:
            return default

    scale = num("runScalePct", 100, 50, 130) / 100.0
    long_cap = num("longRunMaxKm", 36, 10, 60)
    z2_km = min(10.0, 6.0 + 0.5 * (s // 4))
    long_km = half(min(long_cap, 10.0 + 0.75 * s))
    long_ride = int(round(min(240, 120 + 7.5 * s) / 5) * 5)
    # VO2max-Intervalle: (Wiederholungen, Minuten je Intervall) je Fortschrittsschritt
    vo2_table = [(0, 5, 2), (2, 6, 2), (4, 5, 3), (6, 6, 3), (8, 5, 4), (12, 6, 4)]
    reps, vo2_min = next((r, m) for st0, r, m in reversed(vo2_table) if s >= st0)
    # Schwelle auf dem Rad: 2 x N min, ab dem zweiten Aufbauschritt
    thr_min = 0 if s < 1 else (10 if s < 2 else 12 if s < 4 else 15 if s < 6 else 18 if s < 8 else 20)
    bike_min = min(75, 45 + 5 * (s // 2))
    run_days = 3 if s < 3 else 4

    z2_km = max(4.0, half(z2_km * scale * (0.85 if phase == "recovery" else 1.0) * min(1.0, taper_factor + 0.1)))
    long_km = max(6.0, half(long_km * factor * scale))
    manual = inputs["runOverrides"].get(iso(monday)) or {}
    if "longKm" in manual:
        long_km = half(manual["longKm"])
    if "z2Km" in manual:
        z2_km = half(manual["z2Km"])
    long_ride = max(60, int(round(long_ride * factor / 5) * 5))
    reps = max(3, int(round(reps * (0.7 if phase == "recovery" else 1.0) * min(1.0, taper_factor + 0.1))))
    thr_min = int(round(thr_min * (0.7 if phase == "recovery" else 1.0) * min(1.0, taper_factor + 0.1)))
    thr_min = thr_min if thr_min >= 8 else 0
    bike_min = int(round(bike_min * (0.85 if phase == "recovery" else 1.0) / 5) * 5)
    if phase in ("taper", "wettkampf", "erholung"):
        bike_min = min(bike_min, 45)
    if phase == "wettkampf" or (phase == "erholung" and factor < 0.6):
        reps = 0
        thr_min = 0

    return {
        "p": p, "step": s, "phase": phase, "recovery": phase == "recovery",
        "factor": round(factor, 3), "z2Km": z2_km, "longKm": long_km, "longRideMin": long_ride,
        "intervalReps": reps, "vo2Min": vo2_min, "thresholdMin": thr_min, "bikeMin": bike_min, "runDays": run_days,
        "skipHeavy": phase == "wettkampf" or (phase == "erholung" and factor < 0.6), "weeksToRace": weeks_to_race, "taper": phase in ("taper", "wettkampf"),
    }


# ----------------------------------------------------------------------------
# Einheiten bauen
# ----------------------------------------------------------------------------

def mk_unit(name, utype, tag, detail, dur, **extra):
    u = {"name": name, "type": utype, "tag": tag, "detail": detail, "plannedDurationMin": int(dur)}
    u.update(extra)
    return u


def hint_bike():
    return {"activityTypes": BIKE_TYPES}


def exercises_for(lib, key):
    return copy.deepcopy((lib.get(key) or {}).get("exercises") or [])


def run_minutes(km: float) -> int:
    return int(round(km * 6.1))


def vo2_rest_min(m: int) -> int:
    return min(m, 3)


def interval_total_min(reps: int, m: int = 3) -> int:
    return 25 + reps * (m + vo2_rest_min(m))   # 15 min Einlaufen + 10 min Auslaufen + Intervalle/Traben


def interval_km(reps: int, m: int = 3) -> float:
    return round(4.2 + reps * (m / 4.2 + vo2_rest_min(m) / 7.0), 1)


def threshold_total_min(w: int) -> int:
    return 15 + 2 * w + 5 + 10   # einrollen + 2 x Schwelle + Pause + ausrollen


PREF = {
    "long_run":   [5, 6, 2, 3, 4, 0, 1],
    "long_ride":  [6, 5, 3, 2, 4, 0, 1],
    "intervals":  [1, 3, 4, 2, 0, 5, 6],
    "threshold":  [2, 0, 4, 3, 1, 5, 6],
    "heavy_legs": [0, 2, 1, 3, 4, 5, 6],
    "z2_run":     [2, 0, 3, 4, 1, 5, 6],
    "rest":       [4, 0, 2, 1, 3, 6, 5],
}


def pref_bonus(key: str, i: int) -> int:
    order = PREF[key]
    return 25 * (len(order) - order.index(i)) if i in order else 0


class Planner:
    def __init__(self, inputs: dict, library: dict):
        self.inputs = inputs
        self.st = inputs["settings"]
        self.lib = library

    # ---------- Slot-Suche (keine Belegung, nur Vorschlag) ----------
    def _slot(self, ctx: DayCtx, dur: int, *, pref, min_start, window_ok=None, gap=None, after=None):
        st = self.st
        gap = st["afterBufferMin"] if gap is None else gap
        for s, e in ctx.free:
            if window_ok and not window_ok(s, e, ctx):
                continue
            pre_busy = e < st["dayEndMin"] - 1
            lo = max(s + (gap if ctx.free_after_busy.get(s) else 0), min_start)
            if after is not None:
                lo = max(lo, after)
            hi = e - (st["prepBufferMin"] if pre_busy else 0) - dur
            if hi < lo:
                continue
            want = pref(s, e, pre_busy) if callable(pref) else pref
            start = int(min(max(want, lo), hi))
            for cand in (int(round(start / 15.0) * 15), int(math.ceil(start / 15.0) * 15), int(start // 15 * 15)):
                if lo <= cand <= hi:
                    start = cand
                    break
            return int(start)
        return None

    def slot_fasted(self, ctx, dur):
        st = self.st
        return self._slot(ctx, dur, pref=st["offdayBikeStartMin"], min_start=st["dayStartMin"], gap=0,
                          window_ok=lambda s, e, c: s < 10 * 60)

    def slot_bike_pm(self, ctx, dur):
        return self._slot(ctx, dur, pref=0, min_start=9 * 60 + 30)

    def slot_long(self, ctx, dur):
        st = self.st
        return self._slot(ctx, dur, pref=st["longSessionStartMin"], min_start=6 * 60 + 30,
                          window_ok=lambda s, e, c: e - s >= dur + 20)

    def slot_run(self, ctx, dur, after=None):
        st = self.st
        return self._slot(ctx, dur, pref=lambda s, e, pre: 10 * 60 + 30 if pre else st["afternoonStartMin"] - 30,
                          min_start=9 * 60 + 30, after=after)

    def slot_core(self, ctx, dur, after=None):
        return self._slot(ctx, dur, pref=lambda s, e, pre: 10 * 60 if pre else 17 * 60, min_start=9 * 60 + 30,
                          gap=0 if after is not None else None, after=after)

    # ---------- Wochenplanung ----------
    def plan_week(self, monday: date, ctxs: list[DayCtx], params: dict, today: date):
        st, lib = self.st, self.lib
        n = 7
        recovery = params["recovery"]
        placed = {i: [] for i in range(n)}
        roles: list[set] = [set() for _ in range(n)]
        missing: list[str] = []

        easy_only = [c.sick_return_level == "easy" for c in ctxs]
        level = [c.sick_return_level if isinstance(c.sick_return_level, float) else 1.0 for c in ctxs]
        pool = [i for i in range(n) if ctxs[i].kind != "krank" and not easy_only[i]]
        key_pool = [i for i in pool if level[i] >= 0.85]   # Schluesseleinheiten erst wieder bei fast voller Belastbarkeit
        last_end = {i: None for i in range(n)}

        def commit(i, unit, start, dur):
            placed[i].append({"unit": unit, "start": start, "dur": dur})
            if start is not None:
                ctxs[i].allocate(start, dur)
                last_end[i] = max(last_end[i] or 0, start + dur)

        def tsuf(start, fasted=False):
            if start is None:
                return ""
            return f" · {min_to_hm(start)} Uhr" + (", nüchtern" if fasted else "")

        def choose(key, dur, slot_fn, candidates, penalty_fn=None):
            best = None
            for i in candidates:
                start = slot_fn(ctxs[i], dur)
                if start is None:
                    continue
                score = ctxs[i].largest_window() + pref_bonus(key, i) - (penalty_fn(i) if penalty_fn else 0)
                if start >= 18 * 60:
                    score -= 200  # sehr spaete Einheit nach einem langen Tag ungern
                if best is None or score > best[0]:
                    best = (score, i)
            return best[1] if best else None

        # --- 1. langer Lauf ---
        long_km = params["longKm"]
        long_dur = run_minutes(long_km) + 10
        li = None
        if params["phase"] != "wettkampf":
            li = choose("long_run", long_dur, self.slot_long, key_pool)
            if li is None:
                missing.append("langer Lauf")
        if li is not None:
            roles[li].add("long_run")

        # --- 2. langes Rad (nicht in der Wettkampfwoche) ---
        lr_dur = params["longRideMin"]
        ri = None
        if params["phase"] != "wettkampf" and st.get("includeLongRide"):
            ri = choose("long_ride", lr_dur, self.slot_long, [i for i in key_pool if i != li])
            if ri is not None:
                roles[ri].add("long_ride")
            else:
                missing.append("langes Rad")

        # --- 3. Intervalle (nicht neben dem langen Lauf) ---
        reps = params["intervalReps"]
        ii = None
        if reps >= 3:
            iv_dur = interval_total_min(reps, params["vo2Min"])
            ii = choose("intervals", iv_dur, self.slot_run, [i for i in key_pool if i not in (li, ri)],
                        penalty_fn=lambda i: 600 if (li is not None and abs(i - li) == 1) else 0)
            if ii is not None:
                roles[ii].add("intervals")
            else:
                missing.append("VO2max-Intervalle")

        # --- 3b. Schwellentraining auf dem Rad (nicht neben Intervallen/Langlauf) ---
        ti = None
        thr = params["thresholdMin"]
        if thr:
            def thr_pen(i):
                pen = 0
                if ii is not None and abs(i - ii) == 1:
                    pen += 600
                if li is not None and abs(i - li) == 1:
                    pen += 400
                return pen
            ti = choose("threshold", threshold_total_min(thr), self.slot_bike_pm,
                        [i for i in key_pool if i not in (li, ri, ii)], thr_pen)
            if ti is not None:
                roles[ti].add("threshold")
            else:
                missing.append("Schwellentraining")

        # --- 4. schweres Beintraining (nicht vor Intervallen/Langlauf) ---
        hl_dur = int((lib.get("heavyLegs") or {}).get("durationMin") or 65)
        taken = {d for d in (li, ri, ii, ti) if d is not None}

        def hl_penalty(i):
            pen = 0
            if li is not None and i + 1 == li:
                pen += 600
            if ii is not None and i + 1 == ii:
                pen += 600
            if ti is not None and i + 1 == ti:
                pen += 300
            if ii is not None and i == ii + 1:
                pen += 150
            if li is not None and abs(i - li) == 1:
                pen += 100
            return pen

        hi = None
        if not params.get("skipHeavy"):
            hi = choose("heavy_legs", hl_dur, self.slot_run, [i for i in key_pool if i not in taken], hl_penalty)
            if hi is not None:
                roles[hi].add("heavy_legs")
            else:
                missing.append("schweres Beintraining")

        # --- 5. Ruhetage: die zwei am staerksten belegten Tage ohne Key-Einheit ---
        keyed = {d for d in (li, ri, ii, ti, hi) if d is not None}
        rest_cands = [i for i in pool if i not in keyed]
        rest_cands.sort(key=lambda i: (ctxs[i].free_minutes() // 90, PREF["rest"].index(i)))
        rest_days = rest_cands[:2]
        for i in rest_days:
            roles[i].add("rest")

        # --- 6. lockere Zone-2-Laeufe ---
        z2_km = params["z2Km"]
        z2_dur = run_minutes(z2_km) + 10
        run_target = 1 if params["phase"] == "wettkampf" else max(1, params["runDays"] - 2)
        z2_days = []
        for _ in range(run_target):
            def z2_pen(i):
                pen = 0
                if (i + 1) in [x for x in (li, ii) if x is not None]:
                    pen += 150
                if i in z2_days:
                    pen += 10_000
                if hi is not None and i == hi:
                    pen += 250
                if z2_days and abs(i - z2_days[0]) == 1:
                    pen += 80
                return pen
            cands = [i for i in pool if i not in (li, ri, ii, ti, hi) and i not in rest_days and i not in z2_days]
            ci = choose("z2_run", z2_dur, self.slot_run, cands, z2_pen)
            if ci is None and len(rest_days) >= 2:
                ci = choose("z2_run", z2_dur, self.slot_run, [i for i in rest_days if i not in z2_days], z2_pen)
                if ci is not None:
                    rest_days.remove(ci)
                    roles[ci].discard("rest")
            if ci is None:
                break
            z2_days.append(ci)
            roles[ci].add("z2_run")

        # ---------- Einheiten pro Tag platzieren ----------
        for i, ctx in enumerate(ctxs):
            if ctx.kind == "krank":
                continue
            lvl = level[i]
            if easy_only[i]:
                start = self.slot_fasted(ctx, 30) or self.slot_bike_pm(ctx, 30)
                commit(i, mk_unit("Rad Zone 1 (locker)", "rad", "pflicht",
                                  f"30 min, ganz entspannt – Wiedereinstieg nach der Krankheit{tsuf(start)}", 30,
                                  matchHint=hint_bike()), start, 30)
                continue

            r = roles[i]
            # --- langes Rad ---
            if "long_ride" in r:
                dur = max(60, int(round(params["longRideMin"] * min(lvl, 1.0) / 5) * 5))
                start = self.slot_long(ctx, dur)
                h, mm = divmod(dur, 60)
                dur_txt = (f"{h} h" + (f" {mm} min" if mm else "")) if h else f"{mm} min"
                commit(i, mk_unit("Langes Rad Zone 2", "rad", "pflicht",
                                  f"165 W · {dur_txt}{tsuf(start)}, mit Frühstück/Verpflegung", dur,
                                  keySession=True, matchHint=hint_bike()), start, dur)
            # --- langer Lauf ---
            if "long_run" in r:
                km = long_km if lvl >= 1 else max(6.0, round(long_km * lvl * 2) / 2)
                dur = run_minutes(km) + 10
                start = self.slot_long(ctx, dur)
                commit(i, mk_unit("Langer Lauf", "lauf", "pflicht",
                                  f"{fmt_km(km)} km · Zone 2 (130–140 bpm){tsuf(start)}, nach dem Frühstück", run_minutes(km),
                                  keySession=True,
                                  matchHint={"activityTypes": ["running"], "minDistanceKm": int(max(4, round(km * 0.8)))}), start, dur)
            # --- taegliches Rad (nicht am Langlauf-/Langrad-Tag) ---
            if "threshold" in r:
                w = thr if lvl >= 0.85 else max(8, int(round(thr * 0.7)))
                dur = threshold_total_min(w)
                start = self.slot_bike_pm(ctx, dur) or self.slot_fasted(ctx, dur)
                commit(i, mk_unit("Schwellentraining Rad", "rad", "pflicht",
                                  f"15 min einrollen · 2×{w} min Schwelle (hart, aber gleichmäßig – ca. 90–95 % deiner Schwellenleistung, "
                                  f"HF ~165–172 bpm, „kontrolliert unbequem“) · 5 min locker dazwischen · 10 min ausrollen{tsuf(start)}, nicht nüchtern",
                                  dur, keySession=True, matchHint=hint_bike()), start, dur)
            if "long_ride" not in r and "long_run" not in r and "threshold" not in r:
                if "rest" in r:
                    dur = 45 if ctx.kind == "free" else 30
                    start = self.slot_fasted(ctx, dur) or self.slot_bike_pm(ctx, dur)
                    fasted = start is not None and start < 11 * 60
                    commit(i, mk_unit("Rad Zone 1 (locker)", "rad", "ergaenzung",
                                      f"{dur} min, ganz entspannt{tsuf(start, fasted)}", dur, matchHint=hint_bike()), start, dur)
                else:
                    dur = params["bikeMin"] if lvl >= 0.7 else min(45, params["bikeMin"])
                    start = self.slot_fasted(ctx, dur)
                    fasted = start is not None
                    if start is None:
                        start = self.slot_bike_pm(ctx, dur)
                    if start is not None:
                        commit(i, mk_unit("Rad Zone 2", "rad", "pflicht",
                                          f"165 W · {dur} min{tsuf(start, fasted)}", dur, matchHint=hint_bike()), start, dur)
            # --- Intervalle ---
            if "intervals" in r:
                rp = reps if lvl >= 0.85 else max(3, reps - 1)
                vm = params["vo2Min"]
                dur = interval_total_min(rp, vm)
                start = self.slot_run(ctx, dur, after=(last_end[i] + 10) if last_end[i] else None)
                commit(i, mk_unit("VO2max-Intervalle", "lauf", "pflicht",
                                  f"15 min einlaufen · {rp}×{vm} min sehr hart (ca. 5-km-Tempo, grob 4:05–4:20 min/km, gleichmäßig, HF steigt Richtung 180) "
                                  f"mit je {vo2_rest_min(vm)} min lockerem Traben · 10 min auslaufen{tsuf(start)}, nicht nüchtern",
                                  dur - 10, keySession=True, matchHint={"activityTypes": ["running"]}), start, dur)
            # --- Zone-2-Lauf ---
            if "z2_run" in r:
                km = z2_km if lvl >= 1 else max(4.0, round(z2_km * lvl * 2) / 2)
                dur = run_minutes(km) + 10
                start = self.slot_run(ctx, dur, after=(last_end[i] + 10) if last_end[i] else None)
                if start is not None:
                    commit(i, mk_unit("Zone-2-Lauf", "lauf", "pflicht",
                                      f"{fmt_km(km)} km · 130–140 bpm{tsuf(start)}", run_minutes(km),
                                      matchHint={"activityTypes": ["running"], "minDistanceKm": int(max(3, round(km * 0.7)))}), start, dur)
            # --- Kraft ---
            if "heavy_legs" in r:
                detail = (lib.get("heavyLegs") or {}).get("detail") or ""
                if recovery or lvl < 0.85:
                    detail += " · leichter: 3–4 Wdh. im Tank"
                start = self.slot_run(ctx, hl_dur, after=(last_end[i] + 10) if last_end[i] else None)
                commit(i, mk_unit("Schweres Beintraining", "kraft", "pflicht", f"{detail}{tsuf(start)}", hl_dur,
                                  exercises=exercises_for(lib, "heavyLegs"),
                                  matchHint={"activityTypes": ["strength_training"]}), start, hl_dur)
            if st.get("includeLegStabi") and "long_run" in r:
                dur = int((lib.get("legStabi") or {}).get("durationMin") or 20)
                commit(i, mk_unit("Bein-Stabi", "kraft", "ergaenzung",
                                  f"{(lib.get('legStabi') or {}).get('detail', '')} · direkt im Anschluss", dur,
                                  exercises=exercises_for(lib, "legStabi"),
                                  matchHint={"activityTypes": ["strength_training"]}), None, dur)
            if st.get("includeLegSupersets") and "intervals" in r:
                dur = int((lib.get("legSupersets") or {}).get("durationMin") or 15)
                commit(i, mk_unit("Bein-Supersätze", "kraft", "ergaenzung",
                                  f"{(lib.get('legSupersets') or {}).get('detail', '')} · ≥6 h nach dem Lauf", dur,
                                  exercises=exercises_for(lib, "legSupersets"),
                                  matchHint={"activityTypes": ["strength_training"]}), None, dur)

        # --- Core x2 / Arme-Schultern x1 / EMOM ---
        core_dur = int((lib.get("core") or {}).get("durationMin") or 15)
        arm_dur = int((lib.get("armShoulders") or {}).get("durationMin") or 25)
        core_days = []
        for i in sorted(range(n), key=lambda i: (-ctxs[i].largest_window(), i)):
            if len(core_days) >= (1 if recovery else 2):
                break
            if ctxs[i].kind == "krank" or easy_only[i] or level[i] < 0.7:
                continue
            if roles[i] & {"intervals", "long_run", "long_ride", "rest", "threshold"}:
                continue
            if any(abs(i - c) < 2 for c in core_days):
                continue
            start = self.slot_core(ctxs[i], core_dur, after=(last_end[i] + 10) if last_end[i] else None)
            if start is None:
                continue
            core_days.append(i)
            commit(i, mk_unit("Core", "core", "ergaenzung", f"{core_dur} min{tsuf(start)}", core_dur,
                              exercises=exercises_for(lib, "core"),
                              matchHint={"activityTypes": ["strength_training", "cardio"]}), start, core_dur)

        arm_day = None
        if not recovery:
            for i in sorted(range(n), key=lambda i: (-ctxs[i].largest_window(), i)):
                if ctxs[i].kind == "krank" or easy_only[i] or level[i] < 0.85:
                    continue
                if roles[i] & {"heavy_legs", "long_run", "intervals", "rest", "threshold"} or i in core_days:
                    continue
                start = self.slot_core(ctxs[i], arm_dur, after=(last_end[i] + 10) if last_end[i] else None)
                if start is None:
                    continue
                arm_day = i
                commit(i, mk_unit("Arme/Schultern", "kraft", "ergaenzung",
                                  f"{(lib.get('armShoulders') or {}).get('detail', '')}{tsuf(start)} (statt EMOM)", arm_dur,
                                  exercises=exercises_for(lib, "armShoulders"),
                                  matchHint={"activityTypes": ["strength_training"]}), start, arm_dur)
                break

        for i, ctx in enumerate(ctxs):
            if ctx.kind == "krank" or easy_only[i] or i == arm_day or level[i] < 0.7:
                continue
            plan_no = 1 if (ctx.date.toordinal() % 2 == 0) else 2
            entry = lib.get(f"emom{plan_no}") or {}
            dur = int(entry.get("durationMin") or 10)
            commit(i, mk_unit("EMOM", "emom", "bonus", entry.get("detail") or "10 min EMOM", dur,
                              planLabel=f"Plan {plan_no}", exercises=exercises_for(lib, f"emom{plan_no}"),
                              matchHint={"activityTypes": ["strength_training", "cardio"]}), None, dur)

        return placed, roles, missing


def fmt_km(km: float) -> str:
    return str(int(km)) if float(km).is_integer() else f"{km:.1f}"


# ----------------------------------------------------------------------------
# Oeffentliche API
# ----------------------------------------------------------------------------

ORDER = {"rad": 0, "lauf": 1, "kraft": 2, "core": 3, "emom": 4}


def short_label(unit: dict) -> str:
    n = unit["name"]
    return {"Rad Zone 2": "Rad", "Rad Zone 1 (locker)": "lockeres Rad", "Langes Rad Zone 2": "langes Rad",
            "VO2max-Intervalle": "VO2max-Intervalle", "Schwellentraining Rad": "Schwelle (Rad)",
            "Zone-2-Lauf": "Lauf", "Langer Lauf": "langer Lauf", "Schweres Beintraining": "schwere Beine",
            "Arme/Schultern": "Arme/Schultern"}.get(n, n)


def generate_week(monday: date, inputs: dict, today: date, template_library: dict | None = None) -> dict:
    lib = inputs["library"]
    params = week_params(monday, inputs)
    ctxs = build_day_contexts(monday, inputs, today)
    planner = Planner(inputs, lib)
    placed, roles, missing = planner.plan_week(monday, ctxs, params, today)

    days = {}
    run_km = bike_min = total_min = 0.0
    race_date = parse_date(inputs["settings"]["raceDate"])
    for i, ctx in enumerate(ctxs):
        if ctx.date == race_date:
            rname = (inputs["settings"].get("raceName") or "Wettkampf").strip()
            rdist = inputs["settings"].get("raceDistanceKm")
            placed[i] = [{"unit": mk_unit(f"Wettkampf: {rname}" + (f" {rdist:g} km" if isinstance(rdist, (int, float)) and rdist else ""), "lauf", "pflicht",
                                          "Zielwettkampf – Termin ist eine Annahme, im Dienstplan-Tab unter Einstellungen anpassbar",
                                          0, keySession=True, matchHint={"activityTypes": ["running"], "minDistanceKm": 20}),
                          "start": None, "dur": 0}]
            roles[i] = {"race"}
        elif ctx.date == race_date - timedelta(days=1):
            placed[i] = [{"unit": mk_unit("Lockeres Auslaufen", "lauf", "pflicht", "15–20 min locker traben + Material checken", 20,
                                          matchHint={"activityTypes": ["running"]}), "start": None, "dur": 20}]
    for i, ctx in enumerate(ctxs):
        items = placed[i]
        # nach Startzeit sortieren (unbestimmte Einheiten ans Ende)
        items.sort(key=lambda it: (it["start"] if it["start"] is not None else 10_000, ORDER.get(it["unit"]["type"], 9)))
        units = [it["unit"] for it in items]
        focus = ctx.focus_prefix
        if roles[i] == {"race"}:
            focus += "WETTKAMPFTAG"
        elif ctx.kind == "krank":
            focus += "Krank – Training pausiert. Wenn du wieder gesund bist: im Coach-Tab „Ich bin wieder gesund“ eintragen."
            units = []
        elif ctx.sick_return_level == "easy":
            focus += "Wiedereinstieg nach Krankheit – nur locker bewegen"
        elif not units:
            focus += "Ruhetag"
        else:
            parts = [short_label(u) for u in units if u["tag"] in ("pflicht",) or u.get("keySession")]
            if "rest" in roles[i]:
                parts.insert(0, "Ruhetag")
            focus += " + ".join(dict.fromkeys(parts)) if parts else "Training"
        day = {"focus": focus.rstrip(" ·").strip(), "units": units}
        notes = [u for u in units if u.get("keySession")]
        if notes and any(u["name"] in ("Langer Lauf", "VO2max-Intervalle", "Langes Rad Zone 2", "Schwellentraining Rad") for u in notes):
            run_key = any(u["name"] in ("Langer Lauf", "VO2max-Intervalle") for u in notes)
            day["fallbackNote"] = "Schlüsseleinheit – nicht durchs Rad ersetzen." if run_key else None
        days[ctx.weekday] = day

        for u in units:
            total_min += u.get("plannedDurationMin", 0)
            if u["type"] == "lauf":
                if u["name"] == "VO2max-Intervalle":
                    reps = params["intervalReps"] if params["intervalReps"] else 4
                    run_km += interval_km(reps, params["vo2Min"])
                else:
                    try:
                        run_km += float(u["detail"].split(" km")[0].replace(",", "."))
                    except Exception:
                        pass
            if u["type"] == "rad":
                bike_min += u.get("plannedDurationMin", 0)

    targets = {
        "runVolumeKm": round(run_km, 1),
        "bikeVolumeKm": round(bike_min / 60 * 27.5),
        "timeMin": int(total_min),
        "zone2SharePct": 90 if params["phase"] in ("recovery", "taper", "erholung") else 82,
    }
    label = phase_label(params)
    note_bits = []
    if any(c.kind == "krank" for c in ctxs):
        note_bits.append("Krankheit – Plan pausiert")
    if params["phase"] == "wettkampf":
        note_bits.append("Wettkampfwoche (Termin im Plan hinterlegt)")
    if missing:
        note_bits.append("keine Zeit für: " + ", ".join(missing))
    known = any(c.agenda for c in ctxs)
    if not known:
        note_bits.append("Dienstplan noch offen – Zeiten vorläufig")
    run_h = bike_h = strength_h = 0.0
    for d in days.values():
        for u in d["units"]:
            mins = u.get("plannedDurationMin", 0)
            if u["type"] == "lauf":
                run_h += mins / 60
            elif u["type"] == "rad":
                bike_h += mins / 60
            else:
                strength_h += mins / 60
    return {
        "note": " · ".join(note_bits),
        "days": days,
        "meta": {
            "monday": iso(monday), "phase": params["phase"],
            "weekType": "recovery" if params["recovery"] else "aufbau",
            "p": params["p"], "step": params["step"], "factor": params["factor"],
            "targets": targets, "label": label, "scheduleKnown": known,
            "runKm": {"long": params["longKm"], "z2": params["z2Km"]},
            "hours": {"run": round(run_h, 1), "bike": round(bike_h, 1), "strength": round(strength_h, 1)},
        },
    }


def phase_label(params: dict) -> str:
    ph = params["phase"]
    if ph == "recovery":
        return "Recovery-Woche"
    if ph == "taper":
        return f"Taper (noch {params['weeksToRace']} Wo. bis zum Wettkampf)"
    if ph == "wettkampf":
        return "Wettkampfwoche"
    if ph == "erholung":
        return "Erholung nach dem Wettkampf"
    pos = params["p"] % BLOCK
    return f"Woche {pos + 1} von 3 · Aufbau"


def generate_plan(inputs_raw: dict | None, from_monday: date, to_date: date, today: date,
                  template_library: dict | None = None) -> dict:
    inputs = normalize_inputs(inputs_raw)
    if template_library:
        inputs["library"] = merge_library((inputs_raw or {}).get("library"), template_library)
    weeks = {}
    monday = monday_of(from_monday)
    while monday <= to_date:
        weeks[iso(monday)] = generate_week(monday, inputs, today)
        monday += timedelta(days=7)
    return weeks


def build_agenda(inputs_raw: dict | None, today: date, days_ahead: int = 60) -> list:
    """Tagesagenda aus Schichten/Terminen/Status (fuer Heute-Karte & Telegram)."""
    inputs = normalize_inputs(inputs_raw)
    out = []
    start_monday = monday_of(today)
    for w in range(math.ceil(days_ahead / 7) + 1):
        for ctx in build_day_contexts(start_monday + timedelta(days=7 * w), inputs, today):
            if ctx.date < today or not ctx.agenda:
                continue
            out.append({"date": iso(ctx.date), "weekday": ctx.weekday, "items": ctx.agenda})
    return out


def build_agenda_all(inputs_raw: dict | None) -> list:
    """Agenda fuer alle Tage mit Eintraegen (zeitunabhaengig, daher stabil -
    wird nur neu geschrieben, wenn sich Dienstplan/Termine aendern)."""
    inputs = normalize_inputs(inputs_raw)
    dates = set(inputs["shifts"]) | {e["date"] for e in inputs["events"]} | set(inputs["dayStatus"])
    if not dates:
        return []
    ds = sorted(parse_date(d) for d in dates)
    out = []
    monday = monday_of(ds[0])
    while monday <= ds[-1]:
        for ctx in build_day_contexts(monday, inputs, PROGRAM_START_MONDAY):
            if ctx.agenda:
                out.append({"date": iso(ctx.date), "weekday": ctx.weekday, "items": ctx.agenda})
        monday += timedelta(days=7)
    return out


def progression_hint(completions: list, overload: bool) -> dict | None:
    """Vorschlag fuer den Coach-Tab - nie automatisch angewendet. completions:
    Erledigungsquoten (%) der letzten abgeschlossenen Wochen, aelteste zuerst."""
    recent = [c for c in completions if c is not None][-2:]
    if len(recent) < 2:
        return None
    if all(c < 60 for c in recent):
        return {"type": "hold", "text": f"Die letzten zwei Wochen waren nur zu {recent[0]}% und {recent[1]}% geschafft – Vorschlag: Fortschritt eine Woche pausieren."}
    if all(c >= 90 for c in recent) and not overload:
        return {"type": "advance", "text": f"Die letzten zwei Wochen zu {recent[0]}% und {recent[1]}% geschafft, keine Überlastungs-Warnung – Vorschlag: eine Woche hochgehen."}
    return None


def compact_week(week: dict) -> dict:
    """Schlanke Fassung fuer die Wochenansicht in der Zukunft (ohne matchHint/Uebungen)."""
    days = {}
    for wd, d in week["days"].items():
        units = []
        for u in d["units"]:
            cu = {k: u[k] for k in ("name", "type", "tag", "detail", "plannedDurationMin") if k in u}
            for k in ("keySession", "planLabel"):
                if u.get(k):
                    cu[k] = u[k]
            units.append(cu)
        days[wd] = {"focus": d["focus"], "units": units, **({"fallbackNote": d["fallbackNote"]} if d.get("fallbackNote") else {})}
    return {"note": week["note"], "meta": week["meta"], "days": days}
