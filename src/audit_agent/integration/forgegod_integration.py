"""Integration: ForgeGod loop hook and skill loader."""

from __future__ import annotations

import subprocess
from enum import Enum
from pathlib import Path


class AuditStatus(Enum):
    CURRENT = "current"
    STALE = "stale"
    MISSING = "missing"


async def check_audit_status(
    repo_root: Path,
    stale_after_commits: int = 20,
) -> AuditStatus:
    """Check if a current AUDIT.md exists in the repo."""
    audit_path = repo_root / ".forgegod" / "AUDIT.md"
    if not audit_path.exists():
        return AuditStatus.MISSING

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return AuditStatus.STALE

        total_commits = int(result.stdout.strip())
        # Count commits since AUDIT.md was last modified (result unused, just side-effect)
        subprocess.run(
            ["git", "-C", str(repo_root), "log", "--oneline", "--since", "9999-01-01",
             "--until", "2099-01-01", "--", str(audit_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Simpler heuristic: check file modification against HEAD commit date
        result2 = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%ct", "--", str(audit_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result2.returncode == 0:
            audit_commits_ago = total_commits - int(result2.stdout.strip())
            if audit_commits_ago > stale_after_commits:
                return AuditStatus.STALE
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass

    return AuditStatus.CURRENT


async def forgegod_loop_hook(
    repo_root: Path,
    stale_after_commits: int = 20,
) -> tuple[bool, str]:
    """Called by Ralph Loop before spawning stories.

    Returns (should_proceed, reason).
    If AUDIT.md is missing or stale, loop should not proceed.
    """
    status = await check_audit_status(repo_root, stale_after_commits)
    if status == AuditStatus.MISSING:
        return False, "No AUDIT.md found. Run audit-agent first."
    if status == AuditStatus.STALE:
        return False, "AUDIT.md is stale (>20 commits). Run audit-agent first."
    return True, "AUDIT.md is current. Proceeding."


def skill_prompt(skill_path: Path | None = None) -> str:
    """Load the audit-agent system prompt from the skill file."""
    if skill_path is None:
        # Default: look relative to this file
        skill_path = Path(__file__).parent.parent / "PROMPT.md"
    if not skill_path.exists():
        return f"Error: skill file not found at {skill_path}"
    return skill_path.read_text(encoding="utf-8", errors="replace")
