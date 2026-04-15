"""Smoke tests for AuditAgent."""

from __future__ import annotations


from audit_agent.core.audit_agent import AuditAgent
from audit_agent.core.audit_config import AuditConfig


def test_audit_agent_instantiation():
    """AuditAgent can be instantiated with default config."""
    agent = AuditAgent()
    assert agent.config is not None
    assert isinstance(agent.config, AuditConfig)


def test_audit_agent_instantiation_with_custom_config(mock_audit_config):
    """AuditAgent accepts a custom AuditConfig."""
    agent = AuditAgent(config=mock_audit_config)
    assert agent.config is mock_audit_config


def test_audit_result_has_required_fields():
    """AuditResult has all required fields."""
    from audit_agent.core.audit_result import AuditResult

    result = AuditResult(
        repo="test-repo",
        ready_to_plan=True,
    )
    assert hasattr(result, "version")
    assert hasattr(result, "timestamp")
    assert hasattr(result, "repo")
    assert hasattr(result, "findings")
    assert hasattr(result, "blockers")
    assert hasattr(result, "high_risk_modules")
    assert hasattr(result, "recommended_start_points")
    assert hasattr(result, "effort_level")
    assert hasattr(result, "taste_pre_flight_failures")
    assert hasattr(result, "ready_to_plan")
    assert hasattr(result, "markdown_content")


def test_audit_result_ready_to_plan_is_bool():
    """AuditResult.ready_to_plan is a boolean."""
    from audit_agent.core.audit_result import AuditResult

    result = AuditResult(repo="test", ready_to_plan=True)
    assert isinstance(result.ready_to_plan, bool)
    assert result.ready_to_plan is True

    result2 = AuditResult(repo="test", ready_to_plan=False)
    assert result2.ready_to_plan is False


def test_is_stale_returns_true_when_no_file(tmp_path):
    """is_stale returns True when AUDIT.md does not exist."""
    config = AuditConfig(
        repo_root=tmp_path,
        output_path=tmp_path / ".forgegod" / "AUDIT.md",
    )
    agent = AuditAgent(config)
    assert agent.is_stale() is True


def test_is_stale_returns_false_for_fresh_file(tmp_path):
    """is_stale returns False when AUDIT.md is freshly written."""
    audit_file = tmp_path / ".forgegod" / "AUDIT.md"
    audit_file.parent.mkdir(parents=True)
    audit_file.write_text("# AUDIT.md\n", encoding="utf-8")

    config = AuditConfig(repo_root=tmp_path, output_path=audit_file)
    agent = AuditAgent(config)

    # Fresh file should not be stale
    assert agent.is_stale() is False


def test_load_existing_returns_none_when_missing(tmp_path):
    """load_existing returns None when no AUDIT.md exists."""
    config = AuditConfig(
        repo_root=tmp_path,
        output_path=tmp_path / "AUDIT.md",
    )
    agent = AuditAgent(config)
    assert agent.load_existing() is None


def test_load_existing_parses_audit_file(tmp_path):
    """load_existing parses an existing AUDIT.md."""
    audit_content = """# AUDIT.md
**Repo:** test-repo · **Generated:** 2026-04-15T10:00:00Z · **Agent:** audit-agent

---

## Summary
Test summary

---

```json
{
  "audit_agent": {
    "version": "1.0",
    "timestamp": "2026-04-15T10:00:00Z",
    "repo": "test-repo",
    "blockers": [],
    "high_risk_modules": [],
    "recommended_start_points": [],
    "effort_level": "thorough",
    "taste_pre_flight_failures": [],
    "ready_to_plan": true
  }
}
```
"""
    audit_file = tmp_path / ".forgegod" / "AUDIT.md"
    audit_file.parent.mkdir(parents=True)
    audit_file.write_text(audit_content, encoding="utf-8")

    config = AuditConfig(repo_root=tmp_path, output_path=audit_file)
    agent = AuditAgent(config)
    result = agent.load_existing()

    assert result is not None
    assert result.repo == "test-repo"
    assert result.ready_to_plan is True
    assert result.effort_level == "thorough"