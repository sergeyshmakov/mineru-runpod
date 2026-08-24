"""Two defects found while reviewing the sibling PaddleOCR-VL worker.

Both were carried here rather than there: `deploy.py` was copied out of this
repo, and the schema shares the page-field shape. Kept in one file because what
they have in common is how they were found — a review of other code — and
because that is worth knowing about a test file that otherwise looks arbitrary.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import runpod

from worker import schema


# -----------------------------------------------------------------------------
# deploy.py passed a keyword the SDK does not accept
# -----------------------------------------------------------------------------

def test_the_sdk_still_has_no_execution_timeout_parameter() -> None:
    """The guard on the fix below. `create_endpoint` takes no execution-timeout
    argument and no **kwargs, so passing one raised TypeError and no endpoint was
    created at all."""
    parameters = inspect.signature(runpod.create_endpoint).parameters
    assert not any("execution" in name for name in parameters), (
        "the SDK grew the parameter — apply it in deploy.py and delete this test"
    )
    assert not any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    ), "the SDK now swallows unknown keywords; this test no longer proves anything"


def test_deploy_does_not_pass_the_execution_timeout_to_the_sdk() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("deploy.py").read_text(
        encoding="utf-8"
    )
    assert "execution_timeout_ms" not in source, (
        "deploy.py must not pass a keyword create_endpoint rejects"
    )
    assert "NOT applied" in source, (
        "deploy.py must say the execution timeout is reported, not applied"
    )


# -----------------------------------------------------------------------------
# Booleans are not page numbers
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["start_page", "end_page"])
@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_page_index_is_refused(field: str, value: bool) -> None:
    """rp_validator skips its declared type check when the value is an instance
    of the default's type, and `isinstance(True, int)` is True — so `true` reached
    the page resolver and was used as index 1."""
    with pytest.raises(ValueError, match="must be an integer, not a boolean"):
        schema.validate_input({"file_b64": "ZmFrZQ==", field: value})


def test_real_page_numbers_still_pass() -> None:
    cleaned = schema.validate_input(
        {"file_b64": "ZmFrZQ==", "start_page": 1, "end_page": 4}
    )
    assert (cleaned["start_page"], cleaned["end_page"]) == (1, 4)
