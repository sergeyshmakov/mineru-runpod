"""Every piece of telemetry state, in one module because it is shared.

Seventeen of these are rebound at runtime -- by `init_telemetry`, by `_enable`, by
`register_worker_gauges`, by the NVML lookup, by `_reset_for_tests`. So they are
read through this module everywhere: ``_tracer``, never
``from .state import _tracer``. The from-import binds the value at import time,
which for a tracer built later means `None` for the life of the process.

`_metrics` and `_resource_attrs` are only ever mutated in place, so an alias to
either would work -- they are here and read the same way anyway, because a rule
with two exceptions is a rule nobody applies.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

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
# Set once when log export turns out to be calling the SDK wrongly, so the
# report is one line rather than one per record.
_emit_defect_reported = False

_trace_api: Any = None

_context_api: Any = None

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

# pynvml needs to be imported and initialized exactly once per process.
# The init has a measurable cost (~30 ms) so we defer it until first use.
# We also cache the device handle list — the count and per-index handles
# don't change after nvmlInit, so re-querying on every export tick wastes
# work for no benefit.
_nvml: Any = None

_nvml_init_attempted = False

_nvml_handles: list[tuple[int, Any]] = []


def is_enabled() -> bool:
    """Whether OTel export is active. Cheap, safe to call from anywhere."""
    return _enabled
