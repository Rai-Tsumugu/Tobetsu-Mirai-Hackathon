from copy import deepcopy
import json
import unittest

from .contract import common_scenario_fixture
from . import e15


class E15VoiceCandidateTests(unittest.TestCase):
    def test_allowed_tags_and_negation_are_extracted_without_text(self):
        parsed = e15.extract_candidates("錆はない。ローターは固着している。雪あり")
        self.assertEqual([item["tag"] for item in parsed["candidates"]],
                         ["rust_absent", "rotor_seized", "snow_present"])
        serialized = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("錆はない", serialized)
        self.assertNotIn("ローターは固着している", serialized)
        self.assertNotIn("雪あり", serialized)

    def test_negation_stays_with_its_condition_and_does_not_hide_other_positive_facts(self):
        cases = {
            "錆がなくローターは固着": ["rust_absent", "rotor_seized"],
            "錆じゃなく塗装の剥がれ": ["rust_absent"],
            "錆ではなく塗装の剥がれ": ["rust_absent"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                parsed = e15.extract_candidates(text)
                self.assertEqual([item["tag"] for item in parsed["candidates"]], expected)
                self.assertNotIn(text, json.dumps(parsed, ensure_ascii=False))

    def test_opposite_side_facts_remain_two_pending_candidates_until_human_confirmation(self):
        source = "右前は錆なし、左前は錆あり"
        parsed = e15.extract_candidates(source)
        candidates = parsed["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual([(item["side"], item["tag"], item["status"]) for item in candidates],
                         [("right", "rust_absent", "pending"), ("left", "rust_present", "pending")])

        scenario = common_scenario_fixture()
        scenario["fields"]["rust_observation"] = {"value": "unknown", "status": "unknown"}
        before = deepcopy(scenario)
        result = e15.run(scenario, {"manual_transcription": source})
        self.assertEqual(scenario, before)
        self.assertEqual(result["voice_candidates"], candidates)
        self.assertTrue(all(item["status"] == "pending" for item in result["voice_candidates"]))

        right = e15.confirm_candidate(scenario, candidates[0], "owner", "right inspected")
        self.assertIsNone(right["error"])
        self.assertEqual(right["scenario_input"]["fields"]["rust_observation"]["value"], "unknown")
        left = e15.confirm_candidate(right["scenario_input"], candidates[1], "owner", "left inspected")
        self.assertEqual(left["scenario_input"]["side_observations"]["rust_observation"]["right"]["value"], "absent")
        self.assertEqual(left["scenario_input"]["side_observations"]["rust_observation"]["left"]["value"], "present")
        self.assertEqual(left["scenario_input"]["fields"]["rust_observation"]["value"], "unknown")

    def test_conflicting_same_target_requires_explicit_human_choice(self):
        parsed = e15.extract_candidates("左前は錆なし、左前は錆あり")
        self.assertEqual(len(parsed["candidates"]), 1)
        candidate = parsed["candidates"][0]
        self.assertEqual(candidate["status"], "ambiguous")
        self.assertEqual(candidate["ambiguity"], "condition_conflict")
        self.assertEqual(set(candidate["alternatives"]), {"rust_absent", "rust_present"})
        scenario = common_scenario_fixture()
        blocked = e15.confirm_candidate(scenario, candidate, "owner", "inspect")
        self.assertIn("ambiguous_candidate_requires", blocked["error"])
        chosen = e15.confirm_candidate(scenario, candidate, "owner", "inspect", resolved_tag="rust_present")
        self.assertIsNone(chosen["error"])
        self.assertEqual(chosen["scenario_input"]["side_observations"]["rust_observation"]["left"]["value"], "present")

    def test_unknown_transcription_and_unknown_confirmation_are_controlled(self):
        parsed = e15.extract_candidates("お客様の山田さん、来週の電話番号は...")
        self.assertEqual(parsed["candidates"], [])
        self.assertEqual(parsed["unknowns"], ["manual_transcription:no_allowed_tags"])
        result = e15.confirm_candidate(common_scenario_fixture(),
                                       {"tag": "customer_name", "status": "pending"}, "staff", "確認")
        self.assertEqual(result["error"], "candidate:unknown_tag")
        self.assertEqual(result["scenario_input"]["fields"], common_scenario_fixture()["fields"])

    def test_ambiguous_sides_require_human_resolution_with_audit(self):
        parsed = e15.extract_candidates("左か右のどちらかのローターが固着")
        candidate = parsed["candidates"][0]
        self.assertEqual(candidate["status"], "ambiguous")
        blocked = e15.confirm_candidate(common_scenario_fixture(), candidate, "staff", "確認した")
        self.assertIn("ambiguous_candidate_requires", blocked["error"])
        resolved = e15.confirm_candidate(common_scenario_fixture(), candidate, "staff", "右側を実車で確認", resolved_side="right")
        self.assertIsNone(resolved["error"])
        self.assertEqual(resolved["scenario_input"]["fields"]["rotor_relevance"]["value"], "relevant")
        self.assertEqual(resolved["approval"]["actor"], "staff")

    def test_pending_candidate_cannot_change_condition_or_labor(self):
        scenario = common_scenario_fixture()
        scenario["fields"]["rotor_relevance"] = {"value": None, "status": "unknown"}
        before = deepcopy(scenario)
        result = e15.run(scenario, {"manual_transcription": "ローター固着なし"})
        self.assertEqual(scenario, before)
        self.assertEqual(result["voice_candidates"][0]["status"], "pending")
        self.assertIsNone(scenario["fields"]["rotor_relevance"]["value"])
        self.assertEqual(result["status"], "missing-required")
        self.assertEqual(result["labor"]["person_hours"], {"low": None, "typical": None, "high": None})

    def test_confirmed_words_change_actual_observation_and_engine_result(self):
        scenario = common_scenario_fixture()
        scenario["fields"]["rotor_relevance"] = {"value": None, "status": "unknown"}
        candidate = e15.extract_candidates("ローター固着なし")["candidates"][0]
        confirmed = e15.confirm_candidate(scenario, candidate, "owner", "ローターを確認")
        result = e15.run(confirmed["scenario_input"])
        self.assertEqual(confirmed["scenario_input"]["fields"]["rotor_relevance"]["value"], "unrelated")
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["labor"]["person_hours"]["typical"], 1.88)
        self.assertEqual(result["approvals"][0]["reason"], "ローターを確認")

    def test_confirmations_are_append_only_and_input_is_immutable(self):
        scenario = common_scenario_fixture()
        scenario["fields"]["rust_observation"] = {"value": "unknown", "status": "unknown"}
        original = deepcopy(scenario)
        first_candidate = e15.extract_candidates("錆あり")["candidates"][0]
        first = e15.confirm_candidate(scenario, first_candidate, "owner", "錆を見た")
        second_candidate = e15.extract_candidates("錆なし")["candidates"][0]
        second = e15.confirm_candidate(first["scenario_input"], second_candidate, "owner", "再確認")
        self.assertEqual(scenario, original)
        self.assertEqual(len(second["scenario_input"]["observations"]), 2)
        self.assertEqual(second["scenario_input"]["fields"]["rust_observation"]["value"], "absent")
        self.assertEqual([item["value"] for item in second["scenario_input"]["observations"]], ["present", "absent"])
        self.assertEqual(first["approval"]["old_value"], "unknown")

    def test_trace_never_contains_transcription_or_personal_text(self):
        scenario = common_scenario_fixture()
        secret_text = "山田太郎の電話番号09012345678、錆なし"
        result = e15.run(scenario, {"manual_transcription": secret_text})
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("山田太郎", serialized)
        self.assertNotIn("09012345678", serialized)
        self.assertNotIn(secret_text, serialized)
        self.assertIn("rust_absent", serialized)
        self.assertTrue(all(item.get("raw_transcription_stored") is False for item in result["trace"]
                            if item["event"] == "voice_candidates_checked"))

    def test_invalid_pack_and_confirmation_require_actor_reason_and_approval(self):
        scenario = common_scenario_fixture()
        invalid = e15.run(scenario, {"engine_id": "e02", "manual_transcription": "錆あり"})
        self.assertEqual(invalid["status"], "missing-required")
        self.assertEqual(invalid["labor"]["person_hours"], {"low": None, "typical": None, "high": None})
        candidate = e15.extract_candidates("錆あり")["candidates"][0]
        no_actor = e15.confirm_candidate(scenario, candidate, "", "確認")
        self.assertEqual(no_actor["error"], "confirmation:actor_and_reason_required")
        no_reason = e15.confirm_candidate(scenario, candidate, "staff", " ")
        self.assertEqual(no_reason["error"], "confirmation:actor_and_reason_required")
        rejected = e15.confirm_candidate(scenario, candidate, "staff", "根拠が弱い", approved=False)
        self.assertFalse(rejected["approval"]["approved"])
        self.assertEqual(rejected["scenario_input"]["fields"], scenario["fields"])

    def test_raw_audio_and_unknown_pack_keys_are_not_accepted(self):
        result = e15.run(common_scenario_fixture(), {"audio": b"raw", "manual_transcription": "錆あり"})
        self.assertEqual(result["status"], "missing-required")
        self.assertIn("rule_pack:unknown_key", result["labor"]["unknowns"])


if __name__ == "__main__":
    unittest.main()
