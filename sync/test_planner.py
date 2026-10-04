"""Tests fuer planner.py - laufen komplett offline: python -m unittest test_planner -v"""

import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import planner as pl  # noqa: E402

TODAY = date(2026, 10, 4)
OCT_SHIFTS = {
    "2026-10-05": [{"start": "16:00", "end": "22:00"}],
    "2026-10-09": [{"start": "13:00", "end": "19:00"}],
    "2026-10-19": [{"start": "07:00", "end": "13:00"}],
    "2026-10-20": [{"start": "07:00", "end": "13:00"}],
    "2026-10-21": [{"start": "07:00", "end": "13:00"}],
    "2026-10-22": [{"start": "07:00", "end": "13:00"}],
    "2026-10-23": [{"start": "07:00", "end": "13:00"}],
}


def week(monday, raw=None, today=TODAY):
    return pl.generate_plan(raw or {}, monday, monday, today)[pl.iso(monday)]


def units(w, weekday):
    return w["days"][weekday]["units"]


def find(w, weekday, name):
    return next((u for u in units(w, weekday) if u["name"] == name), None)


def all_units(w):
    return [u for d in w["days"].values() for u in d["units"]]


class TimeHelpers(unittest.TestCase):
    def test_hm_roundtrip(self):
        self.assertEqual(pl.min_to_hm(pl.hm_to_min("06:15")), "06:15")

    def test_round_up_15(self):
        self.assertEqual(pl.round_up_15(61), 75)
        self.assertEqual(pl.round_up_15(60), 60)

    def test_shorten(self):
        self.assertEqual(pl.shorten("kurz"), "kurz")
        self.assertTrue(len(pl.shorten("Seminar Ausbildung Prinzenallee Berlin Mitte")) <= 27)


class NormalizeInputs(unittest.TestCase):
    def test_empty(self):
        n = pl.normalize_inputs(None)
        self.assertEqual(n["shifts"], {})
        self.assertEqual(n["settings"]["travelMin"], 75)

    def test_garbage_ignored(self):
        n = pl.normalize_inputs({
            "shifts": {"2026-10-05": [{"start": "xx", "end": "22:00"}, {"start": "16:00", "end": "22:00"}]},
            "events": [{"date": "kaputt"}, {"date": "2026-10-06", "title": "Ok", "start": "09:00", "end": "13:00"}],
            "dayStatus": {"2026-10-07": {"kind": "quatsch"}},
        })
        self.assertEqual(len(n["shifts"]["2026-10-05"]), 1)
        self.assertEqual(len(n["events"]), 1)
        self.assertEqual(n["dayStatus"], {})

    def test_library_merge_user_wins(self):
        lib = pl.merge_library({"core": {"exercises": [{"name": "Hollow Hold", "sets": 3, "reps": "30 s", "rest": "30 s"}]}})
        self.assertEqual(lib["core"]["exercises"][0]["name"], "Hollow Hold")
        self.assertEqual(lib["emom1"]["name"], "EMOM Plan 1")


