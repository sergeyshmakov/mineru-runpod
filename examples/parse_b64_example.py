"""Minimal example: parse a local document by sending it inline as base64.

Accepts any format the worker supports: PDF, image (PNG/JPEG/GIF/BMP/TIFF/WebP),
DOCX, PPTX, XLSX. Only practical for files ≤ ~10 MB on /run and ~20 MB on
/runsync — RunPod's gateway rejects bigger payloads. For larger files, use
a URL or a mounted volume_path.

Usage:
    set RUNPOD_API_KEY=...
    set RUNPOD_ENDPOINT_ID=...
    python examples/parse_b64_example.py path/to/small_doc.pdf
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mineru_client import MineruClient


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: parse_b64_example.py <file_path>", file=sys.stderr)
        return 2
    file_path = Path(sys.argv[1])
    if not file_path.is_file():
        print(f"file not found: {file_path}", file=sys.stderr)
        return 2

    client = MineruClient(
        endpoint_id=os.environ["RUNPOD_ENDPOINT_ID"],
        api_key=os.environ["RUNPOD_API_KEY"],
    )
    result = MineruClient.parse_document_from_file(
        client,
        file_path,
        transport="inline",   # small enough to keep everything in-memory
        basename=file_path.stem,
    )
    entry = MineruClient.first(result)
    print(
        f"ok={result['ok']}  "
        f"elapsed={result['elapsed_seconds']}s  "
        f"version={result['mineru_version']}  "
        f"images={len(entry.get('images') or {})}"
    )
    dest = Path(f"./out/{file_path.stem}")
    client.save_inline(result, dest, basename=file_path.stem)
    print(f"Saved to: {dest.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
