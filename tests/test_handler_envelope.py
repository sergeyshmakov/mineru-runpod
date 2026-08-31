"""Handler-side unit tests. Exercise the parts that don't need a GPU or MinerU. -- envelope."""

from __future__ import annotations

import asyncio
import base64

import pytest
from runpod_doc_worker.transport import io as worker_io

import handler


def test_resolve_requires_exactly_one_source():
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(handler._resolve_input_bytes({}))
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(handler._resolve_input_bytes({"file_url": "x", "file_b64": "y"}))


def test_resolve_b64_roundtrip():
    payload = base64.b64encode(b"%PDF-1.4 inline").decode("ascii")
    raw, src = asyncio.run(handler._resolve_input_bytes({"file_b64": payload}))
    assert raw == b"%PDF-1.4 inline"
    assert src == "b64"


def test_resolve_b64_rejects_oversized_payload():
    too_big = base64.b64encode(b"x" * (handler.MAX_INLINE_FILE_MB * 1024 * 1024 + 1)).decode("ascii")
    with pytest.raises(ValueError, match="inline file too large"):
        asyncio.run(handler._resolve_input_bytes({"file_b64": too_big}))


def test_resolve_volume_path_reads_file(tmp_path, monkeypatch):
    # Point the input roots at the pytest tmp dir: its location differs by
    # platform, so pinning it here keeps the test deterministic everywhere.
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 volume")
    raw, src = asyncio.run(handler._resolve_input_bytes({"volume_path": str(pdf)}))
    assert raw == b"%PDF-1.4 volume"
    assert src.startswith("volume:")


def test_resolve_volume_path_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_VOLUME_ROOTS", str(tmp_path))
    missing = tmp_path / "nope.pdf"
    with pytest.raises(ValueError, match="volume_path not found"):
        asyncio.run(handler._resolve_input_bytes({"volume_path": str(missing)}))


@pytest.mark.parametrize(
    ("source_label", "expected"),
    [
        ("b64", "b64"),
        ("url:https://example.com/report.pdf?token=secret", "url"),
        ("volume:/customer/acme/report.pdf", "volume"),
        ("other:customer-data", "unknown"),
        ("", "unknown"),
    ],
)
def test_telemetry_source_kind_is_bounded(source_label, expected):
    assert worker_io.telemetry_source_kind(source_label) == expected


def test_detect_format_pdf():
    assert handler._detect_format(b"%PDF-1.4\nfoo") == "pdf"


def test_detect_format_image_png():
    assert handler._detect_format(b"\x89PNG\r\n\x1a\nfoo") == "image"


def test_detect_format_image_jpeg():
    assert handler._detect_format(b"\xff\xd8\xff\xe0junk") == "image"


def test_detect_format_ooxml():
    # DOCX/PPTX/XLSX all start with the ZIP magic.
    assert handler._detect_format(b"PK\x03\x04rest") == "ooxml"


def test_detect_format_unknown():
    assert handler._detect_format(b"not a real file") == "unknown"
    assert handler._detect_format(b"") == "unknown"


def test_handler_returns_error_on_bad_input():
    result = asyncio.run(handler.handler({"input": {}}))  # no source provided
    # RunPod-convention: top-level `error` key marks the job FAILED.
    assert "error" in result
    assert result["ok"] is False
    assert "exactly one" in result["error"]
    # Even on error, the metadata fields are present.
    assert "mineru_version" in result
    assert "elapsed_seconds" in result


def test_handler_rejects_bad_basename():
    result = asyncio.run(handler.handler({"input": {"file_b64": "AA==", "basename": "../bad"}}))
    assert "error" in result
    assert result["ok"] is False
    # rp_validator reports its own message; we just check it's about input.
    assert "input validation" in result["error"].lower() or "basename" in result["error"].lower()


def test_handler_failure_response_reports_compacted_text(monkeypatch):
    """Both text fields of a failure response go through the same reduction.

    The reduction itself is the harness's; what this asserts is that the
    handler routes `error` and `traceback` through it, so a signed URL a
    caller passed in does not come back in the response it gets.
    """
    async def boom(*args, **kwargs):
        raise RuntimeError(
            "GET failed for 'https://files.example.com/doc.pdf?sig=abcdef123456'"
        )

    monkeypatch.setattr(worker_io, "resolve_input_bytes", boom)
    result = asyncio.run(handler.handler({
        "id": "compact-test",
        "input": {"file_b64": "JVBERi0xLjQK"},
    }))

    assert result["ok"] is False
    assert "sig=" not in result["error"]
    assert "sig=" not in result["traceback"]
    assert "https://files.example.com/doc.pdf" in result["error"]


