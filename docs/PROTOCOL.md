# Audit Protocol Reference

The audit-agent follows a strict 11-step protocol to produce `AUDIT.md`. This document is a brief reference — see `src/audit_agent/PROMPT.md` for the full system prompt.

---

## Trigger Conditions

audit-agent triggers automatically when:

1. ForgeGod enters a repo for the first time (no `.forgegod/AUDIT.md` exists)
2. A human says: "audit this repo", "run audit-agent", "audit before you plan"
3. ForgeGod's Ralph Loop is about to plan a new PRD with no current AUDIT.md
4. More than 20 commits have been made since the last AUDIT.md
5. A new dependency was added to `requirements.txt`, `pyproject.toml`, `package.json`
6. A human says: "re-audit" or "refresh audit"

---

## The 11 Steps

### Step 1 — Repo Snapshot (30 seconds max)

Collects:
- Repo name, primary language(s), framework(s)
- Total file count, total line count
- Last commit hash + date
- Package manager and entry point(s)
- Test framework(s)
- CI/CD config
- Presence of AGENTS.md, CLAUDE.md, taste.md, effort.md, .forgegod/config.toml

Output: compact table. No prose.

### Step 2 — Entry Points Map

Maps how the code starts and flows:
- Primary entry point (`cli.py`, `main.py`, `server.py`, `index.ts`, etc.)
- CLI commands and handlers
- API routes and controllers
- Background jobs or loops
- Import graph roots

Output: one line per entry point.

### Step 3 — Architecture Map

Identifies the structural pattern:
- Layered (routes → services → repositories)?
- Domain-driven (bounded contexts)?
- Monolithic, modular monolith, or service-split?
- God modules (one file doing too much)?
- Circular imports?
- Top 5 most-imported internal modules (load-bearing walls)

Output: ASCII diagram + risk-annotated module table.

### Step 4 — Dependency Surface

**4A — External dependencies:**
- Every non-standard-library dependency
- Flags: deprecated, abandoned, typosquat-risk, vulnerable version
- Runtime-critical vs. dev-only

**4B — Internal dependency paths:**
- Top 3 longest import chains
- Modules importing from >5 other internal modules
- Dead code candidates (modules nothing imports)

### Step 5 — Health Indicators

Scans and counts:
- `# TODO`, `# FIXME`, `# HACK`, `# XXX` comments
- Placeholder functions (`pass`, `raise NotImplementedError`, empty bodies)
- Functions longer than 60 lines
- Files longer than 500 lines
- Hardcoded config strings (URLs, credentials, magic numbers)
- Debug leaks (`print()`, `console.log()` in non-CLI code)

Output: counts per category + top 3 worst offenders.

### Step 6 — Test Surface

- Percentage of modules with a corresponding test file
- Test runner configured
- Integration, E2E, or unit-only tests
- Modules with NO test coverage
- Whether tests run in CI
- Count of `skip`/`xfail` tests

Output: coverage table by module category.

### Step 7 — Security Surface

Scans for:
- Hardcoded secrets (API keys, passwords, tokens)
- `eval()`, `exec()`, `subprocess` with shell=True, `os.system()`
- SQL string concatenation (injection risk)
- Path traversal risks
- Abandoned or supply-chain-risk dependencies
- Accidentally committed `.env` files

Output: CRITICAL / WARNING / INFO lists.

### Step 8 — Change Risk Map

For every major module or file cluster:

- **HIGH RISK**: changes will likely break other things; low test coverage; multiple dependencies
- **MEDIUM RISK**: safe if tests pass; watch for interface drift
- **LOW RISK**: isolated, well-tested, or unused

Output: risk table (Module | Risk | Why | Dependencies affected).

### Step 9 — taste-agent Pre-Flight

Flags dimensions most likely to trigger REVISE or REJECT:
- Which taste dimensions already have visible violations
- Naming inconsistencies (snake_case vs camelCase, generic names)
- API response shape inconsistencies
- Layer boundary violations

Output: pre-flight checklist with YES/NO/UNKNOWN per dimension.

### Step 10 — effort-agent Requirements

Based on codebase health:
- Is `research_before_code = true` warranted?
- What `min_drafts` level? (`efficient`, `thorough`, `exhaustive`)
- Which modules need mandatory test verification before DONE?
- Modules where single-pass completion is never acceptable?

Output: effort.md recommendations block.

### Step 11 — Planning Constraints

Plain language. No tables. What must be true before ForgeGod plans:

1. Blockers (CRITICAL security, circular imports, missing test infrastructure)
2. Recommended pre-work before implementing
3. Top 3 safest places to start
4. Top 3 riskiest places to touch last

---

## Output Format

AUDIT.md follows this exact structure:

```markdown
# AUDIT.md
**Repo:** {name} · **Generated:** {ISO date} · **Agent:** audit-agent

---

## 1. Repo Snapshot
{table}

## 2. Entry Points Map
{list}

## 3. Architecture Map
{ASCII diagram + table}

## 4. Dependency Surface
### 4A External
{table}
### 4B Internal
{table}

## 5. Health Indicators
{counts + offenders}

## 6. Test Surface
{table}

## 7. Security Surface
{CRITICAL / WARNING / INFO}

## 8. Change Risk Map
{risk table}

## 9. taste-agent Pre-Flight
{checklist}

## 10. effort-agent Requirements
{effort.md block}

## 11. Planning Constraints
{numbered list}

---
**Audit complete. ForgeGod may now plan.**

```json
{
  "audit_agent": {
    "version": "1.0",
    "timestamp": "{ISO datetime}",
    "repo": "{name}",
    "blockers": [],
    "high_risk_modules": [],
    "recommended_start_points": [],
    "effort_level": "thorough",
    "taste_pre_flight_failures": [],
    "ready_to_plan": true
  }
}
```
```

`ready_to_plan: false` if CRITICAL security issues or hard architectural blockers exist.

---

## Behavioral Rules

- audit-agent produces AUDIT.md. It does NOT plan, suggest implementations, or review quality.
- If a file cannot be read, note it as UNREADABLE and continue. Never halt.
- If the repo has fewer than 5 files, output a minimal audit noting it's a greenfield repo.
- Never hallucinate file contents. Say so if a file was not read.
- Do not truncate sections. Every section must be present even if "none found."
- Sections 7 (Security) and 8 (Risk Map) are NEVER skipped, even for small repos.
- If taste.md or effort.md exist, read them before writing Steps 9 and 10.
- Output language matches the repo's primary documentation language. Default: English.