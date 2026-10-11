#!/usr/bin/env python3
"""S18 人時と経過時間・納期の分離計算（解釈の統一 第2版 U1〜U9 対応）

アルゴリズムの手順:
  1. scenario.json を、このファイルの位置から相対で読む。
  2. 人時の出発点は、重複控除後の基準 1.7 人時 (base_totals.deduplicated_base)。
     J1/J2 の included_operations を共通工程の重複なしで足した値と一致するか検算する。
  3. S18 は工程の前後関係から人時と経過時間を分ける案なので、個別指示により、U3 で typical に入る
     追加工程をすべて工程表に載せる（他案の要因を混ぜない共通ルール3の例外）。
       雪下ろし PRE-SNOW (入庫1回) / 氷塊除去 PRE-ICE × 前輪2か所 (HK03)
       ハブ錆落とし・防錆 FX-HUBCLEAN × 前2側 (HK07: ハブ錆グレード2以上、または防錆施工歴の申告)
       固着対応 FX-SEIZE: U3 の表をそのまま使う。
         重 (左ブラケット2本)  low = FX-SEIZE low / typical = FX-SEIZE typical / high = FX-SEIZE high
                                 + FX-BROKEN high + FX-THREAD high (各2本分)
         中 (右ブラケット2本)  low 0 / typical = FX-SEIZE typical / high = FX-SEIZE high
         未確認 (スライドボルト4本)  low 0 / typical 0 / high = FX-SEIZE high
         軽 (ホイールナット)  0
     high は U3 の high (折れ込み・未確認) を工程表に足したもの。
     人時 = 基準 1.7 + 上記の追加工程。low / typical / high はそれぞれの水準どうしで合計する。
     待機は人時に入れない。サブフレーム(U4)・下回り洗浄・タイヤ重量差(U6)・付随部品(U8)は入れない。
  4. 工程の依存関係を有向グラフで持つ。
       雪下ろし ----------------------\
       氷塊除去(左/右) -> 融解待ち ------> リフトアップ -> 前2輪取り外し
       -> 浸透待ち -> 固着対応 -> (折れ込み抜き取り -> ねじ山修正) -> キャリパー
       -> ローター -> パッド交換 -> 前2輪取り付け -> 空気圧・トルク確認 -> 試運転
       ローター -> ハブ錆落とし・防錆 -> 防錆乾燥待ち -> 前2輪取り付け
       リフトアップ -> 後2輪の脱着 -> 空気圧・トルク確認  (後輪は前輪・ブレーキと並行可能)
     前2輪の脱着 0.2 は取り外し/取り付けに半分ずつ割る (仮定)。
  5. 待機は U5 に従い、該当する工程を含む水準の経過時間にだけ足す。
       融解待ち 0.5 (氷塊除去あり) / 浸透待ち 0.25 (FX-SEIZE を含む水準) /
       防錆乾燥 0.3 (FX-HUBCLEAN あり。冬季仮説値を全水準に使う) / 部品待ち 0 (parts_wait_hours)
  6. 経過時間は、待機中は作業者を拘束しない前提でリスト・スケジューリングして求める。
     作業者数は shop_policy.workers_available (2人) を主とし、1人の場合も別掲する。
     2人でも人時の合計は変わらない (並行化は経過時間だけを短縮する)。
  7. 納車見込み = 経過時間 + 部品待ち。
  8. 人時は丸めずに計算し、出力時だけ小数第2位に丸める。
  9. 経年(初度登録からの年数)は使わない。ハブ再防錆の要否は施工歴の申告を通じて間接的に関わるだけ。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sc = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

LEVELS = ("low", "typical", "high")
r2 = lambda x: round(x + 1e-12, 2)
tri = lambda d: {k: r2(d[k]) for k in LEVELS}
tri_s = lambda d: f"{r2(d['low'])} / {r2(d['typical'])} / {r2(d['high'])}"

base = sc["base_totals"]["deduplicated_base"]
ops = sc["mechanic_provisional_add_ops"]
cond = sc["condition"]
waits = sc["elapsed_waits"]
workers_n = sc["shop_policy"]["workers_available"]

# --- 基準の検算: J1/J2 の工程を共通工程の重複なしで足す
op_hours = {}
for job in sc["jobs"]:
    for o in job["included_operations"]:
        op_hours.setdefault(o["op"], o["hours"])  # 共通工程は1回だけ
dedup_check = sum(op_hours.values())

# --- 人時: 雪下ろし (入庫1回)
snow = ops["PRE-SNOW"]
snow_on = cond["snow_on_body"]["state"] == "問題あり"
snow_h = {k: snow[k] if snow_on else 0.0 for k in LEVELS}

# --- 人時: HK03 の氷塊除去
ice_state = cond["ice_in_wheel_house"]["state"]
ice_n = cond["ice_in_wheel_house"]["locations"] if ice_state == "問題あり" else 0
ice = ops["PRE-ICE"]
ice_h = {k: ice[k] * ice_n for k in LEVELS}

# --- 人時: HK07 ハブ錆落とし・防錆 (前2輪の2側)
hub_grade = cond["underbody_rust_grade"]["wheel_hub"]
undercoat = cond["rustproof_undercoat"]["value"]
hub_n = 2 if ((hub_grade is not None and hub_grade >= 2) or undercoat) else 0
hubc = ops["FX-HUBCLEAN"]
hub_h = {k: hubc[k] * hub_n for k in LEVELS}

# --- 人時: 締結部 (U3 の表)
seize, broken, thread = ops["FX-SEIZE"], ops["FX-BROKEN"], ops["FX-THREAD"]
fast = cond["fasteners"]
n_heavy = sum(1 for f in fast if f["rust"].startswith("重"))
n_mid = sum(1 for f in fast if f["rust"].startswith("中"))
n_unc = sum(1 for f in fast if f["rust"].startswith("未確認"))
seize_h = {"low": seize["low"] * n_heavy,
           "typical": seize["typical"] * (n_heavy + n_mid),
           "high": seize["high"] * (n_heavy + n_mid + n_unc)}
broken_h = {"low": 0.0, "typical": 0.0, "high": broken["high"] * n_heavy}
thread_h = {"low": 0.0, "typical": 0.0, "high": thread["high"] * n_heavy}

labor = {k: base + snow_h[k] + ice_h[k] + hub_h[k] + seize_h[k] + broken_h[k] + thread_h[k]
         for k in LEVELS}

# --- 待機 (U5。経過時間にだけ入れる)
thaw = waits["thaw_wait_hours"] if ice_n > 0 else 0.0
dry_v = waits["rustproof_dry_wait_hours"]["winter_hypothesis"] if hub_n > 0 else 0.0
dry = {k: dry_v for k in LEVELS}
soak = {k: waits["penetrant_soak_wait_hours"] if seize_h[k] > 0 else 0.0 for k in LEVELS}
parts_wait = waits["parts_wait_hours"]

# --- 工程グラフ: (id, 名前, 人数, 所要, 依存)  人数0は待機
def build(level):
    t = op_hours
    per_ice = ice[level]
    g = []
    ice_ids = []
    if snow_h[level] > 0:
        g.append(("SNOW", "雪下ろし（屋根・ボンネット）", 1, snow_h[level], []))
    for i in range(ice_n):
        g.append((f"ICE{i+1}", f"氷塊除去（前輪ホイールハウス{i+1}）", 1, per_ice, []))
        ice_ids.append(f"ICE{i+1}")
    if thaw > 0:
        g.append(("THAW", "融解待ち", 0, thaw, ice_ids))
    lift_dep = (["SNOW"] if snow_h[level] > 0 else []) + (["THAW"] if thaw > 0 else [])
    g.append(("LIFT", "リフトアップ", 1, t["OP-LIFT"], lift_dep))
    g.append(("F2OFF", "前2輪取り外し", 1, t["OP-WHEEL-F2"] / 2, ["LIFT"]))
    prev = "F2OFF"
    if soak[level] > 0:
        g.append(("SOAK", "浸透待ち（浸透剤を塗布後）", 0, soak[level], [prev]))
        prev = "SOAK"
    if seize_h[level] > 0:
        g.append(("SEIZE", "固着した締結部の対応（浸透剤＋加熱）", 1, seize_h[level], [prev]))
        prev = "SEIZE"
    if broken_h[level] > 0:
        g.append(("BROKEN", "折れ込みボルトの抜き取り", 1, broken_h[level], [prev]))
        prev = "BROKEN"
    if thread_h[level] > 0:
        g.append(("THREAD", "ねじ山の修正", 1, thread_h[level], [prev]))
        prev = "THREAD"
    g.append(("CALIPER", "キャリパー・ブラケット脱着", 1, t["OP-CALIPER"], [prev]))
    g.append(("ROTOR", "ローター脱着", 1, t["OP-ROTOR"], ["CALIPER"]))
    g.append(("PAD", "パッド交換・清掃・グリスアップ", 1, t["OP-PAD"], ["ROTOR"]))
    f2on_dep = ["PAD"]
    if hub_n > 0:
        g.append(("HUB", "ハブ当たり面の錆落とし・防錆（前2輪の2側）", 1, hub_h[level], ["ROTOR"]))
        g.append(("DRY", "防錆乾燥待ち（ハブ当たり面）", 0, dry[level], ["HUB"]))
        f2on_dep = ["PAD", "DRY"]
    g.append(("F2ON", "前2輪取り付け", 1, t["OP-WHEEL-F2"] / 2, f2on_dep))
    g.append(("R2", "後2輪の脱着", 1, t["OP-WHEEL-R2"], ["LIFT"]))
    g.append(("CHECK", "空気圧調整・トルク確認", 1, t["OP-CHECK-TIRE"], ["F2ON", "R2"]))
    g.append(("TEST", "試運転・確認", 1, t["OP-TEST"], ["CHECK"]))
    return g

def schedule(graph, n_workers):
    """リスト・スケジューリング。待機(人数0)は依存が済み次第、作業者を使わず進む。"""
    by_id = {x[0]: x for x in graph}
    tail = {}
    def tail_len(i):  # その工程の開始から終了までの最長経路
        if i not in tail:
            nxt = [tail_len(x[0]) for x in graph if i in x[4]]
            tail[i] = by_id[i][3] + max(nxt, default=0.0)
        return tail[i]
    free = [0.0] * n_workers
    end, rows, done = {}, [], set()
    while len(done) < len(graph):
        cands = []
        for tid, name, persons, dur, deps in graph:
            if tid in done or any(d not in done for d in deps):
                continue
            ready = max([end[d] for d in deps], default=0.0)
            start = ready if persons == 0 else max(min(free), ready)
            cands.append((start, -tail_len(tid), graph.index(by_id[tid]), by_id[tid], ready))
        start, _, _, (tid, name, persons, dur, deps), ready = min(cands, key=lambda c: c[:3])
        if persons > 0:
            w = min(range(n_workers), key=lambda i: max(free[i], ready))
            free[w] = start + dur
        end[tid] = start + dur
        done.add(tid)
        rows.append((tid, name, persons, dur, start, end[tid]))
    return max(end.values()), rows

elapsed2, elapsed1, rows2 = {}, {}, {}
for k in LEVELS:
    g = build(k)
    elapsed2[k], rows2[k] = schedule(g, workers_n)
    elapsed1[k], _ = schedule(g, 1)
delivery = {k: elapsed2[k] + parts_wait for k in LEVELS}
wait_total = {k: thaw + soak[k] + dry[k] for k in LEVELS}
# 人時の合計は作業者数に依存しないことを確認 (作業工程の所要の和)
labor_from_graph = {k: sum(r[3] * r[2] for r in rows2[k]) for k in LEVELS}
assert all(abs(labor_from_graph[k] - labor[k]) < 1e-9 for k in LEVELS), "人時の検算が合わない"
assert abs(dedup_check - base) < 1e-9, "基準 1.7 の検算が合わない"

def table(level):
    return [{"id": r[0], "step": r[1], "persons": r[2], "hours": r2(r[3]), "start": r2(r[4]), "end": r2(r[5])}
            for r in rows2[level]]

fastener_h = {k: seize_h[k] + broken_h[k] + thread_h[k] for k in LEVELS}
intermediates = [
    {"label": "基準の検算（共通工程の重複なし）", "value": r2(dedup_check), "unit": "人時",
     "formula": "J1/J2 の included_operations を OP 単位で1回ずつ足す = 基準 1.7"},
    {"label": "前処理の人時（雪下ろし + 氷塊除去）", "value": tri_s({k: snow_h[k] + ice_h[k] for k in LEVELS}),
     "unit": "人時 (low/typical/high)",
     "formula": f"PRE-SNOW（入庫1回）+ PRE-ICE × {ice_n}か所（前輪。後輪は少量で除去不要）"},
    {"label": "ハブ錆落とし・防錆（HK07）", "value": tri_s(hub_h), "unit": "人時 (low/typical/high)",
     "formula": f"FX-HUBCLEAN × 前{hub_n}側（ハブ錆グレード{hub_grade}、防錆施工歴{'あり（申告）' if undercoat else 'なし'}）"},
    {"label": "締結部の追加人時（U3）", "value": tri_s(fastener_h), "unit": "人時 (low/typical/high)",
     "formula": (f"low = FX-SEIZE low × 重{n_heavy}本 / typical = FX-SEIZE typical × (重{n_heavy}+中{n_mid})本 / "
                 f"high = FX-SEIZE high × (重{n_heavy}+中{n_mid}+未確認{n_unc})本 + FX-BROKEN high × {n_heavy} + FX-THREAD high × {n_heavy}")},
    {"label": "人時（請求の根拠）", "value": tri_s(labor), "unit": "人時 (low/typical/high)",
     "formula": "基準 1.7 + 雪下ろし + 氷塊除去 + ハブ錆落とし・防錆 + 締結部。待機は入れない"},
    {"label": "待機の合計（人時0）", "value": tri_s(wait_total), "unit": "時間 (low/typical/high)",
     "formula": f"融解 {thaw} + 浸透 {soak['low']}/{soak['typical']}/{soak['high']} + 防錆乾燥 {dry['typical']}。部品待ち {parts_wait} は納車見込みで加算"},
    {"label": "経過時間（2人作業）", "value": tri_s(elapsed2), "unit": "時間 (low/typical/high)",
     "formula": "工程グラフを依存順にリスト・スケジューリングし、完了時刻の最大値。待機中は作業者を拘束しない"},
    {"label": "経過時間（1人作業）/ 2人化の短縮（typical）", "value": f"{tri_s(elapsed1)} / 短縮 {r2(elapsed1['typical'] - elapsed2['typical'])}",
     "unit": "時間 (low/typical/high / typical の差)",
     "formula": "同じグラフを作業者1人で割り当てる。人時は同じ。差は2人化で並行できる分"},
]

schedule_out = table("typical")
schedule_high = table("high")

result_json = {
    "id": "S18",
    "name": "人時と経過時間・納期の分離計算",
    "base_method": "C",
    "factors": ["HK03", "HK07", "HK01", "HK02"],
    "algorithm": [
        "手順1: 重複控除後の基準 1.7 人時を、工程の和として検算する",
        "手順2: S18 の実装指示（工程の前後関係から人時と経過時間を分ける案なので追加工程を工程表に載せる、という依頼元の指示。SPEC の U1〜U9 とは別に受けた例外）として、U3 で typical に入る追加工程（雪下ろし、氷塊除去、中・重の固着対応 FX-SEIZE、ハブ錆落とし FX-HUBCLEAN）を工程表に載せる。high は U3 の high（重の折れ込み FX-BROKEN・FX-THREAD、未確認の FX-SEIZE）を足す",
        "手順3: 雪下ろし->リフト、氷塊除去->融解待ち->リフト（雪下ろしは融解待ちの前提にしない。氷塊の融解は雪下ろしと独立に進む）->前輪->浸透待ち->固着対応->ブレーキ->組付け->試運転の依存グラフを作る。後輪は前輪・ブレーキと並行可。ハブ錆落としはローター脱着後にパッド交換と並行可",
        "手順4: 融解待ち 0.5・浸透待ち 0.25（固着対応を含む水準）・防錆乾燥 0.3 を経過時間にだけ入れる（U5）。部品待ちは 0",
        "手順5: 作業者2人で依存順に割り当て、経過時間を求める（1人の場合も別掲）",
        "手順6: 経過時間 + 部品待ちを納車見込みとして出す。人時は作業者数で変わらない",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "仮定"},
        {"key": "condition.snow_on_body", "value": cond["snow_on_body"]["state"], "status": "確認済み"},
        {"key": "condition.ice_in_wheel_house", "value": f"{ice_state}（{ice_n}か所）", "status": "確認済み"},
        {"key": "mechanic_provisional_add_ops", "value": "PRE-SNOW / PRE-ICE / FX-SEIZE / FX-BROKEN / FX-THREAD / FX-HUBCLEAN（整備士の暫定値）", "status": "仮定"},
        {"key": "condition.fasteners", "value": f"重{n_heavy}本・中{n_mid}本・未確認{n_unc}本（スライドボルト。ブーツに隠れて見えない）", "status": "重・中は確認済み、スライドボルトは不明"},
        {"key": "elapsed_waits", "value": f"融解 {waits['thaw_wait_hours']} / 浸透 {waits['penetrant_soak_wait_hours']} / 防錆乾燥 {waits['rustproof_dry_wait_hours']['winter_hypothesis']}（冬季仮説値） / 部品待ち {parts_wait}", "status": "仮定"},
        {"key": "condition.rustproof_undercoat", "value": "施工歴あり（顧客申告）。ハブ錆落とし・防錆の要否の判定に使う", "status": "申告"},
        {"key": "condition.underbody_rust_grade.wheel_hub", "value": hub_grade, "status": "確認済み"},
        {"key": "shop_policy.workers_available", "value": workers_n, "status": "仮定"},
    ],
    "intermediates": intermediates,
    "result": {
        "labor_hours": tri(labor),
        "elapsed_hours": tri(elapsed2),
        "other_outputs": [
            {"label": "経過時間（1人作業）low/typical/high", "value": tri(elapsed1), "unit": "時間"},
            {"label": "待機の合計（人時に入れない）low/typical/high", "value": tri(wait_total), "unit": "時間"},
            {"label": "納車見込み（部品待ち込み）low/typical/high", "value": tri(delivery), "unit": "時間"},
            {"label": "typical の工程表（2人作業）", "value": schedule_out, "unit": "時間"},
            {"label": "high の工程表（2人作業。折れ込み・未確認の固着対応を含む）", "value": schedule_high, "unit": "時間"},
        ],
        "note": "人時は請求の根拠、経過時間は納車予定。待機は作業者を拘束しない前提で人時に入れない。S18 は工程の前後関係から人時と経過時間を分ける案なので、依頼元の S18 実装指示（SPEC 外の例外）として U3 で typical に入る追加工程（雪下ろし、氷塊除去、中・重の固着対応、ハブ錆落とし）をすべて工程表に載せた。high はこの案の範囲での上限で、U3 の high（重の折れ込み・ねじ山修正、未確認のスライドボルトの固着対応）を足している。待機中も拘束する場合の扱いは工場方針で決める。サブフレーム・下回り洗浄・腐食・経年・タイヤ重量差は対象外。",
    },
    "assumptions": [
        "仮定: factors に HK01・HK02 を含めるのは、S18 の実装指示の例外で固着対応（HK01）と雪下ろし（HK02）を工程表に載せるため。docs §3 の主に扱う要因は HK03・HK07 で、この2つは SPEC の U1 の範囲外にあたる",
        "仮定: 雪下ろしは融解待ちの前提にしない（氷塊の融解は雪下ろしと独立）。リフトアップの前に雪下ろしと融解待ちの両方が済む必要がある",
        "仮定: 融解・浸透・防錆乾燥の待機時間は架空の冬季仮説値で、実測ではない。U5 に従い防錆乾燥は全水準 0.3",
        "仮定: 待機中は作業者を拘束せず、他の工程に回れる",
        "仮定: 前2輪の脱着 0.2 人時は取り外し・取り付けに半分ずつ割る",
        "仮定: 浸透剤の塗布は前2輪の取り外し直後に行い、その後に浸透待ち 0.25 を置く。FX-SEIZE の人時は浸透待ち明けの作業（加熱・取り外し）として置き、折れ込み抜き取り・ねじ山修正はその後に続ける。依存順は docs・scenario に記載がなく、整備士に確認が必要",
        "仮定: ハブ錆落とし・防錆はローター脱着後にハブ当たり面が出るため、パッド交換と並行できる（依存関係の記載はなく、整備士に確認が必要）。防錆乾燥待ちはその後、前2輪の取り付け前に必要",
        "仮定: ハブ錆落とし・防錆は、ハブ錆グレード2以上または防錆施工歴(申告)があるとき前2側で行う（HK07 の仮説に基づく。今回はグレード2でも発動する）",
        "仮定: 作業者2人が同時に空いており、2人でも各工程の人時は変わらない。2人目の作業者による並行化は、雪下ろしと氷塊除去、後輪の脱着、ハブ防錆とパッド交換などの並行に現れる",
        "仮定: 各工程は1人で行う。タイヤ重量差（U6）は S07 だけが扱うため反映しない",
        "注記: scenario の pre_processing_billing は雪下ろし・氷塊除去を入庫1回分の請求とするため、人時と請求額は1対1に対応しない。請求の単位は工場方針で決める",
        "S18 は経年（初度登録からの年数）を計算に使わない。経年は施工歴(HK07)を通じてハブ錆落としの要否にのみ間接的に関わる",
        "仮定: 部品待ちは今回の作業で 0（ブーツ・ボルト在庫あり）",
    ],
    "unknowns": [
        "スライドボルト4本の実際の固着状態（未確認。high にだけ FX-SEIZE high を入れている。low・typical の 0 は「問題なし」の確定ではない）",
        "重のブラケットボルト2本で折れ込みが起きるか（high にだけ FX-BROKEN・FX-THREAD を入れている）",
        "サブフレームは未確認で作業範囲外（U4）。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る",
        "下回り洗浄、ブーツ交換などの付随作業の人時（S18 の対象外）",
        "ハブ錆落とし・防錆の要否と範囲は、分解後のハブの実際の状態と施工歴の確認次第（現在は申告とグレード2から必要と仮定）",
        "待機中に作業者を拘束する場合の人時の扱い（工場方針）",
    ],
}

out = json.dumps(result_json, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S18.json").write_text(out + "\n", encoding="utf-8")
print(out)
