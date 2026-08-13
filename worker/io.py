"""Input transport + format detection.

Fetches raw bytes from whichever transport the caller used and tells the
caller what kind of file we got. Format-specific preprocessing (e.g.
image → PDF) lives next to MinerU in worker.parse.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import httpx

from worker import net as _net


# RunPod's gateway caps payloads at 10 MB (/run) and 20 MB (/runsync). The
# 20 MB ceiling is the largest a caller can realistically send inline; the
# handler enforces it defensively but oversized requests are normally
# rejected at the gateway before reaching us. For larger files, use
# file_url or volume_path.
MAX_INLINE_FILE_MB = 20

# Same ceiling expressed in encoded characters, so an oversized payload is
# rejected by measuring the string we were handed instead of after allocating
# the decoded copy of it. Base64 costs 4 characters per 3 bytes; the 5%
# headroom absorbs padding and the line breaks some encoders insert.
MAX_INLINE_B64_CHARS = int((MAX_INLINE_FILE_MB * 1024 * 1024) / 3 * 4 * 1.05)

# Cap on file_url downloads. Larger than MAX_INLINE_FILE_MB because URL
# fetches aren't constrained by RunPod's gateway, but still bounded so a
# hostile or misconfigured URL can't OOM the worker.
MAX_URL_FILE_MB = 200

# httpx timeout for the file_url GET. Long enough for slow CDNs / large
# files; short enough that a dead URL doesn't pin a worker indefinitely.
URL_FETCH_TIMEOUT_SECONDS = 120.0

# Directories a `volume_path` input is expected to live under. The defaults
# cover the places a document can actually come from on a deployed worker:
# the network-volume mount (`/runpod-volume`, or `/workspace` when the
# operator mounts it there), files baked into the image (the Hub validator's
# fixture is at `/worker/test-fixture.pdf`), and the per-job temp tree.
# Operators who pre-stage a corpus somewhere else — or who want to narrow the
# worker to one subtree — set MINERU_VOLUME_ROOTS to a comma-separated list of
# absolute paths, which replaces this list.
DEFAULT_VOLUME_ROOTS: tuple[str, ...] = (
    "/runpod-volume",
    "/workspace",
    "/worker",
    "/tmp",
)


# Magic bytes for the input formats MinerU supports.
# - PDFs and Office docs pass straight to aio_do_parse (it auto-detects).
# - Images need preprocessing to single-page PDF via images_bytes_to_pdf_bytes.
_IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",        # JPEG
    b"GIF87a", b"GIF89a",   # GIF
    b"BM",                  # BMP
    b"II*\x00",             # TIFF little-endian
    b"MM\x00*",             # TIFF big-endian
    b"RIFF",                # WebP container (also AVI / WAV — rare as PDF inputs)
)
_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"  # DOCX / PPTX / XLSX (all OOXML) and ZIP itself


def detect_format(file_bytes: bytes) -> str:
    """Return one of: "pdf" | "image" | "ooxml" | "unknown".

    OOXML (DOCX/PPTX/XLSX) all start with the ZIP magic; MinerU's own
    `guess_suffix_by_bytes` inspects the archive's content-types to discriminate.
    We just flag "ooxml" and let MinerU decide which of the three it is.
    """
    if not file_bytes:
        return "unknown"
    if file_bytes.startswith(_PDF_MAGIC):
        return "pdf"
    if any(file_bytes.startswith(m) for m in _IMAGE_MAGIC):
        return "image"
    if file_bytes.startswith(_ZIP_MAGIC):
        return "ooxml"
    return "unknown"


def volume_roots() -> list[Path]:
    """Return the directories a `volume_path` may resolve inside.

    MINERU_VOLUME_ROOTS (comma-separated absolute paths) replaces
    DEFAULT_VOLUME_ROOTS when set; blank entries are ignored so a trailing
    comma or an accidentally-empty value falls back to the defaults.
    """
    raw = os.environ.get("MINERU_VOLUME_ROOTS", "")
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    return [Path(e) for e in (entries or DEFAULT_VOLUME_ROOTS)]


def resolve_volume_file(volume_path: str) -> Path:
    """Resolve a `volume_path` input to the file the worker will read.

    Resolving first (rather than reading the string as given) means a path
    that arrives with `..` segments, a trailing separator, or a symlink in the
    middle is compared in its canonical form — so the path we check is the
    path we open, and a mistyped input reports the root it landed outside of
    instead of quietly reading some unrelated file. Relative paths are
    rejected: `volume_path` has always been documented as absolute, and
    resolving one against the worker's cwd would be a coin flip.
    """
    p = Path(volume_path)
    if not p.is_absolute():
        raise ValueError(f"volume_path must be an absolute path; got {volume_path!r}")

    resolved = p.resolve()
    roots = volume_roots()
    for root in roots:
        try:
            r = root.resolve()
        except OSError:
            continue
        if resolved == r or r in resolved.parents:
            break
    else:
        raise ValueError(
            f"volume_path is outside the configured input roots "
            f"({', '.join(str(r) for r in roots)}): {volume_path}"
        )

    if not resolved.is_file():
        raise ValueError(f"volume_path not found inside container: {volume_path}")
    return resolved


def telemetry_source_kind(source_label: str) -> str:
    """Return a bounded, non-sensitive input-source label for telemetry."""
    kind = source_label.partition(":")[0]
    return kind if kind in {"url", "b64", "volume"} else "unknown"


async def resolve_input_bytes(job_input: dict) -> tuple[bytes, str]:
    """Return (file_bytes, source_label). Raises ValueError on a bad source.

    Enforces XOR over the three sources as a defensive check — the schema
    validates this too, but this function is safe to use standalone (and the
    test suite calls it directly). Format is auto-detected downstream by
    `detect_format` / MinerU itself.
    """
    provided = [k for k in ("file_url", "file_b64", "volume_path") if job_input.get(k)]
    if len(provided) != 1:
        raise ValueError(
            f"must provide exactly one of file_url / file_b64 / volume_path "
            f"(got {provided!r})"
        )

    if file_url := job_input.get("file_url"):
        max_bytes = MAX_URL_FILE_MB * 1024 * 1024
        # The checked transport is the client's default, and whatever the
        # environment wants proxied is mounted over it. Supplying a transport
        # is what stops httpx reading the proxy environment itself, so that
        # reading is done for it — otherwise an operator whose egress needs a
        # proxy would have every download attempt a direct connection and fail.
        #
        # Requests the environment does not proxy — another scheme, or a
        # NO_PROXY host — fall through the mounts to the default and stay on the
        # checked path. Requests that are proxied open their socket to the
        # proxy, which resolves the document host itself; where those end up is
        # the proxy's to decide and its policy to enforce.
        #
        # The hook runs per request either way, which includes every redirect
        # httpx follows on its own.
        async with httpx.AsyncClient(
            timeout=URL_FETCH_TIMEOUT_SECONDS,
            transport=_net.CheckedTargetTransport(field="file_url"),
            mounts=_net.environment_proxy_mounts(),
            event_hooks={"request": [_net.request_hook]},
        ) as client:
            async with client.stream("GET", file_url, follow_redirects=True) as resp:
                resp.raise_for_status()
                # Pre-check Content-Length when the server provided one so we
                # can fail before pulling bytes. Some CDNs omit it; for those
                # we enforce the cap incrementally below.
                cl = resp.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > max_bytes:
                    raise ValueError(
                        f"file_url body too large ({int(cl) / 1024 / 1024:.1f} MB); "
                        f"max is {MAX_URL_FILE_MB} MB"
                    )
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise ValueError(
                            f"file_url body exceeded {MAX_URL_FILE_MB} MB while streaming"
                        )
                return bytes(buf), f"url:{file_url}"

    if file_b64 := job_input.get("file_b64"):
        if len(file_b64) > MAX_INLINE_B64_CHARS:
            raise ValueError(
                f"inline file too large (encoded length {len(file_b64)} chars); "
                f"use file_url or volume_path for files > {MAX_INLINE_FILE_MB} MB"
            )
        raw = base64.b64decode(file_b64)
        if len(raw) > MAX_INLINE_FILE_MB * 1024 * 1024:
            raise ValueError(
                f"inline file too large ({len(raw) / 1024 / 1024:.1f} MB); "
                f"use file_url or volume_path for files > {MAX_INLINE_FILE_MB} MB"
            )
        return raw, "b64"

    volume_path = job_input["volume_path"]
    resolved = resolve_volume_file(volume_path)
    # Label keeps the caller's own spelling of the path — it's what they sent
    # and what they'll match against in their own logs.
    return resolved.read_bytes(), f"volume:{volume_path}"
