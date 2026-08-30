from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Risk = Literal["low", "medium", "high"]
Decision = Literal["auto", "approved", "rejected", "refused", "escalated", "proposed"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class EvidenceRef(BaseModel):
    evidence_id: str
    tool_call_id: str


class Claim(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceRef]
    confirmed: bool = True


class ToolCall(BaseModel):
    tool_call_id: str = Field(default_factory=lambda: f"call_{uuid4().hex[:12]}")
    tool: str
    args: dict[str, Any]
    result_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    duration_ms: float = Field(default=0, ge=0)
    ts: datetime = Field(default_factory=utc_now)


class ActionProposal(BaseModel):
    tool_call_id: str
    tool: str
    args: dict[str, Any]
    args_hash: str
    rationale: str
    risk: Risk
    reversible: bool
    evidence: list[EvidenceRef] = Field(default_factory=list)
    status: Decision = "proposed"


class InvestigationResult(BaseModel):
    incident_id: str = Field(default_factory=lambda: f"inc_{uuid4().hex[:12]}")
    description: str
    root_cause: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    claims: list[Claim]
    trace: list[ToolCall]
    cited_evidence_ids: list[str]
    proposed_action: ActionProposal | None = None
    escalated: bool = False
    refused: bool = False
    refusal_reason: str | None = None
    attempted_actions: list[str] = Field(default_factory=list)
    prompt_variant: str = "guarded"
    model: str = "deterministic-rules-v1"
    token_usage: dict[str, int] = Field(default_factory=dict)


class InvestigateRequest(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    seed: str | None = None
    prompt_variant: str = "guarded"


class ApprovalRequest(BaseModel):
    tool_call_id: str
    approve: bool
    token: str | None = None
    actor: str = "human"
