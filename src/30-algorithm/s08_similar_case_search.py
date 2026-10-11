#!/usr/bin/env python3
"""S08 類似事例の検索と条件差の表示（基礎方式 B）

アルゴリズムの手順:
  1. scenario.json を読み、今回の作業範囲（jobs の J1+J2）、現車の条件
     （ブレーキ周り錆グレード、初度登録からの経過年数、季節、車格）を取り出す。
  2. historical_records から、作業範囲が今回と同じ（J1 と J2 の両方を含み、
     余計な作業を含まない）事例をすべて候補にする（R08〜R11、同一車両 R11 を含む）。
  3. 比較条件は docs の「錆・固着の状態、経過年数、季節」の3つ。
       - 錆・固着の状態: brake_area のグレードが同じなら一致。事例の記録が null なら
         「条件不明」（R10）。固着対応タグの有無・人時は参考として併記するだけ。
       - 経過年数: 差が AGE_TOLERANCE 年以内なら一致（仮定）。
       - 季節: 事例の月が 11〜3 月なら冬で、今回（冬季）と一致。
     車格は表示だけで、採用判定には使わない。
  4. 採用規則: 候補はすべて採用する。条件の相違や記録なしがあっても除外せず、
     各事例の条件差（一致/相違/条件不明）を並べて表示する。同一車両（R11）も採用し、
     同一車両である旨を表示する。
  5. 採用事例の実作業人時（actual）の 中央値・件数・範囲(最小〜最大) を求める。
  6. 件数が shop_policy.min_records_for_reference 以上なら、typical=中央値、
     low=最小、high=最大とする。未満なら参考扱いとして基準 1.7 を据え置く。
  7. 実績には他案の要因（雪下ろし・氷塊除去・ローター固着など）の人時が含まれる。
     これは方式B（実績から見積もる）の性質であり、note に明記する。
  8. scenario.json を自分の位置から相対で読み、results/S08.json に出力を書く。
"""
import json
import os
import statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.join(HERE, "scenario.json")
OUT = os.path.join(HERE, "results", "S08.json")

# --- シナリオにない仮定値 ---
AGE_TOLERANCE = 2          # 経過年数が一致とみなす幅（年）
WINTER_MONTHS = {11, 12, 1, 2, 3}  # scenario.intake.season の「冬季（11〜3月）」と同じ
BODY_CLASS_MAP = {"普通車SUV": "SUV"}  # 現車の車格 -> 事例側の body 表記
FASTENER_TAG = "固着対応"  # 事例側で固着の発生を示すタグ
# 他案が扱う要因のタグ（S05/S06 の雪下ろし・氷塊除去、S03 系のローター固着）。S08 の要因外
OTHER_FACTOR_TAGS = ("雪下ろし", "氷塊除去", "ローター固着")


WAIT_SEIZE = 0.25  # U5 浸透待ち（FX-SEIZE を含む範囲）
WAIT_MELT = 0.5    # U5 融解待ち（氷塊除去を含む範囲）


def r2(x):
    return round(x + 1e-9, 2)


