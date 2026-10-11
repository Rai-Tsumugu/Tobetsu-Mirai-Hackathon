#!/usr/bin/env python3
"""S06 入庫日の気象に連動した前処理の確認

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。
 2. 入庫日の気象予報（weather_forecast_for_intake_day）を、工場方針
    shop_policy.weather_prompt_threshold と比べる。
    最低気温 <= min_temp_c_le、または降雪予報 >= snowfall_cm_ge のどちらかを
    満たせば「前処理（雪下ろし・氷塊除去）の確認を促す」表示を出す。
    気象は確認を促すためだけに使い、人時は決めない。
 3. 前処理の人時は、入庫時の現車確認（condition.snow_on_body,
    condition.ice_in_wheel_house）の状態で決める。
    - 雪下ろし(PRE-SNOW)は入庫1回分。「問題あり」なら加算。
    - 氷塊除去(PRE-ICE)はホイールハウス1か所ごと。locations 数を掛ける。
    - 「未確認」は typical に入れず high 側にだけ入れ、unknowns に記録する。
    - 「問題を観察していない」は 0。
 4. 出発点は重複控除後の基準 1.7 人時。そこへ low/typical/high ごとに前処理を足す。
    S06 は HK02・HK03 だけを扱うため、固着対応など他の要因は加えない。
 5. 経過時間は人時 + 融解待ち（U5。氷塊除去を含む水準ごとに足す。人時には入れない）。
 6. 請求対象は雪下ろし・氷塊除去（shop_policy.pre_processing_billing）。
    金額は人時に足さない。
 7. 結果を JSON で標準出力と results/S06.json に出す。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def r2(x):
    return round(x + 1e-9, 2)


def main():
    with open(os.path.join(HERE, "scenario.json"), encoding="utf-8") as f:
        sc = json.load(f)

    wx = sc["weather_forecast_for_intake_day"]
    th = sc["shop_policy"]["weather_prompt_threshold"]
    cond = sc["condition"]
    ops = sc["mechanic_provisional_add_ops"]
    base = sc["base_totals"]["deduplicated_base"]
    thaw = sc["elapsed_waits"]["thaw_wait_hours"]

    # 気象判定（確認を促すだけ）
    cold = wx["min_temp_c"] <= th["min_temp_c_le"]
    snowy = wx["snowfall_forecast_cm"] >= th["snowfall_cm_ge"]
    prompt = cold or snowy
    prompt_msg = ("【確認を促す】入庫日は低温または降雪の予報です。"
                  "雪下ろし・氷塊除去の要否を入庫時に現車で確認してください。"
                  if prompt else "気象上の確認促しは出ません（現車確認は通常どおり）。")

    # 現車確認による前処理
    snow_state = cond["snow_on_body"]["state"]
    ice_state = cond["ice_in_wheel_house"]["state"]
    ice_locs = cond["ice_in_wheel_house"].get("locations", 0)

    def count(state, n):
        # (low/typical 用の件数, high 用の件数)
        if state == "問題あり":
            return n, n
        if state == "未確認":
            return 0, n
        return 0, 0

    snow_n, snow_n_hi = count(snow_state, 1)
    ice_n, ice_n_hi = count(ice_state, max(ice_locs, 1))

    def pre(level):
        hi = level == "high"
        s = ops["PRE-SNOW"][level] * (snow_n_hi if hi else snow_n)
        i = ops["PRE-ICE"][level] * (ice_n_hi if hi else ice_n)
        return s, i

    levels = ["low", "typical", "high"]
    snow_h = {}
    ice_h = {}
    lab = {}
    for lv in levels:
        snow_h[lv], ice_h[lv] = pre(lv)
        lab[lv] = base + snow_h[lv] + ice_h[lv]

    # U5: 氷塊除去を含む水準ごとに融解待ちを経過時間へ足す（人時には入れない）
    ice_in = {lv: ice_h[lv] > 0 for lv in levels}
    has_ice = ice_in["typical"]
    thaw_by = {lv: (thaw if ice_in[lv] else 0.0) for lv in levels}
    elapsed = {lv: lab[lv] + thaw_by[lv] for lv in levels}

    # 請求対象の前処理（金額は求めず人時のみ）
    billed_typ = snow_h["typical"] + ice_h["typical"]

    inputs = [
        {"key": "weather_forecast_for_intake_day.min_temp_c", "value": wx["min_temp_c"], "status": "仮定"},
        {"key": "weather_forecast_for_intake_day.snowfall_forecast_cm", "value": wx["snowfall_forecast_cm"], "status": "仮定"},
        {"key": "weather_forecast_for_intake_day.snowfall_previous_day_cm", "value": wx["snowfall_previous_day_cm"], "status": "仮定"},
        {"key": "shop_policy.weather_prompt_threshold", "value": th, "status": "仮定"},
        {"key": "condition.snow_on_body", "value": cond["snow_on_body"], "status": "確認済み"},
        {"key": "condition.ice_in_wheel_house", "value": cond["ice_in_wheel_house"], "status": "確認済み"},
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
    ]

    inter = [
        {"label": "気象による確認促し", "value": "あり" if prompt else "なし", "unit": "",
         "formula": f"最低気温{wx['min_temp_c']}℃ <= {th['min_temp_c_le']}℃ ({cold}) または 降雪予報{wx['snowfall_forecast_cm']}cm >= {th['snowfall_cm_ge']}cm ({snowy})"},
        {"label": "気象が決める人時", "value": 0.0, "unit": "人時",
         "formula": "気象は確認を促すだけ。人時は現車確認で決める（気象→人時の換算はしない）"},
        {"label": "現車確認による雪下ろし", "value": r2(snow_h["typical"]), "unit": "人時",
         "formula": f"PRE-SNOW {ops['PRE-SNOW']['typical']} × {snow_n}回（snow_on_body={snow_state}）"},
        {"label": "現車確認による氷塊除去", "value": r2(ice_h["typical"]), "unit": "人時",
         "formula": f"PRE-ICE {ops['PRE-ICE']['typical']} × {ice_n}か所（ice_in_wheel_house={ice_state}）"},
        {"label": "前処理の合計（typical）", "value": r2(snow_h["typical"] + ice_h["typical"]), "unit": "人時",
         "formula": "雪下ろし + 氷塊除去"},
        {"label": "融解待ち（経過時間のみ）", "value": thaw_by["typical"], "unit": "時間",
         "formula": f"elapsed_waits.thaw_wait_hours {thaw}（U5: 氷塊除去を含む low/typical/high それぞれの経過時間に足す。low={thaw_by['low']}, typical={thaw_by['typical']}, high={thaw_by['high']}。人時には入れない）"},
        {"label": "気象と現車確認の役割の違い", "value": "気象=予約段階の注意喚起 / 現車=人時の根拠", "unit": "",
         "formula": "気象統計は個別車両の状態の代用にしない。予報が基準未満でも現車に雪氷があれば加算、予報が基準以上でも現車に無ければ加算しない"},
        {"label": "前日降雪（参考表示）", "value": wx["snowfall_previous_day_cm"], "unit": "cm",
         "formula": "weather_forecast_for_intake_day.snowfall_previous_day_cm（人時には使わない）"},
    ]

    unknowns = [
        "気象データの取得先・利用条件は未調査（予報値は架空）",
        "しきい値（-5℃以下／5cm以上）は仮置き",
        "下回り洗浄(PRE-WASH)は S06 の対象外のため加えていない",
    ]
    if snow_state == "未確認" or ice_state == "未確認":
        unknowns.append("雪・氷の現車確認が未確認の項目は high にだけ含めた")

    out = {
        "id": "S06",
        "name": "入庫日の気象に連動した前処理の確認",
        "base_method": "共",
        "factors": ["HK02", "HK03"],
        "algorithm": [
            "手順1: 入庫日の予報を shop_policy.weather_prompt_threshold と比べ、どちらか満たせば前処理の確認を促す表示を出す",
            "手順2: 気象からは人時を決めない。入庫時の現車確認（雪の状態、ホイールハウスの氷の箇所数）で決める",
            "手順3: 雪下ろし＝入庫1回分、氷塊除去＝箇所数×単価。未確認は high のみに含める",
            "手順4: 重複控除後の基準1.7人時に low/typical/high の前処理を加える",
            "手順5: 融解待ち（U5）は氷塊除去を含む low/typical/high それぞれの経過時間にだけ足す。請求対象は雪下ろし・氷塊除去",
        ],
        "inputs": inputs,
        "intermediates": inter,
        "result": {
            "labor_hours": {lv: r2(lab[lv]) for lv in levels},
            "elapsed_hours": {lv: r2(elapsed[lv]) for lv in levels},
            "other_outputs": [
                {"label": "気象による確認促し表示", "value": prompt_msg, "unit": ""},
                {"label": "請求対象の前処理人時（typical）", "value": r2(billed_typ), "unit": "人時"},
            ],
            "note": "前処理の人時は現車確認で決め、気象は確認を促すためだけに使う。",
        },
        "assumptions": [
            "仮定: 予報値は架空で、取得先は未調査",
            "仮定: 閾値 -5℃以下／降雪5cm以上は仮置き",
            "仮定: 融解待ちは氷塊除去を含む水準（low/typical/high）の経過時間にそれぞれ足す（待機は作業者を拘束しない）",
            "仮定: 経過時間は人時の合計を直列に並べ、融解待ちを足したもの",
        ],
        "unknowns": unknowns,
    }

    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "S06.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
