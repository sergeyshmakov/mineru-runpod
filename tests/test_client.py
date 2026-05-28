"""Client-side unit tests. No GPU, no MinerU, no network."""

from __future__ import annotations

import base64
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from mineru_client import MineruClient, MineruClientError


def _wrap(entry: dict) -> dict:
    """Build a worker-shaped wrapper around a single result entry."""
    return {
        "ok": True,
        "elapsed_seconds": 0.1,
        "mineru_version": "fake",
        "results": [entry],
    }


@pytest.fixture
def fake_endpoint(monkeypatch):
    """Patch runpod.Endpoint so MineruClient never reaches the network."""
    import runpod

    class _FakeEndpoint:
        def __init__(self, endpoint_id):
            self.endpoint_id = endpoint_id
            self.last_payload = None
            # next_result is mutated by tests before calling parse_document().
            self.next_result = _wrap({
                "basename": "doc",
                "source": "b64",
                "pages_requested": 0,
                "tarball_b64": "",
            })

        def run_sync(self, payload, timeout):  # noqa: ARG002
            self.last_payload = payload
            return self.next_result

    monkeypatch.setattr(runpod, "Endpoint", _FakeEndpoint)
    return _FakeEndpoint


def test_requires_endpoint_id():
    with pytest.raises(ValueError, match="endpoint_id is required"):
        MineruClient(endpoint_id="")


def test_requires_api_key():
    os.environ.pop("RUNPOD_API_KEY", None)
    with pytest.raises(ValueError, match="api_key not provided"):
        MineruClient(endpoint_id="ep-1")


def test_constructs_with_explicit_api_key(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="secret")
    assert client.endpoint_id == "ep-1"


def test_constructs_with_env_api_key(monkeypatch, fake_endpoint):
    monkeypatch.setenv("RUNPOD_API_KEY", "secret-env")
    client = MineruClient(endpoint_id="ep-1")
    assert client.endpoint_id == "ep-1"