class DayContexts(unittest.TestCase):
    def ctx(self, raw, d):
        inputs = pl.normalize_inputs(raw)
        mon = pl.monday_of(d)
        return pl.build_day_contexts(mon, inputs, TODAY)[d.weekday()]

    def test_shift_depart_return(self):
        c = self.ctx({"shifts": OCT_SHIFTS}, date(2026, 10, 19))
        self.assertEqual(pl.min_to_hm(c.depart), "05:30")
        self.assertEqual(pl.min_to_hm(c.return_), "14:15")
        self.assertEqual(c.kind, "work")

    def test_free_day_whole_window(self):
        c = self.ctx({}, date(2026, 10, 10))
        self.assertEqual(c.free[0], [360, 1290])

    def test_school_event_travel(self):
        raw = {"events": [{"date": "2026-10-06", "title": "Schulung", "kind": "schule", "start": "09:00", "end": "13:00"}]}
        c = self.ctx(raw, date(2026, 10, 6))
        self.assertEqual(pl.min_to_hm(c.depart), "07:30")
        self.assertEqual(pl.min_to_hm(c.return_), "14:15")
        self.assertEqual(c.kind, "school")

    def test_uni_status_without_events_blocks_day(self):
        c = self.ctx({"dayStatus": {"2026-10-07": {"kind": "uni"}}}, date(2026, 10, 7))
        self.assertEqual(c.kind, "school")
        self.assertTrue(c.depart is not None)

    def test_sick_ongoing_covers_today_plus_two(self):
        raw = {"sick": {"from": "2026-10-05", "to": None}}
        ctxs = pl.build_day_contexts(date(2026, 10, 5), pl.normalize_inputs(raw), date(2026, 10, 5))
        self.assertEqual([c.kind for c in ctxs[:4]], ["krank", "krank", "krank", "free"])


class FastedBikeFormula(unittest.TestCase):
    """Rad-Start = Abfahrt - Raddauer - 30 min, nie vor 6:00 - exakt wie in den
    von Hand geschriebenen Wochen (Di 9-13 -> 6:00, Fruehdienst -> Nachmittag)."""

    def planner_and_ctx(self, raw, d):
        inputs = pl.normalize_inputs(raw)
        ctx = pl.build_day_contexts(pl.monday_of(d), inputs, TODAY)[d.weekday()]
        return pl.Planner(inputs, inputs["library"]), ctx

    def test_school_9_to_13_bike_at_6(self):
        raw = {"events": [{"date": "2026-10-06", "title": "S", "kind": "schule", "start": "09:00", "end": "13:00"}]}
        planner, ctx = self.planner_and_ctx(raw, date(2026, 10, 6))
        self.assertEqual(planner.slot_fasted(ctx, 60), 6 * 60)

    def test_school_9_to_13_easy_spin_at_6_30(self):
        raw = {"events": [{"date": "2026-10-06", "title": "S", "kind": "schule", "start": "09:00", "end": "13:00"}]}
        planner, ctx = self.planner_and_ctx(raw, date(2026, 10, 6))
        self.assertEqual(planner.slot_fasted(ctx, 30), 6 * 60 + 30)

    def test_early_shift_has_no_fasted_slot_and_bike_after_return(self):
        planner, ctx = self.planner_and_ctx({"shifts": OCT_SHIFTS}, date(2026, 10, 19))
        self.assertIsNone(planner.slot_fasted(ctx, 60))
        self.assertEqual(pl.min_to_hm(planner.slot_bike_pm(ctx, 60)), "14:45")

    def test_late_shift_bike_default_7(self):
        planner, ctx = self.planner_and_ctx({"shifts": OCT_SHIFTS}, date(2026, 10, 5))
        self.assertEqual(pl.min_to_hm(planner.slot_fasted(ctx, 60)), "07:00")

    def test_week_with_early_shifts_has_no_fasted_bike(self):
        w = week(date(2026, 10, 19), {"shifts": OCT_SHIFTS})
        for wd in ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"):
            for u in units(w, wd):
                if u["type"] == "rad":
                    self.assertNotIn("nüchtern", u["detail"])
                    gym_day = any(x["name"] == "Schweres Beintraining" for x in units(w, wd))
                    # am Studio-Tag verschiebt sich die Rueckkehr um das Beintraining (13:20 + 65 min + Heimweg 75 min + 30 min Puffer = 15:45)
                    self.assertIn("15:45" if gym_day else "14:45", u["detail"])


