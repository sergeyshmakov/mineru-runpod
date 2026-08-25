"""Optional OpenTelemetry export. -- metrics."""

from __future__ import annotations

import asyncio

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


def _enable(monkeypatch, **extras):
    """Set the env vars that trip telemetry on, then call init_telemetry."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    for k, v in extras.items():
        monkeypatch.setenv(k, v)
    from worker import telemetry

    return telemetry.init_telemetry()


def test_counter_and_histogram_are_noop_when_disabled():
    from worker import telemetry

    telemetry.init_telemetry()
    # These must not raise even though no instruments exist.
    telemetry.counter_add("jobs_total", 5, status="ok")
    telemetry.counter_add("nonexistent_metric", 99)
    telemetry.histogram_record("job_duration", 1.23)
    telemetry.histogram_record("not_in_catalog", 0.0)


def test_init_is_idempotent_when_enabled(monkeypatch):
    """Calling init twice must not duplicate providers or instruments."""
    from worker import telemetry

    _enable(monkeypatch)
    first_metrics_id = id(telemetry._metrics)
    assert telemetry.init_telemetry() is True
    assert id(telemetry._metrics) == first_metrics_id  # same dict, no rebuild


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


def test_counter_and_histogram_record_without_error(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    telemetry.counter_add("jobs_total", 1, status="ok")
    telemetry.histogram_record("job_duration", 4.2, backend="vlm-auto-engine")


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
