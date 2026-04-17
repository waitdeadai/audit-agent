"""Plan runner — task decomposition informed by audit findings.

The plan runner takes an audit result and a task, then produces an ordered
set of implementation stories (PLAN.md) respecting the audit's risk map,
dependency ordering, and guardrails.

SOTA 2026 patterns integrated from ForgeGod + Claude Code:
- Audit-informed story decomposition (risk map → story ordering)
- Repo-backlog seeding (respect existing docs/STORIES.md)
- Verification commands per story (testable completion criteria)
- Guardrails from security findings + non-goals
- Adversarial plan review (second model critiques plan before writing)
- Dependency-ordered execution (risk graph → topological sort)
- Effort-gated story sizing (audit §10 → min_drafts level)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .audit_config import AuditConfig, PlanConfig
from .audit_result import AuditResult, PlanResult, PlanStory
from .audit_runner import call_llm

logger = logging.getLogger("audit_agent.plan_runner")

# ── Repo doc loading ──────────────────────────────────────────────────────────

_REPO_DOC_CANDIDATES = [
    "docs/STORIES.md",
    "docs/PRD.md",
    "docs/ARCHITECTURE.md",
    "docs/DESIGN.md",
    "docs/RUNBOOK.md",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
]


def _load_repo_docs(repo_root: Path, max_chars: int = 4000) -> dict[str, str]:
    """Load bounded repo docs for planning context."""
    remaining = max_chars
    docs: dict[str, str] = {}

    for rel_path in _REPO_DOC_CANDIDATES:
        if remaining <= 0:
            break
        path = repo_root / rel_path
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if not text:
            continue
        snippet = text[:remaining]
        docs[rel_path] = snippet
        remaining -= len(snippet)

    return docs


def _parse_existing_stories(stories_md: str) -> list[dict[str, Any]]:
    """Parse docs/STORIES.md into story dicts for seeding."""
    if not stories_md.strip():
        return []

    stories: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    milestone = ""

    for raw_line in stories_md.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("## "):
            milestone = line[3:].strip()
            continue

        match = re.match(r"^###\s+([A-Z]\d{3,})\s*-\s*(.+)$", line)
        if match:
            if current:
                stories.append(current)
            story_id, title = match.groups()
            current = {
                "id": story_id,
                "title": title.strip(),
                "description": (f"{milestone}: {title.strip()}" if milestone else title.strip()),
                "acceptance_criteria": [],
                "status": "todo",
            }
            continue

        if current is None:
            continue

        if line.startswith("- "):
            current["acceptance_criteria"].append(line[2:].strip())

    if current:
        stories.append(current)

    return stories


# ── Guardrail extraction ─────────────────────────────────────────────────────

def _extract_guardrails(
    audit_result: AuditResult,
    repo_docs: dict[str, str],
) -> list[str]:
    """Build guardrails from audit findings + repo non-goals."""
    guardrails: list[str] = []

    # From audit blockers (CRITICAL security issues)
    for blocker in audit_result.blockers:
        if any(
            keyword in blocker.upper()
            for keyword in ["SECURITY", "CRITICAL", "HARDCODE", "SECRET", "INJECTION"]
        ):
            guardrails.append(f"BLOCKED: {blocker}")

    # From high-risk modules — changes here require extra verification
    for module in audit_result.high_risk_modules:
        guardrails.append(f"HIGH-RISK module {module}: extra verification required")

    # From taste pre-flight failures
    for failure in audit_result.taste_pre_flight_failures:
        guardrails.append(f"TASTE constraint: {failure}")

    # From repo non-goals in PRD.md and ARCHITECTURE.md
    non_goal_markers = ["## v1 Non-Goals", "## Non-Goals", "## Constraints"]
    for doc_name, doc_text in repo_docs.items():
        for marker in non_goal_markers:
            if marker in doc_text:
                capture = False
                for line in doc_text.splitlines():
                    if line.strip() == marker:
                        capture = True
                        continue
                    if capture:
                        if line.startswith("#"):
                            break
                        if line.startswith("- "):
                            guardrails.append(f"Non-goal: {line[2:].strip()}")

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for g in guardrails:
        normalized = g.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)

    return deduped


# ── Plan prompt building ──────────────────────────────────────────────────────

def _build_plan_prompt(
    task: str,
    audit_result: AuditResult,
    repo_docs: dict[str, str],
    existing_stories: list[dict[str, Any]],
    guardrails: list[str],
    config: PlanConfig,
) -> str:
    """Build the planning prompt using audit context."""
    effort_level = audit_result.effort_level or "thorough"

    # Build risk context from audit
    risk_context_parts = []
    if audit_result.high_risk_modules:
        risk_context_parts.append(
            "HIGH-RISK modules (touch carefully, require extra verification):\n  " +
            "\n  ".join(f"- {m}" for m in audit_result.high_risk_modules)
        )
    if audit_result.recommended_start_points:
        risk_context_parts.append(
            "Recommended start points (safest modules to begin with):\n  " +
            "\n  ".join(f"- {s}" for s in audit_result.recommended_start_points)
        )
    risk_context = "\n\n".join(risk_context_parts) if risk_context_parts else "No specific high-risk modules identified."

    # Build repo backlog seed
    backlog_seed = ""
    if existing_stories:
        lines = ["Existing story backlog (preserve IDs and order):"]
        for s in existing_stories:
            lines.append(f"- {s['id']}: {s['title']}")
            for ac in s.get("acceptance_criteria", []):
                lines.append(f"  ✓ {ac}")
        backlog_seed = "\n\n".join(lines)
    else:
        backlog_seed = "(no existing story backlog found)"

    # Build repo docs context
    docs_context_parts = []
    for name, content in repo_docs.items():
        snippet = content[:1500]
        docs_context_parts.append(f"=== {name} ===\n{snippet}")
    docs_context = "\n\n".join(docs_context_parts) if docs_context_parts else "(no repo docs found)"

    # Build guardrails
    guardrails_text = "\n".join(f"- {g}" for g in guardrails) if guardrails else "(no specific guardrails)"

    # Effort-based story sizing
    effort_hints = {
        "trivial": "Stories should be 1-2 files, <30 lines of code, 5-10 min work.",
        "low": "Stories should be 1-3 files, single module, 15-30 min work.",
        "medium": "Stories should be 1-5 files, touching 1-2 modules, 30-60 min work.",
        "high": "Stories should be 3-10 files, multi-module, 60-120 min work.",
        "exhaustive": "Stories should be scoped carefully — large refactors may need to be split.",
    }
    story_size_hint = effort_hints.get(effort_level, effort_hints["medium"])

    return f"""You are a senior software architect. Decompose a task into ordered, independently-executable stories.

