from __future__ import annotations

import hashlib
import math
import ssl
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests

from app.data.discovery import DiscoveryResult
from app.data.postgres import deterministic_embedding
from app.data.webprobe import (
    LiveTargetMutationRefused,
    ProbeTransport,
    RawProbeResponse,
    RequestsProbeTransport,
    SocketTLSInspector,
    TLSInspector,
)
from app.policy.scope import DNSResolutionError, LiveScopeGuard, ScopeRefusal

CRAWLER_USER_AGENT = "HeimdallPropertyCrawler/2.1 (+https://arjunrnair.com)"


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(float(ordered[index]), 3)


def _route_key(path: str) -> str:
    return quote(path or "/", safe="/")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


@dataclass(frozen=True)
class CrawlPage:
    host: str
    url: str
    path: str
    depth: int
    status_code: int
    latency_p50_ms: float
    latency_p95_ms: float
    response_size_bytes: float
    redirect_count: int
    content_sha256: str
    sample_count: int
    measurement_truncated: bool


@dataclass(frozen=True)
class HostCrawl:
    host: str
    sources: tuple[str, ...]
    dns_resolve_ms: float | None
    tls_days_remaining: float | None
    pages: tuple[CrawlPage, ...]
    errors: tuple[dict[str, str], ...]
    robots_disallowed: tuple[str, ...]


