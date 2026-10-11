#!/usr/bin/env python3
"""S30 3方式の根拠を並べる比較画面

SPEC「解釈の統一（第2版）」U1〜U9 に合わせた版。

反映する要因（列ごとに異なる）:
  案A: 基準 1.7 + 締結部の固着・折れ込み（U3 の typical / high）
  案B: S08 と同じ規則。J1+J2 の類似実績（R08〜R11 の4件、同一車両の前回を含む）の中央値・最小・最大
  案C: 工程積み上げ。前処理（雪下ろし・氷塊除去・下回り洗浄）、締結部（U3）、ハブ錆落とし、
       スライドピンブーツ、未確認のローター固着（high のみ）。待機は U5 で経過時間にだけ足す

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. 案A: 基準 1.7 に U3 の締結部の人時だけを足す。
      low  = 重の FX-SEIZE low（中・未確認は 0）
      typical = 重＋中の FX-SEIZE typical
      high = 重＋中＋未確認の FX-SEIZE high + 重の FX-BROKEN high + 重の FX-THREAD high
    案Aは前処理・ブーツ・ハブ・ローター・タイヤを扱わない（それらは案Cの範囲）。
 3. 案B: S08 と同じ規則。作業範囲が J1+J2 と一致する historical_records をすべて採用し
      （同一車両の前回 R11 も含める）、actual の中央値を typical、最小・最大を low・high とする。
      件数が min_records_for_reference 未満なら「根拠なし」。
 4. 案C: 共有工程の重複を控除した工程合計 1.7 に、前処理、U3 の締結部、ハブ錆落とし、ブーツ、
      high のみ未確認のローター固着・右ブーツを積む。タイヤ重量の差（U6）は加算しない。
      待機は U5 に従い、FX-SEIZE を含めたら浸透待ち、FX-HUBCLEAN を含めたら防錆乾燥、
      氷塊除去を含めたら融解待ちを経過時間にだけ足す。
 5. 3方式を平均しない。result.labor_hours: low = 3方式の low の最小、high = 3方式の high の最大、
      typical = 案A の typical。
 6. 各列に 根拠・不足情報・錆と固着の反映状態 を付け、other_outputs に並べる。
 7. 人時は丸めずに計算し、出力時だけ小数第2位に丸める。結果を標準出力と results/S30.json に出す。
"""
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
cond = SC["condition"]
waits = SC["elapsed_waits"]
min_n = SC["shop_policy"]["min_records_for_reference"]
policy_wash = ops["PRE-WASH"]["policy"]


def op_sum(items, rng):
    """items: [(op, 数)] -> rng の人時合計"""
    return sum(ops[o][rng] * n for o, n in items)


# --- 今回の観察 -> 単位数 ---
HUB_GRADE_THRESHOLD = 2  # 仮定: 錆グレード2（進行錆）以上でハブ錆落としを行う
BRAKE_SIDES = 2          # 前ブレーキは左右2側
fast = [f for f in cond["fasteners"] if f["job"] == "J2"]
n_heavy = sum(1 for f in fast if f["rust"].startswith("重"))
n_mid = sum(1 for f in fast if f["rust"].startswith("中"))
n_unk = sum(1 for f in fast if f["rust"].startswith("未確認"))
n_ice = cond["ice_in_wheel_house"]["locations"]
boot_left = 1 if cond["slide_pin_boots"]["left"].startswith("問題あり") else 0
boot_right_unknown = 1 if cond["slide_pin_boots"]["right"].startswith("未確認") else 0
rotor_unknown_sides = BRAKE_SIDES if cond["rotor_hub_seizure"]["state"] == "未確認" else 0
hub_grade = cond["underbody_rust_grade"]["wheel_hub"]
hub_sides = BRAKE_SIDES if (hub_grade or 0) >= HUB_GRADE_THRESHOLD else 0
snow = 1 if cond["snow_on_body"]["state"] == "問題あり" else 0


def u3(rng):
    """SPEC U3 の締結部の表（重・中・未確認）-> [(op, 数)]"""
    if rng == "low":
        return [("FX-SEIZE", n_heavy)]
    if rng == "typical":
        return [("FX-SEIZE", n_heavy + n_mid)]
    return [("FX-SEIZE", n_heavy + n_mid + n_unk), ("FX-BROKEN", n_heavy), ("FX-THREAD", n_heavy)]


