# Audit-Agent Evolution Plan (Research-Backed, 2026-04-17)

## Goal

Turn `audit-agent` into a first-class repo-entry and pre-plan gate for ForgeGod:

- strong on first contact with a new repository
- cheap and deterministic on repeated runs
- able to re-audit before risky plans
- able to feed planners, reviewers, and execution loops with structured evidence

This document is based on current 2026 primary sources and mapped against the current `audit-agent` codebase.

---

## Executive Summary

The strongest 2026 pattern is not "one giant audit prompt."

The strongest pattern is:

1. deterministic local scanners and repo mapping first
2. instruction/context ingestion second
3. LLM synthesis third
4. targeted re-audits before risky planning or after failures
5. specialist subagents only where they reduce context pressure or improve precision
6. layered guardrails and evals everywhere

For this repo specifically, the highest-value upgrade is to make `audit-agent` a hybrid pipeline:

- local scanners produce structured facts
- a repo map compresses codebase shape
- instruction files are ingested explicitly
- the LLM writes the final audit narrative from evidence, not from a coarse file tree alone

That is the clearest path from "interesting auditor" to "one of the strongest parts of the engine."

---

## What 2026 Sources Say

### 1. Start simple, then specialize

OpenAI's practical guide still recommends starting with the simplest working agent shape and using evals to decide when more complexity is justified. It also frames multi-agent orchestration around clear specialization, manager patterns, and explicit handoffs rather than vague agent swarms.

Implication for `audit-agent`:

- keep one main audit orchestrator
- add specialist passes only for narrow jobs
- do not split into many LLM agents before deterministic evidence collection is wired in

### 2. Manager pattern is the right default for audit orchestration

OpenAI's agent guide and Agents SDK docs support a central manager that calls specialized agents as tools, plus handoff input filters when context must be trimmed. LangGraph's supervisor package reinforces the same architecture: one supervisor, multiple specialists, controlled message flow.

Implication for `audit-agent`:

- `audit-agent` should remain the manager
- security, dependency, architecture, and plan-risk specialists should be subordinate surfaces
- each specialist should receive only the relevant evidence bundle

### 3. Hooks are ideal for repo-entry and pre-plan gates

Claude Code's hooks model is highly relevant here. `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `SubagentStart`, and `SubagentStop` are built exactly for "inject context", "block risky actions", and "run automatic checks before work continues."

Implication for ForgeGod:

- run a repo-entry audit trigger on session start or first repo attach
- run a pre-plan delta audit before story planning
- run targeted troubleshooting audits after bad reviews or repeated failures

### 4. Memory should store stable project rules, not everything

Claude Code's memory guidance separates durable project instructions (`CLAUDE.md`) from automatic memory, and points to path-specific rules for large repos. GitHub Copilot similarly supports repository-wide instructions and path-specific instruction files under `.github/instructions/`.

Implication for `audit-agent`:

- ingest repo instructions as first-class audit inputs
- prioritize:
  - `AGENTS.md`
  - `CLAUDE.md`
  - `.github/copilot-instructions.md`
  - `.github/instructions/*.instructions.md`
  - `GEMINI.md`
- do not rely on raw prompt memory alone

### 5. Skills/commands should be composable and scoped

Claude Code merged custom commands into skills and supports nested discovery for monorepos. That is a strong signal for keeping reusable audit behaviors as small, composable, discoverable units.

Implication for `audit-agent`:

- separate repo-entry audit, delta audit, security audit, and plan audit into distinct reusable surfaces
- monorepo packages should be able to carry path-local audit rules

### 6. Repo maps are now table stakes for large-codebase comprehension

Aider's repository map is still one of the clearest practical references: compress the codebase into symbols and high-signal structure, then size the map dynamically to the token budget. This is far more useful than dumping a flat file tree.

Implication for `audit-agent`:

- replace "file tree only" prompting with a repo map
- rank important files/modules by graph centrality and symbol relevance
- feed the LLM a bounded, high-signal structural map

### 7. Separate reasoning from editing or implementation when needed

Aider's architect/editor split is a strong precedent: reasoning and final action formatting often benefit from separation. For auditing, the analogous split is "evidence gathering" then "judgment/synthesis."

Implication for `audit-agent`:

- deterministic scanners gather evidence
- the LLM synthesizes findings, constraints, and recommendations
- optional reviewer critiques the audit or plan only after evidence exists

### 8. Security scanning should not be LLM-only

