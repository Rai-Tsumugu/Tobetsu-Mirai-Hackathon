"""R20 worker internal cost. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R20"
router = APIRouter(tags=["R20 worker internal cost"])

class WorkerInput(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    annual_cost_yen: float | None = Field(default=None, ge=0)
    annual_billable_hours: float | None = Field(default=None, ge=0)

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    workers: list[WorkerInput] = Field(min_length=1)
    job_hours_by_worker: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def worker_ids_are_unique(self):
        worker_ids = [worker.id for worker in self.workers]
        if len(worker_ids) != len(set(worker_ids)):
            raise ValueError("worker IDs must be unique; duplicate anonymous worker IDs are not allowed")
        return self


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    total_cost=0.0; total_hours=0.0; job_cost=0.0; job_hours=0.0
    worker_ids={worker.id for worker in body.workers}
    if set(body.job_hours_by_worker) != worker_ids: blockers.append("案件人時は登録済み匿名作業者全員分を指定してください")
    if any(value < 0 for value in body.job_hours_by_worker.values()): blockers.append("作業者別案件人時に負数は指定できません")
    for worker in body.workers:
        wid=worker.id; wage=worker.annual_cost_yen; hours=worker.annual_billable_hours
        if not wid or wage is None or hours is None or hours <= 0:
            blockers.append("匿名作業者ID・年間原価・正の請求可能人時が必要です"); continue
        total_cost += float(wage); total_hours += float(hours)
        assigned=body.job_hours_by_worker.get(wid)
        if assigned is not None:
            job_hours += assigned; job_cost += assigned * float(wage)/float(hours)
        basis.append(BasisRow(label=f"匿名作業者 {wid} 年間原価",value=wage,unit="円/年"))
    if not body.job_hours_by_worker: blockers.append("内部原価の作業者別案件人時が不明です")
    if total_hours <= 0: blockers.append("作業者の年間請求可能人時が0です")
    if not blockers:
        candidate=job_cost/job_hours if job_hours>0 else None; denominator=job_hours
        if candidate is None: blockers.append("案件人時が0のため停止")
    basis += [BasisRow(label="作業者加重内部原価",value=candidate,unit="円/人時"),BasisRow(label="案件作業者人時",value=job_hours,unit="人時"),BasisRow(label="氏名・給与明細は保存せず匿名IDのみ",value="内部専用",unit="privacy")]
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
    return store.create_proposal(proposal, module_calculation=calc, rate_scope=(f"worker:{body.workers[0].id}" if len(body.workers)==1 else "worker:combined"), rate_type="internal")

@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    with store.connect() as db:
        row = db.execute("SELECT module_id FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None or row["module_id"] != MODULE_ID:
        raise HTTPException(404, "module proposal not found")
    return store.get_proposal(proposal_id)
