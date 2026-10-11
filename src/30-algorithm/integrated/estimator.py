"""統合版 工数見積もりエンジン（30案の良いところを1本の流れにまとめた決定版）。

使い方:
    python3 src/30-algorithm/integrated/estimator.py
    python3 src/30-algorithm/integrated/estimator.py --case 別の入力.json --out-json 出力.json

値の置き場所（estimator.py は数値リテラルを持たない）:
- data/records.json      過去の実績。作業のたびに増え、単価の候補・類似実績が変わる
- data/shop_params.json  整備士の暫定値・しきい値・単価の元になる経費など。最新の情報・工場方針で変わる
- data/job_catalog.json  基準工数。基準データの版で変わる
- data/case_example.json 今回の車両と入庫時の観察
- constants.py           定義で決まる定数（和暦の起点、丸め桁、状態の選択肢など）

処理の流れと、取り込んだ案:
 1. 車両情報: 電子車検証の取込、和暦→西暦、経過年数（S26）、季節の判定
 2. 基準工数: 作業の選択、共通工程の重複排除、前処理は入庫1回（S17）
 3. 工程の展開: 状態に応じた分岐（S15）、状態チェックリスト（S01）、部位別の錆グレード（S02）、
    締結部ごとの固着リスク（S03）、冬季の前処理（S05）、タイヤ重量による人数（S07）、付随部品（S22）
 4. 単価: 承認済みの補正表を使い、実績から次の版の候補を作る（S11・S12）。他工場の値は参照幅だけ（S13）
 5. 3点見積もり（S19）と、人時・経過時間の分離（S18）
 6. 方式比較: 方式A/Cの積み上げと方式Bの類似実績を平均せずに並べる（S08・S30）
 7. 確認: 確認強度（S04）、気象による前処理の確認（S06）、確認リスト（S16）、確認優先度（S21）、
    撮影ガイド（S24）、AIの一次分類（S23）、同一車両の履歴（S09）
 8. 条件付き見積もり（S20）、時間単価（S27）、材料費の別建て（S28）、顧客向けの内訳（S29）
 9. 記録の分析: 見積もりと実績の差（S10）、工程ログの集計（S14）、音声メモの振り分け（S25）

全案共通のガードレール（docs/man-hours/system-ideas-30.md §1）:
- 年式・走行距離・地域・季節だけで人時を増やさない。人時は観察した状態と工程に対応づける
- 未確認を0として確定しない。typical に入れず high（上限）に入れる
- 待機は経過時間にだけ入れる。暖房費・材料費は人時に足さない
- 方式を平均しない。計算は提案で、確定は整備士・見積もり担当者が行う
"""

import argparse
import decimal
import json
import re
import statistics
from pathlib import Path

import constants as C

HERE = Path(__file__).resolve().parent
ERA_PATTERN = re.compile(r"^(?P<era>\D+?)(?P<year>\d+|元)年(?P<month>\d+)月$")


# ---------------------------------------------------------------- 共通の小道具

ROUNDING = {}


def set_rounding(params):
    """丸め方は工場に確認する事項なので shop_params.rounding（変数）から読む。"""
    cfg = params["rounding"]
    ROUNDING.update(hours=(cfg["hours_decimals"], getattr(decimal, cfg["hours_mode"])),
                    yen=(cfg["yen_decimals"], getattr(decimal, cfg["yen_mode"])),
                    percent=(cfg["percent_decimals"], getattr(decimal, cfg["percent_mode"])))


def quantize(value, kind):
    decimals, mode = ROUNDING[kind]
    step = decimal.Decimal(C.ROUNDING_BASE).scaleb(-decimals)
    return decimal.Decimal(str(value)).quantize(step, rounding=mode)


def hours(value):
    return float(quantize(value, "hours"))


def yen(value):
    return int(quantize(value, "yen"))


def per_band(fn):
    return {band: fn(band) for band in C.BANDS}


def rounded_bands(values, rounder=hours):
    return {band: rounder(values[band]) for band in C.BANDS}


def load_json(path):
    return json.loads(Path(path).read_text())


def normalize_state(text, params):
    """入力の先頭が状態の名前（shop_params.state_labels）と一致すれば、その状態の ID を返す。"""
    labels = public(params["state_labels"])
    for state_id in sorted(labels, key=lambda key: len(labels[key]), reverse=True):
        if str(text).startswith(labels[state_id]):
            return state_id
    raise ValueError(f"現車状態の選択肢にない値: {text}")


def state_label(state_id, params):
    return params["state_labels"].get(state_id, state_id)


def first(items):
    return next(iter(items))


