"""ゴールデン照合データの生成スクリプト（元の Python 実装を import して出力するだけ）。

実行方法（リポジトリ内の任意の場所から）:

    python3 src/web-app/tests/systems/engine/golden/generate.py [engine_id ...]

引数を省かなければ e01〜e30 と integrated の全部を `cases-<engine_id>.json` に書き出す。
各ケースは {name, engine_id, scenario_input, rule_pack, expected} で、expected は
`auto_repair_engine.runner.run_engine` の戻り値、または例外なら {"error": "<例外クラス名>"}。
ほかに共通フィクスチャ・全30比較・統合版 schema/evaluate・store の出力も書き出す。
元の Python コードは変更しない（SQLite は一時ファイルを使う）。
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))  # .../src

from auto_repair_engine import contract  # noqa: E402
from auto_repair_engine.runner import ENGINE_IDS, compare_engines, run_engine  # noqa: E402

COMMON = contract.common_scenario_fixture
APPROVED = contract.approved_common_scenario_fixture


def fictional_e02_pack(scenario):
    """api.py の create_app 内にあるクロージャと同じ内容（api を import すると DB を作るため複製）。"""
    return {"engine_id": "e02_versioned_json", "rule_version": scenario.get("rule_version", "fictional-rule-v1"),
            "status": "approved", "approved_by": "fictional_shop_owner", "effective_from": "2026-10-11",
            "source": "fictional_fixture_only", "basis_unit": scenario.get("basis_unit"),
            "basis_definition": scenario.get("basis_definition"), "rules": [
                {"job_id": "front_brake_service", "operation_key": "base_service", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 1.7, "typical": 1.7, "high": 1.7}, "unit": "person_hours", "source": "fictional_json:base"},
                {"job_id": "front_brake_service", "operation_key": "replacement_carry", "condition": {"field": "included_operations", "contains": "remove_install"}, "hours": {"low": 0.2, "typical": 0.2, "high": 0.2}, "unit": "person_hours", "source": "fictional_json:carry"},
                {"job_id": "front_brake_service", "operation_key": "snow_melt", "condition": {"field": "included_operations", "contains": "snow_removal"}, "hours": {"low": 0.5, "typical": 0.5, "high": 0.5}, "unit": "elapsed_hours", "source": "fictional_json:snow"},
                {"job_id": "front_brake_service", "operation_key": "penetrant_wait", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 0.25, "typical": 0.25, "high": 0.25}, "unit": "elapsed_hours", "source": "fictional_json:penetrant"},
                {"job_id": "front_brake_service", "operation_key": "parts_wait", "condition": {"field": "parts_wait_stock_checked", "equals": True}, "hours": {"low": 0.0, "typical": 0.0, "high": 0.0}, "unit": "elapsed_hours", "source": "fictional_json:parts"},
                {"job_id": "front_brake_service", "operation_key": "wash", "condition": {"field": "work_scope", "equals": "front_brake_service"}, "hours": {"low": 0.1, "typical": 0.1, "high": 0.1}, "unit": "person_hours", "source": "fictional_json:wash"},
                {"job_id": "front_brake_service", "operation_key": "rotor_seizure", "condition": {"field": "rotor_relevance", "equals": "relevant"}, "hours": {"low": 0.0, "typical": 0.25, "high": 0.5}, "unit": "person_hours", "source": "fictional_json:rotor"}]}


def op(scenario, operation_id):
    return next(o for o in scenario["operations"] if o["operation_id"] == operation_id)


# --- シナリオの変種（共通フィクスチャに小さな変更を加えて分岐を踏む） ---
def _unrelated(s):
    s["fields"]["rotor_relevance"] = {"value": "unrelated", "status": "confirmed", "source": "x", "confirmed_at": None}
    s["fields"].pop("rotor_seizure_hours", None)
    s["metadata"].pop("approved_condition_widths", None)


def _snow_unknown(s):
    op(s, "snow_melt")["elapsed_hours"] = None
    op(s, "snow_melt")["hours"] = None


def _stock_unchecked(s):
    op(s, "parts_wait")["stock_checked"] = False


def _scope_wrong(s):
    s["fields"]["work_scope"]["value"] = "other_job"


def _scope_assumed(s):
    s["fields"]["work_scope"]["status"] = "assumed"


def _drop_wash(s):
    s["operations"] = [o for o in s["operations"] if o["operation_id"] != "wash"]


def _drop_replacement(s):
    s["operations"] = [o for o in s["operations"] if o["operation_id"] != "replacement_carry"]


def _carry_exceeds(s):
    op(s, "included_carry")["hours"] = 5.0


def _bad_basis(s):
    s["basis_unit"] = "hour"


def _rotor_mismatch(s):
    s["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["new_value"] = {"low": 0.0, "typical": 0.3, "high": 0.5}


def _rotor_no_actor(s):
    s["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["actor"] = " "


def _extra_scope(s):
    s["fields"]["included_operations"]["value"] = ["remove_install", "rust_observation", "snow_removal", "extra_op"]


def _unknown_op(s):
    s["operations"].append({"operation_id": "mystery", "operation": "mystery", "hours": 1.0, "person_count": 1, "status": "x"})


def _job_other(s):
    s["job_id"] = "rear_brake_service"


def _base_not_dedup(s):
    op(s, "base_service")["deduplicated"] = False


def _version_other(s):
    s["rule_version"] = "fictional-rule-v2"


def _rotor_unknown(s):
    s["fields"].pop("rotor_relevance", None)
    s["fields"].pop("rotor_seizure_hours", None)
    s["metadata"].pop("approved_condition_widths", None)


VARIANTS = [
    ("common", COMMON, None), ("approved", APPROVED, None),
    ("unrelated", APPROVED, _unrelated), ("snow_unknown", APPROVED, _snow_unknown),
    ("stock_unchecked", APPROVED, _stock_unchecked), ("scope_wrong", APPROVED, _scope_wrong),
    ("scope_assumed", APPROVED, _scope_assumed), ("drop_wash", APPROVED, _drop_wash),
    ("drop_replacement", APPROVED, _drop_replacement), ("carry_exceeds", APPROVED, _carry_exceeds),
    ("bad_basis", APPROVED, _bad_basis), ("rotor_mismatch", APPROVED, _rotor_mismatch),
    ("rotor_no_actor", APPROVED, _rotor_no_actor), ("extra_scope", APPROVED, _extra_scope),
    ("unknown_op", APPROVED, _unknown_op), ("job_other", APPROVED, _job_other),
    ("base_not_dedup", APPROVED, _base_not_dedup), ("version_other", APPROVED, _version_other),
    ("rotor_unknown", APPROVED, _rotor_unknown),
]


def make_variant(maker, mutate):
    s = maker()
    if mutate:
        mutate(s)
    return s


# engine ごとの追加ケース: engine_id -> [(name, scenario_or_None, rule_pack)]。scenario が None なら approved。
EXTRA: dict[str, list] = {}
# engine ごとの通常ケースで使う既定の rule_pack を返す関数（api.py の挙動に合わせる）
DEFAULT_PACK = {"e02": fictional_e02_pack}


def reset_state():
    """E05/E06 はモジュール内に公開済みスナップショットを保持する。ケースごとに空にして順序依存をなくす。"""
    from auto_repair_engine import e05, e06
    e05._PUBLISHED.clear()
    e06._PUBLISHED.clear()


def run_case(engine_id, scenario, pack):
    reset_state()
    try:
        return run_engine(engine_id, copy.deepcopy(scenario), copy.deepcopy(pack))
    except Exception as exc:  # noqa: BLE001 - 例外クラス名を期待値として記録する
        return {"error": type(exc).__name__}


def build_cases(engine_id):
    cases = []
    for name, maker, mutate in VARIANTS:
        scenario = make_variant(maker, mutate)
        pack_fn = DEFAULT_PACK.get(engine_id)
        pack = pack_fn(scenario) if pack_fn else None
        cases.append({"name": name, "engine_id": engine_id, "variant": name, "scenario_input": scenario, "rule_pack": pack})
        if pack is not None and engine_id == "e02":
            cases.append({"name": name + ":no_pack", "engine_id": engine_id, "variant": name, "scenario_input": scenario, "rule_pack": None})
    for name, scenario, pack in EXTRA.get(engine_id, []):
        scenario = copy.deepcopy(scenario) if scenario is not None else APPROVED()
        cases.append({"name": name, "engine_id": engine_id, "scenario_input": scenario, "rule_pack": pack})
    for case in cases:
        case["expected"] = run_case(engine_id, case["scenario_input"], case["rule_pack"])
        if "variant" in case:  # 共通シナリオ変種は variants.json 側にだけ持つ
            del case["scenario_input"]
    return cases


# --- 関数単位のゴールデン（units.json）: (キー, 引数, 呼び出す関数) ---
UNITS: list = []


def unit(key, fn, *args):
    UNITS.append((key, list(args), fn))


def build_units():
    out = []
    for key, args, fn in UNITS:
        reset_state()
        try:
            expected = fn(*copy.deepcopy(args))
        except Exception as exc:  # noqa: BLE001
            expected = {"error": type(exc).__name__}
        out.append({"fn": key, "args": args, "expected": expected})
    return out


def extra(engine_id, name, pack, scenario=None):
    EXTRA.setdefault(engine_id, []).append((name, scenario, pack))


# ---------------------------------------------------------------- E03
def _e03_extras():
    from auto_repair_engine import e03
    base = e03._default_rule_pack(COMMON())

    def mod(fn):
        pack = copy.deepcopy(base)
        fn(pack)
        return pack

    def rule(pack, rule_id):
        return next(r for r in pack["rules"] if r["rule_id"] == rule_id)

    extra("e03", "explicit_default", copy.deepcopy(base))
    extra("e03", "base_range_changed", mod(lambda p: rule(p, "base_service").update(expression='when work_scope equals "front_brake_service" -> set_range base_service {"low":1.6,"typical":1.8,"high":2.0} person_hours')))
    extra("e03", "nan_range", mod(lambda p: p["rules"][0].update(expression='when work_scope equals "front_brake_service" -> set_range base_service {"low":0,"typical":NaN,"high":2} person_hours')))
    extra("e03", "extra_rule_key", mod(lambda p: p["rules"][0].update(extra="eval")))
    extra("e03", "version_mismatch", mod(lambda p: p.update(rule_version="fictional-rule-v2")))
    extra("e03", "rotor_range_mismatch", mod(lambda p: p["rules"][-1].update(expression='when rotor_relevance equals "relevant" -> set_range rotor_seizure {"low":0,"typical":0.3,"high":0.5} person_hours')))
    extra("e03", "snow_width", mod(lambda p: rule(p, "snow_melt").update(expression='when work_scope equals "front_brake_service" -> set_range snow_melt {"low":0.4,"typical":0.5,"high":0.6} elapsed_hours')))
    extra("e03", "missing_version", mod(lambda p: p.pop("rule_version")))
    extra("e03", "not_a_dict_pack", ["x"])
    extra("e03", "duplicate_rule_id", mod(lambda p: p["rules"].append(copy.deepcopy(p["rules"][0]))))
    extra("e03", "empty_rules", mod(lambda p: p.update(rules=[])))
    extra("e03", "unapproved", mod(lambda p: p.update(status="draft")))
    extra("e03", "no_source_reason", mod(lambda p: p["rules"][1].update(source=" ")))

    def snow_unknown(s):
        s["operations"][3]["elapsed_hours"] = None
        return s
    extra("e03", "snow_unknown_default", None, snow_unknown(APPROVED()))
    for text in (
        'when work_scope equals "front_brake_service" -> __import__("os").system("id")',
        'when arbitrary_field equals true -> set_range wash {"low":0,"typical":0,"high":0} person_hours',
        'when work_scope equals "front_brake_service" -> set_range wash {"low":2,"typical":1,"high":3} person_hours',
        'when work_scope equals "front_brake_service" -> set_range wash {"low":0,"typical":1,"high":2} exec',
        'when work_scope equals "front_brake_service" -> set_range wash {"low":0,"typical":1,"high":2} person_hours',
        '  when work_scope equals "a\\u00e9\\"b" -> set_range wash {"low":0.5,"typical":1e-2,"high":2} person_hours  ',
        'when parts_wait_stock_checked equals true -> set_range parts_wait {"low":0,"typical":0,"high":0} elapsed_hours',
        'when rotor_relevance equals null -> set_range rotor_seizure {"low":0,"typical":0,"high":0} elapsed_hours',
        'when rotor_relevance equals -0.5 -> set_range rotor_seizure {"low":0,"typical":0,"high":0} person_hours',
        'when work_scope equals 01 -> set_range wash {"low":0,"typical":0,"high":0} person_hours',
        'when work_scope equals "x"\n-> set_range wash {"low":0,"typical":0,"high":0} person_hours',
        5,
    ):
        unit("e03.parse_to_ast", e03.parse_to_ast, text)


_e03_extras()


# ---------------------------------------------------------------- E04（rule_pack を JSON で渡すケース）
def _e04_pack(version="fictional-rule-v1", wash_hours=0.1):
    definitions = (
        ("base_service", "承認済み基準作業", "work", "person_hours", 1.7, 1),
        ("included_carry", "含有運搬", "work", "person_hours", 0.12, 1),
        ("replacement_carry", "二人作業の運搬", "work", "person_hours", 0.2, 2),
        ("rotor_seizure", "ローター固着", "work", "person_hours", {"low": 0, "typical": 0.25, "high": 0.5}, 1),
        ("snow_melt", "雪の融解待ち", "wait", "elapsed_hours", 0.5, 0),
        ("penetrant_wait", "浸透待ち", "wait", "elapsed_hours", 0.25, 0),
        ("parts_wait", "部品待ち", "wait", "elapsed_hours", 0.0, 0),
        ("wash", "洗浄", "wait" if False else "work", "person_hours", wash_hours, 1),
    )
    entries = []
    for operation_id, name, kind, unit, hours, person_count in definitions:
        if isinstance(hours, (int, float)):
            hours = {"low": hours, "typical": hours, "high": hours}
        entries.append({"operation_id": operation_id, "operation_key": operation_id, "operation": name, "kind": kind,
                        "unit": unit, "hours": hours, "person_count": person_count,
                        "evidence": [{"source": "fictional_simulator_fixture", "note": f"架空 evidence: {operation_id}"}]})
    return {"id": "fictional_labor_rules", "rule_version": version, "status": "approved",
            "approved_by": "fictional_shop_owner", "effective_from": "2026-10-11",
            "source": "fictional_simulator_fixture", "rules": entries}


def _e04_extras():
    def mod(fn, **kw):
        p = _e04_pack(**kw)
        fn(p)
        return p

    extra("e04", "pack_v1", _e04_pack())
    extra("e04", "pack_v2_mismatch", _e04_pack("fictional-rule-v2", 0.2))
    extra("e04", "pack_v2_pinned", _e04_pack("fictional-rule-v2", 0.2), None)
    s = APPROVED()
    s["rule_version"] = "fictional-rule-v2"
    extra("e04", "pack_v2_matches_pin", _e04_pack("fictional-rule-v2", 0.2), s)
    extra("e04", "no_version", mod(lambda p: p.pop("rule_version")))
    extra("e04", "version_key_alias", mod(lambda p: (p.pop("rule_version"), p.update(version="fictional-rule-v1"))))
    extra("e04", "draft_without_approver", mod(lambda p: p.update(status="draft", approved_by=None)))
    extra("e04", "draft_pack", mod(lambda p: p.update(status="draft")))
    extra("e04", "bad_status", mod(lambda p: p.update(status="weird")))
    extra("e04", "approved_without_approver", mod(lambda p: p.update(approved_by=" ")))
    extra("e04", "empty_rules", mod(lambda p: p.update(rules=[])))
    extra("e04", "duplicate_operation", mod(lambda p: p["rules"].append(copy.deepcopy(p["rules"][-1]))))
    extra("e04", "bad_hours_order", mod(lambda p: p["rules"][0].update(hours={"low": 2, "typical": 1, "high": 3})))
    extra("e04", "negative_hours", mod(lambda p: p["rules"][0].update(hours=-1)))
    extra("e04", "bool_hours", mod(lambda p: p["rules"][0].update(hours=True)))
    extra("e04", "hours_missing", mod(lambda p: p["rules"][0].pop("hours")))
    extra("e04", "bad_person_count", mod(lambda p: p["rules"][0].update(person_count=-1)))
    extra("e04", "bad_kind_unit", mod(lambda p: p["rules"][0].update(unit="elapsed_hours")))
    extra("e04", "entry_not_dict", mod(lambda p: p["rules"].append(5)))
    extra("e04", "evidence_no_source", mod(lambda p: p["rules"][0].update(evidence=[{"note": "x"}])))
    extra("e04", "evidence_bad_note", mod(lambda p: p["rules"][0].update(evidence=[{"source": "s", "note": 5}])))
    extra("e04", "evidence_duplicate_id", mod(lambda p: p["rules"][0].update(evidence=[{"id": "e", "source": "s"}, {"id": "e", "source": "t"}])))
    extra("e04", "dup_operation_key", mod(lambda p: p["rules"][1].update(operation_key="base_service")))
    extra("e04", "effective_from_null", mod(lambda p: p.update(effective_from=None)))
    extra("e04", "source_dict", mod(lambda p: p.update(source={"a": 1})))
    extra("e04", "not_dict", [1, 2])
    extra("e04", "rotor_8", mod(lambda p: next(r for r in p["rules"] if r["operation_id"] == "rotor_seizure").update(hours={"low": 8.0, "typical": 8.0, "high": 8.0})))
    extra("e04", "missing_op", mod(lambda p: p["rules"].pop(0)))
    extra("e04", "custom_id", mod(lambda p: p.update(id="other_rules")))
    extra("e04", "numeric_id", mod(lambda p: p.update(id=5)))


_e04_extras()


# ---------------------------------------------------------------- E08 / E09
def _e08_extras():
    for name, pack in {
        "s05_v": {"method_id": "S05", "rule_version": "fixture-r7"},
        "s19": {"method_id": "S19"},
        "unknown_method": {"method_id": "not_registered"},
        "blank_version": {"method_id": "S01", "rule_version": " "},
        "method_not_str": {"method_id": 5},
        "pack_list": ["x"],
        "empty_pack": {},
    }.items():
        extra("e08", name, pack)
    s = APPROVED()
    s.pop("basis_unit")
    extra("e08", "no_basis_unit", None, s)
    s = APPROVED()
    s["basis_definition"] = ""
    extra("e08", "empty_definition", None, s)
    s = APPROVED()
    s["operations"] = "x"
    extra("e08", "operations_not_list", None, s)
    s = COMMON()
    extra("e08", "common", {"method_id": "S01"}, s)


_e08_extras()


def _dag(nodes, edges=(), limit=2, version="fictional-rule-v1", **kw):
    pack = {"engine_id": "e09_process_dag", "rule_version": version, "status": "approved",
            "resource_limit": limit, "nodes": nodes, "edges": [list(e) if isinstance(e, tuple) else e for e in edges]}
    pack.update(kw)
    return pack


def _e09_extras():
    n = lambda **k: k  # noqa: E731
    extra("e09", "parallel", _dag([n(operation_id="a", duration_hours={"low": 1, "typical": 2, "high": 3}, person_count=1),
                                    n(operation_id="b", duration_hours=1, person_count=1),
                                    n(operation_id="c", duration_hours=0.5, person_count=2)], [("a", "c"), ("b", "c")]), COMMON())
    extra("e09", "serial", _dag([n(operation_id="a", duration_hours={"low": 1, "typical": 2, "high": 3}, person_count=1),
                                  n(operation_id="b", duration_hours=1, person_count=1),
                                  n(operation_id="c", duration_hours=0.5, person_count=2)], [("a", "b"), ("b", "c")]), COMMON())
    two = [n(operation_id=k, duration_hours=2, person_count=1) for k in ("first", "second")]
    extra("e09", "one_worker", _dag(two, limit=1), COMMON())
    extra("e09", "two_workers", _dag(two, limit=2), COMMON())
    extra("e09", "unknown_wait", _dag([n(operation_id="work", duration_hours=2, person_count=2),
                                       n(operation_id="wait", kind="wait", duration_hours=None, person_count=0)], [("work", "wait")]), COMMON())
    extra("e09", "known_wait", _dag([n(operation_id="work", duration_hours=2, person_count=2),
                                     n(operation_id="wait", kind="wait", duration_hours=0.75)], [{"before": "work", "after": "wait"}]), COMMON())
    extra("e09", "missing_ref", _dag([n(operation_id="a", duration_hours=1)], [("a", "missing")]), COMMON())
    extra("e09", "duplicate", _dag([n(operation_id="a", duration_hours=1), n(operation_id="a", duration_hours=1)]), COMMON())
    extra("e09", "cycle", _dag([n(operation_id="a", duration_hours=1), n(operation_id="b", duration_hours=1)], [("a", "b"), ("b", "a")]), COMMON())
    extra("e09", "capacity", _dag([n(operation_id="a", duration_hours=1, person_count=3)], limit=2), COMMON())
    extra("e09", "unknown_work", _dag([n(operation_id="a", duration_hours=None)]), COMMON())
    extra("e09", "version_mismatch", _dag([n(operation_id="a", duration_hours=1)], version="different"), COMMON())
    extra("e09", "empty_pack", {}, APPROVED())
    extra("e09", "list_pack", [], APPROVED())
    extra("e09", "version_only", {"rule_version": "fictional-rule-v1"}, APPROVED())
    extra("e09", "bad_edges", _dag([n(operation_id="a", duration_hours=1)], [("a", "a"), "x", [1, 2, 3], {"before": "a"}]), COMMON())
    extra("e09", "bad_nodes", _dag([5, n(operation_id=" "), n(operation_id="k", kind="odd"), n(operation_id="w", kind="wait", person_count=2, duration_hours=1),
                                   n(operation_id="z", duration_hours=-1), n(operation_id="y", person_count=True, duration_hours=1),
                                   n(operation_id="x", duration_hours={"low": 3, "typical": 2, "high": 1})]), COMMON())
    extra("e09", "bad_limit", _dag([n(operation_id="a", duration_hours=1)], limit=0), COMMON())
    extra("e09", "bool_limit", _dag([n(operation_id="a", duration_hours=1)], limit=True), COMMON())
    extra("e09", "draft_other_engine", _dag([n(operation_id="a", duration_hours=1)], status="draft", engine_id="other"), COMMON())
    extra("e09", "no_nodes", _dag([]), COMMON())
    extra("e09", "edges_not_list", {"rule_version": "fictional-rule-v1", "nodes": [n(operation_id="a", duration_hours=1)], "edges": "x", "resource_limit": 1}, COMMON())
    extra("e09", "diamond", _dag([n(operation_id="s", duration_hours=1, person_count=1), n(operation_id="l", duration_hours=2.5, person_count=2),
                                  n(operation_id="r", duration_hours=0.7, person_count=1), n(operation_id="t", duration_hours={"low": 0.1, "typical": 0.3, "high": 0.9}, person_count=3),
                                  n(operation_id="d", kind="wait", duration_hours=1.3)],
                                 [("s", "l"), ("s", "r"), ("l", "t"), ("r", "t"), ("t", "d")], limit=3), COMMON())


_e09_extras()


# ---------------------------------------------------------------- E10 / E11
def _e10_extras():
    from auto_repair_engine import e10
    v = "fictional-rule-v1"
    s = APPROVED()
    extra("e10", "gross_explicit", None, dict(s, ledger_mode="gross"))
    c = COMMON()
    c["ledger_mode"] = "gross"
    extra("e10", "common_gross_rededuction", None, c)
    s2 = APPROVED()
    s2["ledger_mode"] = "deduplicated"
    extra("e10", "deduplicated_mode", None, s2)
    s3 = APPROVED()
    s3["ledger_mode"] = "other"
    extra("e10", "bad_mode", None, s3)
    extra("e10", "dup_shared_keys", {"rule_version": v, "shared_deductions": [
        {"key": ["shared_overlap", "both", "front_brake_service"], "hours": 0.3, "owners": ["left", "right"], "reason": "one shared operation"},
        {"key": ["shared_overlap", "both", "front_brake_service"], "hours": 0.3, "owners": ["left", "right"], "reason": "repeated request"}]})
    extra("e10", "exclusive_two", {"rule_version": v, "exclusive_groups": [{"name": "carry-choice", "selected": ["included", "replacement"]}]})
    extra("e10", "exclusive_one", {"rule_version": v, "exclusive_groups": [{"name": "carry-choice", "selected": ["included"]}]})
    extra("e10", "exclusive_bad", {"rule_version": v, "exclusive_groups": [5, {"selected": "x"}]})
    extra("e10", "exclusive_not_list", {"rule_version": v, "exclusive_groups": "x"})
    extra("e10", "empty_pack", {})
    extra("e10", "bad_ledger_entry", {"rule_version": v, "ledger": {"entries": [{"operation": "x"}]}})
    extra("e10", "bad_ledger_shape", {"rule_version": v, "ledger": {"entries": 5}})
    extra("e10", "ledger_entry_not_obj", {"rule_version": v, "ledger": [5]})
    extra("e10", "ledger_prefilled", {"rule_version": v, "ledger": [{"operation": "shared_overlap", "side": "both", "scope": "front_brake_service", "owners": ["x"]}],
                                      "shared_deductions": [{"key": ["shared_overlap", "both", "front_brake_service"], "hours": 0.3, "owners": ["a"], "reason": "r"}]},
          dict(s, ledger_mode="gross"))
    extra("e10", "shared_ok_gross", {"rule_version": v, "shared_deductions": [{"key": {"operation": "o", "side": "l", "scope": "s"}, "hours": 0.2, "owners": "alice", "reason": "ok"},
                                                                          {"key": ("o", "r", "s"), "hours": 0.1, "owners": ["a", "a", " b "], "reason": "ok2"}]},
          dict(s, ledger_mode="gross", operations=[dict(o, gross_hours=2.0) if o["operation_id"] == "base_service" else o for o in s["operations"]]))
    extra("e10", "shared_bad_items", {"rule_version": v, "shared_deductions": [5, {"hours": -1}, {"hours": 0.1, "key": 5}, {"hours": 0.1, "key": ["a", "b", " "]},
                                                                         {"hours": 0.1, "key": ["a", "b", "c"], "owners": []}, {"hours": 0.1, "key": ["a", "b", "c"], "owners": "x", "reason": ""}]},
          dict(s, ledger_mode="gross"))
    extra("e10", "shared_not_list", {"rule_version": v, "shared_deductions": "x"}, dict(s, ledger_mode="gross"))
    extra("e10", "shared_too_much", {"rule_version": v, "shared_deductions": [{"key": ["a", "b", "c"], "hours": 99, "owners": "x", "reason": "r"}]},
          dict(s, ledger_mode="gross"))
    extra("e10", "pack_not_dict", ["x"])
    extra("e10", "pack_mismatch_engine", {"engine_id": "other", "rule_version": "zzz", "status": "draft"})
    s4 = APPROVED()
    s4["operations"] = [o for o in s4["operations"] if o["operation_id"] != "wash"] + [dict(next(o for o in s4["operations"] if o["operation_id"] == "base_service"))]
    extra("e10", "dup_and_missing_ops", None, s4)
    s5 = APPROVED()
    s5["operations"].append(5)
    s5["operations"].append({"operation_id": 5})
    extra("e10", "bad_ops_items", None, s5)
    s6 = APPROVED()
    s6["fields"] = []
    extra("e10", "fields_not_dict", None, s6)
    s7 = APPROVED()
    s7["operations"] = {}
    extra("e10", "ops_not_dict", None, s7)
    s8 = APPROVED()
    op(s8, "included_carry")["included_in_base"] = False
    extra("e10", "included_not_in_base", None, s8)
    s9 = APPROVED()
    op(s9, "replacement_carry")["person_count"] = 0
    extra("e10", "replacement_zero", None, s9)
    s10 = APPROVED()
    op(s10, "parts_wait")["stock_checked"] = False
    extra("e10", "stock_unchecked", None, s10)
    s11 = APPROVED()
    op(s11, "wash")["hours"] = None
    extra("e10", "wash_none", None, s11)
    s12 = APPROVED()
    op(s12, "penetrant_wait")["elapsed_hours"] = "x"
    extra("e10", "wait_invalid", None, s12)
    s13 = APPROVED()
    s13["fields"]["rotor_relevance"]["value"] = "relevant"
    s13["metadata"].pop("approved_condition_widths")
    extra("e10", "rotor_no_approval", None, s13)
    s14 = APPROVED()
    s14["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["new_value"] = {"low": 0, "typical": 1, "high": 2}
    extra("e10", "rotor_mismatch", None, s14)
    s15 = APPROVED()
    s15["fields"]["rotor_seizure_hours"]["value"] = {"low": 1, "typical": 0.5, "high": 2}
    extra("e10", "rotor_bad_range", None, s15)
    s16 = APPROVED()
    s16["fields"].pop("rotor_relevance")
    extra("e10", "rotor_relevance_missing", None, s16)
    s17 = APPROVED()
    s17["fields"]["work_scope"] = 5
    extra("e10", "work_scope_not_dict", None, s17)
    s18 = APPROVED()
    s18["metadata"] = None
    extra("e10", "metadata_none", None, s18)

    ledger0 = {"entries": []}
    key = ["shared_operation", "both", "front_brake_service"]
    d = lambda ledger, key, amount, owners, reason: e10.deduct_once(ledger, key, amount, owners=owners, reason=reason)  # noqa: E731
    r = lambda ledger, key, rkey, owners, old_hours, replacement_hours, reason: e10.replace_once(  # noqa: E731
        ledger, key, rkey, owners=owners, old_hours=old_hours, replacement_hours=replacement_hours, reason=reason)
    once = d(ledger0, key, 0.3, ["left", "right"], "shared once")[0]
    unit("e10.deduct_once", d, ledger0, key, 0.3, ["left", "right"], "shared once")
    unit("e10.deduct_once", d, once, key, 0.3, ["third"], "attempt again")
    unit("e10.deduct_once", d, ledger0, ["align", "left", "front"], 0.1, "left-tech", "left")
    unit("e10.deduct_once", d, None, {"operation": " a ", "side": "b", "scope": "c"}, 0, " x ", " why ")
    unit("e10.deduct_once", d, [], key, -1, "x", "r")
    unit("e10.deduct_once", d, [], key, 1, "x", " ")
    unit("e10.deduct_once", d, [], ["a", "b"], 1, "x", "r")
    unit("e10.deduct_once", d, [], ["a", "b", 3], 1, "x", "r")
    unit("e10.deduct_once", d, [], key, 1, [], "r")
    unit("e10.deduct_once", d, [], key, 1, ["a", ""], "r")
    unit("e10.deduct_once", d, 5, key, 1, "x", "r")
    unit("e10.deduct_once", d, {"entries": [5]}, key, 1, "x", "r")
    unit("e10.deduct_once", d, {"entries": [], "extra": 1}, key, True, "x", "r")
    source = {"operation": "included_carry", "side": "both", "scope": "front"}
    target = {"operation": "replacement_carry", "side": "both", "scope": "front"}
    ledger1 = d(ledger0, source, 0.12, "base_service", "included")[0]
    replaced = r(ledger1, source, target, "replacement_carry", 0.12, 0.2, "two-person replacement")
    unit("e10.replace_once", r, ledger1, source, target, "replacement_carry", 0.12, 0.2, "two-person replacement")
    unit("e10.replace_once", r, replaced[0], source, target, "replacement_carry", 0.12, 0.2, "duplicate")
    unit("e10.replace_once", r, ledger0, source, target, "replacement_carry", 0.12, 0.2, "missing source")
    unit("e10.replace_once", r, ledger1, source, target, "x", -1, 0.2, "bad hours")
    unit("e10.replace_once", r, ledger1, source, target, "x", 1, 0.2, "")
    unit("e10.replace_once", r, ledger1, source, target, [], 1, 0.2, "no owners")


_e10_extras()


def _e11_extras():
    from auto_repair_engine import e11
    s = APPROVED()
    v = e11.RULE_VERSION
    extra("e11", "no_choice", None)
    extra("e11", "choose_a", {"selected_method": "A", "actor": "human", "reason": "review"})
    extra("e11", "choose_b", {"selected_method": "B", "actor": "human", "reason": "review"})
    extra("e11", "choose_b_no_actor", {"selected_method": "B", "actor": " ", "reason": "review"})
    extra("e11", "choose_c", {"selected_method": "C", "actor": "human", "reason": "review"})
    extra("e11", "choose_missing", {"selected_method": "Z", "actor": "human", "reason": "review"})
    extra("e11", "choose_s05", {"selected_method": "S05", "methods": ["A", "B", "S05"], "actor": "h", "reason": "r", "rule_version": v})
    extra("e11", "methods_with_c", {"selected_method": "A", "methods": ["A", "C"], "actor": "h", "reason": "r"})
    extra("e11", "methods_dup", {"selected_method": "A", "methods": ["A", "A"], "actor": "h", "reason": "r"})
    extra("e11", "methods_empty", {"selected_method": "A", "methods": [], "actor": "h", "reason": "r"})
    extra("e11", "methods_bad", {"selected_method": "A", "methods": "AB", "actor": "h", "reason": "r"})
    extra("e11", "methods_only_b", {"selected_method": "A", "methods": ["B"], "actor": "h", "reason": "r"})
    extra("e11", "blank_version", {"selected_method": "A", "rule_version": " ", "actor": "h", "reason": "r"})
    extra("e11", "common_choose_a", {"selected_method": "A", "actor": "h", "reason": "r"}, COMMON())
    extra("e11", "common_choose_b", {"selected_method": "B", "actor": "h", "reason": "r"}, COMMON())
    sn = APPROVED()
    op(sn, "snow_melt")["elapsed_hours"] = None
    extra("e11", "snow_unknown_a", {"selected_method": "A", "actor": "h", "reason": "r"}, sn)
    extra("e11", "snow_unknown_b", {"selected_method": "B", "actor": "h", "reason": "r"}, sn)
    extra("e11", "pack_not_dict", ["x"], s)


_e11_extras()


# ---------------------------------------------------------------- スクリプト形式のゴールデン（scripted.json）
SCRIPTS: dict = {}


def script(fn):
    SCRIPTS[fn.__name__] = fn
    return fn


E05_CSV = """job_id,operation_key,condition_field,match_value,low,typical,high,unit,source,reason
front_brake_service,base_service,work_scope,front_brake_service,1.7,1.7,1.7,person_hours,fixture:base,base work
front_brake_service,replacement_carry,included_operations,remove_install,0.2,0.2,0.2,person_hours,fixture:carry,replacement handling
front_brake_service,snow_melt,included_operations,snow_removal,0.5,0.5,0.5,elapsed_hours,fixture:snow,wait only
front_brake_service,penetrant_wait,work_scope,front_brake_service,0.25,0.25,0.25,elapsed_hours,fixture:penetrant,wait only
front_brake_service,parts_wait,parts_wait_stock_checked,true,0,0,0,elapsed_hours,fixture:parts,stock checked wait
front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fixture:wash,performed wash
front_brake_service,rotor_seizure,rotor_relevance,relevant,0,0.25,0.5,person_hours,fixture:rotor,condition range
"""


def _batch_json(batch):
    return {"hash": batch.hash, "rows": [r.__dict__ for r in batch.rows], "errors": list(batch.errors)}


@script
def e04_replay():
    from auto_repair_engine.e04 import create_database, publish_rule_pack, run, seed_default_rule_pack
    db = create_database()
    seed_default_rule_pack(db)
    scenario = APPROVED()
    original = run(scenario, connection=db)
    publish_rule_pack(db, _e04_pack("fictional-rule-v2", wash_hours=0.2))
    scenario["rule_version"] = "fictional-rule-v2"
    changed = run(scenario, connection=db)
    old = run(APPROVED(), connection=db)
    return {"original": original, "changed": changed, "old_after_v2": old}


@script
def e04_rotor_mismatch():
    from auto_repair_engine.e04 import create_database, publish_rule_pack, run, seed_default_rule_pack
    db = create_database()
    seed_default_rule_pack(db, "fictional-rule-v1")
    pack = _e04_pack("fictional-rule-v2")
    next(i for i in pack["rules"] if i["operation_id"] == "rotor_seizure")["hours"] = {"low": 8.0, "typical": 8.0, "high": 8.0}
    publish_rule_pack(db, pack)
    scenario = APPROVED()
    scenario["rule_version"] = "fictional-rule-v2"
    return run(scenario, connection=db)


@script
def e04_duplicate_publish():
    from auto_repair_engine.e04 import create_database, publish_rule_pack
    db = create_database()
    pack = _e04_pack("fictional-duplicate")
    pack["rules"].append(copy.deepcopy(pack["rules"][-1]))
    try:
        publish_rule_pack(db, pack)
    except ValueError as exc:
        message = str(exc)
    counts = [db.execute("SELECT COUNT(*) FROM rules").fetchone()[0], db.execute("SELECT COUNT(*) FROM rule_operations").fetchone()[0],
              db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]]
    return {"message": message, "counts": counts}


@script
def e05_parse_and_validate():
    from auto_repair_engine import e05
    out = {}
    out["fixture_bytes"] = _batch_json(e05.parse_csv(E05_CSV.encode("utf-8")))
    out["fixture_errors"] = list(e05.validate_units(e05.parse_csv(E05_CSV)))
    out["preview"] = e05.preview_diff(e05.parse_csv(E05_CSV))
    malformed = E05_CSV.replace("1.7,1.7,1.7,person_hours,fixture:base", "nan,-1,2,elapsed_hours,fixture:base").replace("front_brake_service,wash,", "front_brake_service,mystery_step,")
    out["malformed_batch_errors"] = list(e05.parse_csv(malformed).errors)
    out["malformed_validate"] = list(e05.validate_units(e05.parse_csv(malformed)))
    out["wrong_unit"] = list(e05.validate_units(e05.parse_csv(E05_CSV.replace("0.5,0.5,0.5,elapsed_hours,fixture:snow", "0.5,0.5,0.5,person_hours,fixture:snow"))))
    out["duplicate"] = list(e05.validate_units(e05.parse_csv(E05_CSV + "front_brake_service,wash,work_scope,front_brake_service,0.1,0.1,0.1,person_hours,fixture:wash2,duplicate\n")))
    out["bad_boolean"] = list(e05.validate_units(e05.parse_csv(E05_CSV.replace("parts_wait_stock_checked,true,", "parts_wait_stock_checked,perhaps,"))))
    out["misaligned"] = list(e05.validate_units(e05.parse_csv(E05_CSV.replace("0,0.25,0.5", "0.5,0.25,0.1"))))
    odd = [
        "", "\n", "a,b\n", "job_id,operation_key\n1,2\n", "﻿" + E05_CSV,
        E05_CSV.replace("\n", "\r\n"), E05_CSV.replace("\n", "\r"), E05_CSV + "\n\n",
        E05_CSV.replace("fixture:base,base work", '"fixture:base","base, work"'),
        E05_CSV.replace("fixture:base,base work", '"fixture:base","base ""quoted"" work"'),
        E05_CSV.replace("fixture:base,base work", '"fixture:base","multi\nline"'),
        E05_CSV.rstrip("\n").replace("person_hours,fixture:wash,performed wash", "person_hours,fixture:wash") + "\n",
        E05_CSV.replace("fixture:carry,replacement handling", "fixture:carry,replacement handling,EXTRA"),
        E05_CSV.replace("job_id,operation_key", " job_id , operation_key"),
        E05_CSV.replace("1.7,1.7,1.7", " 1.7 , 1.7 ,1.7"),
        E05_CSV.replace("1.7,1.7,1.7", "1e0,+1.7,inf"),
        E05_CSV.replace("1.7,1.7,1.7", "abc,1.7,1.7"),
        E05_CSV.replace("1.7,1.7,1.7", ",,"),
        '"job_id","operation_key"\n"a,"b"c"\n',
        "x\n\n\ny\n",
        E05_CSV + '"unterminated,quoted\n',
    ]
    out["odd"] = [_batch_json(e05.parse_csv(t)) for t in odd]
    out["invalid_utf8"] = _batch_json(e05.parse_csv(b"\xff\xfe\x00"))
    return out


def _e05_publish(csv_text=E05_CSV, version="e05-test-v1", previous=None):
    from auto_repair_engine import e05
    return e05.human_publish(e05.parse_csv(csv_text), "fixture_reviewer", "fixture approval reason", version,
                             "2026-10-11T00:00:00+00:00", "person_hour",
                             "架空の整備作業範囲。含有運搬を除き、承認済み作業行を人時で集計する", previous)


def _pack_json(pack):
    return {"engine_id": pack.engine_id, "rule_version": pack.rule_version, "effective_from": pack.effective_from, "source": pack.source,
            "basis_unit": pack.basis_unit, "basis_definition": pack.basis_definition, "import_hash": pack.import_hash,
            "snapshot_hash": pack.snapshot_hash, "approved_by": pack.approved_by, "approval_reason": pack.approval_reason,
            "rules": [r.__dict__ for r in pack.rules], "audit": [a.__dict__ for a in pack.audit]}


@script
def e05_publish_flow():
    from auto_repair_engine import e05
    out = {}
    scenario = APPROVED()
    baseline_pack = _e05_publish(version="e05-baseline-test-v1")
    out["baseline_pack"] = _pack_json(baseline_pack)
    scenario["rule_version"] = baseline_pack.rule_version
    out["baseline"] = e05.run(copy.deepcopy(scenario), baseline_pack)
    changed_csv = E05_CSV.replace("1.7,1.7,1.7", "2.0,2.0,2.0")
    next_pack = _e05_publish(changed_csv, "e05-changed-test-v1", previous=baseline_pack)
    out["next_pack"] = _pack_json(next_pack)
    out["replay"] = e05.run(copy.deepcopy(scenario), baseline_pack)
    changed_scenario = copy.deepcopy(scenario)
    changed_scenario["rule_version"] = next_pack.rule_version
    out["changed"] = e05.run(changed_scenario, next_pack)
    attr_csv = E05_CSV.replace("front_brake_service,base_service,work_scope,front_brake_service,", "other,base_service,work_scope,front_brake_service,")
    out["attr_preview"] = e05.preview_diff(e05.parse_csv(attr_csv), baseline_pack)
    out["attr_pack"] = _pack_json(_e05_publish(attr_csv, "e05-attr-next-test-v1", previous=baseline_pack))
    out["source_preview"] = e05.preview_diff(e05.parse_csv(E05_CSV.replace("fixture:base", "fixture:base-v2")), baseline_pack)
    wrong = copy.deepcopy(scenario)
    wrong["rule_version"] = "different-version"
    out["version_gate"] = e05.run(wrong, baseline_pack)
    from dataclasses import replace
    forged = replace(baseline_pack, import_hash="f" * 64, snapshot_hash="a" * 64, audit=())
    out["forged"] = e05.run(copy.deepcopy(scenario), forged)
    errs = {}
    for name, call in {
        "actor": lambda: e05.human_publish(e05.parse_csv(E05_CSV), " ", "reason", "v", "today", "person_hour", "fixture"),
        "reason": lambda: e05.human_publish(e05.parse_csv(E05_CSV), "reviewer", " ", "v", "today", "person_hour", "fixture"),
        "version": lambda: e05.human_publish(e05.parse_csv(E05_CSV), "reviewer", "r", " ", "today", "person_hour", "fixture"),
        "effective": lambda: e05.human_publish(e05.parse_csv(E05_CSV), "reviewer", "r", "v", "", "person_hour", "fixture"),
        "basis": lambda: e05.human_publish(e05.parse_csv(E05_CSV), "reviewer", "r", "v", "today", "", "fixture"),
        "invalid": lambda: _e05_publish(E05_CSV.replace("parts_wait_stock_checked,true,", "parts_wait_stock_checked,perhaps,"), "e05-invalid-boolean-test-v1"),
        "immutable": lambda: _e05_publish(E05_CSV.replace("1.7,1.7,1.7", "1.8,1.8,1.8"), baseline_pack.rule_version),
    }.items():
        try:
            call()
            errs[name] = None
        except ValueError as exc:
            errs[name] = str(exc)
    out["errors"] = errs
    out["same_again"] = _pack_json(_e05_publish(version="e05-baseline-test-v1"))
    return out


def _e06_fixture_pack():
    from auto_repair_engine.e06 import publish_rule_pack
    scenario = COMMON()
    pack = {
        "engine_id": "e06_approval_rules", "rule_version": "fictional-e06-test-v1",
        "source": "fixture", "basis_unit": scenario["basis_unit"],
        "basis_definition": scenario["basis_definition"], "rules": [
            {"job_id": "front_brake_service", "operation_key": key, "condition": condition,
             "hours": hours, "unit": unit, "source": "fixture:" + key}
            for key, condition, hours, unit in (
                ("base_service", {"field": "work_scope", "equals": "front_brake_service"}, {"low": 1.7, "typical": 1.7, "high": 1.7}, "person_hours"),
                ("replacement_carry", {"field": "included_operations", "contains": "remove_install"}, {"low": .2, "typical": .2, "high": .2}, "person_hours"),
                ("snow_melt", {"field": "included_operations", "contains": "snow_removal"}, {"low": .5, "typical": .5, "high": .5}, "elapsed_hours"),
                ("penetrant_wait", {"field": "work_scope", "equals": "front_brake_service"}, {"low": .25, "typical": .25, "high": .25}, "elapsed_hours"),
                ("parts_wait", {"field": "parts_wait_stock_checked", "equals": True}, {"low": 0, "typical": 0, "high": 0}, "elapsed_hours"),
                ("wash", {"field": "work_scope", "equals": "front_brake_service"}, {"low": .1, "typical": .1, "high": .1}, "person_hours"),
                ("rotor_seizure", {"field": "rotor_relevance", "equals": "relevant"}, {"low": 0, "typical": .25, "high": .5}, "person_hours"),
            )
        ]}
    return publish_rule_pack(pack, "fictional_reviewer", "fixture rules approved", "2026-10-11", previous=None)


@script
def e06_lifecycle():
    from auto_repair_engine import e06
    out = {}
    scenario = APPROVED()
    out["default"] = e06.run(copy.deepcopy(scenario))
    pack = _e06_fixture_pack()
    out["pack"] = pack
    changed_payload = copy.deepcopy(pack)
    changed_payload["rule_version"] = "fictional-rule-v2"
    base = next(r for r in changed_payload["rules"] if r["operation_key"] == "base_service")
    base["hours"] = {"low": 1.9, "typical": 1.9, "high": 1.9}
    changed_payload.pop("payload_hash")
    changed = e06.publish_rule_pack(changed_payload, "reviewer_2", "approved revised labor", "2026-10-11", previous=pack)
    out["changed_pack"] = changed
    cs = copy.deepcopy(scenario)
    cs["rule_version"] = changed["rule_version"]
    out["revised"] = e06.run(cs, changed)
    s2 = copy.deepcopy(scenario)
    s2["rule_version"] = pack["rule_version"]
    stops = []
    for mutate in (lambda p: p.update(status="draft"), lambda p: p.pop("payload_hash"), lambda p: p["rules"][0]["hours"].update(typical=99)):
        bad = copy.deepcopy(pack)
        mutate(bad)
        stops.append(e06.run(copy.deepcopy(s2), bad))
    out["stops"] = stops
    future_payload = copy.deepcopy(pack)
    future_payload.pop("payload_hash")
    future_payload["rule_version"] = "fictional-e06-future-v1"
    future = e06.publish_rule_pack(future_payload, "reviewer", "scheduled future approval", "2027-01-01", previous=pack)
    out["future"] = e06.run(copy.deepcopy(s2), future)
    wrong = copy.deepcopy(s2)
    wrong["rule_version"] = "unpublished-v99"
    out["mismatch"] = e06.run(wrong, pack)
    forged = copy.deepcopy(pack)
    forged["rules"][0]["hours"] = {"low": 8, "typical": 8, "high": 8}
    forged["payload_hash"] = e06.payload_hash(forged)
    out["forged"] = e06.run(copy.deepcopy(s2), forged)
    revised_payload = copy.deepcopy(pack)
    revised_payload.pop("payload_hash")
    revised_payload["rule_version"] = "fictional-e06-condition-v2"
    target = next(r for r in revised_payload["rules"] if r["operation_key"] == "base_service")
    target["condition"] = {"field": "work_scope", "equals": "different_job"}
    revised = e06.publish_rule_pack(revised_payload, "reviewer_3", "narrow rule applicability", "2026-10-11", previous=pack)
    out["condition_pack"] = revised
    s3 = copy.deepcopy(s2)
    s3["rule_version"] = revised["rule_version"]
    out["condition_run"] = e06.run(s3, revised)
    attrs_payload = copy.deepcopy(pack)
    attrs_payload.pop("payload_hash")
    attrs_payload["rule_version"] = "fictional-e06-pack-attrs-v2"
    attrs_payload["source"] = "fixture:reviewed-source"
    attrs_payload["basis_definition"] = "Revised fictional person-hour basis."
    out["attrs_pack"] = e06.publish_rule_pack(attrs_payload, "reviewer_3", "clarify pack basis", "2026-10-12", previous=pack)
    errs = {}
    changed2 = copy.deepcopy(pack)
    changed2["rules"][0]["hours"] = {"low": 2, "typical": 2, "high": 2}
    for name, call in {
        "immutable": lambda: e06.publish_rule_pack(changed2, "reviewer", "another change", "2026-10-11"),
        "empty": lambda: e06.publish_rule_pack({"engine_id": e06.ENGINE_ID, "rule_version": "fictional-e06-empty-v1", "rules": []}, "reviewer", "r", "2026-10-11"),
        "actor": lambda: e06.publish_rule_pack(pack, " ", "r", "2026-10-11"),
        "reason": lambda: e06.publish_rule_pack(pack, "a", "", "2026-10-11"),
        "date": lambda: e06.publish_rule_pack(pack, "a", "r", "20261011x"),
        "date_type": lambda: e06.publish_rule_pack(pack, "a", "r", 5),
        "payload": lambda: e06.publish_rule_pack([], "a", "r", "2026-10-11"),
        "version": lambda: e06.publish_rule_pack({"rules": [1]}, "a", "r", "2026-10-11"),
        "mixed_keys": lambda: e06.publish_rule_pack({"rule_version": "mix", "rules": [{"x": 1}, {"operation_key": "a"}]}, "a", "r", "2026-10-11"),
    }.items():
        try:
            call()
            errs[name] = None
        except Exception as exc:  # noqa: BLE001
            errs[name] = [type(exc).__name__, str(exc)]
    out["errors"] = errs
    out["date_formats"] = {d: _date_ok(d) for d in ("2026-10-11", "20261011", "2026-W41-7", "2026W417", "2026-W41", "2026-02-30", "2026-13-01", "0000-01-01", "2026-W54-1", "2020-W53-1", "2021-W53-1", "abc", "")}
    return out


@script
def e11_flows():
    from auto_repair_engine import e11
    out = {}
    scenario = APPROVED()
    comparison = e11.compare_methods(scenario)
    out["comparison"] = comparison
    out["chosen_a"] = e11.select_method(comparison, "A", "reviewer", "根拠の適用範囲を確認した")
    out["chosen_b"] = e11.select_method(comparison, "B", "reviewer", "ok")
    tampered = copy.deepcopy(comparison)
    tampered["runs"][1]["labor"]["person_hours"] = {"low": 8, "typical": 8, "high": 8}
    out["tampered"] = e11.select_method(tampered, "B", "human", "independently chose this run")
    out["no_actor"] = e11.select_method(comparison, "B", "", "why")
    cleared = copy.deepcopy(comparison)
    cleared["runs"][1]["labor"]["breakdown"].clear()
    out["cleared"] = e11.select_method(cleared, "B", "human", "verified")
    fresh = e11.compare_methods(scenario)
    out["input_binding"] = e11.select_method(fresh, "A", "human", "verified", {**scenario, "person_count": 999})
    out["same_input"] = e11.select_method(fresh, "A", "human", "verified", scenario)
    out["wrong_version"] = e11.select_method(fresh, "A", "human", "verified", scenario, "wrong-version")
    out["absent"] = e11.select_method(comparison, "missing", "human", "reason")
    incomplete = copy.deepcopy(comparison)
    incomplete["runs"][0]["unknowns"] = ["evidence:missing"]
    incomplete["comparison_hash"] = e11._hash({k: v for k, v in incomplete.items() if k != "comparison_hash"})
    out["incomplete"] = e11.select_method(incomplete, "A", "human", "reason")
    out["not_obj"] = e11.select_method([], "A", "h", "r")
    out["no_runs"] = e11.select_method({"runs": 5}, "A", "h", "r")
    bad_version = copy.deepcopy(comparison)
    bad_version["runs"][1]["rule_version"] = "x"
    bad_version["comparison_hash"] = e11._hash({k: v for k, v in bad_version.items() if k != "comparison_hash"})
    out["selected_result_tampered"] = e11.select_method(bad_version, "B", "h", "r")
    out["with_version"] = e11.compare_methods(scenario, ["A", "B", "S05", "ZZ"], "fixture-r7")
    out["bad_methods"] = [e11.compare_methods(scenario, m) for m in ("AB", [], ["A", "A"], [5], [""])]
    return out


def _e13_extras():
    from auto_repair_engine import e13

    def ans(value, actor="fictional_owner", source="fictional_observation", confirmed_at="2026-10-11T00:00:00+00:00"):
        return {"value": value, "confirmed": True, "actor": actor, "source": source, "confirmed_at": confirmed_at}

    width = {"low": 0.0, "typical": 0.25, "high": 0.5}
    s = COMMON()
    s["fields"].pop("subframe_relevance")
    extra("e13", "subframe_missing", None, s)
    s = COMMON()
    s["fields"]["rotor_relevance"] = {"value": None, "status": "unknown"}
    extra("e13", "rotor_unknown", None, s)
    s = COMMON()
    s["fields"]["rotor_relevance"] = {"value": "relevant", "status": "confirmed"}
    extra("e13", "relevant_without_width", None, s)
    s = APPROVED()
    s["fields"] = []
    extra("e13", "fields_list", None, s)
    extra("e13", "custom_schema_pack", {"form_schemas": {"front_brake_service": [{"field": "work_scope", "choices": ["x"], "required": True}]}, "schema_version": "v9"})
    d = lambda *a: e13.apply_answers(*a)  # noqa: E731
    base = COMMON()
    unit("e13.render_form", e13.render_form, base)
    unit("e13.render_form", e13.render_form, APPROVED())
    unit("e13.render_form", e13.render_form, 5)
    unit("e13.build_schema", e13.build_schema, "fictional_job", {"form_schemas": {"fictional_job": [{"field": "f", "choices": ["x"]}]}, "schema_version": "pack-v2"})
    unit("e13.build_schema", e13.build_schema, None)
    unit("e13.build_schema", e13.build_schema, "front_brake_service")
    unit("e13.apply_answers", d, base, {"rotor_relevance": ans("relevant"), "rotor_seizure_hours": ans(width)})
    unit("e13.apply_answers", d, base, {"rotor_seizure_hours": ans(width), "rotor_relevance": ans("relevant")})
    unit("e13.apply_answers", d, base, {"rotor_relevance": ans("maybe")})
    unit("e13.apply_answers", d, base, {"rotor_relevance": {"value": "unknown", "status": "unknown"}})
    unit("e13.apply_answers", d, base, {"rotor_relevance": {"value": "unknown", "status": "unknown", "confirmed": True, "actor": "reviewer", "source": "inspection", "confirmed_at": "2026-10-11"}})
    unit("e13.apply_answers", d, base, {"parts_wait_stock_checked": ans(False)})
    unit("e13.apply_answers", d, base, {"rotor_seizure_hours": ans(width)})
    unit("e13.apply_answers", d, base, {"rotor_relevance": {"value": "relevant", "confirmed": True}})
    unit("e13.apply_answers", d, base, {"rotor_relevance": ans("relevant", confirmed_at="bad-date")})
    unit("e13.apply_answers", d, base, {"rotor_relevance": ans("relevant", confirmed_at="")})
    unit("e13.apply_answers", d, base, {"nope": ans(1), "work_scope": 5})
    unit("e13.apply_answers", d, base, {"included_operations": ans(["remove_install", "remove_install"])})
    unit("e13.apply_answers", d, base, {"included_operations": ans(["remove_install", "snow_removal"])})
    unit("e13.apply_answers", d, base, {"rotor_relevance": ans("relevant"), "rotor_seizure_hours": ans({"low": 1, "typical": 0, "high": 2})})
    unit("e13.apply_answers", d, base, {"rotor_relevance": ans("relevant"), "rotor_seizure_hours": dict(ans(width), reason="because")})
    unit("e13.apply_answers", d, base, [1])
    unit("e13.apply_answers", d, dict(base, fields=None), {"a": 1})
    unit("e13.apply_answers", d, {"job_id": "front_brake_service"}, {"work_scope": ans("front_brake_service")})
    unit("e13.apply_answers", d, 5, {})


_e13_extras()


def _e19_to_e23_extras():
    # E19: 左右の観測
    s = APPROVED()
    s["operations"].append({"operation_id": "align", "operation": "align", "hours": 0.5, "side": "left", "person_count": 1})
    s["operations"].append({"operation_id": "align", "operation": "align", "hours": 0.75, "side": "right", "person_count": 1})
    s["operations"].append({"operation_id": "toe", "operation": "toe", "hours": 0.2, "side": "left"})
    s["operations"].append({"operation_id": "bolt", "operation": "bolt", "hours": None, "side": "left"})
    s["operations"].append({"operation_id": "bolt", "operation": "bolt", "hours": 0.3, "side": "right"})
    s["operations"].append({"operation_id": "flag", "hours": True, "side": "left"})
    s["operations"].append({"operation_id": "flag", "hours": 0.1, "side": "right"})
    s["operations"].append({"operation_id": 5, "hours": 0.1, "side": "right"})
    s["operations"].append({"operation_id": "center", "hours": 0.1, "side": "center"})
    extra("e19", "sides", None, s)
    s2 = APPROVED()
    s2["operations"].append({"operation_id": "x", "side": ["left"]})
    extra("e19", "side_unhashable", None, s2)
    s3 = APPROVED()
    s3["operations"] = "x"
    extra("e19", "ops_not_list", None, s3)
    extra("e19", "with_pack", {"anything": 1}, APPROVED())
    # E20: what-if
    extra("e20", "empty_hypothesis", {"hypothesis": {}})
    extra("e20", "wash_longer", {"hypothesis": {"actor": "owner", "reason": "what if", "operations": [{"operation_id": "wash", "hours": 0.4}]}})
    extra("e20", "two_changes", {"hypothesis": {"actor": "owner", "reason": "r", "operations": [{"operation_id": "wash", "hours": 0.4}, {"operation_id": "snow_melt", "elapsed_hours": 1.0, "extra": [1]}]}})
    extra("e20", "no_actor", {"hypothesis": {"reason": "r", "operations": [{"operation_id": "wash", "hours": 0.4}]}})
    extra("e20", "unknown_op", {"hypothesis": {"actor": "a", "reason": "r", "operations": [{"operation_id": "nope"}]}})
    extra("e20", "bad_change", {"hypothesis": {"actor": "a", "reason": "r", "operations": [5]}})
    extra("e20", "ops_not_list", {"hypothesis": {"operations": "x"}})
    extra("e20", "pack_not_dict", ["x"])
    extra("e20", "pack_no_hypothesis", {"other": 1})
    # E21: 証拠付きの追加
    approval = {"actor": "owner", "reason": "evidence reviewed", "old_value": None,
                "new_value": {"hours": 0.5, "unit": "person_hour", "source": "fictional_photo"}, "rule_version": "e21-evidence-additions-v1"}
    good = {"operation_id": "extra_clean", "unit": "person_hour", "hours": 0.5, "source": "fictional_photo", "old_value": None, "approval": approval}
    extra("e21", "one_good", {"additions": [good]})
    extra("e21", "two_good", {"additions": [good, dict(good, operation_id="extra_2", hours=0.25, approval=dict(approval, new_value={"hours": 0.25, "unit": "person_hour", "source": "fictional_photo"}))]})
    extra("e21", "no_approval", {"additions": [dict(good, approval=None)]})
    extra("e21", "wrong_version", {"additions": [dict(good, approval=dict(approval, rule_version="x"))]})
    extra("e21", "bad_hours", {"additions": [dict(good, hours=-1), dict(good, hours=True), dict(good, hours="1")]})
    extra("e21", "bad_unit_source", {"additions": [dict(good, unit="hour", source=" ", operation_id="")]})
    extra("e21", "not_dict_item", {"additions": [5]})
    extra("e21", "additions_not_list", {"additions": "x"})
    extra("e21", "pack_not_dict", ["x"])
    extra("e21", "existing_op_old_value", {"additions": [dict(good, operation_id="wash", old_value=0.1, approval=dict(approval, old_value=0.1))]})
    extra("e21", "existing_op_wrong_old", {"additions": [dict(good, operation_id="wash", old_value=0.2)]})
    extra("e21", "new_with_old", {"additions": [dict(good, old_value=1.0)]})
    extra("e21", "on_unresolved", {"additions": [good]}, COMMON())
    extra("e21", "empty", {})
    # E22: 実績の結合
    steps = [{"operation_id": "base_service", "unit": "person_hour", "person_count": 1, "duration_hours": 1.58},
             {"operation_id": "replacement_carry", "unit": "person_hour", "person_count": 2, "duration_hours": 0.1},
             {"operation_id": "wash", "unit": "person_hour", "person_count": 1, "duration_hours": 0.1},
             {"operation_id": "rotor_seizure", "unit": "person_hour", "person_count": 1, "duration_hours": 0.25},
             {"operation_id": "snow_melt", "unit": "elapsed_hours", "duration_hours": 0.5},
             {"is_wait": True}]
    base = {"scope_id": "front_brake_service", "rule_version": "fictional-rule-v1", "actual_steps": steps}
    extra("e22", "complete", base)
    extra("e22", "missing_step", dict(base, actual_steps=steps[:2]))
    extra("e22", "unknown_op", dict(base, actual_steps=steps + [{"operation_id": "zzz", "unit": "person_hour", "person_count": 1, "duration_hours": 1}]))
    extra("e22", "bad_steps", dict(base, actual_steps=[5, {"unit": "person_hour"}, {"operation_id": "wash", "unit": "person_hour", "person_count": 0, "duration_hours": 1},
                                                      {"operation_id": "wash", "unit": "person_hour", "person_count": 1, "duration_hours": -1},
                                                      {"operation_id": "wash", "unit": "person_hour", "person_count": True, "duration_hours": 1}]))
    extra("e22", "scope_mismatch", dict(base, scope_id="other"))
    extra("e22", "version_mismatch", dict(base, rule_version="other"))
    extra("e22", "steps_not_list", dict(base, actual_steps="x"))
    extra("e22", "no_pack", None)
    extra("e22", "pack_list", ["x"])
    extra("e22", "common_incomplete", base, COMMON())
    # E23: 参照バケット
    def sample(i, op="wash", cond="dry", hours=0.1):
        return {"sample_id": f"s{i}", "operation_id": op, "unit": "person_hour", "condition": cond, "hours": hours}
    extra("e23", "five_samples", {"samples": [sample(i, hours=0.1 * i) for i in range(1, 6)]})
    extra("e23", "few_samples", {"samples": [sample(1), sample(2, hours=0.3), sample(3, "base_service", "wet", 1.5), sample(4, "base_service", "wet", 2)]})
    extra("e23", "min_samples_2", {"minimum_samples": 2, "samples": [sample(1), sample(2, hours=0.3)]})
    extra("e23", "bad_min", {"minimum_samples": 0, "samples": [sample(1)]})
    extra("e23", "bool_min", {"minimum_samples": True})
    extra("e23", "bad_samples", {"samples": [5, dict(sample(1), unit="elapsed"), dict(sample(2), hours=True), dict(sample(3), hours=-1), {"sample_id": "x"}, sample(4), sample(4)]})
    extra("e23", "samples_not_list", {"samples": "x"})
    extra("e23", "pack_not_dict", ["x"])
    extra("e23", "no_pack", None)
    extra("e23", "ints", {"samples": [sample(1, hours=2), sample(2, hours=4), sample(3, hours=7)]})
    from auto_repair_engine import e23
    unit("e23.summarize_buckets", e23.summarize_buckets, [sample(i, hours=h) for i, h in enumerate([1, 2, 3, 4], 1)], 3)
    unit("e23.summarize_buckets", e23.summarize_buckets, [sample(1, "b", "x", 1.5), sample(2, "a", "y", 2.5), sample(3, "a", "x", 0.1)])
    unit("e23.summarize_buckets", e23.summarize_buckets, [])
    unit("e23.summarize_buckets", e23.summarize_buckets, [{"operation_id": "a"}])


_e19_to_e23_extras()


def _e18_extras():
    from auto_repair_engine import e18
    extra("e18", "with_pack", {"x": 1})
    extra("e18", "with_empty_pack", {})
    s = APPROVED()
    s.pop("rule_version")
    extra("e18", "no_version", None, s)
    s = APPROVED()
    for o in s["operations"]:
        o.pop("source", None)
    extra("e18", "no_sources", None, s)
    s = APPROVED()
    s["fields"]["subframe_relevance"]["status"] = "unknown"
    extra("e18", "subframe_unknown", None, s)
    s = APPROVED()
    op(s, "snow_melt")["elapsed_hours"] = None
    extra("e18", "snow_unknown", None, s)
    s = APPROVED()
    s["fields"] = []
    extra("e18", "fields_list", None, s)
    scenario = APPROVED()
    tree = e18.build_trace_tree(scenario)
    unit("e18.build_trace_tree", e18.build_trace_tree, scenario)
    unit("e18.build_trace_tree", e18.build_trace_tree, scenario, "pinned-v9")
    unit("e18.build_trace_tree", e18.build_trace_tree, COMMON())
    unit("e18.build_trace_tree", e18.build_trace_tree, 5)
    unit("e18.evaluate_tree", e18.evaluate_tree, tree)
    unit("e18.evaluate_tree", e18.evaluate_tree, {"rule": "sum_children", "children": []})
    unit("e18.evaluate_tree", e18.evaluate_tree, {"rule": "sum_children"})
    unit("e18.evaluate_tree", e18.evaluate_tree, [])
    unit("e18.evaluate_tree", e18.evaluate_tree, {"rule": "operation_contribution", "children": [], "result": {"person_hours": {"low": 1, "typical": 1, "high": 1}, "elapsed_hours": {"low": None, "typical": None, "high": None}}})
    unit("e18.evaluate_tree", e18.evaluate_tree, {"rule": "operation_contribution", "children": [], "result": {"person_hours": {"low": 2, "typical": 1, "high": 1}, "elapsed_hours": {"low": None, "typical": None, "high": None}}})
    unit("e18.evaluate_tree", e18.evaluate_tree, {"rule": "sum_children", "children": [{"rule": "operation_contribution", "children": [], "result": {"person_hours": {"low": 0.1, "typical": 0.2, "high": 0.3}, "elapsed_hours": {"low": 0.1, "typical": 0.2, "high": 0.3}}}] * 3})


_e18_extras()


@script
def e18_inspect():
    """トレースの入力ハッシュは言語ごとに値が違うため、木はそれぞれの言語で作ってから改ざんして検査する。"""
    from auto_repair_engine import e18
    scenario = APPROVED()
    tree = e18.build_trace_tree(scenario)
    out = {"tree": tree, "ok": e18.inspect_trace(tree, scenario), "no_scenario": e18.inspect_trace(tree),
           "other_scenario": e18.inspect_trace(tree, dict(scenario, person_count=9)),
           "not_dict": e18.inspect_trace(5), "wrong_root": e18.inspect_trace({"rule": "sum_children"})}
    t = copy.deepcopy(tree)
    t["children"][0]["result"]["person_hours"]["typical"] = 99
    out["leaf_changed"] = e18.inspect_trace(t, scenario)
    t = copy.deepcopy(tree)
    t["children"][1]["node_id"] = t["children"][0]["node_id"]
    t["children"][2]["rule_version"] = "x"
    t["children"][3]["input_hash"] = "x"
    t["children"][4]["input_refs"] = 5
    t["children"][5]["input_refs"] = [{"path": "/nope", "value": 1}, {"path": "x"}, {"path": "/operations/99"}, 5]
    out["many_issues"] = e18.inspect_trace(t, scenario)
    t = copy.deepcopy(tree)
    t["children"][0]["children"] = [1]
    out["leaf_with_children"] = e18.inspect_trace(t, scenario)
    t = copy.deepcopy(tree)
    t["children"][0]["rule"] = "weird"
    t["children"][1]["result"] = 5
    t["audit_expected"] = None
    out["weird_rule"] = e18.inspect_trace(t)
    t = copy.deepcopy(tree)
    t["children"].append(5)
    t["input_hash"] = "short"
    out["short_hash"] = e18.inspect_trace(t, scenario)
    return out


def _e17_extras():
    from auto_repair_engine import e17
    fixture = e17._fixture_events()
    app = e17.append_observation_event
    extended = app(fixture, "rotor_relevance", "relevant", "tech", "confirmed on current visit", "2026-10-11T12:00:00+09:00", "rotor-revision", "fixture-01")
    extended = app(extended, "rotor_seizure_hours", {"low": 0, "typical": .25, "high": .5}, "owner", "approved condition width", "2026-10-11T12:01:00+09:00", "rotor-range")
    version = "fictional-rule-v1"
    extra("e17", "fixture_events", {"engine_id": e17.ENGINE_ID, "rule_version": version, "events": fixture})
    extra("e17", "extended_events", {"engine_id": e17.ENGINE_ID, "rule_version": version, "events": extended})
    extra("e17", "extended_unversioned", {"events": extended}, COMMON())
    pending = app([], "rotor_relevance", "unrelated", "", "", "", "pending-1", status="pending")
    extra("e17", "pending_only", {"events": pending}, COMMON())
    extra("e17", "no_events_key", {}, COMMON())
    extra("e17", "events_none", {"events": None}, COMMON())
    extra("e17", "events_not_list", {"events": "x"}, COMMON())
    extra("e17", "events_nondict", {"events": [5]}, COMMON())
    extra("e17", "empty_events", {"events": []}, COMMON())
    extra("e17", "pack_not_dict", ["x"], COMMON())
    extra("e17", "pack_unknown", {"events": fixture, "x": 1, "engine_id": "z", "rule_version": "v9"}, COMMON())
    audit = {"actor": "fixture", "reason": "cycle probe", "observed_at": "2026-10-11T00:00:00Z", "source": "fictional"}
    a = {"id": "a", "target": "rotor_relevance", "value": "unrelated", "supersedes": "b", "status": "confirmed", **audit}
    b = {"id": "b", "target": "rotor_relevance", "value": "relevant", "supersedes": "a", "status": "confirmed", **audit}
    extra("e17", "cycle", {"events": [a, b]}, COMMON())
    event = {"id": "a", "target": "rotor_relevance", "value": "unrelated", "supersedes": None, "actor": "tech", "reason": "checked", "observed_at": "2026-10-11T00:00:00Z", "source": "fixture", "status": "confirmed"}
    extra("e17", "fork", {"events": [event, dict(event, id="b", value="relevant"), dict(event, id="c", value="relevant")]}, COMMON())
    extra("e17", "target_mismatch", {"events": [event, dict(event, id="b", target="parts_wait_stock_checked", value=True, supersedes="a")]}, COMMON())
    extra("e17", "unknown_supersedes", {"events": [dict(event, supersedes="zzz")]}, COMMON())
    extra("e17", "supersedes_list", {"events": [dict(event, supersedes=["a"])]}, COMMON())
    extra("e17", "target_list", {"events": [dict(event, target=["a"])]}, COMMON())
    extra("e17", "status_list", {"events": [dict(event, status=["a"])]}, COMMON())
    extra("e17", "value_list", {"events": [dict(event, value=["a"])]}, COMMON())
    extra("e17", "raw_unaudited", {"events": [dict(event, actor="", reason="", observed_at="", source="")]}, COMMON())
    extra("e17", "bad_value", {"events": [dict(event, value="maybe")]}, COMMON())
    extra("e17", "bad_date", {"events": [dict(event, observed_at="yesterday")]}, COMMON())
    extra("e17", "dup_id", {"events": [event, event]}, COMMON())
    extra("e17", "chain_ok", {"events": [event, dict(event, id="b", value="relevant", supersedes="a"), dict(event, id="s1", target="rotor_seizure_hours", value={"low": 0, "typical": 0.1, "high": 0.2})]}, APPROVED())
    extra("e17", "snow_absent", {"events": fixture[:3] + [dict(fixture[3], value="absent")]}, APPROVED())
    extra("e17", "stock_false", {"events": fixture[:2] + [dict(fixture[2], value=False)] + fixture[3:]}, APPROVED())
    s = APPROVED()
    s["fields"] = []
    extra("e17", "fields_list", {"events": fixture}, s)
    s = COMMON()
    s["operations"] = [o for o in s["operations"] if o["operation_id"] != "parts_wait"] + [
        {"operation_id": "parts_wait", "operation": "parts_wait", "hours": None, "elapsed_hours": None, "person_count": 0, "status": "wait", "stock_checked": False}]
    extra("e17", "parts_wait_null", {"events": fixture}, s)
    unit("e17.reduce_observations", e17.reduce_observations, fixture)
    unit("e17.reduce_observations", e17.reduce_observations, extended)
    unit("e17.reduce_observations", e17.reduce_observations, [])
    unit("e17.reduce_observations", e17.reduce_observations, "x")
    unit("e17.reduce_observations", e17.reduce_observations, [{"id": "r"}])
    unit("e17.reduce_observations", e17.reduce_observations, [dict(event, target=["a"])])
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", "tech", "r", "2026-10-11T00:00:00Z", "e1")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", " tech ", " r ", "2026-10-11", " e1 ")
    unit("e17.append_observation_event", app, [event], "rotor_relevance", "relevant", "tech", "r", "2026-10-11T00:00:00Z", "a")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", "tech", "r", "2026-10-11T00:00:00Z", "b", "missing")
    unit("e17.append_observation_event", app, [event], "parts_wait_stock_checked", True, "tech", "r", "2026-10-11T00:00:00Z", "b", "a")
    unit("e17.append_observation_event", app, [], "nope", "relevant", "tech", "r", "2026-10-11T00:00:00Z", "b")
    unit("e17.append_observation_event", app, [], ["x"], "relevant", "tech", "r", "2026-10-11T00:00:00Z", "b")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", "tech", "r", "2026-10-11T00:00:00Z", " ")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", "tech", "r", "2026-10-11T00:00:00Z", "b", None, "weird")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", "", "r", "2026-10-11T00:00:00Z", "b")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", "tech", "r", "never", "b")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "relevant", "tech", "r", "2026-10-11T00:00:00Z", "b", None, "confirmed", " ")
    unit("e17.append_observation_event", app, [], "rotor_relevance", "maybe", "tech", "r", "2026-10-11T00:00:00Z", "b")
    unit("e17.append_observation_event", app, [], "rotor_seizure_hours", {"low": 0, "typical": 1, "high": 2}, "tech", "r", "2026-10-11T00:00:00Z", "b")
    unit("e17.append_observation_event", app, [], "rotor_seizure_hours", {"low": 3, "typical": 1, "high": 2}, "tech", "r", "2026-10-11T00:00:00Z", "b")
    unit("e17.append_observation_event", app, [], "parts_wait_stock_checked", 1, "tech", "r", "2026-10-11T00:00:00Z", "b")
    unit("e17.append_observation_event", app, [], "snow_observation", "present", None, None, None, "b", None, "pending")
    unit("e17.append_observation_event", app, 5, "snow_observation", "present", "a", "b", "2026-10-11T00:00:00Z", "b")


_e17_extras()


def _e16_previous_visit():
    return {
        "visit_id": "visit-old", "vehicle_token": "veh_fictional_001", "job_id": "front_brake_service",
        "observed_at": "2026-10-01T10:00:00+09:00",
        "conditions": {
            "work_scope": {"value": "front_brake_service", "status": "confirmed"},
            "included_operations": {"value": ["remove_install", "rust_observation", "snow_removal"], "status": "confirmed"},
            "rotor_relevance": {"value": "relevant", "status": "confirmed"},
            "rotor_seizure_hours": {"value": {"low": 0.0, "typical": 0.25, "high": 0.5}, "status": "confirmed"},
            "parts_wait_stock_checked": {"value": True, "status": "confirmed"},
            "snow_observation": {"value": "present", "status": "confirmed"},
        },
    }


def _e16_scenario():
    scenario = COMMON()
    scenario["visit_id"] = "visit-current"
    scenario["observed_at"] = "2026-10-11T10:00:00+09:00"
    return scenario


def _e16_extras():
    from auto_repair_engine import e16
    pv = _e16_previous_visit
    confirms = [
        {"field": "rotor_relevance", "value": "relevant", "actor": "fictional_tech", "reason": "今訪問でローター固着を確認"},
        {"field": "rotor_seizure_hours", "value": {"low": 0.0, "typical": 0.25, "high": 0.5}, "actor": "fictional_owner", "reason": "今訪問の条件幅を承認"},
        {"field": "subframe_relevance", "value": "unrelated", "actor": "fictional_tech", "reason": "今訪問で確認"},
        {"field": "parts_wait_stock_checked", "value": True, "actor": "fictional_tech", "reason": "今訪問で在庫確認"},
        {"field": "snow_observation", "value": "present", "actor": "fictional_tech", "reason": "今訪問で雪を確認"},
    ]
    sc = _e16_scenario
    extra("e16", "no_confirms", {"previous_visit": pv()}, sc())
    extra("e16", "all_confirms", {"previous_visit": pv(), "current_confirm": confirms}, sc())
    extra("e16", "snow_absent", {"previous_visit": pv(), "current_confirm": confirms[:4] + [dict(confirms[4], value="absent")]}, sc())
    extra("e16", "rotor_unrelated", {"previous_visit": pv(), "current_confirm": [dict(confirms[0], value="unrelated"), confirms[2], confirms[3], confirms[4]]}, sc())
    extra("e16", "stock_false", {"previous_visit": pv(), "current_confirm": confirms[:3] + [dict(confirms[3], value=False), confirms[4]]}, sc())
    extra("e16", "bad_confirms", {"previous_visit": pv(), "current_confirm": [5, {"field": "nope"}, dict(confirms[0], value="maybe"), dict(confirms[1], value={"low": 2, "typical": 1, "high": 3}),
                                                                           dict(confirms[3], value="yes"), dict(confirms[4], value="x"), dict(confirms[0], actor=" "), dict(confirms[0], observed_at=" "),
                                                                           dict(confirms[0], value=["x"])]}, sc())
    extra("e16", "confirms_not_list", {"previous_visit": pv(), "current_confirm": "x"}, sc())
    extra("e16", "confirm_without_previous", {"current_confirm": confirms})
    extra("e16", "empty_pack", {})
    extra("e16", "pack_not_dict", ["x"])
    extra("e16", "pack_version", {"rule_version": "other", "previous_visit": pv()}, sc())
    extra("e16", "pack_unknown_key", {"x": 1})
    extra("e16", "pack_engine", {"engine_id": "z"})
    extra("e16", "pack_version_blank", {"rule_version": " "})
    bad_token = pv()
    bad_token["vehicle_token"] = "plate 1234"
    extra("e16", "bad_token", {"previous_visit": bad_token}, sc())
    no_time = pv()
    no_time.pop("observed_at")
    extra("e16", "no_time", {"previous_visit": no_time}, sc())
    extra("e16", "previous_not_dict", {"previous_visit": 5}, sc())
    s = sc()
    s.pop("visit_id")
    extra("e16", "no_visit_id", {"previous_visit": pv()}, s)
    s = sc()
    s["observed_at"] = " "
    extra("e16", "blank_observed", {"previous_visit": pv()}, s)
    s = sc()
    s["job_id"] = "other"
    extra("e16", "job_mismatch", {"previous_visit": pv()}, s)
    s = sc()
    s["job_id"] = None
    extra("e16", "job_none", {"previous_visit": pv(), "current_confirm": confirms}, s)
    s = sc()
    s["fields"] = []
    extra("e16", "fields_list", {"previous_visit": pv()}, s)
    s = sc()
    s["operations"] = {}
    extra("e16", "ops_dict", None, s)
    s = sc()
    s["operations"] = [5]
    extra("e16", "ops_nondict", None, s)
    s = sc()
    s["fields"] = []
    extra("e16", "fields_list_nopack", None, s)
    prev2 = pv()
    prev2["conditions"].pop("snow_observation")
    s = sc()
    s["fields"]["snow_observation"] = {"value": "present", "status": "confirmed"}
    extra("e16", "snow_in_scenario_only", {"previous_visit": prev2, "current_confirm": confirms[:4]}, s)
    s = sc()
    s["fields"]["rotor_relevance"] = {"value": None, "status": "unknown"}
    extra("e16", "unknown_in_scenario", {"previous_visit": pv(), "current_confirm": confirms}, s)

    visit = e16.copy_previous_visit(pv(), "visit-current", "2026-10-11T10:00:00+09:00")
    unit("e16.copy_previous_visit", e16.copy_previous_visit, pv(), "visit-current", "2026-10-11T10:00:00+09:00")
    unit("e16.copy_previous_visit", e16.copy_previous_visit, pv(), " cur ", " now ")
    unit("e16.copy_previous_visit", e16.copy_previous_visit, 5, "a", "b")
    unit("e16.copy_previous_visit", e16.copy_previous_visit, pv(), "", "b")
    unit("e16.copy_previous_visit", e16.copy_previous_visit, pv(), "a", None)
    unit("e16.copy_previous_visit", e16.copy_previous_visit, dict(pv(), vehicle_token="vehicle_abcd"), "a", "b")
    unit("e16.copy_previous_visit", e16.copy_previous_visit, dict(pv(), vehicle_token="veh_abc"), "a", "b")
    unit("e16.copy_previous_visit", e16.copy_previous_visit, dict(pv(), conditions=[]), "a", "b")
    cc = e16.current_confirm
    unit("e16.current_confirm", cc, visit, "rotor_relevance", "unrelated", "", "確認")
    unit("e16.current_confirm", cc, visit, "rotor_relevance", "unrelated", "tech", "確認")
    unit("e16.current_confirm", cc, visit, "rotor_relevance", "unrelated", "tech", "確認", "2026-10-12")
    unit("e16.current_confirm", cc, visit, "work_scope", "x", "tech", "確認")
    unit("e16.current_confirm", cc, visit, "rust_observation", "present", "tech", "確認")
    unit("e16.current_confirm", cc, None, "rust_observation", "present", "tech", "確認")
    unit("e16.current_confirm", cc, visit, "parts_wait_stock_checked", 1, "tech", "確認")
    unit("e16.current_confirm", cc, visit, "rotor_seizure_hours", {"low": 0, "typical": 0.1, "high": 0.2, "x": 1}, "tech", "確認")
    unit("e16.current_confirm", cc, visit, "rotor_seizure_hours", {"low": 0, "typical": 0.1, "high": 0.2}, "tech", "確認")
    unit("e16.current_confirm", cc, visit, "rotor_relevance", {"a": 1}, "tech", "確認")


_e16_extras()


def _e15_extras():
    from auto_repair_engine import e15
    texts = [
        "錆はない。ローターは固着している。雪あり", "錆がなくローターは固着", "錆じゃなく塗装の剥がれ", "錆ではなく塗装の剥がれ",
        "右前は錆なし、左前は錆あり", "左前は錆なし、左前は錆あり", "お客様の山田さん、来週の電話番号は...", "左か右のどちらかのローターが固着",
        "ローター固着なし", "錆あり", "錆なし", "", "   ", "雪も氷もない", "凍結してない", "左右ともさびあり", "両側のローターが固まっている",
        "ローター 左 固着 右 固着", "サビが見られない。雪が出ていない", "錆ありません。固着ず", "錆\nあり", "錆あり🙂雪なし", "🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂錆ない",
        "右の錆と左の雪", "左か右の雪、右の錆", "ローター固着していない。ローター固着あり", "x" * 2001, "錆" * 2000, 5, None, ["錆"],
    ]
    for text in texts:
        unit("e15.extract_candidates", e15.extract_candidates, text)
    for i, text in enumerate(texts[:12]):
        if isinstance(text, str):
            extra("e15", f"transcription_{i}", {"manual_transcription": text})
    for name, pack in {
        "pack_unknown_key": {"audio": "x", "manual_transcription": "錆あり"},
        "pack_engine": {"engine_id": "e02", "manual_transcription": "錆あり"},
        "pack_version_blank": {"rule_version": " ", "manual_transcription": "錆あり"},
        "pack_version_pin": {"rule_version": "other", "manual_transcription": "錆あり"},
        "pack_version_ok": {"rule_version": "fictional-rule-v1"},
        "pack_not_dict": ["x"],
        "pack_transcription_not_str": {"manual_transcription": 5},
        "pack_long": {"manual_transcription": "x" * 3000},
        "pack_no_tags": {"manual_transcription": "こんにちは"},
    }.items():
        extra("e15", name, pack)
    scenario = COMMON()
    scenario["fields"]["rust_observation"] = {"value": "unknown", "status": "unknown"}
    cands = e15.extract_candidates("右前は錆なし、左前は錆あり")["candidates"]
    conf = lambda *a, **k: e15.confirm_candidate(*a, **k)  # noqa: E731
    unit("e15.confirm_candidate", conf, scenario, cands[0], "owner", "right inspected")
    right = conf(scenario, cands[0], "owner", "right inspected")["scenario_input"]
    unit("e15.confirm_candidate", conf, right, cands[1], "owner", "left inspected")
    unit("e15.confirm_candidate", conf, scenario, cands[1], "", "x")
    unit("e15.confirm_candidate", conf, scenario, cands[1], "a", " ")
    unit("e15.confirm_candidate", conf, scenario, cands[1], "a", "b", "yes")
    unit("e15.confirm_candidate", conf, scenario, cands[1], "a", "b", False)
    unit("e15.confirm_candidate", conf, scenario, cands[1], "a", "b", True, "left")
    unit("e15.confirm_candidate", conf, 5, cands[1], "a", "b")
    unit("e15.confirm_candidate", conf, scenario, 5, "a", "b")
    unit("e15.confirm_candidate", conf, scenario, {"tag": "nope"}, "a", "b")
    unit("e15.confirm_candidate", conf, scenario, dict(cands[0], status="confirmed"), "a", "b")
    unit("e15.confirm_candidate", conf, scenario, dict(cands[0], side="up"), "a", "b")
    unit("e15.confirm_candidate", conf, scenario, dict(cands[0], candidate_id="bad"), "a", "b")
    unit("e15.confirm_candidate", conf, dict(scenario, fields=[]), cands[0], "a", "b")
    unit("e15.confirm_candidate", conf, dict(scenario, observations=5), cands[0], "a", "b")
    unit("e15.confirm_candidate", conf, dict(scenario, side_observations=5), cands[0], "a", "b")
    unit("e15.confirm_candidate", conf, dict(scenario, side_observations={"rust_observation": 5}), cands[0], "a", "b")
    conflict = e15.extract_candidates("左前は錆なし、左前は錆あり")["candidates"][0]
    unit("e15.confirm_candidate", conf, scenario, conflict, "owner", "inspect")
    unit("e15.confirm_candidate", conf, scenario, conflict, "owner", "inspect", True, None, "rust_present")
    unit("e15.confirm_candidate", conf, scenario, conflict, "owner", "inspect", True, None, "rotor_seized")
    unit("e15.confirm_candidate", conf, scenario, dict(conflict, alternatives=["rust_present", "rust_present"]), "o", "r", True, None, "rust_present")
    unit("e15.confirm_candidate", conf, scenario, dict(conflict, side="up"), "o", "r", True, None, "rust_present")
    side_amb = e15.extract_candidates("左か右のどちらかのローターが固着")["candidates"][0]
    unit("e15.confirm_candidate", conf, COMMON(), side_amb, "staff", "確認した")
    unit("e15.confirm_candidate", conf, COMMON(), side_amb, "staff", "右側を実車で確認", True, "right")
    unit("e15.confirm_candidate", conf, COMMON(), side_amb, "staff", "x", True, "up")
    unit("e15.confirm_candidate", conf, COMMON(), side_amb, "staff", "x", False, "left")
    rust = e15.extract_candidates("錆あり")["candidates"][0]
    first = conf(COMMON(), rust, "owner", "錆を見た")["scenario_input"]
    unit("e15.confirm_candidate", conf, first, e15.extract_candidates("錆なし")["candidates"][0], "owner", "再確認")
    sc2 = APPROVED()
    sc2["observations"] = [{"source": "e15_manual_voice", "candidate_id": "voice-1", "field": "f", "value": "v", "actor": "a", "reason": "r", "extra": 1}, 5]
    extra("e15", "observations_approvals", {"manual_transcription": "錆あり"}, sc2)


_e15_extras()


E14_STAMP = "2026-10-11T01:02:03+00:00"


def _e14_candidate(field="rotor_seizure_hours", value=None, candidate_id="cand_1"):
    if value is None:
        value = {"low": 0.0, "typical": 0.25, "high": 0.5}
    return {"candidate_id": candidate_id, "photo_ref": {"area": "brake", "id": "photo_01"},
            "ai_candidate": {"field": field, "value": copy.deepcopy(value)}}


def _e14_rotor_scenario():
    scenario = APPROVED()
    scenario["fields"].pop("rotor_seizure_hours")
    scenario["fields"]["rotor_relevance"] = {"value": "relevant", "status": "confirmed", "source": "fictional_fixture", "confirmed_at": E14_STAMP}
    scenario["metadata"].pop("approved_condition_widths", None)
    return scenario


@script
def e14_flows():
    from auto_repair_engine import e14
    out = {}
    out["default"] = e14.run(APPROVED())
    queued = e14.propose_candidates(_e14_rotor_scenario(), [_e14_candidate()])
    out["queued"] = queued
    out["run_queued"] = e14.run(queued)
    confirmed = e14.confirm_candidate(queued, "cand_1", "shop_owner", "visual check", E14_STAMP)
    out["confirmed"] = confirmed
    out["run_confirmed"] = e14.run(confirmed)
    modified = e14.modify_candidate(queued, "cand_1", {"low": 0.1, "typical": 0.3, "high": 0.6}, "shop_owner", "corrected by inspection", E14_STAMP)
    out["modified"] = modified
    out["run_modified"] = e14.run(modified)
    rejected = e14.reject_candidate(queued, "cand_1", "shop_owner", "not visible", E14_STAMP)
    out["rejected"] = rejected
    out["run_rejected"] = e14.run(rejected)
    two = e14.propose_candidates(_e14_rotor_scenario(), [_e14_candidate(), _e14_candidate("rotor_relevance", "relevant", "cand_2"), _e14_candidate("subframe_relevance", "unrelated", "cand_3")])
    two = e14.confirm_candidate(two, "cand_1", "a", "r", "2026-10-11T01:02:03Z")
    two = e14.reject_candidate(two, "cand_2", "b", "r2", E14_STAMP)
    two = e14.confirm_candidate(two, "cand_3", "c", "r3", "2026-10-11 09:00:00+09:00")
    out["multi"] = two
    out["run_multi"] = e14.run(two)
    tampered = copy.deepcopy(confirmed)
    tampered["photo_candidates"][0]["human_audit"]["reason"] = "changed"
    out["run_tampered_reason"] = e14.run(tampered)
    t2 = copy.deepcopy(confirmed)
    t2["fields"]["rotor_seizure_hours"]["value"]["high"] = 9
    out["run_tampered_field"] = e14.run(t2)
    t3 = copy.deepcopy(confirmed)
    t3["metadata"]["photo_candidate_audit_log"] = []
    out["run_log_missing"] = e14.run(t3)
    t4 = copy.deepcopy(confirmed)
    t4["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["actor"] = "x"
    out["run_tampered_approval"] = e14.run(t4)
    t5 = copy.deepcopy(confirmed)
    t5["photo_candidates"][0]["extra"] = 1
    t5["photo_candidates"].append(5)
    t5["photo_candidates"].append({"candidate_id": "bad id", "photo_ref": {"area": "A", "id": "x"}, "ai_candidate": {"field": "nope", "value": 1}, "status": "weird"})
    out["run_bad_candidates"] = e14.run(t5)
    out["run_candidates_not_list"] = e14.run(dict(APPROVED(), photo_candidates="x"))
    out["run_pending_with_audit"] = e14.run(dict(_e14_rotor_scenario(), photo_candidates=[dict(_e14_candidate(), human_audit={"a": 1})]))
    out["run_custom_pack"] = e14.run(queued, {"allowed_values": {"rotor_relevance": ["relevant"], "rotor_seizure_hours": "person_hour_range", "subframe_relevance": ["x", "x"]}})
    out["run_pack_ok"] = e14.run(APPROVED(), {"allowed_values": {"rotor_relevance": ["relevant"], "rotor_seizure_hours": "person_hour_range", "subframe_relevance": ["x"]}})
    out["run_pack_bad"] = [e14.run(APPROVED(), p) for p in ([], {"engine_id": "z", "rule_version": "q", "status": "d", "other": 1}, {"allowed_values": 5}, {"allowed_values": {"rotor_relevance": []}})]
    errs = {}
    cases = {
        "propose_type": lambda: e14.propose_candidates([], []),
        "propose_item": lambda: e14.propose_candidates({}, [5]),
        "propose_state": lambda: e14.propose_candidates({}, [dict(_e14_candidate(), status="approved")]),
        "propose_list": lambda: e14.propose_candidates({"photo_candidates": 5}, []),
        "confirm_again": lambda: e14.confirm_candidate(confirmed, "cand_1", "s", "again", E14_STAMP),
        "confirm_missing": lambda: e14.confirm_candidate(queued, "nope", "s", "r", E14_STAMP),
        "confirm_blank_actor": lambda: e14.confirm_candidate(queued, "cand_1", " ", "r", E14_STAMP),
        "confirm_naive": lambda: e14.confirm_candidate(queued, "cand_1", "s", "r", "2026-10-11T01:02:03"),
        "confirm_badstamp": lambda: e14.confirm_candidate(queued, "cand_1", "s", "r", "yesterday"),
        "confirm_date_only": lambda: e14.confirm_candidate(queued, "cand_1", "s", "r", "2026-10-11"),
        "confirm_not_dict": lambda: e14.confirm_candidate([], "cand_1", "s", "r", E14_STAMP),
        "modify_bad": lambda: e14.modify_candidate(queued, "cand_1", {"low": 0.5, "typical": 0.2, "high": 0.7}, "s", "r", E14_STAMP),
        "modify_bool": lambda: e14.modify_candidate(queued, "cand_1", {"low": True, "typical": 1, "high": 2}, "s", "r", E14_STAMP),
        "reject_missing": lambda: e14.reject_candidate(queued, "zzz", "s", "r", E14_STAMP),
        "reject_not_dict": lambda: e14.reject_candidate(5, "cand_1", "s", "r"),
        "fields_not_dict": lambda: e14.confirm_candidate(dict(queued, fields=[]), "cand_1", "s", "r", E14_STAMP),
        "metadata_not_dict": lambda: e14.confirm_candidate(dict(queued, metadata=5), "cand_1", "s", "r", E14_STAMP),
    }
    for name, call in cases.items():
        try:
            call()
            errs[name] = None
        except Exception as exc:  # noqa: BLE001
            errs[name] = [type(exc).__name__, str(exc)]
    out["errors"] = errs
    return out


def _e12_scenarios():
    """E12 の差分再計算で使う入力の変種（TS 側 tests/systems/engine/fixtures.ts の e12Scenarios と同じ内容）。"""
    base = APPROVED()
    out = {"base": base}
    s = APPROVED()
    s["fields"]["rotor_relevance"]["value"] = "unrelated"
    s["fields"].pop("rotor_seizure_hours")
    s["metadata"].pop("approved_condition_widths")
    out["rotor_unrelated"] = s
    s = APPROVED()
    op(s, "wash")["hours"] = 0.2
    out["wash_changed"] = s
    s = APPROVED()
    s["rule_version"] = "fictional-rule-v2"
    out["version_changed"] = s
    s = APPROVED()
    s["person_count"] = 3
    out["person_count"] = s
    s = APPROVED()
    s["fields"]["extra_field"] = {"value": 1, "status": "confirmed", "source": "x", "confirmed_at": None}
    out["extra_field"] = s
    s = APPROVED()
    s["fields"]["parts_wait_stock_checked"]["value"] = False
    out["stock_false"] = s
    s = APPROVED()
    op(s, "snow_melt")["elapsed_hours"] = None
    out["snow_unknown"] = s
    s = APPROVED()
    s["fields"]["work_scope"]["value"] = "other"
    out["scope_changed"] = s
    s = APPROVED()
    s["metadata"]["approved_condition_widths"]["rotor_seizure_hours"]["actor"] = "someone_else"
    out["approval_actor"] = s
    s = APPROVED()
    s["operations"] = [o for o in s["operations"] if o["operation_id"] != "wash"]
    out["wash_removed"] = s
    s = APPROVED()
    s["fields"] = []
    out["fields_list"] = s
    out["common"] = COMMON()
    return out


@script
def e12_flows():
    from auto_repair_engine import e12
    out = {}
    scen = _e12_scenarios()
    baseline = e12.run(copy.deepcopy(scen["base"]))
    out["baseline"] = baseline

    def with_prev(scenario, snapshot):
        scenario = copy.deepcopy(scenario)
        scenario["metadata"]["previous_snapshot"] = copy.deepcopy(snapshot)
        return scenario

    snap = baseline["delta_snapshot"]
    for name, scenario in scen.items():
        out["delta_" + name] = e12.run(with_prev(scenario, snap))
    out["delta_via_pack"] = e12.run(copy.deepcopy(scen["wash_changed"]), {"previous_snapshot": copy.deepcopy(snap)})
    out["pack_changes_hash"] = e12.run(with_prev(scen["base"], snap), {"extra": 1})
    forged = copy.deepcopy(snap)
    forged["result"]["labor"]["person_hours"]["typical"] = 99
    out["forged"] = e12.run(with_prev(scen["wash_changed"], forged))
    out["garbage_snapshot"] = [e12.run(with_prev(scen["base"], g)) for g in (5, "x", [], {"a": 1})]
    chained = e12.run(with_prev(scen["rotor_unrelated"], snap))
    out["chain_2"] = e12.run(with_prev(scen["wash_changed"], chained["delta_snapshot"]))
    out["index"] = e12.build_dependency_index(scen["extra_field"])
    out["index_bad"] = [e12.build_dependency_index(x) for x in (5, {}, {"fields": 3, "operations": [5, {"operation_id": "zz"}]})]
    out["evaluate"] = {oid: e12._evaluate_operation(scen["base"], oid) for oid in
                       ("base_service", "included_carry", "replacement_carry", "rotor_seizure", "snow_melt", "penetrant_wait", "parts_wait", "wash", "nope")}
    out["evaluate_unrelated"] = e12._evaluate_operation(scen["rotor_unrelated"], "rotor_seizure")
    out["evaluate_mismatch"] = e12._evaluate_operation(scen["approval_actor"], "rotor_seizure")
    out["changed_fields"] = [e12._changed_fields(scen["base"], scen[k]) for k in ("rotor_unrelated", "extra_field", "approval_actor", "fields_list")]
    return out


def _date_ok(text):
    from datetime import date
    try:
        d = date.fromisoformat(text)
        return d.isoformat()
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


def build_scripts():
    out = {}
    for name, fn in SCRIPTS.items():
        reset_state()
        out[name] = fn()
    return out


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(argv):
    everything = not argv
    ids = [a for a in argv if a not in ("units", "compare", "scripts")] or ([*ENGINE_IDS, "integrated"] if everything else [])
    dump(HERE / "variants.json", {name: make_variant(maker, mutate) for name, maker, mutate in VARIANTS})
    for engine_id in ids:
        dump(HERE / f"cases-{engine_id}.json", build_cases(engine_id))
        print("wrote", engine_id)
    if everything or "units" in argv:
        dump(HERE / "units.json", build_units())
    if everything or "scripts" in argv:
        dump(HERE / "scripted.json", build_scripts())
    if everything or "compare" in argv:
        compare_cases = []
        for name, maker, mutate in VARIANTS[:2]:
            scenario = make_variant(maker, mutate)
            # POST /api/compare: e02 だけ架空パックを補い、各案の結果から 5 項目だけ取り出す
            api_results = []
            for engine_id in ENGINE_IDS:
                result = run_engine(engine_id, copy.deepcopy(scenario), fictional_e02_pack(scenario) if engine_id == "e02" else None)
                api_results.append({"engine_id": engine_id, "labor": result.get("labor"), "status": result.get("status"),
                                    "rule_version": result.get("rule_version"), "trace": result.get("trace", [])})
            compare_cases.append({"name": name, "variant": name, "expected": api_results,
                                  "runner_expected": compare_engines(scenario, None)})
        dump(HERE / "compare.json", compare_cases)


if __name__ == "__main__":
    main(sys.argv[1:])
