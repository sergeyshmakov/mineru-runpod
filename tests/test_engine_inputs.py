"""The MinerU 4 seam, continued: file-name hints, render targets, Hub-form env.

Split from test_engine_adapter.py to stay under the repo's file-size cap; the
fakes and helpers are shared from there.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path

import pytest

import handler
from worker import inputs, parse, schema
from tests.test_engine_adapter import PDF, _b64, _capture_run, _fake_mineru

# -----------------------------------------------------------------------------
# File names as hints
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("job_input", "hint"),
    [
        ({"file_b64": "AA==", "file_name": "table.csv"}, "table.csv"),
        ({"file_url": "https://x.example/files/q3%20report.tsv?sig=abc"}, "q3 report.tsv"),
        ({"file_url": "https://x.example/files/table.csv", "file_name": "real.tsv"}, "real.tsv"),
        ({"volume_path": "/runpod-volume/in/page.mhtml"}, "page.mhtml"),
        ({"file_url": "https://x.example/"}, None),
        ({"file_b64": "AA=="}, None),
    ],
)
def test_name_hint_prefers_the_callers_file_name(job_input, hint):
    assert inputs.name_hint(job_input) == hint


def test_the_detector_gets_the_extension_not_the_callers_name(monkeypatch):
    seen: dict = {}
    module = types.ModuleType("mineru.parser.file_type")

    def guess_suffix_by_bytes(data, file_path=None):  # noqa: ARG001
        seen["file_path"] = file_path
        return "csv"

    module.guess_suffix_by_bytes = guess_suffix_by_bytes
    for name in ("mineru", "mineru.parser"):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "mineru.parser.file_type", module)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", True)

    assert inputs.detect_suffix(b"a,b\n1,2\n", "../../etc/q3 Report.CSV") == "csv"
    assert seen["file_path"] == "input.csv"


def test_without_mineru_a_hint_names_text_formats(monkeypatch):
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    assert inputs.detect_suffix(b"a,b\n1,2\n", "table.csv") == "csv"
    assert inputs.detect_suffix(b"a,b\n1,2\n", "notes.txt") is None
    # Content still decides where it can: a PDF stays a PDF.
    assert inputs.detect_suffix(PDF, "table.csv") == "pdf"


@pytest.mark.parametrize("file_name", ["table.csv", "Report.PDF", "page.mhtml", "q3 report.tsv", "scan.TIF"])
def test_file_name_accepts_a_parseable_name(file_name):
    assert schema.validate_input({"file_b64": "AA==", "file_name": file_name})["file_name"] == file_name


@pytest.mark.parametrize(
    ("file_name", "message"),
    [
        ("notes.txt", "extension MinerU parses"),
        ("noextension", "extension MinerU parses"),
        ("dir/table.csv", "not a path"),
        ("..\table.csv", "not a path"),
        ("tab\tle.csv", "not a path"),
        ("", "not a path"),
        ("x" * 252 + ".csv", "not a path"),
    ],
)
def test_file_name_refuses_anything_but_a_parseable_name(file_name, message):
    with pytest.raises(ValueError, match=message):
        schema.validate_input({"file_b64": "AA==", "file_name": file_name})


def test_a_csv_named_by_the_caller_parses_natively(monkeypatch):
    captured = _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler({"id": "j", "input": {
        "file_b64": _b64(b"name,qty\nalpha,1\n"), "file_name": "stock.csv", "tier": "advanced",
    }}))
    assert result["ok"] is True, result
    assert (captured["suffix"], captured["tier"]) == ("csv", "flash")


def test_an_unnamed_text_input_is_told_to_name_itself(monkeypatch):
    _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler({"id": "j", "input": {"file_b64": _b64(b"name,qty\nalpha,1\n")}}))
    assert result["ok"] is False
    assert "set file_name" in result["error"]


# -----------------------------------------------------------------------------
# Render targets
# -----------------------------------------------------------------------------

def _fake_renders(monkeypatch, calls: dict) -> None:
    render_mod = sys.modules["mineru.render"]

    def recorder(name, result):
        def render(middle, **kwargs):
            calls.setdefault("renders", []).append((name, middle, kwargs))
            return result
        return render

    render_mod.render_html = recorder("html", "<html>embedded</html>")
    render_mod.render_latex = recorder("latex", "\\includegraphics{images/x.png}")
    render_mod.render_docx = recorder("docx", b"PK-docx")
    render_mod.render_epub = recorder("epub", b"PK-epub")
    render_mod.render_pdf = recorder("pdf", b"%PDF-render")
    render_mod.PdfLayout = types.SimpleNamespace(AUTO="auto")
    monkeypatch.setattr(sys.modules["mineru"], "render", render_mod, raising=False)


def test_run_mineru_writes_only_the_renders_asked_for(monkeypatch, tmp_path):
    calls: dict = {}
    _fake_mineru(monkeypatch, calls)
    _fake_renders(monkeypatch, calls)
    out = asyncio.run(parse.run_mineru(
        PDF, "doc", tmp_path, suffix="pdf", tier="flash", ocr_mode="txt",
        page_range="", renders=["html", "pdf"],
    ))
    assert (out / "doc.html").read_text(encoding="utf-8") == "<html>embedded</html>"
    assert (out / "doc.pdf").read_bytes() == b"%PDF-render"
    assert not any((out / f"doc{ext}").exists() for ext in (".tex", ".docx", ".epub"))
    assert [name for name, _, _ in calls["renders"]] == ["html", "pdf"]
    # PDF keeps the source's own layout where it has one.
    assert calls["renders"][1][2] == {"layout": "auto"}


def test_renders_come_from_the_copy_that_resolves_their_images(monkeypatch, tmp_path):
    """HTML/DOCX/EPUB/PDF embed images, so they render from the in-memory
    document that still holds them; LaTeX can only reference files, so it
    renders from the saved copy whose references are the written images."""
    calls: dict = {}
    _fake_mineru(monkeypatch, calls)
    _fake_renders(monkeypatch, calls)
    asyncio.run(parse.run_mineru(
        PDF, "doc", tmp_path, suffix="pdf", tier="flash", ocr_mode="txt",
        page_range="", renders=["html", "latex", "docx", "epub", "pdf"],
    ))
    sources = {name: middle for name, middle, _ in calls["renders"]}
    assert sources["latex"] == {"saved": True}
    for name in ("html", "docx", "epub", "pdf"):
        assert sources[name] == {"in_memory": True}, name


def test_a_failing_render_fails_the_parse(monkeypatch, tmp_path):
    """As in MinerU's own API: a requested format that cannot be produced is a
    failure, not a response quietly missing what was asked for."""
    calls: dict = {}
    _fake_mineru(monkeypatch, calls)
    _fake_renders(monkeypatch, calls)

    def broken(middle, **kwargs):
        raise RuntimeError("docx writer failed")

    sys.modules["mineru.render"].render_docx = broken
    with pytest.raises(RuntimeError, match="docx writer failed"):
        asyncio.run(parse.run_mineru(
            PDF, "doc", tmp_path, suffix="pdf", tier="flash", ocr_mode="txt",
            page_range="", renders=["docx"],
        ))


def test_the_handler_asks_only_for_the_renders_in_formats(monkeypatch):
    captured = _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    result = asyncio.run(handler.handler({"id": "j", "input": {
        "file_b64": _b64(PDF), "transport": "inline",
        "formats": ["markdown", "docx", "images", "html"],
    }}))
    assert result["ok"] is True, result
    assert captured["renders"] == ["docx", "html"]


def test_default_formats_ask_for_no_render(monkeypatch):
    captured = _capture_run(monkeypatch)
    monkeypatch.setattr(parse, "MINERU_AVAILABLE", False)
    asyncio.run(handler.handler({"id": "j", "input": {"file_b64": _b64(PDF)}}))
    assert captured["renders"] == []


def test_inline_egress_counts_the_renders():
    from worker.envelope import _measure_output_bytes

    response = {"results": [{
        "markdown": "ab", "html": "<p>x</p>", "latex": "\\x",
        "images": {"a.png": "QUJD"}, "docx": {"doc.docx": "UEs="}, "pdf": {"doc.pdf": "JVBE"},
    }]}
    assert _measure_output_bytes(response, "inline") == 2 + 8 + 2 + 4 + 4 + 4


# -----------------------------------------------------------------------------
# Empty MINERU_* variables from a Hub form
# -----------------------------------------------------------------------------

def test_an_empty_mineru_variable_is_dropped_before_mineru_reads_it():
    """Run in a fresh interpreter: the cleanup happens once, at import."""
    import subprocess

    env = {
        **os.environ,
        "MINERU_LLM_AIDED_FEATURES_TITLE_LEVELING": "",
        "MINERU_PROCESSING_WINDOW_SIZE": "  ",
        "MINERU_LOG_LEVEL": "",
        "MINERU_WARMUP_TIER": "advanced",
    }
    probe = (
        "import os, worker; "
        "print(sorted(k for k in os.environ if k.startswith('MINERU_')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], env=env, capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[1], check=True,
    ).stdout
    assert "MINERU_LLM_AIDED_FEATURES_TITLE_LEVELING" not in out
    assert "MINERU_PROCESSING_WINDOW_SIZE" not in out
    assert "MINERU_LOG_LEVEL" not in out
    assert "MINERU_WARMUP_TIER" in out
