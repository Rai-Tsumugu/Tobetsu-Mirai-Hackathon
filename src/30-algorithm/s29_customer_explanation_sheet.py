#!/usr/bin/env python3
"""S29 顧客向けの説明シート

反映する要因: HK01（融雪剤による腐食）, HK02（車体の雪）, HK03（ホイールハウスの氷塊）,
              AG01（締結部の固着・折れ込み）, AG03（ゴム部品の硬化）, AG02（付随部品の候補）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. 見積もりを顧客向けの「行」に分ける。各行は 人時(low/typical/high)・根拠(写真の有無、観察か未確認か)・
    区分 を持つ。区分は次の3つ。
      確定      : 観察があり、追加工程が特定できる行。typical に入れる（雪下ろし、氷塊除去、左ブーツ交換）。
      可能性    : 写真つきで錆などを観察したが、固着・折れ込みが実際に起きるかは分解前で不明な行。
                  低位は 0、typical は固着対応、high は折れ込みも含める。
      未確認    : 観察も写真もない行。一般論だけで追加を正当化しないため typical には入れず、
                  high にだけ入れ、unknowns に記録する（右ブーツ、スライドボルト、ローター固着、サブフレーム）。
 3. 写真の有無は photo_guide_S24 の taken / missing_reason と突き合わせる。写真のない行は、入庫時の観察記録
    （scenario.json の condition が「問題あり」）で裏づけられる場合に限り「確定」にし、写真欄に
    「写真なし（入庫時の観察記録）」と明示する（雪下ろし・氷塊除去）。観察記録もない行は「確定」にしない。
 4. 行の組み立て:
      A 基準作業          : 1.7 人時（確定）
      B 雪下ろし          : PRE-SNOW x 入庫1回（snow_on_body が問題あり）
      B 氷塊除去          : PRE-ICE x 問題ありのホイールハウス数（後輪は除去不要なので数えない）
      C 固着の可能性      : 重/中のブラケットボルト（左右のブラケット写真あり）に FX-SEIZE。
                            SPEC U3: 重は low=FX-SEIZE low、high=FX-SEIZE high+FX-BROKEN high+FX-THREAD high。中は low 0。
      D 未確認の締結部    : スライドボルト4本は typical に入れず high に FX-SEIZE を加える。
      D ローター固着      : 状態は未確認。high に FX-ROTOR x 左右を加える。
      E 付随部品の候補    : 左ブーツ硬化（観察・写真あり）は確定行。右ブーツは high のみ。
                            ブラケットボルト交換は部品代のみ（工数は固着対応に含む）。表示しきい値以上の候補を別記。
 5. 合計 = 全行の合計。範囲は low / typical / high の3値。確率で平均化した値は使わない。
 6. 下回り洗浄（PRE-WASH）は範囲内の実作業なので labor_hours に入れる（SPEC U7）。請求人時（洗浄を除く）は other_outputs に別記する。暖房費・家賃・材料費も人時に足さない。
 7. 経過時間 = 人時（1人で順に作業する仮定）+ 待機。融解待ちは氷塊除去があれば全範囲に、浸透待ちは
    その範囲に固着対応の人時がある範囲にだけ加える。重の固着対応は low も > 0 なので low にも浸透待ちを加える。
    待機は人時に入れない。経過時間 = labor_hours（洗浄込み）+ 待機。
    サブフレーム前部は追加工程を特定できず人時を置けないので、上限（high）にも未算入とし、
    未算入であることを合計と同じ other_outputs に明示する。
 8. 追加分が連絡基準（0.5 人時超）を超える範囲は、作業前に顧客へ連絡する注記を出す。
 9. 人時は丸めずに計算し、出力時だけ小数第2位に丸める。結果を標準出力と results/S29.json に書く。
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
guide = SC["photo_guide_S24"]
waits = SC["elapsed_waits"]
pol = SC["shop_policy"]
cat = pol["companion_parts_catalog_S22"]
mat = SC["materials_S28"]

taken = set(guide["taken"])
def photo(*names):
    return all(n in taken for n in names)

def rng(op, n=1, only=None):
    """工程 op を n 回。only を指定した範囲にだけ値を入れる。"""
    return {r: (ops[op][r] * n if (only is None or r in only) else 0.0) for r in RANGES}

def add(*ds):
    return {r: sum(d[r] for d in ds) for r in RANGES}

rows = []
def row(group, name, hours, cls, photo_state, basis):
    rows.append({"group": group, "name": name, "class": cls, "photo": photo_state,
                 "basis": basis, "hours": hours})

# A 基準作業
row("A 基準作業", "冬タイヤ交換＋フロントブレーキパッド・ローター交換（重複控除後）",
    {r: base for r in RANGES}, "確定", "不要", "基準値。共通作業（リフトアップ・前輪脱着）の二重計上を除いた値")

# B 前処理
snow_obs = cond["snow_on_body"]["state"] == "問題あり"
if snow_obs:
    row("B 前処理", "雪下ろし", rng("PRE-SNOW"), "確定", "写真なし（入庫時の観察記録）",
        f"観察済み: {cond['snow_on_body']['detail']}。入庫1回分")
ice_n = cond["ice_in_wheel_house"]["locations"] if cond["ice_in_wheel_house"]["state"] == "問題あり" else 0
if ice_n:
    row("B 前処理", f"氷塊除去（前輪ホイールハウス{ice_n}か所）", rng("PRE-ICE", ice_n), "確定", "写真なし（入庫時の観察記録）",
        f"観察済み: {cond['ice_in_wheel_house']['detail']}")

sub_state = cond["underbody_rust_grade"]["subframe"]

# C 固着の可能性（観察あり: ブラケットボルト重・中）
brk = [f for f in cond["fasteners"] if "ブラケット" in f["name"]]
heavy = [f for f in brk if f["rust"].startswith("重")]
mid = [f for f in brk if f["rust"].startswith("中")]
brk_photo = photo("左ブラケット", "右ブラケット")
# SPEC U3: 重 = low FX-SEIZE low / typical FX-SEIZE typical / high FX-SEIZE high + FX-BROKEN high + FX-THREAD high
#          中 = low 0 / typical FX-SEIZE typical / high FX-SEIZE high
n_seize = len(heavy) + len(mid)
nh = len(heavy)
seize_row = {
    "low": ops["FX-SEIZE"]["low"] * nh,
    "typical": ops["FX-SEIZE"]["typical"] * n_seize,
    "high": ops["FX-SEIZE"]["high"] * n_seize + (ops["FX-BROKEN"]["high"] + ops["FX-THREAD"]["high"]) * nh,
}
row("C 固着の可能性", f"キャリパーブラケットボルト（重 {len(heavy)} 本・中 {len(mid)} 本）の固着対応",
    seize_row, "可能性" if brk_photo else "未確認", "あり（左右ブラケット）" if brk_photo else "一部なし",
    "錆を観察し写真あり（頭部腐食 左2本、中程度 右2本）。外れるかは分解前で不明。SPEC U3: 重は low も固着対応、"
    "high は固着対応＋折れ込み抜き取り＋ねじ山修正。中は low 0")

# D 未確認（high のみ）
sld = [f for f in cond["fasteners"] if "スライド" in f["name"]]
row("D 未確認", f"スライドボルト（{len(sld)} 本、ブーツに隠れて錆の状態が見えない）",
    rng("FX-SEIZE", len(sld), only=("high",)), "未確認", "なし",
    "状態が見えないため0とは確定しない。typical に入れず high にだけ入れる")
rotor_state = cond["rotor_hub_seizure"]["state"]
row("D 未確認", "ローター固着の除去（左右）",
    rng("FX-ROTOR", 2, only=("high",)), "未確認" if rotor_state == "未確認" else "確定", "なし",
    f"ローターのハブ固着は{rotor_state}（ハブ錆グレード {cond['underbody_rust_grade']['wheel_hub']}）。分解後に判明")
# SPEC U4: サブフレームは作業範囲外。high に入れず unknowns に記録する
excluded_items = [
    "防錆アンダーコートの下に隠れた腐食（顧客申告。人時を置けず未算入。ブラケットボルト・サブフレーム周りで上乗せの可能性）"]

# ハブ錆（観察済み・写真あり）: 錆落とし・防錆
hub_grade = cond["underbody_rust_grade"]["wheel_hub"]
if hub_grade and hub_grade >= 2:
    row("B 前処理", "ハブ当たり面の錆落とし・防錆（左右）", rng("FX-HUBCLEAN", 2), "確定",
        "あり（左右ハブ）" if photo("左ハブ", "右ハブ") else "なし",
        f"ホイールハブの錆グレード {hub_grade}（進行錆）を観察済み。ローター取付面の錆落とし・防錆")

# E 付随部品の候補
lb = cond["slide_pin_boots"]["left"]
rb = cond["slide_pin_boots"]["right"]
left_ok = lb.startswith("問題あり")
row("E 付随部品", "スライドピンブーツ交換（左）",
    rng("AG-BOOT") if left_ok else {r: 0.0 for r in RANGES},
    "確定" if left_ok else "未確認", "あり（左スライドピンブーツ）" if photo("左スライドピンブーツ") else "なし",
    f"左は{lb}を観察")
right_unc = rb.startswith("未確認")
row("E 付随部品", "スライドピンブーツ交換（右）",
    rng("AG-BOOT", only=("high",)) if right_unc else {r: 0.0 for r in RANGES},
    "未確認", "なし（泥と氷で撮影不可）" if "右スライドピンブーツ" in guide["missing_reason"] else "なし",
    "右は未確認。typical に入れず high にだけ入れる")

for g in rows:
    g["hours"] = {r: g["hours"][r] for r in RANGES}

total = {r: sum(g["hours"][r] for g in rows) for r in RANGES}
by_class = {c: {r: sum(g["hours"][r] for g in rows if g["class"] == c) for r in RANGES}
            for c in ("確定", "可能性", "未確認")}
wash = ops["PRE-WASH"]  # SPEC U7: 範囲内の作業なので labor_hours に入れる。請求人時は別出し
billed = dict(total)
labor = {r: total[r] + wash[r] for r in RANGES}
added = {r: r2(total[r] - base) for r in RANGES}  # 浮動小数点誤差で連絡判定が狂わないよう丸めて比較

# 経過時間（1人で順に作業する仮定 + 待機）
ice_wait = waits["thaw_wait_hours"] if ice_n else 0.0
# SPEC U5: FX-SEIZE を含む範囲に浸透待ち、FX-HUBCLEAN を含む範囲に防錆乾燥（冬季仮説値）、氷塊除去があれば融解待ち
hub_in = any(g["name"].startswith("ハブ当たり面") for g in rows)
dry = waits["rustproof_dry_wait_hours"]["winter_hypothesis"] if hub_in else 0.0
soak = waits["penetrant_soak_wait_hours"]
elapsed = {
    "low": labor["low"] + ice_wait + dry + (soak if seize_row["low"] > 0 else 0.0),
    "typical": labor["typical"] + ice_wait + dry + (soak if seize_row["typical"] > 0 else 0.0),
    "high": labor["high"] + ice_wait + dry + (soak if seize_row["high"] > 0 else 0.0) + waits["parts_wait_hours"],
}

# 付随部品の候補（別記）
thr = cat["display_threshold_freq"]
cands = [{"part": k, "freq": v["freq"]} for k, v in cat.items() if isinstance(v, dict) and v.get("freq", 0) >= thr and v.get("op") != "AG-BOOT"]
cands.sort(key=lambda c: -c["freq"])
bolt_price = mat["bracket_bolt"]["price_yen"]
contact = pol["contact_threshold"]["labor_hours_gt"]

confirmed_rows = [g for g in rows if g["class"] == "確定"]
photo_rows = [g for g in rows if g["photo"].startswith("あり")]
unconf_rows = [g for g in rows if g["class"] == "未確認"]

intermediates = [
    {"label": "顧客向けの行数（確定 / 可能性 / 未確認）。確定には基準作業（観察不要）を含む", "value": f"{len(confirmed_rows)} / {sum(1 for g in rows if g['class']=='可能性')} / {len(unconf_rows)}", "unit": "行",
     "formula": "区分ごとの行数。確定=観察あり（基準作業は観察不要の基準値）、可能性=写真つき錆の観察のみ、未確認=観察なし"},
    {"label": "写真つきの根拠がある行", "value": len(photo_rows), "unit": "行",
     "formula": f"photo_guide_S24 の撮影済み {len(taken)} 枚と照合"},
    {"label": "確定行の追加人時（typical）", "value": r2(by_class["確定"]["typical"] - base), "unit": "人時",
     "formula": f"雪下ろし {ops['PRE-SNOW']['typical']} + 氷塊除去 {ops['PRE-ICE']['typical']} x {ice_n} + ハブ防錆 {ops['FX-HUBCLEAN']['typical']} x 2 + 左ブーツ {ops['AG-BOOT']['typical']}（基準 {base} は除く）"},
    {"label": "固着の可能性行（typical / high）", "value": f"{r2(seize_row['typical'])} / {r2(seize_row['high'])}", "unit": "人時",
     "formula": f"low = FX-SEIZE low x 重 {nh} 本。typical = FX-SEIZE {ops['FX-SEIZE']['typical']} x {n_seize} 本。high = FX-SEIZE high x {n_seize} + (FX-BROKEN high + FX-THREAD high) x 重 {nh} 本"},
    {"label": "未確認行が high に足す人時", "value": r2(by_class["未確認"]["high"]), "unit": "人時",
     "formula": f"スライドボルト {len(sld)} 本 x FX-SEIZE high + ローター 2 側 x FX-ROTOR high + 右ブーツ AG-BOOT high（サブフレーム前部は人時を置けず含まない）"},
    {"label": "追加人時の範囲（基準 1.7 を除く）", "value": f"{r2(added['low'])} / {r2(added['typical'])} / {r2(added['high'])}", "unit": "人時",
     "formula": "合計 - 基準 1.7（low / typical / high）"},
    {"label": "経過時間に入れる待機", "value": f"{r2(ice_wait + dry + (soak if seize_row['low'] > 0 else 0))} / {r2(ice_wait + dry + soak)} / {r2(ice_wait + dry + soak)}", "unit": "時間（low / typical / high）",
     "formula": f"（下回り洗浄は実作業なので経過時間に別途加える: {wash['low']}/{wash['typical']}/{wash['high']}）融解待ち {waits['thaw_wait_hours']}（氷塊除去があるので全範囲）+ 防錆乾燥 {dry}（ハブ処置があるので全範囲、冬季仮説値）+ 浸透待ち {soak}（固着対応を含む全範囲。low も重の固着対応を含む）。人時には入れない"},
]

rows_out = [{"group": g["group"], "name": g["name"], "class": g["class"], "photo": g["photo"],
             "basis": g["basis"], "labor_hours": {r: r2(g["hours"][r]) for r in RANGES}} for g in rows]

contact_flags = [r for r in RANGES if added[r] > contact]
out = {
    "id": "S29",
    "name": "顧客向けの説明シート",
    "base_method": "A",
    "factors": ["HK01", "HK02", "HK03", "AG01", "AG02", "AG03"],
    "algorithm": [
        "手順1: 重複控除後の基準 1.7 人時を A 行に置く",
        "手順2: 入庫時の観察から雪下ろし・氷塊除去（問題ありのホイールハウス数）の確定行を作る",
        "手順3: 写真つきで錆を観察した重/中のブラケットボルトを「可能性」行にする（SPEC U3: 重は low=固着対応、high=固着対応＋折れ込み抜き取り＋ねじ山修正。中は low 0、typical・high は固着対応）",
        "手順4: 観察も写真もない締結部・ローター・右ブーツを「未確認」行にし、high にだけ入れる。サブフレームは作業範囲外（U4）で unknowns に記録",
        "手順5: 左ブーツ硬化（観察・写真あり）を確定行に、付随部品の候補は頻度がしきい値以上のものを別記する",
        "手順6: 各行に写真の有無と観察/未確認の根拠を付け、合計の人時範囲と人時（下回り洗浄を含む）と経過時間（人時＋待機: 融解0.5・浸透0.25・防錆乾燥0.3 を含む範囲に足す。待機は人時に入れない）を出す",
        "手順7: 追加分が連絡基準を超える範囲に、作業前連絡の注記を付ける",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "condition.snow_on_body", "value": cond["snow_on_body"]["detail"], "status": "確認済み"},
        {"key": "condition.ice_in_wheel_house.locations", "value": ice_n, "status": "確認済み"},
        {"key": "condition.fasteners（ブラケット重/中）", "value": f"重{len(heavy)}・中{len(mid)}", "status": "確認済み"},
        {"key": "condition.fasteners（スライドボルト）", "value": "未確認（ブーツに隠れて見えない）", "status": "不明"},
        {"key": "condition.rotor_hub_seizure", "value": rotor_state, "status": "不明"},
        {"key": "condition.slide_pin_boots", "value": f"左: {lb} / 右: {rb}", "status": "確認済み"},
        {"key": "condition.underbody_rust_grade.subframe", "value": sub_state, "status": "不明"},
        {"key": "photo_guide_S24.taken", "value": f"{len(taken)}/{len(guide['required_shots_for_J2'])} 枚", "status": "確認済み"},
        {"key": "condition.rustproof_undercoat", "value": cond["rustproof_undercoat"]["detail"], "status": "申告"},
    ],
    "intermediates": intermediates,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "顧客向け見積もり行（根拠つき）", "value": rows_out, "unit": "リスト"},
            {"label": "付随部品の候補（別記。頻度がしきい値以上。スライドピンブーツは確定行・未確認行で計上済みのため除く）", "value": cands, "unit": "リスト"},
            {"label": "ブラケットボルト交換の部品代（候補。重・中の全数 4 本を交換する場合の最大額。頻度で重みづけしていない。本体に含めない）", "value": (len(heavy) + len(mid)) * bolt_price, "unit": "円"},
            {"label": "作業前に顧客へ連絡する範囲（追加が0.5人時超）", "value": contact_flags, "unit": "範囲"},
            {"label": "上限に含まれない未算入項目（人時0ではなく、人時を置けないため合計外）", "value": excluded_items,
             "unit": "リスト（合計に含まない）"},
            {"label": "labor_hours の定義", "value": "実作業人時。範囲内の下回り洗浄を含む（SPEC U7）。請求人時は別項目", "unit": "注記"},
            {"label": "請求人時（下回り洗浄を除く）", "value": {r: r2(billed[r]) for r in RANGES}, "unit": "人時"},
            {"label": "下回り洗浄（実施するが請求しない。labor_hours には含む）", "value": {r: wash[r] for r in RANGES}, "unit": "人時（請求外）"},
        ],
        "note": "範囲の幅は、確定した追加と、写真つきの可能性と、未確認の3区分に分けて顧客に見せるためのもの。"
                "high はこの案の範囲での上限（重のブラケットボルトの折れ込み抜き取り・ねじ山修正、未確認項目の上限を含む）。"
                "サブフレーム前部は作業範囲外（腐食があれば作業範囲の拡大として見積もりを変更し顧客の了承を得る）、防錆コート下の腐食は人時を置けず合計外。"
                "未確認は『なし』とは確定しておらず、分解して状態が分かった時点で連絡する。labor_hours と経過時間には請求外の下回り洗浄を含む。"
                "地域や年式の一般論からは加算していない。",
    },
    "assumptions": [
        "仮定: SPEC U3 に従い、重のブラケットボルトは全数、high で固着対応＋折れ込み抜き取り＋ねじ山修正を見込む",
        "仮定: 経過時間は1人で順に作業する前提（人時（請求外の下回り洗浄を含む）+ 待機）",
        "仮定: 可能性行の low は固着が起きない場合として 0",
        "仮定: サブフレーム前部は SPEC U4 により作業範囲外（high に入れない）。防錆コート下の腐食は人時を置けないため『上限に含まれない未算入項目』として別表示する",
        "仮定: ローター固着除去は左右2側で数える",
        "仮定: ハブ錆グレード2以上は観察・写真ありとして錆落とし・防錆を左右分、確定行に入れる",
        "仮定: SPEC U5 に従い、浸透待ち・防錆乾燥（冬季仮説値）・融解待ちは該当工程を含む範囲に加える（low も重の固着対応とハブ処置を含む）",
        f"仮定: SPEC U7 に従い labor_hours に下回り洗浄 typical {wash['typical']} 人時を含める。請求人時は other_outputs に別記",
        "仮定: 雪下ろし・氷塊除去は写真ではなく入庫時の観察記録（condition）を根拠に確定とする。説明シートでは写真欄に『写真なし（入庫時の観察記録）』と記載し、観察内容の文言を併記する",
    ],
    "unknowns": [
        "スライドボルト4本の錆（ブーツに隠れて見えない）",
        "ローターのハブ固着（分解前）",
        "右スライドピンブーツの状態（泥と氷で撮影不可）",
        "サブフレーム前部の腐食（アンダーカバーで見えず撮影なし）。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る",
        "防錆アンダーコートが下の腐食を隠している可能性（顧客申告）",
    ],
}

(HERE / "results").mkdir(exist_ok=True)
text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results" / "S29.json").write_text(text + "\n", encoding="utf-8")
print(text)
