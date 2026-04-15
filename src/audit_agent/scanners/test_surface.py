"""Scanner: test surface — Step 6 of the audit protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def scan_test_surface(repo_root: Path) -> dict[str, Any]:
    """Assess test coverage by module.

    Returns a dict with:
        - total_modules (int)
        - modules_with_tests (int)
        - test_percentage (float)
        - test_runner (str or None)
        - modules_without_tests (list[str])
        - skip_count (int)
        - xfail_count (int)
        - ci_has_tests (bool)
    """
    py_files = _all_source_files(repo_root)
    test_files = _all_test_files(repo_root)
    test_runner = _detect_test_runner(repo_root)
    modules_with_tests = _modules_with_tests(py_files, test_files)
    modules_without = [m for m in py_files if m not in modules_with_tests and not _is_test_file(m)]
    skip_count, xfail_count = _count_skips_xfails(test_files)
    ci_has_tests = _ci_has_tests(repo_root)

    total = len(py_files)
    covered = len(modules_with_tests)
    pct = (covered / total * 100) if total > 0 else 0

    return {
        "total_modules": total,
        "modules_with_tests": covered,
        "test_percentage": round(pct, 1),
        "test_runner": test_runner,
        "modules_without_tests": [str(m) for m in modules_without[:15]],
        "skip_count": skip_count,
        "xfail_count": xfail_count,
        "ci_has_tests": ci_has_tests,
    }


def _all_source_files(repo_root: Path) -> list[Path]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "tests", "test"}
    return [f for f in repo_root.rglob("*.py")
            if not any(p in f.parts for p in skip) and not _is_test_file(f)]


def _all_test_files(repo_root: Path) -> list[Path]:
    skip = {".git", "node_modules", "__pycache__"}
    return [f for f in repo_root.rglob("*test*.py")
            if not any(p in f.parts for p in skip)]


def _is_test_file(f: Path) -> bool:
    return "test" in f.name.lower() or f.name.startswith("test_")


def _detect_test_runner(repo_root: Path) -> str | None:
    if (repo_root / "pytest.ini").exists():
        return "pytest"
    ptoml = repo_root / "pyproject.toml"
    if ptoml.exists():
        content = ptoml.read_text(errors="replace")
        if "[tool.pytest" in content or "pytest" in content:
            return "pytest"
    if (repo_root / "package.json").exists():
        content = (repo_root / "package.json").read_text(errors="replace")
        if "vitest" in content:
            return "vitest"
        if "jest" in content:
            return "jest"
    return None


def _modules_with_tests(source_files: list[Path], test_files: list[Path]) -> set[Path]:
    covered: set[Path] = set()
    for tf in test_files:
        content = tf.read_text(errors="replace")
        for sf in source_files:
            if sf.name.replace(".py", "") in content or sf.stem in content:
                covered.add(sf)
    return covered


def _count_skips_xfails(test_files: list[Path]) -> tuple[int, int]:
    skip_count = xfail_count = 0
    import re
    skip_pat = re.compile(r"@pytest\.mark\.skip", re.IGNORECASE)
    xfail_pat = re.compile(r"@pytest\.mark\.xfail", re.IGNORECASE)
    for tf in test_files:
        try:
            content = tf.read_text(errors="replace")
            skip_count += len(skip_pat.findall(content))
            xfail_count += len(xfail_pat.findall(content))
        except OSError:
            continue
    return skip_count, xfail_count


def _ci_has_tests(repo_root: Path) -> bool:
    workflows = repo_root / ".github" / "workflows"
    if not workflows.exists():
        return False
    for wf in workflows.rglob("*.yml"):
        content = wf.read_text(errors="replace")
        if "pytest" in content or "test" in content.lower():
            return True
    return False
