"""Offline eval harness for audit-agent quality checks."""

from __future__ import annotations

import tempfile
from pathlib import Path

from audit_agent.scanners.planning_constraints import scan_planning_constraints
from audit_agent.scanners.repo_snapshot import scan_repo_snapshot
from audit_agent.scanners.risk_map import scan_risk_map

from .audit_config import AuditConfig
from .audit_result import AuditResult, EvalCaseResult, EvalRunResult
from .audit_runner import _derive_blockers_from_evidence
from .delta_audit import detect_delta_triggers
from .evidence import collect_audit_evidence, collect_instruction_context


def run_eval_harness(config: AuditConfig) -> EvalRunResult:
    """Run deterministic offline evals and write machine-readable artifacts."""

    cases = [
        _case_repo_snapshot(),
        _case_instruction_ingestion(),
        _case_blocker_detection(),
        _case_risk_ranking(),
        _case_safest_start_points(),
        _case_delta_triggers(),
        _case_small_repo_false_positive_rate(),
    ]
    passed = sum(1 for case in cases if case.passed)
    failed = len(cases) - passed

    result = EvalRunResult(
        suite="audit-agent-offline",
        passed=passed,
        failed=failed,
        cases=cases,
    )
    result.markdown_content = _render_eval_markdown(result)
    _write_eval_artifacts(config.repo_root, result)
    return result


def _case_repo_snapshot() -> EvalCaseResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir)
        _write(repo / "pyproject.toml", "[project]\nname='demo'\n[tool.poetry.dependencies]\nfastapi='*'\n")
        _write(repo / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")

        snapshot = scan_repo_snapshot(repo)
        passed = (
            snapshot.get("primary_language") == "Python"
            and snapshot.get("framework") == "FastAPI"
            and "main.py" in snapshot.get("entry_points", [])
        )
        detail = (
            f"language={snapshot.get('primary_language')} "
            f"framework={snapshot.get('framework')} "
            f"entry_points={snapshot.get('entry_points')}"
        )
        return EvalCaseResult(name="repo_snapshot_correctness", passed=passed, detail=detail)


def _case_instruction_ingestion() -> EvalCaseResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir)
        (repo / ".github" / "instructions").mkdir(parents=True)
        _write(
            repo / "AGENTS.md",
            "## Rules\n- Respect module boundaries\n- Run pytest before merge\n",
        )
        _write(
            repo / ".github" / "instructions" / "python.instructions.md",
            "- Keep tests green\n- Do not hardcode secrets\n",
        )

        context = collect_instruction_context(repo)
        files = context.get("files", [])
        buckets = context.get("policy_buckets", {})
        passed = len(files) == 2 and bool(buckets.get("verification")) and bool(buckets.get("security"))
        detail = f"files={len(files)} verification={len(buckets.get('verification', []))}"
        return EvalCaseResult(name="instruction_ingestion_correctness", passed=passed, detail=detail)


def _case_blocker_detection() -> EvalCaseResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir)
        _write(repo / "config.py", 'api_key = "123456789012345678901234"\n')

        evidence = collect_audit_evidence(repo)
        blockers = _derive_blockers_from_evidence(evidence)
        passed = any("CRITICAL security" in blocker for blocker in blockers)
        detail = f"blockers={blockers}"
        return EvalCaseResult(name="blocker_detection_precision", passed=passed, detail=detail[:200])


def _case_risk_ranking() -> EvalCaseResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir)
        (repo / "tests").mkdir()
        _write(repo / "shared.py", "def helper():\n    return 1\n")
        large_module = ["from shared import helper\n"] * 8 + [f"def fn_{idx}():\n    return helper()\n" for idx in range(80)]
        _write(repo / "engine.py", "\n".join(large_module))
        for index in range(6):
            _write(
                repo / f"feature_{index}.py",
                f"from engine import fn_{index}\n\ndef run_{index}():\n    return fn_{index}()\n",
            )

        risk_map = scan_risk_map(repo)
        top = risk_map.get("risks", [{}])[0]
        passed = Path(top.get("module", "")).stem == "engine" and "HIGH" in top.get("risk", "")
        detail = f"top={top}"
        return EvalCaseResult(name="high_risk_module_ranking_quality", passed=passed, detail=detail[:200])


def _case_safest_start_points() -> EvalCaseResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir)
        _write(repo / "tiny_helper.py", "def run():\n    return 1\n")
        _write(
            repo / "service.py",
            "import os\nimport sys\nimport json\n\n"
            "def run_service():\n"
            + "    return 1\n" * 60,
        )

        planning = scan_planning_constraints(repo)
        safest = planning.get("safest_start_points", [])
        passed = "tiny_helper.py" in safest
        detail = f"safest={safest}"
        return EvalCaseResult(name="safest_start_recommendations", passed=passed, detail=detail)


def _case_delta_triggers() -> EvalCaseResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir)
        _write(repo / "pyproject.toml", "[project]\nname='demo'\n")
        audit = AuditResult(
            repo="demo",
            repo_root=repo,
            high_risk_modules=["auth.py"],
        )

        triggers = detect_delta_triggers(
            audit,
            task="touch auth pipeline",
            review_feedback="REVISE: missing verification",
            changed_files=["pyproject.toml"],
        )
        reasons = {trigger.reason for trigger in triggers}
        passed = {"dependency_change", "bad_review", "high_risk_plan"} <= reasons
        detail = f"reasons={sorted(reasons)}"
        return EvalCaseResult(name="delta_audit_trigger_correctness", passed=passed, detail=detail)


def _case_small_repo_false_positive_rate() -> EvalCaseResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Path(temp_dir)
        _write(repo / "main.py", "def run():\n    return 1\n")
        (repo / "tests").mkdir()
        _write(repo / "tests" / "test_main.py", "from main import run\n\ndef test_run():\n    assert run() == 1\n")
        _write(repo / "pytest.ini", "[pytest]\n")

        evidence = collect_audit_evidence(repo)
        blockers = _derive_blockers_from_evidence(evidence)
        passed = len(blockers) == 0
        detail = f"blockers={blockers}"
        return EvalCaseResult(name="small_repo_false_positive_rate", passed=passed, detail=detail)


def _render_eval_markdown(result: EvalRunResult) -> str:
    lines = [
        "# AUDIT_EVALS.md",
        f"**Suite:** {result.suite}",
        "",
        "## Summary",
        f"- Passed: {result.passed}",
        f"- Failed: {result.failed}",
        "",
        "## Cases",
    ]
    for case in result.cases:
        status = "PASS" if case.passed else "FAIL"
        lines.append(f"- [{status}] {case.name}: {case.detail}")
    lines.extend(["", "```json", result.to_json_block(), "```"])
    return "\n".join(lines)


def _write_eval_artifacts(repo_root: Path, result: EvalRunResult) -> None:
    artifacts_dir = repo_root / ".forgegod"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "AUDIT_EVALS.md").write_text(result.markdown_content, encoding="utf-8")
    (artifacts_dir / "AUDIT_EVALS.json").write_text(result.to_json_block(), encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
