"""Delta-audit triggers and targeted re-audit runtime."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit_config import AuditConfig
from .audit_result import AuditResult, DeltaAuditResult, DeltaTrigger
from .audit_runner import call_llm
from .evidence import collect_audit_evidence, summarize_evidence_for_prompt

logger = logging.getLogger("audit_agent.delta")

_DEPENDENCY_FILES = {
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "uv.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
}

_INSTRUCTION_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/RUNBOOK.md",
    "docs/DESIGN.md",
}

_DELTA_JSON_KEY = "delta_audit"

_DELTA_PROMPT = """Produce AUDIT_DELTA.md for this repository state.

Task (if any):
{task}

Trigger summary:
{trigger_summary}

Changed files since the last audit:
{changed_files}

Relevant modules:
{relevant_modules}

Latest review feedback:
{review_feedback}

Failure details:
{failure_details}

Deterministic evidence summary:
{evidence_summary}

Instructions:
- This is a targeted delta audit, not a full repo audit.
- Focus on what changed since the last audit and what matters for the next plan.
- If dependency or instruction changes materially alter the repo contract, require a full re-audit.
- If the trigger is a bad review or a stuck execution, explain what must be re-checked before planning continues.

Output format:

```markdown
# AUDIT_DELTA.md
**Repo:** {{repo_name}} · **Generated:** {{ISO datetime}}

## Trigger Summary
- ...

## Changed Files
- ...

## Impact on Current Audit
- ...

## Guardrail Updates
- ...

## Planning Verdict
- ready_to_plan: true|false
- full_reaudit_required: true|false
- recommended_action: proceed | run_delta_audit | full_reaudit

```json
{{
  "delta_audit": {{
    "version": "1.0",
    "timestamp": "{{ISO datetime}}",
    "repo": "{{repo_name}}",
    "task": "{task}",
    "triggers": [
      {{
        "reason": "dependency_change",
        "summary": "Dependency manifest changed since the last audit",
        "changed_files": ["pyproject.toml"],
        "relevant_modules": [],
        "full_reaudit_recommended": true
      }}
    ],
    "changed_files": [],
    "blocker_updates": [],
    "relevant_modules": [],
    "guardrail_updates": [],
    "ready_to_plan": true,
    "full_reaudit_required": false,
    "recommended_action": "run_delta_audit"
  }}
}}
```
```

