"""Shared calculations and isolated R-module discovery contract."""
from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from pathlib import Path
from fastapi import APIRouter

from .models import HoursBasis, RateCalculation, RateProposal, RateStatus
from .models import HoursRange


def calculate(proposal: RateProposal) -> RateCalculation:
    unknowns: list[str] = []
    # Reconcile entered costs only when every pool item has a known value. Never
    # infer missing items as zero; the explicit aggregate can stand alone.
    included_costs = [c for c in proposal.costs if c.included_in_labor_pool]
    excluded = [c for c in proposal.costs if not c.included_in_labor_pool]
    if any(c.amount_yen is None or c.evidence_status.value == "unknown" for c in included_costs):
        unknowns.append("included_cost_amount_or_source")
    cost = proposal.allocable_cost_yen
    included_sum = sum(c.amount_yen or 0 for c in included_costs)
    if cost is None and included_costs and not unknowns:
        cost = included_sum
    elif cost is not None and included_costs and not unknowns and cost != included_sum:
        unknowns.append("allocable_cost_does_not_match_included_cost_items")
    if cost is None:
        unknowns.append("allocable_cost_yen")
    if cost is not None and not proposal.evidence and not included_costs:
        unknowns.append("allocable_cost_evidence")

    total_hours = proposal.period_total_person_hours
    if total_hours is None:
        unknowns.append("total_person_hours")
    u = proposal.u_period
    if u is None:
        unknowns.append("u_period")
    denominator: float | None = None
    if total_hours is not None and u is not None:
        # u_period belongs to the period denominator and is always applied once.
        denominator = total_hours * u
    if denominator is not None and denominator <= 0:
        unknowns.append("required_denominator_is_zero")
    elif denominator is None:
        unknowns.append("required_denominator_unknown")

    job_unknowns: list[str] = []
    job_billable_hours: dict[str, float] | None = None
    if proposal.job_person_hours is not None:
        if proposal.hours_basis is None:
            job_unknowns.append("hours_basis")
        elif proposal.hours_basis == HoursBasis.billable_person_hours:
            # Already billable: pass through and do not apply the job ratio.
            job_billable_hours = proposal.job_person_hours.model_dump()
        elif proposal.job_billable_ratio is None:
            job_unknowns.append("job_billable_ratio")
        else:
            # Convert each bound exactly once. This does not change period capacity.
            ratio = Decimal(str(proposal.job_billable_ratio))
            job_billable_hours = {band: float(Decimal(str(hours)) * ratio)
                                  for band, hours in proposal.job_person_hours.model_dump().items()}
    else:
        job_unknowns.append("job_person_hours")

    candidate = None
    if not unknowns and cost is not None and denominator is not None:
        candidate = cost / denominator
    status = RateStatus.draft if candidate is not None else RateStatus.blocked
    basis: list[dict[str, Any]] = []
    if cost is not None:
        basis.append({"label": "配賦費用合計", "value": cost, "unit": "円/期間"})
    if total_hours is not None:
        basis.append({"label": "期間総労働人時", "value": total_hours, "unit": "人時/期間"})
    if u is not None:
        basis.append({"label": "期間請求可能割合 u_period", "value": u, "unit": "割合"})
    if denominator is not None:
        basis.append({"label": "算定分母", "value": denominator, "unit": "請求可能人時/期間"})
    # Excluded item evidence is returned separately, not added to the fixed labor_rate basis contract.
    return RateCalculation(status=status, candidate_yen_per_person_hour=candidate,
                           denominator_person_hours=denominator, hours_basis=proposal.hours_basis,
                           u_period=u,
                           job_billable_person_hours=(HoursRange(**job_billable_hours) if job_billable_hours else None),
                           job_unknowns=job_unknowns, job_billable_ratio=proposal.job_billable_ratio,
                           unknowns=sorted(set(unknowns)), excluded_items=excluded, basis=basis)


def discover_module_routers() -> list[tuple[str, APIRouter]]:
    """Load optional backend.modules.Rxx files exposing MODULE_ID and router.

    Each R implementation owns a standalone module and can be added without
    changing the shared API or other R implementations.
    """
    root = Path(__file__).parent / "modules"
    discovered = []
    if not root.is_dir():
        return discovered
    for file in sorted(root.glob("R[0-9][0-9].py")):
        mod = import_module(f"backend.modules.{file.stem}")
        module_id: str = getattr(mod, "MODULE_ID", file.stem)
        router: Any = getattr(mod, "router", None)
        if isinstance(router, APIRouter):
            discovered.append((module_id, router))
    return discovered
