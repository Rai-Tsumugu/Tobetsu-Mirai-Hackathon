"""Shared contract for the local auto-repair labor-estimate simulator.

All estimate inputs use snake_case JSON names so Python, TypeScript, SQLite,
and the HTTP API can exchange snapshots without translation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
import uuid

ValueStatus = Literal["confirmed", "declared", "assumed", "unknown"]
KNOWN_SCOPE_KEYS = frozenset({"remove_install", "rust_observation", "snow_removal"})


@dataclass
class RangeValue:
    low: float | None
    typical: float | None
    high: float | None

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


@dataclass
class OperationLine:
    operation: str
    hours: RangeValue
    reason: str
    status: str
    operation_id: str | None = None
    person_count: int | None = None
    elapsed_hours: RangeValue | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["hours"] = self.hours.to_dict()
        if self.elapsed_hours:
            result["elapsed_hours"] = self.elapsed_hours.to_dict()
        return result


@dataclass
class Labor:
    person_hours: RangeValue
    elapsed_hours: RangeValue
    breakdown: list[OperationLine]
    unknowns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_hours": self.person_hours.to_dict(),
            "elapsed_hours": self.elapsed_hours.to_dict(),
            "breakdown": [line.to_dict() for line in self.breakdown],
            "unknowns": list(self.unknowns),
        }


def null_range() -> RangeValue:
    return RangeValue(None, None, None)


def stop_labor(unknowns: list[str], breakdown: list[OperationLine] | None = None) -> Labor:
    """Required gaps stop both totals and affected lines; never coerce unknown to zero."""
    rows = breakdown or []
    for row in rows:
        row.hours = null_range()
        row.status = "missing-required"
    return Labor(null_range(), null_range(), rows, list(dict.fromkeys(unknowns)))


def common_scenario_fixture() -> dict[str, Any]:
    """Fictional shared fixture used to compare implementations on identical evidence."""
    return {
        "scenario_id": "fictional-common-scenario-01",
        "job_id": "front_brake_service",
        "engine_id": "e07_pipeline",
        "rule_version": "fictional-rule-v1",
        "basis_unit": "person_hour",
        "basis_definition": "架空の整備作業範囲。含有運搬を除き、承認済み作業行を人時で集計する",
        "base_hours": {"value": 1.0, "status": "declared", "source": "fictional_fixture", "confirmed_at": None},
        "labor_rate": {"value": 9000, "status": "assumed", "source": "fictional_fixture_only", "confirmed_at": None},
        "fields": {
            "work_scope": {"value": "front_brake_service", "status": "confirmed", "source": "fictional_fixture", "confirmed_at": "2026-10-11T00:00:00+00:00"},
            "included_operations": {"value": ["remove_install", "rust_observation", "snow_removal"], "status": "confirmed", "source": "fictional_fixture", "confirmed_at": "2026-10-11T00:00:00+00:00"},
            "rotor_seizure": {"value": None, "status": "unknown", "source": None, "confirmed_at": None},
            "subframe_relevance": {"value": "unrelated", "status": "confirmed", "source": "fictional_fixture", "confirmed_at": "2026-10-11T00:00:00+00:00"},
            "parts_wait_stock_checked": {"value": True, "status": "confirmed", "source": "fictional_fixture", "confirmed_at": "2026-10-11T00:00:00+00:00"},
        },
        "operations": [
            {"operation_id": "base_service", "operation": "approved_deduplicated_base", "gross_hours": 2.0, "hours": 1.7, "person_count": 1, "duration_hours": 1.7, "status": "confirmed-observation", "source": "fictional_fixture", "deduplicated": True, "reason": "E10's 0.3 shared overlap is already removed outside E10"},
            {"operation_id": "included_carry", "operation": "included_transport", "hours": 0.12, "person_count": 1, "status": "confirmed-observation", "included_in_base": True, "billable": False, "source": "fictional_fixture"},
            {"operation_id": "replacement_carry", "operation": "two_person_handling", "hours_per_person": 0.10, "person_count": 2, "status": "confirmed-observation", "replaces_operation_id": "included_carry", "source": "fictional_fixture"},
            {"operation_id": "snow_melt", "operation": "snow_melting", "hours": 0.5, "person_count": 0, "elapsed_hours": 0.5, "status": "wait", "source": "fictional_fixture"},
            {"operation_id": "penetrant_wait", "operation": "penetrant_wait", "hours": 0.25, "person_count": 0, "elapsed_hours": 0.25, "status": "wait", "source": "fictional_fixture"},
            {"operation_id": "parts_wait", "operation": "parts_wait", "hours": 0.0, "person_count": 0, "elapsed_hours": 0.0, "status": "wait", "source": "fictional_fixture", "stock_checked": True},
            {"operation_id": "wash", "operation": "wash", "hours": 0.1, "person_count": 1, "status": "nonbillable-work", "source": "fictional_fixture"},
        ],
        "person_count": 1,
        "duration_hours": None,
        "waiting_hours": 0.75,
        "metadata": {"fictional_values": True},
    }


def approved_common_scenario_fixture() -> dict[str, Any]:
    """Same fixture with a fictional human-approved rotor-condition range."""
    import copy

    scenario = copy.deepcopy(common_scenario_fixture())
    scenario["fields"]["rotor_relevance"] = {
        "value": "relevant", "status": "confirmed", "source": "fictional_fixture", "confirmed_at": "2026-10-11T00:00:00+00:00"
    }
    scenario["fields"]["rotor_seizure_hours"] = {
        "value": {"low": 0.0, "typical": 0.25, "high": 0.5}, "status": "confirmed",
        "source": "fictional_human_approved_condition_width", "confirmed_at": "2026-10-11T00:00:00+00:00"
    }
    scenario["metadata"]["approved_condition_widths"] = {"rotor_seizure_hours": {
        "actor": "fictional_shop_owner", "reason": "fictional fixture approval",
        "old_value": None, "new_value": {"low": 0.0, "typical": 0.25, "high": 0.5},
    }}
    return scenario


def validate_core_contract(labor: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    import math

    def valid_range(value: Any) -> bool:
        if not isinstance(value, dict) or set(("low", "typical", "high")) - set(value):
            return False
        numbers = [value[key] for key in ("low", "typical", "high")]
        if any(number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0) for number in numbers):
            return False
        present = [number for number in numbers if number is not None]
        return not present or len(present) == 3 and present[0] <= present[1] <= present[2]

    for key in ("person_hours", "elapsed_hours"):
        value = labor.get(key, {})
        if not valid_range(value):
            issues.append(f"{key}:invalid_range")
    rows = labor.get("breakdown", [])
    if not isinstance(rows, list):
        issues.append("breakdown:not_list")
        rows = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"breakdown[{index}]:not_object")
            continue
        if not all(key in row for key in ("operation", "hours", "reason", "status")):
            issues.append(f"breakdown[{index}]:shape")
        if not valid_range(row.get("hours")):
            issues.append(f"breakdown[{index}]:invalid_range")
        if row.get("status") == "missing-required" and any(v is not None for v in (row.get("hours") or {}).values()):
            issues.append(f"breakdown[{index}]:missing_must_be_null")
    if not isinstance(labor.get("unknowns"), list) or any(not isinstance(item, str) for item in labor.get("unknowns", [])):
        issues.append("unknowns:must_be_string_list")
    return issues


def reference_labor(scenario_input: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Canonical fictional labor calculation shared by the 30 architecture demos.

    It preserves unapproved uncertainty as a stop, separates elapsed waits from
    worker-hours, removes the included transport before adding two-person work,
    and does not subtract E10's overlap twice.
    """
    import copy

    scenario = copy.deepcopy(scenario_input)
    operations = scenario.get("operations", [])
    fields = scenario.get("fields", {})
    unknowns: list[str] = []
    elapsed_unknowns: list[str] = []
    rows: list[dict[str, Any]] = []

    def obs_value(key: str) -> tuple[Any, str]:
        item = fields.get(key, {})
        if isinstance(item, dict) and "value" in item:
            return item.get("value"), item.get("status", "unknown")
        return item, "declared" if item is not None else "unknown"

    work_scope, scope_status = obs_value("work_scope")
    if work_scope != scenario.get("job_id") or scope_status not in ("confirmed", "declared"):
        unknowns.append("work_scope:required_match_and_status")
    included_operations, included_status = obs_value("included_operations")
    if not isinstance(included_operations, list) or included_status not in ("confirmed", "declared"):
        unknowns.append("included_operations:required_and_status")
    elif not included_operations or any(not isinstance(key, str) or key not in KNOWN_SCOPE_KEYS for key in included_operations):
        unknowns.append("included_operations:unknown_or_empty_scope")
    if scenario.get("basis_unit") != "person_hour" or not isinstance(scenario.get("basis_definition"), str) or not scenario.get("basis_definition", "").strip():
        unknowns.append("basis_unit_or_definition:required")

    base = next((op for op in operations if op.get("operation_id") == "base_service"), None)
    if not base or base.get("hours") is None or not base.get("deduplicated"):
        unknowns.append("approved_deduplicated_base")
    base_hours = float(base["hours"]) if base and base.get("deduplicated") and base.get("hours") is not None else 0.0
    included = next((op for op in operations if op.get("operation_id") == "included_carry"), None)
    replacement = next((op for op in operations if op.get("operation_id") == "replacement_carry"), None)
    if included and replacement and replacement.get("replaces_operation_id") == "included_carry":
        included_hours = float(included.get("hours", 0)) if included.get("included_in_base") else 0.0
        net_base_hours = base_hours - included_hours
        if net_base_hours < 0:
            unknowns.append("included_transport:exceeds_base")
        if net_base_hours and base:
            rows.append({"operation": "approved_deduplicated_base_after_included_removal", "hours": {"low": net_base_hours, "typical": net_base_hours, "high": net_base_hours}, "reason": "E10共有工程0.3控除済みの基準から含有運搬0.12を控除。二重控除しない", "status": "confirmed-observation", "operation_id": "base_service", "source": base.get("source")})
        rows.append({"operation": "included_transport_removed", "hours": {"low": 0.0, "typical": 0.0, "high": 0.0}, "reason": "含有運搬0.12は含有済みのため追加計上しない", "status": "confirmed-observation", "operation_id": "included_carry", "source": included.get("source")})
        handling = float(replacement.get("hours_per_person", 0)) * int(replacement.get("person_count", 0))
        rows.append({"operation": "two_person_handling", "hours": {"low": handling, "typical": handling, "high": handling}, "reason": "2人×0.10人時。含有運搬を追加計上しない", "status": "confirmed-observation", "operation_id": "replacement_carry", "person_count": replacement.get("person_count"), "source": replacement.get("source")})
    else:
        unknowns.append("included_transport_replacement")

    rotor_relevance, relevance_status = obs_value("rotor_relevance")
    rotor_hours, rotor_status = obs_value("rotor_seizure_hours")
    if rotor_relevance == "relevant":
        approval = scenario.get("metadata", {}).get("approved_condition_widths", {}).get("rotor_seizure_hours")
        if relevance_status not in ("confirmed", "declared"):
            unknowns.append("rotor_relevance:human_confirmation_required")
        elif not approval or not isinstance(rotor_hours, dict) or rotor_status != "confirmed":
            unknowns.append("rotor_seizure_hours:human_approval_required")
        else:
            rotor = {key: rotor_hours.get(key) for key in ("low", "typical", "high")}
            expected_approval = {"low": rotor.get("low"), "typical": rotor.get("typical"), "high": rotor.get("high")}
            if (not isinstance(approval, dict) or not isinstance(approval.get("actor"), str) or not approval["actor"].strip()
                    or not isinstance(approval.get("reason"), str) or not approval["reason"].strip()
                    or approval.get("old_value") is not None or approval.get("new_value") != expected_approval):
                unknowns.append("rotor_seizure_hours:approval_audit_mismatch")
            else:
                rows.append({"operation": "rotor_seizure", "hours": rotor, "reason": "人が承認した条件幅。条件付き提案", "status": "conditional", "operation_id": "rotor_seizure", "approval": approval, "source": fields["rotor_seizure_hours"].get("source")})
    elif rotor_relevance == "unrelated" and relevance_status == "confirmed":
        rows.append({"operation": "rotor_seizure", "hours": {"low": 0.0, "typical": 0.0, "high": 0.0}, "reason": "このscenarioの作業関連性なしとして人が確認。0は条件不適用を示す", "status": "confirmed-observation", "operation_id": "rotor_seizure"})
    else:
        unknowns.append("rotor_relevance:confirm_whether_required")

    for operation_id in ("snow_melt", "penetrant_wait", "parts_wait"):
        operation = next((op for op in operations if op.get("operation_id") == operation_id), None)
        if not operation:
            unknowns.append(f"{operation_id}:missing")
            continue
        if operation_id == "parts_wait" and not operation.get("stock_checked"):
            unknowns.append("parts_wait:stock_confirmation_required")
            continue
        raw_elapsed = operation.get("elapsed_hours", operation.get("hours", 0))
        if raw_elapsed is None:
            elapsed_range = {"low": None, "typical": None, "high": None}
            elapsed_unknowns.append(f"{operation_id}:elapsed_duration_unknown")
        else:
            elapsed = float(raw_elapsed)
            elapsed_range = {"low": elapsed, "typical": elapsed, "high": elapsed}
        rows.append({"operation": operation["operation"], "hours": {"low": 0.0, "typical": 0.0, "high": 0.0}, "reason": "非拘束の待機。人時0、確認できた経過時間にのみ加算", "status": "wait", "operation_id": operation_id, "elapsed_hours": elapsed_range, "source": operation.get("source")})

    wash = next((op for op in operations if op.get("operation_id") == "wash"), None)
    wash_hours = float(wash.get("hours", 0)) if wash else 0.0
    if wash:
        rows.append({"operation": "wash", "hours": {"low": wash_hours, "typical": wash_hours, "high": wash_hours}, "reason": "実作業人時は保持し、請求控除は別承認", "status": "nonbillable-work", "operation_id": "wash", "source": wash.get("source")})

    if unknowns:
        all_unknowns = list(dict.fromkeys([*unknowns, *elapsed_unknowns]))
        labor = {
            "person_hours": {"low": None, "typical": None, "high": None},
            "elapsed_hours": {"low": None, "typical": None, "high": None},
            "breakdown": [{**row, "hours": {"low": None, "typical": None, "high": None}, "status": "missing-required"} for row in rows],
            "unknowns": all_unknowns,
        }
        return labor, rows, all_unknowns

    rotor_row = next((row for row in rows if row["operation_id"] == "rotor_seizure"), None)
    rotor = rotor_row["hours"] if rotor_row else {"low": 0.0, "typical": 0.0, "high": 0.0}
    included_hours = float(included.get("hours", 0)) if included and included.get("included_in_base") else 0.0
    net_base_hours = base_hours - included_hours
    person_values = {
        key: round(net_base_hours + float(replacement["hours_per_person"]) * int(replacement["person_count"]) + float(rotor[key]) + wash_hours, 10)
        for key in ("low", "typical", "high")
    }
    work_elapsed = net_base_hours + float(replacement["hours_per_person"]) + wash_hours + float(rotor["typical"])
    if elapsed_unknowns:
        elapsed = {"low": None, "typical": None, "high": None}
    else:
        wait_elapsed = sum(float(row["elapsed_hours"]["typical"]) for row in rows if row.get("status") == "wait")
        elapsed = {"low": round(max(0.0, work_elapsed - float(rotor["typical"]) + float(rotor["low"])) + wait_elapsed, 10),
                   "typical": round(work_elapsed + wait_elapsed, 10),
                   "high": round(max(0.0, work_elapsed - float(rotor["typical"]) + float(rotor["high"])) + wait_elapsed, 10)}
    labor = {"person_hours": person_values, "elapsed_hours": elapsed, "breakdown": rows, "unknowns": list(elapsed_unknowns)}
    return labor, rows, list(elapsed_unknowns)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ObservedValue:
    value: Any = None
    status: ValueStatus = "unknown"
    source: str | None = None
    confirmed_at: str | None = None

    @classmethod
    def from_value(cls, raw: Any) -> "ObservedValue":
        if isinstance(raw, dict) and {"value", "status", "source", "confirmed_at"}.intersection(raw):
            return cls(raw.get("value"), raw.get("status", "unknown"), raw.get("source"), raw.get("confirmed_at"))
        return cls(raw, "unknown" if raw is None else "declared")