def count(items, op):
    return sum(n for o, n in items if o == op)


# ========== 案A: 1.7 + U3 ==========
a_items = {r: u3(r) for r in RANGES}
a_add = {r: op_sum(a_items[r], r) for r in RANGES}
A = {r: base + a_add[r] for r in RANGES}
a_wait = {r: waits["penetrant_soak_wait_hours"] if count(a_items[r], "FX-SEIZE") else 0.0 for r in RANGES}  # U5
A_el = {r: A[r] + a_wait[r] for r in RANGES}

# ========== 案B: S08 と同じ規則 ==========
scope = {j["id"] for j in SC["jobs"]}
sim = [x for x in SC["historical_records"] if set(x["jobs"]) == scope]  # R08〜R11（同一車両 R11 を含む）
acts = [x["actual"] for x in sim]
b_ok = len(sim) >= min_n
B = {"low": min(acts), "typical": statistics.median(acts), "high": max(acts)} if b_ok else None
b_ids = [x["id"] for x in sim]
same_ids = [x["id"] for x in sim if x.get("same_vehicle")]
rust3 = [x["id"] for x in sim if x["brake_rust"] == cond["underbody_rust_grade"]["brake_area"]]
rust_none = [x["id"] for x in sim if x["brake_rust"] is None]

# ========== 案C: 工程積み上げ ==========
seen, c_base = set(), 0.0
for job in SC["jobs"]:
    for o in job["included_operations"]:
        if o["shared"] and o["op"] in seen:
            continue
        seen.add(o["op"])
        c_base += o["hours"]
c_common = [("PRE-SNOW", snow), ("PRE-ICE", n_ice), ("PRE-WASH", 1), ("FX-HUBCLEAN", hub_sides), ("AG-BOOT", boot_left)]
c_items = {
    "low": c_common + u3("low"),
    "typical": c_common + u3("typical"),
    "high": c_common + u3("high") + [("FX-ROTOR", rotor_unknown_sides), ("AG-BOOT", boot_right_unknown)],
}
c_add = {r: op_sum(c_items[r], r) for r in RANGES}
C = {r: c_base + c_add[r] for r in RANGES}


def c_wait(rng):
    it = c_items[rng]
    w = 0.0
    if count(it, "PRE-ICE"):
        w += waits["thaw_wait_hours"]
    if count(it, "FX-SEIZE"):
        w += waits["penetrant_soak_wait_hours"]
    if count(it, "FX-HUBCLEAN"):
        w += waits["rustproof_dry_wait_hours"]["winter_hypothesis"]
    return w


c_waits = {r: c_wait(r) for r in RANGES}
C_el = {r: C[r] + c_waits[r] for r in RANGES}
# 請求人時は下回り洗浄を除く（U7: labor_hours は実作業人時）
C_bill = {r: C[r] - ops["PRE-WASH"][r] for r in RANGES}

# ========== 提示範囲 ==========
typicals = {"A": A["typical"], "B": B["typical"] if B else None, "C": C["typical"]}
tv = [v for v in typicals.values() if v is not None]
typ_low, typ_high = min(tv), max(tv)
methods = [m for m in (A, B, C) if m]
labor = {"low": min(m["low"] for m in methods), "typical": A["typical"], "high": max(m["high"] for m in methods)}
el_methods = [A_el, C_el]  # 案Bは経過時間を持たない
elapsed = {"low": min(m["low"] for m in el_methods), "typical": A_el["typical"], "high": max(m["high"] for m in el_methods)}

# 感度: 重の折れ込みを typical に入れた場合。折れ込みは固着対応のあとの別工程（U3）なので FX-BROKEN typical をそのまま加算する
broken_shift = n_heavy * ops["FX-BROKEN"]["typical"]
sens = {"A": A["typical"] + broken_shift, "C": C["typical"] + broken_shift}