class WeekInvariants(unittest.TestCase):
    def assert_no_overlap(self, raw, monday):
        inputs = pl.normalize_inputs(raw)
        ctxs = pl.build_day_contexts(monday, inputs, TODAY)
        busy = {c.weekday: [tuple(b) for b in c.busy] for c in ctxs}
        w = week(monday, raw)
        for wd, d in w["days"].items():
            timed = []
            for u in d["units"]:
                m = __import__("re").search(r"(\d{2}):(\d{2}) Uhr", u["detail"])
                if m and u["type"] != "emom":
                    start = int(m.group(1)) * 60 + int(m.group(2))
                    dur = u["plannedDurationMin"] + (10 if u["name"] in ("Zone-2-Lauf", "Langer Lauf", "VO2max-Intervalle") else 0)
                    timed.append((start, start + dur, u["name"]))
            timed.sort()
            for (s1, e1, n1), (s2, e2, n2) in zip(timed, timed[1:]):
                self.assertLessEqual(e1 - 12, s2, f"{wd}: {n1} und {n2} ueberlappen")
            for s, e, n in timed:
                if n == "Schweres Beintraining" and "im Studio" in " ".join(u["detail"] for u in d["units"] if u["name"] == n):
                    continue    # Studio direkt nach der Schicht: bewusst im Arbeitsblock, Heimweg danach
                self.assertGreaterEqual(s, 360, f"{wd}: {n} vor 6:00")
                self.assertLessEqual(e, 22 * 60 + 5, f"{wd}: {n} nach 22:00")
                for bs, be in busy[wd]:
                    self.assertFalse(s < be and e > bs and (bs > 0) and not (e <= bs), f"{wd}: {n} ({pl.min_to_hm(s)}) kollidiert mit Arbeit/Termin {pl.min_to_hm(bs)}-{pl.min_to_hm(be)}")

    def test_real_october_weeks_no_overlap(self):
        raw = {"shifts": OCT_SHIFTS, "events": [
            {"date": "2026-10-06", "title": "Schulung", "kind": "schule", "start": "09:00", "end": "13:00"},
            {"date": "2026-10-07", "title": "Seminar", "kind": "schule", "start": "09:00", "end": "17:00"},
            {"date": "2026-10-12", "title": "Schulung", "kind": "schule", "start": "09:00", "end": "16:00"},
        ]}
        for mon in (date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)):
            self.assert_no_overlap(raw, mon)

    def test_random_weeks_hold_invariants(self):
        rnd = random.Random(42)
        for trial in range(40):
            shifts = {}
            mon = date(2026, 11, 2) + timedelta(days=7 * trial)
            for i in range(7):
                if rnd.random() < 0.65:
                    start = rnd.choice(["07:00", "08:00", "09:30", "13:00", "15:00", "16:00"])
                    sh = pl.hm_to_min(start)
                    shifts[pl.iso(mon + timedelta(days=i))] = [{"start": start, "end": pl.min_to_hm(sh + 360)}]
            self.assert_no_overlap({"shifts": shifts}, mon)

    def test_at_least_one_rest_day_and_key_sessions(self):
        w = week(date(2026, 11, 2))
        names = [u["name"] for u in all_units(w)]
        self.assertIn("Langer Lauf", names)
        self.assertIn("VO2max-Intervalle", names)
        self.assertIn("Schwellentraining Rad", names)
        self.assertNotIn("Langes Rad Zone 2", names)   # standardmaessig aus
        self.assertIn("Schweres Beintraining", names)
        rest_days = [wd for wd, d in w["days"].items() if "Ruhetag" in d["focus"]]
        self.assertGreaterEqual(len(rest_days), 1)

    def test_long_run_not_next_to_intervals(self):
        for mon in [date(2026, 11, 2) + timedelta(days=7 * k) for k in range(12)]:
            w = week(mon)
            idx = {u["name"]: i for i, (wd, d) in enumerate(w["days"].items()) for u in d["units"]}
            if "Langer Lauf" in idx and "VO2max-Intervalle" in idx:
                self.assertGreater(abs(idx["Langer Lauf"] - idx["VO2max-Intervalle"]), 1, mon)

    def test_heavy_legs_not_day_before_long_run(self):
        for mon in [date(2026, 11, 2) + timedelta(days=7 * k) for k in range(12)]:
            w = week(mon)
            idx = {u["name"]: i for i, (wd, d) in enumerate(w["days"].items()) for u in d["units"]}
            if "Schweres Beintraining" in idx and "Langer Lauf" in idx:
                self.assertNotEqual(idx["Schweres Beintraining"] + 1, idx["Langer Lauf"], mon)

    def test_unit_schema(self):
        w = week(date(2026, 10, 5), {"shifts": OCT_SHIFTS})
        for u in all_units(w):
            for key in ("name", "type", "tag", "detail", "plannedDurationMin"):
                self.assertIn(key, u)
            self.assertIn(u["tag"], ("pflicht", "ergaenzung", "bonus"))

    def test_emom_alternates_plans_and_has_exercises(self):
        w = week(date(2026, 11, 2))
        labels = {u.get("planLabel") for u in all_units(w) if u["name"] == "EMOM"}
        self.assertEqual(labels, {"Plan 1", "Plan 2"})
        emom = next(u for u in all_units(w) if u["name"] == "EMOM")
        self.assertTrue(emom["exercises"])

    def test_day_with_nothing_free_reports_missing(self):
        raw = {"events": [{"date": pl.iso(date(2026, 12, 14) + timedelta(days=i)), "title": "Gold's Gym", "kind": "schule",
                           "start": "08:00", "end": "17:00"} for i in range(5)]}
        w = week(date(2026, 12, 14), raw)
        self.assertTrue(all_units(w))   # Wochenende traegt die Einheiten
        self.assertIn("Schule", w["days"]["Montag"]["focus"])


