"""Tests for PlanResult and PlanStory models."""

from __future__ import annotations

import json

from audit_agent.core.audit_result import PlanResult, PlanStory


def test_plan_story_defaults():
    """PlanStory has correct defaults."""
    story = PlanStory(id="S001", title="Add auth")
    assert story.id == "S001"
    assert story.title == "Add auth"
    assert story.priority == 1
    assert story.depends_on == []
    assert story.acceptance_criteria == []
    assert story.verification_commands == []
    assert story.effort == "medium"
    assert story.risk == "low"
    assert story.modules_touched == []
    assert story.blocked_by == []


def test_plan_story_full():
    """PlanStory stores all fields."""
    story = PlanStory(
        id="S002",
        title="Add REST API",
        description="Expose user CRUD over HTTP",
        priority=2,
        depends_on=["S001"],
        acceptance_criteria=["GET /users returns 200", "POST /users creates user"],
        verification_commands=["pytest tests/test_api.py -q"],
        effort="high",
        risk="medium",
        modules_touched=["api/routes/users.py", "models/user.py"],
        blocked_by=["audit: CRITICAL auth bypass"],
    )
    assert story.id == "S002"
    assert story.description == "Expose user CRUD over HTTP"
    assert story.priority == 2
    assert story.depends_on == ["S001"]
    assert story.effort == "high"
    assert story.risk == "medium"
    assert len(story.acceptance_criteria) == 2
    assert len(story.verification_commands) == 1


def test_plan_result_to_json_block():
    """to_json_block produces valid JSON with plan_agent key."""
    story = PlanStory(
        id="S001",
        title="Add auth",
        effort="low",
        risk="low",
    )
    result = PlanResult(
        repo="my-repo",
        task="add authentication",
        stories=[story],
        guardrails=["Never commit secrets"],
        effort_level="thorough",
        ready_to_execute=True,
        blockers=[],
        high_risk_modules=["core/auth.py"],
        recommended_start="S001",
    )

    json_str = result.to_json_block()
    parsed = json.loads(json_str)

    assert "plan_agent" in parsed
    agent = parsed["plan_agent"]
    assert agent["repo"] == "my-repo"
    assert agent["task"] == "add authentication"
    assert len(agent["stories"]) == 1
    assert agent["stories"][0]["id"] == "S001"
    assert agent["effort_level"] == "thorough"
    assert agent["ready_to_execute"] is True
    assert agent["recommended_start"] == "S001"
    assert "Never commit secrets" in agent["guardrails"]


def test_plan_result_to_json_block_required_keys():
    """JSON block has all required keys per spec."""
    result = PlanResult(repo="my-repo", task="fix bug")
    json_str = result.to_json_block()
    parsed = json.loads(json_str)

    required_keys = [
        "version", "timestamp", "repo", "task", "stories",
        "guardrails", "effort_level", "ready_to_execute",
        "blockers", "high_risk_modules", "recommended_start",
    ]
    for key in required_keys:
        assert key in parsed["plan_agent"], f"Missing key: {key}"


def test_plan_result_to_json_block_valid_json():
    """to_json_block output is valid parseable JSON."""
    result = PlanResult(repo="test", task="test")
    json_str = result.to_json_block()
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)


def test_plan_result_summary():
    """summary() produces non-empty human-readable string."""
    result = PlanResult(
        repo="test-repo",
        task="add REST API",
        stories=[
            PlanStory(id="S001", title="Auth", effort="low", risk="low"),
            PlanStory(id="S002", title="Users", effort="medium", risk="medium"),
        ],
        guardrails=["No secrets in code"],
        effort_level="medium",
        ready_to_execute=True,
    )
    summary = result.summary()
    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "READY" in summary
    assert "test-repo" in summary
    assert "stories=2" in summary
    assert "guardrails=1" in summary


def test_plan_result_summary_blocked():
    """summary() shows BLOCKED when ready_to_execute is False."""
    result = PlanResult(
        repo="test-repo",
        task="refactor all",
        stories=[],
        effort_level="exhaustive",
        ready_to_execute=False,
        blockers=["CRITICAL: security vulnerability found"],
    )
    summary = result.summary()
    assert "BLOCKED" in summary


def test_plan_result_timestamp_auto_set():
    """timestamp is auto-set if not provided."""
    result = PlanResult(repo="test")
    assert result.timestamp != ""


def test_plan_result_multiple_stories():
    """PlanResult handles multiple stories correctly."""
    stories = [
        PlanStory(
            id=f"S{i:03d}",
            title=f"Story {i}",
            priority=i,
            depends_on=[f"S{i-1:03d}"] if i > 1 else [],
        )
        for i in range(1, 4)
    ]
    result = PlanResult(repo="test", stories=stories)
    assert len(result.stories) == 3
    assert result.stories[0].depends_on == []
    assert result.stories[1].depends_on == ["S001"]
    assert result.stories[2].depends_on == ["S002"]
