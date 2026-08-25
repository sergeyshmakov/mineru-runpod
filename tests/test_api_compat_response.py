"""MinerU-API-compat client tests. No GPU, no MinerU, no network. -- response."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from mineru_client import MineruApiClient, MineruClientError
from mineru_client import _mapping as m


class _FakeEndpoint:
    def __init__(self, endpoint_id):
        self.endpoint_id = endpoint_id
        self.rp_client = _FakeRpClient()
        self.last_run = None

    def run(self, body):
        # Mirror the real SDK heuristic (runner.py: wrap only if not already
        # wrapped) so a regression that stopped pre-wrapping would surface here вЂ”
        # the sibling `webhook` would get buried inside `input`.
        if not body.get("input"):
            body = {"input": body}
        self.last_run = body
        return _FakeJob("job-abc")


class _FakeJob:
    def __init__(self, job_id):
        self.job_id = job_id


class _FakeRpClient:
    def __init__(self):
        self.last_get = None
        self.next_status = {"status": "IN_QUEUE"}

    def get(self, endpoint, timeout=10):  # noqa: ARG002
        self.last_get = endpoint
        return self.next_status


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
