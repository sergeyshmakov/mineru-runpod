"""Python client for the mineru-runpod serverless service.

Stateless except for the endpoint id + api key. Safe to share across threads.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Iterable, Literal

import runpod
from runpod_doc_client import (
    ResponseError,
    decode_b64,
    describe_dropped_response,
    download,
    extract,
    limits,
    require_fetchable_url,
    safe_output_name,
)


MineruClientError = ResponseError
"""Raised when the remote handler returns ok=false, or transport fails.

An alias rather than a subclass. The shared reader raises ``ResponseError``
from inside ``download`` and ``extract``, and a subclass here would leave
``except MineruClientError`` not catching it -- which is the single-error-type
property the shared package exists to provide.
"""


# Truthy spellings accepted for the opt-in below. Matches what the worker already
# accepts for MINERU_ALLOW_LOCAL_FETCH, so an operator who has set one does not
# have to discover that the other spells it differently.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _apply_fetch_policy() -> None:
    """Honour MINERU_CLIENT_ALLOW_PRIVATE_FETCH before an archive fetch.

    The shared reader refuses to fetch from an address that is not globally
    routable, judged on the socket it actually connected to. That is the right
    default for a client: the URL comes out of a *response*, so without the check
    a worker could make the machine running this code open connections inside its
    own network.

    It is wrong for one documented deployment, though. An S3-compatible store on
    a private network -- a self-hosted MinIO beside the endpoint is the case in
    the docs -- serves presigned URLs on exactly the addresses the policy
    rejects, and this used to work. Hence the opt-in, read per call so a process
    can set it late, and named for the client because the worker's
    MINERU_ALLOW_LOCAL_FETCH governs a different fetch in a different process.

    Only ever widens. A caller who set the shared flag directly keeps it, which
    matters because the error message tells them to do precisely that.
    """
    if os.environ.get("MINERU_CLIENT_ALLOW_PRIVATE_FETCH", "").strip().lower() in _TRUTHY:
        limits.ALLOW_PRIVATE_FETCH_TARGETS = True



class MineruClient:
    """Wraps a single deployed mineru-runpod endpoint.

    The job contract is documented in the docs site's API reference
    (docs/content/docs/reference/api.mdx in the mineru-runpod repo).
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
        file_name: str | None = None,
        tier: Literal["flash", "basic", "standard", "advanced"] = "standard",
        ocr_mode: Literal["auto", "txt", "ocr"] = "auto",
        page_range: str | None = None,
        server_url: str | None = None,
        transport: Literal["tarball_b64", "inline", "s3"] = "tarball_b64",
        formats: Iterable[str] | str | None = None,
        basename: str = "doc",
        timeout: int = 900,
    ) -> dict[str, Any]:
        """Submit a synchronous parse job. Returns the handler's response dict.

        The response shape is ``{"ok": True, "results": [{...}], "debug": {...}}``;
        a single-file job has a one-element ``results`` list. Use
        ``MineruClient.first(result)`` to grab the entry without indexing.

        Input formats (detected by the worker, by content):
            PDF, images, Office (DOC/DOCX/PPT/PPTX/XLS/XLSX), RTF, OpenDocument,
            EPUB, OFD, HTML and CSV/TSV. Everything but PDFs and images is
            parsed natively at the flash tier, whatever ``tier`` says. Text
            formats (CSV, TSV, HTML fragments) need ``file_name`` (e.g.
            "table.csv") unless the URL or volume path already ends in the
            extension; only the extension is used.

        Tiers (MinerU 4.1.x), for PDFs and images:
            "flash"     Text layer and native formats, no models; Flash
                        OCR (small models, no VLM) for scans.
            "basic"     Small models for layout, OCR, formulas and tables.
            "standard"  Small models + the VLM (default).
            "advanced"  The VLM leads layout and content; slowest, best on
                        hard documents.

        MinerU 4's OCR model covers Chinese, Japanese, English and Latin-script
        languages; scanned pages in other scripts (Cyrillic, Arabic, ...)
        need a VLM tier (standard or advanced).

        ``ocr_mode``: "auto" lets MinerU sample the document and choose, "txt" trusts the text
        layer, "ocr" OCRs everything. ``page_range`` (PDFs only) is MinerU's
        1-based grammar: "1-5,8", "r3-r1" (r1 is the last page). ``server_url``
        points the VLM tiers at an external OpenAI-compatible VLM server.

        Transport:
            "tarball_b64"  (default) base64-encoded .tar.gz inside the entry
            "inline"       per-format keys (markdown / content_list / middle /
                           images) inside the entry, filtered by ``formats``
            "s3"           uploads the .tar.gz to an S3-compatible bucket
                           configured on the worker via BUCKET_* env vars
                           and returns a presigned URL valid for ~1 hour.
                           Use this when outputs would exceed RunPod's
                           gateway response cap (~20 MB).

        Formats:
            Subset of ["markdown", "content_list", "middle", "images",
            "content_list_v2", "structured_content", "html", "latex", "docx",
            "epub", "pdf"]. Omit to get the first four inline. The last five are
            renders, produced only when listed — for every transport: an
            archive (tarball_b64 / s3) always carries the first six and adds
            the renders asked for. A bare string is wrapped to a one-list.
        """
        provided = sum(1 for x in (file_url, file_b64, volume_path) if x)
        if provided != 1:
            raise ValueError(
                "exactly one of file_url / file_b64 / volume_path must be set"
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
        # rp_validator declares fields with typed schemas (e.g. page_range must
        # be a string) and rejects JSON null even when the field is "optional".
        # Letting the handler apply its own defaults is safer than transmitting
        # None.
        payload: dict[str, Any] = {
            "tier": tier,
            "ocr_mode": ocr_mode,
            "transport": transport,
            "basename": basename,
        }
        if page_range is not None:
            payload["page_range"] = page_range
        if file_name is not None:
            payload["file_name"] = file_name
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

        if result is None:
            # Not a handler bug: the gateway dropped the response. See
            # `_no_output_message`.
            raise MineruClientError(describe_dropped_response(transport, bulky_artifact="middle.json"))
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

        Any format the worker parses: PDF, images, Office and OpenDocument
        files, RTF, EPUB, OFD, HTML, CSV/TSV. The file's own name goes along
        as ``file_name`` (only its extension is used) unless you pass one, so
        CSV, TSV and HTML need nothing extra.
        """
        path = Path(file_path)
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        if "." in path.name:
            kwargs.setdefault("file_name", path.name)
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
        """Extract the ``tarball_b64`` archive from `result` into dest_dir.

        Accepts either the full response wrapper or a single result entry.
        Autodetects the container — ``.tar.gz`` (default) or ``.zip``
        (``archive_format="zip"``). Returns the dir.
        """
        entry = MineruClient._unwrap(result)
        if "tarball_b64" not in entry:
            raise MineruClientError(
                "result has no tarball_b64; was transport='tarball_b64'?"
            )
        return extract(
            decode_b64(entry["tarball_b64"], what="tarball_b64"), dest_dir
        )

    @staticmethod
    def save_s3_tarball(result: dict[str, Any], dest_dir: str | Path) -> Path:
        """Download the presigned `tarball_url` from a `transport: "s3"` response
        and extract it into dest_dir. Returns the dir.

        Accepts either the full response wrapper or a single result entry.
        Autodetects the container (``.tar.gz`` or ``.zip``).

        The presigned URL expires after ~1 hour; call this promptly after the
        job returns.
        """
        entry = MineruClient._unwrap(result)
        if "tarball_url" not in entry:
            raise MineruClientError(
                "result has no tarball_url; was transport='s3'?"
            )
        _apply_fetch_policy()
        require_fetchable_url(entry["tarball_url"])
        return extract(download(entry["tarball_url"]), dest_dir)

    @staticmethod
    def save_inline(
        result: dict[str, Any],
        dest_dir: str | Path,
        basename: str | None = None,
    ) -> Path:
        """Write the inline format keys (markdown, the JSON renderings, images
        and any requested render) onto disk under the worker's own file names.

        Accepts either the full response wrapper or a single result entry.
        Any format absent from the entry (because the caller filtered with
        ``formats=``) is silently skipped — only the requested artifacts
        get written.

        When ``basename`` is None (the default), the entry's own ``basename``
        is used; explicit values override.
        """
        entry = MineruClient._unwrap(result)
        if "markdown" not in entry:
            present = sorted(k for k in entry if k != "basename")
            raise MineruClientError(
                "result has no markdown; was transport='inline'? "
                f"The entry carries: {present or 'nothing'}. "
                "If you passed `formats`, markdown has to be in the list -- "
                "filtering it out removes it from the response."
            )
        if basename is None:
            basename = entry.get("basename") or "doc"
        # Both the stem and the image keys come from the result dict, and both
        # become filenames below — check them before opening anything.
        basename = safe_output_name(basename, what="basename")
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
        for key, suffix in (("content_list_v2", "_content_list_v2.json"),
                            ("structured_content", "_structured_content.json")):
            if key in entry:
                (dest / f"{basename}{suffix}").write_text(
                    json.dumps(entry[key], indent=2, ensure_ascii=False), encoding="utf-8"
                )
        for key, suffix in (("html", ".html"), ("latex", ".tex")):
            if isinstance(entry.get(key), str):
                (dest / f"{basename}{suffix}").write_text(entry[key], encoding="utf-8")
        # The binary renders arrive as {filename: base64}, one file each; the
        # name is the worker's, but it becomes a path here, so it is checked.
        for key in ("docx", "epub", "pdf"):
            for name, b64 in (entry.get(key) or {}).items():
                safe_name = safe_output_name(name, what=f"{key} name")
                (dest / safe_name).write_bytes(decode_b64(b64, what=f"{key} {name!r}"))
        images = entry.get("images") or {}
        if images:
            (dest / "images").mkdir(parents=True, exist_ok=True)
            for name, b64 in images.items():
                safe_name = safe_output_name(name, what="image name")
                (dest / "images" / safe_name).write_bytes(
                    decode_b64(b64, what=f"image {name!r}")
                )
        return dest
