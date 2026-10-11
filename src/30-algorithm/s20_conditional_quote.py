#!/usr/bin/env python3
"""S20 条件付き見積書（追加発生時の連絡基準）

反映する要因: HK01（融雪剤による腐食）, AG01（締結部の固着・折れ込み）,
              AG02（付随部品の破損）, AG03（ゴム部品の硬化）, AG04（腐食による範囲拡大）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. 「確定分」を決める。観察済みで問題ありと記録された項目だけが対象。
      左スライドピンブーツ（問題あり: 硬化）-> AG-BOOT 片側1個
    観察していない・未確認の項目は確定分に入れない。
 2b. AG07（経過年数・走行距離）: 工数にも条件の数にも使わない。確認強度で未確認の条件を
    消さず、未確認の条件は常に条件表と上限（high）に載せる（U2・U3）。
 3. 「条件付き追加」を condition から条件ごとに作る。各条件に
    (発生条件, 対象本数/箇所数, 1回あたりの追加人時 low/typical/high, 最大件数) を持たせる。
      C1 ブラケットボルト折れ  : fasteners のうち rust=重 の本数。1本あたり FX-BROKEN + FX-THREAD
                                 （固着対応 C2 に「加えて」足す。置換しない）
      C2 ブラケットボルト固着  : rust=重・中の本数。1本あたり FX-SEIZE（U3: 重の折れ込みは固着対応のあとの別工程）
      C3 スライドボルト固着    : rust=未確認の本数。1本あたり FX-SEIZE（high にだけ入れる）
      C4 ローター固着          : rotor_hub_seizure が未確認 -> 左右。片側あたり FX-ROTOR + FX-HUBCLEAN
      C5 右ブーツ硬化          : slide_pin_boots.right が未確認 -> AG-BOOT 片側
      C6 ブレーキホース劣化    : AG-HOSE。freq が表示しきい値未満なので条件表の参考のみ（U8）
      C7 腐食による範囲拡大    : サブフレーム等 underbody_rust_grade が null、または 3 の部位がある場合。
                                 人時は見積もれないため数値化せず、発生したら必ず連絡する。
 4. 単価を算出する（仮定）: cost_data_S27 の年間経費合計 / 年間請求可能時間（年間配賦）。
    暖房費は人時に足さず、単価の側に含める（共通ルール7）。
 5. 連絡基準（shop_policy.contact_threshold）で条件ごとに判定する。
      追加人時 > 0.5 または 追加金額 > 5000円 のどちらかを超えうるなら連絡対象。
      - 「1回で超える」: 1回あたり high が基準超 -> 発生を見つけた時点で作業前に連絡
      - 「累積で超える」: 1回では超えないが最大件数ぶんの high 合計が基準超
                          -> 発生ごとに記録し、その条件での追加の累計が基準を超える前に連絡
      - 「連絡不要」: 最大件数ぶんの high でも基準以下 -> 記録だけ残す
      - 数値化できない条件(C7)は常に連絡。
 6. 結果の人時（U3。丸めずに計算し、出力時だけ小数第2位に丸める）:
      low     = 1.7 + 確定分 + 重ボルトの FX-SEIZE low
      typical = 1.7 + 確定分 + 重・中ボルトの FX-SEIZE typical
      high    = 1.7 + 確定分 + 重・中ボルトの FX-SEIZE high + 重ボルトの FX-BROKEN/FX-THREAD high
                + 未確認ボルト(C3)の FX-SEIZE high + C4 + C5（未確認は常に high に入れる）。
                C6 は U8 により high に入れず条件表の参考のみ、C7 は数値化しない。
 7. 経過時間（U5）: 人時と別に、FX-SEIZE を含む low/typical/high のそれぞれに浸透待ちを足す。
    FX-HUBCLEAN（C4）を含む high には防錆乾燥待ち(冬季仮説)も足す。待機は人時に入れない。
    ブレーキホースの取り寄せ待ち(1日)は条件表に書き、経過時間には入れない。
 7b. 作業中の運用（連絡と記録）: 条件が発生したら、同じ画面で (a)発生記録(条件ID・本数・実績人時)
    と (b)連絡(要連絡なら作業前に顧客へ。累積型は累計が基準を超える前に)を行う。
    本スクリプトは判定値のみ作る。運用手順は result.operation_flow に文面で出す。
 8. SPEC.md の形で JSON を標準出力と results/S20.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
cond = SC["condition"]
thr = SC["shop_policy"]["contact_threshold"]
waits = SC["elapsed_waits"]
cost = SC["cost_data_S27"]

# --- 手順4: 単価（仮定: 年間配賦。暖房費は単価側に含み、人時には足さない） ---
annual_cost = (cost["labor_cost_yen"] + cost["rent_yen"] + cost["heating_yen"]
               + cost["equipment_yen"] + cost["utilities_excl_heating_yen"]
               + cost["target_profit_yen"])
unit_price = annual_cost / cost["annual_billable_hours"]
hours_at_yen_limit = thr["yen_gt"] / unit_price  # 金額基準を人時に直した値（other_outputs に出す）

RUST_SEVERE = 3   # 仮定: underbody_rust_grade が 3 以上を重度（C7）
SIDES = 2         # 仮定: ローターは左右2側
BOOT_N = 1        # 仮定: 右ブーツ（C5）・確定分の左ブーツは各1個

def op(name, r):
    return ops[name][r]

def combo(names, r):
    return sum(op(n, r) for n in names)

# --- 手順2b: AG07（工数・条件数に使わない） ---
# 確認強度で条件を消す分岐は持たない（U2・U3）。経過年数・走行距離は工数にも条件数にも使わない。

# --- 手順2: 確定分 ---
definite = []
if cond["slide_pin_boots"]["left"].startswith("問題あり"):
    definite.append(("左スライドピンブーツ交換（硬化を観察済み）", ["AG-BOOT"], BOOT_N))
definite_h = {r: sum(combo(ns, r) * n for _, ns, n in definite) for r in RANGES}

# --- 手順3: 条件付き追加 ---
def rust_head(s):
    for k in ("未確認", "重", "中", "軽"):
        if s.startswith(k):
            return k
    return "未確認"

brk_bolts = [f for f in cond["fasteners"] if f["job"] == "J2" and rust_head(f["rust"]) == "重"]
mid_bolts = [f for f in cond["fasteners"] if f["job"] == "J2" and rust_head(f["rust"]) == "中"]
unk_bolts = [f for f in cond["fasteners"] if f["job"] == "J2" and rust_head(f["rust"]) == "未確認"]
n_brk, n_mid, n_unk = len(brk_bolts), len(mid_bolts), len(unk_bolts)
n_c1 = n_brk

conditions = []
def add_cond(cid, trigger, ops_used, max_n, unit, status, note=""):
    conditions.append({"id": cid, "trigger": trigger, "ops": ops_used, "max_n": max_n,
                       "unit": unit, "status": status, "note": note,
                       "per": {r: combo(ops_used, r) for r in RANGES}})

add_cond("C1", "左ブラケットボルト（頭部腐食）が折れた場合", ["FX-BROKEN", "FX-THREAD"], n_c1, "本",
         "観察（重）",
         "折れた本数ぶん。C2 の固着対応を試みたあとに起きる別工程として足す（U3）")
add_cond("C2", "ブラケットボルトが固着した場合", ["FX-SEIZE"], n_brk + n_mid, "本",
         "観察（重・中）", "左（重）2本+右（中）2本")
add_cond("C3", "スライドボルトが固着した場合", ["FX-SEIZE"], n_unk, "本",
         "未確認（ブーツに隠れて見えない）", "分解して初めて分かる")
if cond["rotor_hub_seizure"]["state"] == "未確認":
    add_cond("C4", "ローターがハブに固着していた場合", ["FX-ROTOR", "FX-HUBCLEAN"], SIDES, "片側",
             "未確認（ハブ錆グレード2）", "左右。ハブ当たり面の錆落とし・防錆を伴う")
if cond["slide_pin_boots"]["right"].startswith("未確認"):
    add_cond("C5", "右スライドピンブーツが硬化していた場合", ["AG-BOOT"], BOOT_N, "片側", "未確認")
# C6 の人時と取り寄せ待ちは mechanic_provisional_add_ops / elapsed_waits を使う。
# 発生頻度は S22（付随部品候補）の要因なので S20 では参照しない。
add_cond("C6", "ブレーキホースの劣化が見つかった場合", ["AG-HOSE"], 1, "左右一式",
         "未観察", "参考のみ（U8）。取り寄せ1日。範囲の人時には入れない。発生頻度の見込みは S22 側で扱う")

# --- 手順5: 連絡判定 ---
def yen(h):
    return h * unit_price

for c in conditions:
    c["max_total"] = {r: c["per"][r] * c["max_n"] for r in RANGES}
    one_h, one_y = c["per"]["high"], yen(c["per"]["high"])
    tot_h, tot_y = c["max_total"]["high"], yen(c["max_total"]["high"])
    over = lambda h, y: h > thr["labor_hours_gt"] or y > thr["yen_gt"]
    if c["id"] == "C6":  # U8: 表示しきい値未満の付随部品は常に参考扱い（連絡対象に数えない）
        c["contact"] = "参考（U8・range外。発見時に連絡要否を判断）"
    elif over(one_h, one_y):
        c["contact"] = "要連絡（1回で超える）"
    elif over(tot_h, tot_y):
        c["contact"] = "要連絡（累積で超える）"
    else:
        c["contact"] = "連絡不要（記録のみ）"
# C7 数値化しない条件
scope_areas = [k for k, v in cond["underbody_rust_grade"].items()
               if not k.startswith("_") and (v is None or v >= RUST_SEVERE)]

# --- 手順6: 結果 ---
by_id = {c["id"]: c for c in conditions}
seize_typ_bolts = (n_brk + n_mid) * op("FX-SEIZE", "typical")
mx = lambda cid: by_id[cid]["max_total"]["high"] if cid in by_id else 0.0
seize_low_brk = n_brk * op("FX-SEIZE", "low")                        # U3: 重の low
high_cond = (mx("C2")                                                # 重・中: FX-SEIZE high
             + mx("C1")                                              # 重: FX-BROKEN + FX-THREAD high（別工程）
             + mx("C3") + mx("C4") + mx("C5"))                       # 未確認は常に high に入れる
labor = {
    "low": base + definite_h["typical"] + seize_low_brk,
    "typical": base + definite_h["typical"] + seize_typ_bolts,
    "high": base + definite_h["typical"] + high_cond,
}
# --- 手順7: 経過時間 ---
soak = waits["penetrant_soak_wait_hours"]
dry_w = waits["rustproof_dry_wait_hours"]
dry = dry_w["winter_hypothesis"] if "冬季" in SC["intake"]["season"] else dry_w["normal"]
elapsed = {"low": labor["low"] + (soak if n_brk else 0.0), "typical": labor["typical"] + soak,
           "high": labor["high"] + soak + (dry if "C4" in by_id else 0.0)}

cond_total_high = high_cond
cond_total_yen_high = yen(cond_total_high)

# --- 出力 ---
inputs = [
    {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
    {"key": "condition.slide_pin_boots.left", "value": cond["slide_pin_boots"]["left"], "status": "確認済み"},
    {"key": "condition.slide_pin_boots.right", "value": cond["slide_pin_boots"]["right"], "status": "不明"},
    {"key": "condition.fasteners(J2: 重/中/未確認)", "value": "%d/%d/%d 本" % (n_brk, n_mid, n_unk), "status": "確認済み"},
    {"key": "condition.rotor_hub_seizure", "value": cond["rotor_hub_seizure"]["state"], "status": "不明"},
    {"key": "condition.underbody_rust_grade(subframe)", "value": None, "status": "不明"},
    {"key": "elapsed_waits.rustproof_dry_wait_hours", "value": dry, "status": "仮定"},
    {"key": "shop_policy.contact_threshold", "value": "%.1f人時 / %d円超" % (thr["labor_hours_gt"], thr["yen_gt"]), "status": "仮定"},
    {"key": "cost_data_S27", "value": "年間経費合計 %d円 / %d人時" % (annual_cost, cost["annual_billable_hours"]), "status": "申告"},
]

n_contact = sum(1 for c in conditions if c["contact"].startswith("要連絡"))
intermediates = [
    {"label": "確定分（観察済みの問題あり）", "value": r2(definite_h["typical"]), "unit": "人時",
     "formula": "AG-BOOT(左) typical %.2f x %d個 = %.2f" % (op("AG-BOOT", "typical"), BOOT_N, definite_h["typical"])},
    {"label": "条件付き追加の件数（連絡判定の対象）", "value": len(conditions) + 1, "unit": "条件",
     "formula": "C1〜C6 の %d 条件（未確認も常に載せる）+ 数値化できない C7 の1条件" % len(conditions)},
    {"label": "時間単価（年間配賦）", "value": r2(unit_price), "unit": "円/人時",
     "formula": "(%d+%d+%d+%d+%d+%d) / %d = %d / %d" % (
         cost["labor_cost_yen"], cost["rent_yen"], cost["heating_yen"], cost["equipment_yen"],
         cost["utilities_excl_heating_yen"], cost["target_profit_yen"], cost["annual_billable_hours"],
         annual_cost, cost["annual_billable_hours"])},
    {"label": "折れ込み C1 の1本あたり追加（low〜high）", "value": "%.2f〜%.2f" % (by_id["C1"]["per"]["low"], by_id["C1"]["per"]["high"]), "unit": "人時/本",
     "formula": "FX-BROKEN(%.2f〜%.2f) + FX-THREAD(%.2f〜%.2f)" % (op("FX-BROKEN", "low"), op("FX-BROKEN", "high"), op("FX-THREAD", "low"), op("FX-THREAD", "high"))},
    {"label": "ローター固着 C4 の最大追加（両側 high）", "value": r2(by_id["C4"]["max_total"]["high"]), "unit": "人時",
     "formula": "(FX-ROTOR %.2f + FX-HUBCLEAN %.2f) x %d側" % (op("FX-ROTOR", "high"), op("FX-HUBCLEAN", "high"), SIDES)},
    {"label": "条件付き追加の合計（全条件が上限で発生）", "value": r2(cond_total_high), "unit": "人時",
     "formula": "C2(重・中 %d本 固着 high) %.2f + C1(重 %d本 折れ込み high) %.2f + C3 %.2f + C4 %.2f + C5 %.2f = %.2f（約%d円）。確定分 %.2f と合わせた high = %.2f" % (
         n_brk + n_mid, mx("C2"), n_c1, mx("C1"), mx("C3"), mx("C4"), mx("C5"), cond_total_high, round(cond_total_yen_high),
         base + definite_h["typical"], labor["high"])},
    {"label": "経過時間 high の内訳", "value": r2(elapsed["high"]), "unit": "時間",
     "formula": "人時 high %.2f + 浸透待ち %.2f + 防錆乾燥待ち %.2f（C4 を含むため）" % (labor["high"], soak, dry if "C4" in by_id else 0.0)},
    {"label": "作業前連絡の対象になる条件", "value": n_contact + 1, "unit": "条件",
     "formula": "条件表のうち要連絡 %d 条件 + C7(常に連絡)" % n_contact},
]

cond_table = []
for c in conditions:
    cond_table.append({
        "label": "%s %s [%s] %s" % (c["id"], c["trigger"], c["status"], c["contact"]),
        "value": "%.2f〜%.2f（最大%d%s、上限合計 %.2f人時・約%d円）" % (
            c["per"]["low"], c["per"]["high"], c["max_n"], c["unit"], c["max_total"]["high"],
            round(yen(c["max_total"]["high"]))),
        "unit": "人時/%s" % c["unit"]})
cond_table.append({"label": "C7 腐食による作業範囲の拡大 [未確認部位: %s] 要連絡（常に）" % "、".join(scope_areas),
                   "value": "数値化しない（見積もり変更と顧客の了承が必要）", "unit": ""})

other_outputs = [
    {"label": "時間単価（年間配賦）", "value": r2(unit_price), "unit": "円/人時"},
    {"label": "確定分の金額（typical）", "value": round(yen(definite_h["typical"])), "unit": "円"},
    {"label": "条件付き追加の金額（全条件が上限）", "value": round(cond_total_yen_high), "unit": "円"},
    {"label": "金額基準を人時に直した値", "value": r2(hours_at_yen_limit), "unit": "人時（%d円 / 時間単価）" % thr["yen_gt"]},
    {"label": "連絡基準", "value": "追加が %.1f人時 または %d円 を超えうるなら作業前に連絡" % (thr["labor_hours_gt"], thr["yen_gt"]), "unit": ""},
    {"label": "ブレーキホース取り寄せ待ち（C6 発生時のみ）", "value": 24, "unit": "時間（暦時間）"},
] + cond_table

result = {
    "id": "S20",
    "name": "条件付き見積書（追加発生時の連絡基準）",
    "base_method": "共",
    "factors": ["HK01", "AG01", "AG02", "AG03", "AG04"],
    "algorithm": [
        "手順1: 重複控除後の基準 1.7 人時から始める",
        "手順2: 観察済みで問題ありの項目（左ブーツ硬化）だけを確定分として加算する",
        "手順2b: 経過年数・走行距離は工数にも条件数にも使わない。確認強度で未確認の条件を消さず、常に条件表と high に載せる（AG07、U2・U3）",
        "手順3: 固着・折れ込み・ローター固着・右ブーツ・ホース等を『発生条件・件数・追加人時の範囲』として条件化する（C1〜C6）。ホース C6 は U8 により参考のみ。数値化できない範囲拡大は C7（サブフレームは作業範囲外のため人時に入れない、U4）",
        "手順4: 年間配賦の時間単価を算出し、金額基準を人時に直す（仮定）",
        "手順5: 条件ごとに、1回あたりまたは最大件数ぶんの上限が 0.5人時／5000円 を超えうるかで連絡要否を判定する",
        "手順6（U3）: low=基準+確定分+重ボルトの FX-SEIZE low、typical=確定分+重・中ボルトの FX-SEIZE typical、high=重・中の FX-SEIZE high+重の折れ込み(FX-BROKEN+FX-THREAD)+未確認ボルト・ローター・右ブーツの上限（ホースは含めない）",
        "手順7（U5）: 浸透待ちを FX-SEIZE を含む low/typical/high の経過時間に足す。high は C4 を含むので防錆乾燥待ちも足す",
    ],
    "inputs": inputs,
    "intermediates": intermediates,
    "result": {
        "labor_hours": {k: r2(v) for k, v in labor.items()},
        "elapsed_hours": {k: r2(v) for k, v in elapsed.items()},
        "other_outputs": other_outputs,
        "operation_flow": [
            "作業中に条件(C1〜C7)が発生したら、同じ画面で『条件ID・本数・実績人時』を記録する",
            "『要連絡（1回で超える）』と C7 は、その場で作業を止めて顧客へ連絡し、了承後に続ける",
            "『要連絡（累積で超える）』は発生ごとに記録し、その条件の累計が基準を超える前に連絡する",
            "『参考』（C6 ブレーキホース）は範囲の人時に入れず、発見時に連絡要否を判断する（U8）",
            "『連絡不要』は記録のみ。顧客との合意方法は工場に未確認（unknowns 参照）",
        ],
        "note": "見積書は『確定 %.2f人時（基準1.7+確定分）＋条件付き追加』の形で示す。low は重のボルトの固着対応 low のみ、typical は重・中のブラケットボルト%d本の固着対応を見込み、high はこの案の範囲での上限として、折れ込み・ローター固着・未確認ボルト・右ブーツを常に含める。ホース(C6)は U8 により high に入れず条件表の参考、範囲拡大(C7)は数値化しない。年式・走行距離は工数にも条件数にも使わない。"  % (base + definite_h["typical"], n_brk + n_mid),
    },
    "assumptions": [
        "仮定: 時間単価は cost_data_S27 の年間経費（人件費・家賃・暖房費・設備・光熱・目標利益）÷年間請求可能時間の年間配賦 = %s円/人時。冬季配賦は使わない" % r2(unit_price),
        "仮定: 折れ込み1本につきねじ山修正1か所を伴う",
        "仮定: 連絡判定は『追加が基準を超えうるか』を high 値で見る。基準は工場の仮置き",
        "仮定: 折れ込み(C1)は固着対応(C2)を試みたあとに起きる別工程として足す（U3。二重計上ではない）",
        "仮定: 未確認の条件(C3〜C5)は確認強度に関わらず high にだけ入れる（U2）。ブレーキホース(C6)は U8 により high に入れない",
        "仮定: 経過時間は作業者1人で連続作業する前提。雪下ろし・氷塊除去・洗浄は S20 の要因外のため加えない",
        "仮定: ブレーキホース取り寄せ待ちは1日（24時間）。scenario.json には文字列『1日』のみのためコード側で 24 を直書き",
        "仮定: C7 の重度しきい値は underbody_rust_grade >= %d、ローターは左右 %d 側、ブーツは片側 %d 個" % (RUST_SEVERE, SIDES, BOOT_N),
        "仮定: 確定分（左ブーツ）は観察済みのため low/high でも typical 値で固定する。待機は U5 に従い、浸透待ちは FX-SEIZE を含む各範囲に、防錆乾燥待ち（冬季仮説）は C4 を含む high にだけ足す",
        "仮定: 基準 1.7 は 18kg 以下・1人運搬を前提とするが tire_with_wheel_weight_kg は 23kg（仮定）。S20 の要因外のため S17 等で確認が必要",
    ],
    "unknowns": [
        "右スライドピンブーツの状態（未確認）",
        "スライドボルト4本の錆（ブーツに隠れて未確認）",
        "ローター・ハブの固着（分解前のため不明）",
        "サブフレームの腐食（アンダーカバーで見えず写真なし）。J1・J2 では外さず作業範囲外。腐食があれば作業範囲の拡大（AG04, C7）として見積もりを変更し、顧客の了承を得る",
        "ブレーキホースの劣化（未観察。U8 により high に入れず条件表の参考のみ）",
        "防錆アンダーコート（申告）の下に腐食が隠れている可能性",
        "顧客との条件合意の方法は工場に未確認",
    ],
}

out = json.dumps(result, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S20.json").write_text(out + "\n", encoding="utf-8")
print(out)
