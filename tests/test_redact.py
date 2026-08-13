"""Failure text is reported in one shape across every sink."""

from __future__ import annotations

import pytest

from worker import redact


# -----------------------------------------------------------------------------
# compact_url
# -----------------------------------------------------------------------------

def test_compact_url_keeps_scheme_host_and_path():
    assert redact.compact_url("https://cdn.example.com/docs/report.pdf") == (
        "https://cdn.example.com/docs/report.pdf"
    )


def test_compact_url_keeps_a_port():
    assert redact.compact_url("http://vllm.internal:8000/v1") == (
        "http://vllm.internal:8000/v1"
    )


def test_compact_url_drops_query_and_fragment():
    out = redact.compact_url(
        "https://bucket.example.com/doc.tar.gz?X-Amz-Signature=abc123&e=900#frag"
    )
    assert out == "https://bucket.example.com/doc.tar.gz"


def test_compact_url_drops_credentials():
    out = redact.compact_url("https://user:secret@files.example.com/a.pdf")
    assert out == "https://files.example.com/a.pdf"


def test_compact_url_truncates_a_long_path():
    out = redact.compact_url("https://h.example.com/" + "p" * 200)
    assert out.startswith("https://h.example.com/")
    assert out.endswith("...")
    assert len(out) < 120


def test_compact_url_leaves_a_non_url_alone():
    assert redact.compact_url("not a url") == "not a url"


def test_compact_url_keeps_a_bracketed_ipv6_host_together():
    out = redact.compact_url("http://[2001:db8::1]:8000/v1/x?sig=SECRET")
    assert out == "http://[2001:db8::1]:8000/v1/x"


# -----------------------------------------------------------------------------
# compact
# -----------------------------------------------------------------------------

def test_compact_rewrites_a_url_inside_a_message():
    msg = (
        "ConnectTimeout: timed out for url "
        "'https://cdn.example.com/a.pdf?token=t0ps3cret&exp=99' after 120s"
    )
    out = redact.compact(msg)
    assert "token=" not in out
    assert "https://cdn.example.com/a.pdf" in out
    assert out.startswith("ConnectTimeout: timed out")
    assert out.endswith("after 120s")


def test_compact_rewrites_every_url_in_a_message():
    out = redact.compact(
        "redirected from http://a.example/x?k=1 to http://b.example/y?k=2"
    )
    assert out == "redirected from http://a.example/x to http://b.example/y"


def test_compact_leaves_url_free_text_untouched():
    msg = "ValueError: must provide exactly one of file_url / file_b64 / volume_path"
    assert redact.compact(msg) == msg


def test_compact_truncates_to_the_limit():
    out = redact.compact("x" * 300, limit=100)
    assert out.startswith("x" * 100)
    assert "200 more characters" in out


def test_compact_handles_empty_text():
    assert redact.compact("") == ""


# A URL's own characters overlap with the punctuation that wraps one in prose,
# so each of these used to end the match early and leave the rest of the query
# — the part worth dropping — outside it.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "GET https://h.example/p?a=1,2&sig=DEADBEEF failed",
            "GET https://h.example/p failed",
        ),
        (
            "for url 'https://b.example/Report%20(final).pdf?sig=SEC'",
            "for url 'https://b.example/Report%20(final).pdf'",
        ),
        (
            "connect to http://[2001:db8::1]:8000/v1/x?sig=SECRET failed",
            "connect to http://[2001:db8::1]:8000/v1/x failed",
        ),
        (
            "fetch (https://h.example/p?k=1) failed",
            "fetch (https://h.example/p) failed",
        ),
        (
            "see https://h.example/a/b.pdf?x=1.",
            "see https://h.example/a/b.pdf.",
        ),
        (
            "tried [https://h.example/a?k=1] and {https://i.example/b?k=2}",
            "tried [https://h.example/a] and {https://i.example/b}",
        ),
    ],
)
def test_compact_reduces_urls_with_adjacent_punctuation(text, expected):
    assert redact.compact(text) == expected


def test_compact_stays_fast_on_a_long_caller_supplied_value():
    """A rejected field's value is quoted back in the message, and the caller
    picks its length. Reducing must not scale worse than the text does."""
    import time

    long_value = "A" * 400_000
    start = time.perf_counter()
    out = redact.compact(f"lang must be a short code; got {long_value!r}")
    elapsed = time.perf_counter() - start
    assert len(out) < redact.DEFAULT_LIMIT + 60
    assert elapsed < 0.5, f"compact() took {elapsed:.2f}s on a 400k-char message"


def test_compact_reports_the_original_length_when_it_skips_the_tail():
    out = redact.compact("y" * 100_000, limit=1000)
    assert out.startswith("y" * 1000)
    assert "99000 more characters" in out


# -----------------------------------------------------------------------------
# Handler wiring — the response fields go through the same path.
# -----------------------------------------------------------------------------

def test_handler_failure_response_reports_compacted_text(monkeypatch):
    import asyncio

    import handler

    async def boom(*args, **kwargs):
        raise RuntimeError(
            "GET failed for 'https://files.example.com/doc.pdf?sig=abcdef123456'"
        )

    monkeypatch.setattr("worker.io.resolve_input_bytes", boom)
    result = asyncio.run(handler.handler({
        "id": "compact-test",
        "input": {"file_b64": "JVBERi0xLjQK"},
    }))

    assert result["ok"] is False
    assert "sig=" not in result["error"]
    assert "sig=" not in result["traceback"]
    assert "https://files.example.com/doc.pdf" in result["error"]
