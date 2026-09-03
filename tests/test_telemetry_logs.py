"""Optional OpenTelemetry export. -- logs."""

from __future__ import annotations

import io
import json
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


def _enable(monkeypatch, **extras):
    """Set the env vars that trip telemetry on, then call init_telemetry."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    for k, v in extras.items():
        monkeypatch.setenv(k, v)
    from worker import telemetry

    return telemetry.init_telemetry()


def _capture_logs(monkeypatch):
    """Enable telemetry with an in-memory logs exporter, and a real tracer."""
    from opentelemetry import trace
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        InMemoryLogRecordExporter,
        SimpleLogRecordProcessor,
    )
    from opentelemetry.sdk.trace import TracerProvider

    from worker.telemetry import state as telemetry_state

    _enable(monkeypatch)
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    monkeypatch.setattr(telemetry_state, "_logger", provider.get_logger("test"))
    trace.set_tracer_provider(TracerProvider())
    return exporter, trace.get_tracer("test")


def test_emit_log_is_noop_when_disabled():
    from worker import telemetry

    telemetry.init_telemetry()
    telemetry.emit_log("info", "test", {"backend": "vlm-auto-engine"})  # must not raise


def test_emit_log_does_not_raise_on_clean_path(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    telemetry.emit_log("info", "hello", {"backend": "vlm-auto-engine", "pages": 3})
    telemetry.emit_log("warning", "watch out", {})
    telemetry.emit_log("error", "kaboom", {"code": 1})


def test_emit_log_failure_is_silent(monkeypatch):
    """A broken OTel logger must not propagate exceptions back to the log mirror."""
    from worker import telemetry
    from worker.telemetry import state as telemetry_state

    _enable(monkeypatch)

    class FailingLogger:
        def emit(self, **kwargs):
            raise RuntimeError("collector down")

    monkeypatch.setattr(telemetry_state, "_logger", FailingLogger())
    telemetry.emit_log("info", "test", {"k": "v"})  # must not raise


def test_logging_mirrors_to_telemetry_when_enabled(monkeypatch):
    """A log line should fan out to telemetry.emit_log when enabled."""
    from runpod_doc_worker.obs import logging as worker_logging

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
    # `message`, not `msg`: harness v0.9.0 renamed the field to the name RunPod's
    # log viewer actually reads. Under the old spelling the viewer filled its
    # LEVEL column and left MESSAGE empty on every structured line.
    assert data["message"] == "hello"
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
    from runpod_doc_worker.obs import logging as worker_logging

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
    from runpod_doc_worker.obs import logging as worker_logging

    from worker import telemetry

    telemetry.init_telemetry()  # disabled — no env var set

    calls: list = []
    monkeypatch.setattr(
        telemetry, "emit_log",
        lambda level, msg, fields: calls.append((level, msg)),
    )
    worker_logging.info("hello")
    assert calls == []  # mirror skipped because telemetry.is_enabled() is False


def test_emit_log_maps_critical_and_fatal_severity(monkeypatch):
    """The harness only emits debug/info/warning/error today, but the
    mirror should still map critical/fatal correctly in case a helper
    is added later (or a caller bypasses the wrapper)."""
    from worker import telemetry
    from worker.telemetry import state as telemetry_state

    _enable(monkeypatch)

    captured_kwargs: list[dict] = []

    class CaptureLogger:
        def emit(self, **kwargs):
            captured_kwargs.append(kwargs)

    monkeypatch.setattr(telemetry_state, "_logger", CaptureLogger())

    telemetry.emit_log("critical", "fire", {})
    telemetry.emit_log("fatal", "kaboom", {})

    from opentelemetry._logs import SeverityNumber
    assert captured_kwargs[0]["severity_number"] == SeverityNumber.FATAL
    assert captured_kwargs[1]["severity_number"] == SeverityNumber.FATAL


def test_a_log_emitted_inside_a_span_is_exported(monkeypatch):
    """The regression: this is the case that raised on every job."""
    from worker import telemetry

    exporter, tracer = _capture_logs(monkeypatch)
    with tracer.start_as_current_span("mineru.job"):
        telemetry.emit_log("info", "inside a span", {"job_id": "abc"})

    records = exporter.get_finished_logs()
    assert len(records) == 1, "the record never reached the exporter"
    assert records[0].log_record.body == "inside a span"


def test_the_exported_record_keeps_its_trace_correlation(monkeypatch):
    """Correlation is why those keyword arguments were there, so the fix has to
    preserve it rather than drop the ids to make the call legal."""
    from worker import telemetry

    exporter, tracer = _capture_logs(monkeypatch)
    with tracer.start_as_current_span("mineru.job") as span:
        telemetry.emit_log("error", "correlate me", {})
        expected = span.get_span_context()

    record = exporter.get_finished_logs()[0].log_record
    assert record.trace_id == expected.trace_id
    assert record.span_id == expected.span_id


def test_a_log_emitted_outside_a_span_still_exports(monkeypatch):
    """The half that always worked, kept so a fix cannot trade one for the other."""
    from worker import telemetry

    exporter, _ = _capture_logs(monkeypatch)
    telemetry.emit_log("warning", "no span here", {"k": "v"})
    assert len(exporter.get_finished_logs()) == 1


def test_a_broken_emit_is_reported_once_not_silently(monkeypatch, capsys):
    """A downed collector must stay silent; calling the SDK wrongly must not.
    That distinction is what this bug cost, so it is now enforced."""
    from worker import telemetry
    from worker.telemetry import state as telemetry_state

    _enable(monkeypatch)

    class Wrong:
        def emit(self, **kwargs):
            raise TypeError("Logger.emit() got an unexpected keyword argument 'x'")

    monkeypatch.setattr(telemetry_state, "_logger", Wrong())
    monkeypatch.setattr(telemetry_state, "_emit_defect_reported", False)
    telemetry.emit_log("info", "one", {})
    telemetry.emit_log("info", "two", {})

    out = capsys.readouterr().out
    assert "calling the OTel SDK" in out
    assert out.count("[mineru-telemetry] log export") == 1, "reported once, not per record"
