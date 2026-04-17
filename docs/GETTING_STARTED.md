# Getting Started with audit-agent

## Install

From PyPI:

```bash
pip install audit-agent
```

From source:

```bash
git clone https://github.com/waitdeadai/audit-agent.git
cd audit-agent
pip install -e ".[dev]"
```

## Base Audit

Run the full hybrid audit:

```bash
audit run .
```

Artifacts written under the target repo:

- `.forgegod/AUDIT.md`
- `.forgegod/AUDIT.json`
- `.forgegod/AUDIT_EVIDENCE.json`

Useful variations:

```bash
audit run /path/to/repo
audit run . --verbose
audit run . --model openai/gpt-4.4
audit status .
audit diff .
```

## Delta Audit

Use the targeted delta surface when the repo changed after the base audit, when a review went badly, or when execution gets stuck:

```bash
audit delta .
audit delta . --task "refactor payment pipeline"
audit delta . --review-feedback "reviewer asked for auth boundary fixes"
audit delta . --failure-details "planner looped on billing adapter"
```

Artifacts:

- `.forgegod/AUDIT_DELTA.md`
- `.forgegod/AUDIT_DELTA.json`

`audit plan` runs delta checks automatically unless `--skip-delta-audit` is set.

## Specialist Audits

Security:

```bash
audit security .
audit security . --changed-file src/auth.py
audit security . --semgrep
```

Artifacts:

- `.forgegod/SECURITY_AUDIT.md`
- `.forgegod/SECURITY_AUDIT.json`

Architecture:

```bash
audit architecture .
audit architecture . --changed-file src/router.py
```

Artifacts:

- `.forgegod/ARCHITECTURE_AUDIT.md`
- `.forgegod/ARCHITECTURE_AUDIT.json`

Plan-risk:

```bash
audit plan "ship auth refactor"
audit plan-risk .
audit plan-risk . --plan .forgegod/PLAN.md
```

Artifacts:

- `.forgegod/PLAN_RISK_AUDIT.md`
- `.forgegod/PLAN_RISK_AUDIT.json`

## Eval Harness

Run the deterministic offline eval suite:

```bash
audit eval .
```

Artifacts:

- `.forgegod/AUDIT_EVALS.md`
- `.forgegod/AUDIT_EVALS.json`

Current eval buckets:

- repo snapshot correctness
- instruction ingestion correctness
- blocker detection precision
- high-risk module ranking quality
- safest-start recommendations
- delta trigger correctness
- false-positive rate on small repos

## What the Hybrid Runtime Reads

Scanner evidence:

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

Instruction files:

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `.github/copilot-instructions.md`
- `.github/instructions/*.instructions.md`
- `CONTRIBUTING.md`
- `docs/ARCHITECTURE.md`
- `docs/RUNBOOK.md`
- `docs/DESIGN.md`

## ForgeGod Integration

Recommended flow inside ForgeGod:

1. Run `audit run` on repo entry or when the audit is stale.
2. Run `audit delta` before risky plans or after `REVISE` / failure loops.
3. Run `audit plan` to produce guarded stories.
4. Run specialist surfaces when the manager needs deeper security, architecture, or plan-risk evidence.

## Programmatic Usage

```python
from pathlib import Path

from audit_agent import AuditAgent, AuditConfig

config = AuditConfig(repo_root=Path("/path/to/repo"))
agent = AuditAgent(config)

audit_result = await agent.run()
plan_result = await agent.run_plan("add authentication")
security_result = await agent.run_security_audit(use_semgrep=False)
eval_result = agent.run_evals()
```
