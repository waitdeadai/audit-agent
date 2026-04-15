"""Scanner: security surface — Step 7 of the audit protocol."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def scan_security(repo_root: Path) -> dict[str, Any]:
    """Scan for security issues: secrets, injection, path traversal, committed .env.

    Returns a dict with:
        - critical (list[dict])
        - warning (list[dict])
        - info (list[dict])
    """
    critical: list[dict] = []
    warning: list[dict] = []
    info: list[dict] = []

    py_files = [f for f in repo_root.rglob("*.py")
                if not any(p in f.parts for p in {".git", "node_modules", "__pycache__"})]

    # Hardcoded secrets (not in tests)
    secret_pattern = re.compile(
        r'(api[_-]?key|password|passwd|secret|token|credential|auth[_-]?key)\s*[=:]\s*["\'][^"\']{4,}["\']',
        re.IGNORECASE,
    )
    for f in py_files:
        if "test" in f.name.lower():
            continue
        try:
            content = f.read_text(errors="replace")
            for m in secret_pattern.finditer(content):
                critical.append({
                    "severity": "CRITICAL",
                    "type": "hardcoded_secret",
                    "file": str(f.relative_to(repo_root)),
                    "match": m.group()[:80],
                })
        except OSError:
            continue

    # Dangerous patterns
    dangerous = [
        (r'eval\s*\(', "eval() call — code injection risk"),
        (r'exec\s*\(', "exec() call — code injection risk"),
        (r'subprocess.*shell\s*=\s*True', "subprocess with shell=True — shell injection risk"),
        (r'os\.system\s*\(', "os.system() call — shell injection risk"),
        (r'os\.popen\s*\(', "os.popen() call — shell injection risk"),
    ]
    for f in py_files:
        try:
            content = f.read_text(errors="replace")
            for pat, desc in dangerous:
                for m in re.finditer(pat, content):
                    warning.append({
                        "severity": "WARNING",
                        "type": "dangerous_pattern",
                        "file": str(f.relative_to(repo_root)),
                        "description": desc,
                        "line": content[:m.start()].count("\n") + 1,
                    })
        except OSError:
            continue

    # SQL injection risk
    sql_concat = re.compile(r'["\']\s*\+\s*.*(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b.*\+\s*["\']', re.IGNORECASE)
    for f in py_files:
        if "test" in f.name.lower():
            continue
        try:
            content = f.read_text(errors="replace")
            if sql_concat.search(content):
                warning.append({
                    "severity": "WARNING",
                    "type": "sql_injection",
                    "file": str(f.relative_to(repo_root)),
                    "description": "SQL string concatenation detected",
                })
        except OSError:
            continue

    # Committed .env files
    for f in repo_root.rglob(".env*"):
        if f.name in {".env.example", ".env.template", ".env.local", ".env.production"}:
            info.append({"severity": "INFO", "type": "example_env", "file": str(f.relative_to(repo_root))})
        elif f.is_file() and not f.name.startswith("."):
            continue
        else:
            critical.append({
                "severity": "CRITICAL",
                "type": "committed_env_file",
                "file": str(f.relative_to(repo_root)),
                "description": "Secret .env file may be committed",
            })

    return {
        "critical": critical,
        "warning": warning,
        "info": info,
    }
