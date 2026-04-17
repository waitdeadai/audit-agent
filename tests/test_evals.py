"""Tests for the offline eval harness."""

from __future__ import annotations

from audit_agent.core.audit_config import AuditConfig
from audit_agent.core.evals import run_eval_harness


def test_run_eval_harness_writes_artifacts_and_reports_green(tmp_path):
    result = run_eval_harness(AuditConfig(repo_root=tmp_path))

    assert result.failed == 0
    assert result.passed >= 7
    assert (tmp_path / ".forgegod" / "AUDIT_EVALS.md").exists()
    assert (tmp_path / ".forgegod" / "AUDIT_EVALS.json").exists()
