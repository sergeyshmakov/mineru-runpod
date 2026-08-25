"""MinerU-API-compat client tests. No GPU, no MinerU, no network. -- request."""

from __future__ import annotations

import os

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