@dataclass(frozen=True)
class WorstOffender:
    classification: str
    host: str
    route: str | None
    summary: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PropertyHealthMap:
    apex: str
    generated_at: str
    discovery: DiscoveryResult
    hosts: tuple[HostCrawl, ...]
    max_depth: int
    max_pages_per_host: int
    global_page_cap: int
    samples_per_page: int

    def metric_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for host in self.hosts:
            if host.dns_resolve_ms is not None:
                rows.append(
                    self._host_metric(host.host, "dns_resolve_ms", host.dns_resolve_ms, "ms")
                )
            if host.tls_days_remaining is not None:
                rows.append(
                    self._host_metric(
                        host.host, "tls_days_remaining", host.tls_days_remaining, "days"
                    )
                )
            for page in host.pages:
                prefix = f"metric:{page.host}:{_route_key(page.path)}"
                common = {
                    "service": page.host,
                    "route": page.path,
                    "recorded_at": self.generated_at,
                    "source": "property_crawl",
                    "sample_count": page.sample_count,
                    "measurement_truncated": page.measurement_truncated,
                }
                rows.extend(
                    [
                        {
                            **common,
                            "evidence_id": f"{prefix}:http_status",
                            "metric": "http_status",
                            "value": page.status_code,
                            "unit": "code",
                        },
                        {
                            **common,
                            "evidence_id": f"{prefix}:latency_p50",
                            "metric": "latency_p50",
                            "value": page.latency_p50_ms,
                            "unit": "ms",
                        },
                        {
                            **common,
                            "evidence_id": f"{prefix}:latency_p95",
                            "metric": "latency_p95",
                            "value": page.latency_p95_ms,
                            "unit": "ms",
                        },
                        {
                            **common,
                            "evidence_id": f"{prefix}:response_size_bytes",
                            "metric": "response_size_bytes",
                            "value": page.response_size_bytes,
                            "unit": "bytes",
                        },
                        {
                            **common,
                            "evidence_id": f"{prefix}:redirect_count",
                            "metric": "redirect_count",
                            "value": page.redirect_count,
                            "unit": "count",
                        },
                    ]
                )
        return rows

    def _host_metric(self, host: str, metric: str, value: float, unit: str) -> dict[str, Any]:
        return {
            "evidence_id": f"metric:{host}:{metric}",
            "service": host,
            "route": None,
            "metric": metric,
            "value": value,
            "unit": unit,
            "recorded_at": self.generated_at,
            "source": "property_crawl",
            "sample_count": 1,
            "measurement_truncated": False,
        }

    def log_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for host in self.hosts:
            for index, error in enumerate(host.errors, start=1):
                rows.append(
                    self._log(
                        host.host,
                        f"{error['kind']}:{index}",
                        "error",
                        error["kind"].replace("_", " "),
                        {"error": error["message"]},
                    )
                )
            failing = [page for page in host.pages if page.status_code >= 500]
            if failing:
                worst = max(failing, key=lambda page: (page.status_code, page.latency_p95_ms))
                rows.append(
                    self._log(
                        host.host,
                        "http_5xx",
                        "error",
                        f"HTTP 5xx response observed on route {worst.path}",
                        {
                            "route": worst.path,
                            "status_code": worst.status_code,
                            "route_evidence_id": (
                                f"metric:{host.host}:{_route_key(worst.path)}:http_status"
                            ),
                        },
                    )
                )
            high_latency = [page for page in host.pages if page.latency_p95_ms >= 1_000]
            if high_latency:
                slowest = max(high_latency, key=lambda page: page.latency_p95_ms)
                rows.append(
                    self._log(
                        host.host,
                        f"{_route_key(slowest.path)}:latency_high",
                        "warning",
                        f"web latency regression on route {slowest.path}",
                        {
                            "route": slowest.path,
                            "latency_p95_ms": slowest.latency_p95_ms,
                            "route_evidence_id": (
                                f"metric:{host.host}:{_route_key(slowest.path)}:latency_p95"
                            ),
                        },
                    )
                )
            if host.tls_days_remaining is not None and host.tls_days_remaining <= 30:
                rows.append(
                    self._log(
                        host.host,
                        "tls_expiring",
                        "warning",
                        "TLS certificate expiry is within 30 days",
                        {"tls_days_remaining": host.tls_days_remaining},
                    )
                )
            if host.pages and not failing and not high_latency and not any(
                error["kind"] == "dns_nxdomain" for error in host.errors
            ):
                rows.append(
                    self._log(
                        host.host,
                        "healthy",
                        "info",
                        "property crawl metrics normal",
                        {"page_count": len(host.pages)},
                    )
                )
        return rows

    def _log(
        self, host: str, kind: str, severity: str, message: str, attributes: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "evidence_id": f"log:{host}:{kind}",
            "service": host,
            "severity": severity,
            "message": message,
            "attributes": {**attributes, "source": "property_crawl"},
            "recorded_at": self.generated_at,
        }

    def worst_offender(self) -> WorstOffender:
        for host in self.hosts:
            dns_errors = [error for error in host.errors if error["kind"] == "dns_nxdomain"]
            if dns_errors:
                return WorstOffender(
                    classification="web_dns_resolution_failure",
                    host=host.host,
                    route=None,
                    summary=f"{host.host} failed public DNS resolution during the crawl.",
                    evidence_ids=(f"log:{host.host}:dns_nxdomain:1",),
                )

        failures = [
            page for host in self.hosts for page in host.pages if page.status_code >= 500
        ]
        if failures:
            page = max(failures, key=lambda item: (item.status_code, item.latency_p95_ms))
            return WorstOffender(
                classification="web_http_5xx",
                host=page.host,
                route=page.path,
                summary=f"{page.host}{page.path} returned HTTP {page.status_code}.",
                evidence_ids=(
                    f"metric:{page.host}:{_route_key(page.path)}:http_status",
                    f"log:{page.host}:http_5xx",
                ),
            )

        expiring = [
            host
            for host in self.hosts
            if host.tls_days_remaining is not None and host.tls_days_remaining <= 30
        ]
        if expiring:
            host = min(expiring, key=lambda item: item.tls_days_remaining or 0)
            return WorstOffender(
                classification="web_tls_certificate_expiry",
                host=host.host,
                route=None,
                summary=(
                    f"{host.host} has {host.tls_days_remaining:.1f} TLS certificate days left."
                ),
                evidence_ids=(
                    f"metric:{host.host}:tls_days_remaining",
                    f"log:{host.host}:tls_expiring",
                ),
            )

        pages = [page for host in self.hosts for page in host.pages]
        if pages:
            page = max(pages, key=lambda item: item.latency_p95_ms)
            if page.latency_p95_ms >= 1_000:
                return WorstOffender(
                    classification="web_latency_regression",
                    host=page.host,
                    route=page.path,
                    summary=(
                        f"{page.host}{page.path} is the slowest route at "
                        f"{page.latency_p95_ms:.1f} ms p95."
                    ),
                    evidence_ids=(
                        f"metric:{page.host}:{_route_key(page.path)}:latency_p95",
                        f"log:{page.host}:{_route_key(page.path)}:latency_high",
                    ),
                )
            return WorstOffender(
                classification="false_positive_alert",
                host=page.host,
                route=page.path,
                summary=(
                    f"No configured anomaly threshold fired; {page.host}{page.path} was the "
                    f"slowest observed route at {page.latency_p95_ms:.1f} ms p95."
                ),
                evidence_ids=(
                    f"metric:{page.host}:{_route_key(page.path)}:http_status",
                    f"metric:{page.host}:{_route_key(page.path)}:latency_p95",
                ),
            )
        return WorstOffender(
            classification="insufficient_or_ambiguous_evidence",
            host=self.apex,
            route=None,
            summary="No page measurements were available for a property diagnosis.",
            evidence_ids=(),
        )


