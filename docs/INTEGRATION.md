# Integration Guide

How to integrate audit-agent with ForgeGod, taste-agent, effort-agent, Claude Code MCP, and CI/CD.

---

## ForgeGod Integration

### Skill Placement

```
.forgegod/
  skills/
    audit-agent/
      SKILL.md   ← copy of src/audit_agent/PROMPT.md
  config.toml
  AUDIT.md      ← produced by audit-agent, read by ForgeGod
```

```bash
mkdir -p .forgegod/skills/audit-agent
cp src/audit_agent/PROMPT.md .forgegod/skills/audit-agent/SKILL.md
```

### AGENTS.md Section

Add to your repo's `AGENTS.md`:

```markdown
## audit-agent

**Trigger:** Run before planning any story or loop. Run when entering a repo with no current AUDIT.md.

**Model:** minimax/minimax-m2.7-highspeed
**Skill:** `.forgegod/skills/audit-agent/SKILL.md`
**Output:** `.forgegod/AUDIT.md`

**Rules:**
- Ralph Loop must check for `.forgegod/AUDIT.md` before spawning any story agent.
- If AUDIT.md is older than 20 commits, re-run audit-agent before planning.
- If audit sets `ready_to_plan: false`, halt and surface blockers to human.
- AUDIT.md is read-only for all other agents — only audit-agent writes it.
- audit-agent does NOT plan, implement, or review — it only audits.
```

### Ralph Loop Hook

ForgeGod's Ralph Loop should check:

```python
# Before spawning any story agent
audit_file = Path(".forgegod/AUDIT.md")
if not audit_file.exists():
    raise RuntimeError("AUDIT.md missing — run audit-agent before planning")

# Parse ready_to_plan
import json, re
content = audit_file.read_text()
match = re.search(r'"ready_to_plan":\s*(true|false)', content)
if match and match.group(1) == "false":
    raise RuntimeError("audit-agent blocked planning — fix blockers first")
```

### config.toml

```toml
[audit]
enabled = true
model = "minimax/minimax-m2.7-highspeed"
skill_path = ".forgegod/skills/audit-agent/SKILL.md"
output_path = ".forgegod/AUDIT.md"
auto_trigger = true
stale_after_commits = 20
block_loop_if_stale = true
block_loop_if_ready_to_plan_false = true
```

---

## taste-agent Bridge

taste-agent evaluates whether the output matched the vision. audit-agent's **Step 9** flags pre-flight failures that taste-agent will likely catch.

### Pre-flight output (Step 9)

```markdown
## 9. taste-agent Pre-Flight

| Dimension | Status | Notes |
|---|---|---|
| Aesthetic | YES | Inconsistent color tokens across components |
| UX | NO | No visible violations |
| Copy | UNKNOWN | Not enough text to evaluate |
| Adherence | YES | output_format.md not followed in render_email.py |
| Architecture | NO | Clean layered structure |
| Naming | YES | snake_case/camelCase mixing in api/ routes |
| API design | NO | Consistent response shapes |
| Code style | UNKNOWN | Not evaluated at this stage |
| Coherence | NO | No contradictions detected |
```

taste-agent should read these pre-flight failures before running its own evaluation to focus on the known problem areas.

---

## effort-agent Bridge

effort-agent checks whether the agent did the work thoroughly. audit-agent's **Step 10** provides effort recommendations.

### Step 10 output example

```markdown
## 10. effort-agent Requirements

Based on Step 8 (Change Risk Map) and Step 6 (Test Surface):

- `research_before_code = true` warranted: YES
  - Domain (payment processing) requires understanding Stripe API nuances
  - Multiple deprecated dependency updates could introduce subtle breakage

- `min_drafts` level: `exhaustive`
  - auth/ and billing/ modules are HIGH RISK with no test coverage
  - Any change to auth/ requires mandatory test verification

- Mandatory test verification before DONE verdict:
  - `services/auth.py`
  - `services/billing.py`
  - `api/routes/payment.py`

- Single-pass completion NEVER acceptable:
  - `services/auth.py` (HIGH RISK, multiple dependents)
  - `core/security.py` (security surface, circular dependency risk)
```

