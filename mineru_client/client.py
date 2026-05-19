"""Python client for the runpod-mineru serverless service.

Stateless except for the endpoint id + api key. Safe to share across threads.
"""

from __future__ import annotations

import base64
import io
import json
import os
import tarfile
from pathlib import Path
from typing import Any, Literal

import runpod


class MineruClientError(RuntimeError):
    """Raised when the remote handler returns ok=false, or transport fails."""


class MineruClient:
    """Wraps a single deployed runpod-mineru endpoint.

    The handler API is documented in the runpod-mineru repo's handler.py.
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

    def parse_pdf(
        self,
        *,
        pdf_url: str | None = None,
        pdf_b64: str | None = None,
        volume_path: str | None = None,
        start_page: int = 0,
        end_page: int | None = None,
        lang: str = "en",
        backend: str = "vlm-vllm-async-engine",
        formula_enable: bool = True,
        table_enable: bool = True,
        return_format: Literal["tarball_b64", "inline"] = "tarball_b64",
        basename: str = "doc",
        timeout: int = 900,
    ) -> dict[str, Any]:
        """Submit a synchronous parse job. Returns the handler's response dict."""
        provided = sum(1 for x in (pdf_url, pdf_b64, volume_path) if x)
        if provided != 1:
            raise ValueError(
                "exactly one of pdf_url / pdf_b64 / volume_path must be set"
            )

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
            "return": return_format,
            "basename": basename,
        }
        if end_page is not None:
            payload["end_page"] = end_page
        if pdf_url is not None:
            payload["pdf_url"] = pdf_url
        if pdf_b64 is not None:
            payload["pdf_b64"] = pdf_b64
        if volume_path is not None:
            payload["volume_path"] = volume_path

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
    def parse_pdf_from_file(
        client: "MineruClient",
        pdf_path: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience: read a small local PDF and submit as pdf_b64."""
        data = Path(pdf_path).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return client.parse_pdf(pdf_b64=b64, **kwargs)

    # -- Result handling ----------------------------------------------------

    @staticmethod
    def save_tarball(result: dict[str, Any], dest_dir: str | Path) -> Path:
        """Extract the tarball_b64 from `result` into dest_dir. Returns the dir."""
        if "tarball_b64" not in result:
            raise MineruClientError(
                "result has no tarball_b64; was return_format='tarball_b64'?"
            )
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(result["tarball_b64"])
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(dest)
        return dest

    @staticmethod
    def save_inline(result: dict[str, Any], dest_dir: str | Path, basename: str = "doc") -> Path:
        """Write markdown + content_list + middle + images from an inline response."""
        if "markdown" not in result:
            raise MineruClientError(
                "result has no markdown; was return_format='inline'?"
            )
        dest = Path(dest_dir)
        (dest / "images").mkdir(parents=True, exist_ok=True)
        (dest / f"{basename}.md").write_text(result["markdown"], encoding="utf-8")
        (dest / f"{basename}_content_list.json").write_text(
            json.dumps(result.get("content_list", []), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (dest / f"{basename}_middle.json").write_text(
            json.dumps(result.get("middle", {}), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for name, b64 in (result.get("images") or {}).items():
            (dest / "images" / name).write_bytes(base64.b64decode(b64))
        return dest
