"""Pure translation between the official MinerU v4 API and the worker contract.

No network, no SDK — just dict/string transforms, so every rule here is unit
testable in isolation. ``MineruApiClient`` (in ``api_compat.py``) is the thin
I/O shell around these functions.

Why this exists: callers of the official MinerU cloud API
(``mineru.net/api/v4/...``) speak a different vocabulary than the RunPod MinerU
worker. The worker's HTTP envelope is fixed by RunPod (``/run`` + ``{"input":
...}``), so we cannot host MinerU's REST paths; instead we reproduce its
request params and response dicts here and route them onto the worker.

Mapping summary (MinerU → worker):
    url            -> file_url
    model_version  -> tier              (pipeline->basic, vlm->advanced,
                                         MinerU-HTML->flash)
    is_ocr         -> ocr_mode          (True->"ocr", False->"auto")
    page_ranges    -> page_range        ("2,4-6" as is, "2--2" -> "2-r2")
    enable_formula, enable_table, language: accepted, no effect — the
                      open-source MinerU 4 engine has no such switches

And MinerU's task lifecycle onto RunPod's:
    POST /extract/task        -> endpoint.run()      (returns a job id == task_id)
    GET  /extract/task/{id}   -> GET /status/{id}    (status -> MinerU state)
    full_zip_url              -> results[0].tarball_url  (transport="s3")
"""

from __future__ import annotations

from typing import Any


# MinerU `model_version` -> worker `tier`, the nearest MinerU 4 equivalent of
# what the cloud runs for each. `vlm` is the VLM reading layout and content
# itself, which is the `advanced` tier; `pipeline` is the small models alone,
# `basic`. `MinerU-HTML` is the cloud's HTML parser; MinerU 4 parses HTML
# natively, at flash.
MODEL_VERSION_TO_TIER: dict[str, str] = {
    "pipeline": "basic",
    "vlm": "advanced",
    "MinerU-HTML": "flash",
}

# RunPod job status -> MinerU task state. RunPod's terminal states beyond
# COMPLETED (FAILED / TIMED_OUT / CANCELLED) all collapse to MinerU `failed`.
RUNPOD_STATUS_TO_STATE: dict[str, str] = {
    "IN_QUEUE": "pending",
    "IN_PROGRESS": "running",
    "COMPLETED": "done",
    "FAILED": "failed",
    "TIMED_OUT": "failed",
    "CANCELLED": "failed",
}


def model_version_to_tier(model_version: str | None) -> str:
    """Translate a MinerU ``model_version`` to a worker ``tier``.

    Raises ValueError on an unknown value.
    """
    mv = model_version or "pipeline"
    try:
        return MODEL_VERSION_TO_TIER[mv]
    except KeyError:
        raise ValueError(
            f"unknown model_version {mv!r}; expected one of "
            f"{sorted(MODEL_VERSION_TO_TIER)}. For the worker's own tiers "
            f"(flash/basic/standard/advanced) use MineruClient directly."
        ) from None


def to_page_range(page_ranges: str) -> str:
    """Translate a MinerU cloud ``page_ranges`` string to the worker's ``page_range``.

    Both are 1-based and comma-separated; they differ only in how a range
    counts from the end. The cloud writes ``2--2`` (page 2 to the second from
    last), MinerU 4 writes ``2-r2``:

        "5"      -> "5"
        "2,4-6"  -> "2,4-6"
        "2--2"   -> "2-r2"

    Anything else raises ValueError, so a caller learns about a range the
    worker would read differently before the job is submitted.
    """
    s = "".join((page_ranges or "").split())
    if not s:
        raise ValueError("page_ranges is empty; omit it to parse the whole document")

    def _page(num: str, part: str) -> int:
        if not num.isdigit() or int(num) < 1 or num != str(int(num)):
            raise ValueError(
                f"page_ranges part {part!r} is not a 1-based page or range; "
                f"use 'N', 'N-M' or 'N--K' (K counted from the end)"
            )
        return int(num)

    parts: list[str] = []
    for part in s.split(","):
        if "--" in part:
            first, _, from_end = part.partition("--")
            parts.append(f"{_page(first, part)}-r{_page(from_end, part)}")
        elif "-" in part:
            first, _, last = part.partition("-")
            start, end = _page(first, part), _page(last, part)
            if end < start:
                raise ValueError(f"page_ranges part {part!r}: end precedes start")
            parts.append(f"{start}-{end}")
        else:
            parts.append(str(_page(part, part)))
    return ",".join(parts)


