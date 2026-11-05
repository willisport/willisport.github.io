"""Aktivitaeten ohne passende geplante Einheit erscheinen als erledigte Zusatzeinheit:
python -m unittest test_unplanned_activity -v"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sync  # noqa: E402


def day(units):
    return {"weekday": "Mittwoch", "focus": "Rad", "units": units}


BIKE = {"name": "Rad Zone 2", "type": "rad", "tag": "pflicht", "detail": "165 W · 60 min"}
RUN = {"startTime": "2026-11-04T07:30:00", "type": "lauf", "durationMin": 42, "distanceKm": 6.2, "avgHr": 141}


class UnplannedActivity(unittest.TestCase):
    TODAY = datetime(2026, 11, 5)

    def build(self, units, acts, d=datetime(2026, 11, 4)):
        return sync.build_day(day(units), d, acts, self.TODAY, {})

    def test_run_instead_of_bike_shows_as_done_extra_and_bike_stays_skipped(self):
        out = self.build([BIKE], [RUN])
        by = {u["name"]: u for u in out["units"]}
        self.assertEqual(by["Rad Zone 2"]["status"], "skipped")
        self.assertEqual(by["Lauf (zusätzlich)"]["status"], "done")
        self.assertIn("6.2 km", by["Lauf (zusätzlich)"]["detail"])
        self.assertEqual(by["Lauf (zusätzlich)"]["tag"], "extra")

    def test_matching_activity_is_not_duplicated(self):
        run_unit = {"name": "Zone-2-Lauf", "type": "lauf", "tag": "pflicht", "detail": "6 km"}
        out = self.build([run_unit], [RUN])
        self.assertEqual([u["name"] for u in out["units"]], ["Zone-2-Lauf"])

    def test_short_or_other_activities_are_ignored(self):
        short = {**RUN, "durationMin": 5}
        walk = {**RUN, "type": "sonstiges"}
        out = self.build([BIKE], [short, walk])
        self.assertEqual([u["name"] for u in out["units"]], ["Rad Zone 2"])

    def test_future_days_get_no_extras(self):
        future = {**RUN, "startTime": "2026-11-06T07:30:00"}
        out = self.build([BIKE], [future], d=datetime(2026, 11, 6))
        self.assertEqual([u["name"] for u in out["units"]], ["Rad Zone 2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
