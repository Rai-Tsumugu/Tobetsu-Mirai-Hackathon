"""R06 explicit utilization scenario proposals in the shared rate store."""
from datetime import date, datetime, timezone

from fastapi import APIRouter
from pydantic import ConfigDict, Field

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, HoursRange, RateCalculation, RateProposal, RateStatus
from backend.r06_utilization_scenarios import calculate_utilization_scenarios

MODULE_ID = "R06"
router = APIRouter(tags=["R06 utilization scenarios"])


class R06Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date | None = None
    effective_from: date
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    period_total_person_hours: float | None = Field(default=None, ge=0)
    u_period_low: float | None = None
    u_period_mid: float | None = None
    u_period_high: float | None = None
    selected_scenario: str | None = None
    source: str = Field(min_length=1)
    scenario_source: str | None = None
    scenario_status: str = "entered"
    cost_evidence: str | None = None
    scenario_evidence: str | None = None
    hours_basis: str | None = None
    job_person_hours: HoursRange | None = None
    job_billable_ratio: float | None = Field(default=None, ge=0, le=1)
    materials_yen: float | None = Field(default=None, ge=0)
    period_label: str = "算定期間"


def _evidence_blockers(body: R06Create, result: dict) -> list[str]:
    blockers = list(result["blockers"])
    if not (body.cost_evidence or "").strip():
        blockers.append("期間配賦原価の根拠が必要です")
    if not (body.scenario_source or "").strip() or not (body.scenario_evidence or "").strip():
        blockers.append("稼働率の出典と根拠が必要です")
    if body.scenario_status not in {"entered", "factory_reported", "assumed", "unknown"}:
        blockers.append("稼働率の根拠状態が不正です")
    if body.hours_basis == "total_person_hours" and body.job_person_hours and body.job_billable_ratio is None:
        blockers.append("案件時間の基準が総人時の場合、案件請求可能割合が必要です")
    return sorted(set(blockers))


@router.post("/scenarios/preview")
def preview_scenarios(body: R06Create):
    """Calculate comparison cards before the user chooses and saves a candidate."""
    result = calculate_utilization_scenarios(
        allocable_cost_yen=body.allocable_cost_yen,
        period_total_person_hours=body.period_total_person_hours,
        u_period_low=body.u_period_low, u_period_mid=body.u_period_mid,
        u_period_high=body.u_period_high, selected_scenario="typical",
    )
    blockers = _evidence_blockers(body, {**result, "blockers": [
        blocker for blocker in result["blockers"] if blocker != "採用するシナリオを明示してください"
    ]})
    return {
        "available": not blockers,
        "scenario_rates": result["scenario_rates"],
        "scenario_denominators": result["scenario_denominators"],
        "formulas": result["formulas"], "explanations": result["explanations"],
        "blockers": blockers,
    }


