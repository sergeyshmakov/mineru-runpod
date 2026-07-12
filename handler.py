"""RunPod serverless entry point for the MinerU worker.

The pieces this orchestrates live in the worker/ package:
  worker.schema   — input validation
  worker.io       — fetch raw bytes from URL / b64 / volume + format detection
  worker.parse    — MinerU lazy import + async parse call
  worker.package  — tarball / inline / s3 response packaging
  worker.debug    — GPU info, model dir, /runpod-volume probe
  worker.logging  — JSON / text structured logging

The module surface (``handler.MAX_INLINE_FILE_MB``, ``handler._detect_format``,
``handler._validate_input``, ``handler._package_tarball``, etc.) is preserved
for tests/back-compat — see the re-exports near the bottom of this file.
"""

from __future__ import annotations

import os
import signal
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import runpod

from worker import debug as _debug
from worker import io as _io
from worker import logging as _logging
from worker import package as _package
from worker import parse as _parse
from worker import schema as _schema
from worker import telemetry as _telemetry


# -----------------------------------------------------------------------------
# Graceful shutdown
# -----------------------------------------------------------------------------
#
# RunPod sends SIGTERM when recycling a worker (idle timeout, refresh, manual
# stop). The SDK already drains in-flight jobs, but the user-visible signal
# tends to be "worker logs go silent." We install a breadcrumb handler + a
# shutdown event that the handler checks between phases — so a request that's
# between fetch_input and parse can bail out instead of consuming GPU time
# that's about to be killed anyway. Mid-parse cancellation is NOT possible
# (vLLM forward pass is a blocking GPU call from asyncio's POV).

_shutting_down = threading.Event()


def _on_sigterm(signum: int, frame: Any) -> None:  # noqa: ARG001
    _logging.warning("sigterm received, draining current job")
    _telemetry.counter_add("refresh_total", reason="sigterm")
    _shutting_down.set()


# Install at module init. RunPod's SDK may install its own handler when
# runpod.serverless.start() runs; in that case our handler is replaced and
# this becomes a no-op breadcrumb that never fires. Acceptable — failure is
# silent and the rest of the worker is unaffected.
try:
    signal.signal(signal.SIGTERM, _on_sigterm)
except (ValueError, OSError) as e:  # pragma: no cover — non-main-thread case
    _logging.warning("could not install sigterm handler", error=repr(e))


def _check_shutdown() -> None:
    """Raise if SIGTERM has been received. Called between request phases."""
    if _shutting_down.is_set():
        raise RuntimeError("worker shutting down, refusing further work")


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


# -----------------------------------------------------------------------------
# Progress + debug envelope
# -----------------------------------------------------------------------------

def _maybe_progress(job: dict, data: dict) -> None:
    """Best-effort progress update. Tests / sync clients without a job id
    shouldn't fail just because we tried to surface progress."""
    try:
        runpod.serverless.progress_update(job, data)
    except Exception as e:  # noqa: BLE001
        _logging.debug("progress_update failed", error=repr(e))


def _build_debug(phase_ms: dict[str, int], gpu_info: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "gpu": gpu_info,
        "model_dir": _debug.find_model_dir(),
        "phase_ms": phase_ms,
        **extra,
    }