def test_validate_input_rejects_unknown_backend():
    with pytest.raises(ValueError, match="backend must be one of"):
        handler._validate_input({"file_b64": "AA==", "backend": "magic-engine"})


def test_validate_input_http_client_requires_server_url():
    with pytest.raises(ValueError, match="server_url"):
        handler._validate_input({"file_b64": "AA==", "backend": "vlm-http-client"})


def test_validate_input_rejects_overlong_basename():
    with pytest.raises(ValueError, match="basename must be at most"):
        handler._validate_input({"file_b64": "AA==", "basename": "d" * 129})


def test_validate_input_accepts_basename_at_the_limit():
    cleaned = handler._validate_input({"file_b64": "AA==", "basename": "d" * 128})
    assert cleaned["basename"] == "d" * 128


# The charset rule accepts unicode alphanumerics, and a filesystem bounds a name
# in bytes — so the character limit alone does not keep the generated filenames
# legal. 78 CJK characters plus the longest suffix is exactly 255 bytes.
def test_validate_input_accepts_a_multibyte_basename_that_fits():
    basename = "文" * 78
    cleaned = handler._validate_input({"file_b64": "AA==", "basename": basename})
    assert cleaned["basename"] == basename
    from worker import schema

    assert len(
        f"{basename}{schema.LONGEST_ARTEFACT_SUFFIX}".encode()
    ) == schema.MAX_OUTPUT_NAME_BYTES


def test_validate_input_rejects_a_multibyte_basename_that_overruns_the_name():
    with pytest.raises(ValueError, match="too long for the filenames it produces"):
        handler._validate_input({"file_b64": "AA==", "basename": "文" * 79})


def test_validate_input_rejects_the_reported_cjk_basename():
    # 80 CJK characters pass the 128-character rule and produce 261 bytes.
    with pytest.raises(ValueError, match="261 bytes"):
        handler._validate_input({"file_b64": "AA==", "basename": "文" * 80})


def test_validate_input_backfills_an_empty_basename():
    cleaned = handler._validate_input({"file_b64": "AA==", "basename": ""})
    assert cleaned["basename"] == "doc"


@pytest.mark.parametrize("lang", ["en", "ch", "east_slavic", "zh-Hans"])
def test_validate_input_accepts_real_lang_codes(lang):
    assert handler._validate_input({"file_b64": "AA==", "lang": lang})["lang"] == lang


@pytest.mark.parametrize(
    "lang",
    [
        "en us", "../en", "e" * 33, "en/ch",
        # A `$` anchor also matches just before a final newline, so these have
        # to be rejected by the anchoring rather than by the character class.
        "en\n", "east_slavic\n", "en\r\n", "en\n\n",
    ],
)
def test_validate_input_rejects_malformed_lang(lang):
    with pytest.raises(ValueError, match="lang must be a short"):
        handler._validate_input({"file_b64": "AA==", "lang": lang})


def test_validate_input_rejects_end_page_before_start_page():
    with pytest.raises(ValueError, match="end_page must be >= start_page"):
        handler._validate_input({"file_b64": "AA==", "start_page": 10, "end_page": 4})


def test_validate_input_allows_a_single_page_range():
    cleaned = handler._validate_input(
        {"file_b64": "AA==", "start_page": 4, "end_page": 4}
    )
    assert (cleaned["start_page"], cleaned["end_page"]) == (4, 4)


def test_validate_input_keeps_the_open_ended_range():
    cleaned = handler._validate_input({"file_b64": "AA==", "start_page": 10})
    assert cleaned["end_page"] == -1


def test_page_ceiling_is_off_by_default(monkeypatch):
    monkeypatch.delenv("MINERU_MAX_PAGES_PER_JOB", raising=False)
    cleaned = handler._validate_input(
        {"file_b64": "AA==", "start_page": 0, "end_page": 4999}
    )
    assert cleaned["end_page"] == 4999


def test_page_ceiling_rejects_a_larger_range(monkeypatch):
    monkeypatch.setenv("MINERU_MAX_PAGES_PER_JOB", "50")
    with pytest.raises(ValueError, match="allows at most 50"):
        handler._validate_input({"file_b64": "AA==", "start_page": 0, "end_page": 50})


