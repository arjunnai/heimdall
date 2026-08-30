from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg
import yaml

from app.config import get_settings
from app.data.postgres import deterministic_embedding

TABLE_COLUMNS = {
    "metrics": ["evidence_id", "service", "metric", "value", "unit"],
    "deployments": ["evidence_id", "service", "version", "commit_sha", "status"],
    "logs": ["evidence_id", "service", "severity", "message", "attributes"],
}


def _values(row: dict[str, Any], columns: list[str]) -> list[Any]:
    values = [row.get(column, {} if column == "attributes" else None) for column in columns]
    return [json.dumps(value) if isinstance(value, dict) else value for value in values]


def seed_database(seed: str, database_url: str | None = None) -> None:
    path = Path("db/seeds") / f"{seed}.yaml"
    data = yaml.safe_load(path.read_text())
    url = database_url or get_settings().database_url
    with psycopg.connect(url) as connection:
        connection.execute("DROP INDEX IF EXISTS orders_customer_id_idx")
        connection.execute("DROP INDEX IF EXISTS orders_notes_trgm_idx")
        connection.execute("TRUNCATE metrics, deployments, logs, service_state, orders")
        for table, columns in TABLE_COLUMNS.items():
            placeholders = ", ".join(["%s"] * len(columns))
            statement = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            for row in data.get(table, []):
                connection.execute(statement, _values(row, columns))
        state = data.get("service_state", {})
        if state:
            connection.execute(
                """INSERT INTO service_state(service, version, connection_pool_size)
                   VALUES (%s, %s, %s)""",
                (state["service"], state.get("version"), state.get("connection_pool_size", 20)),
            )
        orders = data.get("orders", [])
        for row in orders:
            connection.execute(
                "INSERT INTO orders(customer_id, status, notes) VALUES (%s, %s, %s)",
                (row["customer_id"], row["status"], row.get("notes", "")),
            )
        for statement in data.get("setup_sql", []):
            connection.execute(statement)
        connection.execute("TRUNCATE runbook_chunks")
        for runbook in Path("runbooks").glob("*.md"):
            content = runbook.read_text()
            evidence_id = f"runbook:{runbook.stem}:1"
            connection.execute(
                """INSERT INTO runbook_chunks(evidence_id, source, heading, content, embedding)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    evidence_id,
                    runbook.name,
                    content.splitlines()[0].lstrip("# "),
                    content,
                    deterministic_embedding(content),
                ),
            )
        if not data.get("skip_analyze", False):
            connection.execute("ANALYZE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load a deterministic OpsPilot seed")
    parser.add_argument("seed", nargs="?", default="checkout_v42_pool")
    args = parser.parse_args()
    seed_database(args.seed)
