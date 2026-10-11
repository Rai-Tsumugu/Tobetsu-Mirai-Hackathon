#!/usr/bin/env python3
"""S13 道内の整備工場間で匿名化した実績の共有

反映する要因: HK01（融雪剤による腐食）, AG01（締結部の固着・折れ込み、ローター固着）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. 自工場の historical_records から、タグ（固着対応 / ボルト折れ / ローター固着）ごとに
    「1本あたり（ローターは1側あたり）の人時」を記録ごとに hours / count で求める。
    固着対応だけは、現車のブレーキ周り腐食グレード（underbody_rust_grade.brake_area = 3）と
    同じ brake_rust の記録に絞って集計する（S13 の「腐食の程度別」）。
 3. タグごとに実績件数 n を数える。n が min_records_for_reference（3）以上なら
    自工場の実績を採用する（low=最小, typical=中央値, high=最大）。
    n が足りなければ整備士暫定値（mechanic_provisional_add_ops）を採用する。
 4. other_shops_anonymized（shop_X, shop_Y）の中央値を並べ、参照幅（最小〜最大）と
    件数加重平均を出す。他工場の値は採用しない。妥当性の確認にだけ使う。
    自工場の採用 typical が参照幅の内側か外側かを判定して記録する。
 5. 現車の締結部を condition.fasteners と fastener_risk_rule で分類する。
      中 -> 固着対応の可能性 / 重 -> 折れ込みの可能性 / 未確認 -> 不明 / 軽 -> 通常
 6. 採用した単価で追加人時を積み上げる（S03 と同じ区分ルール）。
      SPEC U3 の表に従う。
      中（固着対応の可能性）: low 0 / typical・high は固着対応単価
      重（折れ込みの可能性）: low・typical・high とも固着対応単価。high のみ さらに ボルト折れ + FX-THREAD
      未確認（スライドボルト）: high のみ固着対応単価
      ローター固着（状態は未確認）: high のみ 2側 x ローター固着単価
 7. 人時 = 1.7 + 追加人時。丸めずに計算し、出力時だけ小数第2位に丸める。
 8. 浸透待ち（U5）は人時に入れず、固着対応を含む low/typical/high それぞれの経過時間にだけ足す。
 9. 参考として、他工場の参照幅の単価で同じ積み上げをした「参照人時」を出す
    （採用値ではない）。SPEC.md の形で JSON を標準出力と results/S13.json に出す。
"""
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
r4 = lambda x: round(x + 1e-12, 4)  # 単価の表示用（未丸めの計算値との差を出さない）
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
min_rec = SC["shop_policy"]["min_records_for_reference"]
rule = SC["condition"]["fastener_risk_rule"]
others = SC["other_shops_anonymized"]
shops = [k for k in others if not k.startswith("_")]

# --- 手順2-3: 自工場の単価 ---
TAGS = {  # タグ名: (暫定値の工程ID, 他工場のキー)
    "固着対応": ("FX-SEIZE", "固着対応_per_bolt"),
    "ボルト折れ": ("FX-BROKEN", "ボルト折れ_per_bolt"),
    "ローター固着": ("FX-ROTOR", "ローター固着_per_side"),
}
BRAKE_GRADE = SC["condition"]["underbody_rust_grade"]["brake_area"]
own = {}
for tag, (opid, okey) in TAGS.items():
    rates = []
    for rec in SC["historical_records"]:
        if tag == "固着対応" and rec.get("brake_rust") != BRAKE_GRADE:
            continue  # 腐食グレードで層別（固着対応のみ）
        t = rec["tags"].get(tag)
        if t and t.get("count"):
            rates.append(t["hours"] / t["count"])
    n = len(rates)
    if n >= min_rec:
        rs = sorted(rates)
        adopted = {"low": rs[0], "typical": statistics.median(rs), "high": rs[-1]}
        source = "自工場実績"
    else:
        adopted = {r: ops[opid][r] for r in RANGES}
        source = "整備士暫定値"
    # --- 手順4: 他工場の参照幅 ---
    meds = {s: others[s][okey]["median"] for s in shops}
    ns = {s: others[s][okey]["n"] for s in shops}
    wmean = sum(meds[s] * ns[s] for s in shops) / sum(ns.values())
    ref = {"min": min(meds.values()), "max": max(meds.values()), "wmean": wmean, "n": sum(ns.values())}
    inside = ref["min"] <= adopted["typical"] <= ref["max"]
    own[tag] = {"n": n, "rates": rates, "adopted": adopted, "source": source, "ref": ref, "inside": inside}

# --- 手順5: 現車の締結部分類 ---
def rust_key(text):
    for k in ("未確認", "重", "中", "軽"):
        if text.startswith(k):
            return k
    return "未確認"

cnt = {"通常": 0, "固着対応の可能性": 0, "折れ込みの可能性": 0, "不明": 0}
for f in SC["condition"]["fasteners"]:
    c = rule[rust_key(f["rust"])]
    cnt[c if c in cnt else "不明"] += f.get("count", 1)
