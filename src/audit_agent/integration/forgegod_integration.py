"""Integration: ForgeGod loop hook and skill loader."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from audit_agent.core.audit_agent import AuditAgent
from audit_agent.core.audit_config import AuditConfig


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

    config = AuditConfig(
        repo_root=repo_root,
        output_path=audit_path,
        stale_after_commits=stale_after_commits,
    )
    agent = AuditAgent(config)
    return AuditStatus.STALE if agent.is_stale() else AuditStatus.CURRENT


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
    candidates = [skill_path]
    if skill_path.name == "PROMPT.md":
        candidates.append(skill_path.with_name("SKILL.md"))
    elif skill_path.name == "SKILL.md":
        candidates.append(skill_path.with_name("PROMPT.md"))

    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return f"Error: skill file not found at {skill_path}"
