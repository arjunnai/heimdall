from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.tools.registry import ToolSpec

DecisionKind = Literal["auto", "require-approval", "forbid"]


@dataclass(frozen=True)
class PolicyDecision:
    decision: DecisionKind
    reason: str


class RiskPolicy:
    """Fail-closed policy evaluated in code, independent of model behavior."""

    forbidden_tools = frozenset(
        {"drop_table", "delete_database", "restart_database", "terminate_session"}
    )
    forbidden_text = re.compile(r"\b(drop\s+table|delete_database|delete\s+database)\b", re.I)

    def decide(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        spec: ToolSpec | None = None,
    ) -> PolicyDecision:
        rendered_args = " ".join(str(value) for value in args.values())
        if tool_name in self.forbidden_tools or self.forbidden_text.search(rendered_args):
            return PolicyDecision("forbid", "Action is in the destructive forbidden set")
        if spec is None:
            return PolicyDecision("forbid", "Unknown tools fail closed")
        if spec.mutating:
            return PolicyDecision(
                "require-approval", f"{spec.risk}-risk mutation requires approval"
            )
        return PolicyDecision("auto", "Read-only diagnostic tool")
