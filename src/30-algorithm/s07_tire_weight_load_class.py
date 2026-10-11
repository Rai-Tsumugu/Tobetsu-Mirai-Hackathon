#!/usr/bin/env python3
"""S07 車格・タイヤ重量による作業負担区分

手順:
1. scenario.json を、このファイルの位置から相対で読む。
2. 出発点は重複控除後の基準 1.7 人時(base_totals.deduplicated_base)。基準は1人運搬(18kg以下)前提。
3. 区分は車格(body_class)・タイヤサイズ(tire_size)・重量(仮定値 tire_with_wheel_weight_kg)の
   3つで判定する。車格とタイヤサイズからは「大型側(2人運搬の可能性あり)」かを見て、
   重量を工場ルール(tire_handling.rule「20kg超は2人作業または機材」)の閾値と比べる。
4. 区分: 20kg超かつ機材なし -> 2人作業 / 20kg超かつ機材あり -> 機材使用 / 18kg以下 -> 1人 /
   18kg超〜20kg -> ルール上未定義(typical は1人)。
5. 人時: typical = high = 基準 + (2人運搬 - 1人運搬)。low = 基準(重量が20kg以下と確認できた場合)。
   SPEC U6: 23kg による差(+0.08人時)は S07 だけが扱う。
6. 経過時間は算出しない(elapsed_hours は null)。運搬工程だけの経過時間差は intermediates に出す。
7. この案は運搬の人数だけを扱う。固着・雪・氷・錆は加えない。
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
sc = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

TIRES_PER_CAR = 4

base = sc["base_totals"]["deduplicated_base"]
veh = sc["vehicle"]
th = sc["tire_handling"]
workers_available = sc["shop_policy"]["workers_available"]
weight = veh["tire_with_wheel_weight_kg"]["value"]
weight_status = veh["tire_with_wheel_weight_kg"]["status"]

# 閾値は scenario の文字列から読む(数値フィールドが無いため)。
# 20kg: rule 文の「N kg超」。18kg: 1人運搬の項目名「..._leNNkg」。
LIMIT_2P = float(re.search(r"(\d+)kg超", th["rule"]).group(1))
key_1p = next(k for k in th if re.fullmatch(r"OP-TIRE-CARRY_1person_le\d+kg", k))
key_2p = next(k for k in th if re.fullmatch(r"OP-TIRE-CARRY_2persons_gt\d+kg", k))
LIMIT_1P = float(re.search(r"le(\d+)kg", key_1p).group(1))
has_lifter = th["shop_has_tire_lifter"]
one = th[key_1p]
two = th[key_2p]

one_labor = one["persons"] * one["hours_each"]
two_labor = two["persons"] * two["hours_each"]
two_delta = two_labor - one_labor
two_elapsed_delta = two["hours_each"] - one["hours_each"]

# 車格・タイヤサイズ: 「大型側」の判定は仮定(docs に数値基準なし)。軽自動車でなく17インチ以上を大型側とみなす。
m = re.fullmatch(r"(\d+)/(\d+)R(\d+)", veh["tire_size"])
tire_width, tire_rim = int(m.group(1)), int(m.group(3))
is_kei = "軽" in veh["body_class"]
large_side = (not is_kei) and tire_rim >= 17
body_tire_text = "大型側" if large_side else "小型側"

if weight > LIMIT_2P:
    cls = "機材使用" if has_lifter else "2人作業"
elif weight <= LIMIT_1P:
    cls = "1人"
else:
    cls = "ルール上未定義(18kg超〜20kg)"

typ_carry_labor = two_labor if cls == "2人作業" else one_labor
delta = typ_carry_labor - one_labor

typ = base + delta
# high: 18kg超〜20kg の未定義帯は整備士判断なので、上限側として2人作業の値を入れる(U2)。
high_carry_labor = two_labor if cls.startswith("ルール上未定義") else typ_carry_labor
high = base + (high_carry_labor - one_labor)
low = base  # 重量が20kg以下と確認できた場合(1人運搬のまま)

r = lambda x: round(x, 2)
if cls == "2人作業":
    cls_formula = f"{weight}kg > {LIMIT_2P:g}kg かつ 機材なし -> 2人作業"
elif cls == "機材使用":
    cls_formula = f"{weight}kg > {LIMIT_2P:g}kg かつ 機材あり -> 機材使用"
elif cls == "1人":
    cls_formula = f"{weight}kg <= {LIMIT_1P:g}kg -> 1人"
else:
    cls_formula = f"{LIMIT_1P:g}kg < {weight}kg <= {LIMIT_2P:g}kg -> ルール上未定義(typical は1人)"
lifter_text = "あり" if has_lifter else "なし"

res = {
    "id": "S07",
    "name": "車格・タイヤ重量による作業負担区分",
    "base_method": "A/C",
    "factors": ["HK05"],
    "algorithm": [
        f"手順1: 重複控除後の基準 {base} 人時を出発点にする(基準は1人運搬 {r(one_labor)} 人時を含む)",
        f"手順2: 車格「{veh['body_class']}」とタイヤサイズ「{veh['tire_size']}」から {body_tire_text} と見る(軽でなく {tire_rim}インチ)。これは2人運搬の可能性を見る目安で、数値基準は仮定",
        f"手順3: ホイール付き1本 {weight}kg(仮定)を 閾値 {LIMIT_2P:g}kg 超・1人運搬の上限 {LIMIT_1P:g}kg と比べる。タイヤリフターは{lifter_text}、作業可能人数 {workers_available} 人。区分は「{cls}」",
        f"手順4: OP-TIRE-CARRY を 人数x時間 で再計算する: 2人 {two['persons']}x{two['hours_each']} = {r(two_labor)} 人時、1人 {r(one_labor)} 人時。差分 +{r(two_delta)} 人時",
        f"手順5: typical = high = 基準 + 差分 = {r(typ)} 人時。low は重量が{LIMIT_2P:g}kg以下と確認できた場合の基準 {r(low)} 人時",
        "手順6: 経過時間は算出しない(null)。運搬工程だけの経過時間の差は intermediates に出す",
    ],
    "inputs": [
        {"key": "vehicle.body_class", "value": veh["body_class"], "status": "scenarioに記載(区分の判定に使用)"},
        {"key": "vehicle.tire_size", "value": veh["tire_size"], "status": "scenarioに記載(区分の判定に使用)"},
        {"key": "vehicle.tire_with_wheel_weight_kg", "value": weight, "status": "仮定" if "仮定" in weight_status else "確認済み"},
        {"key": "tire_handling.rule", "value": th["rule"], "status": "仮定"},
        {"key": "tire_handling.shop_has_tire_lifter", "value": has_lifter, "status": "scenarioに記載"},
        {"key": "shop_policy.workers_available", "value": workers_available, "status": "scenarioに記載"},
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
    ],
    "intermediates": [
        {"label": "車格・タイヤサイズの目安", "value": body_tire_text, "unit": "", "formula": f"{veh['body_class']}(軽でない)かつ {veh['tire_size']} のリム {tire_rim}インチ >= 17"},
        {"label": "作業負担区分", "value": cls, "unit": "", "formula": cls_formula},
        {"label": "タイヤ運搬 1人の場合", "value": r(one_labor), "unit": "人時", "formula": f"{one['persons']}人 x {one['hours_each']}時間"},
        {"label": "タイヤ運搬 2人の場合", "value": r(two_labor), "unit": "人時", "formula": f"{two['persons']}人 x {two['hours_each']}時間"},
        {"label": "運搬の人時差分(typical/high)", "value": r(delta), "unit": "人時", "formula": f"{r(typ_carry_labor)} - {r(one_labor)}"},
        {"label": "運搬工程の経過時間の差(2人並行)", "value": r(two_elapsed_delta), "unit": "時間", "formula": f"{two['hours_each']} - {one['hours_each']}(2人で分担すると1人あたりの運搬時間が短くなる分の参考値。docs に根拠はなく scenario の hours_each の差。人時は増えるが運搬工程の経過時間だけは縮みうる。全体の経過時間は算出しない)"},
    ],
    "result": {
        "labor_hours": {"low": r(low), "typical": r(typ), "high": r(high)},
        "elapsed_hours": None,
        "other_outputs": [
            {"label": "作業負担区分", "value": cls, "unit": ""},
            {"label": "必要作業者数(運搬時)", "value": two["persons"] if cls == "2人作業" else one["persons"], "unit": "人"},
            {"label": f"{TIRES_PER_CAR}本合計重量(参考)", "value": weight * TIRES_PER_CAR, "unit": "kg"},
        ],
        "note": f"[typical/high は仮定重量 {weight}kg に基づく暫定値] 車格・タイヤサイズ・重量から区分を「{cls}」とし、運搬を2人作業にした分 +{r(delta)} 人時だけを反映。low は重量が{LIMIT_2P:g}kg以下と確認できた場合の基準 {r(low)} 人時。high はこの案の範囲での上限で、typical と同じ。経過時間は算出しない(運搬工程だけなら2人並行で {r(two_elapsed_delta)} 時間の差だが、全体の短縮とは読まない)。固着・雪・氷・錆は他案の要因なので加えない。",
    },
    "assumptions": [
        f"仮定: ホイール付き重量 {weight}kg は資料値の確認なし",
        f"仮定: タイヤ運搬は基準 {base} 人時の中に {r(one_labor)} 人時が1回分含まれる(tire_handling._note)",
        "仮定: 車格が軽でなくリム17インチ以上なら大型側とみなす(docs に数値基準なし)",
        f"仮定: 2人目の作業者は待ちなしで確保できる(workers_available={workers_available})",
        f"仮定: 区分「{cls}」は仮定重量 {weight}kg から決めたもので、整備士の確認前の暫定値",
        "仮定: 運搬工程の人数は全タイヤ共通(4本とも同じ区分)",
    ],
    "unknowns": [
        f"ホイール付き重量は仮定値で、資料値で確認していない。{LIMIT_2P:g}kg 以下と確認できれば low の基準 {r(low)} 人時になる",
        f"{LIMIT_1P:g}kg超〜{LIMIT_2P:g}kg は工場ルールに定義がなく、重量が実際にこの範囲なら区分は整備士の判断になる",
        "2人作業・機材が必要になるタイヤ・車格の目安は整備士の確認が必要(docs §7 項目4)",
        "社外アルミホイールの実重量が純正と異なる可能性",
        "OP-TIRE-CARRY が4本セットで1回分か1本ごとかは scenario に明記がない。1本ごとなら差分は最大4倍(+0.32人時)になりうる",
        "2人作業中、もう1人が他の作業を止めることによる損失は含めていない",
    ],
}

out = json.dumps(res, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S07.json").write_text(out + "\n", encoding="utf-8")
print(out)
