"""Every place that names the engine names the one requirements.txt pins.

Engine upgrades in this repo have repeatedly left the old version, model or
backend names behind in the README, the docs and the Hub listing — each time
found by a reader rather than a test. The pin is the source of truth; this
derives the series from it and checks every surface that states it, and checks
that the 3.x engine's vocabulary survives only where a page is about history.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_PIN = re.compile(r"^(mineru\[[^\]]*\]>=(\d+)\.(\d+)\.\d+,<\d+\.\d+\.0)$", re.MULTILINE)


def _pin() -> tuple[str, str]:
    match = _PIN.search((ROOT / "requirements.txt").read_text(encoding="utf-8"))
    assert match, "requirements.txt has no minor-locked mineru pin"
    return match.group(1), f"{match.group(2)}.{match.group(3)}"


PIN, SERIES = _pin()


@pytest.mark.parametrize(
    "path",
    ["README.md", "AGENTS.md", "docs/content/docs/reference/versioning.mdx"],
)
def test_the_pin_is_quoted_exactly(path):
    assert PIN in (ROOT / path).read_text(encoding="utf-8"), f"{path} does not quote {PIN}"


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/content/docs/getting-started/overview.mdx",
        "docs/lib/site.ts",
        "docs/app/(home)/page.tsx",
        "docs/public/og-default.svg",
        ".runpod/hub.json",
    ],
)
def test_the_series_is_named(path):
    # "MinerU 4.1", "[MinerU](https://...) 4.1.x" and "MinerU `4.1.x`" all count.
    named = re.compile(rf"MinerU(?:\]\([^)]*\))?\s+`?{re.escape(SERIES)}\b")
    assert named.search((ROOT / path).read_text(encoding="utf-8")), (
        f"{path} does not name MinerU {SERIES}"
    )


def test_documented_mineru_version_examples_are_the_pinned_series():
    stale = []
    for path in (ROOT / "docs" / "content" / "docs").rglob("*.mdx"):
        for value in re.findall(r'"mineru_version":\s*"([^"]+)"', path.read_text(encoding="utf-8")):
            if not value.startswith(SERIES):
                stale.append(f"{path.relative_to(ROOT)}: {value}")
    assert not stale, stale


# The 3.x engine's entry point, backends and model bundle, and its extras.
_STALE = re.compile(
    r"aio_do_parse|vlm-auto-engine|hybrid-auto-engine|vlm-http-client|"
    r"hybrid-http-client|PDF-Extract-Kit|mineru\[core"
)

# Where the old names belong: history (changelog, dated posts, backlog), the
# migration pages, and the tests that assert the old fields are refused.
_HISTORY = (
    "CHANGELOG.md",
    "backlog/",
    "docs/content/blog/",
    "tests/",
    "docs/content/docs/getting-started/upgrade-to-2.mdx",
    "docs/content/docs/reference/versioning.mdx",
    "docs/content/docs/guides/choosing-gpu.mdx",
    "docs/content/docs/guides/troubleshooting.mdx",
)


def test_the_3x_engine_vocabulary_survives_only_in_history():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    leftovers = []
    for rel in tracked:
        if rel.startswith(_HISTORY) or rel.startswith(".wolf/"):
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if _STALE.search(line):
                leftovers.append(f"{rel}:{number}: {line.strip()[:100]}")
    assert not leftovers, "\n".join(leftovers)
