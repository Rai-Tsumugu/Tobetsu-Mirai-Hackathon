"""R19 factory standard rate. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R19"
router = APIRouter(tags=["R19 factory standard as-of history"])

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    annual_cost_yen: float | None = Field(default=None, ge=0)
    annual_billable_hours: float | None = Field(default=None, ge=0)
    valid_from: date


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    if body.valid_from != body.effective_from: blockers.append("候補の適用日と有効開始日を一致させてください")
    if body.annual_cost_yen is None: blockers.append("年間配賦費用が不明です")
    if body.annual_billable_hours is None: blockers.append("年間請求可能人時が不明です")
    if body.annual_billable_hours is not None and body.annual_billable_hours <= 0: blockers.append("年間請求可能人時が0のため停止")
    if not blockers:
        candidate = body.annual_cost_yen / body.annual_billable_hours; denominator=body.annual_billable_hours
    basis += [BasisRow(label="工場標準・有効開始日",value=body.valid_from.isoformat(),unit="日付"), BasisRow(label="年間費用",value=body.annual_cost_yen,unit="円"), BasisRow(label="年間請求可能人時",value=body.annual_billable_hours,unit="人時"), BasisRow(label="根拠更新日",value=body.source_date.isoformat(),unit="日付")]
    return blockers, basis, candidate, denominator

@router.post("/rates/preview")
def preview(body: Input):
    blockers, basis, candidate, denominator = _result(body)
    return {"status": "blocked" if blockers else "draft", "candidate_yen_per_person_hour": candidate,
            "denominator_person_hours": denominator, "blockers": blockers,
            "basis": [row.model_dump() for row in basis]}

@router.post("/proposals")
def create_proposal(body: Input):
    blockers, basis, candidate, denominator = _result(body)
    now = datetime.now(timezone.utc)
    evidence = [Evidence(label="入力根拠", value=body.evidence_notes, unit="説明",
                         status="assumed" if "架空" in body.source else "factory_reported",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now,
                         notes=f"原資料日={body.source_date}")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, effective_from=body.effective_from,
                            allocable_cost_yen=(candidate * denominator if candidate is not None and denominator else None),
                            period_total_person_hours=denominator, u_period=1 if denominator else None,
                            evidence=evidence, source=body.source, notes="候補はサーバー側で算出。別請求材料費は含まない。")
    calc = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft,
                           candidate_yen_per_person_hour=candidate if not blockers else None,
                           denominator_person_hours=denominator, u_period=1 if denominator else None,
                           unknowns=blockers, basis=basis)
    return store.create_proposal(proposal, module_calculation=calc, rate_scope="factory_standard", rate_type="customer")

@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "module proposal not found")
    return store.get_proposal(proposal_id)

@router.get("/rates/active")
def active_rate(as_of: date | None = None):
    return store.get_rate_as_of(as_of or date.today(), rate_scope="factory_standard", rate_type="customer")
