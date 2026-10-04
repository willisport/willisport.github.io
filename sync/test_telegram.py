"""Tests fuer telegram_agenda.py: Zeitsteuerung (Sommer-/Winterzeit), Statusdatei, Wochenrueckblick - offline."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import telegram_agenda as ta  # noqa: E402

B = ZoneInfo("Europe/Berlin")
CFG = ta.load_config({})


def at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=B)


class Config(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(CFG["morning"]["time"], "05:30")
        self.assertEqual(CFG["evening"]["time"], "20:00")
        self.assertEqual((CFG["weekly"]["day"], CFG["weekly"]["time"]), (6, "20:00"))

    def test_user_settings_override_and_bad_values_fall_back(self):
        ov = {"__plan": {"settings": {"telegram": {"morning": {"time": "06:15"}, "evening": {"on": False},
                                                   "weekly": {"day": 9, "time": "99:99"}}}}}
        cfg = ta.load_config(ov)
        self.assertEqual(cfg["morning"]["time"], "06:15")
        self.assertFalse(cfg["evening"]["on"])
        self.assertEqual((cfg["weekly"]["day"], cfg["weekly"]["time"]), (6, "20:00"))


class DueSlots(unittest.TestCase):
    def test_not_due_before_time(self):
        self.assertEqual(ta.due_slots(CFG, at(2026, 10, 6, 5, 20), {}), [])

    def test_morning_due_from_0530_and_only_once(self):
        self.assertEqual(ta.due_slots(CFG, at(2026, 10, 6, 5, 40), {}), ["morning"])
        self.assertEqual(ta.due_slots(CFG, at(2026, 10, 6, 5, 50), {"morning": "2026-10-06"}), [])

    def test_late_runs_are_caught_up_but_not_after_three_hours(self):
        self.assertEqual(ta.due_slots(CFG, at(2026, 10, 6, 8, 20), {}), ["morning"])
        self.assertEqual(ta.due_slots(CFG, at(2026, 10, 6, 8, 31), {}), [])

    def test_evening_and_weekly_on_sunday_only(self):
        self.assertEqual(ta.due_slots(CFG, at(2026, 10, 7, 20, 5), {}), ["evening"])          # Mittwoch
        self.assertEqual(ta.due_slots(CFG, at(2026, 10, 11, 20, 5), {}), ["evening", "weekly"])   # Sonntag

    def test_works_in_winter_time_too(self):
        # 05:30 lokal ist im Winter 04:30 UTC - die Steuerung rechnet in Berliner Zeit, nicht UTC
        self.assertEqual(ta.due_slots(CFG, at(2026, 12, 8, 5, 31), {}), ["morning"])
        self.assertEqual(ta.due_slots(CFG, at(2026, 12, 8, 4, 31), {}), [])

    def test_disabled_slot_never_sent(self):
        cfg = ta.load_config({"__plan": {"settings": {"telegram": {"morning": {"on": False}}}}})
        self.assertEqual(ta.due_slots(cfg, at(2026, 10, 6, 5, 40), {}), [])


class RunAuto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, "state.json")
        self.p = [mock.patch.object(ta, "STATE_PATH", self.state),
                  mock.patch.object(ta, "get_weather", lambda d: "WETTER"),
                  mock.patch.object(ta, "get_mail_summary", lambda: ""),
                  mock.patch.object(ta, "load_generated_plan", lambda: None),
                  mock.patch.object(ta, "load_training_data", lambda: None)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_sends_once_and_remembers(self):
        sent = []
        out = ta.run_auto(at(2026, 10, 6, 5, 35), sent.append, CFG)
        self.assertEqual(out, ["morning"])
        self.assertIn("Heute steht an", sent[0])
        again = ta.run_auto(at(2026, 10, 6, 5, 45), sent.append, CFG)
        self.assertEqual(again, [])
        self.assertEqual(len(sent), 1)
        self.assertEqual(json.load(open(self.state))["morning"], "2026-10-06")

    def test_failed_send_is_retried(self):
        def boom(_):
            raise OSError("telegram down")
        self.assertEqual(ta.run_auto(at(2026, 10, 6, 5, 35), boom, CFG), [])
        self.assertFalse(os.path.exists(self.state))
        ok = []
        self.assertEqual(ta.run_auto(at(2026, 10, 6, 5, 45), ok.append, CFG), ["morning"])

    def test_evening_talks_about_tomorrow(self):
        sent = []
        ta.run_auto(at(2026, 10, 6, 20, 2), sent.append, CFG)
        self.assertIn("Für morgen", sent[0])
        self.assertIn("07.10.2026", sent[0])


DATA = {
    "week": {"startDate": "2026-10-05", "targets": {"runVolumeKm": 36, "bikeVolumeKm": 125, "timeMin": 630},
             "actuals": {"runVolumeKm": 31.2, "bikeVolumeKm": 118, "timeMin": 552},
             "days": [
                 {"weekday": "Dienstag", "units": [{"name": "VO2max-Intervalle", "tag": "pflicht", "status": "done"}]},
                 {"weekday": "Donnerstag", "units": [{"name": "Schwellentraining Rad", "tag": "pflicht", "status": "planned"},
                                                      {"name": "EMOM", "tag": "bonus", "status": "planned"}]},
             ]},
    "planState": {"hint": {"type": "advance", "text": "Vorschlag: eine Woche hochgehen."},
                  "settings": {"raceDate": "2027-08-28", "raceName": "Ultramarathon", "raceDistanceKm": 100},
                  "shoes": [{"name": "Ghost 18", "km": 640.5, "retireKm": 700}],
                  "metrics": {"targets": {"ftpStale": True}}},
}
GEN = {"weeks": {"2026-10-12": {"note": "", "meta": {"label": "Recovery-Woche", "targets": {"runVolumeKm": 25, "bikeVolumeKm": 100, "timeMin": 480}},
                                "days": {"Dienstag": {"units": [{"name": "VO2max-Intervalle", "detail": "4×2 min ALL OUT · Ziel", "keySession": True}]}}}}}


class Weekly(unittest.TestCase):
    def setUp(self):
        self.txt = ta.format_weekly(DATA, GEN, date(2026, 10, 11))

    def test_sections(self):
        for needle in ("Wochenrückblick KW 41", "31,2 / 36 km (87 %)", "118 / 125 km", "9 h 12 min / 10 h 30 min",
                       "Pflichteinheiten: 1 von 2", "Do Schwellentraining Rad", "Nächste Woche (12.10.): Recovery-Woche",
                       "Di VO2max-Intervalle", "Vorschlag: eine Woche hochgehen", "Ultramarathon 100 km: noch 45 Wochen",
                       "Ghost 18: 640,5 / 700 km", "Richtwert fast erreicht", "FTP-Wert ist alt"):
            self.assertIn(needle, self.txt)

    def test_works_with_minimal_data(self):
        minimal = {"week": {"startDate": "2026-10-05", "targets": {}, "actuals": {}, "days": []}}
        self.assertIn("Wochenrückblick", ta.format_weekly(minimal, None, date(2026, 10, 11)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
