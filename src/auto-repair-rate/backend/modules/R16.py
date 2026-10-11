"""R16 role-based labor capacity estimate."""
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import ConfigDict, Field
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r16_capacity import calculate_capacity

MODULE_ID = "R16"
router = APIRouter(tags=["R16 role capacity estimate"])
class Role(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1)
    people: int = Field(ge=1)
    weekly_hours: float = Field(ge=0)
    work_weeks: float = Field(ge=0)
class R16Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[Role] = Field(min_length=1)
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    u_period: float | None = Field(default=None, ge=0, le=1)
    period_start: str = Field(min_length=10); period_end: str = Field(min_length=10); effective_from: str = Field(min_length=10)
    source: str = Field(min_length=1); source_date: str = Field(min_length=10); evidence_ref: str = Field(min_length=1); evidence_notes: str = Field(min_length=1)
def _calc(body):
    rows = [{**row.model_dump(), "weekly_hours": row.weekly_hours * row.people} for row in body.roles]
    return calculate_capacity(rows, body.u_period)
@router.post("/rates/preview")
def preview(body: R16Input):
    result = _calc(body); blockers = list(result["blockers"])
    if body.allocable_cost_yen is None: blockers.append("配賦費用合計が不明です")
    candidate = body.allocable_cost_yen / result["billable_person_hours"] if not blockers and result["billable_person_hours"] else None
    return {**result, "blockers": blockers, "candidate_yen_per_person_hour": candidate}
@router.post("/proposals")
def create_proposal(body: R16Input):
    result = preview(body); now = datetime.now(timezone.utc)
    evidence = [Evidence(label="匿名役割別の勤務計画", value=body.evidence_notes, unit="説明", status="assumed" if "架空" in body.source else "factory_reported", source=body.source, evidence_ref=body.evidence_ref, recorded_at=now, notes=f"資料日={body.source_date}; 計画時間であり実績労務記録ではありません")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, period_end=body.period_end, effective_from=body.effective_from, allocable_cost_yen=body.allocable_cost_yen, period_total_person_hours=result["period_total_person_hours"], u_period=body.u_period, evidence=evidence, source=body.source, notes="役割別概算。非請求時間はu_periodに一度だけ反映")
    basis = [BasisRow(label=f"{r.role}: 人数 × 週時間 × 稼働週", value=r.people * r.weekly_hours * r.work_weeks, unit="人時/期間") for r in body.roles]
    basis += [BasisRow(label="期間総労働人時", value=result["period_total_person_hours"], unit="人時/期間"), BasisRow(label="請求可能割合 u_period", value=body.u_period, unit="割合"), BasisRow(label="請求可能人時", value=result["billable_person_hours"], unit="人時/期間"), BasisRow(label="配賦費用合計", value=body.allocable_cost_yen, unit="円/期間"), BasisRow(label="根拠資料日・参照", value=f"{body.source_date} / {body.evidence_ref}", unit="source_ref")]
    blockers = result["blockers"] + ([] if body.allocable_cost_yen is not None else ["配賦費用合計が不明です"])
    calc = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft, candidate_yen_per_person_hour=result["candidate_yen_per_person_hour"], denominator_person_hours=result["billable_person_hours"], u_period=body.u_period, unknowns=blockers, basis=basis)
    return store.create_proposal(proposal, module_calculation=calc)
