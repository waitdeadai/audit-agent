"""Scanner: health indicators — Step 5 of the audit protocol."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


def scan_health(repo_root: Path) -> dict[str, Any]:
    """Scan for health indicators: TODOs, stubs, long functions, hardcoded config, debug prints.

    Returns a dict with:
        - todo_count, fixme_count, hack_count, xxx_count
        - placeholder_count
        - long_functions (list)
        - long_files (list)
        - hardcoded_config (list)
        - debug_prints (list)
    """
    py_files = [f for f in repo_root.rglob("*.py")
                if not any(p in f.parts for p in {".git", "node_modules", "__pycache__", ".venv", "venv"})]

    todo_count = fixme_count = hack_count = xxx_count = 0
    placeholder_items: list[dict] = []
    long_functions: list[dict] = []
    long_files: list[dict] = []
    hardcoded_items: list[dict] = []
    debug_prints: list[dict] = []

    todo_pattern = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)", re.IGNORECASE)
    placeholder_patterns = [
        re.compile(r"^\s*pass\s*$"),
        re.compile(r"raise\s+NotImplementedError"),
    ]
    secret_re = r"(api[_-]?key|password|token|secret|credential)"
    hardcoded_pattern = re.compile(
        rf'{secret_re}\s*[=:]\s*["\'][^"\']{{4,}}["\']', re.IGNORECASE
    )
    debug_print = re.compile(r"\bprint\s*\(", re.MULTILINE)

    for f in py_files:
        try:
            content = f.read_text(errors="replace")
        except OSError:
            continue

        # Count comments
        for m in todo_pattern.finditer(content):
            tag = m.group(1).upper()
            if tag == "TODO":
                todo_count += 1
            elif tag == "FIXME":
                fixme_count += 1
            elif tag == "HACK":
                hack_count += 1
            elif tag == "XXX":
                xxx_count += 1

        # Placeholders
        for pat in placeholder_patterns:
            for m in pat.finditer(content):
                placeholder_items.append({"file": str(f.relative_to(repo_root)), "pattern": m.group()})

        # Hardcoded config
        for m in hardcoded_pattern.finditer(content):
            if "test" not in f.name.lower():
                hardcoded_items.append({"file": str(f.relative_to(repo_root)), "match": m.group()[:60]})

        # Debug prints (not in tests)
        if "test" not in f.name.lower():
            for m in debug_print.finditer(content):
                debug_prints.append({"file": str(f.relative_to(repo_root)), "line": content[:m.start()].count("\n") + 1})

        # Long functions via AST
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end_line = node.end_lineno or 0
                    start_line = node.lineno or 0
                    if end_line - start_line > 60:
                        long_functions.append({
                            "file": str(f.relative_to(repo_root)),
                            "function": node.name,
                            "lines": end_line - start_line,
                        })
        except (SyntaxError, OSError):
            pass

        # Long files
        line_count = content.count("\n") + 1
        if line_count > 500:
            long_files.append({"file": str(f.relative_to(repo_root)), "lines": line_count})

    return {
        "todo_count": todo_count,
        "fixme_count": fixme_count,
        "hack_count": hack_count,
        "xxx_count": xxx_count,
        "placeholder_count": len(placeholder_items),
        "placeholder_items": placeholder_items[:10],
        "long_functions": sorted(long_functions, key=lambda x: -x["lines"])[:10],
        "long_files": sorted(long_files, key=lambda x: -x["lines"])[:10],
        "hardcoded_config": hardcoded_items[:10],
        "debug_prints": debug_prints[:20],
    }
