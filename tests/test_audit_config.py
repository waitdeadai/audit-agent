"""Tests for AuditConfig."""

from __future__ import annotations

from pathlib import Path

from audit_agent.core.audit_config import AuditConfig


def test_audit_config_defaults():
    """AuditConfig has sensible defaults."""
    config = AuditConfig()

    assert config.repo_root == Path.cwd()
    assert config.output_path == Path(".forgegod/AUDIT.md")
    assert config.model == "minimax/minimax-m2.7-highspeed"
    assert config.temperature == 0.2
    assert config.top_p == 0.9
    assert config.max_tokens == 8000
    assert config.stale_after_commits == 20
    assert config.verbose is False


def test_audit_config_custom_values():
    """AuditConfig accepts custom values."""
    config = AuditConfig(
        repo_root=Path("/tmp/my-repo"),
        output_path=Path("/tmp/my-repo/AUDIT.md"),
        model="openai/gpt-4.4",
        temperature=0.5,
        top_p=0.95,
        max_tokens=4000,
        stale_after_commits=10,
        verbose=True,
    )

    assert config.repo_root == Path("/tmp/my-repo")
    assert config.output_path == Path("/tmp/my-repo/AUDIT.md")
    assert config.model == "openai/gpt-4.4"
    assert config.temperature == 0.5
    assert config.top_p == 0.95
    assert config.max_tokens == 4000
    assert config.stale_after_commits == 10
    assert config.verbose is True


def test_audit_config_validation_temperature():
    """AuditConfig accepts temperature in valid range."""
    config_low = AuditConfig(temperature=0.0)
    assert config_low.temperature == 0.0

    config_high = AuditConfig(temperature=1.0)
    assert config_high.temperature == 1.0


def test_audit_config_model_specs_single():
    """model_specs returns single item for a single model."""
    config = AuditConfig(model="minimax/minimax-m2.7-highspeed")
    specs = config.model_specs()
    assert len(specs) == 1
    assert specs[0] == ("minimax", "minimax-m2.7-highspeed")


def test_audit_config_model_specs_with_fallbacks():
    """model_specs returns chain with fallbacks."""
    config = AuditConfig(
        model="minimax/minimax-m2.7-highspeed",
        model_fallback="openai/gpt-4.4-mini",
        model_fallback2="zai/glm-5",
    )
    specs = config.model_specs()
    assert len(specs) == 3
    assert specs[0] == ("minimax", "minimax-m2.7-highspeed")
    assert specs[1] == ("openai", "gpt-4.4-mini")
    assert specs[2] == ("zai", "glm-5")


def test_audit_config_bare_model_name():
    """Bare model name defaults to openai provider."""
    config = AuditConfig(model="gpt-4.4")
    specs = config.model_specs()
    assert specs[0] == ("openai", "gpt-4.4")


def test_audit_config_is_pydantic_model():
    """AuditConfig is a valid Pydantic model."""
    config = AuditConfig.model_validate({
        "repo_root": "/tmp/test",
        "model": "minimax/test",
    })
    assert config.model == "minimax/test"
    assert config.repo_root == Path("/tmp/test")