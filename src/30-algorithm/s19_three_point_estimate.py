#!/usr/bin/env python3
"""S19 3点見積もり（少ない・標準・多い）

反映する要因: AG01（締結部の固着・折れ込み）, AG02（外したときに付随部品が壊れる）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. 観察を数える。
      ブラケットボルト 重(頭部腐食)2本・中2本、スライドボルト 未確認4本、
      ローター固着 未確認、スライドピンブーツ 左=硬化・右=未確認。
 3. 3つの前提（シナリオ）を観察から具体的に定義する。
      少ない「固着は重のみ軽微」: SPEC U3 の low 列。重(頭部腐食)2本だけ FX-SEIZE を low 単価で入れる。
                            中・未確認・ローターは問題なし。折れ込みなし。
                            観察済みの左ブーツ硬化は前提によらず交換(AG-BOOT 片側1)。
      標準  「一部固着」  : 観察で問題のあるものだけが対応を要する。
                            ブラケット 重2本+中2本=4本に固着対応(FX-SEIZE)。
                            折れ込みなし。未確認(スライド4本・ローター・右ブーツ)は問題なし。
                            硬化を観察した左ブーツは交換(AG-BOOT 片側1)。
      多い  「固着が多く、ボルト折れあり」(SPEC U3 の high に合わせる):
                            ブラケット重2本は固着対応+折れ込み抜き取り+ねじ山修正(FX-SEIZE/FX-BROKEN/FX-THREAD 各2)、
                            中2本は固着対応、未確認のスライド4本も固着対応(FX-SEIZE)、
                            ローター固着除去は左右(FX-ROTOR 2側)、ブーツは左右交換(AG-BOOT 2側)。
 4. 各前提の追加人時 = 工程の数(本/か所/側) x 暫定単価。単価は「少ない」の FX-SEIZE は U3 の low、
    それ以外の「少ない」「標準」は typical、「多い」は U3 の high に合わせて high を使う(SPEC U2)。
    low / typical / high の人時はそれぞれ 前提「少ない」「標準」「多い」の合計とする。
 5. 人時 = 1.7 + 追加人時。作業全体への倍率は使わない。地域・年式・走行距離からは加算しない。
 6. 各前提について、単価を low / high に振った場合の幅も参考に出す(other_outputs)。
 7. 浸透待ち(penetrant_soak_wait_hours)は固着対応を含む前提でのみ経過時間に加える。人時に入れない。
 8. 丸めずに計算し、出力時だけ小数第2位に丸める。SPEC.md の形で標準出力と results/S19.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))
r2 = lambda x: round(x + 1e-12, 2)

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
soak = SC["elapsed_waits"]["penetrant_soak_wait_hours"]
fasteners = SC["condition"]["fasteners"]


def count(prefix, rust_head):
    return sum(f.get("count", 1) for f in fasteners
               if f["id"].startswith(prefix) and f["rust"].startswith(rust_head))


n_heavy = count("F-", "重")            # ブラケット 重
n_mid = count("F-", "中")              # ブラケット 中
n_unk = count("F-", "未確認")          # スライド 未確認
n_unk_slide = sum(1 for f in fasteners if "SLD" in f["id"] and f["rust"].startswith("未確認"))
boots = SC["condition"]["slide_pin_boots"]
boot_left_obs = boots["left"].startswith("問題あり")
n_boot_obs = 1 if boot_left_obs else 0                       # 観察済みで交換が要る側
n_boot_all = sum(1 for v in boots.values() if isinstance(v, str))  # 左右

# 仮定(scenario.json に無い)。assumptions にも出す。
ASSUME = {
    "rotor_sides": 2,      # 多い: ローター固着除去の側数(左右)
}
# U3 high: 重は 固着対応 + 折れ込み抜き取り + ねじ山修正 を重の全本数に当てる。
RATE_OF = {"少ない": "typical", "標準": "typical", "多い": "high"}
RATE_OVERRIDE = {"少ない": {"FX-SEIZE": "low"}}  # U3: 重の low 列は FX-SEIZE low

# 前提ごとの追加工程の数 {op: 数量}
SCEN = {
    "少ない": {"title": "固着は重のみ軽微", "ops": {
        "FX-SEIZE": n_heavy,
        "AG-BOOT": n_boot_obs,
    }},
    "標準": {"title": "一部固着", "ops": {
        "FX-SEIZE": n_heavy + n_mid,
        "AG-BOOT": n_boot_obs,
    }},
    "多い": {"title": "固着が多く、ボルト折れあり", "ops": {
        "FX-SEIZE": n_heavy + n_mid + n_unk_slide,
        "FX-BROKEN": n_heavy,
        "FX-THREAD": n_heavy,
        "FX-ROTOR": ASSUME["rotor_sides"],
        "AG-BOOT": n_boot_all,
    }},
}
ORDER = ["少ない", "標準", "多い"]
RANGES = {"少ない": "low", "標準": "typical", "多い": "high"}


def add_hours(qty, rate, ov=None):
    ov = ov or {}
    return sum(q * ops[op][ov.get(op, rate)] for op, q in qty.items())


res = {}
for s in ORDER:
    q = SCEN[s]["ops"]
    a = add_hours(q, RATE_OF[s], RATE_OVERRIDE.get(s))
    res[s] = {
        "add": a, "labor": base + a,
        "add_low": add_hours(q, "low"), "add_high": add_hours(q, "high"),
        "soak": soak if q.get("FX-SEIZE", 0) > 0 else 0.0,
    }
    res[s]["elapsed"] = res[s]["labor"] + res[s]["soak"]


def rate_formula(q, rate="typical", ov=None):
    ov = ov or {}
    return "+".join(f"{n}x{ops[op][ov.get(op, rate)]:.2f}" for op, n in q.items() if n) or "0"


def desc(q):
    return "・".join(f"{op}x{n}" for op, n in q.items() if n) or "追加なし"


inter = [
    {"label": "前提「少ない：固着は重のみ軽微」の追加工程", "value": desc(SCEN["少ない"]["ops"]), "unit": "",
     "formula": f"U3 の low 列: 重{n_heavy}本に FX-SEIZE low({ops['FX-SEIZE']['low']})。中・未確認は0。観察済みの左ブーツ交換{n_boot_obs}側"},
    {"label": "前提「標準：一部固着」の固着本数", "value": SCEN["標準"]["ops"]["FX-SEIZE"], "unit": "本",
     "formula": f"ブラケット重{n_heavy}本 + 中{n_mid}本。折れ0本、スライド{n_unk_slide}本とローターは問題なしと置く。左ブーツ交換{n_boot_obs}側"},
    {"label": "前提「多い：固着が多く、ボルト折れあり」の内訳", "value": desc(SCEN["多い"]["ops"]), "unit": "",
     "formula": f"U3 high: 重{n_heavy}本は固着対応+折れ込み(FX-BROKEN)+ねじ山修正(FX-THREAD)、中{n_mid}本とスライド{n_unk_slide}本(未確認)は固着対応、ローター固着{ASSUME['rotor_sides']}側、ブーツ{n_boot_all}側。単価は high"},
    {"label": "追加人時（少ない/標準/多い）", "value": [r2(res[s]["add"]) for s in ORDER], "unit": "人時",
     "formula": "sum(工程数 x 単価)。少ない(FX-SEIZE は low)・標準は typical、多いは high。" + "、".join(f"{s}={rate_formula(SCEN[s]['ops'], RATE_OF[s], RATE_OVERRIDE.get(s))}" for s in ORDER)},
    {"label": "標準の人時", "value": r2(res["標準"]["labor"]), "unit": "人時",
     "formula": f"{base} + {r2(res['標準']['add'])}"},
    {"label": "多いの人時", "value": r2(res["多い"]["labor"]), "unit": "人時",
     "formula": f"{base} + {r2(res['多い']['add'])}"},
    {"label": "幅（多い - 少ない）", "value": r2(res["多い"]["labor"] - res["少ない"]["labor"]), "unit": "人時",
     "formula": "labor(多い) - labor(少ない)"},
    {"label": "浸透待ち（経過時間のみ）", "value": soak, "unit": "時間",
     "formula": "U5: FX-SEIZE を含む前提(少ない・標準・多い)それぞれに1回加算。人時には入れない"},
]

out = {
    "id": "S19",
    "name": "3点見積もり（少ない・標準・多い）",
    "base_method": "共",
    "factors": ["AG01", "AG02"],
    "algorithm": [
        "手順1: 基準 1.7 人時を出発点にする",
        f"手順2: 観察（ブラケット重{n_heavy}・中{n_mid}、スライド未確認{n_unk_slide}、ローター未確認、左ブーツ硬化）を数える",
        "手順3: 「固着は重のみ軽微」「一部固着」「固着が多く、ボルト折れあり」の3前提を、観察に対応づけた追加工程の数で定義。「多い」は U3 の high（重=固着対応+折れ込み+ねじ山、未確認スライド=固着対応）。観察済みの左ブーツ交換は全前提に入れる（硬化した部品は外すと壊れる付随部品として AG02 に当てる）",
        "手順4: 追加人時 = 工程数 x 暫定単価。少ないの FX-SEIZE は low、他の少ない・標準は typical、多いは high 単価。low/typical/high は3前提に対応",
        "手順5: 人時 = 1.7 + 追加人時（倍率や地域・年式からの加算はしない）",
        "手順6: 単価を low/high に振った幅を参考に併記",
        "手順7: U5 に従い、浸透待ち0.25時間を FX-SEIZE を含む前提（少ない・標準・多い）の経過時間に加算。人時には入れない",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "condition.fasteners(ブラケット重/中)", "value": {"重": n_heavy, "中": n_mid}, "status": "申告"},
        {"key": "condition.fasteners(スライド)", "value": f"未確認{n_unk_slide}本", "status": "不明"},
        {"key": "condition.rotor_hub_seizure", "value": SC["condition"]["rotor_hub_seizure"]["state"], "status": "不明"},
        {"key": "condition.slide_pin_boots", "value": SC["condition"]["slide_pin_boots"], "status": "確認済み(左)/不明(右)"},
        {"key": "mechanic_provisional_add_ops", "value": {k: ops[k]["typical"] for k in ("FX-SEIZE", "FX-BROKEN", "FX-THREAD", "FX-ROTOR", "AG-BOOT")}, "status": "仮定"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {RANGES[s]: r2(res[s]["labor"]) for s in ORDER},
        "elapsed_hours": {RANGES[s]: r2(res[s]["elapsed"]) for s in ORDER},
        "other_outputs": [
            {"label": f"前提「{s}：{SCEN[s]['title']}」の人時(単価 low〜high)",
             "value": [r2(base + res[s]["add_low"]), r2(res[s]["labor"]), r2(base + res[s]["add_high"])],
             "unit": "人時"} for s in ORDER
        ],
        "note": "low/typical/high は『前提の違い』。high は『多い』前提（U3 の high、単価も high）でのこの案の範囲での上限。標準が最頻値かは実績で確かめる。前提の内容を見積書に併記する。",
    },
    "assumptions": [
        "仮定: 「少ない」の FX-SEIZE は U3 の low、他の「少ない」「標準」は暫定値の typical、「多い」は U3 high に合わせて high を使う。単価の幅は other_outputs に別掲。",
        f"仮定: 「少ない」は U3 の low 列。重{n_heavy}本のみ FX-SEIZE low、中・未確認は0。観察済みの左ブーツ硬化は交換する（{n_boot_obs}側）。",
        "仮定: ローター固着（FX-ROTOR）は締結部ではないため U3 の表にない。U2 の『範囲内の未確認項目の上限』として「多い」にだけ左右2側を入れる（側数2は script 内の仮定）。",
        "仮定: 左ブーツ硬化の交換は、硬化したゴム部品は外すと壊れる付随部品とみなして AG02 に当てる（AG03 の観察でもあるが S19 の範囲は AG02）。右ブーツ（未確認）は U2 に沿い「多い」にだけ入れる。",
        f"仮定: 「標準」では観察した重・中のブラケット{n_heavy + n_mid}本が固着対応を要し、折れはなし。未確認は問題なしではなく『この前提では起きない』と置く。",
        f"仮定: 「多い」は U3 の high。重{n_heavy}本は固着対応に加え折れ込み（抜き取り{n_heavy}本+ねじ山修正{n_heavy}か所）、中{n_mid}本とスライド{n_unk_slide}本(未確認)は固着対応、ローター固着は{ASSUME['rotor_sides']}側。",
        f"仮定: 付随部品(AG02)は硬化を観察した左ブーツを全前提で、左右ブーツ{n_boot_all}側を多いで交換。",
        "仮定: 雪下ろし・氷塊・ハブ錆・ホース等は S19 の対象外で含めない。",
    ],
    "unknowns": [
        f"スライドボルト{n_unk_slide}本・ローター固着・右ブーツは未確認。標準には入れず、多いの前提にだけ入れた。",
        "サブフレームは未確認で J1・J2 では外さないため作業範囲外（U4）。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る。",
        "標準が実際の最頻値かは実績がなく不明。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
print(text)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S19.json").write_text(text + "\n", encoding="utf-8")
