"""Tests fuer stock_news.py (ohne Netz): Alarm-Logik, Flut-Schutz, Zeitsteuerung."""

import unittest
from datetime import datetime

import stock_news as sn

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=sn.BERLIN)   # Montag


def entry(name, titles, pct=None):
    news = [{"title": t, "source": "Test", "link": "", "time": NOW} for t in titles]
    move = {"price": 100.0, "pct": pct, "currency": "USD"} if pct is not None else None
    return {"name": name, "news": news, "move": move}


class FindAlertsTest(unittest.TestCase):
    def test_big_move_alerts_once(self):
        state = {}
        alerts, _ = sn.find_alerts([entry("X", [], pct=-7.0)], NOW, state)
        self.assertEqual(len(alerts), 1)
        state["alerts"] = [a[0] for a in alerts]
        again, _ = sn.find_alerts([entry("X", [], pct=-7.5)], NOW, state)
        self.assertEqual(again, [])

    def test_small_move_no_alert(self):
        alerts, _ = sn.find_alerts([entry("X", [], pct=-2.0)], NOW, {})
        self.assertEqual(alerts, [])

    def test_only_newest_keyword_headline_sent(self):
        titles = ["CEO tritt zurück: Rücktritt bei X", "Klage gegen X eingereicht", "X Quartal ruhig"]
        alerts, silent = sn.find_alerts([entry("X", titles)], NOW, {})
        self.assertEqual(len(alerts), 1)
        self.assertIn("Rücktritt", alerts[0][1])
        self.assertEqual(len(silent), 1)

    def test_daily_cap_per_stock(self):
        state = {}
        sent_total = 0
        for i in range(5):
            alerts, silent = sn.find_alerts([entry("X", [f"Klage Nummer {i}"])], NOW, state)
            state["alerts"] = (state.get("alerts") or []) + [a[0] for a in alerts] + silent
            sent_total += len(alerts)
        self.assertEqual(sent_total, sn.MAX_NEWS_ALERTS_PER_DAY)


class DigestTimesTest(unittest.TestCase):
    def test_due_at_8_on_weekday(self):
        self.assertEqual(sn.due_digests(NOW.replace(hour=8, minute=10), {}), ["digest_08:00"])

    def test_not_twice_per_day(self):
        state = {"digest_08:00": "2026-11-16"}
        self.assertEqual(sn.due_digests(NOW.replace(hour=8, minute=10), state), [])

    def test_no_digest_on_weekend(self):
        sat = datetime(2026, 11, 14, 8, 10, tzinfo=sn.BERLIN)
        self.assertEqual(sn.due_digests(sat, {}), [])

    def test_too_late_is_skipped(self):
        self.assertEqual(sn.due_digests(NOW.replace(hour=11, minute=0), {}), [])


class TipTest(unittest.TestCase):
    def test_tip_for_resignation(self):
        self.assertIn("Chef", sn.tip_for("Huang Rücktritt bei Nvidia"))


if __name__ == "__main__":
    unittest.main()
