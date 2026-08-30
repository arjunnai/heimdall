from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query

import app.tools.mutating  # noqa: F401
from app.agent import IncidentAgent
from app.agent.provider import make_provider
from app.config import get_settings
from app.data import FixtureDataStore, PostgresDataStore
from app.models import ApprovalRequest, InvestigateRequest, InvestigationResult
from app.policy import ApprovalService, ApprovalTokenManager, AuditLog, RiskPolicy
from app.tools.diagnostic import registry

app = FastAPI(
    title="OpsPilot",
    version="1.0.0",
    description="Evidence-grounded, approval-gated incident response",
)

settings = get_settings()
audit_log = AuditLog(settings.audit_log_path)
approval_service = ApprovalService(
    registry=registry,
    policy=RiskPolicy(),
    tokens=ApprovalTokenManager(settings.approval_secret, settings.approval_ttl_seconds),
    audit=audit_log,
)
pending_proposals: dict[str, tuple[Any, Any]] = {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/investigate", response_model=InvestigationResult)
def investigate(request: InvestigateRequest) -> InvestigationResult:
    try:
        datastore = (
            FixtureDataStore(request.seed)
            if request.seed
            else PostgresDataStore(get_settings().database_url)
        )
        provider = None if settings.llm_provider == "deterministic" else make_provider(settings)
        agent = IncidentAgent(
            datastore,
            prompt_variant=request.prompt_variant,
            audit=audit_log,
            provider=provider,
        )
        result = agent.investigate(request.description)
        if result.proposed_action:
            pending_proposals[result.proposed_action.tool_call_id] = (
                result.proposed_action,
                agent.context,
            )
        return result
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/approve")
def approve(request: ApprovalRequest) -> dict[str, Any]:
    pending = pending_proposals.pop(request.tool_call_id, None)
    if not pending:
        raise HTTPException(status_code=404, detail="Unknown or already resolved proposal")
    proposal, context = pending
    try:
        if request.approve:
            return approval_service.approve(proposal, context, actor=request.actor)
        return approval_service.reject(proposal, actor=request.actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/audit")
def audit(limit: int = Query(default=200, ge=1, le=2000)) -> dict[str, Any]:
    events = audit_log.read(limit)
    return {"events": events, "count": len(events)}
