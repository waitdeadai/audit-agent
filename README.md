# audit-agent

`audit-agent` is the pre-planning auditor for ForgeGod. It enters a repository before execution, builds deterministic evidence from scanners and repo instructions, synthesizes `AUDIT.md`, and blocks planning when the repo state is unsafe or unclear.

The runtime is now hybrid and evidence-driven:

- deterministic scanners first
- repo instruction ingestion and repo map generation
- LLM synthesis after evidence collection
- targeted delta-audits when planning conditions change
- specialist audit surfaces for security, architecture, and plan risk
- offline eval harness for auditor quality checks

## Install

```bash
pip install audit-agent
```

For development:

```bash
git clone https://github.com/waitdeadai/audit-agent.git
cd audit-agent
pip install -e ".[dev]"
```

## CLI

```bash
audit run .
audit status .
audit diff .
audit delta . --task "refactor payment pipeline"
audit security . --semgrep
audit architecture .
audit plan "add auth flow"
audit plan-risk .
audit eval .
```

## Artifacts

Base audit:

- `.forgegod/AUDIT.md`
- `.forgegod/AUDIT.json`
- `.forgegod/AUDIT_EVIDENCE.json`

Delta audit:

- `.forgegod/AUDIT_DELTA.md`
- `.forgegod/AUDIT_DELTA.json`

Specialist audits:

- `.forgegod/SECURITY_AUDIT.md`
- `.forgegod/SECURITY_AUDIT.json`
- `.forgegod/ARCHITECTURE_AUDIT.md`
- `.forgegod/ARCHITECTURE_AUDIT.json`
- `.forgegod/PLAN_RISK_AUDIT.md`
- `.forgegod/PLAN_RISK_AUDIT.json`

Eval harness:

- `.forgegod/AUDIT_EVALS.md`
- `.forgegod/AUDIT_EVALS.json`

## What It Checks

The hybrid runtime collects evidence from:

- repo snapshot
- entry points
- architecture map
- dependency surface
- health indicators
- test surface
- security findings
- risk map
- taste preflight
- effort requirements
- planning constraints

It also ingests repo-local instructions from files like:

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `.github/copilot-instructions.md`
- `.github/instructions/*.instructions.md`
- `CONTRIBUTING.md`
- `docs/ARCHITECTURE.md`
- `docs/RUNBOOK.md`
- `docs/DESIGN.md`

## Specialist Surfaces

`audit security`
- deterministic security scan
- optional Semgrep-backed pass when `semgrep` is installed

`audit architecture`
- circular import detection
- god module surfacing
- high-risk module review

`audit plan-risk`
- checks story dependency validity
- blocks high-risk stories without verification commands
- adds guardrails before execution

`audit plan`
- runs delta checks automatically unless `--skip-delta-audit` is set
- runs plan-risk review before returning the plan surface

## Eval Harness

`audit eval` runs an offline deterministic suite that checks:

- repo snapshot correctness
- instruction ingestion correctness
- blocker detection precision
- high-risk module ranking quality
- safest-start recommendations
- delta trigger correctness
- false-positive rate on small repos

This gives you a local quality signal for the auditor itself without requiring live model calls.

## ForgeGod Integration

Typical flow:

1. `audit run` when entering a repo or when the current audit is stale
2. `audit delta` before risky planning changes or after bad reviews
3. `audit plan` to generate a guarded implementation plan
4. specialist surfaces on demand for targeted troubleshooting

`AUDIT.md` and the machine-readable artifacts are intended to be consumed by ForgeGod before code execution.

## Documentation

- [Getting Started](docs/GETTING_STARTED.md)
- [Protocol Reference](docs/PROTOCOL.md)
- [Integration Guide](docs/INTEGRATION.md)
- [2026 Research Plan](docs/WEB_RESEARCH_2026-04-17_AUDIT_AGENT_EVOLUTION.md)

## License

Apache-2.0
