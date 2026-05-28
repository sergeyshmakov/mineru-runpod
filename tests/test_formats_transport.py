"""Schema validation for the orthogonal `transport` + `formats` job-input fields."""

from __future__ import annotations

import pytest

from worker.schema import VALID_FORMATS, validate_input


# -----------------------------------------------------------------------------
# transport
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("transport", ["tarball_b64", "inline", "s3"])
def test_transport_each_valid_value_accepted(transport):
    cleaned = validate_input({"file_b64": "AA==", "transport": transport})
    assert cleaned["transport"] == transport


def test_transport_default_is_tarball_b64():
    cleaned = validate_input({"file_b64": "AA=="})
    assert cleaned["transport"] == "tarball_b64"


def test_transport_invalid_value_rejected():
    with pytest.raises(ValueError, match="transport must be one of"):
        validate_input({"file_b64": "AA==", "transport": "carrier-pigeon"})


# -----------------------------------------------------------------------------
# formats
# -----------------------------------------------------------------------------

def test_formats_default_is_all_four():
    cleaned = validate_input({"file_b64": "AA=="})
    assert cleaned["formats"] == list(VALID_FORMATS)


def test_formats_single_member_subset_accepted():
    cleaned = validate_input({"file_b64": "AA==", "formats": ["markdown"]})
    assert cleaned["formats"] == ["markdown"]


def test_formats_two_member_subset_accepted():
    cleaned = validate_input({"file_b64": "AA==", "formats": ["markdown", "images"]})
    assert cleaned["formats"] == ["markdown", "images"]


def test_formats_all_four_accepted():
    cleaned = validate_input({
        "file_b64": "AA==",
        "formats": ["images", "middle", "content_list", "markdown"],
    })
    # Order is preserved as the caller sent it; canonical order is NOT forced.
    assert cleaned["formats"] == ["images", "middle", "content_list", "markdown"]


def test_formats_empty_list_rejected():
    with pytest.raises(ValueError, match="formats must not be empty"):
        validate_input({"file_b64": "AA==", "formats": []})


def test_formats_unknown_member_rejected():
    with pytest.raises(ValueError, match="formats entry"):
        validate_input({"file_b64": "AA==", "formats": ["markdown", "pdf"]})


def test_formats_non_string_member_rejected():
    with pytest.raises(ValueError, match="must be strings"):
        validate_input({"file_b64": "AA==", "formats": ["markdown", 7]})


def test_formats_non_list_rejected():
    # rp_validator catches the type mismatch first (its own error message),
    # then our normalize step would also reject — either way, ValueError fires.
    with pytest.raises(ValueError, match="formats"):
        validate_input({"file_b64": "AA==", "formats": "markdown"})


def test_formats_duplicates_collapsed_preserving_order():
    cleaned = validate_input({
        "file_b64": "AA==",
        "formats": ["markdown", "images", "markdown", "images", "middle"],
    })
    assert cleaned["formats"] == ["markdown", "images", "middle"]


# -----------------------------------------------------------------------------
# legacy `return` field — rejected by rp_validator as an unknown field
# -----------------------------------------------------------------------------

def test_legacy_return_field_rejected_as_unknown():
    """The old `return` field is gone. rp_validator rejects unknown keys, so
    callers using the old API name get a clear ``Unexpected input`` error
    rather than mysteriously receiving a default-transport response.
    Pre-1.0 cutover — no silent fallback, no migration alias.
    """
    with pytest.raises(ValueError, match="Unexpected input.*return"):
        validate_input({"file_b64": "AA==", "return": "inline"})