---

## Claude Code MCP Integration

When Claude Code runs with an MCP server, expose `mcp__audit__run`:

### MCP server handler

```python
# In your MCP server implementation
def mcp__audit__run(repo_path: str | None = None) -> dict:
    """Run audit-agent on a repository."""
    from audit_agent import AuditAgent, AuditConfig
    from pathlib import Path
    import asyncio

    config = AuditConfig(
        repo_root=Path(repo_path) if repo_path else Path.cwd(),
    )
    agent = AuditAgent(config)
    result = asyncio.run(agent.run())

    return {
        "summary": result.summary(),
        "ready_to_plan": result.ready_to_plan,
        "blockers": result.blockers,
        "high_risk_modules": result.high_risk_modules,
        "effort_level": result.effort_level,
    }
```

### Trigger rules

Set up MCP hooks in your Claude Code config:

```json
{
  "mcpHooks": {
    "onRepoOpen": "mcp__audit__run",
    "onCommand": {
      "audit": "mcp__audit__run"
    }
  }
}
```

---

## CI/CD Integration

### GitHub Actions

```yaml
name: Audit Gate

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install audit-agent
        run: pip install audit-agent

      - name: Run audit
        env:
          MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}
        run: audit run .

      - name: Upload AUDIT.md
        uses: actions/upload-artifact@v4
        with:
          name: audit-report-${{ github.sha }}
          path: AUDIT.md
          retention-days: 30

      - name: Fail if blocked
        run: |
          if grep '"ready_to_plan": false' AUDIT.md; then
            echo "::error:: Planning is blocked by audit-agent. Fix blockers in AUDIT.md."
            exit 1
          fi

      - name: Comment on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: '## audit-agent\\n\\nAudit ran. See artifacts for `AUDIT.md`.'
            })
```

### Blocking ForgeGod loop until audit is fresh

```yaml
- name: Check AUDIT.md freshness
  run: |
    LAST_AUDIT=$(git log -1 --format=%ci -- .forgegod/AUDIT.md 2>/dev/null)
    if [ -z "$LAST_AUDIT" ]; then
      echo "::error:: No AUDIT.md found. Run audit-agent first."
      exit 1
    fi
    AUDIT_COMMITS=$(git log --since="$LAST_AUDIT" --oneline | wc -l)
    if [ "$AUDIT_COMMITS" -gt 20 ]; then
      echo "::error:: AUDIT.md is stale ($AUDIT_COMMITS commits since). Re-run audit-agent."
      exit 1
    fi
    echo "AUDIT.md is fresh ($AUDIT_COMMITS commits since)."
```

### GitLab CI

```yaml
audit:
  stage: pre-plan
  image: python:3.12-slim
  variables:
    MINIMAX_API_KEY: $MINIMAX_API_KEY
  before_script:
    - pip install audit-agent
  script:
    - audit run . --verbose
    - grep '"ready_to_plan": true' AUDIT.md || (cat AUDIT.md; exit 1)
  artifacts:
    paths:
      - AUDIT.md
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Pre-commit hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

if [ -f .forgegod/AUDIT.md ]; then
  LAST_AUDIT=$(git log -1 --format=%ci -- .forgegod/AUDIT.md)
  COMMITS_SINCE=$(git log --since="$LAST_AUDIT" --oneline | wc -l)
  if [ "$COMMITS_SINCE" -gt 20 ]; then
    echo "WARNING: AUDIT.md is stale ($COMMITS_SINCE commits since)"
    echo "Run: audit run ."
    # Uncomment to block:
    # exit 1
  fi
fi
```

---

## Event-Driven Integration

audit-agent publishes events when it completes (for future NATS/RabbitMQ integration):

| Event | Payload |
|---|---|
| `audit.completed` | `{repo, ready_to_plan, blockers, effort_level}` |
| `audit.blocked` | `{repo, blockers}` |
| `audit.stale` | `{repo, commits_since_audit}` |

This allows ForgeGod to subscribe to audit completion events and automatically trigger the Ralph Loop once `ready_to_plan: true`.