OpenAI's guide explicitly recommends layered guardrails, combining rules-based protections with model-based checks. Semgrep's 2026 agent plugin goes further: MCP + hooks + skills + automatic rescanning on generated files.

Implication for `audit-agent`:

- security findings should come from deterministic scanners first
- LLMs can explain severity, ordering, and remediation impact
- for production mode, Semgrep-backed scans should be optional but first-class

### 9. Evals are not optional

OpenAI's guidance is explicit: establish evals first, then optimize cost and latency. For an auditor, this means checking extraction quality, blocker detection, risk ranking, and trigger decisions.

Implication for `audit-agent`:

- "looks good" is not enough
- we need audit-specific evals before calling the component hardened

---

## What The Current Repo Already Has

Current strengths in this repo:

- a usable CLI surface: `audit run`, `audit status`, `audit diff`, `audit plan`
- a real planning flow with adversarial review hooks
- scanner modules for architecture, dependencies, health, tests, security, risk, taste, effort, and planning constraints
- ForgeGod bridge, MCP server, and taste/effort integration surfaces

Files worth noting:

- `src/audit_agent/core/audit_runner.py`
- `src/audit_agent/core/plan_runner.py`
- `src/audit_agent/scanners/`
- `src/audit_agent/integration/`

---

## The Main Gap Right Now

The repo already contains many local scanners, but the live audit path is still mostly a one-shot LLM synthesis path.

`run_audit()` currently builds:

- a file tree
- a small key-file bundle
- a single user prompt

and then asks the model to produce `AUDIT.md`.

That means the strongest deterministic work in `src/audit_agent/scanners/` is not yet the backbone of the runtime audit pipeline.

This is the biggest architecture gap in the package today.

If we want SOTA 2026 behavior, the scanners need to be promoted from "nice side modules" to "the evidence engine."

---

## Recommended Target Architecture

## 1. Repo-Entry Audit Pipeline

Trigger:

- first entry into a repo
- missing audit
- stale audit
- repo attached to a new session

Pipeline:

1. Collect repo metadata
2. Ingest instruction files
3. Build repo map
4. Run deterministic scanners
5. Build structured evidence bundle
6. Ask the LLM to synthesize `AUDIT.md` from evidence
7. Emit machine-readable artifacts

Outputs:

- `.forgegod/AUDIT.md`
- `.forgegod/AUDIT.json`
- `.forgegod/AUDIT_EVIDENCE.json`

Why:

- the markdown is for humans
- the JSON is for planners/reviewers/workflows
- the evidence artifact is for debugging and evals

## 2. Pre-Plan Delta Audit

Do not run the full audit before every plan.

Instead, run a cheaper delta audit when:

- dependencies changed
- instructions changed
- a high-risk module is about to be touched
- the previous review failed
- the agent got stuck
- the last audit is stale beyond a threshold

Delta audit inputs:

- git diff since last audit
- touched files/modules
- plan intent or user task
- last review feedback

Delta audit outputs:

- changed risk areas
- newly relevant guardrails
- whether full re-audit is required
- plan-specific blocker list

This is the right balance between rigor and latency.

## 3. Specialist Audit Surfaces

Recommended specialists:

- `security-audit`
  - deterministic first
  - optional Semgrep-backed pass
- `architecture-audit`
  - module graph, fan-in, circular imports, load-bearing walls
- `dependency-audit`
  - runtime vs dev, abandoned packages, version risk, supply chain flags
- `plan-risk-audit`
  - given a proposed plan, check whether it violates current guardrails

These should be subordinate to the main audit manager, not user-facing chaos.

## 4. Instruction Ingestion Layer

The auditor should ingest and normalize repo instructions across ecosystems:

- `AGENTS.md`
- `CLAUDE.md`
- `.github/copilot-instructions.md`
- `.github/instructions/*.instructions.md`
- `GEMINI.md`
- local project docs like `docs/ARCHITECTURE.md`, `CONTRIBUTING.md`, `RUNBOOK.md`

The key is to convert them into structured policy buckets:

- architecture rules
- code-style rules
- test/verification rules
- security/compliance rules
- non-goals and product constraints

Then the LLM synthesizer works from those normalized rules, not from arbitrary markdown blobs.

## 5. Repo Map Layer

Replace the flat file tree prompt with a repo map containing:

- top-level packages and entry points
- key symbols and signatures
- high fan-in modules
- risk-ranked modules
- test ownership hints
- instruction-bearing files

This map should be token-budgeted and dynamic.

For very large repos:

- summary map for entry
- path-local expansions only when needed

## 6. Review-Aware Re-Audits

