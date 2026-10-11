#!/usr/bin/env python3
"""S12 整備士の暫定値を実績で更新する補正表

反映する要因: 全般（原因タグ付きの追加工程。HK01/HK02/HK03/AG01/AG03 に対応する工程を、実績が取れる範囲で扱う）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. 補正表 v1 = mechanic_provisional_add_ops の整備士の暫定値（status「仮定」。承認の記録はない）。
 3. historical_records の tags から、原因タグを追加工程に対応づけて「1本・1側・1か所あたり」の
    人時を作る。 tag.hours / tag.count（count がなければ入庫1回分の hours）。
      固着対応 -> FX-SEIZE / ボルト折れ -> FX-BROKEN / ローター固着 -> FX-ROTOR
      雪下ろし -> PRE-SNOW / 氷塊除去 -> PRE-ICE / ブーツ交換 -> AG-BOOT
    原因の記録がない「その他」、実績タグのない工程（FX-THREAD 等）は使わない。
 4. 工程ごとに、実績の件数 n（その工程のタグがある「記録」の数。本数・側数ではない）、
    1記録あたりの1単位人時の中央値、最小、最大を求める。
 5. 補正表 v2（候補）を作る。
      n < min_records_for_reference（3件）: 更新せず v1 のまま「参考」表示（実績は併記するだけ）
      n >= 3: docs §4 S12 のとおり実績の中央値と範囲で更新する（重み付けはしない）。
        typical は実績の中央値、low は実績の最小、high は実績の最大。
      v2 は自動適用しない。整備士が承認するまで採用値は v1（暫定値）。
 6. 今回の観察（condition）を追加工程の数量に変換する。
      雪下ろし1回、氷塊2か所は全範囲。締結部は SPEC U3 の表に従う。
        low: 重2本に FX-SEIZE low / typical: 中2本+重2本に FX-SEIZE typical
        high: 中+重+未確認の計8本に FX-SEIZE high、重2本に FX-BROKEN high と FX-THREAD high
        （折れ込みは固着対応を試みたあとの別工程。FX-THREAD は実績タグがないので v1 の暫定値）。
      ローター固着2側・右ブーツは未確認のため high のみ。左ブーツ硬化は観察済みなので全範囲で1個。
      サブフレームは J1・J2 で外さない作業範囲外（U4）。high に入れず、unknowns に作業範囲の拡大（AG04）として書く。
 7. 同じ数量に v1 と v2 を当てはめ、追加人時を 数量 x 単価 で積み上げる（倍率は使わない）。
 8. 暫定値（v1）を採用値とし、人時 = 1.7 + v1 の追加人時。v2 は比較用に並べる。
 9. 経過時間（U5）: 氷塊除去を含めば融解待ち、FX-SEIZE を含めば浸透待ちを、その範囲の経過時間に足す
    （elapsed_waits から読む。人時には入れない）。FX-HUBCLEAN は S12 の範囲外なので防錆乾燥は足さない。
    下回り洗浄（PRE-WASH）は実績タグがなく案の範囲外のため、人時にも入れない。
10. SPEC.md の形で JSON を標準出力と results/S12.json に出す。丸めは出力時のみ。
"""
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
v1 = SC["mechanic_provisional_add_ops"]
min_n = SC["shop_policy"]["min_records_for_reference"]
RULE_VERSION = "S12-table-v1"  # 補正表の版識別子（README rule_version に対応させる想定）

TAG_TO_OP = {"固着対応": "FX-SEIZE", "ボルト折れ": "FX-BROKEN", "ローター固着": "FX-ROTOR",
             "雪下ろし": "PRE-SNOW", "氷塊除去": "PRE-ICE", "ブーツ交換": "AG-BOOT"}

# --- 手順3-4: 実績から1単位あたり人時を作る ---
samples = {op: [] for op in TAG_TO_OP.values()}
for rec in SC["historical_records"]:
    for tag, v in rec["tags"].items():
        op = TAG_TO_OP.get(tag)
        if op is None:
            continue
        samples[op].append((rec["id"], v["hours"] / v.get("count", 1)))

