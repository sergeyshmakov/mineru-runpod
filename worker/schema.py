"""Input schema (rp_validator) + cross-field validation."""

from __future__ import annotations

from typing import Any

from runpod.serverless.utils.rp_validator import validate


VALID_TRANSPORTS = {"tarball_b64", "inline", "s3"}

# Order is the canonical output order — used as the default when `formats`
# is omitted, and as the iteration order for deduplication.
VALID_FORMATS: tuple[str, ...] = ("markdown", "content_list", "middle", "images")

# MinerU 3.4.x backends. Validated at the handler boundary so callers get a
# friendly error instead of a deep MinerU stack trace.
VALID_BACKENDS = {
    "pipeline",
    "vlm-auto-engine",
    "vlm-http-client",
    "hybrid-auto-engine",
    "hybrid-http-client",
}

# MinerU's hybrid-backend "effort" lever (3.3+). `high` enables image/chart
# analysis at a speed cost; `medium` (MinerU's own default) disables it. Only
# meaningful for the hybrid-* backends — rejected on the others in
# validate_input. `None` means "let MinerU decide" and is not forwarded.
VALID_EFFORTS = {"medium", "high"}

# Archive container for the archive transports (tarball_b64, s3). The default
# preserves historical behavior (.tar.gz); "zip" exists for callers that need a
# real .zip — e.g. the MinerU-API compat client matching the cloud API's
# `full_zip_url`. No-op for the inline transport.
VALID_ARCHIVE_FORMATS = {"tar.gz", "zip"}


# rp_validator's `constraints` lambdas are silently ignored on some versions
# — we declare them anyway for documentation but never rely on them.
# Cross-field rules and per-field bounds are re-checked manually in
# validate_input() below.
INPUT_SCHEMA: dict[str, dict[str, Any]] = {
    "file_url":       {"type": str,  "required": False, "default": None},
    "file_b64":       {"type": str,  "required": False, "default": None},
    "volume_path":    {"type": str,  "required": False, "default": None},
    # When `probe` is true the handler skips MinerU entirely and returns a
    # filesystem dump of /runpod-volume + relevant env vars. Used to debug
    # RunPod Cached Models setup.
    "probe":          {"type": bool, "required": False, "default": False},
    "start_page":     {"type": int,  "required": False, "default": 0},
    "end_page":       {"type": int,  "required": False, "default": -1},
    "lang":           {"type": str,  "required": False, "default": "en"},
    "backend":        {"type": str,  "required": False, "default": "vlm-auto-engine"},
    "effort":         {"type": str,  "required": False, "default": None},
    "server_url":     {"type": str,  "required": False, "default": None},
    "formula_enable": {"type": bool, "required": False, "default": True},
    "table_enable":   {"type": bool, "required": False, "default": True},
    "transport":      {"type": str,  "required": False, "default": "tarball_b64"},
    "formats":        {"type": list, "required": False, "default": list(VALID_FORMATS)},
    "basename":       {"type": str,  "required": False, "default": "doc"},
    "archive_format": {"type": str,  "required": False, "default": "tar.gz"},
}


def _fail(msg: str) -> None:
    raise ValueError(f"input validation failed: {msg}")


def _normalize_formats(raw: Any) -> list[str]:
    """Validate + dedupe a `formats` list. Returns a list with first-seen order.

    rp_validator catches outer-type mismatches (e.g. ``formats: "markdown"``)
    before this function runs; the per-element and emptiness checks below
    are what we actually rely on. Duplicates collapse. Empty list is rejected —
    callers asking for nothing would get no useful response.
    """
    if raw is None:
        return list(VALID_FORMATS)
    if not isinstance(raw, list):
        # Defensive: rp_validator already rejects non-list values, but keep
        # this in case the SDK behavior changes.
        _fail(f"formats must be a list of strings; got {type(raw).__name__}")
    if not raw:
        _fail("formats must not be empty; omit the field to get all formats")
    seen: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            _fail(f"formats entries must be strings; got {type(item).__name__}")
        if item not in VALID_FORMATS:
            _fail(
                f"formats entry {item!r} not one of {list(VALID_FORMATS)}"
            )
        if item not in seen:
            seen.append(item)
    return seen


def validate_input(job_input: dict) -> dict:
    """Run rp_validator over the schema and enforce cross-field rules.

    Returns the cleaned input dict with defaults applied. Raises ValueError
    with an ``input validation failed: ...`` prefix on any rejection.
    """
    result = validate(job_input, INPUT_SCHEMA)
    if result.get("errors"):
        _fail("; ".join(result["errors"]))

    cleaned = result["validated_input"]

    basename = cleaned.get("basename") or "doc"
    if not basename or not all(c.isalnum() or c in "-_" for c in basename):
        _fail(f"basename must be alphanumeric (with - or _); got {basename!r}")

    # Write `transport` and `backend` back so downstream code can read them
    # with `cleaned[...]` (rather than `.get(...) or default`) regardless of
    # whether rp_validator's `default` mechanism populated the key.
    transport = cleaned.get("transport") or "tarball_b64"
    if transport not in VALID_TRANSPORTS:
        _fail(f"transport must be one of {sorted(VALID_TRANSPORTS)}; got {transport!r}")
    cleaned["transport"] = transport

    # `archive_format` selects the container for the archive transports
    # (tarball_b64 / s3). Inline ignores it. Default keeps the .tar.gz behavior.
    archive_format = cleaned.get("archive_format") or "tar.gz"
    if archive_format not in VALID_ARCHIVE_FORMATS:
        _fail(
            f"archive_format must be one of {sorted(VALID_ARCHIVE_FORMATS)}; "
            f"got {archive_format!r}"
        )
    cleaned["archive_format"] = archive_format

    cleaned["formats"] = _normalize_formats(cleaned.get("formats"))

    backend = cleaned.get("backend") or "vlm-auto-engine"
    if backend not in VALID_BACKENDS:
        _fail(f"backend must be one of {sorted(VALID_BACKENDS)}; got {backend!r}")
    cleaned["backend"] = backend

    # `effort` is a hybrid-backend-only lever. Left as None it isn't forwarded,
    # so MinerU applies its own default. When set we validate it and require a
    # hybrid-* backend, keeping the error next to the caller rather than deep in
    # MinerU. Written back so downstream reads `cleaned["effort"]` unconditionally.
    effort = cleaned.get("effort")
    if effort is not None:
        if effort not in VALID_EFFORTS:
            _fail(f"effort must be one of {sorted(VALID_EFFORTS)}; got {effort!r}")
        if not backend.startswith("hybrid-"):
            _fail(
                f"effort is only valid with a hybrid-* backend; got backend={backend!r}"
            )
    cleaned["effort"] = effort

    start_page = cleaned.get("start_page", 0) or 0
    if start_page < 0:
        _fail(f"start_page must be >= 0; got {start_page!r}")

    # XOR over the three transports. The handler also relies on this — only
    # one of file_url/file_b64/volume_path may be set per job.
    sources = [k for k in ("file_url", "file_b64", "volume_path") if cleaned.get(k)]
    if len(sources) != 1:
        _fail(
            f"must provide exactly one of file_url / file_b64 / volume_path "
            f"(got {sources!r})"
        )

    if backend.endswith("-http-client") and not cleaned.get("server_url"):
        _fail(
            f"backend={backend!r} requires `server_url` pointing at an "
            f"external vLLM OpenAI-compatible server"
        )

    return cleaned