def main():
    with open(SCEN, encoding="utf-8") as f:
        sc = json.load(f)

    veh = sc["vehicle"]
    intake = sc["intake"]
    fy, fm = map(int, veh["first_registration"].split("-"))
    iy, im, _ = map(int, intake["date"].split("-"))
    age = (iy - fy) + (im - fm) / 12.0
    age_years = round(age)  # 2014-01 -> 2027-01 = 13
    cur_rust = sc["condition"]["underbody_rust_grade"]["brake_area"]
    cur_body = BODY_CLASS_MAP.get(veh["body_class"], veh["body_class"])
    cur_winter = im in WINTER_MONTHS
    scope = [j["id"] for j in sc["jobs"]]
    base = sc["base_totals"]["deduplicated_base"]
    min_n = sc["shop_policy"]["min_records_for_reference"]

    # 2. 作業範囲で絞り込み
    records = sc["historical_records"]
    cands = [r for r in records if set(r["jobs"]) == set(scope)]

    # 3. 条件比較（車格は表示のみ）
    rows = []
    for r in cands:
        rm = int(r["date"].split("-")[1])
        cond = {}
        if r["brake_rust"] is None:
            cond["錆・固着の状態"] = "条件不明"
        else:
            cond["錆・固着の状態"] = "一致" if r["brake_rust"] == cur_rust else "相違"
        cond["経過年数"] = "一致" if abs(r["age_years"] - age_years) <= AGE_TOLERANCE else "相違"
        cond["季節"] = "一致" if (rm in WINTER_MONTHS) == cur_winter else "相違"
        tags = r.get("tags") or {}
        same = bool(r.get("same_vehicle"))
        n_diff = sum(v == "相違" for v in cond.values())
        n_unk = sum(v == "条件不明" for v in cond.values())
        rows.append({
            "id": r["id"], "date": r["date"], "actual": r["actual"], "estimate": r["estimate"],
            "same_vehicle": same, "conditions": cond,
            "display_only": {"車格": r["body"], "錆グレード": r["brake_rust"], "経過年数": r["age_years"],
                             "固着対応人時": (tags.get(FASTENER_TAG) or {}).get("hours")},
            "other_factor_hours": r2(sum((tags.get(k) or {}).get("hours", 0) for k in OTHER_FACTOR_TAGS)),
            "mismatch": n_diff, "unknown": n_unk,
            "label": ("同一車両の前回事例。" if same else "") +
                     ("条件不明を含む（除外せず表示）。" if n_unk else "") +
                     ("条件に相違あり（除外せず差を表示）。" if n_diff else ""),
        })

    # 4. 候補はすべて採用
    acts = [x["actual"] for x in rows]
    n = len(acts)
    reference = n < min_n
    if n:
        med, lo, hi = statistics.median(acts), min(acts), max(acts)
    else:
        med = lo = hi = base
    if reference:
        lab = {"low": base, "typical": base, "high": base}
    else:
        lab = {"low": r2(lo), "typical": r2(med), "high": r2(hi)}

    # U5: S08 の範囲は全般（U1）で FX-SEIZE（浸透待ち）と氷塊除去（融解待ち）を含む。
    # 待機は人時に入れず、low/typical/high それぞれの経過時間に足す。
    wait_hours = WAIT_SEIZE + WAIT_MELT
    elapsed = {k: r2(v + wait_hours) for k, v in lab.items()}

    unknown_cases = [x for x in rows if x["unknown"]]
    prev = next((x for x in rows if x["same_vehicle"]), None)
    oth_avg = sum(x["other_factor_hours"] for x in rows) / n if n else 0.0

    inter = [
        {"label": "今回の経過年数", "value": age_years, "unit": "年",
         "formula": "intake.date(%s) - first_registration(%s) を年に丸める" % (intake["date"][:7], veh["first_registration"])},
        {"label": "作業範囲(J1+J2)で一致した候補数", "value": len(cands), "unit": "件",
         "formula": "count(records where set(jobs)==set(scenario.jobs の id))"},
        {"label": "採用事例数", "value": n, "unit": "件",
         "formula": "候補はすべて採用。件数 %d と min_records_for_reference %d を比べる（%s）" % (n, min_n, "未満=参考扱い" if reference else "以上=実績で置換")},
        {"label": "採用事例の実作業人時 中央値", "value": r2(med), "unit": "人時",
         "formula": "median(%s)" % ", ".join("%s=%.2f" % (x["id"], x["actual"]) for x in rows)},
        {"label": "採用事例の実作業人時 範囲", "value": "%.2f〜%.2f" % (lo, hi), "unit": "人時",
         "formula": "min〜max(採用事例のactual)"},
        {"label": "中央値と基準の差", "value": r2(med - base), "unit": "人時",
         "formula": "中央値 %.2f - 基準 %.1f" % (med, base)},
        {"label": "経過時間に足す待機", "value": r2(wait_hours), "unit": "時間（人時に含めない）",
         "formula": "浸透待ち %.2f（FX-SEIZE）+ 融解待ち %.2f（氷塊除去）。U5 により low/typical/high の経過時間に足す。実績の人時は待機を除く" % (WAIT_SEIZE, WAIT_MELT)},
        {"label": "条件不明の事例", "value": ", ".join(x["id"] for x in unknown_cases) or "なし", "unit": "",
         "formula": "錆・固着の状態の記録が null の事例。除外せず『条件不明』と表示"},
        {"label": "採用事例に含まれる他の要因の人時（平均）", "value": r2(oth_avg), "unit": "人時",
         "formula": "平均(各事例の %s タグ hours 合計)。方式Bの性質として実績に含まれる" % "・".join(OTHER_FACTOR_TAGS)},
    ]

    if reference:
        note = ("採用 %d 件は閾値 %d 件未満のため参考扱い。low・typical・high は基準 %.1f を据え置く。" % (n, min_n, base))
    else:
        note = ("採用 %d 件は閾値 %d 件以上。typical=実作業人時の中央値 %.2f、low=最小 %.2f、high=最大 %.2f とした（この案の範囲での上限は実績の最大）。"
                % (n, min_n, med, lo, hi))
    note += ("作業範囲が J1+J2 の事例 R08〜R11 をすべて採用した。条件の記録がない事例（%s の錆）は除外せず『条件不明』と表示し、"
             "同一車両 %s も含めて同一車両である旨を表示する。車格は表示のみで採用判定に使わない。"
             % ("・".join(x["id"] for x in unknown_cases) or "なし", prev["id"] if prev else "なし"))
    note += ("実績には他の要因（雪下ろし・氷塊除去・ローター固着など）の人時が事例平均 %.2f 人時含まれる。これは方式Bの性質で、"
             "実績の中央値にそのまま含めている。" % oth_avg)

    out = {
        "id": "S08",
        "name": "類似事例の検索と条件差の表示",
        "base_method": "B",
        "factors": ["HK01", "AG01", "AG02"],
        "algorithm": [
            "手順1: 作業範囲（J1+J2）が同一の実績 R08〜R11 をすべて候補にする（同一車両 R11 を含む）",
            "手順2: 候補ごとに 錆・固着の状態、経過年数、季節 を 一致/相違/条件不明 で比較して表示（車格は表示のみ）",
            "手順3: 条件の相違や記録なしがあっても除外せず、候補をすべて採用する",
            "手順4: 採用事例の実作業人時の中央値・件数・範囲を出す",
            "手順5: 件数が min_records_for_reference 以上なら typical=中央値、low=最小、high=最大（未満なら基準 1.7 据え置き）",
        ],
        "inputs": [
            {"key": "jobs", "value": "+".join(scope), "status": "確認済み"},
            {"key": "condition.underbody_rust_grade.brake_area", "value": cur_rust, "status": "確認済み"},
            {"key": "elapsed_years", "value": age_years, "status": "確認済み"},
            {"key": "intake.season", "value": intake["season"], "status": "確認済み"},
            {"key": "vehicle.body_class", "value": veh["body_class"], "status": "確認済み"},
            {"key": "shop_policy.min_records_for_reference", "value": min_n, "status": "確認済み"},
        ],
        "intermediates": inter,
        "result": {
            "labor_hours": lab,
            "elapsed_hours": elapsed,
            "other_outputs": [
                {"label": "採用事例数", "value": n, "unit": "件"},
                {"label": "参考扱い", "value": reference, "unit": ""},
                {"label": "実績の中央値・範囲", "value": {"median": r2(med), "min": r2(lo), "max": r2(hi), "n": n} if n else None, "unit": "人時"},
                {"label": "事例ごとの条件差（車格は表示のみ）",
                 "value": [{k: x[k] for k in ("id", "date", "actual", "conditions", "display_only", "same_vehicle", "other_factor_hours", "label")} for x in rows],
                 "unit": ""},
                {"label": "条件不明の事例", "value": [x["id"] for x in unknown_cases], "unit": ""},
                {"label": "同一車両の前回事例", "value": {"id": prev["id"], "actual": prev["actual"], "conditions": prev["conditions"]} if prev else None, "unit": ""},
            ],
            "note": note,
        },
        "assumptions": [
            "仮定: 経過年数は差 %d 年以内を一致とする" % AGE_TOLERANCE,
            "仮定: 季節は事例の月が11〜3月なら冬とする",
            "仮定: 錆・固着の状態は brake_area のグレードが同じなら一致とし、隣接グレードは相違とする。固着対応タグは参考表示のみ",
            "仮定: 比較条件は docs の『錆・固着の状態、経過年数、季節』。車格は表示だけで採用判定に使わない",
            "仮定: 作業範囲が J1+J2 の事例はすべて採用する。相違・条件不明があっても除外せず、条件差を表示する",
            "仮定: 採用が閾値 min_records_for_reference 以上なら low=最小、typical=中央値、high=最大とする",
            "仮定: 『類似』は作業範囲の一致で定義し、錆・経過年数・季節の相違は除外理由にせず条件差として表示する（依頼の指示。実績が4件と少なく、除外すると閾値3件を割るため）",
            "仮定: S08 の範囲は docs §3 の『全般』（U1）。FX-SEIZE と氷塊除去を含むため、U5 の待機 %.2f 時間を経過時間に足す（factors の HK01/AG01/AG02 は実績に含まれる主な要因）" % wait_hours,
            "仮定: high は実績の最大。S08 の仕組みは実績の中央値と件数の提示で、未確認項目への暫定値の割り当て（U2/U3）は S04・S21・S24 など対象の案に限られるため行わない",
            "仮定: actual は作業者の実作業人時（待機時間を除く）",
            "仮定: 実績には他の要因（雪下ろし・氷塊除去・ローター固着など）の人時が含まれる。方式Bの性質として中央値に含めたまま使う",
        ],
        "unknowns": [
            "R10 は錆・固着の状態の記録がなく『条件不明』。人時0.55の『その他』も原因の記録なし",
            "R11 は同一車両だが錆グレードが異なり、前回の状態が今回と同じとは限らない",
            "採用 %d 件のため範囲（最小〜最大）は少数の実績で決まる" % n,
            "実績の人時が実測かどうかは未確認",
            "サブフレームの腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る（範囲外）",
        ],
    }
    s = json.dumps(out, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s)


if __name__ == "__main__":
    main()