class PropertyCrawler:
    """Sequential, robots-aware property crawler with hard depth and page limits."""

    def __init__(
        self,
        *,
        scope_guard: LiveScopeGuard | None = None,
        transport: ProbeTransport | None = None,
        tls_inspector: TLSInspector | None = None,
        max_depth: int = 2,
        max_pages_per_host: int = 25,
        global_page_cap: int = 50,
        samples_per_page: int = 2,
        rate_limit_seconds: float = 0.2,
        timeout_seconds: float = 6,
        max_body_bytes: int = 2_000_000,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_depth < 0 or max_depth > 2:
            raise ValueError("max_depth must be between 0 and 2")
        if not 1 <= max_pages_per_host <= 25:
            raise ValueError("max_pages_per_host must be between 1 and 25")
        if not 1 <= global_page_cap <= 250:
            raise ValueError("global_page_cap must be between 1 and 250")
        if not 1 <= samples_per_page <= 5:
            raise ValueError("samples_per_page must be between 1 and 5")
        if rate_limit_seconds < 0.2:
            raise ValueError("rate_limit_seconds must be at least 0.2")
        self.scope_guard = scope_guard or LiveScopeGuard.for_arjunrnair_property()
        self.transport = transport or RequestsProbeTransport(
            user_agent=CRAWLER_USER_AGENT, same_origin_only=True
        )
        self.tls_inspector = tls_inspector or SocketTLSInspector()
        self.max_depth = max_depth
        self.max_pages_per_host = max_pages_per_host
        self.global_page_cap = global_page_cap
        self.samples_per_page = samples_per_page
        self.rate_limit_seconds = rate_limit_seconds
        self.timeout_seconds = timeout_seconds
        self.max_body_bytes = max_body_bytes
        self.sleep = sleep
        self.monotonic = monotonic
        self._last_request: dict[str, float] = {}

    def crawl(self, discovery: DiscoveryResult) -> PropertyHealthMap:
        hosts: list[HostCrawl] = []
        remaining = self.global_page_cap
        for discovered in discovery.hosts:
            if remaining <= 0:
                break
            host_result, attempts = self._crawl_host(
                discovered.host,
                discovered.sources,
                min(self.max_pages_per_host, remaining),
            )
            hosts.append(host_result)
            remaining -= attempts
        return PropertyHealthMap(
            apex=discovery.apex,
            generated_at=datetime.now(UTC).isoformat(),
            discovery=discovery,
            hosts=tuple(hosts),
            max_depth=self.max_depth,
            max_pages_per_host=self.max_pages_per_host,
            global_page_cap=self.global_page_cap,
            samples_per_page=self.samples_per_page,
        )

    def _crawl_host(
        self, host: str, sources: tuple[str, ...], page_budget: int
    ) -> tuple[HostCrawl, int]:
        errors: list[dict[str, str]] = []
        try:
            scoped = self.scope_guard.validate(f"https://{host}/")
        except DNSResolutionError as exc:
            return (
                HostCrawl(
                    host=host,
                    sources=sources,
                    dns_resolve_ms=None,
                    tls_days_remaining=None,
                    pages=(),
                    errors=({"kind": "dns_nxdomain", "message": str(exc)},),
                    robots_disallowed=(),
                ),
                0,
            )
        dns_resolve_ms = scoped.dns_resolve_ms
        tls_days: float | None = None
        try:
            tls_days = self.tls_inspector.days_remaining(
                scoped,
                scope_guard=self.scope_guard,
                timeout_seconds=self.timeout_seconds,
            )
        except ScopeRefusal:
            raise
        except (OSError, ssl.SSLError, TimeoutError, ConnectionError) as exc:
            errors.append({"kind": "tls_failed", "message": f"{type(exc).__name__}: {exc}"})

        robots, disallowed, sitemap_urls = self._robots(host, errors)
        if robots.can_fetch(CRAWLER_USER_AGENT, "/sitemap.xml"):
            sitemap_urls.add(f"https://{host}/sitemap.xml")
        else:
            disallowed.add("/sitemap.xml")

        initial_urls = {f"https://{host}/"}
        for sitemap_url in sorted(sitemap_urls):
            sitemap_path = urlsplit(sitemap_url).path or "/"
            if not robots.can_fetch(CRAWLER_USER_AGENT, sitemap_path):
                disallowed.add(sitemap_path)
                continue
            sitemap = self._control_fetch(host, sitemap_url, errors)
            if sitemap and sitemap.status_code == 200:
                initial_urls.update(self._sitemap_links(host, sitemap.untrusted_body))

        queue: deque[tuple[str, int]] = deque()
        seen: set[str] = set()
        ordered_initial_urls = sorted(
            initial_urls, key=lambda value: (value != f"https://{host}/", value)
        )
        for candidate in ordered_initial_urls:
            canonical = self._validated_same_origin_link(host, f"https://{host}/", candidate)
            if canonical and robots.can_fetch(CRAWLER_USER_AGENT, urlsplit(canonical).path):
                queue.append((canonical, 0))
                seen.add(canonical)
            elif canonical:
                disallowed.add(urlsplit(canonical).path or "/")

        pages: list[CrawlPage] = []
        attempts = 0
        while queue and attempts < page_budget:
            url, depth = queue.popleft()
            path = urlsplit(url).path or "/"
            if not robots.can_fetch(CRAWLER_USER_AGENT, path):
                continue
            attempts += 1
            raw_samples: list[RawProbeResponse] = []
            try:
                for _ in range(self.samples_per_page):
                    raw_samples.append(self._fetch(host, url))
            except ScopeRefusal:
                raise
            except (OSError, TimeoutError, ConnectionError, requests.RequestException) as exc:
                errors.append(
                    {
                        "kind": "page_probe_failed",
                        "message": f"{url}: {type(exc).__name__}: {exc}",
                    }
                )
                continue
            page = self._safe_page(host, url, depth, raw_samples)
            pages.append(page)
            if depth >= self.max_depth:
                continue
            first = raw_samples[0]
            content_type = next(
                (
                    str(value).lower()
                    for key, value in first.headers.items()
                    if str(key).lower() == "content-type"
                ),
                "",
            )
            if content_type and "html" not in content_type:
                continue
            for href in self._html_links(first.untrusted_body):
                candidate = self._validated_same_origin_link(host, url, href)
                if not candidate or candidate in seen:
                    continue
                candidate_path = urlsplit(candidate).path or "/"
                if not robots.can_fetch(CRAWLER_USER_AGENT, candidate_path):
                    disallowed.add(candidate_path)
                    continue
                seen.add(candidate)
                queue.append((candidate, depth + 1))

        return (
            HostCrawl(
                host=host,
                sources=sources,
                dns_resolve_ms=dns_resolve_ms,
                tls_days_remaining=tls_days,
                pages=tuple(pages),
                errors=tuple(errors),
                robots_disallowed=tuple(sorted(disallowed)),
            ),
            attempts,
        )

    def _robots(
        self, host: str, errors: list[dict[str, str]]
    ) -> tuple[RobotFileParser, set[str], set[str]]:
        parser = RobotFileParser()
        parser.set_url(f"https://{host}/robots.txt")
        disallowed: set[str] = set()
        sitemaps: set[str] = set()
        raw = self._control_fetch(host, f"https://{host}/robots.txt", errors)
        if not raw or raw.status_code == 429 or raw.status_code >= 500:
            parser.disallow_all = True
            return parser, disallowed, sitemaps
        if raw.status_code != 200:
            parser.parse([])
            return parser, disallowed, sitemaps
        text = raw.untrusted_body.decode("utf-8", errors="replace")
        parser.parse(text.splitlines())
        for line in text.splitlines():
            name, separator, value = line.partition(":")
            if not separator:
                continue
            if name.strip().lower() == "sitemap" and value.strip():
                candidate = self._validated_same_origin_link(
                    host, f"https://{host}/", value.strip()
                )
                if candidate:
                    sitemaps.add(candidate)
        return parser, disallowed, sitemaps

    def _control_fetch(
        self, host: str, url: str, errors: list[dict[str, str]]
    ) -> RawProbeResponse | None:
        try:
            return self._fetch(host, url)
        except ScopeRefusal:
            raise
        except (OSError, TimeoutError, ConnectionError, requests.RequestException) as exc:
            errors.append(
                {"kind": "control_fetch_failed", "message": f"{url}: {type(exc).__name__}: {exc}"}
            )
            return None

    def _fetch(self, host: str, url: str) -> RawProbeResponse:
        scoped = self.scope_guard.validate(url)
        if scoped.host != host:
            raise ScopeRefusal("Crawler fetch crossed the same-origin boundary")
        self._rate_limit(host)
        return self.transport.fetch(
            scoped,
            scope_guard=self.scope_guard,
            timeout_seconds=self.timeout_seconds,
            max_body_bytes=self.max_body_bytes,
        )

    def _rate_limit(self, host: str) -> None:
        now = self.monotonic()
        last = self._last_request.get(host)
        if last is not None:
            remaining = self.rate_limit_seconds - (now - last)
            if remaining > 0:
                self.sleep(remaining)
                now = self.monotonic()
        self._last_request[host] = now

    def _validated_same_origin_link(
        self, host: str, base_url: str, raw_link: str
    ) -> str | None:
        candidate = urljoin(base_url, raw_link.strip())
        parsed = urlsplit(candidate)
        try:
            port = parsed.port or 443
        except ValueError:
            return None
        candidate_host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() != "https" or port != 443 or candidate_host != host:
            return None
        canonical = urlunsplit(("https", host, parsed.path or "/", "", ""))
        try:
            self.scope_guard.validate(canonical)
        except (DNSResolutionError, ScopeRefusal):
            return None
        return canonical

    @staticmethod
    def _html_links(body: bytes) -> list[str]:
        parser = _LinkParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
        return parser.links

    def _sitemap_links(self, host: str, body: bytes) -> set[str]:
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            return set()
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return set()
        links: set[str] = set()
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1].lower() != "loc" or not element.text:
                continue
            candidate = self._validated_same_origin_link(
                host, f"https://{host}/", element.text.strip()
            )
            if candidate:
                links.add(candidate)
        return links

    @staticmethod
    def _safe_page(
        host: str, url: str, depth: int, samples: Sequence[RawProbeResponse]
    ) -> CrawlPage:
        statuses = [sample.status_code for sample in samples]
        latency = [sample.total_ms for sample in samples]
        sizes = [len(sample.untrusted_body) for sample in samples]
        redirects = [sample.redirect_count for sample in samples]
        first_body = samples[0].untrusted_body
        return CrawlPage(
            host=host,
            url=url,
            path=urlsplit(url).path or "/",
            depth=depth,
            status_code=max(statuses),
            latency_p50_ms=_percentile(latency, 0.50),
            latency_p95_ms=_percentile(latency, 0.95),
            response_size_bytes=_percentile(sizes, 0.50),
            redirect_count=int(_percentile(redirects, 0.95)),
            content_sha256=hashlib.sha256(first_body).hexdigest(),
            sample_count=len(samples),
            measurement_truncated=any(sample.truncated for sample in samples),
        )


