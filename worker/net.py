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
* ``CheckedTargetTransport`` — an httpx transport that opens the connection to
  the address ``resolve_checked`` just returned, so the address described by
  the check is the address the request actually reaches.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlsplit

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


def resolve_checked(url: str, *, field: str) -> list[str]:
    """Check ``url`` and return the addresses a connection may use.

    Handing back the addresses, rather than just approving the URL, is the
    point: a name is only as stable as the answer behind it, and a second
    lookup at connect time can return something the check never saw — leaving
    the check describing a connection that didn't happen. The caller connects
    to one of these. See :class:`CheckedTargetTransport`.

    All of them are returned, in resolver order, because a host with several
    records expects a client to work down the list — pinning to the first alone
    would strand a dual-stack name whose first record the worker can't reach.

    Blocking: resolution is a synchronous DNS call.
    """
    host = require_http_url(url, field=field)
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as e:
        raise ValueError(f"{field} has an invalid port: {url!r}") from e
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


def check_target(url: str, *, field: str) -> None:
    """Check the shape of ``url`` and where it resolves to, discarding the
    address. Equivalent to :func:`resolve_checked` for callers that only want
    the verdict."""
    resolve_checked(url, field=field)


class CheckedTargetTransport(httpx.AsyncHTTPTransport):
    """Connect to the address the check approved.

    Resolution happens here, immediately before the connection is opened, and
    the connection goes to that exact address. The request keeps the caller's
    host in both the ``Host`` header and the TLS handshake, so virtual hosting
    and certificate verification behave exactly as they do without pinning.

    httpx calls a transport for every request it makes, including the ones it
    generates while following redirects, so each hop is resolved and connected
    the same way.
    """

    def __init__(self, *, field: str = "file_url", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._field = field

    def _pin(self, request: httpx.Request, addr: str) -> httpx.Request:
        """Copy ``request`` so it opens against ``addr``, host details intact."""
        url = request.url
        # An IPv6 address has to go back into the URL bracketed.
        literal = f"[{addr}]" if ":" in addr else addr
        headers = httpx.Headers(request.headers)
        headers["Host"] = url.netloc.decode("ascii")
        return httpx.Request(
            request.method,
            url.copy_with(host=literal),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": url.host},
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        addresses = await asyncio.to_thread(
            resolve_checked, str(request.url), field=self._field
        )
        # Work down the checked answers the way the socket layer would, so a
        # host whose first record is unreachable from this worker still gets
        # fetched. Only a failure to establish the connection moves on; once a
        # connection is up, its errors belong to the caller.
        last_error: Exception | None = None
        for addr in addresses:
            try:
                return await super().handle_async_request(self._pin(request, addr))
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_error = e
        raise last_error  # type: ignore[misc]  — addresses is never empty here


async def request_hook(request) -> None:  # noqa: ANN001 — httpx.Request
    """httpx event hook: shape-check each outgoing request's URL.

    The hook runs for every request httpx makes, redirects included, so a hop
    that lands on a scheme the worker doesn't speak is reported with the field
    name rather than as a protocol error from a library the caller never
    called. Where the request actually connects is settled by
    :class:`CheckedTargetTransport`.
    """
    require_http_url(str(request.url), field="file_url")
