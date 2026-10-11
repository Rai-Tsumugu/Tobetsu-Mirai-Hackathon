from __future__ import annotations

import unittest
from copy import deepcopy

from .fixtures import demo_inputs
from .p11 import apply, conditions_panel


class ConditionsPanelTests(unittest.TestCase):
    def setUp(self):
        self.inputs = demo_inputs()
        self.quote = {"conditions": [], "reasons": []}

    def test_unknown_is_retained_as_unknown_and_never_zeroed_or_auto_acked(self):
        self.inputs["labor"]["unknowns"] = ["架空: 分解後の追加作業は未確認"]
        row = conditions_panel(self.quote, self.inputs)[0]
        self.assertEqual(row["text"], self.inputs["labor"]["unknowns"][0])
        self.assertEqual(row["status"], "unknown")
        self.assertTrue(row["customer_ack_required"])
        self.assertEqual(row["customer_ack_status"], "pending")
        self.assertIsNone(row["approved_by"])
        updated = apply(self.quote, self.inputs)
        self.assertEqual(updated["conditions"][0]["status"], "unknown")
        self.assertEqual(self.quote, {"conditions": [], "reasons": []})

    def test_conditional_and_excluded_breakdown_are_collected_with_band_context(self):
        self.inputs["labor"]["breakdown"] = [
            {
                "operation": "架空: 固着対応",
                "reason": "架空: 現車確認後に追加",
                "status": "conditional",
                "source_ref": "operation:1",
                "hours": {"low": 0, "typical": 0.5, "high": 1},
            },
            {
                "operation": "架空: 請求対象外の確認",
                "reason": "架空: 工場負担",
                "status": "approved_nonbillable",
                "approved_by": "担当者A",
                "source_ref": "operation:2",
                "hours": {"low": 0, "typical": 0.1, "high": 0.2},
            },
        ]
        rows = conditions_panel(self.quote, self.inputs)
        self.assertEqual([row["status"] for row in rows], ["conditional", "excluded"])
        self.assertEqual(rows[0]["source_ref"], "operation:1")
        self.assertEqual(rows[1]["approved_by"], "担当者A")
        self.assertEqual(rows[1]["customer_ack_status"], "pending")
        self.assertTrue(all(row["customer_ack_required"] for row in rows))

    def test_internal_approval_does_not_imply_customer_acknowledgement(self):
        self.inputs["conditions"] = [{
            "text": "架空: 顧客へ追加連絡",
            "source_ref": "condition:1",
            "status": "approved",
            "approved_by": "責任者",
            "customer_ack_required": True,
        }]
        row = conditions_panel(self.quote, self.inputs)[0]
        self.assertEqual(row["approved_by"], "責任者")
        self.assertEqual(row["customer_ack_status"], "pending")

    def test_apply_preserves_normal_operation_explanation_and_deduplicates(self):
        self.inputs["labor"]["breakdown"][0]["reason"] = "架空: 通常工程の説明"
        initial = {"conditions": [], "reasons": ["架空: 通常工程の説明"]}
        once = apply(initial, self.inputs)
        twice = apply(once, self.inputs)
        self.assertIn("架空: 通常工程の説明", once["reasons"])
        self.assertEqual(once["reasons"], twice["reasons"])
        self.assertEqual(once["conditions"], twice["conditions"])
        self.assertEqual(once["reasons"].count("架空: 通常工程の説明"), 1)


if __name__ == "__main__":
    unittest.main()
