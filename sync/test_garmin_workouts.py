"""Tests fuer die Garmin-Workouts (komplett offline mit einer Fake-Schnittstelle):
python -m unittest test_garmin_workouts -v"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import garmin_workouts as gw  # noqa: E402

VO2 = {"name": "VO2max-Intervalle", "detail": "6×2 min ALL OUT · auf jeden Fall schneller als 4:42 min/km (deiner Garmin-5-km-Prognose) – so schnell, wie du es alle Wiederholungen halten kannst · je 2 min locker traben · "
                                               "davor einlaufen (mind. 10 min, bis du am Platz bist), danach auslaufen · 10:30 Uhr, nicht nüchtern"}
SIM = {"name": "Backyard-Simulation", "detail": "18 km · 3 Runden à 6 km, jede volle Stunde ein Start, locker (Zone 2, 130–140 bpm) · in den Pausen essen/trinken · 09:00 Uhr"}
LONG = {"name": "Langer Lauf", "detail": "12 km · Zone 2 (130–140 bpm) · 06:30 Uhr, nach dem Frühstück"}


class FakeApi:
    def __init__(self):
        self.n = 100
        self.workouts, self.scheduled, self.log = {}, {}, []

    def upload_workout(self, w):
        self.n += 1
        self.workouts[self.n] = w
        self.log.append(("upload", w["workoutName"]))
        return {"workoutId": self.n}

    def schedule_workout(self, wid, day):
        self.n += 1
        self.scheduled[self.n] = (wid, day)
        return {"workoutScheduleId": self.n}

    def unschedule_workout(self, sid):
        self.scheduled.pop(sid, None)
        self.log.append(("unschedule", sid))

    def delete_workout(self, wid):
        self.workouts.pop(wid, None)
        self.log.append(("delete", wid))


class Builder(unittest.TestCase):
    def test_vo2_has_warmup_repeat_cooldown_and_pace_target(self):
        w = gw.build_workout(VO2)
        self.assertEqual(w["workoutName"], "Intervalle 6×2 min ALL OUT")
        steps = w["workoutSegments"][0]["workoutSteps"]
        self.assertEqual([s["stepType"]["stepTypeKey"] for s in steps], ["warmup", "repeat", "cooldown"])
        rep = steps[1]
        self.assertEqual(rep["numberOfIterations"], 6)
        work, rest = rep["workoutSteps"]
        self.assertEqual((work["endConditionValue"], rest["endConditionValue"]), (120.0, 120.0))
        self.assertEqual(work["targetType"]["workoutTargetTypeKey"], "pace.zone")
        self.assertAlmostEqual(work["targetValueOne"], 1000 / 282, places=3)      # nur Untergrenze: schneller als 4:42 min/km
        self.assertGreater(work["targetValueTwo"], 4.5)                           # nach oben praktisch offen (kein Piepen bei Vollgas)
        self.assertEqual(steps[0]["endCondition"]["conditionTypeKey"], "lap.button")      # Einlaufen: bis du die Lap-Taste drueckst
        self.assertEqual(steps[2]["endCondition"]["conditionTypeKey"], "lap.button")      # Auslaufen: ebenso
        self.assertEqual(w["estimatedDurationInSecs"], (15 + 6 * 4 + 10) * 60)

    def test_backyard_simulation_laps_with_lap_button_rests(self):
        w = gw.build_workout(SIM)
        self.assertEqual(w["workoutName"], "Backyard-Simulation 3×6 km")
        steps = w["workoutSegments"][0]["workoutSteps"]
        self.assertEqual([s["stepType"]["stepTypeKey"] for s in steps], ["interval", "rest", "interval", "rest", "interval"])
        self.assertEqual(steps[0]["endCondition"]["conditionTypeKey"], "distance")
        self.assertEqual(steps[0]["endConditionValue"], 6000.0)
        self.assertEqual(steps[1]["endCondition"]["conditionTypeKey"], "lap.button")
        self.assertEqual((steps[0]["targetValueOne"], steps[0]["targetValueTwo"]), (130.0, 140.0))
        self.assertEqual([s["stepOrder"] for s in steps], [1, 2, 3, 4, 5])

    def test_long_run_and_unknown_units(self):
        self.assertEqual(gw.build_workout(LONG)["workoutName"], "Langer Lauf 12 km")
        self.assertIsNone(gw.build_workout({"name": "Push", "detail": "x"}))
        self.assertIsNone(gw.build_workout({"name": "VO2max-Intervalle", "detail": "kaputt"}))


class Matching(unittest.TestCase):
    WEEKS = {"2026-11-09": {"days": {"Mittwoch": {"units": [VO2]}, "Samstag": {"units": [SIM, {"name": "Push", "detail": "x"}]}}},
             "2026-12-07": {"days": {"Montag": {"units": [LONG]}}}}

    def test_only_key_units_in_the_next_days(self):
        w = gw.wanted_workouts(self.WEEKS, date(2026, 11, 10), days_ahead=14)
        self.assertEqual(sorted(w), ["2026-11-11|VO2max-Intervalle", "2026-11-14|Backyard-Simulation"])
        none_yet = gw.wanted_workouts(self.WEEKS, date(2026, 11, 10), days_ahead=2)
        self.assertEqual(sorted(none_yet), ["2026-11-11|VO2max-Intervalle"])

    def test_sync_is_idempotent_replaces_changes_and_removes_dropped_units(self):
        api = FakeApi()
        wanted = gw.wanted_workouts(self.WEEKS, date(2026, 11, 10), days_ahead=14)
        state = gw.sync_workouts(api, wanted, {}, log=lambda *_: None)
        self.assertEqual(len(api.workouts), 2)
        self.assertEqual(len(api.scheduled), 2)
        # zweiter Lauf ohne Aenderung: nichts passiert
        before = list(api.log)
        state2 = gw.sync_workouts(api, wanted, state, log=lambda *_: None)
        self.assertEqual(api.log, before)
        self.assertEqual(state2, state)
        # Einheit aendert sich -> altes Workout raus, neues rein
        changed = {"2026-11-09": {"days": {"Mittwoch": {"units": [{**VO2, "detail": VO2["detail"].replace("6×2", "5×3")}]}, "Samstag": {"units": [SIM]}}}}
        state3 = gw.sync_workouts(api, gw.wanted_workouts(changed, date(2026, 11, 10)), state2, log=lambda *_: None)
        names = sorted(w["workoutName"] for w in api.workouts.values())
        self.assertEqual(names, ["Backyard-Simulation 3×6 km", "Intervalle 5×3 min ALL OUT"])
        self.assertEqual(len(api.scheduled), 2)
        # Einheit faellt weg -> aus Kalender und Bibliothek entfernt
        state4 = gw.sync_workouts(api, {}, state3, log=lambda *_: None)
        self.assertEqual((len(api.workouts), len(api.scheduled), state4), (0, 0, {"items": {}}))

    def test_api_errors_never_raise(self):
        class Broken(FakeApi):
            def upload_workout(self, w):
                raise OSError("garmin down")
        wanted = gw.wanted_workouts(self.WEEKS, date(2026, 11, 10))
        msgs = []
        state = gw.sync_workouts(Broken(), wanted, {}, log=msgs.append)
        self.assertEqual(state, {"items": {}})
        self.assertTrue(any("fehlgeschlagen" in m for m in msgs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
