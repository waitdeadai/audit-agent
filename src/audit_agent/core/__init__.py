"""audit-agent core — pre-planning auditor for the WAITDEAD system."""

from __future__ import annotations

from .audit_agent import AuditAgent
from .audit_config import AuditConfig, PlanConfig
from .audit_result import (
    AuditResult,
    AuditFinding,
    DeltaAuditResult,
    DeltaTrigger,
    EvalCaseResult,
    EvalRunResult,
    PlanResult,
    PlanStory,
    SpecialistAuditResult,
)
from .audit_runner import run_audit
from .delta_audit import collect_delta_context, detect_delta_triggers, run_delta_audit
from .evals import run_eval_harness
from .plan_runner import run_plan
from .specialist_audits import (
    run_architecture_audit,
    run_plan_risk_audit,
    run_security_audit,
)

__version__ = "0.3.0"

__all__ = [
    "AuditAgent",
    "AuditConfig",
    "AuditResult",
    "AuditFinding",
    "DeltaAuditResult",
    "DeltaTrigger",
    "EvalCaseResult",
    "EvalRunResult",
    "PlanResult",
    "PlanStory",
    "SpecialistAuditResult",
    "PlanConfig",
    "detect_delta_triggers",
    "collect_delta_context",
    "run_audit",
    "run_delta_audit",
    "run_security_audit",
    "run_architecture_audit",
    "run_plan_risk_audit",
    "run_eval_harness",
    "run_plan",
]
