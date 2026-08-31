"""Turning telemetry on, and off again.

`init_telemetry` is the only thing a worker calls. Everything it touches lives in
`state`, which is why this module writes there rather than holding anything of its
own -- the tracer built here is read by `tracing`, and the meter by `instruments`.
"""

from __future__ import annotations

import os
from typing import Any


from worker.telemetry import instruments, state


def init_telemetry() -> bool:
    """Initialize OTel if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.

    Returns ``True`` if telemetry was activated, ``False`` otherwise
    (env var unset, SDK import failed, or exporter setup raised).
    Idempotent — subsequent calls return the initial decision without
    re-running setup. Never raises: a misconfigured endpoint must not
    block worker boot.
    """
    with state._lock:
        if state._initialized:
            return state._enabled
        state._initialized = True

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            return False

        try:
            _enable()
            state._enabled = True
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
            state._enabled = False
        return state._enabled


def _enable() -> None:
    """Configure OTel SDK providers + exporters. Called once by init_telemetry()."""

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
    state._resource_attrs.clear()
    state._resource_attrs.update({k: str(v) for k, v in attrs.items()})
    resource = Resource.create(attrs)

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(), schedule_delay_millis=500)
    )
    trace.set_tracer_provider(tracer_provider)
    state._tracer = trace.get_tracer("mineru-worker")

    state._logger_provider = LoggerProvider(resource=resource)
    state._logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(), schedule_delay_millis=500)
    )
    set_logger_provider(state._logger_provider)
    state._logger = state._logger_provider.get_logger("mineru-worker")

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
    state._meter = metrics.get_meter("mineru-worker")
    instruments._build_instruments(state._meter)

    # Cache OTel symbols accessed on every emit so we skip the lazy
    # import on the hot path. The SDK is already in sys.modules at
    # this point; this just hoists the per-call dict lookups.
    from opentelemetry import context as context_api  # noqa: PLC0415

    state._trace_api = trace
    state._context_api = context_api
    state._severity_number = SeverityNumber
    state._status_cls = Status
    state._status_code = StatusCode

    # First metric the world sees from this worker — useful for
    # cold-start rate dashboards.
    state._metrics["cold_starts_total"].add(1)


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


def shutdown(timeout_millis: int = 2000) -> None:
    """Flush buffered spans/logs/metrics. Best-effort, never raises."""
    if not state._enabled:
        return
    try:
        if state._trace_api is not None:
            tp = state._trace_api.get_tracer_provider()
            if hasattr(tp, "shutdown"):
                tp.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        if state._logger_provider is not None and hasattr(state._logger_provider, "shutdown"):
            state._logger_provider.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        from opentelemetry import metrics  # noqa: PLC0415
        mp = metrics.get_meter_provider()
        if hasattr(mp, "shutdown"):
            mp.shutdown(timeout_millis=timeout_millis)
    except Exception:  # noqa: BLE001
        pass


def _reset_for_tests() -> None:
    """Drop initialization state so the next init_telemetry() runs again."""
    with state._lock:
        state._initialized = False
        state._enabled = False
        state._tracer = None
        state._logger = None
        state._logger_provider = None
        state._meter = None
        state._metrics.clear()
        state._resource_attrs.clear()
        state._nvml = None
        state._nvml_init_attempted = False
        state._nvml_handles.clear()
        state._trace_api = None
        state._context_api = None
        state._severity_number = None
        state._status_cls = None
        state._status_code = None
        state._jobs_getter = None
        state._pages_getter = None
        state._warned_unknown_names.clear()
