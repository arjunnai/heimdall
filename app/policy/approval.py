from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from app.models import ActionProposal
from app.policy.audit import AuditLog
from app.policy.risk import RiskPolicy
from app.tools.registry import ToolContext, ToolRegistry, canonical_args_hash


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class ApprovalTokenError(PermissionError):
    pass


class ApprovalTokenManager:
    """Issues short-lived HMAC tokens bound to call id, tool, and exact args hash."""

    def __init__(self, secret: str, ttl_seconds: int = 300) -> None:
        if len(secret) < 32:
            raise ValueError("Approval secret must contain at least 32 characters")
        self.secret = secret.encode()
        self.ttl_seconds = ttl_seconds

    def issue(self, proposal: ActionProposal, *, now: int | None = None) -> str:
        issued_at = int(time.time() if now is None else now)
        payload = {
            "tool_call_id": proposal.tool_call_id,
            "tool": proposal.tool,
            "args_hash": proposal.args_hash,
            "iat": issued_at,
            "exp": issued_at + self.ttl_seconds,
        }
        encoded = _b64_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signature = _b64_encode(hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(
        self, token: str | None, proposal: ActionProposal, *, now: int | None = None
    ) -> dict[str, Any]:
        if not token:
            raise ApprovalTokenError("A signed approval token is required")
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected_signature = _b64_encode(
                hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise ApprovalTokenError("Approval token signature is invalid")
            payload = json.loads(_b64_decode(encoded))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApprovalTokenError("Approval token is malformed") from exc
        expected = {
            "tool_call_id": proposal.tool_call_id,
            "tool": proposal.tool,
            "args_hash": canonical_args_hash(proposal.args),
        }
        if proposal.args_hash != expected["args_hash"]:
            raise ApprovalTokenError("Proposal args hash does not match its arguments")
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ApprovalTokenError("Approval token is bound to a different action")
        current_time = int(time.time() if now is None else now)
        if current_time >= int(payload.get("exp", 0)):
            raise ApprovalTokenError("Approval token has expired")
        return payload


@dataclass
class ApprovalService:
    registry: ToolRegistry
    policy: RiskPolicy
    tokens: ApprovalTokenManager
    audit: AuditLog

    def approve(
        self,
        proposal: ActionProposal,
        context: ToolContext,
        *,
        actor: str,
    ) -> dict[str, Any]:
        spec = self.registry.spec(proposal.tool)
        decision = self.policy.decide(tool_name=proposal.tool, args=proposal.args, spec=spec)
        if decision.decision != "require-approval":
            self.audit.append(
                decision="refused",
                tool=proposal.tool,
                tool_call_id=proposal.tool_call_id,
                args=proposal.args,
                outcome=decision.reason,
                actor=actor,
            )
            raise PermissionError(decision.reason)
        token = self.tokens.issue(proposal)
        context.approval_tokens = self.tokens
        result = self.registry.execute_mutation(proposal, context, token)
        self.audit.append(
            decision="approved",
            tool=proposal.tool,
            tool_call_id=proposal.tool_call_id,
            args=proposal.args,
            outcome="mutation_executed",
            actor=actor,
            details={"result": result},
        )
        return {"status": "approved", "result": result}

    def reject(self, proposal: ActionProposal, *, actor: str) -> dict[str, str]:
        self.audit.append(
            decision="rejected",
            tool=proposal.tool,
            tool_call_id=proposal.tool_call_id,
            args=proposal.args,
            outcome="human_rejected",
            actor=actor,
        )
        return {"status": "rejected"}
