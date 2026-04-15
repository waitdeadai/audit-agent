"""Tests for AuditResult."""

from __future__ import annotations

import json

from audit_agent.core.audit_result import AuditFinding, AuditResult


def test_audit_result_to_json_block():
    """to_json_block produces valid JSON with all required keys."""
    result = AuditResult(
        repo="test-repo",
        ready_to_plan=True,
        effort_level="thorough",
        blockers=["CRITICAL: hardcoded password in config.py"],
        high_risk_modules=["core/auth.py", "services/payment.py"],
        recommended_start_points=["utils/helpers.py"],
        taste_pre_flight_failures=["naming inconsistencies in API"],
    )

    json_str = result.to_json_block()
    parsed = json.loads(json_str)

    assert "audit_agent" in parsed
    agent = parsed["audit_agent"]
    assert agent["version"] == "1.0"
    assert agent["repo"] == "test-repo"
    assert agent["ready_to_plan"] is True
    assert agent["effort_level"] == "thorough"
    assert len(agent["blockers"]) == 1
    assert len(agent["high_risk_modules"]) == 2
    assert len(agent["recommended_start_points"]) == 1
    assert len(agent["taste_pre_flight_failures"]) == 1


def test_audit_result_to_json_block_required_keys():
    """JSON block has all required keys per spec."""
    result = AuditResult(repo="my-repo")
    json_str = result.to_json_block()
    parsed = json.loads(json_str)

    required_keys = [
        "version", "timestamp", "repo", "blockers",
        "high_risk_modules", "recommended_start_points",
        "effort_level", "taste_pre_flight_failures", "ready_to_plan",
    ]
    for key in required_keys:
        assert key in parsed["audit_agent"], f"Missing key: {key}"


def test_audit_result_to_json_block_valid_json():
    """to_json_block output is valid parseable JSON."""
    result = AuditResult(repo="test")
    json_str = result.to_json_block()

    # Must not raise
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)


def test_audit_result_summary():
    """summary() produces a non-empty human-readable string."""
    result = AuditResult(
        repo="test-repo",
        ready_to_plan=True,
        effort_level="exhaustive",
    )
    summary = result.summary()
    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "READY" in summary
    assert "test-repo" in summary
    assert "exhaustive" in summary


def test_audit_result_summary_blocked():
    """summary() shows BLOCKED when ready_to_plan is False."""
    result = AuditResult(
        repo="test-repo",
        ready_to_plan=False,
        blockers=["CRITICAL: secret in source"],
    )
    summary = result.summary()
    assert "BLOCKED" in summary


def test_audit_finding_creation():
    """AuditFinding stores severity, category, and description."""
    finding = AuditFinding(
        severity="CRITICAL",
        category="security",
        file="config.py",
        line=42,
        description="Hardcoded password found",
    )
    assert finding.severity == "CRITICAL"
    assert finding.category == "security"
    assert finding.file == "config.py"
    assert finding.line == 42
    assert finding.description == "Hardcoded password found"


def test_audit_result_timestamp_auto_set():
    """timestamp is auto-set if not provided."""
    result = AuditResult(repo="test")
    assert result.timestamp != ""
    # Should be an ISO format string
    assert "T" in result.timestamp or ":" in result.timestamp


def test_audit_result_with_findings():
    """AuditResult stores a list of AuditFinding objects."""
    finding1 = AuditFinding(
        severity="CRITICAL",
        category="security",
        description="Hardcoded secret",
    )
    finding2 = AuditFinding(
        severity="WARNING",
        category="code-quality",
        description="TODO comment",
    )
    result = AuditResult(
        repo="test-repo",
        findings=[finding1, finding2],
    )
    assert len(result.findings) == 2
    assert result.findings[0].severity == "CRITICAL"
    assert result.findings[1].severity == "WARNING"