"""What the client says when the gateway drops an oversized response.

Found by running the worker for real against a scanned document. RunPod returned
`status: COMPLETED` with a normal executionTime and no `output` key at all --
the ~20 MB response cap had been exceeded and the reply said nothing about size.
The SDK surfaces that as `None`, and the client reported
`unexpected handler return type: <class 'NoneType'>`, which points a reader at
the handler rather than at the size of what they asked for.

The cap is documented, in the output-modes guide and a blog post. It was the
*error* that did not mention it, at the one moment someone is looking.
"""

from __future__ import annotations

import pytest

from mineru_client import MineruClient, MineruClientError
from mineru_client.client import _no_output_message


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


def test_the_message_names_every_way_out(
    client: MineruClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error that says what went wrong and not what to do next just moves the
    problem. All three remedies are real and were checked against the docs."""
    _drop_the_response(client, monkeypatch)
    with pytest.raises(MineruClientError) as caught:
        client.parse_document(file_url="https://example.com/scan.pdf")
    message = str(caught.value)
    assert 'transport="inline"' in message
    assert 'transport="s3"' in message
    assert "BUCKET_" in message, "s3 is useless without saying what it needs"
    assert "start_page" in message


def test_the_default_transport_is_called_out() -> None:
    """`tarball_b64` is the client default and the likeliest to trip the cap, so
    a caller who never chose a transport should be told which one they got."""
    assert 'transport="tarball_b64"' in _no_output_message("tarball_b64")
    assert "middle.json" in _no_output_message("inline")


def test_an_unknown_transport_still_produces_a_message() -> None:
    """The advice is per-transport, so a new transport must not KeyError here --
    the failure would replace a size explanation with a stack trace."""
    message = _no_output_message("something-new")
    assert "20 MB" in message and "something-new" in message


def test_a_non_dict_response_is_still_reported_as_a_type_error(
    client: MineruClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard on the narrowing: only `None` means a dropped response. A string
    or a list is a genuinely unexpected return and should not be explained away
    as a size problem."""
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
