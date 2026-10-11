"""R05 factory proposal endpoints; approval and history use shared APIs."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, HoursRange, RateCalculation, RateProposal, RateStatus
from backend.r05_cost_floor import calculate_cost_floor

MODULE_ID = "R05"
router = APIRouter(tags=["R05 cost floor and target profit"])


class R05Create(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date | None = None
    period_end: date | None = None
    effective_from: date
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    period_total_person_hours: float | None = Field(default=None, ge=0)
    u_period: float | None = Field(default=None, ge=0, le=1)
    target_type: str | None = None
    target_value: float | None = None
    source: str = Field(min_length=1)
    cost_evidence: str | None = None
    target_evidence: str | None = None
    hours_basis: str | None = None
    job_person_hours: HoursRange | None = None
    job_billable_ratio: float | None = Field(default=None, ge=0, le=1)
    materials_yen: float | None = Field(default=None, ge=0)
    period_label: str = "算定期間"

    @model_validator(mode="after")
    def target_is_single(self):
        if self.target_type not in {"profit_amount", "profit_margin"}:
            return self
        return self


@router.post("/proposals")
def create_proposal(body: R05Create):
    cost_evidence = body.cost_evidence.strip() if body.cost_evidence else None
    target_evidence = body.target_evidence.strip() if body.target_evidence else None
    result = calculate_cost_floor(
        allocable_cost_yen=body.allocable_cost_yen,
        period_total_person_hours=body.period_total_person_hours,
        u_period=body.u_period, target_type=body.target_type, target_value=body.target_value,
    )
    now = datetime.now(timezone.utc)
    period_start = body.period_start if body.period_start else body.effective_from.replace(month=1, day=1)
    period_end = body.period_end
    excluded = []
    if body.materials_yen is not None:
        from backend.models import CostItem, EvidenceStatus
        excluded = [CostItem(cost_id="separately_billed_materials", label="別請求の部品・材料費",
                             amount_yen=body.materials_yen, period=body.period_label, source=body.source,
                             evidence_status=EvidenceStatus.entered, billing_class="separately_billed_item",
                             included_in_labor_pool=False, excluded_reason="別請求のため労務原価から除外")]
    proposal = RateProposal(
        module_id=MODULE_ID, period_start=period_start, period_end=period_end,
        effective_from=body.effective_from, allocable_cost_yen=body.allocable_cost_yen,
        period_total_person_hours=body.period_total_person_hours, u_period=body.u_period,
        hours_basis=body.hours_basis, job_person_hours=body.job_person_hours,
        job_billable_ratio=body.job_billable_ratio,
        costs=excluded,
        source=body.source,
        notes=f"R05 selected target={body.target_type}; value={body.target_value}; cost_evidence={cost_evidence}; target_evidence={target_evidence}",
        evidence=[
            Evidence(label="期間配賦原価", value=body.allocable_cost_yen, unit="円/期間", status="entered" if body.allocable_cost_yen is not None and cost_evidence else "unknown", source=body.source, recorded_at=now, notes=cost_evidence),
            Evidence(label="期間人時と請求可能割合", value=f"{body.period_total_person_hours} × {body.u_period}", unit="人時 × 割合", status="entered" if body.period_total_person_hours is not None and body.u_period is not None else "unknown", source=body.source, recorded_at=now, notes="期間分母 H_period_bill = period_total_person_hours × u_period。案件比率は適用しない"),
            Evidence(label="選択した目標利益", value=body.target_value, unit="円/期間" if body.target_type == "profit_amount" else "売上比率", status="entered" if body.target_value is not None and target_evidence else "unknown", source=body.source, recorded_at=now, notes=f"選択方式: {body.target_type}; {target_evidence}"),
        ],
    )
    # Factory rate is withheld whenever any required evidence is missing.
    blockers = list(result["blockers"])
    if not cost_evidence:
        blockers.append("配賦原価の根拠が必要です")
    if not target_evidence:
        blockers.append("目標利益の根拠が必要です")
    basis = [
        BasisRow(label="期間配賦原価", value=body.allocable_cost_yen, unit="円/期間"),
        BasisRow(label="期間総労働人時", value=body.period_total_person_hours, unit="人時/期間"),
        BasisRow(label="期間請求可能割合 u_period", value=body.u_period, unit="割合"),
        BasisRow(label="H_period_bill", value=result["denominator_person_hours"], unit="請求可能人時/期間"),
        BasisRow(label="原価下限単価", value=result["cost_rate"], unit="円/人時"),
        BasisRow(label="目標利益方式", value=body.target_type, unit="方式"),
        BasisRow(label="目標利益値", value=body.target_value, unit="円/期間" if body.target_type == "profit_amount" else "売上比率"),
        BasisRow(label="採用候補の式", value=result["formula"], unit="式"),
        BasisRow(label="計算候補単価", value=result["candidate_yen_per_person_hour"], unit="円/人時"),
    ]
    if body.materials_yen is not None:
        basis.append(BasisRow(label="別請求材料費（除外）", value=body.materials_yen, unit="円"))
    if body.hours_basis == "total_person_hours" and body.job_billable_ratio is None and body.job_person_hours:
        blockers.append("案件の時間基準が総人時の場合、案件比率が必要です")
    job_result = None
    job_unknowns = []
    if body.job_person_hours is not None:
        if body.hours_basis == "billable_person_hours":
            job_result = body.job_person_hours
        elif body.hours_basis == "total_person_hours" and body.job_billable_ratio is not None:
            from backend.models import HoursRange
            job_result = HoursRange(**{key: value * body.job_billable_ratio
                                       for key, value in body.job_person_hours.model_dump().items()})
        else:
            job_unknowns.append("hours_basis" if body.hours_basis is None else "job_billable_ratio")
    calc = RateCalculation(
        status=RateStatus.blocked if blockers else RateStatus.draft,
        candidate_yen_per_person_hour=None if blockers else result["candidate_yen_per_person_hour"],
        denominator_person_hours=result["denominator_person_hours"], hours_basis=body.hours_basis,
        u_period=body.u_period, job_billable_ratio=body.job_billable_ratio,
        job_unknowns=job_unknowns,
        job_billable_person_hours=job_result,
        unknowns=sorted(set(blockers)), excluded_items=excluded, basis=basis,
    )
    return store.create_proposal(proposal, module_calculation=calc)


@router.get("/proposals/{proposal_id}")
def get_r05_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "R05 proposal not found")
    return store.get_proposal(proposal_id)
