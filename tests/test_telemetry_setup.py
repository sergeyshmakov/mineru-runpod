"""Optional OpenTelemetry export. -- setup."""

from __future__ import annotations

import httpx
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


def test_shutdown_is_noop_when_disabled():
    from worker import telemetry

    telemetry.init_telemetry()
    telemetry.shutdown()  # must not raise


def test_init_returns_true_when_endpoint_set(monkeypatch):
    from worker import telemetry

    assert _enable(monkeypatch) is True
    assert telemetry.is_enabled() is True


def test_init_does_not_import_python_logging(monkeypatch):
    """The OTel logs path must NOT route through Python's logging module.

    The runpod SDK reconfigures the root logger inside serverless.start()
    and silences anything plumbed through it (see the harness's obs.logging
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


def test_span_yields_real_span_when_enabled(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    with telemetry.span("test.span", foo="bar") as sp:
        assert sp is not None
        # Real OTel spans have set_attribute; the no-op type does not.
        sp.set_attribute("extra", "value")


def test_init_failure_is_nonfatal(monkeypatch):
    """If OTel SDK setup raises, init_telemetry() returns False, doesn't crash."""
    from worker import telemetry
    from worker.telemetry import setup as telemetry_setup

    # Patch _enable to blow up; init must catch and return False.
    def boom():
        raise RuntimeError("simulated SDK explosion")

    monkeypatch.setattr(telemetry_setup, "_enable", boom)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert telemetry.init_telemetry() is False
    assert telemetry.is_enabled() is False


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


def test_exception_leaving_a_span_is_recorded_once_and_compacted(monkeypatch):
    """A failure passing through a phase span must be described there the same
    way as everywhere else.

    The SDK records exceptions on a span by default, which would put a second,
    unreduced copy of the text on every span the failure passes through.
    """
    from worker import telemetry

    _enable(monkeypatch)
    child = None
    with telemetry.span("test.job") as parent:
        try:
            with telemetry.span("test.phase") as sp:
                child = sp
                raise RuntimeError("GET https://f.example/a.pdf?sig=SECRETSIG failed")
        except RuntimeError as exc:
            telemetry.record_exception(exc)

    from opentelemetry.trace import StatusCode

    for span_under_test in (child, parent):
        events = [e for e in span_under_test.events if e.name == "exception"]
        assert len(events) == 1, f"expected one exception event, got {len(events)}"
        attrs = events[0].attributes
        assert "sig=" not in attrs["exception.message"]
        assert "sig=" not in attrs["exception.stacktrace"]
        assert "https://f.example/a.pdf" in attrs["exception.message"]
        assert "sig=" not in str(span_under_test.status.description)
        assert span_under_test.status.status_code == StatusCode.ERROR


def test_record_exception_reports_a_qualified_type(monkeypatch):
    """Third-party exception types keep their module, as the SDK's own
    recorder emitted — dashboards group on this attribute."""
    from worker import telemetry

    _enable(monkeypatch)
    with telemetry.span("test.op") as sp:
        try:
            raise httpx.ConnectTimeout("timed out")
        except httpx.ConnectTimeout as exc:
            telemetry.record_exception(exc)
    attrs = {e.name: e.attributes for e in sp.events}["exception"]
    assert attrs["exception.type"] == "httpx.ConnectTimeout"


def test_record_exception_leaves_builtins_unqualified(monkeypatch):
    from worker import telemetry

    _enable(monkeypatch)
    with telemetry.span("test.op") as sp:
        try:
            raise ValueError("plain")
        except ValueError as exc:
            telemetry.record_exception(exc)
    attrs = {e.name: e.attributes for e in sp.events}["exception"]
    assert attrs["exception.type"] == "ValueError"


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
