"""What this worker declares about itself to the harness.

The harness is engine-agnostic, which means every operator-facing name and
every output key it produces comes from worker/harness.py. A wrong value
there does not fail loudly: MINERU_VOLUME_ROOTS silently stops being read,
a format the schema accepts has no file behind it, telemetry stops seeing
log records. These tests watch the declaration, not the mechanics.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runpod_doc_worker import config
from runpod_doc_worker.contract import artifacts
from runpod_doc_worker.obs import logging as harness_logging

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


def test_absent_artifacts_keep_their_declared_defaults(tmp_path):
    """A page that produced no text must come back as an empty value of the
    right type, not a missing key a caller would KeyError on."""
    out = artifacts.resolve(MANIFEST, tmp_path, "doc")
    assert out["markdown"] == ""
    assert out["content_list"] == []
    assert out["middle"] == {}
    assert out["images"] == {}


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
