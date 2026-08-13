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


# Anything URL-shaped inside a longer message.
#
# The scheme is anchored with a lookbehind so a long run of ordinary characters
# is examined once rather than once per offset — without it, every position in
# such a run starts a fresh scan to the end of the string, which is quadratic in
# the message length. Messages quote whatever value the caller sent, so the
# length is theirs to choose.
#
# A URL runs to whitespace or a quote. Characters like `,` `)` `]` are part of a
# query or a path as often as they are prose punctuation around a URL, so they
# are consumed here and trimmed off the end afterwards; stopping the match at
# them instead would leave the rest of a query string — the part worth
# dropping — sitting outside the match.
_URL_RE = re.compile(r"""(?<![a-zA-Z0-9+.\-])[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s'"<>]+""")

# Punctuation that ends a sentence or closes a bracket around a URL. Trimmed
# from the match, reduced-URL emitted, then put back.
_TRAILING_PUNCT = ".,;:!?)]}"

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
    # The bracketed alternative keeps an IPv6 literal host together — `[^/?#]*`
    # alone stops at the first `:` group separator inside the brackets and the
    # match then fails to describe the authority at all.
    m = re.match(
        r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://(\[[^\]]*\][^/?#]*|[^/?#]*)([^?#]*)", url
    )
    if not m:
        return url
    scheme, authority, path = m.group(1), m.group(2), m.group(3)
    host = authority.rpartition("@")[2]
    if len(path) > _MAX_PATH_CHARS:
        path = path[:_MAX_PATH_CHARS] + "..."
    return f"{scheme}://{host}{path}"


def _reduce_match(m: "re.Match[str]") -> str:
    """Reduce one matched URL, handing back any punctuation that followed it."""
    token = m.group(0)
    url = token.rstrip(_TRAILING_PUNCT)
    return compact_url(url) + token[len(url):]


def compact(text: str, *, limit: int = DEFAULT_LIMIT) -> str:
    """Return ``text`` with its URLs reduced and its length capped."""
    if not text:
        return text
    original_len = len(text)
    # Only the head can survive the cap, so that is all that gets scanned. An
    # error message quotes whatever the caller sent — which can be as long as
    # the request allows — and this runs on the failure path of a live job.
    over_budget = original_len > limit * 4
    head = text[: limit * 4] if over_budget else text
    out = _URL_RE.sub(_reduce_match, head)
    if over_budget or len(out) > limit:
        out = out[:limit] + f"... ({original_len - limit} more characters)"
    return out
