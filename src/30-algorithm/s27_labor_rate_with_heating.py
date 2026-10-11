#!/usr/bin/env python3
"""S27 暖房費等を配賦する時間単価計算機

アルゴリズムの手順:
1. scenario.json の base_totals.deduplicated_base（1.7人時）を読む。S27 は工数を算出しない案なので、
   工数は変えず 1.7 のまま据え置く（暖房費・家賃等を人時に足さない）。
2. cost_data_S27 から年間総コスト = 人件費 + 家賃 + 暖房費 + 設備費 + 目標利益 を求める。
3. 【年間配賦】年間総コスト / 年間請求人時 = 年間配賦の時間単価（円/人時）。暖房費も年間で薄く広げる。
4. 【冬季配賦】暖房費を冬季分（heating_winter_months_yen）と残り（年間暖房費 - 冬季分）に分ける。
   暖房以外の経費と残りの暖房費は年間請求人時で配賦し、冬季分の暖房費は冬季請求人時だけで配賦する。
   冬季単価 = 暖房以外の単価 + 残り暖房費の単価 + 冬季暖房費 / 冬季請求人時。
   非冬季単価 = 暖房以外の単価 + 残り暖房費の単価。
5. 検算: 冬季・非冬季の単価を請求人時で加重平均すると年間単価に一致することを確かめる。
6. 参考として 1.7人時 x 各単価の工賃（円）を other_outputs に出す。
   季節別単価は選択肢として示すだけで、採用は工場の経営判断（ヒアリングに「冬だから値段を上げてはいない」の発言あり）。
7. 結果を標準出力と results/S27.json に出す。人時は丸めずに計算し、出力時のみ小数第2位に丸める。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sc = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

base = sc["base_totals"]["deduplicated_base"]
c = sc["cost_data_S27"]

# docs §4.6 S27 の母体は 人件費・家賃・暖房費・設備費・目標利益。暖房以外の光熱費は含めない（docs を正とする）。
total_cost = (c["labor_cost_yen"] + c["rent_yen"] + c["heating_yen"] + c["equipment_yen"]
              + c["target_profit_yen"])
annual_h, winter_h, non_winter_h = c["annual_billable_hours"], c["winter_billable_hours"], c["non_winter_billable_hours"]

annual_rate = total_cost / annual_h
heating_winter = c["heating_winter_months_yen"]
heating_rest = c["heating_yen"] - heating_winter
non_heating_rate = (total_cost - c["heating_yen"]) / annual_h
rest_rate = heating_rest / annual_h
winter_heating_rate = heating_winter / winter_h
non_winter_rate = non_heating_rate + rest_rate
winter_rate = non_winter_rate + winter_heating_rate
check = (winter_rate * winter_h + non_winter_rate * non_winter_h) / annual_h
heating_per_h = c["heating_yen"] / annual_h

r2 = lambda x: round(x, 2)
r0 = lambda x: round(x)

result = {
    "id": "S27",
    "name": "暖房費等を配賦する時間単価計算機",
    "base_method": "共",
    "factors": ["HK08"],
    "algorithm": [
        "手順1: 重複控除後の基準 1.7 人時を据え置く（金額の案なので工数は変えない）",
        "手順2: 人件費・家賃・暖房費・設備費・目標利益を合計して年間総コストを出す",
        "手順3: 年間総コスト / 年間請求人時 = 年間配賦の時間単価",
        "手順4: 暖房費を冬季分と残りに分け、冬季分だけ冬季請求人時で配賦して冬季/非冬季の単価を出す",
        "手順5: 冬季・非冬季の加重平均が年間単価に一致するか検算する",
        "手順6: 参考として 1.7 人時 x 各単価の工賃を出す（暖房費は人時に足さない）",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "cost_data_S27.heating_yen", "value": c["heating_yen"], "status": "申告"},
        {"key": "cost_data_S27.heating_winter_months_yen", "value": heating_winter, "status": "申告"},
        {"key": "cost_data_S27.annual_billable_hours", "value": annual_h, "status": "申告"},
        {"key": "cost_data_S27.winter_billable_hours", "value": winter_h, "status": "申告"},
        {"key": "cost_data_S27.target_profit_yen", "value": c["target_profit_yen"], "status": "仮定"},
    ],
    "intermediates": [
        {"label": "年間総コスト", "value": total_cost, "unit": "円",
         "formula": "人件費+家賃+暖房費+設備費+目標利益"},
        {"label": "年間配賦の時間単価", "value": r2(annual_rate), "unit": "円/人時",
         "formula": "年間総コスト / 年間請求人時"},
        {"label": "うち暖房費の寄与（年間配賦）", "value": r2(heating_per_h), "unit": "円/人時",
         "formula": "暖房費 / 年間請求人時"},
        {"label": "暖房以外の経費の単価", "value": r2(non_heating_rate), "unit": "円/人時",
         "formula": "(年間総コスト-暖房費) / 年間請求人時"},
        {"label": "冬季だけ配賦する暖房費の単価", "value": r2(winter_heating_rate), "unit": "円/人時",
         "formula": "冬季暖房費 / 冬季請求人時"},
        {"label": "冬季の時間単価", "value": r2(winter_rate), "unit": "円/人時",
         "formula": "暖房以外の単価 + 残り暖房費/年間請求人時 + 冬季暖房費/冬季請求人時"},
        {"label": "非冬季の時間単価", "value": r2(non_winter_rate), "unit": "円/人時",
         "formula": "暖房以外の単価 + 残り暖房費/年間請求人時"},
        {"label": "加重平均の検算", "value": r2(check), "unit": "円/人時",
         "formula": "(冬季単価x冬季人時 + 非冬季単価x非冬季人時) / 年間請求人時（年間単価と一致）"},
    ],
    "result": {
        "labor_hours": {"low": base, "typical": base, "high": base},
        "elapsed_hours": None,
        "other_outputs": [
            {"label": "時間単価（年間配賦）", "value": r0(annual_rate), "unit": "円/人時"},
            {"label": "時間単価（冬季）", "value": r0(winter_rate), "unit": "円/人時"},
            {"label": "時間単価（非冬季）", "value": r0(non_winter_rate), "unit": "円/人時"},
            {"label": "参考工賃（1.7人時 x 年間配賦単価）", "value": r0(base * annual_rate), "unit": "円"},
            {"label": "参考工賃（1.7人時 x 冬季単価）", "value": r0(base * winter_rate), "unit": "円"},
            {"label": "参考工賃（1.7人時 x 非冬季単価）", "value": r0(base * non_winter_rate), "unit": "円"},
        ],
        "note": "工数は変えない。暖房費は人時ではなく時間単価の側で扱うため、基準 1.7 人時を据え置く。"
                "季節別単価は選択肢として示すだけで、採用は工場の経営判断。",
    },
    "assumptions": [
        "仮定: 年間暖房費のうち冬季分を除いた残り（heating_yen - heating_winter_months_yen）は年間請求人時で配賦する",
        "仮定: 目標利益 3,000,000 円は金額の仮定（実際の目標は工場の経営判断。総コストと全単価に影響する）",
        "仮定: 暖房費の冬季分（heating_winter_months_yen）と残りの分割は申告値に基づく。分割規則は docs に未記載で、工場への確認が必要",
        "除外: 暖房以外の光熱費（utilities_excl_heating_yen）は docs の母体に挙がっていないため総コストに含めない",
        "仮定: 暖房以外の経費と目標利益は季節にかかわらず年間請求人時で均等に配賦する",
        "仮定: 金額はすべて架空値（scenario.json の cost_data_S27）",
    ],
    "unknowns": [
        "経費の開示範囲と、冬季単価を実際の請求に使うかは工場に確認が必要",
        "目標利益の金額と、暖房以外の光熱費を母体に含めるか（docs 追記の要否）は未確認",
        "請求人時の見込み（年間・冬季）は実績で変わる",
    ],
}

out = json.dumps(result, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S27.json").write_text(out + "\n", encoding="utf-8")
print(out)
