"""results/*.json から 30 案の比較表（README.md）を作る。

使い方: python3 src/30-algorithm/build_table.py
results/checks.json（3重チェックの結果）があれば検証欄に反映する。
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

LENS_LABEL = {"arith": "算術", "spec": "仕様", "input": "入力"}


def fmt_num(v):
    if isinstance(v, dict):
        if {"low", "typical", "high"} <= set(v):
            return " / ".join(fmt_num(v[k]) for k in ("low", "typical", "high"))
        return "、".join(f"{k} {fmt_num(x)}" for k, x in v.items())
    if isinstance(v, list):
        return " / ".join(fmt_num(x) for x in v)
    if isinstance(v, bool):
        return "はい" if v else "いいえ"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"
    if isinstance(v, int) and abs(v) >= 1000:
        return f"{v:,}"
    return str(v)


def cell(text):
    return str(text).replace("|", "／").replace("\n", " ")


def fmt_range(r):
    if not r:
        return "—"
    return f"{r['low']:.2f} / **{r['typical']:.2f}** / {r['high']:.2f}"


def clip(text, limit=70):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fmt_inputs(items):
    out = []
    for i in items:
        value = i.get("value")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        status = f"（{i['status']}）" if i.get("status") and i["status"] != "確認済み" else ""
        out.append(cell(f"{i.get('key', '')}: {clip(value)}{clip(status, 30)}"))
    return "<br>".join(out)


def fmt_intermediates(items):
    out = []
    for i in items:
        unit = i.get("unit") or ""
        out.append(cell(f"{clip(i['label'], 50)}: **{clip(fmt_num(i['value']), 60)}** {unit}".rstrip()))
    return "<br>".join(out)


def fmt_final(res):
    parts = [f"人時 {fmt_range(res.get('labor_hours'))}"]
    if res.get("elapsed_hours"):
        parts.append(f"経過 {fmt_range(res['elapsed_hours'])}")
    for o in res.get("other_outputs") or []:
        parts.append(cell(f"{clip(o['label'], 40)}: {clip(fmt_num(o['value']), 50)} {o.get('unit') or ''}".rstrip()))
    return "<br>".join(parts)


def fmt_check(check):
    if not check:
        return "—"
    marks = "".join("✓" if c["pass"] and not c["major"] else "✗" for c in check["checks"])
    status = "合格" if check["final_pass"] else check.get("adjudication", "要確認")
    return f"{status} {marks}"


def main():
    checks_path = RESULTS / "checks.json"
    checks = {c["id"]: c for c in json.loads(checks_path.read_text())} if checks_path.exists() else {}
    rows = [json.loads(p.read_text()) for p in sorted(RESULTS.glob("S[0-9][0-9].json"))]

    lines = [
        "# 30案の演算アルゴリズム：比較表",
        "",
        "[system-ideas-30.md](../../docs/man-hours/system-ideas-30.md) の S01〜S30 を、共通の入力 [scenario.json](scenario.json) で計算した結果。"
        "**数値はすべて架空値**で、補正率・人時の実測ではない。共通ルールは [SPEC.md](SPEC.md)。この README は `build_table.py` で生成する。",
        "",
        "## 共通シナリオ",
        "",
        "- 車両: 架空SUV-X（4WD、寒冷地仕様）、初度登録 2014-01、走行 128,000km、タイヤ 225/65R17（ホイール付き約23kg、仮定）",
        "- 入庫: 2027-01-20（冬季、外気 -8℃）。車体に積雪15cm、前輪ホイールハウスに氷塊2か所",
        "- 作業: J1 冬タイヤ交換（基準0.6人時）＋ J2 フロントブレーキパッド・ローター交換（基準1.4人時）。共通工程の重複控除後 **1.7人時** を全案の出発点にする（S17のみ 2.0 から控除を計算）",
        "- 状態: ブレーキ周り錆グレード3、ハブ2、左ブラケットボルト錆「重」2本・右「中」2本、スライドボルト4本とローター固着・サブフレームは未確認、左ブーツ硬化",
        "- 各案は**自分が扱う要因だけ**を反映するため、最終工数の差は「その案が何を見ているか」の差である。合算・平均はしない",
        "",
        "## 比較表",
        "",
        "最終的な工数は「人時 low / **typical** / high」。経過時間は待機（融解・浸透・乾燥）を含む納車側の時間で、人時とは別。"
        "3重チェック欄の ✓／✗ は Haiku 3体（算術の独立再計算／仕様・解釈の統一／入力整合・再現性）の最終判定。"
        "「裁定済み」は、Haiku の指摘がオーケストレーターの個別指示と食い違うもので、指示どおりの実装を残した。理由は末尾の各案の節に書く。"
        "「要確認」は人時の値に影響しない不足が残っているもの。",
        "",
        "| No | 案名 | 入力内容 | 重要な途中計算数値 | 最終的な工数 | 3重チェック |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {cell(r['name'])}（{r.get('base_method', '')}） | {fmt_inputs(r.get('inputs', []))} "
            f"| {fmt_intermediates(r.get('intermediates', []))} | {fmt_final(r['result'])} | {fmt_check(checks.get(r['id']))} |"
        )

    lines += ["", "## 最終工数の一覧（typical の昇順）", "", "| No | 案名 | low | typical | high | 備考 |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["result"]["labor_hours"]["typical"], x["id"])):
        lh = r["result"]["labor_hours"]
        lines.append(f"| {r['id']} | {cell(r['name'])} | {lh['low']:.2f} | {lh['typical']:.2f} | {lh['high']:.2f} | {cell(clip(r['result'].get('note', ''), 140))} |")

    lines += ["", "## 各案の手順・仮定・未確認", ""]
    for r in rows:
        lines += [f"### {r['id']} {r['name']}", "", f"スクリプト: 同フォルダの `{r['id'].lower()}_*.py`。仮定・未確認の全文は [results/{r['id']}.json](results/{r['id']}.json)", ""]
        lines += [f"{n}. {cell(s)}" for n, s in enumerate(r.get("algorithm", []), 1)]
        lines.append("")
        c = checks.get(r["id"])
        if c:
            notes = [f"{LENS_LABEL.get(x['lens'], x['lens'])}: " + ("合格" if x["pass"] and not x["major"] else "不合格 " + "／".join(cell(clip(m, 160)) for m in x["major"])) for x in c["checks"]]
            lines += ["- 3重チェック: " + "、".join(notes) + ("（初回不合格 → Sonnet が修正 → 再検証）" if c["fixed"] else "")]
            if c.get("adjudication"):
                lines += [f"- {c['adjudication']}: {cell(c['adjudication_reason'])}"]
        lines.append("")

    (HERE / "README.md").write_text("\n".join(lines))
    print(f"wrote README.md ({len(rows)} rows)")


if __name__ == "__main__":
    main()