fmt = lambda d: {r: r2(d[r]) for r in RANGES} if d else None
n_a_typ = count(a_items["typical"], "FX-SEIZE")
columns = [
    {
        "column": "案A 基準＋締結部の補正",
        "labor_hours": fmt(A),
        "elapsed_hours": fmt(A_el),
        "basis": f"基準 {base} 人時 + 締結部の補正（SPEC U3）。typical は重{n_heavy}本＋中{n_mid}本の固着対応 {n_a_typ}本 = +{r2(a_add['typical'])}",
        "missing": [f"スライドボルト{n_unk}本の錆が未確認（high のみ）",
                    "前処理・ブーツ・ハブ錆落とし・ローター固着は案Aの範囲外（案Cで扱う）",
                    "サブフレーム腐食が未確認（範囲外。腐食があれば作業範囲の拡大として見積もりを変更し、顧客の了承を得る）"],
        "rust_fastener_reflection": f"重{n_heavy}本は low で FX-SEIZE low、typical で固着対応、high で折れ込み＋ねじ山修正まで反映。中{n_mid}本は typical から、未確認{n_unk}本は high のみ（0 と確定していない）",
    },
    {
        "column": "案B J1+J2 の類似実績",
        "labor_hours": fmt(B),
        "elapsed_hours": None,
        "basis": (f"J1+J2 実績 {len(sim)}件（{', '.join(b_ids)}。同一車両の {', '.join(same_ids)} を含む）の actual 中央値。範囲は最小〜最大" if b_ok
                  else f"実績 {len(sim)}件で基準 {min_n}件に満たない"),
        "missing": [f"同一車両の前回({', '.join(same_ids)})は錆グレードなど状態が今回と異なる",
                    f"{', '.join(rust_none)} は錆グレード不明", f"錆グレードが今回と同じの実績は {len(rust3)}件（{', '.join(rust3)}）のみ",
                    "実績に含まれた要因の内訳を分解していない"] if b_ok else ["根拠なし"],
        "rust_fastener_reflection": "実績の合計に混ざる形での間接的な反映のみ。今回の個別の固着本数・未確認箇所は反映できない",
    },
    {
        "column": "案C 工程積み上げ",
        "labor_hours": fmt(C),
        "elapsed_hours": fmt(C_el),
        "basis": f"共有工程の重複を控除した工程合計 {r2(c_base)} 人時 + 追加工程 +{r2(c_add['typical'])}（前処理・締結部・ハブ錆落とし・ブーツ）",
        "missing": [f"スライドボルト{n_unk}本・右ブーツ・ローター固着が未確認（high のみ）",
                    "サブフレーム腐食が未確認（範囲外。腐食があれば作業範囲の拡大として見積もりを変更し、顧客の了承を得る）",
                    "工程ごとの実測人時は無く、暫定値を使用"],
        "rust_fastener_reflection": f"締結部は案Aと同じ U3 の表。ハブ錆グレード{hub_grade}（{hub_sides}側の錆落とし）を工程として反映。未確認は high のみ",
    },
]

