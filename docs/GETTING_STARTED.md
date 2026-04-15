# Getting Started with audit-agent

## Installation

### From PyPI (future)

```bash
pip install audit-agent
```

### From source (development)

```bash
git clone https://github.com/waitdeadai/audit-agent.git
cd audit-agent
pip install -e .
```

### With dev dependencies

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
audit run .
```

This runs the 11-step audit protocol on the current directory and produces `AUDIT.md`.

```bash
# Audit a specific repo
audit run /path/to/my-project

# Verbose output
audit run . --verbose

# Custom model
audit run . --model openai/gpt-4.4

# Custom output path
audit run . --output /path/to/my-project/.forgegod/AUDIT.md
```

## ForgeGod Integration

### 1. Install as a skill

```bash
mkdir -p .forgegod/skills/audit-agent
cp src/audit_agent/PROMPT.md .forgegod/skills/audit-agent/SKILL.md
```

### 2. Add to AGENTS.md

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
```

### 3. config.toml integration (optional)

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

## Claude Code MCP Integration

When running Claude Code with an MCP server that exposes `mcp__audit__run`, audit-agent can be triggered:

- On repo open (set up an MCP hook)
- On demand via `mcp__audit__run`

Configure your MCP server to invoke:

```bash
audit run /path/to/repo
```

## CI Integration

### GitHub Actions

```yaml
name: Audit Gate

on:
  push:
    branches: [main]
  pull_request:

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install audit-agent
        run: pip install audit-agent

      - name: Run audit
        env:
          MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}
        run: audit run .

      - name: Upload AUDIT.md
        uses: actions/upload-artifact@v4
        with:
          name: audit-report
          path: AUDIT.md

      - name: Check blockers
        run: |
          if grep '"ready_to_plan": false' AUDIT.md; then
            echo "::error:: Audit blocked — fix blockers before proceeding."
            exit 1
          fi
```

### GitLab CI

```yaml
audit:
  stage: pre-plan
  image: python:3.12
  before_script:
    - pip install audit-agent
  script:
    - audit run .
    - grep '"ready_to_plan": true' AUDIT.md || (cat AUDIT.md && exit 1)
  artifacts:
    paths:
      - AUDIT.md
```

## Configuration

`AuditConfig` fields:

| Field | Default | Description |
|---|---|---|
| `repo_root` | `Path.cwd()` | Repository root to audit |
| `output_path` | `.forgegod/AUDIT.md` | Where to write AUDIT.md |
| `model` | `minimax/minimax-m2.7-highspeed` | Model string |
| `temperature` | `0.2` | Sampling temperature |
| `top_p` | `0.9` | Nucleus sampling |
| `max_tokens` | `8000` | Max output tokens |
| `stale_after_commits` | `20` | Re-trigger after N new commits |
| `verbose` | `False` | Enable debug logging |

### Environment variables

| Variable | Description |
|---|---|
| `MINIMAX_API_KEY` | MiniMax API key (default) |
| `OPENAI_API_KEY` | OpenAI API key (fallback) |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key |
| `AZURE_OPENAI_BASE_URL` | Azure endpoint URL |

### Programmatic usage

```python
from audit_agent import AuditAgent, AuditConfig

config = AuditConfig(
    repo_root=Path("/path/to/repo"),
    output_path=Path("/path/to/repo/.forgegod/AUDIT.md"),
    model="minimax/minimax-m2.7-highspeed",
    verbose=True,
)
agent = AuditAgent(config)
result = await agent.run()

print(result.summary())
print(result.to_json_block())
```