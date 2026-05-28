"""Worker-process behaviors that aren't request-shape semantics.

- Cumulative refresh counters (REFRESH_WORKER_AFTER_JOBS / _PAGES)
- Concurrency modifier env-var parsing (MINERU_MAX_CONCURRENCY)
- SIGTERM shutdown event
"""

from __future__ import annotations

import asyncio

import pytest

import handler


@pytest.fixture(autouse=True)
def reset_counters(monkeypatch):
    """Each test starts with clean counters and no thresholds set."""
    handler._jobs_processed = 0
    handler._pages_processed_total = 0
    monkeypatch.delenv("REFRESH_WORKER_AFTER_JOBS", raising=False)
    monkeypatch.delenv("REFRESH_WORKER_AFTER_PAGES", raising=False)
    yield


# -----------------------------------------------------------------------------
# Refresh counters
# -----------------------------------------------------------------------------

def test_refresh_disabled_by_default():
    # With no thresholds set, every job returns None (no recycle).
    for _ in range(5):
        assert handler._record_job(10) is None


def test_refresh_jobs_threshold_crosses(monkeypatch):
    monkeypatch.setenv("REFRESH_WORKER_AFTER_JOBS", "3")
    assert handler._record_job(0) is None
    assert handler._record_job(0) is None
    # Third job crosses the jobs threshold — reason identifies which one.
    assert handler._record_job(0) == "jobs_threshold"
    assert handler._jobs_processed == 3


def test_refresh_pages_threshold_crosses(monkeypatch):
    monkeypatch.setenv("REFRESH_WORKER_AFTER_PAGES", "50")
    assert handler._record_job(20) is None
    assert handler._record_job(20) is None  # 40 cumulative
    # 60 cumulative crosses 50 — pages reason wins.
    assert handler._record_job(20) == "pages_threshold"
    assert handler._pages_processed_total == 60


def test_refresh_unbounded_jobs_do_not_count_pages(monkeypatch):
    # End-page=-1 jobs pass pages=0; jobs counter still increments.
    monkeypatch.setenv("REFRESH_WORKER_AFTER_PAGES", "10")
    monkeypatch.setenv("REFRESH_WORKER_AFTER_JOBS", "2")
    assert handler._record_job(0) is None
    assert handler._record_job(0) == "jobs_threshold"  # job count 2 crosses


def test_refresh_either_threshold_trips(monkeypatch):
    # If BOTH thresholds are set, whichever trips first wins.
    monkeypatch.setenv("REFRESH_WORKER_AFTER_JOBS", "100")
    monkeypatch.setenv("REFRESH_WORKER_AFTER_PAGES", "5")
    assert handler._record_job(3) is None       # pages 3
    assert handler._record_job(3) == "pages_threshold"  # pages 6, crosses


def test_refresh_jobs_reason_wins_when_both_trip_same_job(monkeypatch):
    """When jobs AND pages thresholds both trip on the same call, jobs
    wins deterministically — order matches the env-var documentation."""
    monkeypatch.setenv("REFRESH_WORKER_AFTER_JOBS", "1")
    monkeypatch.setenv("REFRESH_WORKER_AFTER_PAGES", "1")
    assert handler._record_job(5) == "jobs_threshold"


def test_refresh_malformed_env_var_treated_as_disabled(monkeypatch):
    monkeypatch.setenv("REFRESH_WORKER_AFTER_JOBS", "not-a-number")
    assert handler._record_job(0) is None


def test_refresh_worker_signal_via_full_handler_path(monkeypatch):
    """End-to-end: set threshold=1, run handler, confirm refresh_worker key."""
    monkeypatch.setenv("REFRESH_WORKER_AFTER_JOBS", "1")

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "fake-out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)

    result = asyncio.run(handler.handler({
        "input": {"file_b64": "JVBERi0xLjQK", "basename": "test"}  # %PDF-1.4
    }))
    assert result.get("ok") is True
    assert result.get("refresh_worker") is True


# -----------------------------------------------------------------------------
# Concurrency modifier
# -----------------------------------------------------------------------------