class Progression(unittest.TestCase):
    def plan(self):
        return pl.generate_plan({}, date(2026, 10, 5), date(2027, 9, 30), TODAY)

    def long_km(self, w):
        for d in w["days"].values():
            for u in d["units"]:
                if u["name"] == "Langer Lauf":
                    return float(u["detail"].split(" km")[0])
        return None

    def test_covers_until_september_2027(self):
        weeks = self.plan()
        self.assertEqual(min(weeks), "2026-10-05")
        self.assertGreaterEqual(max(weeks), "2027-09-27")

    def test_first_week_matches_start_values(self):
        w = self.plan()["2026-10-05"]
        self.assertEqual(self.long_km(w), 10.0)
        self.assertEqual(w["meta"]["step"], 0)

    def test_build_weeks_increase_and_recovery_drops(self):
        weeks = self.plan()
        order = sorted(weeks)
        for prev, cur in zip(order, order[1:]):
            mp, mc = weeks[prev]["meta"], weeks[cur]["meta"]
            if mc["phase"] == "recovery":
                self.assertLess(self.long_km(weeks[cur]), self.long_km(weeks[prev]))
            if mp["phase"] == "aufbau" and mc["phase"] == "aufbau":
                self.assertGreaterEqual(self.long_km(weeks[cur]), self.long_km(weeks[prev]))

    def test_every_fourth_week_is_recovery(self):
        weeks = self.plan()
        recov = [m for m, w in weeks.items() if w["meta"]["phase"] == "recovery"]
        for a, b in zip(recov, recov[1:]):
            self.assertEqual((pl.parse_date(b) - pl.parse_date(a)).days, 28)

    def test_long_run_cap(self):
        self.assertLessEqual(max(self.long_km(w) or 0 for w in self.plan().values()), 36.0)

    def test_taper_reduces_before_race(self):
        weeks = self.plan()
        peak = self.long_km(weeks["2027-07-26"])
        self.assertLess(self.long_km(weeks["2027-08-16"]), peak)
        self.assertEqual(weeks["2027-08-23"]["meta"]["phase"], "wettkampf")

    def test_race_day_unit(self):
        w = self.plan()["2027-08-23"]
        self.assertEqual(w["days"]["Samstag"]["units"][0]["name"], "Wettkampf: Ultramarathon 100 km")

    def test_offset_weeks_moves_progression(self):
        base = pl.generate_plan({}, date(2026, 11, 9), date(2026, 11, 9), TODAY)["2026-11-09"]
        ahead = pl.generate_plan({"progression": {"offsetWeeks": 1}}, date(2026, 11, 9), date(2026, 11, 9), TODAY)["2026-11-09"]
        # 2026-11-09 ist Recovery -> +1 Woche = erste Aufbauwoche des naechsten Blocks, also mehr Umfang
        self.assertEqual(base["meta"]["phase"], "recovery")
        self.assertEqual(ahead["meta"]["phase"], "aufbau")
        self.assertGreater(self.long_km(ahead), self.long_km(base))

    def test_deload_reduces_volume(self):
        mon = date(2026, 11, 2)
        base = week(mon)
        low = week(mon, {"deload": {"2026-11-02": {"active": True}}})
        self.assertLess(low["meta"]["targets"]["runVolumeKm"], base["meta"]["targets"]["runVolumeKm"])
        self.assertLess(self.long_km(low), self.long_km(base))


