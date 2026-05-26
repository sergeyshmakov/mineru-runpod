"""Guard tests for our runpod-python internal-API dependency.

handler.py's `_bootstrap_main()` bypasses `runpod.serverless.start()`
and reaches directly into:
  - `runpod.serverless.modules.rp_scale.JobScaler`
  - `runpod.serverless.modules.rp_ping.Heartbeat`
  - `runpod.serverless.modules.rp_fitness.run_fitness_checks`

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
