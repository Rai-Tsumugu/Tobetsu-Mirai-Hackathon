import unittest
from .e26 import active_view

class E26Tests(unittest.TestCase):
    def test_append_revision_rebuilds_bucket_without_mutating_quote_or_log(self):
        actuals = [{"event_id": "a1", "operation_id": "wash", "hours": 0.5, "quote_id": "q1"}]
        revisions = [{"revision_id": "r1", "parent_id": "a1", "delta_hours": 0.2,
                      "reason": "corrected timer entry", "actor": "fictional_tech", "rule_version": "v2"}]
        result = active_view(actuals, revisions)
        self.assertEqual(result["active_view"][0]["hours"], 0.7)
        self.assertEqual(result["bucket_hours"], {"wash": 0.7})
        self.assertEqual(actuals[0]["hours"], 0.5)
        self.assertEqual(actuals[0]["quote_id"], "q1")
        with self.assertRaises(ValueError):
            active_view(actuals, revisions + [{**revisions[0], "revision_id": "r2", "delta_hours": 0.4}])

    def test_missing_parent_and_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            active_view([], [{"revision_id": "r", "parent_id": "missing", "delta_hours": 1,
                              "reason": "x", "actor": "a", "rule_version": "v"}])

    def test_chained_deltas_accumulate_and_nonfinite_hours_rejected(self):
        actual = [{"event_id": "a", "operation_id": "repair", "hours": 2}]
        chain = [{"revision_id": "r1", "parent_id": "a", "delta_hours": 1,
                  "reason": "first", "actor": "tech", "rule_version": "v2"},
                 {"revision_id": "r2", "parent_id": "r1", "delta_hours": 0.5,
                  "reason": "second", "actor": "tech", "rule_version": "v3"}]
        self.assertEqual(active_view(actual, chain)["bucket_hours"]["repair"], 3.5)
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                active_view([{"event_id": "x", "operation_id": "repair", "hours": bad}], [])

if __name__ == "__main__": unittest.main()
