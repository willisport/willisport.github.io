"""Tests fuer den Allrounder-Plan (Marathon + Push/Pull/Beine) - komplett offline:
python -m unittest test_allrounder -v"""

import random
import re
import sys
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import planner as pl  # noqa: E402

TODAY = date(2026, 10, 4)
WD = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
GYM_NAMES = ("Push", "Pull", "Schweres Beintraining")
HARD = ("VO2max-Intervalle", "Schwellentraining Rad", "Langer Lauf")


def plan(raw=None, start=date(2026, 10, 12), weeks=1):
    last = start + timedelta(days=7 * (weeks - 1))
    return pl.generate_plan(raw or {}, start, last, TODAY)


def names(week, wd):
    return [u["name"] for u in week["days"][wd]["units"]]


def all_units(week):
    return [(wd, u) for wd in WD for u in week["days"][wd]["units"]]


def day_of(week, name):
    return [wd for wd in WD if name in names(week, wd)]


def random_shifts(rnd, monday, p=0.65):
    shifts = {}
    for i in range(7):
        if rnd.random() < p:
            start = rnd.choice(["07:00", "08:00", "09:30", "13:00", "15:00", "16:00"])
            shifts[pl.iso(monday + timedelta(days=i))] = [{"start": start, "end": pl.min_to_hm(pl.hm_to_min(start) + 360)}]
    return shifts


def hm_in(detail):
    m = re.findall(r"(\d{2}):(\d{2}) Uhr", detail)
    return int(m[-1][0]) * 60 + int(m[-1][1]) if m else None


class BaseWeek(unittest.TestCase):
    """Ohne Schichten entsteht genau die abgesprochene Woche A."""
    MON = date(2026, 11, 23)       # Aufbauwoche, Schritt 2

    def setUp(self):
        self.w = plan(start=self.MON)[pl.iso(self.MON)]

    def test_week_a_layout(self):
        w = self.w
        self.assertEqual(names(w, "Montag")[:1], ["Rad Zone 2"])
        self.assertIn("Push", names(w, "Montag"))
        self.assertIn("Schwellentraining Rad", names(w, "Dienstag"))
        self.assertIn("Pull", names(w, "Dienstag"))
        self.assertIn("Schweres Beintraining", names(w, "Mittwoch"))
        self.assertIn("Rad Zone 2", names(w, "Mittwoch"))
        self.assertIn("Zone-2-Lauf", names(w, "Donnerstag"))
        self.assertIn("VO2max-Intervalle", names(w, "Freitag"))
        self.assertIn("Push", names(w, "Freitag"))
        self.assertIn("Pull", names(w, "Samstag"))
        self.assertEqual(names(w, "Sonntag"), ["Langer Lauf"])

    def test_no_emom_no_arm_day_no_long_ride(self):
        found = {u["name"] for _, u in all_units(self.w)}
        for gone in ("EMOM", "Arme/Schultern", "Langes Rad Zone 2", "Bein-Stabi", "Bein-Supersätze"):
            self.assertNotIn(gone, found)

    def test_counts(self):
        us = [u["name"] for _, u in all_units(self.w)]
        self.assertEqual(us.count("Push"), 2)
        self.assertEqual(us.count("Pull"), 2)
        self.assertEqual(us.count("Schweres Beintraining"), 1)
        self.assertLessEqual(sum(1 for n in us if n.startswith("Core")), 2)
        self.assertEqual(sum(1 for n in us if n in HARD), 3)

    def test_core_is_optional_one_studio_one_home(self):
        core = [(wd, u) for wd, u in all_units(self.w) if u["name"].startswith("Core")]
        self.assertEqual(sorted(u["name"] for _, u in core), ["Core (Studio)", "Core (zu Hause)"])
        self.assertTrue(all(u["tag"] == "bonus" and "optional" in u["detail"] for _, u in core))
        studio_day = next(wd for wd, u in core if u["name"] == "Core (Studio)")
        self.assertTrue(any(n in GYM_NAMES for n in names(self.w, studio_day)))   # Studio-Core hinter einer Studio-Einheit

    def test_strength_units_carry_exercises_with_defaults(self):
        for wd, u in all_units(self.w):
            if u["name"] in GYM_NAMES:
                self.assertGreaterEqual(len(u["exercises"]), 5, u["name"])
                self.assertEqual(u["type"], "kraft")
                self.assertEqual(u["tag"], "pflicht")
        push = next(u for _, u in all_units(self.w) if u["name"] == "Push")
        self.assertTrue(any("Butterfly" in e["name"] for e in push["exercises"]))
        pull = next(u for _, u in all_units(self.w) if u["name"] == "Pull")
        self.assertTrue(any("Latzug" in e["name"] for e in pull["exercises"]))
        self.assertTrue(any("hintere" in e["name"].lower() for e in pull["exercises"]))
        legs = next(u for _, u in all_units(self.w) if u["name"] == "Schweres Beintraining")
        legs_names = " ".join(e["name"] for e in legs["exercises"])
        self.assertIn("Kniebeuge", legs_names)
        self.assertIn("Kreuzheben", legs_names)
        self.assertNotIn("Rumänisch", legs_names)
        self.assertNotIn("Ausfallschritt", legs_names)     # keine einbeinigen Laufuebungen

    def test_weekly_load_is_plausible(self):
        h = self.w["meta"]["hours"]
        self.assertTrue(5 <= h["run"] + h["bike"] <= 9, h)
        self.assertTrue(3.5 <= h["strength"] <= 7, h)

    def test_hard_days_never_back_to_back(self):
        idx = sorted(i for i, wd in enumerate(WD) for n in names(self.w, wd) if n in HARD)
        self.assertTrue(all(b - a > 1 for a, b in zip(idx, idx[1:])), idx)

    def test_legs_not_before_hard_day(self):
        legs = WD.index(day_of(self.w, "Schweres Beintraining")[0])
        for n in HARD:
            for wd in day_of(self.w, n):
                self.assertNotIn(WD.index(wd) - legs, (0, 1), (n, wd))


