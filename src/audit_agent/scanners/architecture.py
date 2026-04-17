"""Scanner: architecture map — Step 3 of the audit protocol."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def scan_architecture(repo_root: Path) -> dict[str, Any]:
    """Identify structural patterns, god modules, circular imports, load-bearing modules.

    Returns a dict with keys:
        - structure_type (str): layered|domain|monolithic|modular|service-split
        - god_modules (list[dict])
        - circular_imports (list[dict])
        - top_imported_modules (list[dict])
        - ascii_diagram (str)
    """
    py_files = _all_py_files(repo_root)
    imports_graph = _build_import_graph(py_files, repo_root)
    structure_type = _detect_structure(imports_graph, py_files)
    god_modules = _find_god_modules(py_files)
    circular = _find_circular_imports(imports_graph)
    top_imported = _top_imported(imports_graph)
    diagram = _ascii_diagram(structure_type, top_imported[:5], god_modules)

    return {
        "structure_type": structure_type,
        "god_modules": god_modules,
        "circular_imports": circular,
        "top_imported_modules": top_imported,
        "ascii_diagram": diagram,
    }


def _all_py_files(repo_root: Path) -> list[Path]:
    files = []
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    for f in repo_root.rglob("*.py"):
        if not any(p in f.parts for p in skip):
            files.append(f)
    return files


def _build_import_graph(files: list[Path], repo_root: Path) -> dict[str, set[str]]:
    """Map each module to the set of modules it imports."""
    graph: dict[str, set[str]] = {}
    for f in files:
        try:
            content = f.read_text(errors="replace")
            tree = ast.parse(content)
            module_name = _module_name(f, repo_root)
            graph[module_name] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    graph[module_name].add(node.module.split(".")[0])
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        graph[module_name].add(alias.name.split(".")[0])
        except (SyntaxError, OSError):
            continue
    return graph


def _module_name(f: Path, repo_root: Path) -> str:
    try:
        rel_path = f.relative_to(repo_root)
    except ValueError:
        rel_path = f
    parts = list(rel_path.parts)
    for root in ["src", "lib", "packages"]:
        if root in parts:
            idx = parts.index(root)
            parts = parts[idx + 1:]
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    if not parts:
        return f.stem
    return ".".join(parts).replace(".py", "")


def _detect_structure(imports_graph: dict[str, set[str]], files: list[Path]) -> str:
    """Detect overall architecture pattern."""
    has_api = any("route" in str(f) or "router" in f.name for f in files[:20])
    has_service = any("service" in str(f) for f in files)
    has_repo = any("repository" in str(f) or "repo" in f.name for f in files)
    has_domain = any("domain" in str(f) or "entities" in str(f) for f in files)

    if has_api and has_service and has_repo:
        return "layered"
    elif has_domain:
        return "domain-driven"
    elif any("microservice" in str(f) or "grpc" in str(f) for f in files):
        return "service-split"
    elif len(files) < 20:
        return "monolithic"
    else:
        return "modular-monolith"


def _find_god_modules(files: list[Path]) -> list[dict[str, Any]]:
    """Files >500 lines or >25 functions are god module candidates."""
    god_modules = []
    for f in files:
        try:
            content = f.read_text(errors="replace")
            size = len(content)
            tree = ast.parse(content)
            func_count = sum(1 for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            if size > 50000 or func_count > 25:
                god_modules.append({
                    "file": str(f.relative_to(f.parents[len(f.parts) - 1]) if f.parts else str(f)),
                    "lines": size,
                    "functions": func_count,
                    "risk": "🔴 HIGH" if size > 80000 else "🟡 MEDIUM",
                })
        except (SyntaxError, OSError):
            continue
    return sorted(god_modules, key=lambda x: -x["lines"])[:10]


def _find_circular_imports(graph: dict[str, set[str]]) -> list[dict[str, str]]:
    """Find pairs of modules that import each other."""
    circular = []
    for mod, deps in graph.items():
        for dep in deps:
            if dep in graph and mod in graph.get(dep, set()):
                pair = sorted([mod, dep])
                circular.append({"modules": pair})
    # Deduplicate
    seen = set()
    result = []
    for c in circular:
        key = tuple(c["modules"])
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def _top_imported(graph: dict[str, set[str]]) -> list[dict[str, Any]]:
    """Count how many modules import each module — that's its fan-in."""
    fan_in: dict[str, int] = {}
    for mod, deps in graph.items():
        for dep in deps:
            fan_in[dep] = fan_in.get(dep, 0) + 1
    return sorted(
        [{"module": m, "import_count": c} for m, c in fan_in.items()],
        key=lambda x: -x["import_count"]
    )[:10]


def _ascii_diagram(structure: str, top: list[dict], gods: list[dict]) -> str:
    lines = [
        f"Architecture: {structure}",
        "",
        "Top-imported modules (load-bearing walls):",
    ]
    for item in top:
        lines.append(f"  {item['import_count']:3d}x  {item['module']}")
    if gods:
        lines += ["", "God modules (HIGH risk — avoid changing these):"]
        for g in gods[:5]:
            lines.append(f"  {g['risk']}  {g.get('file', 'unknown')} ({g['lines']}L, {g['functions']} fns)")
    return "\n".join(lines)
