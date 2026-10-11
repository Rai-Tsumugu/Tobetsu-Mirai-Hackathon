#!/usr/bin/env python3
"""S16 質問形式の工程展開

方針: 作業(J1/J2)ごとに数問の選択式の質問を定義し、scenario.json から回答を導く。回答に応じて
該当する工程と確認事項を展開し、展開された工程だけを基準 1.7 人時に加える。質問の出し方は
季節と確認強度(S04連動)で変える。冬季(intake.season)なら雪・氷の質問を出し、確認強度「強」
(経過年数・走行距離がしきい値以上)なら錆・ゴム部品の追加質問を出す(docs の「冬季や経過年数の
長い車では、錆・雪・ゴム部品の質問が増える」)。強で増える追加質問は人時0の確認事項で、経過年数・走行距離は
倍率に使わない(共通ルール5)。回答は対話ではなく scenario.json から自動導出する。

手順:
 1. 基準 1.7 人時 (base_totals.deduplicated_base) を出発点にする。
 2. 季節(intake.season が冬季か)と、経過年数・走行距離による確認強度(S04連動)を決める。
 3. 質問バンクを定義する。各質問は対象作業(入庫全体 / J1 / J2)と出す条件(常時 / 冬季 / 強のみ)を持つ。
 4. 各質問の回答を scenario.json の condition 等から導く。状態は「問題あり / 問題なし / 未確認」。
 5. 回答ごとに工程を展開する。締結部は SPEC U3 の表に従う。
    - 錆 中: low 0 / typical FX-SEIZE typical / high FX-SEIZE high
    - 錆 重: low FX-SEIZE low / typical FX-SEIZE typical / high FX-SEIZE high + FX-BROKEN high + FX-THREAD high
    - 未確認: high にだけ FX-SEIZE high
    ハブ錆はグレード2以上で FX-HUBCLEAN(左右)。暫定値がないハブ径リング・コート下の腐食は
    近い作業の high で代用した上限を high にだけ入れる。サブフレームは U4 により作業範囲外
    (人時に入れず、unknowns に作業範囲拡大(AG04)の扱いを書く)。
 6. 展開した工程の人時を low/typical/high それぞれ合計し、基準 1.7 に足す。
 7. 経過時間 = 人時 + 待機(U5)。FX-SEIZE を含む水準に浸透待ち、FX-HUBCLEAN を含む水準に
    防錆乾燥(冬季仮説値)、氷塊除去を含む水準に融解待ちを足す。
 8. 前処理(雪下ろし・氷塊除去・下回り洗浄)は S16 の範囲(U1)なので工程として人時に入れる(U7)。
    洗浄は請求しないので、請求人時を other_outputs に別に出す。
 9. 質問数・展開した工程数・確認事項数を intermediates に出す。
"""
import json
import os
import sys
from datetime import date