# --- 手順5: 補正表 v2 ---
v2 = {}
table = []
for op in TAG_TO_OP.values():
    vals = [h for _, h in samples[op]]
    n = len(vals)
    old = {r: v1[op][r] for r in RANGES}
    if n >= min_n:
        act = {"low": min(vals), "typical": statistics.median(vals), "high": max(vals)}
        new = dict(act)
        # 範囲の順序が崩れないようにする
        new["low"] = min(new["low"], new["typical"])
        new["high"] = max(new["high"], new["typical"])
        status = "更新候補"
    else:
        act = {r: (None if n == 0 else {"low": min(vals), "typical": statistics.median(vals), "high": max(vals)}[r]) for r in RANGES}
        new = dict(old)
        status = "参考（%d件のため更新しない）" % n
    v2[op] = new
    table.append({"op": op, "name": v1[op]["name"], "n": n, "status": status,
                  "v1": {r: r2(old[r]) for r in RANGES},
                  "actual": {r: (None if act[r] is None else r2(act[r])) for r in RANGES},
                  "v2": {r: r2(new[r]) for r in RANGES}})

# --- 手順6: 今回の観察 -> 数量 ---
fs = SC["condition"]["fasteners"]
rule = SC["condition"]["fastener_risk_rule"]
def risk(f):
    for k in ("未確認", "重", "中", "軽"):
        if f["rust"].startswith(k):
            return rule[k]
    return rule["未確認"]
n_mid = sum(f.get("count", 1) for f in fs if risk(f) == rule["中"])
n_heavy = sum(f.get("count", 1) for f in fs if risk(f) == rule["重"])
n_unk = sum(f.get("count", 1) for f in fs if risk(f).startswith("不明"))
ice = SC["condition"]["ice_in_wheel_house"]["locations"]
unk_rotor_sides = 2  # 仮定: ローター固着は未確認のため左右とも high に含める
boot_left, boot_right_unknown = 1, 1

# SPEC U3: 重は low も FX-SEIZE、中は typical から、未確認は high のみ。折れ込みと FX-THREAD は重の high のみ
qty = {
    "low":     {"PRE-SNOW": 1, "PRE-ICE": ice, "FX-SEIZE": n_heavy, "AG-BOOT": boot_left},
    "typical": {"PRE-SNOW": 1, "PRE-ICE": ice, "FX-SEIZE": n_mid + n_heavy, "AG-BOOT": boot_left},
    "high":    {"PRE-SNOW": 1, "PRE-ICE": ice, "FX-SEIZE": n_mid + n_heavy + n_unk,
                "FX-BROKEN": n_heavy, "FX-THREAD": n_heavy,
                "FX-ROTOR": unk_rotor_sides,
                "AG-BOOT": boot_left + boot_right_unknown},
}

# --- U5: 経過時間の待機（人時に入れない） ---
waits = SC["elapsed_waits"]
elapsed = {}
for r in RANGES:
    e = 0.0
    if qty[r].get("PRE-ICE"):
        e += waits["thaw_wait_hours"]
    if qty[r].get("FX-SEIZE"):
        e += waits["penetrant_soak_wait_hours"]
    elapsed[r] = e

# --- 手順7: v1 と v2 を同じ数量に当てはめる ---
def apply(tbl):
    out = {}
    for r in RANGES:
        out[r] = sum(q * (tbl[op][r] if op in tbl else v1[op][r]) for op, q in qty[r].items())
    return out
add_v1 = apply({op: v1[op] for op in v1})
add_v2 = apply(v2)
diff = {r: add_v2[r] - add_v1[r] for r in RANGES}
labor = {r: base + add_v1[r] for r in RANGES}          # 手順8: 採用は v1
labor_v2 = {r: base + add_v2[r] for r in RANGES}

seize_row = next(t for t in table if t["op"] == "FX-SEIZE")
n_updated = sum(1 for t in table if t["status"] == "更新候補")

