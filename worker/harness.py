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
endpoint: MINERU_ALLOW_LOCAL_FETCH and MINERU_VOLUME_ROOTS keep the
spellings `.runpod/hub.json` documents them under, because the prefix comes
from here rather than from the package.

MINERU_DISABLE_PROBE is not in that list because the harness does not read
it at all. Who may ask this endpoint for its filesystem layout is decided in
`handler.py`, under a name this repo owns — see `_probe_allowed` there.
"""

from __future__ import annotations

from typing import Any

from runpod_doc_worker import config
from runpod_doc_worker.transport import response_size as _response_size
from runpod_doc_worker.config import DEFAULT_VOLUME_ROOTS
from runpod_doc_worker.contract.artifacts import Artifact


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
        # No model globs or probe ids: the harness looks for them in the
        # Hugging Face hub cache (`models--*`), and MinerU 4 keeps its weights
        # as plain directories under its own model root instead. The worker
        # reports them itself, from MinerU's registry — see `worker.models`.
        model_globs=(),
        probe_model_ids=(),
        # Things an operator can get wrong in a way that looks like a missing
        # model. MINERU_VL_MODEL_NAME is a 3.x variable that MinerU 4 rejects
        # alongside a per-job `server_url`; an endpoint deployed from the 1.x
        # form still carries it, so the probe says so.
        probe_env_keys=(
            "MINERU_HOME",
            "MINERU_MODEL_SOURCE",
            "MINERU_MODEL_SMALL_BACKEND",
            "MINERU_MODEL_VLM_ENGINE",
            "MINERU_VL_MODEL_NAME",
        ),
        log_mirror=_telemetry_mirror,
    )
)


# What `worker.parse` writes into the output directory, and what each file
# becomes in an inline response. Declaration order is the canonical output
# order and what worker.schema validates `formats` against, so a key added
# here reaches the input contract with it. `DEFAULT_FORMATS` below is the
# inline default.
#
# The content lists' defaults are lists rather than the {} the kind would
# derive, because callers index them.
#
# markdown is required: it is what a caller asked for, and an empty string in
# its place is worth less to them than a failed job they can retry. The others
# are worth shipping without — a corrupt content_list still leaves a usable
# document, and one unreadable image should not cost a caller the other forty.
# Those degrade instead, and say so in the response.

# Refuse a response the RunPod gateway would discard rather than have it dropped.
# Over ~20 MB the gateway returns COMPLETED with no `output` key at all, so the
# caller receives None having paid for the parse -- see the harness's packaging
# guide. Off by default there, because a library should not start raising from a
# version bump; on here, because the alternative is a silent failure.
#
# BULKY_ARTIFACT names the heaviest optional output so the refusal can suggest the
# smallest `formats` change that would fit.
_response_size.ENFORCE_RESPONSE_CAP = True
_response_size.BULKY_ARTIFACT = "middle.json"

MANIFEST = (
    Artifact("markdown", ("{basename}.md",), kind="text", required=True),
    Artifact("content_list", ("{basename}_content_list.json",), kind="json", default=[]),
    Artifact("middle", ("{basename}_middle.json",), kind="json"),
    Artifact("images", ("images/*",), kind="b64map"),
    Artifact("content_list_v2", ("{basename}_content_list_v2.json",), kind="json", default=[]),
    Artifact("structured_content", ("{basename}_structured_content.json",), kind="json"),
    # MinerU's other render targets, written only when `formats` asks for
    # them (see RENDER_FORMATS). HTML embeds its images; LaTeX references the
    # `images/` files; the binary ones arrive inline as {filename: base64}.
    Artifact("html", ("{basename}.html",), kind="text"),
    Artifact("latex", ("{basename}.tex",), kind="text"),
    Artifact("docx", ("{basename}.docx",), kind="b64map"),
    Artifact("epub", ("{basename}.epub",), kind="b64map"),
    Artifact("pdf", ("{basename}.pdf",), kind="b64map"),
)

# The manifest keys that cost a render, so are produced only on request — for
# every transport: an archive carries the core artifacts plus these, if asked.
RENDER_FORMATS = ("html", "latex", "docx", "epub", "pdf")

# What an inline response carries when the caller does not choose: the four
# keys it has always carried. The archive transports ship every artifact
# regardless; adding the two newer JSON renderings to the inline default
# would only bring a large document closer to the response cap.
DEFAULT_FORMATS = ("markdown", "content_list", "middle", "images")
