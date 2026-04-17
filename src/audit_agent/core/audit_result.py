"""AuditResult — structured output of an audit run."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class AuditFinding:
    """A single finding discovered during the audit."""

    severity: str  # CRITICAL | WARNING | INFO
    category: str
    file: str | None = None
    line: int | None = None
    description: str = ""


@dataclass
class PlanStory:
    """A single story in the plan — mirrors ForgeGod Story model."""

    id: str
    title: str
    description: str = ""
    priority: int = 1
    depends_on: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    verification_commands: list[str] = field(default_factory=list)
    effort: str = "medium"  # trivial | low | medium | high | exhaustive
    risk: str = "low"  # low | medium | high
    modules_touched: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)  # audit blockers


@dataclass
class DeltaTrigger:
    """A concrete reason why a delta audit was triggered."""

    reason: str
    summary: str
    changed_files: list[str] = field(default_factory=list)
    relevant_modules: list[str] = field(default_factory=list)
    full_reaudit_recommended: bool = False


@dataclass
class DeltaAuditResult:
    """Structured result of a delta audit pass."""

    version: str = "1.0"
    timestamp: str = ""
    repo: str = ""
    task: str = ""
    triggers: list[DeltaTrigger] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    blocker_updates: list[str] = field(default_factory=list)
    relevant_modules: list[str] = field(default_factory=list)
    guardrail_updates: list[str] = field(default_factory=list)
    ready_to_plan: bool = True
    full_reaudit_required: bool = False
    recommended_action: str = "proceed"
    markdown_content: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json_block(self) -> str:
        """Render machine-readable JSON block for ForgeGod parsing."""
        block = {
            "delta_audit": {
                "version": self.version,
                "timestamp": self.timestamp,
                "repo": self.repo,
                "task": self.task,
                "triggers": [
                    {
                        "reason": trigger.reason,
                        "summary": trigger.summary,
                        "changed_files": trigger.changed_files,
                        "relevant_modules": trigger.relevant_modules,
                        "full_reaudit_recommended": trigger.full_reaudit_recommended,
                    }
                    for trigger in self.triggers
                ],
                "changed_files": self.changed_files,
                "blocker_updates": self.blocker_updates,
                "relevant_modules": self.relevant_modules,
                "guardrail_updates": self.guardrail_updates,
                "ready_to_plan": self.ready_to_plan,
                "full_reaudit_required": self.full_reaudit_required,
                "recommended_action": self.recommended_action,
            }
        }
        return json.dumps(block, indent=2)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        status = "READY" if self.ready_to_plan else "BLOCKED"
        return (
            f"[delta-audit] {status} | "
            f"repo={self.repo!r} | "
            f"triggers={len(self.triggers)} | "
            f"changed_files={len(self.changed_files)} | "
            f"action={self.recommended_action}"
        )


@dataclass
class SpecialistAuditResult:
    """Structured result of a specialist audit surface."""

    version: str = "1.0"
    timestamp: str = ""
    kind: str = ""
    repo: str = ""
    task: str = ""
    findings: list[AuditFinding] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    guardrail_updates: list[str] = field(default_factory=list)
    relevant_modules: list[str] = field(default_factory=list)
    ready: bool = True
    metadata: dict[str, object] = field(default_factory=dict)
    markdown_content: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json_block(self) -> str:
        """Render machine-readable JSON block for specialist audit surfaces."""
        block = {
            "specialist_audit": {
                "version": self.version,
                "timestamp": self.timestamp,
                "kind": self.kind,
                "repo": self.repo,
                "task": self.task,
                "findings": [
                    {
                        "severity": finding.severity,
                        "category": finding.category,
                        "file": finding.file,
                        "line": finding.line,
                        "description": finding.description,
                    }
                    for finding in self.findings
                ],
                "blockers": self.blockers,
                "guardrail_updates": self.guardrail_updates,
                "relevant_modules": self.relevant_modules,
                "ready": self.ready,
                "metadata": self.metadata,
            }
        }
        return json.dumps(block, indent=2)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        status = "READY" if self.ready else "BLOCKED"
        return (
            f"[specialist:{self.kind}] {status} | "
            f"repo={self.repo!r} | "
            f"findings={len(self.findings)} | "
            f"blockers={len(self.blockers)}"
        )


@dataclass
class PlanResult:
    """Structured plan output — drives story execution after audit."""

    version: str = "1.0"
    timestamp: str = ""
    repo: str = ""
    task: str = ""
    stories: list[PlanStory] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    effort_level: str = "thorough"
    ready_to_execute: bool = True
    blockers: list[str] = field(default_factory=list)
    high_risk_modules: list[str] = field(default_factory=list)
    recommended_start: str = ""
    delta_audit: DeltaAuditResult | None = None
    specialist_audits: list[SpecialistAuditResult] = field(default_factory=list)
    markdown_content: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json_block(self) -> str:
        """Render machine-readable JSON block for ForgeGod parsing."""
        block = {
            "plan_agent": {
                "version": self.version,
                "timestamp": self.timestamp,
                "repo": self.repo,
                "task": self.task,
                "stories": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "description": s.description,
                        "priority": s.priority,
                        "depends_on": s.depends_on,
                        "acceptance_criteria": s.acceptance_criteria,
                        "verification_commands": s.verification_commands,
                        "effort": s.effort,
                        "risk": s.risk,
                        "modules_touched": s.modules_touched,
                        "blocked_by": s.blocked_by,
                    }
                    for s in self.stories
                ],
                "guardrails": self.guardrails,
                "effort_level": self.effort_level,
                "ready_to_execute": self.ready_to_execute,
                "blockers": self.blockers,
                "high_risk_modules": self.high_risk_modules,
                "recommended_start": self.recommended_start,
                "delta_audit": (
                    {
                        "triggers": len(self.delta_audit.triggers),
                        "recommended_action": self.delta_audit.recommended_action,
                        "full_reaudit_required": self.delta_audit.full_reaudit_required,
                    }
                    if self.delta_audit is not None
                    else None
                ),
                "specialist_audits": [
                    {
                        "kind": specialist.kind,
                        "ready": specialist.ready,
                        "blockers": len(specialist.blockers),
                        "findings": len(specialist.findings),
                    }
                    for specialist in self.specialist_audits
                ],
            }
        }
        return json.dumps(block, indent=2)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        status = "READY" if self.ready_to_execute else "BLOCKED"
        return (
            f"[plan-agent] {status} | "
            f"repo={self.repo!r} | "
            f"stories={len(self.stories)} | "
            f"effort={self.effort_level} | "
            f"guardrails={len(self.guardrails)}"
        )


@dataclass
class EvalCaseResult:
    """Structured result for a single deterministic eval case."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class EvalRunResult:
    """Structured result for the offline eval harness."""

    version: str = "1.0"
    timestamp: str = ""
    suite: str = "audit-agent"
    passed: int = 0
    failed: int = 0
    cases: list[EvalCaseResult] = field(default_factory=list)
    markdown_content: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json_block(self) -> str:
        """Render machine-readable JSON block for eval runs."""
        block = {
            "audit_eval": {
                "version": self.version,
                "timestamp": self.timestamp,
                "suite": self.suite,
                "passed": self.passed,
                "failed": self.failed,
                "cases": [
                    {
                        "name": case.name,
                        "passed": case.passed,
                        "detail": case.detail,
                    }
                    for case in self.cases
                ],
            }
        }
        return json.dumps(block, indent=2)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        status = "GREEN" if self.failed == 0 else "FAIL"
        return (
            f"[audit-evals] {status} | "
            f"suite={self.suite!r} | "
            f"passed={self.passed} | "
            f"failed={self.failed}"
        )


