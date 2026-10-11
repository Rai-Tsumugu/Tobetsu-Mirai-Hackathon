#!/usr/bin/env python3
"""S17 同時作業での共通工程の重複排除

反映する要因: HK02, HK05（共通工程の二重計上の排除。リフトアップ・前2輪脱着に加え、雪下ろし・下回り洗浄も入庫1回で計上）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は S17 だけ重複控除前の
    総和（各作業の base_labor_hours の合計 = 2.0 人時）。
 2. 各作業の included_operations の hours 合計が base_labor_hours と一致するか確かめる。
 3. 同時に見積もる作業（J1, J2）の included_operations を走査し、op ID ごとに
    出現した作業を集める。shared=true で 2 作業以上に現れる op を「共通工程」とする。
 4. 共通工程は最初に現れた作業（J1）に 1 回だけ計上し、2 回目以降の作業（J2）から
    その hours を控除する。どの作業のどの op をいくら控除したかを記録する。
 5. 控除後の人時 = 総和 - 控除合計（= 1.7）。scenario.json の deduplicated_base と一致するか検算する。
 6. shared=false の op は ID が同名でも控除しない。別名の op は控除しない（整備士の確認が前提）。
 7. 前処理の共通工程化（docs の仕組み）。共通工程の検出がデータ駆動なのは OP-LIFT・OP-WHEEL-F2 だけで、
    前処理（PRE-SNOW・PRE-WASH）は included_operations から検出せず、暫定値を固定で1回分加える: 雪下ろし（PRE-SNOW）と下回り洗浄（PRE-WASH）は入庫1回の
    作業なので、リフトアップ・前2輪脱着と同じく見積もり全体で1回だけ計上する。
    typical = 控除後（1.7）+ PRE-SNOW typical + PRE-WASH typical。作業ごとに重ねた場合
    （各作業に付けると2回分）との差を控除額として出す。
 8. 人時は丸めずに計算し、出力時だけ小数第2位に丸める。
    low = 控除後 + 各 low、high = 控除を整備士が認めない場合（控除なし 2.0）+ 各 high。
    下回り洗浄は請求しない方針だが実作業人時なので labor_hours に入れ（SPEC U7）、
    請求人時は other_outputs に別に出す。待機は扱わないので elapsed_hours は null。
 9. SPEC.md の形で JSON を標準出力と results/S17.json に出す。
"""
import json
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)

jobs = SC["jobs"]
gross = sum(j["base_labor_hours"] for j in jobs)

# 手順2: 内訳の検算
breakdown_check = {j["id"]: abs(sum(o["hours"] for o in j["included_operations"]) - j["base_labor_hours"]) < 1e-9
                   for j in jobs}

# 手順3: op ID ごとに出現作業を集める
occ = OrderedDict()
for j in jobs:
    for o in j["included_operations"]:
        occ.setdefault(o["op"], []).append((j["id"], o))

# 手順4: 共通工程の検出と控除
deductions = []
kept = []
for op, lst in occ.items():
    if len(lst) >= 2 and all(o["shared"] for _, o in lst):
        keep_job, keep_o = lst[0]
        kept.append({"op": op, "name": keep_o["name"], "kept_in": keep_job, "hours": keep_o["hours"]})
        for jid, o in lst[1:]:
            deductions.append({"op": op, "name": o["name"], "deducted_from": jid,
                               "kept_in": keep_job, "hours": o["hours"]})
deduct_total = sum(d["hours"] for d in deductions)

# 手順5
net = gross - deduct_total
base_ref = SC["base_totals"]["deduplicated_base"]
matches = abs(net - base_ref) < 1e-9

# 手順7: 前処理（雪下ろし・下回り洗浄）を入庫1回の共通工程として1回だけ計上
ops = SC["mechanic_provisional_add_ops"]
snow, wash = ops["PRE-SNOW"], ops["PRE-WASH"]
n_jobs = len(jobs)
pre = lambda k: snow[k] + wash[k]
stack_extra = pre("typical") * (n_jobs - 1)       # 作業ごとに重ねた場合の余分
dedup_all = deduct_total + stack_extra            # リフト等の控除 + 前処理の重複防止