def _measure_output_bytes(response: dict[str, Any], transport: str) -> int:
    """Approximate bytes shipped to the caller, for the egress metrics.

    Reads from ``response["results"][0]`` — the per-file entry — because the
    payload-carrying keys (``tarball_b64``, ``markdown``, ``images``,
    ``bucket_bytes``) live there in the unified response shape.

    Per-transport sizing:
      * tarball_b64 — the b64 string IS the payload; len() is exact.
      * inline      — markdown text + image bytes dominate the JSON-encoded
                      response; sum those (json overhead for content_list/
                      middle is ignored). Cheap and within ~10% of the true
                      response size on real documents.
      * s3          — package_s3 records the uploaded tarball size in
                      `bucket_bytes`; the worker shipped exactly that.
    Returns 0 when the response shape doesn't include the expected fields
    (e.g. an empty parse or a failure response with no `results`) so the
    histogram doesn't get a misleading zero sample for "no output produced."
    """
    results = response.get("results") or []
    if not results:
        return 0
    entry = results[0] if isinstance(results[0], dict) else {}
    if transport == "tarball_b64":
        tb = entry.get("tarball_b64")
        return len(tb) if isinstance(tb, str) else 0
    if transport == "s3":
        return int(entry.get("bucket_bytes") or 0)
    if transport == "inline":
        md = entry.get("markdown") or ""
        images = entry.get("images") or {}
        md_bytes = len(md.encode("utf-8")) if isinstance(md, str) else 0
        image_bytes = sum(
            len(v) for v in images.values() if isinstance(v, str)
        ) if isinstance(images, dict) else 0
        return md_bytes + image_bytes
    return 0


async def _handle_probe(started: float, gpu_info: dict[str, Any], phase_ms: dict[str, int]) -> dict[str, Any]:
    _logging.info("probe job: dumping filesystem layout")
    return {
        "ok": True,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "mineru_version": _parse.MINERU_VERSION,
        "mineru_available": _parse.MINERU_AVAILABLE,
        "probe": _debug.probe_filesystem(),
        "debug": _build_debug(phase_ms, gpu_info),
    }


