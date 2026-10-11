#!/usr/bin/env python3
"""S09 同一車両の経年履歴の追跡

docs/man-hours/system-ideas-30.md の S09: 基盤 B、主に扱う要因 AG08, HK01。
仕組み: 過去の見積もり・観察・実作業人時を時系列で表示し、前回の観察から今回確認すべき箇所を提示する。
工数は算出する案として扱う（個別指示。SPEC 第2版 U1〜U3, U5）。前回 R11 の固着対応の単価を今回の観察に当てはめる。

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. 前回と今回を時系列で並べる（経過年数・走行距離の差、ハブ錆グレードの変化）。
 3. 前回の観察から固着対応の単価（人時/本）と本数を読む。R11: 1本 0.25 人時 → 単価 0.25。
 4. 今回の締結部を U3 の表で割り当てる。単価は FX-SEIZE の代わりに前回の 0.25 を使う。
    折れ込み・ねじ山修正は前回に実績がないので暫定値の high を使う（重の high のみ）。
 5. 前回なかった変化（ハブ錆の進行）は確認箇所に出し、範囲内の錆落とし（FX-HUBCLEAN）を high に入れる。
 6. 経過時間は U5 の待機（浸透 0.25、防錆乾燥 0.3）を足す。雪下ろし・氷塊は範囲外。
 7. SPEC.md の形で JSON を標準出力と results/S09.json に出す。
"""
import json
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
prev = SC["previous_visit_same_vehicle"]
cond = SC["condition"]
rule = cond["fastener_risk_rule"]

# --- 手順2: 前回と今回の並置 ---
d_now = date.fromisoformat(SC["intake"]["date"])
d_prev = date.fromisoformat(prev["date"])
years_between = (d_now - d_prev).days / 365.25
km_between = SC["vehicle"]["odometer_km"] - prev["odometer_km"]
fr = SC["vehicle"]["first_registration"]
reg = date(int(fr[:4]), int(fr[5:7]), 1)
age_now = (d_now - reg).days / 365.25
age_prev = (d_prev - reg).days / 365.25

m = re.search(r"グレード(\d)", prev["observations"])
hub_prev = int(m.group(1)) if m else None
hub_now = cond["underbody_rust_grade"]["wheel_hub"]


def rust_key(text):
    for k in ("未確認", "重", "中", "軽"):
        if text.startswith(k):
            return k
    return "未確認"


brk = [f for f in cond["fasteners"] if "ブラケット" in f["name"]]
sld = [f for f in cond["fasteners"] if "スライド" in f["name"]]
heavy = [f for f in brk if rust_key(f["rust"]) == "重"]
mid = [f for f in brk if rust_key(f["rust"]) == "中"]
sld_unk = [f for f in sld if rule[rust_key(f["rust"])].startswith("不明")]
rotor_state = cond["rotor_hub_seizure"]["state"]
subframe = cond["underbody_rust_grade"]["subframe"]

# --- 手順4: 今回確認すべき箇所（前回の観察との対応） ---
checklist = []
if "ブラケットボルト" in prev["observations"] and "固着" in prev["observations"]:
    checklist.append({"place": "左キャリパーブラケットボルト", "prev": "前回: 固着の観察あり",
                      "now": f"今回: 重（頭部腐食）{len(heavy)}本・中{len(mid)}本。外す前に固着・折れ込みを確認"})
if hub_prev is not None:
    trend = "進行" if hub_now > hub_prev else "変化なし"
    checklist.append({"place": "ハブ当たり面", "prev": f"前回: 錆グレード{hub_prev}",
                      "now": f"今回: 錆グレード{hub_now}（{trend}）。分解後に当たり面の状態を確認"})
checklist.append({"place": "スライドボルト", "prev": "前回: 記録なし",
                  "now": f"今回: 未確認{len(sld_unk)}本。ブーツをめくって確認"})
checklist.append({"place": "ローター・ハブの固着", "prev": "前回: 記録なし",
                  "now": f"今回: {rotor_state}。分解時に確認"})
if subframe is None:
    checklist.append({"place": "サブフレーム", "prev": "前回: 記録なし",
                      "now": "今回: 未確認（アンダーカバーで見えない）。次回比較のため撮影"})

# --- 手順3: 前回の単価と本数 ---
mp = re.search(r"(\d+)本が固着.*?対応\s*([0-9.]+)人時", prev["observations"])
prev_bolts = int(mp.group(1))
prev_cost = float(mp.group(2))
unit = prev_cost / prev_bolts  # 前回の同一車両実績の単価（人時/本）

ops = SC["mechanic_provisional_add_ops"]
waits = SC["elapsed_waits"]
broken_hi = ops["FX-BROKEN"]["high"]
thread_hi = ops["FX-THREAD"]["high"]
hub_clean_hi = ops["FX-HUBCLEAN"]["high"]

