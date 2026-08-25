"""Every Python file stays under a line cap, checked rather than hoped for.

The cap exists because this repository grew several files past the point where
anyone reads one whole -- a 707-line handler, a 696-line telemetry module carrying
seventeen pieces of shared state, and three test files over 500. Splitting them was
straightforward once someone looked; the problem was that nothing prompted anyone
to look. A failing test does.

The number is a convention, not a discovery. What matters is that crossing it is a
decision someone makes deliberately, by editing this file, rather than something
that happens over thirty commits.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

MAX_LINES = 500

REPO = Path(__file__).resolve().parent.parent

# Directories that are not ours to keep under the cap.
SKIP = {".venv", "node_modules", "__pycache__", ".git", ".wolf", "out", "dist"}


def _python_files() -> list[Path]:
    """Tracked Python files, from git when it is available.

    Falls back to walking the tree, because the test has to work from an unpacked
    source archive where there is no git metadata -- and a check that silently
    passes when it cannot run is worse than no check.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        # Pruned in place. Filtering after `rglob` means descending into every
        # skipped tree first, and walking `node_modules` to throw it away took
        # this from under a second to over two minutes.
        found: list[Path] = []
        for directory, subdirectories, names in os.walk(REPO):
            subdirectories[:] = [
                name for name in subdirectories if name not in SKIP
            ]
            found.extend(
                Path(directory) / name for name in names if name.endswith(".py")
            )
        return found
    # Symlinks are skipped: `.runpod/handler.py` is a link to `../handler.py`,
    # and counting it would report the same file twice under two names.
    return [
        REPO / name
        for name in listed
        if (REPO / name).is_file() and not (REPO / name).is_symlink()
    ]


def test_the_file_list_is_not_empty() -> None:
    """The guard on the guard. Both ways of finding files can return nothing --
    a `git ls-files` in the wrong directory, a glob that matches no path -- and an
    empty list would make the cap below pass without checking anything."""
    assert len(_python_files()) > 20, "the file discovery found suspiciously little"


def test_no_python_file_exceeds_the_line_cap() -> None:
    oversized = {
        str(path.relative_to(REPO)).replace("\\", "/"): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in _python_files()
    }
    oversized = {
        name: count for name, count in oversized.items() if count > MAX_LINES
    }
    assert not oversized, (
        f"over the {MAX_LINES}-line cap: "
        + ", ".join(f"{name} ({count})" for name, count in sorted(oversized.items()))
        + ". Split it along whatever subjects it turns out to contain, or raise "
        "MAX_LINES deliberately if the file genuinely is one thing."
    )


@pytest.mark.parametrize("directory", ["worker", "tests"])
def test_the_cap_is_measured_where_the_code_is(directory: str) -> None:
    """Sanity: the discovery actually reaches the two trees that matter. A path
    change that quietly excluded `worker/` would leave the cap passing forever."""
    found = {str(path.relative_to(REPO)).replace("\\", "/") for path in _python_files()}
    assert any(name.startswith(f"{directory}/") for name in found), (
        f"no files found under {directory}/"
    )
