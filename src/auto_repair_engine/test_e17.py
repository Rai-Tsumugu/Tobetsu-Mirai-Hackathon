"""Focused tests for append-only E17 observations and deterministic reduction."""
from __future__ import annotations

from copy import deepcopy
import unittest

from .contract import approved_common_scenario_fixture, common_scenario_fixture
from . import e17


class E17ObservationEventTests(unittest.TestCase):
    def test_fixture_events_and_new_confirmed_condition_change_labor(self):
        scenario = approved_common_scenario_fixture()
        default = e17.run(scenario)
        self.assertEqual(default["status"], "proposed")
        self.assertEqual(default["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        events = e17._fixture_events()
        extended = e17.append_observation_event(events, "rotor_relevance", "relevant", "tech",
                                                "confirmed on current visit", "2026-10-11T12:00:00+09:00",
                                                "rotor-revision", "fixture-01")
        extended = e17.append_observation_event(extended, "rotor_seizure_hours",
                                                {"low": 0, "typical": .25, "high": .5}, "owner",
                                                "approved condition width", "2026-10-11T12:01:00+09:00",
                                                "rotor-range")
        pack = {"engine_id": e17.ENGINE_ID, "rule_version": scenario["rule_version"], "events": extended}
        updated = e17.run(scenario, pack)
        self.assertEqual(updated["status"], "proposed")
        self.assertEqual(updated["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(next(row for row in updated["approvals"] if row["id"] == "rotor-revision")["old_value"], "unrelated")
        replay = e17.run(deepcopy(scenario), deepcopy(pack))
        self.assertEqual(replay["labor"], updated["labor"])

    def test_pending_event_is_not_adopted_and_stops_required_observation(self):
        pending = e17.append_observation_event([], "rotor_relevance", "unrelated", "", "", "",
                                               "pending-1", status="pending")
        reduced = e17.reduce_observations(pending)
        self.assertNotIn("rotor_relevance", reduced)
        result = e17.run(common_scenario_fixture(), {"events": pending})
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_duplicate_ids_bad_references_target_mismatch_and_forks_reject(self):
        event = {"id": "a", "target": "rotor_relevance", "value": "unrelated", "supersedes": None,
                 "actor": "tech", "reason": "checked", "observed_at": "2026-10-11T00:00:00Z",
                 "source": "fixture", "status": "confirmed"}
        with self.assertRaisesRegex(ValueError, "duplicate_id"):
            e17.append_observation_event([event], "rotor_relevance", "relevant", "tech", "reason",
                                         "2026-10-11T00:00:00Z", "a")
        with self.assertRaisesRegex(ValueError, "unknown_supersedes"):
            e17.append_observation_event([], "rotor_relevance", "relevant", "tech", "reason",
                                         "2026-10-11T00:00:00Z", "b", "missing")
        mismatch = dict(event, id="b", target="parts_wait_stock_checked", value=True, supersedes="a")
        with self.assertRaisesRegex(ValueError, "target_mismatch"):
            e17.reduce_observations([event, mismatch])
        fork = [event, dict(event, id="b", value="relevant"), dict(event, id="c", value="relevant")]
        with self.assertRaisesRegex(ValueError, "sequence_ambiguity"):
            e17.reduce_observations(fork)

    def test_revision_cycle_and_null_wait_duration_handling(self):
        audit = {"actor": "fixture", "reason": "cycle probe", "observed_at": "2026-10-11T00:00:00Z", "source": "fictional"}
        a = {"id": "a", "target": "rotor_relevance", "value": "unrelated", "supersedes": "b", "status": "confirmed", **audit}
        b = {"id": "b", "target": "rotor_relevance", "value": "relevant", "supersedes": "a", "status": "confirmed", **audit}
        with self.assertRaisesRegex(ValueError, "revision_cycle"):
            e17.reduce_observations([a, b])
        scenario = common_scenario_fixture()
        scenario["operations"] = [op for op in scenario["operations"] if op["operation_id"] != "parts_wait"]
        # The wait observation remains unknown; elapsed total is null while worker hours remain known.
        scenario["operations"].append({"operation_id": "parts_wait", "operation": "parts_wait",
                                       "hours": None, "elapsed_hours": None, "person_count": 0,
                                       "status": "wait", "stock_checked": False})
        events = e17._fixture_events()
        result = e17.run(scenario, {"events": events})
        self.assertIsNone(result["labor"]["elapsed_hours"]["typical"])
        self.assertIsNotNone(result["labor"]["person_hours"]["typical"])

    def test_default_has_no_synthetic_events_and_preserves_approved_scenario(self):
        scenario = approved_common_scenario_fixture()
        original = deepcopy(scenario)
        result = e17.run(scenario)
        self.assertEqual(scenario, original)
        self.assertEqual(result["trace"][0]["event_ids"], [])
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})

    def test_reducer_rejects_raw_confirmed_events_without_audit(self):
        raw = {"id": "raw", "target": "rotor_relevance", "value": "unrelated", "supersedes": None,
               "actor": "", "reason": "", "observed_at": "", "source": "", "status": "confirmed"}
        with self.assertRaisesRegex(ValueError, "confirmed_audit_required"):
            e17.reduce_observations([raw])


if __name__ == "__main__":
    unittest.main()