async def _handle_parse(
    job: dict,
    cleaned: dict[str, Any],
    started: float,
    gpu_info: dict[str, Any],
    phase_ms: dict[str, int],
) -> dict[str, Any]:
    # rp_validator's strict typing forces end_page to be an int; translate
    # the -1 sentinel back to None so MinerU treats it as "until end of doc".
    end_page_val = cleaned["end_page"]
    end_page = None if end_page_val is None or end_page_val < 0 else int(end_page_val)
    backend = cleaned["backend"]

    _logging.info(
        "starting job",
        backend=backend,
        lang=cleaned["lang"],
        start_page=cleaned["start_page"],
        end_page=end_page,
        gpu_name=gpu_info.get("name"),
        compute_capability=gpu_info.get("compute_capability"),
    )

    _check_shutdown()
    _maybe_progress(job, {"phase": "fetching_input"})
    t = time.monotonic()
    with _telemetry.span("mineru.fetch_input", phase="fetch_input"):
        file_bytes, source = await _io.resolve_input_bytes(cleaned)
        _telemetry.set_span_attrs(**{
            "mineru.source": source,
            "mineru.bytes_in": len(file_bytes),
        })
    fetch_seconds = time.monotonic() - t
    phase_ms["fetch_input"] = int(fetch_seconds * 1000)
    _telemetry.histogram_record("phase_duration", fetch_seconds, phase="fetch_input")
    _telemetry.counter_add("bytes_in_total", len(file_bytes), source=source)
    _telemetry.histogram_record("input_size_bytes", float(len(file_bytes)))

    input_format = _io.detect_format(file_bytes)
    if input_format == "unknown":
        raise ValueError(
            "input bytes do not match any supported format "
            "(PDF, PNG/JPEG/GIF/BMP/TIFF/WebP image, or DOCX/PPTX/XLSX). "
            "Check that file_b64 was base64-encoded correctly and that "
            "file_url returned the file body (not an error page)."
        )

    _check_shutdown()
    _maybe_progress(job, {
        "phase": "parsing",
        "input_bytes": len(file_bytes),
        "input_format": input_format,
        "start_page": cleaned["start_page"],
        "end_page": end_page,
    })

    with tempfile.TemporaryDirectory(prefix="mineru-job-") as tmp:
        work_dir = Path(tmp)
        t = time.monotonic()
        with _telemetry.span(
            "mineru.parse",
            phase="parse",
            **{
                "mineru.backend": backend,
                "mineru.input_format": input_format,
                "mineru.start_page": cleaned["start_page"],
                "mineru.end_page": end_page if end_page is not None else -1,
            },
        ):
            output_dir = await _parse.run_mineru(
                file_bytes,
                basename=cleaned["basename"],
                work_dir=work_dir,
                input_format=input_format,
                start_page=cleaned["start_page"],
                end_page=end_page,
                lang=cleaned["lang"],
                backend=backend,
                server_url=cleaned.get("server_url"),
                formula_enable=cleaned["formula_enable"],
                table_enable=cleaned["table_enable"],
                effort=cleaned["effort"],
            )
        parse_seconds = time.monotonic() - t
        phase_ms["mineru_parse"] = int(parse_seconds * 1000)
        _telemetry.histogram_record("phase_duration", parse_seconds, phase="parse")

        _check_shutdown()
        # No progress_update here: the SDK sends progress from a background
        # thread to the same endpoint as the final result, and packaging
        # finishes in milliseconds — an update this close to completion can
        # land after the COMPLETED post and strand the job IN_PROGRESS.

        t = time.monotonic()
        # `pages_requested` reflects the slice the caller asked for, NOT the
        # number MinerU actually produced (MinerU may emit fewer if the doc
        # is shorter than end_page). -1 == "full document".
        pages_requested = (
            (end_page - cleaned["start_page"] + 1) if end_page is not None else -1
        )
        transport = cleaned["transport"]
        formats = cleaned["formats"]
        with _telemetry.span(
            "mineru.package",
            phase="package",
            **{"mineru.transport": transport},
        ):
            entry = _package.package_results_entry(
                transport=transport,
                formats=formats,
                output_dir=output_dir,
                basename=cleaned["basename"],
                source=source,
                pages_requested=pages_requested,
                archive_format=cleaned["archive_format"],
            )
        response: dict[str, Any] = {
            "ok": True,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "mineru_version": _parse.MINERU_VERSION,
            "results": [entry],
        }
        package_seconds = time.monotonic() - t
        phase_ms["package"] = int(package_seconds * 1000)
        _telemetry.histogram_record("phase_duration", package_seconds, phase="package")

        # Egress accounting per transport. Each path knows its own payload
        # size: the base64 tarball string for tarball_b64, the markdown +
        # images byte sum for inline (best estimate without re-serializing
        # the whole response), and the uploaded tarball size that
        # package_s3 records in the bucket_bytes response field.
        out_bytes = _measure_output_bytes(response, transport)
        if out_bytes > 0:
            _telemetry.counter_add(
                "bytes_out_total", out_bytes, transport=transport,
            )
            _telemetry.histogram_record(
                "output_size_bytes", float(out_bytes), transport=transport,
            )

        response["debug"] = _build_debug(
            phase_ms, gpu_info, backend=backend, input_format=input_format
        )

        # Cumulative refresh check — outside the lock so logging happens
        # after the counter bump. Bounded slices contribute their page
        # count; unbounded ones contribute 0 to the pages tally (jobs
        # still +1). The returned reason ("jobs_threshold" /
        # "pages_threshold") is forwarded to the refresh_total counter.
        bumped_pages = pages_requested if pages_requested > 0 else 0
        refresh_reason = _record_job(bumped_pages)
        if refresh_reason is not None:
            response["refresh_worker"] = True
            _telemetry.counter_add("refresh_total", reason=refresh_reason)
            _logging.info(
                "refresh threshold crossed; signaling worker recycle",
                reason=refresh_reason,
                jobs_processed=_jobs_processed,
                pages_processed_total=_pages_processed_total,
            )

        # Top-level metrics for the just-completed job. Labels match the
        # catalog in the observability guide. Histograms use the raw
        # monotonic elapsed (sub-10ms precision); the rounded
        # `elapsed_seconds` is for the human-readable response only.
        job_seconds = time.monotonic() - started
        _telemetry.counter_add(
            "jobs_total", status="ok", backend=backend, input_format=input_format,
        )
        if bumped_pages > 0:
            _telemetry.counter_add("pages_total", bumped_pages, backend=backend)
        _telemetry.histogram_record(
            "job_duration", job_seconds,
            backend=backend, input_format=input_format,
        )
        if bumped_pages > 0 and job_seconds > 0:
            _telemetry.histogram_record(
                "pages_per_second", bumped_pages / job_seconds, backend=backend,
            )

        _logging.info(
            "done",
            elapsed_seconds=response["elapsed_seconds"],
            phase_ms=phase_ms,
            model_dir=response["debug"]["model_dir"],
            refresh_worker=response.get("refresh_worker", False),
        )
        return response


