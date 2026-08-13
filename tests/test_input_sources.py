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


def test_url_check_follows_the_same_chain_the_client_does(monkeypatch):
    """The check is an httpx event hook so it applies to each request the client
    makes, including the ones it generates while following redirects — the first
    hop passing says nothing about where the chain ends up."""
    import httpx

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {
        "cdn.example.com": ["93.184.216.34"],
        "second.example": ["10.0.0.7"],
    })

    handled: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        handled.append(str(request.url))
        if request.url.host == "cdn.example.com":
            return httpx.Response(
                302, headers={"location": "http://second.example/r.pdf"}
            )
        return httpx.Response(200, content=b"%PDF-1.4 second hop")

    transport = httpx.MockTransport(respond)
    real_client = httpx.AsyncClient

    def with_mock_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(worker_io.httpx, "AsyncClient", with_mock_transport)

    with pytest.raises(ValueError, match="publicly routable"):
        _resolve({"file_url": "https://cdn.example.com/r.pdf"})

    # First hop was fetched; the redirect target never reached the transport.
    assert handled == ["https://cdn.example.com/r.pdf"]
