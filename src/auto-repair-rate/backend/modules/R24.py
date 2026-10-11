"""R24 threshold recalculation. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R24"
router = APIRouter(tags=["R24 change thresholds"])

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    metric: Literal["cost", "billable_hours"]
    old_value: float | None = Field(default=None, ge=0)
    new_value: float | None = Field(default=None, ge=0)
    threshold_ratio: float = Field(gt=0, le=1)
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    billable_hours: float | None = Field(default=None, ge=0)


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    if body.old_value is None or body.new_value is None: blockers.append("旧値または新値が不明です。比率判定を停止")
    elif body.old_value<=0: blockers.append("旧値が0のため比率判定を停止。絶対額で人が再確認してください")
    else:
        ratio=abs(body.new_value-body.old_value)/body.old_value
        basis.append(BasisRow(label="変化率",value=ratio,unit="割合")); basis.append(BasisRow(label="設定閾値",value=body.threshold_ratio,unit="割合"))
        if ratio<body.threshold_ratio: blockers.append("変化が閾値未満のため再計算候補を作成しません")
    if body.allocable_cost_yen is None or body.billable_hours is None or body.billable_hours<=0: blockers.append("候補計算には費用と正の請求可能人時が必要です")
    elif not blockers and body.old_value is not None and body.new_value is not None and body.old_value>0 and abs(body.new_value-body.old_value)/body.old_value>=body.threshold_ratio: candidate=body.allocable_cost_yen/body.billable_hours; denominator=body.billable_hours
    basis += [BasisRow(label="監視項目",value=body.metric,unit="metric"),BasisRow(label="旧値",value=body.old_value,unit="円または人時"),BasisRow(label="新値",value=body.new_value,unit="円または人時")]
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
