#!/usr/bin/env python3
"""S23 写真記録とAIによる一次分類

下回りの写真をAIが一次分類(腐食グレード候補)し、整備士が確定する。
工数の計算には整備士の確定値だけを使い、AI候補は比較と記録に使う。

手順:
 1. scenario.json を読み、出発点を重複控除後の基準 1.7 人時にする。
 2. photo_ai_S23.items から、部位ごとに AI候補・信頼度・整備士確定値を取る。
    写真なし(確定値 null)の部位は「未確認」として扱い、0 と置き換えない。
 3. AI候補と確定値を比較する。一致率 = 一致した部位数 / 両方に値がある部位数。
    不一致の部位(差の向き付き)を記録する。写真なしの部位は一致率の分母に入れない。
 4. 作業(J1/J2)に関係する部位(brake_area, wheel_hub, front_suspension, rear_suspension)
    だけを工数に反映する。写真に無い関係部位は condition.underbody_rust_grade の
    目視値を使う(状態は「写真なし・目視」と記録)。
 5. グレード→追加工程と数量(仮定の対応表)と整備士の暫定値(mechanic_provisional_add_ops)で
    low/typical/high の追加人時を出す。ローター固着は部位間の最大値、ハブ錆落としは前2輪1回。
 6. 関係部位が未確認なら typical に入れず high に FX-SEIZE high だけを入れ(U3)、unknowns に記録する。
    (subframe は写真なしだが J1/J2 では外さない作業範囲外(U4)のため high にも入れず、unknowns に残す)
 7. 同じ計算を AI候補のグレードで行い、確定値との差を intermediates に出す。
    AI値を採用しない理由(過小評価・信頼度の低さ)の説明に使う。結果には採用しない。
 8. 待機は人時に入れない。固着対応があれば浸透待ち0.25、ハブ錆落としがあれば防錆乾燥0.3(冬季仮説値)を経過時間に足す(U5)。
 9. グレード3の部位は AG04(穴あき等)の可能性として顧客連絡の要否を other_outputs に出す。
10. 雪下ろし・氷塊・洗浄・個別ボルトの錆・過去実績・防錆コートは扱わない(他案の要因)。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO = os.path.join(HERE, "scenario.json")
OUT = os.path.join(HERE, "results", "S23.json")

CASES = ("low", "typical", "high")
Q = lambda lo, ty, hi: {"low": lo, "typical": ty, "high": hi}
# 仮定: 作業に関係する部位
RELEVANT = ["brake_area", "wheel_hub", "rear_suspension"]
LOW_CONF = 0.6  # 仮定: AI信頼度の低信頼しきい値
# 仮定: グレード -> [(工程ID, 数量)]。数量は工程の per の単位
GRADE_MAP = {
    "brake_area": {
        0: [], 1: [],
        2: [("FX-SEIZE", Q(0, 1, 2))],
        3: [("FX-SEIZE", Q(1, 2, 3)), ("FX-ROTOR", Q(0, 1, 2)), ("FX-BROKEN", Q(0, 0, 1)), ("FX-THREAD", Q(0, 0, 1))],
    },
    "wheel_hub": {
        0: [], 1: [],
        2: [("FX-HUBCLEAN", Q(1, 2, 2)), ("FX-ROTOR", Q(0, 0, 1))],
        3: [("FX-HUBCLEAN", Q(2, 2, 2)), ("FX-ROTOR", Q(1, 1, 2))],
    },
    "rear_suspension": {0: [], 1: [], 2: [], 3: []},
}
# U3: 未確認は high にだけ FX-SEIZE high を当てる(グレード3相当にはしない)
UNCONFIRMED_LINES = [("FX-SEIZE", Q(0, 0, 1))]
FASTENER_CAP = 8  # 仮定: J2 のキャリパー関連締結部


def r2(x):
    return round(x + 1e-9, 2)


def compute(grades, ops, base, unconfirmed_fasteners=0):
    """grades: {部位: グレード or None}。未確認は high にグレード3相当。"""
    totals = {c: {} for c in CASES}
    unknown = []
    for c in CASES:
        for a in RELEVANT:
            g = grades.get(a)
            if g is None:
                if a not in unknown:
                    unknown.append(a)
                lines = UNCONFIRMED_LINES if c == "high" else []
            else:
                lines = GRADE_MAP[a][g]
            for op, q in lines:
                n = q[c]
                if op == "FX-ROTOR":
                    totals[c][op] = max(totals[c].get(op, 0), n)
                else:
                    totals[c][op] = totals[c].get(op, 0) + n
        if c == "high" and unconfirmed_fasteners:
            # U3: 範囲内の未確認の締結部は high に FX-SEIZE high を本数分
            totals[c]["FX-SEIZE"] = totals[c].get("FX-SEIZE", 0) + unconfirmed_fasteners
        totals[c]["FX-SEIZE"] = min(totals[c].get("FX-SEIZE", 0), FASTENER_CAP)
    add = {c: sum(n * ops[op][c] for op, n in totals[c].items()) for c in CASES}
    return {"totals": totals, "add": add, "labor": {c: base + add[c] for c in CASES}, "unknown": unknown}


def main():
    with open(SCENARIO, encoding="utf-8") as f:
        sc = json.load(f)
    base = sc["base_totals"]["deduplicated_base"]
    ops = sc["mechanic_provisional_add_ops"]
    soak = sc["elapsed_waits"]["penetrant_soak_wait_hours"]
    dry = sc["elapsed_waits"]["rustproof_dry_wait_hours"]["winter_hypothesis"]
    rust = sc["condition"]["underbody_rust_grade"]
    items = {i["area"]: i for i in sc["photo_ai_S23"]["items"]}

    # 比較: AI候補 vs 整備士確定値
    both = [a for a, i in items.items() if i["ai_grade"] is not None and i["mechanic_grade"] is not None]
    matched = [a for a in both if items[a]["ai_grade"] == items[a]["mechanic_grade"]]
    mismatch = [{"area": a, "ai": items[a]["ai_grade"], "mechanic": items[a]["mechanic_grade"],
                 "diff": items[a]["ai_grade"] - items[a]["mechanic_grade"],
                 "ai_confidence": items[a]["ai_confidence"]} for a in both if a not in matched]
    no_photo = [a for a, i in items.items() if i["mechanic_grade"] is None]
    match_rate = len(matched) / len(both) if both else None

    # 工数に使う確定値(写真に無い関係部位は目視値)
    confirmed, ai_based, src = {}, {}, {}
    for a in RELEVANT:
        if a in items:
            confirmed[a] = items[a]["mechanic_grade"]
            ai_based[a] = items[a]["ai_grade"]
            src[a] = "写真+整備士確定" if items[a]["mechanic_grade"] is not None else "写真なし(未確認)"
        else:
            confirmed[a] = ai_based[a] = rust.get(a)
            src[a] = "写真なし・目視値"

    # U3: J2 の締結部のうち錆が「未確認」の本数(scenario.condition.fasteners から数える)
    unc_f = [f["id"] for f in sc["condition"]["fasteners"] if f["job"] == "J2" and f["rust"].startswith("未確認")]
    rotor_hub_state = sc["condition"]["rotor_hub_seizure"]["state"]
    real = compute(confirmed, ops, base, len(unc_f))
    ai = compute(ai_based, ops, base, len(unc_f))
    # 差の中身(typical): AI候補で過小になる工程
    ai_diff_ops = {op: real["totals"]["typical"].get(op, 0) - ai["totals"]["typical"].get(op, 0)
                   for op in set(real["totals"]["typical"]) | set(ai["totals"]["typical"])}
    ai_diff_ops = {op: n for op, n in ai_diff_ops.items() if n}

    seize = {c: real["totals"][c].get("FX-SEIZE", 0) for c in CASES}
    hubc = {c: real["totals"][c].get("FX-HUBCLEAN", 0) for c in CASES}
    elapsed = {c: real["labor"][c] + (soak if seize[c] > 0 else 0.0) + (dry if hubc[c] > 0 else 0.0) for c in CASES}
    grade3 = [a for a in RELEVANT if confirmed.get(a) == 3]
    low_conf = [a for a in both if items[a]["ai_confidence"] is not None and items[a]["ai_confidence"] < LOW_CONF]

    inputs = []
    for a, i in items.items():
        inputs.append({"key": f"photo_ai_S23.{a}.mechanic_grade",
                       "value": i["mechanic_grade"] if i["mechanic_grade"] is not None else "未確認(写真なし)",
                       "status": "確認済み" if i["mechanic_grade"] is not None else "不明"})
        inputs.append({"key": f"photo_ai_S23.{a}.ai_grade(信頼度)",
                       "value": f"{i['ai_grade']}({i['ai_confidence']})" if i["ai_grade"] is not None else "なし",
                       "status": "仮定(AIは未検証。工数には使わない)" if i["ai_grade"] is not None else "不明"})
    inputs.append({"key": "condition.underbody_rust_grade.rear_suspension", "value": rust.get("rear_suspension"),
                   "status": "確認済み(写真なし・目視値)"})
    inputs.append({"key": "condition.fasteners(J2, 錆=未確認)", "value": unc_f, "status": "不明(ブーツに隠れて見えない)"})
    inputs.append({"key": "condition.rotor_hub_seizure", "value": rotor_hub_state, "status": "不明"})
    inputs.append({"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"})

    intermediates = [
        {"label": "未確認の締結部(J2)の本数", "value": len(unc_f), "unit": "本",
         "formula": "condition.fasteners のうち job=J2 かつ rust=未確認。U3 により high に FX-SEIZE high × 本数を足す(typical・low は 0)。固着合計は上限8本"},
        {"label": "固着対応の本数(low/typical/high)", "value": [seize[c] for c in CASES], "unit": "本",
         "formula": "brake_area の対応表の本数 + 未確認締結部(highのみ)。上限8本"},
        {"label": "AI候補と整備士確定値の一致率", "value": r2(match_rate) if match_rate is not None else None, "unit": "比",
         "formula": f"一致 {len(matched)} 部位 / 両方に値がある {len(both)} 部位(写真なしは分母に入れない)"},
        {"label": "不一致の部位", "value": mismatch, "unit": "部位",
         "formula": "ai_grade != mechanic_grade の部位。diff = ai - mechanic(負ならAIが過小)"},
        {"label": "写真なし(未確認)の部位", "value": no_photo, "unit": "部位",
         "formula": "mechanic_grade == null。0 とは置かず、J1/J2 に関係しない subframe は加算せず unknowns に残す(U4)"},
        {"label": "確定値での追加人時(low/typical/high)", "value": [r2(real["add"][c]) for c in CASES], "unit": "人時",
         "formula": "Σ 工程の数量 × 暫定値。brake g3 → 固着1/2/3本+ローター0/1/2片側(+折れ込み・ねじ山修正はhighのみ)、hub g2 → 錆落とし1/2/2片側(ローター固着highのみ1片側は部位間の最大値で数えるため brake と二重に足さない)、未確認の締結部4本 → high のみ固着+4本(U3)。固着は合計で上限8本"},
        {"label": "AI候補のままの追加人時(low/typical/high)", "value": [r2(ai["add"][c]) for c in CASES], "unit": "人時",
         "formula": "確定値の代わりに ai_grade で同じ計算(採用しない参考値)。wheel_hub を 1 とみなすためハブ錆落とし等が消える"},
        {"label": "AI候補採用との差(typical, 確定 - AI)", "value": r2(real["add"]["typical"] - ai["add"]["typical"]), "unit": "人時",
         "formula": f"確定値の typical 追加 - AI候補の typical 追加。差の工程(確定-AIの数量): {ai_diff_ops}"},
        {"label": "AI信頼度が0.6未満の不一致部位", "value": low_conf, "unit": "部位",
         "formula": f"ai_confidence < {LOW_CONF} かつ両方に値がある部位。低信頼で外れた例としてAI値を確定に使わない理由に使う"},
    ]

    other = [
        {"label": "AG04(穴あき等)の可能性がある部位", "value": grade3, "unit": "部位"},
        {"label": "顧客連絡の目安(追加typicalが連絡しきい値を超える)",
         "value": real["add"]["typical"] > sc["shop_policy"]["contact_threshold"]["labor_hours_gt"], "unit": "真偽"},
        {"label": "AI候補のまま計算した場合の labor_hours(参考、採用しない)",
         "value": {c: r2(ai["labor"][c]) for c in CASES}, "unit": "人時"},
    ]

    result = {
        "id": "S23",
        "name": "写真記録とAIによる一次分類",
        "base_method": "共",
        "factors": ["HK01", "AG04"],
        "algorithm": [
            "手順1: 基準 1.7 人時(重複控除後)から始める",
            "手順2: 部位ごとに AI候補・信頼度・整備士確定値を取り、写真なしは未確認として扱う",
            "手順3: AI候補と確定値の一致率と不一致の部位を出して記録する(工数には入れない)",
            "手順4: 確定値だけで、J1/J2 に関係する部位のグレード→追加工程(仮定の対応表×整備士暫定値)から追加人時を出す",
            "手順5: 関係部位と J2 の未確認の締結部(スライドボルト4本)は typical に入れず high に固着対応(FX-SEIZE high)だけを入れる(U3)。subframe は範囲外(U4)で入れない",
            "手順6: AI候補のまま計算した場合の人時を参考に出し、確定値との差を示す",
            "手順7: 固着対応があれば浸透待ち0.25、ハブ錆落としがあれば防錆乾燥0.3を経過時間にだけ足す(人時に入れない)。AIの分類そのものは計算せず scenario の ai_grade を入力として読む。グレード3は AG04 として顧客連絡を促す",
        ],
        "inputs": inputs,
        "intermediates": intermediates,
        "result": {
            "labor_hours": {c: r2(real["labor"][c]) for c in CASES},
            "elapsed_hours": {c: r2(elapsed[c]) for c in CASES},
            "other_outputs": other,
            "note": ("工数は整備士の確定値だけで計算した。AIは wheel_hub を 1(確定は 2)と低く出し、信頼度も 0.55 と低かったため、"
                     "AI値のままだとハブ錆落としが抜けて過小になる。AI候補は一次分類と写真の記録に使う。"
                     "J2 のスライドボルト4本は未確認(ブーツに隠れて見えない)で、HK01(締結部の腐食)の範囲内のため high に FX-SEIZE high × 4 を入れた(U2・U3)。ローター・ハブの固着も未確認で、ローター固着の high はこの未確認の上限。subframe は写真なしの未確認だが、J1/J2 では外さない作業範囲外(U4)のため high にも入れず unknowns に残した。high はこの案の範囲での上限。経過時間には浸透待ちと防錆乾燥(冬季仮説値)を足した。"),
        },
        "assumptions": [
            "仮定: 関係部位は brake_area, wheel_hub, rear_suspension。front_suspension は J2 の included_operations にサスペンション側の脱着が無く、キャリパー・ブラケットの締結部は brake_area と condition.fasteners で数えているため工数に入れない(写真の記録と一致率には含める)。muffler と subframe は使わない",
            "仮定: グレード→追加工程の対応は S02 と同じ表(brake g3: 固着1/2/3本+ローター固着0/1/2片側+折れ込み・ねじ山修正highのみ各1、hub g2: 錆落とし1/2/2片側+ローター固着highのみ1片側(ローター固着は部位間の最大値で数えるため brake と二重に足さない)、rear_suspension: 追加なし)",
            "仮定: 各工程の人時は scenario の整備士暫定値を使う",
            "仮定: 写真に無い関係部位(rear_suspension)は condition の目視値を使う",
            "仮定: 一致率は部位数が4(うち比較可能3)と少なく、AIの精度の評価にはならない",
            "仮定: 浸透待ち 0.25 と防錆乾燥 0.3(冬季仮説値)を、固着対応・ハブ錆落としがあるときだけ low/typical/high それぞれの経過時間に加える(U5)。待機は人時に入れない",
            "仮定: キャリパー関連の締結部は最大8本(OP-CALIPER の締結部計8本)",
            "仮定: 部位グレードから固着本数を決める対応表は写真の分類(部位単位)に合わせた概算で、個別の締結部の錆区分(重2・中2)は使わない。個別の区分で数えるのは S03 の領域。ただし錆が未確認の締結部は scenario から本数を数えて high に入れる(U3)",
            "仮定: AIの一次分類(グレード候補)は計算で実装せず、scenario の photo_ai_S23 の ai_grade・ai_confidence を入力として読む",
            f"仮定: AI信頼度の低信頼しきい値は {LOW_CONF}(仮置き)",
            "仮定: 関係部位が未確認のときの上限は FX-SEIZE high × 1本(U3)。今回のシナリオでは関係部位はすべて確認済みなので発動しない",
            "仮定: 顧客連絡の目安は労働時間(contact_threshold.labor_hours_gt)だけで判定する。金額のしきい値(yen_gt)は費用の入力が無いため判定しない",
        ],
        "unknowns": [
            "subframe は写真なし(アンダーカバーで見えない)で未確認。J1/J2 では外さないので作業範囲外。腐食があれば作業範囲の拡大(AG04)として見積もりを変更し、顧客の了承を得る",
            "ハブ・ローターの固着は分解前で不明。グレード2からの推定",
            "AIの判定精度は未検証(3部位中1部位が不一致)。照明・汚れ・雪の影響も未評価",
            "防錆アンダーコート(申告)の上から腐食が見えにくく、写真でも過小になる恐れ",
            "スライドボルト4本とスライドピンブーツ(右)は未確認。個別の締結部の錆の評価は S03 の領域で、この案では未確認本数だけを high に入れた",
            "顧客連絡の金額しきい値(yen_gt 5000)は費用の入力が無く判定していない",
        ],
    }
    out = json.dumps(result, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out + "\n")
    print(out)


if __name__ == "__main__":
    main()
