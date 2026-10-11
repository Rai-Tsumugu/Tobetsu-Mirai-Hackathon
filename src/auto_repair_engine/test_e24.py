import copy
import math
import unittest
from .e24 import approve, propose
from .test_e02 import approved_pack

class E24Tests(unittest.TestCase):
    def test_draft_does_not_apply_until_actor_approves_new_version(self):
        old = approved_pack(); before = copy.deepcopy(old)
        proposal = propose(old, "base_service", {"low": 1.8, "typical": 1.9, "high": 2.0},
                           [{"actual_id": "fictional-1", "hours": 1.9}], "two fictional reviewed samples")
        self.assertEqual(proposal["status"], "draft")
        self.assertEqual(old, before)
        approved = approve(proposal, "fictional_owner", "reviewed evidence", "fictional-v2", "2026-10-12")
        self.assertEqual(approved["rule_pack"]["rule_version"], "fictional-v2")
        self.assertNotEqual(approved["rule_pack"]["rules"][0]["hours"], before["rules"][0]["hours"])
        self.assertEqual(old, before)

    def test_bad_range_and_missing_approval_are_rejected(self):
        with self.assertRaises(ValueError):
            propose(approved_pack(), "base_service", {"low": 3, "typical": 2, "high": 1}, [{"id": 1}], "reason")
        p = propose(approved_pack(), "base_service", {"low": 1, "typical": 1, "high": 1}, [{"id": 1}], "reason")
        with self.assertRaises(ValueError): approve(p, "", "reason", "v2", "today")
        with self.assertRaises(ValueError): approve(p, "owner", "ok", "v2", "not-a-date")
        p["samples"][0]["id"] = 2
        with self.assertRaises(ValueError): approve(p, "owner", "ok", "v2", "2026-10-12")

    def test_infinite_candidate_and_infinite_baseline_ranges_reject(self):
        for candidate in ({"low": 1, "typical": math.inf, "high": math.inf},
                          {"low": 1, "typical": 2, "high": math.inf}):
            with self.assertRaises(ValueError):
                propose(approved_pack(), "base_service", candidate, [{"id": "sample"}], "reviewed")
        old = approved_pack()
        old["rules"][0]["hours"] = {"low": 1, "typical": math.inf, "high": math.inf}
        with self.assertRaises(ValueError):
            propose(old, "base_service", {"low": 1, "typical": 2, "high": 3}, [{"id": "sample"}], "reviewed")

if __name__ == "__main__": unittest.main()
