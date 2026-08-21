"""The handler's use of the log stream: every line carries the job id.

Formatting, flushing, level gating and the contextvar itself belong to the
harness and are covered in its own suite. What has to hold here is the
wiring: handler() pins the id RunPod gave it, so lines emitted anywhere
under one request can be correlated with that request.
"""

from __future__ import annotations

import asyncio
import json

from runpod_doc_worker.obs import logging as worker_logging

import handler


def _stub_run_mineru(monkeypatch):
    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        return out
    monkeypatch.setattr("worker.parse.run_mineru", fake_run)


def test_handler_sets_job_id_contextvar(monkeypatch, capsys):
    """End-to-end: handler() pins job["id"] into the contextvar and log lines carry it."""
    _stub_run_mineru(monkeypatch)
    monkeypatch.setenv("LOG_FORMAT", "json")

    captured: dict = {}

    async def spy_handler(job):
        result = await handler.handler(job)
        captured["job_id_during_request"] = worker_logging.job_id_var.get()
        return result

    asyncio.run(spy_handler({
        "id": "queued-job-uuid-789",
        "input": {"file_b64": "JVBERi0xLjQK", "basename": "test"},
    }))

    assert captured["job_id_during_request"] == "queued-job-uuid-789"

    # The "starting job" line should be in stdout with the correct job_id.
    out = capsys.readouterr().out
    starting_lines = [
        json.loads(ln) for ln in out.splitlines()
        if ln.startswith("{") and '"starting job"' in ln
    ]
    assert starting_lines, "no 'starting job' log line emitted"
    assert starting_lines[0]["job_id"] == "queued-job-uuid-789"


def test_handler_uses_fallback_when_no_job_id(monkeypatch):
    """Sync clients without a queued job have no id; handler uses <unknown>."""
    _stub_run_mineru(monkeypatch)

    captured: dict = {}

    async def spy():
        await handler.handler({
            # No "id" key in the job dict.
            "input": {"file_b64": "JVBERi0xLjQK", "basename": "test"},
        })
        captured["job_id"] = worker_logging.job_id_var.get()

    asyncio.run(spy())
    assert captured["job_id"] == "<unknown>"
