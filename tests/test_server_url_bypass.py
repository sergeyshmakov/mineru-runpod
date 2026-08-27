"""A caller cannot borrow the operator's local-fetch exemption for server_url.

`MINERU_ALLOW_LOCAL_FETCH` exists so an operator can serve documents from their own
network. It is scoped to the whole worker, and `check_target` honoured it for every
field -- so an endpoint configured for a private document mirror also accepted any
private `server_url` a caller sent, cloud metadata included, and the worker would
POST OpenAI-compatible requests there.

Reproduced before the fix, with both variables set as a real deployment would:

    server_url=http://169.254.169.254/v1   ACCEPTED
    server_url=http://127.0.0.1:8000/v1    ACCEPTED
    server_url=http://10.0.0.5/v1          ACCEPTED

`allow_local=False` holds the field to the policy while leaving the operator's own
document fetches exempt. An operator who genuinely runs a private model server
names it in `MINERU_ALLOWED_SERVER_HOSTS`, which is checked before this.

Resolution is stubbed. A test that let one of these through would open a real
socket, which took this suite from 3s to 24s once before.
"""

from __future__ import annotations

import pytest

from runpod_doc_worker.transport import net
from worker import schema

HOSTS = {
    "metadata.internal": ["169.254.169.254"],
    "loopback.internal": ["127.0.0.1"],
    "private.internal": ["10.0.0.5"],
    "vllm.internal": ["10.0.0.9"],
    "public.example": ["93.184.216.34"],
}


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(net, "_addresses_for", lambda host, port: HOSTS.get(host, []))


@pytest.fixture(autouse=True)
def _enforcing(monkeypatch: pytest.MonkeyPatch):
    """The configuration the hole needed: the operator's document bypass on, and
    the target policy enforced."""
    monkeypatch.setenv("MINERU_ALLOW_LOCAL_FETCH", "1")
    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    monkeypatch.delenv("MINERU_ALLOWED_SERVER_HOSTS", raising=False)


def _parse(server_url: str) -> dict:
    return schema.validate_input(
        {
            "file_url": "https://example.com/a.pdf",
            "backend": "vlm-http-client",
            "server_url": server_url,
        }
    )


@pytest.mark.parametrize(
    "host", ["metadata.internal", "loopback.internal", "private.internal"]
)
def test_a_caller_cannot_name_a_private_model_server(host: str) -> None:
    with pytest.raises(ValueError, match="publicly routable"):
        _parse(f"http://{host}/v1")


def test_the_refusal_does_not_suggest_the_variable_that_is_already_set() -> None:
    """The operator has `ALLOW_LOCAL_FETCH=1` and it does not apply here, so
    repeating it would send them to a switch they have already flipped."""
    with pytest.raises(ValueError) as caught:
        _parse("http://private.internal/v1")
    message = str(caught.value)
    assert "does not honour" in message
    assert "ALLOW_LOCAL_FETCH=1 to allow this" not in message


def test_a_public_model_server_is_still_accepted() -> None:
    """The guard on the narrowing: this must refuse private targets, not all of
    them."""
    assert _parse("http://public.example/v1")["server_url"] == (
        "http://public.example/v1"
    )


def test_an_allow_listed_private_host_is_still_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator who really does run a private model server names it. That path
    is checked before the address policy and is how the legitimate case works."""
    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", "vllm.internal")
    assert _parse("http://vllm.internal/v1")["server_url"] == "http://vllm.internal/v1"


def test_the_operator_document_bypass_is_untouched() -> None:
    """What `ALLOW_LOCAL_FETCH` is for. If this broke, every endpoint serving its
    own private mirror would stop working -- a worse outcome than the hole."""
    net.check_target("http://private.internal/report.pdf", field="file_url")
