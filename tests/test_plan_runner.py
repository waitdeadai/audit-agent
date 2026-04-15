"""Tests for the plan runner."""

from __future__ import annotations


from audit_agent.core.audit_config import AuditConfig, PlanConfig
from audit_agent.core.audit_result import AuditResult
from audit_agent.core.plan_runner import (
    _extract_guardrails,
    _parse_existing_stories,
    _build_plan_prompt,
    _extract_json_block,
    _parse_stories_from_json,
)


class TestParseExistingStories:
    """Tests for _parse_existing_stories()."""

    def test_empty_string(self):
        """Empty input returns empty list."""
        assert _parse_existing_stories("") == []

    def test_single_story(self):
        """Single story with acceptance criteria is parsed."""
        md = """## Phase 1

### S001 - Add user model
- User has email and password
- User has created_at timestamp
"""
        stories = _parse_existing_stories(md)
        assert len(stories) == 1
        assert stories[0]["id"] == "S001"
        assert "Add user model" in stories[0]["title"]
        assert len(stories[0]["acceptance_criteria"]) == 2

    def test_multiple_stories_with_milestone(self):
        """Multiple stories with milestone headers are parsed."""
        md = """## Setup

### S001 - Init project
- Create package.json
- Install dependencies

## Auth

### S002 - Add login
- POST /auth/login returns JWT
"""
        stories = _parse_existing_stories(md)
        assert len(stories) == 2
        assert stories[0]["id"] == "S001"
        assert "Setup:" in stories[0]["description"]
        assert stories[1]["id"] == "S002"
        assert "Auth:" in stories[1]["description"]

    def test_story_without_criteria(self):
        """Story without acceptance criteria still parsed."""
        md = "### S001 - Initial commit\n"
        stories = _parse_existing_stories(md)
        assert len(stories) == 1
        assert stories[0]["acceptance_criteria"] == []


class TestExtractGuardrails:
    """Tests for _extract_guardrails()."""

    def test_security_blocker_becomes_guardrail(self):
        """CRITICAL security blockers are promoted to guardrails."""
        audit_result = AuditResult(
            repo="test",
            blockers=["CRITICAL: hardcoded password in config.py"],
        )
        guardrails = _extract_guardrails(audit_result, {})
        assert any("hardcoded password" in g for g in guardrails)

    def test_high_risk_modules_become_guardrails(self):
        """High-risk modules get extra-verification guardrails."""
        audit_result = AuditResult(
            repo="test",
            high_risk_modules=["core/payment.py", "services/auth.py"],
        )
        guardrails = _extract_guardrails(audit_result, {})
        assert any("core/payment.py" in g for g in guardrails)
        assert any("services/auth.py" in g for g in guardrails)

    def test_taste_failures_become_guardrails(self):
        """Taste pre-flight failures are included."""
        audit_result = AuditResult(
            repo="test",
            taste_pre_flight_failures=["naming inconsistencies in API routes"],
        )
        guardrails = _extract_guardrails(audit_result, {})
        assert any("naming inconsistencies" in g for g in guardrails)

    def test_prd_non_goals_extracted(self):
        """Non-goals from PRD.md become guardrails."""
        audit_result = AuditResult(repo="test")
        repo_docs = {
            "docs/PRD.md": """## Non-Goals
- No runtime AI calls
- No third-party analytics
"""
        }
        guardrails = _extract_guardrails(audit_result, repo_docs)
        assert any("runtime AI" in g for g in guardrails)
        assert any("analytics" in g for g in guardrails)

    def test_empty_guardrails(self):
        """Empty audit + docs returns empty guardrails list."""
        audit_result = AuditResult(repo="test")
        guardrails = _extract_guardrails(audit_result, {})
        assert isinstance(guardrails, list)


class TestExtractJsonBlock:
    """Tests for _extract_json_block()."""

    def test_json_block_extracted(self):
        """JSON block in ``` delimiters is extracted."""
        text = """# Plan

Some text

```json
{
  "plan_agent": {
    "version": "1.0",
    "stories": [{"id": "S001", "title": "Test"}]
  }
}
```
"""
        block = _extract_json_block(text)
        assert "plan_agent" in block
        assert block["plan_agent"]["version"] == "1.0"

    def test_fallback_extraction(self):
        """Falls back to scanning for plan_agent key."""
        text = '{"plan_agent": {"version": "1.0", "stories": []}}'
        block = _extract_json_block(text)
        assert "plan_agent" in block

    def test_invalid_json_returns_empty(self):
        """Invalid JSON returns empty dict."""
        text = "not json at all"
        block = _extract_json_block(text)
        assert block == {}


