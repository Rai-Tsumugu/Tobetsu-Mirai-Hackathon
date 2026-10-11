#!/usr/bin/env python3
"""S04 経過年数・走行距離による確認強度の切替

方針: 経過年数と走行距離は工数を増やす倍率に使わない。「何を確認すべきか」を切り替えるためだけに使う。

手順:
 1. scenario.json から first_registration と intake.date を読み、初度登録からの経過年数を月単位で計算する。
 2. 走行距離 odometer_km を読む。
 3. shop_policy.check_intensity_threshold（年数・距離）と比べ、どちらかを満たせば確認強度「強」、
    どちらも満たさなければ「通常」とする。
 4. 強の場合、追加確認項目（下回りの撮影、締結部の観察、ゴム部品の状態）を出す。
 5. 追加確認項目ごとに scenario.json の condition を照合し、「未確認」の項目を数える
    （スライドボルト、ローター固着、右ブーツ、サブフレーム錆グレード）。
 6. typical は増やさない。low = typical = 基準 1.7 人時（SPEC 共通ルール10）。
 7. docs の仕組み「確認しなかった項目は『未確認』として上限の幅に反映する」に従い、確認強度「強」で出た
    追加確認項目のうち未確認のもの（スライドボルト→FX-SEIZE、ローター→FX-ROTOR、ブーツ→AG-BOOT）を
    mechanic_provisional_add_ops の high 値で high にだけ加える（docs を正とする。ルール4の「上限側に入れる」とも整合）。
    typical には足さない。サブフレーム錆グレードは対応する追加工程が定義されていないため人時にせず unknowns に残す。
    年数・距離そのものは人時の根拠にしない（ルール5）。
 8. 経過時間（U5）: high に FX-SEIZE を含めたら浸透待ち（scenario.json の elapsed_waits）を high の経過時間にだけ足す。
    low / typical は FX-SEIZE を含めないので待機を足さず、人時と同じ。待機は人時に入れない。
 9. サブフレーム（U4）は J1・J2 で外さないので作業範囲外。high に入れず unknowns に作業範囲拡大（AG04）の旨を書く。
"""
import json
import os
import sys


