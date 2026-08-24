"""The REST calls that replaced three nonexistent SDK functions.

`destroy.py` looked `delete_endpoint` up with `getattr` and, finding nothing,
printed to stderr and returned 0 — a teardown that exits successfully having
deleted nothing, which a CI job believes while the endpoint keeps billing.
`deploy.py` could only report the execution timeout it could not pass.

Both failure modes came from calling an SDK on faith, so the first test here
holds the SDK to what it actually exposes. The rest drive the replacement
against a fake `urlopen`, which is the only layer where the URL, method, headers
and body can all be asserted without touching the network.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

import runpod_rest


API_KEY = "test-key"


class FakeResponse(io.BytesIO):
    def __init__(self, status: int, payload: bytes = b"") -> None:
        super().__init__(payload)
        self.status = status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[urllib.request.Request]:
    """Capture requests; answer every one with 204."""
    captured: list[urllib.request.Request] = []

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        captured.append(request)
        return FakeResponse(204)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


# -----------------------------------------------------------------------------
# Why this module exists at all
# -----------------------------------------------------------------------------

def test_the_sdk_still_cannot_do_any_of_this() -> None:
    """The guard. If a future SDK grows these, prefer them and delete this
    module — but find out from a failing test, not from a stack trace."""
    import inspect

    import runpod

    assert not hasattr(runpod, "delete_endpoint")
    assert not hasattr(runpod, "delete_template")
    parameters = inspect.signature(runpod.create_endpoint).parameters
    assert not any("execution" in name for name in parameters)


# -----------------------------------------------------------------------------
# The request the API actually receives
# -----------------------------------------------------------------------------

def test_delete_endpoint_targets_the_documented_route(sent: list) -> None:
    runpod_rest.delete_endpoint("ep123", api_key=API_KEY)
    request = sent[0]
    assert request.full_url == "https://rest.runpod.io/v1/endpoints/ep123"
    assert request.method == "DELETE"
    assert request.get_header("Authorization") == f"Bearer {API_KEY}"
    assert request.data is None


def test_delete_template_targets_the_documented_route(sent: list) -> None:
    runpod_rest.delete_template("tpl456", api_key=API_KEY)
    assert sent[0].full_url == "https://rest.runpod.io/v1/templates/tpl456"
    assert sent[0].method == "DELETE"


def test_scale_to_zero_sets_both_bounds(sent: list) -> None:
    """RunPod documents min and max at zero as the delete precondition. One
    without the other does not satisfy it."""
    runpod_rest.scale_to_zero("ep123", api_key=API_KEY)
    request = sent[0]
    assert request.method == "PATCH"
    assert json.loads(request.data) == {"workersMin": 0, "workersMax": 0}
    assert request.get_header("Content-type") == "application/json"


def test_the_execution_timeout_is_sent_in_milliseconds(sent: list) -> None:
    """The field is executionTimeoutMs and the CLI flag is in seconds. Getting
    this factor wrong would cap a job at 3.6 seconds instead of an hour."""
    runpod_rest.set_execution_timeout("ep123", seconds=3600, api_key=API_KEY)
    assert json.loads(sent[0].data) == {"executionTimeoutMs": 3_600_000}


# -----------------------------------------------------------------------------
# Failures have to be loud — this is the money path
# -----------------------------------------------------------------------------

def test_an_http_error_becomes_a_runpod_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"no such endpoint"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(runpod_rest.RunpodApiError, match="404"):
        runpod_rest.delete_endpoint("missing", api_key=API_KEY)


def test_the_error_carries_the_response_body() -> None:
    """A bare status tells an operator nothing about why their endpoint is still
    running and still billing."""
    with pytest.MonkeyPatch.context() as m:
        def fake_urlopen(request, timeout=None):  # noqa: ARG001
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {},
                io.BytesIO(b'{"error":"workers must be zero"}'),
            )

        m.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(runpod_rest.RunpodApiError, match="workers must be zero"):
            runpod_rest.delete_endpoint("ep123", api_key=API_KEY)


def test_an_unreachable_api_becomes_a_runpod_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        raise urllib.error.URLError("dns failure")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(runpod_rest.RunpodApiError, match="could not reach RunPod"):
        runpod_rest.delete_endpoint("ep123", api_key=API_KEY)


def test_an_unexpected_success_status_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(202)
    )
    with pytest.raises(runpod_rest.RunpodApiError, match="202"):
        runpod_rest.delete_endpoint("ep123", api_key=API_KEY)


def test_a_json_body_is_returned_and_an_empty_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: FakeResponse(200, b'{"id":"ep123"}'),
    )
    assert runpod_rest.call("PATCH", "/endpoints/ep123", api_key=API_KEY) == {
        "id": "ep123"
    }

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(204)
    )
    assert runpod_rest.call("DELETE", "/endpoints/ep123", api_key=API_KEY) is None


# -----------------------------------------------------------------------------
# The teardown script's own contract
# -----------------------------------------------------------------------------
#
# The old failure was not a crash. `destroy.py` looked the delete up with getattr,
# found nothing, printed to stderr and returned 0 — so `destroy.py && echo ok` in
# a CI teardown reported success on an endpoint that was still running.

def _destroy_source() -> str:
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1].joinpath("destroy.py").read_text(
            encoding="utf-8"
        )
    )


def test_destroy_no_longer_reaches_into_the_sdk() -> None:
    """Checked over the parsed tree, not the text: the module docstring names the
    old behaviour deliberately, and a substring assertion would trip on it."""
    import ast

    tree = ast.parse(_destroy_source())
    reached = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "runpod"
    }
    assert reached == set(), f"destroy.py still reaches into the SDK: {reached}"


def test_a_failed_teardown_exits_non_zero() -> None:
    """The one outcome that must never look like success."""
    source = _destroy_source()
    assert "was NOT deleted" in source
    assert "return 1" in source


def test_destroy_scales_to_zero_before_deleting() -> None:
    """RunPod documents both worker bounds at zero as the delete precondition, and
    the script has claimed to do this since it was written without doing it."""
    source = _destroy_source()
    assert source.index("scale_to_zero") < source.index("runpod_rest.delete_endpoint")


def test_deploy_applies_the_execution_timeout() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1].joinpath("deploy.py").read_text(
            encoding="utf-8"
        )
    )
    assert "runpod_rest.set_execution_timeout" in source
    assert "execution_timeout_ms=" not in source, (
        "create_endpoint has no such parameter; passing it raises TypeError"
    )
    assert "NOT applied" not in source, "that text described the old behaviour"
