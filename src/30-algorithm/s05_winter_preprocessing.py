#!/usr/bin/env python3
"""S05 冬季の前処理モジュール

アルゴリズムの手順:
  1. scenario.json を、このファイルの位置から相対で読む。
  2. 出発点は重複控除後の基準 1.7 人時 (base_totals.deduplicated_base)。
  3. 入庫時の観察 (condition) から前処理の要否を決める。
     - 屋根・ボンネットに雪あり -> 雪下ろし PRE-SNOW を「入庫1回」だけ付ける。
     - ホイールハウスに氷あり   -> 氷塊除去 PRE-ICE を「氷のある箇所数」だけ付ける
       (後輪の少量の氷は除去不要として数えない。locations=2)。
     - 氷があれば融解待ち (thaw_wait_hours) を経過時間にだけ入れる (人時0)。
     - 下回り洗浄 PRE-WASH は入庫1回実施する。工場方針で請求しないので、
       請求人時には入れないが、実作業人時には入れる (U7)。
  4. 前処理は見積もり全体に1回だけ。J1・J2 それぞれに付けず二重計上しない。
  5. low / typical / high を、整備士の暫定値の同名列どうしで合計する。
       請求人時 = 1.7 + 雪下ろし + 氷塊除去(箇所数分)  -> other_outputs
       実作業人時 = 請求人時 + 下回り洗浄               -> labor_hours (U7)
  6. 経過時間 = 実作業人時 (作業者1人が順に行う前提) + 融解待ち (U5: 氷塊除去を含む水準だけ 0.5)。
  7. S05 は前処理以外の要因 (固着・腐食・タイヤ重量・ブーツ等) を扱わない。
     未確認の締結部などは加算せず unknowns に記録する。
  8. 人時は丸めずに計算し、出力時だけ小数第2位に丸める。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sc = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

LEVELS = ("low", "typical", "high")
r2 = lambda x: round(x + 1e-12, 2)

base = sc["base_totals"]["deduplicated_base"]
ops = sc["mechanic_provisional_add_ops"]
cond = sc["condition"]
waits = sc["elapsed_waits"]
snow, ice, wash = ops["PRE-SNOW"], ops["PRE-ICE"], ops["PRE-WASH"]

snow_state = cond["snow_on_body"]["state"]
ice_state = cond["ice_in_wheel_house"]["state"]
# 未確認(「問題あり」でも「問題なし/観察していない」でもない)は 0 で確定しない。
# low/typical には入れず high にだけ入れ、unknowns に記録する (SPEC 共通ルール4)。
# 雪: 入庫1回分。氷: 前輪2か所分 (確認済みの locations があればそれ)。
FRONT_WHEEL_HOUSES = 2
snow_unconfirmed = snow_state not in ("問題あり", "問題なし", "問題を観察していない")
ice_unconfirmed = ice_state not in ("問題あり", "問題なし", "問題を観察していない")
def counts(confirmed_n, present, unconfirmed):
    """水準ごとの件数。present なら全水準、未確認なら high だけ。"""
    if present:
        return {k: confirmed_n for k in LEVELS}
    if unconfirmed:
        return {"low": 0, "typical": 0, "high": confirmed_n}
    return {k: 0 for k in LEVELS}
snow_cnt = counts(1, snow_state == "問題あり", snow_unconfirmed)           # 入庫1回
ice_n = cond["ice_in_wheel_house"].get("locations", FRONT_WHEEL_HOUSES) if ice_state == "問題あり" else FRONT_WHEEL_HOUSES
ice_cnt = counts(ice_n, ice_state == "問題あり", ice_unconfirmed)          # 箇所数
snow_count, ice_count = snow_cnt["typical"], ice_cnt["typical"]            # 表示用
wash_count = 1                                                              # 前処理として実施する
# 融解待ちは氷塊の件数に連動 (未確認なら high だけ)
thaw_by = {k: (waits["thaw_wait_hours"] if ice_cnt[k] > 0 else 0.0) for k in LEVELS}
thaw = thaw_by["typical"]
wash_billed = "請求しない" not in wash["policy"]            # 方針文から請求可否を判定

snow_h = {k: snow[k] * snow_cnt[k] for k in LEVELS}
ice_h = {k: ice[k] * ice_cnt[k] for k in LEVELS}
wash_h = {k: wash[k] * wash_count for k in LEVELS}
pre_billed = {k: snow_h[k] + ice_h[k] + (wash_h[k] if wash_billed else 0) for k in LEVELS}
pre_actual = {k: snow_h[k] + ice_h[k] + wash_h[k] for k in LEVELS}
billed = {k: base + pre_billed[k] for k in LEVELS}
actual = {k: base + pre_actual[k] for k in LEVELS}
elapsed = {k: actual[k] + thaw_by[k] for k in LEVELS}
unbilled = {k: actual[k] - billed[k] for k in LEVELS}

def tri(d): return {k: r2(d[k]) for k in LEVELS}
def tri_s(d): return f"{r2(d['low'])} / {r2(d['typical'])} / {r2(d['high'])}"

intermediates = [
    {"label": "雪下ろし（入庫1回）", "value": tri_s(snow_h), "unit": "人時 (low/typical/high)",
     "formula": f"PRE-SNOW × {snow_count}回（屋根・ボンネット約15cm、見積もり全体で1回）"},
    {"label": "氷塊除去（ホイールハウス）", "value": tri_s(ice_h), "unit": "人時 (low/typical/high)",
     "formula": f"PRE-ICE × {ice_count}か所（前輪2か所。後輪は少量で除去不要）"},
    {"label": "前処理の請求人時（洗浄を除く）", "value": tri_s(pre_billed), "unit": "人時 (low/typical/high)",
     "formula": "雪下ろし + 氷塊除去（下回り洗浄は請求しない方針）"},
    {"label": "下回り洗浄（実施するが請求しない）", "value": tri_s(wash_h), "unit": "人時 (low/typical/high)",
     "formula": f"PRE-WASH × {wash_count}回。実作業人時にだけ加える"},
    {"label": "融解待ち（経過時間のみ）", "value": f"{r2(thaw_by['low'])} / {r2(thaw_by['typical'])} / {r2(thaw_by['high'])}", "unit": "時間 (low/typical/high)",
     "formula": "氷塊あり ? elapsed_waits.thaw_wait_hours : 0。未確認なら high だけ。人時には入れない"},
    {"label": "請求人時（typical、other_outputs）", "value": r2(billed["typical"]), "unit": "人時",
     "formula": f"基準 {base} + 前処理の請求人時 {r2(pre_billed['typical'])}"},
    {"label": "実作業人時（typical、labor_hours）", "value": r2(actual["typical"]), "unit": "人時",
     "formula": f"請求人時 {r2(billed['typical'])} + 下回り洗浄 {r2(wash_h['typical'])}"},
    {"label": "経過時間（typical）", "value": r2(elapsed["typical"]), "unit": "時間",
     "formula": f"実作業人時 {r2(actual['typical'])} + 融解待ち {thaw_by['typical']}（1人が順に作業）"},
]

result_json = {
    "id": "S05",
    "name": "冬季の前処理モジュール",
    "base_method": "A",
    "factors": ["HK02", "HK03"],
    "algorithm": [
        "手順1: 重複控除後の基準 1.7 人時を出発点にする",
        "手順2: 屋根・ボンネットの雪を確認し、雪下ろしを入庫1回だけ付ける",
        "手順3: ホイールハウスの氷のある箇所数（前輪2）× 氷塊除去を付ける",
        "手順4: 氷があれば融解待ちを経過時間にだけ入れる（人時0）。雪・氷が未確認なら 0 で確定せず high にだけ入れる",
        "手順5: 下回り洗浄は実施するが請求しない。実作業人時には入れ（labor_hours）、請求人時（洗浄を除く）は other_outputs に別に出す",
        "手順6: 前処理はJ1・J2に分けず見積もり全体に1回だけ付ける",
        "手順7: low/typical/high を暫定値の同名列で合計する。labor_hours は実作業人時、前処理以外の要因は加算しない",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "仮定"},
        {"key": "condition.snow_on_body", "value": f"{snow_state}（{cond['snow_on_body'].get('detail', '')}）", "status": "確認済み" if not snow_unconfirmed else "未確認"},
        {"key": "condition.ice_in_wheel_house", "value": f"{ice_state}（{ice_count}か所）", "status": "確認済み" if not ice_unconfirmed else "未確認"},
        {"key": "mechanic_provisional_add_ops.PRE-SNOW/PRE-ICE/PRE-WASH", "value": "整備士の暫定値", "status": "仮定"},
        {"key": "elapsed_waits.thaw_wait_hours", "value": waits["thaw_wait_hours"], "status": "仮定"},
        {"key": "shop_policy.pre_processing_billing", "value": sc["shop_policy"]["pre_processing_billing"], "status": "仮定"},
        {"key": "condition.fasteners / underbody_rust_grade 等", "value": "S05では使わない", "status": "不明"},
    ],
    "intermediates": intermediates,
    "result": {
        "labor_hours": tri(actual),
        "elapsed_hours": tri(elapsed),
        "other_outputs": [
            {"label": "請求人時（下回り洗浄を除く）low/typical/high", "value": tri(billed), "unit": "人時"},
            {"label": "請求しない人時（下回り洗浄）low/typical/high", "value": tri(unbilled), "unit": "人時"},
            {"label": "前処理の請求人時 low/typical/high", "value": tri(pre_billed), "unit": "人時"},
        ],
        "note": ("labor_hours は下回り洗浄を含む実作業人時。請求人時（洗浄を除く）は other_outputs に別掲。"
                 "下回り洗浄を請求する方針なら請求人時は typical で "
                 f"{r2(wash['typical'])} 人時増える（未確定事項: 前処理を請求するか）。"
                 "氷塊除去は PRE-ICE の単位（ホイールハウス1か所）に従い箇所数分を積む。"
                 "「入庫1回分を請求」は作業ごと（J1・J2）に重ねず見積もり全体で1回という意味で、箇所数を1に減らす意味ではない。"
                 "融解待ちは経過時間にだけ入れ人時に入れない（氷塊除去を含む水準のみ）。"
                 "この案の範囲（前処理）での上限が high。固着・腐食・サブフレームなど範囲外の未確認は high に入れず unknowns に記録した。"),
    },
    "assumptions": [
        "仮定: 前処理の人時は整備士の暫定値（架空）で、実測ではない",
        "仮定: 作業者1人が前処理を順に行い、洗浄は融解待ちと並行しない。経過時間 = 実作業人時 + 融解待ち",
        "仮定: 後輪の少量の氷は除去不要で、氷塊除去に数えない",
        "仮定: 下回り洗浄を請求しない方針は仮置きの工場方針",
    ],
    "unknowns": [
        "固着・腐食の対応人時（S05の対象外。サブフレーム未確認、スライドボルト4本未確認など）",
        "融解待ち 0.5 時間は固定の仮定で範囲を持たない",
        "氷塊以外の凍結部品（樹脂・ブーツ等）の融解待ち・作業は scenario にデータがないため見積もりに含めていない",
        "融解待ちを洗浄で埋められるか（並行できれば経過時間は短くなる）",
        "下回り洗浄で下回りの錆が見えやすくなるか（工数には反映していない）",
    ],
}

if snow_unconfirmed:
    result_json["unknowns"].append("屋根・ボンネットの雪が未確認: 雪下ろしを high にだけ入庫1回分入れた")
if ice_unconfirmed:
    result_json["unknowns"].append("ホイールハウスの氷が未確認: 氷塊除去（前輪2か所分）と融解待ちを high にだけ入れた")

out = json.dumps(result_json, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S05.json").write_text(out + "\n", encoding="utf-8")
print(out)
