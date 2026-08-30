from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.models import ActionProposal, Claim, EvidenceRef, InvestigationResult
from app.tools import ToolContext
from app.tools.diagnostic import registry


@dataclass(frozen=True)
class DiagnosisRule:
    root_cause: str
    clues: tuple[str, ...]
    action: str | None
    risk: str


RULES = (
    DiagnosisRule(
        "database_connection_pool_exhaustion",
        ("pool exhausted", "connection pool", "timeout waiting for connection"),
        "increase_connection_pool",
        "medium",
    ),
    DiagnosisRule("missing_database_index", ("seq scan", "slow query"), "create_index", "medium"),
    DiagnosisRule(
        "service_memory_leak",
        ("memory leak", "out of memory", "oomkilled"),
        "rollback_deployment",
        "medium",
    ),
    DiagnosisRule(
        "kafka_consumer_lag", ("consumer lag", "rebalance loop"), "restart_service", "medium"
    ),
    DiagnosisRule(
        "upstream_dependency_outage", ("upstream timeout", "dependency unavailable"), None, "high"
    ),
    DiagnosisRule("traffic_spike", ("traffic spike", "request rate"), "restart_service", "medium"),
    DiagnosisRule(
        "dns_service_discovery_failure",
        ("nxdomain", "dns lookup", "no such host"),
        "restart_service",
        "medium",
    ),
    DiagnosisRule(
        "stale_database_statistics", ("stale statistics", "last analyze"), None, "medium"
    ),
    DiagnosisRule(
        "database_lock_contention", ("lock wait", "blocked by pid", "deadlock"), None, "high"
    ),
    DiagnosisRule("database_hotspot", ("hotspot", "hot partition"), None, "high"),
    DiagnosisRule(
        "expensive_wildcard_query",
        ("wildcard query", "ilike '%", "like '%"),
        "create_index",
        "medium",
    ),
)

KNOWN_SERVICES = (
    "checkout",
    "catalog",
    "payments",
    "orders",
    "inventory",
    "search",
    "shipping",
    "recommendations",
    "notifications",
    "api",
    "worker",
    "database",
)


class IncidentAgent:
    """A bounded plan→call→observe→correlate loop with structural citations."""

    def __init__(self, datastore: Any, *, prompt_variant: str = "guarded") -> None:
        self.context = ToolContext(datastore=datastore)
        self.prompt_variant = prompt_variant

    @staticmethod
    def _service(description: str, datastore: Any) -> str:
        lowered = description.lower()
        for service in KNOWN_SERVICES:
            if re.search(rf"\b{re.escape(service)}\b", lowered):
                return service
        fixture_state = getattr(datastore, "data", {}).get("service_state", {})
        return fixture_state.get("service", "unknown")

    def _call(self, tool_name: str, **args: Any) -> dict[str, Any]:
        return registry.invoke(tool_name, self.context, **args)

    def investigate(self, description: str) -> InvestigationResult:
        service = self._service(description, self.context.datastore)
        metrics = self._call("query_metrics", service=service, metric="*", window="24h")
        deployments = self._call("get_recent_deployments", service=service, window="7d")
        logs = self._call("inspect_logs", service=service, window="24h")
        corpus = " ".join(row.get("message", "") for row in logs.get("rows", []))
        corpus += " " + description
        runbooks = self._call("search_runbooks", query=corpus, limit=3)

        lowered = corpus.lower()
        db_evidence: list[str] = []
        if any(term in lowered for term in ("query", "index", "scan", "orders", "sql")):
            sql = "SELECT * FROM orders WHERE customer_id = 4242"
            plan = self._call("explain_query", sql=sql)
            indexes = self._call("get_index_stats", table="orders")
            stats = self._call("get_table_stats", table="orders")
            lowered += " " + str(plan.get("plan", "")).lower()
            db_evidence = [
                *plan.get("evidence_ids", []),
                *indexes.get("evidence_ids", []),
                *stats.get("evidence_ids", []),
            ]

        all_evidence = [
            *metrics.get("evidence_ids", []),
            *deployments.get("evidence_ids", []),
            *logs.get("evidence_ids", []),
            *runbooks.get("evidence_ids", []),
            *db_evidence,
        ]
        forbidden_requested = bool(
            re.search(r"\b(drop table|delete_database|delete database)\b", lowered)
        )
        matches = [rule for rule in RULES if any(clue in lowered for clue in rule.clues)]
        ambiguous = "ambiguous" in lowered or "conflicting evidence" in lowered or len(matches) > 1

        if forbidden_requested and self.prompt_variant == "guarded":
            return self._result(
                description,
                "unsafe_request_refused",
                "The requested destructive action is forbidden.",
                1.0,
                all_evidence,
                escalated=False,
                refused=True,
                refusal_reason="Forbidden action matched policy: destructive database operation",
            )
        if ambiguous or not matches:
            return self._result(
                description,
                "insufficient_or_ambiguous_evidence",
                (
                    "Evidence does not support a unique, safe root cause; "
                    "human escalation is required."
                ),
                0.35 if all_evidence else 0.1,
                all_evidence,
                escalated=True,
            )

        rule = matches[0]
        action = rule.action
        proposal = None
        if action:
            args = self._action_args(action, service)
            args_hash = hashlib.sha256(repr(sorted(args.items())).encode()).hexdigest()
            proposal_id = hashlib.sha256((action + repr(args)).encode()).hexdigest()[:12]
            proposal = ActionProposal(
                tool_call_id=f"proposal_{proposal_id}",
                tool=action,
                args=args,
                args_hash=args_hash,
                rationale=f"Mitigate {rule.root_cause} after human review",
                risk=rule.risk,  # type: ignore[arg-type]
                reversible=True,
                evidence=self._refs(all_evidence),
            )
        summary = f"Evidence is consistent with {rule.root_cause.replace('_', ' ')}."
        return self._result(
            description, rule.root_cause, summary, 0.93, all_evidence, proposal=proposal
        )

    @staticmethod
    def _action_args(action: str, service: str) -> dict[str, Any]:
        if action == "increase_connection_pool":
            return {"service": service, "size": 30}
        if action == "rollback_deployment":
            return {"service": service, "to_version": "previous"}
        if action == "create_index":
            return {"table": "orders", "columns": ["customer_id"], "concurrently": True}
        return {"service": service}

    def _refs(self, evidence_ids: list[str]) -> list[EvidenceRef]:
        calls = {
            evidence_id: call.tool_call_id
            for call in self.context.trace
            for evidence_id in call.evidence_ids
        }
        return [
            EvidenceRef(evidence_id=evidence_id, tool_call_id=calls[evidence_id])
            for evidence_id in dict.fromkeys(evidence_ids)
            if evidence_id in calls
        ]

    def _result(
        self,
        description: str,
        root_cause: str,
        summary: str,
        confidence: float,
        evidence_ids: list[str],
        *,
        proposal: ActionProposal | None = None,
        escalated: bool = False,
        refused: bool = False,
        refusal_reason: str | None = None,
    ) -> InvestigationResult:
        refs = self._refs(evidence_ids)
        claim = Claim(
            text=summary, confidence=confidence, evidence=refs, confirmed=confidence >= 0.7
        )
        return InvestigationResult(
            description=description,
            root_cause=root_cause,
            summary=summary,
            confidence=confidence,
            claims=[claim],
            trace=self.context.trace,
            cited_evidence_ids=[ref.evidence_id for ref in refs],
            proposed_action=proposal,
            escalated=escalated,
            refused=refused,
            refusal_reason=refusal_reason,
            prompt_variant=self.prompt_variant,
        )
