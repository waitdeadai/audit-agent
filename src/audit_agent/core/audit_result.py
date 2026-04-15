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