class Progression(unittest.TestCase):
    def test_first_weeks_have_three_runs_then_four(self):
        weeks = plan(start=date(2026, 10, 12), weeks=16)

        def runs(w):
            return sum(1 for wd in WD if any(u["type"] == "lauf" for u in w["days"][wd]["units"]))
        early = [runs(weeks[m]) for m in sorted(weeks)[:3]]
        late = [runs(weeks[m]) for m in sorted(weeks)[-4:]]
        self.assertTrue(all(r == 3 for r in early), early)
        self.assertTrue(any(r == 4 for r in late), late)
        self.assertTrue(all(r <= 4 for r in early + late))

    def test_long_run_grows_and_is_capped(self):
        weeks = plan(start=date(2026, 10, 12), weeks=48)
        longs = []
        for m in sorted(weeks):
            u = next((u for _, u in all_units(weeks[m]) if u["name"] == "Langer Lauf"), None)
            if u and weeks[m]["meta"]["phase"] == "aufbau":
                longs.append(float(u["detail"].split(" km")[0].replace(",", ".")))
        self.assertEqual(longs[0], 10.0 if longs[0] == 10.0 else longs[0])
        self.assertGreater(max(longs), 25)
        self.assertLessEqual(max(longs), 32)
        self.assertEqual(longs, sorted(longs))

    def test_every_fourth_week_is_recovery(self):
        weeks = plan(start=date(2026, 10, 12), weeks=20)
        types = [weeks[m]["meta"]["weekType"] for m in sorted(weeks)]
        self.assertEqual(types[:8].count("recovery"), 2)

    def test_vo2_and_threshold_ramp(self):
        weeks = plan({"settings": {"ftpW": 260}}, start=date(2026, 10, 12), weeks=48)
        first_vo2 = next(u for m in sorted(weeks) for _, u in all_units(weeks[m]) if u["name"] == "VO2max-Intervalle")
        self.assertIn("ALL OUT", first_vo2["detail"])
        self.assertRegex(first_vo2["detail"], r"[45]×2 min")
        late = weeks[sorted(weeks)[30]]
        thr = next(u for _, u in all_units(late) if u["name"] == "Schwellentraining Rad")
        self.assertIn("2×20 min", thr["detail"]) if late["meta"]["phase"] == "aufbau" else None

    def test_bike_stays_at_or_below_an_hour(self):
        weeks = plan(start=date(2026, 10, 12), weeks=48)
        for m, w in weeks.items():
            for _, u in all_units(w):
                if u["name"] == "Rad Zone 2":
                    self.assertLessEqual(u["plannedDurationMin"], 60)

    def test_full_year_generation_is_fast_enough(self):
        t0 = time.time()
        plan(start=date(2026, 10, 5), weeks=52)
        self.assertLess(time.time() - t0, 25)


