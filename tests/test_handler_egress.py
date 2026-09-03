"""What the handler posts to RunPod while a job is still running.

A progress update travels to the same job-results URL as the final result, so
these tests are about *ordering*, not content: an update that is still in flight
when the handler returns can be applied after the COMPLETED status and strand a
finished job at IN_PROGRESS forever. Issue #4 hit that at `packaging`; issue #40
hit it again at `parsing`, on office inputs whose parse takes ~88 ms.

The old regression test here asserted `parsing` was the *last* phase, which only
ever encoded a guess about how much work followed it. What is asserted now is the
property that guess was standing in for: when the handler returns, nothing is
outstanding.

`fake_run` returns immediately, so every test below runs in the sub-millisecond
parse regime that made #40 reachable -- no MinerU and no office fixture needed.
"""

from __future__ import annotations

import asyncio
import json
import time

import aiohttp
import pytest

from runpod.serverless.modules import rp_http

import handler

# Any absolute URL defeats the "webhook env unset" short-circuit. It is never
# fetched -- every test patches the sender, the session, or both.
_WEBHOOK = "https://webhook.test/v2/endpoint/job-done/$ID?token=x"

_JOB_INPUT = {"file_b64": "JVBERi0xLjQK", "basename": "doc", "transport": "inline"}


def _stub_run_mineru(monkeypatch):
    """A parse that finishes instantly -- the worst case for this race."""
    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        return out
    monkeypatch.setattr("worker.parse.run_mineru", fake_run)


class _FakeSession:
    """Stands in for AsyncClientSession() so no connector or credential is touched."""

    def __init__(self, log: list):
        self.headers: dict = {}
        self.closed = False
        log.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False


def _patch_session(monkeypatch) -> list:
    sessions: list = []
    monkeypatch.setattr(
        "worker.envelope.AsyncClientSession", lambda *a, **kw: _FakeSession(sessions)
    )
    return sessions


def _patch_sender(monkeypatch, fn) -> None:
    """Patch every route to the job-results POST.

    `rp_progress` holds its own reference to `send_result` (`from .rp_http import
    send_result`), so patching `rp_http` alone would not see a call made through
    the SDK helper. Patching both means a future revert to
    `runpod.serverless.progress_update` still lands in the recorder -- from its
    daemon thread, after the handler returned, which is exactly what fails the
    ordering assertion below.
    """
    monkeypatch.setattr("runpod.serverless.modules.rp_http.send_result", fn)
    monkeypatch.setattr("runpod.serverless.modules.rp_progress.send_result", fn)


def test_progress_posts_complete_before_the_handler_returns(monkeypatch):
    """The invariant: nothing is in flight when the handler hands back a result.

    This replaces `test_no_progress_update_after_parse`. Its phase list still
    carries #9's finding -- no update may be emitted after the parse -- but the
    assertion that matters is `outstanding`, which is what actually strands a job.
    """
    _stub_run_mineru(monkeypatch)
    _patch_session(monkeypatch)
    monkeypatch.setattr(rp_http, "JOB_DONE_URL", _WEBHOOK)

    started: list = []
    finished: list = []

    async def slow_send(session, job_data, job, is_stream=False):
        phase = job_data["output"].get("phase")
        started.append(phase)
        # Long enough that a fire-and-forget POST would still be running.
        await asyncio.sleep(0.15)
        finished.append(phase)

    _patch_sender(monkeypatch, slow_send)

    sdk_calls: list = []
    monkeypatch.setattr(
        "runpod.serverless.progress_update",
        lambda job, data: sdk_calls.append(data.get("phase")),
    )

    snapshot: dict = {}

    async def spy(job):
        result = await handler.handler(job)
        # Read inside the handler's own task, at the moment it returns.
        snapshot["started"] = list(started)
        snapshot["finished"] = list(finished)
        return result

    result = asyncio.run(spy({"id": "ordering-test", "input": _JOB_INPUT}))

    assert result["ok"] is True
    assert snapshot["started"] == ["fetching_input", "parsing"]
    assert snapshot["finished"] == ["fetching_input", "parsing"], (
        f"a progress POST was still in flight when the handler returned "
        f"(started {snapshot['started']!r}, finished {snapshot['finished']!r}); "
        f"it can be applied after the COMPLETED post and strand the job IN_PROGRESS"
    )
    assert sdk_calls == [], (
        f"progress went through runpod.serverless.progress_update ({sdk_calls!r}), "
        f"which posts from a daemon thread the handler does not wait for"
    )


def test_a_hung_progress_post_is_bounded_and_does_not_fail_the_job(monkeypatch, capsys):
    """A hung results API costs the budget, twice, and nothing else."""
    _stub_run_mineru(monkeypatch)
    _patch_session(monkeypatch)
    monkeypatch.setattr(rp_http, "JOB_DONE_URL", _WEBHOOK)
    monkeypatch.setattr("worker.envelope._PROGRESS_BUDGET_SECONDS", 0.2)
    monkeypatch.setenv("LOG_FORMAT", "json")

    cancelled: list = []

    async def hang(session, job_data, job, is_stream=False):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(job_data["output"].get("phase"))
            raise

    _patch_sender(monkeypatch, hang)

    started = time.monotonic()
    result = asyncio.run(handler.handler({"id": "hung-post", "input": _JOB_INPUT}))
    elapsed = time.monotonic() - started

    assert result["ok"] is True, "a hung progress post must not fail the job"
    assert 0.4 <= elapsed < 5.0, (
        f"expected to wait out two 0.2s budgets and then move on, took {elapsed:.2f}s"
    )
    assert cancelled == ["fetching_input", "parsing"], (
        f"the POST coroutine must be cancelled at the budget, not orphaned "
        f"(cancelled {cancelled!r})"
    )

    warnings = [
        json.loads(ln) for ln in capsys.readouterr().out.splitlines()
        if ln.startswith("{") and "progress update timed out" in ln
    ]
    assert len(warnings) == 2, "a timed-out update is the only trace of the residual race"
    assert warnings[0]["level"] == "warning"
    assert warnings[0]["phase"] == "fetching_input"


