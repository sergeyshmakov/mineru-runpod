"""The MinerU 4 seam: format detection, effective tier, artifact layout, recycle.

No GPU, no MinerU. Where the code reaches into MinerU, a fake stands in at the
same import path, so what is tested is the worker's half of the contract: the
names it writes, the tier it reports, the files it refuses to write. The real
engine runs in the CPU engine job (`pytest -m engine`).
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

import handler
from worker import inputs, lifecycle, models, parse, schema

PDF = b"%PDF-1.4\nfake"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 8


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w/>")
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Format and tier
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("data", "suffix"),
    [(PDF, "pdf"), (PNG, "png"), (_zip(), "docx"), (b"plain text", None)],
)
def test_without_mineru_the_coarse_label_carries_the_request(data, suffix, monkeypatch):
    """Nothing parses without MinerU; the label only has to reach the failure."""
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    assert inputs.detect_suffix(data) == suffix


def _fake_detector(monkeypatch, result):
    module = types.ModuleType("mineru.parser.file_type")

    def guess_suffix_by_bytes(data, file_path=None):  # noqa: ARG001
        if isinstance(result, Exception):
            raise result
        return result

    module.guess_suffix_by_bytes = guess_suffix_by_bytes
    for name in ("mineru", "mineru.parser"):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "mineru.parser.file_type", module)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", True)


@pytest.mark.parametrize("found", ["pdf", "EPUB", "odt", "jp2"])
def test_mineru_decides_the_format(found, monkeypatch):
    _fake_detector(monkeypatch, found)
    assert inputs.detect_suffix(b"anything") == found.lower()


@pytest.mark.parametrize("result", ["txt", "md", "exe", RuntimeError("magika failed")])
def test_what_mineru_would_not_parse_is_refused(result, monkeypatch):
    """Plain text is detectable but not parseable; a detector error is a
    rejection the caller can act on, not a crash."""
    _fake_detector(monkeypatch, result)
    assert inputs.detect_suffix(b"anything") is None


@pytest.mark.parametrize(
    ("suffix", "requested", "effective"),
    [
        ("pdf", "advanced", "advanced"),
        ("png", "basic", "basic"),
        ("jp2", "standard", "standard"),
        ("docx", "advanced", "flash"),
        ("html", "standard", "flash"),
        ("epub", "basic", "flash"),
    ],
)
def test_native_formats_run_at_flash(suffix, requested, effective):
    assert inputs.effective_tier(suffix, requested) == effective


def test_the_suffix_lists_do_not_overlap():
    assert not inputs.TIERED_SUFFIXES & inputs.NATIVE_SUFFIXES


@pytest.mark.parametrize(
    ("page_range", "pages"),
    [("", -1), ("5", 1), ("1-5,8", 6), ("1-5,3-6", 6), ("r3-r1", -1), ("2,r1", -1)],
)
def test_count_pages(page_range, pages):
    assert schema.count_pages(page_range) == pages


# -----------------------------------------------------------------------------
# What the handler does with them
# -----------------------------------------------------------------------------

def _capture_run(monkeypatch) -> dict:
    captured: dict = {}

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        captured.update(kwargs)
        out = work_dir / "out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    return captured


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode()


def test_a_native_document_is_reported_at_the_tier_that_ran(monkeypatch):
    captured = _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler(
        {"id": "j", "input": {"file_b64": _b64(_zip()), "tier": "advanced", "transport": "inline"}}
    ))
    assert result["ok"] is True, result
    assert captured["tier"] == "flash"
    assert captured["suffix"] == "docx"
    assert result["debug"]["tier"] == "flash"
    assert result["debug"]["input_format"] == "docx"


def test_a_pdf_keeps_the_requested_tier(monkeypatch):
    captured = _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler(
        {"id": "j", "input": {"file_b64": _b64(PDF), "tier": "basic", "page_range": "1-3"}}
    ))
    assert result["ok"] is True, result
    assert (captured["tier"], captured["page_range"], captured["ocr_mode"]) == ("basic", "1-3", "auto")
    assert result["results"][0]["pages_requested"] == 3


def test_a_page_range_on_anything_but_a_pdf_is_refused(monkeypatch):
    _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler(
        {"id": "j", "input": {"file_b64": _b64(PNG), "page_range": "1"}}
    ))
    assert result["ok"] is False
    assert "page_range applies to PDFs only" in result["error"]


def test_undetectable_bytes_name_what_mineru_parses(monkeypatch):
    _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler({"id": "j", "input": {"file_b64": _b64(b"plain text")}}))
    assert result["ok"] is False
    assert "do not match any format MinerU parses" in result["error"]


# -----------------------------------------------------------------------------
# A dead engine recycles the worker
# -----------------------------------------------------------------------------

class EngineDeadError(RuntimeError):
    """Named like MinerU's and vLLM's own; matched by name on purpose."""


def test_a_dead_engine_asks_for_a_new_worker():
    assert lifecycle.refresh_after_failure(EngineDeadError("gone")) == {"refresh_worker": True}


def test_other_failures_keep_the_worker():
    assert lifecycle.refresh_after_failure(ValueError("bad input")) == {}


def test_the_failure_response_carries_the_recycle(monkeypatch):
    async def dead(*args, **kwargs):
        raise EngineDeadError("engine core died")

    monkeypatch.setattr("worker.parse.run_mineru", dead)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler({"id": "j", "input": {"file_b64": _b64(PDF)}}))
    assert result["ok"] is False
    assert result["refresh_worker"] is True


# -----------------------------------------------------------------------------
# Model diagnostics without MinerU
# -----------------------------------------------------------------------------

def test_model_diagnostics_degrade_without_mineru(monkeypatch):
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    models.vlm_model_dir.cache_clear()
    try:
        assert models.vlm_model_dir() is None
    finally:
        models.vlm_model_dir.cache_clear()
    assert models.probe_models() == {"mineru_available": False}
    assert models.probe_payload()["mineru_models"] == {"mineru_available": False}


# -----------------------------------------------------------------------------
# The artifact layout, against a fake MinerU
# -----------------------------------------------------------------------------

def test_the_writer_names_saved_files_after_the_basename(tmp_path):
    writer = parse._OutputWriter(tmp_path, "report")
    writer.write_string("markdown.md", "# t")
    writer.write_string("middle_json.json", '{"pages": []}')
    writer.write_string("structured_content.json", "{}")
    writer.write("images/page_0_image_0.png", b"png")
    names = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert names == [
        "images/page_0_image_0.png",
        "report.md",
        "report_middle.json",
        "report_structured_content.json",
    ]
    assert writer.middle_json == '{"pages": []}'


@pytest.mark.parametrize("path", ["../escape.png", "images/../../escape.png"])
def test_the_writer_refuses_a_path_outside_the_output(path, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(RuntimeError, match="escapes the output directory"):
        parse._OutputWriter(out, "doc").write(path, b"x")
    assert not (tmp_path / "escape.png").exists()


def _fake_mineru(monkeypatch, calls: dict) -> None:
    parser_mod = types.ModuleType("mineru.parser")
    render_mod = types.ModuleType("mineru.render")

    class ParseResult:
        def __init__(self, middle_json):
            self.middle_json = middle_json

        @classmethod
        def from_json(cls, text):
            return cls(json.loads(text))

        def save(self, writer):
            writer.write_string("markdown.md", "# saved")
            writer.write_string("middle_json.json", json.dumps({"saved": True}))
            writer.write_string("structured_content.json", "{}")
            writer.write("images/page_0_image_0.jpg", b"jpg")

    class MinerUParser:
        def __init__(self, **kwargs):
            calls["parser"] = kwargs

        async def parse_async(self, path, *, page_range=""):
            calls["path"] = Path(path)
            calls["source_bytes"] = Path(path).read_bytes()
            calls["page_range"] = page_range
            return ParseResult({"in_memory": True})

    parser_mod.MinerUParser = MinerUParser
    parser_mod.ParseResult = ParseResult
    render_mod.render_content_list = lambda middle: [{"from": middle}]
    render_mod.render_content_list_v2 = lambda middle: [[{"from": middle}]]
    monkeypatch.setitem(sys.modules, "mineru", sys.modules.get("mineru") or types.ModuleType("mineru"))
    monkeypatch.setitem(sys.modules, "mineru.parser", parser_mod)
    monkeypatch.setitem(sys.modules, "mineru.render", render_mod)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", True)


def test_run_mineru_writes_every_manifest_artifact(monkeypatch, tmp_path):
    calls: dict = {}
    _fake_mineru(monkeypatch, calls)
    out = asyncio.run(parse.run_mineru(
        PDF, "doc", tmp_path, suffix="pdf", tier="basic", ocr_mode="ocr", page_range="2-3",
    ))

    assert calls["parser"] == {"tier": "basic", "parse_mode": "ocr", "vlm_config": None}
    assert calls["page_range"] == "2-3"
    # The source sits beside the output, not in it: archives ship the whole dir.
    assert calls["path"] == tmp_path / "src" / "doc.pdf"
    assert calls["source_bytes"] == PDF
    assert out == tmp_path / "out"

    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert files == [
        "doc.md",
        "doc_content_list.json",
        "doc_content_list_v2.json",
        "doc_middle.json",
        "doc_structured_content.json",
        "images/page_0_image_0.jpg",
    ]
    # The content lists are rendered from the saved copy, whose image
    # references point at the files just written, not from the in-memory one.
    content_list = json.loads((out / "doc_content_list.json").read_text(encoding="utf-8"))
    assert content_list == [{"from": {"saved": True}}]


def test_run_mineru_refuses_without_the_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="mineru is not importable"):
        asyncio.run(parse.run_mineru(
            PDF, "doc", tmp_path, suffix="pdf", tier="flash", ocr_mode="auto", page_range="",
        ))
