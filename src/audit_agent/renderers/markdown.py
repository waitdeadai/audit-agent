"""Renderer: Markdown output for AUDIT.md."""

from __future__ import annotations

from audit_agent.core.audit_result import AuditResult


def render_audit_markdown(result: AuditResult) -> str:
    """Render an AuditResult as a formatted Markdown string.

    Produces the full AUDIT.md content including the JSON block.
    """
    lines = [
        "# AUDIT.md",
        f"**Repo:** {result.repo} · **Generated:** {result.timestamp} · "
        f"**Agent:** audit-agent · **Model:** minimax/minimax-m2.7-highspeed",
        "",
        "---",
        "",
    ]

    if result.markdown_content:
        # Use the pre-formatted markdown from LLM, append JSON block
        content = result.markdown_content.rstrip()
        if not content.endswith("}"):
            content += "\n\n" + result.to_json_block()
        return content

    # Fallback: generate from structured data
    lines.extend([
        "## Summary",
        f"- **Repo:** {result.repo}",
        f"- **Ready to plan:** {result.ready_to_plan}",
        f"- **Effort level:** {result.effort_level}",
        f"- **Findings:** {len(result.findings)}",
        f"- **Blockers:** {len(result.blockers)}",
        f"- **High-risk modules:** {len(result.high_risk_modules)}",
        "",
    ])

    if result.blockers:
        lines.append("## Blockers")
        for b in result.blockers:
            lines.append(f"- {b}")
        lines.append("")

    if result.high_risk_modules:
        lines.append("## High-Risk Modules")
        for m in result.high_risk_modules:
            lines.append(f"- {m}")
        lines.append("")

    lines.append("---")
    lines.append(result.to_json_block())

    return "\n".join(lines)