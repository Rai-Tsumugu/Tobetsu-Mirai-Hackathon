"""R25 approval and history review. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R25"
router = APIRouter(tags=["R25 approval candidate history"])

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    source_proposal_id: str | None = None
    current_rate_yen: float | None = Field(default=None, gt=0)
    approval_reason: str = Field(min_length=1)
    approver_role: Literal["owner_review_required"]


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    version = store.get_proposal(body.source_proposal_id) if body.source_proposal_id else None
    calc = version.calculation if version else None
    candidate = calc.candidate_yen_per_person_hour if calc else None
    denominator = calc.denominator_person_hours if calc else None
    if version is None: blockers.append("既存の保存済み候補を選択してください")
    elif version.status != RateStatus.draft or version.rate_type != "customer" or candidate is None or denominator is None or denominator <= 0:
        blockers.append("選択した提案は未承認の顧客単価候補ではありません")
    basis += [BasisRow(label="参照する保存済み提案ID",value=body.source_proposal_id,unit="proposal_id"),BasisRow(label="承認理由",value=body.approval_reason,unit="説明"),BasisRow(label="適用開始日",value=body.effective_from.isoformat(),unit="日付"),BasisRow(label="候補は未承認のまま",value=True,unit="approval_required"),BasisRow(label="現行単価",value=body.current_rate_yen,unit="円/人時"),BasisRow(label="現行単価との差（人の判断用）",value=(candidate-body.current_rate_yen if candidate is not None and body.current_rate_yen is not None else None),unit="円/人時")]
    return blockers, basis, candidate, denominator

@router.post("/rates/preview")
def preview(body: Input):
    blockers, basis, candidate, denominator = _result(body)
    return {"status": "blocked" if blockers else "draft", "source_proposal_id":body.source_proposal_id, "candidate_yen_per_person_hour": candidate,
            "denominator_person_hours": denominator, "blockers": blockers,
            "basis": [row.model_dump() for row in basis]}

@router.post("/proposals")
def create_proposal(body: Input):
    blockers, _, _, _ = _result(body)
    if blockers: raise HTTPException(409, "; ".join(blockers))
    return store.get_proposal(body.source_proposal_id)

@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "module proposal not found")
    return store.get_proposal(proposal_id)