class RunSettings(unittest.TestCase):
    MON = date(2027, 3, 1)

    def long_km(self, raw):
        w = week(self.MON, raw)
        u = find(w, next(d for d in w["days"] if find(w, d, "Langer Lauf")), "Langer Lauf")
        return float(u["detail"].split(" km")[0].replace(",", "."))

    def test_scale_reduces_and_increases(self):
        base = self.long_km({})
        self.assertLess(self.long_km({"settings": {"runScalePct": 70}}), base)
        self.assertGreater(self.long_km({"settings": {"runScalePct": 120}}), base)

    def test_scale_is_clamped(self):
        self.assertEqual(self.long_km({"settings": {"runScalePct": 5}}), self.long_km({"settings": {"runScalePct": 50}}))

    def test_long_run_cap_setting(self):
        self.assertLessEqual(self.long_km({"settings": {"longRunMaxKm": 20}}), 20)

    def test_manual_override_for_one_week(self):
        raw = {"runOverrides": {pl.iso(self.MON): {"longKm": 18.5}}}
        self.assertEqual(self.long_km(raw), 18.5)
        self.assertNotEqual(float(week(self.MON + timedelta(days=7), raw)["meta"]["runKm"]["long"]), 18.5)

    def test_meta_exposes_run_km_and_bad_overrides_ignored(self):
        w = week(self.MON, {"runOverrides": {pl.iso(self.MON): {"longKm": "abc", "z2Km": -3}}})
        self.assertGreater(w["meta"]["runKm"]["long"], 10)
        self.assertEqual(pl.normalize_inputs({"runOverrides": {"2027-03-01": {"longKm": 500}}})["runOverrides"], {})


