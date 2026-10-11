"""R29 current versus candidate impact. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus, HoursRange

MODULE_ID = "R29"
router = APIRouter(tags=["R29 delta and range review"])

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    current_rate_yen: float | None = Field(default=None, ge=0)
    candidate_rate_yen: float | None = Field(default=None, ge=0)
    job_billable_hours: HoursRange | None = None
    period_utilization: float | None = Field(default=None, ge=0, le=1)


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    if body.current_rate_yen is None or body.candidate_rate_yen is None: blockers.append("現行単価と候補単価が必要です")
    if body.job_billable_hours is None: blockers.append("low/typical/high別の請求人時が必要です")
    if not blockers:
        for band,hours in body.job_billable_hours.model_dump().items():
            delta=(body.candidate_rate_yen-body.current_rate_yen)*hours
            basis.append(BasisRow(label=f"{band} 工賃差額（期間比率を重ねない）",value=delta,unit="円"))
        candidate=body.candidate_rate_yen; denominator=1
    basis += [BasisRow(label="現行単価",value=body.current_rate_yen,unit="円/人時"),BasisRow(label="候補単価",value=body.candidate_rate_yen,unit="円/人時"),BasisRow(label="請求可能人時 low/typical/high",value=(str(body.job_billable_hours.model_dump()) if body.job_billable_hours else None),unit="人時"),BasisRow(label="期間稼働率は案件差額に適用しない",value=body.period_utilization,unit="u_period（参考のみ）")]
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
    # A comparison scenario is informational and must never enter approved customer-rate history.
    return {"module_id": MODULE_ID, "status": "blocked" if blockers else "draft",
            "rate_scope": "comparison_only", "rate_type": "customer",
            "candidate_yen_per_person_hour": candidate, "unknowns": blockers,
            "basis": [row.model_dump() for row in basis], "persisted": False}
