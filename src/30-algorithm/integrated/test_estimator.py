"""統合版エンジンのテスト。

実行: python3 -m unittest discover -s src/30-algorithm/integrated -p "test_*.py"

期待値（2.35 など）は data/ の架空値から手計算した値。計算式はテストのコメントに書く。
"""

import ast
import copy
import json
import re
import unittest
from pathlib import Path

import constants as C
import estimator

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"


def load_all():
    return (estimator.load_json(DATA / "case_example.json"), estimator.load_json(DATA / "shop_params.json"),
            estimator.load_json(DATA / "job_catalog.json"), estimator.load_json(DATA / "records.json"))


def run(case=None, params=None, catalog=None, records=None):
    base = load_all()
    return estimator.estimate(case or base[0], params or base[1], catalog or base[2], records or base[3])


class NoMagicNumbers(unittest.TestCase):
    def test_engine_has_no_numeric_literals(self):
        """estimator.py の数値は constants.py か data/ の変数から来る。"""
        tree = ast.parse((HERE / "estimator.py").read_text())
        literals = [(node.lineno, node.value) for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool)]
        self.assertEqual(literals, [], f"数値リテラルが残っている: {literals}")

    def test_engine_has_no_numbers_hidden_in_strings(self):
        """数値だけの文字列（"0.5" など）や書式指定の桁数で、数値を持ち込んでいない。"""
        tree = ast.parse((HERE / "estimator.py").read_text())
        numeric = re.compile(r"^\s*-?\d+(\.\d+)?\s*$|^0?\d+[dfe%]$")
        hidden = [(node.lineno, node.value) for node in ast.walk(tree)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str) and numeric.match(node.value)]
        self.assertEqual(hidden, [], f"数値を表す文字列が残っている: {hidden}")

    def test_every_constant_is_named_upper_case(self):
        tree = ast.parse((HERE / "constants.py").read_text())
        names = [target.id for node in tree.body if isinstance(node, ast.Assign) for target in node.targets]
        self.assertTrue(names)
        self.assertTrue(all(name.isupper() for name in names), names)


class ExampleValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run()

    def test_base_dedup(self):
        # 0.6 + 1.4 = 2.0、共通工程（リフト 0.1、前2輪 0.2）を1回分控除して 1.7
        self.assertEqual(self.result["base"]["gross_hours"], 2.0)
        self.assertEqual(self.result["base"]["base_hours"], 1.7)

    def test_labor_hours(self):
        # low   = 1.7 + 前処理(0.10+0.10+0.15) + 重2本×0.05 + ハブ2×0.05 + 左ブーツ0.10 = 2.35
        # typ   = 1.7 + 前処理(0.15+0.16+0.20) + 重中4本×0.15 + ハブ2×0.10 + 左ブーツ0.15 + 運搬0.08 = 3.24
        # high  = 1.7 + 前処理(0.25+0.30+0.30) + 重2×(0.30+1.50+0.50) + 中2×0.30 + 未確認4×0.30
        #         + ハブ2×0.15 + ローター2×0.40 + ブーツ2×0.20 + 運搬0.08 = 10.53
        self.assertEqual(self.result["estimate"]["labor_hours"], {"low": 2.35, "typical": 3.24, "high": 10.53})

    def test_elapsed_hours(self):
        # 待機 = 融解0.5 + 浸透0.25 + 防錆乾燥（冬季）0.3 = 1.05。2人運搬で経過は 0.12→0.10（-0.02）
        self.assertEqual(self.result["estimate"]["elapsed_hours"], {"low": 3.4, "typical": 4.27, "high": 11.56})

    def test_method_b_is_not_averaged(self):
        b = self.result["method_comparison"]["b"]
        # J1+J2 の実績 R08 2.3, R09 3.0, R10 2.4。同一車両の前回 R11（1.9）は集計に入れず別に示す
        self.assertEqual(b["n"], 3)
        self.assertEqual(b["labor_hours"], {"low": 2.3, "typical": 2.4, "high": 3.0})
        self.assertEqual([row["id"] for row in b["same_vehicle_cases"]], ["R11"])
        self.assertNotIn("average", json.dumps(self.result["method_comparison"]))

    def test_unbilled_wash_is_labor_but_not_billed(self):
        est = self.result["estimate"]
        # 下回り洗浄（請求しない）0.15 / 0.20 / 0.30 だけ請求人時が少ない
        self.assertEqual(est["billed_hours"], {"low": 2.2, "typical": 3.04, "high": 10.23})
        # 工賃 = 請求人時 × 8,000
        self.assertEqual(self.result["money"]["labor_yen"], {"low": 17600, "typical": 24320, "high": 81840})

    def test_labor_rate(self):
        rate = self.result["money"]["labor_rate"]
        # 年間経費 28,800,000 円 ÷ 年間請求人時 3,600 = 8,000 円/人時
        self.assertEqual(rate["annual_yen_per_hour"], 8000)
        # 冬季だけに暖房費を配賦: 27,000,000/3,600 + 1,700,000/1,450 = 8,672.4
        self.assertEqual(rate["seasonal_winter_yen_per_hour"], 8672)

    def test_materials_round_half_up(self):
        # low = 浸透剤・ガス (98+30)×2 + 防錆 206.25×2 + ブーツ 1,200 = 1,868.5 → 四捨五入で 1,869
        self.assertEqual(self.result["money"]["materials_yen"]["low"], 1869)

    def test_rate_candidate_from_records(self):
        evidence = {row["tag"]: row for row in self.result["rates"]["evidence"]}
        # 固着対応の1本あたり実績 8件の中央値 0.15
        self.assertEqual(evidence["固着対応"]["n"], 8)
        self.assertEqual(evidence["固着対応"]["median"], 0.15)
        self.assertFalse(evidence["ボルト折れ"]["used_for_v2"])  # 1件しかない

    def test_vehicle_age_from_wareki(self):
        self.assertEqual(self.result["vehicle"]["first_registration"], "2014-01")
        self.assertEqual(self.result["vehicle"]["elapsed_years"], 13)

    def test_priority_score(self):
        # 経過年数2 + 走行1 + 錆グレード3 + 未確認1 + 防錆1 + 前回固着2 = 10 → 高
        self.assertEqual(self.result["checks"]["priority"]["score"], 10)
        self.assertEqual(self.result["checks"]["priority"]["band"], "高")


