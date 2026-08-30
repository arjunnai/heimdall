from __future__ import annotations

import re

from app.tools.registry import ToolContext, registry, tool


@registry.register
@tool(mutating=False, risk="low")
def query_metrics(context: ToolContext, service: str, metric: str, window: str = "2h") -> dict:
    """Return timestamped metric rows from Postgres for a service."""
    rows = context.datastore.query_metrics(service, metric, window)
    return {"rows": rows, "evidence_ids": [row["evidence_id"] for row in rows]}


@registry.register
@tool(mutating=False, risk="low")
def get_recent_deployments(context: ToolContext, service: str, window: str = "24h") -> dict:
    """Return deployment history from Postgres for a service."""
    rows = context.datastore.get_recent_deployments(service, window)
    return {"rows": rows, "evidence_ids": [row["evidence_id"] for row in rows]}


@registry.register
@tool(mutating=False, risk="low")
def inspect_logs(
    context: ToolContext,
    service: str,
    severity: str | None = None,
    window: str = "2h",
    contains: str | None = None,
) -> dict:
    """Search structured application logs from Postgres."""
    rows = context.datastore.inspect_logs(service, severity, window, contains)
    return {"rows": rows, "evidence_ids": [row["evidence_id"] for row in rows]}


@registry.register
@tool(mutating=False, risk="low")
def search_runbooks(context: ToolContext, query: str, limit: int = 3) -> dict:
    """Retrieve relevant runbook chunks from pgvector with stable source ids."""
    rows = context.datastore.search_runbooks(query, min(max(limit, 1), 8))
    return {"rows": rows, "evidence_ids": [row["evidence_id"] for row in rows]}


_READ_ONLY_SQL = re.compile(r"^\s*(select|with|explain)\b", re.IGNORECASE)
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|copy|call|do)\b",
    re.IGNORECASE,
)


@registry.register
@tool(mutating=False, risk="low")
def explain_query(context: ToolContext, sql: str) -> dict:
    """Run a real EXPLAIN (FORMAT JSON) for a strictly read-only SQL statement."""
    if not _READ_ONLY_SQL.match(sql) or _FORBIDDEN_SQL.search(sql):
        return {
            "status": "refused",
            "reason": "Only read-only SELECT/WITH statements may be explained",
            "evidence_ids": [],
        }
    result = context.datastore.explain_query(sql)
    return {**result, "evidence_ids": list(result.get("evidence_ids", []))}


@registry.register
@tool(mutating=False, risk="low")
def get_table_stats(context: ToolContext, table: str) -> dict:
    """Read row and maintenance statistics from pg_stat_user_tables."""
    result = context.datastore.get_table_stats(table)
    return {**result, "evidence_ids": list(result.get("evidence_ids", []))}


@registry.register
@tool(mutating=False, risk="low")
def get_index_stats(context: ToolContext, table: str) -> dict:
    """Read index definitions and usage from pg_stat_user_indexes."""
    rows = context.datastore.get_index_stats(table)
    return {"rows": rows, "evidence_ids": [row["evidence_id"] for row in rows]}


def diagnostic_tool_names() -> list[str]:
    return [spec.name for spec in registry.specs() if not spec.mutating]
