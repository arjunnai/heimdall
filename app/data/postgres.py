from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

_WINDOW = re.compile(r"^(\d+)(m|h|d)$")
_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _interval(window: str) -> str:
    match = _WINDOW.fullmatch(window)
    if not match:
        raise ValueError("window must look like 30m, 2h, or 7d")
    count, unit = match.groups()
    units = {"m": "minutes", "h": "hours", "d": "days"}
    return f"{count} {units[unit]}"


def deterministic_embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 8) for value in vector]


class PostgresDataStore:
    """Production datastore. All diagnostics execute against PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @contextmanager
    def connection(self, *, read_only: bool = True) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            if read_only:
                connection.execute("SET TRANSACTION READ ONLY")
            yield connection

    def query_metrics(self, service: str, metric: str, window: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT evidence_id, service, metric, value, unit, recorded_at
                FROM metrics
                WHERE service = %s AND (%s IN ('*', '%%') OR metric = %s)
                  AND recorded_at >= now() - %s::interval
                ORDER BY recorded_at DESC LIMIT 200
                """,
                (service, metric, metric, _interval(window)),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_deployments(self, service: str, window: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT evidence_id, service, version, commit_sha, status, deployed_at
                FROM deployments WHERE service = %s
                  AND deployed_at >= now() - %s::interval
                ORDER BY deployed_at DESC LIMIT 50
                """,
                (service, _interval(window)),
            ).fetchall()
        return [dict(row) for row in rows]

    def inspect_logs(
        self, service: str, severity: str | None, window: str, contains: str | None
    ) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT evidence_id, service, severity, message, attributes, recorded_at
                FROM logs WHERE service = %s
                  AND (%s IS NULL OR lower(severity) = lower(%s))
                  AND (%s IS NULL OR message ILIKE '%%' || %s || '%%')
                  AND recorded_at >= now() - %s::interval
                ORDER BY recorded_at DESC LIMIT 200
                """,
                (service, severity, severity, contains, contains, _interval(window)),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_runbooks(self, query: str, limit: int) -> list[dict[str, Any]]:
        embedding = deterministic_embedding(query)
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT evidence_id, source, heading, content,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM runbook_chunks ORDER BY embedding <=> %s::vector LIMIT %s
                """,
                (embedding, embedding, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def explain_query(self, sql: str) -> dict[str, Any]:
        with self.connection() as connection:
            plan = connection.execute(f"EXPLAIN (FORMAT JSON) {sql}").fetchone()["QUERY PLAN"]
        digest = hashlib.sha256(sql.encode()).hexdigest()[:12]
        return {"plan": plan, "evidence_ids": [f"explain:{digest}"], "backend": "postgres"}

    def get_table_stats(self, table: str) -> dict[str, Any]:
        if not _IDENTIFIER.fullmatch(table):
            raise ValueError("Invalid table identifier")
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT relname AS table, n_live_tup, n_dead_tup, last_analyze, last_autoanalyze
                FROM pg_stat_user_tables WHERE relname = %s
                """,
                (table,),
            ).fetchone()
        if not row:
            return {"stats": {}, "evidence_ids": []}
        result = dict(row)
        evidence_id = f"table_stats:{table}:{result['n_live_tup']}:{result['n_dead_tup']}"
        result["evidence_id"] = evidence_id
        return {"stats": result, "evidence_ids": [evidence_id]}

    def get_index_stats(self, table: str) -> list[dict[str, Any]]:
        if not _IDENTIFIER.fullmatch(table):
            raise ValueError("Invalid table identifier")
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT i.relname AS index_name, s.idx_scan, s.idx_tup_read, s.idx_tup_fetch,
                       pg_get_indexdef(s.indexrelid) AS definition
                FROM pg_stat_user_indexes s JOIN pg_class i ON i.oid = s.indexrelid
                WHERE s.relname = %s ORDER BY i.relname
                """,
                (table,),
            ).fetchall()
        return [
            {**dict(row), "evidence_id": f"index_stats:{table}:{row['index_name']}"} for row in rows
        ]

    def mutate(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "create_index":
            table = str(args["table"])
            columns = [str(column) for column in args["columns"]]
            if (
                not _IDENTIFIER.fullmatch(table)
                or not columns
                or not all(_IDENTIFIER.fullmatch(column) for column in columns)
            ):
                raise ValueError("Invalid table or column identifier")
            index_name = f"{table}_{'_'.join(columns)}_idx"
            concurrently = "CONCURRENTLY " if args.get("concurrently", True) else ""
            with psycopg.connect(self.database_url, autocommit=True) as connection:
                connection.execute(
                    f"CREATE INDEX {concurrently}IF NOT EXISTS {index_name} "
                    f"ON {table} ({', '.join(columns)})"
                )
            return {"status": "executed", "backend": "postgres", "index": index_name}

        service = str(args["service"])
        with self.connection(read_only=False) as connection:
            if tool_name == "increase_connection_pool":
                connection.execute(
                    "UPDATE service_state SET connection_pool_size = %s, updated_at = now() "
                    "WHERE service = %s",
                    (int(args["size"]), service),
                )
            elif tool_name == "rollback_deployment":
                connection.execute(
                    "UPDATE service_state SET version = %s, updated_at = now() WHERE service = %s",
                    (str(args["to_version"]), service),
                )
            elif tool_name == "restart_service":
                connection.execute(
                    "UPDATE service_state SET restart_count = restart_count + 1, "
                    "updated_at = now() WHERE service = %s",
                    (service,),
                )
            else:
                raise ValueError(f"Unsupported mutation: {tool_name}")
        return {"status": "executed", "backend": "modeled-service-state", "tool": tool_name}
