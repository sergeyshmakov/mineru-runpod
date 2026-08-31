"""What an enforcing endpoint accepts for `server_url`, and why it is a list.

Two findings, one after the other.

The first: `MINERU_ALLOW_LOCAL_FETCH` exists so an operator can serve documents from
their own network, and `check_target` honoured it for every field -- so an endpoint
configured for a private document mirror also accepted any private `server_url` a
caller sent, cloud metadata included.

The second: checking where a host *resolves* cannot hold for this field at all. The
engine's HTTP client resolves the name again and opens the connection itself, so a
host answering publicly at validation can answer privately at connect time.
`mineru_vl_utils` builds its `httpx.Client` internally with no transport to inject,
and pinning the address would mean handing it a literal IP with a `Host` header --
which fails certificate validation for any https target, the configuration a remote
model server should be using.

So enforcement means the allow-list. A name the operator chose is not subject to
rebinding by a caller, which is the whole difference. Without enforcement the field
keeps its shape check only, as documented.

Resolution is stubbed. A test that let one of these through would open a real
socket, which took this suite from 3s to 24s once before.
"""

from __future__ import annotations

import pytest

from runpod_doc_worker.transport import net
from worker import schema

HOSTS = {
    "metadata.internal": ["169.254.169.254"],
    "private.internal": ["10.0.0.5"],
    "vllm.internal": ["10.0.0.9"],
    "public.example": ["93.184.216.34"],
}


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(net, "_addresses_for", lambda host, port: HOSTS.get(host, []))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "MINERU_ENFORCE_TARGET_POLICY",
        "MINERU_ALLOWED_SERVER_HOSTS",
        "MINERU_ALLOW_LOCAL_FETCH",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def enforcing(monkeypatch: pytest.MonkeyPatch):
    """An endpoint that has turned the policy on, with the operator's document
    bypass also set -- the configuration the first hole needed."""
    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    monkeypatch.setenv("MINERU_ALLOW_LOCAL_FETCH", "1")


def _parse(server_url: str) -> dict:
    return schema.validate_input(
        {
            "file_url": "https://example.com/a.pdf",
            "backend": "vlm-http-client",
            "server_url": server_url,
        }
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/v1",
        "http://metadata.internal/v1",
        "http://private.internal/v1",
    ],
)
def test_a_caller_cannot_name_a_private_model_server(url: str, enforcing) -> None:
    """The first finding. The operator's document bypass is set, and it does not
    reach this field."""
    with pytest.raises(ValueError, match="MINERU_ALLOWED_SERVER_HOSTS"):
        _parse(url)


def test_an_unlisted_public_host_is_refused_under_enforcement(enforcing) -> None:
    """The second finding, and the contract change it required.

    A public host used to pass on the strength of where it resolved. That check is
    exactly what DNS rebinding defeats when the engine reconnects, so enforcement
    no longer offers it -- the host has to be one the operator named.
    """
    with pytest.raises(ValueError, match="MINERU_ALLOWED_SERVER_HOSTS"):
        _parse("https://public.example/v1")


def test_an_empty_allow_list_says_so(enforcing) -> None:
    """An operator who turns enforcement on without a list has accidentally
    disabled per-job model servers. The message says that rather than looking like
    a rejection of the particular URL."""
    with pytest.raises(ValueError) as caught:
        _parse("https://public.example/v1")
    assert "is empty" in str(caught.value)
    assert "accepts no per-job server_url" in str(caught.value)


def test_a_listed_host_is_accepted_even_when_private(
    enforcing, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The legitimate case, and the reason the list exists: an operator running
    their own VLM on a private address names it, and rebinding is irrelevant
    because the name is theirs."""
    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", "vllm.internal")
    assert _parse("http://vllm.internal/v1")["server_url"] == "http://vllm.internal/v1"


def test_the_list_is_matched_exactly(
    enforcing, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No suffix matching, so an attacker-registered lookalike does not satisfy an
    entry. Asserted here because the allow-list is now the whole defence."""
    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", "vllm.internal")
    with pytest.raises(ValueError, match="MINERU_ALLOWED_SERVER_HOSTS"):
        _parse("http://evil-vllm.internal/v1")


def test_without_enforcement_the_field_keeps_its_shape_check_only() -> None:
    """The documented default. An endpoint that has not turned the policy on trusts
    its callers, and this change must not quietly start refusing their jobs."""
    assert _parse("https://vlm.example.com/v1")["server_url"] == (
        "https://vlm.example.com/v1"
    )


def test_a_malformed_url_is_still_refused_without_enforcement() -> None:
    """The shape check is not conditional on the policy."""
    with pytest.raises(ValueError, match="server_url"):
        _parse("vlm.example.com/v1")


def test_the_operator_document_bypass_is_untouched(enforcing) -> None:
    """What `ALLOW_LOCAL_FETCH` is for. If this broke, every endpoint serving its
    own private mirror would stop working -- worse than either hole."""
    net.check_target("http://private.internal/report.pdf", field="file_url")
