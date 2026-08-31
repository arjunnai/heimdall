from __future__ import annotations

import hashlib
import math
import socket
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import urljoin

import requests

from app.data.postgres import deterministic_embedding
from app.policy.scope import DNSResolutionError, LiveScopeGuard, ScopedTarget, ScopeRefusal

_CACHE_MISS_STATES = frozenset({"MISS", "DYNAMIC", "BYPASS", "EXPIRED", "STALE"})
_CACHE_KNOWN_STATES = _CACHE_MISS_STATES | frozenset({"HIT", "REVALIDATED", "UPDATING"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class LiveTargetMutationRefused(PermissionError):
    """No mutating operation may execute against a live web target."""


@dataclass(frozen=True)
class RawProbeResponse:
    """Ephemeral transport output. Body bytes are discarded at the adapter boundary."""

    status_code: int
    ttfb_ms: float
    total_ms: float
    headers: Mapping[str, str]
    untrusted_body: bytes
    redirect_count: int = 0
    truncated: bool = False


class ProbeTransport(Protocol):
    def fetch(
        self,
        target: ScopedTarget,
        *,
        scope_guard: LiveScopeGuard,
        timeout_seconds: float,
        max_body_bytes: int,
    ) -> RawProbeResponse: ...


class RequestsProbeTransport:
    """HTTPS transport with guarded, manually followed redirects."""

    def __init__(
        self,
        *,
        user_agent: str = "Heimdall-Live-Probe/2.0",
        same_origin_only: bool = False,
    ) -> None:
        self.user_agent = user_agent
        self.same_origin_only = same_origin_only

    def fetch(
        self,
        target: ScopedTarget,
        *,
        scope_guard: LiveScopeGuard,
        timeout_seconds: float,
        max_body_bytes: int,
    ) -> RawProbeResponse:
        started = perf_counter()
        current = target
        original_origin = (target.host, target.port)
        redirect_count = 0
        while True:
            # Re-resolve immediately before every network request, including redirects.
            current = scope_guard.validate(current.url)
            response = requests.get(
                current.url,
                allow_redirects=False,
                headers={"User-Agent": self.user_agent},
                stream=True,
                timeout=(timeout_seconds, timeout_seconds),
            )
            if response.status_code in _REDIRECT_STATUSES and response.headers.get("location"):
                if redirect_count >= 5:
                    response.close()
                    raise ConnectionError("Live probe exceeded five guarded redirects")
                next_url = urljoin(current.url, response.headers["location"])
                next_target = scope_guard.validate(next_url)
                if self.same_origin_only and (
                    next_target.host,
                    next_target.port,
                ) != original_origin:
                    total_ms = (perf_counter() - started) * 1000
                    response.close()
                    return RawProbeResponse(
                        status_code=response.status_code,
                        ttfb_ms=round(response.elapsed.total_seconds() * 1000, 3),
                        total_ms=round(total_ms, 3),
                        headers={},
                        untrusted_body=b"",
                        redirect_count=redirect_count + 1,
                    )
                response.close()
                current = next_target
                redirect_count += 1
                continue

            ttfb_ms = response.elapsed.total_seconds() * 1000
            body = bytearray()
            truncated = False
            try:
                for chunk in response.iter_content(chunk_size=16_384):
                    if not chunk:
                        continue
                    remaining = max_body_bytes - len(body)
                    if remaining <= 0:
                        truncated = True
                        break
                    body.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
                        break
            finally:
                response.close()
            total_ms = (perf_counter() - started) * 1000
            return RawProbeResponse(
                status_code=response.status_code,
                ttfb_ms=round(ttfb_ms, 3),
                total_ms=round(total_ms, 3),
                headers=dict(response.headers),
                untrusted_body=bytes(body),
                redirect_count=redirect_count,
                truncated=truncated,
            )


class TLSInspector(Protocol):
    def days_remaining(
        self, target: ScopedTarget, *, scope_guard: LiveScopeGuard, timeout_seconds: float
    ) -> float: ...


class SocketTLSInspector:
    def days_remaining(
        self, target: ScopedTarget, *, scope_guard: LiveScopeGuard, timeout_seconds: float
    ) -> float:
        checked = scope_guard.validate(target.url)
        context = ssl.create_default_context()
        with socket.create_connection((checked.host, checked.port), timeout=timeout_seconds) as raw:
            with context.wrap_socket(raw, server_hostname=checked.host) as secured:
                certificate = secured.getpeercert()
        expires = certificate.get("notAfter")
        if not expires:
            raise ssl.SSLError("Peer certificate omitted notAfter")
        seconds = ssl.cert_time_to_seconds(expires) - datetime.now(UTC).timestamp()
        return round(seconds / 86_400, 3)


@dataclass(frozen=True)
class SafeProbeSample:
    """Model-visible probe data contains no response body or free-form remote text."""

    status_code: int
    ttfb_ms: float
    total_ms: float
    response_size_bytes: int
    redirect_count: int
    cache_status: str | None
    content_sha256: str
    truncated: bool
    dns_resolve_ms: float


@dataclass(frozen=True)
class ProbeSnapshot:
    target: str
    host: str
    recorded_at: str
    requested_samples: int
    samples: tuple[SafeProbeSample, ...]
    tls_days_remaining: float | None
    errors: tuple[dict[str, str], ...]


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(float(ordered[index]), 3)


def _cache_status(headers: Mapping[str, str]) -> str | None:
    lowered = {str(key).lower(): str(value) for key, value in headers.items()}
    raw = lowered.get("cf-cache-status") or lowered.get("x-nextjs-cache")
    if not raw:
        return None
    normalized = raw.split(",", 1)[0].strip().upper()
    return normalized if normalized in _CACHE_KNOWN_STATES else "UNKNOWN"


class WebProbeDataStore:
    """Live, read-only synthetics adapter with a quarantined content boundary."""

    is_live_target = True

    def __init__(
        self,
        target: str,
        *,
        samples: int = 3,
        scope_guard: LiveScopeGuard | None = None,
        transport: ProbeTransport | None = None,
        tls_inspector: TLSInspector | None = None,
        timeout_seconds: float = 10,
        max_body_bytes: int = 2_000_000,
        runbook_dir: Path | str = "runbooks",
    ) -> None:
        if not 1 <= samples <= 20:
            raise ValueError("samples must be between 1 and 20")
        self.scope_guard = scope_guard or LiveScopeGuard()
        normalized_url, host, _ = self.scope_guard.normalize(target)
        self.target_url = normalized_url
        self.target_host = host
        self.samples = samples
        self.transport = transport or RequestsProbeTransport()
        self.tls_inspector = tls_inspector or SocketTLSInspector()
        self.timeout_seconds = timeout_seconds
        self.max_body_bytes = max_body_bytes
        self.runbook_dir = Path(runbook_dir)
        self._cached_snapshot: ProbeSnapshot | None = None

    @property
    def snapshot(self) -> ProbeSnapshot | None:
        return self._cached_snapshot

    def _collect(self) -> ProbeSnapshot:
        if self._cached_snapshot is not None:
            return self._cached_snapshot
        safe_samples: list[SafeProbeSample] = []
        errors: list[dict[str, str]] = []
        first_scoped: ScopedTarget | None = None
        for _ in range(self.samples):
            try:
                scoped = self.scope_guard.validate(self.target_url)
                first_scoped = first_scoped or scoped
                raw = self.transport.fetch(
                    scoped,
                    scope_guard=self.scope_guard,
                    timeout_seconds=self.timeout_seconds,
                    max_body_bytes=self.max_body_bytes,
                )
            except DNSResolutionError as exc:
                errors.append({"kind": "dns_nxdomain", "message": str(exc)})
                break
            except ScopeRefusal:
                raise
            except (requests.RequestException, ConnectionError, TimeoutError, OSError) as exc:
                errors.append({"kind": "probe_failed", "message": f"{type(exc).__name__}: {exc}"})
                continue
            # Untrusted bytes terminate here: only length and a one-way digest survive.
            safe_samples.append(
                SafeProbeSample(
                    status_code=int(raw.status_code),
                    ttfb_ms=round(float(raw.ttfb_ms), 3),
                    total_ms=round(float(raw.total_ms), 3),
                    response_size_bytes=len(raw.untrusted_body),
                    redirect_count=int(raw.redirect_count),
                    cache_status=_cache_status(raw.headers),
                    content_sha256=hashlib.sha256(raw.untrusted_body).hexdigest(),
                    truncated=bool(raw.truncated),
                    dns_resolve_ms=scoped.dns_resolve_ms,
                )
            )

        tls_days: float | None = None
        if first_scoped is not None:
            try:
                tls_days = self.tls_inspector.days_remaining(
                    first_scoped,
                    scope_guard=self.scope_guard,
                    timeout_seconds=self.timeout_seconds,
                )
            except ScopeRefusal:
                raise
            except (ssl.SSLError, OSError, ConnectionError, TimeoutError) as exc:
                errors.append({"kind": "tls_failed", "message": f"{type(exc).__name__}: {exc}"})

        self._cached_snapshot = ProbeSnapshot(
            target=self.target_url,
            host=self.target_host,
            recorded_at=datetime.now(UTC).isoformat(),
            requested_samples=self.samples,
            samples=tuple(safe_samples),
            tls_days_remaining=tls_days,
            errors=tuple(errors),
        )
        return self._cached_snapshot

    def _metric(self, name: str, value: float | int, unit: str, snapshot: ProbeSnapshot) -> dict:
        return {
            "evidence_id": f"metric:{self.target_host}:{name}",
            "service": self.target_host,
            "metric": name,
            "value": value,
            "unit": unit,
            "recorded_at": snapshot.recorded_at,
            "source": "live_probe",
            "sample_count": len(snapshot.samples),
            "measurement_truncated": any(sample.truncated for sample in snapshot.samples),
        }

    def query_metrics(self, service: str, metric: str, window: str) -> list[dict[str, Any]]:
        snapshot = self._collect()
        rows: list[dict[str, Any]] = []
        if snapshot.samples:
            statuses = [sample.status_code for sample in snapshot.samples]
            ttfb = [sample.ttfb_ms for sample in snapshot.samples]
            latency = [sample.total_ms for sample in snapshot.samples]
            sizes = [sample.response_size_bytes for sample in snapshot.samples]
            redirects = [sample.redirect_count for sample in snapshot.samples]
            dns = [sample.dns_resolve_ms for sample in snapshot.samples]
            rows.extend(
                [
                    self._metric("http_status", max(statuses), "code", snapshot),
                    self._metric("ttfb_p50", _percentile(ttfb, 0.50), "ms", snapshot),
                    self._metric("ttfb_p95", _percentile(ttfb, 0.95), "ms", snapshot),
                    self._metric("latency_p50", _percentile(latency, 0.50), "ms", snapshot),
                    self._metric("latency_p95", _percentile(latency, 0.95), "ms", snapshot),
                    self._metric(
                        "response_size_bytes", _percentile(sizes, 0.50), "bytes", snapshot
                    ),
                    self._metric(
                        "redirect_count", _percentile(redirects, 0.95), "count", snapshot
                    ),
                    self._metric("dns_resolve_ms", _percentile(dns, 0.50), "ms", snapshot),
                ]
            )
        else:
            rows.append(self._metric("probe_success", 0, "boolean", snapshot))
        if snapshot.tls_days_remaining is not None:
            rows.append(
                self._metric(
                    "tls_days_remaining", snapshot.tls_days_remaining, "days", snapshot
                )
            )
        if metric not in {"*", "%"}:
            rows = [row for row in rows if row["metric"] == metric]
        return rows

    def get_recent_deployments(self, service: str, window: str) -> list[dict[str, Any]]:
        return []

    def inspect_logs(
        self, service: str, severity: str | None, window: str, contains: str | None
    ) -> list[dict[str, Any]]:
        snapshot = self._collect()
        rows: list[dict[str, Any]] = []

        def add(kind: str, level: str, message: str, attributes: dict[str, Any]) -> None:
            rows.append(
                {
                    "evidence_id": f"log:{self.target_host}:{kind}",
                    "service": self.target_host,
                    "severity": level,
                    "message": message,
                    "attributes": {**attributes, "source": "live_probe"},
                    "recorded_at": snapshot.recorded_at,
                }
            )

        for error in snapshot.errors:
            add(
                error["kind"],
                "error",
                error["kind"].replace("_", " "),
                {"error": error["message"]},
            )
        if snapshot.samples:
            statuses = [sample.status_code for sample in snapshot.samples]
            status = max(statuses)
            if any(item >= 500 for item in statuses):
                add(
                    "http_5xx",
                    "error",
                    "HTTP 5xx response observed",
                    {"status_codes": statuses},
                )
            elif any(item >= 400 for item in statuses):
                add(
                    "http_error",
                    "warning",
                    "HTTP error response observed",
                    {"status_codes": statuses},
                )
            latency_p95 = _percentile([sample.total_ms for sample in snapshot.samples], 0.95)
            if latency_p95 >= 1_000:
                add(
                    "latency_high",
                    "warning",
                    "web latency regression: p95 exceeded 1000 ms",
                    {"latency_p95_ms": latency_p95},
                )
            if any(sample.cache_status in _CACHE_MISS_STATES for sample in snapshot.samples):
                cache_states = sorted(
                    {sample.cache_status for sample in snapshot.samples if sample.cache_status}
                )
                add(
                    "cache_miss",
                    "warning",
                    "cache miss observed in trusted response-header classification",
                    {"cache_statuses": cache_states},
                )
            if not rows:
                add("healthy", "info", "live probe metrics normal", {"status_code": status})
        if snapshot.tls_days_remaining is not None and snapshot.tls_days_remaining <= 30:
            add(
                "tls_expiring",
                "warning",
                "TLS certificate expiry is within 30 days",
                {"tls_days_remaining": snapshot.tls_days_remaining},
            )
        if severity:
            rows = [row for row in rows if row["severity"].lower() == severity.lower()]
        if contains:
            rows = [row for row in rows if contains.lower() in row["message"].lower()]
        return rows

    def search_runbooks(self, query: str, limit: int) -> list[dict[str, Any]]:
        query_embedding = deterministic_embedding(query)
        ranked: list[tuple[float, Path, str]] = []
        for path in sorted(self.runbook_dir.glob("*.md")):
            content = path.read_text()
            embedding = deterministic_embedding(content)
            similarity = sum(
                left * right for left, right in zip(query_embedding, embedding, strict=True)
            )
            ranked.append((similarity, path, content))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "evidence_id": f"runbook:{path.stem}:1",
                "source": path.name,
                "heading": content.splitlines()[0].lstrip("# "),
                "content": content,
                "similarity": round(similarity, 6),
                "backend": "local_runbook_rag",
            }
            for similarity, path, content in ranked[:limit]
        ]

    def explain_query(self, sql: str) -> dict[str, Any]:
        return {
            "status": "not_applicable",
            "reason": "not applicable for web target",
            "backend": "live_web_probe",
            "evidence_ids": [],
        }

    def get_table_stats(self, table: str) -> dict[str, Any]:
        return {
            "status": "not_applicable",
            "reason": "not applicable for web target",
            "backend": "live_web_probe",
            "stats": {},
            "evidence_ids": [],
        }

    def get_index_stats(self, table: str) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": f"not_applicable:{self.target_host}:index_stats",
                "status": "not_applicable",
                "reason": "not applicable for web target",
                "backend": "live_web_probe",
            }
        ]

    def mutate(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        raise LiveTargetMutationRefused(
            f"Mutation {tool_name!r} refused: live web targets are diagnosis-only"
        )
