"""What this worker declares about itself to the harness.

The harness is engine-agnostic, which means every operator-facing name and
every output key it produces comes from worker/harness.py. A wrong value
there does not fail loudly: MINERU_VOLUME_ROOTS silently stops being read,
a format the schema accepts has no file behind it, telemetry stops seeing
log records. These tests watch the declaration, not the mechanics.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from runpod_doc_worker import config
from runpod_doc_worker.contract import artifacts
from runpod_doc_worker.obs import logging as harness_logging

import handler
from worker import schema
from worker.harness import MANIFEST


HUB_JSON = Path(__file__).resolve().parents[1] / ".runpod" / "hub.json"


# -----------------------------------------------------------------------------
# Operator-facing names
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("knob", "expected"),
    [
        ("VOLUME_ROOTS", "MINERU_VOLUME_ROOTS"),
        ("ALLOW_LOCAL_FETCH", "MINERU_ALLOW_LOCAL_FETCH"),
        ("DISABLE_PROBE", "MINERU_DISABLE_PROBE"),
    ],
)
def test_env_names_keep_their_documented_spelling(knob, expected):
    """Renaming these silently stops reading what an operator already set."""
    assert config.active().env_name(knob) == expected


def test_every_declared_env_var_is_documented_in_hub_json():
    """The deploy form is where an operator finds these, so it has to list them.

    Read from hub.json rather than restated here: a knob added to the
    harness config without an entry on the form is one nobody can set.
    """
    documented = {
        entry["key"]
        for entry in json.loads(HUB_JSON.read_text(encoding="utf-8"))["config"]["env"]
    }
    cfg = config.active()
    for knob in ("VOLUME_ROOTS", "ALLOW_LOCAL_FETCH", "DISABLE_PROBE"):
        assert cfg.env_name(knob) in documented


def test_logger_name_is_the_one_log_filters_match():
    """`logger` is a field operators filter RunPod's log viewer on."""
    assert config.active().logger_name == "mineru-worker"


def test_log_mirror_reaches_telemetry(monkeypatch):
    """A record has to arrive at telemetry.emit_log when export is enabled."""
    from worker import telemetry

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(telemetry, "is_enabled", lambda: True)
    monkeypatch.setattr(
        telemetry, "emit_log",
        lambda level, msg, fields: calls.append((level, msg)),
    )

    harness_logging.info("mirrored")
    assert calls == [("info", "mirrored")]


def test_log_mirror_is_inert_without_telemetry(monkeypatch):
    """And must not when it is not — the default for most endpoints."""
    from worker import telemetry

    calls: list = []
    monkeypatch.setattr(telemetry, "is_enabled", lambda: False)
    monkeypatch.setattr(
        telemetry, "emit_log",
        lambda level, msg, fields: calls.append((level, msg)),
    )

    harness_logging.info("not mirrored")
    assert calls == []


# -----------------------------------------------------------------------------
# Input roots
# -----------------------------------------------------------------------------

def test_declared_roots_cover_the_documented_locations():
    """Each is promised by the network-volumes guide, so dropping one is a
    contract change rather than a tidy-up. `/worker` is where the image bakes
    the fixture the boot warmup parses."""
    assert set(config.active().volume_roots) >= {
        "/runpod-volume", "/workspace", "/worker", "/tmp",
    }


# -----------------------------------------------------------------------------
# Output manifest
# -----------------------------------------------------------------------------

def test_manifest_keys_are_the_schema_formats():
    """`formats` is validated against the manifest, in declaration order, so a
    caller cannot ask for an artifact that has no file behind it."""
    assert artifacts.keys(MANIFEST) == list(schema.VALID_FORMATS)


def test_manifest_covers_what_mineru_writes(tmp_path):
    """The four files a parse produces resolve to the four response keys."""
    (tmp_path / "doc.md").write_text("# heading\n", encoding="utf-8")
    (tmp_path / "doc_content_list.json").write_text('[{"type": "text"}]', encoding="utf-8")
    (tmp_path / "doc_middle.json").write_text('{"k": 1}', encoding="utf-8")
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "fig1.png").write_bytes(b"\x89PNG fake")

    out = artifacts.resolve(MANIFEST, tmp_path, "doc")
    assert out["markdown"] == "# heading\n"
    assert out["content_list"] == [{"type": "text"}]
    assert out["middle"] == {"k": 1}
    assert "fig1.png" in out["images"]


def test_content_list_falls_back_to_the_versioned_name(tmp_path):
    """MinerU renamed this file; a build writing only the newer name still
    fills the same response key."""
    (tmp_path / "doc_content_list_v2.json").write_text('[{"type": "text"}]', encoding="utf-8")
    out = artifacts.resolve(MANIFEST, tmp_path, "doc", keys=["content_list"])
    assert out["content_list"] == [{"type": "text"}]