R = lambda x: round(x + 1e-9, 2)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "scenario.json"), encoding="utf-8") as f:
        sc = json.load(f)

    base = sc["base_totals"]["deduplicated_base"]
    ops = sc["mechanic_provisional_add_ops"]
    cond = sc["condition"]
    veh = sc["vehicle"]
    waits = sc["elapsed_waits"]
    th = sc["shop_policy"]["check_intensity_threshold"]
    prev = sc["previous_visit_same_vehicle"]

    def tri(op, n=1):
        o = ops[op]
        return {k: o[k] * n for k in ("low", "typical", "high")}

    ZERO = {"low": 0.0, "typical": 0.0, "high": 0.0}
    HIGH_ONLY = lambda op, n=1: {"low": 0.0, "typical": 0.0, "high": ops[op]["high"] * n}

    # 1-2. 確認強度(S04連動)
    fy, fm = map(int, veh["first_registration"].split("-")[:2])
    iy, im, _ = map(int, sc["intake"]["date"].split("-"))
    months = (iy - fy) * 12 + (im - fm)
    years = months / 12
    km = veh["odometer_km"]
    strong = years >= th["age_years"] or km >= th["odometer_km"]
    winter = sc["intake"]["season"].startswith("冬季")

    rust = cond["underbody_rust_grade"]
    fast = cond["fasteners"]
    brk = [x for x in fast if x["job"] == "J2" and "BRK" in x["id"]]
    sld = [x for x in fast if x["job"] == "J2" and "SLD" in x["id"]]

    questions = []  # 各要素: id, job, level, text, answer, status, steps[(name, op, count, hours, kind)]

    def Q(qid, job, level, text, answer, status, steps=None):  # level: 常時 / 冬季 / 強のみ
        questions.append({"id": qid, "job": job, "level": level, "text": text,
                          "answer": answer, "status": status, "steps": steps or []})

    # 入庫全体(HK02, HK03)
    snow = cond["snow_on_body"]["state"] == "問題あり"
    Q("Q01", "入庫", "冬季", "屋根・ボンネットに雪があるか", "あり(約15cm)" if snow else "なし", "確認済み",
      [("雪下ろし", "PRE-SNOW", 1, tri("PRE-SNOW"), "工程")] if snow else [])
    ice_n = cond["ice_in_wheel_house"]["locations"] if cond["ice_in_wheel_house"]["state"] == "問題あり" else 0
    Q("Q02", "入庫", "冬季", "ホイールハウスに氷塊があるか(何か所)", f"あり({ice_n}か所)" if ice_n else "なし", "確認済み",
      [(f"氷塊除去({ice_n}か所。融解待ちは経過時間のみ)", "PRE-ICE", ice_n, tri("PRE-ICE", ice_n), "工程")] if ice_n else [])
    Q("Q03", "入庫", "常時", "下回り洗浄を前処理として行うか(請求なし)", "行う(請求しない方針)", "確認済み",
      [("下回り洗浄(実作業として人時に入れる。請求対象外、U7)", "PRE-WASH", 1, tri("PRE-WASH"), "工程")])

    # J2 共通(HK01, AG01)
    brake_g = rust["brake_area"]
    Q("Q04", "J2", "常時", "ブレーキ周りの下回りに錆が見えるか(グレード)",
      f"見える(グレード{brake_g}:重度)" if brake_g and brake_g >= 2 else "見えない", "確認済み",
      [("ブレーキ周りの錆の写真記録", None, 1, ZERO, "確認")] if brake_g and brake_g >= 2 else [])
    Q("Q05", "J2", "常時", "前回この部位を外したか。そのとき問題はあったか",
      f"外した({prev['date']}、左ブラケットボルト1本が固着)", "申告・記録あり",
      [("左ブラケットボルトの再固着を優先して確認", None, 1, ZERO, "確認"),
       ("前回(ハブ錆グレード1)との進行を比較", None, 1, ZERO, "確認")])

    # 締結部(重=折れ込みの可能性、中=固着、未確認=highのみ)
    def bolt_steps(items):
        out = []
        S, B, T = ops["FX-SEIZE"], ops["FX-BROKEN"], ops["FX-THREAD"]
        for x in items:
            r = x["rust"]
            if r.startswith("重"):  # U3: 折れ込みの可能性
                h = {"low": S["low"], "typical": S["typical"], "high": S["high"] + B["high"] + T["high"]}
                out.append((f"{x['name']}: 固着対応(上限は折れ込みの抜き取り＋ねじ山修正を加える)", "FX-SEIZE/FX-BROKEN/FX-THREAD", 1, h, "工程"))
            elif r.startswith("中"):  # U3: 固着対応の可能性
                h = {"low": 0.0, "typical": S["typical"], "high": S["high"]}
                out.append((f"{x['name']}: 固着対応", "FX-SEIZE", 1, h, "工程"))
            elif r.startswith("未確認"):  # U3: high にだけ固着対応
                out.append((f"{x['name']}: 未確認(上限のみ)", "FX-SEIZE", 1, HIGH_ONLY("FX-SEIZE"), "未確認"))
        return out

    n_heavy = sum(1 for x in brk if x["rust"].startswith("重"))
    Q("Q06", "J2", "常時", "キャリパーブラケットボルトの頭部が腐食しているか",
      f"重{n_heavy}本・中{len(brk)-n_heavy}本", "確認済み", bolt_steps(brk))
    n_unc = sum(1 for x in sld if x["rust"].startswith("未確認"))
    Q("Q07", "J2", "常時", "スライドボルトの状態がブーツを外さず見えるか",
      f"見えない({n_unc}本)" if n_unc else "見える", "未確認" if n_unc else "確認済み", bolt_steps(sld))
    # ブーツ(AG03)
    boots = cond["slide_pin_boots"]
    bs = []
    for side, v in boots.items():
        s = "左" if side == "left" else "右"
        if v.startswith("問題あり"):
            bs.append((f"{s}スライドピンブーツ交換", "AG-BOOT", 1, tri("AG-BOOT"), "工程"))
        elif v.startswith("未確認"):
            bs.append((f"{s}スライドピンブーツ: 未確認(上限のみ)", "AG-BOOT", 1, HIGH_ONLY("AG-BOOT"), "未確認"))
    Q("Q08", "J2", "常時", "スライドピンブーツが硬化・破れしているか",
      "左=硬化、右=未確認", "一部未確認", bs)
    # ハブ・ローター(HK01/AG01)
    hub_g = rust["wheel_hub"]
    hub_steps = [("ハブ当たり面の錆落とし・防錆(左右両側)", "FX-HUBCLEAN", 2, tri("FX-HUBCLEAN", 2), "工程")] \
        if hub_g and hub_g >= 2 else []
    Q("Q09", "J2", "常時", "ハブ当たり面の錆は進行錆(グレード2)以上か",
      f"はい(グレード{hub_g})" if hub_steps else "いいえ", "確認済み", hub_steps)
    rotor_unc = cond["rotor_hub_seizure"]["state"] == "未確認"
    Q("Q10", "J2", "常時", "ローターがハブに固着しているか(分解前に分かるか)",
      "分解前のため不明" if rotor_unc else "固着なし", "未確認" if rotor_unc else "確認済み",
      [("ローター固着除去(左右とも未確認、上限のみ)", "FX-ROTOR", 2, HIGH_ONLY("FX-ROTOR", 2), "未確認")] if rotor_unc else [])
    sub_unc = rust["subframe"] is None
    Q("Q11", "J2", "常時", "サブフレームの錆が見えるか",
      "見えない(アンダーカバー、撮影なし)" if sub_unc else f"グレード{rust['subframe']}", "未確認" if sub_unc else "確認済み",
      [("サブフレームの錆は J1・J2 では外さないため作業範囲外。腐食があれば作業範囲の拡大(AG04)として見積もりを変更し、顧客の了承を得る(人時に入れない)", None, 1, ZERO, "確認")] if sub_unc else [])
    # AG06 社外部品、HK07 防錆コート
    Q("Q12", "J1/J2", "常時", "社外部品(ホイール等)が付いているか", f"{cond['modification']}(顧客申告)", "申告",
      [("ハブ径リングの固着・脱着(未確認、上限のみ。暫定値がないため FX-SEIZE の high を左右分代用)", "FX-SEIZE-PROXY", 2, HIGH_ONLY("FX-SEIZE", 2), "未確認")] if "ハブ径リング" in cond["modification"] else [])
    coat = cond["rustproof_undercoat"]["value"]
    dry = waits["rustproof_dry_wait_hours"]["winter_hypothesis"]
    Q("Q13", "J2", "常時", "防錆アンダーコートの施工歴があるか", "あり(2022年、顧客申告)" if coat else "なし", "申告",
      [("コートの上から腐食が見えにくいため、触診・剥離して確認(ハブ以外の下回り面が対象。ハブ当たり面は Q09 で計上済みなので二重計上しない。未確認、上限のみ。暫定値がないため FX-HUBCLEAN の high を左右分代用)", "FX-HUBCLEAN-PROXY", 2, HIGH_ONLY("FX-HUBCLEAN", 2), "未確認")] if coat else [])

    # 強のみの追加質問(錆・ゴム部品): 人時0の確認事項だけ(経年・走行距離で工数を増やさない。共通ルール5)
    other_rust = {k: v for k, v in rust.items() if k not in ("brake_area", "wheel_hub", "subframe") and not k.startswith("_") and v}
    Q("Q14", "J2", "強のみ", "ブレーキ周り・ハブ以外の下回り(足回り・マフラー等)にも錆があるか(確認のみ)",
      "あり(" + "、".join(f"{k}=グレード{v}" for k, v in other_rust.items() if v >= 1) + ")", "確認済み",
      [("ブレーキ周り以外の錆の範囲を写真で記録(人時に入れない)", None, 1, ZERO, "確認")])
    Q("Q15", "J2", "強のみ", "経年劣化しやすいゴム部品(ブーツ以外のブレーキホース等)に亀裂・硬化があるか(確認のみ)", "見る(分解時に確認)", "確認済み",
      [("ブレーキホース等のゴム部品の亀裂・硬化を分解時に確認(人時に入れない。ホース交換は付随部品の参考で、high に入れない)", None, 1, ZERO, "確認")])
    Q("Q16", "J2", "強のみ", "樹脂クリップの劣化・破損があるか(確認のみ)", "見る(分解時に確認。現状は観察なし)", "未確認",
      [("樹脂クリップの劣化を分解時に確認(人時に入れない。個数が不明なので AG-CLIP は high にも入れず unknowns に記録)", None, 1, ZERO, "確認")])

    # 3. 質問の選別
    def is_asked(q, w, st):
        return q["level"] == "常時" or (q["level"] == "冬季" and w) or (q["level"] == "強のみ" and st)
    asked = [q for q in questions if is_asked(q, winter, strong)]
    asked_base = [q for q in questions if is_asked(q, False, False)]
    n_winter_add = sum(1 for q in questions if is_asked(q, True, False)) - len(asked_base)
    n_strong_add = sum(1 for q in questions if is_asked(q, False, True)) - len(asked_base)

    # 6. 集計
    tot = dict(ZERO)
    has_seize = {"low": False, "typical": False, "high": False}
    has_hub = dict(has_seize)
    has_ice = dict(has_seize)
    wash_h = 0.0
    n_steps = n_confirm = n_unconf = 0
    confirm_names = []
    steps_out = []
    for q in asked:
        for name, op, cnt, h, kind in q["steps"]:
            steps_out.append(f"{q['id']} {name}")
            if kind == "確認":
                n_confirm += 1
                confirm_names.append(f"{q['id']} {name}")
                continue
            if kind == "未確認":
                n_unconf += 1
            else:
                n_steps += 1
            for k in tot:
                tot[k] += h[k]
                if op and "SEIZE" in op and h[k] > 0: has_seize[k] = True
                if op and "HUBCLEAN" in op and h[k] > 0: has_hub[k] = True
                if op == "PRE-ICE" and h[k] > 0: has_ice[k] = True
    # U5: 浸透待ち(FX-SEIZE)・防錆乾燥(FX-HUBCLEAN、冬季仮説値)を、含む水準にだけ足す。
    # 氷塊除去は S16 に含めない(人時0の確認事項)ので融解待ちは足さない
    soak = {k: waits["penetrant_soak_wait_hours"] if has_seize[k] else 0.0 for k in tot}
    dry_w = {k: dry if has_hub[k] else 0.0 for k in tot}
    thaw_w = {k: waits["thaw_wait_hours"] if has_ice[k] else 0.0 for k in tot}
    thaw = waits["thaw_wait_hours"]
    wash = ops["PRE-WASH"]

    lab = {k: base + tot[k] for k in ("low", "typical", "high")}
    el = {k: lab[k] + soak[k] + dry_w[k] + thaw_w[k] for k in lab}
    billed = {k: lab[k] - (wash[k] if any(s_[1] == "PRE-WASH" for q in asked for s_ in q["steps"]) else 0.0) for k in lab}

    unknowns = [
        "スライドボルト4本の固着(ブーツに隠れて未確認)。U3 により high にだけ FX-SEIZE high を反映",
        "ローター固着(左右)は分解前で不明。highにのみ反映",
        "右スライドピンブーツの状態は未確認。highにのみ反映",
        "サブフレームの錆はアンダーカバーで見えず未確認。J1・J2 では外さないので作業範囲外(U4)とし、人時に入れていない。腐食があれば作業範囲の拡大(AG04)として見積もりを変更し、顧客の了承を得る",
        "ブラケットボルト左2本(頭部腐食)の折れ込みの有無は分解するまで不明。U3 により high に FX-SEIZE・FX-BROKEN・FX-THREAD の high を入れた",
        "コートの下の腐食は剥離して見るまで不明。暫定値がないため FX-HUBCLEAN の high を左右分(0.30)代用して high にだけ入れた",
        "ハブ径リングの固着は分解後でないと不明。暫定値がないため FX-SEIZE の high を左右分(0.60)代用して high にだけ入れた",
        "樹脂クリップの劣化・破損は分解するまで不明で、個数も不明。AG-CLIP(1個あたり high 0.05)は個数を仮定できないため high にも入れていない。破損があれば個数分を加算する",
    ]
    assumptions = [
        "仮定: 1人で順に作業し、2人作業による経過時間の短縮は見込まない(workers_available=2 は使わない)",
        "仮定: 錆グレード2以上のハブは両側とも防錆処理が要るものとして FX-HUBCLEAN を左右に入れた(グレードは部位全体の値で、左右別の観察はない)",
        "仮定: 締結部は SPEC U3 の表に従う。重は low=FX-SEIZE low、typical=FX-SEIZE typical、high=FX-SEIZE high+FX-BROKEN high+FX-THREAD high。中は low 0、typical=FX-SEIZE typical、high=FX-SEIZE high。未確認は high にだけ FX-SEIZE high。折れ込みは固着対応を試みたあとに起きる別工程で二重計上ではない",
        "仮定: 待機は SPEC U5 に従う。FX-SEIZE を含む水準に浸透待ち0.25h、FX-HUBCLEAN を含む水準に防錆乾燥0.3h(冬季仮説値)を足す。low・typical・high それぞれの経過時間に入れ、人時には入れない。防錆乾燥はハブ当たり面の防錆(Q09)で low から含まれる",
        "仮定: 氷塊除去は S16 の範囲内(factors に HK03、§3 の主に扱う要因は「全般」、U1)。PRE-ICE を2か所分人時に入れ、U5 に従い融解待ち0.5hを全水準の経過時間に足す",
        "仮定: S16 の factors は §3 の「全般」を、§4 の仕組み(錆・前回の分解歴・社外部品、冬季の雪・氷、経年の確認強度)に対応する HK01(下回りの錆)・HK02(雪)・HK03(氷塊)・HK07(防錆コート)・AG01(固着)・AG03(ブーツ)・AG06(社外部品)・AG07(経年・走行距離)・AG08(前回入庫)に具体化したもの。HK04(クリップ・ゴムの割れ)は Q15・Q16 で確認事項として扱い人時には入れない。HK06(4WD・後付け装備)、HK08(暖房費は人時に足さない、共通ルール7)は質問の対象外。ローター固着(FX-ROTOR)は HK01/AG01 の範囲内とみなして high に入れた",
        "仮定: サブフレーム(Q11)は J1・J2 では外さない作業範囲外(U4)なので high にも入れない。確認事項として残し、腐食があれば作業範囲拡大(AG04)の見積もり変更を顧客に了承してもらう",
        "仮定: タイヤ重量(HK05)、気象予報(S06)、過去実績(S08)は S16 の要因ではないので反映しない",
        "仮定: 雪下ろし・氷塊除去・下回り洗浄(HK02・HK03)は S16 の範囲内(U1・U7)なので人時に入れる(PRE-SNOW 1回、PRE-ICE 2か所、PRE-WASH 1回。いずれも暫定値)。洗浄は請求しない方針でも実作業なので人時に入れ、請求人時は other_outputs に別に出す。S05・S17 との重複は S16 内では起きない(各案は独立に比較する)。洗浄の質問(Q03)は人時が確認強度で変わらないよう常時の質問にした",
        "仮定: 質問の出し方は docs の「冬季や経過年数の長い車では、錆・雪・ゴム部品の質問が増える」に合わせた。冬季(intake.season)で雪・氷の質問(Q01・Q02)を出し、確認強度「強」で錆・ゴム部品の追加質問(Q14〜Q16、洗浄の Q03)を出す。強で増える追加質問(Q14〜Q16)はすべて人時0の確認事項",
        "仮定: 質問数は docs の「作業ごとに数問」を超えており、J2 だけで多くなる。実運用では選択肢のグループ化で絞る必要がある",
        "仮定: Q03・Q15・Q16 の回答文は固定文、Q12 は scenario の modification を読んでハブ径リングの語があるときだけ上限を加算する。他の回答は condition 等から導く",
        "仮定: 質問の選択肢と回答の導き方は整備士への聞き取り前の暫定案。冬季・強のみの質問の区分も仮置き",
        "仮定: 経過年数・走行距離は人時に影響させない。工程を展開する質問は季節・強度にかかわらず出し、冬季・強で増えるのは人時0の確認事項の質問だけ。同じ観察なら通常でも強でも同じ人時になる",
        "仮定: 暫定値がない未確認項目(ハブ径リング・コート下の腐食)の high は、近い作業の暫定値(FX-HUBCLEAN / FX-SEIZE)の high で代用した上限の仮置き。typical・low には入れない",
        "仮定: ブレーキホース交換(AG-HOSE)は付随部品の発生頻度が表示しきい値(0.15)未満なので high に入れない(U8)。Q15 の確認事項に留める",
    ]
    inputs = [
        {"key": "vehicle.first_registration / intake.date", "value": f"{veh['first_registration']} → {sc['intake']['date']}(約{years:.1f}年)", "status": "確認済み"},
        {"key": "vehicle.odometer_km", "value": km, "status": "確認済み"},
        {"key": "intake.season / outside_temp_c", "value": f"{sc['intake']['season']} / {sc['intake']['outside_temp_c']}度", "status": "確認済み"},
        {"key": "condition.snow_on_body", "value": "問題あり(約15cm)", "status": "確認済み"},
        {"key": "condition.ice_in_wheel_house", "value": f"{ice_n}か所", "status": "確認済み"},
        {"key": "condition.underbody_rust_grade.brake_area", "value": brake_g, "status": "確認済み"},
        {"key": "condition.underbody_rust_grade.subframe", "value": None, "status": "不明"},
        {"key": "condition.fasteners(J2)", "value": f"ブラケット重{n_heavy}・中{len(brk)-n_heavy}、スライド未確認{n_unc}", "status": "一部未確認"},
        {"key": "condition.rotor_hub_seizure", "value": "未確認", "status": "不明"},
        {"key": "condition.slide_pin_boots", "value": "左=問題あり、右=未確認", "status": "一部未確認"},
        {"key": "condition.modification", "value": cond["modification"], "status": "申告"},
        {"key": "condition.rustproof_undercoat", "value": coat, "status": "申告"},
        {"key": "previous_visit_same_vehicle", "value": f"{prev['date']} 左ブラケットボルト1本固着", "status": "確認済み"},
    ]

    interm = [
        {"label": "季節と確認強度(S04連動)", "value": f"{'冬季' if winter else '冬季以外'} / {'強' if strong else '通常'}", "unit": "",
         "formula": f"季節={sc['intake']['season']}。経過年数 ({iy}-{fy})x12+({im}-{fm}) = {months}か月 / 12 = {years:.1f}年 >= {th['age_years']} または 走行{km} >= {th['odometer_km']} なら強"},
        {"label": "出した質問数", "value": len(asked), "unit": "問",
         "formula": f"常時{len(asked_base)}問 + 冬季の雪・氷{n_winter_add if winter else 0}問 + 強の錆・ゴム等{n_strong_add if strong else 0}問(全{len(questions)}問)"},
        {"label": "展開された工程", "value": n_steps, "unit": "工程",
         "formula": f"問題あり回答から展開した工程(typicalに入るもの)。未確認の上限工程は別に{n_unconf}件"},
        {"label": "展開された確認事項", "value": n_confirm, "unit": "件",
         "formula": "人時0の確認・撮影。内訳: " + " / ".join(confirm_names)},
        {"label": "追加人時(low/typical/high)", "value": [R(tot['low']), R(tot['typical']), R(tot['high'])], "unit": "人時",
         "formula": "展開工程の add_ops 人時の合計(U3の表)。未確認は high のみ"},
        {"label": "待機時間(経過のみ。low/typical/high)", "value": [R(soak[k] + dry_w[k] + thaw_w[k]) for k in ("low", "typical", "high")], "unit": "h",
         "formula": f"浸透待ち {waits['penetrant_soak_wait_hours']}(FX-SEIZE を含む水準) + 防錆乾燥 {dry}(FX-HUBCLEAN を含む水準)。融解待ち {thaw}(氷塊除去を含む全水準)"},
        {"label": "typical 人時", "value": R(lab["typical"]), "unit": "人時",
         "formula": f"{base} + {R(tot['typical'])}"},
    ]

    out = {
        "id": "S16",
        "name": "質問形式の工程展開",
        "base_method": "C",
        "factors": ["HK01", "HK02", "HK03", "HK07", "AG01", "AG03", "AG06", "AG07", "AG08"],
        "algorithm": [
            "手順1: 基準 1.7 人時から始める(前処理は S16 の範囲なので手順3の質問から展開して足す)",
            "手順2: 季節(冬季か)と、経過年数・走行距離から確認強度(通常/強)を決める。工数は変えない",
            "手順3: 作業ごとの質問バンクから質問を選ぶ。工程を展開する質問は常に出す。冬季なら雪・氷の質問、強なら錆・ゴム部品の追加質問が増える(追加分は人時0の確認事項)",
            "手順4: scenario の condition から各質問の回答(問題あり/なし/未確認)を導く",
            "手順5: 回答ごとに工程を展開する。締結部は U3 の表(中=固着対応、重=固着対応＋high に折れ込み・ねじ山、未確認=high に固着対応のみ)。サブフレームは U4 により作業範囲外",
            "手順6: 展開工程の人時を low/typical/high で合計して基準に足す",
            "手順7: U5 に従い、FX-SEIZE を含む水準に浸透待ち、FX-HUBCLEAN を含む水準に防錆乾燥、氷塊除去を含む水準に融解待ちを、経過時間にだけ足す",
        ],
        "inputs": inputs,
        "intermediates": interm,
        "result": {
            "labor_hours": {k: R(lab[k]) for k in ("low", "typical", "high")},
            "elapsed_hours": {k: R(el[k]) for k in ("low", "typical", "high")},
            "other_outputs": [
                {"label": "請求人時(下回り洗浄を除く。low/typical/high)", "value": [R(billed[k]) for k in ("low", "typical", "high")], "unit": "人時"},
                {"label": "質問数(常時のみ)", "value": len(asked_base), "unit": "問"},
                {"label": "質問数(今回・冬季かつ強)", "value": len(asked), "unit": "問"},
                {"label": "展開された質問と回答(自動導出: scenario.json の condition 由来。対話ではない)", "value": [f"{q['id']} {q['text']} → {q['answer']}" for q in asked], "unit": ""},
                {"label": "展開された工程・確認事項", "value": steps_out, "unit": ""},
            ],
            "note": "冬季なら雪・氷の質問、確認強度「強」なら錆・ゴム部品の追加質問を出すが、強で増える追加分は人時0の確認事項で、経過年数・走行距離は工数を変えない。工程を展開する質問は季節・強度にかかわらず出すので、同じ観察なら同じ人時になる。締結部は U3 の表、待機は U5 に従った。未確認の項目は暫定値(近い作業の high で代用したものを含む)を、この案の範囲での上限として high にだけ反映した。サブフレームは作業範囲外(U4)で人時に入れていない。前処理(雪下ろし・氷塊除去・洗浄)は S16 の範囲(U1)として人時に入れ、氷塊除去を含むので融解待ちを経過時間に足した(U5)。回答は主に scenario.json から導いた。",
        },
        "assumptions": assumptions,
        "unknowns": unknowns,
    }

    text = json.dumps(out, ensure_ascii=False, indent=2)
    os.makedirs(os.path.join(here, "results"), exist_ok=True)
    with open(os.path.join(here, "results", "S16.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
