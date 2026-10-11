#!/usr/bin/env python3
"""S15 状態に応じて分岐する工程テンプレート

反映する要因: HK01（融雪剤による腐食）, AG01（締結部の固着・折れ込み）,
              AG03（ゴム・樹脂部品の硬化。ブーツのみ）, AG04（腐食範囲の拡大。記録のみ）
              AG02（付随部品の破損）に対応する分岐は定義されていないため反映しない。

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。
 2. J1・J2 の included_operations を工程テンプレートとして読み、op ID が同じ共通工程
    （OP-LIFT, OP-WHEEL-F2）は1回だけ数えて基本工程一覧を作る。合計が
    base_totals.deduplicated_base（1.7 人時）と一致することを確認する。
 3. 分岐条件を condition の各状態に当てて判定する。各条件は 発火 / 未発火 / 判定不能 のいずれか。
      B1 ハブ錆グレード >= 2（問題あり）-> docs §4.3 のとおり FX-ROTOR（ローターの固着除去）と
                                        FX-HUBCLEAN を左右（2側）追加。全範囲
      B2 ブラケットボルトの錆「重」    -> FX-SEIZE（全範囲）+ 折れ込み候補
                                        （FX-BROKEN + FX-THREAD は high のみ）
      B3 ブラケットボルト錆「中」    -> FX-SEIZE（typical・high。low は 0。SPEC U3）
      B4 スライドボルト錆「未確認」    -> 判定不能。high のみ FX-SEIZE
      B5 スライドピンブーツ「硬化」    -> AG-BOOT（その側、全範囲）
      B6 スライドピンブーツ「未確認」  -> 判定不能。high のみ AG-BOOT
      B7 ローター・ハブ固着「未確認」  -> 判定不能。FX-ROTOR は B1 で展開済みのため重複して足さない
      B8 サブフレーム錆グレード null   -> 判定不能。工程は展開せず unknowns に記録（AG04）
 4. 発火した分岐ごとに、追加工程を 数量 x 単価（mechanic_provisional_add_ops の low/typical/high）で
    展開し、展開後の工程一覧（基本工程 + 追加工程）と合計を得る。
    未確認は 0 と確定せず、typical には入れず high にだけ入れる（SPEC 共通ルール4）。
 5. 人時 = 1.7（基本工程の合計）+ 追加工程の合計。丸めず計算し、出力時だけ小数第2位に丸める。
    S15 は雪下ろし・氷塊・洗浄・タイヤ重量・実績参照などの他案の要因は加えない。
    地域・年式・走行距離からも加算しない。
 6. 待機（SPEC U5）: その範囲で FX-SEIZE を含めたら浸透待ち 0.25、FX-HUBCLEAN を含めたら
    防錆乾燥 0.3（winter_hypothesis）を、該当する low / typical / high の経過時間に足す。人時には入れない。
    折れ込み（観察なし）は B2 の high のみ。サブフレーム（U4）は作業範囲外で、unknowns に記録するだけ。
 7. SPEC.md の形で JSON を標準出力と results/S15.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")
base_total = SC["base_totals"]["deduplicated_base"]
OPS = SC["mechanic_provisional_add_ops"]
cond = SC["condition"]

# --- 手順2: テンプレート（共通工程は op ID で1回だけ数える） ---
template = {}
for job in SC["jobs"]:
    for o in job["included_operations"]:
        if o["op"] not in template:
            template[o["op"]] = {"op": o["op"], "name": o["name"], "hours": o["hours"],
                                 "from_jobs": [job["id"]]}
        else:
            template[o["op"]]["from_jobs"].append(job["id"])
template_list = list(template.values())
template_sum = sum(t["hours"] for t in template_list)
assert abs(template_sum - base_total) < 1e-9, "テンプレート合計が重複控除後の基準と一致しない"

# --- 手順3-4: 分岐の判定と追加工程の展開 ---
expanded = []     # 追加工程: {branch, op, name, qty, low, typical, high, note}
branches = []     # 分岐判定の記録

def add(branch, op, qty, ranges, note=""):
    """ranges: 工程を入れる範囲のタプル。入れない範囲は 0。"""
    o = OPS[op]
    row = {"branch": branch, "op": op, "name": o["name"], "qty": qty, "per": o["per"], "note": note}
    for r in RANGES:
        row[r] = qty * o[r] if r in ranges else 0.0
    expanded.append(row)

def record(bid, rule, status, detail):
    branches.append({"id": bid, "condition": rule, "status": status, "detail": detail})

fasteners = cond["fasteners"]
j2_brk = [f for f in fasteners if f["job"] == "J2" and "BRK" in f["id"]]
j2_sld = [f for f in fasteners if f["job"] == "J2" and "SLD" in f["id"]]
heavy = [f for f in j2_brk if f["rust"].startswith("重")]
mid = [f for f in j2_brk if f["rust"].startswith("中")]
unk_sld = [f for f in j2_sld if f["rust"].startswith("未確認")]

# B1 ハブ錆グレード
hub = cond["underbody_rust_grade"]["wheel_hub"]
if hub is not None and hub >= 2:
    add("B1", "FX-ROTOR", 2, RANGES, "ハブ錆グレード%d >= 2（問題あり）-> ローターの固着除去（docs §4.3）、左右" % hub)
    add("B1", "FX-HUBCLEAN", 2, RANGES, "ハブ錆グレード%d >= 2 -> 当たり面の錆落とし、左右" % hub)
    record("B1", "ハブ錆グレード >= 2 -> FX-ROTOR + FX-HUBCLEAN", "発火", "wheel_hub=%d、左右2側" % hub)
else:
    record("B1", "ハブ錆グレード >= 2 -> FX-ROTOR + FX-HUBCLEAN", "未発火" if hub is not None else "判定不能", "wheel_hub=%s" % hub)

# B2 ブラケットボルト 重
if heavy:
    add("B2", "FX-SEIZE", len(heavy), RANGES, "頭部腐食（重）のため固着対応は要る（U3: 全範囲）")
    add("B2", "FX-BROKEN", len(heavy), ("high",), "折れ込み候補（可能性のため high のみ）")
    add("B2", "FX-THREAD", len(heavy), ("high",), "折れ込み1本につきねじ山1か所（仮定、high のみ）")
    record("B2", "ブラケットボルト錆「重」 -> FX-SEIZE + 折れ込み候補", "発火",
           "%d本: %s" % (len(heavy), ", ".join(f["id"] for f in heavy)))
else:
    record("B2", "ブラケットボルト錆「重」 -> FX-SEIZE + 折れ込み候補", "未発火", "該当なし")

# B3 ブラケットボルト 中
if mid:
    add("B3", "FX-SEIZE", len(mid), ("typical", "high"), "錆「中」-> 固着対応の可能性（U3: low は 0）")
    record("B3", "ブラケットボルト錆「中」 -> FX-SEIZE", "発火",
           "%d本: %s" % (len(mid), ", ".join(f["id"] for f in mid)))
else:
    record("B3", "ブラケットボルト錆「中」 -> FX-SEIZE", "未発火", "該当なし")

# B4 スライドボルト 未確認
if unk_sld:
    add("B4", "FX-SEIZE", len(unk_sld), ("high",), "未確認のため上限にのみ固着対応を含める")
    record("B4", "スライドボルト錆「未確認」 -> high のみ FX-SEIZE", "判定不能",
           "%d本: ブーツに隠れて見えない" % len(unk_sld))
else:
    record("B4", "スライドボルト錆「未確認」 -> high のみ FX-SEIZE", "未発火", "該当なし")

# B5/B6 スライドピンブーツ
boots = cond["slide_pin_boots"]
n_boot_hard = sum(1 for v in boots.values() if "硬化" in v)
n_boot_unk = sum(1 for v in boots.values() if v.startswith("未確認"))
if n_boot_hard:
    add("B5", "AG-BOOT", n_boot_hard, RANGES, "硬化を観察した側")
    record("B5", "ブーツ硬化 -> AG-BOOT", "発火", "%d側（左）" % n_boot_hard)
else:
    record("B5", "ブーツ硬化 -> AG-BOOT", "未発火", "該当なし")
if n_boot_unk:
    add("B6", "AG-BOOT", n_boot_unk, ("high",), "未確認のため上限にのみ")
    record("B6", "ブーツ未確認 -> high のみ AG-BOOT", "判定不能", "%d側（右）" % n_boot_unk)
else:
    record("B6", "ブーツ未確認 -> high のみ AG-BOOT", "未発火", "該当なし")

# B7 ローター・ハブ固着 未確認
rot = cond["rotor_hub_seizure"]["state"]
if rot == "未確認":
    if any(e["op"] == "FX-ROTOR" for e in expanded):
        record("B7", "ローター固着「未確認」 -> FX-ROTOR（B1 で展開済み）", "判定不能",
               "FX-ROTOR は B1（ハブ錆）が全範囲に展開済みのため二重に足さない")
    else:
        add("B7", "FX-ROTOR", 2, ("high",), "未確認のため上限にのみ左右")
        record("B7", "ローター固着「未確認」 -> high のみ FX-ROTOR", "判定不能", "左右2側")
else:
    record("B7", "ローター固着「未確認」 -> high のみ FX-ROTOR", "未発火", "state=%s" % rot)

# B8 サブフレーム（AG04）
sub = cond["underbody_rust_grade"]["subframe"]
if sub is None:
    record("B8", "サブフレーム錆 null -> 工程は展開せず記録", "判定不能", "アンダーカバーで見えず撮影なし")
else:
    record("B8", "サブフレーム錆 null -> 工程は展開せず記録", "未発火", "grade=%s" % sub)

add_sum = {r: sum(e[r] for e in expanded) for r in RANGES}
labor = {r: template_sum + add_sum[r] for r in RANGES}

# --- 手順6: 経過時間 ---
soak = SC["elapsed_waits"]["penetrant_soak_wait_hours"]
dry = SC["elapsed_waits"]["rustproof_dry_wait_hours"]["winter_hypothesis"]
elapsed = {}
wait = {}
for r in RANGES:
    seize = any(e["op"] == "FX-SEIZE" and e[r] > 0 for e in expanded)
    hubc = any(e["op"] == "FX-HUBCLEAN" and e[r] > 0 for e in expanded)
    wait[r] = (soak if seize else 0.0) + (dry if hubc else 0.0)
    elapsed[r] = labor[r] + wait[r]

fired = sum(1 for b in branches if b["status"] == "発火")
undetermined = sum(1 for b in branches if b["status"] == "判定不能")

def by_op(op, r):
    return sum(e[r] for e in expanded if e["op"] == op)

inter = [
    {"label": "テンプレート基本工程の合計（共通工程は1回）", "value": r2(template_sum), "unit": "人時",
     "formula": "J1・J2 の op を op ID で重複排除して合計 = 0.1+0.2+0.2+0.1+0.3+0.2+0.4+0.2"},
    {"label": "発火した分岐 / 判定不能の分岐", "value": [fired, undetermined], "unit": "件",
     "formula": "B1〜B8 のうち 発火 / 判定不能（未確認）の件数"},
    {"label": "待機時間（浸透待ち+防錆乾燥、low/typical/high）", "value": [r2(wait[r]) for r in RANGES], "unit": "時間",
     "formula": "FX-SEIZE を含む範囲に %.2f + FX-HUBCLEAN を含む範囲に %.2f（人時に入れない）" % (soak, dry)},
    {"label": "FX-SEIZE の人時（low/typical/high）", "value": [r2(by_op("FX-SEIZE", r)) for r in RANGES], "unit": "人時",
     "formula": "B2 重2本 x 単価(全範囲) + B3 中2本 x 単価(typical・high) + B4 未確認4本 x 単価(high のみ)"},
    {"label": "折れ込み候補 FX-BROKEN+FX-THREAD（high のみ）",
     "value": r2(by_op("FX-BROKEN", "high") + by_op("FX-THREAD", "high")), "unit": "人時",
     "formula": "2本 x (%.2f + %.2f)" % (OPS["FX-BROKEN"]["high"], OPS["FX-THREAD"]["high"])},
    {"label": "FX-HUBCLEAN + AG-BOOT + FX-ROTOR の人時（low/typical/high）",
     "value": [r2(by_op("FX-HUBCLEAN", r) + by_op("AG-BOOT", r) + by_op("FX-ROTOR", r)) for r in RANGES], "unit": "人時",
     "formula": "ハブ2側 x HUBCLEAN + ブーツ(左 / high は左右) x BOOT + ローター2側(B1、全範囲) x ROTOR"},
    {"label": "追加工程の人時合計（low/typical/high）", "value": [r2(add_sum[r]) for r in RANGES], "unit": "人時",
     "formula": "展開した追加工程の 数量 x 単価 の合計"},
    {"label": "展開後の工程合計（low/typical/high）", "value": [r2(labor[r]) for r in RANGES], "unit": "人時",
     "formula": "テンプレート 1.7 + 追加工程の合計"},
]

def row_out(e):
    return {"branch": e["branch"], "op": e["op"], "name": e["name"], "qty": e["qty"], "per": e["per"],
            "hours": {r: r2(e[r]) for r in RANGES}, "note": e["note"]}

expanded_list = (
    [{"branch": "template", "op": t["op"], "name": t["name"], "qty": 1, "per": "テンプレート",
      "hours": {r: r2(t["hours"]) for r in RANGES}, "note": "J1・J2: " + "/".join(t["from_jobs"])}
     for t in template_list]
    + [row_out(e) for e in expanded]
)

out = {
    "id": "S15",
    "name": "状態に応じて分岐する工程テンプレート",
    "base_method": "C",
    "factors": ["HK01", "AG01", "AG03", "AG04"],
    "algorithm": [
        "手順1: scenario.json を読む",
        "手順2: J1・J2 の included_operations をテンプレートにし、op ID が同じ共通工程は1回だけ数える（合計 1.7 人時）",
        "手順3: condition の各状態を分岐条件 B1〜B8 に当てて 発火 / 未発火 / 判定不能 を判定",
        "手順4: 発火した分岐は追加工程を全範囲に、判定不能（未確認）は high にだけ展開（数量 x 単価）",
        "手順5: 人時 = 1.7 + 追加工程の合計（他案の要因・地域・年式・走行距離は加えない）",
        "手順6: 経過時間に待機を足す（FX-SEIZE を含む範囲に浸透待ち 0.25、FX-HUBCLEAN を含む範囲に防錆乾燥 0.3。人時には入れない）",
        "手順7: SPEC の形で出力",
    ],
    "inputs": [
        {"key": "jobs[J1,J2].included_operations", "value": [t["op"] for t in template_list], "status": "仮定"},
        {"key": "base_totals.deduplicated_base", "value": base_total, "status": "確認済み"},
        {"key": "condition.underbody_rust_grade.wheel_hub", "value": hub, "status": "確認済み"},
        {"key": "condition.fasteners (J2)", "value": {f["id"]: f["rust"] for f in j2_brk + j2_sld}, "status": "確認済み（スライドボルトは不明）"},
        {"key": "condition.slide_pin_boots", "value": boots, "status": "確認済み（右は不明）"},
        {"key": "condition.rotor_hub_seizure", "value": cond["rotor_hub_seizure"]["state"], "status": "不明"},
        {"key": "condition.underbody_rust_grade.subframe", "value": sub, "status": "不明"},
        {"key": "mechanic_provisional_add_ops", "value": {k: {r: OPS[k][r] for r in RANGES} for k in
            ("FX-HUBCLEAN", "FX-SEIZE", "FX-BROKEN", "FX-THREAD", "AG-BOOT", "FX-ROTOR")}, "status": "仮定"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "分岐判定", "value": branches, "unit": ""},
            {"label": "展開後の工程一覧", "value": expanded_list, "unit": ""},
            {"label": "展開後の工程数", "value": len(expanded_list), "unit": "行"},
        ],
        "note": "テンプレートは重複排除後 1.7 人時。この案の範囲での上限として、未確認の分岐は high にだけ入れ、typical に確定しない。錆「中」は low=0、「重」は low から固着対応、折れ込みは観察がないため high のみ（SPEC U3）。サブフレームは作業範囲外（U4）。経過時間は人時 + 待機（浸透待ち 0.25、防錆乾燥 0.3 を含む範囲に加算、U5）。",
    },
    "assumptions": [
        "仮定: テンプレートは J1・J2 の included_operations を整備士が確認済みのものとして扱う。",
        "仮定: ハブ錆グレード2（進行錆=問題あり）のため、docs §4.3 の例どおり FX-ROTOR（ローターの固着除去）と FX-HUBCLEAN を左右2側に全範囲で展開する（グレードは左右共通の値として扱う）。",
        "仮定: docs の条件は「ボルト折れ」（観察された折れ）だが、scenario に折れの観察はなく、あるのは錆「重」=折れ込みの可能性（fastener_risk_rule）だけ。そのため FX-BROKEN と FX-THREAD は発生を観察していない可能性として high のみに入れ、typical には入れない（発生確率の根拠データがなく、期待値を作れない）。折れ込み1本につきねじ山1か所。",
        "仮定: high の折れ込み候補（2本分）は発生確率ではなく上限の見込みである。折れを観察したら B2 を「折れ観察」に切り替えて typical に入れる。",
        "仮定: SPEC U3 の表に従う。錆「中」は low=0・typical/high で FX-SEIZE、錆「重」は全範囲で FX-SEIZE、折れ込み（FX-BROKEN+FX-THREAD）は high のみ、未確認は high のみ FX-SEIZE。折れの観察がない限り「ボルト折れ」分岐は発火しない。",
        "仮定: ローター固着・右ブーツ・スライドボルトは未確認のため high のみ。low・typical には入れない。",
        "仮定: 経過時間は1人作業の直列で、待機（浸透待ち 0.25・防錆乾燥 0.3 の冬季仮説値）は該当工程を含む範囲ごとに1回だけ加える。",
        "仮定: 雪下ろし・氷塊・洗浄・タイヤ重量・過去実績などの他案の要因は、S15 の対象外のため含めない。",
    ],
    "unknowns": [
        "スライドボルト4本の錆は未確認（ブーツに隠れる）。high にのみ固着対応を含めた。",
        "右スライドピンブーツ・ローター固着は未確認。high にのみ含めた。",
        "サブフレームは J1・J2 では外さないため作業範囲外（U4）。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る。high には入れていない。",
        "折れ込みの実際の発生は分解前のため不明。high の折れ込み分（FX-BROKEN+FX-THREAD）は確率ではなく上限の見込み。",
        "ねじ山修正（FX-THREAD）用の部材の在庫は scenario に記載がなく、parts_wait_hours=0.0 は high 側には根拠がない。high の経過時間は部品待ちを含まない下限の可能性。",
        "ブレーキ周り錆グレード3（重度）に対応する分岐は docs・SPEC に定義がなく追加していない。過去実績（brake_rust 3 の追加工程）との整合は S15 の範囲外。",
        "AG02（付随部品の破損・部品待ち）に対応する分岐は定義がなく、反映していない。AG03 はブーツ（B5/B6）のみ。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
res = HERE / "results"
res.mkdir(exist_ok=True)
(res / "S15.json").write_text(text + "\n", encoding="utf-8")
print(text)
