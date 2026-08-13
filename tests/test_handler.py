"""Handler-side unit tests. Exercise the parts that don't need a GPU or MinerU.

The handler module is intentionally written so it imports cleanly even when
the heavy `mineru` dependency is unavailable (it wraps that import in try /
except and falls back to a "mineru is not importable" path). That lets us
test input validation, packaging, and error handling on plain Python CI.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import tarfile
from pathlib import Path

import pytest

import handler
from worker import io as worker_io


# -----------------------------------------------------------------------------
# _resolve_input_bytes
# -----------------------------------------------------------------------------

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


# -----------------------------------------------------------------------------
# _detect_format
# -----------------------------------------------------------------------------

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


# -----------------------------------------------------------------------------
# _package_tarball / _package_inline
# -----------------------------------------------------------------------------

def _seed_mineru_output(dir_: Path, basename: str) -> None:
    (dir_ / f"{basename}.md").write_text("# heading\n\nbody\n", encoding="utf-8")
    (dir_ / f"{basename}_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "body", "page_idx": 0}]),
        encoding="utf-8",
    )
    (dir_ / f"{basename}_middle.json").write_text(json.dumps({"k": 1}), encoding="utf-8")
    (dir_ / "images").mkdir()
    (dir_ / "images" / "fig1.png").write_bytes(b"\x89PNG fake")


def test_package_tarball_includes_all_artefacts(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")

    encoded = handler._package_tarball(out)
    raw = base64.b64decode(encoded)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = set(tar.getnames())
    assert "doc.md" in names
    assert "doc_content_list.json" in names
    assert "doc_middle.json" in names
    assert "images/fig1.png" in names or "images" in names


def test_package_inline_returns_full_payload(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")

    pkg = handler._package_inline(out, "doc")
    assert pkg["markdown"].startswith("# heading")
    assert pkg["content_list"][0]["text"] == "body"
    assert pkg["middle"]["k"] == 1
    assert "fig1.png" in pkg["images"]
    assert base64.b64decode(pkg["images"]["fig1.png"]) == b"\x89PNG fake"


# -----------------------------------------------------------------------------
# handler() top-level error paths
# -----------------------------------------------------------------------------

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


def test_validate_input_rejects_invalid_transport_value():
    with pytest.raises(ValueError, match="input validation"):
        handler._validate_input({"file_b64": "AA==", "transport": "tarball-xml"})


def test_validate_input_defaults_applied():
    cleaned = handler._validate_input({"file_b64": "AA=="})
    assert cleaned["start_page"] == 0
    assert cleaned["end_page"] == -1
    assert cleaned["lang"] == "en"
    assert cleaned["backend"] == "vlm-auto-engine"
    assert cleaned["transport"] == "tarball_b64"
    assert cleaned["formats"] == ["markdown", "content_list", "middle", "images"]
    assert cleaned["basename"] == "doc"


def test_validate_input_accepts_s3_transport():
    cleaned = handler._validate_input({"file_b64": "AA==", "transport": "s3"})
    assert cleaned["transport"] == "s3"


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


def test_validate_input_backfills_an_empty_basename():
    cleaned = handler._validate_input({"file_b64": "AA==", "basename": ""})
    assert cleaned["basename"] == "doc"


@pytest.mark.parametrize("lang", ["en", "ch", "east_slavic", "zh-Hans"])
def test_validate_input_accepts_real_lang_codes(lang):
    assert handler._validate_input({"file_b64": "AA==", "lang": lang})["lang"] == lang


@pytest.mark.parametrize("lang", ["en us", "../en", "e" * 33, "en/ch"])
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
    too_big = "A" * (worker_io.MAX_INLINE_B64_CHARS + 1)
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


def test_validate_input_accepts_a_private_server_url():
    # An operator's own model server may well live on a private address.
    cleaned = handler._validate_input({
        "file_b64": "AA==",
        "backend": "vlm-http-client",
        "server_url": "http://10.1.2.3:8000",
    })
    assert cleaned["server_url"] == "http://10.1.2.3:8000"


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


# -----------------------------------------------------------------------------
# probe mode — bypasses MinerU and dumps filesystem layout.
# -----------------------------------------------------------------------------

def test_handler_probe_mode_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("MINERU_DISABLE_PROBE", "1")
    result = asyncio.run(handler.handler({"input": {"probe": True}}))
    assert result["ok"] is False
    assert "probe is disabled" in result["error"]
    assert "probe" not in result


def test_handler_probe_mode_enabled_by_default(monkeypatch):
    monkeypatch.delenv("MINERU_DISABLE_PROBE", raising=False)
    result = asyncio.run(handler.handler({"input": {"probe": True}}))
    assert result["ok"] is True


def test_handler_probe_mode_returns_filesystem_dump():
    result = asyncio.run(handler.handler({"input": {"probe": True}}))
    assert result["ok"] is True
    assert "probe" in result
    assert "env" in result["probe"]
    assert "paths" in result["probe"]
    assert "models_found" in result["probe"]
    # Surfaces the MinerU availability flag so a busted import doesn't hide
    # behind a happy ok=true probe response.
    assert "mineru_available" in result
    assert isinstance(result["mineru_available"], bool)


# -----------------------------------------------------------------------------
# Progress updates — regression guard for the packaging/completion race.
#
# progress_update POSTs {"status": "IN_PROGRESS"} from a background thread
# to the same endpoint the SDK posts the final result to. Any update emitted
# after the parse phase runs milliseconds before the handler returns, so it
# can land AFTER the COMPLETED post and overwrite the finished job back to
# IN_PROGRESS — the job then appears stuck forever. The parse phase must
# therefore be the last progress event of a request.
# -----------------------------------------------------------------------------

def test_no_progress_update_after_parse(monkeypatch):
    async def fake_run(file_bytes, *, basename, work_dir, **kwargs):
        out = work_dir / "out"
        out.mkdir()
        (out / f"{basename}.md").write_text("# fake\n", encoding="utf-8")
        return out

    monkeypatch.setattr("worker.parse.run_mineru", fake_run)

    phases: list = []
    monkeypatch.setattr(
        "runpod.serverless.progress_update",
        lambda job, data: phases.append(data.get("phase")),
    )

    result = asyncio.run(handler.handler({
        "id": "race-regression-test",
        "input": {"file_b64": "JVBERi0xLjQK", "basename": "doc", "transport": "inline"},
    }))

    assert result["ok"] is True
    assert phases, "expected progress updates during the request"
    assert phases[-1] == "parsing", (
        f"last progress phase must be 'parsing'; a later update (got {phases!r}) "
        f"races the COMPLETED result post and can strand the job IN_PROGRESS"
    )


# -----------------------------------------------------------------------------
# _package_s3 — env-var validation only; the actual upload requires boto3 +
# a live S3 endpoint and is not exercised here.
# -----------------------------------------------------------------------------

def test_package_s3_requires_bucket_env_vars(tmp_path, monkeypatch):
    # Strip any leaked credentials from the test process.
    for var in (
        "BUCKET_ENDPOINT_URL",
        "BUCKET_NAME",
        "BUCKET_ACCESS_KEY_ID",
        "BUCKET_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    with pytest.raises(ValueError, match="BUCKET_"):
        handler._package_s3(out, "doc")


def test_package_s3_complains_about_each_missing_env_var(tmp_path, monkeypatch):
    # All four names should be mentioned in the error.
    for var in (
        "BUCKET_ENDPOINT_URL",
        "BUCKET_NAME",
        "BUCKET_ACCESS_KEY_ID",
        "BUCKET_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    with pytest.raises(ValueError) as excinfo:
        handler._package_s3(out, "doc")
    msg = str(excinfo.value)
    assert "BUCKET_ENDPOINT_URL" in msg
    assert "BUCKET_NAME" in msg
    assert "BUCKET_ACCESS_KEY_ID" in msg
    assert "BUCKET_SECRET_ACCESS_KEY" in msg


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
    from worker import package as worker_package

    if env_value is None:
        monkeypatch.delenv("BUCKET_PRESIGN_TTL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("BUCKET_PRESIGN_TTL_SECONDS", env_value)
    assert worker_package.presign_ttl_seconds() == expected


def test_package_s3_signs_with_the_configured_lifetime(tmp_path, monkeypatch):
    """The knob has to reach the signing call and the reported value, not just
    resolve correctly on its own."""
    # package_s3 imports boto3 lazily, so the patch goes on the module itself.
    import boto3  # noqa: PLC0415

    recorded = {}

    class _FakeS3:
        def put_object(self, **kwargs):
            recorded["key"] = kwargs["Key"]

        def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
            recorded["op"] = op
            recorded["expires_in"] = ExpiresIn
            return f"https://bucket.example/{Params['Key']}?signature=x"

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3())
    for var, val in (
        ("BUCKET_ENDPOINT_URL", "https://bucket.example"),
        ("BUCKET_NAME", "parses"),
        ("BUCKET_ACCESS_KEY_ID", "id"),
        ("BUCKET_SECRET_ACCESS_KEY", "secret"),
        ("BUCKET_PRESIGN_TTL_SECONDS", "900"),
    ):
        monkeypatch.setenv(var, val)

    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    result = handler._package_s3(out, "doc")

    assert recorded["expires_in"] == 900
    assert result["tarball_url_expires_in"] == 900
    assert result["bucket_key"] == recorded["key"]
    assert result["bucket_bytes"] > 0


def test_build_tarball_bytes_roundtrip(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    data = handler._build_tarball_bytes(out)
    # Should be valid gzip-tar with the seeded files inside.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = set(tar.getnames())
    assert "doc.md" in names
    assert "doc_content_list.json" in names


def test_build_zip_bytes_roundtrip(tmp_path):
    import zipfile  # noqa: PLC0415

    out = tmp_path / "out"
    out.mkdir()
    _seed_mineru_output(out, "doc")
    data = handler._build_zip_bytes(out)
    assert data[:4] == b"PK\x03\x04"  # zip magic
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
    assert "doc.md" in names
    assert "doc_content_list.json" in names
    assert "images/fig1.png" in names
