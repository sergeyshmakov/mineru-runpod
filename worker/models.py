"""Where MinerU keeps its weights, as MinerU's own registry says.

The harness looks for weights in the Hugging Face hub cache (`models--*`).
MinerU 4 keeps them as plain directories under its own model root instead
(`model.base_dir`, `$MINERU_HOME/models` by default), so the two questions the
harness used to answer are answered here: which VLM snapshot a response ran
against (`debug.model_dir`), and, for `probe: true`, whether every model the
VLM tiers need is in place.
"""

from __future__ import annotations

import functools
from typing import Any

from runpod_doc_worker.obs import debug as _debug

from worker import parse as _parse


def _repos() -> list[tuple[str, Any]]:
    """The two repos the standard and advanced tiers load, for the configured backends."""
    from mineru.model.registry import small_model_repo, vlm_model_repo  # type: ignore[import-not-found]  # noqa: PLC0415

    return [("small_models", small_model_repo()), ("vlm", vlm_model_repo())]


@functools.lru_cache(maxsize=1)
def vlm_model_dir() -> str | None:
    """The VLM snapshot directory when it is complete, else None.

    Cached: weights do not appear or move under a running worker, and this is
    reported on every response.
    """
    if not _parse.MINERU_AVAILABLE:
        return None
    try:
        from mineru.model.download import verify_model_repo  # type: ignore[import-not-found]  # noqa: PLC0415

        result = verify_model_repo(dict(_repos())["vlm"])
    except Exception:  # noqa: BLE001 - a diagnostic must not fail the job it describes
        return None
    return str(result.root) if result.ready else None


def probe_models() -> dict[str, Any]:
    """Readiness of each model repo, the way MinerU checks it before loading."""
    if not _parse.MINERU_AVAILABLE:
        return {"mineru_available": False}
    try:
        from mineru.config import get_config  # type: ignore[import-not-found]  # noqa: PLC0415
        from mineru.model.download import verify_model_repo  # type: ignore[import-not-found]  # noqa: PLC0415

        report: dict[str, Any] = {"base_dir": str(get_config().model.base_dir)}
        for label, repo in _repos():
            result = verify_model_repo(repo)
            report[label] = {
                "repo": repo.name,
                "ready": result.ready,
                "root": str(result.root),
                "missing": list(result.missing_paths)[:20],
            }
        return report
    except Exception as exc:  # noqa: BLE001 - the probe reports what it cannot read
        return {"error": f"{type(exc).__name__}: {exc}"}


def probe_payload() -> dict[str, Any]:
    """The `probe: true` body: the harness's filesystem dump plus MinerU's models."""
    return {**_debug.probe_filesystem(), "mineru_models": probe_models()}