class VariablesDriveTheResult(unittest.TestCase):
    """過去の実績・最新の情報で変わる値は data/ にあり、書き換えると結果が変わる。"""

    def test_new_record_changes_method_b_and_candidate(self):
        case, params, catalog, records = load_all()
        records = copy.deepcopy(records)
        records["historical_records"].append({"id": "R13", "date": "2027-02", "body": "SUV", "drive": "4WD",
                                              "age_years": 13, "km": 130000, "brake_rust": 3, "jobs": ["J1", "J2"],
                                              "estimate": 1.7, "actual": 4.0,
                                              "tags": {"ボルト折れ": {"hours": 0.9, "count": 1}}})
        before, after = run(), run(records=records)
        self.assertNotEqual(before["method_comparison"]["b"]["labor_hours"], after["method_comparison"]["b"]["labor_hours"])
        # 採用中の補正表（v1）は承認されるまで変わらない
        self.assertEqual(before["estimate"]["labor_hours"], after["estimate"]["labor_hours"])

    def test_adopting_v2_uses_actuals(self):
        case, params, catalog, records = load_all()
        params = copy.deepcopy(params)
        params["adopted_rate_table"] = C.RATE_TABLE_V2
        result = run(params=params)
        self.assertEqual(result["estimate"]["labor_hours"], run()["rates"]["candidate_labor_hours"])

    def test_provisional_rate_change(self):
        case, params, catalog, records = load_all()
        params = copy.deepcopy(params)
        params["provisional_rates_v1"]["ops"]["PRE-SNOW"]["typical"] += 0.1
        self.assertAlmostEqual(run(params=params)["estimate"]["labor_hours"]["typical"],
                               run()["estimate"]["labor_hours"]["typical"] + 0.1,
                               places=params["rounding"]["hours_decimals"])

    def test_rounding_is_a_variable(self):
        case, params, catalog, records = load_all()
        params = copy.deepcopy(params)
        params["rounding"]["yen_mode"] = "ROUND_FLOOR"
        # 1,868.5 円 → 切り捨てで 1,868
        self.assertEqual(run(params=params)["money"]["materials_yen"]["low"], 1868)

    def test_excluding_by_condition_in_method_b(self):
        case, params, catalog, records = load_all()
        params = copy.deepcopy(params)
        params["similar_case"]["exclude_if_differs"] = ["brake_rust"]
        b = run(params=params)["method_comparison"]["b"]
        # ブレーキ周りの錆が相違する R08 を除くと R09・R10 の2件で、最小件数3に届かない
        self.assertEqual(b["n"], 2)
        self.assertFalse(b["enough_records"])

    def test_base_catalog_version(self):
        case, params, catalog, records = load_all()
        catalog = copy.deepcopy(catalog)
        catalog["jobs"]["J2"]["base_labor_hours"] = 1.5
        self.assertEqual(run(catalog=catalog)["base"]["base_hours"], 1.8)


