"""The parts of a response that are about the response rather than the parse.

Whether a probe is allowed, what the debug block carries, how much was actually
shipped. Each is small, and each is the kind of thing that gets quietly wrong
because nobody owns it -- the egress measurement in particular reads from the
per-file entry, and a change to the response shape moves it.
"""

from __future__ import annotations

import os
from typing import Any

import runpod

from pathlib import Path

from runpod_doc_worker.obs import debug as _debug
from runpod_doc_worker.obs import logging as _logging
from runpod_doc_worker.transport import package as _package

from worker import harness as _harness

# -----------------------------------------------------------------------------
# Probe policy
# -----------------------------------------------------------------------------
#
# Who may ask this endpoint for its filesystem layout is this worker's call.
# The payload names container paths and the model-source env values, and only a
# worker knows whether its callers are its own operators. The harness supplies
# the dump and reads no variable of its own, so this name belongs to this repo
# and cannot be renamed by a dependency release.

_PROBE_NOT_DISABLED = ("0", "false", "no", "off")


def _probe_allowed() -> bool:
    """Whether `probe: true` is answered on this endpoint.

    On unless MINERU_DISABLE_PROBE says otherwise, which is what this endpoint
    has always done and what the troubleshooting guide points someone to when
    a Cached Models setup is not being found.

    An unrecognised value denies rather than allows. An operator who typed
    something into this variable meant to turn the probe off, and a typo should
    not be what publishes a filesystem dump.
    """
    value = os.environ.get("MINERU_DISABLE_PROBE", "").strip().lower()
    if not value:
        return True
    return value in _PROBE_NOT_DISABLED


# -----------------------------------------------------------------------------
# Progress + debug envelope
# -----------------------------------------------------------------------------

def _maybe_progress(job: dict, data: dict) -> None:
    """Best-effort progress update. Tests / sync clients without a job id
    shouldn't fail just because we tried to surface progress."""
    try:
        runpod.serverless.progress_update(job, data)
    except Exception as e:  # noqa: BLE001
        _logging.debug("progress_update failed", error=repr(e))


def _build_debug(phase_ms: dict[str, int], gpu_info: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "gpu": gpu_info,
        "model_dir": _debug.find_model_dir(),
        "phase_ms": phase_ms,
        **extra,
    }


def _measure_output_bytes(response: dict[str, Any], transport: str) -> int:
    """Approximate bytes shipped to the caller, for the egress metrics.

    Reads from ``response["results"][0]`` — the per-file entry — because the
    payload-carrying keys (``tarball_b64``, ``markdown``, ``images``,
    ``bucket_bytes``) live there in the unified response shape.

    Per-transport sizing:
      * tarball_b64 — the b64 string IS the payload; len() is exact.
      * inline      — markdown text + image bytes dominate the JSON-encoded
                      response; sum those (json overhead for content_list/
                      middle is ignored). Cheap and within ~10% of the true
                      response size on real documents.
      * s3          — package_s3 records the uploaded tarball size in
                      `bucket_bytes`; the worker shipped exactly that.
    Returns 0 when the response shape doesn't include the expected fields
    (e.g. an empty parse or a failure response with no `results`) so the
    histogram doesn't get a misleading zero sample for "no output produced."
    """
    results = response.get("results") or []
    if not results:
        return 0
    entry = results[0] if isinstance(results[0], dict) else {}
    if transport == "tarball_b64":
        tb = entry.get("tarball_b64")
        return len(tb) if isinstance(tb, str) else 0
    if transport == "s3":
        return int(entry.get("bucket_bytes") or 0)
    if transport == "inline":
        md = entry.get("markdown") or ""
        images = entry.get("images") or {}
        md_bytes = len(md.encode("utf-8")) if isinstance(md, str) else 0
        image_bytes = sum(
            len(v) for v in images.values() if isinstance(v, str)
        ) if isinstance(images, dict) else 0
        return md_bytes + image_bytes
    return 0


def _package_inline(
    output_dir: Path, basename: str, formats: Any = None
) -> dict[str, Any]:
    """Inline packaging with this worker's manifest bound.

    The harness reads whatever manifest it is handed; which files MinerU
    writes is this repo's to declare, so the binding happens here rather
    than at each call site. See :mod:`worker.harness`.
    """
    return _package.package_inline(
        output_dir, basename, _harness.MANIFEST, formats=formats
    )