inter = [
    {"label": "案A 締結部の補正（typical）", "value": r2(a_add["typical"]), "unit": "人時",
     "formula": f"FX-SEIZE typical {ops['FX-SEIZE']['typical']} x (重{n_heavy} + 中{n_mid})本"},
    {"label": "案A 人時", "value": r2(A["typical"]), "unit": "人時",
     "formula": (f"typical = {base} + 補正。low {r2(A['low'])} = {base} + FX-SEIZE low {ops['FX-SEIZE']['low']}x{n_heavy}。"
                 f"high {r2(A['high'])} = {base} + FX-SEIZE high {ops['FX-SEIZE']['high']}x{n_heavy + n_mid + n_unk}(重＋中＋未確認)"
                 f" + FX-BROKEN high {ops['FX-BROKEN']['high']}x{n_heavy} + FX-THREAD high {ops['FX-THREAD']['high']}x{n_heavy}")},
    {"label": "案B 類似実績の件数", "value": len(sim), "unit": "件",
     "formula": "作業範囲が J1+J2 と一致する historical_records の数（S08 と同じ。同一車両を含む）"},
    {"label": "案B 実績 actual の中央値", "value": r2(B["typical"]) if B else None, "unit": "人時",
     "formula": f"median({acts}) 範囲 {min(acts)}〜{max(acts)}"},
    {"label": "案C 共有工程の重複控除後の工程合計", "value": r2(c_base), "unit": "人時",
     "formula": "J1 + J2 の工程合計 2.0 - 重複(OP-LIFT 0.1 + OP-WHEEL-F2 0.2)"},
    {"label": "案C 人時", "value": r2(C["typical"]), "unit": "人時",
     "formula": (f"typical = {r2(c_base)} + 雪下ろし{ops['PRE-SNOW']['typical']}x{snow} + 氷塊{ops['PRE-ICE']['typical']}x{n_ice}"
                 f" + 下回り洗浄{ops['PRE-WASH']['typical']} + 固着{ops['FX-SEIZE']['typical']}x{n_heavy + n_mid}"
                 f" + ハブ錆落とし{ops['FX-HUBCLEAN']['typical']}x{hub_sides} + 左ブーツ{ops['AG-BOOT']['typical']}x{boot_left}。"
                 f"low {r2(C['low'])} / high {r2(C['high'])}（high は U3 の high に FX-ROTOR high x{rotor_unknown_sides}、右ブーツ high x{boot_right_unknown} を追加）")},
    {"label": "案C 経過時間の待機（typical）", "value": r2(c_waits["typical"]), "unit": "時間",
     "formula": f"融解待ち{waits['thaw_wait_hours']} + 浸透待ち{waits['penetrant_soak_wait_hours']} + 防錆乾燥{waits['rustproof_dry_wait_hours']['winter_hypothesis']}（U5。人時に入れない）"},
    {"label": "提示範囲（3方式の low の最小〜high の最大）", "value": f"{r2(labor['low'])}〜{r2(labor['high'])}", "unit": "人時",
     "formula": f"min(A,B,C の low) = {r2(labor['low'])}、max(A,B,C の high) = {r2(labor['high'])}。3方式の typical の幅は {r2(typ_low)}〜{r2(typ_high)}。平均は取らない"},
]

inputs = [
    {"key": "base_totals.deduplicated_base", "value": base, "status": "仮定"},
    {"key": "condition.fasteners (J2)", "value": f"重{n_heavy} / 中{n_mid} / 未確認{n_unk}", "status": "確認済み"},
    {"key": "condition.ice_in_wheel_house.locations", "value": n_ice, "status": "確認済み"},
    {"key": "condition.snow_on_body", "value": cond["snow_on_body"]["detail"], "status": "確認済み"},
    {"key": "condition.slide_pin_boots", "value": f"左: {cond['slide_pin_boots']['left']} / 右: {cond['slide_pin_boots']['right']}", "status": "確認済み"},
    {"key": "condition.rotor_hub_seizure", "value": cond["rotor_hub_seizure"]["state"], "status": "不明"},
    {"key": "condition.underbody_rust_grade.wheel_hub", "value": hub_grade, "status": "確認済み"},
    {"key": "condition.underbody_rust_grade.subframe", "value": None, "status": "不明"},
    {"key": "historical_records (J1+J2)", "value": b_ids, "status": "申告"},
    {"key": "vehicle.first_registration", "value": SC["vehicle"]["first_registration"], "status": "確認済み（この案では未使用: 年式だけで工数を増やさない）"},
    {"key": "vehicle.odometer_km", "value": SC["vehicle"]["odometer_km"], "status": "確認済み（この案では未使用: 走行距離だけで工数を増やさない）"},
]

