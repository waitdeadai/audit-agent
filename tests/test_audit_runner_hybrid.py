"""Tests for the hybrid audit runner."""

from __future__ import annotations

import json

from audit_agent.core.audit_config import AuditConfig
from audit_agent.core.audit_runner import run_audit


def _seed_repo(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "## Rules\n"
        "- Respect architecture boundaries\n"
        "- Run pytest before merge\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "from helper import compute\n\n"
        "def main():\n"
        "    return compute()\n",
        encoding="utf-8",
    )
    (tmp_path / "helper.py").write_text(
        "def compute():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_helper.py").write_text(
        "from helper import compute\n\n"
        "def test_compute():\n"
        "    assert compute() == 1\n",
        encoding="utf-8",
    )


async def test_run_audit_writes_markdown_and_machine_readable_artifacts(tmp_path, monkeypatch):
    _seed_repo(tmp_path)

    captured_prompt: dict[str, str] = {}

    monkeypatch.setattr("audit_agent.core.audit_runner._load_prompt", lambda: "system prompt")

    async def fake_call(system_prompt, user_prompt, config):
        captured_prompt["value"] = user_prompt
        return """# AUDIT.md
**Repo:** demo

## Summary
Hybrid audit test

```json
{
  "audit_agent": {
    "repo": "demo"
  }
}
```"""

    monkeypatch.setattr("audit_agent.core.audit_runner.call_llm", fake_call)

    config = AuditConfig(repo_root=tmp_path)
    result = await run_audit(config)

    assert "Deterministic repository map:" in captured_prompt["value"]
    assert "Repository instructions and policy files:" in captured_prompt["value"]

    audit_md = tmp_path / ".forgegod" / "AUDIT.md"
    audit_json = tmp_path / ".forgegod" / "AUDIT.json"
    evidence_json = tmp_path / ".forgegod" / "AUDIT_EVIDENCE.json"

    assert audit_md.exists()
    assert audit_json.exists()
    assert evidence_json.exists()

    parsed_audit = json.loads(audit_json.read_text(encoding="utf-8"))
    parsed_evidence = json.loads(evidence_json.read_text(encoding="utf-8"))

    assert parsed_audit["audit_agent"]["repo"] == "demo"
    assert "instruction_context" in parsed_evidence
    assert result.effort_level == "efficient"
    assert result.recommended_start_points
