"""Input-source resolution: which files and which URLs the worker accepts.

No GPU, no MinerU, no network — every case here is decided before a socket
opens or MinerU is imported.
"""

from __future__ import annotations

import asyncio
import socket
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


def _patch_socket_layer(monkeypatch, respond):
    """Answer requests below CheckedTargetTransport, so its own resolve-and-pin
    logic still runs. Replacing the transport itself would skip the code under
    test."""
    import httpx

    monkeypatch.setattr(
        httpx.AsyncHTTPTransport,
        "handle_async_request",
        lambda self, request: respond(request),
    )


def test_url_check_follows_the_same_chain_the_client_does(monkeypatch):
    """Each request the client makes is checked and connected the same way,
    including the ones it generates while following redirects — the first hop
    passing says nothing about where the chain ends up."""
    import httpx

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "cdn.example.com": ["93.184.216.34"],
        "second.example": ["10.0.0.7"],
    })

    handled: list[str] = []

    async def respond(request):
        # The transport rewrote the URL host to the checked address, so the
        # caller's host is read back off the Host header.
        handled.append(request.headers["host"])
        if request.headers["host"].startswith("cdn."):
            return httpx.Response(
                302, headers={"location": "http://second.example/r.pdf"}
            )
        return httpx.Response(200, content=b"%PDF-1.4 second hop")

    _patch_socket_layer(monkeypatch, respond)

    with pytest.raises(ValueError, match="publicly routable"):
        _resolve({"file_url": "https://cdn.example.com/r.pdf"})

    # First hop was fetched; the redirect target never opened a connection.
    assert handled == ["cdn.example.com"]


def test_connection_goes_to_the_address_that_was_checked(monkeypatch):
    """The address the check approved is the address the request reaches.

    A name is only as stable as the answer behind it: if the connection
    resolved the host again on its own, it could land somewhere the check never
    saw. Here the resolver hands back one address and the request must arrive
    at that one, with the caller's host preserved for virtual hosting and for
    the TLS handshake.
    """
    import httpx

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"files.example.com": ["93.184.216.34"]})

    seen = {}

    async def respond(request):
        seen["connected_host"] = request.url.host
        seen["host_header"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, content=b"%PDF-1.4 pinned")

    _patch_socket_layer(monkeypatch, respond)

    raw, _ = _resolve({"file_url": "https://files.example.com/a.pdf"})
    assert raw == b"%PDF-1.4 pinned"
    assert seen["connected_host"] == "93.184.216.34"
    assert seen["host_header"] == "files.example.com"
    assert seen["sni"] == "files.example.com"


def test_all_checked_addresses_are_tried_before_giving_up(monkeypatch):
    """A host with several records expects a client to work down the list.

    Pinning to the first answer alone would strand a dual-stack name whose
    first record this worker cannot reach — the common case being an AAAA
    record on a container with no IPv6 route.
    """
    import httpx

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "dual.example.com": ["2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34"],
    })

    attempts = []

    async def respond(request):
        # httpx stores an IPv6 host unbracketed, so ":" is what identifies it.
        attempts.append(request.url.host)
        if ":" in request.url.host:
            raise httpx.ConnectError("no route to host")
        return httpx.Response(200, content=b"%PDF-1.4 second address")

    _patch_socket_layer(monkeypatch, respond)

    raw, _ = _resolve({"file_url": "https://dual.example.com/a.pdf"})
    assert raw == b"%PDF-1.4 second address"
    assert attempts == ["2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34"]


def test_a_connect_failure_on_every_address_surfaces(monkeypatch):
    import httpx

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"down.example.com": ["93.184.216.34", "93.184.216.35"]})

    async def respond(request):
        raise httpx.ConnectError("no route to host")

    _patch_socket_layer(monkeypatch, respond)

    with pytest.raises(httpx.ConnectError):
        _resolve({"file_url": "https://down.example.com/a.pdf"})


def test_checked_address_is_used_even_if_the_name_answers_differently_later(
    monkeypatch,
):
    """A host whose answer changes between lookups cannot move the connection.

    The resolver below returns a routable address the first time it is asked
    and a private one afterwards. Whichever lookup the check used, the request
    must arrive at an address the check accepted.
    """
    import httpx

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    answers = ["93.184.216.34", "127.0.0.1", "127.0.0.1"]
    calls = {"n": 0}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        addr = answers[min(calls["n"], len(answers) - 1)]
        calls["n"] += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    reached = []

    async def respond(request):
        reached.append(request.url.host)
        return httpx.Response(200, content=b"%PDF-1.4 ok")

    _patch_socket_layer(monkeypatch, respond)

    raw, _ = _resolve({"file_url": "https://shifting.example/a.pdf"})
    assert raw == b"%PDF-1.4 ok"
    assert reached == ["93.184.216.34"], (
        f"connected to {reached!r} — must be the address the check accepted"
    )