def public(mapping):
    """先頭が _ の説明用キーを除く。"""
    return {k: v for k, v in mapping.items() if not k.startswith("_")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(params, records, catalog, case):
    """変数ファイルと入力の整合を確かめる。書き間違いを黙って別の扱いにしないため。"""
    jobs = set(catalog["jobs"])
    areas = {area for job in catalog["jobs"].values() for area in job.get("work_areas", [])}
    require(set(case["jobs"]) <= jobs, f"今回の作業が基準工数にない: {case['jobs']}")
    for fastener in case["condition"]["fasteners"]:
        require(fastener["job"] in jobs, f"締結部の作業が基準工数にない: {fastener['id']} {fastener['job']}")
        require(isinstance(fastener.get("count"), int) and fastener["count"] > C.NO_COUNT,
                f"締結部の本数（count）が正の整数でない: {fastener['id']}")
    for area, grade in public(case["condition"]["underbody_rust_grade"]).items():
        require(grade is None or (isinstance(grade, int) and not isinstance(grade, bool)),
                f"錆グレードは整数か null（未確認）にする: {area} {grade!r}")
    ids = set(C.STATE_IDS)
    require(set(public(params["state_labels"])) == ids, "state_labels の ID が constants.STATE_IDS と一致しない")
    require(set(public(params["state_treatment"])) == ids, "state_treatment の ID が constants.STATE_IDS と一致しない")
    tire = params["tire_handling"]
    require(set(tire["weight_status_to_state"].values()) <= ids, "tire_handling.weight_status_to_state に未知の状態 ID がある")

    ops = params["provisional_rates_v1"]["ops"]
    for rule in params["condition_rules"]:
        require(rule["kind"] in C.RULE_KINDS, f"condition_rules の kind が未知: {rule['kind']}")
        require(rule["op"] in ops, f"condition_rules の op が暫定値にない: {rule['op']}")
        require("job" not in rule or rule["job"] in jobs, f"condition_rules の job が基準工数にない: {rule['id']} {rule.get('job')}")
        require("area" not in rule or rule["area"] in areas, f"condition_rules の area が作業部位にない: {rule['id']} {rule.get('area')}")
        if rule["kind"] == C.RULE_SIDE_STATE and rule["job"] in case["jobs"]:
            sides = set(catalog["jobs"][rule["job"]]["sides"])
            require(sides <= set(case["condition"][rule["path"]]),
                    f"左右の状態が足りない: {rule['path']} に {sorted(sides)} が必要")
    for tag, mapping in public(params["tag_to_op"]).items():
        require(mapping["unit"] in C.TAG_UNITS, f"tag_to_op の unit が未知: {tag} {mapping['unit']}")
        require(mapping["op"] in ops, f"tag_to_op の op が暫定値にない: {tag} {mapping['op']}")
        entries = [r["tags"][tag] for r in records["historical_records"] if tag in r["tags"]]
        counted = [e for e in entries if "count" in e]
        require(all(e["count"] > C.NO_COUNT for e in counted), f"実績の count は正の数にする: {tag}")
        if mapping["unit"] == C.TAG_UNIT_COUNT:
            require(len(counted) == len(entries), f"tag_to_op の unit は count だが、count のない実績がある: {tag}")
        else:
            require(not counted, f"tag_to_op の unit は visit だが、count のある実績がある: {tag}")
    require(set(records["other_shop_tag_to_op"].values()) <= set(ops), "other_shop_tag_to_op の op が暫定値にない")
    treatment = public(params["fastener_treatment"])
    require(set(public(params["fastener_rust_classes"]).values()) <= set(treatment),
            "fastener_rust_classes のリスク区分が fastener_treatment にない")
    require(all(op in ops for plan in treatment.values() for band in C.BANDS for op, _level in plan[band]),
            "fastener_treatment の工程が暫定値にない")
    waits = params["waits"]
    require(set(waits["by_op"].values()) <= set(waits["hours"]), "waits.by_op の待機が waits.hours にない")
    require(params["adopted_rate_table"] in C.RATE_TABLES, f"adopted_rate_table が不正: {params['adopted_rate_table']}")
    similar = params["similar_case"]
    require(set(similar["conditions"]) <= set(C.SIMILAR_CONDITIONS), "similar_case.conditions に未知の条件がある")
    require(set(similar["exclude_if_differs"]) <= set(similar["conditions"]), "exclude_if_differs が conditions にない")

    rate = params["labor_rate"]
    require(rate["mode"] in (C.RATE_MODE_ANNUAL, C.RATE_MODE_SEASONAL), f"labor_rate.mode が不正: {rate['mode']}")
    require(rate["heating_key"] in rate["cost_keys"], "labor_rate.heating_key が cost_keys に含まれていない")
    require(rate["heating_winter_yen"] <= rate["cost_yen"][rate["heating_key"]], "冬季の暖房費が年間の暖房費を超えている")
    billable = rate["billable_hours"]
    require(billable["winter"] + billable["non_winter"] == billable["annual"],
            "labor_rate.billable_hours の冬季＋冬季以外が年間と一致しない")


# ---------------------------------------------------------------- 1. 車両情報（S26）

def parse_year_month(text):
    year_text, month_text, *_ = str(text).split(C.DATE_SEPARATOR)
    return int(year_text), int(month_text)


def parse_wareki(text):
    match = ERA_PATTERN.match(text)
    if not match:
        raise ValueError(f"初度登録年月を読めない: {text}")
    era_year = C.ERA_FIRST_YEAR_NUMBER if match["year"] == C.ERA_FIRST_YEAR_LABEL else int(match["year"])
    return C.ERA_START_YEAR[match["era"]] + era_year - C.ERA_YEAR_OFFSET, int(match["month"])


def season_of(month, params):
    return C.SEASON_WINTER if month in params["season"]["winter_months"] else C.SEASON_OTHER


def vehicle_info(case, params):
    reg_year, reg_month = parse_wareki(case["e_shakensho"]["初度登録年月"])
    in_year, in_month = parse_year_month(case["intake"]["date"])
    months = (in_year - reg_year) * C.MONTHS_PER_YEAR + (in_month - reg_month)
    first_registration = f"{reg_year}{C.DATE_SEPARATOR}{str(reg_month).zfill(C.MONTH_DIGITS)}"
    return {
        "first_registration": first_registration,
        # 同一車両の照合キーは手入力にせず、電子車検証の型式と初度登録から作る（表記揺れを防ぐ）
        "vehicle_key": f"{case['e_shakensho']['型式']}{C.VEHICLE_KEY_SEPARATOR}{first_registration}",
        "elapsed_months": months,
        "elapsed_years": months // C.MONTHS_PER_YEAR,
        "odometer_km": case["vehicle"]["odometer_km"],
        "season": season_of(in_month, params),
        "imported": {k: v for k, v in case["e_shakensho"].items() if k not in params["e_shakensho_excluded"]},
        "note": "初度登録年月は製造年ではない。使用者の情報は取り込まない",
    }


# ---------------------------------------------------------------- 2. 基準工数と重複排除（S17）

def base_estimate(job_ids, catalog, params, rates):
    jobs = [catalog["jobs"][job_id] for job_id in job_ids]
    gross = sum(job["base_labor_hours"] for job in jobs)
    shared = {}
    for job in jobs:
        for op in job["included_operations"]:
            if op["shared"]:
                shared.setdefault(op["op"], []).append(op)
    deductions = []
    for op_id, occurrences in shared.items():
        repeats = len(occurrences) - C.COUNTED_ONCE
        if repeats > C.NO_COUNT:
            sample = first(occurrences)
            deductions.append({"op": op_id, "name": sample["name"], "jobs": len(occurrences),
                               "deducted_hours": hours(sample["hours"] * repeats)})
    deducted = sum(d["deducted_hours"] for d in deductions)
    per_visit_ops = [op_id for op_id, rate in rates.items() if rate.get("per_visit")]
    avoided = sum(rates[op_id][C.TYPICAL] for op_id in per_visit_ops) * (len(job_ids) - C.COUNTED_ONCE)
    return {
        "jobs": [{"id": job_id, "name": catalog["jobs"][job_id]["name"],
                  "base_labor_hours": catalog["jobs"][job_id]["base_labor_hours"]} for job_id in job_ids],
        "gross_hours": hours(gross),
        "deductions": deductions,
        "base_hours": hours(gross - deducted),
        "per_visit_ops": per_visit_ops,
        "per_visit_double_count_avoided_typical": hours(avoided),
        "per_visit_note": "前処理を作業ごとに重ねた場合との差（参考）。前処理は入庫1回だけ計上しているので差し引きはしない",
        "catalog_version": catalog["version"],
    }


# ---------------------------------------------------------------- 4. 単価（S11・S12・S13）

def tag_samples(records, tag, unit):
    samples = []
    for record in records:
        entry = record["tags"].get(tag)
        if entry:
            samples.append(entry["hours"] / entry["count"] if unit == C.TAG_UNIT_COUNT else entry["hours"])
    return samples


STATISTICS = {"min": min, "median": statistics.median, "max": max}


def rate_tables(params, records):
    v1 = params["provisional_rates_v1"]["ops"]
    rule = params["rate_update_rule"]
    v2 = {op_id: dict(rate, source=f"暫定値（{C.RATE_TABLE_V1}）") for op_id, rate in v1.items()}
    evidence = []
    for tag, mapping in public(params["tag_to_op"]).items():
        op_id = mapping["op"]
        samples = tag_samples(records["historical_records"], tag, mapping["unit"])
        enough = len(samples) >= rule["min_records"]
        evidence.append({"tag": tag, "op": op_id, "n": len(samples),
                         "min": hours(min(samples)) if samples else None,
                         "median": hours(statistics.median(samples)) if samples else None,
                         "max": hours(max(samples)) if samples else None,
                         "used_for_v2": enough})
        if enough:
            v2[op_id] = dict(v1[op_id], **{band: STATISTICS[rule[band]](samples) for band in C.BANDS},
                             source=f"実績 {len(samples)} 件")
    adopted_name = params["adopted_rate_table"]
    adopted = v1 if adopted_name == C.RATE_TABLE_V1 else v2
    candidate_name = C.RATE_TABLE_V2 if adopted_name == C.RATE_TABLE_V1 else C.RATE_TABLE_V1
    candidate = v2 if adopted_name == C.RATE_TABLE_V1 else v1
    return adopted_name, adopted, candidate_name, candidate, evidence


def other_shop_bands(records, adopted):
    bands = []
    for key, op_id in records["other_shop_tag_to_op"].items():
        medians = [shop[key]["median"] for shop in records["other_shops"].values() if key in shop]
        if not medians:
            continue
        own = adopted[op_id][C.TYPICAL]
        bands.append({"op": op_id, "other_shops_min": min(medians), "other_shops_max": max(medians),
                      "own_typical": own, "inside": min(medians) <= own <= max(medians),
                      "note": "参照幅だけに使う。他工場の値を自工場の値にしない"})
    return bands


# ---------------------------------------------------------------- 3. 工程の展開（S01・S02・S03・S05・S07・S15・S22）

def item_from_levels(item_id, label, rule, state, quantity, op_id, levels, rates):
    hours_by_band = per_band(lambda b: rates[op_id][levels[b]] * quantity if levels[b] else C.NO_HOURS)
    units_by_band = per_band(lambda b: {op_id: quantity} if levels[b] else {})
    return {"id": item_id, "group": item_id, "label": label, "factor": rule.get("factor"), "from": rule.get("from"),
            "state_id": state, "quantity": quantity, "billable": rates[op_id]["billable"],
            "hours": hours_by_band, "op_units": units_by_band,
            "elapsed_adjust": per_band(lambda b: C.NO_HOURS)}


def rule_quantity(rule, condition, job_ids, catalog):
    kind = rule["quantity"]
    if kind == C.QUANTITY_PER_VISIT:
        return C.ONE_UNIT
    if kind == C.QUANTITY_SIDES:
        return len(catalog["jobs"][rule["job"]]["sides"])
    return condition[rule["path"]][kind]  # 観察した数（例: 氷塊のあるホイールハウスの数）


def work_area_grades(job_ids, catalog, condition):
    grades = condition["underbody_rust_grade"]
    areas = [area for job_id in job_ids for area in catalog["jobs"][job_id].get("work_areas", [])]
    return {area: grades.get(area) for area in areas}


def grade_state(grade, min_grade):
    if grade is None:
        return C.STATE_UNCONFIRMED
    return C.STATE_PROBLEM if grade >= min_grade else C.STATE_NOT_OBSERVED


def condition_items(case, params, catalog, rates):
    condition, job_ids = case["condition"], case["jobs"]
    treatment = params["state_treatment"]
    items = []
    for rule in params["condition_rules"]:
        if rule.get("job") and rule["job"] not in job_ids:
            continue
        op_id, name = rule["op"], rates[rule["op"]]["name"]
        if rule["kind"] == C.RULE_SIDE_STATE:
            for side_key, side_label in catalog["jobs"][rule["job"]]["sides"].items():
                state = normalize_state(condition[rule["path"]][side_key], params)
                items.append(item_from_levels(f"{rule['id']}:{side_key}", f"{name}（{side_label}）", rule, state,
                                              C.ONE_UNIT, op_id, treatment[state], rates))
            continue
        if rule["kind"] == C.RULE_STATE:
            state = normalize_state(condition[rule["path"]]["state"], params)
        elif rule["kind"] == C.RULE_AREA_GRADE:
            state = grade_state(condition["underbody_rust_grade"].get(rule["area"]), rule["min_grade"])
        elif rule["kind"] == C.RULE_WORK_AREA_GRADE:  # 作業部位のうち最も進んだ錆。未確認の部位があれば上限に入れる
            grades = list(work_area_grades(job_ids, catalog, condition).values())
            known = [g for g in grades if g is not None]
            if known and max(known) >= rule["min_grade"]:
                state = C.STATE_PROBLEM
            elif len(known) < len(grades):
                state = C.STATE_UNCONFIRMED
            else:
                state = C.STATE_NOT_OBSERVED
        else:
            raise ValueError(f"condition_rules の kind が未知: {rule['kind']}")
        quantity = rule_quantity(rule, condition, job_ids, catalog)
        items.append(item_from_levels(rule["id"], name, rule, state, quantity, op_id, treatment[state], rates))
    return items


def fastener_class(rust_text, params):
    for prefix, risk in public(params["fastener_rust_classes"]).items():
        if str(rust_text).startswith(prefix):
            return risk
    raise ValueError(f"締結部の錆の区分にない値: {rust_text}")


def fastener_items(case, params, rates, excluded=None):
    items = []
    label = params["fastener_treatment"]["_label"]
    for fastener in case["condition"]["fasteners"]:
        if fastener["job"] not in case["jobs"]:
            if excluded is not None:
                excluded.append(f"{fastener['name']}: 作業 {fastener['job']} が今回の作業に含まれないため計算から除外")
            continue
        risk = fastener_class(fastener["rust"], params)
        plan = params["fastener_treatment"][risk]
        count = fastener["count"]
        items.append({
            "id": f"fastener:{fastener['id']}", "group": f"締結部（{risk}）", "label": fastener["name"],
            "factor": label["factor"], "from": label["from"],
            "state_id": risk, "quantity": count, "billable": all(rates[op]["billable"] for b in C.BANDS for op, _l in plan[b]),
            "hours": per_band(lambda b: sum(rates[op][level] for op, level in plan[b]) * count),
            "op_units": per_band(lambda b: {op: count for op, _level in plan[b]}),
            "elapsed_adjust": per_band(lambda b: C.NO_HOURS),
        })
    return items


def tire_item(case, params, catalog, unknowns):
    """タイヤ重量で運搬の人数が変わる分（S07）。基準は1人運搬を前提にしている。"""
    if not any(catalog["jobs"][job_id].get("tire_carry") for job_id in case["jobs"]):
        return None
    base = first(catalog["jobs"][job_id]["tire_carry"] for job_id in case["jobs"]
                 if catalog["jobs"][job_id].get("tire_carry"))
    rule = params["tire_handling"]
    weight = case["vehicle"]["tire_with_wheel_weight_kg"]
    if weight["value"] <= base["basis_max_wheel_kg"]:
        return None
    if weight["value"] <= rule["one_person_max_wheel_kg"]:
        unknowns.append(f"タイヤ（ホイール付き {weight['value']}kg）は基準の前提（{base['basis_max_wheel_kg']}kg 以下）を超えるが、"
                        f"1人で扱える範囲（{rule['one_person_max_wheel_kg']}kg 以下）。運搬時間の差は未設定")
        return None
    matches = [state for prefix, state in rule["weight_status_to_state"].items()
               if str(weight["status"]).startswith(prefix)]
    if not matches:
        raise ValueError(f"tire_handling.weight_status_to_state にない重量の状態: {weight['status']}")
    state = first(matches)
    if rule["has_lifter"]:
        if rule["lifter_labor_hours"] is None:
            unknowns.append("タイヤリフターを使う運搬の人時が未設定（shop_params.tire_handling.lifter_labor_hours）")
            return None
        labor, elapsed = rule["lifter_labor_hours"], rule["lifter_labor_hours"]
        how = "機材（タイヤリフター）"
    else:
        two = rule["two_person"]
        labor, elapsed = two["persons"] * two["hours_each"], two["hours_each"]
        how = f"{two['persons']}人作業"
    levels = params["state_treatment"][state]
    labor_delta = labor - base["labor_hours"]
    elapsed_delta = elapsed - base["labor_hours"] / base["persons"]
    return {"id": "tire_carry", "group": "tire_carry", "label": f"タイヤ運搬を{how}にする差分（ホイール付き {weight['value']}kg）",
            "factor": rule["factor"], "from": rule["from"], "state_id": state, "quantity": C.ONE_UNIT,
            "billable": rule["billable"],
            "elapsed_reason": f"{how}は運搬を同時に行うので、経過時間は1人あたりの時間になる（重量は{weight['status']}）",
            "hours": per_band(lambda b: labor_delta if levels[b] else C.NO_HOURS),
            "op_units": per_band(lambda b: {}),
            "elapsed_adjust": per_band(lambda b: elapsed_delta if levels[b] else C.NO_HOURS)}


def out_of_scope_unknowns(case, params, catalog):
    in_scope = set(work_area_grades(case["jobs"], catalog, case["condition"]))
    notes = []
    for area, grade in case["condition"]["underbody_rust_grade"].items():
        if area.startswith("_") or area in in_scope or grade is not None:
            continue
        notes.append(f"{area}: 未確認。{params['out_of_scope_areas'].get(area, '作業範囲外')}")
    return notes


# ---------------------------------------------------------------- 5. 3点見積もりと経過時間（S18・S19）

def totals(base_hours, items, params, season):
    labor = per_band(lambda b: base_hours + sum(item["hours"][b] for item in items))
    waits_cfg = params["waits"]
    variant = C.WAIT_VARIANT_WINTER if season == C.SEASON_WINTER else C.WAIT_VARIANT_DEFAULT

    def waits_for(band):
        ops = {op for item in items for op, units in item["op_units"][band].items() if units > C.NO_COUNT}
        keys = sorted({waits_cfg["by_op"][op] for op in ops if op in waits_cfg["by_op"]})
        table = waits_cfg["hours"]
        return {key: table[key].get(variant, table[key][C.WAIT_VARIANT_DEFAULT]) for key in keys}

    waits = per_band(waits_for)
    elapsed = per_band(lambda b: labor[b] + sum(i["elapsed_adjust"][b] for i in items) + sum(waits[b].values()))
    return labor, elapsed, waits


# ---------------------------------------------------------------- 6. 方式Bの類似実績（S08）

def age_band(age, thresholds):
    return sum(age >= threshold for threshold in thresholds)


DIFF_LABELS = {C.DIFF_MATCH: "一致", C.DIFF_DIFFERENT: "相違", C.DIFF_UNKNOWN: "条件不明"}


def compare(record_value, case_value):
    if record_value is None or case_value is None:
        return C.DIFF_UNKNOWN
    return C.DIFF_MATCH if record_value == case_value else C.DIFF_DIFFERENT


def same_vehicle_record_ids(vinfo, records):
    return {h["record_id"] for h in records["vehicle_history"] if h["vehicle_key"] == vinfo["vehicle_key"]}


def similar_cases(case, params, records, vinfo):
    job_set = set(case["jobs"])
    cfg = params["similar_case"]
    thresholds = params["diff_log_age_bands"]
    own_records = same_vehicle_record_ids(vinfo, records)
    now = {C.CONDITION_BRAKE_RUST: case["condition"]["underbody_rust_grade"].get(cfg["rust_area"]),
           C.CONDITION_AGE_BAND: age_band(vinfo["elapsed_years"], thresholds),
           C.CONDITION_SEASON: vinfo["season"]}
    rows, same_vehicle_rows = [], []
    for record in records["historical_records"]:
        if set(record["jobs"]) != job_set:
            continue
        _year, month = parse_year_month(record["date"])
        then = {C.CONDITION_BRAKE_RUST: record["brake_rust"],
                C.CONDITION_AGE_BAND: age_band(record["age_years"], thresholds),
                C.CONDITION_SEASON: season_of(month, params)}
        codes = {k: compare(then[k], now[k]) for k in cfg["conditions"]}
        row = {"id": record["id"], "actual": record["actual"],
               "conditions": {k: {"result": DIFF_LABELS[codes[k]], "record": then[k], "now": now[k]} for k in codes}}
        if cfg["exclude_same_vehicle"] and (record.get("same_vehicle") or record["id"] in own_records):
            same_vehicle_rows.append(row)
            continue
        excluded = [k for k in cfg["exclude_if_differs"] if codes[k] == C.DIFF_DIFFERENT]
        rows.append(dict(row, adopted=not excluded, excluded_by=excluded))
    actuals = [row["actual"] for row in rows if row["adopted"]]
    enough = len(actuals) >= cfg["min_records"]
    summary = per_band(lambda b: None)
    if actuals:
        summary = {C.LOW: min(actuals), C.TYPICAL: statistics.median(actuals), C.HIGH: max(actuals)}
    return {"method": C.METHOD_B, "n": len(actuals), "enough_records": enough,
            "labor_hours": rounded_bands(summary) if actuals else summary, "cases": rows,
            "same_vehicle_cases": same_vehicle_rows,
            "note": "実績には雪下ろし等すべての要因が含まれる。件数が足りなければ参考扱い。"
                    "同一車両の前回実績は集計に入れず別に示す（車の状態が変わっているため）"}


# ---------------------------------------------------------------- 7. 確認（S04・S06・S09・S16・S21・S23・S24）

def tier_points(value, tiers):
    return max((tier["points"] for tier in tiers if value >= tier["min"]), default=C.NO_POINTS)


def checks(case, params, catalog, records, vinfo, items, out_of_scope):
    condition = case["condition"]
    intensity_cfg = params["check_intensity"]
    strong = vinfo["elapsed_years"] >= intensity_cfg["age_years"] or vinfo["odometer_km"] >= intensity_cfg["odometer_km"]

    weather_cfg, forecast = params["weather_prompt"], case["weather_forecast"]
    weather_prompt = (forecast["min_temp_c"] <= weather_cfg["min_temp_c_le"]
                      or forecast["snowfall_forecast_cm"] >= weather_cfg["snowfall_cm_ge"])

    history = [h for h in records["vehicle_history"] if h["vehicle_key"] == vinfo["vehicle_key"]]
    latest = max(history, key=lambda h: parse_year_month(h["date"])) if history else None

    score_cfg = params["priority_score"]
    grades = [g for g in work_area_grades(case["jobs"], catalog, condition).values() if g is not None]
    unconfirmed = [i for i in items if i["hours"][C.TYPICAL] == C.NO_HOURS and i["hours"][C.HIGH] > C.NO_HOURS]
    breakdown = {
        "経過年数": tier_points(vinfo["elapsed_years"], score_cfg["age_years"]),
        "走行距離": tier_points(vinfo["odometer_km"], score_cfg["odometer_km"]),
        "作業部位の錆グレード": tier_points(max(grades), score_cfg["work_area_rust_grade"]) if grades else C.NO_POINTS,
        "未確認の部位あり": score_cfg["unconfirmed_area_exists"] if (unconfirmed or out_of_scope) else C.NO_POINTS,
        "防錆施工歴": score_cfg["rustproof_coat_history"] if condition["rustproof_undercoat"]["value"] else C.NO_POINTS,
        "前回の固着記録": score_cfg["previous_seizure_record"] if latest and latest["observed"]["seized_fasteners"] else C.NO_POINTS,
    }
    score = sum(breakdown.values())
    band = max((b for b in score_cfg["bands"] if score >= b["min"]), key=lambda b: b["min"])

    checklist = sorted(
        ({"item": i["label"], "state": i["state"], "high_only_hours": hours(i["hours"][C.HIGH] - i["hours"][C.TYPICAL])}
         for i in unconfirmed),
        key=lambda row: row["high_only_hours"], reverse=True)

    required = [shot for job_id in case["jobs"] for shot in params["photo_required_shots"].get(job_id, [])]
    taken = [shot for shot in required if shot in case["photos"]["taken"]]
    ai_rows = [row for row in case["photos"]["ai_items"]
               if row["ai_grade"] is not None and row["mechanic_grade"] is not None]
    ai_agree = [row for row in ai_rows if row["ai_grade"] == row["mechanic_grade"]]

    same_vehicle = None
    if latest:
        compare = public(params["vehicle_history_compare"])
        fasteners = {f["id"]: f for f in condition["fasteners"]}
        same_vehicle = {
            "previous_record": latest["record_id"], "previous_date": latest["date"],
            "km_since_previous": vinfo["odometer_km"] - latest["odometer_km"],
            "grades": {key: {"previous": latest["observed"][key], "now": condition["underbody_rust_grade"].get(area)}
                       for key, area in compare.items()},
            "previously_seized_now": [{"id": fid, "now": fastener_class(fasteners[fid]["rust"], params)}
                                      for fid in latest["observed"]["seized_fasteners"] if fid in fasteners],
            "note": "前回の実績値はそのまま使わない。前回固着した箇所と錆の進行を確認箇所として示す",
        }

    return {
        "check_intensity": {"level": "強" if strong else "通常",
                            "extra_items": intensity_cfg["extra_items"] if strong else [],
                            "note": "経過年数・走行距離は確認の強さだけに使い、人時は増やさない"},
        "weather_prompt": {"prompt": weather_prompt, "forecast": forecast,
                           "note": "気象は確認を促すだけ。前処理の人時は入庫時の現車確認で決める"},
        "priority": {"score": score, "breakdown": breakdown, "band": band["name"], "when": band["when"],
                     "note": "確認の順番と時期に使う。人時には変換しない"},
        "checklist": checklist,
        "out_of_scope": out_of_scope,
        "photos": {"required": len(required), "taken": len(taken),
                   "coverage_percent": float(quantize(len(taken) / len(required) * C.PERCENT, "percent")) if required else None,
                   "missing": {shot: case["photos"]["missing_reason"].get(shot, "") for shot in required if shot not in taken}},
        "ai_classification": {"compared": len(ai_rows), "agree": len(ai_agree),
                              "disagree": [row["area"] for row in ai_rows if row not in ai_agree],
                              "note": "計算には整備士の確定値だけを使う"},
        "same_vehicle": same_vehicle,
    }


# ---------------------------------------------------------------- 8. 金額・条件付き・顧客向け（S20・S22・S27・S28・S29）

def labor_rates(params, season):
    cfg = params["labor_rate"]
    total_cost = sum(cfg["cost_yen"][key] for key in cfg["cost_keys"])
    billable = cfg["billable_hours"]
    annual = total_cost / billable["annual"]
    heating = cfg["cost_yen"][cfg["heating_key"]]
    without_heating = (total_cost - heating) / billable["annual"]
    winter = without_heating + cfg["heating_winter_yen"] / billable["winter"]
    non_winter = without_heating + (heating - cfg["heating_winter_yen"]) / billable["non_winter"]
    if cfg["mode"] == C.RATE_MODE_ANNUAL:
        applied = annual
    else:
        applied = winter if season == C.SEASON_WINTER else non_winter
    return {"mode": cfg["mode"], "applied_yen_per_hour": yen(applied), "annual_yen_per_hour": yen(annual),
            "seasonal_winter_yen_per_hour": yen(winter), "seasonal_non_winter_yen_per_hour": yen(non_winter),
            "note": "暖房費は人時に足さず、時間単価の側で扱う。配賦方法は工場の経営判断"}, applied


def materials(params, items):
    cfg = params["materials"]
    prices = cfg["prices"]

    def cost(band):
        total = C.NO_YEN
        for item in items:
            for op, units in item["op_units"][band].items():
                for material in cfg["by_op"].get(op, []):
                    price = prices[material]
                    total += price["price_yen"] / price["uses"] * units
        return total

    return rounded_bands(per_band(cost), yen)


def is_conditional(item):
    """発生するかどうか分からない追加: typical にない工程が high で加わるもの（未確認・折れ込み等）。"""
    return bool(set(item["op_units"][C.HIGH]) - set(item["op_units"][C.TYPICAL])) or (
        item["hours"][C.TYPICAL] == C.NO_HOURS and item["hours"][C.HIGH] > C.NO_HOURS)


def conditional_quote(items, params, rate):
    threshold = params["contact_threshold"]
    groups = {}
    for item in filter(is_conditional, items):
        groups.setdefault(item["group"], []).append(item)
    rows = []
    for group, members in groups.items():
        extra = sum(i["hours"][C.HIGH] - i["hours"][C.TYPICAL] for i in members)
        extra_yen = sum(i["hours"][C.HIGH] - i["hours"][C.TYPICAL] for i in members if i["billable"]) * rate
        label = group if len(members) > C.ONE_UNIT else first(members)["label"]
        rows.append({"condition": label, "items": [i["label"] for i in members], "state": first(members)["state"],
                     "extra_hours": hours(extra), "extra_yen": yen(extra_yen),
                     "contact_before_work": extra > threshold["labor_hours_gt"] or extra_yen > threshold["yen_gt"]})
    rows.sort(key=lambda row: row["extra_hours"], reverse=True)
    return {"confirmed_typical_basis": "typical に入っている工程は見積もりに含める。追加金額は請求する工程の分だけ",
            "conditions": rows,
            "all_conditions_extra_hours": hours(sum(row["extra_hours"] for row in rows)),
            "note": "条件が発生したら記録し、作業前連絡が「要」なら顧客の了承を得てから作業する"}


def companion_parts(params, items):
    cfg = params["companion_parts"]
    estimated_ops = {op for item in items for band in C.BANDS for op in item["op_units"][band]}
    shown, reference = [], []
    for name, part in cfg["items"].items():
        row = {"part": name, "freq": part["freq"], "same_op_in_estimate": part.get("op") in estimated_ops,
               "labor_hours_each": part.get("labor_hours_each"),
               "note": part.get("note", "")}
        (shown if part["freq"] >= cfg["display_threshold"] else reference).append(row)
    return {"shown": shown, "reference_below_threshold": reference,
            "note": "候補は見積もり本体に入れない。観察で必要が分かったものだけ工程として入る"}


def customer_sheet(base, items):
    lines = [{"line": f"基準作業: {job['name']}", "typical": job["base_labor_hours"], "high": job["base_labor_hours"],
              "basis": "基準工数"} for job in base["jobs"]]
    lines += [{"line": f"共通工程の重複分: {d['name']}", "typical": -d["deducted_hours"], "high": -d["deducted_hours"],
               "basis": "同時作業で1回だけ計上"} for d in base["deductions"]]
    for item in items:
        basis = {"basis": f"現車の状態: {item['state']}", "billed": item["billable"]}
        if item["hours"][C.TYPICAL] > C.NO_HOURS:
            upper = item["hours"][C.TYPICAL] if is_conditional(item) else item["hours"][C.HIGH]
            lines.append({"line": f"見込む追加: {item['label']}", "typical": hours(item["hours"][C.TYPICAL]),
                          "high": hours(upper), **basis})
        if is_conditional(item):
            lines.append({"line": f"発生した場合だけの追加: {item['label']}", "typical": C.NO_HOURS,
                          "high": hours(item["hours"][C.HIGH] - item["hours"][C.TYPICAL]), **basis})
    return lines


# ---------------------------------------------------------------- 9. 記録の分析（S10・S14・S25）

def diff_log(params, records):
    thresholds = params["diff_log_age_bands"]
    groups = {}
    for record in records["historical_records"]:
        _year, month = parse_year_month(record["date"])
        key = (season_of(month, params), age_band(record["age_years"], thresholds))
        groups.setdefault(key, []).append(record)
    rows = []
    for (season, band_index), group in sorted(groups.items()):
        diffs = [r["actual"] - r["estimate"] for r in group]
        tags = {}
        for record in group:
            for tag, entry in record["tags"].items():
                tags[tag] = tags.get(tag, C.NO_HOURS) + entry["hours"]
        rows.append({"season": season, "age_band": band_index, "n": len(group),
                     "mean_diff": hours(statistics.mean(diffs)), "median_diff": hours(statistics.median(diffs)),
                     "tag_hours": {tag: hours(value) for tag, value in tags.items()}})
    return {"age_band_thresholds_years": thresholds, "rows": rows,
            "note": "区分ごとの差を人時に足すと季節・年式による一律加算になるので、単価の更新（v2）の元データとしてだけ使う"}


def tap_log_summary(records):
    out = {}
    for log_id, steps in records["tap_logs"].items():
        work = [s for s in steps if not s.get("wait")]
        out[log_id] = {"labor_hours": hours(sum(s["persons"] * s["hours"] for s in work)),
                       "wait_hours": hours(sum(s["hours"] for s in steps if s.get("wait"))),
                       "elapsed_hours": hours(sum(s["hours"] for s in steps))}
    return out


def voice_memo_tags(params, memo):
    dictionary = {tag: words for tag, words in params["voice_memo_tags"].items() if not tag.startswith("_")}
    rows = []
    for sentence in filter(None, (s.strip() for s in memo.split(C.SENTENCE_DELIMITER))):
        remaining, tags = sentence, []
        for tag, words in dictionary.items():
            for word in words:
                if word in remaining:
                    tags.append(tag)
                    remaining = remaining.replace(word, "")
        rows.append({"sentence": sentence, "tags": tags})
    return {"rows": rows, "note": "振り分けは候補。整備士が確認してから実績（records.json）に記録する"}


# ---------------------------------------------------------------- 全体

def estimate(case, params, catalog, records):
    validate(params, records, catalog, case)
    set_rounding(params)
    vinfo = vehicle_info(case, params)
    adopted_name, rates, candidate_name, candidate, rate_evidence = rate_tables(params, records)
    base = base_estimate(case["jobs"], catalog, params, rates)

    unknowns, excluded = [], []
    items = condition_items(case, params, catalog, rates) + fastener_items(case, params, rates, excluded)
    tire = tire_item(case, params, catalog, unknowns)
    if tire:
        items.append(tire)
    for item in items:
        item["state"] = state_label(item["state_id"], params)
    out_of_scope = out_of_scope_unknowns(case, params, catalog)
    unknowns += out_of_scope

    labor, elapsed, waits = totals(base["base_hours"], items, params, vinfo["season"])
    candidate_items = condition_items(case, params, catalog, candidate) + fastener_items(case, params, candidate)
    candidate_labor, _e, _w = totals(base["base_hours"], candidate_items + ([tire] if tire else []), params, vinfo["season"])

    rate_info, applied_rate = labor_rates(params, vinfo["season"])
    billed = per_band(lambda b: labor[b] - sum(i["hours"][b] for i in items if not i["billable"]))
    return {
        "case_id": case["case_id"],
        "status": "提案（未確定）。確定は整備士・見積もり担当者が行い、修正理由を残す",
        "vehicle": vinfo,
        "estimate": {
            "method": C.METHOD_A_C,
            "labor_hours": rounded_bands(labor),
            "billed_hours": rounded_bands(billed),
            "elapsed_hours": rounded_bands(elapsed),
            "waits_hours": {band: {k: hours(v) for k, v in waits[band].items()} for band in C.BANDS},
            "rate_table": adopted_name,
            "note": "typical は観察済みの状態から見込む値。high はこの見積もりの範囲での上限で、未確認項目の上限を含む",
        },
        "base": base,
        "items": [dict(item, hours=rounded_bands(item["hours"]),
                       elapsed_adjust=rounded_bands(item["elapsed_adjust"])) for item in items],
        "method_comparison": {
            "a_c": {"labor_hours": rounded_bands(labor), "basis": "基準工数＋現車の状態から展開した工程"},
            "b": similar_cases(case, params, records, vinfo),
            "note": "方式を平均しない。担当者が選ぶか手で入力し、理由を残す",
        },
        "rates": {"adopted": adopted_name, "candidate": candidate_name,
                  "candidate_labor_hours": rounded_bands(candidate_labor),
                  "evidence": rate_evidence, "other_shops": other_shop_bands(records, rates),
                  "note": "候補の版は自動で適用しない。整備士が承認した版を shop_params.adopted_rate_table に書く"},
        "checks": checks(case, params, catalog, records, vinfo, items, out_of_scope),
        "conditional_quote": conditional_quote(items, params, applied_rate),
        "money": {"labor_rate": rate_info,
                  "labor_yen": rounded_bands(per_band(lambda b: billed[b] * applied_rate), yen),
                  "labor_yen_basis": "請求人時（請求しない工程を除く）× 時間単価",
                  "materials_yen": materials(params, items),
                  "note": "材料費・部品代は工賃と別に記載する"},
        "companion_parts": companion_parts(params, items),
        "customer_sheet": customer_sheet(base, items),
        "analysis": {"diff_log": diff_log(params, records), "tap_logs": tap_log_summary(records),
                     "voice_memo": voice_memo_tags(params, case.get("voice_memo", ""))},
        "unknowns": unknowns,
        "excluded_from_this_job": excluded,
        "data_versions": {"shop_params": params["version"], "job_catalog": catalog["version"],
                          "records": len(records["historical_records"])},
    }


def to_markdown(result):
    est, b = result["estimate"], result["method_comparison"]["b"]
    rows = [
        f"# 見積もり結果 {result['case_id']}（{result['status']}）",
        "",
        f"- 車両: 初度登録 {result['vehicle']['first_registration']}（{result['vehicle']['elapsed_years']}年）、"
        f"{result['vehicle']['odometer_km']}km、{result['vehicle']['season']}",
        f"- 基準: {result['base']['gross_hours']} 人時 → 重複控除後 {result['base']['base_hours']} 人時（基準 {result['base']['catalog_version']}）",
        "",
        "| 区分 | low | typical | high |",
        "|---|---|---|---|",
        "| 人時（" + est["method"] + "） | " + " | ".join(str(est["labor_hours"][k]) for k in C.BANDS) + " |",
        "| 請求人時（請求しない工程を除く） | " + " | ".join(str(est["billed_hours"][k]) for k in C.BANDS) + " |",
        "| 経過時間 | " + " | ".join(str(est["elapsed_hours"][k]) for k in C.BANDS) + " |",
        "| 人時（" + b["method"] + f"、{b['n']}件） | " + " | ".join(str(b["labor_hours"][k]) for k in C.BANDS) + " |",
        "| 工賃（円） | " + " | ".join(str(result["money"]["labor_yen"][k]) for k in C.BANDS) + " |",
        "| 材料費（円） | " + " | ".join(str(result["money"]["materials_yen"][k]) for k in C.BANDS) + " |",
        "",
        "## 内訳",
        "",
        "| 項目 | 状態 | low | typical | high | 案 |",
        "|---|---|---|---|---|---|",
    ]
    rows += [f"| {i['label']} | {i['state']} | " + " | ".join(str(i["hours"][k]) for k in C.BANDS) + f" | {i['from']} |"
             for i in result["items"]]
    rows += ["", "## 作業前に連絡する条件", "", "| 条件 | 追加人時 | 追加金額 | 作業前連絡 |", "|---|---|---|---|"]
    rows += [f"| {q['condition']} | {q['extra_hours']} | {q['extra_yen']} | {'要' if q['contact_before_work'] else '不要'} |"
             for q in result["conditional_quote"]["conditions"]]
    rows += ["", "## 未確認・範囲外", ""] + [f"- {u}" for u in result["unknowns"]]
    return "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser(description="統合版 工数見積もりエンジン")
    parser.add_argument("--data-dir", default=str(HERE / "data"))
    parser.add_argument("--case", default=None, help="今回の入力（既定: data/case_example.json）")
    parser.add_argument("--out-json", default=str(HERE / "result_example.json"))
    parser.add_argument("--out-md", default=str(HERE / "result_example.md"))
    args = parser.parse_args()
    data = Path(args.data_dir)
    result = estimate(load_json(args.case or data / "case_example.json"), load_json(data / "shop_params.json"),
                      load_json(data / "job_catalog.json"), load_json(data / "records.json"))
    text = json.dumps(result, ensure_ascii=False, indent=C.JSON_INDENT)
    Path(args.out_json).write_text(text + "\n")
    Path(args.out_md).write_text(to_markdown(result))
    print(text)


if __name__ == "__main__":
    main()
