"""Input-source resolution as this worker configures it.

The transport itself belongs to the harness, which covers the mechanics in
its own suite — root containment, scheme rules, resolved-address checks, the
socket seam, proxy patterns, fetch budgets. What has to hold here is that a
job arriving at *this* worker is resolved against *this* worker's roots and
refused before a connection when the target does not check out.

No GPU, no MinerU, no network — every case here is decided before a socket
opens or MinerU is imported.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from runpod_doc_worker.transport import io as worker_io
from runpod_doc_worker.transport import net as worker_net


def _resolve(job_input: dict):
    return asyncio.run(worker_io.resolve_input_bytes(job_input))


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


# -----------------------------------------------------------------------------
# volume_path — resolved against the roots this worker declares
# -----------------------------------------------------------------------------

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


def test_volume_roots_env_var_is_the_documented_one(monkeypatch, tmp_path):
    """MINERU_VOLUME_ROOTS is what hub.json and the network-volumes guide name.

    The harness reads it under whatever prefix worker.harness declares, so
    this asserts the declaration rather than the mechanism.
    """
    other = tmp_path / "other"
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", f"{tmp_path}, {other} ,")
    assert [str(p) for p in worker_io.volume_roots()] == [str(tmp_path), str(other)]


def test_volume_path_missing_file_keeps_its_message(monkeypatch, tmp_path):
    # The wording is quoted in the network-volumes guide and matched by
    # callers' own error handling — it must not drift.
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    with pytest.raises(ValueError, match="volume_path not found inside container"):
        _resolve({"volume_path": str(tmp_path / "absent.pdf")})


# -----------------------------------------------------------------------------
# file_url — refused before a connection is attempted
# -----------------------------------------------------------------------------

def test_resolve_input_bytes_checks_the_url_before_connecting(monkeypatch):
    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    _stub_resolver(monkeypatch, {"docs.internal": ["10.0.0.7"]})
    with pytest.raises(ValueError, match="publicly routable"):
        _resolve({"file_url": "http://docs.internal/report.pdf"})


def test_resolve_input_bytes_rejects_a_non_http_url():
    with pytest.raises(ValueError, match="must be an http"):
        _resolve({"file_url": "file:///etc/hosts"})


def test_allow_local_fetch_env_var_is_the_documented_one(monkeypatch):
    """MINERU_ALLOW_LOCAL_FETCH is the escape hatch hub.json documents for
    operators fetching from a sidecar or a private mirror.

    Asserted at the check rather than through a fetch: letting the URL
    through means opening a socket, and this suite does not touch the
    network.
    """
    _stub_resolver(monkeypatch, {"docs.internal": ["10.0.0.7"]})
    url = "http://docs.internal/report.pdf"

    monkeypatch.delenv("MINERU_ALLOW_LOCAL_FETCH", raising=False)
    with pytest.raises(ValueError, match="publicly routable"):
        worker_net.check_target(url, field="file_url")

    monkeypatch.setenv("MINERU_ALLOW_LOCAL_FETCH", "1")
    worker_net.check_target(url, field="file_url")  # no longer refused
