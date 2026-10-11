#!/usr/bin/env python3
"""S10 見積もりと実績の差分ログ

アルゴリズムの手順:
  1. scenario.json を、このファイルの位置から相対で読む。
  2. 出発点は重複控除後の基準 1.7 人時 (base_totals.deduplicated_base)。
  3. 今回の区分を決める。
       季節     : intake.date の月が 11〜3 月なら「冬季」、それ以外は「冬季以外」。
       経過年数 : first_registration から intake.date までの年数 (2014-01 -> 2027-01 = 13年)。
                  10年未満 / 10年以上 (shop_policy.check_intensity_threshold.age_years) に区分。
       作業     : J1 + J2。
  4. historical_records の各件で 差 = actual - estimate を出し、record の date の月から季節を、
     age_years から経過年数区分を決める。原因タグ (tags) の hours を合計し、
     「タグで説明できた差」と「説明できない差 (差 - タグ合計)」を分ける。
  5. 季節 x 経過年数区分 (全作業) と、同じ作業構成 (J1+J2) だけに絞った区分ごとに、
     件数・差の平均・中央値・最小・最大を集計する。
  6. 参照実績は「同じ作業構成 (J1+J2) の全実績」とする。件数が shop_policy.min_records_for_reference
     以上ならそれを参照し、足りなければ全作業の実績を「参考」扱いにする (unknowns に記録)。
     参照実績の差 (平均・中央値・最小・最大) は、見積もりのずれの大きさを示す診断として出すだけ。
  7. S10 は工数を算出しない案 (SPEC U9)。low = typical = high = 基準 1.7 人時 (deduplicated_base)。
     区分別の差を人時に足すと、季節・年式による一律加算になるため据え置く。
     区分別の差は S11・S12 の元データとして intermediates と other_outputs に出す。
  8. 冬季/冬季以外 x 経過年数区分ごとの差の集計と、原因タグの内訳 (タグ別 hours 合計・件数・
     説明できない差) を並べ、どの原因で延びたかを示す。記録の無いタグを0と確定せず、
     「説明できない差」として別掲する。
  9. 今回車両の個別状態 (固着・腐食等) は加算しない。経過時間 (待機) は扱わず null。
 10. 人時は丸めずに計算し、出力時だけ小数第2位に丸める。
"""
import json
import re
import statistics
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sc = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