class ValidationStopsTypos(unittest.TestCase):
    """変数ファイルの書き間違いは、黙って別の扱いにせずエラーにする。"""

    def assert_rejected(self, mutate, target="params"):
        case, params, catalog, records = (copy.deepcopy(x) for x in load_all())
        mutate({"params": params, "records": records, "case": case}[target])
        with self.assertRaises(ValueError):
            estimator.estimate(case, params, catalog, records)

    def test_unknown_rule_kind(self):
        self.assert_rejected(lambda p: p["condition_rules"][C.NO_COUNT].update(kind="stat"))

    def test_unknown_tag_unit(self):
        self.assert_rejected(lambda p: p["tag_to_op"]["固着対応"].update(unit="per_bolt"))

    def test_heating_key_outside_cost_keys(self):
        self.assert_rejected(lambda p: p["labor_rate"]["cost_keys"].remove(p["labor_rate"]["heating_key"]))

    def test_unknown_rate_table(self):
        self.assert_rejected(lambda p: p.update(adopted_rate_table="V2"))

    def test_unknown_state_label_in_case(self):
        self.assert_rejected(lambda c: c["condition"]["snow_on_body"].update(state="多い"), target="case")

    def test_unknown_tire_weight_status(self):
        self.assert_rejected(lambda c: c["vehicle"]["tire_with_wheel_weight_kg"].update(status="目視"), target="case")

    def test_unknown_job_in_rule(self):
        self.assert_rejected(lambda p: next(r for r in p["condition_rules"] if r.get("job")).update(job="J3"))

    def test_unknown_job_in_fastener(self):
        self.assert_rejected(lambda c: c["condition"]["fasteners"][C.NO_COUNT].update(job="J3"), target="case")

    def test_unknown_area_in_rule(self):
        self.assert_rejected(lambda p: next(r for r in p["condition_rules"] if r.get("area")).update(area="wheel_hubb"))

    def test_tag_unit_contradicts_records(self):
        # 固着対応の実績は本数（count）付きなので、入庫単位（visit）と書くと矛盾する
        self.assert_rejected(lambda p: p["tag_to_op"]["固着対応"].update(unit=C.TAG_UNIT_VISIT))

    def test_grade_must_be_integer_or_null(self):
        self.assert_rejected(lambda c: c["condition"]["underbody_rust_grade"].update(brake_area="3"), target="case")

    def test_record_count_must_be_positive(self):
        def zero(records):
            next(r for r in records["historical_records"] if "固着対応" in r["tags"])["tags"]["固着対応"]["count"] = C.NO_COUNT
        self.assert_rejected(zero, target="records")

    def test_missing_side_state(self):
        self.assert_rejected(lambda c: c["condition"]["slide_pin_boots"].pop("right"), target="case")

    def test_billable_hours_mismatch(self):
        self.assert_rejected(lambda p: p["labor_rate"]["billable_hours"].update(winter=1))


