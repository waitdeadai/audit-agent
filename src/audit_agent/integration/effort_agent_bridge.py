"""Integration: Bridge to effort-agent."""

from __future__ import annotations


def format_effort_requirements(
    effort_block: str,
    effort_level: str = "thorough",
    research_before_code: bool = True,
) -> str:
    """Format audit effort requirements as effort-agent input."""
    lines = [
        "## Effort Requirements from audit-agent",
        "",
        f"Effort level: **{effort_level}**",
        f"research_before_code: {research_before_code}",
        "",
        effort_block.strip(),
    ]
    return "\n".join(lines)


def effort_level_recommendation(
    file_count: int,
    has_complex_deps: bool,
    has_god_modules: bool,
) -> str:
    """Recommend effort level based on repo characteristics."""
    if file_count > 100 or has_god_modules:
        return "exhaustive"
    elif file_count > 30 or has_complex_deps:
        return "thorough"
    return "efficient"
