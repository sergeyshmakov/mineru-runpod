"""Debug / observability helpers.

Almost everything here is best-effort — operator tooling that should never
crash the request path. The probe payload is the big one: when a job has
``probe: true``, the handler returns a filesystem dump of /runpod-volume so
we can debug RunPod Cached Models setups without shelling into a worker.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any


def probe_enabled() -> bool:
    """Whether this worker answers ``probe: true`` jobs.

    On by default — the probe payload is how the troubleshooting guide has
    callers diagnose a model-cache problem without shelling into a worker.
    Operators running an endpoint whose callers have no business seeing its
    disk layout set MINERU_DISABLE_PROBE=1 and get the normal error envelope
    instead.
    """
    return os.environ.get("MINERU_DISABLE_PROBE", "").strip().lower() not in (
        "1", "true", "yes", "on",
    )


def collect_gpu_info() -> dict[str, Any]:
    """Best-effort GPU inventory for the response's `debug` block.

    Helps callers distinguish a 4090 from an A5000 from a Blackwell MIG slice
    without having to read worker logs. compute_capability >= 12.0 is what
    triggers the xformers flash-attn crash on the VLM backend.
    """
    try:
        import torch  # noqa: PLC0415
        if not torch.cuda.is_available():
            return {"available": False}
        props = torch.cuda.get_device_properties(0)
        return {
            "available": True,
            "name": props.name,
            "compute_capability": f"{props.major}.{props.minor}",
            "total_memory_gb": round(props.total_memory / 1024**3, 2),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@functools.lru_cache(maxsize=1)
def find_model_dir() -> str | None:
    """Locate the MinerU model snapshot under HF_HOME so we can prove which
    weights actually loaded (Pro-2605 vs an older or unexpected variant).

    Cached because the model dir doesn't change after worker boot and the
    rglob over ~/.cache/huggingface/hub is non-trivial on cold cache.
    """
    hf_home = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    hub = Path(hf_home) / "hub"
    if not hub.is_dir():
        return None
    matches = list(hub.glob("models--opendatalab--MinerU*"))
    if not matches:
        return None
    # If multiple MinerU model dirs are cached, report the most recently used
    # one — that's the one the library most likely resolved to.
    best = max(matches, key=lambda p: p.stat().st_mtime)
    snapshots = best / "snapshots"
    if snapshots.is_dir():
        snap_dirs = [d for d in snapshots.iterdir() if d.is_dir()]
        if snap_dirs:
            return str(max(snap_dirs, key=lambda p: p.stat().st_mtime))
    return str(best)


def _resolve_snapshot_path(hub_root: Path, model_id: str) -> dict[str, Any]:
    """Emulate the resolve_snapshot_path() helper from RunPod's tutorial.

    Returns a dict that says what the tutorial's algorithm would have found
    for `model_id` at `hub_root` — including whether refs/main is stale
    (points at a hash that doesn't exist in snapshots/).
    """
    out: dict[str, Any] = {
        "model_id": model_id,
        "expected_root": "",
        "model_root_exists": False,
        "refs_main_path": "",
        "refs_main_content": None,
        "snapshots_dir_exists": False,
        "snapshot_subdirs": [],
        "resolved_path": None,
        "resolution_method": None,
        "issue": None,
    }
    if "/" not in model_id:
        out["issue"] = f"model_id {model_id!r} not in org/name format"
        return out
    org, name = model_id.split("/", 1)
    model_root = hub_root / f"models--{org}--{name}"
    out["expected_root"] = str(model_root)
    if not model_root.is_dir():
        out["issue"] = "model_root not present (RunPod didn't populate, or wrong casing)"
        return out
    out["model_root_exists"] = True

    refs_main = model_root / "refs" / "main"
    out["refs_main_path"] = str(refs_main)
    if refs_main.is_file():
        try:
            out["refs_main_content"] = refs_main.read_text(encoding="utf-8").strip()
        except OSError as e:
            out["refs_main_content"] = f"<read error: {e}>"

    snapshots_dir = model_root / "snapshots"
    out["snapshots_dir_exists"] = snapshots_dir.is_dir()
    if out["snapshots_dir_exists"]:
        try:
            out["snapshot_subdirs"] = sorted(
                d.name for d in snapshots_dir.iterdir() if d.is_dir()
            )
        except OSError as e:
            out["issue"] = f"snapshots/ iter error: {e}"
            return out

    # Resolution attempt 1: refs/main → snapshots/<hash>/
    if out["refs_main_content"] and isinstance(out["refs_main_content"], str):
        candidate = snapshots_dir / out["refs_main_content"]
        if candidate.is_dir():
            out["resolved_path"] = str(candidate)
            out["resolution_method"] = "refs/main"
            return out
        out["issue"] = (
            f"refs/main points at {out['refs_main_content']!r} but "
            f"snapshots/{out['refs_main_content']}/ does not exist (stale refs/main)"
        )

    # Resolution attempt 2: first available snapshot subdir
    if out["snapshot_subdirs"]:
        first = snapshots_dir / out["snapshot_subdirs"][0]
        out["resolved_path"] = str(first)
        out["resolution_method"] = "first snapshot subdir (fallback)"
        return out

    if out["issue"] is None:
        out["issue"] = "no snapshots/ subdir or no entries inside it"
    return out


def probe_filesystem() -> dict[str, Any]:
    """Inspect /runpod-volume layout for Cached Models debugging.

    Returns whatever's actually on disk where MinerU's HF lookup expects it.
    Triggered by `probe: true` in the input. Used to diagnose
    LocalEntryNotFoundError on workers that have Cached Models configured but
    aren't finding the model.

    Safe to call without MinerU installed. Read-only. No network. No PDF.
    """
    def _list(p: Path, max_entries: int = 50) -> list[str] | str:
        try:
            entries = sorted(p.iterdir())
        except (PermissionError, FileNotFoundError) as e:
            return f"<error: {type(e).__name__}: {e}>"
        result: list[str] = []
        for entry in entries[:max_entries]:
            kind = "d" if entry.is_dir() else "f"
            try:
                size = entry.stat().st_size if entry.is_file() else "-"
            except OSError:
                size = "?"
            result.append(f"{kind} {entry.name} {size}")
        if len(entries) > max_entries:
            result.append(f"... ({len(entries) - max_entries} more entries elided)")
        return result

    hf_home = os.environ.get("HF_HOME", "")
    hub_path = Path(hf_home) / "hub" if hf_home else None

    out: dict[str, Any] = {
        "env": {
            "HF_HOME": hf_home,
            "HF_HUB_CACHE": os.environ.get("HF_HUB_CACHE", ""),
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", ""),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE", ""),
            "TRANSFORMERS_CACHE": os.environ.get("TRANSFORMERS_CACHE", ""),
            "MINERU_MODEL_SOURCE": os.environ.get("MINERU_MODEL_SOURCE", ""),
            "MINERU_VL_MODEL_NAME": os.environ.get("MINERU_VL_MODEL_NAME", ""),
        },
        "paths": {},
        "models_found": [],
        "resolution_attempts": [],
    }

    # Try the tutorial's snapshot resolver for each model MinerU would care
    # about. Reports whether refs/main is stale, whether canonical casing is
    # present, and what (if anything) MinerU's library would find.
    if hub_path and hub_path.is_dir():
        for model_id in (
            "opendatalab/MinerU2.5-Pro-2605-1.2B",  # VLM backend
            "opendatalab/PDF-Extract-Kit-1.0",      # pipeline backend
        ):
            out["resolution_attempts"].append(
                _resolve_snapshot_path(hub_path, model_id)
            )

    for label, path_str in (
        ("/runpod-volume", "/runpod-volume"),
        ("/runpod-volume/huggingface-cache", "/runpod-volume/huggingface-cache"),
        ("/runpod-volume/huggingface-cache/hub", "/runpod-volume/huggingface-cache/hub"),
        ("HF_HOME", hf_home),
        ("HF_HOME/hub", str(hub_path) if hub_path else ""),
    ):
        if not path_str:
            out["paths"][label] = "<empty path>"
            continue
        p = Path(path_str)
        if not p.exists():
            out["paths"][label] = "<not present>"
            continue
        if not p.is_dir():
            out["paths"][label] = "<not a directory>"
            continue
        out["paths"][label] = _list(p)

    # Hunt for any `models--*` directories regardless of casing, anywhere
    # under /runpod-volume up to depth 4. This catches the case where
    # RunPod populated under a different path than HF_HOME/hub.
    for search_root in ("/runpod-volume",):
        root = Path(search_root)
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("models--*"):
                try:
                    rel_depth = len(path.relative_to(root).parts)
                except ValueError:
                    continue
                if rel_depth > 4:
                    continue
                snapshots = path / "snapshots"
                snap_names: list[str] = []
                if snapshots.is_dir():
                    try:
                        snap_names = [d.name for d in snapshots.iterdir() if d.is_dir()][:5]
                    except OSError:
                        pass
                out["models_found"].append({
                    "path": str(path),
                    "depth": rel_depth,
                    "snapshots": snap_names,
                })
                if len(out["models_found"]) >= 20:
                    break
        except (PermissionError, OSError) as e:
            out["models_found_error"] = f"{type(e).__name__}: {e}"

    return out
