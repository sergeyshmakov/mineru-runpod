"""MinerU-API-compat client tests. No GPU, no MinerU, no network.

Split in two: pure mapping rules (``mineru_client._mapping``) and the
``MineruApiClient`` I/O shell against a faked ``runpod.Endpoint``.
"""

from __future__ import annotations

import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from mineru_client import MineruApiClient, MineruClientError
from mineru_client import _mapping as m


# -----------------------------------------------------------------------------
# Pure mapping — model_version / page_ranges / payload
# -----------------------------------------------------------------------------

def test_model_version_pipeline_and_vlm():
    assert m.model_version_to_backend("pipeline") == "pipeline"
    assert m.model_version_to_backend("vlm") == "vlm-auto-engine"
    assert m.model_version_to_backend(None) == "pipeline"


def test_model_version_html_unsupported():
    with pytest.raises(ValueError, match="MinerU-HTML"):
        m.model_version_to_backend("MinerU-HTML")


def test_model_version_unknown():
    with pytest.raises(ValueError, match="unknown model_version"):
        m.model_version_to_backend("gpt-9")


@pytest.mark.parametrize(
    "raw,expected",
    [("5", (4, 4)), ("1", (0, 0)), ("2-6", (1, 5)), ("10-10", (9, 9))],
)
def test_page_ranges_single_contiguous(raw, expected):
    assert m.parse_page_ranges(raw) == expected


@pytest.mark.parametrize("raw", ["2,4-6", "2-", "2--2", "", "  ", "-3", "0", "abc", "5-2"])
def test_page_ranges_rejected(raw):
    with pytest.raises(ValueError):
        m.parse_page_ranges(raw)


def test_build_payload_defaults():
    payload = m.build_worker_payload(url="https://x/p.pdf")
    assert payload == {
        "file_url": "https://x/p.pdf",
        "backend": "pipeline",
        "formula_enable": True,
        "table_enable": True,
        "lang": "ch",
        "transport": "s3",
        "archive_format": "zip",
    }
    # page slice omitted when page_ranges is None → worker applies its default
    assert "start_page" not in payload and "end_page" not in payload


def test_build_payload_translates_all_fields():
    payload = m.build_worker_payload(
        url="https://x/p.pdf",
        model_version="vlm",
        enable_formula=False,
        enable_table=False,
        language="en",
        page_ranges="2-6",
    )
    assert payload["backend"] == "vlm-auto-engine"
    assert payload["formula_enable"] is False
    assert payload["table_enable"] is False
    assert payload["lang"] == "en"
    assert payload["start_page"] == 1
    assert payload["end_page"] == 5


def test_build_payload_rejects_extra_formats():
    with pytest.raises(ValueError, match="extra_formats"):
        m.build_worker_payload(url="https://x", extra_formats=["docx", "latex"])


# -----------------------------------------------------------------------------
# Pure mapping — status -> state and response shaping
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,state",
    [
        ("IN_QUEUE", "pending"),
        ("IN_PROGRESS", "running"),
        ("COMPLETED", "done"),
        ("FAILED", "failed"),
        ("TIMED_OUT", "failed"),
        ("CANCELLED", "failed"),
        ("SOMETHING_NEW", "running"),  # unknown -> poll-safe
        (None, "running"),
    ],
)
def test_status_to_state(status, state):
    assert m.runpod_status_to_state(status) == state


def test_create_response_shape():
    assert m.build_create_response("job-1") == {
        "code": 0,
        "msg": "ok",
        "trace_id": "job-1",
        "data": {"task_id": "job-1"},
    }


def test_task_response_pending():
    resp = m.build_task_response("job-1", {"status": "IN_QUEUE"})
    assert resp["data"] == {"task_id": "job-1", "state": "pending", "err_msg": ""}


def test_task_response_done_with_url():
    raw = {"status": "COMPLETED", "output": {"ok": True, "results": [{"tarball_url": "https://s3/x.tar.gz"}]}}
    resp = m.build_task_response("job-1", raw)
    assert resp["data"]["state"] == "done"
    assert resp["data"]["full_zip_url"] == "https://s3/x.tar.gz"
    assert resp["data"]["err_msg"] == ""


def test_task_response_done_without_url_becomes_failed():
    """COMPLETED with results but no tarball_url means the endpoint lacks BUCKET_*."""
    raw = {"status": "COMPLETED", "output": {"ok": True, "results": [{"markdown": "# hi"}]}}
    resp = m.build_task_response("job-1", raw)
    assert resp["data"]["state"] == "failed"
    assert "BUCKET_" in resp["data"]["err_msg"]


