"""Renderer: JSON integration block for ForgeGod."""

from __future__ import annotations

import json
from datetime import datetime, timezone


def render_json_block(
    version: str = "1.0",
    repo: str = "",
    blockers: list[str] | None = None,
    high_risk_modules: list[str] | None = None,
    recommended_start_points: list[str] | None = None,
    effort_level: str = "thorough",
    taste_pre_flight_failures: list[str] | None = None,
    ready_to_plan: bool = True,
) -> str:
    """Render the JSON block that ForgeGod parses after running an audit.

    This is the INTEGRATION OUTPUT block from the audit protocol.
    """
    if blockers is None:
        blockers = []
    if high_risk_modules is None:
        high_risk_modules = []
    if recommended_start_points is None:
        recommended_start_points = []
    if taste_pre_flight_failures is None:
        taste_pre_flight_failures = []

    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    block = {
        "audit_agent": {
            "version": version,
            "timestamp": ts,
            "repo": repo,
            "blockers": blockers,
            "high_risk_modules": high_risk_modules,
            "recommended_start_points": recommended_start_points,
            "effort_level": effort_level,
            "taste_pre_flight_failures": taste_pre_flight_failures,
            "ready_to_plan": ready_to_plan,
        }
    }

    return json.dumps(block, indent=2)
