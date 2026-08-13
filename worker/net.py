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
* ``check_target`` — additionally resolves the host and requires the answer to
  be a publicly routable address, which is what a document URL passed to a
  serverless worker is in practice. ``MINERU_ALLOW_LOCAL_FETCH=1`` lifts that
  requirement for local development and for operators serving documents from a
  host inside their own network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit


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


def check_target(url: str, *, field: str) -> None:
    """Check the shape of ``url`` and where it resolves to.

    Blocking: resolution is a synchronous DNS call. Use
    :func:`request_hook` from async code.
    """
    host = require_http_url(url, field=field)
    if allow_local_targets():
        return
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as e:
        raise ValueError(f"{field} has an invalid port: {url!r}") from e
    for addr in _addresses_for(host, port):
        if not _is_routable(addr):
            raise ValueError(
                f"{field} must point at a publicly routable host; "
                f"{host!r} resolves to {addr} "
                f"(set MINERU_ALLOW_LOCAL_FETCH=1 to allow this)"
            )


async def request_hook(request) -> None:  # noqa: ANN001 — httpx.Request
    """httpx event hook: check each outgoing request's target.

    Registered as an httpx ``request`` hook rather than called once on the
    caller's URL, because httpx runs the hook for every request it makes
    including the ones it generates while following redirects — so one code
    path covers the whole chain instead of just the first hop. The resolution
    itself is blocking, hence the thread.
    """
    await asyncio.to_thread(check_target, str(request.url), field="file_url")
