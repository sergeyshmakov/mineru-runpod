"""Repository configuration that is easy to get subtly wrong.

Config is not covered by any other test here, and its failures are quiet: nothing
breaks, a job still runs, and the only symptom is something that should have
happened not happening. A security update that is never opened looks exactly like
a repository with no vulnerabilities.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _dependabot() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )


def test_npm_security_updates_reach_lockfile_only_vulnerabilities() -> None:
    """`allow: dependency-type: direct` narrows security updates as well as
    version ones — `allow` carries the security shield in GitHub's options
    reference — so it excluded any CVE reachable only through package-lock.json.
    In an npm tree that is most of them.

    Removing it loses nothing: the documented default for version updates is
    already "all dependencies explicitly defined in a manifest", which is what the
    restriction specified. The npm-security-updates group in the same file only
    means something once transitive vulnerabilities can reach it.
    """
    npm = [u for u in _dependabot()["updates"] if u["package-ecosystem"] == "npm"]
    assert npm, "the npm ecosystem must be configured"
    for entry in npm:
        allowed = entry.get("allow") or []
        assert not any(rule.get("dependency-type") == "direct" for rule in allowed), (
            "this excludes lockfile-only vulnerabilities from security updates"
        )


def test_the_npm_security_group_still_exists() -> None:
    """The thing the above enables. Without it the fix is half a fix."""
    npm = [u for u in _dependabot()["updates"] if u["package-ecosystem"] == "npm"][0]
    groups = npm.get("groups") or {}
    assert any(g.get("applies-to") == "security-updates" for g in groups.values())


def test_github_actions_keeps_its_restriction() -> None:
    """Actions have no transitive dependencies, so there the restriction is inert
    rather than harmful — and removing it would be churn, not a fix.
    """
    actions = [
        u for u in _dependabot()["updates"]
        if u["package-ecosystem"] == "github-actions"
    ]
    assert actions
    assert any(
        rule.get("dependency-type") == "direct"
        for entry in actions
        for rule in (entry.get("allow") or [])
    )
