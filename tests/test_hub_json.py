"""Static checks for the two files RunPod's Hub reads.

Both checks come from the harness, which knows the Hub's constraints and
carries the rules with its own tests. What is specific to this repo is
where the files are and which input roots the validator's jobs are measured
against — and the roots are whatever worker.harness declares, so importing
`worker` is what makes the second check mean anything.
"""

from __future__ import annotations

from pathlib import Path

from runpod_doc_worker.testing import hub

import worker  # noqa: F401 — installs this worker's input roots


_RUNPOD_DIR = Path(__file__).resolve().parents[1] / ".runpod"


def test_hub_json_is_publishable():
    """Every description fits the varchar(191) column the Hub stores it in.

    Over the limit, the push fails with an opaque database error, so long
    guidance belongs in docs/content/docs/guides/ instead.
    """
    hub.check(_RUNPOD_DIR / "hub.json")


def test_validator_inputs_are_reachable():
    """Every volume_path in tests.json sits inside this worker's input roots.

    The Hub validator runs those jobs against a release build. A path
    outside the roots is rejected there rather than here, which is an
    expensive place to find out.
    """
    hub.check_test_inputs(_RUNPOD_DIR / "tests.json")
