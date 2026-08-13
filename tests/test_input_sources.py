"""Input-source resolution: which files and which URLs the worker accepts.

No GPU, no MinerU, no network — every case here is decided before a socket
opens or MinerU is imported.
"""

from __future__ import annotations

import asyncio
import socket
import time
from pathlib import Path

import pytest

from worker import io as worker_io
from worker import net as worker_net


# -----------------------------------------------------------------------------
# volume_path — input roots
# -----------------------------------------------------------------------------

def _resolve(job_input: dict):
    return asyncio.run(worker_io.resolve_input_bytes(job_input))


def test_volume_roots_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("MINERU_VOLUME_ROOTS", raising=False)
    assert [str(p) for p in worker_io.volume_roots()] == [
        str(worker_io.Path(r)) for r in worker_io.DEFAULT_VOLUME_ROOTS
    ]


def test_default_roots_cover_the_documented_locations():
    """Each default root is promised by the network-volumes guide, so dropping
    one is a contract change rather than a tidy-up."""
    assert set(worker_io.DEFAULT_VOLUME_ROOTS) >= {
        "/runpod-volume", "/workspace", "/worker", "/tmp",
    }


def test_hub_validator_input_sits_under_a_default_root():
    """.runpod/tests.json is the only job the Hub validator runs on a release
    build, and it arrives as a volume_path. Compared with PurePosixPath because
    the roots are container paths regardless of the machine running the test."""
    import json
    from pathlib import PurePosixPath

    spec = json.loads(
        (Path(__file__).resolve().parent.parent / ".runpod" / "tests.json")
        .read_text(encoding="utf-8")
    )
    roots = [PurePosixPath(r) for r in worker_io.DEFAULT_VOLUME_ROOTS]
    for case in spec["tests"]:
        volume_path = case["input"].get("volume_path")
        if not volume_path:
            continue
        target = PurePosixPath(volume_path)
        assert any(r == target or r in target.parents for r in roots), (
            f"{volume_path!r} from .runpod/tests.json is outside the default "
            f"input roots — the Hub validator would reject it"
        )


def test_volume_roots_env_replaces_defaults(monkeypatch, tmp_path):
    other = tmp_path / "other"
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", f"{tmp_path}, {other} ,")
    assert [str(p) for p in worker_io.volume_roots()] == [str(tmp_path), str(other)]


def test_volume_roots_blank_env_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", "   ")
    assert len(worker_io.volume_roots()) == len(worker_io.DEFAULT_VOLUME_ROOTS)


def test_volume_path_inside_a_root_is_read(monkeypatch, tmp_path):
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    doc = tmp_path / "nested" / "doc.pdf"
    doc.parent.mkdir()
    doc.write_bytes(b"%PDF-1.4 nested")
    raw, src = _resolve({"volume_path": str(doc)})
    assert raw == b"%PDF-1.4 nested"
    assert src == f"volume:{doc}"


def test_volume_path_outside_the_roots_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"%PDF-1.4 elsewhere")
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(root))
    with pytest.raises(ValueError, match="outside the configured input roots"):
        _resolve({"volume_path": str(outside)})


def test_volume_path_with_parent_segments_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"%PDF-1.4 elsewhere")
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(root))
    with_parent_segment = root / ".." / "elsewhere.pdf"
    with pytest.raises(ValueError, match="outside the configured input roots"):
        _resolve({"volume_path": str(with_parent_segment)})


def test_volume_path_symlink_leaving_the_root_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"%PDF-1.4 elsewhere")
    link = root / "link.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(root))
    with pytest.raises(ValueError, match="outside the configured input roots"):
        _resolve({"volume_path": str(link)})


def test_volume_path_must_be_absolute(monkeypatch, tmp_path):
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    with pytest.raises(ValueError, match="must be an absolute path"):
        _resolve({"volume_path": "relative/doc.pdf"})


def test_volume_path_missing_file_keeps_its_message(monkeypatch, tmp_path):
    # The wording is quoted in the network-volumes guide and matched by
    # callers' own error handling — it must not drift.
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    with pytest.raises(ValueError, match="volume_path not found inside container"):
        _resolve({"volume_path": str(tmp_path / "absent.pdf")})


