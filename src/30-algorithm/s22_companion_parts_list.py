#!/usr/bin/env python3
"""S22 付随作業・連鎖交換の候補リスト

反映する要因: AG02（外したときに付随部品が壊れる）, AG03（ゴム・樹脂部品の硬化）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. companion_parts_catalog_S22 の各付随部品について、発生頻度(freq)を表示しきい値
    (display_threshold_freq)と比べる。しきい値以上だけを「候補リスト」に出す。未満は表示しない。
 3. 候補ごとに、交換が必要になったときの工程（op）の人時を mechanic_provisional_add_ops から引き、
      期待人時 = freq x 単位数 x 工程の人時（typical）
    を参考値として計算する。op が null の部品は labor_hours_each（なければ 0）を使い、部品のみとして扱う。
 4. 候補を現車の観察と突き合わせる（U2）。
      観察で問題あり（左ブーツ硬化）  -> 必要が分かっているので「確定した追加工程」。
                                          low/typical/high = AG-BOOT の low/typical/high x 1 片側を本体に入れる。
      未確認（右ブーツ）             -> typical には入れない。範囲内の未確認項目の上限として、
                                          発生した場合の人時（AG-BOOT high x 1 片側）を high にだけ加える。
      ブラケットボルト交換           -> カタログ上の工数は 0（固着対応に含む）。人時は足さず、部品（本数 x 単価）として
                                          other_outputs に別記する。固着対応そのものは他案の範囲。
      しきい値未満（パッドセンサー・ブレーキホース） -> U8 により high に入れず、other_outputs に参考として出す。
 5. 人時 = 1.7 + 左ブーツ（本体）。high だけ未確認の右ブーツ分を足す。
    候補の期待人時（freq x 人時）は typical に混ぜない。確率を人時に「平均化」して確定しないため。
 6. 地域・年式・走行距離からは加算しない。固着対応・雪下ろし・氷塊除去など他案の要因は加えない。
 7. 待機・2人作業は扱わないので elapsed_hours は null。
 8. 人時は丸めずに計算し、出力時だけ小数第2位に丸める。
 9. SPEC.md の形で JSON を標準出力と results/S22.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
cat = SC["shop_policy"]["companion_parts_catalog_S22"]
thr = cat["display_threshold_freq"]
cond = SC["condition"]
mat = SC["materials_S28"]

# --- 手順2: 表示しきい値で絞る ---
parts = {k: v for k, v in cat.items() if isinstance(v, dict)}
shown = {k: v for k, v in parts.items() if v["freq"] >= thr}
hidden = {k: v for k, v in parts.items() if v["freq"] < thr}

# --- 手順3: 期待人時 ---
def unit_hours(p, rng="typical"):
    if p.get("op"):
        return ops[p["op"]][rng]
    return p.get("labor_hours_each", 0.0)

SIDES = 2  # 左右（仮定: 片側単位の部品は左右の2か所）
expected = {}
for k, p in shown.items():
    n = SIDES if p.get("unit") == "片側" else 1
    expected[k] = p["freq"] * n * unit_hours(p)

# --- 手順4: 観察との突き合わせ ---
boot = ops["AG-BOOT"]
left_boot_state = cond["slide_pin_boots"]["left"]
right_boot_state = cond["slide_pin_boots"]["right"]
left_boot_confirmed = left_boot_state.startswith("問題あり")
right_boot_unconfirmed = right_boot_state.startswith("未確認")

body_add = {r: (boot[r] if left_boot_confirmed else 0.0) for r in RANGES}
high_extra_right_boot = boot["high"] if right_boot_unconfirmed else 0.0

# ブラケットボルト（部品のみ）: 固着リスク重・中のブラケットボルト本数
brk = [f for f in cond["fasteners"] if "ブラケット" in f["name"]]
brk_heavy = [f for f in brk if f["rust"].startswith("重")]
brk_mid = [f for f in brk if f["rust"].startswith("中")]
bolt_price = mat["bracket_bolt"]["price_yen"]
bolt_candidates = len(brk_heavy) + len(brk_mid)

bolt_labor_each = parts["キャリパーブラケットボルト交換"].get("labor_hours_each", 0.0)  # catalog で 0（固着対応に含む）
assert bolt_labor_each == 0.0

labor = {
    "low": base + body_add["low"],
    "typical": base + body_add["typical"],
    "high": base + body_add["high"] + high_extra_right_boot,
}

# --- 出力 ---
boot_freq = parts["スライドピンブーツ"]["freq"]
intermediates = [
    {"label": "表示する候補の数（頻度がしきい値以上）", "value": len(shown), "unit": "件",
     "formula": f"頻度 >= {thr} の部品数（{'・'.join(shown)}）。未満は表示しない: {'・'.join(f'{k}({v['freq']})' for k, v in hidden.items())}"},
    {"label": "左ブーツ（硬化を観察）を本体に入れる人時（typical）", "value": r2(body_add["typical"]), "unit": "人時",
     "formula": f"1片側 x AG-BOOT typical（low {boot['low']} / typical {boot['typical']} / high {boot['high']}）"},
    {"label": "右ブーツ（未確認）の発生時の人時（high にだけ加算）", "value": r2(high_extra_right_boot), "unit": "人時",
     "formula": "1片側 x AG-BOOT high。typical には入れない"},
    {"label": "ブラケットボルト交換の人時（人時に足さない）", "value": r2(bolt_candidates * bolt_labor_each), "unit": "人時",
     "formula": f"{bolt_candidates} 本 x {bolt_labor_each}（catalog: 固着対応に含む）。固着対応は他案の範囲"},
    {"label": "ブラケットボルト部品代（重＋中の全数交換した場合）", "value": bolt_candidates * bolt_price, "unit": "円",
     "formula": f"重 {len(brk_heavy)} 本 + 中 {len(brk_mid)} 本 = {bolt_candidates} 本 x {bolt_price} 円。人時ではないので足さない"},
    {"label": "候補の期待人時の合計（参考。本体に入れない）", "value": r2(sum(expected.values())), "unit": "人時",
     "formula": "Σ(頻度 x 単位数 x 工程人時 typical)。確率で平均化した値は見積もりに使わない"},
]

candidate_rows = []
for k, p in parts.items():
    if k == "キャリパーブラケットボルト交換":
        status = "観察なし（別記。部品のみで人時は足さない）"
    elif k == "スライドピンブーツ":
        status = f"左: {left_boot_state}（本体に計上） / 右: {right_boot_state}（別記・high のみ）"
    elif k in hidden:
        status = "しきい値未満（参考。high にも入れない）"
    else:
        status = "観察なし（別記のみ。本体に入れない）"
    candidate_rows.append({"part": k, "freq": p["freq"], "freq_basis": "整備士の見込み（架空・実績未検証。順序は目安）",
                           "op": p.get("op"), "shown": k in shown,
                           "hours_each": r2(unit_hours(p)), "hours_basis": "typical", "status": status})

other_outputs = [
    {"label": "別記する候補リスト（仮定の頻度順。実績ではない。顧客への事前説明用。しきい値未満は参考）",
     "value": sorted(candidate_rows, key=lambda r: -r["freq"]), "unit": "リスト"},
    {"label": "ブラケットボルト交換の部品代（候補。人時は固着対応に含み、見積もり本体には含めない）", "value": bolt_candidates * bolt_price, "unit": "円"},
    {"label": "右ブーツ交換の部品代（候補）", "value": mat["boot"]["price_yen"], "unit": "円"},
    {"label": "左ブーツ交換の部品代（本体）", "value": mat["boot"]["price_yen"] if left_boot_confirmed else 0, "unit": "円"},
]

out = {
    "id": "S22",
    "name": "付随作業・連鎖交換の候補リスト",
    "base_method": "C",
    "factors": ["AG02", "AG03"],
    "algorithm": [
        "手順1: 基準 1.7 人時を出発点にする",
        f"手順2: 付随部品カタログから頻度 {thr} 以上の候補だけを表示する",
        "手順3: 候補ごとに工程人時と期待人時（頻度 x 単位数 x 人時）を参考値として計算する",
        "手順4: 現車の観察と突き合わせる。観察で問題あり（左ブーツ）は必要が分かっているので本体の low/typical/high に入れる。未確認（右ブーツ）は high にだけ加える",
        "手順4b: 候補カタログは作業 J2（前ブレーキ）用の1種類。対象作業が変わる場合は、その作業用のカタログに差し替える（この実装では切り替え未対応）",
        "手順5: ブラケットボルト交換は catalog で工数 0（固着対応に含む）なので人時を足さず、部品代として other_outputs に別記。パッドセンサー・ブレーキホース（しきい値未満）も other_outputs に参考として出し、high に入れない（U8）",
        "手順5b: 人時 = 1.7 + 左ブーツ。high にだけ未確認の右ブーツを加算。期待人時は typical に混ぜない",
        "手順6: 地域・年式・走行距離からは加算しない。他案の要因は加えない",
        "手順7: 待機・2人作業は扱わないので経過時間は null",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "shop_policy.companion_parts_catalog_S22（頻度）", "value": {k: v["freq"] for k, v in parts.items()}, "status": "仮定"},
        {"key": "shop_policy.companion_parts_catalog_S22.display_threshold_freq", "value": thr, "status": "仮定"},
        {"key": "condition.slide_pin_boots.left", "value": left_boot_state, "status": "確認済み"},
        {"key": "condition.slide_pin_boots.right", "value": right_boot_state, "status": "不明"},
        {"key": "condition.fasteners（ブラケットボルト）", "value": {"重": len(brk_heavy), "中": len(brk_mid)}, "status": "確認済み"},
        {"key": "mechanic_provisional_add_ops.AG-BOOT", "value": {r: boot[r] for r in RANGES}, "status": "仮定"},
        {"key": "companion_parts_catalog_S22.キャリパーブラケットボルト交換.labor_hours_each", "value": bolt_labor_each, "status": "仮定"},
    ],
    "intermediates": intermediates,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": None,
        "other_outputs": other_outputs,
        "note": "見積もり本体に入れるのは、観察で必要が分かっている左ブーツ交換だけ（low/typical/high）。"
                "右ブーツ（未確認）は、この案の範囲での上限として high にだけ加える。"
                "ブラケットボルト交換は catalog で工数 0（固着対応に含む）。これは固着対応を計上する他案が取付工数を持つ前提で、S22 単独では新品の取付工数や折れ込みは見えないため、人時を足さず部品として別記する。"
                "カタログにない付随部品（ブッシュ、クリップ、アンダーカバー裏の部位）は数値化できず範囲外なので、high にも入れず unknowns に記録する。"
                "パッドセンサー・ブレーキホースはしきい値未満のため other_outputs の参考にとどめ、high に入れない。"
                "候補の頻度としきい値は整備士の見込み（架空・実績未検証）で、実績ではない。",
    },
    "assumptions": [
        "仮定: 付随部品の発生頻度と表示しきい値 0.15 は整備士見込み（架空）で、実績で見直す",
        "仮定: 片側単位の部品の期待人時は左右2か所で計算する",
        "仮定: ブーツ交換の人時は AG-BOOT の暫定値（片側 0.10 / 0.15 / 0.20）",
        "仮定: ブラケットボルト交換の工数は catalog どおり 0（固着対応に含む）。人時を足さず部品代のみ別記する",
        "docs との差: docs §4.4 S22 は『作業ごとに』候補を表示するとしているが、付随部品カタログは作業 J2 用の固定1種類で、作業ごとの切り替えは未実装",
        "仮定: 現車観察で必要が分かっている付随部品（左ブーツ）は見積もり本体に入れる。docs §4.4 S22 の『見積もりには含めず別記し、必要が分かった時点で追加する』に沿った扱いで、docs と矛盾しない",
        "仮定: docs §4.4 S22 が候補に挙げる『ブッシュ、クリップ』は companion_parts_catalog_S22 に項目も頻度も人時もないため候補に出さない（数値化できない。必要なら整備士見込みを catalog に追加する）",
        "仮定: ブラケットボルトの工数 0 は、固着対応（折れ込みを含む重の扱いは U3）を計上する他案が持つ前提。S22 は fastener_risk_rule の折れ込みを反映しない",
        "仮定: ブラケットボルトの部品代は materials_S28 の単価を流用（人時には足さない）",
    ],
    "unknowns": [
        "右スライドピンブーツの硬化の有無（未確認）。発生時は high に 0.20 人時",
        "アンダーカバーで見えない部位の付随部品。カタログにない項目で人時の根拠がなく、U1 の案の範囲（カタログの候補）外のため、high に上限を置かずここに記録するだけにする（U2: 範囲外の未確認項目）",
        "ブレーキホース（頻度 0.05）とパッド摩耗センサー（0.10）はしきい値未満のため候補に出さず、other_outputs の参考のみ",
        "ブラケットボルトを実際に交換するかは固着対応の結果次第。固着対応・折れ込みは S22 の範囲外（他案の要因）で、この結果に含まれない",
        "サブフレーム周りは J2 では外さず作業範囲外。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る"
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S22.json").write_text(text + "\n", encoding="utf-8")
print(text)