rotor_sides = 2  # 仮定: ローター固着は未確認、疑うときは左右2側

# --- 手順6: 積み上げ ---
thread = {r: ops["FX-THREAD"][r] for r in RANGES}

def build(seize, broken, rotor):
    """SPEC U3 の表どおり。中: low=0 / typ,high=固着。重: low,typ,high=固着 + high のみ折れ+ねじ山。未確認: high のみ固着。"""
    add, parts = {}, {}
    for r in RANGES:
        s_mid = cnt["固着対応の可能性"] * seize[r] if r != "low" else 0.0
        s_hvy = cnt["折れ込みの可能性"] * seize[r]
        if r == "high":
            b = cnt["折れ込みの可能性"] * broken[r]
            th = cnt["折れ込みの可能性"] * thread[r]
            u = cnt["不明"] * seize[r]
            ro = rotor_sides * rotor[r]
        else:
            b = th = u = ro = 0.0
        parts[r] = {"seize": s_mid + s_hvy, "broken": b, "thread": th, "unknown": u, "rotor": ro}
        add[r] = sum(parts[r].values())
    return add, parts


add, parts = build(own["固着対応"]["adopted"], own["ボルト折れ"]["adopted"], own["ローター固着"]["adopted"])
labor = {r: base + add[r] for r in RANGES}

# --- 手順8: 経過時間 ---
soak = SC["elapsed_waits"]["penetrant_soak_wait_hours"]
elapsed = {}
for r in RANGES:
    p = parts[r]
    elapsed[r] = labor[r] + (soak if (p["seize"] + p["unknown"]) > 0 else 0.0)

# --- 手順9: 他工場の参照幅での参考人時（採用しない） ---
def flat(v):
    return {r: v for r in RANGES}
ref_s = {tag: own[tag]["ref"] for tag in own}
ref_lo, _ = build(flat(ref_s["固着対応"]["min"]), flat(ref_s["ボルト折れ"]["min"]), flat(ref_s["ローター固着"]["min"]))
ref_hi, _ = build(flat(ref_s["固着対応"]["max"]), flat(ref_s["ボルト折れ"]["max"]), flat(ref_s["ローター固着"]["max"]))
# 参照幅は単一の中央値なので、typical 列のみ（固着対応中心）と high 列を並べる
ref_typ_lo = base + ref_lo["typical"]
ref_typ_hi = base + ref_hi["typical"]
ref_high_lo = base + ref_lo["high"]
ref_high_hi = base + ref_hi["high"]

def tag_rows(tag):
    o = own[tag]
    a = o["adopted"]
    return {"自工場の採用値": {r: r4(a[r]) for r in RANGES}, "採用元": o["source"], "自工場の実績件数": o["n"],
            "他工場の参照幅": [o["ref"]["min"], o["ref"]["max"]], "他工場の件数加重平均": r2(o["ref"]["wmean"]),
            "他工場の件数合計": o["ref"]["n"], "自工場typicalは参照幅内": o["inside"]}

sz, bk, rt = own["固着対応"], own["ボルト折れ"], own["ローター固着"]
inter = [
    {"label": "自工場の固着対応 単価（low/typical/high）", "value": [r4(sz["adopted"][r]) for r in RANGES], "unit": "人時/本",
     "formula": f"腐食グレード{BRAKE_GRADE}の記録ごとに hours/count（n={sz['n']}）の 最小 / 中央値 / 最大"},
    {"label": "他工場の固着対応 参照幅", "value": [sz["ref"]["min"], sz["ref"]["max"]], "unit": "人時/本",
     "formula": f"shop_X・shop_Y の中央値の最小〜最大（件数加重平均 {r2(sz['ref']['wmean'])}、n合計 {sz['ref']['n']}）"},
    {"label": "自工場typicalと他工場参照幅の位置関係", "value": "参照幅内" if sz["inside"] else "参照幅外", "unit": "",
     "formula": f"{sz['ref']['min']} <= {r2(sz['adopted']['typical'])} <= {sz['ref']['max']}"},
    {"label": "ボルト折れ 採用単価（実績不足のため暫定値）", "value": [r2(bk["adopted"][r]) for r in RANGES], "unit": "人時/本",
     "formula": f"自工場の実績 n={bk['n']} < 基準{min_rec}件 -> FX-BROKEN の暫定値。他工場参照幅 {bk['ref']['min']}〜{bk['ref']['max']}"},
    {"label": "ローター固着 採用単価（自工場実績）", "value": [r2(rt["adopted"][r]) for r in RANGES], "unit": "人時/側",
     "formula": f"記録ごとに hours/count（n={rt['n']}）の 最小 / 中央値 / 最大。他工場参照幅 {rt['ref']['min']}〜{rt['ref']['max']}"},
    {"label": "追加人時合計（low/typical/high）", "value": [r2(add[r]) for r in RANGES], "unit": "人時",
     "formula": f"中 {cnt['固着対応の可能性']}本（lowは0） + 重 {cnt['折れ込みの可能性']}本（全区分で固着単価、highはさらに折れ+ねじ山）+ 不明 {cnt['不明']}本（high）+ ローター {rotor_sides}側（high）"},
    {"label": "参考: 他工場参照幅の単価で積んだ場合の typical", "value": [r2(ref_typ_lo), r2(ref_typ_hi)], "unit": "人時",
     "formula": "同じ積み上げで単価を他工場の最小・最大に置き換え。採用値ではない"},
    {"label": "参考: 他工場参照幅の単価で積んだ場合の high", "value": [r2(ref_high_lo), r2(ref_high_hi)], "unit": "人時",
     "formula": "同上（high の積み上げ）。採用値ではない"},
]

