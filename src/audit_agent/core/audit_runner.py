"""Audit runner — orchestrates the 11-step audit protocol.

The runner:
1. Loads the audit-agent system prompt from PROMPT.md
2. Builds a user prompt with repo root + file tree
3. Calls the LLM via OpenAI-compatible API
4. Parses the AUDIT.md output and extracts the JSON block
5. Writes .forgegod/AUDIT.md
6. Returns AuditResult
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from .audit_config import AuditConfig
from .audit_result import AuditResult

logger = logging.getLogger("audit_agent.runner")

# ── PROMPT.md loading ────────────────────────────────────────────────────────

_PROMPT_CACHE: str | None = None


def _load_prompt() -> str:
    """Load the system prompt from PROMPT.md.

    Tries in order:
    1. Package resource (pkgutil) — for installed package
    2. Relative to this file's grandparent — for development checkout
    3. ~/.forgegod/skills/audit-agent/PROMPT.md
    4. .forgegod/skills/audit-agent/PROMPT.md relative to cwd
    """
    global _PROMPT_CACHE
    if _PROMPT_CACHE:
        return _PROMPT_CACHE

    candidates: list[Path] = []

    # 1. Package resource (installed package)
    try:

        pkg_path = Path(__file__).parent.parent  # core/ -> src/audit_agent/
        prompt_file = pkg_path / "PROMPT.md"
        if prompt_file.is_file():
            candidates.append(prompt_file)
    except Exception:
        pass

    # 2. Development checkout: audit-agent/src/audit_agent/PROMPT.md
    dev_path = Path(__file__).resolve().parent.parent.parent / "PROMPT.md"
    if dev_path.is_file():
        candidates.append(dev_path)

    # 3. Skill path: ~/.forgegod/skills/audit-agent/PROMPT.md
    home = Path.home()
    skill_path = home / ".forgegod" / "skills" / "audit-agent" / "PROMPT.md"
    if skill_path.is_file():
        candidates.append(skill_path)

    # 4. CWD relative: .forgegod/skills/audit-agent/PROMPT.md
    cwd_skill = Path.cwd() / ".forgegod" / "skills" / "audit-agent" / "PROMPT.md"
    if cwd_skill.is_file():
        candidates.append(cwd_skill)

    for candidate in candidates:
        try:
            content = candidate.read_text(encoding="utf-8")
            _PROMPT_CACHE = content
            logger.debug("Loaded PROMPT.md from %s", candidate)
            return content
        except OSError as e:
            logger.debug("Failed to read %s: %s", candidate, e)

    raise FileNotFoundError(
        "PROMPT.md not found. Searched: " +
        ", ".join(str(p) for p in candidates)
    )


# ── File tree building ────────────────────────────────────────────────────────

_MAX_TREE_FILES = 2000
_MAX_TREE_DEPTH = 20


def _build_file_tree(repo_root: Path) -> str:
    """Build a compact file tree string for the user prompt.

    Walks repo_root up to _MAX_TREE_DEPTH deep, caps at _MAX_TREE_FILES entries.
    Skips common non-audit targets (node_modules, .git, __pycache__, etc.).
    """
    skip_dirs = {
        ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
        "node_modules", ".venv", "venv", ".tox", ".direnv",
        ".eggs", "*.egg-info", ".tox", ".hypothesis",
        "dist", "build", ".wheel", ".npm", ".yarn",
        ".next", ".nuxt", ".output",
    }

    skip_extensions = {
        ".pyc", ".pyo", ".so", ".dll", ".dylib", ".bin",
        ".exe", ".msi", ".deb", ".rpm", ".snap",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
        ".mp3", ".mp4", ".wav", ".webm", ".mkv",
        ".zip", ".tar", ".gz", ".rar", ".7z",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".ttf", ".otf", ".woff", ".woff2",
        ".lock", ".sum",
    }

    lines: list[str] = []
    count = 0

    for root, dirs, files in os.walk(repo_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(repo_root)

        # Prune skipped directories in-place to prevent descending
        dirs[:] = [
            d for d in dirs
            if d not in skip_dirs and not any(
                rel_root.match(pat) for pat in skip_dirs
            )
        ]

        # Stop if too deep
        if len(rel_root.parts) > _MAX_TREE_DEPTH:
            dirs.clear()
            continue

        for file in sorted(files):
            if count >= _MAX_TREE_FILES:
                break

            ext = Path(file).suffix.lower()
            if ext in skip_extensions:
                continue

            line = str(rel_root / file)
            lines.append(line)
            count += 1

        if count >= _MAX_TREE_FILES:
            break

    if not lines:
        return "(empty repository)"

    tree = "\n".join(sorted(lines))
    if count >= _MAX_TREE_FILES:
        tree += f"\n... ({count} files shown, repo has more)"
    return tree


# ── Key files to read ────────────────────────────────────────────────────────

_KEY_FILES = [
    "README.md", "README.es.md", "README.es-ES.md",
    "pyproject.toml", "setup.py", "setup.cfg", "package.json",
    "Cargo.toml", "go.mod", "Gopkg.toml",
    "AGENTS.md", "CLAUDE.md", "CLAUDE.md",
    "taste.md", "effort.md",
    ".forgegod/config.toml", ".forgegod/skills/audit-agent/SKILL.md",
    "main.py", "cli.py", "server.py", "index.ts", "index.js",
    "app.py", "__main__.py",
]


def _read_key_files(repo_root: Path) -> str:
    """Read contents of key files for the audit prompt."""
    parts: list[str] = []
    for pattern in _KEY_FILES:
        # Try exact match first
        f = repo_root / pattern
        if f.is_file():
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                # Truncate very large files
                if len(content) > 5000:
                    content = content[:5000] + "\n... [truncated]"
                parts.append(f"\n=== {f.name} ===\n{content}")
            except OSError:
                pass
            continue

        # Try glob for files like README.*.md
        if "*" in pattern:
            import glob
            for match in glob.glob(str(repo_root / pattern)):
                f = Path(match)
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if len(content) > 5000:
                        content = content[:5000] + "\n... [truncated]"
                    parts.append(f"\n=== {f.name} ===\n{content}")
                except OSError:
                    pass

    return "".join(parts) if parts else ""


# ── LLM calling ──────────────────────────────────────────────────────────────

_MINIMAX_BASE_URL = "https://api.minimax.io/v1"
_AZURE_BASE_URL_ENV = "AZURE_OPENAI_BASE_URL"
_AZURE_API_KEY_ENV = "AZURE_OPENAI_API_KEY"
_MINIMAX_API_KEY_ENV = "MINIMAX_API_KEY"


async def _call_openai_compatible(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    azure_api_version: str | None = None,
    timeout: float = 120.0,
) -> str:
    """Call an OpenAI-compatible endpoint.

    Handles: MiniMax, Azure OpenAI, any OpenAI-compatible server.
    """
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
    }

    # Azure uses api-key header and has versioned base URLs
    if "azure" in base_url.lower() or azure_api_version:
        headers["api-key"] = api_key
        url = f"{base_url.rstrip('/')}/chat/completions?api-version={azure_api_version or '2024-02-01'}"
    else:
        url = f"{base_url.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Connection error calling {url}: {e}.\n"
                "Check that the API endpoint is reachable and the API key is correct."
            ) from e

        if resp.status_code == 401:
            raise RuntimeError(
                f"Authentication error (401) calling {url}.\n"
                "Verify your API key is valid."
            )
        if resp.status_code == 403:
            raise RuntimeError(
                f"Forbidden (403) calling {url}.\n"
                "Check that your API key has permission for this model."
            )
        if resp.status_code == 429:
            raise RuntimeError(
                f"Rate limited (429) calling {url}.\n"
                "Wait before retrying or increase rate limit."
            )
        if resp.status_code >= 500:
            raise RuntimeError(
                f"Server error ({resp.status_code}) from {url}.\n"
                "The provider is experiencing issues. Try again shortly."
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Unexpected response {resp.status_code} from {url}: {resp.text[:500]}"
            )

        data = resp.json()
        content = data.get("choices", [{}])
        if isinstance(content, list) and content:
            message = content[0].get("message", {})
            text = message.get("content", "")
            if text:
                return text

        raise RuntimeError(f"No content in response from {url}: {data}")


def _resolve_api_key_and_url(
    config: AuditConfig,
) -> tuple[str, str]:
    """Resolve API key and base URL from config + environment.

    Returns (api_key, base_url).
    """
    # Explicit config wins
    if config.minimax_api_key:
        return config.minimax_api_key, config.minimax_base_url
    if config.azure_api_key and config.azure_base_url:
        return config.azure_api_key, config.azure_base_url

    # Azure env vars
    azure_key = os.environ.get(_AZURE_API_KEY_ENV, "") or os.environ.get("AZURE_OPENAI_KEY", "")
    azure_url = os.environ.get(_AZURE_BASE_URL_ENV, "") or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    if azure_key and azure_url:
        return azure_key, azure_url

    # MiniMax / OpenAI env var
    minimax_key = os.environ.get(_MINIMAX_API_KEY_ENV, "") or os.environ.get("OPENAI_API_KEY", "")
    if minimax_key:
        base_url = config.minimax_base_url or _MINIMAX_BASE_URL
        return minimax_key, base_url

    raise RuntimeError(
        "No API key found. Set one of:\n"
        "  MINIMAX_API_KEY  — for MiniMax (default, model minimax/minimax-m2.7-highspeed)\n"
        "  AZURE_OPENAI_API_KEY — for Azure OpenAI\n"
        "  OPENAI_API_KEY  — for generic OpenAI-compatible\n"
        "Or pass minimax_api_key=... in AuditConfig."
    )


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    config: AuditConfig,
) -> str:
    """Call the configured LLM (OpenAI-compatible).

    Tries each model spec in config.model_specs() until one succeeds.
    """
    if config.verbose:
        logger.info("Calling LLM with model=%s", config.model)

    api_key, base_url = _resolve_api_key_and_url(config)

    # Determine if this is Azure
    is_azure = bool(config.azure_api_key and config.azure_base_url) or (
        "azure" in base_url.lower()
    )

    errors: list[str] = []

    for provider, model in config.model_specs():
        try:
            if config.verbose:
                logger.info("Trying provider=%s model=%s", provider, model)

            text = await _call_openai_compatible(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                top_p=config.top_p,
                azure_api_version=config.azure_api_version if is_azure else None,
            )
            return text

        except Exception as e:
            err_msg = f"{provider}/{model}: {e}"
            errors.append(err_msg)
            if config.verbose:
                logger.warning("Model %s/%s failed: %s", provider, model, e)
            continue

    raise RuntimeError(
        "All models failed:\n" + "\n".join(errors)
    )


# ── Output parsing ──────────────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(
    r"```json\s*\n(.*?)\n```",
    re.DOTALL,
)
_JSON_BLOCK_RE2 = re.compile(
    r"\{[^{}]*\"audit_agent\"[^{}]*\}",
    re.DOTALL,
)


def _extract_json_block(text: str) -> dict[str, Any]:
    """Extract and parse the JSON block from LLM output."""
    # Try ```json ... ``` block first
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON block: %s", e)

    # Try finding any JSON with "audit_agent" key
    m = _JSON_BLOCK_RE2.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON block (fallback): %s", e)

    # Last resort: try to find {...} containing audit_agent
    start = text.find('{"audit_agent"')
    if start == -1:
        start = text.find('"audit_agent"')
    if start != -1:
        # Walk forward to find matching close brace
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        pass
                    break

    logger.warning("No parseable JSON block found in LLM output")
    return {}


def _parse_markdown_sections(content: str) -> dict[str, str]:
    """Split LLM markdown output into sections.

    Sections are delimited by lines starting with ##.
    Returns {section_name: section_content}.
    """
    sections: dict[str, str] = {}
    current_header = ""
    current_body: list[str] = []

    for line in content.splitlines(keepends=True):
        if line.startswith("## "):
            if current_header:
                sections[current_header] = "".join(current_body).strip()
            current_header = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)

    if current_header:
        sections[current_header] = "".join(current_body).strip()

    return sections


# ── AuditResult building ────────────────────────────────────────────────────

def _build_result(
    content: str,
    json_block: dict[str, Any],
    config: AuditConfig,
) -> AuditResult:
    """Build an AuditResult from LLM output + parsed JSON block."""
    agent_block = json_block.get("audit_agent", {})

    # Detect blockers: CRITICAL security issues in markdown content
    blockers: list[str] = list(agent_block.get("blockers", []))
    if "CRITICAL" in content:
        # Extract CRITICAL lines
        for line in content.splitlines():
            if "CRITICAL" in line.upper():
                stripped = line.strip()
                if stripped and stripped not in blockers:
                    blockers.append(stripped[:200])

    # high_risk_modules
    high_risk: list[str] = list(agent_block.get("high_risk_modules", []))

    # recommended_start_points
    start_pts: list[str] = list(agent_block.get("recommended_start_points", []))

    # effort_level
    effort = agent_block.get("effort_level", "thorough")

    # taste_pre_flight_failures
    taste_fails: list[str] = list(agent_block.get("taste_pre_flight_failures", []))

    # ready_to_plan
    ready = bool(agent_block.get("ready_to_plan", True))
    # Downgrade to False if CRITICAL blockers found
    if any("CRITICAL" in b.upper() for b in blockers):
        ready = False

    # repo name
    repo_name = agent_block.get("repo", "")
    if not repo_name:
        repo_name = config.repo_root.name

    return AuditResult(
        version=agent_block.get("version", "1.0"),
        timestamp=agent_block.get("timestamp", ""),
        repo=repo_name,
        repo_root=config.repo_root,
        output_path=config.output_path,
        blockers=blockers,
        high_risk_modules=high_risk,
        recommended_start_points=start_pts,
        effort_level=effort,
        taste_pre_flight_failures=taste_fails,
        ready_to_plan=ready,
        markdown_content=content,
    )


# ── Main runner ──────────────────────────────────────────────────────────────

_USER_PROMPT_TEMPLATE = """Audit this repository. Produce AUDIT.md following your full 11-step protocol.

