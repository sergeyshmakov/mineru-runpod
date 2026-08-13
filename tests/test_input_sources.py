"""Input-source resolution: which files and which URLs the worker accepts.

No GPU, no MinerU, no network — every case here is decided before a socket
opens or MinerU is imported.
"""

from __future__ import annotations

import asyncio

import pytest

from worker import io as worker_io


# -----------------------------------------------------------------------------
# volume_path — input roots
# -----------------------------------------------------------------------------

def _resolve(job_input: dict):
    return asyncio.run(worker_io.resolve_input_bytes(job_input))


def test_volume_roots_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("MINERU_VOLUME_ROOTS", raising=False)
    assert [str(p) for p in worker_io.volume_roots()] == [
        str(worker_io.Path(r)) for r in worker_io.DEFAULT_VOLUME_ROOTS
    ]


def test_volume_roots_env_replaces_defaults(monkeypatch, tmp_path):
    other = tmp_path / "other"
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", f"{tmp_path}, {other} ,")
    assert [str(p) for p in worker_io.volume_roots()] == [str(tmp_path), str(other)]


def test_volume_roots_blank_env_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", "   ")
    assert len(worker_io.volume_roots()) == len(worker_io.DEFAULT_VOLUME_ROOTS)


def test_volume_path_inside_a_root_is_read(monkeypatch, tmp_path):
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    doc = tmp_path / "nested" / "doc.pdf"
    doc.parent.mkdir()
    doc.write_bytes(b"%PDF-1.4 nested")
    raw, src = _resolve({"volume_path": str(doc)})
    assert raw == b"%PDF-1.4 nested"
    assert src == f"volume:{doc}"


def test_volume_path_outside_the_roots_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"%PDF-1.4 elsewhere")
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(root))
    with pytest.raises(ValueError, match="outside the configured input roots"):
        _resolve({"volume_path": str(outside)})


def test_volume_path_with_parent_segments_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"%PDF-1.4 elsewhere")
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(root))
    sneaky = root / ".." / "elsewhere.pdf"
    with pytest.raises(ValueError, match="outside the configured input roots"):
        _resolve({"volume_path": str(sneaky)})


def test_volume_path_symlink_leaving_the_root_is_rejected(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"%PDF-1.4 elsewhere")
    link = root / "link.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(root))
    with pytest.raises(ValueError, match="outside the configured input roots"):
        _resolve({"volume_path": str(link)})


def test_volume_path_must_be_absolute(monkeypatch, tmp_path):
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    with pytest.raises(ValueError, match="must be an absolute path"):
        _resolve({"volume_path": "relative/doc.pdf"})


def test_volume_path_missing_file_keeps_its_message(monkeypatch, tmp_path):
    # The wording is quoted in the network-volumes guide and matched by
    # callers' own error handling — it must not drift.
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    with pytest.raises(ValueError, match="volume_path not found inside container"):
        _resolve({"volume_path": str(tmp_path / "absent.pdf")})
