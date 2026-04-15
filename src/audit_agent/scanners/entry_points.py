"""Scanner: entry points map — Step 2 of the audit protocol."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def scan_entry_points(repo_root: Path) -> dict[str, Any]:
    """Identify how the code starts and flows.

    Returns a dict with keys:
        - entry_points (list[dict]): each with name, type, description, touches
        - cli_commands (list[dict])
        - api_routes (list[dict])
        - background_loops (list[dict])
        - import_roots (list[str])
    """
    import re

    entry_points: list[dict[str, str]] = []
    cli_commands: list[dict[str, str]] = []
    api_routes: list[dict[str, str]] = []
    background_loops: list[dict[str, str]] = []
    import_roots: list[str] = []

    # Find CLI entry points
    cli_candidates = [
        "cli.py", "main.py", "app.py", "__main__.py",
        "server.py", "cmd.py", "console.py",
    ]
    for ep in cli_candidates:
        for f in repo_root.rglob(ep):
            if any(p in f.parts for p in {".git", "node_modules", "__pycache__"}):
                continue
            content = f.read_text(errors="replace")
            ep_type = _detect_ep_type(content, f.name)
            rel = f.relative_to(repo_root)
            entry_points.append({
                "name": str(rel),
                "type": ep_type,
                "description": f"Entry point: {rel}",
                "touches": _guess_touches(content),
            })
            break

    # Detect CLI commands (typer, click, argparse)
    for py_file in repo_root.rglob("*.py"):
        if any(p in py_file.parts for p in {".git", "node_modules", "__pycache__"}):
            continue
        try:
            content = py_file.read_text(errors="replace")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id == "command":
                        cli_commands.append({"file": str(py_file.relative_to(repo_root)), "type": "click"})
                    elif isinstance(func, ast.Attribute):
                        if func.attr in ("add", "command", "Typer"):
                            cli_commands.append({"file": str(py_file.relative_to(repo_root)), "type": "typer"})
        except (SyntaxError, OSError):
            continue

    # Detect API routes (FastAPI, Flask, FastAPI app routes)
    route_pattern = re.compile(r"(app|router|api)\.(get|post|put|delete|patch)\(", re.IGNORECASE)
    for py_file in repo_root.rglob("*.py"):
        if any(p in py_file.parts for p in {".git", "node_modules", "__pycache__"}):
            continue
        try:
            content = py_file.read_text(errors="replace")
            if route_pattern.search(content):
                api_routes.append({"file": str(py_file.relative_to(repo_root)), "type": "web"})
        except OSError:
            continue

    # Detect background loops / schedulers
    loop_patterns = ["while True:", "schedule.every", "asyncio.gather", "loop.run_forever"]
    for py_file in repo_root.rglob("*.py"):
        if any(p in py_file.parts for p in {".git", "node_modules", "__pycache__"}):
            continue
        try:
            content = py_file.read_text(errors="replace")
            for pat in loop_patterns:
                if pat in content:
                    background_loops.append({
                        "file": str(py_file.relative_to(repo_root)),
                        "pattern": pat,
                    })
                    break
        except OSError:
            continue

    # Import graph roots — top-level packages with many internal imports
    root_modules: set[str] = set()
    for py_file in repo_root.rglob("*.py"):
        if any(p in py_file.parts for p in {".git", "node_modules", "__pycache__"}):
            continue
        try:
            content = py_file.read_text(errors="replace")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        root_modules.add(node.module.split(".")[0])
        except (SyntaxError, OSError):
            continue
    import_roots = sorted(root_modules)

    return {
        "entry_points": entry_points,
        "cli_commands": cli_commands,
        "api_routes": api_routes,
        "background_loops": background_loops,
        "import_roots": import_roots,
    }


def _detect_ep_type(content: str, filename: str) -> str:
    if "typer" in content or "app = typer.Typer" in content:
        return "typer-cli"
    if "click" in content or "@click" in content:
        return "click-cli"
    if "argparse" in content:
        return "argparse-cli"
    if "fastapi" in content or "Flask" in content:
        return "web-server"
    if "__main__" in content:
        return "script"
    return "unknown"


def _guess_touches(content: str) -> str:
    """Guess what systems this entry point touches."""
    touches = []
    if "database" in content.lower() or "db" in content.lower():
        touches.append("db")
    if "http" in content.lower() or "api" in content.lower():
        touches.append("network")
    if "file" in content.lower() or "path" in content.lower():
        touches.append("filesystem")
    if "git" in content.lower():
        touches.append("git")
    return ", ".join(touches) if touches else "unknown"
