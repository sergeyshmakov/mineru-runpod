"""Container-side worker code for the mineru-runpod handler.

The handler module lives at the repo root (``handler.py``) because that's
what RunPod's serverless CMD invokes. What it orchestrates is split in two:
the MinerU-specific pieces live here, and the engine-agnostic ones —
input transport, outbound target checks, response packaging, structured
logging, redaction, model-cache probes — come from the ``runpod_doc_worker``
package.

Importing ``worker.harness`` is what tells that package about this worker,
so it happens here: every ``from worker import ...`` configures the harness
before anything can call into it.
"""

from worker import harness as harness  # noqa: F401 — imported for its side effect
