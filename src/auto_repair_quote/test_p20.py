import unittest
from copy import deepcopy

from .fixtures import demo_presets
from .p20 import search_jobs, select_job


class P20Tests(unittest.TestCase):
    def setUp(self):
        self.jobs = demo_presets()

    def test_demo_preset_is_found_by_abbreviation_without_price(self):
        result = search_jobs(self.jobs, "パッド")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job_id"], "JOB-DEMO-01")
        self.assertEqual(
            set(result[0]),
            {"job_id", "job_ref", "preset_id", "name", "aliases", "source", "approved_by"},
        )
        self.assertFalse(any("price" in key or "amount" in key for key in result[0]))

    def test_ambiguous_partial_match_returns_all_candidates(self):
        jobs = deepcopy(self.jobs)
        second = deepcopy(jobs[0])
        second.update(job_id="JOB-DEMO-02", job_ref="JOB-DEMO-02", preset_id="PRESET-DEMO-02")
        second["name"] = "架空: ブレーキ点検"
        jobs.append(second)

        result = search_jobs(jobs, "ブレーキ")
        self.assertEqual({job["job_id"] for job in result}, {"JOB-DEMO-01", "JOB-DEMO-02"})
        self.assertIsNone(select_job(jobs, "missing"))

    def test_unapproved_jobs_and_aliases_are_excluded(self):
        jobs = deepcopy(self.jobs)
        jobs[0]["aliases"] = [
            "承認済み文字列alias",
            {"alias": "承認済みdict", "approved_by": "operator-demo-02"},
            {"alias": "未承認dict"},
        ]
        unapproved = deepcopy(jobs[0])
        unapproved["job_id"] = "JOB-UNAPPROVED"
        unapproved["approved_by"] = " "
        unapproved["name"] = "未承認作業"
        jobs.append(unapproved)

        self.assertEqual(search_jobs(jobs, "未承認dict"), [])
        result = search_jobs(jobs, "承認済み")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["aliases"], ["承認済みdict"])
        self.assertIsNone(select_job(jobs, "JOB-UNAPPROVED"))

    def test_nfkc_casefold_and_whitespace_normalization(self):
        jobs = [{
            "job_id": "job-1", "job_ref": "ref-1", "preset_id": "preset-1",
            "name": "ＡＢＣ　 Brake   Repair", "aliases": [],
            "source": "factory", "approved_by": "operator-1",
        }]
        self.assertEqual(search_jobs(jobs, "abc brake repair")[0]["job_id"], "job-1")
        jobs[0]["name"] = "Straße Service"
        self.assertEqual(search_jobs(jobs, "STRASSE")[0]["job_id"], "job-1")

    def test_select_job_requires_one_approved_id_match(self):
        jobs = deepcopy(self.jobs)
        selected = select_job(jobs, "JOB-DEMO-01")
        self.assertEqual(selected["preset_id"], "PRESET-DEMO-01")
        jobs.append(deepcopy(jobs[0]))
        self.assertIsNone(select_job(jobs, "JOB-DEMO-01"))


if __name__ == "__main__":
    unittest.main()
