"""The names `handler.py` promises, asserted so a refactor cannot quietly drop one.

This exists because refactors did, three times in one session and always the same
way: a symbol moves to a new module, its test is repointed at the new location, the
suite stays green, and the compatibility promise this module makes in a comment is
broken with nothing left to notice. `handler._package_inline` was the third.

A list of names in a comment cannot fail. This can.

The list is the back-compat block in `handler.py`. Adding to it is cheap; the point
is that removing one has to be deliberate.
"""

from __future__ import annotations

import importlib

import pytest

# Helpers that moved out of `handler.py` and are re-exported from it. Anything
# that imported them from here has to keep working.
RELOCATED = (
    "MAX_INLINE_FILE_MB",
    "MINERU_VERSION",
    "_MINERU_AVAILABLE",
    "_build_debug",
    "_build_tarball_bytes",
    "_build_zip_bytes",
    "_collect_gpu_info",
    "_concurrency_modifier",
    "_detect_format",
    "_find_model_dir",
    "_jobs_processed",
    "_maybe_progress",
    "_measure_output_bytes",
    "_note_shutdown",
    "_on_sigterm",
    "_package_inline",
    "_package_s3",
    "_package_tarball",
    "_pages_processed_total",
    "_probe_allowed",
    "_probe_filesystem",
    "_record_degradation",
    "_record_job",
    "_refresh_lock",
    "_refresh_thresholds",
    "_resolve_input_bytes",
    "_run_mineru",
    "_shutting_down",
    "_validate_input",
)

# What RunPod itself calls, which is the only part outside this repo's control.
ENTRY_POINTS = ("handler", "_bootstrap_main")


@pytest.mark.parametrize("name", RELOCATED + ENTRY_POINTS)
def test_handler_still_exposes_the_name(name: str) -> None:
    module = importlib.import_module("handler")
    assert hasattr(module, name), (
        f"handler.{name} is part of the back-compat surface and no longer exists. "
        f"If it moved, re-export it there -- repointing its test at the new module "
        f"makes the suite green and the promise false."
    )


def test_the_shutdown_event_is_the_object_the_lifecycle_module_mutates() -> None:
    """Not merely present: the same object.

    A copy would satisfy `hasattr` and then diverge the moment either side set it,
    which is the failure mode a name-only check cannot see. The event and the
    counters are the two places that matters.
    """
    import handler

    from worker import lifecycle

    assert handler._shutting_down is lifecycle._shutting_down
    assert handler._refresh_lock is lifecycle._refresh_lock


def test_the_relocated_helpers_are_the_same_callables() -> None:
    """Each alias resolves to the function that moved, not to a wrapper around it.

    Worth asserting because a re-export written as a small forwarding function
    would pass every other test here while breaking `monkeypatch.setattr` on the
    module that owns it.
    """
    import handler

    from worker import envelope, lifecycle

    assert handler._package_inline is envelope._package_inline
    assert handler._measure_output_bytes is envelope._measure_output_bytes
    assert handler._record_job is lifecycle._record_job
