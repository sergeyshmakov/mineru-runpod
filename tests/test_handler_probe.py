"""Handler-side unit tests. Exercise the parts that don't need a GPU or MinerU. -- probe."""

from __future__ import annotations

import asyncio

import pytest

import handler


def test_handler_probe_mode_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("MINERU_DISABLE_PROBE", "1")
    result = asyncio.run(handler.handler({"input": {"probe": True}}))
    assert result["ok"] is False
    assert "probe is disabled" in result["error"]
    assert "probe" not in result


def test_the_refusal_names_the_knob(monkeypatch):
    """A caller reading this is usually the operator who can act on it."""
    monkeypatch.setenv("MINERU_DISABLE_PROBE", "1")
    result = asyncio.run(handler.handler({"input": {"probe": True}}))
    assert "MINERU_DISABLE_PROBE" in result["error"]


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", " 1 "])
def test_every_affirmative_spelling_turns_the_probe_off(monkeypatch, value):
    monkeypatch.setenv("MINERU_DISABLE_PROBE", value)
    assert handler._probe_allowed() is False


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_an_explicit_negative_leaves_the_probe_on(monkeypatch, value):
    monkeypatch.setenv("MINERU_DISABLE_PROBE", value)
    assert handler._probe_allowed() is True


@pytest.mark.parametrize("value", ["maybe", "typo", "disabled", "2"])
def test_an_unrecognised_value_denies(monkeypatch, value):
    """An operator who typed something into this variable meant to turn the
    probe off. A typo must not be what publishes a filesystem dump."""
    monkeypatch.setenv("MINERU_DISABLE_PROBE", value)
    assert handler._probe_allowed() is False


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_value_is_not_a_setting(monkeypatch, value):
    monkeypatch.setenv("MINERU_DISABLE_PROBE", value)
    assert handler._probe_allowed() is True


def test_handler_probe_mode_enabled_by_default(monkeypatch):
    """Unset means available, which is what this endpoint has always done."""
    monkeypatch.delenv("MINERU_DISABLE_PROBE", raising=False)
    result = asyncio.run(handler.handler({"input": {"probe": True}}))
    assert result["ok"] is True


def test_handler_probe_mode_returns_filesystem_dump():
    result = asyncio.run(handler.handler({"input": {"probe": True}}))
    assert result["ok"] is True
    assert "probe" in result
    assert "env" in result["probe"]
    assert "paths" in result["probe"]
    assert "models_found" in result["probe"]
    # Surfaces the MinerU availability flag so a busted import doesn't hide
    # behind a happy ok=true probe response.
    assert "mineru_available" in result
    assert isinstance(result["mineru_available"], bool)