lo = r2(net + pre("low"))
hv = r2(net + pre("typical"))
hi = r2(gross + pre("high"))  # 控除を整備士が認めない場合（+控除額）と各 high
billed = r2(net + snow["typical"])  # 下回り洗浄は請求しない
result = {
    "id": "S17",
    "name": "同時作業での共通工程の重複排除",
    "base_method": "A/C",
    "factors": ["HK02", "HK05"],
    "algorithm": [
        "手順1: 各作業の基準人時を合計して重複控除前の総和を出す（S17 は 2.0 から開始）",
        "手順2: 各作業の included_operations の合計が基準人時と一致するか検算する",
        "手順3: op ID ごとに出現する作業を集め、shared=true で2作業以上に現れる op（" + "・".join(k["name"] for k in kept) + "）を共通工程とする",
        "手順4: 共通工程を最初の作業に1回だけ残し、2回目以降の作業から hours を控除して控除後（1.7）を出し、scenario の deduplicated_base と検算する",
        "手順5: shared=false の op は控除しない。控除の可否は整備士が確認する",
        "手順6: 雪下ろし（PRE-SNOW）と下回り洗浄（PRE-WASH）も入庫1回の共通工程として、見積もり全体で1回だけ加える。手順3の検出対象はリフトアップ・前2輪脱着だけで、前処理は included_operations から検出せず mechanic_provisional_add_ops の暫定値を固定で加える",
        "手順7: typical = 控除後 + PRE-SNOW typical + PRE-WASH typical。low は控除後 + 各 low、high は控除なし（控除を整備士が認めない場合）+ 各 high",
        "手順8: 作業ごとに重ねた場合との差を intermediates に出す（前処理分は typical から引かず、仮想の差として示す）。下回り洗浄は実作業人時として入れ、請求人時は別に示す",
    ],
    "inputs": [
        {"key": f"jobs.{j['id']}.base_labor_hours", "value": j["base_labor_hours"], "status": "仮定"} for j in jobs
    ] + [
        {"key": "jobs.included_operations(shared)", "value": [f"{k['op']} {k['hours']}" for k in kept], "status": "仮定"},
        {"key": "mechanic_provisional_add_ops.PRE-SNOW（low/typical/high）", "value": [snow["low"], snow["typical"], snow["high"]], "status": "仮定"},
        {"key": "mechanic_provisional_add_ops.PRE-WASH（low/typical/high・請求しない方針）", "value": [wash["low"], wash["typical"], wash["high"]], "status": "仮定"},
    ],
    "intermediates": [
        {"label": "重複控除前の総和", "value": r2(gross), "unit": "人時",
         "formula": " + ".join(f"{j['id']} {j['base_labor_hours']}" for j in jobs) + f" = {r2(gross)}"},
        {"label": "共通工程の控除額（" + "・".join(k["op"] for k in kept) + "）", "value": r2(deduct_total), "unit": "人時",
         "formula": " + ".join(f"{d['deducted_from']}の{d['op']} {d['hours']}" for d in deductions) + f" = {r2(deduct_total)}（{kept[0]['kept_in']}に1回残す）"},
        {"label": "重複控除後", "value": r2(net), "unit": "人時",
         "formula": f"{r2(gross)} - {r2(deduct_total)} = {r2(net)}（scenario の deduplicated_base と一致: {matches}）"},
        {"label": "前処理（雪下ろし＋下回り洗浄）を1回だけ計上", "value": r2(pre("typical")), "unit": "人時",
         "formula": f"PRE-SNOW {snow['typical']} + PRE-WASH {wash['typical']} = {r2(pre('typical'))}（入庫1回）"},
        {"label": "前処理を作業ごとに重ねた場合との差（typical からは引かない仮想の差）", "value": r2(stack_extra), "unit": "人時",
         "formula": f"({snow['typical']} + {wash['typical']}) × {n_jobs}作業 - ({snow['typical']} + {wash['typical']}) × 1回 = {r2(stack_extra)}"},
        {"label": "重ねた場合との差の合計（リフト等の控除＋前処理の仮想の差）", "value": r2(dedup_all), "unit": "人時",
         "formula": f"{r2(deduct_total)} + {r2(stack_extra)} = {r2(dedup_all)}（作業ごとに積むと {r2(gross + pre('typical') * n_jobs)}、共通化すると {hv}）"},
        {"label": "typical", "value": hv, "unit": "人時",
         "formula": f"2.0 - {r2(deduct_total)} + {snow['typical']} + {wash['typical']} = {hv}"},
        {"label": "low / high", "value": [lo, hi], "unit": "人時",
         "formula": f"low = {r2(net)} + {snow['low']} + {wash['low']} = {lo}；high = {r2(gross)}（控除なし）+ {snow['high']} + {wash['high']} = {hi}"},
    ],
    "result": {
        "labor_hours": {"low": lo, "typical": hv, "high": hi},
        "elapsed_hours": None,
        "other_outputs": [
            {"label": "控除の内訳", "value": [f"{d['deducted_from']}から{d['op']} {d['hours']}人時を控除（{d['kept_in']}に計上）" for d in deductions], "unit": ""},
            {"label": "J1/J2 の控除後の配分", "value": {j["id"]: r2(j["base_labor_hours"] - sum(d["hours"] for d in deductions if d["deducted_from"] == j["id"])) for j in jobs}, "unit": "人時"},
            {"label": "請求人時（下回り洗浄は請求しない方針）", "value": billed, "unit": "人時（実作業人時 labor_hours.typical から PRE-WASH typical を除く）"},
            {"label": "作業ごとに重ねた場合との差（前処理分は typical からは引かない仮想の差）", "value": {"リフト等の共通工程": r2(deduct_total), "前処理（雪下ろし・下回り洗浄）": r2(stack_extra), "合計": r2(dedup_all)}, "unit": "人時"},
        ],
        "note": ("この案は、リフトアップ・前2輪脱着に加え、雪下ろし（PRE-SNOW）と下回り洗浄（PRE-WASH）も入庫1回の共通工程として、"
                 "見積もり全体で1回だけ計上する。typical は 2.0 から控除 0.3 を引き、前処理 typical を足した値。"
                 f"low は各 low、high は控除を整備士が認めない場合（控除なし 2.0）と各 high を採り、この案の範囲での上限とする。"
                 "下回り洗浄は請求しないが実作業なので labor_hours には入れ、請求人時は other_outputs に別に示す。"
                 "共通工程の自動検出はリフトアップ・前2輪脱着だけで、雪下ろし・下回り洗浄は暫定値の固定加算（観察条件とは結びつけていない）。"
                 "J1・J2 が別入庫になり前処理が2回分かかる場合は範囲外とし、unknowns に記す。"
                 "固着・錆・折れ込みなどの追加工程やタイヤ重量による差は、この案では扱わない。"),
    },
    "assumptions": [
        "仮定: 共通工程は最初の作業（J1）に残し、後の作業（J2）から控除する。どちらに残すかで作業別の配分は変わるが合計は変わらない",
        "仮定: 雪下ろし・下回り洗浄は J1・J2 を同じ入庫で行う限り1回で足りる（作業ごとに繰り返さない）",
        "仮定: 控除後 1.7（scenario の deduplicated_base）は整備士の確認前。確認が取れない場合に備え high は控除なし 2.0 を基にする",
        "仮定: PRE-SNOW・PRE-WASH は mechanic_provisional_add_ops の暫定値（整備士の仮の値）を使う",
    ],
    "unknowns": [
        "J1 と J2 を同じ入庫・同じリフト状態で続けて作業できるか（整備士の確認が必要）",
        "J1 の _note は OP-WHEEL-F2 と OP-WHEEL-R2 の両方にタイヤ運搬が含まれると読め、控除する OP-WHEEL-F2 の 0.2 人時に運搬分がどれだけ含まれるか未確認（HK05）",
        "J2 で前輪を外す際に J1 の脱着と完全に兼ねられるかの実測は未確認",
        "範囲外: 雪下ろし・下回り洗浄を1回で足りるとする前提が、実際の入庫の流れ（J1・J2 が別入庫になる等）で成り立つか未確認。別入庫なら前処理2回分（2.0 + 2×0.55 = 3.10 程度）になりうるが、high には含めない",
        *( [] if all(breakdown_check.values()) else ["included_operations の合計が基準人時と一致しない作業がある"] ),
    ],
}

out = json.dumps(result, ensure_ascii=False, indent=2)
print(out)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S17.json").write_text(out + "\n", encoding="utf-8")
