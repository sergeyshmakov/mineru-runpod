"""What a job's input bytes are, and which tier MinerU will actually run on them.

MinerU 4 decides the format itself, from content (file signatures plus a
content-type model), and decides the tier too: only PDFs and images go through
the four quality tiers. Every other format MinerU accepts is parsed natively at
`flash`, whatever was requested. The worker asks the same questions first so a
response can say what actually ran rather than echo what was asked for.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from runpod_doc_worker.transport import io as _io

from worker import parse as _parse

# MinerU's own lists (`mineru.filetypes`). Restated rather than imported
# because the worker must start, validate and fail politely on a machine
# without MinerU; the engine CI job compares them with the installed release.
TIERED_SUFFIXES = frozenset({"pdf", "png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "jp2"})
NATIVE_SUFFIXES = frozenset({
    "doc", "docx", "ppt", "pptx", "xls", "xlsx", "rtf", "odt", "ods", "odp",
    "html", "htm", "shtml", "mhtml", "mht", "csv", "tsv", "epub", "ofd",
})
PARSEABLE_SUFFIXES = TIERED_SUFFIXES | NATIVE_SUFFIXES

# The harness's coarse labels, for the one case MinerU's detector is absent:
# nothing can parse then, and the label only has to carry the request as far
# as the failure response.
_COARSE_SUFFIXES = {"pdf": "pdf", "image": "png", "ooxml": "docx"}


def suffix_of(name: str | None) -> str:
    """The lower-cased extension of a file name, without the dot ("" if none)."""
    if not name or "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower()


def name_hint(job_input: dict[str, Any]) -> str | None:
    """The file name the input arrived under, for the detector to break ties with.

    The caller's `file_name` first; otherwise the last segment of the URL path
    or of `volume_path`. Only ever used as a hint, never as a path.
    """
    if name := job_input.get("file_name"):
        return name
    if url := job_input.get("file_url"):
        name = PurePosixPath(unquote(urlsplit(url).path)).name
    elif path := job_input.get("volume_path"):
        name = PurePosixPath(path.replace("\\", "/")).name
    return name or None


def detect_suffix(file_bytes: bytes, hint: str | None = None) -> str | None:
    """The file suffix MinerU would parse these bytes as, or None if it would not.

    Uses MinerU's own detector, so the answer is the one the parse will act on.
    Content decides for binary formats (a PDF named `.docx` is still a PDF); the
    `hint` decides only where content cannot, as between CSV, TSV, an HTML
    fragment and plain text, which MinerU otherwise reads as text and refuses.
    """
    hinted = suffix_of(hint)
    if not _parse.MINERU_AVAILABLE:
        coarse = _COARSE_SUFFIXES.get(_io.detect_format(file_bytes))
        return coarse or (hinted if hinted in PARSEABLE_SUFFIXES else None)
    from mineru.parser.file_type import guess_suffix_by_bytes  # type: ignore[import-not-found]  # noqa: PLC0415

    try:
        # Only the extension is the caller's; the name handed on is ours.
        suffix = guess_suffix_by_bytes(file_bytes, f"input.{hinted}" if hinted else None).lower()
    except Exception:  # noqa: BLE001 - an undetectable input is a rejection, not a crash
        return None
    return suffix if suffix in PARSEABLE_SUFFIXES else None


def effective_tier(suffix: str, requested: str) -> str:
    """The tier MinerU runs for this suffix: the requested one, or flash for native formats."""
    return requested if suffix in TIERED_SUFFIXES else "flash"