class NewTrainingStructure(unittest.TestCase):
    """Rad fast taeglich, VO2max-Laeufe, Schwelle auf dem Rad, sanfter Start."""
    START = date(2026, 10, 5)   # Fortschrittsschritt 0

    def names(self, w):
        return [u["name"] for u in all_units(w)]

    def test_first_week_is_gentle(self):
        w = week(self.START)
        z2 = [u for u in all_units(w) if u["name"] == "Rad Zone 2"]
        self.assertTrue(z2)
        self.assertTrue(all(u["plannedDurationMin"] == 45 for u in z2))
        self.assertNotIn("Schwellentraining Rad", self.names(w))     # erst ab dem 2. Aufbauschritt
        runs = {wd for wd, d in w["days"].items() if any(u["type"] == "lauf" for u in d["units"])}
        self.assertEqual(len(runs), 3)

    def test_threshold_and_four_run_days_come_later(self):
        w = week(date(2026, 11, 16))
        self.assertIn("Schwellentraining Rad", self.names(w))
        runs = {wd for wd, d in w["days"].items() if any(u["type"] == "lauf" for u in d["units"])}
        self.assertEqual(len(runs), 4)

    def test_bike_duration_grows_to_cap(self):
        durs = []
        for k in range(0, 44, 4):   # bis vor den Taper
            w = week(self.START + timedelta(days=7 * k))
            z = [u["plannedDurationMin"] for u in all_units(w) if u["name"] == "Rad Zone 2"]
            if z and w["meta"]["phase"] == "aufbau":
                durs.append(max(z))
        self.assertEqual(durs, sorted(durs))
        self.assertLessEqual(max(durs), 60)
        self.assertGreater(max(durs), 45)

    def test_threshold_ramps_to_two_times_twenty(self):
        w = week(self.START + timedelta(days=7 * 40))
        thr = next(u for u in all_units(w) if u["name"] == "Schwellentraining Rad")
        self.assertIn("2×20 min", thr["detail"])
        self.assertTrue(thr["keySession"])

    def test_vo2_intervals_ramp_and_are_not_fasted(self):
        a = next(u for u in all_units(week(self.START)) if u["name"] == "VO2max-Intervalle")
        self.assertIn("5×2 min ALL OUT", a["detail"])
        b = next(u for u in all_units(week(self.START + timedelta(days=7 * 40))) if u["name"] == "VO2max-Intervalle")
        self.assertRegex(b["detail"], r"[56]×4 min")
        self.assertNotIn("nüchtern Uhr", a["detail"])
        self.assertIn("nicht nüchtern", a["detail"])

    def test_long_ride_off_by_default_and_switchable(self):
        for k in range(8):
            self.assertNotIn("Langes Rad Zone 2", self.names(week(self.START + timedelta(days=7 * k))))
        w = week(date(2026, 11, 16), {"settings": {"includeLongRide": True}})
        self.assertIn("Langes Rad Zone 2", self.names(w))

    def test_hard_bike_not_next_to_vo2(self):
        for k in range(1, 30):
            w = week(self.START + timedelta(days=7 * k))
            idx = {u["name"]: i for i, (wd, d) in enumerate(w["days"].items()) for u in d["units"]}
            if "VO2max-Intervalle" in idx and "Schwellentraining Rad" in idx:
                self.assertGreater(abs(idx["VO2max-Intervalle"] - idx["Schwellentraining Rad"]), 1, k)

    def test_bike_nearly_every_day(self):
        w = week(date(2026, 11, 16))
        bike_days = sum(1 for d in w["days"].values() if any(u["type"] == "rad" for u in d["units"]))
        self.assertGreaterEqual(bike_days, 5)


