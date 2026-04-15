"""Scanner: planning constraints — Step 11 of the audit protocol."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


def scan_planning_constraints(repo_root: Path) -> dict[str, Any]:
    """Identify blockers, pre-work, safest and riskiest modules.

    Returns a dict with:
        - blockers (list[str])
        - recommended_prework (list[str])
        - safest_start_points (list[str])
        - riskiest_modules (list[str])
    """
    py_files = _all_py(repo_root)
    blockers: list[str] = []
    prework: list[str] = []

    # Check for CRITICAL security issues
    critical = _has_critical_security(repo_root)
    if critical:
        blockers.append(f"CRITICAL security: {critical}")

    # Circular imports
    if _has_circular_imports(py_files):
        blockers.append("Circular imports detected — must be resolved before any change")

    # Missing test infrastructure
    if not (repo_root / "pytest.ini").exists() and not _has_pytest_in_config(repo_root):
        prework.append("Set up pytest — no test infrastructure detected")

    # Find safest start points (small, isolated modules)
    safest = _find_safest_modules(py_files)

    # Find riskiest modules (large, highly-connected, untested)
    riskiest = _find_riskiest_modules(py_files)

    return {
        "blockers": blockers,
        "recommended_prework": prework,
        "safest_start_points": safest,
        "riskiest_modules": riskiest,
    }


def _all_py(repo_root: Path) -> list[Path]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    return [f for f in repo_root.rglob("*.py") if not any(p in f.parts for p in skip)]


def _has_critical_security(repo_root: Path) -> str | None:
    # Quick scan for committed secrets
    for f in repo_root.rglob(".env"):
        if f.is_file() and not f.name.startswith("."):
            return f"secret file committed: {f.name}"
    py_files = [f for f in repo_root.rglob("*.py") if "test" not in f.name.lower()]
    secret_pat = re.compile(r'api[_-]?key\s*[=:]\s*["\'][a-zA-Z0-9]{20,}["\']', re.IGNORECASE)
    for f in py_files:
        try:
            if secret_pat.search(f.read_text(errors="replace")):
                return f"hardcoded secret in {f.name}"
        except OSError:
            continue
    return None


def _has_circular_imports(files: list[Path]) -> bool:
    graph: dict[str, set[str]] = {}
    for f in files:
        try:
            tree = ast.parse(f.read_text(errors="replace"))
            mod = f.stem
            graph[mod] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    graph[mod].add(node.module.split(".")[-1])
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        graph[mod].add(a.name.split(".")[0])
        except (SyntaxError, OSError):
            continue
    for mod, deps in graph.items():
        for dep in deps:
            if dep in graph and mod in graph.get(dep, set()):
                return True
    return False


def _has_pytest_in_config(repo_root: Path) -> bool:
    ptoml = repo_root / "pyproject.toml"
    if ptoml.exists():
        return "pytest" in ptoml.read_text(errors="replace")
    return False


def _find_safest_modules(files: list[Path]) -> list[str]:
    """Small, isolated modules with few dependencies."""
    scored = []
    for f in files:
        if "test" in f.name.lower():
            continue
        try:
            content = f.read_text(errors="replace")
            lines = content.count("\n")
            deps = content.count("import ") + content.count("from ")
            score = lines + deps * 5
            scored.append((score, f.name))
        except OSError:
            continue
    scored.sort()
    return [name for _, name in scored[:3]]


def _find_riskiest_modules(files: list[Path]) -> list[str]:
    """Large files with high connectivity."""
    scored = []
    for f in files:
        if "test" in f.name.lower():
            continue
        try:
            content = f.read_text(errors="replace")
            lines = content.count("\n")
            deps = content.count("import ") + content.count("from ")
            score = lines + deps * 10
            scored.append((score, f.name))
        except OSError:
            continue
    scored.sort(reverse=True)
    return [name for _, name in scored[:3]]
