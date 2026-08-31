"""Refusing a response the gateway would discard, as this worker configures it.

The refusal itself lives in `runpod_doc_worker.transport.response_size` and is
tested there. What is asserted here is the half that belongs to this repository
and was not covered anywhere: that this worker *turns the refusal on*, and that
when it fires the explanation reaches the caller instead of a job reported
COMPLETED with no output.

Both halves are needed. `ENFORCE_RESPONSE_CAP` defaults to false in the harness
— deliberately, so adopting a release cannot change what an existing worker
returns — so the two assignments in `worker/harness.py` are the entire reason
this endpoint refuses anything at all. Delete them and every test in the suite
still passed before this file existed.

The cap is lowered rather than fed a real 18 MB payload: `measure_entry_bytes`
walks a string character by character, so asserting against the shipped 20 MB
would spend seconds of a suite that runs in three. What the constant *is* stays
the harness's business; what this worker does when a response exceeds it is
this file's.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from runpod_doc_worker.transport import response_size

import handler

# `%PDF-1.4\n` — the source bytes never reach a parser here, only the schema.
PDF_B64 = "JVBERi0xLjQK"

# One Cyrillic character is two UTF-8 bytes and six once JSON-escaped, which is
# the gap the measurement exists to close.
CYRILLIC = "д"


def _fake_parse(monkeypatch, *, markdown: str) -> None:
    """Stand in for MinerU, writing one markdown artefact of a chosen size."""

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):  # noqa: ARG001
        out = work_dir / "fake-out"
        out.mkdir()
        (out / f"{basename}.md").write_text(markdown, encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)


def _run(**input_overrides) -> dict:
    job = {"input": {"file_b64": PDF_B64, "basename": "doc", **input_overrides}}
    return asyncio.run(handler.handler(job))


# -----------------------------------------------------------------------------
# The configuration this repository owns
# -----------------------------------------------------------------------------

def test_this_worker_turns_the_refusal_on():
    """`import handler` must leave the cap enforced.

    Asserted through the module the packaging path reads, not through
    `worker.harness`, because a correct assignment to the wrong module would
    satisfy the latter and leave the endpoint silently dropping responses.
    """
    assert response_size.ENFORCE_RESPONSE_CAP is True


def test_the_refusal_can_name_this_engine_s_heaviest_artefact():
    """Without this the message suggests "a shorter formats list" and leaves the
    caller to work out which format is the bulk of a scan."""
    assert response_size.BULKY_ARTIFACT == "middle.json"


# -----------------------------------------------------------------------------
# What the caller gets when it fires
# -----------------------------------------------------------------------------

@pytest.fixture
def oversized_result(monkeypatch) -> dict:
    monkeypatch.setattr(response_size, "MAX_RESPONSE_MB", 1)
    _fake_parse(monkeypatch, markdown="x" * 1_000_000)
    return _run(transport="inline", formats=["markdown"])


def test_an_undeliverable_response_is_refused_rather_than_sent(oversized_result):
    assert oversized_result["ok"] is False
    # The alternative this exists to prevent is a caller holding a response that
    # looks like a success and carries nothing.
    assert "results" not in oversized_result


def test_the_refusal_reaches_the_caller_in_the_error_field(oversized_result):
    """`redact.compact` caps the error at 2000 characters and the message is
    ~700, so the whole explanation survives the trip. A future change to either
    number is what this asserts against."""
    error = oversized_result["error"]
    assert error.startswith("ResponseTooLargeError:")
    assert "past the" in error and "MB" in error


def test_the_refusal_says_how_to_get_the_output_anyway(oversized_result):
    """An error that only says "too large" leaves the caller guessing, so each
    of the three ways out is part of the contract."""
    error = oversized_result["error"]
    assert "middle.json" in error          # drop the heaviest format
    assert 'transport="s3"' in error       # a presigned URL instead of bytes
    assert "start_page" in error           # a bounded page range
    # And why it was refused here rather than delivered and dropped.
    assert "COMPLETED" in error


def test_an_ordinary_response_is_left_alone(monkeypatch):
    """The shipped cap, unpatched. A refusal that fired on a normal parse would
    break every job on the endpoint, so the negative case is the important one."""
    _fake_parse(monkeypatch, markdown="# heading\n\nbody\n")
    result = _run(transport="inline", formats=["markdown"])
    assert result["ok"] is True
    assert result["results"][0]["markdown"] == "# heading\n\nbody\n"


# -----------------------------------------------------------------------------
# Measured how the gateway measures
# -----------------------------------------------------------------------------

def test_escaped_length_decides_not_utf8_length(monkeypatch):
    """A Cyrillic parse is more than twice its byte size once serialised.

    Counting UTF-8 bytes would let this response through to be dropped: 200k
    Cyrillic characters are 400 KB of UTF-8, comfortably inside the budget, and
    1.2 MB of `\\uXXXX` escapes in the body the gateway actually measures.
    """
    monkeypatch.setattr(response_size, "MAX_RESPONSE_MB", 1)
    _fake_parse(monkeypatch, markdown=CYRILLIC * 200_000)
    result = _run(transport="inline", formats=["markdown"])

    assert len((CYRILLIC * 200_000).encode()) < response_size.budget_bytes("inline")
    assert result["ok"] is False
    assert "ResponseTooLargeError" in result["error"]


def test_the_same_character_count_in_ascii_is_delivered(monkeypatch):
    """The other half of the pair: what was refused above is the escaping, not
    the length. Without this a cap set far too low would pass the test above."""
    monkeypatch.setattr(response_size, "MAX_RESPONSE_MB", 1)
    _fake_parse(monkeypatch, markdown="d" * 200_000)
    result = _run(transport="inline", formats=["markdown"])
    assert result["ok"] is True
    assert len(result["results"][0]["markdown"]) == 200_000


# -----------------------------------------------------------------------------
# The documented exemption
# -----------------------------------------------------------------------------

def test_s3_returns_a_url_so_the_cap_does_not_apply(monkeypatch):
    """s3 ships a presigned URL, so the response weighs the same whatever the
    parse produced. Named in the refusal as a way out, which only holds if an
    oversized parse really does succeed through it."""
    import boto3  # noqa: PLC0415

    class _FakeS3:
        def put_object(self, **kwargs):
            pass

        def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803, ARG002
            return f"https://bucket.example/{Params['Key']}?signature=x"

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3())
    for var, val in (
        ("BUCKET_ENDPOINT_URL", "https://bucket.example"),
        ("BUCKET_NAME", "parses"),
        ("BUCKET_ACCESS_KEY_ID", "id"),
        ("BUCKET_SECRET_ACCESS_KEY", "secret"),
    ):
        monkeypatch.setenv(var, val)
    monkeypatch.setattr(response_size, "MAX_RESPONSE_MB", 1)
    _fake_parse(monkeypatch, markdown="x" * 1_000_000)

    result = _run(transport="s3")
    assert result["ok"] is True
    entry = result["results"][0]
    assert entry["tarball_url"].startswith("https://bucket.example/")
    # The whole point of the exemption: the response is a URL, not the bytes.
    assert len(json.dumps(entry)) < 4096