@dataclass
class AuditResult:
    """The complete result of an audit-agent run."""

    version: str = "1.0"
    timestamp: str = ""
    repo: str = ""
    repo_root: Path | None = None
    output_path: Path | None = None
    findings: list[AuditFinding] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    high_risk_modules: list[str] = field(default_factory=list)
    recommended_start_points: list[str] = field(default_factory=list)
    effort_level: str = "thorough"
    taste_pre_flight_failures: list[str] = field(default_factory=list)
    ready_to_plan: bool = True
    markdown_content: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json_block(self) -> str:
        """Render the machine-readable JSON block for ForgeGod parsing."""
        block = {
            "audit_agent": {
                "version": self.version,
                "timestamp": self.timestamp,
                "repo": self.repo,
                "blockers": self.blockers,
                "high_risk_modules": self.high_risk_modules,
                "recommended_start_points": self.recommended_start_points,
                "effort_level": self.effort_level,
                "taste_pre_flight_failures": self.taste_pre_flight_failures,
                "ready_to_plan": self.ready_to_plan,
            }
        }
        return json.dumps(block, indent=2)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        status = "READY" if self.ready_to_plan else "BLOCKED"
        risk_count = len(self.high_risk_modules)
        blocker_count = len(self.blockers)
        return (
            f"[audit-agent] {status} | "
            f"repo={self.repo!r} | "
            f"findings={len(self.findings)} | "
            f"high_risk={risk_count} | "
            f"blockers={blocker_count} | "
            f"effort={self.effort_level}"
        )