class GymRules(unittest.TestCase):
    """Beintraining im Studio: nach Fruehschicht ja, an Spaetschicht-Tagen nie."""

    def heavy_days(self, w):
        return [wd for wd, d in w["days"].items() if any(u["name"] == "Schweres Beintraining" for u in d["units"])]

    def test_never_on_late_shift_days(self):
        rnd = random.Random(7)
        for trial in range(60):
            mon = date(2026, 11, 2) + timedelta(days=7 * trial)
            shifts = {}
            for i in range(7):
                if rnd.random() < 0.7:
                    start = rnd.choice(["07:00", "08:00", "13:00", "15:00", "16:00"])
                    shifts[pl.iso(mon + timedelta(days=i))] = [{"start": start, "end": pl.min_to_hm(pl.hm_to_min(start) + 360)}]
            w = week(mon, {"shifts": shifts})
            for wd in self.heavy_days(w):
                idx = list(w["days"]).index(wd)
                sh = shifts.get(pl.iso(mon + timedelta(days=idx)))
                if sh:
                    self.assertLess(pl.hm_to_min(sh[0]["start"]), 12 * 60, f"{mon} {wd}: Beine an Spaetschicht")

    def test_after_early_shift_it_happens_at_the_gym(self):
        mon = date(2026, 11, 2)
        shifts = {pl.iso(mon + timedelta(days=i)): [{"start": "07:00", "end": "13:00"}] for i in range(5)}
        w = week(mon, {"shifts": shifts})
        days = self.heavy_days(w)
        self.assertEqual(len(days), 1)
        u = find(w, days[0], "Schweres Beintraining")
        self.assertIn("im Studio direkt nach der Schicht", u["detail"])
        self.assertIn("13:20 Uhr", u["detail"])        # Schichtende 13:00 + 20 min

    def test_only_late_shifts_means_no_heavy_legs_on_work_days(self):
        mon = date(2026, 11, 2)
        shifts = {pl.iso(mon + timedelta(days=i)): [{"start": "16:00", "end": "22:00"}] for i in range(7)}
        w = week(mon, {"shifts": shifts})
        self.assertEqual(self.heavy_days(w), [])
        self.assertIn("schweres Beintraining", w["note"])

    def test_no_overlap_after_gym_on_early_shift_day(self):
        mon = date(2026, 11, 2)
        shifts = {pl.iso(mon + timedelta(days=i)): [{"start": "07:00", "end": "13:00"}] for i in range(5)}
        w = week(mon, {"shifts": shifts})
        for wd, d in w["days"].items():
            timed = sorted((int(m.group(1)) * 60 + int(m.group(2)), u["plannedDurationMin"], u["name"])
                           for u in d["units"] if u["type"] != "emom"
                           for m in [__import__("re").search(r"(\d{2}):(\d{2}) Uhr", u["detail"])] if m)
            for (s1, d1, n1), (s2, d2, n2) in zip(timed, timed[1:]):
                self.assertLessEqual(s1 + d1 - 12, s2, f"{wd}: {n1}/{n2}")


class TrainingTargets(unittest.TestCase):
    """Watt- und Pace-Vorgaben kommen automatisch aus Garmin-Werten (metrics), per Einstellung ueberschreibbar."""
    MET = {"ftpW": 230, "ftpStale": True, "ltHr": 174, "pace5kSec": 290.4}

    def unit(self, raw, mon, name):
        return next(u for u in all_units(week(mon, raw)) if u["name"] == name)

    def test_defaults_without_metrics(self):
        z2 = self.unit({}, date(2026, 10, 5), "Rad Zone 2")
        self.assertIn("165 W", z2["detail"])
        vo2 = self.unit({}, date(2026, 10, 5), "VO2max-Intervalle")
        self.assertNotIn("Ziel-Pace", vo2["detail"])

    def test_threshold_uses_ftp_zone4_and_heart_rate(self):
        thr = self.unit({"metrics": self.MET}, date(2026, 11, 16), "Schwellentraining Rad")
        self.assertIn("Zone 4", thr["detail"])
        self.assertIn("210–230 W", thr["detail"])         # 92-100 % von 230 W
        self.assertIn("FTP von 230 W", thr["detail"])
        self.assertIn("HF ca. 164–171", thr["detail"])    # Laktatschwellen-Puls 174

    def test_manual_ftp_overrides_garmin(self):
        thr = self.unit({"metrics": self.MET, "settings": {"ftpW": 260}}, date(2026, 11, 16), "Schwellentraining Rad")
        self.assertIn("FTP von 260 W", thr["detail"])
        z2 = self.unit({"metrics": self.MET, "settings": {"ftpW": 260}}, date(2026, 11, 16), "Rad Zone 2")
        self.assertIn("185 W", z2["detail"])              # 72 % von 260 W

    def test_vo2_pace_from_5k_prediction_and_shorter_reps_are_faster(self):
        short = self.unit({"metrics": self.MET}, date(2026, 10, 5), "VO2max-Intervalle")           # 5x2 min
        self.assertIn("Ziel-Pace 4:", short["detail"])
        self.assertIn("5-km-Prognose", short["detail"])
        tg = pl.training_targets(pl.normalize_inputs({"metrics": self.MET}))
        self.assertGreater(tg["pace5kSec"], 280)
        p2 = pl.vo2_pace_text(tg, 2)
        p4 = pl.vo2_pace_text(tg, 4)
        self.assertNotEqual(p2, p4)
        self.assertTrue(p2.split()[1] < p4.split()[1])    # 2-min-Intervalle schneller als 4-min

    def test_manual_5k_time_overrides_prediction(self):
        tg = pl.training_targets(pl.normalize_inputs({"metrics": self.MET, "settings": {"ref5kSec": 1200}}))
        self.assertEqual(tg["pace5kSec"], 240)
        self.assertIn("eingetragenen", tg["paceSource"])

    def test_stale_ftp_is_flagged(self):
        self.assertTrue(pl.training_targets(pl.normalize_inputs({"metrics": self.MET}))["ftpStale"])
        self.assertFalse(pl.training_targets(pl.normalize_inputs({"metrics": self.MET, "settings": {"ftpW": 250}}))["ftpStale"])


