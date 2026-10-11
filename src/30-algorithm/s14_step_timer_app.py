#!/usr/bin/env python3
"""S14 工程別の作業時間を計測するアプリ

反映する要因: HK02（雪下ろし）, HK03（氷塊・融解待ち）, HK01/AG01（締結部の固着・ローター固着）
方式: B/C（工程単位の実測値を今回の工程に換算して積み上げる）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. tap_log_R09（スマホの工程タップ記録）を集計する。
      工程の人時 = 人数 x 時間（wait=true の待機は人数0なので人時0）。
      経過時間   = 工程の時間の合計（待機を含む。工程は直列に並ぶ前提）。
      待機       = wait=true の時間の合計（人時に入れず経過時間にだけ入れる）。
    集計した人時が R09 の実績合計 3.0 人時に一致するか確かめる。
 3. 工程を「基準工程」と「追加工程」に分ける。追加工程は
    雪下ろし / 氷塊除去 / 固着対応 / ローター固着除去 / その他。
    基準工程の人時が基準 1.7 人時に一致することを assert で確かめる。「その他」は範囲外の付帯作業なので人時に加えない（U1・U2）。
 4. 追加工程の実測値を、今回の車の観察状態に合わせて換算単価にする。
      雪下ろし        : 入庫1回あたり（実測 0.20 人時）をそのまま使う。
      氷塊除去        : 実測 0.15 人時 / 2か所 = 1か所あたり。今回の氷塊の箇所数を掛ける。
      固着対応        : 実測 0.55 人時 / 3本 = 1本あたり。今回の固着対応の本数を掛ける。
      ローター固着除去: 実測 0.30 人時 / 1側 = 片側あたり。今回の側数を掛ける。
 5. 今回の本数・側数は condition から数える（SPEC U3）。
      締結部の割り当て: 中 = low 0 / typical 固着対応 / high 固着対応。
                        重 = low 固着対応 / typical 固着対応 / high 固着対応 + 折れ込み + ねじ山。
                        未確認 = high にだけ固着対応。軽 = 0。
      low    : 雪下ろし・氷塊（観察済み）と、重（頭部腐食）2本の固着対応。中は含めない。
      typical: 雪下ろし・氷塊と、重・中4本の固着対応。
      high   : typical に、未確認のスライドボルト4本の固着対応、ローター固着が未確認の前2輪（左右）の除去、
               重2本の折れ込み（R02 実測 0.85 人時/本）とねじ山の修正
               （実測なし。FX-THREAD high 0.5/か所）を加える。サブフレームは作業範囲外（U4）。
 6. 労力 = 1.7 + 追加人時。地域・年式・走行距離からは加算しない。丸めずに計算し、出力時だけ小数第2位に丸める。
 7. 経過時間 = 基準工程の時間(実測) + 追加工程の時間(1人作業なので人時と同じ) + 待機。
      待機は U5 に従い、low/typical/high それぞれで、氷塊除去を含めれば融解待ち(0.5)、固着対応があれば浸透待ち(0.25)を足す（雪下ろしだけでは足さない）。
 8. 実測が R09 の1件だけで、参照に必要な最小件数(3)に満たないことを unknowns に記録する。
 9. SPEC.md の形で JSON を標準出力と results/S14.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)

base = SC["base_totals"]["deduplicated_base"]
log = SC["tap_log_R09"]["steps"]
rec_R09 = next(r for r in SC["historical_records"] if r["id"] == "R09")
cond = SC["condition"]
waits = SC["elapsed_waits"]

# --- 手順2: tap_log の集計 ---
ph = lambda s: s["persons"] * s["hours"]
log_person_hours = sum(ph(s) for s in log)
log_elapsed = sum(s["hours"] for s in log)
log_wait = sum(s["hours"] for s in log if s.get("wait"))
assert abs(log_person_hours - rec_R09["actual"]) < 1e-9, "R09 の実績合計と一致しない"

# --- 手順3: 基準工程と追加工程に分ける ---
ADD_KEYS = {
    "雪下ろし": "snow", "氷塊除去": "ice", "固着対応": "seize",
    "ローター固着除去": "rotor", "その他": "other",
}
def kind(step):
    if step.get("wait"):
        return "wait"
    for k, v in ADD_KEYS.items():
        if step["step"].startswith(k):
            return v
    return "base"

agg = {k: {"ph": 0.0, "h": 0.0} for k in ("base", "snow", "ice", "seize", "rotor", "other", "wait")}
for s in log:
    k = kind(s)
    agg[k]["ph"] += ph(s)
    agg[k]["h"] += s["hours"]
base_from_log = agg["base"]["ph"]
base_elapsed_from_log = agg["base"]["h"]
add_from_log = log_person_hours - base_from_log
assert abs(base_from_log - base) < 1e-9, "基準工程の人時が基準 1.7 と一致しない"

# --- 手順4: 換算単価 ---
unit_snow = agg["snow"]["ph"]                                   # 入庫1回
unit_ice = agg["ice"]["ph"] / 2                                 # 1か所（ログは2か所）
unit_seize = agg["seize"]["ph"] / 3                             # 1本（ログは3本）
unit_rotor = agg["rotor"]["ph"] / 1                             # 片側（ログは1側）
rec_R02 = next(r for r in SC["historical_records"] if r["id"] == "R02")
_brk = rec_R02["tags"]["ボルト折れ"]
unit_broken = _brk["hours"] / _brk["count"]                     # 折れ込み1本（R02 の実測 0.85 人時 / 1本）
unit_thread = SC["mechanic_provisional_add_ops"]["FX-THREAD"]["high"]  # ねじ山の修正（実測なし。U3 に従い FX-THREAD high を使う）

# --- 手順5: 今回の本数・側数 ---
def rust_key(text):
    for k in ("未確認", "重", "中", "軽"):
        if text.startswith(k):
            return k
    return "未確認"

n_heavy = sum(f.get("count", 1) for f in cond["fasteners"] if f["job"] == "J2" and rust_key(f["rust"]) == "重")
n_mid = sum(f.get("count", 1) for f in cond["fasteners"] if f["job"] == "J2" and rust_key(f["rust"]) == "中")
n_unk = sum(f.get("count", 1) for f in cond["fasteners"] if f["job"] == "J2" and rust_key(f["rust"]) == "未確認")
n_ice = cond["ice_in_wheel_house"]["locations"] if cond["ice_in_wheel_house"]["state"] == "問題あり" else 0
snow = 1 if cond["snow_on_body"]["state"] == "問題あり" else 0
rotor_sides_unconfirmed = 2 if cond["rotor_hub_seizure"]["state"] == "未確認" else 0  # 前2輪の左右

def total(rng):
    n_seize = {"low": n_heavy, "typical": n_heavy + n_mid, "high": n_heavy + n_mid + n_unk}[rng]
    sides = rotor_sides_unconfirmed if rng == "high" else 0
    n_broken = n_heavy if rng == "high" else 0                      # 重は折れ込みの可能性(fastener_risk_rule)。上限では全数が折れ込むとする
    parts = {
        "雪下ろし": snow * unit_snow,
        "氷塊除去": n_ice * unit_ice,
        "固着対応": n_seize * unit_seize,
        "ローター固着除去": sides * unit_rotor,
        "折れ込み対応（重の締結部）": n_broken * unit_broken,
        "ねじ山の修正（折れ込み後）": n_broken * unit_thread,
    }
    return n_seize, sides, parts

labor, elapsed, detail = {}, {}, {}
for rng in ("low", "typical", "high"):
    n_seize, sides, parts = total(rng)
    add = sum(parts.values())
    labor[rng] = base + add
    wait = 0.0
    if n_ice:
        wait += waits["thaw_wait_hours"]
    if n_seize:
        wait += waits["penetrant_soak_wait_hours"]
    elapsed[rng] = base_elapsed_from_log + add + wait   # 追加工程は1人作業なので時間=人時
    detail[rng] = {"seize": n_seize, "rotor_sides": sides, "add": add, "wait": wait}

typ = detail["typical"]
add_typ = typ["add"]

result = {
    "id": "S14",
    "name": "工程別の作業時間を計測するアプリ",
    "base_method": "B/C",
    "factors": ["HK02", "HK03", "HK01", "AG01"],
    "algorithm": [
        "手順1: scenario.json を読み、出発点を重複控除後の基準 1.7 人時にする",
        "手順2: tap_log_R09 を集計する。工程の人時=人数x時間、待機は人時0で経過時間にだけ入れる。R09 の実績 3.0 人時を再現して確かめる",
        "手順3: 工程を基準工程と追加工程（雪下ろし・氷塊・固着対応・ローター固着・その他）に分け、基準工程が 1.7 人時と一致することを assert で確かめる",
        "手順4: 追加工程の実測を換算単価にする（氷塊=1か所、固着対応=1本、ローター固着=片側あたり）",
        "手順5: SPEC U3 の表に沿って本数を数える。中2本は low 0・typical/high 固着対応、重2本は low/typical 固着対応・high は固着対応＋折れ込み（R02 実測 0.85 人時/本）＋ねじ山（FX-THREAD high）、未確認スライドボルト4本は high にだけ固着対応。ローター固着2側も high にだけ入れる。R09 の「その他」は範囲外なので入れない",
        "手順6: 1.7 + 追加人時 を low / typical / high で出す。年式・地域からは加算しない",
        "手順7: 経過時間 = 基準工程の実測時間 + 追加工程の時間 + 待機（U5: 氷塊除去を含めれば融解待ち、固着対応があれば浸透待ちを足す）",
        "手順8: 実測が1件だけで最小参照件数(3)に満たないことを unknowns に記録する",
    ],
    "inputs": [
        {"key": "tap_log_R09.steps", "value": f"{len(log)}工程（待機{sum(1 for s in log if s.get('wait'))}件）", "status": "申告"},
        {"key": "condition.snow_on_body", "value": cond["snow_on_body"]["state"], "status": "確認済み"},
        {"key": "condition.ice_in_wheel_house.locations", "value": n_ice, "status": "確認済み"},
        {"key": "condition.fasteners(J2) 重", "value": n_heavy, "status": "確認済み"},
        {"key": "condition.fasteners(J2) 中", "value": n_mid, "status": "確認済み"},
        {"key": "condition.fasteners(J2) 未確認", "value": n_unk, "status": "不明"},
        {"key": "condition.rotor_hub_seizure", "value": cond["rotor_hub_seizure"]["state"], "status": "不明"},
        {"key": "elapsed_waits.thaw_wait_hours", "value": waits["thaw_wait_hours"], "status": "仮定"},
        {"key": "elapsed_waits.penetrant_soak_wait_hours", "value": waits["penetrant_soak_wait_hours"], "status": "仮定"},
    ],
    "intermediates": [
        {"label": "R09 の工程ログ集計 人時", "value": r2(log_person_hours), "unit": "人時",
         "formula": "Σ(人数 x 時間)。R09 の実績 3.0 人時を再現"},
        {"label": "基準工程の実測人時（基準 1.7 との照合）", "value": r2(base_from_log), "unit": "人時",
         "formula": f"集計 {r2(log_person_hours)} − 追加工程 {r2(add_from_log)}"},
        {"label": "固着対応 1本あたり", "value": r2(unit_seize), "unit": "人時/本",
         "formula": "0.55 人時 / 3本"},
        {"label": "折れ込み対応 1本あたり（R02 実測）", "value": r2(unit_broken), "unit": "人時/本",
         "formula": "R02 ボルト折れ 0.85 人時 / 1本。high にだけ重の本数分を加える"},
        {"label": "ねじ山の修正 1か所あたり（FX-THREAD high）", "value": unit_thread, "unit": "人時/か所",
         "formula": "scenario の mechanic_provisional_add_ops.FX-THREAD.high。実測なし。high にだけ重の本数分を加える"},
        {"label": "今回の追加人時（typical）", "value": r2(add_typ), "unit": "人時",
         "formula": f"雪 {r2(unit_snow)} + 氷 {n_ice}x{unit_ice:.3f} + 固着 {typ['seize']}本x{unit_seize:.4f}（ローター固着 {r2(unit_rotor)}/側 は high のみ）"},
        {"label": "今回の経過時間（typical）", "value": r2(elapsed["typical"]), "unit": "時間",
         "formula": f"基準工程 {r2(base_elapsed_from_log)} + 追加 {r2(add_typ)} + 待機 {r2(typ['wait'])}"},
    ],
    "result": {
        "labor_hours": {k: r2(v) for k, v in labor.items()},
        "elapsed_hours": {k: r2(v) for k, v in elapsed.items()},
        "other_outputs": [
            {"label": "実測の参照件数", "value": 1, "unit": "件（最小 %d 件に不足）" % SC["shop_policy"]["min_records_for_reference"]},
            {"label": "待機（人時に含めない）", "value": r2(typ["wait"]), "unit": "時間"},
        ],
        "note": "R09 の工程ログ1件（n=1）の換算による暫定の見積もり。high はこの案の範囲での上限（折れ込み＋ねじ山を含む）。参照件数が最小件数に満たないため、実績が3件以上になるまで参考値として扱う。",
    },
    "assumptions": [
        "仮定: 固着対応は R09 の実測 0.55 人時 / 3本 を1本あたりに均等割りして今回の本数に換算する（締結部ごとの難易度差は無視）",
        "仮定: 氷塊除去は 0.15 人時 / 2か所、ローター固着除去は 0.30 人時 / 1側 を単純に比例させる",
        "仮定: 重（頭部腐食）の締結部は low・typical では固着対応の単価で換算し、high では折れ込みの可能性（fastener_risk_rule）として、折れ込み（R02 の実測 0.85 人時/本）とねじ山の修正（FX-THREAD high 0.5 人時/か所）を固着対応に加える（U3）。折れ込みの実測は R02 の1件のみ",
        "仮定: 工程は直列に並ぶとして経過時間を足す。追加工程は1人作業で、時間=人時",
        "仮定: 融解待ち・浸透待ちは scenario.json の elapsed_waits の値を使う（R09 の実測と同じ値）",
        "仮定: R09 の「その他（工具準備・清掃）0.10」は S14 の範囲（U1）の要因ではないため、どの範囲にも入れない",
        "仮定: 雪下ろしの typical は R09 の実測 0.20 人時を使う（S14 は実測の換算が方式）。整備士の暫定値 PRE-SNOW typical 0.15 とは出どころが違い、R08・R10・R11 の 0.15 とも揃わない。実測が3件に達するまで暫定値に寄せず、差 0.05 人時は残る",
        "仮定: low は U3 に従い、重（頭部腐食）の締結部2本だけを固着対応とみなす。中の2本は『固着対応の可能性』で確定ではないため low は 0、typical・high で固着対応とする",
        "仮定: 待機は U5 に従い low / typical / high それぞれで、氷塊除去を含めれば融解待ち 0.5、固着対応があれば浸透待ち 0.25 を足す（人時には入れない）",
    ],
    "unknowns": [
        "実測が R09 の1件のみ（n=1、最小参照件数 3 に不足）。単価の元は R09 の計測アプリの実測で、ばらつきは不明",
        "スライドボルト4本の錆（ブーツに隠れて未確認）。high にだけ固着対応を含めた",
        "ローター・ハブの固着（分解前で未確認）。high にだけ前2輪の左右を含めた",
        "サブフレームの腐食（未確認）。J1・J2 では外さないので作業範囲外（U4）。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る",
        "ねじ山の修正の実測はない。FX-THREAD high（0.5 人時/か所）を重2本に当てた暫定値",
        "重の締結部が折れ込みになる場合の実測は R02 の1件（1本）のみ。high は全数が折れ込む上限で、実際にそうなる確率は不明",
    ],
}

out = json.dumps(result, ensure_ascii=False, indent=2)
print(out)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S14.json").write_text(out + "\n", encoding="utf-8")
