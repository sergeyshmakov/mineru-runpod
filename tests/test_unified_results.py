"""Unified `results: [...]` response shape.

Exercises worker.package.package_results_entry directly (no GPU, no MinerU)
plus the handler-level shape assertions and the egress sizing helper.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import tarfile
from pathlib import Path

import pytest

import handler
from worker import package


# -----------------------------------------------------------------------------
# Fixture
# -----------------------------------------------------------------------------

def _seed_mineru_output(dir_: Path, basename: str) -> None:
    (dir_ / f"{basename}.md").write_text("# heading\n\nbody\n", encoding="utf-8")
    (dir_ / f"{basename}_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "body", "page_idx": 0}]),
        encoding="utf-8",
    )
    (dir_ / f"{basename}_middle.json").write_text(json.dumps({"k": 1}), encoding="utf-8")
    (dir_ / "images").mkdir()
    (dir_ / "images" / "fig1.png").write_bytes(b"\x89PNG fake")


# -----------------------------------------------------------------------------
# package_results_entry — per-transport assembly
# -----------------------------------------------------------------------------

def test_tarball_entry_carries_basename_source_pages_and_tarball(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    entry = package.package_results_entry(
        transport="tarball_b64",
        formats=["markdown"],  # no-op for tarball
        output_dir=out,
        basename="doc",
        source="b64",
        pages_requested=10,
    )
    assert entry["basename"] == "doc"
    assert entry["source"] == "b64"
    assert entry["pages_requested"] == 10
    assert isinstance(entry["tarball_b64"], str) and entry["tarball_b64"]
    # tarball is self-contained — formats filter does NOT remove files inside
    raw = base64.b64decode(entry["tarball_b64"])
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = set(tar.getnames())
    assert "doc.md" in names
    assert "doc_content_list.json" in names
    # No inline-format keys leak into a tarball entry.
    assert "markdown" not in entry
    assert "content_list" not in entry


def test_inline_entry_with_all_formats(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    entry = package.package_results_entry(
        transport="inline",
        formats=["markdown", "content_list", "middle", "images"],
        output_dir=out,
        basename="doc",
        source="url:https://x/doc.pdf",
        pages_requested=-1,
    )
    assert entry["basename"] == "doc"
    assert entry["source"] == "url:https://x/doc.pdf"
    assert entry["markdown"].startswith("# heading")
    assert entry["content_list"][0]["text"] == "body"
    assert entry["middle"] == {"k": 1}
    assert "fig1.png" in entry["images"]
    assert "tarball_b64" not in entry
    assert "tarball_url" not in entry


def test_inline_entry_with_markdown_only_omits_other_keys(tmp_path):
    """formats=['markdown'] produces ONLY the markdown key in the entry —
    the other three are absent, not present-as-empty.
    """
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    entry = package.package_results_entry(
        transport="inline",
        formats=["markdown"],
        output_dir=out,
        basename="doc",
        source="b64",
        pages_requested=5,
    )
    assert "markdown" in entry
    assert "content_list" not in entry
    assert "middle" not in entry
    assert "images" not in entry


def test_inline_entry_with_two_formats(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    entry = package.package_results_entry(
        transport="inline",
        formats=["content_list", "images"],
        output_dir=out,
        basename="doc",
        source="b64",
        pages_requested=5,
    )
    assert "markdown" not in entry
    assert "middle" not in entry
    assert "content_list" in entry
    assert "images" in entry


def test_inline_entry_without_images_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc.md").write_text("# md", encoding="utf-8")
    # No images dir — `images` should be present-as-empty when requested.
    entry = package.package_results_entry(
        transport="inline",
        formats=["markdown", "images"],
        output_dir=out,
        basename="doc",
        source="b64",
        pages_requested=1,
    )
    assert entry["markdown"] == "# md"
    assert entry["images"] == {}


# -----------------------------------------------------------------------------
# Handler-level shape — error path has no results
# -----------------------------------------------------------------------------

def test_handler_failure_response_has_no_results_key():
    """A validation failure must produce error+ok=false, NOT an empty results list."""
    result = asyncio.run(handler.handler({"input": {}}))  # missing source
    assert result["ok"] is False
    assert "error" in result
    assert "results" not in result


def test_handler_success_wraps_entry_in_results_list(monkeypatch):
    """Full handler path: a fake MinerU parse produces one entry in the results list."""

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):  # noqa: ARG001
        out = work_dir / "fake-out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)

    result = asyncio.run(handler.handler({
        "input": {"file_b64": "JVBERi0xLjQK", "basename": "doc"}  # %PDF-1.4
    }))
    assert result["ok"] is True
    assert "results" in result
    assert isinstance(result["results"], list)
    assert len(result["results"]) == 1
    entry = result["results"][0]
    assert entry["basename"] == "doc"
    assert entry["source"] == "b64"
    assert "tarball_b64" in entry  # default transport
    # Top-level keys job-scoped, NOT per-file:
    assert "elapsed_seconds" in result
    assert "mineru_version" in result
    assert "debug" in result
    # Per-entry keys NOT mirrored at top level:
    assert "basename" not in result
    assert "source" not in result
    assert "tarball_b64" not in result
    assert "pages_processed" not in result  # alias dropped per the pre-1.0 cutover


def test_handler_success_with_inline_filtered_formats(monkeypatch):
    """End-to-end: transport=inline + formats=['markdown'] returns ONLY markdown."""

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):  # noqa: ARG001
        out = work_dir / "fake-out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        (out / f"{basename}_content_list.json").write_text("[]", encoding="utf-8")
        (out / f"{basename}_middle.json").write_text("{}", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)

    result = asyncio.run(handler.handler({
        "input": {
            "file_b64": "JVBERi0xLjQK",
            "basename": "doc",
            "transport": "inline",
            "formats": ["markdown"],
        }
    }))
    assert result["ok"] is True
    entry = result["results"][0]
    assert entry["markdown"] == "# fake\n"
    assert "content_list" not in entry
    assert "middle" not in entry
    assert "images" not in entry
