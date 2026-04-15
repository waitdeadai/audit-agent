"""audit-agent — Mandatory pre-planning auditor for AI coding agents."""

from audit_agent.core import (
    AuditAgent,
    AuditConfig,
    AuditFinding,
    AuditResult,
    run_audit,
)

__version__ = "0.1.0"

__all__ = [
    "AuditAgent",
    "AuditConfig",
    "AuditFinding",
    "AuditResult",
    "run_audit",
    "__version__",
]