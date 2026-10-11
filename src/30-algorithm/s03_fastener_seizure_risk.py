#!/usr/bin/env python3
"""S03 締結部ごとの固着リスク表

反映する要因: HK01（融雪剤による腐食）, AG01（締結部の固着・折れ込み）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. condition.fasteners を1本ずつ（count があればその本数分）取り出す。
 3. fastener_risk_rule で各締結部のリスクを判定する。
      軽 -> 通常 / 中 -> 固着対応の可能性 / 重 -> 折れ込みの可能性 / 未確認 -> 不明
 4. リスク区分ごとの本数を数える（通常 / 固着対応の可能性 / 折れ込みの可能性 / 不明）。
 5. SPEC U3 の表で、区分ごとに low / typical / high を決める。
      軽  : 0 / 0 / 0
      中  : 0 / FX-SEIZE typical / FX-SEIZE high
      重  : FX-SEIZE low / FX-SEIZE typical / FX-SEIZE high + FX-BROKEN high + FX-THREAD high
      未確認: 0 / 0 / FX-SEIZE high
      折れ込みは固着対応のあとの別工程なので二重計上ではない。
 6. 区分ごとに 本数 x 単価 を積み上げ、low / typical / high の追加人時を得る。
    作業全体への倍率は使わない。地域・年式・走行距離からは加算しない。
 7. 労力 = 1.7 + 追加人時。丸めずに計算し、出力時だけ小数第2位に丸める。
 8. U5: FX-SEIZE を含む範囲（low/typical/high それぞれ）の経過時間に、浸透待ち
    （penetrant_soak_wait_hours）を足す。人時には入れない。他の待機は S03 の対象外。
 9. SPEC.md の形で JSON を標準出力と results/S03.json に出す。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
rule = SC["condition"]["fastener_risk_rule"]
RANGES = ("low", "typical", "high")

# --- 手順2-4: 締結部ごとのリスク判定 ---
def rust_key(text):
    for k in ("未確認", "重", "中", "軽"):
        if text.startswith(k):
            return k
    return "未確認"

CLASS = {"通常": [], "固着対応の可能性": [], "折れ込みの可能性": [], "不明": []}
table = []
for f in SC["condition"]["fasteners"]:
    n = f.get("count", 1)
    cls = rule[rust_key(f["rust"])]
    key = {"通常": "通常", "固着対応の可能性": "固着対応の可能性",
           "折れ込みの可能性": "折れ込みの可能性"}.get(cls, "不明")
    CLASS[key].append((f["id"], n))
    table.append({"id": f["id"], "rust": f["rust"], "risk": cls, "count": n})
cnt = {k: sum(n for _, n in v) for k, v in CLASS.items()}

# --- 手順5-6: 区分ごとの人時（SPEC U3 の表） ---
def per(op, r):
    return ops[op][r]

# U3: 中 = 0 / typ / high、重 = low / typ / high、未確認 = high のみ
add = {}
detail = {}
for r in RANGES:
    mid = cnt["固着対応の可能性"] * per("FX-SEIZE", r) if r != "low" else 0.0
    heavy_seize = cnt["折れ込みの可能性"] * per("FX-SEIZE", r)
    broken = thread = unk = 0.0
    if r == "high":
        # 折れ込みは固着対応のあとに起きる別工程（二重計上ではない）。折れ込み1本につきねじ山1か所と仮定
        broken = cnt["折れ込みの可能性"] * per("FX-BROKEN", r)
        thread = cnt["折れ込みの可能性"] * per("FX-THREAD", r)
        unk = cnt["不明"] * per("FX-SEIZE", r)
    detail[r] = {"seize": mid + heavy_seize + unk, "broken": broken, "thread": thread}
    add[r] = mid + heavy_seize + broken + thread + unk

labor = {r: base + add[r] for r in RANGES}

# --- 手順8: 経過時間（U5: FX-SEIZE を含む範囲それぞれに浸透待ちを足す） ---
soak = SC["elapsed_waits"]["penetrant_soak_wait_hours"]
elapsed = {r: labor[r] + (soak if detail[r]["seize"] > 0 else 0.0) for r in RANGES}

def desc(key):
    return "、".join(f"{i} {n}本" for i, n in CLASS[key]) or "なし"
add_v = {r: r2(add[r]) for r in RANGES}

inter = [
    {"label": "リスク区分別本数（通常/固着対応/折れ込み/不明）",
     "value": cnt, "unit": "本",
     "formula": f"rule で判定: 軽->通常（{desc('通常')}）、中->固着対応の可能性（{desc('固着対応の可能性')}）、重->折れ込みの可能性（{desc('折れ込みの可能性')}）、未確認->不明（{desc('不明')}）"},
    {"label": "固着対応(FX-SEIZE)の人時（low/typical/high）",
     "value": {r: r2(detail[r]["seize"]) for r in RANGES}, "unit": "人時",
     "formula": "U3: 中本数 x FX-SEIZE（lowは0、typical・high）+ 重本数 x FX-SEIZE（low・typical・high）+ 未確認本数 x FX-SEIZE high（highのみ）"},
    {"label": "FX-BROKEN の人時（high のみ）", "value": r2(detail["high"]["broken"]), "unit": "人時",
     "formula": f"{cnt['折れ込みの可能性']}本 x {per('FX-BROKEN','high')}"},
    {"label": "FX-THREAD の人時（high のみ）", "value": r2(detail["high"]["thread"]), "unit": "人時",
     "formula": f"{cnt['折れ込みの可能性']}か所（折れ込み1本につき1か所） x {per('FX-THREAD','high')}"},
    {"label": "追加人時合計（low/typical/high）", "value": add_v, "unit": "人時",
     "formula": "FX-SEIZE + FX-BROKEN + FX-THREAD"},
    {"label": "浸透待ち（経過時間のみ）", "value": {r: (soak if detail[r]["seize"] > 0 else 0.0) for r in RANGES}, "unit": "時間",
     "formula": "U5: その範囲に FX-SEIZE を含めたら penetrant_soak_wait_hours を足す（人時に入れない）"},
]

out = {
    "id": "S03",
    "name": "締結部ごとの固着リスク表",
    "base_method": "A/C",  # スクリプト内の分類ラベル（scenario 側に対応記載なし）
    "factors": ["HK01", "AG01"],
    "algorithm": [
        f"手順1: 基準 {base} 人時を出発点にする",
        "手順2: condition.fasteners を1本ずつ列挙（ホイールナットは count 分）",
        "手順3: fastener_risk_rule で 通常/固着対応の可能性/折れ込みの可能性/不明 に判定",
        "手順4: 区分ごとの本数を数える",
        "手順5: SPEC U3 の表で当てる（中: 0/typ/high、重: low/typ/high＋high のみ折れ込み・ねじ山、未確認: high のみ FX-SEIZE）",
        "手順6: 本数 x 単価を積み上げて追加人時（作業全体の倍率は使わない）",
        f"手順7: 人時 = {base} + 追加人時",
        "手順8: FX-SEIZE を含む範囲の経過時間にだけ浸透待ちを足す（U5）",
    ],
    "inputs": [
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": "condition.fasteners", "value": table, "status": "申告"},
        {"key": "condition.fastener_risk_rule", "value": rule, "status": "仮定"},
        {"key": "mechanic_provisional_add_ops.FX-SEIZE/FX-BROKEN/FX-THREAD",
         "value": {k: {r: ops[k][r] for r in RANGES} for k in ("FX-SEIZE", "FX-BROKEN", "FX-THREAD")},
         "status": "仮定"},
        {"key": "elapsed_waits.penetrant_soak_wait_hours", "value": soak, "status": "仮定"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "リスク区分別本数", "value": cnt, "unit": "本"},
        ],
        "note": "この案の範囲での上限を high とする。SPEC U3 の表どおり、中は low 0・typical/high で FX-SEIZE、重は全範囲で FX-SEIZE（high のみ FX-BROKEN と FX-THREAD を上乗せ）、未確認は high のみ FX-SEIZE。経過時間は人時 + 浸透待ち（FX-SEIZE を含む範囲ごと）。",
    },
    "assumptions": [
        "仮定: SPEC.md 解釈の統一 U3 の表に従う（中: 0/typical/high、重: low/typical/high＋折れ込み＋ねじ山、未確認: high のみ）。",
        "仮定: 折れ込みは固着対応のあとの別工程であり二重計上ではない。折れ込み1本につきねじ山修正1か所。",
        "仮定: 浸透待ちは U5 に従い、FX-SEIZE を含む low/typical/high それぞれの経過時間に1回足す。",
        "仮定: 地域・年式・走行距離・前回実績からは加算しない。他案の要因（雪下ろし・氷塊・ローター固着等）は含めない。",
    ],
    "unknowns": [
        "スライドボルト4本は錆が未確認（ブーツに隠れる）。low・typical には入れず、high にのみ FX-SEIZE を含めた。",
        "分解前のため、折れ込みの実際の発生は不明。折れ込みボルトの抜き取り・ねじ山修正は high のみに入れており、typical には含まない。",
        "サブフレームの腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る（U4。high には入れない）。",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
(HERE / "results").mkdir(exist_ok=True)
(HERE / "results" / "S03.json").write_text(text + "\n", encoding="utf-8")
print(text)
