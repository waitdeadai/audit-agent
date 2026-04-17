"""Hybrid audit runner for audit-agent.

The runtime is evidence-driven:
1. Load the audit system prompt
2. Collect deterministic evidence from scanners + repo instructions
3. Build a repo map and prompt summary from that evidence
4. Ask the LLM to synthesize AUDIT.md from the evidence
5. Parse the result and backfill structured fields from deterministic evidence
6. Write AUDIT.md plus machine-readable audit artifacts
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
from .evidence import (
    build_repo_map,
    collect_audit_evidence,
    summarize_evidence_for_prompt,
)

logger = logging.getLogger("audit_agent.runner")

_PROMPT_CACHE: str | None = None

_MAX_TREE_FILES = 2000
_MAX_TREE_DEPTH = 20

_KEY_FILES = [
    "README.md",
    "README.es.md",
    "README.es-ES.md",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Gopkg.toml",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "CONTRIBUTING.md",
    ".github/copilot-instructions.md",
    ".github/instructions/*.instructions.md",
    "taste.md",
    "effort.md",
    "docs/ARCHITECTURE.md",
    "docs/RUNBOOK.md",
    "docs/DESIGN.md",
    ".forgegod/config.toml",
    ".forgegod/skills/audit-agent/SKILL.md",
    "main.py",
    "cli.py",
    "server.py",
    "index.ts",
    "index.js",
    "app.py",
    "__main__.py",
]

_MINIMAX_BASE_URL = "https://api.minimax.io/v1"
_AZURE_BASE_URL_ENV = "AZURE_OPENAI_BASE_URL"
_AZURE_API_KEY_ENV = "AZURE_OPENAI_API_KEY"
_MINIMAX_API_KEY_ENV = "MINIMAX_API_KEY"

_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
_JSON_BLOCK_RE2 = re.compile(r"\{[^{}]*\"audit_agent\"[^{}]*\}", re.DOTALL)

_USER_PROMPT_TEMPLATE = """Audit this repository. Produce AUDIT.md following your full 11-step protocol.

Repository root: {repo_root}

Available file tree:
{file_tree}

High-signal key files:
{key_files}

Repository instructions and policy files:
{instruction_context}

Deterministic repository map:
{repo_map}

Deterministic evidence summary:
{evidence_summary}

Rules:
- Treat the deterministic evidence and instruction files as source material.
- If the evidence conflicts with your inference, prefer the evidence and explain the conflict.
- Do not invent files, dependencies, tests, or architecture details that are not present in the evidence.
- Use the instruction files as hard constraints when they exist.

