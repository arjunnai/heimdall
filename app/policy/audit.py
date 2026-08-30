from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


class AuditLog:
    """Append-only JSONL audit sink. Existing entries are never rewritten."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def append(
        self,
        *,
        decision: str,
        tool: str | None,
        tool_call_id: str | None,
        args: dict[str, Any] | None,
        outcome: str,
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "ts": datetime.now(UTC).isoformat(),
            "decision": decision,
            "tool": tool,
            "tool_call_id": tool_call_id,
            "args": args or {},
            "outcome": outcome,
            "actor": actor,
            "details": details or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, sort_keys=True, default=str) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-max(1, min(limit, 2000)) :]]
