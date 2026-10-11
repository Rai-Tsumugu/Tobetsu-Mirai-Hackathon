#!/usr/bin/env python3
"""S26 電子車検証の取込による車両情報の自動入力

方針: 車検証から取れる項目だけを vehicle に写し、初度登録からの経過年数を自動計算して
S04（確認強度）と S21（加点）に渡す。経過年数・走行距離は工数の倍率に使わない。
所有者・使用者の情報は工数入力に取り込まない。工数そのものは変えない。

手順:
 1. scenario.json の e_shakensho_sample を読む。取り込む項目は 車名・型式・原動機の型式・
    初度登録年月・車両重量 の5つだけ。「使用者」は読まず、出力にも入れない。
 2. 和暦の初度登録年月（例: 平成26年1月）を西暦に変換する。
    西暦 = 元号の元年の西暦 + 年 - 1（平成の元年=1989、令和=2019、昭和=1926）。
 3. 取込値と vehicle の値（型式、原動機型式、初度登録、重量）を照合する。不一致は unknowns に記録。
 4. intake.date と初度登録年月から経過年数を月単位で計算する（年・月と小数年）。
 5. S04 に渡す値: shop_policy.check_intensity_threshold と比べ、年数または走行距離が
    しきい値以上なら確認強度「強」、そうでなければ「通常」。
 6. S21 に渡す値: priority_score_table_S21 のうち、車検証と走行距離で決まる加点
    （年数 10年以上=2、15年以上=3。走行距離 10万km以上=1、15万km以上=2。各要素の中では上位の区分のみ採り、年数と走行距離は別要素なので合算する）。
    錆・未確認・防錆歴・前回固着は車検証から分からないので、ここでは加点しない。
 7. 寒冷地仕様・4WD・後付け装備は車検証で確定できないため、現車確認が必要な項目として記録する。
 8. 工数は変えない。low = typical = high = 基準 1.7 人時（deduplicated_base）。
    取込は入力作業の支援であり、作業の追加工程を生まない。経過時間は扱わない（null）。
"""
import json
import os
import re
import sys

ERA_FIRST_YEAR = {"令和": 2019, "平成": 1989, "昭和": 1926}  # 仮定: 各元号の元年の西暦