inter = [
    {"label": "実績から更新候補になった工程数", "value": n_updated, "unit": "工程",
     "formula": f"n >= {min_n} の工程数（全{len(table)}工程中。残りは参考のみ）"},
    {"label": "FX-SEIZE 実績の件数と中央値", "value": [seize_row["n"], seize_row["actual"]["typical"]], "unit": "件, 人時/本",
     "formula": "各記録（n は記録数）の 固着対応 hours / count の中央値"},
    {"label": "FX-SEIZE typical（v1 -> v2）", "value": [seize_row["v1"]["typical"], seize_row["v2"]["typical"]], "unit": "人時/本",
     "formula": "v2 = 実績の中央値（n>=3。重み付けなし）"},
    {"label": "FX-SEIZE の本数（low/typical/high）", "value": [qty[r].get("FX-SEIZE", 0) for r in RANGES], "unit": "本",
     "formula": f"U3: low=重{n_heavy} / typical=中{n_mid}+重{n_heavy} / high=中+重+未確認{n_unk}。重{n_heavy}本の high には FX-BROKEN・FX-THREAD も {n_heavy} 本分"},
    {"label": "追加人時 v1 暫定（low/typical/high）", "value": [r2(add_v1[r]) for r in RANGES], "unit": "人時",
     "formula": "Σ 数量 x v1単価（雪下ろし・氷塊・固着・折れ込み抜き取り・ねじ山修正・ローター・ブーツ）"},
    {"label": "v2 - v1 の差（low/typical/high）", "value": [r2(diff[r]) for r in RANGES], "unit": "人時",
     "formula": "同じ数量 x v2単価の追加人時 - 追加人時v1（v2 は未承認のため採用値には入れない）"},
    {"label": "採用値の人時（v1・暫定値）", "value": [r2(labor[r]) for r in RANGES], "unit": "人時",
     "formula": f"{base} + 追加人時v1（暫定値）"},
    {"label": "経過時間の待機（low/typical/high）", "value": [r2(elapsed[r]) for r in RANGES], "unit": "時間",
     "formula": f"氷塊除去を含めば融解待ち {waits['thaw_wait_hours']} + FX-SEIZE を含めば浸透待ち {waits['penetrant_soak_wait_hours']}（人時に入れない。経過時間 = 待機のみ）"},
]

