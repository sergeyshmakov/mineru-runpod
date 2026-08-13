"""Optional OpenTelemetry export.

The default codepath is no-op: when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is
unset, the SDK is never imported and every public function returns
cheaply. These tests cover both halves:

- no-op (env unset) — must work without the OTel SDK being present at all
- enabled (env set) — must wire up tracer/meter/logger providers without
  importing Python's ``logging`` module and without raising on a bad
  endpoint
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from contextlib import redirect_stdout

import pytest


# Every test starts with a clean module state. Without _reset_for_tests()
# the first init_telemetry() call wins for the whole test session.
@pytest.fixture(autouse=True)
def _clean_telemetry_state(monkeypatch):
    from worker import telemetry

    for var in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_SERVICE_NAME",
        "OTEL_RESOURCE_ATTRIBUTES",
        "RUNPOD_ENDPOINT_ID",
        "RUNPOD_POD_ID",
        "RUNPOD_GPU_TYPE",
        "RUNPOD_GPU_COUNT",
    ):
        monkeypatch.delenv(var, raising=False)
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


# -----------------------------------------------------------------------------
# No-op path: env unset → init returns False, public API is safe to call
# -----------------------------------------------------------------------------

def test_init_returns_false_when_env_unset():
    from worker import telemetry

    assert telemetry.init_telemetry() is False
    assert telemetry.is_enabled() is False


def test_init_is_idempotent_when_disabled():
    from worker import telemetry

    assert telemetry.init_telemetry() is False
    assert telemetry.init_telemetry() is False  # second call returns same decision


def test_span_is_noop_when_disabled():
    from worker import telemetry

    telemetry.init_telemetry()
    with telemetry.span("test.span", foo="bar") as sp:
        assert sp is None  # contract: yields None when disabled


def test_counter_and_histogram_are_noop_when_disabled():
    from worker import telemetry

    telemetry.init_telemetry()
    # These must not raise even though no instruments exist.
    telemetry.counter_add("jobs_total", 5, status="ok")
    telemetry.counter_add("nonexistent_metric", 99)
    telemetry.histogram_record("job_duration", 1.23)
    telemetry.histogram_record("not_in_catalog", 0.0)


def test_emit_log_is_noop_when_disabled():
    from worker import telemetry

    telemetry.init_telemetry()
    telemetry.emit_log("info", "test", {"backend": "vlm-auto-engine"})  # must not raise


def test_shutdown_is_noop_when_disabled():
    from worker import telemetry

    telemetry.init_telemetry()
    telemetry.shutdown()  # must not raise


# -----------------------------------------------------------------------------
# Enabled path: env set → providers configured, instruments registered
# -----------------------------------------------------------------------------

def _enable(monkeypatch, **extras):
    """Set the env vars that trip telemetry on, then call init_telemetry."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    for k, v in extras.items():
        monkeypatch.setenv(k, v)
    from worker import telemetry

    return telemetry.init_telemetry()


def test_init_returns_true_when_endpoint_set(monkeypatch):
    from worker import telemetry

    assert _enable(monkeypatch) is True
    assert telemetry.is_enabled() is True


def test_init_does_not_import_python_logging(monkeypatch):
    """The OTel logs path must NOT route through Python's logging module.

    The runpod SDK reconfigures the root logger inside serverless.start()
    and silences anything plumbed through it (see worker/logging.py
    docstring). Reintroducing Python logging here would re-create the
    disappearing-logs bug.
    """
    _enable(monkeypatch)

    # The OTel SDK's LoggingHandler exists, but we must not have installed
    # it. The handler is what bridges Python `logging` into the OTel logs
    # pipeline — its absence on the root logger proves we use direct emit.
    import logging as stdlib_logging

    from opentelemetry.sdk._logs import LoggingHandler

    handler_classes = [type(h).__name__ for h in stdlib_logging.getLogger().handlers]
    assert "LoggingHandler" not in handler_classes, (
        f"OTel LoggingHandler installed on root logger: {handler_classes}. "
        "Telemetry must emit log records directly via Logger.emit() — see "
        "worker/telemetry.py docstring for why."
    )
    # And the symbol exists so a future regression that does install it
    # would still resolve. The test exists to guard the *not-installed*
    # state.
    assert LoggingHandler is not None


def test_init_is_idempotent_when_enabled(monkeypatch):
    """Calling init twice must not duplicate providers or instruments."""
    from worker import telemetry

    _enable(monkeypatch)
    first_metrics_id = id(telemetry._metrics)
    assert telemetry.init_telemetry() is True
    assert id(telemetry._metrics) == first_metrics_id  # same dict, no rebuild


