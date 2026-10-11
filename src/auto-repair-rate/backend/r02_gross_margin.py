"""R02 gross-margin labor-rate calculation, separate from markup."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .models import BasisRow, RateCalculation, RateProposal, RateStatus
from .shared import calculate as calculate_shared


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a finite number") from None
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return result


def calculate_gross_margin(
    proposal: RateProposal, gross_margin: Any, *, payroll_nonduplicated: bool = False,
) -> RateCalculation:
    """Calculate candidate = cost per billable period hour / (1 - margin).

    The margin is gross profit divided by selling revenue, never a markup on
    cost. Cost evidence and the shared period denominator must be complete.
    """
    blockers: list[str] = []
    if not payroll_nonduplicated:
        blockers.append("payroll_nonduplicated_confirmation_required")
    try:
        margin = _decimal(gross_margin, "gross_margin")
        if margin < 0 or margin >= 1:
            blockers.append("gross_margin_must_be_at_least_0_and_less_than_1")
    except ValueError:
        margin = Decimal(0)
        blockers.append("gross_margin_must_be_finite")

    included_costs = [item for item in proposal.costs if item.included_in_labor_pool]
    if not proposal.evidence or all(item.status.value == "unknown" or not item.source for item in proposal.evidence):
        blockers.append("allocable_cost_evidence")
    seen_ids: set[str] = set()
    for item in proposal.costs:
        if not item.cost_id or item.cost_id in seen_ids:
            blockers.append("cost_ids_must_be_unique")
        seen_ids.add(item.cost_id)
    if proposal.allocable_cost_yen is None:
        blockers.append("allocable_cost_yen")
    elif proposal.allocable_cost_yen <= 0:
        blockers.append("allocable_cost_must_be_greater_than_zero")

    if included_costs:
        if any(item.amount_yen is None or item.evidence_status.value == "unknown" for item in included_costs):
            blockers.append("included_cost_amount_or_evidence_unknown")
        if any(not item.source for item in included_costs):
            blockers.append("included_cost_source_missing")
        if all(item.amount_yen is not None for item in included_costs) and proposal.allocable_cost_yen is not None:
            if sum(Decimal(str(item.amount_yen)) for item in included_costs) != Decimal(str(proposal.allocable_cost_yen)):
                blockers.append("allocable_cost_does_not_match_included_cost_items")

    shared = calculate_shared(proposal)
    blockers.extend(shared.unknowns)
    candidate: float | None = None
    cost_per_hour: Decimal | None = None
    if not blockers and proposal.allocable_cost_yen is not None and shared.denominator_person_hours is not None:
        denominator = Decimal(str(shared.denominator_person_hours))
        if denominator <= 0:
            blockers.append("required_denominator_is_zero")
        else:
            cost_per_hour = Decimal(str(proposal.allocable_cost_yen)) / denominator
            candidate = float(cost_per_hour / (Decimal(1) - margin))

    result = shared.model_copy(deep=True)
    result.status = RateStatus.blocked if blockers else RateStatus.draft
    result.candidate_yen_per_person_hour = candidate if not blockers else None
    result.unknowns = sorted(set(blockers))
    result.basis = [row for row in result.basis if row.label not in {"粗利率", "請求可能人時あたり原価", "粗利率反映式"}]
    result.basis.append(BasisRow(label="粗利率", value=float(margin), unit="売上高に対する粗利益の割合"))
    if cost_per_hour is not None:
        result.basis.append(BasisRow(label="請求可能人時あたり原価", value=float(cost_per_hour), unit="円/人時"))
    result.basis.append(BasisRow(label="粗利率反映式", value="c / (1 - m)", unit="円/人時"))
    return result
