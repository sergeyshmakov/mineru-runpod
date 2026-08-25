"""Draining, restart counters, and how many jobs this worker will still take.

All of it is process state that outlives a job, which is why it is not in the
handler: a serverless worker is reused, and every number here is about the worker
rather than the request being served. The counters are read by the concurrency
modifier, so they have to be the same objects the recorder mutates -- read them
through this module, not by value.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from runpod_doc_worker.contract import degraded as _degraded
from runpod_doc_worker.obs import logging as _logging

from worker import telemetry as _telemetry

# -----------------------------------------------------------------------------
# Graceful shutdown
# -----------------------------------------------------------------------------
#
# RunPod sends SIGTERM when recycling a worker (idle timeout, refresh, manual
# stop). The SDK already drains in-flight jobs, but the user-visible signal
# tends to be "worker logs go silent." We install a breadcrumb handler + a
# shutdown event that the handler notes between phases, so the logs show
# where a job was when SIGTERM arrived.
#
# The between-phase check deliberately does NOT abort the job. After SIGTERM
# the SDK stops pulling new jobs, so anything that reaches the check was
# already accepted. Failing it would return a top-level `error`, which RunPod
# treats as terminal (FAILED, never retried) — clients saw routine scale-ins
# as permanent "worker shutting down, refusing further work" job failures.
# Draining to completion (or dying with the worker, in which case RunPod
# re-queues the job) is strictly better for the caller. Mid-parse
# cancellation is NOT possible anyway (vLLM forward pass is a blocking GPU
# call from asyncio's POV).

_shutting_down = threading.Event()


def _on_sigterm(signum: int, frame: Any) -> None:  # noqa: ARG001
    _logging.warning("sigterm received, draining current job")
    _telemetry.counter_add("refresh_total", reason="sigterm")
    _shutting_down.set()


def _note_shutdown(phase: str) -> None:
    """Log a breadcrumb if SIGTERM has been received. Called between request
    phases. Never raises — see the drain rationale in the section comment."""
    if _shutting_down.is_set():
        _logging.warning("sigterm received mid-job; continuing to drain", phase=phase)


# -----------------------------------------------------------------------------
# Cumulative refresh counters
# -----------------------------------------------------------------------------
#
# Recycle this worker after N cumulative jobs or M cumulative pages so that
# MinerU + vLLM accumulated VRAM fragmentation gets released. Opt-in via env
# vars; both default to 0 (disabled). When a threshold trips, the handler
# attaches `refresh_worker: True` to the response — RunPod's SDK then kills
# the worker after the response is sent.
#
# Pages counter only increments when the caller used a bounded slice
# (end_page >= 0). Full-document parses (end_page=-1, the default) contribute
# 1 to jobs but 0 to pages — documented in scaling.mdx so operators know to
# use the jobs counter for unbounded workloads.

_jobs_processed = 0


_pages_processed_total = 0


_refresh_lock = threading.Lock()


def _refresh_thresholds() -> tuple[int, int]:
    """Read thresholds from env on every job so they can be tuned without redeploy."""
    try:
        jobs = int(os.environ.get("REFRESH_WORKER_AFTER_JOBS", "0"))
    except ValueError:
        jobs = 0
    try:
        pages = int(os.environ.get("REFRESH_WORKER_AFTER_PAGES", "0"))
    except ValueError:
        pages = 0
    return max(0, jobs), max(0, pages)


def _record_job(pages: int) -> str | None:
    """Bump counters; return the refresh reason if a threshold was crossed.

    ``pages`` is the requested slice size (positive) or 0 for unbounded /
    unknown — only the jobs counter increments in the unbounded case.
    Returns ``"jobs_threshold"`` or ``"pages_threshold"`` when a recycle
    should be signaled, ``None`` otherwise. Jobs is checked first so if
    both trip on the same job, jobs wins (deterministic, matches the
    order the env vars are documented in).
    """
    global _jobs_processed, _pages_processed_total
    with _refresh_lock:
        _jobs_processed += 1
        if pages > 0:
            _pages_processed_total += pages
        jobs_th, pages_th = _refresh_thresholds()
        if jobs_th > 0 and _jobs_processed >= jobs_th:
            return "jobs_threshold"
        if pages_th > 0 and _pages_processed_total >= pages_th:
            return "pages_threshold"
        return None


def _record_degradation(lost: _degraded.Report) -> None:
    """Count what a successful response could not carry.

    The response already names the affected artifacts, per document. This is
    the other half: an operator watching a fleet needs the rate, because a
    response nobody reads back is not a signal. Labelled by reason and by
    artifact — both bounded, so the series count is too.

    `items` stops at the harness's cap while `count` stays true, so the
    remainder is added under its own label rather than dropped. A metric that
    quietly undercounts the pathological case is the failure this whole field
    exists to avoid.
    """
    reported = lost.entry()
    if reported is None:
        return
    for item in reported["items"]:
        _telemetry.counter_add(
            "degraded_total",
            reason=item["reason"],
            # None means an archive member, which no manifest key claims.
            artifact=item["artifact"] or "archive",
        )
    unlisted = reported["count"] - len(reported["items"])
    if unlisted > 0:
        _telemetry.counter_add(
            "degraded_total", unlisted, reason="unlisted", artifact="unlisted",
        )


# -----------------------------------------------------------------------------
# Concurrency
# -----------------------------------------------------------------------------
#
# vLLM pre-allocates a large KV cache and isn't safe to drive from concurrent
# aio_do_parse calls on smaller GPUs. Default 1 is safe on every supported
# GPU type. Operators with ≥24 GB GPUs may raise via MINERU_MAX_CONCURRENCY.
# See guides/scaling.mdx for the VRAM math.

def _concurrency_modifier(current_concurrency: int) -> int:  # noqa: ARG001
    try:
        return max(1, int(os.environ.get("MINERU_MAX_CONCURRENCY", "1")))
    except ValueError:
        return 1
