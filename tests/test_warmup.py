"""Boot-time warmup.

Verifies the warmup module:
- honors MINERU_SKIP_WARMUP
- skips gracefully when the fixture is missing
- calls run_mineru with the expected single-page args
- reads MINERU_WARMUP_TIER from env
- never propagates exceptions (warmup failure must not block worker boot)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worker import warmup as warmup_module


# -----------------------------------------------------------------------------
# Env-driven control surface
# -----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Each test starts with a clean warmup env."""
    for var in ("MINERU_SKIP_WARMUP", "MINERU_WARMUP_BACKEND", "MINERU_WARMUP_LANG"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_warmup_skipped_when_env_var_truthy(monkeypatch, capsys):
    monkeypatch.setenv("MINERU_SKIP_WARMUP", "1")
    warmup_module.warmup()
    out = capsys.readouterr().out
    assert "MINERU_SKIP_WARMUP set" in out
    assert "skipping" in out


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes", "on", "  1  "])
def test_warmup_skip_accepts_various_truthy_values(monkeypatch, capsys, value):
    monkeypatch.setenv("MINERU_SKIP_WARMUP", value)
    warmup_module.warmup()
    out = capsys.readouterr().out
    assert "skipping" in out


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_warmup_skip_falsy_values_do_not_skip(monkeypatch, capsys, value, tmp_path):
    monkeypatch.setenv("MINERU_SKIP_WARMUP", value)
    # Fixture missing → still skips, but via the fixture-not-found path, not the env-skip path.
    monkeypatch.setattr(warmup_module, "WARMUP_FIXTURE_PATH", tmp_path / "missing.pdf")
    warmup_module.warmup()
    out = capsys.readouterr().out
    assert "MINERU_SKIP_WARMUP set" not in out
    assert "fixture not found" in out


# -----------------------------------------------------------------------------
# Fixture-missing path
# -----------------------------------------------------------------------------

def test_warmup_skipped_when_fixture_missing(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(warmup_module, "WARMUP_FIXTURE_PATH", tmp_path / "nope.pdf")
    warmup_module.warmup()
    out = capsys.readouterr().out
    assert "fixture not found" in out
    assert "skipping" in out


# -----------------------------------------------------------------------------
# Happy path: run_mineru receives the expected args
# -----------------------------------------------------------------------------

def _seed_fixture(monkeypatch, tmp_path) -> Path:
    fixture = tmp_path / "fixture.pdf"
    fixture.write_bytes(b"%PDF-1.4\nfake")
    monkeypatch.setattr(warmup_module, "WARMUP_FIXTURE_PATH", fixture)
    return fixture


def test_warmup_calls_run_mineru_with_warmup_shaped_args(monkeypatch, capsys, tmp_path):
    _seed_fixture(monkeypatch, tmp_path)
    captured: dict = {}

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        captured["file_bytes"] = file_bytes
        captured["basename"] = basename
        captured.update(kwargs)
        out = work_dir / "fake-out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# warm\n", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    warmup_module.warmup()

    out = capsys.readouterr().out
    assert "starting" in out
    assert "done in" in out

    assert captured["file_bytes"].startswith(b"%PDF")
    assert captured["basename"] == "warmup"
    assert captured["page_range"] == "1"
    assert captured["suffix"] == "pdf"
    assert captured["ocr_mode"] == "auto"
    assert captured.get("server_url") is None
    # The default, because the env is not set: the tier that loads the VLM.
    assert captured["tier"] == "standard"


def test_warmup_respects_env_tier(monkeypatch, tmp_path):
    _seed_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("MINERU_WARMUP_TIER", "advanced")

    captured: dict = {}

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        captured.update(kwargs)
        out = work_dir / "fake-out"
        out.mkdir()
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    warmup_module.warmup()

    assert captured["tier"] == "advanced"


def test_a_blank_warmup_tier_falls_back_to_standard(monkeypatch, tmp_path):
    """The Hub form sends an empty string for an untouched field."""
    _seed_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("MINERU_WARMUP_TIER", "  ")

    captured: dict = {}

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        captured.update(kwargs)
        out = work_dir / "fake-out"
        out.mkdir()
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    warmup_module.warmup()

    assert captured["tier"] == "standard"


# -----------------------------------------------------------------------------
# Failure path: warmup must NEVER propagate exceptions.
# -----------------------------------------------------------------------------

def test_warmup_failure_is_nonfatal(monkeypatch, capsys, tmp_path):
    _seed_fixture(monkeypatch, tmp_path)

    async def fake_run_that_fails(*args, **kwargs):
        raise RuntimeError("simulated mineru explosion")

    monkeypatch.setattr("worker.parse.run_mineru", fake_run_that_fails)

    # Must not raise. If this propagates, worker boot fails — which is
    # the exact failure mode warmup is supposed to avoid.
    warmup_module.warmup()

    out = capsys.readouterr().out
    assert "failed after" in out
    assert "RuntimeError" in out
    assert "simulated mineru explosion" in out
    assert "lazy-load fallback" in out


def test_warmup_failure_in_filesystem_io_is_nonfatal(monkeypatch, capsys, tmp_path):
    """Even failures before the parse proper (e.g., unreadable fixture) must not propagate."""
    bad_fixture = tmp_path / "fixture.pdf"
    bad_fixture.write_bytes(b"")  # Empty file — read_bytes works, but parse fails later.
    monkeypatch.setattr(warmup_module, "WARMUP_FIXTURE_PATH", bad_fixture)

    async def fake_run(*args, **kwargs):
        raise ValueError("empty pdf")

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    warmup_module.warmup()  # must not raise

    out = capsys.readouterr().out
    assert "failed after" in out


# -----------------------------------------------------------------------------
# Logger choice: warmup uses plain print(), NOT the JSON logger.
# This is deliberate (see warmup.py docstring) — warmup status must be
# visible even if the JSON-logger visibility investigation is still open.
# -----------------------------------------------------------------------------

def test_warmup_logs_have_known_good_prefix(monkeypatch, capsys, tmp_path):
    """Output must use the [mineru-warmup] tag and plain text, not JSON."""
    _seed_fixture(monkeypatch, tmp_path)

    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "fake-out"
        out.mkdir()
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)
    warmup_module.warmup()

    captured = capsys.readouterr().out
    for line in captured.splitlines():
        if line.strip():
            assert line.startswith("[mineru-warmup]"), (
                f"warmup log line missing prefix: {line!r}"
            )
            # Must NOT be JSON (we're deliberately using plain text).
            assert not line.startswith("[mineru-warmup] {"), (
                f"warmup line looks like JSON: {line!r}"
            )
