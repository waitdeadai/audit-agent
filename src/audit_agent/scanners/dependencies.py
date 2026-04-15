"""Scanner: dependency surface — Step 4 of the audit protocol."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def scan_dependencies(repo_root: Path) -> dict[str, Any]:
    """Scan external dependencies from package managers."""
    deps = _scan_external_deps(repo_root)
    return {"external_dependencies": deps}


def scan_internal_deps(repo_root: Path) -> dict[str, Any]:
    """Scan internal dependency paths: longest chains, complexity sinks, dead code."""
    py_files = _all_py_files(repo_root)
    graph = _build_import_graph(py_files)
    chains = _longest_import_chains(graph)
    sinks = _find_complexity_sinks(graph)
    dead = _find_dead_code(py_files, graph)
    return {
        "longest_import_chains": chains,
        "complexity_sinks": sinks,
        "dead_code_candidates": dead,
    }


def _all_py_files(repo_root: Path) -> list[Path]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    return [f for f in repo_root.rglob("*.py") if not any(p in f.parts for p in skip)]


def _scan_external_deps(repo_root: Path) -> list[dict[str, str]]:
    deps = []
    seen = set()

    # pyproject.toml
    ptoml = repo_root / "pyproject.toml"
    if ptoml.exists():
        for dep in _parse_pytoml_deps(ptoml.read_text()):
            if dep["name"] not in seen:
                seen.add(dep["name"])
                deps.append(dep)

    # requirements*.txt
    for req in sorted(repo_root.rglob("requirements*.txt")):
        for dep in _parse_requirements(req.read_text()):
            if dep["name"] not in seen:
                seen.add(dep["name"])
                deps.append(dep)

    # package.json
    pkg = repo_root / "package.json"
    if pkg.exists():
        for dep in _parse_package_json_deps(pkg.read_text()):
            if dep["name"] not in seen:
                seen.add(dep["name"])
                deps.append(dep)

    return deps


def _parse_pytoml_deps(content: str) -> list[dict[str, str]]:
    deps = []
    lines = content.splitlines()
    in_deps = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("dependencies"):
            in_deps = True
            continue
        if in_deps and line.startswith((" ", "\t")):
            import re
            m = re.match(r'"([^"]+)"\s*=\s*"([^"]+)"', stripped)
            if m:
                deps.append({"name": m.group(1), "version": m.group(2), "type": "runtime", "source": "pyproject.toml"})
            elif stripped.startswith("["):
                in_deps = False
    return deps


def _parse_requirements(content: str) -> list[dict[str, str]]:
    deps = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        import re
        m = re.match(r'^([a-zA-Z0-9_-]+)([!=<>~]+.+)?', line)
        if m:
            deps.append({
                "name": m.group(1),
                "version": m.group(2) or "any",
                "type": "runtime",
                "source": "requirements.txt",
            })
    return deps


def _parse_package_json_deps(content: str) -> list[dict[str, str]]:
    import json
    deps = []
    try:
        data = json.loads(content)
        for section in ["dependencies", "devDependencies"]:
            for name, version in data.get(section, {}).items():
                deps.append({
                    "name": name,
                    "version": str(version),
                    "type": "dev" if section == "devDependencies" else "runtime",
                    "source": "package.json",
                })
    except (json.JSONDecodeError, OSError):
        pass
    return deps


def _build_import_graph(files: list[Path]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for f in files:
        try:
            content = f.read_text(errors="replace")
            tree = ast.parse(content)
            module_name = _module_name(f)
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


def _module_name(f: Path) -> str:
    parts = list(f.parts)
    for root in ["src", "lib"]:
        if root in parts:
            idx = parts.index(root)
            parts = parts[idx + 1:]
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    return ".".join(parts).replace(".py", "")


def _longest_import_chains(graph: dict[str, set[str]], max_depth: int = 4) -> list[list[str]]:
    chains = []

    def dfs(node: str, path: list[str], visited: set[str]):
        if len(path) > max_depth:
            chains.append(path[:])
        for dep in graph.get(node, set()):
            if dep not in visited:
                visited.add(dep)
                dfs(dep, path + [dep], visited)
                visited.remove(dep)

    for start in list(graph.keys())[:20]:
        dfs(start, [start], {start})
    chains.sort(key=len, reverse=True)
    return chains[:5]


def _find_complexity_sinks(graph: dict[str, set[str]]) -> list[dict[str, Any]]:
    sinks = []
    for module, deps in graph.items():
        dep_count = len(deps)
        if dep_count > 5:
            sinks.append({"module": module, "imports_count": dep_count})
    return sorted(sinks, key=lambda x: -x["imports_count"])


def _find_dead_code(py_files: list[Path], graph: dict[str, set[str]]) -> list[str]:
    # Modules no other module imports (excluding __main__ and test files)
    all_importers: set[str] = set()
    for deps in graph.values():
        all_importers.update(deps)
    dead = []
    for module in graph:
        if module not in all_importers and not module.startswith("test_") and "__main__" not in module:
            dead.append(module)
    return dead
