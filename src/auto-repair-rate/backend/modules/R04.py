"""R04 manually entered comparison reference; it cannot issue labor rates."""
from datetime import date, datetime, timezone

from fastapi import APIRouter
from pydantic import ConfigDict, Field

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r04_benchmark_reference import BenchmarkInput, calculate_benchmark

MODULE_ID = "R04"
router = APIRouter(tags=["R04 benchmark reference"])


class R04ReferenceCreate(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    effective_from: date
    amount: float
    currency: str = Field(min_length=1, max_length=8)
    amount_type: str
    hours_basis: str | None = None
    documented_person_hours: float | None = Field(default=None, gt=0)
    conditions: str = Field(min_length=1)
    source_url: str | None = None
    source_text: str = Field(min_length=1)
    retrieved_at: date
    permission_status: str
    job_hours_basis: str | None = None
    job_billable_ratio: float | None = Field(default=None, ge=0, le=1)


@router.post("/proposals")
def create_reference(body: R04ReferenceCreate):
    result = calculate_benchmark(BenchmarkInput(
        amount=body.amount, currency=body.currency, amount_type=body.amount_type,
        hours_basis=body.hours_basis, documented_person_hours=body.documented_person_hours,
        permission_status=body.permission_status, source_url=body.source_url,
        source_text=body.source_text, conditions=body.conditions,
    ))
    # Persist through the shared append-only store as permanently blocked from
    # the factory-rate approval flow. References are not RateCalculation candidates.
    notes = (f"R04 external reference only; retrieved_at={body.retrieved_at}; "
             f"conditions={body.conditions}; permission_status={body.permission_status}; "
             f"amount_type={body.amount_type}; hours_basis={body.hours_basis}; "
             f"job_hours_basis={body.job_hours_basis}; job_billable_ratio={body.job_billable_ratio}; "
             f"source_text={body.source_text}")
    proposal = RateProposal(
        module_id=MODULE_ID, period_start=body.period_start, period_end=None,
        effective_from=body.effective_from, allocable_cost_yen=None,
        period_total_person_hours=None, u_period=None, hours_basis=None,
        job_person_hours=None, job_billable_ratio=None, costs=[], source=body.source_url or "manual source text",
        notes=notes,
        evidence=[Evidence(label="手入力した外部比較資料", value=body.amount, unit=body.currency,
                           status="entered", source=body.source_url or body.source_text,
                           recorded_at=datetime.now(timezone.utc),
                           notes=f"資料確認日 {body.retrieved_at}。比較専用。"),
                  Evidence(label="人時・範囲・利用条件", value=body.documented_person_hours,
                           unit=body.hours_basis or "未確認", status="entered" if result.available else "unknown",
                           source=body.source_url or body.source_text,
                           recorded_at=datetime.now(timezone.utc), notes=notes)],
    )
    basis = list(result.basis)
    basis.extend([
        BasisRow(label="比較元", value=body.source_url or body.source_text, unit="URLまたは資料名"),
        BasisRow(label="資料確認日", value=body.retrieved_at.isoformat(), unit="日付"),
        BasisRow(label="記録上の適用開始日", value=body.effective_from.isoformat(), unit="日付"),
        BasisRow(label="比較条件", value=body.conditions, unit="条件"),
    ])
    if result.reason:
        basis.append(BasisRow(label="参考不可の理由", value=result.reason, unit="確認事項"))
    calculation = RateCalculation(status=RateStatus.blocked, candidate_yen_per_person_hour=None,
                                  unknowns=["R04_reference_is_not_factory_rate"], basis=basis)
    return store.create_proposal(proposal, module_calculation=calculation)


@router.get("/proposals/{proposal_id}")
def get_reference(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        from fastapi import HTTPException
        raise HTTPException(404, "R04 reference not found")
    return store.get_proposal(proposal_id)
