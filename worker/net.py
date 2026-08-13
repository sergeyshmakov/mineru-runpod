"""Outbound target checks for the URL-shaped job inputs.

Two job fields carry a URL the worker acts on: ``file_url`` (the document to
fetch) and ``server_url`` (an external vLLM server for the ``*-http-client``
backends). Both arrive as free-form strings, so a typo reaches the network
stack and comes back as a socket error 120 seconds later, or as an httpx
protocol complaint that doesn't say which field was wrong.

This module turns such a string into a checked target first, so the job fails
immediately with a message naming the field:

* ``require_http_url`` — the shape check: a scheme the worker speaks, and a
  host to connect to. This is all ``server_url`` needs; where an operator
  points their own model server is their call.
* ``resolve_checked`` — additionally resolves the host and requires the answer
  to be a publicly routable address, which is what a document URL passed to a
  serverless worker is in practice. ``MINERU_ALLOW_LOCAL_FETCH=1`` lifts that
  requirement for local development and for operators serving documents from a
  host inside their own network.
* ``CheckedTargetTransport`` — an httpx transport whose sockets are opened
  against a checked address, so the address described by the check is the
  address the request actually reaches.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx


ALLOWED_SCHEMES = ("http", "https")


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def allow_local_targets() -> bool:
    """Whether non-routable targets are acceptable for this worker."""
    return _truthy(os.environ.get("MINERU_ALLOW_LOCAL_FETCH", ""))


def require_http_url(url: str, *, field: str) -> str:
    """Return the host of ``url``, or raise if it isn't a usable HTTP target.

    Checked here rather than left to the HTTP client so the error names the
    input field the caller got wrong instead of surfacing a protocol-level
    complaint from a library they didn't call.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(
            f"{field} must be an http(s) URL; got scheme {scheme or '<none>'!r}"
        )
    host = parts.hostname
    if not host:
        raise ValueError(f"{field} has no host: {url!r}")
    return host


def _addresses_for(host: str, port: int | None) -> list[str]:
    """Resolve ``host`` to the addresses a connection would actually use."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise ValueError(f"host {host!r} could not be resolved: {e}") from e
    return [info[4][0] for info in infos if info[4]]


def _is_routable(addr: str) -> bool:
    """Whether ``addr`` is a publicly routable address.

    IPv4-mapped IPv6 answers (``::ffff:a.b.c.d``) are unwrapped first so the
    same address is judged the same way however the resolver spelled it.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # Not an address we can reason about (e.g. a scoped literal) — leave
        # the decision to the connection attempt.
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global


def resolve_checked_host(host: str, port: int | None, *, field: str) -> list[str]:
    """Return the addresses ``host`` may be connected to, in resolver order.

    Every address is returned, not just the first, because a host with several
    records expects a client to work down the list — using one answer alone
    would strand a dual-stack name whose leading record this worker has no
    route to.

    Blocking: resolution is a synchronous DNS call.
    """
    addresses = list(dict.fromkeys(_addresses_for(host, port)))
    if not addresses:
        raise ValueError(f"host {host!r} could not be resolved: no addresses returned")
    if not allow_local_targets():
        for addr in addresses:
            if not _is_routable(addr):
                raise ValueError(
                    f"{field} must point at a publicly routable host; "
                    f"{host!r} resolves to {addr} "
                    f"(set MINERU_ALLOW_LOCAL_FETCH=1 to allow this)"
                )
    return addresses


def resolve_checked(url: str, *, field: str) -> list[str]:
    """Check ``url`` and return the addresses a connection may use."""
    host = require_http_url(url, field=field)
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as e:
        raise ValueError(f"{field} has an invalid port: {url!r}") from e
    return resolve_checked_host(host, port, field=field)


def check_target(url: str, *, field: str) -> None:
    """Check the shape of ``url`` and where it resolves to, discarding the
    address. Equivalent to :func:`resolve_checked` for callers that only want
    the verdict."""
    resolve_checked(url, field=field)


class CheckedAddressBackend(httpcore.AnyIOBackend):
    """Open sockets only to addresses the check accepted.

    Resolving inside the call that opens the socket is what ties the verdict to
    the connection: there is no second lookup in between for the two to
    disagree about.

    The URL is deliberately left alone. Connections are pooled and reused by
    URL origin, and the TLS handshake is performed against the host in that
    origin — so substituting an address into the URL instead would make two
    different hostnames that share an address look like one origin, and the
    second one would be served over the first one's connection without a
    handshake of its own. Directing the socket keeps hostname-level pooling and
    certificate verification exactly as they are without any of this.

    ``AnyIOBackend`` rather than httpcore's private ``AutoBackend``: the worker
    always runs under asyncio, which is the backend ``AutoBackend`` would pick,
    and this one is public API.
    """

    def __init__(self, field: str) -> None:
        self._field = field

    async def connect_tcp(  # noqa: PLR0913 — signature mirrors the base class
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        addresses = await asyncio.to_thread(
            resolve_checked_host, host, port, field=self._field
        )
        # Work down the checked answers the way the socket layer would, so a
        # host whose leading record is unreachable from this worker still gets
        # fetched. Only a failure to open the socket moves on; anything that
        # happens after that belongs to the caller.
        last_error: Exception | None = None
        for addr in addresses:
            try:
                return await super().connect_tcp(
                    addr,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as e:
                last_error = e
        raise last_error  # type: ignore[misc]  — addresses is never empty here


class CheckedTargetTransport(httpx.AsyncHTTPTransport):
    """An httpx transport whose sockets are opened against checked addresses.

    httpx builds its connection pool itself and takes no network backend, so
    the pool's backend is swapped after construction. The pool creates
    connections lazily and hands each one whichever backend it holds at that
    moment, so this covers every connection the transport opens — including the
    ones opened for redirects.

    ``_pool._network_backend`` is not public API. A guard test asserts both
    names still exist and that the backend's ``connect_tcp`` still has the
    signature this subclass overrides, so an httpx or httpcore upgrade that
    moves them fails in CI rather than quietly connecting unchecked.
    """

    def __init__(self, *, field: str = "file_url", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pool._network_backend = CheckedAddressBackend(field)


async def request_hook(request) -> None:  # noqa: ANN001 — httpx.Request
    """httpx event hook: check each outgoing request's target.

    Runs for every request httpx makes, redirects included, and is what reports
    an unacceptable hop against the field name the caller wrote — rather than
    letting it surface as a connection error from a library they never called.
    A hop that reuses a pooled connection opens no socket, so this is also the
    check that sees such a hop at all.

    The lookup here and the one in :class:`CheckedAddressBackend` are separate,
    which costs a second resolution per new connection. That buys the division
    of labour: this one produces the caller-facing message, and the backend's
    guarantees what the socket connects to.
    """
    await asyncio.to_thread(check_target, str(request.url), field="file_url")
