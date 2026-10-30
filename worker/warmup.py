"""Eager warmup at worker boot.

Moves the vLLM + MinerU cold-start tax from first-request latency to
worker-boot latency. The first user request then lands on a fully warm
engine: MinerU 4 caches the vLLM engine and its local models per process,
so the throwaway parse here is what loads them.

The payoff compounds, but only on hosts the worker has visited
before. FlashBoot is process-snapshot based and **per (host,
image-SHA)** — confirmed empirically 2026-05-26 with a 4-request
investigation (see guides/troubleshooting.mdx "FlashBoot mechanism").
First visit to a host: warmup runs in full (~110 s). Subsequent
scale-from-zeroes that RunPod schedules onto that same host:
snapshot restore in ~7-8 s. New host: warmup re-runs once.

Either way the per-request cold tax is gone — the first user
request always lands on a warm engine. The variable is whether the
*worker boot* paid 110 s or 7 s, which is invisible to the caller's
wall-clock on a snapshot-restored boot.

**Which loop.** MinerU 3.x bound vLLM's engine to the asyncio loop that
created it, so a warmup run under its own ``asyncio.run()`` left the
serving loop talking to a dead engine (`EngineDeadError` ~75 ms into the
first request). That is why ``handler._bootstrap_main()`` runs warmup and
serving under one loop. MinerU 4 gives the engine its own thread and loop
(``mineru.model.vlm.async_runtime.AsyncVlmPredictor``), so the constraint no
longer comes from the engine; the composition stays because it is tested and
costs nothing. ``warmup_async()`` remains the production entry point; the
synchronous ``warmup()`` wrapper is for tests and local debugging.

Failure is non-fatal. A worker that can't warm up still serves
requests (just slowly on the first one, falling back to lazy load).
This is deliberate: a broken warmup must NOT prevent the worker from
booting and serving traffic.

Logging here uses plain ``print()`` with a ``[mineru-warmup]`` prefix.
This pre-dates the structured JSON logger being loaded, runs in a
distinct lifecycle phase (pre-``serverless.start()``), and remains
visually distinct in RunPod's log viewer from the per-request JSON
records. No need to change it.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

# Baked into the image at Dockerfile's `COPY .runpod/test-fixture.pdf
# /worker/test-fixture.pdf`. Module-level so tests can monkeypatch it.
WARMUP_FIXTURE_PATH = Path("/worker/test-fixture.pdf")


def _log(msg: str) -> None:
    """Plain stdout breadcrumb — known-good channel."""
    print(f"[mineru-warmup] {msg}", flush=True)


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


async def warmup_async() -> None:
    """Run one throwaway parse at boot to load model + compile kernels.

    Reads ``MINERU_SKIP_WARMUP`` / ``MINERU_WARMUP_TIER`` from the
    environment. Never raises — the caller proceeds to serve requests
    whether this succeeds or not.

    Called from the loop that will serve requests; see the module
    docstring for why that is no longer load-bearing.
    """
    if _truthy(os.environ.get("MINERU_SKIP_WARMUP", "")):
        _log("MINERU_SKIP_WARMUP set, skipping warmup")
        return

    if not WARMUP_FIXTURE_PATH.is_file():
        # Local pytest / non-container envs won't have the fixture. Don't
        # error; just skip and let lazy load kick in on first request.
        _log(f"fixture not found at {WARMUP_FIXTURE_PATH}, skipping warmup")
        return

    # The tier most callers use, so the models it needs are the ones loaded.
    # flash and basic never load the VLM; warming them leaves it for the
    # first standard/advanced request.
    tier = os.environ.get("MINERU_WARMUP_TIER", "").strip() or "standard"
    _log(f"starting (tier={tier} fixture={WARMUP_FIXTURE_PATH})")
    start = time.monotonic()

    # Local import to keep this module light when telemetry isn't wired up
    # (e.g. some test contexts that import warmup standalone).
    from worker import telemetry as _telemetry  # noqa: PLC0415

    with _telemetry.span("mineru.warmup", **{"mineru.tier": tier}):
        try:
            fixture_bytes = WARMUP_FIXTURE_PATH.read_bytes()
            await _warmup_once(fixture_bytes, tier=tier)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            _telemetry.record_exception(exc)
            _telemetry.histogram_record(
                "warmup_duration", elapsed, tier=tier, status="error",
            )
            _log(f"failed after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
            _log("worker will continue with lazy-load fallback")
            return

        elapsed = time.monotonic() - start
        _telemetry.histogram_record(
            "warmup_duration", elapsed, tier=tier, status="ok",
        )
        _log(f"done in {elapsed:.1f}s")


def warmup() -> None:
    """Synchronous wrapper around :func:`warmup_async`.

    Provided for tests and local debugging. Production boot uses
    :func:`warmup_async` inside the serving loop instead (see the module
    docstring).
    """
    asyncio.run(warmup_async())


async def _warmup_once(file_bytes: bytes, *, tier: str) -> None:
    """Drive a single-page parse against a throwaway tempdir.

    Imports `worker.parse` lazily so this module stays importable from
    pytest on a machine without MinerU installed.
    """
    from worker import parse as _parse  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="mineru-warmup-") as tmp:
        work_dir = Path(tmp)
        await _parse.run_mineru(
            file_bytes,
            basename="warmup",
            work_dir=work_dir,
            suffix="pdf",
            tier=tier,
            ocr_mode="auto",
            page_range="1",
        )
