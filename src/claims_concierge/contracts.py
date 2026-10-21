from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceReference(WireModel):
    documentId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page: StrictInt = Field(ge=1, le=9999)


class ProposedFacts(WireModel):
    # Unknown values must be explicit nulls. None of these authorizes an action.
    documentedTherapyWeeks: StrictInt | None = Field(ge=0, le=104)
    ptSessionsPerWeek: StrictInt | None = Field(ge=0, le=14)
    ptModalityPresent: StrictBool | None
    pharmaPresent: StrictBool | None
    treatmentFailedOrWorsened: StrictBool | None


class EvaluationRequest(WireModel):
    schemaVersion: Literal["1.0"]
    claimId: str = Field(pattern=r"^[A-Z0-9-]{3,80}$")
    memberId: str = Field(pattern=r"^[A-Z0-9-]{3,80}$")
    cptCode: str = Field(pattern=r"^[0-9]{5}$")
    policyNumber: str = Field(pattern=r"^[A-Z0-9-]{3,80}$")
    policyVersion: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    claimVersion: StrictInt = Field(ge=1)
    correlationId: UUID
    idempotencyKey: UUID
    evidenceReferences: list[EvidenceReference] = Field(min_length=1, max_length=20)
    proposedFacts: ProposedFacts
    clinicalSummary: str = Field(max_length=2000)
    agentRecommendation: Literal[
        "RecommendHumanReview", "RequestAdditionalInformation", "EscalateMedicalDirector"
    ]


class DecisionRequest(WireModel):
    schemaVersion: Literal["1.0"]
    evaluationId: UUID
    evaluationVersion: StrictInt = Field(ge=1)
    approvalId: UUID
    claimVersion: StrictInt = Field(ge=1)
    decision: Literal["ApproveAuthorization", "DenyClaim", "RequestAdditionalInformation", "Escalate"]
    reason: str = Field(min_length=10, max_length=500)


@dataclass(frozen=True)
class TrustedContext:
    """Out-of-band identity, never parsed from the agent JSON.

    This local harness supplies simulated contexts. A real flow must bind these
    values to authenticated platform/Approvals output and authorization records.
    Creating this dataclass is not an authentication mechanism.
    """
    tenant_id: str
    object_id: str
    authenticated: bool
    capabilities: frozenset[str]


class BoundaryError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