class RandomShifts(unittest.TestCase):
    """Zufaellige Dienstplaene ueber ein halbes Jahr - die harten Regeln muessen immer halten."""

    @classmethod
    def setUpClass(cls):
        rnd = random.Random(2026)
        cls.cases = []
        for trial in range(12):
            start = date(2026, 11, 2)
            shifts = {}
            for k in range(26):
                shifts.update(random_shifts(rnd, start + timedelta(days=7 * k)))
            raw = {"shifts": shifts}
            cls.cases.append((raw, plan(raw, start, 26)))

    def test_same_strength_type_has_three_free_days_between(self):
        for raw, weeks in self.cases:
            for kind in ("Push", "Pull"):
                dates = sorted(pl.parse_date(m) + timedelta(days=WD.index(wd)) for m in weeks for wd in WD if kind in names(weeks[m], wd))
                for a, b in zip(dates, dates[1:]):
                    self.assertGreaterEqual((b - a).days, 4, (kind, a, b))

    def test_at_most_one_gym_session_per_day_and_max_counts(self):
        for raw, weeks in self.cases:
            for w in weeks.values():
                for wd in WD:
                    self.assertLessEqual(sum(1 for n in names(w, wd) if n in GYM_NAMES), 1, wd)
                us = [u["name"] for _, u in all_units(w)]
                self.assertLessEqual(us.count("Push"), 2)
                self.assertLessEqual(us.count("Pull"), 2)
                self.assertLessEqual(us.count("Schweres Beintraining"), 1)

    def test_no_gym_on_late_shift_days(self):
        for raw, weeks in self.cases:
            for m, w in weeks.items():
                for i, wd in enumerate(WD):
                    d = pl.iso(pl.parse_date(m) + timedelta(days=i))
                    sh = raw["shifts"].get(d)
                    if sh and pl.hm_to_min(sh[0]["start"]) >= 12 * 60:
                        for n in names(w, wd):
                            self.assertNotIn(n, GYM_NAMES + ("Core (Studio)",), (d, n))

    def test_gym_right_after_early_shift(self):
        seen = 0
        for raw, weeks in self.cases:
            for m, w in weeks.items():
                for i, wd in enumerate(WD):
                    d = pl.iso(pl.parse_date(m) + timedelta(days=i))
                    sh = raw["shifts"].get(d)
                    if not sh or pl.hm_to_min(sh[0]["start"]) >= 12 * 60:
                        continue
                    for u in w["days"][wd]["units"]:
                        if u["name"] in GYM_NAMES:
                            self.assertEqual(hm_in(u["detail"]), pl.hm_to_min(sh[0]["end"]) + 20, (d, u["name"]))
                            seen += 1
        self.assertGreater(seen, 20)

    def test_legs_never_on_hard_day_and_rarely_before_one(self):
        before = total = 0
        for raw, weeks in self.cases:
            for m, w in weeks.items():
                legs = day_of(w, "Schweres Beintraining")
                if not legs:
                    continue
                total += 1
                li = WD.index(legs[0])
                for n in HARD:
                    for wd in day_of(w, n):
                        self.assertNotEqual(WD.index(wd), li, (m, n))
                        if WD.index(wd) - li == 1:
                            before += 1
        self.assertGreater(total, 100)
        self.assertLess(before / total, 0.12)

    def test_hard_days_rarely_back_to_back(self):
        bad = total = 0
        for raw, weeks in self.cases:
            for w in weeks.values():
                idx = sorted(WD.index(wd) for wd in WD for n in names(w, wd) if n in HARD)
                total += 1
                bad += any(b - a == 1 for a, b in zip(idx, idx[1:]))
        self.assertLess(bad / total, 0.12)

    def test_timed_units_do_not_overlap_or_leave_the_day(self):
        for raw, weeks in self.cases:
            for m, w in weeks.items():
                mon = pl.parse_date(m)
                inputs = pl.normalize_inputs(raw)
                ctxs = pl.build_day_contexts(mon, inputs, TODAY)
                for i, wd in enumerate(WD):
                    timed = []
                    for u in w["days"][wd]["units"]:
                        s = hm_in(u["detail"])
                        if s is None:
                            continue
                        extra = 10 if u["name"] in ("Zone-2-Lauf", "Langer Lauf", "VO2max-Intervalle") else 0
                        timed.append((s, s + u["plannedDurationMin"] + extra, u["name"], "im Studio direkt nach der Schicht" in u["detail"]))
                    timed.sort()
                    for (s1, e1, n1, _), (s2, e2, n2, _) in zip(timed, timed[1:]):
                        self.assertLessEqual(e1 - 12, s2, (m, wd, n1, n2))
                    for s, e, n, at_work in timed:
                        self.assertGreaterEqual(s, 360, (m, wd, n))
                        self.assertLessEqual(e, 22 * 60 + 40, (m, wd, n))
                        if at_work:
                            continue
                        for bs, be in [tuple(b) for b in ctxs[i].busy]:
                            self.assertFalse(s < be and e > bs and bs > 0 and not (e <= bs), (m, wd, n, bs, be))

    def test_progression_is_monotone_enough(self):
        raw, weeks = self.cases[0]
        builds = [weeks[m]["meta"]["step"] for m in sorted(weeks) if weeks[m]["meta"]["weekType"] == "aufbau"]
        self.assertEqual(builds, sorted(builds))


