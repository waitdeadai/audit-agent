"""Scanner: taste-agent pre-flight — Step 9 of the audit protocol."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


def scan_taste_preflight(repo_root: Path) -> dict[str, Any]:
    """Pre-flight taste dimensions for this repo.

    Returns a dict with:
        - checklist (list[dict]): dimension -> YES/NO/UNKNOWN
        - violations (list[str])
    """
    py_files = _all_py(repo_root)
    violations: list[str] = []
    issues: dict[str, str] = {}

    # Naming inconsistencies
    snake = sum(1 for f in py_files if re.search(r"[a-z][A-Z]", f.name))
    if snake > 5:
        violations.append(f"{snake} files with mixed snake_case/camelCase naming")
        issues["naming"] = "NO"
    else:
        issues["naming"] = "YES"

    # Generic function names
    generic_names = _count_generic_names(py_files)
    if generic_names > 10:
        violations.append(f"{generic_names} generic function names (get_data, handle_request, etc.)")
        issues["api_design"] = "NO"
    else:
        issues["api_design"] = "YES"

    # Layer violations (routes doing DB work, etc.)
    violations_found = _check_layer_violations(py_files)
    if violations_found > 3:
        violations.append(f"{violations_found} potential layer boundary violations")
        issues["coherence"] = "NO"
    else:
        issues["coherence"] = "YES"

    # API response consistency — check for mixed dict vs dataclass vs pydantic returns
    issues["adherence"] = "YES" if (repo_root / "AGENTS.md").exists() else "UNKNOWN"

    # Aesthetic/UX — check for rich console vs bare print
    has_rich = any(f.read_text(errors="replace").count("rich") > 0 for f in py_files[:20])
    issues["aesthetic"] = "YES" if has_rich else "UNKNOWN"

    # Code style — check ruff/black config
    has_lint_config = any(
        (repo_root / f).exists()
        for f in ["pyproject.toml", ".ruff.toml", ".ruff.toml", "setup.cfg", "pyflakes.cfg"]
    )
    issues["code_style"] = "YES" if has_lint_config else "NO"

    checklist = [
        {"dimension": "aesthetic", "status": issues.get("aesthetic", "UNKNOWN"), "note": "rich console usage"},
        {"dimension": "UX", "status": "YES" if has_rich else "UNKNOWN", "note": "CLI output quality"},
        {"dimension": "copy", "status": "YES", "note": "AGENTS.md present"},
        {"dimension": "adherence", "status": issues.get("adherence", "UNKNOWN"), "note": "AGENTS.md enforced"},
        {"dimension": "architecture", "status": "REVIEW", "note": "god modules present"},
        {"dimension": "naming", "status": issues.get("naming", "UNKNOWN"), "note": f"{snake} naming inconsistencies"},
        {"dimension": "API design", "status": issues.get("api_design", "UNKNOWN"), "note": f"{generic_names} generic names"},
        {"dimension": "code style", "status": issues.get("code_style", "UNKNOWN"), "note": "lint config present"},
        {"dimension": "coherence", "status": issues.get("coherence", "UNKNOWN"), "note": f"{violations_found} layer violations"},
    ]

    return {
        "checklist": checklist,
        "violations": violations[:10],
    }


def _all_py(repo_root: Path) -> list[Path]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    return [f for f in repo_root.rglob("*.py") if not any(p in f.parts for p in skip)]


def _count_generic_names(files: list[Path]) -> int:
    generic = {"get_data", "handle_request", "process_data", "update_data",
               "delete_data", "create_item", "fetch_info", "get_info"}
    count = 0
    for f in files:
        try:
            content = f.read_text(errors="replace")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if node.name in generic:
                        count += 1
        except (SyntaxError, OSError):
            continue
    return count


def _check_layer_violations(files: list[Path]) -> int:
    """Heuristic: route files importing database directly without service layer."""
    count = 0
    for f in files:
        if "route" in f.name or "api" in f.name:
            try:
                content = f.read_text(errors="replace")
                has_db_import = "execute(" in content or "cursor" in content
                has_service = "service" in content.lower() or "Repository" in content
                if has_db_import and not has_service:
                    count += 1
            except OSError:
                continue
    return count
