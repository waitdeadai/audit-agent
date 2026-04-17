"""Specialist audit surfaces for security, architecture, and plan risk."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from audit_agent.scanners.architecture import scan_architecture
from audit_agent.scanners.risk_map import scan_risk_map
from audit_agent.scanners.security import scan_security

from .audit_config import AuditConfig
from .audit_result import AuditFinding, AuditResult, PlanResult, PlanStory, SpecialistAuditResult

logger = logging.getLogger("audit_agent.specialists")


def run_security_audit(
    audit_result: AuditResult,
    config: AuditConfig,
    *,
    changed_files: list[str] | None = None,
    use_semgrep: bool = False,
) -> SpecialistAuditResult:
    """Run the deterministic security specialist surface."""

    repo_root = audit_result.repo_root or config.repo_root
    security = scan_security(repo_root)
    findings = _security_findings_to_objects(
        security,
        changed_files=changed_files,
    )

    semgrep_findings: list[AuditFinding] = []
    semgrep_status = "disabled"
    if use_semgrep:
        semgrep_findings, semgrep_status = _run_semgrep(repo_root, changed_files=changed_files)

    combined_findings = findings + semgrep_findings
    blockers = [
        _format_blocker(finding)
        for finding in combined_findings
        if finding.severity == "CRITICAL"
    ]
    guardrails = _merge_unique(
        _security_guardrails(combined_findings),
        ["Keep secrets and shell execution paths out of the implementation plan."]
        if blockers
        else [],
    )
    relevant_modules = _merge_unique(
        [finding.file for finding in combined_findings if finding.file],
    )

    result = SpecialistAuditResult(
        kind="security",
        repo=audit_result.repo,
        task="",
        findings=combined_findings,
        blockers=blockers,
        guardrail_updates=guardrails,
        relevant_modules=relevant_modules,
        ready=len(blockers) == 0,
        metadata={
            "changed_files": _normalize_rel_paths(changed_files or []),
            "critical_count": sum(1 for finding in combined_findings if finding.severity == "CRITICAL"),
            "warning_count": sum(1 for finding in combined_findings if finding.severity == "WARNING"),
            "info_count": sum(1 for finding in combined_findings if finding.severity == "INFO"),
            "semgrep_status": semgrep_status,
            "semgrep_enabled": use_semgrep,
        },
    )
    result.markdown_content = _render_security_markdown(result)
    _write_specialist_artifacts(repo_root, "SECURITY_AUDIT", result)
    return result


def run_architecture_audit(
    audit_result: AuditResult,
    config: AuditConfig,
    *,
    changed_files: list[str] | None = None,
) -> SpecialistAuditResult:
    """Run the deterministic architecture specialist surface."""

    repo_root = audit_result.repo_root or config.repo_root
    architecture = scan_architecture(repo_root)
    risk_map = scan_risk_map(repo_root)

    findings: list[AuditFinding] = []
    blockers: list[str] = []
    guardrails: list[str] = []

    for cycle in architecture.get("circular_imports", []):
        modules = cycle.get("modules", [])
        cycle_label = " <-> ".join(modules) if modules else "unknown"
        description = (
            "Circular import detected: "
            f"{cycle_label}"
        )
        findings.append(
            AuditFinding(
                severity="CRITICAL",
                category="architecture",
                file=modules[0] if modules else None,
                description=description,
            )
        )
        blockers.append(description)

    for module in architecture.get("god_modules", [])[:10]:
        file_path = module.get("file")
        if changed_files and not _path_in_scope(file_path, changed_files):
            continue
        findings.append(
            AuditFinding(
                severity="WARNING",
                category="architecture",
                file=file_path,
                description=(
                    f"God module candidate: {file_path} "
                    f"({module.get('lines', 0)} lines, {module.get('functions', 0)} functions)"
                ),
            )
        )
        guardrails.append(
            f"Avoid wide edits in {file_path}; isolate seams and add verification before refactoring."
        )

    for item in risk_map.get("risks", [])[:12]:
        if "HIGH" not in item.get("risk", ""):
            continue
        module_name = item.get("module")
        if changed_files and not _path_in_scope(module_name, changed_files):
            continue
        findings.append(
            AuditFinding(
                severity="WARNING",
                category="architecture",
                file=module_name,
                description=f"High change-risk module: {module_name} ({item.get('why', 'unknown risk')})",
            )
        )

    relevant_modules = _merge_unique(
        [finding.file for finding in findings if finding.file],
        [item.get("module", "") for item in architecture.get("top_imported_modules", [])[:5]],
    )

    result = SpecialistAuditResult(
        kind="architecture",
        repo=audit_result.repo,
        task="",
        findings=findings,
        blockers=blockers,
        guardrail_updates=_merge_unique(guardrails),
        relevant_modules=relevant_modules,
        ready=len(blockers) == 0,
        metadata={
            "changed_files": _normalize_rel_paths(changed_files or []),
            "structure_type": architecture.get("structure_type", "unknown"),
            "ascii_diagram": architecture.get("ascii_diagram", ""),
            "top_imported_modules": architecture.get("top_imported_modules", [])[:5],
            "god_modules": architecture.get("god_modules", [])[:10],
            "circular_imports": architecture.get("circular_imports", []),
        },
    )
    result.markdown_content = _render_architecture_markdown(result)
    _write_specialist_artifacts(repo_root, "ARCHITECTURE_AUDIT", result)
    return result


def run_plan_risk_audit(
    audit_result: AuditResult,
    plan_result: PlanResult,
    config: AuditConfig,
    *,
    task: str = "",
) -> SpecialistAuditResult:
    """Run the deterministic plan-risk specialist surface."""

    findings: list[AuditFinding] = []
    blockers: list[str] = []
    guardrails: list[str] = []
    relevant_modules: list[str] = []

    stories = plan_result.stories
    if not stories:
        blockers.append("PLAN.md does not contain any executable stories.")

    story_ids = {story.id for story in stories}
    safe_starts = audit_result.recommended_start_points
    first_story = stories[0] if stories else None

    if first_story and safe_starts:
        first_story_matches_safe_start = _story_mentions_candidates(first_story, safe_starts)
        first_story_touches_high_risk = _story_mentions_candidates(first_story, audit_result.high_risk_modules)
        if first_story_touches_high_risk and not first_story_matches_safe_start:
            guardrails.append(
                "Start from a recommended safe module before touching high-risk modules."
            )
            findings.append(
                AuditFinding(
                    severity="WARNING",
                    category="plan-risk",
                    description=(
                        f"First story {first_story.id} touches high-risk modules before any recommended safe start."
                    ),
                )
            )

    for story in stories:
        missing_dependencies = [dep for dep in story.depends_on if dep not in story_ids]
        if missing_dependencies:
            blockers.append(
                f"Story {story.id} depends on missing stories: {', '.join(missing_dependencies)}"
            )

        matched_high_risk = _match_story_modules(story, audit_result.high_risk_modules)
        if matched_high_risk:
            relevant_modules.extend(matched_high_risk)
            if not story.verification_commands:
                blockers.append(
                    f"Story {story.id} touches high-risk modules without verification commands: "
                    f"{', '.join(matched_high_risk)}"
                )
            if story.risk.lower() == "low":
                findings.append(
                    AuditFinding(
                        severity="WARNING",
                        category="plan-risk",
                        description=(
                            f"Story {story.id} is marked low risk but touches high-risk modules: "
                            f"{', '.join(matched_high_risk)}"
                        ),
                    )
                )
            if not story.blocked_by and audit_result.blockers:
                findings.append(
                    AuditFinding(
                        severity="WARNING",
                        category="plan-risk",
                        description=(
                            f"Story {story.id} touches risky modules without carrying audit blockers into story scope."
                        ),
                    )
                )

        if not story.acceptance_criteria:
            findings.append(
                AuditFinding(
                    severity="INFO",
                    category="plan-risk",
                    description=f"Story {story.id} has no explicit acceptance criteria.",
                )
            )

    if audit_result.blockers and plan_result.ready_to_execute:
        blockers.append("Plan is marked ready_to_execute despite inherited audit blockers.")

    result = SpecialistAuditResult(
        kind="plan-risk",
        repo=plan_result.repo,
        task=task or plan_result.task,
        findings=findings,
        blockers=_merge_unique(blockers),
        guardrail_updates=_merge_unique(
            guardrails,
            [
                f"Touch {module} only with explicit verification commands."
                for module in _merge_unique(relevant_modules)
            ],
        ),
        relevant_modules=_merge_unique(relevant_modules),
        ready=len(blockers) == 0,
        metadata={
            "story_count": len(stories),
            "recommended_start": plan_result.recommended_start,
            "safe_start_points": safe_starts,
            "high_risk_modules": audit_result.high_risk_modules,
        },
    )
    repo_root = audit_result.repo_root or config.repo_root
    result.markdown_content = _render_plan_risk_markdown(result, plan_result)
    _write_specialist_artifacts(repo_root, "PLAN_RISK_AUDIT", result)
    return result


def _security_findings_to_objects(
    security: dict[str, Any],
    *,
    changed_files: list[str] | None = None,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for severity, items in (
        ("CRITICAL", security.get("critical", [])),
        ("WARNING", security.get("warning", [])),
        ("INFO", security.get("info", [])),
    ):
        for item in items:
            file_path = item.get("file")
            if changed_files and not _path_in_scope(file_path, changed_files):
                continue
            findings.append(
                AuditFinding(
                    severity=severity,
                    category="security",
                    file=file_path,
                    line=item.get("line"),
                    description=(
                        item.get("description")
                        or item.get("match")
                        or item.get("type")
                        or "security finding"
                    ),
                )
            )
    return findings


def _security_guardrails(findings: list[AuditFinding]) -> list[str]:
    guardrails: list[str] = []
    for finding in findings:
        description = finding.description.lower()
        if "shell" in description:
            guardrails.append("Avoid shell execution paths without explicit argument escaping.")
        elif "secret" in description or "token" in description or "password" in description:
            guardrails.append("Move secrets to environment or secret storage before planning changes.")
        elif "sql" in description:
            guardrails.append("Use parameterized queries instead of string concatenation.")
    return _merge_unique(guardrails)


def _run_semgrep(
    repo_root: Path,
    *,
    changed_files: list[str] | None = None,
) -> tuple[list[AuditFinding], str]:
    executable = shutil.which("semgrep")
    if executable is None:
        return [], "unavailable"

    command = [executable, "scan", "--json", "--quiet", "--config", "auto"]
    if changed_files:
        command.extend(changed_files)
    else:
        command.append(".")

    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Semgrep execution failed: %s", exc)
        return [], "failed"

    if result.returncode not in {0, 1}:
        logger.warning("Semgrep returned %s: %s", result.returncode, result.stderr[:200])
        return [], "failed"

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return [], "failed"

    findings: list[AuditFinding] = []
    for item in payload.get("results", [])[:50]:
        extra = item.get("extra", {})
        severity = str(extra.get("severity", "WARNING")).upper()
        if severity == "ERROR":
            severity = "CRITICAL"
        elif severity not in {"CRITICAL", "WARNING", "INFO"}:
            severity = "WARNING"
        findings.append(
            AuditFinding(
                severity=severity,
                category="security",
                file=item.get("path"),
                line=(item.get("start") or {}).get("line"),
                description=extra.get("message") or item.get("check_id") or "semgrep finding",
            )
        )

    return findings, "ok"


def _match_story_modules(story: PlanStory, candidates: list[str]) -> list[str]:
    matched: list[str] = []
    story_text = " ".join(
        [
            story.title,
            story.description,
            *story.modules_touched,
            *story.acceptance_criteria,
        ]
    ).lower()
    for candidate in candidates:
        candidate_norm = candidate.replace("\\", "/")
        tokens = {
            candidate_norm.lower(),
            Path(candidate_norm).stem.lower(),
            Path(candidate_norm).name.lower(),
        }
        if any(token and token in story_text for token in tokens):
            matched.append(candidate)
    return _merge_unique(matched)


def _story_mentions_candidates(story: PlanStory, candidates: list[str]) -> bool:
    return bool(_match_story_modules(story, candidates))


def _path_in_scope(path: str | None, changed_files: list[str]) -> bool:
    if not path:
        return False
    normalized_path = path.replace("\\", "/").lower()
    for changed in _normalize_rel_paths(changed_files):
        if (
            normalized_path == changed
            or normalized_path.endswith(f"/{changed}")
            or changed.endswith(normalized_path)
            or Path(normalized_path).stem == Path(changed).stem
        ):
            return True
    return False


def _normalize_rel_paths(paths: list[str]) -> list[str]:
    return [path.replace("\\", "/").lstrip("./").lower() for path in paths if path]


def _merge_unique(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for value in group:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _format_blocker(finding: AuditFinding) -> str:
    if finding.file:
        return f"{finding.file}: {finding.description}"
    return finding.description


def _render_security_markdown(result: SpecialistAuditResult) -> str:
    lines = [
        "# SECURITY_AUDIT.md",
        f"**Repo:** {result.repo} | **Kind:** {result.kind}",
        "",
        "## Summary",
        f"- Ready: {str(result.ready).lower()}",
        f"- Findings: {len(result.findings)}",
        f"- Blockers: {len(result.blockers)}",
        "",
        "## Blockers",
    ]
    if result.blockers:
        lines.extend(f"- {blocker}" for blocker in result.blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Findings"])
    if result.findings:
        for finding in result.findings:
            location = f" ({finding.file}:{finding.line})" if finding.file and finding.line else (
                f" ({finding.file})" if finding.file else ""
            )
            lines.append(f"- [{finding.severity}] {finding.description}{location}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Guardrail Updates",
        ]
    )
    if result.guardrail_updates:
        lines.extend(f"- {guardrail}" for guardrail in result.guardrail_updates)
    else:
        lines.append("- none")
    lines.extend(["", "```json", result.to_json_block(), "```"])
    return "\n".join(lines)


def _render_architecture_markdown(result: SpecialistAuditResult) -> str:
    lines = [
        "# ARCHITECTURE_AUDIT.md",
        f"**Repo:** {result.repo} | **Kind:** {result.kind}",
        "",
        "## Summary",
        f"- Ready: {str(result.ready).lower()}",
        f"- Structure: {result.metadata.get('structure_type', 'unknown')}",
        f"- Relevant modules: {len(result.relevant_modules)}",
        "",
        "## Blockers",
    ]
    if result.blockers:
        lines.extend(f"- {blocker}" for blocker in result.blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Findings"])
    if result.findings:
        for finding in result.findings:
            target = f" ({finding.file})" if finding.file else ""
            lines.append(f"- [{finding.severity}] {finding.description}{target}")
    else:
        lines.append("- none")
    diagram = result.metadata.get("ascii_diagram", "")
    if diagram:
        lines.extend(["", "## Repo Map", "```text", str(diagram), "```"])
    lines.extend(["", "```json", result.to_json_block(), "```"])
    return "\n".join(lines)


def _render_plan_risk_markdown(
    result: SpecialistAuditResult,
    plan_result: PlanResult,
) -> str:
    lines = [
        "# PLAN_RISK_AUDIT.md",
        f"**Repo:** {result.repo} | **Kind:** {result.kind} | **Task:** {result.task}",
        "",
        "## Summary",
        f"- Ready: {str(result.ready).lower()}",
        f"- Stories: {len(plan_result.stories)}",
        f"- High-risk modules touched: {len(result.relevant_modules)}",
        "",
        "## Blockers",
    ]
    if result.blockers:
        lines.extend(f"- {blocker}" for blocker in result.blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Findings"])
    if result.findings:
        for finding in result.findings:
            lines.append(f"- [{finding.severity}] {finding.description}")
    else:
        lines.append("- none")
    lines.extend(["", "## Guardrail Updates"])
    if result.guardrail_updates:
        lines.extend(f"- {guardrail}" for guardrail in result.guardrail_updates)
    else:
        lines.append("- none")
    lines.extend(["", "```json", result.to_json_block(), "```"])
    return "\n".join(lines)


def _write_specialist_artifacts(
    repo_root: Path,
    stem: str,
    result: SpecialistAuditResult,
) -> None:
    artifacts_dir = repo_root / ".forgegod"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / f"{stem}.md").write_text(result.markdown_content, encoding="utf-8")
    (artifacts_dir / f"{stem}.json").write_text(result.to_json_block(), encoding="utf-8")
