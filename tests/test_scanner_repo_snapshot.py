"""Tests for the repo snapshot scanner."""

from __future__ import annotations

from audit_agent.scanners.repo_snapshot import scan_repo_snapshot


def test_scan_repo_snapshot_returns_dict(repo_root):
    """scan_repo_snapshot returns a dictionary."""
    result = scan_repo_snapshot(repo_root)
    assert isinstance(result, dict)


def test_scan_repo_snapshot_has_expected_keys(repo_root):
    """Result has all required keys."""
    result = scan_repo_snapshot(repo_root)

    required_keys = [
        "repo_name", "primary_language", "framework",
        "file_count", "line_count",
        "last_commit_hash", "last_commit_date",
        "package_manager", "entry_points",
        "test_framework", "has_ci",
        "has_agents_md", "has_claude_md", "has_forgegod_config",
    ]
    for key in required_keys:
        assert key in result, f"Missing key: {key}"


def test_scan_repo_snapshot_self_audit(repo_root):
    """Self-audit on the audit-agent repo itself (repo has Python files)."""
    result = scan_repo_snapshot(repo_root)

    # audit-agent is a Python project
    assert result["primary_language"] == "Python"
    assert result["file_count"] > 0
    assert result["line_count"] > 0
    assert isinstance(result["file_count"], int)
    assert isinstance(result["line_count"], int)


def test_scan_repo_snapshot_entry_points(repo_root):
    """entry_points is a list."""
    result = scan_repo_snapshot(repo_root)
    assert isinstance(result["entry_points"], list)


def test_scan_repo_snapshot_boolean_fields(repo_root):
    """Boolean fields are actually booleans."""
    result = scan_repo_snapshot(repo_root)

    assert isinstance(result["has_ci"], bool)
    assert isinstance(result["has_agents_md"], bool)
    assert isinstance(result["has_claude_md"], bool)
    assert isinstance(result["has_forgegod_config"], bool)


def test_scan_repo_snapshot_works_on_minimal_dir(tmp_path):
    """Scanner works on an empty/minimal directory without errors."""
    # Create a minimal Python file
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

    result = scan_repo_snapshot(tmp_path)

    assert result["repo_name"] == tmp_path.name
    assert result["primary_language"] == "Python"
    assert result["file_count"] >= 1
    assert result["line_count"] >= 1
    assert isinstance(result["entry_points"], list)