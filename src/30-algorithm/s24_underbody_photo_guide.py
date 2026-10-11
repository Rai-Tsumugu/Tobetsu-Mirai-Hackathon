#!/usr/bin/env python3
"""S24 下回り撮影ガイド

反映する要因: HK01（融雪剤による腐食）, HK07（防錆コートの見えにくさ）, AG04（腐食による穴あき・作業範囲の拡大の見落とし防止）

設計書（system-ideas-30.md §4.5 S24）では、S24 は入力支援であり、撮影位置と枚数の案内と、
撮影漏れの「未確認」表示だけを行う。typical・low は 1.7 のまま（撮影案内は人時を足さない）。
SPEC 第2版 U2 の例外（S24 は未確認を上限の幅に反映する）により、撮影漏れの部位だけに
暫定値（mechanic_provisional_add_ops の high）を当てて high に入れる:
右スライドピンブーツ（泥と氷で撮影不可）→ AG-BOOT high。
サブフレーム前部は U4 により作業範囲外（J1・J2 では外さない）のため high に入れず unknowns に残す。
固着対応（スライドボルト等）・ローター／ハブ処置は撮影漏れではなく S03・S22 等の領域のため扱わない。

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. photo_guide_S24 の「必要撮影」と「撮影済み」を照合し、撮影率と未撮影部位を出す。
 3. 撮影位置ごとに案内（位置・枚数・目的）を出す。未撮影は「未確認として残す」。
 4. 撮影済み部位から確認できる対象と、撮影しても確認できない対象（ブーツに隠れたスライドボルト、
    分解前のローター・ハブ固着）を分けて記録する。未確認は 0 と確定せず unknowns に残す。
 5. 防錆コート施工歴（HK07, 申告）がある場合、コート下の確認を確認項目として出す（工数は足さない）。
 6. low = typical = 基準 1.7。high = 1.7 + 撮影漏れ部位の暫定値（右ブーツ AG-BOOT high、U2 の例外）。
    サブフレーム前部は U4 で high に入れない。地域・年式・走行距離からは加算しない。
 7. 待機（U5）は FX-SEIZE・FX-HUBCLEAN・氷塊除去を含めないため足さない。経過時間は扱わない（null）。
 8. SPEC.md の形で JSON を標準出力と results/S24.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
R = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
g = SC["photo_guide_S24"]
cond = SC["condition"]
soak = SC["elapsed_waits"]["penetrant_soak_wait_hours"]

# --- 手順2: 撮影照合 ---
required, taken = g["required_shots_for_J2"], set(g["taken"])
missing = [s for s in required if s not in taken]
rate = len(taken & set(required)) / len(required)

# --- 手順4: 撮影で確認できる対象と、撮影しても確認できない対象 ---
BRK_SHOT = {"左ブラケット": "左ブラケットボルト2本", "右ブラケット": "右ブラケットボルト2本"}
observable = [v for k, v in BRK_SHOT.items() if k in taken]
observable += [f"{n}スライドピンブーツ" for n in ("左", "右") if f"{n}スライドピンブーツ" in taken]
observable += [f"{n}ハブ当たり面の錆" for n in ("左", "右") if f"{n}ハブ" in taken]
observable += ["左ローター裏面の錆（外観のみ）"] if "左ローター裏" in taken else []
observable += ["サブフレーム前部の腐食"] if "サブフレーム前部" in taken else []
slide_bolts = [f["id"] for f in cond["fasteners"] if "SLD" in f["id"] and f["rust"].startswith("未確認")]
not_judgeable = []
if slide_bolts:
    not_judgeable.append(f"スライドボルト{len(slide_bolts)}本（ブーツに隠れる）")
if cond["rotor_hub_seizure"]["state"] == "未確認":
    not_judgeable.append("ローター・ハブの固着（分解前は外観から判断できない）")

# --- 手順6: 撮影漏れの未確認だけを high に入れる（U2 の例外）。サブフレーム前部は U4 で対象外 ---
MISSED_TO_OP = {"右スライドピンブーツ": "AG-BOOT"}
high_ops = [(s, MISSED_TO_OP[s]) for s in missing if s in MISSED_TO_OP]
high_add = sum(ops[op]["high"] for _, op in high_ops)
labor = {"low": base, "typical": base, "high": base + high_add}

# 撮影位置ごとの案内（枚数は scenario に規定がないため、各位置の最低1枚と仮定）
PURPOSE = {"左ブラケット": "左ブラケットボルト2本の頭部腐食", "右ブラケット": "右ブラケットボルト2本の腐食",
           "左ハブ": "左ハブ当たり面の錆", "右ハブ": "右ハブ当たり面の錆",
           "左スライドピンブーツ": "左ブーツの硬化・亀裂", "右スライドピンブーツ": "右ブーツの硬化・亀裂",
           "サブフレーム前部": "サブフレーム前部の腐食", "左ローター裏": "ローター裏面の錆・固着の兆候"}
guide = [{"position": s, "shots": 1, "purpose": PURPOSE.get(s, ""),
          "status": "撮影済み" if s in taken else "未確認として残す（" + g["missing_reason"].get(s, "理由未記録") + "）"}
         for s in required]

# --- 手順5: 防錆コート ---
coat = cond["rustproof_undercoat"]
coat_note = f"防錆コート{('あり' if coat['value'] else 'なし')}（{coat['status']}）"
hub_taken = [s for s in ("左ハブ", "右ハブ") if s in taken]

inter = [
    {"label": "撮影率", "value": r2(rate), "unit": "割合",
     "formula": f"撮影済み{len(taken & set(required))} / 必要{len(required)}"},
    {"label": "未撮影部位", "value": missing, "unit": "部位", "formula": "必要撮影 - 撮影済み"},
    {"label": "撮影で状態を確認できる対象", "value": observable, "unit": "対象",
     "formula": "撮影済み部位に対応する対象（人時は足さない）"},
    {"label": "撮影しても確認できない対象", "value": not_judgeable, "unit": "対象",
     "formula": "scenario で rust=未確認 のスライドボルト、rotor_hub_seizure=未確認"},
    {"label": "high に入れる撮影漏れの暫定人時", "value": r2(high_add), "unit": "人時",
     "formula": "撮影漏れ部位のうち作業(op)がある部位の暫定 high 合計 = " +
                (" + ".join(f"{s}:{op} high {ops[op]['high']}" for s, op in high_ops) or "なし")},
    {"label": "人時(low/typical/high)", "value": {r: r2(labor[r]) for r in R}, "unit": "人時",
     "formula": f"low = typical = 基準 {base}、high = 基準 {base} + {r2(high_add)}"},
]

out = {
    "id": "S24",
    "name": "下回り撮影ガイド",
    "base_method": "A",
    "factors": ["HK01", "HK07", "AG04"],
    "algorithm": [
        "手順1: 基準 1.7 人時を出発点にする",
        "手順2: 必要撮影と撮影済みを照合し、撮影率と未撮影部位を出す",
        "手順3: 撮影位置ごとの案内（位置・枚数・目的）を出し、未撮影は「未確認として残す」",
        "手順4: 撮影で確認できる対象と、撮影しても確認できない対象を分けて記録する",
        "手順5: 防錆コート上からの見えにくさを確認項目に出す（工数は足さない）",
        "手順6: low・typical は基準 1.7。high は撮影漏れの未確認（右スライドピンブーツ）に AG-BOOT high を足す（U2 の例外）。サブフレーム前部は U4 により high に入れない",
    ],
    "inputs": [
        {"key": "photo_guide_S24.required_shots_for_J2", "value": required, "status": "確認済み"},
        {"key": "photo_guide_S24.taken", "value": sorted(taken), "status": "確認済み"},
        {"key": "photo_guide_S24.missing_reason", "value": g["missing_reason"], "status": "確認済み"},
        {"key": "condition.rustproof_undercoat", "value": coat["value"], "status": coat["status"]},
        {"key": "condition.underbody_rust_grade.subframe", "value": None, "status": "不明"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in R},
        "elapsed_hours": None,
        "other_outputs": [
            {"label": "撮影率", "value": r2(rate), "unit": "割合"},
            {"label": "未撮影部位", "value": missing, "unit": "部位"},
            {"label": "確認項目", "value": f"防錆コートの上からは腐食が見えにくい可能性（HK07、仮説）。{coat_note}。撮影済み部位{hub_taken}もコート下の状態を触診・除去して確認する", "unit": "文"},
            {"label": "撮影ガイド(位置と枚数)", "value": guide, "unit": "位置別"},
            {"label": "撮影の再依頼", "value": ["右スライドピンブーツ（泥と氷の除去後）", "サブフレーム前部（リフトアップ・カバー取り外しが可能か確認）"], "unit": "部位"},
            {"label": "他案への入力", "value": "撮影率と未撮影部位を S02・S23・S29 に渡す", "unit": "文"},
        ],
        "note": "typical・low は 1.7 のまま。S24 は撮影位置と枚数の案内、撮影漏れの「未確認」表示、コート下の確認項目を出す入力支援で、typical には人時を足さない。SPEC 第2版 U2 の例外により、撮影漏れの未確認だけを上限の幅に反映し、右スライドピンブーツ（泥と氷で撮影不可）に AG-BOOT high 0.2 を足して high=1.9 とした。high はこの案の範囲での上限。サブフレーム前部は U4（J1・J2 では外さない作業範囲外）により high に入れず unknowns に記録する。ブーツに隠れたスライドボルトの固着対応・ローター／ハブ処置は撮影漏れではなく他案（S03・S21・S22 等）の領域のため加えない。",
    },
    "assumptions": [
        "仮定: 右スライドピンブーツの暫定人時は AG-BOOT（片側）の high を、撮影漏れの未確認の上限として当てた（整備士の暫定値）。",
        "仮定: 撮影枚数は scenario に規定がないため、各位置とも最低1枚とした。",
        "仮定: 左ローター裏は撮影済みで外観の錆・兆候は観察できるが、固着の有無は分解前に判断できないため、固着は未確認として扱う。",
        "仮定: スライドボルトは左右ともブーツに隠れて rust 未確認のため、撮影の有無にかかわらず確認できない対象とした。",
    ],
    "unknowns": [
        "右スライドピンブーツ: 泥と氷で撮影不可。状態不明（未確認）。撮影漏れのため AG-BOOT high を high に入れた（U2 の例外）",
        "スライドボルト4本: ブーツに隠れて未確認",
        "サブフレーム前部: アンダーカバーで見えず未撮影（未確認、AG04 の穴あき見落としに関わる）。U4: J1・J2 では外さない作業範囲外のため high に入れない。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る。0 の確定ではなく、撮影の再依頼で解消する",
        "防錆アンダーコート（申告）の上から腐食が見えにくい可能性があり、撮影済みの腐食グレードが過小の可能性（HK07）",
        "ローター・ハブの固着: 撮影では判断不可（分解前）",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
res = HERE / "results"
res.mkdir(exist_ok=True)
(res / "S24.json").write_text(text + "\n", encoding="utf-8")
print(text)
