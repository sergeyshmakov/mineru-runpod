"""Optional OpenTelemetry export for the worker.

Activates ONLY when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set in the
environment. If unset (the template's default), every function in this
module is a fast no-op and the OTel SDK is never imported — keeping
the cold-start budget clean for forks that don't care about telemetry.

Logs export is **additive**, not replacement. The direct-print stdout
JSON in the harness's logging module continues to fire so RunPod's dashboard
remains the source of truth. When enabled, this module mirrors each
log emission to an OTLP/HTTP logs exporter for downstream sinks
(Axiom, Honeycomb, Tempo, etc.).

The OTel-logs path here is **NOT** the Python ``logging`` module. We
emit log records directly through the OTel logs SDK
(:meth:`Logger.emit`), bypassing the ``LoggingHandler`` adapter
entirely. The runpod SDK silences Python's root logger during
``serverless.start()``, so reintroducing ``logging.Logger`` here would
re-create the disappearing-logs problem the harness's direct-print
logging already solved.

Init order matters: :func:`init_telemetry` MUST be called from
``handler._bootstrap_main()`` BEFORE ``warmup_async()`` so warmup
spans are captured. It must NOT spin up its own asyncio loop or
threads that own an engine handle — the metric reader's background
thread is safe (does not touch vLLM).

Worker-state gauges (jobs/pages since boot) are NOT pulled by
reaching into ``handler``. Instead, ``handler`` calls
:func:`register_worker_gauges` to provide getters, keeping the
dependency arrow pointed from the entry-point module into the
telemetry module (not the reverse).
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import Any, Callable, Iterable, Iterator


# Module-level state. Initialized at most once per process by init_telemetry().
_initialized = False
_enabled = False
_tracer: Any = None
_logger: Any = None  # OTel SDK Logger (NOT Python logging.Logger)
_logger_provider: Any = None
_meter: Any = None
_metrics: dict[str, Any] = {}
_resource_attrs: dict[str, str] = {}
_lock = threading.Lock()

# Hoisted at _enable() time; saves a per-call import + dict lookup
# from emit_log / set_span_attrs / record_exception. None until
# telemetry activates; cleared back to None by _reset_for_tests.
_trace_api: Any = None
_severity_number: Any = None
_status_cls: Any = None
_status_code: Any = None

# Worker-state gauge providers registered by the host module (handler.py).
# Avoids reaching back into ``handler`` from within callback closures.
_jobs_getter: Callable[[], int] | None = None
_pages_getter: Callable[[], int] | None = None

# One-shot warning set so a typo in a counter/histogram name surfaces
# once instead of silently no-opping forever.
_warned_unknown_names: set[str] = set()


def is_enabled() -> bool:
    """Whether OTel export is active. Cheap, safe to call from anywhere."""
    return _enabled


def init_telemetry() -> bool:
    """Initialize OTel if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.

    Returns ``True`` if telemetry was activated, ``False`` otherwise
    (env var unset, SDK import failed, or exporter setup raised).
    Idempotent — subsequent calls return the initial decision without
    re-running setup. Never raises: a misconfigured endpoint must not
    block worker boot.
    """
    global _initialized, _enabled
    with _lock:
        if _initialized:
            return _enabled
        _initialized = True

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            return False

        try:
            _enable()
            _enabled = True
        except Exception as exc:  # noqa: BLE001
            # Stdout breadcrumb on the known-good channel — same pattern as
            # worker/warmup.py. Don't use the harness's logging here: it calls
            # back into us through the log mirror, which would recurse during
            # init if a log line fired before _enabled is set.
            print(
                f"[mineru-telemetry] init failed, continuing without OTel: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            _enabled = False
        return _enabled


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
    global _jobs_getter, _pages_getter
    _jobs_getter = jobs_since_boot
    _pages_getter = pages_since_boot


# -----------------------------------------------------------------------------
# Activation (only runs when OTEL_EXPORTER_OTLP_ENDPOINT is set)
# -----------------------------------------------------------------------------

def _enable() -> None:
    """Configure OTel SDK providers + exporters. Called once by init_telemetry()."""
    global _tracer, _logger, _logger_provider, _meter
    global _trace_api, _severity_number, _status_cls, _status_code

    from opentelemetry import metrics, trace  # noqa: PLC0415
    from opentelemetry._logs import SeverityNumber, set_logger_provider  # noqa: PLC0415
    from opentelemetry.exporter.otlp.proto.http._log_exporter import (  # noqa: PLC0415
        OTLPLogExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: PLC0415
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
        OTLPSpanExporter,
    )
    from opentelemetry.sdk._logs import LoggerProvider  # noqa: PLC0415
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor  # noqa: PLC0415
    from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
    from opentelemetry.metrics import Histogram as _ApiHistogram  # noqa: PLC0415
    from opentelemetry.sdk.metrics.export import (  # noqa: PLC0415
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.metrics.view import (  # noqa: PLC0415
        ExponentialBucketHistogramAggregation,
        View,
    )
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415
    from opentelemetry.trace import Status, StatusCode  # noqa: PLC0415

    attrs = _build_resource_attrs()
    _resource_attrs.clear()
    _resource_attrs.update({k: str(v) for k, v in attrs.items()})
    resource = Resource.create(attrs)

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(), schedule_delay_millis=500)
    )
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer("mineru-worker")

    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(), schedule_delay_millis=500)
    )
    set_logger_provider(_logger_provider)
    _logger = _logger_provider.get_logger("mineru-worker")

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(), export_interval_millis=10000,
    )
    # Prefer base-2 exponential histograms over the SDK default of
    # explicit-bucket. Latency metrics span ms→minutes (job_duration,
    # warmup_duration) and byte-size metrics span KB→hundreds of MB
    # (input_size_bytes, output_size_bytes) — exponential aggregation
    # gives consistent resolution across the whole range without
    # tuning bucket boundaries per metric. Defaults: 160 buckets,
    # max_scale 20 (very high resolution at small values, automatic
    # downscale on tail samples). Modern OTLP backends (Axiom,
    # Honeycomb, Grafana, Datadog) all accept exponential histograms.
    histogram_view = View(
        instrument_type=_ApiHistogram,
        aggregation=ExponentialBucketHistogramAggregation(),
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
        views=[histogram_view],
    )
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter("mineru-worker")
    _build_instruments(_meter)

    # Cache OTel symbols accessed on every emit so we skip the lazy
    # import on the hot path. The SDK is already in sys.modules at
    # this point; this just hoists the per-call dict lookups.
    _trace_api = trace
    _severity_number = SeverityNumber
    _status_cls = Status
    _status_code = StatusCode

    # First metric the world sees from this worker — useful for
    # cold-start rate dashboards.
    _metrics["cold_starts_total"].add(1)


def _build_resource_attrs() -> dict[str, Any]:
    """Return resource attributes for every signal. Pure — no side effects."""
    attrs: dict[str, Any] = {
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "mineru-runpod"),
    }
    try:
        from worker import parse as _parse  # noqa: PLC0415
        if _parse.MINERU_VERSION:
            attrs["mineru.version"] = _parse.MINERU_VERSION
    except Exception:  # noqa: BLE001 — module may not import in test contexts
        pass
    for src_env, attr_name in [
        ("RUNPOD_ENDPOINT_ID", "runpod.endpoint_id"),
        ("RUNPOD_POD_ID", "runpod.pod_id"),
        ("RUNPOD_GPU_TYPE", "runpod.gpu_type"),
        ("RUNPOD_GPU_COUNT", "runpod.gpu_count"),
    ]:
        v = os.environ.get(src_env)
        if v:
            attrs[attr_name] = v
    return attrs


# -----------------------------------------------------------------------------
# Metric instrument catalog. See the metric table in the observability guide.
# -----------------------------------------------------------------------------

def _build_instruments(meter: Any) -> None:
    _metrics["jobs_total"] = meter.create_counter(
        "mineru.jobs.total", description="Jobs processed", unit="1",
    )
    _metrics["pages_total"] = meter.create_counter(
        "mineru.pages.total", description="Pages processed", unit="1",
    )
    _metrics["bytes_in_total"] = meter.create_counter(
        "mineru.bytes_in.total", description="Input bytes received", unit="By",
    )
    _metrics["bytes_out_total"] = meter.create_counter(
        "mineru.bytes_out.total", description="Output bytes sent", unit="By",
    )
    _metrics["errors_total"] = meter.create_counter(
        "mineru.errors.total", description="Errors by phase and type", unit="1",
    )
    _metrics["job_duration"] = meter.create_histogram(
        "mineru.job.duration", description="End-to-end job duration", unit="s",
    )
    _metrics["phase_duration"] = meter.create_histogram(
        "mineru.phase.duration", description="Per-phase duration", unit="s",
    )
    _metrics["pages_per_second"] = meter.create_histogram(
        "mineru.pages_per_second", description="Throughput", unit="1",
    )
    _metrics["input_size_bytes"] = meter.create_histogram(
        "mineru.input.size_bytes", description="Input size distribution", unit="By",
    )
    _metrics["output_size_bytes"] = meter.create_histogram(
        "mineru.output.size_bytes", description="Output size distribution", unit="By",
    )
    _metrics["cold_starts_total"] = meter.create_counter(
        "mineru.worker.cold_starts.total", description="Worker process starts", unit="1",
    )
    _metrics["warmup_duration"] = meter.create_histogram(
        "mineru.worker.warmup.duration", description="Boot-time warmup duration", unit="s",
    )
    _metrics["refresh_total"] = meter.create_counter(
        "mineru.worker.refresh.total", description="Worker recycles", unit="1",
    )
    _metrics["degraded_total"] = meter.create_counter(
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
        callbacks=[_observe_gpu_mem_used],
        description="GPU memory in use", unit="By",
    )
    meter.create_observable_gauge(
        "mineru.gpu.memory_total_bytes",
        callbacks=[_observe_gpu_mem_total],
        description="GPU memory total", unit="By",
    )
    meter.create_observable_gauge(
        "mineru.gpu.utilization_percent",
        callbacks=[_observe_gpu_util],
        description="GPU SM utilization", unit="%",
    )


# -----------------------------------------------------------------------------
# Observable gauge callbacks. OTel calls these on every metric export tick.
# All callbacks must be cheap, side-effect-free, and tolerant of missing deps
# (pynvml may not be installed on the host where pytest runs).
# -----------------------------------------------------------------------------

def _observe_jobs_since_boot(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    if _jobs_getter is None:
        return
    try:
        yield Observation(int(_jobs_getter()))
    except Exception:  # noqa: BLE001
        return


def _observe_pages_since_boot(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    if _pages_getter is None:
        return
    try:
        yield Observation(int(_pages_getter()))
    except Exception:  # noqa: BLE001
        return


# pynvml needs to be imported and initialized exactly once per process.
# The init has a measurable cost (~30 ms) so we defer it until first use.
# We also cache the device handle list — the count and per-index handles
# don't change after nvmlInit, so re-querying on every export tick wastes
# work for no benefit.
_nvml: Any = None
_nvml_init_attempted = False
_nvml_handles: list[tuple[int, Any]] = []


def _get_nvml() -> Any:
    global _nvml, _nvml_init_attempted
    if _nvml_init_attempted:
        return _nvml
    _nvml_init_attempted = True
    try:
        import pynvml  # noqa: PLC0415
        pynvml.nvmlInit()
        _nvml = pynvml
        _cache_gpu_handles()
    except Exception:  # noqa: BLE001
        _nvml = None
    return _nvml


def _cache_gpu_handles() -> None:
    """Populate ``_nvml_handles`` once per process. Failures leave it empty."""
    if _nvml is None:
        return
    try:
        count = _nvml.nvmlDeviceGetCount()
    except Exception:  # noqa: BLE001
        return
    for i in range(count):
        try:
            _nvml_handles.append((i, _nvml.nvmlDeviceGetHandleByIndex(i)))
        except Exception:  # noqa: BLE001
            return


def _gpu_handles() -> Iterable[tuple[int, Any]]:
    if _get_nvml() is None:
        return ()
    return _nvml_handles


def _observe_gpu_mem_used(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    pynvml = _get_nvml()
    if pynvml is None:
        return
    for idx, handle in _gpu_handles():
        try:
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            yield Observation(int(info.used), {"device": str(idx)})
        except Exception:  # noqa: BLE001
            continue


def _observe_gpu_mem_total(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    pynvml = _get_nvml()
    if pynvml is None:
        return
    for idx, handle in _gpu_handles():
        try:
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            yield Observation(int(info.total), {"device": str(idx)})
        except Exception:  # noqa: BLE001
            continue


def _observe_gpu_util(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    pynvml = _get_nvml()
    if pynvml is None:
        return
    for idx, handle in _gpu_handles():
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            yield Observation(int(util.gpu), {"device": str(idx)})
        except Exception:  # noqa: BLE001
            continue


# -----------------------------------------------------------------------------
# Public API used by handler.py / worker.warmup / the harness log mirror.
# All of these short-circuit cheaply when _enabled is False.
# -----------------------------------------------------------------------------

@contextlib.contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """Open an OTel span, or a no-op context if telemetry is disabled.

    The SDK's own exception recording is switched off and routed through
    :func:`record_exception` instead, so a failure that passes through
    several nested spans is described the same way on each of them —
    and the same way as the job response and the stdout log line. The
    two flags move together: turning off only the status one would
    leave a failed span reporting UNSET.
    """
    if not _enabled or _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(
        name,
        attributes=attrs,
        record_exception=False,
        set_status_on_exception=False,
    ) as sp:
        try:
            yield sp
        except BaseException as exc:  # noqa: BLE001 — re-raised immediately
            # ``sp`` is still the current span here, so this lands on it.
            record_exception(exc)
            raise


def set_span_attrs(**attrs: Any) -> None:
    """Add attributes to the currently-active span, if any."""
    if not _enabled or _trace_api is None:
        return
    try:
        sp = _trace_api.get_current_span()
        for k, v in attrs.items():
            sp.set_attribute(k, v)
    except Exception:  # noqa: BLE001
        pass


def record_exception(exc: BaseException) -> None:
    """Attach an exception to the current span AND mark its status ERROR.

    OTel semantic conventions require both: an ``exception`` span event
    carrying the type / message / stack trace, and a span status of
    ERROR so trace dashboards filter it as a failure.

    The event is built here rather than via ``Span.record_exception``
    so the text goes through the harness's ``redact.compact`` first — the
    exported record then reads the same as the job response and the
    stdout log line for the same failure, instead of being a longer
    variant of it.
    """
    if not _enabled or _trace_api is None:
        return
    try:
        import traceback  # noqa: PLC0415

        from runpod_doc_worker.obs import redact as _redact  # noqa: PLC0415

        message = _redact.compact(str(exc))
        stack = _redact.compact(
            "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
            limit=4000,
        )
        # Qualified type name, matching what the SDK's own recorder emits —
        # a saved query or a dashboard grouping on `exception.type` keeps
        # working, and short names don't collide across libraries.
        mod = type(exc).__module__
        qual = type(exc).__qualname__
        exc_type = qual if not mod or mod == "builtins" else f"{mod}.{qual}"
        sp = _trace_api.get_current_span()
        sp.add_event(
            "exception",
            {
                "exception.type": exc_type,
                "exception.message": message,
                "exception.stacktrace": stack,
            },
        )
        if _status_cls is not None and _status_code is not None:
            sp.set_status(_status_cls(_status_code.ERROR, message))
    except Exception:  # noqa: BLE001
        pass


def counter_add(name: str, value: int = 1, **attrs: Any) -> None:
    """Increment a counter from the catalog. Warns once on unknown name
    when telemetry is enabled — silent when disabled (the whole API is
    no-op then, so a typo here doesn't deserve noise)."""
    inst = _metrics.get(name)
    if inst is None:
        _warn_unknown_metric(name)
        return
    try:
        inst.add(value, attributes=attrs)
    except Exception:  # noqa: BLE001
        pass


def histogram_record(name: str, value: float, **attrs: Any) -> None:
    """Record a histogram observation. Warns once on unknown name."""
    inst = _metrics.get(name)
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
    if not _enabled:
        return
    if name in _warned_unknown_names:
        return
    _warned_unknown_names.add(name)
    print(
        f"[mineru-telemetry] unknown metric name {name!r} — "
        f"check worker/telemetry.py _build_instruments",
        flush=True,
    )


def emit_log(level: str, msg: str, fields: dict[str, Any]) -> None:
    """Mirror a stdout log line to the OTel logs exporter.

    Reached through the harness's log mirror (see :mod:`worker.harness`)
    after the stdout JSON line has already been printed, and registered
    there rather than called directly, so a worker without telemetry
    configured never routes a record through this module at all.

    Never raises: a downed collector or
    misconfigured headers must NOT silence the worker's primary logging
    channel.
    """
    if not _enabled or _logger is None or _severity_number is None:
        return
    try:
        sev_map = {
            "debug": _severity_number.DEBUG,
            "info": _severity_number.INFO,
            "warning": _severity_number.WARN,
            "error": _severity_number.ERROR,
            "critical": _severity_number.FATAL,
            "fatal": _severity_number.FATAL,
        }
        # Attach to current span if any — gives the OTel backend the
        # trace_id / span_id for log-to-trace correlation.
        ctx = None
        if _trace_api is not None:
            sp = _trace_api.get_current_span()
            if sp is not None:
                ctx = sp.get_span_context()
        kwargs: dict[str, Any] = {
            "timestamp": int(time.time() * 1e9),
            "severity_text": level.upper(),
            "severity_number": sev_map.get(level, _severity_number.INFO),
            "body": msg,
            "attributes": dict(fields) if fields else None,
        }
        if ctx is not None and ctx.is_valid:
            kwargs["trace_id"] = ctx.trace_id
            kwargs["span_id"] = ctx.span_id
            kwargs["trace_flags"] = ctx.trace_flags
        _logger.emit(**kwargs)
    except Exception:  # noqa: BLE001
        # Silent: the stdout line already fired; we don't degrade logging
        # if the OTel pipeline misbehaves.
        pass


def shutdown(timeout_millis: int = 2000) -> None:
    """Flush buffered spans/logs/metrics. Best-effort, never raises."""
    if not _enabled:
        return
    try:
        if _trace_api is not None:
            tp = _trace_api.get_tracer_provider()
            if hasattr(tp, "shutdown"):
                tp.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        if _logger_provider is not None and hasattr(_logger_provider, "shutdown"):
            _logger_provider.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        from opentelemetry import metrics  # noqa: PLC0415
        mp = metrics.get_meter_provider()
        if hasattr(mp, "shutdown"):
            mp.shutdown(timeout_millis=timeout_millis)
    except Exception:  # noqa: BLE001
        pass


# -----------------------------------------------------------------------------
# Test helpers. NOT public API — exposed so test_telemetry.py can drive the
# enabled path with an in-memory exporter without setting OTEL env vars.
# -----------------------------------------------------------------------------

def _reset_for_tests() -> None:
    """Drop initialization state so the next init_telemetry() runs again."""
    global _initialized, _enabled, _tracer, _logger, _logger_provider, _meter
    global _nvml, _nvml_init_attempted
    global _trace_api, _severity_number, _status_cls, _status_code
    global _jobs_getter, _pages_getter
    with _lock:
        _initialized = False
        _enabled = False
        _tracer = None
        _logger = None
        _logger_provider = None
        _meter = None
        _metrics.clear()
        _resource_attrs.clear()
        _nvml = None
        _nvml_init_attempted = False
        _nvml_handles.clear()
        _trace_api = None
        _severity_number = None
        _status_cls = None
        _status_code = None
        _jobs_getter = None
        _pages_getter = None
        _warned_unknown_names.clear()
