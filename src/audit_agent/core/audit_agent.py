"""AuditAgent — main orchestrator class for the audit-agent package."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .audit_config import AuditConfig, PlanConfig
from .audit_result import AuditResult, DeltaAuditResult, EvalRunResult, PlanResult
from .delta_audit import run_delta_audit
from .evals import run_eval_harness
from .audit_runner import run_audit
from .plan_runner import _extract_json_block, _parse_stories_from_json, run_plan
from .specialist_audits import (
    run_architecture_audit,
    run_plan_risk_audit,
    run_security_audit,
)

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

    async def run_delta(
        self,
        *,
        task: str = "",
        review_feedback: str = "",
        failure_details: str = "",
        changed_files: list[str] | None = None,
    ) -> DeltaAuditResult | None:
        """Run a targeted delta audit when triggers indicate it is needed."""
        if self.result is None:
            self.result = await self.run()
        if self.result is None:
            raise RuntimeError("No base audit result available for delta audit.")
        return await run_delta_audit(
            self.result,
            self.config,
            task=task,
            review_feedback=review_feedback,
            failure_details=failure_details,
            changed_files=changed_files,
        )

    async def run_security_audit(
        self,
        *,
        changed_files: list[str] | None = None,
        use_semgrep: bool = False,
    ):
        """Run the security specialist surface against the current audit context."""
        audit_result = self._ensure_specialist_audit_result()
        return run_security_audit(
            audit_result,
            self.config,
            changed_files=changed_files,
            use_semgrep=use_semgrep,
        )

    async def run_architecture_audit(
        self,
        *,
        changed_files: list[str] | None = None,
    ):
        """Run the architecture specialist surface against the current audit context."""
        audit_result = self._ensure_specialist_audit_result()
        return run_architecture_audit(
            audit_result,
            self.config,
            changed_files=changed_files,
        )

    async def run_plan_risk_audit(
        self,
        plan_result: PlanResult | None = None,
        *,
        task: str = "",
        plan_path: Path | None = None,
    ):
        """Run the plan-risk specialist surface for an existing or in-memory plan."""
        audit_result = await self._ensure_audit_result()
        loaded_plan = plan_result or self.load_existing_plan(plan_path)
        if loaded_plan is None:
            raise RuntimeError("No PLAN.md available for plan-risk audit.")
        return run_plan_risk_audit(
            audit_result,
            loaded_plan,
            self.config,
            task=task or loaded_plan.task,
        )

    def run_evals(self) -> EvalRunResult:
        """Run the deterministic offline eval harness."""
        return run_eval_harness(self.config)

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

    def load_existing_plan(self, plan_path: Path | None = None) -> PlanResult | None:
        """Load and parse an existing PLAN.md if present."""
        resolved_path = plan_path or (
            self.config.plan.output_path
            if self.config.plan is not None
            else self.config.repo_root / ".forgegod" / "PLAN.md"
        )
        if not resolved_path.is_absolute():
            resolved_path = self.config.repo_root / resolved_path
        if not resolved_path.exists():
            return None

        try:
            content = resolved_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read existing PLAN.md: %s", exc)
            return None

        block = _extract_json_block(content)
        plan_block = block.get("plan_agent", {})
        return PlanResult(
            version=plan_block.get("version", "1.0"),
            timestamp=plan_block.get("timestamp", ""),
            repo=plan_block.get("repo", self.config.repo_root.name),
            task=plan_block.get("task", ""),
            stories=_parse_stories_from_json(block),
            guardrails=list(plan_block.get("guardrails", [])),
            effort_level=plan_block.get("effort_level", "thorough"),
            ready_to_execute=bool(plan_block.get("ready_to_execute", True)),
            blockers=list(plan_block.get("blockers", [])),
            high_risk_modules=list(plan_block.get("high_risk_modules", [])),
            recommended_start=plan_block.get("recommended_start", ""),
            markdown_content=content,
        )

    async def run_if_stale(self) -> AuditResult | None:
        """Run audit only if the existing AUDIT.md is stale.

        Returns:
            New AuditResult if stale and re-audited, None if current.
        """
        if not self.is_stale():
            logger.info("AUDIT.md is current, skipping re-run")
            return None
        return await self.run()

    async def run_plan(
        self,
        task: str,
        *,
        review_feedback: str = "",
        failure_details: str = "",
        changed_files: list[str] | None = None,
        skip_delta_audit: bool = False,
    ) -> PlanResult:
        """Run audit then plan pipeline.

        If AUDIT.md is current, loads it and skips re-audit.
        If AUDIT.md is stale or missing, runs audit first.
        Then generates PLAN.md from the task using audit findings.

        Args:
            task: The natural-language task to decompose into stories.

        Returns:
            PlanResult with stories, guardrails, and readiness.
        """
        # Run audit (or load existing)
        if self.is_stale():
            self.result = await run_audit(self.config)
        elif self.result is None:
            existing = self.load_existing()
            if existing is None:
                self.result = await run_audit(self.config)
            else:
                self.result = existing

        if self.result is None:
            raise RuntimeError("No audit result available and could not run audit.")

        # Run planning
        if self.config.plan is None:
            self.config.plan = PlanConfig(enabled=True, task=task)
        else:
            self.config.plan.task = task
            self.config.plan.enabled = True
        if not self.config.plan.output_path.is_absolute():
            self.config.plan.output_path = (
                self.config.repo_root / self.config.plan.output_path
            )

        delta_result: DeltaAuditResult | None = None
        if not skip_delta_audit:
            delta_result = await run_delta_audit(
                self.result,
                self.config,
                task=task,
                review_feedback=review_feedback,
                failure_details=failure_details,
                changed_files=changed_files,
            )
            if delta_result is not None:
                if delta_result.full_reaudit_required:
                    self.result = await run_audit(self.config)
                else:
                    self.result = _merge_audit_with_delta(self.result, delta_result)

        plan_result = await run_plan(self.result, task, self.config)
        plan_result.delta_audit = delta_result
        specialist_result = run_plan_risk_audit(
            self.result,
            plan_result,
            self.config,
            task=task,
        )
        plan_result.specialist_audits.append(specialist_result)
        plan_result.blockers = _merge_unique(plan_result.blockers, specialist_result.blockers)
        plan_result.guardrails = _merge_unique(plan_result.guardrails, specialist_result.guardrail_updates)
        plan_result.high_risk_modules = _merge_unique(
            plan_result.high_risk_modules,
            specialist_result.relevant_modules,
        )
        plan_result.ready_to_execute = plan_result.ready_to_execute and specialist_result.ready
        plan_result.markdown_content = _append_specialist_section(
            plan_result.markdown_content,
            specialist_result,
        )
        if self.config.plan is not None:
            self.config.plan.output_path.write_text(
                plan_result.markdown_content,
                encoding="utf-8",
            )
        return plan_result

    async def _ensure_audit_result(self) -> AuditResult:
        """Return a current audit result, running or loading it if needed."""
        if self.result is not None:
            return self.result
        if self.is_stale():
            self.result = await run_audit(self.config)
            return self.result
        existing = self.load_existing()
        if existing is not None:
            self.result = existing
            return self.result
        self.result = await run_audit(self.config)
        return self.result

    def _ensure_specialist_audit_result(self) -> AuditResult:
        """Return audit context for deterministic specialist surfaces.

        These specialist commands should remain usable on fresh repos without
        forcing a live model call. When no current AUDIT.md exists, seed a
        minimal audit context from repo metadata and let the deterministic
        specialist surface do the rest.
        """
        if self.result is not None:
            return self.result
        existing = self.load_existing()
        if existing is not None:
            self.result = existing
            return self.result
        self.result = AuditResult(
            repo=self.config.repo_root.name,
            repo_root=self.config.repo_root,
            output_path=self.config.output_path,
            ready_to_plan=True,
        )
        return self.result


def _merge_audit_with_delta(
    audit_result: AuditResult,
    delta_result: DeltaAuditResult,
) -> AuditResult:
    """Merge delta-audit findings into the current audit context for planning."""
    blockers = _merge_unique(audit_result.blockers, delta_result.blocker_updates)
    high_risk_modules = _merge_unique(
        audit_result.high_risk_modules,
        delta_result.relevant_modules,
    )
    taste_failures = _merge_unique(
        audit_result.taste_pre_flight_failures,
        delta_result.guardrail_updates,
    )
    return AuditResult(
        version=audit_result.version,
        timestamp=audit_result.timestamp,
        repo=audit_result.repo,
        repo_root=audit_result.repo_root,
        output_path=audit_result.output_path,
        findings=audit_result.findings,
        blockers=blockers,
        high_risk_modules=high_risk_modules,
        recommended_start_points=audit_result.recommended_start_points,
        effort_level=audit_result.effort_level,
        taste_pre_flight_failures=taste_failures,
        ready_to_plan=audit_result.ready_to_plan and delta_result.ready_to_plan,
        markdown_content=audit_result.markdown_content,
    )


def _merge_unique(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for group in groups:
        for value in group:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)
    return output


def _append_specialist_section(content: str, specialist_result) -> str:
    """Append a specialist audit summary to PLAN.md content."""
    section = (
        f"\n\n---\n\n## {specialist_result.kind.title()} Audit\n\n"
        f"- Ready: {str(specialist_result.ready).lower()}\n"
        f"- Findings: {len(specialist_result.findings)}\n"
        f"- Blockers: {len(specialist_result.blockers)}\n"
    )
    if specialist_result.blockers:
        section += "\n".join(f"- {blocker}\n" for blocker in specialist_result.blockers)
    section += "\n```json\n" + specialist_result.to_json_block() + "\n```\n"
    return content.rstrip() + section


# ── Commit counting ──────────────────────────────────────────────────────────

def _count_commits_since(repo_root: Path, since_timestamp: datetime) -> int:
    """Count commits in repo_root since a given timestamp.

    Uses `git log` to count commits after the given time.
    Returns 0 on any error (git not available, not a git repo, etc.).
    """
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_root),
                "rev-list", "--count", f"--after={since_timestamp.isoformat()}",
                "HEAD",
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