def test_parse_document_rejects_no_source(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    with pytest.raises(ValueError, match="exactly one"):
        client.parse_document()


def test_parse_document_rejects_multiple_sources(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    with pytest.raises(ValueError, match="exactly one"):
        client.parse_document(file_url="https://x", file_b64="abc")


def test_parse_document_forwards_options(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    client._endpoint.next_result = _wrap({
        "basename": "custom",
        "source": "url:https://example.com/p.pdf",
        "pages_requested": 11,
        "markdown": "# md",
    })
    client.parse_document(
        file_url="https://example.com/p.pdf",
        start_page=10,
        end_page=20,
        lang="ja",
        backend="vlm-auto-engine",
        formula_enable=False,
        table_enable=False,
        transport="inline",
        basename="custom",
    )
    payload = client._endpoint.last_payload
    assert payload["file_url"] == "https://example.com/p.pdf"
    assert payload["start_page"] == 10
    assert payload["end_page"] == 20
    assert payload["lang"] == "ja"
    assert payload["backend"] == "vlm-auto-engine"
    assert payload["formula_enable"] is False
    assert payload["table_enable"] is False
    assert payload["transport"] == "inline"
    assert payload["basename"] == "custom"
    # No legacy `return` key — the field is gone.
    assert "return" not in payload
    # `formats` omitted from kwargs → omitted from wire payload (server default applies).
    assert "formats" not in payload


def test_parse_document_forwards_formats_list(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    client.parse_document(
        file_url="https://x", transport="inline", formats=["markdown", "images"]
    )
    assert client._endpoint.last_payload["formats"] == ["markdown", "images"]


def test_parse_document_wraps_bare_format_string(fake_endpoint):
    """Client sugar: a bare string for formats becomes a one-element list on the wire."""
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    client.parse_document(file_url="https://x", transport="inline", formats="markdown")
    assert client._endpoint.last_payload["formats"] == ["markdown"]


def test_parse_document_raises_on_handler_error(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    client._endpoint.next_result = {"ok": False, "error": "boom"}
    with pytest.raises(MineruClientError, match="boom"):
        client.parse_document(file_url="https://x")


def test_parse_document_from_file_inlines_bytes(fake_endpoint, tmp_path):
    pdf = tmp_path / "tiny.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    MineruClient.parse_document_from_file(client, pdf)
    payload = client._endpoint.last_payload
    assert "file_b64" in payload
    assert base64.b64decode(payload["file_b64"]) == b"%PDF-1.4\n%%EOF"


def test_parse_document_http_client_requires_server_url(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    with pytest.raises(ValueError, match="server_url"):
        client.parse_document(file_url="https://x", backend="vlm-http-client")


def test_parse_document_forwards_s3_transport(fake_endpoint):
    client = MineruClient(endpoint_id="ep-1", api_key="x")
    client.parse_document(file_url="https://x", transport="s3")
    assert client._endpoint.last_payload["transport"] == "s3"


# -----------------------------------------------------------------------------
# .first() helper
# -----------------------------------------------------------------------------

def test_first_returns_first_entry():
    entry = {"basename": "doc", "markdown": "# hi"}
    wrapper = _wrap(entry)
    assert MineruClient.first(wrapper) is wrapper["results"][0]


def test_first_raises_on_missing_results():
    with pytest.raises(MineruClientError, match="no `results`"):
        MineruClient.first({"ok": True})


def test_first_raises_on_empty_results():
    with pytest.raises(MineruClientError, match="no `results`"):
        MineruClient.first({"ok": True, "results": []})


# -----------------------------------------------------------------------------
# save_tarball — accepts wrapper or entry
# -----------------------------------------------------------------------------

def _make_tarball_b64(name: str = "doc.md", data: bytes = b"# hello\n") -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_save_tarball_requires_tarball_field(tmp_path):
    with pytest.raises(MineruClientError, match="no tarball_b64"):
        MineruClient.save_tarball({"ok": True}, tmp_path)


def test_save_tarball_from_wrapper(tmp_path):
    encoded = _make_tarball_b64()
    wrapper = _wrap({"basename": "doc", "source": "b64", "pages_requested": 1, "tarball_b64": encoded})
    dest = MineruClient.save_tarball(wrapper, tmp_path / "out")
    assert (Path(dest) / "doc.md").read_bytes() == b"# hello\n"


def test_save_tarball_from_entry(tmp_path):
    """save_tarball also accepts an entry directly (post-.first call)."""
    encoded = _make_tarball_b64()
    entry = {"basename": "doc", "tarball_b64": encoded}
    dest = MineruClient.save_tarball(entry, tmp_path / "out")
    assert (Path(dest) / "doc.md").read_bytes() == b"# hello\n"


# -----------------------------------------------------------------------------
# save_inline — accepts wrapper or entry
# -----------------------------------------------------------------------------

def _make_inline_entry() -> dict:
    return {
        "basename": "x",
        "markdown": "# md\n",
        "content_list": [{"type": "text", "text": "hi"}],
        "middle": {"k": 1},
        "images": {"a.png": base64.b64encode(b"\x89PNG").decode("ascii")},
    }


def test_save_inline_from_wrapper(tmp_path):
    dest = MineruClient.save_inline(_wrap(_make_inline_entry()), tmp_path / "out", basename="x")
    assert (dest / "x.md").read_text() == "# md\n"
    assert json.loads((dest / "x_content_list.json").read_text())[0]["text"] == "hi"
    assert json.loads((dest / "x_middle.json").read_text())["k"] == 1
    assert (dest / "images" / "a.png").read_bytes() == b"\x89PNG"


def test_save_inline_from_entry(tmp_path):
    dest = MineruClient.save_inline(_make_inline_entry(), tmp_path / "out", basename="x")
    assert (dest / "x.md").read_text() == "# md\n"


def test_save_inline_requires_markdown_field(tmp_path):
    with pytest.raises(MineruClientError, match="no markdown"):
        MineruClient.save_inline({"ok": True}, tmp_path)


def test_save_inline_skips_missing_formats(tmp_path):
    """When `formats=["markdown"]` filtered out the other keys, save_inline
    must not error — it simply writes whatever's present and doesn't create
    an empty images/ directory."""
    entry = {"basename": "x", "markdown": "# md\n"}
    dest = MineruClient.save_inline(entry, tmp_path / "out", basename="x")
    assert (dest / "x.md").read_text() == "# md\n"
    assert not (dest / "x_content_list.json").exists()
    assert not (dest / "x_middle.json").exists()
    assert not (dest / "images").exists()


def test_save_inline_defaults_basename_to_entry_basename(tmp_path):
    """When `basename` is omitted, save_inline picks it up from the entry."""
    entry = {"basename": "from-entry", "markdown": "# md\n"}
    dest = MineruClient.save_inline(entry, tmp_path / "out")
    assert (dest / "from-entry.md").read_text() == "# md\n"


def test_save_inline_explicit_basename_overrides_entry(tmp_path):
    """An explicit `basename` kwarg wins over the entry's value."""
    entry = {"basename": "from-entry", "markdown": "# md\n"}
    dest = MineruClient.save_inline(entry, tmp_path / "out", basename="override")
    assert (dest / "override.md").read_text() == "# md\n"
    assert not (dest / "from-entry.md").exists()


def test_save_inline_empty_images_dict_skips_dir(tmp_path):
    """An entry with images={} (e.g. doc had no extracted images) should
    not leave an empty images/ directory either."""
    entry = {
        "basename": "x",
        "markdown": "# md\n",
        "content_list": [],
        "middle": {},
        "images": {},
    }
    dest = MineruClient.save_inline(entry, tmp_path / "out", basename="x")
    assert (dest / "x.md").read_text() == "# md\n"
    assert not (dest / "images").exists()


# -----------------------------------------------------------------------------
# save_s3_tarball — accepts wrapper or entry
# -----------------------------------------------------------------------------

def test_save_s3_tarball_requires_url_field(tmp_path):
    with pytest.raises(MineruClientError, match="no tarball_url"):
        MineruClient.save_s3_tarball({"ok": True}, tmp_path)


def test_save_s3_tarball_downloads_and_extracts_from_wrapper(tmp_path):
    src = tmp_path / "fake.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        md_data = b"# from s3\n"
        info = tarfile.TarInfo("doc.md")
        info.size = len(md_data)
        tar.addfile(info, io.BytesIO(md_data))
    src.write_bytes(buf.getvalue())

    wrapper = _wrap({"basename": "doc", "tarball_url": src.as_uri(), "bucket_bytes": 1})
    dest = MineruClient.save_s3_tarball(wrapper, tmp_path / "out")
    assert (Path(dest) / "doc.md").read_bytes() == b"# from s3\n"


def test_save_s3_tarball_downloads_and_extracts_from_entry(tmp_path):
    src = tmp_path / "fake.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        md_data = b"# from s3\n"
        info = tarfile.TarInfo("doc.md")
        info.size = len(md_data)
        tar.addfile(info, io.BytesIO(md_data))
    src.write_bytes(buf.getvalue())

    entry = {"basename": "doc", "tarball_url": src.as_uri()}
    dest = MineruClient.save_s3_tarball(entry, tmp_path / "out")
    assert (Path(dest) / "doc.md").read_bytes() == b"# from s3\n"
