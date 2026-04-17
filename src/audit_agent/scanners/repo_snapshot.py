"""Scanner: repository snapshot — collects high-level repo facts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def scan_repo_snapshot(repo_root: Path) -> dict[str, Any]:
    """Collect a high-level snapshot of the repository.

    Returns a dict with keys:
        - repo_name (str)
        - primary_language (str)
        - framework (str or None)
        - file_count (int)
        - line_count (int)
        - last_commit_hash (str)
        - last_commit_date (str)
        - package_manager (str or None)
        - entry_points (list[str])
        - test_framework (str or None)
        - has_ci (bool)
        - has_agents_md (bool)
        - has_claude_md (bool)
        - has_forgegod_config (bool)
    """
    import os

    name = repo_root.name

    # Primary language — most common extension by file count
    ext_counts: dict[str, int] = {}
    for root, _dirs, files in os.walk(repo_root):
        # Skip common non-source directories
        parts = Path(root).relative_to(repo_root).parts
        skip = {".git", ".forgegod", "__pycache__", "node_modules", ".venv", "venv",
                ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "dist", "build", ".eggs", "*.egg-info"}
        if any(p in skip for p in parts):
            continue
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in {".py", ".ts", ".tsx", ".js", ".jsx", ".go",
                       ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
                       ".cs", ".rb", ".php", ".swift", ".kt", ".scala"}:
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

    lang_map = {
        ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".js": "JavaScript", ".jsx": "JavaScript", ".go": "Go",
        ".rs": "Rust", ".java": "Java", ".c": "C", ".cpp": "C++",
        ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
        ".kt": "Kotlin",
    }
    primary_language = "Unknown"
    if ext_counts:
        top_ext = max(ext_counts, key=ext_counts.get)
        primary_language = lang_map.get(top_ext, top_ext.lstrip(".").upper())

    # Framework detection
    framework: str | None = None
    for pattern in (repo_root).rglob("*.toml"):
        if pattern.name == "pyproject.toml":
            content = pattern.read_text(errors="replace")
            if "fastapi" in content.lower():
                framework = "FastAPI"
            elif "django" in content.lower():
                framework = "Django"
            elif "flask" in content.lower():
                framework = "Flask"
            break
    if not framework:
        for pattern in (repo_root).rglob("package.json"):
            content = pattern.read_text(errors="replace")
            if "next" in content.lower():
                framework = "Next.js"
            elif "nuxt" in content.lower():
                framework = "Nuxt"
            elif "react" in content.lower():
                framework = "React"
            break

    # File count and line count
    file_count = 0
    line_count = 0
    skip_dirs = {".git", ".forgegod", "__pycache__", "node_modules", ".venv", "venv",
                 ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                 "dist", "build", ".eggs", "*.egg-info"}
    skip_exts = {".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".msi",
                 ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
                 ".mp3", ".mp4", ".wav", ".webm", ".pdf", ".doc", ".docx",
                 ".xls", ".xlsx", ".lock", ".sum", ".ttf", ".otf",
                 ".woff", ".woff2", ".zip", ".tar", ".gz"}

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        root_path = Path(root)
        rel = root_path.relative_to(repo_root)
        if any(p in skip_dirs for p in rel.parts):
            continue
        for f in files:
            if any(f.endswith(e) for e in skip_exts):
                continue
            file_count += 1
            try:
                content = root_path / f
                lines = content.read_text(errors="replace")
                line_count += lines.count("\n") + 1
            except (OSError, UnicodeDecodeError):
                pass

    # Git info
    last_commit_hash = ""
    last_commit_date = ""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%H|%cs"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|", 1)
            if len(parts) == 2:
                last_commit_hash, last_commit_date = parts
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Package manager
    package_manager: str | None = None
    if (repo_root / "pyproject.toml").exists():
        package_manager = "pip/pypi"
    elif (repo_root / "package.json").exists():
        package_manager = "npm/yarn/pnpm"
    elif (repo_root / "go.mod").exists():
        package_manager = "Go modules"
    elif (repo_root / "Cargo.toml").exists():
        package_manager = "Cargo"
    elif (repo_root / "requirements.txt").exists():
        package_manager = "pip"

    # Entry points
    entry_points: list[str] = []
    for ep in ["main.py", "cli.py", "server.py", "app.py", "__main__.py",
               "index.ts", "index.js", "main.ts", "main.js"]:
        if (repo_root / ep).exists():
            entry_points.append(ep)

    # Test framework
    test_framework: str | None = None
    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(errors="replace")
        if "[tool.pytest" in content or "[tool:pytest]" in content:
            test_framework = "pytest"
    if test_framework is None and (repo_root / "pytest.ini").exists():
        test_framework = "pytest"
    if not test_framework and (repo_root / "package.json").exists():
        content = (repo_root / "package.json").read_text(errors="replace")
        if "vitest" in content:
            test_framework = "Vitest"
        elif "jest" in content:
            test_framework = "Jest"

    # CI/CD
    has_ci = any(
        (repo_root / p).exists()
        for p in [".github/workflows", ".gitlab-ci.yml", "Jenkinsfile",
                  ".circleci", "azure-pipelines.yml"]
    )

    # Doc files
    has_agents_md = (repo_root / "AGENTS.md").exists()
    has_claude_md = (repo_root / "CLAUDE.md").exists()
    has_forgegod_config = (repo_root / ".forgegod" / "config.toml").exists()

    return {
        "repo_name": name,
        "primary_language": primary_language,
        "framework": framework,
        "file_count": file_count,
        "line_count": line_count,
        "last_commit_hash": last_commit_hash,
        "last_commit_date": last_commit_date,
        "package_manager": package_manager,
        "entry_points": entry_points,
        "test_framework": test_framework,
        "has_ci": has_ci,
        "has_agents_md": has_agents_md,
        "has_claude_md": has_claude_md,
        "has_forgegod_config": has_forgegod_config,
    }