def test_resource_attrs_pulled_from_runpod_env(monkeypatch):
    from worker import telemetry

    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "ep-test-123")
    monkeypatch.setenv("RUNPOD_POD_ID", "pod-test-abc")
    monkeypatch.setenv("RUNPOD_GPU_TYPE", "NVIDIA GeForce RTX 4090")
    _enable(monkeypatch)

    assert telemetry._resource_attrs["runpod.endpoint_id"] == "ep-test-123"
    assert telemetry._resource_attrs["runpod.pod_id"] == "pod-test-abc"
    assert telemetry._resource_attrs["runpod.gpu_type"] == "NVIDIA GeForce RTX 4090"
    assert telemetry._resource_attrs["service.name"] == "mineru-runpod"


def test_service_name_override(monkeypatch):
    from worker import telemetry

    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-service")
    _enable(monkeypatch)
    assert telemetry._resource_attrs["service.name"] == "custom-service"


def test_metric_catalog_registered(monkeypatch):
    """Every metric the handler references must exist in the catalog."""
    from worker import telemetry

    _enable(monkeypatch)
    expected = {
        "jobs_total", "pages_total", "bytes_in_total", "bytes_out_total",
        "errors_total", "job_duration", "phase_duration", "pages_per_second",
        "input_size_bytes", "output_size_bytes", "cold_starts_total",
        "warmup_duration", "refresh_total",
    }
    assert expected.issubset(set(telemetry._metrics)), (
        f"missing metrics: {expected - set(telemetry._metrics)}"
    )