async def handler(job: dict) -> dict:
    started = time.monotonic()
    phase_ms: dict[str, int] = {}
    gpu_info = _debug.collect_gpu_info()
    # Pin the job id into the logging contextvar so every line emitted
    # from this request carries `job_id` for correlation (per RunPod's
    # write-logs guidance). Falls back to "<unknown>" if RunPod doesn't
    # surface an id (sync clients without a queued job).
    job_id = job.get("id") or "<unknown>"
    _logging.job_id_var.set(job_id)
    with _telemetry.span("mineru.job", **{"runpod.job_id": job_id}):
        try:
            raw_input = job.get("input") or {}
            # Probe mode bypasses schema validation: a probe has no file source
            # and the operator may want to send arbitrary debug flags through.
            if raw_input.get("probe") is True:
                return await _handle_probe(started, gpu_info, phase_ms)

            cleaned = _schema.validate_input(raw_input)
            return await _handle_parse(job, cleaned, started, gpu_info, phase_ms)

        except Exception as exc:  # noqa: BLE001
            # Top-level `error` key tells RunPod to mark this job FAILED.
            # Keep `ok=false` and the structured details so clients see context.
            _telemetry.record_exception(exc)
            _telemetry.counter_add(
                "errors_total", type=type(exc).__name__, phase="handler",
            )
            _telemetry.counter_add("jobs_total", status="error")
            _logging.error(
                "job failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
                phase_ms=phase_ms,
            )
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "ok": False,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "mineru_version": _parse.MINERU_VERSION,
                "traceback": traceback.format_exc(limit=5),
                "debug": _build_debug(phase_ms, gpu_info),
            }


# -----------------------------------------------------------------------------
# Back-compat surface for tests and any out-of-tree callers that imported
# helpers from this module directly. New code should import from worker.*.
# -----------------------------------------------------------------------------

MAX_INLINE_FILE_MB = _io.MAX_INLINE_FILE_MB
MINERU_VERSION = _parse.MINERU_VERSION
_MINERU_AVAILABLE = _parse.MINERU_AVAILABLE

_resolve_input_bytes = _io.resolve_input_bytes
_detect_format = _io.detect_format
_validate_input = _schema.validate_input
_package_tarball = _package.package_tarball
_package_inline = _package.package_inline
_package_s3 = _package.package_s3
_build_tarball_bytes = _package._build_tarball_bytes
_build_zip_bytes = _package._build_zip_bytes
_run_mineru = _parse.run_mineru
_collect_gpu_info = _debug.collect_gpu_info
_find_model_dir = _debug.find_model_dir
_probe_filesystem = _debug.probe_filesystem