def find_key(obj, key):
    """scenario.json の入れ子から key の値を探す (見つからなければ KeyError)。"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            try:
                return find_key(v, key)
            except KeyError:
                pass
    elif isinstance(obj, list):
        for v in obj:
            try:
                return find_key(v, key)
            except KeyError:
                pass
    raise KeyError(key)

r2 = lambda x: round(x + 1e-12, 2)

base = sc["base_totals"]["deduplicated_base"]
policy = sc["shop_policy"]
age_th = policy["check_intensity_threshold"]["age_years"]
min_n = policy["min_records_for_reference"]
records = sc["historical_records"]
# 冬季の月集合は scenario.json の「winter_months」(例: "11〜3月") から読む。年をまたぐ範囲は折り返す
_m = re.match(r"\s*(\d+)\s*[〜~\-]\s*(\d+)", find_key(sc, "winter_months"))
_a, _b = int(_m.group(1)), int(_m.group(2))
winter_months = {((_a - 1 + i) % 12) + 1 for i in range(((_b - _a) % 12) + 1)}

# ---- 今回の区分 ----
intake = date.fromisoformat(sc["intake"]["date"])
fy, fm = map(int, sc["vehicle"]["first_registration"].split("-"))
age_now = (intake.year * 12 + intake.month - (fy * 12 + fm)) / 12   # 月差から年数
age_now_i = int(age_now)
cur_season = "冬季" if intake.month in winter_months else "冬季以外"
cur_age = "10年以上" if age_now_i >= age_th else "10年未満"
cur_jobs = ["J1", "J2"]

def season_of(rec):
    return "冬季" if int(rec["date"].split("-")[1]) in winter_months else "冬季以外"

def age_of(rec):
    return "10年以上" if rec["age_years"] >= age_th else "10年未満"

rows = []
for rec in records:
    diff = rec["actual"] - rec["estimate"]
    tag_sum = sum(t["hours"] for t in rec["tags"].values())
    rows.append({
        "id": rec["id"], "season": season_of(rec), "age": age_of(rec), "jobs": rec["jobs"],
        "diff": diff, "tag_sum": tag_sum, "resid": diff - tag_sum, "tags": rec["tags"],
    })

def stats(sel):
    d = [x["diff"] for x in sel]
    if not d:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {"n": len(d), "mean": statistics.mean(d), "median": statistics.median(d),
            "min": min(d), "max": max(d)}

def fmt(s):
    if s["n"] == 0:
        return "n=0"
    return f"n={s['n']} 平均{r2(s['mean'])} 中央値{r2(s['median'])} 範囲{r2(s['min'])}〜{r2(s['max'])}"

def jstr(sel_jobs):
    return "+".join(sel_jobs)

# 区分別集計 (全作業 / 作業構成を J1+J2 に絞る)
table = []
for sea in ("冬季", "冬季以外"):
    for ag in ("10年未満", "10年以上"):
        cell = [x for x in rows if x["season"] == sea and x["age"] == ag]
        cell_j = [x for x in cell if x["jobs"] == cur_jobs]
        table.append({"区分": f"{sea}・{ag}", "全作業": stats(cell), "J1+J2のみ": stats(cell_j)})

# 参照実績は作業構成だけで選ぶ (季節・年式では選ばない)
job_rows = [x for x in rows if x["jobs"] == cur_jobs]
if len(job_rows) >= min_n:
    ref, ref_label, ref_ok = job_rows, f"{jstr(cur_jobs)} の全実績 (季節・年式では絞らない)", True
else:
    ref, ref_label, ref_ok = rows, "全作業の全実績 (件数不足の参考値)", False
ref_seasons = sorted({x["season"] for x in ref})
ref_ages = sorted({x["age"] for x in ref})

# 月別一覧 (月は昇順。月内は差の大きい順に作業構成・主な原因タグを並べる)
by_month = {}
for rec, x in zip(records, rows):
    by_month.setdefault(rec["date"], []).append(x)
month_list = []
for m in sorted(by_month):
    xs = by_month[m]
    tg = {}
    for x in xs:
        for k, v in x["tags"].items():
            tg[k] = tg.get(k, 0) + v["hours"]
    month_list.append({
        "月": m, "件数": len(xs), "差の合計": r2(sum(x["diff"] for x in xs)),
        "差の最大": r2(max(x["diff"] for x in xs)),
        "実績": [{"id": x["id"], "作業": "+".join(x["jobs"]), "差": r2(x["diff"])} for x in sorted(xs, key=lambda y: -y["diff"])],
        "主な原因タグ": [f"{k}{r2(h)}" for k, h in sorted(tg.items(), key=lambda kv: -kv[1])[:3]],
    })

rs = stats(ref)
# U9: 工数を算出しない案。差の範囲は人時に足さず、基準をそのまま返す
labor = {"low": base, "typical": base, "high": base}

# 区分別の原因タグ内訳 (S11・S12 の元データ)
tag_breakdown = []
for sea in ("冬季", "冬季以外"):
    for ag in ("10年未満", "10年以上"):
        cell = [x for x in rows if x["season"] == sea and x["age"] == ag]
        tg = {}
        for x in cell:
            for k, v in x["tags"].items():
                e = tg.setdefault(k, {"hours": 0.0, "n": 0})
                e["hours"] += v["hours"]
                e["n"] += 1
        tag_breakdown.append({
            "区分": f"{sea}・{ag}", "件数": len(cell),
            "差の合計": r2(sum(x["diff"] for x in cell)),
            "タグ別": {k: {"hours合計": r2(e["hours"]), "件数": e["n"]} for k, e in sorted(tg.items(), key=lambda kv: -kv[1]["hours"])},
            "説明できない差の合計": r2(sum(x["resid"] for x in cell)),
        })

# 季節だけ・経過年数だけの比較 (今回区分との差が季節由来か年数由来かを見る)
by_season = {s: stats([x for x in rows if x["season"] == s and x["jobs"] == cur_jobs]) for s in ("冬季", "冬季以外")}
by_age = {a: stats([x for x in rows if x["age"] == a and x["jobs"] == cur_jobs]) for a in ("10年未満", "10年以上")}

# タグ別平均 (参照区分の全件で割る。記録の無いタグは0件扱いではなく「説明できない差」に回す)
tag_names = sorted({t for x in ref for t in x["tags"]})
tag_mean = {t: sum(x["tags"][t]["hours"] for x in ref if t in x["tags"]) / len(ref) for t in tag_names}
tag_cnt = {t: sum(1 for x in ref if t in x["tags"]) for t in tag_names}
resid_mean = statistics.mean(x["resid"] for x in ref)
tag_str = " / ".join(f"{t}{r2(tag_mean[t])}({tag_cnt[t]}件)" for t in sorted(tag_names, key=lambda k: -tag_mean[k]))

ref_ids = ",".join(x["id"] for x in ref)
same_veh = [r for r in records if r.get("same_vehicle")]

intermediates = [
    {"label": "今回の区分 (診断表示用。範囲の計算には使わない)", "value": f"{cur_season}・{cur_age}（{age_now_i}年）・{jstr(cur_jobs)}", "unit": "区分",
     "formula": f"intake.date の月 {intake.month} -> {cur_season}。初度登録 {fy}-{fm:02d} から {intake.year}-{intake.month:02d} = {age_now_i}年 (診断用の仮の閾値 {age_th}年)"},
    {"label": "参照した実績の件数", "value": rs["n"], "unit": "件",
     "formula": f"{ref_label}: {ref_ids}。差 平均{r2(rs['mean'])} / 中央値{r2(rs['median'])} / 範囲{r2(rs['min'])}〜{r2(rs['max'])} (診断のみ)。必要件数 {min_n} 以上: {'満たす' if ref_ok else '満たさない (参考)'}。参照実績の季節: {'・'.join(ref_seasons)}、年数区分: {'・'.join(ref_ages)}"},
    {"label": "J1+J2 の季節別の差の中央値", "value": f"冬季 {r2(by_season['冬季']['median'])} (n={by_season['冬季']['n']}) / 冬季以外 {('n=0 (記録なし)' if by_season['冬季以外']['n']==0 else r2(by_season['冬季以外']['median']))}", "unit": "人時",
     "formula": "J1+J2 の記録を季節だけで分けた中央値。冬季以外のJ1+J2は記録が無く比較できない"},
    {"label": "タグ別の平均追加人時 (参照区分)", "value": tag_str, "unit": "人時/件",
     "formula": "各タグの hours 合計 / 参照件数。タグ無しの件は0として平均に含む"},
    {"label": "タグで説明できない差の平均", "value": r2(resid_mean), "unit": "人時",
     "formula": "mean(差 - タグhours合計)。「その他」「原因の記録なし」も含めた残差"},
    {"label": "区分別の差の集計 (冬季/冬季以外 x 経過年数、全作業)", "value": " / ".join(f"{t['区分']} {fmt(t['全作業'])}" for t in table), "unit": "人時",
     "formula": "区分ごとに 差 = actual - estimate の件数・平均・中央値・最小〜最大。S11・S12 の元データ。人時には足さない"},
    {"label": "工数 low / typical / high", "value": f"{r2(labor['low'])} / {r2(labor['typical'])} / {r2(labor['high'])}", "unit": "人時",
     "formula": f"U9: 工数を算出しない案のため 基準 {base} をそのまま据え置く。区分別の差を足すと季節・年式による一律加算になるため採用しない"},
]

result_json = {
    "id": "S10",
    "name": "見積もりと実績の差分ログ",
    "base_method": "B",
    "factors": ["AG01", "AG02", "AG07", "AG08", "HK01", "HK02", "HK03"],
    "algorithm": [
        "手順1: 重複控除後の基準 1.7 人時を出発点にする",
        "手順2: 今回の区分 (冬季 / 初度登録から13年 / J1+J2) を決める。診断表示用で、人時の計算には使わない",
        "手順3: 実績ごとに 差 = actual - estimate と、原因タグ hours の合計・説明できない差を出す",
        "手順4: 冬季/冬季以外 x 経過年数区分と月別で、件数・差の平均・中央値・最小・最大・原因タグの内訳を集計する (S11・S12 の元データ)",
        "手順5: 参照実績は同じ作業構成 (J1+J2) の全実績。件数が足りなければ全作業を参考扱い。差の大きさを示す診断に使う",
        "手順6: U9 により low = typical = high = 基準 1.7 人時。区分別の差を足すと季節・年式による一律加算になるため据え置く",
        "手順7: 参照区分のタグ別平均と説明できない差を並べて、延びの原因を示す",
        "手順8: 今回車両の個別状態 (固着・腐食等) は加算しない",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "仮定"},
        {"key": "intake.date / season", "value": f"{sc['intake']['date']} / {sc['intake']['season']}", "status": "確認済み"},
        {"key": "vehicle.first_registration", "value": sc["vehicle"]["first_registration"], "status": "確認済み"},
        {"key": "経過年数 (計算)", "value": f"{age_now_i}年", "status": "確認済み"},
        {"key": "jobs", "value": jstr(cur_jobs), "status": "確認済み"},
        {"key": "historical_records", "value": f"{len(records)}件 (架空の実績)。参照 {rs['n']}件", "status": "仮定"},
        {"key": "shop_policy.min_records_for_reference", "value": min_n, "status": "仮定"},
        {"key": "condition.fasteners / underbody_rust_grade 等", "value": "S10では使わない", "status": "不明"},
    ],
    "intermediates": intermediates,
    "result": {
        "labor_hours": {k: r2(v) for k, v in labor.items()},
        "elapsed_hours": None,
        "other_outputs": [
            {"label": "区分別の差の集計 (平均/中央値/最小/最大/件数)", "value": [
                {"区分": t["区分"],
                 **{k: {kk: (None if vv is None else (vv if kk == "n" else r2(vv))) for kk, vv in t[k].items()} for k in ("全作業", "J1+J2のみ")}}
                for t in table], "unit": "人時"},
            {"label": "区分別の原因タグ内訳 (冬季/冬季以外 x 経過年数。タグ別hours合計・件数・説明できない差)", "value": tag_breakdown, "unit": "人時"},
            {"label": "月別の差の一覧 (月は昇順、月内は差の大きい順の実績と主な原因タグ)", "value": month_list, "unit": "人時"},
            {"label": "参照区分のタグ別平均追加人時", "value": {t: r2(tag_mean[t]) for t in tag_names}, "unit": "人時/件"},
            {"label": "参照区分の説明できない差の平均", "value": r2(resid_mean), "unit": "人時"},
            {"label": "同一車両の前回実績 (R11) の差", "value": r2(same_veh[0]["actual"] - same_veh[0]["estimate"]) if same_veh else None, "unit": "人時"},
        ],
        "note": f"S10 は工数を算出しない案のため、U9 により low = typical = high = 基準 {base} 人時とする。区分別の差を人時に足すと季節・年式による一律加算になるため据え置き、S11・S12 の元データとして使う。参照実績「{ref_label}」の差は {fmt(rs)}（参考。参照実績はたまたま {'・'.join(ref_seasons)}・{'・'.join(ref_ages)} のみで、季節・年式の効果は分離できていない）。今回車両の個別状態（錆グレード未記録・スライドボルト4本・サブフレーム・ハブ固着）は見ておらず加算しない。{'' if ref_ok else '参照件数が不足のため参考値。'}",
    },
    "assumptions": [
        "仮定: historical_records は架空の実績で、実測ではない",
        f"仮定: 経過年数区分は S04 用の仮置き閾値 {age_th}年 を流用 (docs の S10 節に閾値の定義は無く、S10 専用の根拠ではない。人時の計算には使わない)",
        "仮定: U9 により low = typical = high = 基準 1.7 人時。区分別の差は人時に足さず、S11・S12 の元データとして出す",
        "仮定: 参照実績は季節・年式で選ばず、作業構成 (J1+J2) だけで決める (地域・年式だけで工数を増やさない)",
        "仮定: 冬季・経過年数の区分は診断表示と S11・S12 の元データ用で、low / typical / high の人時には一切使わない",
        "仮定: 冬季は scenario の winter_months から読む (11〜3月)。記録の date の月で判定",
        "仮定: 同一車両の R11 も参照区分に含める (同一車両の重み付けはしない)",
    ],
    "unknowns": [
        f"参照 {rs['n']} 件では差の最小・最大・中央値が少数の実績に左右される{'' if ref_ok else '。必要件数に届かないため参考値'}",
        "J1+J2 の実績は全て冬季・10年以上で、季節の効果と経過年数の効果を分離できない。区分別の差は診断であり、人時には反映していない",
        "R10 は錆グレード未記録で原因の記録なし (その他 0.55) を含む。説明できない差が残る",
        "未確認の錆グレード・締結部 (スライドボルト4本)・サブフレーム・ハブ固着は、過去実績の差に暗黙に含まれるとみなし (typical 側)、別加算していない。個別には確認していない",
        "docs §4 S10 の原因カテゴリのうち「部品待ち」「付随部品の破損」に対応する記録タグは無く、集計できない (部品待ちは経過時間側の論点で、S10 は経過時間を扱わない)。該当する差は「その他」または説明できない差に入る",
        "factors (AG01,AG02,AG07,AG08,HK01,HK02,HK03) は U1 の範囲を示すだけで、docs §3 の S10 は「全般」。算出には使わない",
        "実績の件数が増えると区分の中央値・範囲が変わる",
    ],
}

out = json.dumps(result_json, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S10.json").write_text(out + "\n", encoding="utf-8")
print(out)
