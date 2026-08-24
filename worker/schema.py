"""Input schema (rp_validator) + cross-field validation."""

from __future__ import annotations

import os
import re
from typing import Any

from runpod.serverless.utils.rp_validator import validate

from runpod_doc_worker import config as _config
from runpod_doc_worker.contract import artifacts as _artifacts
from runpod_doc_worker.transport import net as _net
from runpod_doc_worker.transport import package as _package

from worker.harness import MANIFEST

# Suffix of the operator flag that turns the outbound-target policy on for the
# per-job `server_url`. Off by default: see the reasoning at the call site.
ENFORCE_TARGET_POLICY = "ENFORCE_TARGET_POLICY"


# Both come from where the behaviour is rather than being restated here: a
# transport this worker accepts but the harness cannot pack, or a format the
# schema admits but no artifact produces, would be a contract that validates
# and then fails.
VALID_TRANSPORTS = _package.VALID_TRANSPORTS

# Declaration order in the manifest is the canonical output order — used as
# the default when `formats` is omitted, and as the iteration order for
# deduplication.
VALID_FORMATS: tuple[str, ...] = tuple(_artifacts.keys(MANIFEST))

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

# `basename` becomes the stem of every artefact MinerU writes and of the
# archive entries built from them, so an unbounded one only fails once
# something tries to create the file. 128 characters is far above any real
# document name.
MAX_BASENAME_LEN = 128

# The longest suffix the worker appends to `basename` when writing an artefact
# — it is one of the manifest's patterns, and the longest of them, so it sets
# the longest filename a job produces. A test keeps the two in step.
LONGEST_ARTEFACT_SUFFIX = "_content_list_v2.json"

# Filesystems bound a path component in bytes, not characters, and the charset
# rule above accepts unicode alphanumerics: 80 CJK characters already pass the
# character limit while producing a name over this once the suffix is added.
# Checked here so an over-long name is reported against the field rather than
# surfacing as ENAMETOOLONG partway through writing output.
MAX_OUTPUT_NAME_BYTES = 255

# `lang` is a MinerU script/language code (e.g. "en", "ch", "east_slavic").
# All of them are short ASCII identifiers, so anything else is a caller
# mistake worth reporting here rather than passing down for MinerU to
# rediscover several imports later.
# Matched with fullmatch(), not match(): `$` also matches just before a final
# newline, so "en\n" would otherwise pass and travel on to MinerU as a code.
LANG_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,32}")

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


def _max_pages_per_job() -> int:
    """Largest page range a single job may ask for; 0 means no ceiling.

    Read per job (like the refresh thresholds in handler.py) so an operator
    can tune it without a redeploy. Off by default: the endpoint's execution
    timeout is the backstop that has always applied, and a ceiling here is
    for operators who would rather a too-large request be turned away up
    front than spend GPU minutes on it.
    """
    try:
        return max(0, int(os.environ.get("MINERU_MAX_PAGES_PER_JOB", "0")))
    except ValueError:
        return 0


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
    if len(basename) > MAX_BASENAME_LEN:
        _fail(
            f"basename must be at most {MAX_BASENAME_LEN} characters; "
            f"got {len(basename)}"
        )
    longest_name = len(f"{basename}{LONGEST_ARTEFACT_SUFFIX}".encode())
    if longest_name > MAX_OUTPUT_NAME_BYTES:
        _fail(
            f"basename is too long for the filenames it produces: with "
            f"{LONGEST_ARTEFACT_SUFFIX!r} appended it is {longest_name} bytes, "
            f"and the limit is {MAX_OUTPUT_NAME_BYTES}. Note the limit counts "
            f"bytes, so non-ASCII characters cost more than one each"
        )
    cleaned["basename"] = basename

    lang = cleaned.get("lang") or "en"
    if not LANG_PATTERN.fullmatch(lang):
        _fail(
            f"lang must be a short script/language code (letters, digits, "
            f"- or _); got {lang!r}"
        )
    cleaned["lang"] = lang

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

    # rp_validator skips its own type check when the value is already an
    # instance of the declared default's type, and `isinstance(True, int)` is
    # True — so `start_page: true` reached this resolver and was used as page 1.
    # Driven off INPUT_SCHEMA rather than a list of field names: a later int
    # field would otherwise arrive unguarded, and silently, because nothing
    # ties a hand-written list back to the declared types.
    for field, spec in INPUT_SCHEMA.items():
        if spec["type"] is int and isinstance(cleaned.get(field), bool):
            _fail(
                f"{field} must be an integer, not a boolean; "
                f"got {cleaned[field]!r}"
            )

    start_page = cleaned.get("start_page", 0) or 0
    if start_page < 0:
        _fail(f"start_page must be >= 0; got {start_page!r}")

    # end_page is 0-based and inclusive; any negative value is the "to the end
    # of the document" sentinel (-1 is the documented spelling). A bounded
    # range that ends before it starts is a caller mistake — MinerU would
    # return an empty parse and the caller would have nothing to go on.
    end_page = cleaned.get("end_page")
    if end_page is not None and end_page >= 0:
        if end_page < start_page:
            _fail(
                f"end_page must be >= start_page when set; "
                f"got start_page={start_page}, end_page={end_page}"
            )
        # Only an explicit range has a page count at this point — an
        # open-ended one isn't known until MinerU opens the document, so the
        # ceiling can't speak to it. Operators who set it are expected to pair
        # it with callers that request ranges (see the scaling guide).
        ceiling = _max_pages_per_job()
        requested = end_page - start_page + 1
        if ceiling and requested > ceiling:
            _fail(
                f"requested page range is {requested} pages; this endpoint "
                f"allows at most {ceiling} per job "
                f"(MINERU_MAX_PAGES_PER_JOB)"
            )

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

    # `server_url` can get the same outbound-target policy as `file_url`, but
    # **only when an operator asks for it**, and that default is a deliberate
    # decision rather than an oversight.
    #
    # The exposure is real. `server_url` is a *job input*, not an operator
    # setting — there is no env var for it — so the field is caller-controlled,
    # and any caller of an endpoint can name a loopback, link-local or internal
    # address and have the worker issue OpenAI-compatible requests there from
    # inside its network, cloud metadata endpoints included.
    #
    # Applying the policy by default was tried and reverted. Every existing
    # `*-http-client` deployment whose model server is on a private address —
    # which is the ordinary way to run one — would have started failing jobs that
    # had always succeeded, and this repo publishes from the commit title, so the
    # change would have arrived as a patch that operators discover through broken
    # jobs. A security default that ships as a surprise regression is not a good
    # trade for a field whose risk depends entirely on who can reach the endpoint.
    #
    # So: shape check by default, full policy when
    # MINERU_ENFORCE_TARGET_POLICY is set. Operators exposing an endpoint to
    # untrusted callers should set it; the guides say so. `check_target` is the
    # complete check — it calls `require_http_url` itself and honours
    # MINERU_ALLOW_LOCAL_FETCH, so the two flags compose: policy on, with a
    # documented exemption.
    if server_url := cleaned.get("server_url"):
        try:
            if _config.active().truthy(ENFORCE_TARGET_POLICY):
                _net.check_target(server_url, field="server_url")
            else:
                _net.require_http_url(server_url, field="server_url")
        except ValueError as e:
            _fail(str(e))

    if file_url := cleaned.get("file_url"):
        try:
            _net.require_http_url(file_url, field="file_url")
        except ValueError as e:
            _fail(str(e))

    return cleaned
