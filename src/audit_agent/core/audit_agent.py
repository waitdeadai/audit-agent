"""AuditAgent — main orchestrator class for the audit-agent package."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .audit_config import AuditConfig
from .audit_result import AuditResult
from .audit_runner import run_audit

logger = logging.getLogger("audit_agent")


class AuditAgent:
    """Main orchestrator for the audit-agent.

    Example:
        agent = AuditAgent(config=AuditConfig(repo_root=Path("/path/to/repo")))
        result = await agent.run()
        print(result.summary())
    """

    def __init__(self, config: AuditConfig | None = None) -> None:
        self.config = config or AuditConfig()
        self.result: AuditResult | None = None

    async def run(self) -> AuditResult:
        """Run the full audit protocol.

        Returns:
            AuditResult with findings, blockers, and markdown content.
        """
        self.result = await run_audit(self.config)
        return self.result

    def is_stale(self) -> bool:
        """Check if an existing AUDIT.md is stale.

        An audit is considered stale when:
        - AUDIT.md does not exist, or
        - The repo has more than `stale_after_commits` new commits since audit.

        Returns:
            True if the existing AUDIT.md should be refreshed.
        """
        output_path = self.config.output_path
        if not output_path.exists():
            return True

        try:
            audit_time = datetime.fromtimestamp(
                output_path.stat().st_mtime,
                tz=timezone.utc,
            )
        except OSError:
            return True

        # Count commits since audit file was last modified
        try:
            commit_count = _count_commits_since(
                self.config.repo_root,
                since_timestamp=audit_time,
            )
            is_stale = commit_count >= self.config.stale_after_commits
            if is_stale:
                logger.info(
                    "AUDIT.md is stale: %d commits since %s (threshold=%d)",
                    commit_count,
                    audit_time.date(),
                    self.config.stale_after_commits,
                )
            return is_stale
        except Exception as e:
            logger.warning("Could not count commits, treating as stale: %s", e)
            return True

    def load_existing(self) -> AuditResult | None:
        """Load and parse an existing AUDIT.md if present.

        Returns:
            AuditResult parsed from the existing AUDIT.md, or None if not found.
        """
        output_path = self.config.output_path
        if not output_path.exists():
            return None

        try:
            content = output_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Could not read existing AUDIT.md: %s", e)
            return None

        return _parse_existing_audit(content, output_path, self.config.repo_root)

    async def run_if_stale(self) -> AuditResult | None:
        """Run audit only if the existing AUDIT.md is stale.

        Returns:
            New AuditResult if stale and re-audited, None if current.
        """
        if not self.is_stale():
            logger.info("AUDIT.md is current, skipping re-run")
            return None
        return await self.run()


# ── Commit counting ──────────────────────────────────────────────────────────

def _count_commits_since(repo_root: Path, since_timestamp: datetime) -> int:
    """Count commits in repo_root since a given timestamp.

    Uses `git log` to count commits after the given time.
    Returns 0 on any error (git not available, not a git repo, etc.).
    """
    try:
        # Use git log with timestamp filter
        result = subprocess.run(
            [
                "git", "-C", str(repo_root),
                "log", "--after", since_timestamp.isoformat(),
                "--oneline", "--count",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return int(result.stdout.strip() or "0")
    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        logger.debug("git log failed: %s", e)
    return 0


# ── Existing audit parsing ───────────────────────────────────────────────────

def _parse_existing_audit(
    content: str,
    output_path: Path,
    repo_root: Path,
) -> AuditResult:
    """Parse an existing AUDIT.md into an AuditResult."""
    import re

    # Extract JSON block
    json_block: dict = {}
    json_match = re.search(
        r"```json\s*\n({.*?})\n```",
        content,
        re.DOTALL,
    )
    if json_match:
        try:
            json_block = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    agent_block = json_block.get("audit_agent", {})

    # Extract repo name from header line
    repo = repo_root.name
    header_match = re.search(r"\*\*Repo:\*\*\s+([^·\n]+)", content)
    if header_match:
        repo = header_match.group(1).strip()

    # Extract timestamp
    timestamp_str = agent_block.get("timestamp", "")
    if not timestamp_str:
        ts_match = re.search(
            r"\*\*Generated:\*\*\s+([\dT:\-\.Z+]+)",
            content,
        )
        if ts_match:
            timestamp_str = ts_match.group(1).strip()

    # Extract blockers and high_risk from markdown
    blockers: list[str] = list(agent_block.get("blockers", []))
    high_risk: list[str] = list(agent_block.get("high_risk_modules", []))
    start_pts: list[str] = list(agent_block.get("recommended_start_points", []))
    effort = agent_block.get("effort_level", "thorough")
    taste_fails: list[str] = list(agent_block.get("taste_pre_flight_failures", []))
    ready = bool(agent_block.get("ready_to_plan", True))

    return AuditResult(
        version=agent_block.get("version", "1.0"),
        timestamp=timestamp_str,
        repo=repo,
        repo_root=repo_root,
        output_path=output_path,
        blockers=blockers,
        high_risk_modules=high_risk,
        recommended_start_points=start_pts,
        effort_level=effort,
        taste_pre_flight_failures=taste_fails,
        ready_to_plan=ready,
        markdown_content=content,
    )