out = {
    "id": "S30",
    "name": "3方式の根拠を並べる比較画面",
    "base_method": "A/B/C 併記",
    "factors": ["HK01", "HK02", "HK03", "AG01", "AG03"],
    "algorithm": [
        "手順1: scenario.json を読み、基準 1.7 人時を出発点にする。",
        "手順2: 案A = 1.7 + 締結部の補正（U3 の typical / high）。未確認の締結部は high のみ。",
        "手順3: 案B = S08 と同じ規則。J1+J2 の類似実績（R08〜R11 の4件、同一車両を含む）の actual の中央値・最小・最大。",
        "手順4: 案C = 重複控除後の工程 1.7 + 前処理 + 締結部（U3）+ ハブ錆落とし + ブーツ。待機（U5）は経過時間のみ。",
        "手順5: 3方式を平均しない。提示範囲 = 3方式の low の最小〜high の最大、typical は案A。",
        "手順6: 各列に根拠・不足情報・錆と固着の反映状態を付けて並べる。担当者が選び理由を残す。",
    ],
    "inputs": inputs,
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "3方式の比較（根拠・不足情報・錆と固着の反映）", "value": columns, "unit": "A/B/C の3列"},
            {"label": "3方式の typical の幅（比較用）", "value": [r2(typ_low), r2(typ_high)], "unit": "人時"},
            {"label": "感度: 重の2本を折れ込みとして typical に入れた場合の typical", "value": {"案A": r2(sens["A"]), "案C": r2(sens["C"])}, "unit": "人時"},
            {"label": "案C 請求人時（下回り洗浄を除く）", "value": fmt(C_bill), "unit": "人時"},
            {"label": "下回り洗浄（請求しない）", "value": policy_wash, "unit": ""},
            {"label": "担当者の選択と理由", "value": "未選択（担当者が A/B/C のいずれか、または手入力を選び、理由を残す）", "unit": ""},
        ],
        "note": ("担当者が方式を選ぶ前の「提示範囲」。low は3方式の low の最小、high は3方式の high の最大（この3方式の範囲での上限）で、typical には案Aを置いた（3方式を平均していない）。"
                 "案Aは基準＋締結部（U3）、案Bは S08 と同じ類似実績、案Cは前処理を含む工程積み上げで、扱う範囲が違うため各列の根拠と不足情報を並べて見比べる。"
                 "3方式の typical の幅は other_outputs に別に出す。経過時間の範囲は案Aと案Cから取り、案Bは経過時間を持たない。"),
    },
    "assumptions": [
        "仮定: 締結部は SPEC U3 の表に従う（重は low で FX-SEIZE low、typical で固着対応、high で FX-SEIZE high＋折れ込み＋ねじ山修正。中は typical から、未確認は high のみ）。折れ込みは固着対応のあとの別工程で二重計上ではない。",
        "仮定: 案Aは個別指示どおり 1.7＋U3 だけとし、前処理・ブーツ・ハブ錆落とし・ローター固着は加えない（案Cの範囲）。",
        "仮定: 案Bは S08 と同じ規則で、作業範囲が J1+J2 の事例をすべて採用する（同一車両の前回 R11 を含む）。",
        f"仮定: ハブ錆落としはグレード{HUB_GRADE_THRESHOLD}以上、前ブレーキは{BRAKE_SIDES}側とした。",
        "仮定: 案Cの追加工程の単価は整備士暫定値（mechanic_provisional_add_ops）を使う。",
        "仮定: 案Cは前処理（雪下ろし・氷塊除去・下回り洗浄）を工程に含める。下回り洗浄は請求しないが実作業なので labor_hours に入れ、請求人時は other_outputs に別に出す（U7）。",
        "仮定: タイヤ重量による運搬人数の差は S07 の範囲（U6）。本画面では共通基準 1.7 のまま扱う。",
        "仮定: factors の HK01・HK02・HK03・AG01・AG03 は、案A（基準・締結部）・案B（類似実績）・案C（工程積み上げ）が使う要因の合併。S30 の docs 上の対象は「全般」。",
        "仮定: 経過時間 = 人時 + 待機（U5）。浸透待ち・融解待ち・防錆乾燥待ちは、その範囲で該当工程を含めたときだけ足す。1人作業で直列とした簡易値。",
        "仮定: 案Bは経過時間を持たない。",
    ],
    "unknowns": [
        f"スライドボルト{n_unk}本の錆が未確認（案A・案Cの high にのみ含めた）。",
        "ローター固着は分解前で不明（案Cの high のみ。案Aの範囲外）。",
        "右スライドピンブーツの状態は未確認（案Cの high のみ）。",
        "サブフレームの腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る（範囲外。どの方式の high にも入れない）。",
        f"案Bの類似実績 {len(sim)}件のうち、錆グレードが一致するのは {len(rust3)}件、不明は {len(rust_none)}件。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S30.json").write_text(text + "\n", encoding="utf-8")
print(text)
