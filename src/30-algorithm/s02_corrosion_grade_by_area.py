#!/usr/bin/env python3
"""S02 部位別の腐食グレード入力

下回りを部位に分け、部位ごとの腐食グレード(0〜3, null=未確認)を、
作業(J1/J2)に関係する部位だけ読んで追加工程の候補を出す。

手順:
 1. scenario.json を読み、出発点を重複控除後の基準 1.7 人時にする。
 2. J1/J2 の作業に関係する部位を決める(仮定)。
      J2: brake_area, wheel_hub, front_suspension
      J1: wheel_hub, rear_suspension(後輪の脱着のみ)
    マフラー(muffler)はパッド・ローター交換やホイール脱着で触らないので使わない。
    サブフレーム(subframe)は J1・J2 では外さないので作業範囲外とする(SPEC U4)。
 3. 関係する部位ごとに「グレード→追加工程と数量(low/typical/high)」の対応表
    (仮定)を引く。工程の人時は scenario の整備士暫定値(mechanic_provisional_add_ops)。
    S02 が持つ工程は、HK01 の「錆落とし」(FX-HUBCLEAN)と「ローターの固着除去」(FX-ROTOR)だけ。
 4. 追加人時 = Σ 工程の数量 × 工程の人時(low/typical/high それぞれ)。
    ローター固着は brake_area 由来と wheel_hub 由来の大きい方を採る(二重加算しない)。
    ハブの錆落としは前2輪(J1・J2共通)を1回だけ数える。
 5. 範囲内の関係部位が null(未確認)なら、typical には入れず high にグレード3相当を入れ、
    unknowns に記録する(SPEC U2)。現在の scenario では関係部位はすべて確認済み。
    subframe は作業範囲外なので high に入れず、unknowns に「腐食があれば作業範囲の拡大(AG04)
    として見積もりを変更し、顧客の了承を得る」と書く(U4)。
 6. グレード3の関係部位は AG04(穴あき等)の可能性として、
    見積もりを変えて顧客の了承を得る必要があるかの確認を other_outputs に出す。工数には足さない。
 6b. 経過時間は、FX-HUBCLEAN を含む case に防錆乾燥の待機(冬季仮説値)を足す(U5)。待機は人時に入れない。
 7. 浸透剤・加熱による固着対応(FX-SEIZE。AG01)、折れ込み抜き取り、個別締結部の判定は
    S03 の領域なので扱わない(S02 と S03 を併用しても二重計上しない)。浸透待ちも S03 側。
 8. 雪下ろし・氷塊・洗浄・個別ボルトの錆・過去実績・防錆コートの再施工は扱わない(他案の要因)。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO = os.path.join(HERE, "scenario.json")
OUT = os.path.join(HERE, "results", "S02.json")

# 仮定: 作業に関係する部位
RELEVANT = {
    "J1": ["wheel_hub", "rear_suspension"],
    "J2": ["brake_area", "wheel_hub", "front_suspension"],
}
# 仮定: グレード -> [(工程ID, {low, typical, high} の数量)]
# 数量は「その工程の per の単位」(FX-ROTOR/FX-HUBCLEAN=片側)
# FX-SEIZE(浸透剤＋加熱の固着対応)は AG01 であり S03 の領域のため、S02 の表には入れない。
Q = lambda lo, ty, hi: {"low": lo, "typical": ty, "high": hi}
GRADE_MAP = {
    "brake_area": {
        0: [], 1: [], 2: [],
        3: [("FX-ROTOR", Q(0, 1, 2))],
    },
    "wheel_hub": {
        0: [], 1: [],
        2: [("FX-HUBCLEAN", Q(1, 2, 2)), ("FX-ROTOR", Q(0, 0, 1))],
        3: [("FX-HUBCLEAN", Q(2, 2, 2)), ("FX-ROTOR", Q(1, 1, 2))],
    },
    # 以下の部位は、S02 が持つ工程(錆落とし・ローター固着除去)に対応するものが無い。
    # 締結部の固着対応は S03、穴あき等は AG04(顧客連絡)で扱う。
    "front_suspension": {0: [], 1: [], 2: [], 3: []},
    "rear_suspension": {0: [], 1: [], 2: [], 3: []},  # 後輪脱着のみ
}
CASES = ("low", "typical", "high")


def r2(x):
    return round(x + 1e-9, 2)


def main():
    with open(SCENARIO, encoding="utf-8") as f:
        sc = json.load(f)
    base = sc["base_totals"]["deduplicated_base"]
    rust = sc["condition"]["underbody_rust_grade"]
    ops = sc["mechanic_provisional_add_ops"]
    dry_wait = sc["elapsed_waits"]["rustproof_dry_wait_hours"]["winter_hypothesis"]

    related = []  # 重複なしの関係部位
    for areas in RELEVANT.values():
        for a in areas:
            if a not in related:
                related.append(a)

    # 部位ごとの工程数量
    per_area = {}
    unknown_areas = []
    for a in related:
        g = rust.get(a)
        if g is None:
            unknown_areas.append(a)
            per_area[a] = {c: [] for c in CASES}
            # 未確認: high にグレード3相当
            per_area[a]["high"] = list(GRADE_MAP[a][3])
            continue
        per_area[a] = {c: [(op, q[c]) for op, q in GRADE_MAP[a][g]] for c in CASES}

    # 工程ごとに集計。FX-ROTOR は部位間の最大(片側数)を採用、他は合計
    def tally(case):
        totals = {}
        by_area_hours = {}
        for a in related:
            h = 0.0
            for op, n in per_area[a][case]:
                h += n * ops[op][case]
                if op == "FX-ROTOR":
                    totals[op] = max(totals.get(op, 0), n)
                else:
                    totals[op] = totals.get(op, 0) + n
            by_area_hours[a] = h
        hours = sum(n * ops[op][case] for op, n in totals.items())
        # FX-ROTOR 重複を除いた分の差を表示用に部位別から調整しない(部位別は参考値)
        return totals, hours, by_area_hours

    res = {c: tally(c) for c in CASES}
    add = {c: res[c][1] for c in CASES}
    labor = {c: base + add[c] for c in CASES}
    # U5: FX-HUBCLEAN を含む case に防錆乾燥の待機(冬季仮説値)を足す。待機は人時に入れない
    wait = {c: (dry_wait if res[c][0].get("FX-HUBCLEAN", 0) > 0 else 0.0) for c in CASES}
    elapsed = {c: labor[c] + wait[c] for c in CASES}
    typ_area = res["typical"][2]
    grade3 = [a for a in related if rust.get(a) == 3]
    ag04_check = grade3 + unknown_areas  # 作業範囲外の subframe は含めない(U4)
    thr = sc["shop_policy"]["contact_threshold"]["labor_hours_gt"]

    inputs = []
    for a in ("front_suspension", "brake_area", "wheel_hub", "rear_suspension", "subframe", "muffler"):
        g = rust.get(a)
        used = a in related
        inputs.append({
            "key": f"condition.underbody_rust_grade.{a}",
            "value": g if g is not None else "未確認(null)",
            "status": ("不明" if g is None else "確認済み") + ("" if used else "(J1/J2に関係しないため未使用)"),
        })
    inputs.append({"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"})

    intermediates = [
        {"label": "作業に関係する部位のグレード", "value": {a: rust.get(a) for a in related}, "unit": "グレード",
         "formula": "J1/J2 に関係する部位(brake_area, wheel_hub, front_suspension, rear_suspension)のみ。muffler・subframe は作業範囲外"},
        {"label": "ローター固着の片側数(typical)", "value": res["typical"][0].get("FX-ROTOR", 0), "unit": "片側",
         "formula": "max(brake_area g3 → 1, wheel_hub g2 → 0)。部位間は最大値を採り二重加算しない"},
        {"label": "ハブ錆落としの片側数(typical)", "value": res["typical"][0].get("FX-HUBCLEAN", 0), "unit": "片側",
         "formula": "wheel_hub g2 → 前2輪を1回だけ数える(J1・J2共通)"},
        {"label": "部位別の追加人時(typical)", "value": {a: r2(h) for a, h in typ_area.items()}, "unit": "人時",
         "formula": "Σ 数量 × 暫定値(typical)。ローター固着の重複控除前の参考値"},
        {"label": "追加人時合計(low/typical/high)", "value": [r2(add[c]) for c in CASES], "unit": "人時",
         "formula": "Σ 工程の数量 × 工程の人時(case別)。固着対応(浸透剤・加熱)・折れ込み抜き取りは S03(AG01)の領域のため扱わない"},
        {"label": "グレード3の部位数", "value": len(grade3), "unit": "部位",
         "formula": "count(関係部位の grade == 3)。1以上なら AG04 の可能性として見積変更の要否確認を促す"},
        {"label": "未確認の関係部位", "value": unknown_areas, "unit": "部位",
         "formula": "grade == null の関係部位(範囲内の未確認)。あれば high にグレード3相当を入れる。subframe は作業範囲外(U4)のため含めない"},
        {"label": "防錆乾燥の待機(low/typical/high)", "value": [wait[c] for c in CASES], "unit": "時間",
         "formula": "FX-HUBCLEAN の数量 > 0 の case に elapsed_waits.rustproof_dry_wait_hours.winter_hypothesis を足す。人時には入れない"},
    ]

    note = ("関係部位のグレードだけから、錆落とし(HK01)とローター固着除去の追加工程を出した。"
            "high はこの案の範囲での上限で、範囲内に未確認の部位は無い。"
            "固着対応(浸透剤・加熱。AG01)は S03 の領域なので扱わない。"
            "サブフレームは J1・J2 では外さないため作業範囲外とし、high に入れず unknowns に記録した。"
            f"経過時間は、錆落とし(FX-HUBCLEAN)を含む case に防錆乾燥の待機 {dry_wait} 時間(冬季仮説値)を足した。待機は人時に入れない。")
    other = [
        {"label": "グレード3の部位(層状剥離・欠損。穴あき等AG04の有無は現物確認)", "value": grade3, "unit": "部位"},
        {"label": "AG04の可能性の確認が要る関係部位(グレード3または範囲内の未確認)", "value": ag04_check, "unit": "部位"},
        {"label": "顧客連絡の目安(AG04: 見積もりを変えて了承を得る必要がありうる)", "value": len(ag04_check) > 0, "unit": "真偽"},
        {"label": "顧客連絡の目安(追加typicalが連絡しきい値を超える)", "value": add["typical"] > thr, "unit": "真偽"},
    ]
    result = {
        "id": "S02",
        "name": "部位別の腐食グレード入力",
        "base_method": "A",
        "factors": ["HK01", "AG04"],
        "algorithm": [
            "手順1: 基準 1.7 人時(重複控除後)から始める",
            "手順2: J1/J2 に関係する部位(brake_area, wheel_hub, front_suspension, rear_suspension)だけグレードを読む。subframe は外さないので作業範囲外",
            "手順3: グレード→追加工程・数量の対応表(仮定)と整備士暫定値で low/typical/high の追加人時を出す",
            "手順4: ローター固着は部位間の最大、ハブ錆落としは前2輪1回で二重加算を避ける",
            "手順5: 範囲内の関係部位が未確認なら typical に入れず high にグレード3相当を入れる(現在は該当なし)。subframe は high に入れず unknowns に記録する",
            "手順6: グレード3または範囲内で未確認の関係部位は AG04 の可能性として見積変更の要否確認を促す(工数には足さない)。固着対応(FX-SEIZE)・浸透待ちは S03 の領域のため扱わない",
            "手順7: 経過時間 = 人時 + (FX-HUBCLEAN を含む case のみ)防錆乾燥の待機。待機は人時に入れない",
        ],
        "inputs": inputs,
        "intermediates": intermediates,
        "result": {
            "labor_hours": {c: r2(labor[c]) for c in CASES},
            "elapsed_hours": {c: r2(elapsed[c]) for c in CASES},
            "other_outputs": other,
            "note": note,
        },
        "assumptions": [
            "仮定: 関係部位は J2=brake_area/wheel_hub/front_suspension、J1=wheel_hub/rear_suspension。muffler は使わない。subframe は J1・J2 では外さないので作業範囲外とする(SPEC U4)",
            "仮定: S02 が持つ工程は HK01 の錆落とし(FX-HUBCLEAN)とローター固着除去(FX-ROTOR)だけ。浸透剤・加熱による固着対応(FX-SEIZE。AG01)は S03 が持つ。docs §2.2 の AG01、§4.1 の S03 に合わせ、併用時の二重計上を避ける",
            "仮定: グレード→追加工程の対応(brake_area g3: ローター固着0/1/2片側、wheel_hub g2: 錆落とし1/2/2片側+ローター固着highのみ1片側、g3: 錆落とし2片側+ローター固着1/1/2片側、front_suspension・rear_suspension: 追加工程なし)",
            "仮定: scenario の wheel_hub は単一グレードで、ローター固着の記述(rotor_hub_seizure)から前輪ハブと読む。FX-HUBCLEAN は J2 のローター交換で当たり面を露出する前2輪を数える。J1 の後輪ハブは scenario に評価が無く、タイヤ交換では当たり面を清掃しない前提で数えない",
            "仮定: FX-HUBCLEAN の名称は「錆落とし・防錆」だが、S02 では錆落としの人時としてだけ使う。防錆コートの再施工(HK07)は S28 などの領域で、ここでは足さない。暫定値に防錆の手間が含まれる可能性は残る",
            "仮定: 各工程の人時は scenario の整備士暫定値(mechanic_provisional_add_ops)を使う",
            "仮定: 経過時間は人時(1人作業)に、FX-HUBCLEAN を含む case の防錆乾燥の待機(冬季仮説値)を足す(U5)。浸透待ち(FX-SEIZE)は S03 側、氷塊の融解待ちは前処理の案側で、S02 には足さない",
            "仮定: 段階の数と判定基準は暫定(0〜3)。docs では未定で、写真見本も未整備。範囲内の未確認(null)の関係部位は typical に入れず high にグレード3相当を置く(ルール4、U2)。現在の scenario では該当なし",
            "仮定: AG04 の顧客連絡は、グレード3または範囲内で未確認の関係部位があるときに促す。追加人時が連絡しきい値を超えるかとは別に出す",
        ],
        "unknowns": [
            "subframe は未確認(アンダーカバーで見えず撮影なし)。J1・J2 では外さないので作業範囲外とし high には入れない。腐食があれば作業範囲の拡大(AG04)として見積もりを変更し、顧客の了承を得る",
            "ハブ・ローターの固着は分解前で不明。グレード2からの推定にすぎない",
            "後輪ハブの状態は scenario に無く評価していない",
            "グレードの判定のばらつき(写真見本なし)",
            "防錆アンダーコート(申告)の上から腐食が見えにくい可能性があり、グレードが過小の恐れ",
            "個別ボルトの錆・スライドボルトの状態・固着対応の本数はこの案では見ていない(S03 の領域)",
        ],
    }
    out = json.dumps(result, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out + "\n")
    print(out)


if __name__ == "__main__":
    main()
