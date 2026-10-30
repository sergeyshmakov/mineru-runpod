"""MinerU lazy import + the single async parse entry point."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# MinerU's heavy imports run lazily inside run_mineru so the handler module
# itself imports on a CPU-only test machine (CI exercises input validation
# and packaging without needing a GPU). Module-level only does a soft probe
# so we can report MINERU_VERSION even if the dep failed to install.
try:
    from mineru.version import __version__ as MINERU_VERSION
    from mineru.parser import MinerUParser  # noqa: F401  (smoke import)
    MINERU_AVAILABLE = True
except Exception as e:  # pragma: no cover — handler returns the error to caller
    MINERU_VERSION = f"import-failed: {e}"
    MINERU_AVAILABLE = False


# What `ParseResult.save()` names the files it writes, and what they are called
# here. The harness manifest matches `{basename}`-prefixed names, so a caller
# who sets `basename` finds it on every artifact, as before.
_SAVED_NAMES = {
    "markdown.md": "{basename}.md",
    "middle_json.json": "{basename}_middle.json",
    "structured_content.json": "{basename}_structured_content.json",
}


class _OutputWriter:
    """Receives `ParseResult.save()` output and lays it out under our names.

    `save()` is what materializes images: it moves them out of the in-memory
    document into files and points every reference at them, so the Markdown,
    the JSON and the content lists rendered from its copy all link to files
    that exist. It talks to a writer through `write`/`write_string` only.
    """

    def __init__(self, out_dir: Path, basename: str) -> None:
        self._out_dir = out_dir.resolve()
        self._names = {k: v.format(basename=basename) for k, v in _SAVED_NAMES.items()}
        self.middle_json = ""

    def write(self, path: str, data: bytes) -> None:
        target = (self._out_dir / self._names.get(path, path)).resolve()
        # Asset names come from MinerU, not from the caller, but a name that
        # left the output directory would ship whatever it points at.
        if self._out_dir not in target.parents:
            raise RuntimeError(f"MinerU asset path escapes the output directory: {path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def write_string(self, path: str, data: str) -> None:
        if path == "middle_json.json":
            self.middle_json = data
        self.write(path, data.encode("utf-8"))


def _render(target: str, in_memory: Any, saved: Any) -> tuple[str, str | bytes]:
    """One of MinerU's render targets: (file suffix, content).

    The in-memory document still carries its images, so HTML comes out
    self-contained and DOCX/EPUB/PDF embed them; LaTeX cannot embed, so it is
    rendered from the saved copy and references the `images/` files beside it.
    PDF keeps the source's page layout where it has one (MinerU's AUTO).
    """
    from mineru import render as r  # type: ignore[import-not-found]  # noqa: PLC0415

    if target == "html":
        return ".html", r.render_html(in_memory)
    if target == "latex":
        return ".tex", r.render_latex(saved)
    if target == "docx":
        return ".docx", r.render_docx(in_memory)
    if target == "epub":
        return ".epub", r.render_epub(in_memory)
    if target == "pdf":
        return ".pdf", r.render_pdf(in_memory, layout=r.PdfLayout.AUTO)
    raise ValueError(f"unknown render target {target!r}")


def _vlm_config(server_url: str | None) -> Any:
    """The process's VLM settings with a per-job remote endpoint swapped in.

    None keeps MinerU's own default (its configured local engine). Built through
    the constructor rather than `model_copy` so MinerU's URL normalization runs.
    """
    if not server_url:
        return None
    from mineru.config import VlmConfig, get_config  # type: ignore[import-not-found]  # noqa: PLC0415

    return VlmConfig(**{**get_config().model.vlm.model_dump(), "server_url": server_url})


async def run_mineru(
    file_bytes: bytes,
    basename: str,
    work_dir: Path,
    *,
    suffix: str,
    tier: str,
    ocr_mode: str,
    page_range: str,
    server_url: str | None = None,
    renders: Iterable[str] = (),
) -> Path:
    """Parse one document and write its artifacts; returns the output directory.

    The source is written under its own directory, beside rather than inside
    the output one, because the archive transports ship everything in the
    output directory. `renders` names the extra targets to write (see
    `worker.harness.RENDER_FORMATS`); a render that fails fails the job, as
    in MinerU's own API, rather than shipping without what was asked for.
    """
    if not MINERU_AVAILABLE:
        raise RuntimeError(f"mineru is not importable: {MINERU_VERSION}")
    from mineru.parser import MinerUParser, ParseResult  # type: ignore[import-not-found]  # noqa: PLC0415
    from mineru.render import render_content_list, render_content_list_v2  # type: ignore[import-not-found]  # noqa: PLC0415

    src_dir = work_dir / "src"
    out_dir = work_dir / "out"
    src_dir.mkdir()
    out_dir.mkdir()
    source = src_dir / f"{basename}.{suffix}"
    source.write_bytes(file_bytes)

    parser = MinerUParser(tier=tier, parse_mode=ocr_mode, vlm_config=_vlm_config(server_url))
    result = await parser.parse_async(source, page_range=page_range)

    writer = _OutputWriter(out_dir, basename)
    result.save(writer)
    # The content lists come from the saved copy, whose image references are
    # the files `save()` just wrote, rather than inline base64.
    saved = ParseResult.from_json(writer.middle_json).middle_json
    for name, content in (
        (f"{basename}_content_list.json", render_content_list(saved)),
        (f"{basename}_content_list_v2.json", render_content_list_v2(saved)),
    ):
        (out_dir / name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    for target in renders:
        ext, content = _render(target, result.middle_json, saved)
        path = out_dir / f"{basename}{ext}"
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return out_dir
