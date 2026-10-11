"""Tests for P17 saved draft continuation."""

import unittest
from copy import deepcopy

from .fixtures import demo_inputs
from .p17 import list_drafts, resume_draft, save_draft
from .store import QuoteStore


class DraftResumeTests(unittest.TestCase):
    def setUp(self):
        self.store = QuoteStore()
        self.inputs = demo_inputs()
        self.inputs.update(job_ref="JOB-1", customer_ref="C-1", vehicle_ref="V-1")
        self.inputs["items"][0]["quantity_range"] = {"low": 2, "typical": 3, "high": 4}

    def tearDown(self):
        self.store.close()

    def test_save_and_resume_snapshot_preserve_saved_input(self):
        original = deepcopy(self.inputs)
        draft = save_draft(self.store, "D-1", self.inputs, step=3)
        self.inputs["items"][0]["unit_price"] = 999
        resumed = resume_draft(self.store, "D-1", "snapshot")

        self.assertEqual(draft["step"], 3)
        self.assertEqual(resumed["inputs"]["items"][0]["unit_price"], original["items"][0]["unit_price"])
        self.assertIn("保存日:", resumed["price_notice"])
        self.assertEqual(self.store.get_draft("D-1")["resume_mode"], "snapshot")

    def test_current_price_unit_mismatch_is_not_silently_converted(self):
        save_draft(self.store, "D-UNIT", self.inputs)
        current = deepcopy(self.inputs)
        current["items"][0]["unit"] = "箱"
        with self.assertRaises(ValueError):
            resume_draft(self.store, "D-UNIT", "current", current)

    def test_resume_requires_explicit_mode(self):
        save_draft(self.store, "D-1", self.inputs)
        with self.assertRaises(ValueError):
            resume_draft(self.store, "D-1", "")

    def test_current_prices_update_without_replacing_work_or_source(self):
        saved = save_draft(self.store, "D-1", self.inputs)
        current = deepcopy(self.inputs)
        current["labor_rate"]["yen_per_person_hour"] = 9200
        current["items"][0].update(
            unit_price=1250,
            name="現行品名",
            quantity_range={"low": 90, "typical": 90, "high": 90},
            quantity_unit="個",
            unit="個",
        )
        current["labor"]["person_hours"]["typical"] = 99
        resumed = resume_draft(self.store, "D-1", "current", current)
        item = resumed["inputs"]["items"][0]

        self.assertEqual(resumed["inputs"]["labor_rate"]["yen_per_person_hour"], 9200)
        self.assertEqual(item["unit_price"], 1250)
        self.assertEqual(item["name"], "現行品名")
        self.assertEqual(item["quantity_range"], saved["inputs"]["items"][0]["quantity_range"])
        self.assertEqual(item["quantity_unit"], saved["inputs"]["items"][0]["quantity_unit"])
        self.assertEqual(item["unit"], saved["inputs"]["items"][0]["unit"])
        self.assertEqual(resumed["inputs"]["labor"]["person_hours"], self.inputs["labor"]["person_hours"])
        self.assertEqual(self.store.get_draft("D-1")["inputs"], saved["inputs"])

    def test_unknown_item_mapping_stops_resume(self):
        save_draft(self.store, "D-1", self.inputs)
        current = deepcopy(self.inputs)
        current["items"][0]["item_id"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "mapping mismatch"):
            resume_draft(self.store, "D-1", "current", current)

    def test_listing_returns_saved_drafts(self):
        save_draft(self.store, "D-1", self.inputs)
        listed = list_drafts(self.store)
        listed[0]["inputs"]["items"].clear()
        self.assertEqual(len(self.store.get_draft("D-1")["inputs"]["items"]), 1)


if __name__ == "__main__":
    unittest.main()
