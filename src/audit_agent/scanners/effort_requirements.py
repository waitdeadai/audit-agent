"""Scanner: effort-agent requirements — Step 10 of the audit protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def scan_effort_requirements(repo_root: Path) -> dict[str, Any]:
    """Recommend effort level based on codebase health.

    Returns a dict with:
        - research_before_code (bool)
        - min_drafts (str): efficient | thorough | exhaustive
        - mandatory_tests (list[str])
        - single_pass_not_acceptable (list[str])
        - effort_block (str): formatted block for effort-agent
    """
    # Heuristic: complex deps = research first
    has_complex_deps = any(
        (repo_root / f).exists()
        for f in ["pyproject.toml", "go.mod", "Cargo.toml", "package.json"]
    )
    research_before_code = has_complex_deps

    # File count as a proxy for effort
    py_files = list(repo_root.rglob("*.py"))
    non_test = [f for f in py_files if "test" not in f.name.lower()
                and not any(p in f.parts for p in {".git", "node_modules", "__pycache__"})]
    file_count = len(non_test)

    if file_count > 100:
        min_drafts = "exhaustive"
    elif file_count > 30:
        min_drafts = "thorough"
    else:
        min_drafts = "efficient"

    # Modules needing mandatory tests
    mandatory = _mandatory_test_modules(non_test)
    no_single_pass = _no_single_pass_modules(non_test)

    block = f"""## Effort Requirements (audit-agent)
- research_before_code: {research_before_code} ({'deps complex' if has_complex_deps else 'simple deps'})
- min_drafts: {min_drafts} ({file_count} source files)
- mandatory_tests: {', '.join(mandatory) if mandatory else 'none'}
- single_pass_NOT_acceptable: {', '.join(no_single_pass) if no_single_pass else 'none'}"""

    return {
        "research_before_code": research_before_code,
        "min_drafts": min_drafts,
        "mandatory_tests": mandatory,
        "single_pass_not_acceptable": no_single_pass,
        "effort_block": block,
    }


def _mandatory_test_modules(files: list[Path]) -> list[str]:
    """Modules that MUST have test verification before DONE."""
    return [
        "router" in str(f) and f.name.replace("_", "") for f in files
    ]
    # Simplified: just return known high-risk module names
    risky_names = {"router", "agent", "loop", "security", "auth"}
    return [n for n in risky_names if any(n in f.name.lower() for f in files)]


def _no_single_pass_modules(files: list[Path]) -> list[str]:
    """Modules where single-pass completion is never acceptable."""
    large_files = [f for f in files if f.name.endswith(".py")]
    big = [str(f.name) for f in large_files if _line_count(f) > 800]
    return big
    risky_names = {"router", "agent", "evals", "cli"}
    return [str(f.name) for f in files if any(n in f.name.lower() for n in risky_names)]


def _line_count(f: Path) -> int:
    try:
        return f.read_text(errors="replace").count("\n")
    except OSError:
        return 0