# --- 手順4: U3 の割り当て（単価は前回実績 unit） ---
n_heavy, n_mid, n_unk = len(heavy), len(mid), len(sld_unk)
seize_n = {"low": n_heavy, "typical": n_heavy + n_mid, "high": n_heavy + n_mid + n_unk}
seize = {r: seize_n[r] * unit for r in RANGES}
broken = {"low": 0.0, "typical": 0.0, "high": n_heavy * (broken_hi + thread_hi)}

# --- 手順5: ハブ錆の進行（前回なし）。範囲内の錆落とし(HK01)を high に ---
hub_sides = 2
hub_changed = hub_prev is not None and hub_now > hub_prev
hub = {"low": 0.0, "typical": 0.0, "high": hub_sides * hub_clean_hi if hub_changed else 0.0}

add = {r: seize[r] + broken[r] + hub[r] for r in RANGES}
labor = {r: base + add[r] for r in RANGES}

# --- 手順6: 経過時間（U5。待機は人時に入れない） ---
soak = waits["penetrant_soak_wait_hours"]
dry = waits["rustproof_dry_wait_hours"]["winter_hypothesis"]
wait = {r: (soak if seize_n[r] > 0 else 0.0) + (dry if hub[r] > 0 else 0.0) for r in RANGES}
elapsed = {r: labor[r] + wait[r] for r in RANGES}

# 確認箇所に今回の追加見込みを追記
for c in checklist:
    if c["place"] == "ハブ当たり面" and hub_changed:
        c["now"] += f"。前回なかった変化。錆落とし・防錆（FX-HUBCLEAN）を high に {r2(hub['high'])} 人時入れた"

inter = [
    {"label": "前回からの経過年数", "value": r2(years_between), "unit": "年",
     "formula": f"({SC['intake']['date']} - {prev['date']}) / 365.25"},
    {"label": "固着対応の単価（前回の同一車両実績）", "value": r2(unit), "unit": "人時/本",
     "formula": f"{prev['record_id']} の {prev_cost} 人時 / {prev_bolts} 本"},
    {"label": "固着対応の本数（low / typical / high）", "value": [seize_n[r] for r in RANGES], "unit": "本",
     "formula": f"U3: low=重{n_heavy}、typical=重{n_heavy}+中{n_mid}、high=typical+未確認スライドボルト{n_unk}"},
    {"label": "固着対応の人時（low / typical / high）", "value": [r2(seize[r]) for r in RANGES], "unit": "人時",
     "formula": "本数 x 前回単価"},
    {"label": "折れ込み＋ねじ山修正（high のみ）", "value": r2(broken["high"]), "unit": "人時",
     "formula": f"重{n_heavy}本 x (FX-BROKEN high {broken_hi} + FX-THREAD high {thread_hi})。前回に実績がないため暫定値"},
    {"label": "ハブ錆の進行に伴う錆落とし（high のみ）", "value": r2(hub["high"]), "unit": "人時",
     "formula": f"グレード {hub_prev} -> {hub_now} のとき 左右{hub_sides}側 x FX-HUBCLEAN high {hub_clean_hi}"},
    {"label": "待機（経過時間のみ、low / typical / high）", "value": [r2(wait[r]) for r in RANGES], "unit": "時間",
     "formula": f"固着対応あり→浸透待ち {soak}、錆落としあり→防錆乾燥 {dry}"},
    {"label": "前回の実績（履歴表示のみ）", "value": prev["actual_labor_hours"], "unit": "人時",
     "formula": f"{prev['record_id']} actual_labor_hours。今回の工数には使わない（単価だけ使う）"},
    {"label": "前回の見積もり（履歴表示のみ）", "value": prev["estimate_labor_hours"], "unit": "人時",
     "formula": f"{prev['record_id']} estimate_labor_hours。前回の実績との差 {r2(prev['actual_labor_hours'] - prev['estimate_labor_hours'])} 人時（実績 - 見積もり）"},
]

