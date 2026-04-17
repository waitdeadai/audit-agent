"""Tests for hybrid audit evidence collection."""

from __future__ import annotations

from audit_agent.core.evidence import (
    build_repo_map,
    collect_audit_evidence,
    collect_instruction_context,
    summarize_evidence_for_prompt,
)


def _seed_repo(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "## Rules\n"
        "- Respect architecture boundaries\n"
        "- Run pytest before merge\n"
        "- Never hardcode secrets\n",
        encoding="utf-8",
    )
    (tmp_path / ".github" / "instructions").mkdir(parents=True)
    (tmp_path / ".github" / "instructions" / "api.instructions.md").write_text(
        "# API instructions\n"
        "- Keep response shapes stable\n"
        "- Verify endpoints with tests\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "from service import run\n\n"
        "def main():\n"
        "    return run()\n",
        encoding="utf-8",
    )
    (tmp_path / "service.py").write_text(
        "def run():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_service.py").write_text(
        "from service import run\n\n"
        "def test_run():\n"
        "    assert run()['ok'] is True\n",
        encoding="utf-8",
    )


def test_collect_instruction_context_reads_known_files(tmp_path):
    _seed_repo(tmp_path)

    context = collect_instruction_context(tmp_path)

    assert len(context["files"]) >= 2
    paths = {item["path"] for item in context["files"]}
    assert "AGENTS.md" in paths
    assert ".github/instructions/api.instructions.md" in paths
    assert context["policy_buckets"]["architecture"]
    assert context["policy_buckets"]["verification"]
    assert context["policy_buckets"]["security"]


def test_collect_audit_evidence_contains_core_sections(tmp_path):
    _seed_repo(tmp_path)

    evidence = collect_audit_evidence(tmp_path)

    required_keys = {
        "instruction_context",
        "repo_snapshot",
        "entry_points",
        "architecture",
        "dependencies",
        "internal_dependencies",
        "health",
        "test_surface",
        "security",
        "risk_map",
        "taste_preflight",
        "effort_requirements",
        "planning_constraints",
    }
    assert required_keys.issubset(evidence.keys())


def test_repo_map_and_prompt_summary_are_high_signal(tmp_path):
    _seed_repo(tmp_path)
    evidence = collect_audit_evidence(tmp_path)

    repo_map = build_repo_map(evidence)
    summary = summarize_evidence_for_prompt(evidence)

    assert "Instruction files:" in repo_map
    assert "Entry points:" in repo_map
    assert "Deterministic audit evidence" in summary
    assert "Tests:" in summary