@dataclass
class RulePack:
    engine_id: str
    rule_version: str
    rules: list[dict[str, Any]] = field(default_factory=list)
    status: ValueStatus = "unknown"
    approved_by: str | None = None
    effective_from: str | None = None
    source: str | None = None


@dataclass
class ScenarioInput:
    scenario_id: str
    job_id: str
    fields: dict[str, ObservedValue]
    base_hours: ObservedValue
    labor_rate: ObservedValue
    operations: list[dict[str, Any]] = field(default_factory=list)
    engine_id: str = "e07_pipeline"
    rule_version: str = "simulator-1"
    person_count: int | None = None
    duration_hours: float | None = None
    waiting_hours: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScenarioInput":
        fields = {k: ObservedValue.from_value(v) for k, v in (raw.get("fields") or {}).items()}
        return cls(
            scenario_id=str(raw.get("scenario_id") or uuid.uuid4()),
            job_id=str(raw.get("job_id") or "unknown"),
            fields=fields,
            base_hours=ObservedValue.from_value(raw.get("base_hours")),
            labor_rate=ObservedValue.from_value(raw.get("labor_rate")),
            operations=list(raw.get("operations") or []),
            engine_id=str(raw.get("engine_id") or "e07_pipeline"),
            rule_version=str(raw.get("rule_version") or "simulator-1"),
            person_count=raw.get("person_count"),
            duration_hours=raw.get("duration_hours"),
            waiting_hours=raw.get("waiting_hours"),
            metadata=dict(raw.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LaborResult:
    labor_hours: float | None
    labor_rate: float | None
    labor_amount: int | None
    elapsed_hours: float | None
    waiting_hours: float | None
    status: str


@dataclass
class EngineResult:
    scenario_id: str
    engine_id: str
    rule_version: str
    status: str
    labor_result: LaborResult
    operation_id: str | None = None
    operations: list[dict[str, Any]] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    simulator_notice: str = "架空のシミュレーター値です。実価格・実車検証ではありません。"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_scenario(scenario: ScenarioInput, *, require_rate: bool = True) -> list[str]:
    """Return blocking gaps. Unknown/null observations never silently become zero."""
    missing: list[str] = []
    if scenario.base_hours.value is None:
        missing.append("base_hours")
    if require_rate and scenario.labor_rate.value is None:
        missing.append("labor_rate")
    if scenario.base_hours.value is not None:
        try:
            if float(scenario.base_hours.value) < 0:
                missing.append("base_hours:must_be_nonnegative")
        except (TypeError, ValueError):
            missing.append("base_hours:must_be_number")
    if scenario.labor_rate.value is not None:
        try:
            if float(scenario.labor_rate.value) < 0:
                missing.append("labor_rate:must_be_nonnegative")
        except (TypeError, ValueError):
            missing.append("labor_rate:must_be_number")
    for key, observed in scenario.fields.items():
        if observed.status == "unknown" or observed.value is None:
            missing.append(key)
    return missing


def calculate_labor_result(hours: float | None, rate: float | None, scenario: ScenarioInput) -> LaborResult:
    if hours is None or rate is None:
        return LaborResult(None, rate, None, scenario.duration_hours, scenario.waiting_hours, "blocked")
    return LaborResult(hours, rate, int(hours * rate), scenario.duration_hours, scenario.waiting_hours, "calculated")