class Guardrails(unittest.TestCase):
    def test_age_alone_does_not_add_hours(self):
        case, params, catalog, records = load_all()
        newer = copy.deepcopy(case)
        newer["e_shakensho"]["初度登録年月"] = "令和元年5月"
        newer["vehicle"]["odometer_km"] = 40000
        old, new = run(), run(case=newer)
        # 令和元年 = 2019年。経過7年・4万kmで確認強度は「通常」に下がるが、人時は変わらない
        self.assertEqual(new["vehicle"]["first_registration"], "2019-05")
        self.assertEqual(new["checks"]["check_intensity"]["level"], "通常")
        self.assertEqual(old["estimate"]["labor_hours"], new["estimate"]["labor_hours"])

    def test_unconfirmed_is_in_high_not_typical(self):
        items = {item["id"]: item for item in run()["items"]}
        for item_id in ("rotor", "boot:right", "fastener:F-L-SLD-1"):
            self.assertEqual(items[item_id]["hours"]["typical"], 0.0)
            self.assertGreater(items[item_id]["hours"]["high"], 0.0)

    def test_waits_only_change_elapsed(self):
        case, params, catalog, records = load_all()
        params = copy.deepcopy(params)
        params["waits"]["hours"]["thaw"]["default"] += 1.0
        before, after = run(), run(params=params)
        self.assertEqual(before["estimate"]["labor_hours"], after["estimate"]["labor_hours"])
        self.assertNotEqual(before["estimate"]["elapsed_hours"], after["estimate"]["elapsed_hours"])

    def test_heating_cost_only_changes_rate(self):
        case, params, catalog, records = load_all()
        params = copy.deepcopy(params)
        params["labor_rate"]["cost_yen"]["heating_yen"] *= 2
        before, after = run(), run(params=params)
        self.assertEqual(before["estimate"]["labor_hours"], after["estimate"]["labor_hours"])
        self.assertGreater(after["money"]["labor_rate"]["annual_yen_per_hour"], before["money"]["labor_rate"]["annual_yen_per_hour"])

    def test_unconfirmed_work_area_goes_to_high(self):
        case, params, catalog, records = load_all()
        case = copy.deepcopy(case)
        grades = case["condition"]["underbody_rust_grade"]
        grades.update(brake_area=None, wheel_hub=0, front_suspension=0)
        items = {item["id"]: item for item in run(case=case)["items"]}
        self.assertEqual(items["wash"]["state_id"], C.STATE_UNCONFIRMED)
        self.assertEqual(items["wash"]["state"], "未確認")
        self.assertEqual(items["wash"]["hours"]["typical"], 0.0)
        self.assertGreater(items["wash"]["hours"]["high"], 0.0)

    def test_unconfirmed_tire_weight_is_not_in_typical(self):
        case, params, catalog, records = load_all()
        case = copy.deepcopy(case)
        case["vehicle"]["tire_with_wheel_weight_kg"]["status"] = "未確認"
        tire = {item["id"]: item for item in run(case=case)["items"]}["tire_carry"]
        self.assertEqual(tire["hours"]["typical"], 0.0)
        self.assertGreater(tire["hours"]["high"], 0.0)

    def test_weight_between_basis_and_one_person_limit_is_reported(self):
        case, params, catalog, records = load_all()
        case = copy.deepcopy(case)
        case["vehicle"]["tire_with_wheel_weight_kg"]["value"] = 19
        result = run(case=case)
        self.assertNotIn("tire_carry", {item["id"] for item in result["items"]})
        self.assertTrue(any("基準の前提" in u for u in result["unknowns"]))

    def test_result_is_marked_as_proposal(self):
        self.assertTrue(run()["status"].startswith("提案"))

    def test_unbilled_work_has_no_extra_yen(self):
        case, params, catalog, records = load_all()
        case = copy.deepcopy(case)
        case["condition"]["underbody_rust_grade"].update(brake_area=None, wheel_hub=0, front_suspension=0)
        rows = {row["condition"]: row for row in run(case=case)["conditional_quote"]["conditions"]}
        # 下回り洗浄は請求しないので、発生した場合の追加人時はあっても追加金額は 0
        self.assertGreater(rows["下回り洗浄"]["extra_hours"], 0.0)
        self.assertEqual(rows["下回り洗浄"]["extra_yen"], 0)

    def test_same_vehicle_is_found_by_history_without_flag(self):
        case, params, catalog, records = load_all()
        records = copy.deepcopy(records)
        for record in records["historical_records"]:
            record.pop("same_vehicle", None)
        b = run(records=records)["method_comparison"]["b"]
        self.assertEqual([row["id"] for row in b["same_vehicle_cases"]], ["R11"])

    def test_vehicle_key_comes_from_shakensho(self):
        case, params, catalog, records = load_all()
        self.assertEqual(run()["vehicle"]["vehicle_key"], "ABC-XYZ10/2014-01")
        other = copy.deepcopy(case)
        other["e_shakensho"]["型式"] = "DEF-UVW20"
        records = copy.deepcopy(records)
        for record in records["historical_records"]:
            record.pop("same_vehicle", None)
        # 型式が違えば別の車なので、R11 は類似実績の集計に入る
        self.assertEqual(run(case=other, records=records)["method_comparison"]["b"]["n"], 4)

    def test_fastener_of_other_job_is_reported(self):
        case, params, catalog, records = load_all()
        case = copy.deepcopy(case)
        case["jobs"] = ["J2"]
        case["condition"]["fasteners"][C.NO_COUNT]["job"] = "J1"
        result = run(case=case)
        self.assertEqual(len(result["excluded_from_this_job"]), 2)  # ホイールナット（J1）と書き換えた1本

    def test_customer_sheet_matches_conditional_quote(self):
        result = run()
        sheet_conditional = sum(line["high"] for line in result["customer_sheet"]
                                if line["line"].startswith("発生した場合だけの追加"))
        self.assertAlmostEqual(sheet_conditional, result["conditional_quote"]["all_conditions_extra_hours"],
                               places=load_all()[1]["rounding"]["hours_decimals"])

    def test_out_of_scope_area_is_reported_not_added(self):
        result = run()
        self.assertTrue(any(u.startswith("subframe") for u in result["unknowns"]))


if __name__ == "__main__":
    unittest.main()