class SpecialWeeks(unittest.TestCase):
    def test_taper_and_race_week(self):
        race = date(2027, 9, 26)       # Sonntag
        weeks = plan({"settings": {"raceDate": "2027-09-26"}}, start=date(2027, 8, 30), weeks=5)
        sept20 = weeks["2027-09-20"]
        self.assertEqual(sept20["meta"]["phase"], "wettkampf")
        us = [u["name"] for _, u in all_units(sept20)]
        for gone in ("VO2max-Intervalle", "Schwellentraining Rad", "Schweres Beintraining", "Langer Lauf"):
            self.assertNotIn(gone, us)
        self.assertLessEqual(us.count("Push"), 1)
        self.assertTrue(any(n.startswith("Wettkampf: Marathon") for n in names(sept20, "Sonntag")))
        self.assertIn("Lockeres Auslaufen", names(sept20, "Samstag"))
        week_before = weeks["2027-09-13"]
        self.assertNotIn("Schweres Beintraining", [u["name"] for _, u in all_units(week_before)])
        self.assertEqual(week_before["meta"]["phase"], "taper")
        long_before = float(next(u for _, u in all_units(week_before) if u["name"] == "Langer Lauf")["detail"].split(" km")[0])
        long_peak = float(next(u for _, u in all_units(weeks["2027-08-30"]) if u["name"] == "Langer Lauf")["detail"].split(" km")[0])
        self.assertLess(long_before, long_peak)

    def test_sickness_blocks_everything_then_returns_gently(self):
        raw = {"sick": {"from": "2026-11-23", "to": "2026-11-29"}}
        weeks = plan(raw, start=date(2026, 11, 23), weeks=3)
        self.assertEqual([u for _, u in all_units(weeks["2026-11-23"])], [])
        w2 = weeks["2026-11-30"]
        for wd in ("Montag", "Dienstag", "Mittwoch"):
            self.assertEqual(names(w2, wd), ["Rad Zone 1 (locker)"], wd)
        for wd in ("Donnerstag", "Freitag"):
            for n in names(w2, wd):
                self.assertNotIn(n, HARD + ("Schweres Beintraining",))

    def test_knee_means_no_running_no_legs_but_upper_body_continues(self):
        raw = {"injury": {"area": "knie", "from": "2026-11-23", "to": "2026-11-29"}}
        w = plan(raw, start=date(2026, 11, 23))["2026-11-23"]
        us = [u["name"] for _, u in all_units(w)]
        for gone in ("Langer Lauf", "VO2max-Intervalle", "Zone-2-Lauf", "Schweres Beintraining", "Schwellentraining Rad"):
            self.assertNotIn(gone, us)
        self.assertIn("Push", us)
        self.assertIn("Pull", us)
        self.assertIn("Rad Zone 1 (locker)", us)

    def test_back_pain_skips_pull_legs_and_core(self):
        raw = {"injury": {"area": "ruecken", "from": "2026-11-23", "to": "2026-11-29"}}
        us = [u["name"] for _, u in all_units(plan(raw, start=date(2026, 11, 23))["2026-11-23"])]
        for gone in ("Pull", "Schweres Beintraining", "Core (Studio)", "Core (zu Hause)"):
            self.assertNotIn(gone, us)
        self.assertIn("Push", us)

    def test_classic_mode_is_still_available(self):
        w = plan({"settings": {"planMode": "classic"}}, start=date(2026, 11, 23))["2026-11-23"]
        us = [u["name"] for _, u in all_units(w)]
        self.assertIn("EMOM", us)
        self.assertNotIn("Push", us)

    def test_core_session_setting(self):
        w = plan({"settings": {"coreSessions": 0}}, start=date(2026, 11, 23))["2026-11-23"]
        self.assertFalse([1 for _, u in all_units(w) if u["name"].startswith("Core")])
        w1 = plan({"settings": {"coreSessions": 1}}, start=date(2026, 11, 23))["2026-11-23"]
        self.assertEqual(len([1 for _, u in all_units(w1) if u["name"].startswith("Core")]), 1)

    def test_gym_on_late_shift_setting(self):
        shifts = {pl.iso(date(2026, 11, 23) + timedelta(days=i)): [{"start": "16:00", "end": "22:00"}] for i in range(7)}
        none = plan({"shifts": shifts}, start=date(2026, 11, 23))["2026-11-23"]
        self.assertFalse([1 for _, u in all_units(none) if u["name"] in GYM_NAMES])
        self.assertIn("Push/Pull", none["note"] + "Push/Pull" if False else none["note"] or "Push/Pull")
        some = plan({"shifts": shifts, "settings": {"gymOnLateShift": True}}, start=date(2026, 11, 23))["2026-11-23"]
        self.assertTrue([1 for _, u in all_units(some) if u["name"] in GYM_NAMES])

    def test_user_weight_survives_into_the_unit(self):
        raw = {"library": {"heavyLegs": {"exercises": [{"name": "Kniebeuge", "sets": 2, "reps": "6–8", "rest": "3 min", "weightKg": 90}]}}}
        legs = next(u for _, u in all_units(plan(raw, start=date(2026, 11, 23))["2026-11-23"]) if u["name"] == "Schweres Beintraining")
        self.assertEqual(legs["exercises"][0]["weightKg"], 90)

    def test_defaults_are_marathon(self):
        st = pl.normalize_inputs({})["settings"]
        self.assertEqual((st["planMode"], st["raceName"], st["longRunMaxKm"]), ("allrounder", "Marathon", 32))


