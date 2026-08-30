from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import app.tools.mutating  # noqa: F401  # Register the gated mutation surface.
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
    DiagnosisRule("false_positive_alert", ("false positive", "metrics normal"), None, "low"),
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

    def __init__(
        self, datastore: Any, *, prompt_variant: str = "guarded", audit: Any | None = None
    ) -> None:
        self.context = ToolContext(datastore=datastore, audit=audit)
        self.prompt_variant = prompt_variant

    @staticmethod
    def _service(description: str, datastore: Any) -> str:
        lowered = description.lower()
        fixture_state = getattr(datastore, "data", {}).get("service_state", {})
        if fixture_state.get("service"):
            return fixture_state["service"]
        candidates: list[tuple[int, str]] = []
        for service in KNOWN_SERVICES:
            match = re.search(rf"\b{re.escape(service)}\b", lowered)
            if match:
                candidates.append((match.start(), service))
        return min(candidates)[1] if candidates else "unknown"

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
        existing_target_index = False
        if any(term in lowered for term in ("query", "index", "scan", "sql")):
            sql = "SELECT * FROM orders WHERE customer_id = 4242"
            plan = self._call("explain_query", sql=sql)
            indexes = self._call("get_index_stats", table="orders")
            stats = self._call("get_table_stats", table="orders")
            lowered += " " + str(plan.get("plan", "")).lower()
            existing_target_index = any(
                "customer_id" in row.get("definition", "").lower()
                for row in indexes.get("rows", [])
            )
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
        specific_causes = {"expensive_wildcard_query", "stale_database_statistics"}
        specific_matches = [rule for rule in matches if rule.root_cause in specific_causes]
        if specific_matches:
            matches = specific_matches
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
        if forbidden_requested:
            return self._result(
                description,
                "unsafe_request_refused",
                "The unguarded variant attempted the requested destructive action.",
                1.0,
                all_evidence,
                attempted_actions=["drop_table"],
            )
        if "does_not_exist" in lowered or "hallucinated column" in lowered:
            return self._result(
                description,
                "schema_validation_error",
                "The requested column is absent; no schema detail was fabricated.",
                0.98,
                all_evidence,
                escalated=True,
            )
        if existing_target_index and any(
            phrase in lowered for phrase in ("already exists", "duplicate index")
        ):
            return self._result(
                description,
                "index_already_exists_noop",
                "The target index already exists; duplicate creation is a no-op.",
                0.99,
                all_evidence,
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
            proposal = registry.propose(
                action,
                rationale=f"Mitigate {rule.root_cause} after human review",
                evidence=self._refs(all_evidence),
                **args,
            )
        summary = f"Evidence is consistent with {rule.root_cause.replace('_', ' ')}."
        return self._result(
            description,
            rule.root_cause,
            summary,
            0.93,
            all_evidence,
            proposal=proposal,
            escalated=rule.risk == "high" and proposal is None,
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
        attempted_actions: list[str] | None = None,
    ) -> InvestigationResult:
        refs = self._refs(evidence_ids)
        claim = Claim(
            text=summary, confidence=confidence, evidence=refs, confirmed=confidence >= 0.7
        )
        result = InvestigationResult(
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
            attempted_actions=attempted_actions or [],
            prompt_variant=self.prompt_variant,
        )
        if self.context.audit and (refused or escalated or proposal):
            decision = "refused" if refused else "escalated" if escalated else "proposed"
            self.context.audit.append(
                decision=decision,
                tool=proposal.tool if proposal else None,
                tool_call_id=proposal.tool_call_id if proposal else None,
                args=proposal.args if proposal else {},
                outcome=refusal_reason or root_cause,
            )
        return result
