"""Behavior tests for the E14 human-reviewed photo-candidate queue."""
from copy import deepcopy
import unittest

from . import e07, e14
from .contract import approved_common_scenario_fixture, common_scenario_fixture

STAMP = "2026-10-11T01:02:03+00:00"

def candidate(field="rotor_seizure_hours", value=None, candidate_id="cand_1"):
    if value is None:
        value = {"low": 0.0, "typical": 0.25, "high": 0.5}
    return {"candidate_id": candidate_id, "photo_ref": {"area": "brake", "id": "photo_01"},
            "ai_candidate": {"field": field, "value": deepcopy(value)}}

def rotor_scenario():
    scenario = approved_common_scenario_fixture()
    scenario["fields"].pop("rotor_seizure_hours")
    scenario["fields"]["rotor_relevance"] = {"value": "relevant", "status": "confirmed",
                                                "source": "fictional_fixture", "confirmed_at": STAMP}
    scenario["metadata"].pop("approved_condition_widths", None)
    return scenario

def all_null(result):
    return all(v is None for key in ("person_hours", "elapsed_hours") for v in result["labor"][key].values())

class E14PhotoCandidateTests(unittest.TestCase):
    def test_default_no_candidates_preserves_approved_fixture_calculation(self):
        scenario = approved_common_scenario_fixture()
        before = deepcopy(scenario)
        result = e14.run(scenario)
        self.assertEqual(result["labor"], e07.run(scenario)["labor"])
        self.assertEqual(scenario, before)
        self.assertEqual(result["status"], "proposed")

    def test_pending_candidate_does_not_become_observation_and_required_gap_is_null(self):
        original = rotor_scenario()
        queued = e14.propose_candidates(original, [candidate()])
        self.assertNotIn("rotor_seizure_hours", queued["fields"])
        result = e14.run(queued)
        self.assertEqual(result["status"], "missing-required")
        self.assertTrue(all_null(result))
        self.assertIn("rotor_seizure_hours:human_approval_required", result["labor"]["unknowns"])

    def test_approval_promotes_only_with_complete_human_audit_and_changes_labor(self):
        queued = e14.propose_candidates(rotor_scenario(), [candidate()])
        confirmed = e14.confirm_candidate(queued, "cand_1", "shop_owner", "visual check", STAMP)
        result = e14.run(confirmed)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"], {"low": 1.88, "typical": 2.13, "high": 2.38})
        self.assertEqual(confirmed["photo_candidates"][0]["human_audit"], {
            "actor": "shop_owner", "reason": "visual check",
            "old_value": None,
            "new_value": {"low": 0.0, "typical": 0.25, "high": 0.5}, "timestamp": STAMP,
            "before_sha256": confirmed["metadata"]["photo_candidate_audit_log"][0]["before_sha256"],
            "after_sha256": confirmed["metadata"]["photo_candidate_audit_log"][0]["after_sha256"]})
        self.assertEqual(queued["photo_candidates"][0]["status"], "pending")
        with self.assertRaisesRegex(ValueError, "only_pending"):
            e14.confirm_candidate(confirmed, "cand_1", "shop_owner", "again", STAMP)

    def test_modified_value_is_audited_and_range_validation_is_enforced(self):
        queued = e14.propose_candidates(rotor_scenario(), [candidate()])
        corrected = {"low": 0.1, "typical": 0.3, "high": 0.6}
        modified = e14.modify_candidate(queued, "cand_1", corrected, "shop_owner", "corrected by inspection", STAMP)
        result = e14.run(modified)
        self.assertEqual(modified["photo_candidates"][0]["status"], "modified")
        self.assertIsNone(modified["photo_candidates"][0]["human_audit"]["old_value"])
        self.assertEqual(modified["photo_candidates"][0]["human_audit"]["new_value"], corrected)
        self.assertEqual(result["labor"]["person_hours"]["typical"], 2.18)
        with self.assertRaisesRegex(ValueError, "not_allowed"):
            e14.modify_candidate(queued, "cand_1", {"low": 0.5, "typical": 0.2, "high": 0.7}, "shop_owner", "bad", STAMP)

    def test_rejection_never_writes_the_suggested_value(self):
        queued = e14.propose_candidates(rotor_scenario(), [candidate()])
        rejected = e14.reject_candidate(queued, "cand_1", "shop_owner", "not visible", STAMP)
        self.assertNotIn("rotor_seizure_hours", rejected["fields"])
        self.assertEqual(rejected["photo_candidates"][0]["human_audit"]["new_value"], "rejected")
        result = e14.run(rejected)
        self.assertEqual(result["status"], "missing-required")
        self.assertTrue(all_null(result))

    def test_duplicate_ids_private_photo_data_and_forged_approval_stop_safely(self):
        duplicate = e14.propose_candidates(common_scenario_fixture(), [candidate(candidate_id="same"), candidate(candidate_id="same")])
        result = e14.run(duplicate)
        self.assertIn("same:duplicate_candidate_id", result["labor"]["unknowns"])
        self.assertTrue(all_null(result))
        private = e14.propose_candidates(common_scenario_fixture(), [candidate()])
        private["photo_candidates"][0]["person_name"] = "fictional name"
        self.assertIn("unknown_or_private_data_rejected", e14.run(private)["labor"]["unknowns"][0])
        forged = e14.propose_candidates(rotor_scenario(), [candidate()])
        forged["photo_candidates"][0].update(status="approved", human_value=candidate()["ai_candidate"]["value"],
            human_audit={"actor": "x", "reason": "x", "old_value": None, "new_value": candidate()["ai_candidate"]["value"], "timestamp": STAMP})
        result = e14.run(forged)
        self.assertIn("human_audit_required", result["labor"]["unknowns"][0])
        self.assertTrue(all_null(result))

    def test_old_value_tampering_is_rejected_and_real_ordinary_field_change_is_bound(self):
        scenario = approved_common_scenario_fixture()
        original_relevance = scenario["fields"]["rotor_relevance"]["value"]
        queued = e14.propose_candidates(scenario, [candidate("rotor_relevance", "unrelated")])
        approved = e14.confirm_candidate(queued, "cand_1", "shop_owner", "checked rotor", STAMP)
        audit = approved["photo_candidates"][0]["human_audit"]
        self.assertEqual(audit["old_value"], original_relevance)
        self.assertEqual(approved["metadata"]["photo_candidate_audit_log"][0]["before_snapshot"]["value"]["value"], original_relevance)
        self.assertEqual(e14.run(approved)["status"], "proposed")

        forged = deepcopy(approved)
        forged["photo_candidates"][0]["human_audit"]["old_value"] = "forged-old"
        result = e14.run(forged)
        self.assertIn("condition_approval_audit_mismatch", result["labor"]["unknowns"][0])
        self.assertTrue(all_null(result))

    def test_pending_candidate_cannot_be_forged_approved_without_snapshot_log(self):
        forged = e14.propose_candidates(rotor_scenario(), [candidate()])
        item = forged["photo_candidates"][0]
        item.update(status="approved", human_value=deepcopy(item["ai_candidate"]["value"]),
                    human_audit={"actor": "owner", "reason": "checked", "old_value": None,
                                 "new_value": deepcopy(item["ai_candidate"]["value"]), "timestamp": STAMP,
                                 "before_sha256": "0" * 64, "after_sha256": "0" * 64})
        result = e14.run(forged)
        self.assertIn("confirmed_observation_missing_or_mismatch", result["labor"]["unknowns"][0])
        self.assertTrue(all_null(result))

    def test_malformed_explicit_pack_stops_and_rule_hash_is_bound_to_trace(self):
        scenario = approved_common_scenario_fixture()
        bad = e14.run(scenario, {"engine_id": e14.ENGINE_ID, "rule_version": scenario["rule_version"],
                                 "allowed_values": {"unknown": ["anything"]}})
        self.assertEqual(bad["status"], "missing-required")
        self.assertTrue(all_null(bad))
        good = e14.run(scenario, {"engine_id": e14.ENGINE_ID, "rule_version": scenario["rule_version"]})
        self.assertEqual(good["trace"][0]["rule_version"], scenario["rule_version"])
        self.assertEqual(len(good["trace"][0]["rule_sha256"]), 64)

    def test_proposal_and_decision_inputs_are_immutable_and_photo_ref_is_minimal(self):
        source = rotor_scenario(); proposals = [candidate()]
        source_before, proposals_before = deepcopy(source), deepcopy(proposals)
        queued = e14.propose_candidates(source, proposals)
        queued_before = deepcopy(queued)
        approved = e14.confirm_candidate(queued, "cand_1", "owner", "checked", STAMP)
        self.assertEqual(source, source_before); self.assertEqual(proposals, proposals_before)
        self.assertEqual(queued, queued_before); self.assertEqual(queued["photo_candidates"][0]["status"], "pending")
        self.assertEqual(set(approved["photo_candidates"][0]["photo_ref"]), {"area", "id"})
        self.assertEqual(e14.run(approved)["trace"][0]["candidate_states"][0]["photo_ref"], {"area": "brake", "id": "photo_01"})

if __name__ == "__main__":
    unittest.main()