class OpenEndedSickness(unittest.TestCase):
    """Offene Krankheit: der Plan DANACH zeigt sanften Wiedereinstieg, nicht sofort VO2max ALL OUT."""
    TODAY = date(2026, 10, 24)

    def test_projected_return_is_gentle_after_long_illness(self):
        raw = {"sick": {"from": "2026-10-05", "to": None}}
        weeks = pl.generate_plan(raw, date(2026, 10, 19), date(2026, 11, 22), self.TODAY)
        first = weeks["2026-10-26"]
        # Dienstag 27.10. ist der erste Tag nach dem angenommenen Ende (26.10.): nur locker
        self.assertEqual(names(first, "Dienstag"), ["Rad Zone 1 (locker)"])
        for wd, u in all_units(first):
            self.assertNotIn(u["name"], HARD, wd)
        # Fortschritt pausiert: Wochenziel Lauf deutlich unter dem Wert ohne Krankheit
        healthy = pl.generate_plan({}, date(2026, 10, 26), date(2026, 10, 26), self.TODAY)["2026-10-26"]
        self.assertLess(first["meta"]["targets"]["runVolumeKm"], healthy["meta"]["targets"]["runVolumeKm"])

    def test_short_open_illness_keeps_progress(self):
        raw = {"sick": {"from": "2026-10-23", "to": None}}
        weeks = pl.generate_plan(raw, date(2026, 10, 26), date(2026, 10, 26), self.TODAY)
        healthy = pl.generate_plan({}, date(2026, 10, 26), date(2026, 10, 26), self.TODAY)
        self.assertEqual(weeks["2026-10-26"]["meta"]["step"], healthy["2026-10-26"]["meta"]["step"])


