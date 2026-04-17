"""Evidence collection helpers for the hybrid audit pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_agent.scanners.architecture import scan_architecture
from audit_agent.scanners.dependencies import scan_dependencies, scan_internal_deps
from audit_agent.scanners.effort_requirements import scan_effort_requirements
from audit_agent.scanners.entry_points import scan_entry_points
from audit_agent.scanners.health import scan_health
from audit_agent.scanners.planning_constraints import scan_planning_constraints
from audit_agent.scanners.repo_snapshot import scan_repo_snapshot
from audit_agent.scanners.risk_map import scan_risk_map
from audit_agent.scanners.security import scan_security
from audit_agent.scanners.taste_preflight import scan_taste_preflight
from audit_agent.scanners.test_surface import scan_test_surface

_INSTRUCTION_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/RUNBOOK.md",
    "docs/DESIGN.md",
]

_INSTRUCTION_GLOBS = [
    ".github/instructions/*.instructions.md",
]

_POLICY_BUCKETS = {
    "architecture": ("architecture", "layer", "boundary", "module", "dependency"),
    "code_style": ("style", "naming", "format", "lint", "comment"),
    "verification": ("test", "verify", "verification", "coverage", "ruff", "pytest"),
    "security": ("security", "secret", "token", "password", "sandbox", "permission"),
    "product": ("non-goal", "scope", "ux", "api", "design", "product"),
}


def collect_instruction_context(
    repo_root: Path,
    *,
    max_chars_per_file: int = 4000,
) -> dict[str, Any]:
    """Load high-signal repo instruction files and bucket the rules they contain."""

    files: list[dict[str, str]] = []
    policy_buckets: dict[str, list[str]] = {
        bucket: [] for bucket in _POLICY_BUCKETS
    }

    candidates: list[Path] = []
    for rel_path in _INSTRUCTION_FILES:
        candidate = repo_root / rel_path
        if candidate.is_file():
            candidates.append(candidate)
    for pattern in _INSTRUCTION_GLOBS:
        candidates.extend(sorted(repo_root.glob(pattern)))

    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        try:
            content = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not content:
            continue

        snippet = content[:max_chars_per_file]
        rel_path = path.relative_to(repo_root).as_posix()
        files.append(
            {
                "path": rel_path,
                "kind": _classify_instruction_file(rel_path),
                "content": snippet,
            }
        )
        _collect_policy_lines(rel_path, snippet, policy_buckets)

    return {
        "files": files,
        "policy_buckets": {
            bucket: _dedupe(values)[:20]
            for bucket, values in policy_buckets.items()
        },
    }


def collect_audit_evidence(repo_root: Path) -> dict[str, Any]:
    """Collect deterministic evidence used by the hybrid audit runtime."""

    instruction_context = collect_instruction_context(repo_root)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "instruction_context": instruction_context,
        "repo_snapshot": scan_repo_snapshot(repo_root),
        "entry_points": scan_entry_points(repo_root),
        "architecture": scan_architecture(repo_root),
        "dependencies": scan_dependencies(repo_root),
        "internal_dependencies": scan_internal_deps(repo_root),
        "health": scan_health(repo_root),
        "test_surface": scan_test_surface(repo_root),
        "security": scan_security(repo_root),
        "risk_map": scan_risk_map(repo_root),
        "taste_preflight": scan_taste_preflight(repo_root),
        "effort_requirements": scan_effort_requirements(repo_root),
        "planning_constraints": scan_planning_constraints(repo_root),
    }


def build_repo_map(evidence: dict[str, Any]) -> str:
    """Build a compact repo map from deterministic evidence."""

    snapshot = evidence.get("repo_snapshot", {})
    entry_points = evidence.get("entry_points", {}).get("entry_points", [])
    architecture = evidence.get("architecture", {})
    risk_entries = evidence.get("risk_map", {}).get("risks", [])
    planning = evidence.get("planning_constraints", {})
    tests = evidence.get("test_surface", {})
    internal_deps = evidence.get("internal_dependencies", {})
    instructions = evidence.get("instruction_context", {}).get("files", [])

    lines = [
        f"Repo: {snapshot.get('repo_name', 'unknown')}",
        (
            "Languages/Framework: "
            f"{snapshot.get('primary_language', 'unknown')} / "
            f"{snapshot.get('framework') or 'n/a'}"
        ),
        (
            "Footprint: "
            f"{snapshot.get('file_count', 0)} files, "
            f"{snapshot.get('line_count', 0)} lines"
        ),
        f"Architecture: {architecture.get('structure_type', 'unknown')}",
    ]

    if instructions:
        lines.append("Instruction files:")
        for item in instructions[:8]:
            lines.append(f"- {item['path']} [{item['kind']}]")

    if entry_points:
        lines.append("Entry points:")
        for item in entry_points[:8]:
            touches = item.get("touches", "unknown")
            lines.append(f"- {item['name']} ({item.get('type', 'unknown')}, touches={touches})")

    top_imported = architecture.get("top_imported_modules", [])
    if top_imported:
        lines.append("Load-bearing modules:")
        for item in top_imported[:5]:
            lines.append(f"- {item['module']} ({item['import_count']} imports)")

    high_risk = [
        item["module"]
        for item in risk_entries
        if "HIGH" in item.get("risk", "")
    ]
    if high_risk:
        lines.append("High-risk modules:")
        for module in high_risk[:8]:
            lines.append(f"- {module}")

    no_tests = tests.get("modules_without_tests", [])
    if no_tests:
        lines.append("Modules without tests:")
        for module in no_tests[:8]:
            lines.append(f"- {module}")

    complexity_sinks = internal_deps.get("complexity_sinks", [])
    if complexity_sinks:
        lines.append("Complexity sinks:")
        for item in complexity_sinks[:5]:
            lines.append(f"- {item['module']} ({item['imports_count']} imports)")

    chains = internal_deps.get("longest_import_chains", [])
    if chains:
        lines.append("Longest import chains:")
        for chain in chains[:3]:
            lines.append(f"- {' -> '.join(chain)}")

    safest = planning.get("safest_start_points", [])
    if safest:
        lines.append("Safest starting points:")
        for module in safest[:3]:
            lines.append(f"- {module}")

    riskiest = planning.get("riskiest_modules", [])
    if riskiest:
        lines.append("Touch last:")
        for module in riskiest[:3]:
            lines.append(f"- {module}")

    return "\n".join(lines)


def summarize_evidence_for_prompt(evidence: dict[str, Any]) -> str:
    """Render a compact evidence summary for the LLM prompt."""

    snapshot = evidence.get("repo_snapshot", {})
    health = evidence.get("health", {})
    test_surface = evidence.get("test_surface", {})
    security = evidence.get("security", {})
    planning = evidence.get("planning_constraints", {})
    effort = evidence.get("effort_requirements", {})
    instruction_context = evidence.get("instruction_context", {})
    taste = evidence.get("taste_preflight", {})
    internal_deps = evidence.get("internal_dependencies", {})

    lines = [
        "Deterministic audit evidence (treat this as source material):",
        (
            f"- Repo snapshot: {snapshot.get('primary_language', 'unknown')} / "
            f"{snapshot.get('framework') or 'n/a'}, "
            f"{snapshot.get('file_count', 0)} files, "
            f"{snapshot.get('line_count', 0)} lines"
        ),
        (
            f"- Health: TODO={health.get('todo_count', 0)}, "
            f"FIXME={health.get('fixme_count', 0)}, "
            f"placeholders={health.get('placeholder_count', 0)}, "
            f"long_files={len(health.get('long_files', []))}"
        ),
        (
            f"- Tests: runner={test_surface.get('test_runner') or 'none'}, "
            f"coverage={test_surface.get('test_percentage', 0)}%, "
            f"modules_without_tests={len(test_surface.get('modules_without_tests', []))}"
        ),
        (
            f"- Security: critical={len(security.get('critical', []))}, "
            f"warning={len(security.get('warning', []))}, "
            f"info={len(security.get('info', []))}"
        ),
        (
            f"- Planning constraints: blockers={len(planning.get('blockers', []))}, "
            f"prework={len(planning.get('recommended_prework', []))}"
        ),
        (
            f"- Effort requirements: research_before_code={effort.get('research_before_code', False)}, "
            f"min_drafts={effort.get('min_drafts', 'unknown')}"
        ),
        (
            f"- Instruction files: {len(instruction_context.get('files', []))}, "
            f"policy buckets with rules="
            f"{sum(1 for values in instruction_context.get('policy_buckets', {}).values() if values)}"
        ),
    ]

    risk_entries = evidence.get("risk_map", {}).get("risks", [])
    high_risk = [
        item["module"]
        for item in risk_entries
        if "HIGH" in item.get("risk", "")
    ]
    if high_risk:
        lines.append("- High-risk modules: " + ", ".join(high_risk[:8]))

    complexity_sinks = internal_deps.get("complexity_sinks", [])
    if complexity_sinks:
        sinks = ", ".join(item["module"] for item in complexity_sinks[:5])
        lines.append(f"- Complexity sinks: {sinks}")

    safest = planning.get("safest_start_points", [])
    if safest:
        lines.append("- Safest starting points: " + ", ".join(safest[:3]))

    violations = taste.get("violations", [])
    if violations:
        lines.append("- Taste preflight violations: " + " | ".join(violations[:5]))

    bucket_rules = instruction_context.get("policy_buckets", {})
    for bucket, rules in bucket_rules.items():
        if rules:
            lines.append(f"- {bucket} rules: {' | '.join(rules[:5])}")

    return "\n".join(lines)


def _classify_instruction_file(rel_path: str) -> str:
    lower = rel_path.lower()
    if lower.endswith("agents.md"):
        return "agent-rules"
    if lower.endswith("claude.md"):
        return "claude-memory"
    if lower.endswith("gemini.md"):
        return "gemini-memory"
    if "copilot-instructions" in lower or ".instructions.md" in lower:
        return "copilot-instructions"
    if "contributing" in lower:
        return "contribution-guide"
    if "architecture" in lower:
        return "architecture-doc"
    if "runbook" in lower:
        return "runbook"
    if "design" in lower:
        return "design-doc"
    return "project-doc"


def _collect_policy_lines(
    rel_path: str,
    content: str,
    policy_buckets: dict[str, list[str]],
) -> None:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("-", "*", "+")):
            candidate = line[1:].strip()
        elif line[:2].isdigit() and ". " in line:
            candidate = line.split(". ", 1)[1].strip()
        else:
            continue

        lower = f"{rel_path.lower()} {candidate.lower()}"
        for bucket, keywords in _POLICY_BUCKETS.items():
            if any(keyword in lower for keyword in keywords):
                policy_buckets[bucket].append(candidate)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output
