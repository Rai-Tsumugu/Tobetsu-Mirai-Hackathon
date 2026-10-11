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