def build_worker_payload(
    *,
    url: str,
    model_version: str = "pipeline",
    is_ocr: bool = False,
    page_ranges: str | None = None,
    extra_formats: list[str] | None = None,
    transport: str = "s3",
    archive_format: str = "zip",
) -> dict[str, Any]:
    """Build the worker ``input`` payload from MinerU ``create_task`` params.

    Raises ValueError for features the worker can't honour (``extra_formats``,
    an unreadable ``page_ranges``) so the caller fails fast with an actionable
    message rather than getting a silently-wrong parse.
    """
    if extra_formats:
        raise ValueError(
            "extra_formats (docx/html/latex) is not produced by the RunPod MinerU "
            "worker; it emits markdown + content_list + middle + images only."
        )
    payload: dict[str, Any] = {
        "file_url": url,
        "tier": model_version_to_tier(model_version),
        "ocr_mode": "ocr" if is_ocr else "auto",
        "transport": transport,
        # Request a real .zip so full_zip_url matches the official cloud API
        # (the worker defaults to .tar.gz; the compat client overrides to zip).
        "archive_format": archive_format,
    }
    if page_ranges is not None:
        payload["page_range"] = to_page_range(page_ranges)
    return payload


def runpod_status_to_state(status: str | None) -> str:
    """Map a RunPod job status to a MinerU task state.

    Unknown statuses map to ``running`` (poll-safe: callers keep polling until a
    terminal state or their own timeout).
    """
    return RUNPOD_STATUS_TO_STATE.get(status or "", "running")


def extract_full_zip_url(output: Any) -> str | None:
    """Pull the presigned archive URL out of a worker success response.

    The worker's ``transport:"s3"`` puts a presigned ``tarball_url`` on the first
    (only, for single-file) entry of ``results``; this returns it verbatim as
    MinerU's ``full_zip_url``. The container is whatever the task requested — the
    compat client requests ``archive_format="zip"``, so it is normally a ``.zip``.
    """
    if not isinstance(output, dict):
        return None
    results = output.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0].get("tarball_url")
    return None


def build_create_response(task_id: str) -> dict[str, Any]:
    """Shape a MinerU ``POST /extract/task`` success response."""
    return {"code": 0, "msg": "ok", "trace_id": task_id, "data": {"task_id": task_id}}


def build_task_response(
    task_id: str,
    raw_status: Any,
    *,
    data_id: str | None = None,
) -> dict[str, Any]:
    """Shape a MinerU ``GET /extract/task/{id}`` response from a RunPod status.

    ``raw_status`` is the RunPod ``/status/{id}`` JSON: ``{"status": ...,
    "output": ...}``. Returns the MinerU envelope ``{code, msg, trace_id,
    data:{task_id, state, ...}}``.

    Two worker-specific subtleties are folded in here:

    - The worker signals a soft failure (bad input, parse error) by returning
      ``{"ok": false, "error": ...}`` — sometimes on a job RunPod still reports
      COMPLETED. We treat ``ok is False`` as ``state="failed"``.
    - A ``done`` with results but no ``tarball_url`` means the endpoint lacks the
      ``BUCKET_*`` config that ``transport:"s3"`` needs; a ``done`` with no result
      payload at all gets a generic message. Both are surfaced as ``failed``
      rather than a useless ``done`` with nothing to download.
    """
    status = raw_status.get("status") if isinstance(raw_status, dict) else None
    output = raw_status.get("output") if isinstance(raw_status, dict) else None
    state = runpod_status_to_state(status)

    data: dict[str, Any] = {"task_id": task_id, "state": state, "err_msg": ""}
    if data_id is not None:
        data["data_id"] = data_id

    if state == "done":
        if isinstance(output, dict) and output.get("ok") is False:
            data["state"] = "failed"
            data["err_msg"] = str(output.get("error") or "parse failed")
        else:
            url = extract_full_zip_url(output)
            if url:
                data["full_zip_url"] = url
            elif isinstance(output, dict) and output.get("results"):
                # Completed with results but no tarball_url → object storage is
                # not configured on the endpoint.
                data["state"] = "failed"
                data["err_msg"] = (
                    "endpoint returned no downloadable archive URL. Deploy the "
                    "RunPod endpoint with BUCKET_* env vars so transport='s3' "
                    "produces a presigned archive (surfaced as full_zip_url)."
                )
            else:
                # Completed but no usable result payload at all (empty/odd output).
                data["state"] = "failed"
                data["err_msg"] = "job completed but returned no result payload"
    elif state == "failed":
        # Hard failures (worker crash, OOM, timeout) surface the reason in a
        # top-level `error`; handler-returned errors may sit in `output`. Prefer
        # whichever is present before falling back to the generic status string.
        err = output.get("error") if isinstance(output, dict) else None
        if not err and isinstance(raw_status, dict):
            err = raw_status.get("error")
        data["err_msg"] = str(err) if err else f"job {status}"

    return {"code": 0, "msg": "ok", "trace_id": task_id, "data": data}
