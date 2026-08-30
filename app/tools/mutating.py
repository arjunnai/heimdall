from __future__ import annotations

from typing import Any

from app.models import ActionProposal
from app.policy.approval import ApprovalTokenError, ApprovalTokenManager
from app.tools.registry import ToolContext, registry, tool


def _execute(
    context: ToolContext, proposal: ActionProposal, approval_token: str | None
) -> dict[str, Any]:
    if not isinstance(context.approval_tokens, ApprovalTokenManager):
        raise ApprovalTokenError("Mutation context has no policy-issued token verifier")
    context.approval_tokens.verify(approval_token, proposal)
    return context.datastore.mutate(proposal.tool, proposal.args)


@registry.register
@tool(mutating=True, risk="medium")
def rollback_deployment(
    context: ToolContext, proposal: ActionProposal, approval_token: str | None = None
) -> dict:
    """Roll a simulated service deployment back after signed approval."""
    return _execute(context, proposal, approval_token)


@registry.register
@tool(mutating=True, risk="medium")
def increase_connection_pool(
    context: ToolContext, proposal: ActionProposal, approval_token: str | None = None
) -> dict:
    """Change modeled service pool size after signed approval."""
    return _execute(context, proposal, approval_token)


@registry.register
@tool(mutating=True, risk="medium")
def create_index(
    context: ToolContext, proposal: ActionProposal, approval_token: str | None = None
) -> dict:
    """Create a real PostgreSQL index after signed approval."""
    return _execute(context, proposal, approval_token)


@registry.register
@tool(mutating=True, risk="high")
def restart_service(
    context: ToolContext, proposal: ActionProposal, approval_token: str | None = None
) -> dict:
    """Restart a simulated service after signed approval."""
    return _execute(context, proposal, approval_token)


@registry.register
@tool(mutating=True, risk="high")
def request_approval(
    context: ToolContext, proposal: ActionProposal, approval_token: str | None = None
) -> dict:
    """Record an explicit high-risk escalation through the uniform approval path."""
    if not isinstance(context.approval_tokens, ApprovalTokenManager):
        raise ApprovalTokenError("Mutation context has no policy-issued token verifier")
    context.approval_tokens.verify(approval_token, proposal)
    return {"status": "acknowledged", "backend": "policy"}