class TestParseStoriesFromJson:
    """Tests for _parse_stories_from_json()."""

    def test_single_story(self):
        """Single story is parsed correctly."""
        json_block = {
            "plan_agent": {
                "stories": [
                    {
                        "id": "S001",
                        "title": "Add auth",
                        "description": "Add JWT auth",
                        "priority": 1,
                        "depends_on": [],
                        "effort": "low",
                        "risk": "low",
                        "modules_touched": ["auth.py"],
                        "blocked_by": [],
                        "acceptance_criteria": ["GET /me returns 200"],
                        "verification_commands": ["pytest tests/auth.py"],
                    }
                ]
            }
        }
        stories = _parse_stories_from_json(json_block)
        assert len(stories) == 1
        assert stories[0].id == "S001"
        assert stories[0].title == "Add auth"
        assert stories[0].priority == 1
        assert stories[0].effort == "low"
        assert len(stories[0].acceptance_criteria) == 1

    def test_multiple_stories_with_dependencies(self):
        """Multiple stories with dependencies are parsed."""
        json_block = {
            "plan_agent": {
                "stories": [
                    {
                        "id": "S001",
                        "title": "Setup",
                        "priority": 1,
                        "depends_on": [],
                    },
                    {
                        "id": "S002",
                        "title": "Auth",
                        "priority": 2,
                        "depends_on": ["S001"],
                    },
                ]
            }
        }
        stories = _parse_stories_from_json(json_block)
        assert len(stories) == 2
        assert stories[0].depends_on == []
        assert stories[1].depends_on == ["S001"]

    def test_empty_stories(self):
        """Empty stories list returns empty list."""
        json_block = {"plan_agent": {"stories": []}}
        assert _parse_stories_from_json(json_block) == []

    def test_missing_stories_key(self):
        """Missing stories key returns empty list."""
        json_block = {"plan_agent": {}}
        assert _parse_stories_from_json(json_block) == []


class TestBuildPlanPrompt:
    """Tests for _build_plan_prompt()."""

    def test_prompt_contains_task(self):
        """Built prompt contains the task string."""
        audit_result = AuditResult(
            repo="test-repo",
            effort_level="medium",
            high_risk_modules=["core/auth.py"],
            recommended_start_points=["utils/helpers.py"],
        )
        plan_config = PlanConfig(enabled=True, task="add authentication", max_stories=10)
        prompt = _build_plan_prompt(
            task="add authentication",
            audit_result=audit_result,
            repo_docs={},
            existing_stories=[],
            guardrails=["No secrets in code"],
            config=plan_config,
        )
        assert "add authentication" in prompt
        assert "core/auth.py" in prompt
        assert "No secrets in code" in prompt
        assert "medium" in prompt  # effort level

    def test_prompt_contains_existing_stories(self):
        """Existing stories are embedded in prompt for seeding."""
        audit_result = AuditResult(repo="test")
        plan_config = PlanConfig(enabled=True, max_stories=10)
        existing = [
            {
                "id": "S001",
                "title": "Setup project",
                "acceptance_criteria": ["package.json exists"],
            }
        ]
        prompt = _build_plan_prompt(
            task="add feature",
            audit_result=audit_result,
            repo_docs={},
            existing_stories=existing,
            guardrails=[],
            config=plan_config,
        )
        assert "S001" in prompt
        assert "Setup project" in prompt

    def test_prompt_respects_max_stories(self):
        """max_stories is embedded in prompt rules."""
        audit_result = AuditResult(repo="test")
        plan_config = PlanConfig(enabled=True, max_stories=5)
        prompt = _build_plan_prompt(
            task="big refactor",
            audit_result=audit_result,
            repo_docs={},
            existing_stories=[],
            guardrails=[],
            config=plan_config,
        )
        assert "Maximum 5 stories" in prompt


class TestPlanConfig:
    """Tests for PlanConfig model."""

    def test_plan_config_defaults(self):
        """PlanConfig has correct defaults."""
        config = PlanConfig()
        assert config.enabled is False
        assert config.output_path.name == "PLAN.md"
        assert config.auto_review is True
        assert config.max_stories == 20
        assert config.temperature == 0.3
        assert config.review_temperature == 0.4
        assert config.reviewer_model is None

    def test_plan_config_override(self):
        """PlanConfig accepts custom values."""
        config = PlanConfig(
            enabled=True,
            task="add REST API",
            max_stories=5,
            auto_review=False,
        )
        assert config.enabled is True
        assert config.task == "add REST API"
        assert config.max_stories == 5
        assert config.auto_review is False

    def test_plan_config_in_audit_config(self):
        """AuditConfig accepts PlanConfig."""
        plan_cfg = PlanConfig(enabled=True, task="test")
        config = AuditConfig(plan=plan_cfg)
        assert config.plan is not None
        assert config.plan.enabled is True
