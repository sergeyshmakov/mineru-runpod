"""The metrics: what exists, and how a caller adds to one.

Unknown metric names are reported once and dropped rather than raised, because a
mistyped counter must not be the thing that fails a finished parse. The two
observable gauges read through getters the worker registers, so they stay correct
across a restart without this module knowing what a job is.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any


from worker.telemetry import gpu, state


def register_worker_gauges(
    jobs_since_boot: Callable[[], int],
    pages_since_boot: Callable[[], int],
) -> None:
    """Tell the telemetry module how to read worker-state counters.

    Called from ``handler._bootstrap_main()`` after ``init_telemetry()``.
    Without this, the ``mineru.worker.jobs_since_boot`` and
    ``mineru.worker.pages_since_boot`` gauges report 0. Safe to call
    even when telemetry is disabled — the getters are simply not used.
    """
    state._jobs_getter = jobs_since_boot
    state._pages_getter = pages_since_boot


def _build_instruments(meter: Any) -> None:
    state._metrics["jobs_total"] = meter.create_counter(
        "mineru.jobs.total", description="Jobs processed", unit="1",
    )
    state._metrics["pages_total"] = meter.create_counter(
        "mineru.pages.total", description="Pages processed", unit="1",
    )
    state._metrics["bytes_in_total"] = meter.create_counter(
        "mineru.bytes_in.total", description="Input bytes received", unit="By",
    )
    state._metrics["bytes_out_total"] = meter.create_counter(
        "mineru.bytes_out.total", description="Output bytes sent", unit="By",
    )
    state._metrics["errors_total"] = meter.create_counter(
        "mineru.errors.total", description="Errors by phase and type", unit="1",
    )
    state._metrics["job_duration"] = meter.create_histogram(
        "mineru.job.duration", description="End-to-end job duration", unit="s",
    )
    state._metrics["phase_duration"] = meter.create_histogram(
        "mineru.phase.duration", description="Per-phase duration", unit="s",
    )
    state._metrics["pages_per_second"] = meter.create_histogram(
        "mineru.pages_per_second", description="Throughput", unit="1",
    )
    state._metrics["input_size_bytes"] = meter.create_histogram(
        "mineru.input.size_bytes", description="Input size distribution", unit="By",
    )
    state._metrics["output_size_bytes"] = meter.create_histogram(
        "mineru.output.size_bytes", description="Output size distribution", unit="By",
    )
    state._metrics["cold_starts_total"] = meter.create_counter(
        "mineru.worker.cold_starts.total", description="Worker process starts", unit="1",
    )
    state._metrics["warmup_duration"] = meter.create_histogram(
        "mineru.worker.warmup.duration", description="Boot-time warmup duration", unit="s",
    )
    state._metrics["refresh_total"] = meter.create_counter(
        "mineru.worker.refresh.total", description="Worker recycles", unit="1",
    )
    state._metrics["degraded_total"] = meter.create_counter(
        "mineru.degraded.total",
        description="Artifacts a successful response could not carry",
        unit="1",
    )
    meter.create_observable_gauge(
        "mineru.worker.jobs_since_boot",
        callbacks=[_observe_jobs_since_boot],
        description="Jobs handled since this process started", unit="1",
    )
    meter.create_observable_gauge(
        "mineru.worker.pages_since_boot",
        callbacks=[_observe_pages_since_boot],
        description="Pages handled since this process started", unit="1",
    )
    meter.create_observable_gauge(
        "mineru.gpu.memory_used_bytes",
        callbacks=[gpu._observe_gpu_mem_used],
        description="GPU memory in use", unit="By",
    )
    meter.create_observable_gauge(
        "mineru.gpu.memory_total_bytes",
        callbacks=[gpu._observe_gpu_mem_total],
        description="GPU memory total", unit="By",
    )
    meter.create_observable_gauge(
        "mineru.gpu.utilization_percent",
        callbacks=[gpu._observe_gpu_util],
        description="GPU SM utilization", unit="%",
    )


def _observe_jobs_since_boot(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    if state._jobs_getter is None:
        return
    try:
        yield Observation(int(state._jobs_getter()))
    except Exception:  # noqa: BLE001
        return


def _observe_pages_since_boot(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    if state._pages_getter is None:
        return
    try:
        yield Observation(int(state._pages_getter()))
    except Exception:  # noqa: BLE001
        return


def counter_add(name: str, value: int = 1, **attrs: Any) -> None:
    """Increment a counter from the catalog. Warns once on unknown name
    when telemetry is enabled — silent when disabled (the whole API is
    no-op then, so a typo here doesn't deserve noise)."""
    inst = state._metrics.get(name)
    if inst is None:
        _warn_unknown_metric(name)
        return
    try:
        inst.add(value, attributes=attrs)
    except Exception:  # noqa: BLE001
        pass


def histogram_record(name: str, value: float, **attrs: Any) -> None:
    """Record a histogram observation. Warns once on unknown name."""
    inst = state._metrics.get(name)
    if inst is None:
        _warn_unknown_metric(name)
        return
    try:
        inst.record(value, attributes=attrs)
    except Exception:  # noqa: BLE001
        pass


def _warn_unknown_metric(name: str) -> None:
    """One-shot stdout warning so a typo in a metric name doesn't no-op
    forever in silence. Only fires when telemetry is enabled; on the
    no-op path the whole module is dormant and a stray name is harmless."""
    if not state._enabled:
        return
    if name in state._warned_unknown_names:
        return
    state._warned_unknown_names.add(name)
    print(
        f"[mineru-telemetry] unknown metric name {name!r} — "
        f"check worker/telemetry.py _build_instruments",
        flush=True,
    )
