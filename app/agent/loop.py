from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import app.tools.mutating  # noqa: F401  # Register the gated mutation surface.
from app.agent.provider import LLMProvider
from app.models import ActionProposal, Claim, EvidenceRef, InvestigationResult
from app.policy import RiskPolicy
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

ROOT_CAUSE_TAXONOMY = (
    "database_connection_pool_exhaustion",
    "missing_database_index",
    "service_memory_leak",
    "kafka_consumer_lag",
    "upstream_dependency_outage",
    "traffic_spike",
    "dns_service_discovery_failure",
    "false_positive_alert",
    "stale_database_statistics",
    "database_lock_contention",
    "database_hotspot",
    "expensive_wildcard_query",
    "unsafe_request_refused",
    "schema_validation_error",
    "insufficient_or_ambiguous_evidence",
    "index_already_exists_noop",
)

ACTION_TAXONOMY = (
    "rollback_deployment",
    "increase_connection_pool",
    "create_index",
    "restart_service",
    "request_approval",
)

LLM_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "query_metrics": {
        "required": ["service", "metric"],
        "optional": {"window": "24h"},
        "description": "Query timestamped service metrics. Use metric='*' to inspect all metrics.",
    },
    "get_recent_deployments": {
        "required": ["service"],
        "optional": {"window": "7d"},
        "description": "Get recent deployment versions and timestamps for a service.",
    },
    "inspect_logs": {
        "required": ["service"],
        "optional": {"severity": None, "window": "24h", "contains": None},
        "description": "Inspect structured service logs with optional severity/text filters.",
    },
    "search_runbooks": {
        "required": ["query"],
        "optional": {"limit": 3},
        "description": "Retrieve runbook chunks relevant to the incident.",
    },
    "explain_query": {
        "required": ["sql"],
        "optional": {},
        "description": "Run read-only EXPLAIN (FORMAT JSON) for a SQL query.",
    },
    "get_table_stats": {
        "required": ["table"],
        "optional": {},
        "description": "Read pg_stat_user_tables row/dead-tuple/analyze statistics.",
    },
    "get_index_stats": {
        "required": ["table"],
        "optional": {},
        "description": "Read existing PostgreSQL index definitions and usage.",
    },
}

LLM_PLAN_SYSTEM_PROMPT = """You are Heimdall's investigation planner.
Choose the minimum diagnostic tools needed to investigate the incident across metrics, logs,
deployments, runbooks, and database evidence when relevant. You do not diagnose yet and you cannot
request mutating tools. Return strict JSON only:
{"tools":[{"name":"tool_name","args":{"argument":"value"}}]}
Use only tools and arguments from the supplied catalog. Do not wrap JSON in markdown."""

LLM_SYNTHESIS_SYSTEM_PROMPT = """You are Heimdall's incident investigator.
Diagnose only from the supplied tool observations. Every cited evidence_id must appear verbatim in
available_evidence_ids. Choose a canonical root cause and optional action from the supplied lists.
Escalate when evidence is ambiguous or insufficient. Refuse destructive requests.
Return strict JSON:
{"root_cause":"canonical_name","summary":"one evidence-based sentence","confidence":0.0,
"evidence_ids":["exact:id"],"action":null,"escalated":false,"refused":false}
Do not wrap JSON in markdown and never invent evidence, services, tables, columns, or actions."""


