"""MinerU lazy import + the single async parse entry point."""

from __future__ import annotations

from pathlib import Path

# MinerU's heavy imports run lazily inside _run_mineru so the handler module
# itself imports on a CPU-only test machine (CI exercises input validation
# and packaging without needing a GPU). Module-level only does a soft probe
# so we can report MINERU_VERSION even if the dep failed to install.
try:
    import mineru as _mineru
    from mineru.cli.common import aio_do_parse  # noqa: F401  (smoke import)
    MINERU_VERSION = getattr(_mineru, "__version__", "unknown")
    MINERU_AVAILABLE = True
except Exception as e:  # pragma: no cover — handler returns the error to caller
    _mineru = None  # type: ignore[assignment]
    aio_do_parse = None  # type: ignore[assignment]
    MINERU_VERSION = f"import-failed: {e}"
    MINERU_AVAILABLE = False


async def run_mineru(
    file_bytes: bytes,
    basename: str,
    work_dir: Path,
    *,
    input_format: str,
    start_page: int,
    end_page: int | None,
    lang: str,
    backend: str,
    server_url: str | None,
    formula_enable: bool,
    table_enable: bool,
    effort: str | None = None,
) -> Path:
    if not MINERU_AVAILABLE:
        raise RuntimeError(f"mineru is not importable: {MINERU_VERSION}")
    # Late re-import keeps the static import wrapped; the binding is the real one here.
    from mineru.cli.common import aio_do_parse as _aio_do_parse  # type: ignore[import-not-found]

    # MinerU's `aio_do_parse` accepts PDFs, DOCX, PPTX, XLSX bytes directly via
    # `pdf_bytes_list` (the name is legacy — it's polymorphic). Images need
    # pre-conversion to single-page PDF first.
    if input_format == "image":
        from mineru.utils.pdf_image_tools import images_bytes_to_pdf_bytes  # type: ignore[import-not-found]  # noqa: PLC0415
        try:
            file_bytes = images_bytes_to_pdf_bytes(file_bytes)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"image preprocessing failed: {type(e).__name__}: {e}") from e

    # `effort` (hybrid backends only) is forwarded only when the caller set it,
    # so MinerU's own default governs otherwise. Passing it unconditionally
    # would override that default and would be meaningless on non-hybrid
    # backends — the schema already rejects that combination upstream.
    extra: dict[str, str] = {}
    if effort is not None:
        extra["effort"] = effort

    # MinerU 3.1.x adds f_dump_model_output / f_dump_orig_pdf with default True
    # — both write extra artefacts (raw model output JSON, copy of input PDF)
    # that bloat the response tarball without serving callers we know about.
    # Turn them off; callers who want them can fork the handler.
    await _aio_do_parse(
        output_dir=str(work_dir),
        pdf_file_names=[basename],
        pdf_bytes_list=[file_bytes],
        p_lang_list=[lang],
        backend=backend,
        server_url=server_url,
        parse_method="auto",
        formula_enable=formula_enable,
        table_enable=table_enable,
        f_dump_md=True,
        f_dump_content_list=True,
        f_dump_middle_json=True,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        start_page_id=start_page,
        end_page_id=end_page,
        **extra,
    )

    # Only one basename is passed in, so at most one matching .md exists.
    matches = list(work_dir.rglob(f"{basename}.md"))
    if not matches:
        raise RuntimeError(
            f"MinerU did not produce {basename}.md anywhere under {work_dir}"
        )
    return matches[0].parent
