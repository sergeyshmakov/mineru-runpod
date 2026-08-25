"""Handler-side unit tests. Exercise the parts that don't need a GPU or MinerU. -- egress."""

from __future__ import annotations

import asyncio

import handler


def test_no_progress_update_after_parse(monkeypatch):
    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)

    phases: list = []
    monkeypatch.setattr(
        "runpod.serverless.progress_update",
        lambda job, data: phases.append(data.get("phase")),
    )

    result = asyncio.run(handler.handler({
        "id": "race-regression-test",
        "input": {"file_b64": "JVBERi0xLjQK", "basename": "doc", "transport": "inline"},
    }))

    assert result["ok"] is True
    assert phases, "expected progress updates during the request"
    assert phases[-1] == "parsing", (
        f"last progress phase must be 'parsing'; a later update (got {phases!r}) "
        f"races the COMPLETED result post and can strand the job IN_PROGRESS"
    )
