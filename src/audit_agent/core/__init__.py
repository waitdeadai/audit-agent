"""audit-agent core — pre-planning auditor for the WAITDEAD system."""

from __future__ import annotations

from .audit_agent import AuditAgent
from .audit_config import AuditConfig
from .audit_result import AuditResult, AuditFinding
from .audit_runner import run_audit

__version__ = "0.1.0"

__all__ = [
    "AuditAgent",
    "AuditConfig",
    "AuditResult",
    "AuditFinding",
    "run_audit",
]