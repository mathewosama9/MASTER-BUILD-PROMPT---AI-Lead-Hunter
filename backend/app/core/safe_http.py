"""SSRF-hardened HTTP fetching for crawling untrusted public websites.

Every hop (including redirects) is resolved and checked against private, loopback,
link-local, multicast and reserved ranges. Responses are size- and time-limited and
robots.txt is honoured.

The check is repeated where the TCP connection is opened, against the very address that is
then dialled (`PinnedPublicBackend`), so a DNS answer that changes between the check and the
connect (DNS rebinding) cannot reach an internal address. TLS still verifies the original
hostname (SNI and certificate) and the Host header is unchanged.
"""

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpcore
import httpx

from app.core.config import get_settings


class UnsafeURLError(ValueError):
    pass


class RobotsDisallowed(Exception):
    pass


ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not (addr.is_multicast or addr.is_reserved)


def validate_url_shape(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Scheme not allowed: {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")
    if parsed.username or parsed.password:
        raise UnsafeURLError("Credentials in URL are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURLError("Invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError(f"Port not allowed: {port}")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeURLError("Internal hostnames are not allowed")
    try:
        ipaddress.ip_address(host)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False
    if is_ip_literal and not _is_public_ip(host):
        raise UnsafeURLError("Non-public IP address")
    return parsed.geturl()


async def _resolve(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host}") from exc
    return list(dict.fromkeys(i[4][0] for i in infos))


async def public_addresses(host: str) -> list[str]:
    """Resolve `host`; every address must be public, otherwise the host is refused."""
    candidates = await _resolve(host.strip("[]"))
    if not candidates or not all(_is_public_ip(ip) for ip in candidates):
        raise UnsafeURLError(f"Host {host} resolves to a non-public address")
    return candidates


async def assert_public_host(host: str) -> None:
    await public_addresses(host)


class PinnedPublicBackend(httpcore.AsyncNetworkBackend):
    """Resolves and validates at connect time, then dials the validated IP itself (never the name)."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,  # noqa: ANN001 - httpcore's own type
    ) -> httpcore.AsyncNetworkStream:
        last_exc: Exception | None = None
        for ip in await public_addresses(host):
            try:
                return await self._inner.connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except httpcore.ConnectError as exc:
                last_exc = exc
        raise last_exc or httpcore.ConnectError(f"Could not connect to {host}")

    async def connect_unix_socket(self, *args, **kwargs) -> httpcore.AsyncNetworkStream:  # noqa: ANN002, ANN003
        raise UnsafeURLError("Unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def pinned_transport() -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport()
    # httpx has no public hook for the network backend; swap it on the pool it built (same TLS/limits config).
    transport._pool._network_backend = PinnedPublicBackend()  # noqa: SLF001
    return transport


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str
    fetched_at: float


class SafeFetcher:
    def __init__(
        self,
        *,
        respect_robots: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        skip_dns_check: bool = False,
    ) -> None:
        s = get_settings()
        self.respect_robots = respect_robots
        self.max_bytes = s.crawler_max_bytes
        self.max_redirects = s.crawler_max_redirects
        self.user_agent = s.crawler_user_agent
        self._skip_dns = skip_dns_check
        self._robots: dict[str, RobotFileParser | None] = {}
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(s.crawler_timeout_seconds),
            follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"},
            transport=transport or (None if skip_dns_check else pinned_transport()),
        )

    async def __aenter__(self) -> "SafeFetcher":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _check(self, url: str) -> str:
        url = validate_url_shape(url)
        if not self._skip_dns:
            await assert_public_host(urlparse(url).hostname or "")
        return url

    async def _robots_allows(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                body = await self._raw_get(origin + "/robots.txt", limit=200_000)
                if body.status_code >= 400:
                    parser = None  # no robots.txt => crawling allowed
                else:
                    parser.parse(body.text.splitlines())
            except (httpx.HTTPError, UnsafeURLError):
                parser = None
            self._robots[origin] = parser
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    async def _raw_get(self, url: str, limit: int | None = None) -> FetchResult:
        limit = limit or self.max_bytes
        current = await self._check(url)
        for _ in range(self.max_redirects + 1):
            async with self._client.stream("GET", current) as resp:
                if resp.is_redirect and "location" in resp.headers:
                    current = await self._check(urljoin(current, resp.headers["location"]))
                    continue
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks)
                encoding = resp.charset_encoding or "utf-8"
                return FetchResult(
                    url=str(resp.url),
                    status_code=resp.status_code,
                    content_type=resp.headers.get("content-type", ""),
                    text=raw.decode(encoding, errors="replace"),
                    fetched_at=time.time(),
                )
        raise UnsafeURLError("Too many redirects")

    async def get(self, url: str, limit: int | None = None) -> FetchResult:
        url = await self._check(url)
        if self.respect_robots and not await self._robots_allows(url):
            raise RobotsDisallowed(url)
        return await self._raw_get(url, limit)
