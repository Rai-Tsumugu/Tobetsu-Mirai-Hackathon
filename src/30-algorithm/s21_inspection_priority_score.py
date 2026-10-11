#!/usr/bin/env python3
"""S21 固着・腐食の確認優先度スコア

方針: スコアは「確認の順番」と「上限の幅に含める追加工程の範囲」を決めるためだけに使う。
人時には直接変換しない。low = typical = 基準 1.7 人時（工数は変えない）。

手順:
 1. first_registration と intake.date から初度登録からの経過年数を月単位で計算する。
 2. shop_policy.priority_score_table_S21 の加点表で次の要素を加点する。
    - 経過年数: 15年以上 3点 / 10年以上 2点（高い方1つだけ）
    - 走行距離: 150000km以上 2点 / 100000km以上 1点（高い方1つだけ）
    - 作業部位の錆グレード: 作業 J2 に関係する部位（ブレーキ周り・ハブ・フロントサスペンション）の
      最大グレードで 3 → 3点 / 2 → 2点
    - 未確認の部位または締結部が1つでもあれば 1点
    - 防錆アンダーコートの施工歴があれば 1点
    - 前回入庫で固着の記録があれば 2点
 3. 合計点を帯（低 0-3 / 中 4-7 / 高 8以上）に分け、加点の内訳を出す。
 4. 確認の順番を作る。未確認項目（スライドボルト・ローター固着・右ブーツ）を、
    分解前に確認できるものから、上限加算（人時）の大きい順に並べる。
 5. 帯は確認の緊急度（低: 作業中 / 中: 分解前 / 高: 見積もり確定前）と、上限の幅に含める範囲を決める（docs の仕組み）。
    低: 未確認の締結部（スライドボルト4本 FX-SEIZE high）だけ
    中: 未確認項目だけ（＋ローター2側 FX-ROTOR high、右ブーツ AG-BOOT high）
    高: 未確認項目＋重の締結部の折れ込み・ねじ山（U3: FX-BROKEN high ＋ FX-THREAD high、固着対応 FX-SEIZE high も）
    帯ごとの high を出し、今回の帯の値を採用する。
 6. low = typical = 1.7 人時（U2）。typical には何も入れない。観察済みの中（右ブラケット）は S21 の範囲外。
 7. サブフレームは U4 により作業範囲外（high に入れず unknowns に記録）。経過時間は U5 で、FX-SEIZE を high に含めたら浸透待ちを high にだけ足す。
"""
import json
import os
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "scenario.json"), encoding="utf-8") as f:
        sc = json.load(f)

    base = sc["base_totals"]["deduplicated_base"]
    tbl = sc["shop_policy"]["priority_score_table_S21"]
    ops = sc["mechanic_provisional_add_ops"]
    cond = sc["condition"]
    veh = sc["vehicle"]
    prev = sc["previous_visit_same_vehicle"]

    fy, fm = map(int, veh["first_registration"].split("-")[:2])
    iy, im, _ = map(int, sc["intake"]["date"].split("-"))
    months = (iy - fy) * 12 + (im - fm)
    years = months / 12
    km = veh["odometer_km"]

    # 作業 J2 に関係する部位（定数。仮定）
    work_areas = ["brake_area", "wheel_hub", "front_suspension"]
    grades = cond["underbody_rust_grade"]

    breakdown = []

    def add(label, pts, formula):
        breakdown.append({"label": label, "points": pts, "formula": formula})

    # 年数
    if years >= 15:
        add("経過年数", tbl["age_years_ge_15"], f"{years:.1f}年 >= 15 -> age_years_ge_15")
    elif years >= 10:
        add("経過年数", tbl["age_years_ge_10"], f"{years:.1f}年 >= 10 -> age_years_ge_10")
    else:
        add("経過年数", 0, f"{years:.1f}年 < 10")
    # 走行距離
    if km >= 150000:
        add("走行距離", tbl["odometer_ge_150000"], f"{km} >= 150000")
    elif km >= 100000:
        add("走行距離", tbl["odometer_ge_100000"], f"{km} >= 100000 -> odometer_ge_100000")
    else:
        add("走行距離", 0, f"{km} < 100000")
    # 作業部位の錆
    wa = {a: grades[a] for a in work_areas}
    wmax = max(g for g in wa.values() if g is not None)
    if wmax >= 3:
        add("作業部位の錆グレード", tbl["work_area_rust_grade_3"], f"最大 {wmax}（{wa}） -> work_area_rust_grade_3")
    elif wmax == 2:
        add("作業部位の錆グレード", tbl["work_area_rust_grade_2"], f"最大 {wmax} -> work_area_rust_grade_2")
    else:
        add("作業部位の錆グレード", 0, f"最大 {wmax}")
    # 未確認
    unconf_bolts = [x for x in cond["fasteners"] if x["rust"].startswith("未確認")]
    unconf_rust = [k for k, v in grades.items() if not k.startswith("_") and v is None]
    rotor_unconf = cond["rotor_hub_seizure"]["state"] == "未確認"
    boot_unconf = [s for s, v in cond["slide_pin_boots"].items() if v.startswith("未確認")]
    any_unconf = bool(unconf_bolts or unconf_rust or rotor_unconf or boot_unconf)
    add("未確認の部位・締結部", tbl["unconfirmed_area_exists"] if any_unconf else 0,
        f"スライドボルト{len(unconf_bolts)}本・ローター{int(rotor_unconf)}・右ブーツ{len(boot_unconf)}・錆グレード{len(unconf_rust)}部位 の合計 > 0")
    # 防錆
    coat = cond["rustproof_undercoat"]["value"]
    add("防錆アンダーコート施工歴", tbl["rustproof_coat_history"] if coat else 0, f"施工歴 {coat}（申告）")
    # 前回の固着
    prev_seize = "固着" in prev["observations"]
    add("前回の固着記録", tbl["previous_seizure_record"] if prev_seize else 0,
        f"前回 {prev['record_id']} の観察に「固着」{'あり' if prev_seize else 'なし'}")

    score = sum(b["points"] for b in breakdown)

    def parse(rng):
        return rng
    # 帯の判定（bands は "0-3" / "4-7" / "8以上" の文字列）
    band = None
    for name, rng in tbl["bands"].items():
        if rng.endswith("以上"):
            if score >= int(rng[:-2]):
                band = name
        else:
            lo, hi = map(int, rng.split("-"))
            if lo <= score <= hi:
                band = name

    # 上限の幅に含める追加工程（U2・U3）。帯ごとに high を作り、今回の帯の値を採用する。
    seize_each = ops["FX-SEIZE"]["high"]
    rotor_each = ops["FX-ROTOR"]["high"]
    boot_each = ops["AG-BOOT"]["high"]
    broken_each = ops["FX-BROKEN"]["high"]
    thread_each = ops["FX-THREAD"]["high"]
    heavy = [x for x in cond["fasteners"] if x["rust"].startswith("重")]
    n_b, n_s, n_t, n_h = len(unconf_bolts), (2 if rotor_unconf else 0), len(boot_unconf), len(heavy)
    add_bolt = seize_each * n_b
    add_rotor = rotor_each * n_s
    add_boot = boot_each * n_t
    # U3: 重（折れ込みの可能性）= FX-SEIZE high + FX-BROKEN high + FX-THREAD high
    heavy_each = seize_each + broken_each + thread_each
    add_heavy = heavy_each * n_h
    inc_by_band = {
        "低": add_bolt,
        "中": add_bolt + add_rotor + add_boot,
        "高": add_bolt + add_rotor + add_boot + add_heavy,
    }
    scope_by_band = {
        "低": "未確認の締結部（スライドボルト）だけ",
        "中": "未確認項目だけ（スライドボルト・ローター・右ブーツ）",
        "高": "未確認項目（スライドボルト・ローター・右ブーツ）＋ 重の締結部の折れ込み・ねじ山（U3）",
    }
    included = inc_by_band.get(band, 0.0)
    scope = scope_by_band.get(band, "-")
    high_by_band = {k: base + v for k, v in inc_by_band.items()}
    urgency = {"高": "見積もり確定前に必ず確認", "中": "分解前に確認", "低": "作業中に確認"}.get(band, "-")
    high = base + included
    # 浸透待ち（U5）: FX-SEIZE を high に含めるので high の経過時間にだけ足す
    soak = sc["elapsed_waits"]["penetrant_soak_wait_hours"]
    soak_in_high = (n_b + (n_h if band == "高" else 0)) > 0
    elapsed = {"low": base, "typical": base, "high": high + (soak if soak_in_high else 0.0)}

    # 確認の順番: 上限加算の大きい順（サブフレームは U4 により作業範囲外で 0）
    cands = [
        ("スライドボルト（ブーツ内）の錆", add_bolt, f"FX-SEIZE high {seize_each} x {n_b}本"),
        ("ローターとハブの固着（左右）", add_rotor, f"FX-ROTOR high {rotor_each} x {n_s}側"),
        ("右スライドピンブーツの硬化", add_boot, f"AG-BOOT high {boot_each} x {n_t}側"),
        ("サブフレームの錆（撮影なし・作業範囲外）", 0.0, "U4: J1・J2 では外さないので人時に入れない"),
    ]
    order = sorted(cands, key=lambda c: -c[1])
    order_txt = " > ".join(f"{i+1}. {c[0]}" for i, c in enumerate(order))

    r2 = lambda x: round(x, 2)
    out = {
        "id": "S21",
        "name": "固着・腐食の確認優先度スコア",
        "base_method": "共通基準（重複控除後 1.7 人時）",
        "factors": ["HK01", "HK07", "AG01", "AG07", "AG08"],
        "algorithm": [
            "手順1: 初度登録と入庫日から経過年数を月単位で計算する",
            "手順2: 加点表で 経過年数・走行距離・作業部位の最大錆グレード・未確認の有無・防錆施工歴・前回の固着記録 を加点する",
            "手順3: 合計点を帯（低/中/高）に分け、加点の内訳を出す",
            "手順4: 未確認項目を上限加算の大きい順に並べて確認の順番にする（サブフレームは U4 により範囲外）",
            "手順5: 帯で確認の緊急度（低=作業中 / 中=分解前 / 高=見積もり確定前）と上限に含める範囲を決める。低=未確認の締結部だけ、中=未確認項目だけ、高=未確認項目＋重の締結部の折れ込み・ねじ山（U3）。帯ごとの high を出し、今回の帯の値を採用する",
            "手順6: low = typical = 1.7 人時。high = 1.7 + 今回の帯の範囲の追加工程の high 値。観察済みの中のボルト・左ブーツ硬化は S21 の範囲外。スコアは人時に変換しない",
            "手順7: 経過時間は U5 により、FX-SEIZE を high に含めるので high にだけ浸透待ち 0.25 を足す。サブフレームは U4 により unknowns に記録する",
        ],
        "inputs": [
            {"key": "vehicle.first_registration / intake.date", "value": f"{veh['first_registration']} / {sc['intake']['date']}", "status": "確認済み"},
            {"key": "vehicle.odometer_km", "value": km, "status": "確認済み"},
            {"key": "condition.underbody_rust_grade（作業部位）", "value": wa, "status": "確認済み"},
            {"key": "condition.underbody_rust_grade.subframe", "value": None, "status": "不明"},
            {"key": "condition.rustproof_undercoat", "value": coat, "status": "申告"},
            {"key": "previous_visit_same_vehicle.observations", "value": "固着あり（左前ブラケットボルト1本）", "status": "確認済み"},
            {"key": "condition.fasteners（スライドボルト未確認・重の締結部）", "value": f"未確認{n_b}本・重{n_h}本", "status": "確認済み／不明"},
            {"key": "condition.rotor_hub_seizure / slide_pin_boots", "value": f"ローター{cond['rotor_hub_seizure']['state']}・右ブーツ{boot_unconf}", "status": "不明"},
            {"key": "shop_policy.priority_score_table_S21", "value": "工場承認の加点表（架空）", "status": "仮定"},
        ],
        "intermediates": [
            {"label": "初度登録からの経過年数", "value": r2(years), "unit": "年",
             "formula": f"({iy}-{fy})x12 + ({im}-{fm}) = {months}か月 / 12"},
            {"label": "優先度スコア（加点の内訳つき）", "value": score, "unit": "点",
             "formula": " + ".join(str(b["points"]) for b in breakdown) + f" = {score}（" + "; ".join(f"{b['label']}: {b['formula']}" for b in breakdown) + "）"},
            {"label": "帯", "value": band, "unit": "-",
             "formula": f"bands {tbl['bands']} に {score} 点を当てはめる。緊急度: {urgency}"},
            {"label": "確認の順番", "value": order_txt, "unit": "-",
             "formula": "未確認項目を上限加算（人時）の大きい順に並べる"},
            {"label": "帯ごとの high", "value": " / ".join(f"{k} {r2(v)}" for k, v in high_by_band.items()), "unit": "人時",
             "formula": f"低: {base} + FX-SEIZE high {seize_each} x {n_b}本; "
                        f"中: 低 + FX-ROTOR high {rotor_each} x {n_s}側 + AG-BOOT high {boot_each} x {n_t}側; "
                        f"高: 中 + (FX-SEIZE {seize_each} + FX-BROKEN {broken_each} + FX-THREAD {thread_each}) x 重{n_h}本（U3）"},
            {"label": "上限への加算（今回の帯）", "value": r2(included), "unit": "人時",
             "formula": f"帯「{band}」の範囲: {scope}"},
            {"label": "high", "value": r2(high), "unit": "人時", "formula": f"{base} + {r2(included)}（帯「{band}」の値を採用）"},
        ],
        "result": {
            "labor_hours": {"low": r2(base), "typical": r2(base), "high": r2(high)},
            "elapsed_hours": {k: r2(v) for k, v in elapsed.items()},
            "other_outputs": [
                {"label": "優先度スコア", "value": score, "unit": "点"},
                {"label": "優先度の帯", "value": band, "unit": "-"},
                {"label": "確認の順番", "value": order_txt, "unit": "-"},
                {"label": "確認の緊急度", "value": urgency, "unit": "-"},
                {"label": "帯ごとの high", "value": {k: r2(v) for k, v in high_by_band.items()}, "unit": "人時"},
            ],
            "note": "工数は変えない（typical=1.7）。スコアは確認の順番・緊急度と、上限に含める範囲を決めるために使い、人時へ直接変換しない。"
                    f"この案の範囲での上限（high）は、帯「{band}」の範囲として、未確認のスライドボルト{n_b}本・ローター{n_s}側・右ブーツ{n_t}側に加え、"
                    f"重の締結部{n_h}本の折れ込み抜き取り・ねじ山修正（U3）を含めた（未確認を0として確定しない）。"
                    "観察済みの中（右ブラケット）と左ブーツの硬化は、個別指示により S21 では扱わず（S21 は未確認項目と重の折れ込み・ねじ山を上限の幅にだけ反映する案）、S01・S03 等で扱う。"
                    "スコアは人時へ直接変換せず、帯ごとに上限に含める工程の組を選ぶためにだけ使う（帯ごとの high を intermediates に出した）。"
                    "重の締結部の low・typical は、S21 が工数を変えない案（1.7固定）のため U3 の表の値を足さない。"
                    "ローター固着（FX-ROTOR）は AG01 の「締結部の錆・固着」の延長として未確認の固着を扱う。"
                    "factors の HK07・AG08 は §3 にない加点要素（未確認の有無・前回記録）で、§4 の仕組みに合わせて加えた。"
                    "サブフレームの錆は J1・J2 では外さない作業範囲外のため high に入れない（腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る）。"
                    "経過時間は、FX-SEIZE を含める high にだけ浸透待ち 0.25 を足した。",
        },
        "assumptions": [
            "仮定: 加点表は工場が承認したという想定の架空値で、重みは仮置き（S10の実績で見直す）",
            "仮定: 作業 J2 に関係する部位は ブレーキ周り・ハブ・フロントサスペンション とし、その最大グレードで1回だけ加点する",
            "仮定: 年数・距離の加点は高い方の1つだけ採用し、累積しない",
            "仮定: 帯ごとの確認の緊急度（低=作業中／中=分解前／高=見積もり確定前）と上限に含める範囲（低=未確認の締結部／中=未確認項目／高=未確認＋重の折れ込み・ねじ山）は本スクリプトの定数（docs の仕組み、U2・U3）",
            "仮定: 帯「高」では重の締結部（左ブラケット2本）を U3 の high 列（FX-SEIZE＋FX-BROKEN＋FX-THREAD の high）で含める。観察済みの中（右ブラケット）と左ブーツ硬化は S21 の範囲外",
            "仮定: 浸透待ち 0.25（elapsed_waits）は FX-SEIZE を含める high の経過時間にだけ足す（U5）。待機は人時に入れない",
            "仮定: 作業部位の錆グレードは work_area_rust_grade_2 と _3 のどちらか一方だけを加点し、併存しても累積しない",
            "仮定: HK07・AG08 は点数化している（未確認の有無・前回記録）ので factors に含める。docs §4 本文に合わせた",
            "仮定: 未確認のハブ錆グレード2のローターは左右とも固着の可能性があるとして FX-ROTOR high を2側分入れる",
            "仮定: 加点の閾値（経過年数15年・10年、走行距離150000km・100000km、錆グレード3・2）は加点表のキー名に合わせた本スクリプトの定数で、scenario.json に値はない",
            "仮定: 重の締結部の low・typical は S21 が1.7固定のため U3 の low・typical 行を適用せず、high にだけ U3 の high 列を入れる（帯「高」）",
            "仮定: ローター固着は AG01（締結部の錆・固着）に含めて扱う",
            "仮定: 帯による上限の切り替えは人時への直接変換ではなく、docs の仕組み（上限の幅に反映）に従う範囲の選択",
            "仮定: 前回の固着記録は observations の文字列「固着」の部分一致で判定する（表記揺れに弱い。S10 の実績データ導入時は原因タグでの判定に置き換える）",
        ],
        "unknowns": [
            "スライドボルト4本の錆: ブーツに隠れて見えない",
            "ローター固着: 分解前のため不明",
            "右スライドピンブーツの状態",
            "左スライドピンブーツの硬化: 観察済み。S21 では加算せず他案（AG-BOOT）で扱う",
            "サブフレームの錆グレード: アンダーカバーで見えず撮影なし。J1・J2 では外さない作業範囲外のため high に入れない。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る（U4）",
            "防錆アンダーコートの施工は顧客申告で、コートの上から腐食が見えにくい可能性がある",
        ],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    os.makedirs(os.path.join(here, "results"), exist_ok=True)
    with open(os.path.join(here, "results", "S21.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
