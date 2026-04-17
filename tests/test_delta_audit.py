"""Tests for delta-audit triggers and runtime."""

from __future__ import annotations

import json

import pytest

from audit_agent.core.audit_agent import AuditAgent
from audit_agent.core.audit_config import AuditConfig
from audit_agent.core.audit_result import AuditResult, DeltaAuditResult, PlanResult, PlanStory
from audit_agent.core.delta_audit import (
    collect_delta_context,
    detect_delta_triggers,
    run_delta_audit,
)


def _base_audit(tmp_path) -> AuditResult:
    return AuditResult(
        repo=tmp_path.name,
        repo_root=tmp_path,
        output_path=tmp_path / ".forgegod" / "AUDIT.md",
        timestamp="2026-04-17T00:00:00+00:00",
        high_risk_modules=["src/payment.py", "src/auth.py"],
        recommended_start_points=["src/utils.py"],
        ready_to_plan=True,
    )


def test_detect_delta_triggers_for_dependency_and_instruction_changes(tmp_path):
    audit_result = _base_audit(tmp_path)

    triggers = detect_delta_triggers(
        audit_result,
        changed_files=["pyproject.toml", "AGENTS.md"],
    )

    reasons = {trigger.reason for trigger in triggers}
    assert "dependency_change" in reasons
    assert "instruction_change" in reasons
    assert any(trigger.full_reaudit_recommended for trigger in triggers)


def test_detect_delta_triggers_for_high_risk_task_and_review_feedback(tmp_path):
    audit_result = _base_audit(tmp_path)

    triggers = detect_delta_triggers(
        audit_result,
        task="refactor payment flow and retry auth guard",
        review_feedback="Reviewer says the payment boundary is unclear",
        failure_details="planner kept looping on payment adapter",
        changed_files=[],
    )

    reasons = {trigger.reason for trigger in triggers}
    assert "high_risk_plan" in reasons
    assert "bad_review" in reasons
    assert "stuck" in reasons


def test_collect_delta_context_requires_full_reaudit_for_dependency_changes(tmp_path):
    audit_result = _base_audit(tmp_path)

    context = collect_delta_context(
        audit_result,
        task="update dependencies",
        changed_files=["requirements.txt"],
    )

    assert context["full_reaudit_required"] is True
    assert context["recommended_action"] == "full_reaudit"
    assert context["changed_files"] == ["requirements.txt"]


@pytest.mark.asyncio
async def test_run_delta_audit_writes_artifacts(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("- Run tests\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "payment.py").write_text("def charge():\n    return True\n", encoding="utf-8")
    audit_result = _base_audit(tmp_path)
    config = AuditConfig(repo_root=tmp_path)

    async def fake_call(system_prompt, user_prompt, config):
        return """# AUDIT_DELTA.md
## Trigger Summary
- dependency change

```json
{
  "delta_audit": {
    "repo": "demo",
    "task": "update payment flow",
    "ready_to_plan": false,
    "full_reaudit_required": true,
    "recommended_action": "full_reaudit",
    "blocker_updates": ["Dependencies changed"],
    "guardrail_updates": ["Re-read repository instructions"],
    "relevant_modules": ["src/payment.py"]
  }
}
```"""

    monkeypatch.setattr("audit_agent.core.delta_audit.call_llm", fake_call)

    result = await run_delta_audit(
        audit_result,
        config,
        task="update payment flow",
        changed_files=["pyproject.toml"],
    )

    assert isinstance(result, DeltaAuditResult)
    assert result.full_reaudit_required is True
    assert result.ready_to_plan is False

    delta_md = tmp_path / ".forgegod" / "AUDIT_DELTA.md"
    delta_json = tmp_path / ".forgegod" / "AUDIT_DELTA.json"
    assert delta_md.exists()
    assert delta_json.exists()

    parsed = json.loads(delta_json.read_text(encoding="utf-8"))
    assert parsed["delta_audit"]["recommended_action"] == "full_reaudit"


@pytest.mark.asyncio
async def test_audit_agent_run_plan_attaches_delta_audit(tmp_path, monkeypatch):
    audit_result = _base_audit(tmp_path)
    config = AuditConfig(repo_root=tmp_path)
    agent = AuditAgent(config)
    agent.result = audit_result

    monkeypatch.setattr(agent, "is_stale", lambda: False)

    async def fake_delta(*args, **kwargs):
        return DeltaAuditResult(
            repo=tmp_path.name,
            task="touch payment",
            triggers=[],
            recommended_action="run_delta_audit",
            ready_to_plan=True,
            relevant_modules=["src/payment.py"],
        )

    async def fake_plan(audit_result, task, config):
        return PlanResult(
            repo=tmp_path.name,
            task=task,
            stories=[
                PlanStory(
                    id="S001",
                    title="Touch payment adapter",
                    modules_touched=["src/payment.py"],
                    verification_commands=["pytest tests/test_payment.py"],
                    acceptance_criteria=["Payment tests stay green"],
                )
            ],
            ready_to_execute=True,
            markdown_content="# PLAN.md\n",
        )

    monkeypatch.setattr("audit_agent.core.audit_agent.run_delta_audit", fake_delta)
    monkeypatch.setattr("audit_agent.core.audit_agent.run_plan", fake_plan)

    plan_result = await agent.run_plan("touch payment")

    assert plan_result.delta_audit is not None
    assert plan_result.delta_audit.recommended_action == "run_delta_audit"
    assert plan_result.specialist_audits
