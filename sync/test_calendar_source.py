"""Tests fuer calendar_source.py (Google-Kalender per iCal-Adresse), komplett offline."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import calendar_source as cs  # noqa: E402

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:abc123@google.com
DTSTART:20261007T070000Z
DTEND:20261007T110000Z
SUMMARY:Berufsschule\, Block 2
LOCATION:Steglitz
END:VEVENT
BEGIN:VEVENT
UID:summer@google.com
DTSTART:20260707T070000Z
DTEND:20260707T090000Z
SUMMARY:Seminar Sommer
END:VEVENT
BEGIN:VEVENT
UID:allday
DTSTART;VALUE=DATE:20261010
SUMMARY:Geburtstag
END:VEVENT
BEGIN:VEVENT
UID:own1
DTSTART;TZID=Europe/Berlin:20261012T070000
DTEND;TZID=Europe/Berlin:20261012T130000
SUMMARY:Arbeit
END:VEVENT
BEGIN:VEVENT
UID:own2
DTSTART;TZID=Europe/Berlin:20261012T153000
SUMMARY:Training Lauf
END:VEVENT
BEGIN:VEVENT
UID:vorl
DTSTART;TZID=Europe/Berlin:20261013T090000
SUMMARY:Vorläufig: Schulung
END:VEVENT
BEGIN:VEVENT
UID:web1
DTSTART;TZID=Europe/Berlin:20261014T130000
DTEND;TZID=Europe/Berlin:20261014T143000
SUMMARY:Webinar Dein Start
END:VEVENT
BEGIN:VEVENT
UID:arzt
DTSTART;TZID=Europe/Berlin:20261015T081500
DTEND;TZID=Europe/Berlin:20261015T091500
SUMMARY:Zahnarzt
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
UID:gone
DTSTART;TZID=Europe/Berlin:20261016T100000
SUMMARY:Abgesagt
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


class ParseIcs(unittest.TestCase):
    def setUp(self):
        self.ev = {e["title"]: e for e in cs.parse_ics(ICS)}

    def test_utc_is_converted_to_berlin_winter_and_summer(self):
        self.assertEqual(self.ev["Berufsschule, Block 2"]["start"], "09:00")   # Oktober: Sommerzeit (UTC+2)
        self.assertEqual(self.ev["Seminar Sommer"]["start"], "09:00")
        self.assertEqual(self.ev["Berufsschule, Block 2"]["end"], "13:00")

    def test_skips_own_entries_allday_preliminary_and_cancelled(self):
        for t in ("Arbeit", "Training Lauf", "Geburtstag", "Vorläufig: Schulung", "Abgesagt"):
            self.assertNotIn(t, self.ev)

    def test_kinds_and_online_travel(self):
        self.assertEqual(self.ev["Berufsschule, Block 2"]["kind"], "schule")
        self.assertEqual(self.ev["Zahnarzt"]["kind"], "termin")
        self.assertEqual(self.ev["Webinar Dein Start"]["travelMin"], 0)
        self.assertIsNone(self.ev["Zahnarzt"]["travelMin"])

    def test_from_date_filters_past(self):
        titles = {e["title"] for e in cs.parse_ics(ICS, date(2026, 10, 1))}
        self.assertNotIn("Seminar Sommer", titles)
        self.assertIn("Zahnarzt", titles)

    def test_ids_are_stable_and_unique(self):
        a = [e["id"] for e in cs.parse_ics(ICS)]
        self.assertEqual(a, [e["id"] for e in cs.parse_ics(ICS)])
        self.assertEqual(len(a), len(set(a)))


class LoadAndMerge(unittest.TestCase):
    def test_no_url_or_failing_fetch_returns_empty(self):
        self.assertEqual(cs.load_events(None), [])
        self.assertEqual(cs.load_events("", None), [])

        def boom(_):
            raise OSError("offline")
        self.assertEqual(cs.load_events("http://x", None, fetch=boom), [])

    def test_merge_skips_duplicates_of_manual_events(self):
        inputs = {"events": [{"date": "2026-10-15", "start": "08:15", "title": "Zahnarzt (manuell)"}]}
        events = cs.load_events("http://x", None, fetch=lambda _: ICS)
        added = cs.merge_into_inputs(inputs, events)
        self.assertEqual(added, len(events) - 1)
        self.assertEqual(sum(1 for e in inputs["events"] if e["date"] == "2026-10-15"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
