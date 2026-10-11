import unittest

from auto_repair_engine.contract import (
    approved_common_scenario_fixture,
    common_scenario_fixture,
    reference_labor,
    validate_core_contract,
)


class CommonContractTests(unittest.TestCase):
    def test_unapproved_rotor_condition_stops_with_null_ranges(self):
        labor, _, unknowns = reference_labor(common_scenario_fixture())
        self.assertIn("rotor_relevance:confirm_whether_required", unknowns)
        self.assertEqual(labor["person_hours"], {"low": None, "typical": None, "high": None})
        self.assertEqual(labor["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_approved_fixture_preserves_common_math_and_wait_separation(self):
        labor, _, unknowns = reference_labor(approved_common_scenario_fixture())
        self.assertEqual(unknowns, [])
        self.assertEqual(labor["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(labor["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})
        self.assertEqual(validate_core_contract(labor), [])
        waits = [row for row in labor["breakdown"] if row["status"] == "wait"]
        self.assertEqual(len(waits), 3)
        self.assertTrue(all(row["hours"] == {"low": 0.0, "typical": 0.0, "high": 0.0} for row in waits))
        self.assertEqual(sum(row["elapsed_hours"]["typical"] for row in waits), 0.75)

    def test_transport_is_replaced_and_deduplicated_base_is_not_reduced_twice(self):
        labor, rows, unknowns = reference_labor(approved_common_scenario_fixture())
        self.assertFalse(unknowns)
        by_id = {row["operation_id"]: row for row in rows}
        self.assertEqual(by_id["base_service"]["hours"]["typical"], 1.58)
        self.assertEqual(by_id["included_carry"]["hours"]["typical"], 0.0)
        self.assertEqual(by_id["replacement_carry"]["hours"]["typical"], 0.2)
        self.assertEqual(by_id["wash"]["status"], "nonbillable-work")
        self.assertEqual(by_id["wash"]["hours"]["typical"], 0.1)

    def test_unknown_nonbinding_wait_duration_nulls_elapsed_only(self):
        scenario = approved_common_scenario_fixture()
        next(op for op in scenario["operations"] if op["operation_id"] == "snow_melt")["elapsed_hours"] = None
        labor, _, unknowns = reference_labor(scenario)
        self.assertIn("snow_melt:elapsed_duration_unknown", unknowns)
        self.assertEqual(labor["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(labor["elapsed_hours"], {"low": None, "typical": None, "high": None})
        row = next(row for row in labor["breakdown"] if row["operation_id"] == "snow_melt")
        self.assertEqual(row["hours"], {"low": 0.0, "typical": 0.0, "high": 0.0})
        self.assertEqual(row["elapsed_hours"], {"low": None, "typical": None, "high": None})

    def test_unknown_scope_and_missing_basis_stop_calculation(self):
        for mutate, expected in (
            (lambda s: s["fields"]["included_operations"]["value"].append("unknown_critical_work"), "included_operations:unknown_or_empty_scope"),
            (lambda s: s.pop("basis_unit"), "basis_unit_or_definition:required"),
        ):
            scenario = approved_common_scenario_fixture()
            mutate(scenario)
            labor, _, unknowns = reference_labor(scenario)
            self.assertIn(expected, unknowns)
            self.assertEqual(labor["person_hours"], {"low": None, "typical": None, "high": None})

    def test_rotor_approval_audit_must_match_the_applied_range(self):
        scenario = approved_common_scenario_fixture()
        scenario["metadata"]["approved_condition_widths"]["rotor_seizure_hours"].update(
            actor="", reason="", old_value=123, new_value={"low": 99, "typical": 99, "high": 99}
        )
        labor, _, unknowns = reference_labor(scenario)
        self.assertIn("rotor_seizure_hours:approval_audit_mismatch", unknowns)
        self.assertEqual(labor["person_hours"], {"low": None, "typical": None, "high": None})

    def test_core_contract_rejects_nonfinite_and_misaligned_ranges(self):
        labor = {
            "person_hours": {"low": 2, "typical": float("nan"), "high": 1},
            "elapsed_hours": {"low": 0, "typical": 0, "high": 0},
            "breakdown": [], "unknowns": "not-a-list",
        }
        issues = validate_core_contract(labor)
        self.assertIn("person_hours:invalid_range", issues)
        self.assertIn("unknowns:must_be_string_list", issues)


if __name__ == "__main__":
    unittest.main()