class IncidentAgent:
    """A bounded plan→call→observe→correlate loop with structural citations."""

    def __init__(
        self,
        datastore: Any,
        *,
        prompt_variant: str = "guarded",
        audit: Any | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self.context = ToolContext(datastore=datastore, audit=audit)
        self.prompt_variant = prompt_variant
        self.provider = provider
        self.provider_model = "deterministic-rules-v1"
        self.token_usage: dict[str, int] = {}

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
        if self.provider is not None:
            return self._investigate_llm(description)
        return self._investigate_deterministic(description)

    def _investigate_deterministic(self, description: str) -> InvestigationResult:
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
        confidence = 0.93
        selected_evidence = all_evidence
        proposal = None
        if action:
            args = self._action_args(action, service)
            proposal = registry.propose(
                action,
                rationale=f"Mitigate {rule.root_cause} after human review",
                evidence=self._refs(selected_evidence),
                **args,
            )
        summary = f"Evidence is consistent with {rule.root_cause.replace('_', ' ')}."
        return self._result(
            description,
            rule.root_cause,
            summary,
            confidence,
            selected_evidence,
            proposal=proposal,
            escalated=rule.risk == "high" and proposal is None,
        )

    def _investigate_llm(self, description: str) -> InvestigationResult:
        """Let a live provider plan tools and synthesize a structurally validated diagnosis."""
        assert self.provider is not None
        service_hint = self._service(description, self.context.datastore)
        try:
            planning_response = self.provider.complete(
                [
                    {"role": "system", "content": LLM_PLAN_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "incident": description,
                                "service_hint": service_hint,
                                "diagnostic_tool_catalog": LLM_TOOL_SCHEMAS,
                            }
                        ),
                    },
                ],
                temperature=0,
            )
            self._record_provider_response(planning_response)
            plan = self._parse_provider_json(planning_response.content)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._unverified_provider_result(
                description, "The model did not return a valid diagnostic tool plan."
            )

        observations: list[dict[str, Any]] = []
        planned_calls = plan.get("tools")
        if not isinstance(planned_calls, list):
            return self._unverified_provider_result(
                description, "The model tool plan omitted the tools list."
            )
        for planned_call in planned_calls[:10]:
            validated = self._validated_planned_call(planned_call)
            if validated is None:
                continue
            tool_name, args = validated
            try:
                result = self._call(tool_name, **args)
                observations.append({"tool": tool_name, "args": args, "result": result})
            except (KeyError, TypeError, ValueError, PermissionError) as exc:
                observations.append(
                    {"tool": tool_name, "args": args, "error": f"{type(exc).__name__}: {exc}"}
                )

        available_evidence_ids = list(
            dict.fromkeys(
                evidence_id for call in self.context.trace for evidence_id in call.evidence_ids
            )
        )
        try:
            synthesis_response = self.provider.complete(
                [
                    {"role": "system", "content": LLM_SYNTHESIS_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "incident": description,
                                "canonical_root_causes": ROOT_CAUSE_TAXONOMY,
                                "allowed_actions": ACTION_TAXONOMY,
                                "available_evidence_ids": available_evidence_ids,
                                "tool_observations": observations,
                            },
                            default=str,
                        ),
                    },
                ],
                temperature=0,
            )
            self._record_provider_response(synthesis_response)
            candidate = self._parse_provider_json(synthesis_response.content)
            self._validate_llm_candidate(candidate, available_evidence_ids)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._unverified_provider_result(
                description,
                "The model diagnosis failed the structured evidence contract.",
            )

        root_cause = str(candidate["root_cause"])
        summary = str(candidate["summary"])
        confidence = float(candidate["confidence"])
        selected_evidence = list(candidate["evidence_ids"])
        action = candidate.get("action")
        escalated = bool(candidate["escalated"])
        refused = bool(candidate["refused"])
        refusal_reason = None
        attempted_actions: list[str] = []
        proposal = None

        policy = RiskPolicy()
        destructive_request = bool(policy.forbidden_text.search(description))
        if action:
            attempted_actions.append(str(action))
            spec = None
            if action in ACTION_TAXONOMY:
                try:
                    spec = registry.spec(str(action))
                except KeyError:
                    spec = None
            action_args = self._action_args(str(action), service_hint)
            decision = policy.decide(tool_name=str(action), args=action_args, spec=spec)
            if decision.decision == "forbid":
                refused = True
                refusal_reason = decision.reason
                root_cause = "unsafe_request_refused"
                action = None
            elif decision.decision == "require-approval":
                proposal = registry.propose(
                    str(action),
                    rationale=summary,
                    evidence=self._refs(selected_evidence),
                    **action_args,
                )
        if destructive_request:
            refused = True
            refusal_reason = "Forbidden destructive request matched the code policy"
            root_cause = "unsafe_request_refused"
            proposal = None
        if refused:
            escalated = False

        return self._result(
            description,
            root_cause,
            summary,
            confidence,
            selected_evidence,
            proposal=proposal,
            escalated=escalated,
            refused=refused,
            refusal_reason=refusal_reason,
            attempted_actions=attempted_actions,
        )

    def _validated_planned_call(self, planned_call: Any) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(planned_call, dict):
            return None
        name = planned_call.get("name")
        args = planned_call.get("args")
        if name not in LLM_TOOL_SCHEMAS or not isinstance(args, dict):
            return None
        schema = LLM_TOOL_SCHEMAS[name]
        allowed = set(schema["required"]) | set(schema["optional"])
        if set(args) - allowed or any(key not in args for key in schema["required"]):
            return None
        normalized = {**schema["optional"], **args}
        if any(
            not isinstance(normalized[key], str) or not normalized[key].strip()
            for key in schema["required"]
        ):
            return None
        if name == "search_runbooks":
            limit = normalized.get("limit", 3)
            if not isinstance(limit, int) or isinstance(limit, bool):
                return None
            normalized["limit"] = min(max(limit, 1), 8)
        return str(name), normalized

    def _validate_llm_candidate(
        self, candidate: dict[str, Any], available_evidence_ids: list[str]
    ) -> None:
        if candidate.get("root_cause") not in ROOT_CAUSE_TAXONOMY:
            raise ValueError("Model returned a non-canonical root cause")
        if not isinstance(candidate.get("summary"), str) or not candidate["summary"].strip():
            raise ValueError("Model summary is missing")
        confidence = float(candidate["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError("Model confidence is outside 0..1")
        evidence_ids = candidate.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not all(
            isinstance(evidence_id, str) for evidence_id in evidence_ids
        ):
            raise ValueError("Model evidence_ids must be a string list")
        if available_evidence_ids and not evidence_ids:
            raise ValueError("Model omitted citations despite available evidence")
        if not set(evidence_ids) <= set(available_evidence_ids):
            raise ValueError("Model cited evidence not returned by its tool calls")
        action = candidate.get("action")
        if action is not None and not isinstance(action, str):
            raise ValueError("Model action must be a string or null")
        if not isinstance(candidate.get("escalated"), bool) or not isinstance(
            candidate.get("refused"), bool
        ):
            raise ValueError("Model escalation/refusal flags must be booleans")

    def _record_provider_response(self, response: Any) -> None:
        self.provider_model = response.model
        self.token_usage = {
            "input_tokens": self.token_usage.get("input_tokens", 0) + response.input_tokens,
            "output_tokens": self.token_usage.get("output_tokens", 0) + response.output_tokens,
            "provider_calls": self.token_usage.get("provider_calls", 0) + 1,
        }

    @staticmethod
    def _parse_provider_json(content: str) -> dict[str, Any]:
        rendered = content.strip()
        if rendered.startswith("```"):
            rendered = rendered.split("\n", 1)[-1]
            rendered = rendered.rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(rendered)
        except json.JSONDecodeError:
            start = rendered.find("{")
            end = rendered.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(rendered[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("Provider response must be a JSON object")
        return parsed

    def _unverified_provider_result(self, description: str, reason: str) -> InvestigationResult:
        return self._result(
            description,
            "provider_output_unverified",
            reason,
            0.0,
            [],
            escalated=True,
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
            model=self.provider_model,
            token_usage=self.token_usage,
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
