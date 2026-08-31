from __future__ import annotations

import ipaddress
import json
import socket
import ssl
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

import requests

from app.policy.scope import (
    PROPERTY_ROOT_DOMAIN,
    DNSResolutionError,
    LiveScopeGuard,
    ScopeRefusal,
)

DISCOVERY_SOURCE_HOSTS = frozenset(
    {
        PROPERTY_ROOT_DOMAIN,
        "api.certspotter.com",
        "otx.alienvault.com",
        "web.archive.org",
    }
)
COMMON_SUBDOMAINS = (
    "www",
    "api",
    "app",
    "blog",
    "dev",
    "staging",
    "cdn",
    "mail",
    "docs",
    "static",
    "assets",
    "status",
)

SourceResolver = Callable[[str, int], Iterable[str]]


def _resolve(host: str, port: int) -> Iterable[str]:
    return {
        entry[4][0]
        for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    }


def _public_addresses(addresses: Iterable[str]) -> tuple[str, ...]:
    rendered_addresses = tuple(sorted(set(addresses)))
    if not rendered_addresses:
        raise ConnectionError("Discovery source returned no DNS addresses")
    for rendered in rendered_addresses:
        address = ipaddress.ip_address(rendered)
        if any(
            (
                address.is_private,
                address.is_loopback,
                address.is_link_local,
                address.is_reserved,
                address.is_multicast,
                address.is_unspecified,
            )
        ):
            raise ScopeRefusal(f"Discovery source resolved to non-public address {address}")
    return rendered_addresses


class DiscoverySourceGuard:
    """Separate exact allow-list for certificate and passive-discovery endpoints."""

    def __init__(self, *, resolver: SourceResolver | None = None) -> None:
        self.resolver = resolver or _resolve

    def validate(self, target: str) -> str:
        parsed = urlsplit(target if "://" in target else f"https://{target}")
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if parsed.scheme.lower() != "https" or parsed.port not in {None, 443}:
            raise ScopeRefusal("Discovery sources require HTTPS port 443")
        if parsed.username or parsed.password or host not in DISCOVERY_SOURCE_HOSTS:
            raise ScopeRefusal(f"Discovery source host {host!r} is not allow-listed")
        _public_addresses(self.resolver(host, 443))
        return host


class DiscoveryTransport(Protocol):
    def tls_sans(self, host: str, *, timeout_seconds: float) -> Sequence[str]: ...

    def get_json(self, url: str, *, timeout_seconds: float) -> Any: ...


class RequestsDiscoveryTransport:
    user_agent = "Heimdall-Property-Discovery/2.1"

    def tls_sans(self, host: str, *, timeout_seconds: float) -> Sequence[str]:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout_seconds) as raw:
            with context.wrap_socket(raw, server_hostname=host) as secured:
                certificate = secured.getpeercert()
        return [
            str(value)
            for kind, value in certificate.get("subjectAltName", ())
            if kind == "DNS"
        ]

    def get_json(self, url: str, *, timeout_seconds: float) -> Any:
        response = requests.get(
            url,
            headers={"User-Agent": self.user_agent},
            stream=True,
            timeout=(timeout_seconds, timeout_seconds),
        )
        try:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(chunk_size=16_384):
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ValueError("Discovery source response exceeded 2 MB")
            return json.loads(body)
        finally:
            response.close()


@dataclass(frozen=True)
class DiscoveredHost:
    host: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryResult:
    apex: str
    hosts: tuple[DiscoveredHost, ...]
    source_errors: Mapping[str, str]


