"""Python client for the mineru-runpod serverless service.

Stateless except for the endpoint id + api key. Safe to share across threads.
"""

from __future__ import annotations

import base64
import io
import json
import os
import tarfile
from pathlib import Path
from typing import Any, Iterable, Literal

import runpod


class MineruClientError(RuntimeError):
    """Raised when the remote handler returns ok=false, or transport fails."""


class MineruClient:
    """Wraps a single deployed mineru-runpod endpoint.

    The handler API is documented in the mineru-runpod repo's handler.py.
    """

    def __init__(self, endpoint_id: str, api_key: str | None = None) -> None:
        if not endpoint_id:
            raise ValueError("endpoint_id is required")
        runpod.api_key = api_key or os.environ.get("RUNPOD_API_KEY")
        if not runpod.api_key:
            raise ValueError(
                "api_key not provided and RUNPOD_API_KEY env var is unset"
            )
        self.endpoint_id = endpoint_id
        self._endpoint = runpod.Endpoint(endpoint_id)

    # -- Submission ---------------------------------------------------------

    def parse_document(
        self,
        *,
        file_url: str | None = None,
        file_b64: str | None = None,
        volume_path: str | None = None,
        start_page: int = 0,
        end_page: int | None = None,
        lang: str = "en",
        backend: str = "vlm-auto-engine",
        server_url: str | None = None,
        formula_enable: bool = True,
        table_enable: bool = True,
        transport: Literal["tarball_b64", "inline", "s3"] = "tarball_b64",
        formats: Iterable[str] | str | None = None,
        basename: str = "doc",
        timeout: int = 900,
    ) -> dict[str, Any]:
        """Submit a synchronous parse job. Returns the handler's response dict.

        The response shape is ``{"ok": True, "results": [{...}], "debug": {...}}``;
        a single-file job has a one-element ``results`` list. Use
        ``MineruClient.first(result)`` to grab the entry without indexing.

        Input formats (auto-detected by the worker):
            PDF, image (PNG/JPEG/GIF/BMP/TIFF/WebP), DOCX, PPTX, XLSX.

        Backends (MinerU 3.2.x):
            "pipeline"           PaddleOCR + layout/formula/table. 109-language OCR.
                                  Best for non-Latin scripts; respects `lang`.
            "vlm-auto-engine"    VLM via vLLM (default). Fast on EN/CH; ignores `lang`.
            "vlm-http-client"    VLM via external vLLM server (`server_url` required).
            "hybrid-auto-engine" Pipeline + VLM auto-routed based on page content.
            "hybrid-http-client" Hybrid with external VLM server.

        For non-English/Chinese scripts (e.g. Russian/Cyrillic), use
        `backend="pipeline"` with a script-family `lang` code such as
        `"east_slavic"` (Russian/Ukrainian/Belarusian), `"cyrillic"`,
        `"latin"`, `"arabic"`, `"devanagari"`. NOT ISO codes.

        Transport:
            "tarball_b64"  (default) base64-encoded .tar.gz inside the entry
            "inline"       per-format keys (markdown / content_list / middle /
                           images) inside the entry, filtered by ``formats``
            "s3"           uploads the .tar.gz to an S3-compatible bucket
                           configured on the worker via BUCKET_* env vars
                           and returns a presigned URL valid for ~1 hour.
                           Use this when outputs would exceed RunPod's
                           gateway response cap (~20 MB).

        Formats (inline transport only):
            Subset of ["markdown", "content_list", "middle", "images"].
            Omit to get all four. A bare string is wrapped to a one-list
            for ergonomics. For tarball_b64 and s3 the archive carries all
            four artifacts regardless.
        """
        provided = sum(1 for x in (file_url, file_b64, volume_path) if x)
        if provided != 1:
            raise ValueError(
                "exactly one of file_url / file_b64 / volume_path must be set"
            )
        if backend.endswith("-http-client") and not server_url:
            raise ValueError(
                f"backend={backend!r} requires `server_url` pointing at an "
                f"external vLLM OpenAI-compatible server"
            )

        # Client-side sugar: accept a bare string for a single format. The
        # wire contract always sends a list — the worker rejects a string at
        # the schema boundary.
        if isinstance(formats, str):
            formats_list: list[str] | None = [formats]
        elif formats is None:
            formats_list = None
        else:
            formats_list = list(formats)

        # Build the payload field-by-field, skipping None values. The handler's
        # rp_validator declares fields with typed schemas (e.g. end_page must be
        # int) and rejects JSON null even when the field is "optional". Letting
        # the handler apply its own defaults is safer than transmitting None.
        payload: dict[str, Any] = {
            "start_page": start_page,
            "lang": lang,
            "backend": backend,
            "formula_enable": formula_enable,
            "table_enable": table_enable,
            "transport": transport,
            "basename": basename,
        }
        if end_page is not None:
            payload["end_page"] = end_page
        if server_url is not None:
            payload["server_url"] = server_url
        if file_url is not None:
            payload["file_url"] = file_url
        if file_b64 is not None:
            payload["file_b64"] = file_b64
        if volume_path is not None:
            payload["volume_path"] = volume_path
        if formats_list is not None:
            payload["formats"] = formats_list

        try:
            result = self._endpoint.run_sync(payload, timeout=timeout)
        except Exception as e:
            raise MineruClientError(f"endpoint transport failed: {e}") from e

        if not isinstance(result, dict):
            raise MineruClientError(f"unexpected handler return type: {type(result)}")
        if not result.get("ok", False):
            # Prefer the structured `error` key; if missing (e.g. earlier handler
            # versions that only set `traceback`), fall back to the traceback's
            # last line, which is the raised exception's message.
            err = (
                result.get("error")
                or (result.get("traceback") or "").strip().split("\n")[-1]
                or "<no error>"
            )
            raise MineruClientError(f"handler returned ok=false: {err}")
        return result

    @staticmethod
    def parse_document_from_file(
        client: "MineruClient",
        file_path: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience: read a small local file and submit as file_b64.

        Any format the worker supports (PDF, image, DOCX, PPTX, XLSX).
        """
        data = Path(file_path).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return client.parse_document(file_b64=b64, **kwargs)

    # -- Result handling ----------------------------------------------------

    @staticmethod
    def first(result: dict[str, Any]) -> dict[str, Any]:
        """Return the first entry from a job result's ``results`` list.

        Single-file jobs always have a one-element ``results`` list, so this
        is the ergonomic accessor that skips the ``[0]`` indexing. Raises
        ``MineruClientError`` if the response has no ``results`` array or
        it's empty.
        """
        entries = result.get("results")
        if not isinstance(entries, list) or not entries:
            raise MineruClientError(
                "result has no `results` entries; "
                "was the job successful? Check `result['ok']` and `result.get('error')`."
            )
        return entries[0]

    @staticmethod
    def _unwrap(arg: dict[str, Any]) -> dict[str, Any]:
        """Internal: accept either a wrapper dict or a single result entry.

        Edge case: an ill-formed wrapper (``{"results": []}`` or
        ``{"results": [non_dict]}``) falls through and returns ``arg`` itself —
        the downstream "no tarball_b64 / no markdown / no tarball_url" error
        then surfaces. The handler never emits empty results on success, so
        this only matters for hand-crafted test fixtures.
        """
        if "results" in arg:
            entries = arg.get("results") or []
            if entries and isinstance(entries[0], dict):
                return entries[0]
        return arg

    @staticmethod
    def save_tarball(result: dict[str, Any], dest_dir: str | Path) -> Path:
        """Extract the tarball_b64 from `result` into dest_dir. Returns the dir.

        Accepts either the full response wrapper or a single result entry.
        """
        entry = MineruClient._unwrap(result)
        if "tarball_b64" not in entry:
            raise MineruClientError(
                "result has no tarball_b64; was transport='tarball_b64'?"
            )
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(entry["tarball_b64"])
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(dest)
        return dest

    @staticmethod
    def save_s3_tarball(result: dict[str, Any], dest_dir: str | Path) -> Path:
        """Download the presigned `tarball_url` from a `transport: "s3"` response
        and extract it into dest_dir. Returns the dir.

        Accepts either the full response wrapper or a single result entry.

        The presigned URL expires after ~1 hour; call this promptly after the
        job returns.
        """
        entry = MineruClient._unwrap(result)
        if "tarball_url" not in entry:
            raise MineruClientError(
                "result has no tarball_url; was transport='s3'?"
            )
        # Lazy import so the client stays dependency-light for callers that
        # only use the tarball_b64 / inline paths.
        import urllib.request  # noqa: PLC0415
        with urllib.request.urlopen(entry["tarball_url"]) as resp:
            data = resp.read()
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.extractall(dest)
        return dest

    @staticmethod
    def save_inline(
        result: dict[str, Any],
        dest_dir: str | Path,
        basename: str | None = None,
    ) -> Path:
        """Write the inline format keys (markdown / content_list / middle /
        images) onto disk.

        Accepts either the full response wrapper or a single result entry.
        Any format absent from the entry (because the caller filtered with
        ``formats=``) is silently skipped — only the requested artifacts
        get written.

        When ``basename`` is None (the default), the entry's own ``basename``
        is used; explicit values override.
        """
        entry = MineruClient._unwrap(result)
        if "markdown" not in entry:
            raise MineruClientError(
                "result has no markdown; was transport='inline'?"
            )
        if basename is None:
            basename = entry.get("basename") or "doc"
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{basename}.md").write_text(entry["markdown"], encoding="utf-8")
        if "content_list" in entry:
            (dest / f"{basename}_content_list.json").write_text(
                json.dumps(entry.get("content_list") or [], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        if "middle" in entry:
            (dest / f"{basename}_middle.json").write_text(
                json.dumps(entry.get("middle") or {}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        images = entry.get("images") or {}
        if images:
            (dest / "images").mkdir(parents=True, exist_ok=True)
            for name, b64 in images.items():
                (dest / "images" / name).write_bytes(base64.b64decode(b64))
        return dest
