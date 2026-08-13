"""Failure text is reported in one shape across every sink."""

from __future__ import annotations

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
