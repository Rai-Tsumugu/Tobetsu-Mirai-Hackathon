#!/usr/bin/env python3
"""S01 状態チェックリスト加算型

手順:
1. scenario.json を読み、出発点を重複控除後の基準 1.7 人時 (base_totals.deduplicated_base) とする。
2. 作業 J1/J2 ごとに、錆・固着・損傷・改造のチェック項目を scenario.json の現車状態から作る。
3. 各項目を「未確認／問題を観察していない／問題あり」の3択で評価する。未確認を問題なしに置き換えない。
   - 問題あり: 対応する追加工程 (mechanic_provisional_add_ops) の人時を加算する。
     締結部は SPEC の U3 の表（中: low 0 / typical FX-SEIZE typ / high FX-SEIZE high、
     重: low FX-SEIZE low / typical FX-SEIZE typ / high FX-SEIZE high + FX-BROKEN high + FX-THREAD high）。
   - 問題を観察していない: 加算しない。
   - 未確認（案の範囲内: スライドボルト4本、ローター左右、右ブーツ）: typical に入れず、high に追加工程の high を入れる（U2, U3）。
     「追加の可能性あり」の別表示も other_outputs に残す。
4. 待機（U5）: FX-SEIZE を含む区分に浸透待ち 0.25、FX-HUBCLEAN を含む区分に防錆乾燥 0.3（冬季仮説値）を経過時間にだけ足す。
   氷塊除去は範囲外なので融解待ちは入れない。
5. 雪下ろし・氷塊除去・下回り洗浄 (HK02, HK03) は S05 の要因なので本案では扱わない。
6. 地域・年式・走行距離だけでは加算しない。扱う要因は HK01, AG01, AG02, AG03, AG06。
   AG02（付随部品破損）は S22 の領分で、表示しきい値未満の候補を含め加算しない（U8）。
   サブフレームは作業範囲外（U4）。タイヤ重量差は S07 の領分（U6）。
7. 人時は丸めずに合算し、出力時のみ小数第2位に丸める。結果を標準出力と results/S01.json に出す。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "scenario.json"), encoding="utf-8") as f:
    S = json.load(f)

OPS = S["mechanic_provisional_add_ops"]
COND = S["condition"]
BASE = S["base_totals"]["deduplicated_base"]
WAITS = S["elapsed_waits"]
UNCONF, NOOBS, PROB = "未確認", "問題を観察していない", "問題あり"

items = []  # チェック項目


def add_item(job, cat, factor, name, state, lo=0.0, ty=0.0, hi=0.0, ops=()):
    """lo/ty/hi はこの項目が low/typical/high に足す人時。ops は含まれる追加工程のキー。"""
    items.append(dict(job=job, cat=cat, factor=factor, name=name, state=state,
                      ops=list(ops), low=lo, typical=ty, high=hi))


# --- J1 ---（冬季前処理は S05 の領分のため入れない）
nut = [x for x in COND["fasteners"] if x["job"] == "J1"][0]
add_item("J1", "固着", "AG01", "ホイールナット%d本（錆: 軽=通常）" % nut["count"], NOOBS)
add_item("J1", "改造", "AG06", "社外アルミホイール（ハブ径リング）: 承認済み追加工程なし", NOOBS)

# --- J2 締結部（SPEC U3 の表）---
SZ, BR, TH, RT, HC, BT = (OPS[k] for k in ("FX-SEIZE", "FX-BROKEN", "FX-THREAD", "FX-ROTOR", "FX-HUBCLEAN", "AG-BOOT"))
for x in COND["fasteners"]:
    if x["job"] != "J2":
        continue
    r = x["rust"]
    if r.startswith("重"):
        add_item("J2", "固着", "AG01", x["name"] + "（重）", PROB,
                 SZ["low"], SZ["typical"], SZ["high"] + BR["high"] + TH["high"],
                 ("FX-SEIZE", "FX-BROKEN", "FX-THREAD"))
    elif r.startswith("中"):
        add_item("J2", "固着", "AG01", x["name"] + "（中）", PROB, 0.0, SZ["typical"], SZ["high"], ("FX-SEIZE",))
    elif r.startswith("未確認"):
        add_item("J2", "固着", "AG01", x["name"] + "（未確認）", UNCONF, 0.0, 0.0, SZ["high"], ("FX-SEIZE",))
    else:
        add_item("J2", "固着", "AG01", x["name"], NOOBS)

# ハブ錆（グレード2=進行錆 → 問題あり、左右）
hub = COND["underbody_rust_grade"]["wheel_hub"]
if hub >= 2:
    add_item("J2", "錆", "HK01", "ハブ当たり面の錆 グレード%d（左右）" % hub, PROB,
             2 * HC["low"], 2 * HC["typical"], 2 * HC["high"], ("FX-HUBCLEAN",))
else:
    add_item("J2", "錆", "HK01", "ハブ当たり面の錆 グレード%d" % hub, NOOBS)
# ローター固着（未確認、左右）: typical に入れず high に入れる（U2）
add_item("J2", "固着", "AG01", "ローター固着（左右）", COND["rotor_hub_seizure"]["state"],
         0.0, 0.0, 2 * RT["high"], ("FX-ROTOR",))
# ブーツ
bl, br = COND["slide_pin_boots"]["left"], COND["slide_pin_boots"]["right"]
if bl.startswith("問題あり"):
    add_item("J2", "損傷", "AG03", "スライドピンブーツ左（硬化）", PROB, BT["low"], BT["typical"], BT["high"], ("AG-BOOT",))
else:
    add_item("J2", "損傷", "AG03", "スライドピンブーツ左", NOOBS)
if br.startswith("未確認"):
    add_item("J2", "損傷", "AG03", "スライドピンブーツ右（未確認）", UNCONF, 0.0, 0.0, BT["high"], ("AG-BOOT",))
else:
    add_item("J2", "損傷", "AG03", "スライドピンブーツ右", NOOBS)
add_item("J2", "改造", "AG06", "改造（J2 の作業範囲に影響なし）", NOOBS)

tot = {k: sum(i[k] for i in items) for k in ("low", "typical", "high")}
labor = {k: BASE + tot[k] for k in tot}

# 経過時間（U5）: 人時 + 待機。浸透待ちは FX-SEIZE を含む区分、防錆乾燥は FX-HUBCLEAN を含む区分（冬季仮説値）。
# 氷塊除去は本案の範囲外なので融解待ちは入れない。
def wait_for(k):
    w = 0.0
    if any("FX-SEIZE" in i["ops"] and i[k] > 0 for i in items):
        w += WAITS["penetrant_soak_wait_hours"]
    if any("FX-HUBCLEAN" in i["ops"] and i[k] > 0 for i in items):
        w += WAITS["rustproof_dry_wait_hours"]["winter_hypothesis"]
    return w


waits = {k: wait_for(k) for k in labor}
elapsed = {k: labor[k] + waits[k] for k in labor}

n_prob = sum(i["state"] == PROB for i in items)
n_unconf = sum(i["state"] == UNCONF for i in items)
n_no = sum(i["state"] == NOOBS for i in items)


def sub(pred, k):
    return sum(i[k] for i in items if pred(i))


r = lambda v: round(v + 1e-12, 2)
unconf_hi = sub(lambda i: i["state"] == UNCONF, "high")
heavy = [i for i in items if "（重）" in i["name"]]
broken_add = sum(BR["high"] + TH["high"] for _ in heavy)

result = {
    "id": "S01",
    "name": "状態チェックリスト加算型",
    "base_method": "A",
    "factors": ["HK01", "AG01", "AG02", "AG03", "AG06"],
    "algorithm": [
        "手順1: 重複控除後の基準 %.1f 人時を出発点にする" % BASE,
        "手順2: J1/J2 の錆・固着・損傷・改造のチェック項目を現車状態から作る",
        "手順3: 各項目を 未確認／問題を観察していない／問題あり に分ける",
        "手順4: 問題あり → 追加工程の人時を加算。締結部は U3 の表（中: low 0・typical FX-SEIZE typical・high FX-SEIZE high、重: low FX-SEIZE low・typical FX-SEIZE typical・high FX-SEIZE high + FX-BROKEN high + FX-THREAD high）",
        "手順5: 未確認（スライドボルト4本・ローター左右・右ブーツ）は typical に入れず、high にだけ追加工程の high を加算する。「追加の可能性あり」の別表示と unknowns も残す",
        "手順6: 浸透待ち 0.25 を FX-SEIZE を含む区分、防錆乾燥 0.3（冬季仮説値）を FX-HUBCLEAN を含む区分の経過時間にだけ足す。融解待ち・冬季前処理は S05 の領分のため扱わない",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": BASE, "status": "確認済み"},
        {"key": "condition.fasteners(J2)", "value": "重2・中2・未確認4", "status": "確認済み/未確認混在"},
        {"key": "condition.underbody_rust_grade.wheel_hub", "value": hub, "status": "確認済み"},
        {"key": "condition.rotor_hub_seizure", "value": COND["rotor_hub_seizure"]["state"], "status": "不明"},
        {"key": "condition.slide_pin_boots", "value": "左: %s / 右: %s" % (bl, br), "status": "左 確認済み・右 不明"},
        {"key": "condition.modification", "value": COND["modification"], "status": "申告"},
    ],
    "intermediates": [
        {"label": "チェック項目の数（問題あり／未確認／観察せず）", "value": "%d／%d／%d" % (n_prob, n_unconf, n_no),
         "unit": "項目", "formula": "項目を3状態に分類して数える"},
        {"label": "問題あり項目の追加 low / typical / high",
         "value": "%.2f / %.2f / %.2f" % (r(sub(lambda i: i["state"] == PROB, "low")), r(sub(lambda i: i["state"] == PROB, "typical")), r(sub(lambda i: i["state"] == PROB, "high"))),
         "unit": "人時", "formula": "重2・中2の締結部（U3 の表）+ ハブ2×FX-HUBCLEAN + 左ブーツ×AG-BOOT。high には重の折れ込み・ねじ山修正を含む"},
        {"label": "重2本の折れ込み・ねじ山修正（high のみ）", "value": r(broken_add), "unit": "人時",
         "formula": "重%d本×(FX-BROKEN high %.2f + FX-THREAD high %.2f)" % (len(heavy), BR["high"], TH["high"])},
        {"label": "未確認項目の上限（high のみ）", "value": r(unconf_hi), "unit": "人時",
         "formula": "スライドボルト4×FX-SEIZE high + ローター2×FX-ROTOR high + 右ブーツ×AG-BOOT high"},
        {"label": "追加合計 low / typical / high", "value": "%.2f / %.2f / %.2f" % (r(tot["low"]), r(tot["typical"]), r(tot["high"])),
         "unit": "人時", "formula": "全項目の追加の合計（未確認は high のみ）"},
        {"label": "待機（浸透＋防錆乾燥）low / typical / high", "value": "%.2f / %.2f / %.2f" % (r(waits["low"]), r(waits["typical"]), r(waits["high"])),
         "unit": "時間（人時に含めない）",
         "formula": "FX-SEIZE を含む区分に %.2f + FX-HUBCLEAN を含む区分に %.2f" % (WAITS["penetrant_soak_wait_hours"], WAITS["rustproof_dry_wait_hours"]["winter_hypothesis"])},
    ],
    "result": {
        "labor_hours": {k: r(labor[k]) for k in ("low", "typical", "high")},
        "elapsed_hours": {k: r(elapsed[k]) for k in ("low", "typical", "high")},
        "other_outputs": [
            {"label": "追加の可能性あり（未確認項目・high にのみ含む）", "value": {
                "max_additional_labor_hours": r(unconf_hi),
                "items": [i["name"] for i in items if i["state"] == UNCONF]}, "unit": "人時"},
            {"label": "チェック項目の内訳", "value": [
                {k: (round(v, 2) if isinstance(v, float) else v) for k, v in i.items()} for i in items], "unit": "一覧"},
        ],
        "note": ("基準 %.1f に、問題ありの項目の追加工程を加算。未確認 %d 項目（スライドボルト4本・ローター左右・右ブーツ）は typical に入れず、"
                 "この案の範囲での上限である high にだけ入れた（最大 +%.2f 人時、「追加の可能性あり」として別表示も残す）。"
                 "high には重2本の折れ込み・ねじ山修正（+%.2f 人時）も含む。typical %.2f 人時は観察済みの状態からの見込みで、未確認項目が問題ありだった場合は typical より増える。"
                 "冬季前処理（雪下ろし・氷塊除去・下回り洗浄）は本案の範囲外で人時に含めない。サブフレームは作業範囲外。") % (BASE, n_unconf, r(unconf_hi), r(broken_add), r(labor["typical"])),
    },
    "assumptions": [
        "仮定: 締結部は SPEC U3 の表のとおり。重は折れ込みの可能性があるため high に FX-BROKEN high と FX-THREAD high を各1本分加える（折れ込み確率はシナリオにない）",
        "仮定: 未確認項目は typical に入れず、追加工程の high を high にだけ加算する（U2）",
        "仮定: 経過時間は1人で直列に作業するとして、人時＋待機とする。待機は FX-SEIZE を含む区分に浸透 0.25、FX-HUBCLEAN を含む区分に防錆乾燥 0.3（冬季仮説値）。融解待ちは含めない",
        "仮定: ハブ錆グレード2以上を「問題あり」とし、左右に FX-HUBCLEAN を適用する",
        "仮定: 社外ホイールの改造は承認済み追加工程がなく、加算0とする",
        "仮定: 共通基準 1.7 は1人運搬前提で、タイヤ重量差は本案で扱わない（U6）",
    ],
    "unknowns": [
        "スライドボルト4本の錆（ブーツに隠れて未確認）。high にのみ含めた",
        "ローター・ハブの固着（分解前で未確認）。high にのみ含めた",
        "右スライドピンブーツの状態。high にのみ含めた",
        "サブフレームの腐食（アンダーカバーで見えず未確認）: J2 では外さないため作業範囲外。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る",
        "下回り錆グレードのブレーキ周り=3（重度）・フロントサスペンション=2: S01 のチェック項目に対応する承認済み追加工程がなく、加算していない（整備士に追加工程の確認が必要）",
        "AG02（外したときの付随部品破損）: scenario に観察状態がなく、表示しきい値未満の候補（パッドセンサー、ブレーキホース）も含め人時に加算しない（S22 の領分）",
        "冬季前処理（HK02/HK03）は S05 の領分のため本案では扱わない",
        "防錆アンダーコート（HK07）の影響は本案で扱わない",
    ],
}

out = json.dumps(result, ensure_ascii=False, indent=2)
print(out)
os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
with open(os.path.join(HERE, "results", "S01.json"), "w", encoding="utf-8") as f:
    f.write(out + "\n")