# -----------------------------------------------------------------------------
# URL fields — target checks
#
# Every case below is decided before a connection is attempted, so none of
# these tests touch the network.
# -----------------------------------------------------------------------------

def _stub_resolver(monkeypatch, mapping: dict[str, list[str]]) -> None:
    """Resolve hosts from a dict instead of DNS."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 80))
            for addr in mapping[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/hosts",
        "ftp://example.com/report.pdf",
        "gopher://example.com/report.pdf",
        "example.com/report.pdf",
    ],
)
def test_require_http_url_rejects_other_schemes(url):
    with pytest.raises(ValueError, match="must be an http"):
        worker_net.require_http_url(url, field="file_url")


def test_require_http_url_rejects_missing_host():
    with pytest.raises(ValueError, match="has no host"):
        worker_net.require_http_url("http:///report.pdf", field="file_url")


def test_require_http_url_returns_host():
    assert worker_net.require_http_url(
        "https://User:pw@Example.com:8443/a/b.pdf?t=1", field="file_url"
    ) == "example.com"


def test_check_target_accepts_a_routable_host(monkeypatch):
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"cdn.example.com": ["93.184.216.34"]})
    worker_net.check_target("https://cdn.example.com/r.pdf", field="file_url")


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",
        "169.254.1.5",
        "10.0.0.5",
        "192.168.1.10",
        "172.16.4.4",
        "::1",
        "::ffff:127.0.0.1",  # the same address, spelled as mapped IPv6
    ],
)
def test_check_target_rejects_non_routable_answers(monkeypatch, addr):
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"host.example": [addr]})
    with pytest.raises(ValueError, match="publicly routable"):
        worker_net.check_target("http://host.example/r.pdf", field="file_url")


def test_check_target_rejects_when_any_answer_is_non_routable(monkeypatch):
    # A multi-answer host is only as good as the address the client picks.
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"split.example": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(ValueError, match="publicly routable"):
        worker_net.check_target("http://split.example/r.pdf", field="file_url")


def test_check_target_allows_non_routable_when_opted_in(monkeypatch):
    monkeypatch.setenv("MINERU_ALLOW_LOCAL_FETCH", "1")
    _stub_resolver(monkeypatch, {"localhost": ["127.0.0.1"]})
    worker_net.check_target("http://localhost:8000/r.pdf", field="file_url")


def test_check_target_reports_resolution_failure(monkeypatch):
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {})
    with pytest.raises(ValueError, match="could not be resolved"):
        worker_net.check_target("http://nowhere.invalid/r.pdf", field="file_url")


def test_resolve_input_bytes_checks_the_url_before_connecting(monkeypatch):
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"docs.internal": ["10.0.0.7"]})
    with pytest.raises(ValueError, match="publicly routable"):
        _resolve({"file_url": "http://docs.internal/report.pdf"})


def test_resolve_input_bytes_rejects_a_non_http_url():
    with pytest.raises(ValueError, match="must be an http"):
        _resolve({"file_url": "file:///etc/hosts"})


class _CannedStream:
    """A network stream that replays canned response bytes.

    Enough of httpcore's stream surface for it to parse a real response, so a
    redirect can be driven through the actual client stack — the transport, the
    connection pool and CheckedAddressBackend — rather than around it.
    """

    def __init__(self, payload: bytes) -> None:
        self._data = payload

    async def read(self, max_bytes, timeout=None):
        chunk, self._data = self._data[:max_bytes], self._data[max_bytes:]
        return chunk

    async def write(self, buffer, timeout=None):
        return None

    async def aclose(self):
        return None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self

    def get_extra_info(self, info):
        return None


def test_every_hop_is_checked_including_ones_the_client_generates(monkeypatch):
    """A redirect to another host opens another connection, so it is checked too.

    The first hop passing says nothing about where the chain ends up. Driven
    through the real pool: only the socket layer underneath is canned, so the
    backend's own resolve-and-check runs for both hops.
    """
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "cdn.example.com": ["93.184.216.34"],
        "second.example": ["10.0.0.7"],
    })

    connected = []

    async def fake_connect(self, host, port, timeout=None, local_address=None,
                           socket_options=None):
        connected.append(host)
        return _CannedStream(
            b"HTTP/1.1 302 Found\r\n"
            b"Location: http://second.example/r.pdf\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", fake_connect)

    with pytest.raises(ValueError, match="publicly routable"):
        _resolve({"file_url": "https://cdn.example.com/r.pdf"})

    # The first hop connected; the redirect target never got a socket.
    assert connected == ["93.184.216.34"]


# -----------------------------------------------------------------------------
# Where the socket actually goes.
#
# These drive CheckedAddressBackend directly: it is the seam where a resolved
# address becomes a connection, so it is the honest place to assert what the
# connection connects to. httpcore's own backend is stubbed underneath.
# -----------------------------------------------------------------------------

def _stub_socket_backend(monkeypatch, on_connect):
    """Answer connect_tcp below CheckedAddressBackend, recording the address."""
    import httpcore

    async def fake_connect_tcp(self, host, port, timeout=None, local_address=None,
                               socket_options=None):
        return on_connect(host, port)

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", fake_connect_tcp)


def test_socket_opens_against_the_address_that_was_checked(monkeypatch):
    """A name is only as stable as the answer behind it — so the lookup and the
    connection happen in one place, and the socket goes where the check looked."""
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"files.example.com": ["93.184.216.34"]})
    opened = []
    _stub_socket_backend(monkeypatch, lambda host, port: opened.append((host, port)))

    backend = worker_net.CheckedAddressBackend("file_url")
    asyncio.run(backend.connect_tcp("files.example.com", 443))
    assert opened == [("93.184.216.34", 443)]


def test_socket_is_not_opened_when_the_address_is_rejected(monkeypatch):
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"internal.example": ["10.0.0.7"]})
    opened = []
    _stub_socket_backend(monkeypatch, lambda host, port: opened.append((host, port)))

    backend = worker_net.CheckedAddressBackend("file_url")
    with pytest.raises(ValueError, match="publicly routable"):
        asyncio.run(backend.connect_tcp("internal.example", 443))
    assert opened == []


def test_all_checked_addresses_are_tried_before_giving_up(monkeypatch):
    """A host with several records expects a client to work down the list.

    Using the first answer alone would strand a dual-stack name whose leading
    record this worker cannot reach — an AAAA record on a container with no
    IPv6 route being the everyday case.
    """
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "dual.example.com": ["2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34"],
    })
    attempts = []

    def on_connect(host, port):
        attempts.append(host)
        if ":" in host:
            raise httpcore.ConnectError("no route to host")
        return "stream"

    _stub_socket_backend(monkeypatch, on_connect)

    backend = worker_net.CheckedAddressBackend("file_url")
    assert asyncio.run(backend.connect_tcp("dual.example.com", 443)) == "stream"
    assert attempts == ["2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34"]


def test_a_stalled_lookup_is_bounded_by_the_fetch_budget(monkeypatch):
    """Resolution is inside the budget, not ahead of it.

    A lookup runs before any connection and can block for as long as the
    platform resolver allows, so leaving it outside would let a name that never
    answers hold a fetch open past the timeout the caller was given.
    """
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)

    def never_answers(host, port, *args, **kwargs):
        time.sleep(5)  # far past the budget below
        raise AssertionError("resolution should have been abandoned")

    monkeypatch.setattr(socket, "getaddrinfo", never_answers)

    backend = worker_net.CheckedAddressBackend("file_url")

    async def measure():
        # Timed inside the loop on purpose: the abandoned lookup keeps running
        # in its thread (getaddrinfo cannot be interrupted), and asyncio.run
        # joins the executor on the way out. What has to be bounded is the time
        # the job waits, which is what this measures.
        started = time.monotonic()
        with pytest.raises(httpcore.ConnectTimeout, match="outlasted the fetch budget"):
            await backend.connect_tcp("stalls.example", 443, timeout=0.15)
        return time.monotonic() - started

    elapsed = asyncio.run(measure())
    assert elapsed < 1.0, f"job waited {elapsed:.2f}s on a 0.15s budget"


def test_the_lookup_shares_the_budget_with_the_connect_attempts(monkeypatch):
    """What the lookup spends is taken off what the connects get."""
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)

    def slow_resolver(host, port, *args, **kwargs):
        time.sleep(0.10)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", slow_resolver)

    handed = []

    async def record(self, host, port, timeout=None, local_address=None,
                    socket_options=None):
        handed.append(timeout)
        return "stream"

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", record)

    backend = worker_net.CheckedAddressBackend("file_url")
    asyncio.run(backend.connect_tcp("slow.example", 443, timeout=0.50))
    assert handed and handed[0] < 0.45, (
        f"connect got {handed[0]!r} of a 0.50s budget after a 0.10s lookup"
    )


_PROXY_VARS = (
    "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
    "ALL_PROXY", "all_proxy",
)


def _clear_proxy_env(monkeypatch):
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)


def _transport_chosen_for(monkeypatch, url: str):
    """Which transport the client would use for `url`, as httpx selects it."""
    import httpx

    client = httpx.AsyncClient(
        timeout=1.0,
        transport=worker_net.CheckedTargetTransport(field="file_url"),
        mounts=worker_net.environment_proxy_mounts(),
        event_hooks={"request": [worker_net.request_hook]},
    )
    try:
        return client._transport_for_url(httpx.URL(url))
    finally:
        asyncio.run(client.aclose())


def test_a_proxied_pattern_goes_through_the_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    chosen = _transport_chosen_for(monkeypatch, "http://cdn.example.com/a.pdf")
    assert not isinstance(chosen, worker_net.CheckedTargetTransport)


def test_a_scheme_with_no_proxy_stays_on_the_checked_path(monkeypatch):
    """Only HTTP_PROXY is set, so an https fetch is not proxied at all — it
    must not lose the checked transport on the way past the mounts."""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    chosen = _transport_chosen_for(monkeypatch, "https://cdn.example.com/a.pdf")
    assert isinstance(chosen, worker_net.CheckedTargetTransport)


def test_a_no_proxy_host_stays_on_the_checked_path(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("NO_PROXY", "cdn.example.com")
    chosen = _transport_chosen_for(monkeypatch, "http://cdn.example.com/a.pdf")
    assert isinstance(chosen, worker_net.CheckedTargetTransport)


def test_without_a_proxy_everything_is_on_the_checked_path(monkeypatch):
    _clear_proxy_env(monkeypatch)
    for url in ("https://cdn.example.com/a.pdf", "http://cdn.example.com/a.pdf"):
        assert isinstance(
            _transport_chosen_for(monkeypatch, url),
            worker_net.CheckedTargetTransport,
        )


def test_a_literal_address_is_judged_without_a_lookup(monkeypatch):
    """An address written as one needs no resolution to judge, so it is judged
    even on a request that would be proxied."""
    import httpx

    _clear_proxy_env(monkeypatch)
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: pytest.fail("the hook resolved a literal address"),
    )
    with pytest.raises(ValueError, match="publicly routable"):
        asyncio.run(worker_net.request_hook(
            httpx.Request("GET", "http://10.0.0.7/a.pdf")
        ))
    # A routable literal passes, still without resolving.
    asyncio.run(worker_net.request_hook(
        httpx.Request("GET", "http://93.184.216.34/a.pdf")
    ))


def test_httpx_environment_proxy_helper_guard():
    """Guard: environment_proxy_mounts leans on a private httpx helper.

    Reimplementing NO_PROXY matching would be the more fragile option, so the
    dependency is explicit and checked here instead.
    """
    from httpx._utils import get_environment_proxies

    assert callable(get_environment_proxies)
    assert isinstance(get_environment_proxies(), dict)


def test_the_request_hook_does_not_resolve(monkeypatch):
    """The hook is shape-only, so a hop costs one lookup rather than two.

    A second lookup here would sit outside the connect budget, which is what
    put resolution beyond the documented timeout in the first place.
    """
    import httpx

    calls = []
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: calls.append(a) or [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    asyncio.run(worker_net.request_hook(
        httpx.Request("GET", "https://cdn.example.com/r.pdf")
    ))
    assert calls == [], "the hook resolved the host"


def test_the_request_hook_still_rejects_a_bad_scheme():
    import httpx

    with pytest.raises(ValueError, match="file_url must be an http"):
        asyncio.run(worker_net.request_hook(
            httpx.Request("GET", "ftp://cdn.example.com/r.pdf")
        ))


def test_the_connect_timeout_is_one_budget_for_the_whole_address_list(monkeypatch):
    """Walking the address list must not multiply the caller's timeout.

    The base backend bounds a connect to a name with a single deadline covering
    every address it tries. Handing the full timeout to each attempt instead
    would let a name with several records that accept and then say nothing hold
    the fetch for len(addresses) times as long as promised.
    """
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "many.example": ["93.184.216.34", "93.184.216.35", "93.184.216.36"],
    })

    handed = []

    async def stall(self, host, port, timeout=None, local_address=None,
                    socket_options=None):
        handed.append(timeout)
        await asyncio.sleep(0.05)
        raise httpcore.ConnectTimeout("timed out")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", stall)

    backend = worker_net.CheckedAddressBackend("file_url")
    started = time.monotonic()
    with pytest.raises(httpcore.ConnectTimeout):
        asyncio.run(backend.connect_tcp("many.example", 443, timeout=0.12))
    elapsed = time.monotonic() - started

    assert handed, "no attempt was made"
    # Each attempt gets what is left, never the original budget again.
    assert handed[0] <= 0.12
    assert all(
        later < earlier for earlier, later in zip(handed, handed[1:])
    ), f"timeout was not shared across attempts: {handed}"
    assert elapsed < 0.12 * len(handed), (
        f"took {elapsed:.3f}s across {len(handed)} attempts on a 0.12s budget"
    )


def test_a_stalling_address_does_not_strand_the_reachable_ones(monkeypatch):
    """An address that accepts and then says nothing must not spend the budget.

    Failing fast already fell through to the next answer; burning the whole
    deadline did not, which stranded exactly the dual-stack case this walk
    exists for.
    """
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "dual.example": ["93.184.216.34", "93.184.216.35"],
    })
    attempts = []

    async def first_stalls(self, host, port, timeout=None, local_address=None,
                           socket_options=None):
        attempts.append(host)
        if host == "93.184.216.34":
            await asyncio.sleep(timeout)      # silently drops for its whole slice
            raise httpcore.ConnectTimeout("timed out")
        return "stream"

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", first_stalls)

    backend = worker_net.CheckedAddressBackend("file_url")

    async def measure():
        started = time.monotonic()
        stream = await backend.connect_tcp("dual.example", 443, timeout=0.40)
        return stream, time.monotonic() - started

    stream, elapsed = asyncio.run(measure())
    assert stream == "stream", "never reached the reachable address"
    assert attempts == ["93.184.216.34", "93.184.216.35"]
    assert elapsed < 0.40, f"used {elapsed:.2f}s of a 0.40s budget"


def test_the_last_address_may_use_what_is_left(monkeypatch):
    """Reserving time for later answers must not shortchange the final one."""
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"two.example": ["93.184.216.34", "93.184.216.35"]})
    handed = []

    async def first_fails_fast(self, host, port, timeout=None, local_address=None,
                               socket_options=None):
        handed.append(timeout)
        if host == "93.184.216.34":
            raise httpcore.ConnectError("connection refused")
        return "stream"

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", first_fails_fast)

    backend = worker_net.CheckedAddressBackend("file_url")
    assert asyncio.run(backend.connect_tcp("two.example", 443, timeout=1.0)) == "stream"
    # First got a share; the second, once the first returned unspent time, got
    # substantially more than that share.
    assert handed[0] < 0.60
    assert handed[1] > handed[0]


def test_attempts_stop_once_the_budget_is_spent(monkeypatch):
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "many.example": ["93.184.216.34", "93.184.216.35", "93.184.216.36"],
    })

    attempts = []

    async def stall(self, host, port, timeout=None, local_address=None,
                    socket_options=None):
        attempts.append(host)
        await asyncio.sleep(0.08)
        raise httpcore.ConnectTimeout("timed out")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", stall)

    backend = worker_net.CheckedAddressBackend("file_url")
    with pytest.raises(httpcore.ConnectTimeout):
        asyncio.run(backend.connect_tcp("many.example", 443, timeout=0.10))
    assert len(attempts) < 3, (
        f"kept trying after the budget was spent: {attempts}"
    )


def test_no_timeout_means_every_address_is_still_tried(monkeypatch):
    """timeout=None is unbounded, as it is for the base backend."""
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"two.example": ["93.184.216.34", "93.184.216.35"]})
    handed = []

    async def fail_then_pass(self, host, port, timeout=None, local_address=None,
                             socket_options=None):
        handed.append(timeout)
        if len(handed) == 1:
            raise httpcore.ConnectError("no route")
        return "stream"

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", fail_then_pass)

    backend = worker_net.CheckedAddressBackend("file_url")
    assert asyncio.run(backend.connect_tcp("two.example", 443, timeout=None)) == "stream"
    assert handed == [None, None]


def test_a_connect_failure_on_every_address_surfaces(monkeypatch):
    import httpcore

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"down.example.com": ["93.184.216.34", "93.184.216.35"]})

    def on_connect(host, port):
        raise httpcore.ConnectError("no route to host")

    _stub_socket_backend(monkeypatch, on_connect)

    backend = worker_net.CheckedAddressBackend("file_url")
    with pytest.raises(httpcore.ConnectError):
        asyncio.run(backend.connect_tcp("down.example.com", 443))


def test_url_host_is_left_alone_so_pooling_stays_per_hostname(monkeypatch):
    """Two hostnames sharing an address must not share a connection.

    Connections are pooled by URL origin and the TLS handshake is performed
    against the host in it. Substituting the address into the URL would collapse
    two hostnames into one origin, and the second would be served over the
    first one's connection without a handshake of its own.
    """
    transport = worker_net.CheckedTargetTransport(field="file_url")
    try:
        assert isinstance(
            transport._pool._network_backend, worker_net.CheckedAddressBackend
        )
        # The transport does not touch requests, so httpx keeps building origins
        # from the caller's hostname.
        assert not hasattr(transport, "_pin")
        assert "handle_async_request" not in vars(worker_net.CheckedTargetTransport)
    finally:
        asyncio.run(transport.aclose())


def test_httpx_internals_this_transport_depends_on(monkeypatch):
    """Guard: the two names CheckedTargetTransport reaches into.

    httpx exposes no way to supply a network backend, so the pool's backend is
    swapped after construction. If an upgrade moves either name, fail here
    rather than silently connecting without the check.
    """
    import httpcore
    import httpx

    plain = httpx.AsyncHTTPTransport()
    try:
        assert hasattr(plain, "_pool"), "httpx.AsyncHTTPTransport._pool is gone"
        assert hasattr(plain._pool, "_network_backend"), (
            "httpcore pool no longer holds _network_backend"
        )
    finally:
        asyncio.run(plain.aclose())

    import inspect

    signature = inspect.signature(httpcore.AnyIOBackend.connect_tcp)
    params = list(signature.parameters)
    assert params == [
        "self", "host", "port", "timeout", "local_address", "socket_options",
    ], f"AnyIOBackend.connect_tcp signature changed: {params}"

    # The override hands `host` a str, which is what socket.getaddrinfo returns
    # and what this backend takes. Passing bytes instead makes anyio treat them
    # as a name to resolve, so the connection fails. Pin the parameter type: if
    # a future version takes bytes, that has to fail here rather than on a
    # caller's first real fetch.
    host_annotation = signature.parameters["host"].annotation
    assert host_annotation in (str, "str"), (
        f"AnyIOBackend.connect_tcp host parameter is now {host_annotation!r}; "
        f"CheckedAddressBackend passes a str"
    )
