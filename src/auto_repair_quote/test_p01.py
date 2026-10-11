import unittest
from copy import deepcopy

from .p01 import apply
from .p02 import calculate_billable_person_hours


class P01Tests(unittest.TestCase):
    def setUp(self):
        self.quote = {"lines": []}
        self.inputs = {
            "labor": {
                "person_hours": {"low": 1, "typical": 1.5, "high": 2.5},
                "elapsed_hours": {"low": 1, "typical": 3, "high": 5},
                "breakdown": [{
                    "operation": "repair", "hours": {"low": 1, "typical": 1.5, "high": 2.5},
                    "reason": "observed", "status": "proposed", "source_ref": "op-1",
                }], "unknowns": [], "source_ref": "labor-1",
            },
            "labor_rate": {
                "yen_per_person_hour": 8000,
                "basis": [{"label": "simulator approved rate", "value": 8000, "unit": "円/人時"}],
            },
        }

    def test_calculates_bands_and_does_not_mutate_input(self):
        original = deepcopy(self.quote)
        result = apply(self.quote, self.inputs)
        line = result["lines"][0]
        self.assertEqual(line["amount"], {"low": 8000, "typical": 12000, "high": 20000})
        self.assertEqual(line["quantity_range"], {"low": 1, "typical": 1.5, "high": 2.5})
        self.assertEqual(self.quote, original)
        self.assertEqual(line["snapshot"]["labor"], self.inputs["labor"])

    def test_elapsed_hours_do_not_change_price(self):
        initial = apply(self.quote, self.inputs)["lines"][0]["amount"]
        changed = deepcopy(self.inputs)
        changed["labor"]["elapsed_hours"] = {"low": 20, "typical": 30, "high": 50}
        changed["labor"]["u_period"] = {"low": 99, "typical": 99, "high": 99}
        self.assertEqual(apply(self.quote, changed)["lines"][0]["amount"], initial)

    def test_approved_nonbillable_hours_are_excluded_and_snapshot_preserved(self):
        data = deepcopy(self.inputs)
        data["labor"]["person_hours"] = {"low": 2, "typical": 3, "high": 5}
        data["labor"]["breakdown"] = [
            {"operation": "repair", "hours": {"low": 1, "typical": 1.5, "high": 2.5}, "status": "proposed"},
            {"operation": "warranty", "hours": {"low": 1, "typical": 1.5, "high": 2.5},
             "status": "approved_nonbillable", "reason": "approved exclusion", "approved_by": "owner",
             "billing_selection_ref": "selection-1"},
        ]
        result = apply(self.quote, data)
        line = result["lines"][0]
        self.assertEqual(line["quantity_range"], {"low": 1, "typical": 1.5, "high": 2.5})
        self.assertEqual(line["quantity_range"], calculate_billable_person_hours(data["labor"]["breakdown"]))
        self.assertEqual(line["amount"], {"low": 8000, "typical": 12000, "high": 20000})
        self.assertEqual(result["billing_selection"]["excluded_operations"][0]["approved_by"], "owner")
        self.assertEqual(line["snapshot"]["billing_selection"], result["billing_selection"])
        self.assertFalse(result["billing_selection"]["u_period_applied"])

    def test_unapproved_exclusion_is_rejected(self):
        data = deepcopy(self.inputs)
        data["labor"]["breakdown"][0]["status"] = "nonbillable"
        with self.assertRaises(ValueError):
            apply(self.quote, data)

    def test_rejects_breakdown_mismatch(self):
        data = deepcopy(self.inputs)
        data["labor"]["breakdown"][0]["hours"]["typical"] = 1
        with self.assertRaises(ValueError):
            apply(self.quote, data)

    def test_reapply_does_not_duplicate_line(self):
        once = apply(self.quote, self.inputs)
        twice = apply(once, self.inputs)
        self.assertEqual([x["line_id"] for x in twice["lines"]], ["labor-total"])

    def test_rejects_missing_negative_nan_and_bad_band_order(self):
        for mutate in (
            lambda d: d["labor"]["person_hours"].pop("typical"),
            lambda d: d["labor"]["person_hours"].update(low=-1),
            lambda d: d["labor"]["person_hours"].update(high=float("nan")),
            lambda d: d["labor"]["person_hours"].update(low=2, typical=1, high=3),
            lambda d: d["labor_rate"].pop("basis"),
            lambda d: d["labor"].update(unknowns=["unconfirmed condition"]),
        ):
            bad = deepcopy(self.inputs)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                apply(self.quote, bad)


if __name__ == "__main__":
    unittest.main()
