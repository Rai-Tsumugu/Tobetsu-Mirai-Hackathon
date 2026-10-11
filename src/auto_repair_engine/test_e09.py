import unittest

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from .e09 import ENGINE_ID, run


def pack(nodes, edges=(), limit=2, version="fictional-rule-v1"):
    return {"engine_id": ENGINE_ID, "rule_version": version, "status": "approved",
            "resource_limit": limit, "nodes": nodes, "edges": list(edges)}


class E09ProcessDagTests(unittest.TestCase):
    def test_shared_fixture_retains_common_comparison_baseline(self):
        result = run(approved_common_scenario_fixture())
        self.assertEqual(result["engine_id"], ENGINE_ID)
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": 2.53, "typical": 2.78, "high": 3.03})

    def test_explicit_dag_parallelism_and_precedence_drive_elapsed_and_person_hours(self):
        scenario = common_scenario_fixture()
        dag = pack([
            {"operation_id": "a", "duration_hours": {"low": 1, "typical": 2, "high": 3}, "person_count": 1},
            {"operation_id": "b", "duration_hours": 1, "person_count": 1},
            {"operation_id": "c", "duration_hours": 0.5, "person_count": 2},
        ], [("a", "c"), ("b", "c")])
        result = run(scenario, dag)
        self.assertEqual(result["labor"]["person_hours"], {"low": 3.0, "typical": 4.0, "high": 5.0})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": 1.5, "typical": 2.5, "high": 3.5})
        dag["edges"] = [("a", "b"), ("b", "c")]
        serial = run(scenario, dag)
        self.assertEqual(serial["labor"]["elapsed_hours"]["typical"], 3.5)
        self.assertEqual(result["labor"]["person_hours"], serial["labor"]["person_hours"])

    def test_worker_limit_serializes_parallel_ready_work(self):
        scenario = common_scenario_fixture()
        nodes = [{"operation_id": key, "duration_hours": 2, "person_count": 1}
                 for key in ("first", "second")]
        one_worker = run(scenario, pack(nodes, limit=1))
        two_workers = run(scenario, pack(nodes, limit=2))
        self.assertEqual(one_worker["labor"]["person_hours"]["typical"], 4.0)
        self.assertEqual(one_worker["labor"]["elapsed_hours"]["typical"], 4.0)
        self.assertEqual(two_workers["labor"]["elapsed_hours"]["typical"], 2.0)

    def test_wait_has_no_person_hours_and_unknown_wait_nulls_only_elapsed(self):
        scenario = common_scenario_fixture()
        result = run(scenario, pack([
            {"operation_id": "work", "duration_hours": 2, "person_count": 2},
            {"operation_id": "wait", "kind": "wait", "duration_hours": None, "person_count": 0},
        ], [("work", "wait")]))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["labor"]["person_hours"], {"low": 4.0, "typical": 4.0, "high": 4.0})
        self.assertEqual(result["labor"]["elapsed_hours"], {"low": None, "typical": None, "high": None})
        self.assertEqual(result["labor"]["breakdown"][1]["hours"], {"low": 0.0, "typical": 0.0, "high": 0.0})

    def test_invalid_graph_missing_reference_duplicates_and_capacity_stop(self):
        scenario = common_scenario_fixture()
        samples = [
            (pack([{"operation_id": "a", "duration_hours": 1}], [("a", "missing")]), "missing_node_reference"),
            (pack([{"operation_id": "a", "duration_hours": 1}, {"operation_id": "a", "duration_hours": 1}]), "duplicate_operation_id"),
            (pack([{"operation_id": "a", "duration_hours": 1}, {"operation_id": "b", "duration_hours": 1}], [("a", "b"), ("b", "a")]), "cycle_detected"),
            (pack([{"operation_id": "a", "duration_hours": 1, "person_count": 3}], limit=2), "worker_capacity_exceeded"),
        ]
        for dag, expected in samples:
            with self.subTest(expected=expected):
                result = run(scenario, dag)
                self.assertEqual(result["status"], "missing-required")
                self.assertIn(expected, " ".join(result["labor"]["unknowns"]))
                self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_unknown_required_work_duration_stops_and_version_is_bound(self):
        scenario = common_scenario_fixture()
        unknown = run(scenario, pack([{"operation_id": "a", "duration_hours": None}]))
        self.assertIn("required_person_hour_duration_unknown", " ".join(unknown["labor"]["unknowns"]))
        mismatched = pack([{"operation_id": "a", "duration_hours": 1}], version="different")
        result = run(scenario, mismatched)
        self.assertIn("rule_version_mismatch", " ".join(result["labor"]["unknowns"]))
        self.assertEqual(result["engine_id"], ENGINE_ID)

    def test_explicit_malformed_pack_never_falls_back_to_fixture(self):
        scenario = approved_common_scenario_fixture()
        for explicit in ({}, [], {"rule_version": scenario["rule_version"]}):
            with self.subTest(explicit=explicit):
                result = run(scenario, explicit)
                self.assertEqual(result["status"], "missing-required")
                self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
                self.assertTrue(result["labor"]["unknowns"])


if __name__ == "__main__":
    unittest.main()