def test_the_current_content_list_name_wins(tmp_path):
    """With both present, the unversioned name is the one read — the patterns
    are ordered fallbacks, not alternatives."""
    (tmp_path / "doc_content_list.json").write_text('["current"]', encoding="utf-8")
    (tmp_path / "doc_content_list_v2.json").write_text('["older"]', encoding="utf-8")
    out = artifacts.resolve(MANIFEST, tmp_path, "doc", keys=["content_list"])
    assert out["content_list"] == ["current"]


def test_absent_optional_artifacts_keep_their_declared_defaults(tmp_path):
    """A document with no tables must come back as an empty value of the right
    type, not a missing key a caller would KeyError on."""
    out = artifacts.resolve(
        MANIFEST, tmp_path, "doc", keys=["content_list", "middle", "images"]
    )
    assert out["content_list"] == []
    assert out["middle"] == {}
    assert out["images"] == {}


def test_an_absent_markdown_has_no_default_to_fall_back_on(tmp_path):
    """Being required is exactly this: there is no value that would stand in
    for the document's text. worker.parse refuses first — it looks for the .md
    before packaging is reached — so this is the second of two checks, not the
    only one."""
    with pytest.raises(artifacts.ArtifactError, match="markdown"):
        artifacts.resolve(MANIFEST, tmp_path, "doc", keys=["markdown"])


def test_the_longest_artefact_suffix_is_the_longest_one_declared():
    """schema bounds `basename` by the longest name a job can write, so the
    two have to agree: a longer pattern added to the manifest would let a
    name through that fails at ENAMETOOLONG mid-parse."""
    suffixes = [
        pattern.format(basename="")
        for artifact in MANIFEST
        for pattern in artifact.patterns
        if "*" not in pattern
    ]
    assert schema.LONGEST_ARTEFACT_SUFFIX == max(suffixes, key=len)


# -----------------------------------------------------------------------------
# What this worker will and will not ship a response without
# -----------------------------------------------------------------------------

def test_markdown_is_the_one_required_artifact():
    """The document's text is what a caller asked for; an empty string in its
    place is worth less to them than a failed job they can retry. The other
    three are worth shipping without, so they degrade and say so."""
    required = {a.key for a in MANIFEST if a.required}
    assert required == {"markdown"}


def test_an_unreadable_markdown_fails_the_job(monkeypatch, capsys):
    """End-to-end: the response says ok=false rather than carrying an empty
    string that reads like a document with no text on it."""
    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "out"
        out.mkdir()
        # Written, then unreadable — a disk that filled mid-write, or bytes
        # that are not the UTF-8 the artifact is declared as.
        (out / f"{basename}.md").write_bytes(b"\xff\xfe\x00bad")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    result = asyncio.run(handler.handler({
        "id": "required-markdown",
        "input": {"file_b64": "JVBERi0xLjQK", "basename": "doc"},
    }))
    capsys.readouterr()

    assert result["ok"] is False
    assert "markdown" in result["error"]


def test_an_unreadable_secondary_artifact_still_returns_a_response(monkeypatch, capsys):
    """A corrupt content_list leaves a usable document, so the job succeeds —
    and the response says which artifact it lost, so a caller can requeue that
    document instead of finding out downstream."""
    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# real text\n", encoding="utf-8")
        (out / f"{basename}_content_list.json").write_bytes(b"{truncated")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    result = asyncio.run(handler.handler({
        "id": "degraded-content-list",
        "input": {
            "file_b64": "JVBERi0xLjQK",
            "basename": "doc",
            "transport": "inline",
        },
    }))
    capsys.readouterr()

    assert result["ok"] is True
    entry = result["results"][0]
    assert entry["markdown"] == "# real text\n"
    assert entry["content_list"] == []
    assert entry["degraded"]["count"] == 1
    (item,) = entry["degraded"]["items"]
    assert item["artifact"] == "content_list"
    assert item["reason"] == "unreadable"


def test_an_intact_job_carries_no_degraded_key(monkeypatch, capsys):
    """The field appears only when something was lost, so a caller can treat
    its presence as the signal."""
    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fine\n", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    result = asyncio.run(handler.handler({
        "input": {"file_b64": "JVBERi0xLjQK", "basename": "doc",
                  "transport": "inline", "formats": ["markdown"]},
    }))
    capsys.readouterr()

    assert result["ok"] is True
    assert "degraded" not in result["results"][0]
