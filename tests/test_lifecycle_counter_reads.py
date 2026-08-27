"""The boot-registered gauges have to read the counters, not a copy of them.

`worker.lifecycle` owns two module-level integers and rebinds them under `global`
on every completed job. `handler.py` imported them by name, and `from x import y`
binds by *value* -- so the alias in `handler` kept whatever the integer was at
import time, which is zero. The gauge getters were lambdas closing over that
alias, so both `mineru.worker.*_since_boot` gauges exported zero for the life of
the process, and the log record emitted when a refresh threshold trips reported
zero jobs and zero pages beside the reason it had just crossed a threshold.

Nothing caught it because the thresholds themselves are checked inside
`lifecycle` against its own globals, and those were always right.

An int is the one kind of module attribute that cannot be shared by reference,
which is why the accessors now live beside the state and the entry point wires a
single name instead of writing its own getters.
"""

from __future__ import annotations

import pytest

import handler
from worker import lifecycle


@pytest.fixture(autouse=True)
def _reset_counters():
    lifecycle._jobs_processed = 0
    lifecycle._pages_processed_total = 0
    yield
    lifecycle._jobs_processed = 0
    lifecycle._pages_processed_total = 0


def test_the_accessors_start_at_zero() -> None:
    """The guard on the rest: reading live must not mean reading something else.
    An accessor returning a wrong non-zero value would pass every test below."""
    assert lifecycle.jobs_since_boot() == 0
    assert lifecycle.pages_since_boot() == 0


def test_the_accessors_see_a_completed_job() -> None:
    handler._record_job(7)
    handler._record_job(5)
    assert lifecycle.jobs_since_boot() == 2
    assert lifecycle.pages_since_boot() == 12


def test_the_registered_getters_are_the_live_accessors() -> None:
    """The wiring, which is what actually broke.

    An earlier version of this file asserted only the accessors, and replacing the
    registration with `lambda: 0` left every test passing -- the same gap that let
    the original bug ship. This exercises what boot hands to telemetry.
    """
    assert set(lifecycle.GAUGE_GETTERS) == {"jobs_since_boot", "pages_since_boot"}
    handler._record_job(4)
    assert lifecycle.GAUGE_GETTERS["jobs_since_boot"]() == 1
    assert lifecycle.GAUGE_GETTERS["pages_since_boot"]() == 4


def test_the_entry_point_holds_no_integer_alias() -> None:
    """The regression guard proper.

    Re-adding `_jobs_processed` to the `from worker.lifecycle import (...)` list is
    the single edit that reintroduces this bug, and it looks entirely reasonable in
    a diff. A module-level binding for either counter must not exist.
    """
    for name in ("_jobs_processed", "_pages_processed_total"):
        assert name not in vars(handler), (
            f"handler.{name} is a module-level binding again; `from x import y` "
            f"copies an int, so it will hold zero for the life of the process"
        )


def test_the_compat_names_still_resolve_and_are_live() -> None:
    """Both are named in the compatibility surface, so they stay readable -- but
    forwarded, so a reader gets the current value rather than a snapshot."""
    handler._record_job(3)
    assert handler._jobs_processed == 1
    assert handler._pages_processed_total == 3


def test_an_unknown_attribute_still_raises() -> None:
    """The forward covers two names, not everything. A blanket forward would turn
    every typo into a silent lifecycle lookup."""
    with pytest.raises(AttributeError):
        handler._not_a_real_lifecycle_name  # noqa: B018