## TASK
{task}

## AUDIT FINDINGS (source of truth — respect these)
{risk_context}

## EFFORT LEVEL: {effort_level}
{story_size_hint}

## EXISTING BACKLOG (preserve IDs and order — add new stories after existing ones)
{backlog_seed}

## GUARDRAILS (never do these — they are hard constraints)
{guardrails_text}

## REPOSITORY DOCS (follow these — they define project scope)
{docs_context}

---

## OUTPUT FORMAT

Produce a PLAN.md with this exact structure:

```markdown
# PLAN.md
**Repo:** {{repo_name}} · **Generated:** {{ISO_date}} · **Task:** {task[:50]}...
**Effort:** {effort_level} · **Stories:** N

---

## Task Summary
Brief description of what this plan achieves.

## Guardrails
- each guardrail as a bullet

## Stories (ordered by dependency — prerequisite stories first)

### S001 — Story Title
**Priority:** 1 (1=highest)
**Depends on:** (none, or list of story IDs)
**Effort:** low|medium|high|exhaustive
**Risk:** low|medium|high
**Modules:** comma-separated list

**What:** Description of what to implement (1-3 sentences).

**Acceptance Criteria:**
- Criterion 1 (testable)
- Criterion 2 (testable)

**Verification Commands:**
```bash
# Commands that prove this story is done
pytest tests/test_file.py -q
ruff check src/module
```

---

```json
{{
  "plan_agent": {{
    "version": "1.0",
    "timestamp": "{{ISO datetime}}",
    "repo": "{{repo_name}}",
    "task": "{task}",
    "stories": [
      {{
        "id": "S001",
        "title": "Story Title",
        "priority": 1,
        "depends_on": [],
        "effort": "low",
        "risk": "low",
        "modules_touched": ["module_a"],
        "blocked_by": [],
        "acceptance_criteria": ["Criterion 1", "Criterion 2"],
        "verification_commands": ["pytest tests/test_file.py -q"]
      }}
    ],
    "guardrails": [],
    "effort_level": "{effort_level}",
    "ready_to_execute": true,
    "blockers": [],
    "high_risk_modules": [],
    "recommended_start": "S001"
  }}
}}
```

---

## RULES
- Order stories by dependency: a story that is a prerequisite must come before stories that depend on it
- Use the audit risk map to order HIGH-RISK module changes LAST
- Each story must have VERIFICATION COMMANDS that prove it is done
- Keep stories small: target 30-60 min of work each at most
- Maximum {config.max_stories} stories total
- Story IDs: continue from existing backlog (S001, S002...) or start from S001
- If existing backlog defines a story that matches the task, do NOT duplicate it — reference it
- Guardrails are hard constraints — do not create stories that violate them
- If ready_to_execute should be false, set it and explain blockers in the JSON block

Output ONLY the plan markdown — no preamble, no explanation."""


# ── Review prompt building ───────────────────────────────────────────────────

def _build_review_prompt(plan_markdown: str, task: str) -> str:
    """Build adversarial review prompt for plan critique."""
    return f"""You are an adversarial reviewer. Critique this implementation plan ruthlessly.

## TASK
{task}

## PLAN TO REVIEW
{plan_markdown}

---

## REVIEW DIMENSIONS

Rate each dimension 0-10 and list specific issues:

1. **Completeness** — Does the plan cover everything in the task? Are there gaps?
2. **Dependency ordering** — Are prerequisite stories correctly ordered? Could parallel tracks be parallelized?
3. **Story sizing** — Are stories small enough to be independently executable? Are any too large?
4. **Acceptance criteria quality** — Are criteria specific and testable? Are any vague or missing?
5. **Verification commands** — Do the verification commands actually prove completion? Are any missing or wrong?
6. **Guardrail compliance** — Does the plan violate any guardrails?
7. **Risk management** — Are high-risk modules handled appropriately? Is the ordering safe?
8. **Missing stories** — What stories are missing that should exist?

---

## OUTPUT FORMAT

```markdown
## Review

