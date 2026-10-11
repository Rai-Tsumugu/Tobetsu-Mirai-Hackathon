"""E23: descriptive, non-publishing operation benchmark summaries."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from math import isfinite
from statistics import median
from typing import Any
from .e07 import run as calculate

ENGINE_ID = "e23_reference_buckets"
RULE_VERSION = "e23-reference-buckets-v1"

def summarize_buckets(samples: list[dict[str, Any]], minimum_samples: int = 5) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for sample in samples:
        key = (sample["operation_id"], sample["unit"], sample["condition"])
        grouped[key].append(sample)
    reports = []
    for key, rows in sorted(grouped.items()):
        values = [row["hours"] for row in rows]
        reports.append({"operation_id": key[0], "unit": key[1], "condition": key[2], "n": len(rows),
                        "median_hours": median(values), "range_hours": {"low": min(values), "high": max(values)},
                        "sample_ids": [row["sample_id"] for row in rows],
                        "reference_only": len(rows) < minimum_samples, "autopublished": False})
    return reports

def run(scenario_input: dict, rule_pack: dict | None = None) -> dict[str, Any]:
    pack = deepcopy(rule_pack) if isinstance(rule_pack, dict) else {}
    samples = pack.get("samples", [])
    issues = ["rule_pack:object_required"] if rule_pack is not None and not isinstance(rule_pack, dict) else []
    if not isinstance(samples, list): samples = []; issues.append("samples:list_required")
    seen_ids = set()
    for i, row in enumerate(samples):
        if (not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row.get(k) for k in ("operation_id", "unit", "condition", "sample_id"))
                or row.get("unit") != "person_hour" or isinstance(row.get("hours"), bool) or not isinstance(row.get("hours"), (int, float)) or not isfinite(row.get("hours")) or row.get("hours", -1) < 0):
            issues.append("samples[%d]:invalid_observation" % i)
            continue
        if row["sample_id"] in seen_ids:
            issues.append("samples[%d]:duplicate_sample_id" % i)
        seen_ids.add(row["sample_id"])
    minimum = pack.get("minimum_samples", 5)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        issues.append("minimum_samples:positive_integer_required")
        minimum = 5
    result = calculate(deepcopy(scenario_input))
    result.update({"engine_id": ENGINE_ID, "rule_version": RULE_VERSION,
                   "reference_report": [] if issues else summarize_buckets(samples, minimum),
                   "reference_issues": issues, "autopublished": False})
    return result