@router.post("/proposals")
def create_proposal(body: R06Create):
    result = calculate_utilization_scenarios(
        allocable_cost_yen=body.allocable_cost_yen,
        period_total_person_hours=body.period_total_person_hours,
        u_period_low=body.u_period_low, u_period_mid=body.u_period_mid,
        u_period_high=body.u_period_high, selected_scenario=body.selected_scenario,
    )
    now = datetime.now(timezone.utc)
    scenario_source = (body.scenario_source or "").strip() or None
    cost_evidence = (body.cost_evidence or "").strip() or None
    scenario_evidence = (body.scenario_evidence or "").strip() or None
    blockers = _evidence_blockers(body, result)

    excluded = []
    if body.materials_yen is not None:
        from backend.models import CostItem
        excluded = [CostItem(cost_id="separately_billed_materials", label="別請求の部品・材料費",
                             amount_yen=body.materials_yen, period=body.period_label, source=body.source,
                             evidence_status="entered", billing_class="separately_billed_item",
                             included_in_labor_pool=False, excluded_reason="別請求のため労務原価から除外")]

    evidence = [
        Evidence(label="期間配賦原価", value=body.allocable_cost_yen, unit="円/期間",
                 status="entered" if cost_evidence else "unknown", source=body.source,
                 recorded_at=now, notes=cost_evidence),
        Evidence(label="期間稼働率 low / mid / high",
                 value=f"{body.u_period_low} / {body.u_period_mid} / {body.u_period_high}",
                 unit="割合", status=body.scenario_status if scenario_source and scenario_evidence else "unknown",
                 source=scenario_source, recorded_at=now, notes=scenario_evidence),
    ]
    proposal = RateProposal(
        module_id=MODULE_ID, period_start=body.period_start or body.effective_from.replace(month=1, day=1),
        period_end=None, effective_from=body.effective_from,
        allocable_cost_yen=body.allocable_cost_yen,
        period_total_person_hours=body.period_total_person_hours,
        u_period=body.u_period_mid, hours_basis=body.hours_basis,
        job_person_hours=body.job_person_hours, job_billable_ratio=body.job_billable_ratio,
        costs=excluded, source=body.source,
        notes=(f"R06 selected_scenario={body.selected_scenario}; scenario_source={scenario_source}; "
               f"scenario_status={body.scenario_status}; scenario_evidence={scenario_evidence}; "
               "Materials billed separately and excluded from labor pool."),
        evidence=evidence,
    )

    basis = [
        BasisRow(label="選択シナリオ", value=body.selected_scenario, unit="scenario"),
        BasisRow(label="期間配賦原価 C", value=body.allocable_cost_yen, unit="円/期間"),
        BasisRow(label="期間総労働人時 H_period_total", value=body.period_total_person_hours, unit="人時/期間"),
    ]
    for band, input_band in (("low", "high"), ("typical", "mid"), ("high", "low")):
        basis.extend([
            BasisRow(label=f"u_period_{input_band}", value=getattr(body, f"u_period_{input_band}"), unit="割合"),
            BasisRow(label=f"{band} シナリオ分母", value=result["scenario_denominators"][band], unit="請求可能人時/期間"),
            BasisRow(label=f"{band} シナリオ単価", value=result["scenario_rates"][band], unit="円/人時"),
            BasisRow(label=f"{band} シナリオ式", value=result["formulas"][band], unit="式"),
            BasisRow(label=f"{band} シナリオ説明", value=result["explanations"][band], unit="説明"),
        ])
    basis.extend([
        BasisRow(label="稼働率根拠状態", value=body.scenario_status, unit="status"),
        BasisRow(label="稼働率出典", value=scenario_source, unit="source"),
        BasisRow(label="根拠記録日", value=now.date().isoformat(), unit="日付"),
        BasisRow(label="単価適用開始日", value=body.effective_from.isoformat(), unit="日付"),
        BasisRow(label="期間分母への案件比率適用", value="なし", unit="説明"),
    ])
    if body.job_person_hours is not None:
        job_hours = body.job_person_hours.model_dump()
        job_unknowns = []
        if body.hours_basis == "billable_person_hours":
            job_billable = body.job_person_hours
        elif body.hours_basis == "total_person_hours" and body.job_billable_ratio is not None:
            job_billable = HoursRange(**{key: value * body.job_billable_ratio for key, value in job_hours.items()})
        else:
            job_billable = None
            job_unknowns = ["hours_basis" if body.hours_basis is None else "job_billable_ratio"]
    else:
        job_billable = None
        job_unknowns = ["job_person_hours"]
    if body.materials_yen is not None:
        basis.append(BasisRow(label="別請求材料費（労務原価から除外）", value=body.materials_yen, unit="円"))

    calculation = RateCalculation(
        status=RateStatus.blocked if blockers else RateStatus.draft,
        candidate_yen_per_person_hour=result["candidate_yen_per_person_hour"] if not blockers else None,
        denominator_person_hours=result["denominator_person_hours"] if not blockers else None,
        hours_basis=body.hours_basis, u_period=body.u_period_mid,
        job_billable_ratio=body.job_billable_ratio, job_unknowns=job_unknowns,
        job_billable_person_hours=job_billable, unknowns=sorted(set(blockers)),
        excluded_items=excluded, basis=basis,
    )
    return store.create_proposal(proposal, module_calculation=calculation)


@router.get("/proposals/{proposal_id}")
def get_r06_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        from fastapi import HTTPException
        raise HTTPException(404, "R06 proposal not found")
    return store.get_proposal(proposal_id)
