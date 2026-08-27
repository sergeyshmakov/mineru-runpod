"""MinerU-API-compatible client over a deployed mineru-runpod endpoint.

``MineruApiClient`` reproduces the surface of the official MinerU cloud API
(``mineru.net/api/v4/...``) — ``create_task`` / ``get_task``, returning the same
response dicts — but talks to a RunPod serverless endpoint underneath. Code
written against the official REST API keeps working after swapping the
constructor; the migration is import + constructor + auth.

    # before — official MinerU SaaS
    res = requests.post("https://mineru.net/api/v4/extract/task",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"url": pdf_url, "model_version": "vlm"})
    task_id = res.json()["data"]["task_id"]
    # ... poll GET /api/v4/extract/task/{task_id} until state == "done" ...

    # after — self-hosted on RunPod
    client = MineruApiClient(endpoint_id="...", api_key="...")
    task_id = client.create_task(pdf_url, model_version="vlm")["data"]["task_id"]
    done = client.wait_for_task(task_id)          # convenience (not in MinerU's API)
    client.download_results(done, "./out")        # full_zip_url is a .zip here

This is a *trial / comparison* on-ramp, not a permanent production interface:
for the worker's richer native features (inline markdown, volume_path, format
filtering, the hybrid / http-client backends) use ``MineruClient`` directly.

Faithfulness notes / known gaps (raise rather than silently mis-parse):
    - model_version 'MinerU-HTML' and extra_formats (docx/html/latex): unsupported.
    - page_ranges: single contiguous 1-based range only ('5' or '2-6').
    - full_zip_url is a presigned **.zip** (the compat client requests
      archive_format='zip', matching the cloud API); requires the endpoint to be
      deployed with BUCKET_* env vars (transport='s3').
    - is_ocr / no_cache / cache_tolerance: accepted but no-op (no worker knob).
    - callback: rejected — a RunPod webhook's payload (the raw /status envelope)
      differs from MinerU's signed {checksum, content} callback, so a MinerU
      callback handler can't consume it; poll with get_task()/wait_for_task().
    - seed: accepted but unused (only relevant to callback, which is rejected).
    - data_id is echoed back from an in-process map; it is not persisted on the
      endpoint, so get_task() from a *different* process won't echo it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import runpod
from runpod_doc_client import download, extract, require_fetchable_url

from ._mapping import (
    build_create_response,
    build_task_response,
    build_worker_payload,
)
from .client import MineruClientError


def _download_and_extract(url: str, dest_dir: str | Path) -> Path:
    """Download an archive URL and extract it, autodetecting `.zip` vs `.tar.gz`.

    The compat client requests `.zip` (to match the cloud API's full_zip_url),
    but this handles both containers so it works against any worker
    `tarball_url` regardless of how the task was created. The presigned URL is
    short-lived -- call promptly after the task is ``done``.
    """
    require_fetchable_url(url)
    return extract(download(url), dest_dir)


class MineruApiClient:
    """MinerU v4 API-compatible facade over one mineru-runpod endpoint.

    Stateless except for the endpoint id + api key and an in-process map of
    ``task_id -> data_id`` (used only to echo ``data_id`` back in ``get_task``).
    """

    def __init__(
        self,
        endpoint_id: str,
        api_key: str | None = None,
        *,
        wait_transport: str = "s3",
    ) -> None:
        if not endpoint_id:
            raise ValueError("endpoint_id is required")
        runpod.api_key = api_key or os.environ.get("RUNPOD_API_KEY")
        if not runpod.api_key:
            raise ValueError(
                "api_key not provided and RUNPOD_API_KEY env var is unset"
            )
        self.endpoint_id = endpoint_id
        self._endpoint = runpod.Endpoint(endpoint_id)
        # transport the worker uses so a finished job exposes a URL we can map to
        # MinerU's full_zip_url. "s3" requires BUCKET_* env vars on the endpoint.
        self._wait_transport = wait_transport
        self._data_ids: dict[str, str] = {}

    # -- Task lifecycle (MinerU-shaped) ------------------------------------

    def create_task(
        self,
        url: str,
        *,
        model_version: str = "pipeline",
        is_ocr: bool = False,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
        data_id: str | None = None,
        page_ranges: str | None = None,
        callback: str | None = None,
        seed: str | None = None,
        extra_formats: list[str] | None = None,
        no_cache: bool = False,
        cache_tolerance: int | None = None,
    ) -> dict[str, Any]:
        """Submit a URL parse task. Mirrors ``POST /api/v4/extract/task``.

        Returns ``{"code": 0, "msg": "ok", "trace_id": ..., "data":
        {"task_id": ...}}``. The ``task_id`` is the RunPod job id; poll it with
        :meth:`get_task`.

        ``is_ocr`` / ``seed`` / ``no_cache`` / ``cache_tolerance`` are accepted
        for signature compatibility with the official API but have no worker-side
        effect (the worker has no result cache). ``callback`` is **rejected**: a
        RunPod webhook delivers a different, unsigned payload (the raw /status
        envelope) than MinerU's signed ``{checksum, content}`` callback, so an
        existing MinerU callback handler can't parse or verify it — poll with
        :meth:`get_task` / :meth:`wait_for_task` instead. See the module docstring
        for the full gap list.
        """
        if not url:
            raise ValueError("url is required")
        if callback:
            raise ValueError(
                "callback is not supported by the compat client: a RunPod webhook "
                "delivers a different, unsigned payload (the raw /status envelope) "
                "than MinerU's signed {checksum, content} callback, so existing "
                "MinerU callback handlers can't parse or verify it. Poll with "
                "get_task() / wait_for_task() instead."
            )

        payload = build_worker_payload(
            url=url,
            model_version=model_version,
            enable_formula=enable_formula,
            enable_table=enable_table,
            language=language,
            page_ranges=page_ranges,
            extra_formats=extra_formats,
            transport=self._wait_transport,
        )

        try:
            job = self._endpoint.run(payload)
        except Exception as e:  # noqa: BLE001 — uniform transport-error surface
            raise MineruClientError(f"endpoint submission failed: {e}") from e

        task_id = job.job_id
        if data_id is not None:
            self._data_ids[task_id] = data_id
        return build_create_response(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Poll a task. Mirrors ``GET /api/v4/extract/task/{task_id}``.

        Returns the MinerU envelope with ``data.state`` in
        ``pending | running | done | failed``. On ``done`` the entry carries
        ``full_zip_url`` (a presigned ``.zip``); on ``failed`` it carries
        ``err_msg``.
        """
        if not task_id:
            raise ValueError("task_id is required")
        try:
            raw = self._endpoint.rp_client.get(
                f"{self._endpoint.endpoint_id}/status/{task_id}"
            )
        except Exception as e:  # noqa: BLE001 — uniform transport-error surface
            raise MineruClientError(f"status query failed: {e}") from e
        return build_task_response(task_id, raw, data_id=self._data_ids.get(task_id))

    # -- Convenience (NOT part of MinerU's API) ----------------------------

    def wait_for_task(
        self,
        task_id: str,
        *,
        poll_interval: float = 2.0,
        timeout: float = 900.0,
    ) -> dict[str, Any]:
        """Poll :meth:`get_task` until the task reaches a terminal state.

        Returns the final ``get_task`` response (``state`` is ``done`` or
        ``failed``). Raises ``MineruClientError`` if ``timeout`` elapses first. A
        transient status-query failure does not abort the poll — it is retried
        until the timeout budget is spent. The official API has no wait endpoint;
        this is a client convenience.
        """
        if poll_interval <= 0:
            raise ValueError("poll_interval must be > 0")
        elapsed = 0.0
        while True:
            try:
                response = self.get_task(task_id)
            except MineruClientError as e:
                # Transient status-query failure (5xx / connection blip). Don't
                # discard a healthy long-running job over one bad poll; retry
                # until the timeout budget is spent.
                if elapsed >= timeout:
                    raise MineruClientError(
                        f"task {task_id} did not finish within {timeout}s "
                        f"(last error: {e})"
                    ) from e
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue
            state = response["data"]["state"]
            if state in ("done", "failed"):
                return response
            if elapsed >= timeout:
                raise MineruClientError(
                    f"task {task_id} did not finish within {timeout}s "
                    f"(last state={state!r})"
                )
            time.sleep(poll_interval)
            elapsed += poll_interval

    def download_results(
        self,
        response_or_task_id: dict[str, Any] | str,
        dest_dir: str | Path,
    ) -> Path:
        """Download and extract a finished task's archive into ``dest_dir``.

        Accepts a ``get_task`` response (preferred — avoids a re-poll) or a bare
        ``task_id``. The archive behind ``full_zip_url`` is a ``.zip`` (``.tar.gz``
        also handled); this unpacks it so callers don't have to care about the
        format. The presigned URL is short-lived, so call this promptly after
        the task is ``done``.
        """
        if isinstance(response_or_task_id, str):
            response = self.get_task(response_or_task_id)
        else:
            response = response_or_task_id

        data = response.get("data", {}) if isinstance(response, dict) else {}
        url = data.get("full_zip_url")
        if not url:
            raise MineruClientError(
                f"no full_zip_url to download (state={data.get('state')!r}); "
                f"only present when state == 'done'"
            )
        return _download_and_extract(url, dest_dir)