class SubdomainDiscovery:
    """Resilient TLS-SAN, passive, and bounded active discovery."""

    def __init__(
        self,
        *,
        property_guard: LiveScopeGuard | None = None,
        source_guard: DiscoverySourceGuard | None = None,
        transport: DiscoveryTransport | None = None,
        timeout_seconds: float = 3,
        common_subdomains: Sequence[str] = COMMON_SUBDOMAINS,
        max_hosts: int = 20,
        max_candidates_per_source: int = 100,
    ) -> None:
        self.property_guard = property_guard or LiveScopeGuard.for_arjunrnair_property()
        self.source_guard = source_guard or DiscoverySourceGuard()
        self.transport = transport or RequestsDiscoveryTransport()
        self.timeout_seconds = timeout_seconds
        self.common_subdomains = tuple(common_subdomains)
        self.max_hosts = max_hosts
        self.max_candidates_per_source = max_candidates_per_source

    def discover(self, apex: str = PROPERTY_ROOT_DOMAIN) -> DiscoveryResult:
        if apex.lower().rstrip(".") != PROPERTY_ROOT_DOMAIN:
            raise ScopeRefusal("Property discovery is restricted to arjunrnair.com")
        candidate_sources: dict[str, set[str]] = defaultdict(set)
        source_errors: dict[str, str] = {}
        candidate_sources[PROPERTY_ROOT_DOMAIN].add("apex")

        try:
            self.source_guard.validate(PROPERTY_ROOT_DOMAIN)
            for name in self.transport.tls_sans(
                PROPERTY_ROOT_DOMAIN, timeout_seconds=self.timeout_seconds
            )[: self.max_candidates_per_source]:
                self._add_candidate(candidate_sources, str(name), "tls_san")
        except (
            OSError,
            ssl.SSLError,
            TimeoutError,
            ConnectionError,
            ScopeRefusal,
            ValueError,
        ) as exc:
            source_errors["tls_san"] = f"{type(exc).__name__}: {exc}"

        passive_calls = (
            ("certspotter", self._certspotter),
            ("alienvault_otx", self._alienvault),
            ("wayback_cdx", self._wayback),
        )
        for source, loader in passive_calls:
            try:
                for name in loader()[: self.max_candidates_per_source]:
                    self._add_candidate(candidate_sources, name, source)
            except (
                OSError,
                TimeoutError,
                ConnectionError,
                ScopeRefusal,
                ValueError,
                TypeError,
                KeyError,
                requests.RequestException,
            ) as exc:
                source_errors[source] = f"{type(exc).__name__}: {exc}"

        for label in self.common_subdomains:
            self._add_candidate(
                candidate_sources,
                f"{label}.{PROPERTY_ROOT_DOMAIN}",
                "active_common_wordlist",
            )

        priority = {"apex": 0, "tls_san": 1, "active_common_wordlist": 2}

        def rank(item: tuple[str, set[str]]) -> tuple[int, str]:
            _, sources = item
            return min((priority.get(source, 3) for source in sources), default=3), item[0]

        retained: list[DiscoveredHost] = []
        for host, sources in sorted(candidate_sources.items(), key=rank):
            try:
                self.property_guard.validate(f"https://{host}/")
            except (DNSResolutionError, ScopeRefusal):
                continue
            retained.append(DiscoveredHost(host=host, sources=tuple(sorted(sources))))
            if len(retained) >= self.max_hosts:
                break
        return DiscoveryResult(
            apex=PROPERTY_ROOT_DOMAIN,
            hosts=tuple(retained),
            source_errors=source_errors,
        )

    def _add_candidate(
        self, candidates: dict[str, set[str]], raw_name: str, source: str
    ) -> None:
        candidate = raw_name.strip().lower().rstrip(".")
        if candidate.startswith("*.") or "://" in candidate or not candidate:
            return
        try:
            candidate = candidate.encode("idna").decode("ascii")
        except UnicodeError:
            return
        if self.property_guard.host_in_scope(candidate):
            candidates[candidate].add(source)

    def _certspotter(self) -> list[str]:
        url = (
            "https://api.certspotter.com/v1/issuances?domain=arjunrnair.com"
            "&include_subdomains=true&expand=dns_names"
        )
        self.source_guard.validate(url)
        payload = self.transport.get_json(url, timeout_seconds=self.timeout_seconds)
        return [
            str(name)
            for row in payload
            if isinstance(row, dict)
            for name in row.get("dns_names", [])
        ]

    def _alienvault(self) -> list[str]:
        url = (
            "https://otx.alienvault.com/api/v1/indicators/domain/"
            "arjunrnair.com/passive_dns"
        )
        self.source_guard.validate(url)
        payload = self.transport.get_json(url, timeout_seconds=self.timeout_seconds)
        return [
            str(row["hostname"])
            for row in payload.get("passive_dns", [])
            if isinstance(row, dict) and row.get("hostname")
        ]

    def _wayback(self) -> list[str]:
        query = urlencode(
            {
                "url": "*.arjunrnair.com/*",
                "output": "json",
                "fl": "original",
                "collapse": "urlkey",
            }
        )
        url = f"https://web.archive.org/cdx/search/cdx?{query}"
        self.source_guard.validate(url)
        payload = self.transport.get_json(url, timeout_seconds=self.timeout_seconds)
        names: list[str] = []
        for row in payload[1:] if isinstance(payload, list) else []:
            if isinstance(row, list) and row:
                host = urlsplit(str(row[0])).hostname
                if host:
                    names.append(host)
        return names
