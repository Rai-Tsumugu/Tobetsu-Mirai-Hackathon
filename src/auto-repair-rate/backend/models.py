"""Stable snake_case API and storage models shared by R01-R30 modules."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FiniteModel(BaseModel):
    """Shared Pydantic base that refuses NaN and infinite numeric inputs."""
    model_config = ConfigDict(allow_inf_nan=False)


class EvidenceStatus(str, Enum):
    entered = "entered"
    factory_reported = "factory_reported"
    assumed = "assumed"
    unknown = "unknown"
    terms_unverified = "terms_unverified"


class RateStatus(str, Enum):
    draft = "draft"
    blocked = "blocked"
    approved = "approved"


class HoursBasis(str, Enum):
    total_person_hours = "total_person_hours"
    billable_person_hours = "billable_person_hours"


class Evidence(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: float | str | None = None
    unit: str
    status: EvidenceStatus
    source: str | None = None
    evidence_ref: str | None = None
    recorded_at: datetime
    notes: str | None = None


class BasisRow(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: float | str | None
    unit: str


class HoursRange(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    low: float = Field(ge=0)
    typical: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.typical <= self.high:
            raise ValueError("job hours must satisfy low <= typical <= high")
        return self


class CostItem(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    cost_id: str
    label: str
    amount_yen: float | None = Field(default=None, ge=0)
    period: str
    source: str | None = None
    evidence_status: EvidenceStatus
    billing_class: Literal["labor_pool", "separately_billed_item", "other"]
    included_in_labor_pool: bool
    excluded_reason: str | None = None

    @model_validator(mode="after")
    def separately_billed_is_excluded(self):
        if self.billing_class == "separately_billed_item" and self.included_in_labor_pool:
            raise ValueError("separately billed parts/materials must be excluded from labor_pool")
        if self.billing_class == "separately_billed_item" and not self.excluded_reason:
            self.excluded_reason = "別請求の部品・材料のため労務単価プールから除外"
        return self


class RateProposal(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str | None = None
    module_id: str = "R15"
    period_start: date
    period_end: date | None = None
    effective_from: date
    allocable_cost_yen: float | None = Field(default=None, ge=0)
    period_total_person_hours: float | None = Field(default=None, ge=0)
    u_period: float | None = Field(default=None, ge=0, le=1)
    hours_basis: HoursBasis | None = None
    job_person_hours: HoursRange | None = None
    # Job-only ratio. It never participates in the period rate denominator.
    job_billable_ratio: float | None = Field(default=None, ge=0, le=1)
    costs: list[CostItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    source: str = "manual"
    notes: str | None = None


class RateCalculation(FiniteModel):
    status: RateStatus
    candidate_yen_per_person_hour: float | None = None
    denominator_person_hours: float | None = None
    hours_basis: HoursBasis | None = None
    u_period: float | None = None
    job_billable_person_hours: HoursRange | None = None
    job_unknowns: list[str] = Field(default_factory=list)
    job_billable_ratio: float | None = None
    unknowns: list[str] = Field(default_factory=list)
    excluded_items: list[CostItem] = Field(default_factory=list)
    basis: list[BasisRow] = Field(default_factory=list)


class ApprovalRequest(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    approved_yen_per_person_hour: float = Field(gt=0)
    effective_from: date
    approved_by: str = Field(min_length=1)
    approval_reason: str = Field(min_length=1)


class LaborRate(FiniteModel):
    """Exact shared handoff shape. Present only after explicit human approval."""
    yen_per_person_hour: float = Field(gt=0)
    effective_from: date
    basis: list[BasisRow]


class RateVersion(FiniteModel):
    proposal_id: str
    module_id: str
    rate_scope: str = "factory_standard"
    rate_type: Literal["customer", "internal"] = "customer"
    status: RateStatus
    calculation: RateCalculation
    labor_rate: LaborRate | None = None
    source: str
    evidence: list[Evidence]
    approved_by: str | None = None
    approval_reason: str | None = None
    created_at: datetime


class ProposalCreate(FiniteModel):
    proposal: RateProposal


class ModuleDescriptor(FiniteModel):
    module_id: str
    title: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