MONTHS_PER_YEAR = 12  # 月→年の換算（単位定数）
ROTOR_SIDES_WHEN_UNCONFIRMED = 2  # 仮定: 作業が「ローター交換（左右）」のため未確認なら左右2側を数える
EXTRA_ITEMS_COUNT = 3  # 強のとき出す追加確認項目の数（定数）


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "scenario.json"), encoding="utf-8") as f:
        sc = json.load(f)

    base = sc["base_totals"]["deduplicated_base"]
    th = sc["shop_policy"]["check_intensity_threshold"]
    cond = sc["condition"]

    fy, fm = map(int, sc["vehicle"]["first_registration"].split("-")[:2])
    iy, im, _ = map(int, sc["intake"]["date"].split("-"))
    months = (iy - fy) * MONTHS_PER_YEAR + (im - fm)
    years = months / MONTHS_PER_YEAR
    km = sc["vehicle"]["odometer_km"]

    age_hit = years >= th["age_years"]
    km_hit = km >= th["odometer_km"]
    strong = age_hit or km_hit
    intensity = "強" if strong else "通常"

    # 未確認項目の数え上げ
    unconf_bolts = [x for x in cond["fasteners"] if x["rust"].startswith("未確認")]
    n_bolts = len(unconf_bolts)
    rotor_unconf = cond["rotor_hub_seizure"]["state"] == "未確認"
    n_rotor_sides = ROTOR_SIDES_WHEN_UNCONFIRMED if rotor_unconf else 0
    boot_unconf = [s for s, v in cond["slide_pin_boots"].items() if v.startswith("未確認")]
    n_boot = len(boot_unconf)
    rust_unconf = [k for k, v in cond["underbody_rust_grade"].items()
                   if not k.startswith("_") and v is None]

    # typical は変えない。強のとき、未確認の追加確認項目だけを high（上限）に反映する（docs の仕組み）。
    ops = sc["mechanic_provisional_add_ops"]
    soak = sc["elapsed_waits"]["penetrant_soak_wait_hours"]  # U5: FX-SEIZE を含めたときの浸透待ち
    add_bolt = n_bolts * ops["FX-SEIZE"]["high"] if strong else 0.0
    add_rotor = n_rotor_sides * ops["FX-ROTOR"]["high"] if strong else 0.0
    add_boot = n_boot * ops["AG-BOOT"]["high"] if strong else 0.0
    add_high = add_bolt + add_rotor + add_boot
    high = base + add_high
    soak_added = soak if add_bolt > 0 else 0.0
    elapsed_high = high + soak_added

    extra_items = ["下回りの撮影（錆グレード）", "締結部の観察（スライドボルト・ブラケットボルト）",
                   "ゴム部品の状態（スライドピンブーツ）"] if strong else []  # 表示項目の定数

    r2 = lambda x: round(x, 2)
    out = {
        "id": "S04",
        "name": "経過年数・走行距離による確認強度の切替",
        "base_method": "共通基準（重複控除後 1.7 人時）",
        "factors": ["AG07"],
        "algorithm": [
            "手順1: first_registration と intake.date から初度登録からの経過年数を月単位で計算する",
            "手順2: 経過年数と走行距離を check_intensity_threshold（年数・距離）と比べる。どちらか満たせば確認強度「強」",
            "手順3: 強なら追加確認項目（下回りの撮影、締結部の観察、ゴム部品の状態）を出す",
            "手順4: 追加確認項目のうち condition が「未確認」のものを数える",
            "手順5: typical は増やさない。low = typical = 基準 1.7 人時",
            "手順6: 強のとき未確認の追加確認項目（スライドボルト・ローター・ブーツ）を FX-SEIZE / FX-ROTOR / AG-BOOT の high 値で high にだけ加える。サブフレームは作業範囲外として unknowns に残す（U4）",
            "手順7: high に FX-SEIZE を含めるので、high の経過時間にだけ浸透待ちを足す（U5）",
        ],
        "inputs": [
            {"key": "vehicle.first_registration", "value": sc["vehicle"]["first_registration"], "status": "確認済み"},
            {"key": "intake.date", "value": sc["intake"]["date"], "status": "確認済み"},
            {"key": "vehicle.odometer_km", "value": km, "status": "確認済み"},
            {"key": "shop_policy.check_intensity_threshold", "value": f"{th['age_years']}年 / {th['odometer_km']}km", "status": "仮定"},
            {"key": "condition.fasteners（未確認）", "value": n_bolts, "status": "不明"},
            {"key": "condition.rotor_hub_seizure", "value": cond["rotor_hub_seizure"]["state"], "status": "不明"},
            {"key": "condition.slide_pin_boots（未確認側）", "value": boot_unconf, "status": "不明"},
            {"key": "condition.underbody_rust_grade（未確認）", "value": rust_unconf, "status": "不明"},
        ],
        "intermediates": [
            {"label": "初度登録からの経過年数", "value": r2(years), "unit": "年",
             "formula": f"({iy}-{fy})x12 + ({im}-{fm}) = {months}か月 / 12"},
            {"label": "年数のしきい値判定", "value": age_hit, "unit": "真偽",
             "formula": f"{r2(years)} >= {th['age_years']}"},
            {"label": "走行距離のしきい値判定", "value": km_hit, "unit": "真偽",
             "formula": f"{km} >= {th['odometer_km']}"},
            {"label": "確認強度", "value": intensity, "unit": "-",
             "formula": "年数判定 OR 距離判定 なら 強、それ以外は 通常"},
            {"label": "追加確認項目数", "value": len(extra_items), "unit": "項目",
             "formula": f"強なら {EXTRA_ITEMS_COUNT}項目（下回り撮影・締結部観察・ゴム部品）、通常なら 0"},
            {"label": "未確認の項目数", "value": n_bolts + n_rotor_sides + n_boot + len(rust_unconf), "unit": "項目",
             "formula": f"スライドボルト {n_bolts} + ローター固着 {n_rotor_sides}側 + ブーツ {n_boot}（{'・'.join(boot_unconf) or 'なし'}） + 錆グレード未確認 {len(rust_unconf)}（{'・'.join(rust_unconf) or 'なし'}）"},
            {"label": "未確認項目の high 加算（上限の幅）", "value": r2(add_high), "unit": "人時",
             "formula": f"スライドボルト {n_bolts}本x{ops['FX-SEIZE']['high']} + ローター {n_rotor_sides}側x{ops['FX-ROTOR']['high']} + 右ブーツ {n_boot}側x{ops['AG-BOOT']['high']} = {r2(add_high)}（high のみ。強のときだけ）"},
            {"label": "high の経過時間（浸透待ち込み）", "value": r2(elapsed_high), "unit": "時間",
             "formula": f"high {r2(high)} + 浸透待ち {soak}（FX-SEIZE を high に含めるため。U5。low / typical は待機なしで {r2(base)}）"},
            {"label": "基準に対する typical の増分", "value": 0.0, "unit": "人時",
             "formula": "確認強度は typical を増やさない（0）"},
        ],
        "result": {
            "labor_hours": {"low": r2(base), "typical": r2(base), "high": r2(high)},
            "elapsed_hours": {"low": r2(base), "typical": r2(base), "high": r2(elapsed_high)},
            "other_outputs": [
                {"label": "確認強度", "value": intensity, "unit": "-"},
                {"label": "追加確認項目", "value": " / ".join(extra_items) if extra_items else "なし", "unit": "-"},
            ],
            "note": "typical は変えない（low=typical=1.7、SPEC 共通ルール10）。経過年数・走行距離は何を確認すべきかの切替にだけ使い、人時の根拠にしない（ルール5）。"
                    "上限の幅は docs の S04 の仕組みに基づく（確認しなかった項目は未確認として上限の幅に反映する）。未確認の項目は high にだけ反映し、0 とは確定しない（ルール4）。サブフレーム錆は J1・J2 で外さない作業範囲外のため high に入れず unknowns に残す（U4）。"
                    "経過時間は high にだけ浸透待ち（FX-SEIZE を含めるため）を足し、待機は人時に入れない（U5）。"
                    "high の上昇（1.7→上限）は工数そのものの増加ではなく『未確認の分を含めた上限の幅』であり、docs §6.1 の『工数は増えない』は typical について成り立つ。"
                    "S04 の範囲（U1）は確認強度「強」で出す追加確認項目のうち未確認のものであり、観察済みのブラケットボルトの悪化（重・中）は締結部を扱う他案（S01・S03 など）の範囲のため high に入れない。"
                    "確認強度が通常の場合は追加確認項目を出さないため未確認を扱わず high = typical = 基準になる（未確認を 0 と確定したのではなく、確認項目自体を出していない）。"
                    "加算に使う FX-SEIZE / FX-ROTOR / AG-BOOT は他案（S03・S01、S07・S15、AG03・S22）の領域の暫定値を『上限の幅』の表示にだけ借りたもので、S04 の factors（AG07）は変えない。",
        },
        "assumptions": [
            "仮定: 確認強度のしきい値は shop_policy.check_intensity_threshold（工場の仮置き値）で、実績が溜まるまで根拠は弱い",
            "仮定: 追加確認項目は3つ（下回りの撮影、締結部の観察、ゴム部品の状態）に固定する（定数）",
            "仮定: 未確認項目の high 加算は mechanic_provisional_add_ops の high 値（FX-SEIZE / FX-ROTOR / AG-BOOT）を使う。typical には足さない",
            f"仮定: ローター固着が未確認なら、作業内容が『ローター交換（左右）』のため左右 {ROTOR_SIDES_WHEN_UNCONFIRMED} 側として数える（1側なら high は 0.4 人時下がる）。ローターは片側ごとに FX-ROTOR を1件とする",
            f"仮定: 月→年の換算は {MONTHS_PER_YEAR}、追加確認項目数は {EXTRA_ITEMS_COUNT}（定数）。typical の増分 0.0 は方針（増やさない）の表現",
            "仮定: サブフレームは J1・J2 では外さないので作業範囲外とする（U4）。人時にせず unknowns に残す",
            "仮定: 浸透待ち（elapsed_waits）は人時に入れず、FX-SEIZE を含める high の経過時間にだけ足す（U5）",
        ],
        "unknowns": (
            [f"{x['name']}の錆: {x['rust']}" for x in unconf_bolts]
            + ([f"ローター固着: {cond['rotor_hub_seizure']['state']}（{cond['rotor_hub_seizure']['detail']}）"] if rotor_unconf else [])
            + [f"{s}スライドピンブーツ: {cond['slide_pin_boots'][s]}" for s in boot_unconf]
            + [f"{k}の錆グレード: 未確認（{cond['underbody_rust_grade'].get('_unconfirmed_reason', {}).get(k, '理由なし')}）。J1・J2 では外さないため作業範囲外。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る" for k in rust_unconf]
        ),
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    os.makedirs(os.path.join(here, "results"), exist_ok=True)
    with open(os.path.join(here, "results", "S04.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
