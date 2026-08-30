from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import app.tools.mutating  # noqa: F401
from app.config import get_settings
from app.data import PostgresDataStore
from app.tools import ToolContext
from app.tools.diagnostic import registry

mcp = FastMCP("OpsPilot")


def _invoke(name: str, **args: object) -> dict:
    context = ToolContext(PostgresDataStore(get_settings().database_url))
    return registry.invoke(name, context, **args)


@mcp.tool()
def query_metrics(service: str, metric: str, window: str = "2h") -> dict:
    """Return real Postgres metric rows with evidence ids."""
    return _invoke("query_metrics", service=service, metric=metric, window=window)


@mcp.tool()
def get_recent_deployments(service: str, window: str = "24h") -> dict:
    """Return real Postgres deployment records with evidence ids."""
    return _invoke("get_recent_deployments", service=service, window=window)


@mcp.tool()
def inspect_logs(
    service: str, severity: str | None = None, window: str = "2h", contains: str | None = None
) -> dict:
    """Search real Postgres logs with evidence ids."""
    return _invoke(
        "inspect_logs", service=service, severity=severity, window=window, contains=contains
    )


@mcp.tool()
def search_runbooks(query: str, limit: int = 3) -> dict:
    """Search runbook chunks using pgvector."""
    return _invoke("search_runbooks", query=query, limit=limit)


@mcp.tool()
def explain_query(sql: str) -> dict:
    """Run a read-only real PostgreSQL EXPLAIN (FORMAT JSON)."""
    return _invoke("explain_query", sql=sql)


@mcp.tool()
def get_table_stats(table: str) -> dict:
    """Return pg_stat_user_tables evidence."""
    return _invoke("get_table_stats", table=table)


@mcp.tool()
def get_index_stats(table: str) -> dict:
    """Return pg_stat_user_indexes evidence."""
    return _invoke("get_index_stats", table=table)


def _proposal(name: str, rationale: str, **args: object) -> dict:
    """Return a proposal only; execution is exclusively available through /approve."""
    return registry.propose(name, rationale=rationale, evidence=[], **args).model_dump(mode="json")


@mcp.tool()
def rollback_deployment(service: str, to_version: str, rationale: str) -> dict:
    """Propose a deployment rollback. This cannot execute a mutation."""
    return _proposal("rollback_deployment", rationale, service=service, to_version=to_version)


@mcp.tool()
def increase_connection_pool(service: str, size: int, rationale: str) -> dict:
    """Propose a pool-size change. This cannot execute a mutation."""
    return _proposal("increase_connection_pool", rationale, service=service, size=size)


@mcp.tool()
def create_index(table: str, columns: list[str], rationale: str, concurrently: bool = True) -> dict:
    """Propose an index. This cannot execute a mutation."""
    return _proposal(
        "create_index",
        rationale,
        table=table,
        columns=columns,
        concurrently=concurrently,
    )


@mcp.tool()
def restart_service(service: str, rationale: str) -> dict:
    """Propose a modeled service restart. This cannot execute a mutation."""
    return _proposal("restart_service", rationale, service=service)


if __name__ == "__main__":
    mcp.run()
