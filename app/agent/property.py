from __future__ import annotations

from app.data.crawler import PropertyHealthDataStore
from app.models import ActionProposal, Claim, EvidenceRef, InvestigationResult
from app.tools import ToolContext
from app.tools.diagnostic import registry


class PropertyHealthAgent:
    """Bounded correlation agent over a completed, quarantined property map."""

    def __init__(self, datastore: PropertyHealthDataStore) -> None:
        self.datastore = datastore
        self.context = ToolContext(datastore=datastore)

    def investigate(self, description: str) -> InvestigationResult:
        metrics = registry.invoke(
            "query_metrics",
            self.context,
            service=self.datastore.target_host,
            metric="*",
            window="24h",
        )
        logs = registry.invoke(
            "inspect_logs",
            self.context,
            service=self.datastore.target_host,
            severity=None,
            window="24h",
            contains=None,
        )
        registry.invoke(
            "search_runbooks",
            self.context,
            query="property web latency HTTP 5xx TLS DNS",
            limit=3,
        )
        worst = self.datastore.health_map.worst_offender()
        available = set(metrics["evidence_ids"]) | set(logs["evidence_ids"])
        selected = [item for item in worst.evidence_ids if item in available]
        refs = self._refs(selected)
        confidence = 0.9 if refs else 0.25
        proposal: ActionProposal | None = None
        if refs and worst.classification not in {
            "false_positive_alert",
            "insufficient_or_ambiguous_evidence",
        }:
            proposal = registry.propose(
                "request_approval",
                rationale=worst.summary,
                evidence=refs,
                service=worst.host,
            )
        return InvestigationResult(
            description=description,
            root_cause=worst.classification,
            summary=worst.summary,
            confidence=confidence,
            claims=[
                Claim(
                    text=worst.summary,
                    confidence=confidence,
                    evidence=refs,
                    confirmed=bool(refs),
                )
            ],
            trace=self.context.trace,
            cited_evidence_ids=[ref.evidence_id for ref in refs],
            proposed_action=proposal,
            escalated=not refs,
            model="property-correlation-v1",
        )

    def _refs(self, evidence_ids: list[str]) -> list[EvidenceRef]:
        calls = {
            evidence_id: call.tool_call_id
            for call in self.context.trace
            for evidence_id in call.evidence_ids
        }
        return [
            EvidenceRef(evidence_id=evidence_id, tool_call_id=calls[evidence_id])
            for evidence_id in evidence_ids
            if evidence_id in calls
        ]
