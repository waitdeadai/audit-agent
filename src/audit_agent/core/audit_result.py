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