def test_task_response_done_with_empty_output_is_no_payload():
    """COMPLETED with None/non-dict output -> generic 'no result payload', NOT the
    misleading BUCKET_* guidance (which only fits the results-but-no-url case)."""
    resp = m.build_task_response("job-1", {"status": "COMPLETED", "output": None})
    assert resp["data"]["state"] == "failed"
    assert resp["data"]["err_msg"] == "job completed but returned no result payload"
    assert "BUCKET_" not in resp["data"]["err_msg"]


def test_task_response_soft_failure_ok_false_without_error_key():
    """ok=false with no error key falls back to the generic 'parse failed'."""
    resp = m.build_task_response("job-1", {"status": "COMPLETED", "output": {"ok": False}})
    assert resp["data"]["state"] == "failed"
    assert resp["data"]["err_msg"] == "parse failed"


def test_task_response_soft_failure_ok_false():
    """Handler ok=false (even on a COMPLETED job) surfaces as failed."""
    raw = {"status": "COMPLETED", "output": {"ok": False, "error": "ValueError: bad input"}}
    resp = m.build_task_response("job-1", raw)
    assert resp["data"]["state"] == "failed"
    assert resp["data"]["err_msg"] == "ValueError: bad input"


def test_task_response_hard_failure():
    raw = {"status": "FAILED", "output": {"error": "boom"}}
    resp = m.build_task_response("job-1", raw)
    assert resp["data"]["state"] == "failed"
    assert resp["data"]["err_msg"] == "boom"


def test_task_response_failure_without_output():
    resp = m.build_task_response("job-1", {"status": "TIMED_OUT"})
    assert resp["data"]["state"] == "failed"
    assert resp["data"]["err_msg"] == "job TIMED_OUT"


def test_task_response_failure_uses_top_level_error():
    """Hard failures (crash/OOM/timeout) carry the reason in a top-level
    `error`, not in `output` — surface it instead of the generic status."""
    raw = {"status": "FAILED", "error": "worker exited unexpectedly (OOM)"}
    resp = m.build_task_response("job-1", raw)
    assert resp["data"]["state"] == "failed"
    assert resp["data"]["err_msg"] == "worker exited unexpectedly (OOM)"


def test_task_response_echoes_data_id():
    resp = m.build_task_response("job-1", {"status": "IN_QUEUE"}, data_id="invoice-7")
    assert resp["data"]["data_id"] == "invoice-7"


# -----------------------------------------------------------------------------
# MineruApiClient against a fake endpoint
# -----------------------------------------------------------------------------

class _FakeRpClient:
    def __init__(self):
        self.last_get = None
        self.next_status = {"status": "IN_QUEUE"}

    def get(self, endpoint, timeout=10):  # noqa: ARG002
        self.last_get = endpoint
        return self.next_status


class _FakeJob:
    def __init__(self, job_id):
        self.job_id = job_id


class _FakeEndpoint:
    def __init__(self, endpoint_id):
        self.endpoint_id = endpoint_id
        self.rp_client = _FakeRpClient()
        self.last_run = None

    def run(self, body):
        # Mirror the real SDK heuristic (runner.py: wrap only if not already
        # wrapped) so a regression that stopped pre-wrapping would surface here —
        # the sibling `webhook` would get buried inside `input`.
        if not body.get("input"):
            body = {"input": body}
        self.last_run = body
        return _FakeJob("job-abc")


@pytest.fixture
def fake_endpoint(monkeypatch):
    import runpod

    monkeypatch.setattr(runpod, "Endpoint", _FakeEndpoint)
    return _FakeEndpoint


def _serve(monkeypatch, data: bytes) -> None:
    """Make urllib.request.urlopen return `data` for any (https) URL — no network,
    no file:// (the scheme guard rejects file://). Patches the module attribute
    both client paths resolve at call time."""
    class _Resp:
        def read(self):
            return data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda url, *a, **k: _Resp())


def test_requires_endpoint_id(fake_endpoint):
    with pytest.raises(ValueError, match="endpoint_id is required"):
        MineruApiClient(endpoint_id="", api_key="x")


def test_requires_api_key(fake_endpoint):
    os.environ.pop("RUNPOD_API_KEY", None)
    with pytest.raises(ValueError, match="api_key not provided"):
        MineruApiClient(endpoint_id="ep-1")


def test_create_task_builds_payload_and_returns_task_id(fake_endpoint):
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    resp = client.create_task("https://x/p.pdf", model_version="vlm", page_ranges="2-6")

    assert resp["data"]["task_id"] == "job-abc"
    assert resp["code"] == 0 and resp["msg"] == "ok"

    body = client._endpoint.last_run
    assert body["input"]["file_url"] == "https://x/p.pdf"
    assert body["input"]["backend"] == "vlm-auto-engine"
    assert body["input"]["transport"] == "s3"
    assert body["input"]["archive_format"] == "zip"
    assert body["input"]["start_page"] == 1 and body["input"]["end_page"] == 5
    assert "webhook" not in body


