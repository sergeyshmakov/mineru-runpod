"""The client-side opt-in for fetching an archive from a private address.

The shared reader refuses a `tarball_url` whose socket lands on an address that is
not globally routable. That is the right default here -- the URL arrives in a
*response*, so without the check a worker could make the machine running this code
open connections inside its own network.

It also broke a deployment the docs support: an S3-compatible store on a private
network, a self-hosted MinIO beside the endpoint being the documented case, serves
presigned URLs on exactly those addresses. `MINERU_CLIENT_ALLOW_PRIVATE_FETCH`
restores it for operators who mean it.

Asserted on the policy rather than through a fetch on purpose. A test that lets a
URL past the check opens a real socket, and one that did this on the worker side
took its suite from 3s to 24s sitting in a connect timeout. The env var is what is
under test, not urllib.
"""

from __future__ import annotations

import pytest
from runpod_doc_client import limits

from mineru_client import client as client_module

ENV = "MINERU_CLIENT_ALLOW_PRIVATE_FETCH"


@pytest.fixture(autouse=True)
def _isolate_the_shared_flag(monkeypatch: pytest.MonkeyPatch):
    """The flag is a module global in a shared package -- leaking it would let one
    test silently license private fetches for every test that ran after it."""
    monkeypatch.setattr(limits, "ALLOW_PRIVATE_FETCH_TARGETS", False)
    monkeypatch.delenv(ENV, raising=False)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " on "])
def test_the_opt_in_licenses_a_private_target(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV, value)
    client_module._apply_fetch_policy()
    assert limits.ALLOW_PRIVATE_FETCH_TARGETS is True


def test_the_default_leaves_the_policy_in_place() -> None:
    client_module._apply_fetch_policy()
    assert limits.ALLOW_PRIVATE_FETCH_TARGETS is False


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_a_value_that_is_not_truthy_is_not_an_opt_in(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`=0` has to mean off. An env var read as "present therefore true" is the
    reading that makes people set it to 0 and get the opposite of what they typed."""
    monkeypatch.setenv(ENV, value)
    client_module._apply_fetch_policy()
    assert limits.ALLOW_PRIVATE_FETCH_TARGETS is False


def test_a_caller_who_set_the_flag_directly_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy only ever widens.

    The refusal message tells the caller to set this flag themselves, so the
    absence of the env var must not undo what they were just told to do.
    """
    monkeypatch.setattr(limits, "ALLOW_PRIVATE_FETCH_TARGETS", True)
    client_module._apply_fetch_policy()
    assert limits.ALLOW_PRIVATE_FETCH_TARGETS is True


def test_the_policy_is_applied_before_the_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The wiring, not the policy: unit tests on `_apply_fetch_policy` all pass
    whether or not anything calls it."""
    order: list[str] = []

    monkeypatch.setenv(ENV, "1")
    monkeypatch.setattr(
        client_module,
        "download",
        lambda url: order.append(f"download:{limits.ALLOW_PRIVATE_FETCH_TARGETS}")
        or b"",
    )
    monkeypatch.setattr(
        client_module, "extract", lambda data, dest: order.append("extract") or tmp_path
    )

    client_module.MineruClient.save_s3_tarball(
        {"tarball_url": "https://bucket.example/out.tar.gz"}, tmp_path
    )
    assert order == ["download:True", "extract"], (
        "the opt-in has to be in effect by the time the fetch runs"
    )


def test_the_compat_client_applies_the_same_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """api_compat holds its own download path, which is how it came to hold its own
    copy of the whole reader in the first place."""
    from mineru_client import api_compat

    seen: list[bool] = []
    monkeypatch.setenv(ENV, "1")
    monkeypatch.setattr(
        api_compat,
        "download",
        lambda url: seen.append(limits.ALLOW_PRIVATE_FETCH_TARGETS) or b"",
    )
    monkeypatch.setattr(api_compat, "extract", lambda data, dest: tmp_path)

    api_compat._download_and_extract("https://bucket.example/out.zip", tmp_path)
    assert seen == [True]
