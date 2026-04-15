"""Integration: Bridge to taste-agent."""

from __future__ import annotations

from pathlib import Path


async def get_taste_preflight(
    repo_root: Path,
    audit_result: dict | None = None,
) -> dict:
    """Extract pre-flight taste findings from an AuditResult or AUDIT.md."""
    if audit_result is None:
        audit_path = repo_root / ".forgegod" / "AUDIT.md"
        if audit_path.exists():
            content = audit_path.read_text(errors="replace")
            # Parse pre-flight section
            return _parse_taste_preflight(content)
    return {}


def _parse_taste_preflight(content: str) -> dict:
    """Parse Section 9 (taste-agent Pre-Flight) from AUDIT.md."""
    result = {"checklist": [], "violations": []}
    in_section = False
    for line in content.splitlines():
        if "## 9. taste-agent Pre-Flight" in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                result["violations"].append(line[2:].strip())
            if "YES" in line or "NO" in line or "REVIEW" in line or "UNKNOWN" in line:
                result["checklist"].append(line.strip())
    return result


def format_taste_preflight_bridge(
    checklist: list[str],
    violations: list[str],
) -> str:
    """Format audit pre-flight as a prompt injection for taste-agent."""
    lines = [
        "## Taste Pre-Flight from audit-agent",
        "",
        "Known violations (fix before taste review):",
    ]
    for v in violations:
        lines.append(f"  - {v}")
    lines += ["", "Pre-flight checklist:"]
    for item in checklist:
        lines.append(f"  - {item}")
    return "\n".join(lines)
