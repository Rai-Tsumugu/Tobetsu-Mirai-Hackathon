"""R30 evidence completeness card. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from math import isclose
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R30"
router = APIRouter(tags=["R30 evidence completeness"])

class EvidenceItem(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    key: Literal["cost", "billable_hours"]
    label: str = Field(min_length=1)
    status: Literal["confirmed", "assumed", "unknown"]
    source: str = Field(min_length=1)
    confirmed_at: date | None = None
    value: float | str | None = None
    unit: str = ""

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    required_denominator: float | None = Field(default=None, ge=0)
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    approval_state: Literal["candidate", "approved", "unknown"] = "candidate"
    materials_excluded: bool = False


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    required=["cost", "billable_hours"]
    if not body.materials_excluded: blockers.append("別請求材料費を算定対象費用から除外したことを確認してください")
    for key in required:
        matches=[item for item in body.evidence_items if item.key==key]
        valid=bool(matches and matches[0].status=="confirmed" and matches[0].source and matches[0].confirmed_at)
        if not valid: blockers.append(f"根拠不足: {key} は状態・出典・確認日が必要です")
        elif matches[0].value is None: blockers.append(f"根拠不足: {key} の確認済み値が必要です")
        else:
            entered=body.allocable_cost_yen if key=="cost" else body.required_denominator
            if entered is not None:
                try: matches_value=isclose(float(matches[0].value), float(entered), rel_tol=1e-9, abs_tol=1e-9)
                except (TypeError, ValueError): matches_value=False
                if not matches_value: blockers.append(f"確認済み根拠 {key} と算定入力が一致しません")
    for item in body.evidence_items:
        basis.append(BasisRow(label=f"{item.label} [{item.status}] 出典={item.source} 確認日={item.confirmed_at or '未確認'}",value=item.value,unit=item.unit))
    if body.required_denominator is None: blockers.append("必須分母が不明のため算出を停止")
    elif body.required_denominator<=0: blockers.append("必須分母が0のため算出を停止")
    elif body.allocable_cost_yen is None: blockers.append("算定費用が不明です")
    elif not blockers: candidate=body.allocable_cost_yen/body.required_denominator; denominator=body.required_denominator
    basis += [BasisRow(label="根拠充足件数",value=len(body.evidence_items),unit="件"),BasisRow(label="承認状態（信頼度点数は作らない）",value=body.approval_state,unit="status")]
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
