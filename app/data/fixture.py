from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class FixtureDataStore:
    """Deterministic adapter for tests/evals; production uses PostgresDataStore."""

    def __init__(self, seed: str, seed_dir: Path | str = "db/seeds") -> None:
        path = Path(seed_dir) / f"{seed}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Unknown seed fixture: {seed}")
        self.data = yaml.safe_load(path.read_text()) or {}
        self.state = dict(self.data.get("service_state", {}))

    def query_metrics(self, service: str, metric: str, window: str) -> list[dict[str, Any]]:
        return [
            row
            for row in self.data.get("metrics", [])
            if row["service"] == service and (metric in {"*", "%"} or row["metric"] == metric)
        ]

    def get_recent_deployments(self, service: str, window: str) -> list[dict[str, Any]]:
        return [row for row in self.data.get("deployments", []) if row["service"] == service]

    def inspect_logs(
        self, service: str, severity: str | None, window: str, contains: str | None
    ) -> list[dict[str, Any]]:
        rows = [row for row in self.data.get("logs", []) if row["service"] == service]
        if severity:
            rows = [row for row in rows if row["severity"].lower() == severity.lower()]
        if contains:
            rows = [row for row in rows if contains.lower() in row["message"].lower()]
        return rows

    def search_runbooks(self, query: str, limit: int) -> list[dict[str, Any]]:
        query_terms = set(query.lower().replace("_", " ").split())
        chunks = self.data.get("runbooks", [])
        ranked = sorted(
            chunks,
            key=lambda row: len(query_terms & set(row["content"].lower().split())),
            reverse=True,
        )
        return ranked[:limit]

    def explain_query(self, sql: str) -> dict[str, Any]:
        plan = self.data.get("query_plan", {"Node Type": "Seq Scan", "Total Cost": 1.0})
        return {
            "plan": plan,
            "evidence_ids": list(self.data.get("query_plan_evidence", ["explain:fixture:plan"])),
            "backend": "fixture",
        }

    def get_table_stats(self, table: str) -> dict[str, Any]:
        row = dict(self.data.get("table_stats", {}).get(table, {}))
        evidence_id = row.setdefault("evidence_id", f"table_stats:{table}")
        return {"stats": row, "evidence_ids": [evidence_id]}

    def get_index_stats(self, table: str) -> list[dict[str, Any]]:
        return list(self.data.get("index_stats", {}).get(table, []))

    def mutate(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.state.update({"last_action": tool_name, **args})
        return {"status": "executed", "backend": "simulated-cloud", "state": self.state}
