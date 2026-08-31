"""What this client says when the gateway drops an oversized response.

Found by running the worker against a real scanned document: RunPod returned
`status: COMPLETED` with a normal executionTime and no `output` key at all. The
~20 MB response cap had been exceeded, the gateway dropped the reply, and nothing
in it named size. The SDK surfaces that as `None`, which this client reported as
`unexpected handler return type: <class 'NoneType'>`.

The message itself now lives in `runpod_doc_client.describe_dropped_response`,
shared with the sibling worker, because the transports and the cap are the
harness's and only the name of the heaviest artifact differs. So the assertions
here are about *this package's* wiring — that `None` is recognised, that the
engine-specific artifact is passed, and that a genuinely unexpected return is
still reported as one. What the message says is the harness's own test.
"""

from __future__ import annotations

import pytest

from mineru_client import MineruClient, MineruClientError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> MineruClient:
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")
    return MineruClient(endpoint_id="ep-1", api_key="test-key")


def _drop_the_response(client: MineruClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gateway that reports success and returns nothing, as observed."""
    monkeypatch.setattr(
        client._endpoint, "run_sync", lambda payload, timeout=None: None
    )


def test_a_dropped_response_names_the_size_cap(
    client: MineruClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _drop_the_response(client, monkeypatch)
    with pytest.raises(MineruClientError) as caught:
        client.parse_document(file_url="https://example.com/scan.pdf")
    message = str(caught.value)
    assert "carried no output" in message
    assert "20 MB" in message, "the cap is the whole point of the message"
    assert "NoneType" not in message, (
        "the old message named a Python type; a caller cannot act on that"
    )


def test_the_message_names_this_engine_s_bulky_artifact(
    client: MineruClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one part of the shared message this package supplies.

    `middle.json` carries per-character boxes and is the bulk of a scanned parse,
    so leaving it out of `formats` is the smallest change that usually fits. If the
    argument stopped being passed the message would still be sensible and this
    would be the only thing to notice.
    """
    _drop_the_response(client, monkeypatch)
    with pytest.raises(MineruClientError) as caught:
        client.parse_document(file_url="https://example.com/scan.pdf")
    assert "middle.json" in str(caught.value)


def test_a_non_dict_response_is_still_reported_as_a_type_error(
    client: MineruClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard on the narrowing: only `None` means a dropped response. A string
    or a list is a genuinely unexpected return and should not be explained away as
    a size problem."""
    monkeypatch.setattr(
        client._endpoint, "run_sync", lambda payload, timeout=None: "not a dict"
    )
    with pytest.raises(MineruClientError, match="unexpected handler return type"):
        client.parse_document(file_url="https://example.com/scan.pdf")


def test_a_filtered_formats_list_is_named_when_markdown_is_missing(
    tmp_path,
) -> None:
    """The second thing that cost the same reader a round trip: `formats` without
    "markdown" produces an entry the inline writer refuses, and the old message
    only asked whether the transport was right."""
    entry = {"basename": "scan", "content_list": [], "middle": {}}
    with pytest.raises(MineruClientError) as caught:
        MineruClient.save_inline({"results": [entry]}, tmp_path)
    message = str(caught.value)
    assert "formats" in message
    assert "content_list" in message, "say what did arrive"
