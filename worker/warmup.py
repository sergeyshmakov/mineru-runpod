"""Eager warmup at worker boot.

Moves the ~60-100s vLLM + MinerU cold-start tax from first-request
latency to worker-boot latency. Worker boot is invisible to the caller;
the first request is not. So callers see a near-warm cold start (~6s
parse) instead of ~110s.

**Critical asyncio invariant.** vLLM's `AsyncLLMEngine` creates IPC
primitives (transports, queues) bound to the asyncio loop that owned
the warmup call. If that loop is torn down (e.g., via `asyncio.run()`
returning) and a different loop later tries to talk to the engine, the
parent's view of the engine subprocess is dead even though the
subprocess is still running. Symptom: `EngineDeadError` ~75ms into the
first real request.

To avoid this, production callers MUST use ``warmup_async()`` from
inside the same asyncio loop that will later serve requests. The
synchronous ``warmup()`` wrapper exists only for tests / local debug
where a fresh loop per call is fine because tests mock the engine.

Failure is non-fatal. A worker that can't warm up still serves
requests (just slowly on the first one, falling back to lazy load).
This is deliberate: a broken warmup must NOT prevent the worker from
booting and serving traffic.

Logging here uses plain ``print()`` instead of ``worker.logging`` —
warmup status needs to be visible regardless of how the JSON-logger
visibility investigation resolves. ``[mineru-warmup]`` prefix matches
the same channel as RunPod's own ``Started.`` / ``Finished.`` lines
which we know reaches the dashboard.
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

    Reads ``MINERU_SKIP_WARMUP`` / ``MINERU_WARMUP_BACKEND`` /
    ``MINERU_WARMUP_LANG`` from the environment. Never raises — the
    caller proceeds to serve requests whether this succeeds or not.

    **Must be called from an already-running asyncio loop** that will
    also handle subsequent requests. See module docstring for the
    asyncio-boundary rationale.
    """
    if _truthy(os.environ.get("MINERU_SKIP_WARMUP", "")):
        _log("MINERU_SKIP_WARMUP set, skipping warmup")
        return

    if not WARMUP_FIXTURE_PATH.is_file():
        # Local pytest / non-container envs won't have the fixture. Don't
        # error; just skip and let lazy load kick in on first request.
        _log(f"fixture not found at {WARMUP_FIXTURE_PATH}, skipping warmup")
        return

    backend = os.environ.get("MINERU_WARMUP_BACKEND", "vlm-auto-engine")
    lang = os.environ.get("MINERU_WARMUP_LANG", "en")
    _log(f"starting (backend={backend} lang={lang} fixture={WARMUP_FIXTURE_PATH})")
    start = time.monotonic()

    try:
        fixture_bytes = WARMUP_FIXTURE_PATH.read_bytes()
        await _warmup_once(fixture_bytes, backend=backend, lang=lang)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - start
        _log(f"failed after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
        _log("worker will continue with lazy-load fallback")
        return

    _log(f"done in {time.monotonic() - start:.1f}s")


def warmup() -> None:
    """Synchronous wrapper around :func:`warmup_async`.

    Provided for tests, local debugging, and any sync caller that knows
    it doesn't need to share an asyncio loop with downstream consumers
    of the engine. **Do not use from production worker boot** — the
    `asyncio.run()` here tears down the loop that would own vLLM's
    engine handle, causing EngineDeadError on the first real request.
    """
    asyncio.run(warmup_async())


async def _warmup_once(file_bytes: bytes, *, backend: str, lang: str) -> None:
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
            input_format="pdf",
            start_page=0,
            end_page=0,
            lang=lang,
            backend=backend,
            server_url=None,
            formula_enable=False,
            table_enable=False,
        )
