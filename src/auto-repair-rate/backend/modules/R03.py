"""R03 salary-multiplier candidate endpoint using the shared proposal store."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict

from backend import store
from backend.models import Evidence, FiniteModel, RateProposal
from backend.r03_salary_multiplier import calculate_salary_multiplier

MODULE_ID = "R03"
router = APIRouter(tags=["R03 salary multiplier"])


class R03ProposalCreate(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    proposal: RateProposal
    daily_pay_yen: float | None = None
    paid_days_per_year: float | None = None
    approved_multiplier: float | None = None
    multiplier_approved_by: str | None = None
    salary_basis_acknowledged: bool = False


@router.post("/proposals")
def create_proposal(body: R03ProposalCreate):
    proposal = body.proposal
    if proposal.module_id != MODULE_ID:
        raise HTTPException(422, "module_id must be R03")
    recorded_at = datetime.now(timezone.utc)
    proposal.evidence.extend([
        Evidence(label="給与倍率方式の説明同意", value=body.salary_basis_acknowledged,
                 unit="確認", status="entered", source="R03 proposal input", recorded_at=recorded_at,
                 notes="給与倍率は正式原価式・一般相場ではなく比較用目安候補"),
        Evidence(label="倍率承認者", value=body.multiplier_approved_by,
                 unit="社長承認", status="entered" if body.multiplier_approved_by else "unknown",
                 source="R03 proposal input", recorded_at=recorded_at,
                 notes="この工場で使う倍率の設定者"),
    ])
    for label, value, unit in [
        ("日給", body.daily_pay_yen, "円/日"),
        ("年間支給日数", body.paid_days_per_year, "日/年"),
        ("承認済み給与倍率", body.approved_multiplier, "倍"),
    ]:
        proposal.evidence.append(Evidence(
            label=label, value=value, unit=unit,
            status="entered" if value is not None else "unknown", source="R03 proposal input",
            recorded_at=recorded_at,
            notes="入力値。3倍は録音中の社長目安を示す架空初期例で一般相場ではない。" if label == "承認済み給与倍率" else None,
        ))
    proposal.source = proposal.source or "R03 salary multiplier input"
    calculation = calculate_salary_multiplier(
        proposal, body.daily_pay_yen, body.paid_days_per_year, body.approved_multiplier,
        body.multiplier_approved_by, body.salary_basis_acknowledged,
    )
    return store.create_proposal(proposal, module_calculation=calculation)
