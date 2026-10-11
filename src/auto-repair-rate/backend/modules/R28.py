"""R28 annual winter comparison. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R28"
router = APIRouter(tags=["R28 annual and winter scenarios"])

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
    winter_heating_yen: float | None = Field(default=None, ge=0)
    winter_billable_hours: float | None = Field(default=None, ge=0)
    selected_scenario: Literal["annual", "winter"] = "annual"


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    annual=None; winter=None; winter_unknowns=[]
    if body.annual_cost_yen is None or body.annual_billable_hours is None: blockers.append("通年費用と請求可能人時が必要です")
    elif body.annual_billable_hours<=0: blockers.append("年間請求可能人時が0です")
    else: annual=body.annual_cost_yen/body.annual_billable_hours
    if body.winter_heating_yen is not None:
        if body.winter_billable_hours is None: winter_unknowns.append("冬季請求可能人時が不明のため冬季案は保留")
        elif body.winter_billable_hours<=0: winter_unknowns.append("冬季請求可能人時が0です")
        elif annual is not None: winter=annual+body.winter_heating_yen/body.winter_billable_hours
    basis += [BasisRow(label="通年基準",value=annual,unit="円/人時"),BasisRow(label="冬季追加案（既定で未適用）",value=winter,unit="円/人時"),BasisRow(label="冬季案の不足根拠",value="; ".join(winter_unknowns) or "なし",unit="review"),BasisRow(label="通年と冬季の差",value=(winter-annual if winter is not None and annual is not None else None),unit="円/人時"),BasisRow(label="選択案",value=body.selected_scenario,unit="scenario"),BasisRow(label="冬季案は顧客受容を別途確認",value=True,unit="review")]
    if body.selected_scenario=="winter": blockers.extend(winter_unknowns)
    if body.selected_scenario=="winter" and winter is None: blockers.append("冬季案に必要な根拠が不足しています")
    elif not blockers: candidate=winter if body.selected_scenario=="winter" else annual; denominator=body.winter_billable_hours if body.selected_scenario=="winter" else body.annual_billable_hours
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
    return store.create_proposal(proposal, module_calculation=calc, rate_scope=("factory_standard" if body.selected_scenario == "annual" else "season:winter"), rate_type="customer")

@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "module proposal not found")
    return store.get_proposal(proposal_id)
