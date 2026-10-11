import unittest
from copy import deepcopy

from ..p01 import apply as apply_p01
from ..p02 import apply


class P02Tests(unittest.TestCase):
    def setUp(self):
        self.inputs = {
            "labor": {
                "person_hours": {"low": 1, "typical": 1.5, "high": 2.5},
                "breakdown": [
                    {"operation": "分解", "hours": {"low": 0.25, "typical": 0.5, "high": 1}, "reason": "分解"},
                    {"operation": "交換", "hours": {"low": 0.75, "typical": 1, "high": 1.5}, "reason": "交換"},
                ],
                "source_ref": "labor-1",
            },
            "labor_rate": {
                "yen_per_person_hour": 8000,
                "basis": [{"label": "架空承認単価", "value": 8000, "unit": "円/人時"}],
            },
        }

    def test_expands_p01_total_into_traceable_operation_lines_without_mutation(self):
        original_inputs = deepcopy(self.inputs)
        original_quote = {"lines": [{"line_id": "parts-1", "kind": "part"}]}
        p01_quote = apply_p01(original_quote, self.inputs)
        result = apply(p01_quote, self.inputs)
        self.assertEqual([line["line_id"] for line in result["lines"]], ["parts-1", "labor-breakdown:1", "labor-breakdown:2"])
        self.assertEqual(result["lines"][1]["amount"], {"low": 2000, "typical": 4000, "high": 8000})
        self.assertEqual(result["lines"][2]["amount"], {"low": 6000, "typical": 8000, "high": 12000})
        self.assertEqual(self.inputs, original_inputs)
        self.assertEqual(original_quote["lines"], [{"line_id": "parts-1", "kind": "part"}])

    def test_reapplying_does_not_duplicate_labor_rows(self):
        once = apply(apply_p01({"lines": []}, self.inputs), self.inputs)
        twice = apply(once, self.inputs)
        self.assertEqual(len(twice["lines"]), 2)
        self.assertEqual(sum(line["amount"]["typical"] for line in twice["lines"]), 12000)

    def test_rejects_band_total_mismatch_and_duplicate_identity(self):
        mismatched = deepcopy(self.inputs)
        mismatched["labor"]["breakdown"][0]["hours"]["typical"] = 0.4
        with self.assertRaises(ValueError):
            apply({"lines": []}, mismatched)

        duplicate = deepcopy(self.inputs)
        duplicate["labor"]["breakdown"][1]["operation"] = "分解"
        with self.assertRaises(ValueError):
            apply({"lines": []}, duplicate)

    def test_rejects_invalid_ranges_and_non_finite_rate(self):
        for change in (
            lambda data: data["labor"]["breakdown"][0]["hours"].pop("high"),
            lambda data: data["labor"]["breakdown"][0]["hours"].update(low=0.8, typical=0.5),
            lambda data: data["labor_rate"].update(yen_per_person_hour=float("inf")),
        ):
            bad = deepcopy(self.inputs)
            change(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                apply({"lines": []}, bad)

    def test_stops_for_unknowns_and_preserves_approved_nonbillable_hours(self):
        unknown = deepcopy(self.inputs)
        unknown["labor"]["unknowns"] = ["固着の状態未確認"]
        with self.assertRaises(ValueError):
            apply({"lines": []}, unknown)

        excluded = deepcopy(self.inputs)
        excluded["labor"]["breakdown"][0].update({
            "status": "approved_nonbillable",
            "billing_selection_ref": "selection-1",
            "approved_by": "operator-1",
            "reason": "保証対応として請求しない",
        })
        result = apply({"lines": []}, excluded)
        line = result["lines"][0]
        self.assertEqual(line["quantity_range"], {"low": 0.25, "typical": 0.5, "high": 1})
        self.assertEqual(line["amount"], {"low": 0, "typical": 0, "high": 0})
        self.assertEqual(line["status"], "approved_nonbillable")
        self.assertEqual(result["billing_selection"]["billed_person_hours"], {"low": 0.75, "typical": 1, "high": 1.5})
        self.assertEqual(result["billing_selection"]["excluded_operations"][0]["approved_by"], "operator-1")

    def test_rejects_approved_nonbillable_without_full_approval_record(self):
        for missing in ("reason", "approved_by", "billing_selection_ref"):
            excluded = deepcopy(self.inputs)
            excluded["labor"]["breakdown"][0].update({
                "status": "approved_nonbillable",
                "reason": "除外理由",
                "approved_by": "operator-1",
                "billing_selection_ref": "selection-1",
            })
            excluded["labor"]["breakdown"][0].pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                apply({"lines": []}, excluded)


if __name__ == "__main__":
    unittest.main()