class Sickness(unittest.TestCase):
    RAW = {"sick": {"from": "2026-11-03", "to": "2026-11-06"}}

    def test_sick_days_have_no_units(self):
        w = week(date(2026, 11, 2), self.RAW)
        for wd in ("Dienstag", "Mittwoch", "Donnerstag", "Freitag"):
            self.assertEqual(w["days"][wd]["units"], [])
            self.assertIn("Krank", w["days"][wd]["focus"])
        self.assertTrue(units(w, "Montag"))

    def test_return_is_easy_first(self):
        w = week(date(2026, 11, 9), self.RAW)
        for wd in ("Samstag", "Sonntag", "Montag"):
            if wd == "Montag":
                continue
        # 07.-09.11. (Tag 1-3 nach Krankheit): nur lockeres Rad, kein Lauf
        self.assertEqual([u["name"] for u in units(w, "Montag")], ["Rad Zone 1 (locker)"])
        # Tag 4 nach der Krankheit: noch keine Schluesseleinheiten
        names = [u["name"] for u in units(w, "Dienstag")]
        for forbidden in ("VO2max-Intervalle", "Langer Lauf", "Langes Rad Zone 2", "Schweres Beintraining", "Schwellentraining Rad"):
            self.assertNotIn(forbidden, names)

    def test_ramp_back_to_normal(self):
        w1 = week(date(2026, 11, 16), self.RAW)
        w2 = week(date(2026, 12, 7), self.RAW)
        self.assertLess(w1["meta"]["targets"]["timeMin"], w2["meta"]["targets"]["timeMin"])

    def test_progression_pauses_after_sickness(self):
        sick_weeks = pl.sick_pause_weeks(pl.normalize_inputs(self.RAW))
        self.assertEqual(sick_weeks, 1)
        mon = date(2026, 12, 7)
        healthy = pl.week_params(mon, pl.normalize_inputs({}))
        after = pl.week_params(mon, pl.normalize_inputs(self.RAW))
        self.assertEqual(after["p"], healthy["p"] - 1)


class AgendaOutput(unittest.TestCase):
    def test_agenda_contains_shift_and_event(self):
        raw = {"shifts": {"2026-10-05": [{"start": "16:00", "end": "22:00"}]},
               "events": [{"date": "2026-10-06", "title": "Schulung", "kind": "schule", "start": "09:00", "end": "13:00"}]}
        agenda = pl.build_agenda(raw, TODAY)
        by_date = {a["date"]: a for a in agenda}
        self.assertEqual(by_date["2026-10-05"]["items"][0]["kind"], "arbeit")
        self.assertEqual(by_date["2026-10-06"]["items"][0]["kind"], "schule")

    def test_agenda_skips_past_days(self):
        raw = {"shifts": {"2026-10-01": [{"start": "10:00", "end": "16:00"}]}}
        self.assertEqual(pl.build_agenda(raw, TODAY), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