def test_page_ceiling_allows_a_range_at_the_limit(monkeypatch):
    monkeypatch.setenv("MINERU_MAX_PAGES_PER_JOB", "50")
    cleaned = handler._validate_input(
        {"file_b64": "AA==", "start_page": 10, "end_page": 59}
    )
    assert cleaned["end_page"] == 59


def test_page_ceiling_does_not_apply_to_an_open_ended_range(monkeypatch):
    monkeypatch.setenv("MINERU_MAX_PAGES_PER_JOB", "5")
    cleaned = handler._validate_input({"file_b64": "AA=="})
    assert cleaned["end_page"] == -1


def test_page_ceiling_ignores_a_malformed_value(monkeypatch):
    monkeypatch.setenv("MINERU_MAX_PAGES_PER_JOB", "fifty")
    cleaned = handler._validate_input(
        {"file_b64": "AA==", "start_page": 0, "end_page": 999}
    )
    assert cleaned["end_page"] == 999


def test_resolve_b64_rejects_oversized_encoded_payload():
    # Rejected on the encoded length, before the decoded copy is allocated.
    # One character past the harness's own bound, rather than a copy of its
    # arithmetic that would stop describing it the moment the headroom moved.
    too_big = "A" * (worker_io.max_inline_b64_chars() + 1)
    with pytest.raises(ValueError, match="inline file too large"):
        asyncio.run(handler._resolve_input_bytes({"file_b64": too_big}))


def test_validate_input_rejects_non_http_file_url():
    with pytest.raises(ValueError, match="file_url must be an http"):
        handler._validate_input({"file_url": "file:///etc/hosts"})


def test_validate_input_rejects_non_http_server_url():
    with pytest.raises(ValueError, match="server_url must be an http"):
        handler._validate_input({
            "file_b64": "AA==",
            "backend": "vlm-http-client",
            "server_url": "vllm.internal:8000",
        })


def test_a_private_server_url_is_accepted_by_default():
    """Compatibility is the default, and that is a decision rather than an
    oversight.

    Applying the outbound-target policy here was tried and reverted. Every
    existing `*-http-client` deployment whose model server is on a private
    address — the ordinary way to run one — would have started failing jobs that
    had always succeeded, and this repo publishes from the commit title, so the
    change would have arrived as a patch release discovered through broken jobs.

    The exposure is real and documented: `server_url` is a job input, so any
    caller can aim the worker at an internal address. Operators whose endpoint is
    reachable by untrusted callers set MINERU_ENFORCE_TARGET_POLICY.
    """
    cleaned = handler._validate_input({
        "file_b64": "AA==",
        "backend": "vlm-http-client",
        "server_url": "http://10.1.2.3:8000",
    })
    assert cleaned["server_url"] == "http://10.1.2.3:8000"


def test_the_shape_check_still_applies_by_default():
    """Off does not mean unvalidated: a scheme-less or hostless value is still
    refused, because it is malformed rather than merely private."""
    with pytest.raises(ValueError, match="server_url"):
        handler._validate_input({
            "file_b64": "AA==",
            "backend": "vlm-http-client",
            "server_url": "vllm.internal:8000",
        })


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.10:8000",
        "http://10.1.2.3:8000",
    ],
)
def test_the_policy_refuses_private_server_urls_when_enabled(url, monkeypatch):
    """With the flag set, `server_url` gets exactly the policy `file_url` has.
    The metadata endpoint is in the list deliberately — it is the target that
    turns this from a misconfiguration into an SSRF."""
    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    with pytest.raises(ValueError, match="MINERU_ALLOWED_SERVER_HOSTS"):
        handler._validate_input({
            "file_b64": "AA==",
            "backend": "vlm-http-client",
            "server_url": url,
        })


def test_an_allowlisted_private_host_is_permitted(monkeypatch):
    """How an operator with a private model server enforces the policy.

    The earlier version of this test used MINERU_ALLOW_LOCAL_FETCH, and that was
    wrong in a way worth recording: the flag lifts the address policy for *every*
    field and every target, so it re-admitted arbitrary private `server_url`
    values from any caller and disabled the same protection on `file_url`. The
    "recipe" the docs gave was strictly worse than not enforcing the policy at
    all.
    """
    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", "10.1.2.3")
    cleaned = handler._validate_input({
        "file_b64": "AA==",
        "backend": "vlm-http-client",
        "server_url": "http://10.1.2.3:8000",
    })
    assert cleaned["server_url"] == "http://10.1.2.3:8000"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.10:8000",
    ],
)
def test_the_allowlist_permits_only_what_it_names(url, monkeypatch):
    """The point of an allowlist over a global flag: everything else stays
    refused, the metadata endpoint included."""
    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", "10.1.2.3")
    with pytest.raises(ValueError, match="MINERU_ALLOWED_SERVER_HOSTS"):
        handler._validate_input({
            "file_b64": "AA==",
            "backend": "vlm-http-client",
            "server_url": url,
        })