out = {
    "id": "S09",
    "name": "同一車両の経年履歴の追跡",
    "base_method": "B",
    "factors": ["AG08", "HK01"],
    "algorithm": [
        f"手順1: 基準 {base} 人時を出発点にする",
        "手順2: 前回と今回を並べる（経過年数・走行距離の差、ハブ錆の変化）",
        f"手順3: 前回 {prev['record_id']} の観察から固着対応の単価 {r2(unit)} 人時/本を取る",
        "手順4: SPEC U3 の表で今回の締結部に本数を割り当て、単価を掛ける（重は high に折れ込み・ねじ山修正を足す）",
        "手順5: 前回なかった変化（ハブ錆の進行）は確認箇所に出し、範囲内の錆落としを high に入れる",
        "手順6: 待機（浸透待ち・防錆乾燥）を経過時間にだけ足す。雪下ろし・氷塊は範囲外",
    ],
    "inputs": [
        {"key": "previous_visit_same_vehicle", "value": {k: prev[k] for k in ("record_id", "date", "odometer_km", "estimate_labor_hours", "actual_labor_hours", "observations")}, "status": "確認済み"},
        {"key": "intake.date / vehicle.odometer_km", "value": [SC["intake"]["date"], SC["vehicle"]["odometer_km"]], "status": "確認済み"},
        {"key": "condition.underbody_rust_grade.wheel_hub", "value": hub_now, "status": "確認済み"},
        {"key": "condition.fasteners（ブラケット/スライド）", "value": [{"id": f["id"], "rust": f["rust"]} for f in brk + sld], "status": "申告"},
        {"key": "mechanic_provisional_add_ops（FX-BROKEN/FX-THREAD/FX-HUBCLEAN の high）", "value": [broken_hi, thread_hi, hub_clean_hi], "status": "仮定"},
        {"key": "elapsed_waits", "value": [soak, dry], "status": "仮定"},
        {"key": "condition.rotor_hub_seizure", "value": rotor_state, "status": "不明"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "初度登録からの経過年数(前回→今回)", "value": [r2(age_prev), r2(age_now)], "unit": "年"},
            {"label": "履歴の時系列（見積もり→実績→今回の見積もり typical）",
             "value": [{"date": prev["date"], "record": prev["record_id"], "estimate": prev["estimate_labor_hours"], "actual": prev["actual_labor_hours"]},
                       {"date": SC["intake"]["date"], "record": "今回", "estimate_typical": r2(labor["typical"])}], "unit": "人時"},
            {"label": "前回からの走行距離の差", "value": km_between, "unit": "km"},
            {"label": "今回確認すべき箇所（前回の観察との対応）", "value": checklist, "unit": "リスト"},
        ],
        "note": f"前回 {prev['record_id']} の固着対応の単価 {r2(unit)} 人時/本を今回の締結部に当てはめて工数を算出した。本数は SPEC U3 に従い、low=重{n_heavy}本、typical=重{n_heavy}+中{n_mid}本、high=さらに未確認スライドボルト{n_unk}本と、重{n_heavy}本の折れ込み・ねじ山修正、ハブ錆進行の錆落とし。high はこの案の範囲での上限。経過年数・走行距離そのものは加算していない。ローター・ハブの固着（未確認）は、S09 の仕組みが観察の表示と前回単価の当てはめで、U3 の締結部の表にローターが含まれないため、確認箇所に出すだけで人時には入れていない。ハブ錆の錆落としは、グレード{hub_now}が観察済みでも前回との差が悪化シナリオにあたるため high に置き、typical には見込まない。経過時間は単独作業の前提で、人時に待機を足して求めた。雪下ろし・氷塊・融解待ちは範囲外。サブフレームは J1・J2 の範囲外で、腐食があれば作業範囲の拡大として見積もりを変更し顧客の了承を得る。",
    },
    "assumptions": [
        "仮定: 前回の固着対応の単価は observations の「N本が固着…対応 X人時」から読み、全レンジ共通の単価として使う。",
        "仮定: 前回の実績人時 1.9 は今回の工数に使わず、固着対応の単価だけを使う。",
        "仮定: 折れ込み・ねじ山修正は前回に実績がないため、暫定値の high を重の high にだけ足す。",
        "仮定: ハブ錆が前回のグレードより進んでいれば、左右2側の錆落とし・防錆（FX-HUBCLEAN high）を high に入れる。typical には入れない。",
        "仮定: 待機は U5 に従い、固着対応を含めたレンジに浸透待ち、錆落としを含めたレンジに防錆乾燥（冬季仮説値）を経過時間にだけ足す。",
        "仮定: 雪下ろし・氷塊・融解待ちは S09 の範囲外で、人時にも経過時間にも含めない。",
    ],
    "unknowns": [
        "スライドボルト4本は未確認。high にだけ固着対応を入れ、確認後に置き換える。",
        "ローターのハブへの固着は未確認（ハブ錆の進行あり）。締結部ではなく S09 の仕組み（観察の表示）の工程にも含まれないため、FX-ROTOR は人時に入れず確認箇所に出すのみ。",
        "サブフレームの錆は未確認。J1・J2 では外さないためhigh には入れない。腐食があれば作業範囲の拡大として見積もりを変更し、顧客の了承を得る。",
        "前回の記録には左右のハブ・ブーツ状態の詳細がなく、左右別の比較はできない。",
        "過去見積もりの保存形式・ソフト名は未確認（docs の必要データ）。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S09.json").write_text(text + "\n", encoding="utf-8")
print(text)