Output only the markdown document."""


def _merge_unique(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for group in groups:
        for value in group:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)
    return output


def _parse_iso_timestamp(timestamp: str) -> datetime | None:
    if not timestamp:
        return None
    candidate = timestamp
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _git_changed_files_since(repo_root: Path, since_timestamp: datetime | None) -> list[str]:
    changed: list[str] = []

    if since_timestamp is not None:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "log",
                    "--name-only",
                    "--pretty=format:",
                    f"--after={since_timestamp.isoformat()}",
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                changed.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
        except (subprocess.TimeoutExpired, OSError):
            logger.debug("git log for delta audit failed", exc_info=True)

    try:
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if status.returncode == 0:
            for line in status.stdout.splitlines():
                if len(line) < 4:
                    continue
                changed.append(line[3:].strip())
    except (subprocess.TimeoutExpired, OSError):
        logger.debug("git status for delta audit failed", exc_info=True)

    normalized = [path.replace("\\", "/") for path in changed if path]
    return _merge_unique(normalized)


def _match_high_risk_modules(task: str, high_risk_modules: list[str]) -> list[str]:
    if not task:
        return []
    lowered_task = task.lower()
    matches: list[str] = []
    for module in high_risk_modules:
        parts = [part for part in module.replace("\\", "/").split("/") if part]
        tokens = [module.lower(), Path(module).stem.lower(), *[part.lower() for part in parts]]
        if any(token and token in lowered_task for token in tokens):
            matches.append(module)
    return _merge_unique(matches)


def _match_changed_high_risk_modules(
    changed_files: list[str],
    high_risk_modules: list[str],
) -> list[str]:
    matches: list[str] = []
    normalized_changes = [item.replace("\\", "/").lower() for item in changed_files]
    for module in high_risk_modules:
        module_norm = module.replace("\\", "/").lower()
        module_stem = Path(module).stem.lower()
        if any(
            module_norm in changed
            or changed.endswith(module_norm)
            or changed.endswith(f"/{module_stem}.py")
            or module_stem in changed
            for changed in normalized_changes
        ):
            matches.append(module)
    return _merge_unique(matches)


def detect_delta_triggers(
    audit_result: AuditResult,
    *,
    task: str = "",
    review_feedback: str = "",
    failure_details: str = "",
    changed_files: list[str] | None = None,
) -> list[DeltaTrigger]:
    """Detect reasons to run a targeted delta audit."""

    audit_timestamp = _parse_iso_timestamp(audit_result.timestamp)
    repo_root = audit_result.repo_root or Path.cwd()
    actual_changed_files = changed_files or _git_changed_files_since(repo_root, audit_timestamp)

    triggers: list[DeltaTrigger] = []

    dependency_changes = [
        path for path in actual_changed_files
        if Path(path).name in _DEPENDENCY_FILES
    ]
    if dependency_changes:
        triggers.append(
            DeltaTrigger(
                reason="dependency_change",
                summary="Dependency surface changed since the last audit",
                changed_files=dependency_changes,
                full_reaudit_recommended=True,
            )
        )

    instruction_changes = [
        path for path in actual_changed_files
        if path in _INSTRUCTION_FILES
        or path.startswith(".github/instructions/")
        and path.endswith(".instructions.md")
    ]
    if instruction_changes:
        triggers.append(
            DeltaTrigger(
                reason="instruction_change",
                summary="Repository instructions changed since the last audit",
                changed_files=instruction_changes,
                full_reaudit_recommended=True,
            )
        )

    changed_high_risk = _match_changed_high_risk_modules(
        actual_changed_files,
        audit_result.high_risk_modules,
    )
    if changed_high_risk:
        triggers.append(
            DeltaTrigger(
                reason="high_risk_module_changed",
                summary="A high-risk module changed since the last audit",
                changed_files=actual_changed_files,
                relevant_modules=changed_high_risk,
            )
        )

    task_high_risk = _match_high_risk_modules(task, audit_result.high_risk_modules)
    if task_high_risk:
        triggers.append(
            DeltaTrigger(
                reason="high_risk_plan",
                summary="The requested plan touches modules marked high risk",
                relevant_modules=task_high_risk,
            )
        )

    if review_feedback.strip():
        triggers.append(
            DeltaTrigger(
                reason="bad_review",
                summary="A reviewer requested changes and the plan needs targeted re-audit",
            )
        )

    if failure_details.strip():
        triggers.append(
            DeltaTrigger(
                reason="stuck",
                summary="Execution got stuck and needs troubleshooting before planning continues",
            )
        )

    return triggers


def collect_delta_context(
    audit_result: AuditResult,
    *,
    task: str = "",
    review_feedback: str = "",
    failure_details: str = "",
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    """Collect trigger context for a delta audit."""

    audit_timestamp = _parse_iso_timestamp(audit_result.timestamp)
    repo_root = audit_result.repo_root or Path.cwd()
    actual_changed_files = changed_files or _git_changed_files_since(repo_root, audit_timestamp)
    triggers = detect_delta_triggers(
        audit_result,
        task=task,
        review_feedback=review_feedback,
        failure_details=failure_details,
        changed_files=actual_changed_files,
    )
    relevant_modules = _merge_unique(
        *[trigger.relevant_modules for trigger in triggers],
        audit_result.high_risk_modules[:3] if any(trigger.reason == "bad_review" for trigger in triggers) else [],
    )
    full_reaudit_required = any(trigger.full_reaudit_recommended for trigger in triggers)
    recommended_action = (
        "full_reaudit"
        if full_reaudit_required
        else "run_delta_audit"
        if triggers
        else "proceed"
    )

    return {
        "task": task,
        "review_feedback": review_feedback,
        "failure_details": failure_details,
        "changed_files": actual_changed_files,
        "triggers": triggers,
        "relevant_modules": relevant_modules,
        "full_reaudit_required": full_reaudit_required,
        "recommended_action": recommended_action,
    }


def _default_guardrail_updates(context: dict[str, Any]) -> list[str]:
    guardrails: list[str] = []
    for trigger in context["triggers"]:
        if trigger.reason == "dependency_change":
            guardrails.append("Re-verify runtime contracts and installs after dependency changes.")
        elif trigger.reason == "instruction_change":
            guardrails.append("Re-read repository instruction files before planning.")
        elif trigger.reason == "high_risk_plan":
            guardrails.append("Touch high-risk modules only with explicit verification commands.")
        elif trigger.reason == "bad_review":
            guardrails.append("Address reviewer findings before approving any new plan.")
        elif trigger.reason == "stuck":
            guardrails.append("Do not continue planning until the failure mode is understood.")
    return _merge_unique(guardrails)


def _default_blocker_updates(context: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if context["full_reaudit_required"]:
        blockers.append("A full re-audit is required before planning can continue.")
    for trigger in context["triggers"]:
        if trigger.reason == "bad_review":
            blockers.append("Reviewer feedback must be incorporated before execution.")
        elif trigger.reason == "stuck":
            blockers.append("Execution failure details require targeted troubleshooting.")
    return _merge_unique(blockers)


def _parse_delta_json(markdown: str) -> dict[str, Any]:
    marker = "```json"
    start = markdown.find(marker)
    if start == -1:
        return {}
    start = markdown.find("{", start)
    end = markdown.find("```", start)
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(markdown[start:end].strip())
    except json.JSONDecodeError:
        return {}


def _build_delta_result(
    audit_result: AuditResult,
    context: dict[str, Any],
    evidence_summary: str,
    markdown: str,
) -> DeltaAuditResult:
    parsed = _parse_delta_json(markdown)
    block = parsed.get(_DELTA_JSON_KEY, {})

    triggers = []
    if block.get("triggers"):
        for raw in block["triggers"]:
            triggers.append(
                DeltaTrigger(
                    reason=raw.get("reason", "manual"),
                    summary=raw.get("summary", ""),
                    changed_files=raw.get("changed_files", []),
                    relevant_modules=raw.get("relevant_modules", []),
                    full_reaudit_recommended=raw.get("full_reaudit_recommended", False),
                )
            )
    else:
        triggers = context["triggers"]

    blocker_updates = _merge_unique(
        block.get("blocker_updates", []),
        _default_blocker_updates(context),
    )
    relevant_modules = _merge_unique(
        block.get("relevant_modules", []),
        context["relevant_modules"],
    )
    guardrail_updates = _merge_unique(
        block.get("guardrail_updates", []),
        _default_guardrail_updates(context),
    )

    full_reaudit_required = bool(
        block.get("full_reaudit_required", context["full_reaudit_required"])
    )
    ready_to_plan = bool(block.get("ready_to_plan", not full_reaudit_required))
    if full_reaudit_required:
        ready_to_plan = False

    recommended_action = block.get(
        "recommended_action",
        "full_reaudit" if full_reaudit_required else context["recommended_action"],
    )

    return DeltaAuditResult(
        version=block.get("version", "1.0"),
        timestamp=block.get("timestamp", audit_result.timestamp),
        repo=block.get("repo", audit_result.repo),
        task=context["task"],
        triggers=triggers,
        changed_files=context["changed_files"],
        blocker_updates=blocker_updates,
        relevant_modules=relevant_modules,
        guardrail_updates=guardrail_updates,
        ready_to_plan=ready_to_plan,
        full_reaudit_required=full_reaudit_required,
        recommended_action=recommended_action,
        markdown_content=markdown,
    )


def _delta_output_paths(base_output_path: Path) -> tuple[Path, Path]:
    markdown_path = base_output_path.with_name("AUDIT_DELTA.md")
    json_path = base_output_path.with_name("AUDIT_DELTA.json")
    return markdown_path, json_path


def _write_delta_artifacts(output_path: Path, result: DeltaAuditResult) -> None:
    markdown_path, json_path = _delta_output_paths(output_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(result.markdown_content, encoding="utf-8")
    json_path.write_text(result.to_json_block() + "\n", encoding="utf-8")


async def run_delta_audit(
    audit_result: AuditResult,
    config: AuditConfig,
    *,
    task: str = "",
    review_feedback: str = "",
    failure_details: str = "",
    changed_files: list[str] | None = None,
) -> DeltaAuditResult | None:
    """Run a targeted delta audit when triggers indicate it is needed."""

    context = collect_delta_context(
        audit_result,
        task=task,
        review_feedback=review_feedback,
        failure_details=failure_details,
        changed_files=changed_files,
    )
    if not context["triggers"]:
        return None

    evidence = collect_audit_evidence(config.repo_root)
    evidence_summary = summarize_evidence_for_prompt(evidence)
    trigger_summary = "\n".join(
        f"- {trigger.reason}: {trigger.summary}" for trigger in context["triggers"]
    )
    changed_files_text = "\n".join(f"- {path}" for path in context["changed_files"]) or "- (none)"
    relevant_modules_text = "\n".join(f"- {module}" for module in context["relevant_modules"]) or "- (none)"
    prompt = _DELTA_PROMPT.format(
        task=task or "(no explicit task)",
        trigger_summary=trigger_summary or "- manual delta audit",
        changed_files=changed_files_text,
        relevant_modules=relevant_modules_text,
        review_feedback=review_feedback or "(none)",
        failure_details=failure_details or "(none)",
        evidence_summary=evidence_summary,
    )

    system_prompt = (
        "You are a targeted delta-audit specialist. "
        "You review what changed since the last audit and decide whether planning can proceed, "
        "whether a full re-audit is required, and which guardrails must be updated. "
        "Do not restate the whole repository audit. Focus only on changed surfaces and planning impact."
    )

    markdown = await call_llm(system_prompt, prompt, config)
    result = _build_delta_result(audit_result, context, evidence_summary, markdown.strip())
    _write_delta_artifacts(config.output_path, result)
    return result
