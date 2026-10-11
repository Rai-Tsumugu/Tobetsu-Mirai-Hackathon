#!/usr/bin/env python3
"""S28 錆対応の材料・消耗品の別建て

反映する要因: HK01（融雪剤による腐食）, AG01（締結部の固着・折れ込み）
工数は変えない（SPEC U9: low = typical = high = 1.7 人時）。材料費だけを金額として別記する。

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。工数は重複控除後の基準 1.7 人時のまま据え置く。
 2. condition.fasteners から J2（ブレーキ）の締結部だけを取り出し、fastener_risk_rule で区分する。
      重（頭部腐食）  -> 折れ込みの可能性  / 中 -> 固着対応の可能性 / 未確認 -> 不明
    ホイールナット（J1、軽）は材料を使う対象にしない。
 3. 固着対応の本数（浸透剤・加熱ガス = FX-SEIZE）を SPEC U3 の表どおりに決める。
      low    = 重のみ（中・未確認は0）
      typical= 重 + 中（未確認は0）
      high   = 重 + 中 + 未確認（FX-SEIZE high）
 4. 折れ込み対応（SPEC U3: 重の high のみ FX-BROKEN・FX-THREAD を足す）。交換ブラケットボルトは
    折れ込みで要るので low・typical 0、high = 重の本数。
 5. ねじ山修正部材も折れ込みと同じ割り当て: low・typical 0、high = 重の本数（か所）。
 6. ハブ防錆の側数: ハブ錆グレード >= 2 なら両側（2側）。low・typical・high とも同じ。
 7. 範囲外（SPEC U1・U4）: ローター・ハブ固着、サブフレーム、スライドピンブーツ（AG03/S22）は
    材料に含めず unknowns に記録する。サブフレームは J1・J2 で外さないので作業範囲外（腐食があれば AG04 の範囲拡大）。
 8. materials_S28 の単価で金額化する。浸透剤・加熱ガス・防錆剤は「単価 / 使用回数」で1回分に按分、
    ボルト・ブーツ・ねじ山部材は1個（か所）あたりの単価。
 9. 材料費の合計を other_outputs に出す。人時には足さない。工賃と混ぜない。
10. 待機は人時に入れない。SPEC U5: 範囲内で FX-SEIZE 相当（浸透剤・加熱ガス）の本数が1以上なら浸透待ち0.25、
    FX-HUBCLEAN 相当（ハブ防錆）の側数が1以上なら防錆乾燥0.3（冬季仮説値）を、その範囲の経過時間に足す。
11. SPEC.md の形で JSON を標準出力と results/S28.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
mat = SC["materials_S28"]
cond = SC["condition"]

# --- 手順2: J2 の締結部を区分 ---
def rust_key(t):
    for k in ("未確認", "重", "中", "軽"):
        if t.startswith(k):
            return k
    return "未確認"

j2 = [f for f in cond["fasteners"] if f["job"] == "J2"]
n_heavy = sum(f.get("count", 1) for f in j2 if rust_key(f["rust"]) == "重")
n_mid = sum(f.get("count", 1) for f in j2 if rust_key(f["rust"]) == "中")
n_unk = sum(f.get("count", 1) for f in j2 if rust_key(f["rust"]) == "未確認")

# --- 手順3-7: 数量 ---
seize = {"low": n_heavy, "typical": n_heavy + n_mid, "high": n_heavy + n_mid + n_unk}
# U3: 折れ込み（FX-BROKEN）・ねじ山損傷（FX-THREAD）は重の high のみ。交換ボルトとねじ山部材の数量を同じ割り当てにする
bolts = {"low": 0, "typical": 0, "high": n_heavy}
insert = {"low": 0, "typical": 0, "high": n_heavy}
hub_grade = cond["underbody_rust_grade"]["wheel_hub"]
hub_sides = 2 if hub_grade is not None and hub_grade >= 2 else 0
hub = {r: hub_sides for r in RANGES}
# ローター・ハブ固着（U1 範囲外）とサブフレーム（U4 作業範囲外）は材料に入れず unknowns に記録する

# --- 手順8: 単価 ---
pen_unit = mat["penetrant"]["price_yen"] / mat["penetrant"]["uses"]
gas_unit = mat["heating_gas"]["price_yen"] / mat["heating_gas"]["uses"]
hub_unit = mat["rustproof_hub"]["price_yen"] / mat["rustproof_hub"]["uses"]
bolt_unit = mat["bracket_bolt"]["price_yen"]
ins_unit = mat["thread_insert_kit"]["price_yen"]

def cost(r):
    return {
        "浸透剤": seize[r] * pen_unit,
        "加熱ガス": seize[r] * gas_unit,
        "ハブ防錆剤": hub[r] * hub_unit,
        "交換ボルト": bolts[r] * bolt_unit,
        "ねじ山修正部材": insert[r] * ins_unit,
    }

costs = {r: cost(r) for r in RANGES}
total = {r: sum(costs[r].values()) for r in RANGES}
labor = {r: base for r in RANGES}  # 工数は据え置き
# U5: 材料を計上する範囲は FX-SEIZE / FX-HUBCLEAN を含むので待機を経過時間に足す（人時には入れない）
WAIT_SEIZE = SC["elapsed_waits"]["penetrant_soak_wait_hours"]
WAIT_HUB = SC["elapsed_waits"]["rustproof_dry_wait_hours"]["winter_hypothesis"]  # 入庫は冬季
elapsed = {r: (WAIT_SEIZE if seize[r] > 0 else 0) + (WAIT_HUB if hub[r] > 0 else 0) for r in RANGES}

def triple(d, f=lambda x: x):
    return {r: f(d[r]) for r in RANGES}

out = {
    "id": "S28",
    "name": "錆対応の材料・消耗品の別建て",
    "base_method": "共",
    "factors": ["HK01", "AG01"],
    "algorithm": [
        "手順1: 工数は重複控除後の基準1.7人時のまま据え置く（SPEC U9: low=typical=high=1.7）。",
        "手順2: J2の締結部を fastener_risk_rule で 重/中/未確認 に区分する（ホイールナットは対象外）。",
        "手順3: 固着対応（浸透剤・加熱ガス）の本数を SPEC U3 に合わせ low=重 / typical=重+中 / high=重+中+未確認 とする。",
        "手順4: 折れ込みは重の high のみ。交換ボルトは low・typical 0、high=重の本数。",
        "手順5: ねじ山修正部材も同じ割り当て（low・typical 0、high=重の本数）。",
        "手順6: ハブ錆グレード2以上なら防錆剤を両側（2側）に使う。",
        "手順7: ローター・ハブ固着、サブフレーム（U4 作業範囲外）、ブーツ（AG03/S22）は材料に含めず unknowns に記録する。",
        "手順8: 材料単価（按分または1個単価）で金額化し、合計を other_outputs に別記する。人時に足さない。",
    ],
    "inputs": [
        {"key": "condition.fasteners (J2)", "value": f"重{n_heavy}本 / 中{n_mid}本 / 未確認{n_unk}本", "status": "確認済み（スライドボルト4本は未確認）"},
        {"key": "condition.underbody_rust_grade.wheel_hub", "value": hub_grade, "status": "確認済み"},
        {"key": "materials_S28", "value": "浸透剤・加熱ガス・ハブ防錆・ボルト・ねじ山部材の単価（ブーツ単価は使わない）", "status": "仮定（架空の単価）"},
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
    ],
    "intermediates": [
        {"label": "固着対応の候補本数", "value": triple(seize), "unit": "本",
         "formula": "low=重(%d) / typical=重+中(%d+%d) / high=重+中+未確認(%d+%d+%d)" % (n_heavy, n_heavy, n_mid, n_heavy, n_mid, n_unk)},
        {"label": "浸透剤＋加熱ガスの1本あたり", "value": r2(pen_unit + gas_unit), "unit": "円/本",
         "formula": "%d/%d + %d/%d = %.0f + %.0f" % (mat["penetrant"]["price_yen"], mat["penetrant"]["uses"], mat["heating_gas"]["price_yen"], mat["heating_gas"]["uses"], pen_unit, gas_unit)},
        {"label": "ハブ防錆の側数", "value": triple(hub), "unit": "側",
         "formula": "ハブ錆グレード%s >= 2 なら両側(2)" % hub_grade},
        {"label": "交換ブラケットボルト数（折れ込み）", "value": triple(bolts), "unit": "本",
         "formula": "low・typical=0 / high=重(%d)（FX-BROKEN は重の high のみ）" % n_heavy},
        {"label": "ねじ山修正部材", "value": triple(insert), "unit": "か所",
         "formula": "low・typical=0 / high=重(%d)（FX-THREAD は折れ込みと同じ割り当て）" % n_heavy},
        {"label": "材料費合計", "value": triple(total, r2), "unit": "円",
         "formula": "固着本数x(%.0f+%.0f) + ハブ側数x(%d/%d) + ボルト本数x%d + ねじ山x%d" % (pen_unit, gas_unit, mat["rustproof_hub"]["price_yen"], mat["rustproof_hub"]["uses"], bolt_unit, ins_unit)},
        {"label": "待機（経過時間のみ）", "value": triple(elapsed, r2), "unit": "h",
         "formula": "固着本数>0 なら浸透待ち%s + ハブ防錆側数>0 なら防錆乾燥%s（SPEC U5）" % (WAIT_SEIZE, WAIT_HUB)},
    ],
    "result": {
        "labor_hours": triple(labor, r2),
        "elapsed_hours": {r: r2(labor[r] + elapsed[r]) for r in RANGES},  # 経過時間 = 人時 + 待機（U5）
        "other_outputs": (
            [{"label": "材料費合計（%s）" % r, "value": r2(total[r]), "unit": "円"} for r in RANGES]
            + [{"label": "ボルト・ナット・クリップの別記", "value": "ブラケットボルトは本数×単価で計上。ナット・クリップは数量・単価とも未確定のため金額なし（工場の単価確認後に追加）", "unit": None}]
            + [{"label": "材料費内訳（%s）" % r, "value": {k: r2(v) for k, v in costs[r].items()}, "unit": "円"} for r in RANGES]
            + [{"label": "付随部品の候補（材料費の本体に入れない）: キャリパーブラケットボルト交換", "value": {"freq": SC["shop_policy"]["companion_parts_catalog_S22"]["キャリパーブラケットボルト交換"]["freq"], "price_yen_each": SC["materials_S28"]["bracket_bolt"]["price_yen"]}, "unit": "円/本"}]
        ),
        "note": "工数は変えない（SPEC U9: low=typical=high=1.7人時に据え置く）。経過時間は SPEC U5 に従い、人時 1.7 に浸透待ち0.25hと防錆乾燥0.3h（冬季仮説値）を足した値。S28 は固着対応・ハブ処置の作業人時を入れないので、この経過時間は過小になりうる（作業人時は S03 等が扱う）。付随部品の候補（キャリパーブラケットボルト交換、出現率0.20）は S22 の扱いに合わせて材料費の本体に入れず、単価を候補として別に示す。S28は錆対応で増える材料・消耗品を金額として工賃と別に記載する案で、人時は他案（固着対応の人時を持つ案）が扱うため、S28では人時を加えず基準1.7人時を据え置く。材料費は人時に足さない。材料の数量は SPEC U3 の締結部の割り当てに合わせた（中は typical から固着対応、重の high で折れ込み→交換ボルト・ねじ山修正部材、未確認は high で固着対応）。ローター・ハブ固着、サブフレーム（J1・J2 では外さない作業範囲外）、ブーツ（AG03/S22）はこの案の範囲外で材料に含めず unknowns に記録した。high は材料費のこの案の範囲での上限。S28は人時を足さないため、固着で増える人時は他案の領域で、比較時に人時の差がないことを錆対応の少なさと読まないこと。",
    },
    "assumptions": [
        "仮定: 折れ込みは固着対応を試みたあとに起きる別工程（SPEC U3）で、重の high のみ。交換ボルトとねじ山修正部材は重の本数分を見込む。",
        "仮定: 浸透剤・加熱ガス・ハブ防錆剤は使用回数での按分単価で計上する（缶単位の請求は工場の方針次第）。",
        "仮定: ハブ錆グレード2以上は両側に防錆する。グレードは車両に1つの値で、片側ごとの実測はなく、両側は推定。",
        "仮定: ボルト・ナット・クリップのうち、scenarioに単価があるのはブラケットボルトだけ。ナット・クリップは単価がないため金額は見込まず、other_outputs に「単価未確定」として別記する。",
        "仮定: ハブ防錆の両側は low にも適用する。片側のみなら low は約%.0f円（%d/%d）減る。" % (hub_unit, mat["rustproof_hub"]["price_yen"], mat["rustproof_hub"]["uses"]),
        "仮定: 経過時間は SPEC U5 に従い浸透待ち0.25h（冬季仮説なし）と防錆乾燥0.3h（冬季仮説値）を足す。待機は人時に入れない。",
        "判断: AG-CLIP（樹脂クリップ1個単位）の数量はこの scenario では交換数を決める入力がなく、数量を置くと根拠のない加算になるため、金額は見込まず other_outputs に未確定と記録した。",
        "判断: companion_parts_catalog_S22 のキャリパーブラケットボルト交換（出現率0.20）は付随部品の候補で、S22 と同じく見積もり本体に入れず、単価を other_outputs に候補として示す（必要が分かった時点で追加）。S28 の交換ボルト（折れ込み用、high のみ）とは発生条件が違う。",
    ],
    "unknowns": [
        "スライドボルト4本の錆（ブーツに隠れて未確認）。high で固着対応の材料に含めた。",
        "ローター・ハブ固着は未確認で、この案の範囲外のため材料に含めていない。",
        "サブフレームは J1・J2 では外さない作業範囲外。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る。",
        "スライドピンブーツの交換材料はAG03（S22）の領域で、S28では扱わない。",
        "材料の請求方法（実費・定額・按分）は工場に確認が必要。",
        "参考: companion_parts_catalog_S22 のキャリパーブラケットボルト交換（出現率0.20、部品のみ・人時0）は表示しきい値以上だが、S28 の材料費には含めていない。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S28.json").write_text(text + "\n", encoding="utf-8")
print(text)
