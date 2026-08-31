"""Spans, span attributes, exceptions, and log records.

Grouped because they share one requirement: each is called from the request path
and none of them may raise. A telemetry backend that has gone away has to look like
telemetry that is switched off.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from typing import Any


from worker.telemetry import state


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
    if not state._enabled or state._tracer is None:
        yield None
        return
    with state._tracer.start_as_current_span(
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
    if not state._enabled or state._trace_api is None:
        return
    try:
        sp = state._trace_api.get_current_span()
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
    if not state._enabled or state._trace_api is None:
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
        sp = state._trace_api.get_current_span()
        sp.add_event(
            "exception",
            {
                "exception.type": exc_type,
                "exception.message": message,
                "exception.stacktrace": stack,
            },
        )
        if state._status_cls is not None and state._status_code is not None:
            sp.set_status(state._status_cls(state._status_code.ERROR, message))
    except Exception:  # noqa: BLE001
        pass


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
    if not state._enabled or state._logger is None or state._severity_number is None:
        return
    try:
        sev_map = {
            "debug": state._severity_number.DEBUG,
            "info": state._severity_number.INFO,
            "warning": state._severity_number.WARN,
            "error": state._severity_number.ERROR,
            "critical": state._severity_number.FATAL,
            "fatal": state._severity_number.FATAL,
        }
        kwargs: dict[str, Any] = {
            "timestamp": int(time.time() * 1e9),
            "severity_text": level.upper(),
            "severity_number": sev_map.get(level, state._severity_number.INFO),
            "body": msg,
            "attributes": dict(fields) if fields else None,
        }
        # Log-to-trace correlation by handing over the current context, from
        # which the SDK derives trace_id, span_id and trace_flags itself.
        #
        # Those three used to be passed as keyword arguments, and
        # `Logger.emit()` accepts none of them — it takes an optional LogRecord
        # plus timestamp, observed_timestamp, context, severity_*, body,
        # attributes, event_name and exception. So every log emitted while a
        # span was current raised TypeError into the silent handler below, and
        # the handler wraps every job in a span, so that was every line a job
        # produced. Boot-time lines, emitted outside any span, exported fine —
        # which is the split that made it invisible: an operator who enabled
        # telemetry saw startup logs arrive and concluded it worked.
        if state._context_api is not None:
            kwargs["context"] = state._context_api.get_current()
        state._logger.emit(**kwargs)
    except Exception as e:  # noqa: BLE001
        # Still never raises: the stdout line already fired, and a downed
        # collector must not silence the worker's primary logging channel.
        #
        # But a TypeError or AttributeError is not a downed collector, it is
        # this module calling the SDK wrongly — which is how the bug above
        # survived. Reported once, with print rather than the logging module,
        # because this function is the log mirror and routing through it would
        # recurse.
        if not state._emit_defect_reported and isinstance(e, (TypeError, AttributeError)):
            state._emit_defect_reported = True
            print(
                f"[mineru-telemetry] log export is calling the OTel SDK "
                f"incorrectly and is dropping every record: "
                f"{type(e).__name__}: {e}",
                flush=True,
            )