The auditor should not only run on repo entry.

It should also trigger when:

- an adversarial reviewer returns `REVISE` or `REJECT`
- the executor hits repeated failures
- the task touches modules marked high risk
- a plan crosses architecture boundaries

This turns the auditor into a troubleshooting brain, not just a bootstrap checklist.

## 7. Security Guardrail Mode

For serious production use:

- local scanner checks on every generated diff
- optional Semgrep plugin/rules pass
- hard blocking if secrets, command injection, or dangerous shell patterns appear

This should be configurable:

- `off`
- `warn`
- `block`

---

## Skills And Command Design

Recommended audit surfaces inside ForgeGod:

- `audit-entry`
  - full repo-entry audit
- `audit-delta`
  - targeted re-audit before planning or after failures
- `audit-plan`
  - plan-specific risk check
- `audit-security`
  - deterministic + Semgrep-backed security scan
- `audit-context`
  - instruction ingestion and repo map refresh

Do not overload one giant skill with all behaviors.

Make the surfaces explicit and composable.

---

## What To Build First

## Implementation Status

As of 2026-04-17, this repo has completed the four phases below:

- Phase 1: hybrid evidence-driven runtime
- Phase 2: delta-audit trigger intelligence
- Phase 3: specialist audit surfaces
- Phase 4: offline eval harness

The remaining work after this point is iterative refinement, stricter eval cases, and wider real-world validation, not missing core architecture.

### Phase 1: Make Runtime Hybrid

Highest-priority implementation:

1. Wire scanner outputs into the live audit runtime
2. Emit `AUDIT.json` and `AUDIT_EVIDENCE.json`
3. Add repo-map generation
4. Normalize instruction ingestion

This is the foundation.

### Phase 2: Add Trigger Intelligence

Then implement:

1. repo-entry trigger
2. stale trigger
3. dependency-change trigger
4. bad-review trigger
5. stuck trigger
6. high-risk-plan trigger

### Phase 3: Add Specialist Audit Surfaces

Only after the hybrid core is working:

1. `security-audit`
2. `plan-risk-audit`
3. `architecture-audit`

### Phase 4: Add Eval Harness

Must-have eval buckets:

- repo snapshot correctness
- instruction ingestion correctness
- blocker detection precision
- high-risk module ranking quality
- safest-start recommendations
- delta-audit trigger correctness
- false-positive rate on small repos

---

## What Not To Do

- Do not keep the auditor as a pure "LLM reads file tree and improvises" system
- Do not run a full audit before every single prompt
- Do not turn every scanner into a separate agent before the deterministic core is live
- Do not make security purely prompt-based
- Do not treat project instruction files as optional garnish
- Do not store only markdown when downstream systems need structured audit outputs

---

## Concrete Recommendation For This Repo

If we want the strongest next move, it is this:

1. Promote `src/audit_agent/scanners/` into the primary evidence pipeline
2. Add repo-map generation and instruction ingestion
3. Emit structured audit artifacts alongside markdown
4. Add delta-audit mode before risky planning
5. Add optional Semgrep-backed blocking mode
6. Add evals that measure audit quality, not just code health

That is the cleanest research-backed path to making `audit-agent` one of the most powerful parts of ForgeGod.

---

## Sources

- OpenAI, A practical guide to building agents
  - https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/
  - https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- OpenAI Agents SDK
  - Handoffs: https://openai.github.io/openai-agents-js/guides/handoffs/
  - Handoff API: https://openai.github.io/openai-agents-js/openai/agents/classes/handoff/
  - Tools: https://openai.github.io/openai-agents-js/guides/tools/
  - Guardrails: https://openai.github.io/openai-agents-python/guardrails/
- Anthropic Claude Code
  - Hooks: https://code.claude.com/docs/en/hooks
  - Memory: https://code.claude.com/docs/en/memory
  - Slash commands / skills: https://code.claude.com/docs/en/slash-commands
  - Subagents: https://code.claude.com/docs/en/sub-agents
- GitHub Copilot custom instructions
  - https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions
- Aider
  - Repo map: https://aider.chat/docs/repomap.html
  - Architect/editor split: https://aider.chat/2024/09/26/architect.html
- LangGraph supervisor
  - https://langchain-ai.github.io/langgraphjs/reference/modules/langgraph-supervisor.html
- Semgrep agent plugin / MCP
  - https://semgrep.dev/docs/mcp
  - https://semgrep.dev/docs/
- Gemini CLI
  - https://github.com/google-gemini/gemini-cli
