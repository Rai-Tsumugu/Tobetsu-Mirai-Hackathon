#!/usr/bin/env python3
"""S11 原因タグ別の追加人時の実績表

反映する要因: docs/man-hours/system-ideas-30.md の S11 行に従い HK01, AG01, AG02。なお雪下ろし・氷塊除去のタグ実績も表から適用する（HK02・HK03 相当）が、比較表上の要因は docs を正とする。

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. historical_records の tags を、タグごとの「単位あたり追加人時」に正規化する。
      固着対応 : hours / count = 1本あたり
      ボルト折れ: hours / count = 1本あたり
      ローター固着: hours / count = 片側あたり（count は側数として扱う）
      氷塊除去 : hours / count = 1か所あたり
      雪下ろし : hours = 入庫1回あたり（count なし）
      ブーツ交換・その他: 今回の観察に対応する要因がない（その他は原因の記録なし）ので表には出すが適用しない
 3. タグごとに 件数(n)・中央値・範囲(min-max) を表にする。
 4. n が shop_policy.min_records_for_reference 以上のタグは「実績」として使う。
      low = 最小値, typical = 中央値, high = 最大値
    n が未満のタグは「参考」にとどめ、整備士暫定値（mechanic_provisional_add_ops）へフォールバックする。
 5. 今回の観察を単位数に変換する（SPEC U3 の割り当て）。
      固着対応: low = 重(2本)のみ、typical = 中(2本) + 重(2本) = 4本、high = 中(2本) + 重(2本) + 未確認(4本) = 8本
      ボルト折れ: 重(2本)は折れ込みの可能性なので high にだけ、固着対応のあとの別工程として足す（二重計上ではない）。ねじ山修正も high のみ（実績タグなし -> 暫定値）
      ローター固着: 未確認 2側 -> high にだけ入れる（0と確定しない）
      雪下ろし: 入庫1回、氷塊除去: ホイールハウス2か所
 6. 追加人時 = Σ（単位数 x 単位あたり人時）。作業全体への倍率や、地域・年式・走行距離からの加算はしない。
 7. 人時 = 1.7 + 追加人時。丸めずに計算し、出力時だけ小数第2位に丸める。
 8. 経過時間 = 人時 + 待機。融解待ち（氷塊あり）と浸透待ち（固着対応を含む場合）は人時に入れず経過時間にだけ足す。
 9. SPEC.md の形で JSON を標準出力と results/S11.json に出す。
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
min_n = SC["shop_policy"]["min_records_for_reference"]
cond = SC["condition"]
waits = SC["elapsed_waits"]

# --- 手順2: タグごとに単位あたり人時へ正規化 ---
TAGS = ["固着対応", "ボルト折れ", "ローター固着", "氷塊除去", "雪下ろし", "ブーツ交換", "その他"]
UNIT = {"固着対応": "本", "ボルト折れ": "本", "ローター固着": "片側", "氷塊除去": "か所",
        "雪下ろし": "入庫1回", "ブーツ交換": "片側", "その他": "記録単位"}
OPMAP = {"固着対応": "FX-SEIZE", "ボルト折れ": "FX-BROKEN", "ローター固着": "FX-ROTOR",
         "氷塊除去": "PRE-ICE", "雪下ろし": "PRE-SNOW", "ブーツ交換": "AG-BOOT"}
per_unit = {t: [] for t in TAGS}
for rec in SC["historical_records"]:
    for t, v in rec["tags"].items():
        if t in per_unit:
            per_unit[t].append(v["hours"] / v.get("count", 1))

# --- 手順3-4: 件数・中央値・範囲、参考/フォールバック判定 ---
table = []
use = {}  # タグ -> {low, typical, high, source}
for t in TAGS:
    vals = per_unit[t]
    n = len(vals)
    row = {"tag": t, "unit": UNIT[t], "n": n, "n_unit": "レコード"}
    if n:
        row.update({"median": r2(statistics.median(vals)), "min": r2(min(vals)), "max": r2(max(vals))})
    if t == "その他":
        row["use"] = "適用しない（原因の記録なし）"
    elif n >= min_n:
        row["use"] = "実績"
        use[t] = {"low": min(vals), "typical": statistics.median(vals), "high": max(vals), "source": "実績"}
    else:
        op = OPMAP.get(t)
        row["use"] = f"参考（n<{min_n}）-> 整備士暫定値 {op} にフォールバック" if op else "参考"
        if op:
            use[t] = {**{r: ops[op][r] for r in RANGES}, "source": f"整備士暫定値({op})"}
    table.append(row)

# --- 手順5: 今回の観察 -> 単位数 ---
risk = SC["condition"]["fastener_risk_rule"]
def rk(s):
    for k in ("未確認", "重", "中", "軽"):
        if s.startswith(k):
            return k
    return "未確認"
n_mid = n_heavy = n_unk = 0
for f in cond["fasteners"]:
    k, c = rk(f["rust"]), f.get("count", 1)
    n_mid += c if k == "中" else 0
    n_heavy += c if k == "重" else 0
    n_unk += c if k == "未確認" else 0
n_ice = cond["ice_in_wheel_house"]["locations"]
snow = 1 if cond["snow_on_body"]["state"] == "問題あり" else 0
rotor_sides = 2 if cond["rotor_hub_seizure"]["state"] == "未確認" else 0

units = {  # タグ -> {range: 単位数}
    # U3: 中は typical 以上、重は全範囲、未確認は high のみ。折れ込みは別工程として high に追加する
    "固着対応": {"low": n_heavy, "typical": n_mid + n_heavy, "high": n_mid + n_heavy + n_unk},
    "ボルト折れ": {"low": 0, "typical": 0, "high": n_heavy},
    "ローター固着": {"low": 0, "typical": 0, "high": rotor_sides},
    "氷塊除去": {r: n_ice for r in RANGES},
    "雪下ろし": {r: snow for r in RANGES},
}
# ねじ山修正は実績タグがないので暫定値（折れ込み1本につき1か所、high のみ）
thread = {r: (n_heavy * ops["FX-THREAD"][r] if r == "high" else 0.0) for r in RANGES}

# --- 手順6: 追加人時 ---
contrib = {t: {r: units[t][r] * use[t][r] for r in RANGES} for t in units}
add = {r: sum(contrib[t][r] for t in contrib) + thread[r] for r in RANGES}
labor = {r: base + add[r] for r in RANGES}

# --- 手順8: 経過時間 ---
elapsed = {}
for r in RANGES:
    w = waits["thaw_wait_hours"] if units["氷塊除去"][r] else 0.0
    w += waits["penetrant_soak_wait_hours"] if units["固着対応"][r] else 0.0
    elapsed[r] = labor[r] + w

def tri(d):
    return [r2(d[r]) for r in RANGES]

inter = [
    {"label": "固着対応の単位あたり人時（実績 low/中央値/high）", "value": tri(use["固着対応"]), "unit": "人時/本",
     "formula": f"固着対応タグ n={len(per_unit['固着対応'])} レコードの hours/count の min/median/max"},
    {"label": "固着対応の本数（low / typical / high）", "value": [units['固着対応'][r] for r in RANGES],
     "unit": "本", "formula": f"low=重{n_heavy}; typical=中{n_mid}+重{n_heavy}; high=中{n_mid}+重{n_heavy}+未確認{n_unk}（SPEC U3）"},
    {"label": "固着対応の追加人時", "value": tri(contrib["固着対応"]), "unit": "人時",
     "formula": "本数 x 単位あたり人時（range ごと）"},
    {"label": "ローター固着の追加人時（未確認2側は high のみ）", "value": tri(contrib["ローター固着"]), "unit": "人時",
     "formula": f"{rotor_sides}側 x 実績 high {r2(use['ローター固着']['high'])}（n={len(per_unit['ローター固着'])}）"},
    {"label": "雪下ろしの追加人時", "value": tri(contrib["雪下ろし"]), "unit": "人時",
     "formula": f"入庫1回 x 実績 min/median/max（n={len(per_unit['雪下ろし'])}）"},
    {"label": "氷塊除去の追加人時（n<3 のため暫定値）", "value": tri(contrib["氷塊除去"]), "unit": "人時",
     "formula": f"{n_ice}か所 x PRE-ICE 暫定値（実績 n={len(per_unit['氷塊除去'])}）"},
    {"label": "ボルト折れ+ねじ山の追加人時（high のみ、暫定値）",
     "value": tri({r: contrib["ボルト折れ"][r] + thread[r] for r in RANGES}), "unit": "人時",
     "formula": f"重{n_heavy}本 x (FX-BROKEN high {ops['FX-BROKEN']['high']} + FX-THREAD high {ops['FX-THREAD']['high']})"},
    {"label": "追加人時合計", "value": tri(add), "unit": "人時", "formula": "上記の合計"},
]

fallback = [t for t in units if use[t]["source"] != "実績"]
out = {
    "id": "S11",
    "name": "原因タグ別の追加人時の実績表",
    "base_method": "C",
    "factors": ["HK01", "AG01", "AG02"],
    "algorithm": [
        "手順1: 基準 1.7 人時を出発点にする",
        "手順2: 実績のタグを単位あたり人時（本・片側・か所・入庫1回）に正規化",
        "手順3: タグごとに件数・中央値・範囲の表を作る",
        f"手順4: 件数が {min_n} 以上は実績（low=最小, typical=中央値, high=最大）、未満は整備士暫定値にフォールバック",
        "手順5: 今回の観察を単位数に変換（U3: 重は low から、中は typical から、未確認は high のみ。折れ込み・ねじ山は high のみ）",
        "手順6: 単位数 x 単位あたり人時を積み上げ（作業全体の倍率は使わない）",
        "手順7: 人時 = 1.7 + 追加人時",
        "手順8: 融解待ち・浸透待ちは該当する範囲の経過時間にだけ足す（U5）",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "historical_records（タグ付き実績）", "value": f"{len(SC['historical_records'])}件", "status": "申告"},
        {"key": "shop_policy.min_records_for_reference", "value": min_n, "status": "仮定"},
        {"key": "condition.fasteners", "value": {"中": n_mid, "重": n_heavy, "未確認": n_unk}, "status": "確認済み/未確認混在"},
        {"key": "condition.ice_in_wheel_house.locations", "value": n_ice, "status": "確認済み"},
        {"key": "condition.snow_on_body", "value": cond["snow_on_body"]["state"], "status": "確認済み"},
        {"key": "condition.rotor_hub_seizure", "value": cond["rotor_hub_seizure"]["state"], "status": "不明"},
        {"key": "elapsed_waits.thaw/penetrant", "value": [waits["thaw_wait_hours"], waits["penetrant_soak_wait_hours"]], "status": "仮定"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "タグ別の実績表（単位あたり人時。n は記録レコード数で、本数・か所数の合計ではない）", "value": table, "unit": "人時/単位"},
            {"label": "整備士暫定値へフォールバックしたタグ", "value": fallback, "unit": ""},
        ],
        "note": f"実績で置き換えられたのは n≥{min_n} のタグだけ。ボルト折れ・氷塊除去は実績が1件のため参考にとどめ、暫定値を使った。経過時間は1人作業で直列とした簡易値。",
    },
    "assumptions": [
        "仮定: ローター固着タグの count は側数として扱い、hours/count を片側あたりとする。",
        "仮定: 締結部は SPEC U3 の割り当てに従う。重（2本）は low から固着対応に数え、中（2本）は typical から、未確認（4本）は high のみ。折れ込みの抜き取りとねじ山修正（重1本につき各1）は high のみで、固着対応を試みたあとの別工程として足す。",
        "根拠: 「重」は折れ込みの可能性（確定ではない）。折れ込みは実績が1件（n<3）のため暫定値を使い、typical には入れない。typical は折れ込みを0として扱うため、折れ込みが起きると typical は不足する。",
        f"注意: high の追加 {r2(add['high'])} 人時のうち、実績のない暫定値（ボルト折れ抜き取り・ねじ山修正）由来は {r2(contrib['ボルト折れ']['high'] + thread['high'])} 人時で、high の追加分の約{round((contrib['ボルト折れ']['high'] + thread['high'])/add['high']*100)}%を占める。",
        "仮定: R11（同一車両の前回入庫）も固着対応・雪下ろしのプールに含む。独立した実績ではないが、除外しても固着の中央値・雪下ろしの値は変わらない。",
        "仮定: 経過時間は1人作業の直列合計。scenario の workers_available は2で待機中に並行作業できる可能性があるため、経過時間は上限寄りの簡易値。",
        "仮定: ねじ山修正は実績タグがないため整備士暫定値 FX-THREAD を使う。",
        "仮定: 「その他」タグと「ブーツ交換」は今回扱う要因に対応しないため適用しない。",
        "仮定: 地域・年式・走行距離・前回実績からは加算せず、他案の要因（ブーツ・付随部品・材料費等）は含めない。",
        "仮定: 経過時間は人時 + 融解待ち（氷あり）+ 浸透待ち（その範囲に固着対応あり）の直列合計（U5）。low も重2本の固着対応を含むため浸透待ちを足す。",
    ],
    "unknowns": [
        "【typical は未確認を0として扱う】スライドボルト4本は錆が未確認。typical には含めず high にのみ固着対応を含めた（U3）。",
        "【typical は未確認を0として扱う】ローター固着（2側）は分解前で不明。typical には含めず high にのみ2側分を含めた。",
        "【typical は折れ込みを0として扱う】重（2本）の折れ込みは typical に計上していない。",
        "サブフレームは作業範囲外（J1・J2では外さない）。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る。",
        "氷塊除去・ボルト折れは実績が1件で、件数が揃うまで参考値。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S11.json").write_text(text + "\n", encoding="utf-8")
print(text)