def test_concurrency_default_is_one(monkeypatch):
    monkeypatch.delenv("MINERU_MAX_CONCURRENCY", raising=False)
    assert handler._concurrency_modifier(0) == 1


def test_concurrency_from_env(monkeypatch):
    monkeypatch.setenv("MINERU_MAX_CONCURRENCY", "3")
    assert handler._concurrency_modifier(0) == 3


def test_concurrency_clamps_to_one(monkeypatch):
    # Zero / negative makes no sense for a serverless worker; coerce to 1.
    monkeypatch.setenv("MINERU_MAX_CONCURRENCY", "0")
    assert handler._concurrency_modifier(0) == 1
    monkeypatch.setenv("MINERU_MAX_CONCURRENCY", "-5")
    assert handler._concurrency_modifier(0) == 1


def test_concurrency_malformed_env_var_falls_back_to_one(monkeypatch):
    monkeypatch.setenv("MINERU_MAX_CONCURRENCY", "auto")
    assert handler._concurrency_modifier(0) == 1


# -----------------------------------------------------------------------------
# SIGTERM shutdown breadcrumb
# -----------------------------------------------------------------------------

def test_check_shutdown_raises_when_event_set():
    handler._shutting_down.set()
    try:
        with pytest.raises(RuntimeError, match="shutting down"):
            handler._check_shutdown()
    finally:
        handler._shutting_down.clear()


def test_check_shutdown_is_noop_when_clear():
    handler._shutting_down.clear()
    handler._check_shutdown()  # should not raise


def test_on_sigterm_sets_event():
    handler._shutting_down.clear()
    try:
        handler._on_sigterm(15, None)
        assert handler._shutting_down.is_set()
    finally:
        handler._shutting_down.clear()


# -----------------------------------------------------------------------------
# Egress sizing helper (feeds the bytes_out_total / output_size_bytes metrics)
# -----------------------------------------------------------------------------

def test_measure_output_bytes_tarball():
    """Tarball: the base64 string IS the payload; len() is exact.
    The helper reads through `response["results"][0]` per the unified shape.
    """
    response = {"results": [{"tarball_b64": "QUFB" * 100}]}  # 400-char b64 string
    assert handler._measure_output_bytes(response, "tarball_b64") == 400


def test_measure_output_bytes_inline_sums_markdown_and_images():
    """Inline: dominate fields are markdown text + b64 image strings."""
    response = {"results": [{
        "markdown": "# hello\n",  # 8 utf-8 bytes
        "images": {"page1.png": "A" * 200, "page2.png": "B" * 300},
        # content_list / middle are ignored — JSON overhead is negligible
        # compared to the image and markdown payload on real documents.
        "content_list": [{"foo": "bar"}],
    }]}
    assert handler._measure_output_bytes(response, "inline") == 8 + 500


def test_measure_output_bytes_s3_uses_bucket_bytes():
    """S3: package_s3 records the uploaded tarball size in bucket_bytes."""
    response = {"results": [{
        "tarball_url": "https://example.com/x.tar.gz",
        "bucket_bytes": 1024 * 1024,
    }]}
    assert handler._measure_output_bytes(response, "s3") == 1024 * 1024


def test_measure_output_bytes_empty_response_returns_zero():
    """A response missing the expected fields shouldn't produce a misleading
    zero histogram sample — the caller skips the record on out_bytes <= 0.
    Failure responses also have no `results` key and must return 0.
    """
    assert handler._measure_output_bytes({}, "tarball_b64") == 0
    assert handler._measure_output_bytes({}, "inline") == 0
    assert handler._measure_output_bytes({}, "s3") == 0
    assert handler._measure_output_bytes({"results": []}, "tarball_b64") == 0
    assert handler._measure_output_bytes({"results": [{}]}, "tarball_b64") == 0
    assert handler._measure_output_bytes({"random": "shape"}, "unknown") == 0


def test_measure_output_bytes_inline_handles_unicode():
    """Multi-byte chars count as utf-8 bytes, not codepoints."""
    response = {"results": [{"markdown": "héllo", "images": {}}]}
    # 'h' + 'é' (2 bytes) + 'l' + 'l' + 'o' = 6 utf-8 bytes
    assert handler._measure_output_bytes(response, "inline") == 6
