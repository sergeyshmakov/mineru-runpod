"""OpenTelemetry for this worker: traces, metrics and logs, all optional.

Split into modules because it had grown past being readable whole. The seam that
matters is `state` -- see its docstring for why everything reads through it instead
of importing its names.

Nothing private is imported here. It is forwarded by ``__getattr__``, for two
reasons. A module-level alias to a rebound name is a snapshot:
``telemetry._jobs_getter`` is `None` until a worker registers its gauges, and a
caller reading it through this package has to see the current value. And an import
that exists only to re-export looks unused to every linter -- which is not a
hypothetical, since an autofix deleted exactly that kind of import from a sibling
package and removed a documented function with it.
"""

from __future__ import annotations

from typing import Any

from worker.telemetry import gpu, instruments, setup, state, tracing
from worker.telemetry.instruments import (
    counter_add,
    histogram_record,
    register_worker_gauges,
)
from worker.telemetry.setup import init_telemetry, shutdown
from worker.telemetry.state import is_enabled
from worker.telemetry.tracing import (
    emit_log,
    record_exception,
    set_span_attrs,
    span,
)

# The documented surface: what a worker calls.
__all__ = [
    "counter_add",
    "emit_log",
    "histogram_record",
    "init_telemetry",
    "is_enabled",
    "record_exception",
    "register_worker_gauges",
    "set_span_attrs",
    "shutdown",
    "span",
]

# Searched in order for anything not bound above. `state` first, so a rebound
# value is always read fresh rather than through whatever alias came later.
_SOURCES = (state, setup, instruments, gpu, tracing)


def __getattr__(name: str) -> Any:
    for source in _SOURCES:
        try:
            return getattr(source, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """So `dir(telemetry)` still shows what the forwarding makes reachable."""
    names = set(__all__)
    for source in _SOURCES:
        names.update(n for n in vars(source) if not n.startswith("__"))
    return sorted(names)
