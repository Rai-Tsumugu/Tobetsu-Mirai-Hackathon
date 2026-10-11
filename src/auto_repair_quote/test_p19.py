from __future__ import annotations

import unittest
from copy import deepcopy

from .common import QuoteError
from .fixtures import demo_presets
from .p19 import load_preset


class LoadPresetTests(unittest.TestCase):
    def setUp(self):
        self.presets = demo_presets()

    def test_loads_exact_registered_preset_as_an_independent_copy(self):
        before = deepcopy(self.presets)
        result = load_preset(self.presets, "PRESET-DEMO-01", as_of="2026-10-11")

        self.assertEqual(result["preset_id"], "PRESET-DEMO-01")
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["inputs"], self.presets[0]["inputs"])
        self.assertFalse(result["refresh_required"])
        self.assertEqual(result["warnings"], [])
        result["inputs"]["items"][0]["unit_price"] = 999999
        self.assertEqual(self.presets, before)

    def test_old_item_price_warns_and_requires_human_refresh(self):
        self.presets[0]["inputs"]["items"][0]["updated_at"] = "2026-10-01"

        result = load_preset(self.presets, "PRESET-DEMO-01", as_of="2026-10-11")

        self.assertTrue(result["refresh_required"])
        self.assertTrue(any("価格" in warning and "SIM-PART-001" in warning for warning in result["warnings"]))

    def test_not_yet_effective_rate_stops_loading(self):
        with self.assertRaises(QuoteError):
            load_preset(self.presets, "PRESET-DEMO-01", as_of="2026-09-30")

    def test_unapproved_preset_is_rejected(self):
        self.presets[0]["approved_by"] = " "

        with self.assertRaises(QuoteError):
            load_preset(self.presets, "PRESET-DEMO-01", as_of="2026-10-11")

    def test_unknown_conditions_remain_unknown_and_are_reported(self):
        condition = {"label": "固着の有無", "status": "unknown", "value": None}
        self.presets[0]["required_conditions"] = [condition]

        result = load_preset(self.presets, "PRESET-DEMO-01", as_of="2026-10-11")

        self.assertEqual(result["required_conditions"], [condition])
        self.assertTrue(any("固着の有無" in warning for warning in result["warnings"]))
        self.assertEqual(result["required_conditions"][0]["status"], "unknown")

    def test_missing_registration_evidence_and_ambiguous_id_are_rejected(self):
        self.presets[0]["inputs"]["items"][0].pop("unit_price")
        with self.assertRaises(QuoteError):
            load_preset(self.presets, "PRESET-DEMO-01", as_of="2026-10-11")

        with self.assertRaises(QuoteError):
            load_preset([*self.presets, deepcopy(self.presets[0])], "PRESET-DEMO-01")


if __name__ == "__main__":
    unittest.main()
