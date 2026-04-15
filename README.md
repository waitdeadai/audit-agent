# audit-agent

**Mandatory pre-planning auditor for the WAITDEAD system** — produces `AUDIT.md` via an 11-step protocol before any code change planning begins.

audit-agent is the gate that runs before all other agents in the ForgeGod ecosystem. No story can be planned. No PR can be opened. No ForgeGod loop can execute until `AUDIT.md` exists and is current.

---

## The 4-Agent Ecosystem

```
WAITDEAD SYSTEM — AUDIT · PLAN · SCALE

┌─────────────────────────────────────────────────────────┐
│                    NEW REPO / FIRST RUN                  │
│                           │                              │
│                    ┌──────▼──────┐                       │
│                    │ audit-agent  │  ← YOU ARE HERE       │
│                    └──────┬──────┘                       │
│                    AUDIT.md produced                     │
│                           │                              │
│              ┌────────────▼────────────┐                 │
│              │   ForgeGod Ralph Loop   │                 │
│              │   reads AUDIT.md        │                 │
│              │   plans stories         │                 │
│              └────────────┬────────────┘                 │
│                           │                              │
│              ┌────────────▼────────────┐                 │
│              │  per-story execution    │                 │
│              │  taste-agent reviews    │  (did it right?)│
│              │  effort-agent checks    │  (did the work?)│
│              └─────────────────────────┘                 │
└─────────────────────────────────────────────────────────┘
```

| Agent | Role | Answers |
|---|---|---|
| **audit-agent** | Pre-planning auditor | "What is this codebase? Where are the risks?" |
| **taste-agent** | Output reviewer | "Did the output match the vision?" |
| **effort-agent** | Thoroughness checker | "Did the agent do the work thoroughly?" |
| **ForgeGod** | Execution engine | "Did the code ship?" |

---

## Quick Start

```bash
pip install audit-agent
audit run .
```

This produces `AUDIT.md` in the current directory using the 11-step protocol.

```bash
audit --help
```

```
 Usage: audit [OPTIONS] COMMAND [ARGS]

 Mandatory pre-planning auditor — produces AUDIT.md via 11-step protocol

 Options:
   --install-completion  Install completion for the current shell.
   --show-completion     Show the completion for the current shell.
   --help               Show this message and exit.

 Commands:
   run      Audit a repository
   status   Check if AUDIT.md exists and is current
   diff     Show changes since last audit
```

---

## ForgeGod Integration

### Install as a ForgeGod Skill

```bash
# Copy PROMPT.md to the skill directory
mkdir -p .forgegod/skills/audit-agent
cp src/audit_agent/PROMPT.md .forgegod/skills/audit-agent/SKILL.md
```

Then add to your `AGENTS.md`:

```markdown
## audit-agent

**Trigger:** Run before planning any story or loop. Run when entering a repo with no current AUDIT.md.

**Model:** minimax/minimax-m2.7-highspeed
**Skill:** `.forgegod/skills/audit-agent/SKILL.md` (invoke via `load_skill("audit-agent")`)
**Output:** `.forgegod/AUDIT.md`

**Rules:**
- Ralph Loop must check for `.forgegod/AUDIT.md` before spawning any story agent.
- If AUDIT.md is older than 20 commits, re-run audit-agent before planning.
- If audit sets `ready_to_plan: false`, halt and surface blockers to human.
- AUDIT.md is read-only for all other agents — only audit-agent writes it.
```

### config.toml Integration

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

## Configuration

`AuditConfig` fields:

| Field | Default | Description |
|---|---|---|
| `model` | `minimax/minimax-m2.7-highspeed` | Model string for audit |
| `temperature` | `0.2` | Deterministic for audit |
| `top_p` | `0.9` | Nucleus sampling |
| `max_tokens` | `8000` | Max audit output |
| `output_path` | `AUDIT.md` | Where to write AUDIT.md |
| `stale_after_commits` | `20` | Re-trigger after N commits |
| `api_key` | env `MINIMAX_API_KEY` | API key for model provider |

---

## CI Integration

### GitHub Actions Pre-Plan Gate

```yaml
name: Audit Gate

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run audit-agent
        run: |
          pip install audit-agent
          audit run .

      - name: Upload AUDIT.md
        uses: actions/upload-artifact@v4
        with:
          name: audit-report
          path: AUDIT.md

      - name: Check if ready to plan
        run: |
          if grep '"ready_to_plan": false' AUDIT.md; then
            echo "::error:: Audit blocked planning. Fix blockers before proceeding."
            exit 1
          fi
```

---

## Documentation

- [Getting Started](docs/GETTING_STARTED.md) — Installation, quick start, ForgeGod setup, MCP, CI
- [Protocol Reference](docs/PROTOCOL.md) — The 11-step audit protocol in detail
- [Integration Guide](docs/INTEGRATION.md) — ForgeGod, taste-agent, effort-agent, Claude Code MCP, CI/CD

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Links

- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)
- [docs/PROTOCOL.md](docs/PROTOCOL.md)
- [docs/INTEGRATION.md](docs/INTEGRATION.md)