def test_no_progress_egress_when_the_webhook_url_is_unset(monkeypatch):
    """Nothing is posted anywhere when RunPod has not supplied a results URL."""
    # Assert the precondition, so this cannot pass because a patch went missing.
    assert rp_http.JOB_DONE_URL == "JOB_DONE_URL", (
        "conftest should have popped RUNPOD_WEBHOOK_POST_OUTPUT before import"
    )

    _stub_run_mineru(monkeypatch)
    sessions = _patch_session(monkeypatch)

    posts: list = []

    async def record(session, job_data, job, is_stream=False):
        posts.append(job_data)

    _patch_sender(monkeypatch, record)

    sdk_calls: list = []
    monkeypatch.setattr(
        "runpod.serverless.progress_update", lambda job, data: sdk_calls.append(data)
    )

    result = asyncio.run(handler.handler({"id": "no-webhook", "input": _JOB_INPUT}))

    assert result["ok"] is True
    assert posts == []
    assert sdk_calls == []
    assert sessions == [], "no session should be built when there is nowhere to post"


def test_a_job_without_an_id_parses_and_posts_nothing(monkeypatch):
    """Sync callers have no job id, and a progress post is addressed by id.

    A regression lock rather than a race test: the id is what `_handle_result`
    puts in the URL and the `X-Request-ID` header, so without one there is
    nothing to address and the parse must still succeed.
    """
    _stub_run_mineru(monkeypatch)
    sessions = _patch_session(monkeypatch)
    monkeypatch.setattr(rp_http, "JOB_DONE_URL", _WEBHOOK)

    posts: list = []

    async def record(session, job_data, job, is_stream=False):
        posts.append(job_data)

    _patch_sender(monkeypatch, record)

    # No "id" key at all.
    result = asyncio.run(handler.handler({"input": _JOB_INPUT}))

    assert result["ok"] is True
    assert posts == []
    assert sessions == []


def test_progress_payload_is_the_status_envelope_the_api_expects(monkeypatch):
    """We build the wire format ourselves now, so its shape is our obligation.

    `{"status": "IN_PROGRESS", "output": ...}` is what `rp_progress` used to
    construct. Getting it wrong would not fail a test that only counted phases.
    """
    _stub_run_mineru(monkeypatch)
    _patch_session(monkeypatch)
    monkeypatch.setattr(rp_http, "JOB_DONE_URL", _WEBHOOK)

    captured: list = []

    async def record(session, job_data, job, is_stream=False):
        captured.append((job_data, job))

    _patch_sender(monkeypatch, record)

    job = {"id": "envelope-test", "input": _JOB_INPUT}
    result = asyncio.run(handler.handler(job))

    assert result["ok"] is True
    assert [d["status"] for d, _ in captured] == ["IN_PROGRESS", "IN_PROGRESS"]
    assert set(captured[0][0]) == {"status", "output"}, "no extra top-level keys"
    assert captured[0][0]["output"] == {"phase": "fetching_input"}
    assert set(captured[1][0]["output"]) == {
        "phase", "input_bytes", "input_format", "start_page", "end_page",
    }
    assert captured[1][0]["output"]["input_format"] == "pdf"
    # The job dict is passed through, not copied: _handle_result reads job["id"].
    assert all(passed is job for _, passed in captured)


def test_a_failing_progress_post_does_not_fail_the_job(monkeypatch):
    """The results API being down is not the caller's problem."""
    _stub_run_mineru(monkeypatch)
    _patch_session(monkeypatch)
    monkeypatch.setattr(rp_http, "JOB_DONE_URL", _WEBHOOK)

    async def boom(session, job_data, job, is_stream=False):
        raise aiohttp.ClientError("results API unreachable")

    _patch_sender(monkeypatch, boom)

    result = asyncio.run(handler.handler({"id": "failing-post", "input": _JOB_INPUT}))
    assert result["ok"] is True


def test_maybe_progress_is_awaited_by_the_handler():
    """A plain `def` here would make both call sites fire-and-forget again.

    `handler.py` calls this with `await`. If it ever stops being a coroutine
    function, those awaits break loudly -- but if the awaits were dropped at the
    same time, nothing else in this file would notice.
    """
    import inspect

    from worker import envelope

    assert inspect.iscoroutinefunction(envelope._maybe_progress)
    assert inspect.iscoroutinefunction(handler._maybe_progress)


@pytest.mark.parametrize("phase", ["fetching_input", "parsing"])
def test_every_emitted_phase_is_documented(phase):
    """The phase list in the API reference is a promise; keep it checkable."""
    doc = (
        handler.__file__.replace("handler.py", "")
        + "docs/content/docs/reference/api.mdx"
    )
    with open(doc, encoding="utf-8") as fh:
        text = fh.read()
    assert f'"phase": "{phase}"' in text, (
        f"phase {phase!r} is emitted but not shown in the API reference"
    )
