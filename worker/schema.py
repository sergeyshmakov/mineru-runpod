"""Input schema (rp_validator) + cross-field validation."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

from runpod.serverless.utils.rp_validator import validate

from runpod_doc_worker import config as _config
from runpod_doc_worker.contract import artifacts as _artifacts
from runpod_doc_worker.transport import net as _net
from runpod_doc_worker.transport import package as _package

from worker import inputs as _inputs
from worker.harness import DEFAULT_FORMATS, MANIFEST

# Suffix of the operator flag that turns the outbound-target policy on for the
# per-job `server_url`. Off by default: see the reasoning at the call site.
ENFORCE_TARGET_POLICY = "ENFORCE_TARGET_POLICY"

# Hosts `server_url` may name even when they resolve somewhere private. This
# exists because the obvious alternative is wrong: MINERU_ALLOW_LOCAL_FETCH lifts
# the address policy for *every* field and every target, so an operator who set
# it to reach their own private model server would simultaneously re-admit
# arbitrary private `server_url` values from any caller and switch off the same
# protection on `file_url`. An allowlist says the one thing the operator actually
# means — "my model server lives at this name" — and says nothing else.
ALLOWED_SERVER_HOSTS = "ALLOWED_SERVER_HOSTS"


# Both come from where the behaviour is rather than being restated here: a
# transport this worker accepts but the harness cannot pack, or a format the
# schema admits but no artifact produces, would be a contract that validates
# and then fails.
VALID_TRANSPORTS = _package.VALID_TRANSPORTS

# Declaration order in the manifest is the canonical output order — the
# iteration order for deduplication. The default when `formats` is omitted is
# the harness module's DEFAULT_FORMATS, a subset.
VALID_FORMATS: tuple[str, ...] = tuple(_artifacts.keys(MANIFEST))

# MinerU 4's quality tiers, in MinerU's own order (`mineru.types.TIERS`).
# Validated at the handler boundary so callers get a friendly error instead
# of a deep MinerU stack trace. `standard` is MinerU's default too.
VALID_TIERS = ("flash", "basic", "standard", "advanced")

# The tiers that run the VLM, and so the only ones a per-job `server_url`
# can mean anything to. flash and basic never load it.
VLM_TIERS = ("standard", "advanced")

# MinerU's `ocr_mode`: let it decide per page, trust the PDF's text layer, or
# OCR everything.
VALID_OCR_MODES = ("auto", "txt", "ocr")

# MinerU's page-range grammar, as its CLI, SDK and API share it: 1-based and
# inclusive, comma-separated, `rN` counting from the end (`r1` is the last
# page), `all` for everything. Checked here for shape only -- MinerU resolves
# the range against the document, which is the only place `r3` has a value.
_PAGE_REF = r"(?:[1-9][0-9]*|r[1-9][0-9]*)"
PAGE_RANGE_PATTERN = re.compile(rf"{_PAGE_REF}(?:-{_PAGE_REF})?(?:,{_PAGE_REF}(?:-{_PAGE_REF})?)*")

# `basename` becomes the stem of every artefact MinerU writes and of the
# archive entries built from them, so an unbounded one only fails once
# something tries to create the file. 128 characters is far above any real
# document name.
MAX_BASENAME_LEN = 128

# The longest suffix the worker appends to `basename` when writing an artefact
# — it is one of the manifest's patterns, and the longest of them, so it sets
# the longest filename a job produces. A test keeps the two in step.
LONGEST_ARTEFACT_SUFFIX = "_structured_content.json"

# A logical file name, as MinerU's own API takes one; only its extension is used.
MAX_FILE_NAME_LEN = 255

# Filesystems bound a path component in bytes, not characters, and the charset
# rule above accepts unicode alphanumerics: 80 CJK characters already pass the
# character limit while producing a name over this once the suffix is added.
# Checked here so an over-long name is reported against the field rather than
# surfacing as ENAMETOOLONG partway through writing output.
MAX_OUTPUT_NAME_BYTES = 255

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
    "tier":           {"type": str,  "required": False, "default": "standard"},
    "ocr_mode":       {"type": str,  "required": False, "default": "auto"},
    "page_range":     {"type": str,  "required": False, "default": ""},
    "file_name":      {"type": str,  "required": False, "default": None},
    "server_url":     {"type": str,  "required": False, "default": None},
    "transport":      {"type": str,  "required": False, "default": "tarball_b64"},
    "formats":        {"type": list, "required": False, "default": list(DEFAULT_FORMATS)},
    "basename":       {"type": str,  "required": False, "default": "doc"},
    "archive_format": {"type": str,  "required": False, "default": "tar.gz"},
}


def _fail(msg: str) -> None:
    raise ValueError(f"input validation failed: {msg}")


def _allowed_server_hosts() -> frozenset[str]:
    """Hosts an operator has declared their model server uses.

    Comma-separated, compared case-insensitively against the URL's host and
    nothing else — no suffix matching, so `evil-vllm.internal` does not satisfy
    an entry of `vllm.internal`. Read per job like the other operator knobs, so
    a change does not need a redeploy.
    """
    raw = _config.active().env(ALLOWED_SERVER_HOSTS)
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


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


def count_pages(page_range: str) -> int:
    """How many pages a validated `page_range` names, or -1 when that is unknown.

    Unknown means the whole document (an empty range) or any part counting from
    the end: both depend on a page count only MinerU reads. Overlaps count
    once, as MinerU de-duplicates them.
    """
    if not page_range:
        return -1
    pages: set[int] = set()
    for part in page_range.split(","):
        first, _, last = part.partition("-")
        if not first.isdigit() or (last and not last.isdigit()):
            return -1
        pages.update(range(int(first), int(last or first) + 1))
    return len(pages)


def _normalize_formats(raw: Any) -> list[str]:
    """Validate + dedupe a `formats` list. Returns a list with first-seen order.

    rp_validator catches outer-type mismatches (e.g. ``formats: "markdown"``)
    before this function runs; the per-element and emptiness checks below
    are what we actually rely on. Duplicates collapse. Empty list is rejected —
    callers asking for nothing would get no useful response.
    """
    if raw is None:
        return list(DEFAULT_FORMATS)
    if not isinstance(raw, list):
        # Defensive: rp_validator already rejects non-list values, but keep
        # this in case the SDK behavior changes.
        _fail(f"formats must be a list of strings; got {type(raw).__name__}")
    if not raw:
        _fail("formats must not be empty; omit the field for the default formats")
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

    # Write `transport`, `tier` and the rest back so downstream code can read
    # them with `cleaned[...]` (rather than `.get(...) or default`) regardless
    # of whether rp_validator's `default` mechanism populated the key.
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

    tier = cleaned.get("tier") or "standard"
    if tier not in VALID_TIERS:
        _fail(f"tier must be one of {list(VALID_TIERS)}; got {tier!r}")
    cleaned["tier"] = tier

    ocr_mode = cleaned.get("ocr_mode") or "auto"
    if ocr_mode not in VALID_OCR_MODES:
        _fail(f"ocr_mode must be one of {list(VALID_OCR_MODES)}; got {ocr_mode!r}")
    cleaned["ocr_mode"] = ocr_mode

    # rp_validator skips its own type check when the value is already an
    # instance of the declared default's type, and `isinstance(True, int)` is
    # True — so `start_page: true` once reached a resolver and was used as page
    # 1. Driven off INPUT_SCHEMA rather than a list of field names: a later int
    # field would otherwise arrive unguarded, and silently, because nothing
    # ties a hand-written list back to the declared types.
    for field, spec in INPUT_SCHEMA.items():
        if spec["type"] is int and isinstance(cleaned.get(field), bool):
            _fail(
                f"{field} must be an integer, not a boolean; "
                f"got {cleaned[field]!r}"
            )

    # Empty means the whole document, as it does to MinerU. `all` is MinerU's
    # spelling of the same thing and is normalised to it here, so the rest of
    # the worker has one way to say "no range". Whitespace around the commas is
    # a typing habit rather than a different range.
    page_range = "".join((cleaned.get("page_range") or "").split())
    if page_range.lower() == "all":
        page_range = ""
    if page_range:
        if not PAGE_RANGE_PATTERN.fullmatch(page_range):
            _fail(
                f"page_range must be 1-based pages or ranges separated by "
                f"commas, with rN counting from the end (e.g. '1-5,8' or "
                f"'r3-r1'); got {page_range!r}"
            )
        # A reversed absolute range is a caller mistake MinerU would reject
        # anyway, after the download; relative ends are only known to MinerU.
        for part in page_range.split(","):
            first, _, last = part.partition("-")
            if last and first.isdigit() and last.isdigit() and int(last) < int(first):
                _fail(f"page_range part {part!r} ends before it starts")
        # Only a range of absolute pages has a size at this point — one that
        # counts from the end isn't known until MinerU opens the document, so
        # the ceiling can't speak to it. Operators who set it are expected to
        # pair it with callers that request ranges (see the scaling guide).
        ceiling = _max_pages_per_job()
        requested = count_pages(page_range)
        if ceiling and requested > ceiling:
            _fail(
                f"requested page range is {requested} pages; this endpoint "
                f"allows at most {ceiling} per job "
                f"(MINERU_MAX_PAGES_PER_JOB)"
            )
    cleaned["page_range"] = page_range

    # `file_name` is a hint for formats content cannot settle (CSV against TSV,
    # an HTML fragment against plain text). It is a name, not a path, and only
    # its extension is ever used, so anything else in it is a caller mistake.
    if (file_name := cleaned.get("file_name")) is not None:
        if not 0 < len(file_name) <= MAX_FILE_NAME_LEN or any(
            c in "/\\" or not c.isprintable() for c in file_name
        ):
            _fail(
                f"file_name must be a file name (not a path) of at most "
                f"{MAX_FILE_NAME_LEN} characters; got {file_name!r}"
            )
        if _inputs.suffix_of(file_name) not in _inputs.PARSEABLE_SUFFIXES:
            _fail(
                f"file_name must end in an extension MinerU parses "
                f"({', '.join(sorted(_inputs.PARSEABLE_SUFFIXES))}); got {file_name!r}"
            )

    # XOR over the three transports. The handler also relies on this — only
    # one of file_url/file_b64/volume_path may be set per job.
    sources = [k for k in ("file_url", "file_b64", "volume_path") if cleaned.get(k)]
    if len(sources) != 1:
        _fail(
            f"must provide exactly one of file_url / file_b64 / volume_path "
            f"(got {sources!r})"
        )

    # A remote VLM replaces the local one, and only the VLM tiers have one to
    # replace. Accepting it on flash or basic would ship a field that silently
    # does nothing.
    if cleaned.get("server_url") and tier not in VLM_TIERS:
        _fail(
            f"server_url only applies to the {' and '.join(VLM_TIERS)} tiers, "
            f"which use a VLM; got tier={tier!r}"
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
    # untrusted callers should set it; the guides say so.
    #
    # An operator running a private model server names its host in
    # MINERU_ALLOWED_SERVER_HOSTS. The earlier version of this told them to set
    # MINERU_ALLOW_LOCAL_FETCH instead, which was bad advice: that flag lifts the
    # address policy globally, so it re-admitted arbitrary private `server_url`
    # values from any caller *and* disabled the same protection on `file_url`. The
    # allowlist grants exactly the one host the operator meant.
    #
    # Note `require_http_url` returns the host rather than the URL — the trap the
    # harness's AGENTS.md records. Wanted here, hence the name of the variable.
    if server_url := cleaned.get("server_url"):
        try:
            host = _net.require_http_url(server_url, field="server_url")
            # MinerU's own rule for a VLM endpoint (`VlmConfig.server_url`):
            # no credentials, query or fragment. Checked here so the job fails
            # before the download rather than at the first VLM call.
            parts = urlsplit(server_url)
            if parts.username is not None or parts.password is not None:
                raise ValueError("server_url must not carry credentials")
            if parts.query or parts.fragment:
                raise ValueError("server_url must not carry a query or fragment")
            if _config.active().truthy(ENFORCE_TARGET_POLICY):
                # Enforcement means the allow-list, not an address check.
                #
                # Checking where the host resolves cannot hold for this field: the
                # engine's own HTTP client resolves the name again and opens the
                # connection, so a host whose DNS answers publicly here can answer
                # privately there. `mineru_vl_utils` builds its `httpx.Client`
                # internally with no transport to inject, and pinning the address
                # would mean handing it a literal IP with a Host header -- which
                # fails certificate validation for any https target, the very
                # configuration a remote model server should use.
                #
                # So an enforcing endpoint requires the operator to name the hosts.
                # A name the operator chose is not subject to rebinding by a caller,
                # which is the whole difference. Without enforcement this field
                # keeps its shape check only, as documented.
                if host.lower() not in _allowed_server_hosts():
                    allowed = _config.active().env_name(ALLOWED_SERVER_HOSTS)
                    listed = sorted(_allowed_server_hosts())
                    raise ValueError(
                        f"server_url must name a host listed in {allowed}; got "
                        f"{host!r}"
                        + (f" (listed: {', '.join(listed)})" if listed else
                           f" ({allowed} is empty, so this endpoint accepts no "
                           f"per-job server_url)")
                    )
        except ValueError as e:
            _fail(str(e))

    if file_url := cleaned.get("file_url"):
        try:
            _net.require_http_url(file_url, field="file_url")
        except ValueError as e:
            _fail(str(e))

    return cleaned
