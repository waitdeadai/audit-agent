"""Tests for specialist audit surfaces."""

from __future__ import annotations

from audit_agent.core.audit_config import AuditConfig
from audit_agent.core.audit_result import AuditResult, PlanResult, PlanStory
from audit_agent.core.specialist_audits import (
    run_architecture_audit,
    run_plan_risk_audit,
    run_security_audit,
)


def _base_audit(tmp_path):
    return AuditResult(
        repo=tmp_path.name,
        repo_root=tmp_path,
        output_path=tmp_path / ".forgegod" / "AUDIT.md",
        blockers=[],
        high_risk_modules=["src/auth.py"],
        recommended_start_points=["src/utils.py"],
    )


def test_run_security_audit_writes_artifacts_and_blocks_critical_findings(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "config.py").write_text(
        'api_key = "123456789012345678901234"\n',
        encoding="utf-8",
    )

    result = run_security_audit(_base_audit(tmp_path), AuditConfig(repo_root=tmp_path))

    assert result.kind == "security"
    assert result.ready is False
    assert result.blockers
    assert (tmp_path / ".forgegod" / "SECURITY_AUDIT.md").exists()
    assert (tmp_path / ".forgegod" / "SECURITY_AUDIT.json").exists()


def test_run_architecture_audit_detects_circular_imports(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("from b import run\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("from a import run\n", encoding="utf-8")

    result = run_architecture_audit(_base_audit(tmp_path), AuditConfig(repo_root=tmp_path))

    assert result.kind == "architecture"
    assert result.ready is False
    assert any("Circular import detected" in blocker for blocker in result.blockers)
    assert (tmp_path / ".forgegod" / "ARCHITECTURE_AUDIT.json").exists()


def test_run_plan_risk_audit_blocks_high_risk_story_without_verification(tmp_path):
    audit_result = _base_audit(tmp_path)
    plan_result = PlanResult(
        repo=tmp_path.name,
        task="refactor auth",
        stories=[
            PlanStory(
                id="S001",
                title="Refactor auth adapter",
                modules_touched=["src/auth.py"],
                verification_commands=[],
                acceptance_criteria=["Auth tests stay green"],
            )
        ],
        ready_to_execute=True,
    )

    result = run_plan_risk_audit(
        audit_result,
        plan_result,
        AuditConfig(repo_root=tmp_path),
        task="refactor auth",
    )

    assert result.kind == "plan-risk"
    assert result.ready is False
    assert any("verification commands" in blocker for blocker in result.blockers)
    assert "src/auth.py" in result.relevant_modules
    assert (tmp_path / ".forgegod" / "PLAN_RISK_AUDIT.md").exists()
