from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import signature
from time import perf_counter
from typing import Any, Literal, Protocol, TypeVar
from uuid import uuid4

from app.models import ActionProposal, EvidenceRef, ToolCall

Risk = Literal["low", "medium", "high"]
F = TypeVar("F", bound=Callable[..., dict[str, Any]])


class DataStore(Protocol):
    def query_metrics(self, service: str, metric: str, window: str) -> list[dict[str, Any]]: ...
    def get_recent_deployments(self, service: str, window: str) -> list[dict[str, Any]]: ...
    def inspect_logs(
        self, service: str, severity: str | None, window: str, contains: str | None
    ) -> list[dict[str, Any]]: ...
    def search_runbooks(self, query: str, limit: int) -> list[dict[str, Any]]: ...
    def explain_query(self, sql: str) -> dict[str, Any]: ...
    def get_table_stats(self, table: str) -> dict[str, Any]: ...
    def get_index_stats(self, table: str) -> list[dict[str, Any]]: ...
    def mutate(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ToolSpec:
    name: str
    mutating: bool
    risk: Risk
    description: str
    parameters: dict[str, str]


@dataclass
class ToolContext:
    datastore: DataStore
    trace: list[ToolCall] = field(default_factory=list)
    audit: Any | None = None
    approval_tokens: Any | None = None


def tool(*, mutating: bool, risk: Risk) -> Callable[[F], F]:
    """Declare an auditable tool and its hard mutation boundary."""

    def decorator(function: F) -> F:
        parameters = {
            name: str(parameter.annotation)
            for name, parameter in signature(function).parameters.items()
            if name not in {"context", "approval_token"}
        }
        spec = ToolSpec(
            name=function.__name__,
            mutating=mutating,
            risk=risk,
            description=(function.__doc__ or "").strip(),
            parameters=parameters,
        )
        function.__tool_spec__ = spec
        return function

    return decorator


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {}

    def register(self, function: F) -> F:
        if not hasattr(function, "__tool_spec__"):
            raise TypeError(f"{function.__name__} must use @tool")
        self._tools[function.__name__] = function
        return function

    def get(self, name: str) -> Callable[..., dict[str, Any]]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def spec(self, name: str) -> ToolSpec:
        return self.get(name).__tool_spec__

    def specs(self) -> list[ToolSpec]:
        return [item.__tool_spec__ for item in self._tools.values()]

    def invoke(self, name: str, context: ToolContext, **args: Any) -> dict[str, Any]:
        function = self.get(name)
        spec = self.spec(name)
        if spec.mutating:
            raise PermissionError(
                f"Mutating tool {name} cannot execute through the diagnostic invocation path"
            )
        tool_call_id = f"call_{uuid4().hex[:12]}"
        started = perf_counter()
        result = function(context=context, **args)
        duration_ms = (perf_counter() - started) * 1000
        evidence_ids = list(result.get("evidence_ids", []))
        result["tool_call_id"] = tool_call_id
        context.trace.append(
            ToolCall(
                tool_call_id=tool_call_id,
                tool=name,
                args=args,
                result_summary={
                    "row_count": len(result.get("rows", [])),
                    "status": result.get("status", "ok"),
                },
                evidence_ids=evidence_ids,
                duration_ms=duration_ms,
                ts=datetime.now(UTC),
            )
        )
        if context.audit:
            context.audit.append(
                decision="auto",
                tool=name,
                tool_call_id=tool_call_id,
                args=args,
                outcome="diagnostic_executed",
            )
        return result

    def propose(
        self,
        name: str,
        *,
        rationale: str,
        evidence: list[EvidenceRef],
        **args: Any,
    ) -> ActionProposal:
        spec = self.spec(name)
        if not spec.mutating:
            raise TypeError(f"Diagnostic tool {name} does not require a proposal")
        return ActionProposal(
            tool_call_id=f"call_{uuid4().hex[:12]}",
            tool=name,
            args=args,
            args_hash=canonical_args_hash(args),
            rationale=rationale,
            risk=spec.risk,
            reversible=True,
            evidence=evidence,
        )

    def execute_mutation(
        self,
        proposal: ActionProposal,
        context: ToolContext,
        approval_token: str | None,
    ) -> dict[str, Any]:
        function = self.get(proposal.tool)
        if not self.spec(proposal.tool).mutating:
            raise TypeError(f"{proposal.tool} is not a mutating tool")
        if getattr(context.datastore, "is_live_target", False):
            raise PermissionError(
                "Live web targets are diagnosis-only; mutation execution is forbidden"
            )
        return function(context=context, proposal=proposal, approval_token=approval_token)


def canonical_args_hash(args: dict[str, Any]) -> str:
    encoded = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


registry = ToolRegistry()
