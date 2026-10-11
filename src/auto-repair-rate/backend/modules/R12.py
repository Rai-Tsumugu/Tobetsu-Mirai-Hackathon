"""R12 append-only cost changes. Shared approval creates each new rate version."""
import json
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from backend import store
from backend.models import BasisRow, Evidence, FiniteModel, RateCalculation, RateProposal, RateStatus
from backend.r12_cost_events import calculate_as_of

MODULE_ID = "R12"
router = APIRouter(tags=["R12 cost change events"])


class CostEventCreate(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=1)
    old_amount_yen: float | None = Field(default=None, ge=0)
    new_amount_yen: float = Field(ge=0)
    effective_from: date
    entered_by: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_date: date
    evidence_ref: str = Field(min_length=1)
    notes: str = Field(min_length=1)


class R12Preview(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    base_costs: dict[str, float | None]
    H_period_bill: float | None = Field(default=None, ge=0)
    as_of: date
    period_start: date
    effective_from: date
    source: str = Field(min_length=1)
    source_date: date
    evidence_ref: str = Field(min_length=1)
    evidence_notes: str = Field(min_length=1)
    materials_yen: float | None = Field(default=None, ge=0)


def _init_events():
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS r12_cost_events (
            event_id TEXT PRIMARY KEY, category TEXT NOT NULL, old_amount_yen REAL,
            new_amount_yen REAL NOT NULL, effective_from TEXT NOT NULL, entered_by TEXT NOT NULL,
            source TEXT NOT NULL, source_date TEXT NOT NULL, evidence_ref TEXT NOT NULL,
            notes TEXT NOT NULL, created_at TEXT NOT NULL)""")


def _events():
    _init_events()
    with store.connect() as db:
        rows = db.execute("SELECT * FROM r12_cost_events ORDER BY effective_from,event_id").fetchall()
    return [dict(row) for row in rows]


@router.post("/cost-events")
def append_cost_event(body: CostEventCreate):
    _init_events()
    history = [row for row in _events() if row["category"] == body.category]
    if history:
        latest = max(history, key=lambda row: (row["effective_from"], row["event_id"]))
        if body.effective_from <= date.fromisoformat(latest["effective_from"]):
            raise HTTPException(409, "cost events must be appended in effective-date order")
        if body.old_amount_yen != latest["new_amount_yen"]:
            raise HTTPException(409, "old_amount_yen must match the previous append-only event")
    elif body.old_amount_yen is None:
        raise HTTPException(422, "initial old_amount_yen is required when no earlier event exists")
    event_id = str(uuid4())
    with store.connect() as db:
        db.execute("INSERT INTO r12_cost_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (event_id, body.category, body.old_amount_yen, body.new_amount_yen, body.effective_from.isoformat(),
                    body.entered_by, body.source, body.source_date.isoformat(), body.evidence_ref, body.notes,
                    datetime.now(timezone.utc).isoformat()))
    return {"event_id": event_id, **body.model_dump(mode="json"), "append_only": True}


@router.get("/cost-events")
def list_cost_events():
    return _events()


def _result(body: R12Preview):
    return calculate_as_of(body.base_costs, _events(), body.as_of, body.H_period_bill)


@router.post("/rates/preview")
def preview(body: R12Preview):
    return _result(body)


@router.post("/proposals")
def create_proposal(body: R12Preview):
    result = _result(body)
    now = datetime.now(timezone.utc)
    events = {row["event_id"]: row for row in _events()}
    basis = [BasisRow(label="対象費用期間", value=f"{body.period_start}〜{body.as_of.isoformat()}", unit="期間"),
             BasisRow(label="変更適用日", value=body.effective_from.isoformat(), unit="日付"),
             BasisRow(label="計算基準日", value=body.as_of.isoformat(), unit="日付"),
             BasisRow(label="基準日までの変動費イベント", value=json.dumps(result["applied_event_ids"]), unit="event_ids"),
             BasisRow(label="基準日時点費用", value=json.dumps(result["costs_as_of_yen"], ensure_ascii=False), unit="円"),
             BasisRow(label="費用合計", value=result["total_cost_yen"], unit="円/期間"),
             BasisRow(label="請求可能人時", value=body.H_period_bill, unit="人時/期間"),
             BasisRow(label="根拠資料日・参照", value=f"{body.source_date} / {body.evidence_ref}", unit="source_ref"),
             BasisRow(label="イベント履歴", value=json.dumps([{k: v for k, v in events[i].items() if k in {"event_id", "category", "old_amount_yen", "new_amount_yen", "effective_from", "entered_by"}} for i in result["applied_event_ids"]], ensure_ascii=False), unit="append_only")]
    excluded = []
    materials_from_history = sum(value or 0 for value in result["excluded_materials_as_of_yen"].values())
    materials_total = materials_from_history + (body.materials_yen or 0)
    if materials_total:
        from backend.models import CostItem
        excluded = [CostItem(cost_id="separately_billed_materials", label="別請求の部品・材料費", amount_yen=materials_total,
                             period=body.as_of.isoformat(), source=body.source, evidence_status="assumed" if "架空" in body.source else "entered",
                             billing_class="separately_billed_item", included_in_labor_pool=False)]
    evidence = [Evidence(label="費用イベント履歴と分母", value=body.evidence_notes, unit="説明", status="assumed" if "架空" in body.source else "entered",
                         source=body.source, evidence_ref=body.evidence_ref, recorded_at=now, notes="イベントは追記のみ。適用後も旧イベントを保持")]
    proposal = RateProposal(module_id=MODULE_ID, period_start=body.period_start, effective_from=body.effective_from,
                            allocable_cost_yen=result["total_cost_yen"], period_total_person_hours=body.H_period_bill,
                            u_period=1 if body.H_period_bill is not None else None, costs=excluded, evidence=evidence,
                            source=body.source, notes=f"cost_event_as_of={body.as_of}")
    blockers = result["blockers"]
    calc = RateCalculation(status=RateStatus.blocked if blockers else RateStatus.draft,
                           candidate_yen_per_person_hour=result["candidate_yen_per_person_hour"] if not blockers else None,
                           denominator_person_hours=body.H_period_bill, u_period=1 if body.H_period_bill else None,
                           unknowns=blockers, excluded_items=excluded, basis=basis)
    return store.create_proposal(proposal, module_calculation=calc)
