"""What this worker tells the harness about itself.

`runpod-doc-worker` is engine-agnostic: it fetches input bytes, checks
outbound targets, packs responses, emits structured logs and probes the
model cache without knowing what parses the document. The handful of values
it cannot derive — what this worker's operator-facing env vars are called,
where a `volume_path` input may live, what MinerU's weights look like on
disk — are declared here, once, at import.

Importing this module installs the config. `worker/__init__.py` imports it,
so any `from worker import ...` (including `import handler`) configures the
harness before a job can reach it. The harness reads the active config at
call time rather than at import, so ordering beyond that does not matter.

`env_prefix` is why adopting the harness did not disturb a running
endpoint: MINERU_ALLOW_LOCAL_FETCH, MINERU_VOLUME_ROOTS and
MINERU_DISABLE_PROBE keep the spellings `.runpod/hub.json` documents them
under, because the prefix comes from here rather than from the package.
"""

from __future__ import annotations

from typing import Any

from runpod_doc_worker import config
from runpod_doc_worker.config import DEFAULT_VOLUME_ROOTS


def _telemetry_mirror(level: str, msg: str, fields: dict[str, Any]) -> None:
    """Second sink for log records: the OTLP/HTTP logs exporter.

    Registered as `log_mirror`, so the harness calls this after it has
    written the stdout line. Dormant unless OTEL_EXPORTER_OTLP_ENDPOINT is
    set — `is_enabled()` is what makes the no-telemetry path free.

    The import is local because `worker.telemetry` reaches back into
    `worker.parse` and the harness's redaction, and because a module-level
    import here would run at config time on a path that may never export a
    single record.
    """
    from worker import telemetry as _telemetry  # noqa: PLC0415

    if _telemetry.is_enabled():
        _telemetry.emit_log(level, msg, fields)


config.configure(
    config.WorkerConfig(
        env_prefix="MINERU",
        logger_name="mineru-worker",
        # `/worker` is where the image bakes the Hub validator's fixture
        # (Dockerfile: COPY .runpod/test-fixture.pdf /worker/test-fixture.pdf),
        # which the boot warmup parses. MINERU_VOLUME_ROOTS still replaces
        # the whole list at runtime.
        volume_roots=DEFAULT_VOLUME_ROOTS + ("/worker",),
        # Which weights actually loaded — Pro-2605 vs an older or unexpected
        # variant — reported in every response's `debug.model_dir`.
        model_globs=("models--opendatalab--MinerU*",),
        # Resolved by the `probe: true` response to diagnose a cache that is
        # present but not where MinerU's library looks: the VLM backend's
        # model and the pipeline backend's.
        probe_model_ids=(
            "opendatalab/MinerU2.5-Pro-2605-1.2B",
            "opendatalab/PDF-Extract-Kit-1.0",
        ),
        # Both are things an operator can get wrong in a way that looks like
        # a missing model, so the probe reports them alongside the HF ones.
        probe_env_keys=("MINERU_MODEL_SOURCE", "MINERU_VL_MODEL_NAME"),
        log_mirror=_telemetry_mirror,
    )
)