| Dimension | Score | Issues |
|---|---|---|
| Completeness | /10 | ... |
| Dependency ordering | /10 | ... |
| ... | ... | ... |

## Verdict
APPROVE / REVISE / REJECT

## Required Changes
1. ...
2. ...
```

Output ONLY the review markdown — no preamble."""


# ── Plan parsing ─────────────────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def _extract_json_block(text: str) -> dict[str, Any]:
    """Extract and parse the JSON block from plan output."""
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: find any {...} containing plan_agent
    start = text.find('"plan_agent"')
    if start == -1:
        start = text.find("'plan_agent'")
    if start != -1:
        depth = 0
        for i in range(start - 1, -1, -1):
            if text[i] == "}":
                depth += 1
            elif text[i] == "{":
                depth -= 1
                if depth <= 0:
                    start = i
                    break
        # Walk forward
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
                        break

    return {}


def _config_with_runtime_overrides(
    config: AuditConfig,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AuditConfig:
    """Clone config with per-pass overrides for planning and review."""

    updates: dict[str, Any] = {}
    if model is not None:
        updates["model"] = model
    if temperature is not None:
        updates["temperature"] = temperature
    if max_tokens is not None:
        updates["max_tokens"] = max_tokens
    if not updates:
        return config
    return config.model_copy(update=updates)


def _parse_stories_from_json(json_block: dict[str, Any]) -> list[PlanStory]:
    """Parse stories from the plan JSON block."""
    plan_agent = json_block.get("plan_agent", {})
    stories_data = plan_agent.get("stories", [])

    if not stories_data:
        return []

    stories: list[PlanStory] = []
    for s in stories_data:
        stories.append(
            PlanStory(
                id=s.get("id", f"S{len(stories)+1:03d}"),
                title=s.get("title", "Untitled"),
                description=s.get("description", ""),
                priority=s.get("priority", len(stories) + 1),
                depends_on=s.get("depends_on", []),
                acceptance_criteria=s.get("acceptance_criteria", []),
                verification_commands=s.get("verification_commands", []),
                effort=s.get("effort", "medium"),
                risk=s.get("risk", "low"),
                modules_touched=s.get("modules_touched", []),
                blocked_by=s.get("blocked_by", []),
            )
        )
    return stories


# ── Main plan runner ─────────────────────────────────────────────────────────

async def run_plan(
    audit_result: AuditResult,
    task: str,
    config: AuditConfig,
) -> PlanResult:
    """Run the audit+plan pipeline.

    1. Load repo docs
    2. Extract guardrails from audit + repo
    3. Seed existing stories from docs/STORIES.md
    4. Build planning prompt with audit context
    5. Call LLM to generate plan
    6. Optionally review with second model
    7. Parse and write PLAN.md
    8. Return PlanResult

    Returns PlanResult regardless of plan quality — caller checks ready_to_execute.
    """
    plan_config = config.plan
    if plan_config is None:
        plan_config = PlanConfig()

    repo_root = audit_result.repo_root or config.repo_root
    repo_docs = _load_repo_docs(repo_root)

    # Seed from existing backlog
    existing_stories = _parse_existing_stories(repo_docs.get("docs/STORIES.md", ""))

    # Build guardrails
    guardrails = _extract_guardrails(audit_result, repo_docs)

    # ── Phase 1: Generate plan ────────────────────────────────────────────
    logger.info("Planning phase 1: generating stories for task: %s", task[:80])

    prompt = _build_plan_prompt(
        task=task,
        audit_result=audit_result,
        repo_docs=repo_docs,
        existing_stories=existing_stories,
        guardrails=guardrails,
        config=plan_config,
    )

    system_prompt = (
        "You are a senior software architect with deep expertise in code design, "
        "dependency management, and incremental implementation. You produce precise, "
        "testable, small stories. You NEVER skip the verification commands. "
        "You ALWAYS respect guardrails and risk maps."
    )

    planning_config = _config_with_runtime_overrides(
        config,
        temperature=plan_config.temperature,
        max_tokens=plan_config.max_tokens,
    )
    llm_output = await call_llm(system_prompt, prompt, planning_config)

    # ── Phase 2: Parse plan ───────────────────────────────────────────────
    json_block = _extract_json_block(llm_output)
    plan_agent_block = json_block.get("plan_agent", {})

    stories = _parse_stories_from_json(json_block)

    # Build the full markdown (append JSON block if not at end)
    full_plan_md = llm_output.strip()
    if not full_plan_md.rstrip().endswith("}"):
        full_plan_md += "\n\n" + json.dumps({"plan_agent": plan_agent_block}, indent=2)

    # ── Phase 3: Adversarial review (optional) ────────────────────────────
    if plan_config.auto_review and stories:
        logger.info("Planning phase 2: adversarial review")

        review_system = (
            "You are an expert code reviewer and architect. You are adversarial "
            "but constructive. You catch gaps, missing verifications, and ordering mistakes."
        )

        review_prompt = _build_review_prompt(full_plan_md, task)
        review_config = _config_with_runtime_overrides(
            config,
            model=plan_config.reviewer_model,
            temperature=plan_config.review_temperature,
            max_tokens=plan_config.max_tokens,
        )
        review_output = await call_llm(review_system, review_prompt, review_config)

        # Append review to plan markdown
        full_plan_md += "\n\n---\n\n## Plan Review\n" + review_output.strip()

        # Check verdict
        verdict_upper = review_output.upper()
        if "REJECT" in verdict_upper:
            logger.warning("Plan review: REJECT — plan has serious issues")
        elif "REVISE" in verdict_upper:
            logger.info("Plan review: REVISE — plan needs changes")
        else:
            logger.info("Plan review: APPROVE")

    # ── Phase 4: Build result ─────────────────────────────────────────────
    plan_agent_block = json_block.get("plan_agent", {})
    blockers = list(plan_agent_block.get("blockers", []))
    # Promote audit blockers to plan blockers if they affect execution
    for ab in audit_result.blockers:
        if ab not in blockers:
            blockers.append(f"[audit] {ab}")

    result = PlanResult(
        version="1.0",
        timestamp=audit_result.timestamp,
        repo=audit_result.repo,
        task=task,
        stories=stories,
        guardrails=plan_agent_block.get("guardrails", guardrails),
        effort_level=plan_agent_block.get("effort_level", audit_result.effort_level),
        ready_to_execute=(
            bool(stories)
            and len(blockers) == 0
            and plan_agent_block.get("ready_to_execute", True)
        ),
        blockers=blockers,
        high_risk_modules=audit_result.high_risk_modules,
        recommended_start=plan_agent_block.get("recommended_start", stories[0].id if stories else ""),
        markdown_content=full_plan_md,
    )

    # ── Phase 5: Write PLAN.md ────────────────────────────────────────────
    output_path = plan_config.output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_plan_md, encoding="utf-8")
    logger.info("Wrote PLAN.md to %s", output_path)

    return result