Begin audit now. Do not ask clarifying questions. All requirements are in your system prompt."""


def _prompt_candidates() -> list[Path]:
    """Return ordered prompt candidates for installed and skill-based usage."""

    pkg_dir = Path(__file__).resolve().parent.parent
    skill_dirs = [
        Path.home() / ".forgegod" / "skills" / "audit-agent",
        Path.cwd() / ".forgegod" / "skills" / "audit-agent",
    ]

    candidates = [pkg_dir / "PROMPT.md"]
    for skill_dir in skill_dirs:
        candidates.append(skill_dir / "PROMPT.md")
        candidates.append(skill_dir / "SKILL.md")

    output: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        output.append(candidate)
    return output


def _load_prompt() -> str:
    """Load the system prompt for the audit agent."""

    global _PROMPT_CACHE
    if _PROMPT_CACHE:
        return _PROMPT_CACHE

    candidates = _prompt_candidates()
    for candidate in candidates:
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("Failed to read %s: %s", candidate, exc)
            continue
        _PROMPT_CACHE = content
        logger.debug("Loaded prompt from %s", candidate)
        return content

    raise FileNotFoundError(
        "PROMPT.md not found. Searched: " + ", ".join(str(path) for path in candidates)
    )


def _build_file_tree(repo_root: Path) -> str:
    """Build a compact file tree string for prompt context."""

    skip_dirs = {
        ".git",
        ".forgegod",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".direnv",
        ".eggs",
        ".hypothesis",
        "dist",
        "build",
        ".wheel",
        ".npm",
        ".yarn",
        ".next",
        ".nuxt",
        ".output",
    }

    skip_extensions = {
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".dylib",
        ".bin",
        ".exe",
        ".msi",
        ".deb",
        ".rpm",
        ".snap",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".mp3",
        ".mp4",
        ".wav",
        ".webm",
        ".mkv",
        ".zip",
        ".tar",
        ".gz",
        ".rar",
        ".7z",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".lock",
        ".sum",
    }

    lines: list[str] = []
    count = 0

    for root, dirs, files in os.walk(repo_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(repo_root)

        dirs[:] = [name for name in dirs if name not in skip_dirs]
        if len(rel_root.parts) > _MAX_TREE_DEPTH:
            dirs.clear()
            continue

        for file_name in sorted(files):
            if count >= _MAX_TREE_FILES:
                break
            if Path(file_name).suffix.lower() in skip_extensions:
                continue
            lines.append(str(rel_root / file_name))
            count += 1

        if count >= _MAX_TREE_FILES:
            break

    if not lines:
        return "(empty repository)"

    tree = "\n".join(sorted(lines))
    if count >= _MAX_TREE_FILES:
        tree += f"\n... ({count} files shown, repo has more)"
    return tree


def _iter_key_file_matches(repo_root: Path, pattern: str) -> list[Path]:
    if "*" in pattern:
        return [
            path for path in sorted(repo_root.glob(pattern))
            if path.is_file()
        ]
    candidate = repo_root / pattern
    return [candidate] if candidate.is_file() else []


def _read_key_files(repo_root: Path) -> str:
    """Read high-signal key files for prompt grounding."""

    parts: list[str] = []
    seen: set[Path] = set()

    for pattern in _KEY_FILES:
        for path in _iter_key_file_matches(repo_root, pattern):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(content) > 5000:
                content = content[:5000] + "\n... [truncated]"
            parts.append(f"\n=== {path.relative_to(repo_root)} ===\n{content}")

    return "".join(parts) if parts else "(no key files found)"


def _format_instruction_context(instruction_context: dict[str, Any]) -> str:
    files = instruction_context.get("files", [])
    if not files:
        return "(no instruction files found)"

    chunks: list[str] = []
    for item in files[:8]:
        chunks.append(
            f"=== {item['path']} [{item['kind']}] ===\n{item['content']}"
        )
    return "\n\n".join(chunks)


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
    timeout: float = 300.0,
) -> str:
    """Call an OpenAI-compatible endpoint."""

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

    if "azure" in base_url.lower() or azure_api_version:
        headers["api-key"] = api_key
        url = (
            f"{base_url.rstrip('/')}/chat/completions"
            f"?api-version={azure_api_version or '2024-02-01'}"
        )
    else:
        url = f"{base_url.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Connection error calling {url}: {exc}.\n"
                "Check that the API endpoint is reachable and the API key is correct."
            ) from exc

        if response.status_code == 401:
            raise RuntimeError(
                f"Authentication error (401) calling {url}.\n"
                "Verify your API key is valid."
            )
        if response.status_code == 403:
            raise RuntimeError(
                f"Forbidden (403) calling {url}.\n"
                "Check that your API key has permission for this model."
            )
        if response.status_code == 429:
            raise RuntimeError(
                f"Rate limited (429) calling {url}.\n"
                "Wait before retrying or increase rate limit."
            )
        if response.status_code >= 500:
            raise RuntimeError(
                f"Server error ({response.status_code}) from {url}.\n"
                "The provider is experiencing issues. Try again shortly."
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"Unexpected response {response.status_code} from {url}: "
                f"{response.text[:500]}"
            )

        data = response.json()
        choices = data.get("choices", [{}])
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            text = message.get("content", "")
            if text:
                return text

        raise RuntimeError(f"No content in response from {url}: {data}")


def _resolve_api_key_and_url(config: AuditConfig) -> tuple[str, str]:
    """Resolve API key and base URL from config plus environment."""

    if config.minimax_api_key:
        return config.minimax_api_key, config.minimax_base_url
    if config.azure_api_key and config.azure_base_url:
        return config.azure_api_key, config.azure_base_url

    azure_key = os.environ.get(_AZURE_API_KEY_ENV, "") or os.environ.get("AZURE_OPENAI_KEY", "")
    azure_url = os.environ.get(_AZURE_BASE_URL_ENV, "") or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    if azure_key and azure_url:
        return azure_key, azure_url

    minimax_key = os.environ.get(_MINIMAX_API_KEY_ENV, "") or os.environ.get("OPENAI_API_KEY", "")
    if minimax_key:
        return minimax_key, config.minimax_base_url or _MINIMAX_BASE_URL

    raise RuntimeError(
        "No API key found. Set one of:\n"
        "  MINIMAX_API_KEY - for MiniMax\n"
        "  AZURE_OPENAI_API_KEY - for Azure OpenAI\n"
        "  OPENAI_API_KEY - for generic OpenAI-compatible\n"
        "Or pass minimax_api_key=... in AuditConfig."
    )


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    config: AuditConfig,
) -> str:
    """Call the configured LLM (OpenAI-compatible)."""

    if config.verbose:
        logger.info("Calling LLM with model=%s", config.model)

    api_key, base_url = _resolve_api_key_and_url(config)
    is_azure = bool(config.azure_api_key and config.azure_base_url) or ("azure" in base_url.lower())
    errors: list[str] = []

    for provider, model in config.model_specs():
        try:
            if config.verbose:
                logger.info("Trying provider=%s model=%s", provider, model)
            return await _call_openai_compatible(
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
        except Exception as exc:
            errors.append(f"{provider}/{model}: {type(exc).__name__}('{str(exc) or repr(exc)}')")
            if config.verbose:
                logger.warning("Model %s/%s failed: %s", provider, model, exc)

    raise RuntimeError("All models failed:\n" + "\n".join(errors))


def _extract_json_block(text: str) -> dict[str, Any]:
    """Extract and parse the JSON block from LLM output."""

    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse JSON block: %s", exc)

    match = _JSON_BLOCK_RE2.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse fallback JSON block: %s", exc)

    start = text.find('{"audit_agent"')
    if start == -1:
        start = text.find('"audit_agent"')
    if start != -1:
        depth = 0
        for idx in range(start, len(text)):
            if text[idx] == "{":
                depth += 1
            elif text[idx] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:idx + 1])
                    except json.JSONDecodeError:
                        break

    logger.warning("No parseable JSON block found in LLM output")
    return {}


def _parse_markdown_sections(content: str) -> dict[str, str]:
    """Split LLM markdown output into sections."""

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


def _merge_unique(primary: list[str], secondary: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in [*primary, *secondary]:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _derive_blockers_from_evidence(evidence: dict[str, Any]) -> list[str]:
    planning = evidence.get("planning_constraints", {})
    security = evidence.get("security", {})

    blockers = list(planning.get("blockers", []))
    for finding in security.get("critical", [])[:10]:
        location = finding.get("file", "unknown")
        detail = (
            finding.get("description")
            or finding.get("match")
            or finding.get("type")
            or "critical security finding"
        )
        blockers.append(f"CRITICAL security: {location} - {detail}")
    return _merge_unique(blockers, [])


def _derive_high_risk_modules(evidence: dict[str, Any]) -> list[str]:
    risks = evidence.get("risk_map", {}).get("risks", [])
    high = [item["module"] for item in risks if "HIGH" in item.get("risk", "")]
    if high:
        return high[:8]
    medium = [item["module"] for item in risks if "MEDIUM" in item.get("risk", "")]
    return medium[:8]


def _derive_structured_defaults(evidence: dict[str, Any]) -> dict[str, Any]:
    planning = evidence.get("planning_constraints", {})
    effort = evidence.get("effort_requirements", {})
    taste = evidence.get("taste_preflight", {})
    snapshot = evidence.get("repo_snapshot", {})

    return {
        "repo": snapshot.get("repo_name", ""),
        "blockers": _derive_blockers_from_evidence(evidence),
        "high_risk_modules": _derive_high_risk_modules(evidence),
        "recommended_start_points": planning.get("safest_start_points", [])[:3],
        "effort_level": effort.get("min_drafts", "thorough"),
        "taste_pre_flight_failures": taste.get("violations", [])[:5],
    }


def _build_result(
    content: str,
    json_block: dict[str, Any],
    config: AuditConfig,
    evidence: dict[str, Any],
) -> AuditResult:
    """Build an AuditResult from LLM output plus deterministic evidence."""

    agent_block = json_block.get("audit_agent", {})
    derived = _derive_structured_defaults(evidence)

    blockers = _merge_unique(
        list(agent_block.get("blockers", [])),
        derived["blockers"],
    )
    if "CRITICAL" in content.upper():
        for line in content.splitlines():
            if "CRITICAL" in line.upper():
                stripped = line.strip()
                if stripped:
                    blockers = _merge_unique(blockers, [stripped[:200]])

    high_risk = list(agent_block.get("high_risk_modules", [])) or derived["high_risk_modules"]
    start_points = list(agent_block.get("recommended_start_points", [])) or derived["recommended_start_points"]
    effort = agent_block.get("effort_level") or derived["effort_level"] or "thorough"
    taste_failures = (
        list(agent_block.get("taste_pre_flight_failures", []))
        or derived["taste_pre_flight_failures"]
    )

    ready_to_plan = agent_block.get("ready_to_plan")
    if ready_to_plan is None:
        ready_to_plan = len(blockers) == 0
    else:
        ready_to_plan = bool(ready_to_plan)
    if any("CRITICAL" in blocker.upper() for blocker in blockers):
        ready_to_plan = False

    repo_name = agent_block.get("repo") or derived["repo"] or config.repo_root.name

    return AuditResult(
        version=agent_block.get("version", "1.1"),
        timestamp=agent_block.get("timestamp", ""),
        repo=repo_name,
        repo_root=config.repo_root,
        output_path=config.output_path,
        blockers=blockers,
        high_risk_modules=high_risk,
        recommended_start_points=start_points,
        effort_level=effort,
        taste_pre_flight_failures=taste_failures,
        ready_to_plan=ready_to_plan,
        markdown_content=content,
    )


def _artifact_paths(output_path: Path) -> tuple[Path, Path]:
    audit_json_path = output_path.with_suffix(".json")
    evidence_path = output_path.with_name(f"{output_path.stem}_EVIDENCE.json")
    return audit_json_path, evidence_path


def _write_structured_artifacts(
    result: AuditResult,
    evidence: dict[str, Any],
    output_path: Path,
) -> None:
    audit_json_path, evidence_path = _artifact_paths(output_path)
    audit_json_path.write_text(result.to_json_block() + "\n", encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


async def run_audit(config: AuditConfig) -> AuditResult:
    """Run the full hybrid audit protocol."""

    logger.info("Starting audit of %s", config.repo_root)

    try:
        system_prompt = _load_prompt()
    except FileNotFoundError as exc:
        logger.error("Could not load prompt: %s", exc)
        raise

    evidence = collect_audit_evidence(config.repo_root)
    repo_map = build_repo_map(evidence)
    evidence_summary = summarize_evidence_for_prompt(evidence)
    instruction_context = _format_instruction_context(evidence["instruction_context"])
    file_tree = _build_file_tree(config.repo_root)
    key_files_content = _read_key_files(config.repo_root)

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        repo_root=str(config.repo_root),
        file_tree=file_tree,
        key_files=key_files_content,
        instruction_context=instruction_context,
        repo_map=repo_map,
        evidence_summary=evidence_summary,
    )

    llm_output = await call_llm(system_prompt, user_prompt, config)
    json_block = _extract_json_block(llm_output)
    _parse_markdown_sections(llm_output)

    full_markdown = llm_output.strip()
    if not full_markdown.endswith("}"):
        full_markdown += "\n\n" + json.dumps(
            {"audit_agent": json_block.get("audit_agent", {})},
            indent=2,
        )

    result = _build_result(full_markdown, json_block, config, evidence)

    output_path = config.output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_markdown, encoding="utf-8")
    _write_structured_artifacts(result, evidence, output_path)
    logger.info("Wrote AUDIT.md to %s", output_path)

    if config.verbose:
        logger.info("Audit complete: %s", result.summary())

    return result
