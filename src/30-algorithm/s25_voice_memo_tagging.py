#!/usr/bin/env python3
"""S25 音声入力による作業メモ

反映する要因: AG01（締結部の固着・折れ込み）, AG03（ゴム・樹脂部品の硬化）, HK01（融雪剤による腐食。分解後に判明した状態として）
役割: 本来は「文字起こしを S10 の原因タグとメモに振り分ける入力支援」。ここでは振り分け結果が人時にどう響くかを
      見るため、S11 相当の暫定値（整備士暫定値）で再見積もりも試算する。試算は参考値で、確定は整備士。
扱わない要因: 雪下ろし・氷塊除去などの前処理（音声メモに出てこないので加えない）

アルゴリズムの手順:
 1. scenario.json を自分のファイル位置から相対で読む。出発点は重複控除後の基準 1.7 人時。
 2. voice_memo_S25.text（文字起こし）を「。」で文に分け、さらに「、」で節に分ける。
 3. 文ごとに側（左/右）と部位を持ち回る。「左前」「右前」が出たらそれ以降の文はその側として扱う。
 4. キーワード規則（標準ライブラリの文字列処理と正規表現）で節を原因タグと部位に振り分ける。
      固着 + ブラケット/スライド/ボルト -> 固着対応（キャリパー締結部）。「N本」「N本とも」を本数にする
      固着 + ローター                   -> ローター固着（側ごと）
      ブーツ + 交換/硬化                -> ブーツ交換（側ごと）
      錆/サビ/腐食                      -> 状態タグ（HK01 融雪剤による腐食）。S10 のメモ用で人時は加えない
      折れ/折損                         -> ボルト折れ（今回のメモには出ない。出れば本数を数える）
      「普通に外れた」                  -> その側は問題を観察していない
      ローター固着はAG01（締結部・固着）の範囲とみなす（SPEC に明記なし。仮定として assumptions に記す）
      「見てない/未確認/見えない」      -> 未確認（0にせず unknowns へ）
      「外れた」だけの文は直前のタグの結果（折れていない）として、固着した本数の取り外し成否に使う
 5. 振り分け結果を整備士暫定値（mechanic_provisional_add_ops）の単位あたり人時に掛ける。
      low / typical / high のうち、メモで確定した分は 3 値すべてに入れる（単位あたり人時だけが幅を持つ）。
      メモに書かれていない候補:
        左ブーツの硬化は scenario で観察済み（問題あり）なので typical と high に入れる（low はメモ確定分のみ）。
        右ブラケットボルト2本（scenario で錆「中」）は U3 中の行で typical に FX-SEIZE typical、high に FX-SEIZE high。「普通に外れた」で 0 にしない。
        右ローターは scenario で未確認なので、U2 により FX-ROTOR high を high のみに入れる。
        スライドボルト4本（左右とも scenario で「未確認」）の固着対応（FX-SEIZE high）は high のみ（U3 の未確認の行）。
        折れ込み（FX-BROKEN）と FX-THREAD は仮置きしない（個別指示）。メモでは左ブラケットボルト2本とも外れており折れの記録がない。
        サブフレームは U4 により作業範囲外。人時に入れず、unknowns に「腐食があれば AG04 として見積もり変更し顧客の了承を得る」と書く。
 6. 再見積もり人時 = 1.7 + Σ（単位数 x 単位あたり人時）。地域・年式・走行距離からは加算しない。
 7. 経過時間 = 人時 + 待機（U5）。固着対応を含む low/typical/high それぞれに浸透待ち 0.25 を加える。ハブ処置・氷塊除去はメモに出ないので防錆乾燥・融解待ちは加えない。
 8. 整備士確認が必要な点（振り分け結果の誤認識、サブフレーム（U4）、左右スライドボルト、左ブーツ）を unknowns に出す。
 9. SPEC.md の形で JSON を標準出力と results/S25.json に出す。
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = json.loads((HERE / "scenario.json").read_text(encoding="utf-8"))

r2 = lambda x: round(x + 1e-12, 2)
RANGES = ("low", "typical", "high")

base = SC["base_totals"]["deduplicated_base"]
ops = SC["mechanic_provisional_add_ops"]
waits = SC["elapsed_waits"]
memo = SC["voice_memo_S25"]["text"]
cond = SC["condition"]

# --- 手順2-4: キーワード規則による振り分け ---
KANSUU = {"一": 1, "二": 2, "三": 3, "四": 4}
def count_of(s, default=1):
    m = re.search(r"([0-9０-９一二三四])本", s)
    if not m:
        return default
    c = m.group(1)
    return KANSUU.get(c, int(c.translate(str.maketrans("０１２３４５６７８９", "0123456789"))))

findings = []   # {tag, area, side, count, clause}
negatives = []  # 問題を観察していない側
unconfirmed = []
rust_tags = []  # HK01: 状態タグのみ（人時は加えない）
side = None
for sent in [s for s in memo.split("。") if s.strip()]:
    if "左" in sent and "右" not in sent:
        side = "左"
    elif "右" in sent and "左" not in sent:
        side = "右"
    for clause in [c.strip() for c in sent.split("、") if c.strip()]:
        if re.search(r"見てない|未確認|見えない|見ていない", clause):
            area = "サブフレーム" if "サブフレーム" in clause else clause
            unconfirmed.append({"area": area, "clause": clause})
        elif re.search(r"錆|サビ|さび|腐食", clause):
            rust_tags.append({"side": side, "clause": clause})
        elif re.search(r"折れ|折損", clause):
            findings.append({"tag": "ボルト折れ", "area": "キャリパー締結部", "side": side, "count": count_of(clause), "clause": clause})
        elif "固着" in clause and "ローター" in clause:
            findings.append({"tag": "ローター固着", "area": "ローター", "side": side, "count": 1, "clause": clause})
        elif "固着" in clause and re.search(r"ブラケット|スライド|ボルト", clause):
            area = "スライドボルト" if "スライド" in clause else "キャリパーブラケットボルト"
            findings.append({"tag": "固着対応", "area": area, "side": side, "count": count_of(clause, 1), "clause": clause})
        elif "ブーツ" in clause and re.search(r"交換|硬化", clause):
            bside = "右" if "右" in clause else ("左" if "左" in clause else side)
            findings.append({"tag": "ブーツ交換", "area": "スライドピンブーツ", "side": bside, "count": 1, "clause": clause})
        elif "普通に外れ" in clause:
            negatives.append({"side": side, "clause": clause})

# 「加熱で外れた」「外れた」は固着した締結部の取り外し成否（折れ込みなし）
heated = "加熱" in memo

def total(tag):
    return sum(f["count"] for f in findings if f["tag"] == tag)

n_seize = total("固着対応")
n_rotor = total("ローター固着")
n_boot = total("ブーツ交換")
n_broken = total("ボルト折れ")
boot_sides = sorted({f["side"] for f in findings if f["tag"] == "ブーツ交換"})
rotor_sides = sorted({f["side"] for f in findings if f["tag"] == "ローター固着"})

# --- 手順5: メモ以外の未確認候補（high のみ）---
# 左スライドボルト: 左側はブラケットボルトの固着だけが書かれ、スライドボルトの言及がない。シナリオでも「未確認」
# 右スライドボルトも scenario で未確認。左右とも同じ扱い（high のみ）にする
slide_unknown_ids = [f["id"] for f in cond["fasteners"] if "-SLD-" in f["id"] and f["rust"].startswith("未確認")]
slide_unknown = len(slide_unknown_ids)
# 折れ込み: メモに折れの記録がなく、左ブラケットボルト2本は外れている。FX-BROKEN は仮置きしない（メモで折れが出たときだけ数える）
# 左ブーツ: シナリオでは硬化（問題あり）と観察済み。メモに無くても観察済みの問題なので typical と high に入れる（low はメモ確定分のみ）
left_boot_pending = 1 if (cond["slide_pin_boots"]["left"].startswith("問題あり") and "左" not in boot_sides) else 0

# U3 中の行: 右ブラケットボルトは scenario で錆「中」。メモの「普通に外れた」で 0 にせず、typical に FX-SEIZE typical、high に FX-SEIZE high を入れる（low は 0）
mid_ids = [f["id"] for f in cond["fasteners"] if "-BRK-" in f["id"] and f["rust"].startswith("中")]
mid_n = len(mid_ids)
# U2 high: 右ローターは scenario で未確認。範囲内の未確認の上限として FX-ROTOR high を high のみに入れる
rotor_unknown = 1 if (cond["rotor_hub_seizure"]["state"] == "未確認" and "右" not in rotor_sides) else 0

units = {
    "FX-SEIZE": {"low": n_seize, "typical": n_seize + mid_n, "high": n_seize + mid_n + slide_unknown},
    "FX-ROTOR": {"low": n_rotor, "typical": n_rotor, "high": n_rotor + rotor_unknown},
    "AG-BOOT": {"low": n_boot, "typical": n_boot + left_boot_pending, "high": n_boot + left_boot_pending},
    "FX-BROKEN": {"low": n_broken, "typical": n_broken, "high": n_broken},
}
contrib = {op: {r: units[op][r] * ops[op][r] for r in RANGES} for op in units}
add = {r: sum(contrib[op][r] for op in contrib) for r in RANGES}
labor = {r: base + add[r] for r in RANGES}

# U5: FX-SEIZE を含む範囲ごとに浸透待ちを足す（人時には入れない）
wait_r = {r: (waits["penetrant_soak_wait_hours"] if units["FX-SEIZE"][r] > 0 else 0.0) for r in RANGES}
wait = wait_r["typical"]
elapsed = {r: labor[r] + wait_r[r] for r in RANGES}

def tri(d):
    return [r2(d[r]) for r in RANGES]

inter = [
    {"label": "振り分けた原因タグ（件数）", "value": {"固着対応": n_seize, "ローター固着": n_rotor, "ブーツ交換": n_boot, "ボルト折れ": n_broken},
     "unit": "本/側", "formula": "メモ各節のキーワード規則（固着+ブラケット等、固着+ローター、ブーツ+交換、折れ）に一致した件数。折れはメモに出ないので0（FX-BROKEN は仮置きしない）"},
    {"label": "部位と側の振り分け（行数。原因タグ件数の合計とは別）", "value": [f"{f['side']}前 {f['area']} -> {f['tag']} x{f['count']}" for f in findings],
     "unit": "", "formula": "「左前」「右前」を文をまたいで持ち回り、節のキーワードで部位を決定"},
    {"label": "固着対応の追加人時", "value": tri(contrib["FX-SEIZE"]), "unit": "人時",
     "formula": f"本数 low {n_seize}・typ {units['FX-SEIZE']['typical']}（右ブラケット錆「中」{mid_n}本を typ・high に U3）・high {units['FX-SEIZE']['high']}（左右スライド未確認{slide_unknown}本を high のみ） x FX-SEIZE {tri(ops['FX-SEIZE'])}"},
    {"label": "ローター固着の追加人時", "value": tri(contrib["FX-ROTOR"]), "unit": "人時",
     "formula": f"{'・'.join(rotor_sides)}側 {n_rotor}側（high は右ローター未確認 +{rotor_unknown}側） x FX-ROTOR {tri(ops['FX-ROTOR'])}"},
    {"label": "ブーツ交換の追加人時（メモ外の左ブーツ観察分は typical・high のみ）", "value": tri(contrib["AG-BOOT"]), "unit": "人時",
     "formula": f"{'・'.join(boot_sides)}側 {n_boot}か所（typical・high は左ブーツ観察分 +{left_boot_pending}） x AG-BOOT {tri(ops['AG-BOOT'])}"},
    {"label": "状態タグ（HK01 錆・腐食）", "value": [r["clause"] for r in rust_tags] or "メモに「錆」の記載なし", "unit": "",
     "formula": "「錆/サビ/腐食」を含む節を HK01 の状態タグとして S10 のメモに振り分ける。人時は加えない"},
    {"label": "追加人時合計", "value": tri(add), "unit": "人時", "formula": "固着対応 + ローター固着 + ブーツ交換 + ボルト折れ（メモに出なければ 0。FX-BROKEN 単位数は " + str(n_broken) + "）"},
    {"label": "浸透待ち（経過時間のみ）", "value": tri(wait_r), "unit": "時間",
     "formula": "U5: FX-SEIZE を含む low/typical/high それぞれに penetrant_soak_wait_hours を経過時間にだけ加える（ハブ処置なしなので防錆乾燥は加えない）"},
]

out = {
    "id": "S25",
    "name": "音声入力による作業メモ",
    "base_method": "共",
    "factors": ["AG01", "AG03", "HK01"],
    "algorithm": [
        f"手順1: 基準 {base} 人時を出発点にする",
        "手順2: 文字起こしを文・節に分け、「左前」「右前」の側を文をまたいで持ち回る",
        "手順3: キーワード規則で節を原因タグ（固着対応・ローター固着・ブーツ交換・ボルト折れ）と部位に振り分ける。錆・腐食は HK01 の状態タグ（人時なし）",
        "手順4: 「普通に外れた」は問題を観察していない側、「見てない」は未確認として分け、未確認は0にしない",
        "手順5: メモで確定した分は low/typical/high すべてに加える。メモにない候補のうち、観察済みの左ブーツは typical・high、未確認の左右スライドボルト4本の FX-SEIZE high は high のみに加える（U3 の未確認の行）。折れ込み（FX-BROKEN）は仮置きしない。サブフレームは U4 により作業範囲外",
        f"手順6: 再見積もり人時 = {base} + Σ（単位数 x 単位あたり人時）。地域・年式・走行距離からは加算しない",
        "手順7（U5）: 経過時間 = 人時 + 浸透待ち 0.25（固着対応を含む low/typical/high それぞれ。複数本でも1回）。1人・直列作業の前提で、workers_available による短縮は扱わない",
        "手順8: 振り分け結果、スライドボルト等の未確認、サブフレーム（U4: 範囲外、AG04 の注記）を unknowns に出す",
    ],
    "inputs": [
        {"key": "voice_memo_S25.text", "value": memo, "status": "確認済み"},
        {"key": "base_totals.deduplicated_base", "value": base, "status": "確認済み"},
        {"key": f"condition.fasteners({','.join(slide_unknown_ids)})", "value": sorted({f["rust"] for f in cond["fasteners"] if f["id"] in slide_unknown_ids}), "status": "不明"},
        {"key": "condition.slide_pin_boots.left", "value": cond["slide_pin_boots"]["left"], "status": "確認済み"},
        {"key": "memo.未確認の節", "value": [u["clause"] for u in unconfirmed], "status": "不明"},
    ],
    "intermediates": inter,
    "result": {
        "labor_hours": {r: r2(labor[r]) for r in RANGES},
        "elapsed_hours": {r: r2(elapsed[r]) for r in RANGES},
        "other_outputs": [
            {"label": "メモから振り分けた固着対応本数", "value": n_seize, "unit": "本"},
            {"label": "加熱の記載", "value": "あり" if heated else "なし", "unit": ""},
            {"label": "整備士確認待ちの振り分け行数（部位と側の行。原因タグ件数の合計 " + str(n_seize + n_rotor + n_boot + n_broken) + " とは別の数え方）", "value": len(findings), "unit": "行"},
        ],
        "note": "【参考試算】docs §4.5 の S25 の仕組みは、文字起こしを S10 の原因タグとメモに振り分けるところまで（入力支援）で、人時の算出は S11/S12 の実績表・暫定値の役割。ここの labor_hours・elapsed_hours は、振り分け結果が人時にどう響くかを見るための整備士暫定値による試算で、docs の S25 の仕組みを超える確定値ではない。メモで確定した固着対応・ローター固着・ブーツ交換と、観察済みの左ブーツ（typical・high）を反映。メモにない候補として、右ブラケットボルト2本（錆「中」、U3 で typical・high）、右ローター未確認（FX-ROTOR high を high のみ）、左右スライドボルト4本の固着対応（high のみ）を加えた。これらは音声メモの振り分けではなく scenario の観察値による参考試算（U1 の振り分け範囲外の拡張）。左ブラケットの折れ込み（FX-BROKEN・FX-THREAD）は、メモに折れの記録がなく、整備士の個別指示により仮置きしていない（U3 重の行との差は assumptions 参照）。サブフレームは U4 により作業範囲外で、どの値にも入れていない。振り分けは提案で、確定は整備士。",
    },
    "assumptions": [
        "仮定: キーワード規則は今回の文字起こし1件向けの簡易版。実際の音声認識の誤変換や方言は未検証",
        "仮定: 「左前」「右前」は次に側が出るまで後続の文にも適用する",
        "仮定: 「1本は加熱で外れた、もう1本も外れた」は固着した2本とも折れずに外れたことを表すと解釈した",
        "仮定: ローター固着は AG01（締結部・固着）の範囲とみなした（SPEC に明記なし）",
        "仮定: 右ブラケットボルト2本は scenario で錆「中」。U3 中の行どおり typical・high に FX-SEIZE を入れ、メモの「普通に外れた」では打ち消さない（実績として優先するかは整備士判断）",
        "仮定: 右ローターは scenario で未確認。「普通に外れた」をローターの観察とはみなさず、U2 に従い FX-ROTOR high を high のみに入れる",
        "仮定: 左ブラケットは scenario で錆「重」だが、メモに折れの記録がなく2本とも外れているため、U3 重の行の FX-BROKEN high・FX-THREAD high は個別指示により仮置きしない（折れが出れば本数を数える。FX-THREAD は折れ込み本数と同じ単位で足す想定）",
        "仮定（U1）: 左ブーツ・右ブラケット・右ローター・スライドボルトの加算は音声メモに無く scenario の観察値による。S25 の仕組み（振り分け）の外で、整備士暫定値を使う参考試算に限る",
        "仮定: 折れ込み（FX-BROKEN）は仮置きしない。メモでは左ブラケットボルト2本とも外れ、折れの記録がない。scenario の fastener_risk_rule は未確認に固着対応を上限へ含めるとしており、折れ込みは含めない",
        "仮定（U4）: サブフレームは J1・J2 では外さないので作業範囲外。low/typical/high のどれにも入れない",
        "仮定: 左ブーツは scenario で硬化と観察済み（未確認ではない）なので typical・high に入れる。low は音声メモで確定した分だけに限る。メモに無い観察済み分を typical に入れるかは整備士判断で、現在値はこの扱い",
        "仮定: 経過時間 = 人時 + 浸透待ち 0.25h（U5。固着対応を含む low/typical/high それぞれ、複数本でも1回。ハブ処置なしなので防錆乾燥は加えない）。scenario に経過時間の規則が無いため、1人・直列作業と置いた。workers_available は使っていない",
        "位置づけ: docs §4.5 の S25 は振り分けまでが仕組みで、labor_hours は docs にない参考試算。docs を正とし、確定値としては使わない",
        "仮定: 錆の語は HK01 の状態タグとして振り分けるのみで人時に換算しない（今回のメモには「錆」が出ない）",
        "仮定: 単位あたり人時は整備士暫定値（mechanic_provisional_add_ops）を使い、実績では更新していない",
        "前処理（雪下ろし・氷塊除去）はメモに出ないため、この案の再見積もりには含めない",
    ],
    "unknowns": [
        "サブフレームは「見てない」ので未確認。J1・J2 では外さないので作業範囲外。腐食があれば作業範囲の拡大（AG04）として見積もりを変更し、顧客の了承を得る",
        "左右スライドボルト4本（F-L-SLD-1/2、F-R-SLD-1/2）の錆・固着は未確認（FX-SEIZE high を high のみに含めた）。「右前は普通に外れた」を右スライドボルトの観察とみなすかは整備士確認（みなせば未確認2本 x 0.3 = 0.6 人時が high から外れる）",
        "右ブーツは交換と振り分けた。左ブーツ（硬化の観察あり）はメモに出ないが typical・high に入れたので、交換要否を整備士が確認する",
        "右前は「普通に外れた」とのみ。右ローター・ハブの状態まで確認したかは不明（high に FX-ROTOR high を入れた。確認済みなら外れる）。右ブラケットも scenario は錆「中」だが実際は固着なしだった可能性があり、確認できれば typical −0.30・high −0.60",
        "文字起こしの誤認識（例: 固着/硬化、左右の取り違え）がないか整備士が振り分け結果を確認する",
    ],
}

text = json.dumps(out, ensure_ascii=False, indent=2)
print(text)
res = HERE / "results"
res.mkdir(exist_ok=True)
(res / "S25.json").write_text(text + "\n", encoding="utf-8")
