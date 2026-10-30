"""The real MinerU 4 engine, on CPU, at the flash tier — `pytest -m engine`.

Everything else in this suite runs without MinerU and stubs the parse, so the
first real parse used to be the Hub validator's, after a release. Flash needs
no models and no GPU, which makes the worker's half of the contract checkable
here: the files it writes from a real result, the renders, the format
detection, and that the lists the worker restates still match MinerU's.

Skipped unless MinerU is importable; the `engine` CI job installs it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from pathlib import Path

import pytest

mineru_parser = pytest.importorskip("mineru.parser")

from worker import harness, inputs, parse, schema  # noqa: E402

pytestmark = pytest.mark.engine

REPO = Path(__file__).resolve().parents[1]
FIXTURE = (REPO / ".runpod" / "test-fixture.pdf").read_bytes()
# 8x8 red PNG, so the HTML case has an image to materialize and render.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP4z8CAFWEXHbQSACj/P8Fu7N9hAAAAAElFTkSuQmCC"
)
HTML = (
    "<!DOCTYPE html><html><body><h1>Title</h1><p>Body text.</p>"
    f'<figure><img src="data:image/png;base64,{base64.b64encode(PNG).decode()}">'
    "<figcaption>Figure 1</figcaption></figure></body></html>"
).encode()
CORE = [
    "doc.md",
    "doc_content_list.json",
    "doc_content_list_v2.json",
    "doc_middle.json",
    "doc_structured_content.json",
]


def _run(tmp_path: Path, data: bytes, suffix: str, **kwargs) -> Path:
    kwargs.setdefault("tier", "flash")
    kwargs.setdefault("ocr_mode", "auto")
    kwargs.setdefault("page_range", "")
    return asyncio.run(parse.run_mineru(data, "doc", tmp_path, suffix=suffix, **kwargs))


def _files(out: Path) -> list[str]:
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


def test_a_text_layer_pdf_yields_every_core_artifact(tmp_path):
    out = _run(tmp_path, FIXTURE, "pdf", ocr_mode="txt", page_range="1")
    assert _files(out) == CORE
    assert "MinerU" in (out / "doc.md").read_text(encoding="utf-8")
    middle = json.loads((out / "doc_middle.json").read_text(encoding="utf-8"))
    assert (middle["schema"], middle["schema_version"]) == ("docvortex.middle", "2.0")
    assert middle["extensions"]["mineru"] == {"tier": "flash", "parse_mode": "txt"}


def test_images_are_written_and_every_reference_resolves(tmp_path):
    out = _run(tmp_path, HTML, "html")
    images = [f for f in _files(out) if f.startswith("images/")]
    assert images, "the HTML's image was not materialized"
    content_list = json.loads((out / "doc_content_list.json").read_text(encoding="utf-8"))
    refs = [item["img_path"] for item in content_list if item.get("img_path")]
    assert refs and all((out / ref).is_file() for ref in refs)
    markdown = (out / "doc.md").read_text(encoding="utf-8")
    md_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    assert md_refs and all((out / ref).is_file() for ref in md_refs)


def test_every_render_is_written(tmp_path):
    out = _run(tmp_path, HTML, "html", renders=list(harness.RENDER_FORMATS))
    assert (out / "doc.html").read_text(encoding="utf-8").count("data:image") >= 1
    latex = (out / "doc.tex").read_text(encoding="utf-8")
    tex_refs = re.findall(r"\\detokenize\{([^}]+)\}", latex)
    assert tex_refs and all((out / ref).is_file() for ref in tex_refs)
    assert (out / "doc.docx").read_bytes()[:2] == b"PK"
    assert (out / "doc.epub").read_bytes()[:2] == b"PK"
    assert (out / "doc.pdf").read_bytes()[:5] == b"%PDF-"


def test_a_pdf_source_renders_back_to_pdf(tmp_path):
    out = _run(tmp_path, FIXTURE, "pdf", ocr_mode="txt", renders=["pdf"])
    assert (out / "doc.pdf").read_bytes()[:5] == b"%PDF-"


@pytest.mark.parametrize(
    ("data", "hint", "suffix"),
    [
        (FIXTURE, None, "pdf"),
        (FIXTURE, "renamed.docx", "pdf"),
        (HTML, None, "html"),
        (b"name,qty\nalpha,1\n", "stock.csv", "csv"),
        (b"name\tqty\nalpha\t1\n", "stock.tsv", "tsv"),
        (b"name,qty\nalpha,1\n", None, None),
        (b"just plain text\n", "notes.csv", "csv"),
        (b"just plain text\n", None, None),
    ],
)
def test_mineru_detection_with_and_without_a_name(data, hint, suffix):
    assert inputs.detect_suffix(data, hint) == suffix


def test_the_restated_suffix_lists_match_mineru():
    from mineru import filetypes

    assert inputs.TIERED_SUFFIXES == set(filetypes.TIERED_PARSE_EXTENSIONS)
    assert inputs.NATIVE_SUFFIXES == set(filetypes.FLASH_ONLY_PARSE_EXTENSIONS)


def test_the_restated_tiers_match_mineru():
    from mineru import types

    assert schema.VALID_TIERS == tuple(types.TIERS)


def test_the_page_range_grammar_agrees_with_mineru():
    """Shapes the schema accepts must parse in MinerU, and its rejections too."""
    from docvortex.document import page_range as mineru_ranges

    parse_ranges = next(
        getattr(mineru_ranges, name)
        for name in ("parse_page_range", "parse_page_ranges", "resolve_page_range")
        if hasattr(mineru_ranges, name)
    )
    for spec in ("1", "1-5,8", "r3-r1", "2-r2", "1-3,r1"):
        assert schema.PAGE_RANGE_PATTERN.fullmatch(spec)
        try:
            parse_ranges(spec, 10)
        except TypeError:
            parse_ranges(spec, page_count=10)


def test_mineru_config_loads_with_every_hub_default(monkeypatch):
    """MinerU reads every MINERU_<PATH> variable as config, strictly; a Hub
    default it cannot parse would fail every job on a fresh endpoint."""
    from mineru import config

    hub = json.loads((REPO / ".runpod" / "hub.json").read_text(encoding="utf-8"))
    for entry in hub["config"]["env"]:
        if entry["key"].startswith("MINERU_"):
            monkeypatch.setenv(entry["key"], str(entry["input"].get("default", "")))
    for name in ("_get_loaded_config", "get_config"):
        cached = getattr(config, name, None)
        if hasattr(cached, "cache_clear"):
            cached.cache_clear()
    loaded = config.get_config()
    assert loaded.llm_aided.features.title_leveling is False
    assert loaded.llm_aided.features.cross_page_table_cell_merge is False


def test_the_baked_vlm_is_the_one_mineru_loads(monkeypatch):
    """The Dockerfile bakes what `mineru-kit models download --tier standard`
    lists; the docs, README and probe name the VLM by id. A minor release that
    swaps it (3.1 -> 3.2 did) has to fail here, not on an endpoint."""
    from mineru.model import registry

    monkeypatch.setenv("MINERU_MODEL_VLM_ENGINE", "vllm")
    monkeypatch.setenv("MINERU_MODEL_SMALL_BACKEND", "torch")
    names = [repo.repos["huggingface"] for repo in registry.model_repos_for_tier(
        "standard", small_backend="torch", vlm_engine="vllm",
    )]
    assert names == ["opendatalab/MinerU-4_models_torch", "opendatalab/MinerU2.5-Pro-2605-1.2B"]


def test_the_engine_job_is_not_silently_skipped():
    """If this file ran, MinerU imported; say which, for the CI log."""
    from mineru.version import __version__

    assert __version__.startswith("4.1."), __version__
    assert os.environ.get("MINERU_TELEMETRY_DISABLED") == "1"