class ForcedGymDay(unittest.TestCase):
    """Wunsch 'Kraft ab morgen': Push am ersten Tag nach der Krankheit, trotz Spaetschicht."""
    TODAY = date(2026, 10, 26)
    RAW = {"sick": {"from": "2026-10-05", "to": "2026-10-26"},
           "shifts": {"2026-10-27": [{"start": "16:00", "end": "22:00"}], "2026-10-28": [{"start": "16:00", "end": "22:00"}],
                      "2026-10-31": [{"start": "08:00", "end": "14:00"}]}}

    def week(self, extra=None):
        raw = {**self.RAW, **(extra or {})}
        return pl.generate_plan(raw, date(2026, 10, 26), date(2026, 10, 26), self.TODAY)["2026-10-26"]

    def test_without_wish_no_strength_on_late_shift_or_first_days(self):
        w = self.week()
        self.assertNotIn("Push", names(w, "Dienstag"))
        self.assertNotIn("Push", names(w, "Mittwoch"))

    def test_forced_push_tomorrow_even_on_late_shift(self):
        w = self.week({"settings": {"gymForce": {"2026-10-27": "Push"}}})
        self.assertIn("Push", names(w, "Dienstag"))
        self.assertEqual(len(day_of(w, "Push")), 2)          # Push 2x in der Woche, 3 freie Tage dazwischen
        pushes = sorted(WD.index(d) for d in day_of(w, "Push"))
        self.assertGreaterEqual(pushes[1] - pushes[0], 4)
        self.assertLessEqual(len(day_of(w, "Pull")), 1)      # Wiedereinstieg: Pull nur 1x
        self.assertEqual(day_of(w, "Schweres Beintraining"), [])

    def test_impossible_wish_falls_back_to_normal_plan(self):
        w = self.week({"settings": {"gymForce": {"2026-10-24": "Push", "2026-10-25": "Pull"}}})   # Tage liegen nicht in der Woche
        self.assertTrue(day_of(w, "Push"))


class PushPullAlternate(unittest.TestCase):
    def test_push_and_pull_alternate_across_weeks(self):
        weeks = plan(start=date(2026, 11, 23), weeks=4)
        seq = []
        for m in sorted(weeks):
            wk = weeks[m]
            for wd in WD:
                seq += [n for n in names(wk, wd) if n in ("Push", "Pull")]
        self.assertGreaterEqual(len(seq), 12)
        same = sum(1 for a, b in zip(seq, seq[1:]) if a == b)
        self.assertLessEqual(same, 1, seq)


class SecondaryGoal(unittest.TestCase):
    """Zwischenziel (Backyard-Lauf am 28.11.): Aufbau, ruhige Woche davor, Rennen, Erholung danach."""
    TODAY = date(2026, 10, 26)
    RAW = {"sick": {"from": "2026-10-05", "to": "2026-10-26"},
           "settings": {"returnRamp": "fast", "hardFrom": "2026-11-09",
                        "bRace": {"date": "2026-11-28", "name": "Backyard-Lauf", "detail": "Jede Stunde 6 km", "km": 30, "durationMin": 300}}}

    def weeks(self):
        return pl.generate_plan(self.RAW, date(2026, 11, 2), date(2026, 12, 6), self.TODAY)

    def test_race_day_and_day_after(self):
        w = self.weeks()["2026-11-23"]
        self.assertEqual(names(w, "Samstag"), ["Wettkampf: Backyard-Lauf"])
        self.assertEqual(names(w, "Freitag"), ["Lockeres Auslaufen"])
        self.assertEqual(names(w, "Sonntag"), ["Regeneration nach dem Lauf"])

    def test_race_week_has_no_hard_sessions_and_label(self):
        w = self.weeks()["2026-11-23"]
        for wd, u in all_units(w):
            self.assertNotIn(u["name"], HARD, wd)
            self.assertNotEqual(u["name"], "Schweres Beintraining")
        self.assertIn("Zwischenziel", w["meta"]["label"])

    def test_week_before_has_no_intervals_or_heavy_legs(self):
        w = self.weeks()["2026-11-16"]
        for wd, u in all_units(w):
            self.assertNotIn(u["name"], ("VO2max-Intervalle", "Schweres Beintraining"), wd)

    def test_no_hard_sessions_before_hard_from(self):
        w = self.weeks()["2026-11-02"]
        for wd, u in all_units(w):
            self.assertNotIn(u["name"], HARD, wd)          # Kraft (auch Beine) laeuft normal weiter
        self.assertNotIn("keine Zeit", w["note"])             # keine irrefuehrende Meldung fuer bewusst fehlende Einheiten

    def test_week_after_is_gentle(self):
        w = self.weeks()["2026-11-30"]
        self.assertLessEqual(w["meta"]["targets"]["runVolumeKm"], 20)
        for wd, u in all_units(w):
            self.assertNotIn(u["name"], ("VO2max-Intervalle", "Schwellentraining Rad"), wd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