def _bootstrap_main() -> None:
    """Production worker bootstrap.

    Replicates ``runpod.serverless.worker.run_worker()`` but folds the
    eager warmup into the same asyncio loop that JobScaler.run() will
    use. The standard ``runpod.serverless.start()`` call chain creates
    a fresh event loop *inside* JobScaler.start() — if our warmup runs
    before that and creates its own loop via ``asyncio.run()``, vLLM's
    AsyncLLMEngine handle is bound to the warmup loop. When the
    JobScaler's loop starts and the first request tries to use the
    engine, the parent's view of the engine subprocess is dead
    (EngineDeadError ~75ms in). Composing both phases under one
    ``asyncio.run()`` keeps the engine handle alive across the
    warmup → serve transition.

    NOTE: This reaches into ``runpod.serverless.modules.rp_scale`` and
    ``rp_ping`` — undocumented internals of the runpod-python SDK.
    pyproject pins ``runpod>=1.7`` (worker SDK version 1.9.x at time
    of writing). A test in tests/test_runpod_internals.py asserts the
    internals we depend on still exist and have the expected shape; if
    the SDK refactors, that test fails fast instead of breaking
    production silently.
    """
    import asyncio  # noqa: PLC0415
    from runpod.serverless.modules import rp_ping, rp_scale  # noqa: PLC0415
    from runpod.serverless.modules.rp_fitness import run_fitness_checks  # noqa: PLC0415
    from worker import warmup as _warmup  # noqa: PLC0415

    config: dict[str, Any] = {
        "handler": handler,
        "concurrency_modifier": _concurrency_modifier,
        # JobScaler doesn't read rp_args directly, but some downstream
        # paths in the SDK may. Empty dict is safe; the SDK's defaults
        # apply for anything it does access.
        "rp_args": {},
    }

    async def _bootstrap() -> None:
        # 0. Initialize optional OpenTelemetry export BEFORE warmup so
        # the warmup span (and any spans/log mirrors during fitness
        # checks) are captured. No-op when OTEL_EXPORTER_OTLP_ENDPOINT
        # is unset. Init is sync and runs once per process; the
        # batch processors below it are background threads, not async
        # tasks, so they do not interact with vLLM's event loop.
        _telemetry.init_telemetry()

        # Hand worker-state getters to the telemetry module so its
        # observable gauges don't have to import ``handler`` (avoids
        # an import cycle and keeps the dependency arrow pointing
        # from the entry-point module into telemetry, not the
        # reverse). Safe to call when telemetry is disabled — the
        # getters are simply unused.
        _telemetry.register_worker_gauges(
            jobs_since_boot=lambda: _jobs_processed,
            pages_since_boot=lambda: _pages_processed_total,
        )

        # 1. Fitness checks (runpod-python runs these synchronously
        # before serving; we run them async in the same loop).
        await run_fitness_checks()

        # 2. Eager warmup. Same loop as the serve loop below — see
        # worker/warmup.py docstring for the asyncio invariant.
        await _warmup.warmup_async()

        # 3. Heartbeat is a background thread, not async. Start it
        # after warmup so the control plane doesn't see us "alive"
        # before we can actually serve.
        rp_ping.Heartbeat().start_ping()

        # 4. Install combined signal handlers: our breadcrumb + the
        # scaler's graceful-drain logic. Both must run on SIGTERM /
        # SIGINT; signal.signal() only allows one handler so we wrap.
        scaler = rp_scale.JobScaler(config)

        def _combined_shutdown(signum: int, frame: Any) -> None:
            _on_sigterm(signum, frame)
            try:
                scaler.handle_shutdown(signum, frame)
            except Exception as e:  # noqa: BLE001
                _logging.warning("scaler.handle_shutdown raised", error=repr(e))

        try:
            signal.signal(signal.SIGTERM, _combined_shutdown)
            signal.signal(signal.SIGINT, _combined_shutdown)
        except (ValueError, OSError) as e:
            _logging.warning("could not install runtime signal handlers", error=repr(e))

        # 5. Serve requests on this same loop. JobScaler.run() blocks
        # until shutdown is requested.
        try:
            await scaler.run()
        finally:
            # Best-effort flush of OTel buffers so the last batch of
            # spans/logs/metrics escapes before the process exits.
            # No-op when telemetry is disabled.
            _telemetry.shutdown()

    asyncio.run(_bootstrap())


if __name__ == "__main__":
    # Local-test mode (RUNPOD_WEBHOOK_GET_JOB unset, or --test_input on
    # the CLI) — fall back to runpod.serverless.start() which routes to
    # rp_local. Warmup doesn't apply in local mode (no real worker
    # lifecycle), and rp_local has its own asyncio.run().
    if os.environ.get("RUNPOD_WEBHOOK_GET_JOB") is None:
        runpod.serverless.start({
            "handler": handler,
            "concurrency_modifier": _concurrency_modifier,
        })
    else:
        _bootstrap_main()
