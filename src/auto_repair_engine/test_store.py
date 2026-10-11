import tempfile
import unittest
from pathlib import Path

from auto_repair_engine.store import AutoRepairStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AutoRepairStore(Path(self.temp_dir.name) / "demo.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_rule_versions_are_immutable(self):
        pack = {"engine_id": "e02", "rule_version": "v1", "status": "confirmed", "rules": [{"hours": 1.0}]}
        self.store.save_rule_pack(pack)
        self.store.save_rule_pack(pack)
        changed = {**pack, "rules": [{"hours": 2.0}]}
        with self.assertRaises(ValueError):
            self.store.save_rule_pack(changed)
        self.assertEqual(self.store.get_rule_pack("e02", "v1"), pack)

    def test_offline_version_conflict_stays_visible(self):
        self.store.save_snapshot("s1", "scenario1", "v1", {"scenario_id": "scenario1", "rule_version": "v1"})
        self.assertEqual(self.store.mark_snapshot_synced("s1", "v2", True), "version_conflict")
        self.assertEqual(self.store.list_pending_snapshots(), [])

    def test_actual_correction_appends_with_reason(self):
        self.store.append_revision("r1", "estimate1", None, "initial actual", {"person_hours": 1.0})
        self.store.append_revision("r2", "estimate1", "r1", "corrected duration", {"person_hours": 1.25})
        revisions = self.store.list_revisions("estimate1")
        self.assertEqual([row["revision_id"] for row in revisions], ["r1", "r2"])
        self.assertEqual(revisions[0]["body"]["person_hours"], 1.0)
        self.assertEqual(revisions[1]["supersedes_revision_id"], "r1")
        with self.assertRaises(ValueError):
            self.store.append_revision("r3", "estimate1", "r2", "   ", {})


if __name__ == "__main__":
    unittest.main()
