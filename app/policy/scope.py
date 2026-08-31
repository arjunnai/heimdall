from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

ALLOWED_LIVE_HOSTS = frozenset({"arjunrnair.com", "jobs.msemail.xyz"})
_CLOUD_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


class ScopeRefusal(PermissionError):
    """The requested target is outside the permitted public live scope."""


class DNSResolutionError(ConnectionError):
    """An allow-listed target could not be resolved."""


@dataclass(frozen=True)
class ScopedTarget:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]
    dns_resolve_ms: float


Resolver = Callable[[str, int], Iterable[str]]


def _system_resolver(host: str, port: int) -> Iterable[str]:
    return {
        entry[4][0]
        for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    }


class LiveScopeGuard:
    """Exact-host allow-list plus resolved-IP SSRF protection."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
    ) -> None:
        self.allowed_hosts = ALLOWED_LIVE_HOSTS
        self.resolver = resolver or _system_resolver

    def normalize(self, target: str) -> tuple[str, str, int]:
        candidate = target.strip()
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() != "https":
            raise ScopeRefusal("Live probes require HTTPS")
        if parsed.username or parsed.password:
            raise ScopeRefusal("Credentials are not permitted in live probe targets")
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise ScopeRefusal("Live probe target has an invalid port") from exc
        if port != 443:
            raise ScopeRefusal("Live probes are restricted to HTTPS port 443")
        if not parsed.hostname:
            raise ScopeRefusal("Live probe target must include a hostname")
        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise ScopeRefusal("Live probe target hostname is invalid") from exc
        if host not in self.allowed_hosts:
            raise ScopeRefusal(f"Host {host!r} is not in the live probe allow-list")
        netloc = host if port == 443 else f"{host}:{port}"
        url = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
        return url, host, port

    def validate(self, target: str) -> ScopedTarget:
        url, host, port = self.normalize(target)
        started = perf_counter()
        try:
            addresses = tuple(sorted(set(self.resolver(host, port))))
        except (OSError, socket.gaierror) as exc:
            raise DNSResolutionError(f"DNS resolution failed for {host}: {exc}") from exc
        elapsed_ms = (perf_counter() - started) * 1000
        if not addresses:
            raise DNSResolutionError(f"DNS resolution returned no addresses for {host}")
        for rendered in addresses:
            try:
                address = ipaddress.ip_address(rendered)
            except ValueError as exc:
                raise ScopeRefusal(f"Resolver returned invalid IP address {rendered!r}") from exc
            if address in _CLOUD_METADATA_ADDRESSES or any(
                (
                    address.is_private,
                    address.is_loopback,
                    address.is_link_local,
                    address.is_reserved,
                    address.is_multicast,
                    address.is_unspecified,
                )
            ):
                raise ScopeRefusal(
                    f"Resolved address {address} is not a permitted public destination"
                )
        return ScopedTarget(
            url=url,
            host=host,
            port=port,
            addresses=addresses,
            dns_resolve_ms=round(elapsed_ms, 3),
        )