def test_create_task_rejects_callback(fake_endpoint):
    """callback is unsupported — a RunPod webhook's payload differs from MinerU's
    signed {checksum, content} callback, so we reject rather than mislead."""
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    with pytest.raises(ValueError, match="callback is not supported"):
        client.create_task("https://x/p.pdf", callback="https://hook.example/cb")


def test_create_task_requires_url(fake_endpoint):
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    with pytest.raises(ValueError, match="url is required"):
        client.create_task("")


def test_create_task_rejects_unsupported_model(fake_endpoint):
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    with pytest.raises(ValueError, match="MinerU-HTML"):
        client.create_task("https://x", model_version="MinerU-HTML")


def test_create_task_accepts_no_cache_and_cache_tolerance(fake_endpoint):
    """The official no_cache / cache_tolerance params are accepted (no-op) for
    signature compatibility — they must not raise, and don't reach the payload."""
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    client.create_task("https://x/p.pdf", no_cache=True, cache_tolerance=0)
    payload = client._endpoint.last_run["input"]
    assert "no_cache" not in payload and "cache_tolerance" not in payload


def test_create_task_wraps_transport_error(fake_endpoint, monkeypatch):
    """A raw error from endpoint.run is wrapped in the uniform MineruClientError."""
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")

    def boom(_body):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(client._endpoint, "run", boom)
    with pytest.raises(MineruClientError, match="endpoint submission failed"):
        client.create_task("https://x/p.pdf")


def test_get_task_wraps_transport_error(fake_endpoint, monkeypatch):
    """A raw error from the status query is wrapped in MineruClientError."""
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")

    def boom(*a, **k):
        raise RuntimeError("503 service unavailable")

    monkeypatch.setattr(client._endpoint.rp_client, "get", boom)
    with pytest.raises(MineruClientError, match="status query failed"):
        client.get_task("job-abc")


def test_get_task_maps_status_and_echoes_data_id(fake_endpoint):
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    client.create_task("https://x/p.pdf", data_id="invoice-7")

    client._endpoint.rp_client.next_status = {
        "status": "COMPLETED",
        "output": {"ok": True, "results": [{"tarball_url": "https://s3/x.tar.gz"}]},
    }
    resp = client.get_task("job-abc")
    assert client._endpoint.rp_client.last_get == "ep-1/status/job-abc"
    assert resp["data"]["state"] == "done"
    assert resp["data"]["full_zip_url"] == "https://s3/x.tar.gz"
    assert resp["data"]["data_id"] == "invoice-7"


def test_wait_for_task_polls_until_done(fake_endpoint, monkeypatch):
    monkeypatch.setattr("mineru_client.api_compat.time.sleep", lambda _s: None)
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")

    seq = iter([
        {"status": "IN_QUEUE"},
        {"status": "IN_PROGRESS"},
        {"status": "COMPLETED", "output": {"ok": True, "results": [{"tarball_url": "https://s3/x.tar.gz"}]}},
    ])
    monkeypatch.setattr(client._endpoint.rp_client, "get", lambda *a, **k: next(seq))

    resp = client.wait_for_task("job-abc", poll_interval=0.01, timeout=10)
    assert resp["data"]["state"] == "done"


def test_wait_for_task_times_out(fake_endpoint, monkeypatch):
    monkeypatch.setattr("mineru_client.api_compat.time.sleep", lambda _s: None)
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    client._endpoint.rp_client.next_status = {"status": "IN_PROGRESS"}
    with pytest.raises(MineruClientError, match="did not finish"):
        client.wait_for_task("job-abc", poll_interval=1, timeout=2)


def test_wait_for_task_rejects_nonpositive_poll_interval(fake_endpoint):
    """poll_interval<=0 is rejected up front (else the loop would busy-spin)."""
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    with pytest.raises(ValueError, match="poll_interval must be > 0"):
        client.wait_for_task("job-abc", poll_interval=0)


def test_wait_for_task_retries_transient_error(fake_endpoint, monkeypatch):
    """A transient status-query failure is retried, not propagated, until terminal."""
    monkeypatch.setattr("mineru_client.api_compat.time.sleep", lambda _s: None)
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")

    calls = {"n": 0}
    done = {"status": "COMPLETED",
            "output": {"ok": True, "results": [{"tarball_url": "https://s3/x.zip"}]}}

    def flaky_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise MineruClientError("status query failed: connection reset")
        return done

    monkeypatch.setattr(client._endpoint.rp_client, "get", flaky_get)
    resp = client.wait_for_task("job-abc", poll_interval=0.01, timeout=10)
    assert resp["data"]["state"] == "done"
    assert calls["n"] == 2  # first poll failed, retried, second succeeded


