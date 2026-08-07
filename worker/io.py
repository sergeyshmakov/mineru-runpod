"""Input transport + format detection.

Fetches raw bytes from whichever transport the caller used and tells the
caller what kind of file we got. Format-specific preprocessing (e.g.
image → PDF) lives next to MinerU in worker.parse.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx


# RunPod's gateway caps payloads at 10 MB (/run) and 20 MB (/runsync). The
# 20 MB ceiling is the largest a caller can realistically send inline; the
# handler enforces it defensively but oversized requests are normally
# rejected at the gateway before reaching us. For larger files, use
# file_url or volume_path.
MAX_INLINE_FILE_MB = 20

# Cap on file_url downloads. Larger than MAX_INLINE_FILE_MB because URL
# fetches aren't constrained by RunPod's gateway, but still bounded so a
# hostile or misconfigured URL can't OOM the worker.
MAX_URL_FILE_MB = 200

# httpx timeout for the file_url GET. Long enough for slow CDNs / large
# files; short enough that a dead URL doesn't pin a worker indefinitely.
URL_FETCH_TIMEOUT_SECONDS = 120.0


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
        async with httpx.AsyncClient(timeout=URL_FETCH_TIMEOUT_SECONDS) as client:
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
        raw = base64.b64decode(file_b64)
        if len(raw) > MAX_INLINE_FILE_MB * 1024 * 1024:
            raise ValueError(
                f"inline file too large ({len(raw) / 1024 / 1024:.1f} MB); "
                f"use file_url or volume_path for files > {MAX_INLINE_FILE_MB} MB"
            )
        return raw, "b64"

    volume_path = job_input["volume_path"]
    p = Path(volume_path)
    if not p.is_file():
        raise ValueError(f"volume_path not found inside container: {volume_path}")
    return p.read_bytes(), f"volume:{volume_path}"
