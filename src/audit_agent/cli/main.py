"""CLI entry point for audit-agent."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from audit_agent.core.audit_agent import AuditAgent
from audit_agent.core.audit_config import AuditConfig, PlanConfig

app = typer.Typer(
    name="audit",
    help="Audit + Plan — mandatory pre-planning auditor and story planner.",
    add_completion=False,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
log = logging.getLogger("audit")


def _resolve_repo_root(repo_arg: str | None) -> Path:
    """Resolve the repository root from CLI argument or cwd."""
    if repo_arg:
        p = Path(repo_arg).expanduser().resolve()
        if not p.exists():
            typer.echo(f"Error: path does not exist: {p}", err=True)
            raise SystemExit(1)
        return p
    return Path.cwd()


@app.command()
def run(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository to audit. Defaults to current directory.",
    ),
    output: str | None = typer.Option(
        None,
        "--output", "-o",
        help="Output path for AUDIT.md (default: .forgegod/AUDIT.md)",
    ),
    model: str | None = typer.Option(
        None,
        "--model", "-m",
        help="Model string (e.g. minimax/minimax-m2.7-highspeed)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Run the audit protocol on a repository."""
    repo_root = _resolve_repo_root(repo)

    config_kwargs: dict = {"repo_root": repo_root, "verbose": verbose}
    if output:
        config_kwargs["output_path"] = Path(output)
    if model:
        config_kwargs["model"] = model

    config = AuditConfig(**config_kwargs)

    if verbose:
        log.setLevel(logging.DEBUG)

    typer.echo(f"Starting audit of {repo_root} ...")

    async def _run() -> None:
        agent = AuditAgent(config)
        result = await agent.run()
        typer.echo(f"\nAudit complete: {result.summary()}")
        if result.blockers:
            typer.echo("\nBlockers found:", err=True)
            for b in result.blockers:
                typer.echo(f"  - {b}", err=True)
        if not result.ready_to_plan:
            typer.echo(
                "\nWARNING: ready_to_plan=False. Fix blockers before planning.",
                err=True,
            )
            raise SystemExit(1)

    try:
        asyncio.run(_run())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@app.command()
def status(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository. Defaults to current directory.",
    ),
) -> None:
    """Check if AUDIT.md exists and is current."""
    repo_root = _resolve_repo_root(repo)
    config = AuditConfig(repo_root=repo_root)
    agent = AuditAgent(config)

    if agent.is_stale():
        typer.echo("AUDIT.md is STALE or missing.")
        raise SystemExit(1)
    else:
        typer.echo("AUDIT.md is current.")


@app.command()
def diff(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository. Defaults to current directory.",
    ),
) -> None:
    """Show changes since the last audit (git diff AUDIT.md)."""
    repo_root = _resolve_repo_root(repo)
    config = AuditConfig(repo_root=repo_root)
    agent = AuditAgent(config)

    existing = agent.load_existing()
    if not existing:
        typer.echo("No existing AUDIT.md found.", err=True)
        raise SystemExit(1)

    typer.echo(f"AUDIT.md for {existing.repo!r}")
    typer.echo(f"  Generated: {existing.timestamp}")
    typer.echo(f"  Ready to plan: {existing.ready_to_plan}")
    typer.echo(f"  Effort level: {existing.effort_level}")
    typer.echo(f"  Findings: {len(existing.findings)}")
    typer.echo(f"  Blockers: {len(existing.blockers)}")
    typer.echo(f"  High-risk modules: {len(existing.high_risk_modules)}")


@app.command()
def plan(
    task: str = typer.Argument(
        ...,
        help="Task to decompose into stories (e.g. 'add user authentication').",
    ),
    repo: str | None = typer.Option(
        None,
        "--repo", "-r",
        help="Path to repository. Defaults to current directory.",
    ),
    output: str | None = typer.Option(
        None,
        "--output", "-o",
        help="Output path for PLAN.md (default: .forgegod/PLAN.md)",
    ),
    model: str | None = typer.Option(
        None,
        "--model", "-m",
        help="Model for planning (e.g. minimax/minimax-m2.7-highspeed)",
    ),
    reviewer: str | None = typer.Option(
        None,
        "--reviewer", "-R",
        help="Reviewer model for adversarial plan review (optional)",
    ),
    no_review: bool = typer.Option(
        False,
        "--no-review",
        help="Skip adversarial plan review step",
    ),
    max_stories: int = typer.Option(
        20,
        "--max-stories",
        help="Maximum number of stories to generate",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Run audit then decompose a task into ordered implementation stories.

    This runs the full 11-step audit protocol, then uses the audit findings
    (risk map, dependency graph, guardrails, effort level) to produce
    PLAN.md with independently-executable, verification-command-backed stories.

    Example:
        audit plan "add REST API for user management"
        audit plan "refactor auth module" --output .forgegod/PLAN.md
    """
    repo_root = _resolve_repo_root(repo)

    plan_config = PlanConfig(
        enabled=True,
        task=task,
        output_path=Path(output) if output else None,
        reviewer_model=reviewer,
        auto_review=not no_review,
        max_stories=max_stories,
    )

    config_kwargs: dict = {
        "repo_root": repo_root,
        "verbose": verbose,
        "plan": plan_config,
    }
    if model:
        config_kwargs["model"] = model

    config = AuditConfig(**config_kwargs)

    if verbose:
        log.setLevel(logging.DEBUG)

    typer.echo(f"Starting audit + plan for: {task[:60]}...")
    typer.echo(f"  Repo: {repo_root}")

    async def _run() -> None:
        agent = AuditAgent(config)
        plan_result = await agent.run_plan(task)
        typer.echo(f"\nPlan complete: {plan_result.summary()}")
        typer.echo(f"  Stories: {len(plan_result.stories)}")
        if plan_result.guardrails:
            typer.echo(f"  Guardrails: {len(plan_result.guardrails)}")
        if plan_result.blockers:
            typer.echo("\nBlockers:", err=True)
            for b in plan_result.blockers:
                typer.echo(f"  - {b}", err=True)
        if not plan_result.ready_to_execute:
            typer.echo(
                "\nWARNING: ready_to_execute=False. Fix blockers before executing plan.",
                err=True,
            )
            raise SystemExit(1)

    try:
        asyncio.run(_run())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@app.callback()
def main() -> None:
    """audit — Audit + Plan for AI coding agents."""
    pass


if __name__ == "__main__":
    app()