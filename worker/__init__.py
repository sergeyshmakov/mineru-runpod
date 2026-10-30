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

Before that, an empty ``MINERU_*`` variable is dropped. A RunPod Hub form
sends every field it lists, an untouched one as an empty string, and MinerU
reads its ``MINERU_*`` settings strictly: an empty boolean or log level fails
its config loading, and with it every job, and an empty number logs a warning
on each use. Empty means "not set" on the form, so it is made to mean that
here, before MinerU reads anything. The worker's own ``MINERU_*`` knobs already
treat an empty value as unset, so dropping one changes nothing for them.
"""

import os

for _key in [k for k, v in os.environ.items() if k.startswith("MINERU_") and not v.strip()]:
    del os.environ[_key]

from worker import harness as harness  # noqa: E402, F401 — imported for its side effect