out = {
    "id": "S12",
    "name": "整備士の暫定値を実績で更新する補正表",
    "base_method": "A/B",
    "factors": ["全般（HK01, HK02, HK03, AG01, AG03 の追加工程のうち実績タグがあるもの）"],
    "algorithm": [
        "手順1: 基準 1.7 人時を出発点にする",
        "手順2: 補正表 v1 = 整備士の暫定値（仮定。承認の記録なし）",
        "手順3: 実績の原因タグを追加工程に対応づけ、1本・1側・1か所あたり人時にする",
        f"手順4: 工程ごとに件数・中央値・最小・最大を求める（{min_n}件未満は参考のみ）",
        "手順5: n>=3 の工程は実績の中央値と範囲（最小・最大）で補正表 v2 候補を作る（自動適用しない）",
        "手順6: 今回の観察を追加工程の数量に変換（締結部は U3: 重は low も固着対応、high に折れ込み+ねじ山修正、未確認は high のみ。サブフレームは作業範囲外）",
        "手順7: 同じ数量に v1 と v2 を当てはめ、追加人時を比べる",
        "手順8: 暫定値 v1 を採用値とし、人時 = 1.7 + v1の追加人時",
        "手順9: 経過時間 = 融解待ち（氷塊除去を含む範囲）+ 浸透待ち（FX-SEIZE を含む範囲）。下回り洗浄は実績タグがなく案の範囲外",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "mechanic_provisional_add_ops（実績タグのある6工程）", "value": {op: {r: v1[op][r] for r in RANGES} for op in TAG_TO_OP.values()}, "status": "仮定"},
        {"key": "historical_records（タグ付き工程の件数）", "value": {op: len(samples[op]) for op in samples}, "status": "確認済み"},
        {"key": "condition.fasteners（中/重/未確認の本数）", "value": {"中": n_mid, "重": n_heavy, "未確認": n_unk}, "status": "申告"},
        {"key": "condition.ice_in_wheel_house.locations", "value": ice, "status": "確認済み"},
        {"key": "condition.underbody_rust_grade.subframe", "value": "未確認（対応する追加工程なし。数量に入れていない）", "status": "不明"},
        {"key": "condition.rotor_hub_seizure", "value": "未確認", "status": "不明"},
        {"key": "condition.slide_pin_boots", "value": "左: 問題あり（硬化） / 右: 未確認", "status": "確認済み"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(labor[r] + elapsed[r]) for r in RANGES},  # 経過時間 = 人時 + 待機（U5）
        "other_outputs": [
            {"label": "補正表 v1/v2 の比較（実績件数つき）", "value": table, "unit": "人時/単位"},
            {"label": "v2 候補を当てた場合の人時（採用しない）", "value": {r: r2(labor_v2[r]) for r in RANGES}, "unit": "人時"},
            {"label": "採用した補正表の版", "value": {"rule_version": RULE_VERSION, "kind": "整備士の暫定値（未承認）", "approved_by": None, "approved_on": None}, "unit": ""},
            {"label": "この案の範囲外としたもの", "value": ["サブフレーム（J1・J2 で外さない作業範囲外。腐食があれば AG04 として見積もり変更）", "下回り洗浄 PRE-WASH（実績タグがなく案の範囲外）", "FX-THREAD は実績タグがないので v1 の暫定値を使い、補正表の更新対象外"], "unit": ""},
        ],
        "note": "v2 は実績の中央値・範囲で更新した候補で、整備士の承認までは使わない。採用値は暫定値 v1 に今回の観察を当てた値。high はこの案の範囲（実績タグのある追加工程と FX-THREAD）での上限で、重の折れ込み（抜き取り+ねじ山修正）、未確認の締結部・ローター・右ブーツを含む。サブフレームと下回り洗浄は範囲外。経過時間は融解待ちと浸透待ち。実績の件数が少ない工程は「参考」で、統計的な精度保証ではない。",
    },
    "assumptions": [
        "仮定: n は実績の記録数（1記録=1件。FX-SEIZE は固着対応タグのある記録数で、ボルト本数ではない）。1単位あたり人時は記録ごとに hours / count で作る。",
        f"仮定: 実績が {min_n} 件未満の工程（min_records_for_reference）は更新せず参考表示にとどめる。",
        "仮定: v2 の low は実績の最小、typical は中央値、high は実績の最大を使う。",
        "仮定: 締結部は SPEC U3 に従う。重（頭部腐食）は low も固着対応で、high は固着対応に加え折れ込みの抜き取り（FX-BROKEN）とねじ山修正（FX-THREAD）。中は typical から、未確認は high のみ。FX-THREAD は実績タグがないので v1 の暫定値を使う。",
        "仮定: 折れ込みとねじ山修正は重の締結部1本につき1回。",
        "仮定: 待機は elapsed_waits を使い、氷塊除去を含む範囲に融解待ち、FX-SEIZE を含む範囲に浸透待ちを足す。S12 は FX-HUBCLEAN を扱わないので防錆乾燥は足さない。",
        "仮定: 下回り洗浄（PRE-WASH）は実績タグがなく案の範囲外のため、人時に入れない。",
        "仮定: ローター固着は U3 の表（締結部）ではなく U2（範囲内の未確認項目は high の上限に含める）を根拠に、high に左右2側を含める。右ブーツも同じく U2 により high のみ。",
        "仮定: 原因の記録がない「その他」、他案の要因（融解待ち、タイヤ重量等）は使わない。同一車両の前回実績は補正表に特別扱いしない。",
        "仮定: 地域・年式・走行距離からは加算も区分分けもしない（実績が溜まった段階で整備士が判断）。",
    ],
    "unknowns": [
        "スライドボルト4本、ローター固着、右ブーツは未確認で、low・typical に入れず high に含めた。",
        "サブフレームは未確認で、J1・J2 では外さないため作業範囲外とし high に入れていない。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る。",
        "FX-THREAD は実績タグがなく、v1 の暫定値のまま（補正表の更新対象外）。",
        "分解後の音声メモ（S25 の入力）は見積もり時点の観察ではなく、S25 の領分のため使っていない。S12 は入庫時の観察で数量を作る。",
        "実績の記録は12件で、工程によっては1〜2件。v2 の信頼性は低く、冬季・腐食程度で区分を分けるかは未判断。",
        "R10 の「その他 0.55 人時」は原因の記録がなく、補正表に反映できない。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S12.json").write_text(text + "\n", encoding="utf-8")
print(text)
