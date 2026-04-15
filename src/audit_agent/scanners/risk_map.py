"""Scanner: change risk map — Step 8 of the audit protocol."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def scan_risk_map(repo_root: Path) -> dict[str, Any]:
    """Build risk table for all major modules.

    Returns a dict with:
        - risks (list[dict]): Module | Risk | Why | Dependencies affected
    """
    py_files = _all_modules(repo_root)
    graph = _import_graph(py_files)
    test_coverage = _test_coverage_map(repo_root)

    risks: list[dict[str, str]] = []
    for f in py_files:
        module = _module_name(f)
        deps = len(graph.get(module, []))
        fan_in = sum(1 for v in graph.values() if module in v)
        test_count = test_coverage.get(module, 0)
        size = _file_size(f)

        if fan_in > 5 and test_count == 0:
            risk = "🔴 HIGH"
            why = f"High fan-in ({fan_in}), no tests, {size}L"
        elif fan_in > 3 and test_count < 2:
            risk = "🟡 MEDIUM"
            why = f"Moderate fan-in ({fan_in}), few tests ({test_count})"
        elif deps > 10:
            risk = "🟡 MEDIUM"
            why = f"Many dependencies ({deps}), ripple risk"
        elif test_count >= 3:
            risk = "🟢 LOW"
            why = f"Well-tested ({test_count} tests), low fan-in ({fan_in})"
        else:
            risk = "🟢 LOW"
            why = f"Low coupling, {size}L"

        risks.append({
            "module": module or str(f.name),
            "risk": risk,
            "why": why,
            "fan_in": fan_in,
            "fan_out": deps,
            "tests": test_count,
            "lines": size,
        })

    risks.sort(key=lambda x: (
        0 if "🔴" in x["risk"] else 1 if "🟡" in x["risk"] else 2,
        -x["fan_in"],
    ))
    return {"risks": risks[:30]}


def _all_modules(repo_root: Path) -> list[Path]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    return [f for f in repo_root.rglob("*.py")
            if not any(p in f.parts for p in skip)]


def _import_graph(files: list[Path]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for f in files:
        try:
            content = f.read_text(errors="replace")
            tree = ast.parse(content)
            mod = _module_name(f)
            graph[mod] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    graph[mod].add(node.module.split(".")[0])
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        graph[mod].add(a.name.split(".")[0])
        except (SyntaxError, OSError):
            continue
    return graph


def _module_name(f: Path) -> str:
    parts = list(f.parts)
    for root in ["src", "lib"]:
        if root in parts:
            idx = parts.index(root)
            parts = parts[idx + 1:]
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    return ".".join(parts).replace(".py", "")


def _test_coverage_map(repo_root: Path) -> dict[str, int]:
    """Count test files that reference each module."""
    coverage: dict[str, int] = {}
    test_files = list(repo_root.rglob("*test*.py"))
    for tf in test_files:
        try:
            content = tf.read_text(errors="replace")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    name = ""
                    if isinstance(node, ast.ImportFrom) and node.module:
                        name = node.module.split(".")[-1]
                    else:
                        for a in node.names:
                            name = a.name.split(".")[-1]
                            break
                    if name:
                        coverage[name] = coverage.get(name, 0) + 1
        except (SyntaxError, OSError):
            continue
    return coverage


def _file_size(f: Path) -> int:
    try:
        return f.read_text(errors="replace").count("\n")
    except OSError:
        return 0
