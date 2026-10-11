from __future__ import annotations

import unittest
from copy import deepcopy
from uuid import UUID

from .fixtures import demo_presets
from .p16 import quick_quote


class QuickQuoteTests(unittest.TestCase):
    def setUp(self):
        self.presets = demo_presets()

    def test_registered_demo_preset_runs_as_three_tap_quote(self):
        original = deepcopy(self.presets)
        result = quick_quote(self.presets, "PRESET-DEMO-01")

        self.assertEqual(result["tap_count"], 3)
        self.assertTrue(result["shortcut_available"])
        self.assertTrue(result["fictional"])
        self.assertEqual(result["quote"]["status"], "proposed")
        self.assertTrue(result["quote"]["fictional"])
        self.assertNotEqual(result["inputs"]["quote_id"], "demo")
        UUID(result["inputs"]["quote_id"])
        self.assertEqual(self.presets, original)
        self.assertIn("架空デモ", result["quote"]["reasons"][-1])

    def test_vehicle_override_changes_only_vehicle_and_requires_registration(self):
        result = quick_quote(self.presets, "PRESET-DEMO-01", "V-DEMO-OTHER")

        self.assertEqual(result["inputs"]["vehicle_ref"], "V-DEMO-OTHER")
        self.assertFalse(result["shortcut_available"])
        self.assertFalse(result["registration_checks"]["vehicle_registered"])
        self.assertEqual(result["quote"]["vehicle_ref"], "V-DEMO-OTHER")

    def test_unresolved_required_condition_blocks_amounts_and_shortcut(self):
        self.presets[0]["required_conditions"] = ["固着の有無"]

        result = quick_quote(self.presets, "PRESET-DEMO-01")

        self.assertFalse(result["shortcut_available"])
        self.assertEqual(result["quote"]["status"], "blocked")
        self.assertIsNone(result["quote"]["total"]["typical"])

    def test_missing_rate_registration_disables_shortcut(self):
        self.presets[0]["inputs"].pop("labor_rate")

        result = quick_quote(self.presets, "PRESET-DEMO-01")

        self.assertFalse(result["shortcut_available"])
        self.assertFalse(result["registration_checks"]["rate_registered"])
        self.assertEqual(result["quote"]["status"], "blocked")

    def test_unapproved_purchase_markup_disables_shortcut(self):
        item = self.presets[0]["inputs"]["items"][0]
        item["price_type"] = "仕入"

        result = quick_quote(self.presets, "PRESET-DEMO-01")

        self.assertFalse(result["shortcut_available"])
        self.assertFalse(result["registration_checks"]["items_registered"])
        self.assertEqual(result["quote"]["status"], "blocked")

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            quick_quote(self.presets, "missing")


if __name__ == "__main__":
    unittest.main()
