"""Guard tests for our runpod-python internal-API dependency.

handler.py's `_bootstrap_main()` bypasses `runpod.serverless.start()`
and reaches directly into:
  - `runpod.serverless.modules.rp_scale.JobScaler`
  - `runpod.serverless.modules.rp_ping.Heartbeat`
  - `runpod.serverless.modules.rp_fitness.run_fitness_checks`

`worker/envelope.py`'s `_maybe_progress()` posts its own progress
update rather than calling `runpod.serverless.progress_update`, and
reaches into:
  - `runpod.serverless.modules.rp_http.send_result`
  - `runpod.serverless.modules.rp_http.JOB_DONE_URL`
  - `runpod.http_client.AsyncClientSession`
  - `aiohttp_retry.FibonacciRetry`, for the budget arithmetic

These are undocumented internals — RunPod can rename or restructure
them in a future release. If they do, we want a clear test failure
during CI, not a runtime explosion in production. These tests assert
the API shape we depend on still exists.

If a test here fails after a `pip install -U runpod` upgrade:
  - Either the SDK refactored — adjust `handler._bootstrap_main()` to
    use the new layout, OR
  - Pin runpod to a known-good version range in pyproject.toml.
"""

from __future__ import annotations

import inspect

import pytest


def test_jobscaler_module_path_exists():
    """JobScaler lives at the expected import path."""
    from runpod.serverless.modules import rp_scale  # noqa: F401
    assert hasattr(rp_scale, "JobScaler"), (
        "rp_scale.JobScaler not found — runpod SDK refactored; "
        "update handler._bootstrap_main()"
    )


def test_jobscaler_accepts_config_dict():
    """JobScaler(config: dict) is the constructor signature we rely on."""
    from runpod.serverless.modules.rp_scale import JobScaler
    sig = inspect.signature(JobScaler)
    params = list(sig.parameters.values())
    # __init__(self, config) — signature() on a class hides `self`.
    assert len(params) >= 1, f"JobScaler constructor signature unexpected: {sig}"


def test_jobscaler_has_async_run_method():
    """JobScaler.run() must be an async method we can `await`."""
    from runpod.serverless.modules.rp_scale import JobScaler
    assert hasattr(JobScaler, "run"), "JobScaler.run() missing"
    assert inspect.iscoroutinefunction(JobScaler.run), (
        "JobScaler.run is not a coroutine — SDK changed the serving "
        "model; handler._bootstrap_main() needs to be revisited"
    )


def test_jobscaler_has_sync_handle_shutdown():
    """We chain our SIGTERM handler with scaler.handle_shutdown()."""
    from runpod.serverless.modules.rp_scale import JobScaler
    assert hasattr(JobScaler, "handle_shutdown"), (
        "JobScaler.handle_shutdown missing — signal-handler chaining "
        "in _bootstrap_main() needs to be updated"
    )


def test_heartbeat_class_exists_and_has_start_ping():
    """rp_ping.Heartbeat().start_ping() is the heartbeat thread we start."""
    from runpod.serverless.modules import rp_ping
    assert hasattr(rp_ping, "Heartbeat"), "rp_ping.Heartbeat missing"
    instance = rp_ping.Heartbeat()
    assert hasattr(instance, "start_ping"), "Heartbeat.start_ping missing"


def test_run_fitness_checks_is_async():
    """rp_fitness.run_fitness_checks() must be awaitable."""
    from runpod.serverless.modules.rp_fitness import run_fitness_checks
    assert inspect.iscoroutinefunction(run_fitness_checks), (
        "run_fitness_checks is not a coroutine — bootstrap call site "
        "needs to be updated"
    )


def test_serverless_start_still_exists_for_local_mode():
    """We still fall back to runpod.serverless.start() for local test mode."""
    import runpod.serverless
    assert hasattr(runpod.serverless, "start"), (
        "runpod.serverless.start() missing — local test fallback in "
        "handler.py __main__ needs to be replaced"
    )


# ---------------------------------------------------------------------------
# The progress-update bypass (issue #40)
# ---------------------------------------------------------------------------

