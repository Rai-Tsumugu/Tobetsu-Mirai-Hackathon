"""R02 gross-margin proposal endpoint."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from backend import store
from backend.models import Evidence, FiniteModel, RateProposal
from backend.r02_gross_margin import calculate_gross_margin

MODULE_ID = "R02"
router = APIRouter(tags=["R02 gross margin"])


class R02ProposalCreate(FiniteModel):
    model_config = ConfigDict(extra="forbid")
    proposal: RateProposal
    gross_margin: float = Field(ge=0, lt=1)
    payroll_nonduplicated: bool


@router.post("/proposals")
def create_proposal(body: R02ProposalCreate):
    proposal = body.proposal
    if proposal.module_id != MODULE_ID:
        raise HTTPException(422, "module_id must be R02")
    calculation = calculate_gross_margin(
        proposal, body.gross_margin, payroll_nonduplicated=body.payroll_nonduplicated,
    )
    proposal.evidence.append(Evidence(
        label="R02粗利率入力", value=body.gross_margin,
        unit="売上高に対する粗利益の割合", status="entered",
        source="R02 proposal input", recorded_at=datetime.now(timezone.utc),
        notes="粗利率は粗利益/売上高。原価への上乗せ率ではない。",
    ))
    return store.create_proposal(proposal, module_calculation=calculation)
