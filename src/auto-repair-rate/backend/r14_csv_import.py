"""R14 local CSV validation, review mapping, and transient row processing."""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation


def parse_cost_csv(csv_contents: str, mappings: list[dict], confirm_materials_exclusion: bool,
                   confirm_duplicate_exclusion: bool, period_start: date | None = None,
                   period_end: date | None = None, tax_basis: str = "tax_excluded") -> dict:
    rows = []
    blockers = []
    if tax_basis != "tax_excluded":
        blockers.append("配賦基準は税抜にしてください。CSVを税抜金額で出力して再取込してください")
    try:
        reader = csv.DictReader(io.StringIO(csv_contents))
        required = {"date", "account", "amount", "tax_mode"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            return {"rows": [], "allocated_totals_yen": {}, "blockers": ["CSV列 date, account, amount, tax_mode が必要です"], "raw_csv_persisted": False}
        for row_no, raw in enumerate(reader, 2):
            try:
                row_date = date.fromisoformat((raw.get("date") or "").strip())
                account = (raw.get("account") or "").strip()
                amount = Decimal((raw.get("amount") or "").strip())
                tax_mode = (raw.get("tax_mode") or "").strip()
                if not account or not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
                    raise ValueError("account/amount validation")
                if tax_mode not in {"tax_included", "tax_excluded", "tax_exempt"}:
                    raise ValueError("tax_mode validation")
            except (ValueError, InvalidOperation):
                blockers.append(f"{row_no}行目: 日付・科目・整数円金額・税区分を確認してください")
                continue
            rows.append({"row_no": row_no, "date": row_date.isoformat(), "account": account,
                         "amount_yen": int(amount), "tax_mode": tax_mode})
    except csv.Error:
        blockers.append("CSVを読み取れません")
    counts = Counter((r["date"], r["account"], r["amount_yen"], r["tax_mode"]) for r in rows)
    if period_start and period_end and any(not period_start <= date.fromisoformat(r["date"]) <= period_end for r in rows):
        blockers.append("CSV行に指定期間外の日付があります")
    duplicated = {key for key, count in counts.items() if count > 1}
    if duplicated and not confirm_duplicate_exclusion:
        blockers.append("重複行を除外する確認が必要です")
    seen = set()
    mapped_totals = defaultdict(int)
    mapping_by_account = {m["account"]: m for m in mappings}
    preview_rows = []
    allocated_tax_modes = set()
    for row in rows:
        key = (row["date"], row["account"], row["amount_yen"], row["tax_mode"])
        duplicate_excluded = key in duplicated and key in seen
        seen.add(key)
        mapping = mapping_by_account.get(row["account"])
        category = mapping["category"] if mapping and mapping["approved"] else None
        included = category is not None and category != "materials" and not duplicate_excluded
        if category is None:
            blockers.append(f"未承認または未知の科目: {row['account']}")
        if category == "materials" and not confirm_materials_exclusion:
            blockers.append("別請求材料の二重計上を除外する確認が必要です")
        if included:
            mapped_totals[category] += row["amount_yen"]
            allocated_tax_modes.add(row["tax_mode"])
        preview_rows.append({**row, "mapped_category": category, "included_in_labor_pool": included,
                             "duplicate_excluded": duplicate_excluded,
                             "mapping_approved": bool(mapping and mapping["approved"])})
    if allocated_tax_modes and allocated_tax_modes != {"tax_excluded"}:
        blockers.append("労務費の税区分は税抜に統一してください。CSVを税抜金額で出力して再取込してください")
    return {"rows": preview_rows, "allocated_totals_yen": dict(mapped_totals) if not blockers else {},
            "blockers": sorted(set(blockers)), "raw_csv_persisted": False,
            "duplicate_rows_detected": len(duplicated), "tax_basis": tax_basis,
            "formula": "sum(approved mapped labor-pool rows with tax_mode=tax_excluded)"}