class PropertyHealthDataStore:
    """Read-only adapter exposing a completed property map to IncidentAgent."""

    is_live_target = True
    is_property_map = True

    def __init__(self, health_map: PropertyHealthMap, runbook_dir: Path | str = "runbooks") -> None:
        self.health_map = health_map
        self.target_host = health_map.apex
        self.runbook_dir = Path(runbook_dir)

    def query_metrics(self, service: str, metric: str, window: str) -> list[dict[str, Any]]:
        rows = self.health_map.metric_rows()
        return rows if metric in {"*", "%"} else [row for row in rows if row["metric"] == metric]

    def get_recent_deployments(self, service: str, window: str) -> list[dict[str, Any]]:
        return []

    def inspect_logs(
        self, service: str, severity: str | None, window: str, contains: str | None
    ) -> list[dict[str, Any]]:
        rows = self.health_map.log_rows()
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
            "reason": "not applicable for property crawl",
            "backend": "property_health_map",
            "evidence_ids": [],
        }

    def get_table_stats(self, table: str) -> dict[str, Any]:
        return {
            "status": "not_applicable",
            "reason": "not applicable for property crawl",
            "backend": "property_health_map",
            "stats": {},
            "evidence_ids": [],
        }

    def get_index_stats(self, table: str) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": f"not_applicable:{self.target_host}:index_stats",
                "status": "not_applicable",
                "reason": "not applicable for property crawl",
                "backend": "property_health_map",
            }
        ]

    def mutate(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        raise LiveTargetMutationRefused(
            f"Mutation {tool_name!r} refused: property crawls are diagnosis-only"
        )