Repository root: {repo_root}

Available file tree:
{file_tree}

Key files to read first (in order):
1. README.md or README.es.md
2. pyproject.toml / package.json / Cargo.toml (whichever applies)
3. AGENTS.md / CLAUDE.md (if present)
4. taste.md / effort.md (if present)
5. .forgegod/config.toml (if present)
6. Entry point file(s) identified in Step 2

{key_files}

Begin audit now. Do not ask clarifying questions. All requirements are in your system prompt."""


async def run_audit(config: AuditConfig) -> AuditResult:
    """Run the full 11-step audit protocol.

    1. Load system prompt from PROMPT.md
    2. Build file tree and key file contents
    3. Call LLM
    4. Parse output
    5. Write AUDIT.md
    6. Return AuditResult
    """
    logger.info("Starting audit of %s", config.repo_root)

    # 1. Load system prompt
    try:
        system_prompt = _load_prompt()
    except FileNotFoundError as e:
        logger.error("Could not load PROMPT.md: %s", e)
        raise

    # 2. Build file tree
    file_tree = _build_file_tree(config.repo_root)

    # 3. Read key files
    key_files_content = _read_key_files(config.repo_root)

    # 4. Build user prompt
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        repo_root=str(config.repo_root),
        file_tree=file_tree,
        key_files=key_files_content,
    )

    # 5. Call LLM
    llm_output = await call_llm(system_prompt, user_prompt, config)

    # 6. Parse JSON block
    json_block = _extract_json_block(llm_output)

    # 7. Parse markdown sections (used for structured result)
    _parse_markdown_sections(llm_output)

    # 8. Build full markdown (ensure JSON block is at the end)
    full_markdown = llm_output.strip()
    if not full_markdown.endswith("}"):
        full_markdown += "\n\n" + json.dumps({"audit_agent": json_block.get("audit_agent", {})}, indent=2)

    # 9. Build result
    result = _build_result(full_markdown, json_block, config)

    # 10. Write output
    output_path = config.output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_markdown, encoding="utf-8")
    logger.info("Wrote AUDIT.md to %s", output_path)

    if config.verbose:
        logger.info("Audit complete: %s", result.summary())

    return result