"""One shape for the text the worker reports about a failure.

An error string from a job reaches three sinks: the job response's ``error`` /
``traceback`` fields, the stdout log line, and — when OTel export is
configured — the span event and log record mirrored to the collector. They
should all say the same thing, and that thing should be readable.

Two problems get in the way. Library exceptions quote the request they failed
on, so a message grows a URL's full query string and stops being comparable
between two runs of the same job — the interesting part ("connect timeout") is
buried behind a few hundred characters that differ every time. And a native
traceback can run long enough to dominate a log line or an exported record.

:func:`compact` fixes both: URLs collapse to scheme, host and path, and the
result is truncated to a stated budget. Same input, same output, whichever
sink is reading.
"""

from __future__ import annotations

import re


# Anything URL-shaped inside a longer message. Stops at whitespace and at the
# punctuation that usually wraps a URL quoted inside prose or a repr.
_URL_RE = re.compile(r"""[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s'"<>)\]},]+""")

# Default budget for a single message. Comfortably fits a real exception
# message and its context while keeping one log line readable.
DEFAULT_LIMIT = 2000

# Longest path kept from a URL before the rest is elided. Enough to recognise
# which object was being fetched without carrying a long signed path.
_MAX_PATH_CHARS = 60


def compact_url(url: str) -> str:
    """Reduce a URL to ``scheme://host[:port]/path``.

    Credentials, query and fragment come off: they are per-request detail that
    makes two reports of the same failure look different. The path is kept
    (truncated) because that is the part that identifies the document.
    """
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://([^/?#]*)([^?#]*)", url)
    if not m:
        return url
    scheme, authority, path = m.group(1), m.group(2), m.group(3)
    host = authority.rpartition("@")[2]
    if len(path) > _MAX_PATH_CHARS:
        path = path[:_MAX_PATH_CHARS] + "..."
    return f"{scheme}://{host}{path}"


def compact(text: str, *, limit: int = DEFAULT_LIMIT) -> str:
    """Return ``text`` with its URLs reduced and its length capped."""
    if not text:
        return text
    out = _URL_RE.sub(lambda m: compact_url(m.group(0)), text)
    if len(out) > limit:
        out = out[:limit] + f"... ({len(out) - limit} more characters)"
    return out