outside = [t for t in own if not own[t]["inside"]]
out = {
    "id": "S13",
    "name": "道内の整備工場間で匿名化した実績の共有",
    "base_method": "B",
    "factors": ["HK01", "AG01"],
    "algorithm": [
        "手順1: 基準 1.7 人時を出発点にする",
        "手順2: 自工場の実績から、タグ別に1本（ローターは1側）あたりの人時を hours/count で求める。固着対応は現車と同じブレーキ周り腐食グレードの記録に絞る",
        f"手順3: 実績が{min_rec}件以上ならその最小/中央値/最大を採用、足りなければ整備士暫定値を採用",
        "手順4: 他工場（shop_X, shop_Y）の中央値を並べて参照幅と件数加重平均を出す。採用はしない",
        "手順5: 現車の締結部を fastener_risk_rule で 通常/固着対応/折れ込み/不明 に分類",
        "手順6: 採用単価で U3 の表どおりに積み上げ（中は low 0・typical/high 固着対応。重は全区分で固着対応、high のみ さらに折れ+ねじ山。未確認と ローター固着は high のみ）",
        "手順7: 人時 = 1.7 + 追加人時",
        "手順8: 浸透待ち（U5）は固着対応を含む区分の経過時間にだけ足す",
        "手順9: 他工場の参照幅で同じ積み上げをした参考人時を並べ、自工場値の妥当性を確認する",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "historical_records（自工場）", "value": f"{len(SC['historical_records'])}件", "status": "確認済み"},
        {"key": "other_shops_anonymized", "value": {s: others[s] for s in shops}, "status": "申告"},
        {"key": "condition.fasteners", "value": cnt, "status": "申告"},
        {"key": "condition.rotor_hub_seizure", "value": "未確認", "status": "不明"},
        {"key": "shop_policy.min_records_for_reference", "value": min_rec, "status": "仮定"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "タグ別の自工場採用値と他工場参照幅", "value": {t: tag_rows(t) for t in own}, "unit": ""},
            {"label": "他工場の参照幅で積んだ typical", "value": [r2(ref_typ_lo), r2(ref_typ_hi)], "unit": "人時"},
        ],
        "note": ("採用値は自工場の実績（足りないタグは整備士暫定値）。他工場の値は参照幅としてだけ示し、"
                 "自工場値には使っていない。自工場typicalが参照幅の外のタグ: "
                 + (("、".join(outside)) if outside else "なし")
                 + "。設備・技量・課金方針の差があるため、外れても自動では直さず整備士が理由を確認する。"),
    },
    "assumptions": [
        "仮定: 単価は記録ごとの hours/count を求め、その最小/中央値/最大を low/typical/high とする。",
        f"仮定: 固着対応の単価は現車のブレーキ周り腐食グレード（{BRAKE_GRADE}）と同じ記録（n={sz['n']}）だけで集計する。層別は固着対応のみで、ボルト折れ・ローター固着は全記録を使う（ローターはグレード{BRAKE_GRADE}に絞ると2件で基準未満になるため）。",
        f"仮定: 実績が{min_rec}件未満のタグ（ボルト折れ）は整備士暫定値を使う。",
        "仮定: SPEC U3 に従う。折れ込みの可能性（重）は全区分で固着対応、high のみ固着対応に加えて抜き取り + ねじ山修正（1本につき1か所、折れは固着対応を試みたあとの別工程）。中は low に入れない。",
        "仮定: ローター固着は未確認のため high のみ、左右2側。",
        "仮定: 他工場の値は将来の共有を想定した架空値。共有の同意・形式統一は未整備。",
        "仮定: 経過時間は1人作業で直列に進め、浸透待ちは固着対応を含む区分（low/typical/high それぞれ）に1回だけ加える。",
    ],
    "unknowns": [
        "スライドボルト4本は錆が未確認。low・typical に入れず high に固着対応を含めた。",
        "ローター固着は分解前で不明。high のみ。",
        "他工場の設備・技量・課金方針・車種構成が自工場と同じかは不明。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S13.json").write_text(text + "\n", encoding="utf-8")
print(text)