def parse_wareki(text):
    m = re.fullmatch(r"\s*(令和|平成|昭和)\s*(元|\d+)\s*年\s*(\d{1,2})\s*月\s*", text)
    if not m:
        raise ValueError(f"和暦を解釈できない: {text}")
    era, y, mo = m.group(1), m.group(2), int(m.group(3))
    y = 1 if y == "元" else int(y)
    return ERA_FIRST_YEAR[era] + y - 1, mo


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "scenario.json"), encoding="utf-8") as f:
        sc = json.load(f)

    base = sc["base_totals"]["deduplicated_base"]
    veh = sc["vehicle"]
    sample = sc["e_shakensho_sample"]
    th = sc["shop_policy"]["check_intensity_threshold"]
    tbl = sc["shop_policy"]["priority_score_table_S21"]
    km = veh["odometer_km"]

    # 1. 取込（使用者は読まない）
    imported = {k: sample[k] for k in ("車名", "型式", "原動機の型式", "初度登録年月", "車両重量")}
    weight_kg = int(re.sub(r"\D", "", imported["車両重量"]))

    # 2. 和暦変換
    ry, rm = parse_wareki(imported["初度登録年月"])

    # 3. 照合
    vy, vm = map(int, veh["first_registration"].split("-")[:2])
    checks = [
        ("型式", imported["型式"], veh["katashiki"]),
        ("原動機の型式", imported["原動機の型式"], veh["engine"]),
        ("初度登録", f"{ry}-{rm:02d}", veh["first_registration"]),
        ("車両重量(kg)", weight_kg, veh["vehicle_weight_kg"]),
    ]
    mismatches = [c for c in checks if str(c[1]) != str(c[2])]

    # 4. 経過年数
    iy, im, _ = map(int, sc["intake"]["date"].split("-"))
    months = (iy - ry) * 12 + (im - rm)
    yy, mm = divmod(months, 12)
    years = months / 12

    # 5. S04 へ
    age_hit = years >= th["age_years"]
    km_hit = km >= th["odometer_km"]
    intensity = "強" if (age_hit or km_hit) else "通常"

    # 6. S21 へ（年数・走行距離の加点だけ。各要素内は上位区分のみ、要素間は合算。S21 の実装と同じ）
    age_pts = tbl["age_years_ge_15"] if years >= 15 else (tbl["age_years_ge_10"] if years >= 10 else 0)
    km_pts = tbl["odometer_ge_150000"] if km >= 150000 else (tbl["odometer_ge_100000"] if km >= 100000 else 0)
    s21_partial = age_pts + km_pts

    r2 = lambda x: round(x, 2)
    out = {
        "id": "S26",
        "name": "電子車検証の取込による車両情報の自動入力",
        "base_method": "共通基準（重複控除後 1.7 人時）",
        "factors": ["HK06", "AG07"],
        "algorithm": [
            "手順1: e_shakensho_sample から 車名・型式・原動機の型式・初度登録年月・車両重量 の5項目だけを取り込む（使用者は取り込まない）",
            "手順2: 和暦の初度登録年月を西暦に変換する（平成の元年=1989、西暦 = 1989 + 年 - 1）",
            "手順3: 取込値を vehicle の値と照合し、不一致があれば unknowns に記録する",
            "手順4: intake.date と初度登録年月から経過年数を月単位で計算する",
            "手順5: S04 へ渡す確認強度を、年数または走行距離がしきい値以上かで決める",
            "手順6: S21 へ渡す加点を、年数・走行距離の区分から決める（年数の中・走行距離の中ではそれぞれ上位の区分だけを採り、年数と走行距離は別要素として合算する。錆・未確認・防錆歴・前回固着は含まない）",
            "手順7: 寒冷地仕様・4WD・後付け装備は車検証で確定できないので、現車確認の項目として記録する",
            "手順8: 工数は変えない。low = typical = high = 基準 1.7 人時",
        ],
        "inputs": [
            {"key": "e_shakensho_sample.車名", "value": imported["車名"], "status": "申告"},
            {"key": "e_shakensho_sample.型式", "value": imported["型式"], "status": "申告"},
            {"key": "e_shakensho_sample.原動機の型式", "value": imported["原動機の型式"], "status": "申告"},
            {"key": "e_shakensho_sample.初度登録年月", "value": imported["初度登録年月"], "status": "申告"},
            {"key": "e_shakensho_sample.車両重量", "value": imported["車両重量"], "status": "申告"},
            {"key": "intake.date", "value": sc["intake"]["date"], "status": "確認済み"},
            {"key": "vehicle.odometer_km", "value": km, "status": "確認済み"},
            {"key": "shop_policy.check_intensity_threshold", "value": f"{th['age_years']}年 / {th['odometer_km']}km", "status": "仮定"},
            {"key": "shop_policy.priority_score_table_S21（年数・走行距離）", "value": f"年数10年以上={tbl['age_years_ge_10']}、15年以上={tbl['age_years_ge_15']}、10万km以上={tbl['odometer_ge_100000']}、15万km以上={tbl['odometer_ge_150000']}", "status": "仮定"},
        ],
        "intermediates": [
            {"label": "初度登録（西暦）", "value": f"{ry}-{rm:02d}", "unit": "年-月",
             "formula": f"平成{imported['初度登録年月'].split('年')[0].replace('平成', '')}年 → {ERA_FIRST_YEAR['平成']} + 26 - 1 = {ry}"},
            {"label": "初度登録からの経過", "value": f"{yy}年{mm}か月", "unit": "年・月",
             "formula": f"({iy}-{ry})x12 + ({im}-{rm}) = {months}か月 → {yy}年{mm}か月"},
            {"label": "経過年数（小数）", "value": r2(years), "unit": "年", "formula": f"{months}か月 / 12"},
            {"label": "S04 へ渡す確認強度", "value": intensity, "unit": "-",
             "formula": f"年数 {r2(years)} >= {th['age_years']} は {age_hit}、走行 {km} >= {th['odometer_km']} は {km_hit} → どちらか真なら強"},
            {"label": "S21 へ渡す年数加点", "value": age_pts, "unit": "点",
             "formula": f"{r2(years)}年 >= 15 は {years >= 15}、>= 10 は {years >= 10} → {age_pts}"},
            {"label": "S21 へ渡す走行距離加点", "value": km_pts, "unit": "点",
             "formula": f"{km}km >= 150000 は {km >= 150000}、>= 100000 は {km >= 100000} → {km_pts}"},
            {"label": "S21 へ渡す加点（車検証・走行分の小計）", "value": s21_partial, "unit": "点",
             "formula": f"{age_pts} + {km_pts}（錆・未確認・防錆歴・前回固着は S21 側で加える）"},
            {"label": "車検証と vehicle の不一致", "value": len(mismatches), "unit": "項目",
             "formula": "型式・原動機型式・初度登録・車両重量(kg) を比較した不一致の数"},
        ],
        "result": {
            "labor_hours": {"low": r2(base), "typical": r2(base), "high": r2(base)},
            "elapsed_hours": None,
            "other_outputs": [
                {"label": "S04 へ渡す確認強度", "value": intensity, "unit": "-"},
                {"label": "S21 へ渡す加点（年数＋走行距離）", "value": s21_partial, "unit": "点"},
                {"label": "初度登録からの経過", "value": f"{yy}年{mm}か月", "unit": "年・月"},
            ],
            "note": "工数は変えない。車検証の取込は入力の手間と転記ミスを減らす支援で、追加工程を生まない。"
                    "経過年数は確認の強さと加点の入力に使うだけで、工数の倍率にしない。所有者・使用者の情報は取り込んでいない。",
        },
        "assumptions": [
            "仮定: 平成の元年を 1989 年として和暦を西暦に変換した（scenario.json にない値）",
            "仮定: 初度登録は月の初日として、月単位で経過年数を計算した",
            "仮定: S21 の加点表に合わせ、年数の区分どうし・走行距離の区分どうしは上位だけを採り（15年以上なら 2 ではなく 3）、年数と走行距離は別要素なので合算する",
            "仮定: e_shakensho_sample は架空JSON。実在の様式での読取・取込は未実施",
        ],
        "unknowns": [
            "寒冷地仕様は車検証では確定できない。現車確認が必要（scenario では現車確認済みだが、車検証由来の値ではない）",
            "4WD・後付けエンジンスターターなどの装備も車検証だけでは確定できない。現車・諸元で確認する",
            "初度登録年月は製造年やモデル年ではない。経過年数は「初度登録からの年数」として扱う",
            "車検証に走行距離は含まれない。走行距離は別途メーターで確認する",
        ] + [f"車検証と vehicle が不一致: {c[0]} 車検証={c[1]} vehicle={c[2]}" for c in mismatches],
    }

    text = json.dumps(out, ensure_ascii=False, indent=2)
    os.makedirs(os.path.join(here, "results"), exist_ok=True)
    with open(os.path.join(here, "results", "S26.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