def test_span_yields_real_span_when_enabled(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    with telemetry.span("test.span", foo="bar") as sp:
        assert sp is not None
        # Real OTel spans have set_attribute; the no-op type does not.
        sp.set_attribute("extra", "value")


def test_counter_and_histogram_record_without_error(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    telemetry.counter_add("jobs_total", 1, status="ok")
    telemetry.histogram_record("job_duration", 4.2, backend="vlm-auto-engine")


def test_emit_log_does_not_raise_on_clean_path(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    telemetry.emit_log("info", "hello", {"backend": "vlm-auto-engine", "pages": 3})
    telemetry.emit_log("warning", "watch out", {})
    telemetry.emit_log("error", "kaboom", {"code": 1})


# -----------------------------------------------------------------------------
# Failure safety: bad endpoint must NOT prevent worker boot
# -----------------------------------------------------------------------------

def test_init_failure_is_nonfatal(monkeypatch):
    """If OTel SDK setup raises, init_telemetry() returns False, doesn't crash."""
    from worker import telemetry

    # Patch _enable to blow up; init must catch and return False.
    def boom():
        raise RuntimeError("simulated SDK explosion")

    monkeypatch.setattr(telemetry, "_enable", boom)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert telemetry.init_telemetry() is False
    assert telemetry.is_enabled() is False


def test_emit_log_failure_is_silent(monkeypatch):
    """A broken OTel logger must not propagate exceptions back to worker.logging."""
    from worker import telemetry

    _enable(monkeypatch)

    class FailingLogger:
        def emit(self, **kwargs):
            raise RuntimeError("collector down")

    monkeypatch.setattr(telemetry, "_logger", FailingLogger())
    telemetry.emit_log("info", "test", {"k": "v"})  # must not raise


# -----------------------------------------------------------------------------
# worker.logging mirror integration: enabled telemetry triggers emit_log
# -----------------------------------------------------------------------------

def test_logging_mirrors_to_telemetry_when_enabled(monkeypatch):
    """worker.logging.info() should fan out to telemetry.emit_log when enabled."""
    from worker import logging as worker_logging
    from worker import telemetry

    _enable(monkeypatch)

    calls: list[tuple[str, str, dict]] = []

    def spy_emit(level, msg, fields):
        calls.append((level, msg, dict(fields)))

    monkeypatch.setattr(telemetry, "emit_log", spy_emit)
    monkeypatch.setenv("LOG_FORMAT", "json")

    buf = io.StringIO()
    with redirect_stdout(buf):
        worker_logging.info("hello", backend="vlm-auto-engine", pages=3)

    # The stdout JSON line still fired (primary channel).
    data = json.loads(buf.getvalue().strip())
    assert data["msg"] == "hello"
    assert data["backend"] == "vlm-auto-engine"

    # The mirror fired with the same payload.
    assert len(calls) == 1
    level, msg, fields = calls[0]
    assert level == "info"
    assert msg == "hello"
    assert fields["backend"] == "vlm-auto-engine"
    assert fields["pages"] == 3


def test_logging_mirror_includes_job_id(monkeypatch):
    """The job_id contextvar should be threaded into the mirrored record."""
    from worker import logging as worker_logging
    from worker import telemetry

    _enable(monkeypatch)

    calls: list[dict] = []
    monkeypatch.setattr(
        telemetry, "emit_log",
        lambda level, msg, fields: calls.append(dict(fields)),
    )

    token = worker_logging.job_id_var.set("queued-job-uuid-xyz")
    try:
        worker_logging.info("doing thing")
    finally:
        worker_logging.job_id_var.reset(token)

    assert calls[0]["job_id"] == "queued-job-uuid-xyz"


def test_logging_does_not_mirror_when_disabled(monkeypatch):
    """No env var → mirror is skipped (and the OTel SDK isn't even imported)."""
    from worker import logging as worker_logging
    from worker import telemetry

    telemetry.init_telemetry()  # disabled — no env var set

    calls: list = []
    monkeypatch.setattr(
        telemetry, "emit_log",
        lambda level, msg, fields: calls.append((level, msg)),
    )
    worker_logging.info("hello")
    assert calls == []  # mirror skipped because telemetry.is_enabled() is False


# -----------------------------------------------------------------------------
# Warmup integration: span + duration histogram fire on warmup
# -----------------------------------------------------------------------------

def test_warmup_records_duration_histogram(monkeypatch, tmp_path):
    """warmup_async() should record a mineru.worker.warmup.duration sample."""
    from worker import telemetry
    from worker import warmup as warmup_module

    _enable(monkeypatch)

    fixture = tmp_path / "fixture.pdf"
    fixture.write_bytes(b"%PDF-1.4\nfake")
    monkeypatch.setattr(warmup_module, "WARMUP_FIXTURE_PATH", fixture)

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):  # noqa: ARG001
        out = work_dir / "fake-out"
        out.mkdir()
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)

    captured: list[tuple[str, float, dict]] = []
    monkeypatch.setattr(
        telemetry, "histogram_record",
        lambda name, value, **attrs: captured.append((name, value, attrs)),
    )

    asyncio.run(warmup_module.warmup_async())

    warmup_samples = [c for c in captured if c[0] == "warmup_duration"]
    assert warmup_samples, "warmup_duration histogram not recorded"
    name, value, attrs = warmup_samples[0]
    assert value >= 0.0
    assert attrs["backend"] == "vlm-auto-engine"
    assert attrs["status"] == "ok"


def test_warmup_records_error_status_on_failure(monkeypatch, tmp_path):
    from worker import telemetry
    from worker import warmup as warmup_module

    _enable(monkeypatch)

    fixture = tmp_path / "fixture.pdf"
    fixture.write_bytes(b"%PDF-1.4\nfake")
    monkeypatch.setattr(warmup_module, "WARMUP_FIXTURE_PATH", fixture)

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated mineru explosion")

    monkeypatch.setattr("worker.parse.run_mineru", boom)

    captured: list[tuple[str, float, dict]] = []
    monkeypatch.setattr(
        telemetry, "histogram_record",
        lambda name, value, **attrs: captured.append((name, value, attrs)),
    )

    # Must not raise — warmup failure stays non-fatal.
    asyncio.run(warmup_module.warmup_async())

    # Status label must be 'error', matching the handler's failure-path
    # convention (OTel semantic convention is 'ok' / 'error').
    err = [c for c in captured if c[0] == "warmup_duration" and c[2].get("status") == "error"]
    assert err, "expected a warmup_duration sample with status=error"
    assert not any(c[2].get("status") == "failed" for c in captured), (
        "status='failed' is legacy; warmup should emit status='error'"
    )


# -----------------------------------------------------------------------------
# Gauge registration (handler → telemetry dependency inversion)
# -----------------------------------------------------------------------------

def test_register_worker_gauges_wires_getters():
    from worker import telemetry

    telemetry.register_worker_gauges(
        jobs_since_boot=lambda: 7,
        pages_since_boot=lambda: 42,
    )
    assert telemetry._jobs_getter() == 7
    assert telemetry._pages_getter() == 42


def test_observe_jobs_since_boot_uses_registered_getter(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    telemetry.register_worker_gauges(
        jobs_since_boot=lambda: 13,
        pages_since_boot=lambda: 100,
    )
    observations = list(telemetry._observe_jobs_since_boot(None))
    assert len(observations) == 1
    assert observations[0].value == 13


def test_observe_gauges_yield_nothing_without_registration(monkeypatch):
    """Until handler calls register_worker_gauges, gauges report nothing."""
    from worker import telemetry

    _enable(monkeypatch)
    # _reset_for_tests cleared the getters; do NOT register.
    assert list(telemetry._observe_jobs_since_boot(None)) == []
    assert list(telemetry._observe_pages_since_boot(None)) == []


# -----------------------------------------------------------------------------
# Unknown-name typo guard
# -----------------------------------------------------------------------------

def test_counter_add_warns_once_on_unknown_name(monkeypatch, capsys):
    from worker import telemetry

    _enable(monkeypatch)
    telemetry.counter_add("not_in_catalog", 1)
    telemetry.counter_add("not_in_catalog", 1)  # second call must NOT re-warn
    out = capsys.readouterr().out
    warnings = [ln for ln in out.splitlines() if "unknown metric name" in ln]
    assert len(warnings) == 1
    assert "not_in_catalog" in warnings[0]


def test_counter_add_silent_for_unknown_when_disabled(capsys):
    """No env var = no warnings even for typos. The whole API is dormant."""
    from worker import telemetry

    telemetry.init_telemetry()  # disabled
    telemetry.counter_add("not_in_catalog", 1)
    out = capsys.readouterr().out
    assert "unknown metric name" not in out


# -----------------------------------------------------------------------------
# Span status on exception (OTel semantic convention: record + set_status)
# -----------------------------------------------------------------------------

def test_record_exception_sets_span_status_error(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    with telemetry.span("test.failing.op") as sp:
        assert sp is not None
        try:
            raise ValueError("simulated")
        except ValueError as exc:
            telemetry.record_exception(exc)
        # OTel SDK exposes the current status on read-only spans;
        # we assert it's ERROR via the span's internal status attr.
        from opentelemetry.trace import StatusCode
        assert sp.status.status_code == StatusCode.ERROR


def test_record_exception_adds_the_semantic_convention_event(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    with telemetry.span("test.failing.op") as sp:
        try:
            raise ValueError("simulated")
        except ValueError as exc:
            telemetry.record_exception(exc)
        events = {e.name: e for e in sp.events}
        assert "exception" in events
        attrs = events["exception"].attributes
        assert attrs["exception.type"] == "ValueError"
        assert attrs["exception.message"] == "simulated"
        assert "ValueError: simulated" in attrs["exception.stacktrace"]


def test_record_exception_exports_compacted_text(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    with telemetry.span("test.failing.op") as sp:
        try:
            raise RuntimeError(
                "GET https://files.example.com/a.pdf?sig=abcdef failed"
            )
        except RuntimeError as exc:
            telemetry.record_exception(exc)
        attrs = {e.name: e.attributes for e in sp.events}["exception"]
        assert "sig=" not in attrs["exception.message"]
        assert "sig=" not in attrs["exception.stacktrace"]
        assert "https://files.example.com/a.pdf" in attrs["exception.message"]
        assert "sig=" not in sp.status.description


# -----------------------------------------------------------------------------
# CRITICAL / FATAL severity mapping
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Histogram aggregation: exponential buckets, not the SDK's linear default.
# -----------------------------------------------------------------------------

def test_histograms_use_exponential_bucket_aggregation(monkeypatch):
    """All Histogram instruments must aggregate via base-2 exponential
    buckets, NOT the SDK default of explicit-bucket histograms.

    Why this matters: latency metrics (job_duration, warmup_duration)
    span ms → minutes, and byte-size metrics span KB → hundreds of MB.
    Exponential aggregation gives uniform resolution across those
    ranges without per-metric bucket tuning. A future refactor that
    drops the View on MeterProvider must fail this test.
    """
    from opentelemetry import metrics
    from opentelemetry.metrics import Histogram as ApiHistogram
    from opentelemetry.sdk.metrics.view import (
        ExponentialBucketHistogramAggregation,
    )

    from worker import telemetry

    _enable(monkeypatch)

    views = metrics.get_meter_provider()._sdk_config.views
    histogram_views = [
        v for v in views
        if v._instrument_type is ApiHistogram
        and isinstance(v._aggregation, ExponentialBucketHistogramAggregation)
    ]
    assert histogram_views, (
        f"no ExponentialBucketHistogramAggregation View found on the "
        f"MeterProvider (views: {[type(v._aggregation).__name__ for v in views]}). "
        "worker/telemetry.py must construct the MeterProvider with "
        "views=[View(instrument_type=Histogram, "
        "aggregation=ExponentialBucketHistogramAggregation())] so every "
        "histogram metric exports as base-2 exponential buckets."
    )


def test_emit_log_maps_critical_and_fatal_severity(monkeypatch):
    """worker.logging only emits debug/info/warning/error today, but the
    mirror should still map critical/fatal correctly in case a helper
    is added later (or a caller bypasses the wrapper)."""
    from worker import telemetry

    _enable(monkeypatch)

    captured_kwargs: list[dict] = []

    class CaptureLogger:
        def emit(self, **kwargs):
            captured_kwargs.append(kwargs)

    monkeypatch.setattr(telemetry, "_logger", CaptureLogger())

    telemetry.emit_log("critical", "fire", {})
    telemetry.emit_log("fatal", "kaboom", {})

    from opentelemetry._logs import SeverityNumber
    assert captured_kwargs[0]["severity_number"] == SeverityNumber.FATAL
    assert captured_kwargs[1]["severity_number"] == SeverityNumber.FATAL
