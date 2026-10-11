"""R23 review calendar. Server-side calculations with auditable evidence."""
from datetime import date, datetime, timezone
import calendar
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field, model_validator
from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus

MODULE_ID = "R23"
router = APIRouter(tags=["R23 review reminders"])

class Input(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    source_date: date
    effective_from: date
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    capacity_person_hours: float | None = Field(default=None, ge=0)
    current_rate_yen: float | None = Field(default=None, gt=0)
    last_review_date: date
    interval_months: int = Field(ge=1, le=24)
    next_review_date: date
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    billable_hours: float | None = Field(default=None, ge=0)


def _result(body: Input):
    blockers: list[str] = []
    basis: list[BasisRow] = []
    candidate = None
    denominator = None
    month_index=body.last_review_date.month - 1 + body.interval_months
    year=body.last_review_date.year + month_index // 12
    month=month_index % 12 + 1
    expected=date(year, month, min(body.last_review_date.day, calendar.monthrange(year, month)[1]))
    if body.next_review_date != expected: blockers.append("次回見直し日は前回日付と間隔から算出してください")
    if body.next_review_date < date.today(): blockers.append("定期見直し期日を過ぎています。費用と人時を再確認してください")
    if body.allocable_cost_yen is None or body.billable_hours is None: blockers.append("再試算には費用と請求可能人時の両方が必要です")
    elif body.billable_hours<=0: blockers.append("請求可能人時が0です")
    elif not blockers: candidate=body.allocable_cost_yen/body.billable_hours; denominator=body.billable_hours
    basis += [BasisRow(label="前回見直し",value=body.last_review_date.isoformat(),unit="日付"),BasisRow(label="見直し間隔",value=body.interval_months,unit="月"),BasisRow(label="次回見直し",value=body.next_review_date.isoformat(),unit="日付"),BasisRow(label="現行単価（自動変更なし）",value=body.current_rate_yen,unit="円/人時"),BasisRow(label="期日到来時は再計算を促すのみ",value=body.next_review_date<=date.today(),unit="reminder")]
    basis.append(BasisRow(label="期間能力人時（見直しフォームの確認値）",value=body.capacity_person_hours,unit="人時"))
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

class Schedule(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    last_review_date: date
    interval_months: int = Field(ge=1, le=24)
    next_review_date: date
    capacity_person_hours: float = Field(gt=0)
    source: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def next_date_matches_interval(self):
        month_index = self.last_review_date.month - 1 + self.interval_months
        year = self.last_review_date.year + month_index // 12
        month = month_index % 12 + 1
        expected = date(year, month, min(self.last_review_date.day, calendar.monthrange(year, month)[1]))
        if self.next_review_date != expected:
            raise ValueError("次回見直し日は前回日付と間隔から算出してください")
        return self

@router.post("/schedule")
def save_schedule(body: Schedule):
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS r23_schedule (schedule_id INTEGER PRIMARY KEY, payload_json TEXT NOT NULL, saved_at TEXT NOT NULL)")
        db.execute("INSERT INTO r23_schedule(payload_json,saved_at) VALUES(?,?)", (body.model_dump_json(), datetime.now(timezone.utc).isoformat()))
    return {"saved": True, "schedule": body}

@router.get("/schedule")
def get_schedule():
    import json
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS r23_schedule (schedule_id INTEGER PRIMARY KEY, payload_json TEXT NOT NULL, saved_at TEXT NOT NULL)")
        row=db.execute("SELECT payload_json,saved_at FROM r23_schedule ORDER BY schedule_id DESC LIMIT 1").fetchone()
    return ({"schedule": json.loads(row["payload_json"]), "saved_at": row["saved_at"]} if row else None)
