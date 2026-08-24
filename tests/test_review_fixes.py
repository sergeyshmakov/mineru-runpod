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
    """The first fix here made deploy.py *report* the timeout instead of passing a
    keyword `create_endpoint` rejects. That was the right half of the answer: the
    SDK has no parameter, but `executionTimeoutMs` is a REST field, so the flag can
    be honoured after creation. See tests/test_runpod_rest.py for the rest.
    """
    source = Path(__file__).resolve().parents[1].joinpath("deploy.py").read_text(
        encoding="utf-8"
    )
    assert "execution_timeout_ms" not in source, (
        "deploy.py must not pass a keyword create_endpoint rejects"
    )
    assert "runpod_rest.set_execution_timeout" in source, (
        "the timeout is applied via the REST API now, not merely reported"
    )


# -----------------------------------------------------------------------------
# Booleans are not page numbers
# -----------------------------------------------------------------------------

# Derived from the schema, not typed out: an int field added later is covered
# here the moment it is declared, which is the property worth testing.
_INT_FIELDS = sorted(
    name for name, spec in schema.INPUT_SCHEMA.items() if spec["type"] is int
)


def test_the_schema_still_declares_int_fields() -> None:
    """Without this, an empty _INT_FIELDS would make the test below vacuous and
    pass while guarding nothing."""
    assert _INT_FIELDS, "INPUT_SCHEMA declares no int field; the guard is untested"


@pytest.mark.parametrize("field", _INT_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_is_refused_wherever_an_int_is_declared(
    field: str, value: bool
) -> None:
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
