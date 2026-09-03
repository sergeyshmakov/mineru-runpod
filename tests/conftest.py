"""Shared pytest setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the repo root importable so `import handler` works.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Tests should not see any operator credentials.
for key in ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID", "MINERU_TEMPLATE_ID"):
    os.environ.pop(key, None)

# ...nor post anywhere. RunPod injects these two into a real worker, and the SDK
# reads them into module constants at import, so popping them here -- before any
# test imports handler -- is what makes a progress update a no-op under test. A
# test that runs the handler with a job id and no patched sender would otherwise
# reach for the network and fail somewhere unrelated to what it asserts.
for key in ("RUNPOD_WEBHOOK_POST_OUTPUT", "RUNPOD_WEBHOOK_POST_STREAM"):
    os.environ.pop(key, None)

# Install this worker's harness config for the whole session, the way
# importing handler does in production. Without it a test that reaches the
# harness directly runs against its defaults — a different env prefix and
# different input roots — and passes or fails for the wrong reason.
import worker  # noqa: E402, F401