def test_download_results_extracts_tarball(fake_endpoint, tmp_path, monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"# parsed\n"
        info = tarfile.TarInfo("doc.md")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    _serve(monkeypatch, buf.getvalue())

    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    response = {"data": {"state": "done", "full_zip_url": "https://bucket.example/out.tar.gz"}}
    dest = client.download_results(response, tmp_path / "out")
    assert (Path(dest) / "doc.md").read_bytes() == b"# parsed\n"


def test_download_results_extracts_zip(fake_endpoint, tmp_path, monkeypatch):
    """The compat client requests .zip, so download_results must unpack a zip
    (it autodetects the container from the archive's magic bytes)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("doc.md", "# parsed\n")
    _serve(monkeypatch, buf.getvalue())

    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    response = {"data": {"state": "done", "full_zip_url": "https://bucket.example/out.zip"}}
    dest = client.download_results(response, tmp_path / "out")
    assert (Path(dest) / "doc.md").read_text() == "# parsed\n"


def test_download_results_from_bare_task_id_repolls(fake_endpoint, tmp_path, monkeypatch):
    """A bare task_id re-polls get_task, then downloads — exercises the str branch."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("doc.md", "# parsed\n")
    _serve(monkeypatch, buf.getvalue())

    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    client._endpoint.rp_client.next_status = {
        "status": "COMPLETED",
        "output": {"ok": True, "results": [{"tarball_url": "https://bucket.example/out.zip"}]},
    }
    dest = client.download_results("job-abc", tmp_path / "out")
    assert (Path(dest) / "doc.md").read_text() == "# parsed\n"


def test_download_results_requires_url(fake_endpoint, tmp_path):
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    response = {"data": {"state": "running"}}
    with pytest.raises(MineruClientError, match="no full_zip_url"):
        client.download_results(response, tmp_path / "out")


def test_download_results_rejects_non_http_url(fake_endpoint, tmp_path):
    """A non-HTTP(S) full_zip_url (e.g. file://) is refused before any fetch."""
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    response = {"data": {"state": "done", "full_zip_url": "file:///etc/passwd"}}
    with pytest.raises(MineruClientError, match="non-HTTP"):
        client.download_results(response, tmp_path / "out")


def test_download_results_rejects_tar_path_traversal(fake_endpoint, tmp_path, monkeypatch):
    """A tar member that escapes the destination is refused before any write
    (CVE-2007-4559 path-traversal guard)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        payload = b"pwned\n"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    _serve(monkeypatch, buf.getvalue())

    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    response = {"data": {"state": "done", "full_zip_url": "https://bucket.example/evil.tar.gz"}}
    with pytest.raises(MineruClientError, match="escapes the destination"):
        client.download_results(response, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_download_results_rejects_tar_symlink_member(fake_endpoint, tmp_path, monkeypatch):
    """A symlink member is rejected ('not a regular file or dir') — the
    CVE-2007-4559 member-type branch that the traversal test doesn't reach."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    _serve(monkeypatch, buf.getvalue())

    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    response = {"data": {"state": "done", "full_zip_url": "https://bucket.example/evil.tar.gz"}}
    with pytest.raises(MineruClientError, match="not a regular file or dir"):
        client.download_results(response, tmp_path / "out")


def test_download_results_zip_member_outside_dest_is_reported(
    fake_endpoint, tmp_path, monkeypatch
):
    """A zip member naming a path outside dest is reported, not relocated.

    The stdlib reader would rewrite such a name and extract it somewhere else;
    an archive from a worker never contains one, so the caller hears about it
    instead of finding files where they didn't ask for them.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("../escape.txt", "unexpected\n")
    _serve(monkeypatch, buf.getvalue())

    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    response = {"data": {"state": "done", "full_zip_url": "https://bucket.example/out.zip"}}
    with pytest.raises(MineruClientError, match="refusing zip member"):
        client.download_results(response, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_download_results_passes_a_timeout(fake_endpoint, tmp_path, monkeypatch):
    """urlopen must be called with a timeout so a stalled download can't hang forever."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("doc.md", "x")
    captured = {}

    class _Resp:
        def read(self):
            return buf.getvalue()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url, *a, **k):
        captured["timeout"] = k.get("timeout")
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = MineruApiClient(endpoint_id="ep-1", api_key="x")
    client.download_results(
        {"data": {"state": "done", "full_zip_url": "https://bucket.example/o.zip"}},
        tmp_path / "out",
    )
    assert isinstance(captured["timeout"], (int, float)) and captured["timeout"] > 0
