import copy
import unittest
from .contract import approved_common_scenario_fixture
from .e25 import replay
from .test_e02 import approved_pack

class E25Tests(unittest.TestCase):
    def test_replays_same_snapshot_twice_and_exposes_version_diff(self):
        scenario = approved_common_scenario_fixture(); original = copy.deepcopy(scenario)
        old = approved_pack()
        new = copy.deepcopy(old); new["rule_version"] = "fictional-rule-v2"
        next(r for r in new["rules"] if r["operation_key"] == "base_service")["hours"] = {"low": 2, "typical": 2, "high": 2}
        out = replay(scenario, old, new, actor="fictional_reviewer", reason="compare proposed base", diff_acknowledged=True)
        self.assertEqual(out["status"], "replayed")
        self.assertEqual(out["diff"]["person_hours"], {"low": 0.3, "typical": 0.3, "high": 0.3})
        again = replay(scenario, old, new, actor="fictional_reviewer", reason="compare proposed base", diff_acknowledged=True)
        self.assertEqual(out["batches"], again["batches"])
        self.assertEqual(scenario, original)

    def test_release_needs_ack_and_reason(self):
        old = approved_pack(); new = copy.deepcopy(old); new["rule_version"] = "v2"
        result = replay(approved_common_scenario_fixture(), old, new, actor="", reason="", diff_acknowledged=False)
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("human_actor_reason_and_diff_ack_required", result["unknowns"])

    def test_run_without_replay_inputs_returns_null_labor_envelope(self):
        result = replay(approved_common_scenario_fixture(), approved_pack(), approved_pack(),
                        actor=None, reason="x", diff_acknowledged=True)
        self.assertEqual(result["status"], "missing-required")
        out = __import__("auto_repair_engine.e25", fromlist=["run"]).run(approved_common_scenario_fixture())
        self.assertEqual(out["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

if __name__ == "__main__": unittest.main()
