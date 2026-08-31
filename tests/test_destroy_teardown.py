"""Rerunning a half-finished teardown has to reach whatever is still there.

`destroy.py` deletes an endpoint and then a template. If the endpoint delete
succeeds and the template delete fails -- a transient 5xx, a dropped
connection -- the operator's fix is to run the same command again. That rerun
asks RunPod to scale an endpoint that no longer exists, gets a 404, and used to
stop there: the template it was rerun *for* was never reached, and stayed
registered until someone removed the endpoint id from the command by hand.

The distinction that makes the retry work is between "already absent", which is
the desired end state, and any other failure, which may mean the endpoint is
still running and still billing. The second must keep stopping the script --
that behaviour is load-bearing, and it is why this file asserts both directions.

The other tests for this script read its source with `ast`. These run it, which
is the only layer where the order of the two deletes and the exit code are
observable together.
"""

from __future__ import annotations

import io
import sys
import urllib.error
import urllib.request

import pytest

import destroy

API_KEY = "test-key"
ENDPOINT_ID = "ep123"
TEMPLATE_ID = "tpl456"


class _FakeResponse(io.BytesIO):
    def __init__(self, status: int = 204) -> None:
        super().__init__(b"")
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _run(monkeypatch: pytest.MonkeyPatch, *, endpoint_status: int) -> tuple[int, list[str]]:
    """Run `destroy.main()` against a fake API. Returns its exit code and the
    paths it called, in order."""
    called: list[str] = []

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        called.append(f"{request.method} {request.full_url.split('/v1')[-1]}")
        if "/endpoints/" in request.full_url and endpoint_status not in (200, 204):
            raise urllib.error.HTTPError(
                request.full_url,
                endpoint_status,
                "fake",
                {},
                io.BytesIO(b'{"error":"fake"}'),
            )
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("RUNPOD_API_KEY", API_KEY)
    monkeypatch.setattr(
        sys,
        "argv",
        ["destroy.py", "--endpoint-id", ENDPOINT_ID, "--template-id", TEMPLATE_ID],
    )
    return destroy.main(), called


def test_an_already_absent_endpoint_still_reaches_the_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rerun this exists for."""
    code, called = _run(monkeypatch, endpoint_status=404)
    assert any(f"/templates/{TEMPLATE_ID}" in c for c in called), (
        f"the template was never reached: {called}"
    )
    # Nothing is left to do and nothing failed, so a CI teardown reads success.
    assert code == 0


def test_a_failure_that_may_leave_the_endpoint_running_still_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The direction that must not regress: a 5xx says nothing about whether the
    endpoint is gone, and an endpoint still up is still billing. Continuing to
    the template here would report a teardown that half happened."""
    code, called = _run(monkeypatch, endpoint_status=500)
    assert code == 1
    assert not any("/templates/" in c for c in called), (
        f"a possibly-live endpoint was left behind while the template was deleted: {called}"
    )


def test_the_ordinary_teardown_deletes_both_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard on the two above: if the happy path stopped working, an assertion
    about *where* a failure stops would still pass."""
    code, called = _run(monkeypatch, endpoint_status=204)
    assert code == 0
    joined = " | ".join(called)
    assert f"PATCH /endpoints/{ENDPOINT_ID}" in joined       # scaled to zero first
    assert f"DELETE /endpoints/{ENDPOINT_ID}" in joined
    assert f"DELETE /templates/{TEMPLATE_ID}" in joined
    assert joined.index("/endpoints/") < joined.index("/templates/")