def test_send_result_is_the_awaitable_we_post_progress_through():
    """`_maybe_progress()` awaits rp_http.send_result directly."""
    from runpod.serverless.modules import rp_http
    assert inspect.iscoroutinefunction(rp_http.send_result), (
        "rp_http.send_result is not a coroutine — worker/envelope.py "
        "cannot await it; _maybe_progress() needs to be revisited"
    )
    params = list(inspect.signature(rp_http.send_result).parameters)
    assert params[:3] == ["session", "job_data", "job"], (
        f"rp_http.send_result signature changed to {params} — the call in "
        f"_maybe_progress() passes (session, job_data, job) positionally"
    )


def test_job_done_url_sentinel_is_what_we_short_circuit_on():
    """With no results URL injected, the constant is this literal string.

    `_maybe_progress()` compares against it to decide there is nowhere to post.
    If the SDK ever used None or an empty string instead, the comparison would
    silently stop matching and every local run would attempt a real POST.
    """
    import os

    if os.environ.get("RUNPOD_WEBHOOK_POST_OUTPUT"):
        pytest.skip("a real results URL is configured in this environment")

    from runpod.serverless.modules import rp_http
    assert rp_http.JOB_DONE_URL == "JOB_DONE_URL", (
        f"unset-webhook sentinel is now {rp_http.JOB_DONE_URL!r} — update the "
        f"short-circuit in worker/envelope.py._maybe_progress()"
    )


def test_async_client_session_is_a_self_closing_factory():
    """It is a factory function, not a class, and `async with` closes it."""
    import asyncio

    import aiohttp

    from runpod import http_client

    assert inspect.isfunction(http_client.AsyncClientSession), (
        "AsyncClientSession is no longer a factory function — the "
        "`async with AsyncClientSession() as s` in _maybe_progress() "
        "may need to change shape"
    )

    async def build_and_close():
        async with http_client.AsyncClientSession() as session:
            assert isinstance(session, aiohttp.ClientSession)
            return session

    assert asyncio.run(build_and_close()).closed is True


def test_async_client_session_still_forbids_a_timeout_override():
    """Why we bound with `wait_for` rather than a short per-request timeout.

    The factory passes `timeout=` itself, so supplying one is a TypeError. If
    that ever stops being true, the budget could move into the session and the
    `wait_for` in _maybe_progress() would become redundant.

    Called inside a loop because the factory builds a TCPConnector eagerly,
    which needs a running one — the reason _maybe_progress() constructs its
    session per call from async code rather than once at import.
    """
    import asyncio

    import aiohttp

    from runpod import http_client

    async def override_the_timeout():
        with pytest.raises(TypeError):
            http_client.AsyncClientSession(timeout=aiohttp.ClientTimeout(total=5))

    asyncio.run(override_the_timeout())


def test_the_retry_schedule_still_fits_the_progress_budget():
    """The budget is derived from this schedule, so pin the arithmetic.

    `_transmit` builds `FibonacciRetry(attempts=3)` per POST, which sleeps
    2s + 3s across a full cycle. `_PROGRESS_BUDGET_SECONDS` has to exceed that
    or a degraded results API gets its retries severed mid-flight — the one
    path that can still strand a job.
    """
    from aiohttp_retry import FibonacciRetry

    from worker import envelope

    retry = FibonacciRetry(attempts=3)
    schedule = [retry.get_timeout(1), retry.get_timeout(2)]
    assert schedule == [2.0, 3.0], (
        f"FibonacciRetry schedule changed to {schedule} — recheck "
        f"_PROGRESS_BUDGET_SECONDS in worker/envelope.py"
    )
    assert sum(schedule) < envelope._PROGRESS_BUDGET_SECONDS, (
        f"retry cycle ({sum(schedule)}s) no longer fits inside the "
        f"{envelope._PROGRESS_BUDGET_SECONDS}s progress budget"
    )


def test_sdk_progress_update_is_still_the_threaded_fire_and_forget():
    """The expiry alarm on this whole workaround.

    When this fails, RunPod has stopped posting progress from an unawaited
    daemon thread, the race in issues #4 and #40 is gone upstream, and
    `_maybe_progress()` can go back to calling the SDK helper.
    """
    from runpod.serverless.modules import rp_progress

    assert not inspect.iscoroutinefunction(rp_progress.progress_update)
    assert "threading.Thread" in inspect.getsource(rp_progress.progress_update), (
        "runpod.serverless.progress_update no longer posts from a background "
        "thread — the hand-rolled awaited POST in worker/envelope.py may no "
        "longer be necessary"
    )