def test_the_allowlist_does_not_match_by_suffix(monkeypatch):
    """`evil-vllm.internal` must not satisfy an entry of `vllm.internal`."""
    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", "vllm.internal")
    with pytest.raises(ValueError):
        handler._validate_input({
            "file_b64": "AA==",
            "backend": "vlm-http-client",
            "server_url": "http://evil-vllm.internal:8000",
        })


def test_the_allowlist_is_case_insensitive_and_tolerates_spacing(monkeypatch):
    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", " VLLM.Internal , other.host ")
    monkeypatch.setattr(
        "worker.schema._net.require_http_url",
        lambda url, *, field: "vllm.internal",
    )
    cleaned = handler._validate_input({
        "file_b64": "AA==",
        "backend": "vlm-http-client",
        "server_url": "http://vllm.internal:8000",
    })
    assert cleaned["server_url"] == "http://vllm.internal:8000"


def test_a_public_server_url_needs_listing_once_the_policy_is_on(monkeypatch):
    """The contract change that closed DNS rebinding on this field.

    A public address used to pass under enforcement on the strength of where it
    resolved. That check is precisely what rebinding defeats: the engine resolves
    the host again and opens the connection itself, so an answer that is public
    here can be private there. Enforcement therefore requires the operator to name
    the host, and a name they chose cannot be rebound by a caller.

    Without the policy the field keeps its shape check only, which is the
    documented default and is what most endpoints run.
    """
    url = "https://8.8.8.8/v1"
    payload = {
        "file_b64": "AA==",
        "backend": "vlm-http-client",
        "server_url": url,
    }

    monkeypatch.delenv("MINERU_ENFORCE_TARGET_POLICY", raising=False)
    assert handler._validate_input(dict(payload))["server_url"] == url

    monkeypatch.setenv("MINERU_ENFORCE_TARGET_POLICY", "1")
    monkeypatch.delenv("MINERU_ALLOWED_SERVER_HOSTS", raising=False)
    with pytest.raises(ValueError, match="MINERU_ALLOWED_SERVER_HOSTS"):
        handler._validate_input(dict(payload))

    monkeypatch.setenv("MINERU_ALLOWED_SERVER_HOSTS", "8.8.8.8")
    assert handler._validate_input(dict(payload))["server_url"] == url

def test_validate_input_defaults_effort_to_none():
    cleaned = handler._validate_input({"file_b64": "AA=="})
    assert cleaned["effort"] is None


def test_validate_input_accepts_effort_with_hybrid_backend():
    cleaned = handler._validate_input(
        {"file_b64": "AA==", "backend": "hybrid-auto-engine", "effort": "high"}
    )
    assert cleaned["effort"] == "high"


def test_validate_input_rejects_invalid_effort_value():
    with pytest.raises(ValueError, match="effort must be one of"):
        handler._validate_input(
            {"file_b64": "AA==", "backend": "hybrid-auto-engine", "effort": "turbo"}
        )


def test_validate_input_rejects_effort_on_non_hybrid_backend():
    with pytest.raises(ValueError, match="effort is only valid with a hybrid"):
        handler._validate_input(
            {"file_b64": "AA==", "backend": "vlm-auto-engine", "effort": "high"}
        )


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        (None, 3600),        # unset → the default hour
        ("", 3600),          # blank → the default hour
        ("900", 900),
        ("30", 60),          # below the floor → clamped up
        ("999999999", 604800),  # above the signing maximum → clamped down
        ("soon", 3600),      # unparseable → the default, not a failed job
    ],
)
def test_presign_ttl_resolution(monkeypatch, env_value, expected):
    from runpod_doc_worker.transport import package as worker_package

    if env_value is None:
        monkeypatch.delenv("BUCKET_PRESIGN_TTL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("BUCKET_PRESIGN_TTL_SECONDS", env_value)
    assert worker_package.presign_ttl_seconds() == expected
