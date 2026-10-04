"""Integrationstest: sync.main() mit gefaelschten Garmin-Daten, in einem
temporaeren Datenordner - prueft, dass Plan-Eingaben (verschluesselte
Overrides) wirklich bis in training-data.enc.json und plan.enc.json durchkommen.
Laeuft komplett offline: python -m unittest test_sync_integration -v"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import crypto_utils  # noqa: E402
import sync  # noqa: E402

REPO = Path(__file__).parent.parent
DEK = os.urandom(32)
DEK_B64 = crypto_utils.b64(DEK)

PLAN_INPUTS = {
    "shifts": {
        "2026-10-05": [{"start": "16:00", "end": "22:00"}],
        "2026-10-19": [{"start": "07:00", "end": "13:00"}],
    },
    "events": [{"date": "2026-10-06", "title": "Schulung Steglitz", "kind": "schule", "start": "09:00", "end": "13:00"}],
    "progression": {"offsetWeeks": 0},
    "library": {"core": {"exercises": [{"name": "Hollow Hold", "sets": 3, "reps": "30 s", "rest": "30 s"}]}},
}


class FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 10, 7, 9, 0)
        return base.replace(tzinfo=tz) if tz else base


class SyncIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data").mkdir()
        shutil.copy(REPO / "data" / "plan-template.json", self.tmp / "data" / "plan-template.json")
        overrides = dict(PLAN_INPUTS)
        raw_overrides = {"__plan": overrides, "__deload": {}}
        enc = crypto_utils.encrypt_json_bytes(DEK, json.dumps(raw_overrides).encode("utf-8"))
        (self.tmp / "data" / "overrides.enc.json").write_text(json.dumps(enc), encoding="utf-8")

        d = self.tmp / "data"
        self.patches = [
            mock.patch.object(sync, "PLAN_PATH", d / "plan-template.json"),
            mock.patch.object(sync, "OUTPUT_PATH", d / "training-data.json"),
            mock.patch.object(sync, "ENCRYPTED_OUTPUT_PATH", d / "training-data.enc.json"),
            mock.patch.object(sync, "OVERRIDES_PATH", d / "overrides.enc.json"),
            mock.patch.object(sync, "PLAN_OUT_PATH", d / "plan.enc.json"),
            mock.patch.object(sync, "datetime", FakeDatetime),
            mock.patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": DEK_B64}, clear=False),
            mock.patch.object(sync, "cleanup_stale_requests", lambda *_: None),
            mock.patch.object(sync.garmin_source, "get_client", lambda: object()),
            mock.patch.object(sync.garmin_source, "fetch_activities", lambda *a, **k: []),
            mock.patch.object(sync.garmin_source, "fetch_daily_metrics", lambda *a, **k: {"totalMin": 480, "sleepScore": 80}),
            mock.patch.object(sync.garmin_source, "fetch_hrv_baseline", lambda *a, **k: 60),
            mock.patch.object(sync.garmin_source, "fetch_vo2max_history", lambda *a, **k: [{"date": "2026-10-01", "value": 53.0}]),
            mock.patch.object(sync.garmin_source, "fetch_steps_history", lambda *a, **k: {}),
            mock.patch.object(sync.garmin_source, "fetch_recovery_trend", lambda *a, **k: []),
            mock.patch.object(sync.garmin_source, "fetch_race_predictions", lambda *a, **k: {}),
            mock.patch.object(sync.health_bridge_source, "fetch_latest_weight", lambda *a, **k: {"date": "2026-10-07", "weightKg": 80.5}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, name):
        return crypto_utils.decrypt_json(DEK, json.loads((self.tmp / "data" / name).read_text(encoding="utf-8")))

    def test_inputs_flow_into_plan_and_outputs(self):
        sync.main()
        data = self.read("training-data.enc.json")

        # Dienstag 06.10. (Schulung 9-13): Rad nuechtern um 06:00
        week_days = {d["weekday"]: d for d in data["week"]["days"]}
        self.assertIn("Schule/Seminar 09:00–13:00", week_days["Dienstag"]["focus"])
        self.assertEqual(data["today"]["dayFocus"], week_days["Mittwoch"]["focus"])
        rad = [u for d in data["week"]["days"] for u in d["units"] if u["type"] == "rad" and d["weekday"] == "Dienstag"]
        self.assertTrue(rad, [u["name"] for u in week_days["Dienstag"]["units"]])
        self.assertTrue(any(("06:00 Uhr, nüchtern" in u["detail"]) or ("06:30 Uhr, nüchtern" in u["detail"]) for u in rad), [u["detail"] for u in rad])

        # Wochenziele + Label kommen aus dem Planer
        self.assertIn("Aufbau", data["week"]["label"])
        self.assertGreater(data["week"]["targets"]["runVolumeKm"], 20)

        # Agenda, Bibliothek, Plan-Zustand
        kinds = {(a["date"], i["kind"]) for a in data["agenda"] for i in a["items"]}
        self.assertIn(("2026-10-19", "arbeit"), kinds)
        self.assertNotIn(("2026-10-06", "schule"), kinds)   # vergangene Tage fehlen in der Heute-Agenda
        self.assertEqual(data["library"]["core"]["exercises"][0]["name"], "Hollow Hold")
        self.assertEqual(data["planState"]["counts"], {"shifts": 2, "events": 1})

        # Langzeitplan bis September 2027
        plan = self.read("plan.enc.json")
        self.assertIn("2026-10-12", plan["weeks"])
        self.assertGreaterEqual(max(plan["weeks"]), "2027-09-20")
        self.assertGreaterEqual(len(data["upcomingPlan"]), 50)
        all_kinds = {(a["date"], i["kind"]) for a in plan["agenda"] for i in a["items"]}
        self.assertIn(("2026-10-06", "schule"), all_kinds)   # Langzeit-Agenda enthaelt alle Eingaben

    def test_plan_file_only_rewritten_when_changed(self):
        sync.main()
        first = (self.tmp / "data" / "plan.enc.json").read_bytes()
        sync.main()
        self.assertEqual(first, (self.tmp / "data" / "plan.enc.json").read_bytes())

    def test_runs_without_any_inputs(self):
        (self.tmp / "data" / "overrides.enc.json").unlink()
        sync.main()
        data = self.read("training-data.enc.json")
        self.assertEqual(data["planState"]["counts"], {"shifts": 0, "events": 0})
        self.assertTrue(data["week"]["days"])

    def test_corrupt_overrides_do_not_break_sync(self):
        (self.tmp / "data" / "overrides.enc.json").write_text("{kaputt", encoding="utf-8")
        sync.main()
        self.assertTrue((self.tmp / "data" / "training-data.enc.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
