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
def delta(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository. Defaults to current directory.",
    ),
    task: str = typer.Option(
        "",
        "--task",
        help="Optional task that may touch high-risk modules.",
    ),
    review_feedback: str = typer.Option(
        "",
        "--review-feedback",
        help="Reviewer feedback that should trigger troubleshooting.",
    ),
    failure_details: str = typer.Option(
        "",
        "--failure-details",
        help="Execution failure details that should trigger troubleshooting.",
    ),
    changed_files: list[str] = typer.Option(
        None,
        "--changed-file",
        help="Explicit changed file(s) to evaluate instead of git-detected changes.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Run a targeted delta audit when planning conditions changed."""
    repo_root = _resolve_repo_root(repo)
    config = AuditConfig(repo_root=repo_root, verbose=verbose)

    if verbose:
        log.setLevel(logging.DEBUG)

    async def _run() -> None:
        agent = AuditAgent(config)
        result = await agent.run_delta(
            task=task,
            review_feedback=review_feedback,
            failure_details=failure_details,
            changed_files=changed_files or None,
        )
        if result is None:
            typer.echo("No delta-audit triggers detected. Current audit still applies.")
            return
        typer.echo(f"Delta audit complete: {result.summary()}")
        if result.blocker_updates:
            typer.echo("Blocker updates:", err=True)
            for blocker in result.blocker_updates:
                typer.echo(f"  - {blocker}", err=True)
        if result.full_reaudit_required:
            typer.echo(
                "Full re-audit required before planning continues.",
                err=True,
            )
            raise SystemExit(1)

    try:
        asyncio.run(_run())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@app.command()
def security(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository. Defaults to current directory.",
    ),
    changed_files: list[str] = typer.Option(
        None,
        "--changed-file",
        help="Limit the security audit to explicit changed file(s).",
    ),
    semgrep: bool = typer.Option(
        False,
        "--semgrep",
        help="Use Semgrep when installed for an additional security pass.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Run the security specialist audit surface."""
    repo_root = _resolve_repo_root(repo)
    config = AuditConfig(repo_root=repo_root, verbose=verbose)

    if verbose:
        log.setLevel(logging.DEBUG)

    async def _run() -> None:
        agent = AuditAgent(config)
        result = await agent.run_security_audit(
            changed_files=changed_files or None,
            use_semgrep=semgrep,
        )
        typer.echo(f"Security audit complete: {result.summary()}")
        if result.blockers:
            typer.echo("Blockers:", err=True)
            for blocker in result.blockers:
                typer.echo(f"  - {blocker}", err=True)
            raise SystemExit(1)

    try:
        asyncio.run(_run())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@app.command()
def architecture(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository. Defaults to current directory.",
    ),
    changed_files: list[str] = typer.Option(
        None,
        "--changed-file",
        help="Limit the architecture audit to explicit changed file(s).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Run the architecture specialist audit surface."""
    repo_root = _resolve_repo_root(repo)
    config = AuditConfig(repo_root=repo_root, verbose=verbose)

    if verbose:
        log.setLevel(logging.DEBUG)

    async def _run() -> None:
        agent = AuditAgent(config)
        result = await agent.run_architecture_audit(changed_files=changed_files or None)
        typer.echo(f"Architecture audit complete: {result.summary()}")
        if result.blockers:
            typer.echo("Blockers:", err=True)
            for blocker in result.blockers:
                typer.echo(f"  - {blocker}", err=True)
            raise SystemExit(1)

    try:
        asyncio.run(_run())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@app.command("plan-risk")
def plan_risk(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository. Defaults to current directory.",
    ),
    task: str = typer.Option(
        "",
        "--task",
        help="Optional task label to associate with the existing PLAN.md.",
    ),
    plan_path: str | None = typer.Option(
        None,
        "--plan",
        help="Path to PLAN.md (default: .forgegod/PLAN.md under the repo).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Run the plan-risk specialist over an existing PLAN.md."""
    repo_root = _resolve_repo_root(repo)
    config = AuditConfig(repo_root=repo_root, verbose=verbose)

    if verbose:
        log.setLevel(logging.DEBUG)

    async def _run() -> None:
        agent = AuditAgent(config)
        result = await agent.run_plan_risk_audit(
            task=task,
            plan_path=Path(plan_path) if plan_path else None,
        )
        typer.echo(f"Plan-risk audit complete: {result.summary()}")
        if result.blockers:
            typer.echo("Blockers:", err=True)
            for blocker in result.blockers:
                typer.echo(f"  - {blocker}", err=True)
            raise SystemExit(1)

    try:
        asyncio.run(_run())
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@app.command("eval")
def eval_command(
    repo: str | None = typer.Argument(
        None,
        help="Path to repository. Defaults to current directory.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """Run the offline audit eval harness."""
    repo_root = _resolve_repo_root(repo)
    config = AuditConfig(repo_root=repo_root, verbose=verbose)

    if verbose:
        log.setLevel(logging.DEBUG)

    try:
        result = AuditAgent(config).run_evals()
        typer.echo(f"Eval harness complete: {result.summary()}")
        if result.failed:
            raise SystemExit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


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
    review_feedback: str = typer.Option(
        "",
        "--review-feedback",
        help="Reviewer feedback that should trigger a delta audit before planning.",
    ),
    failure_details: str = typer.Option(
        "",
        "--failure-details",
        help="Execution failure details that should trigger a delta audit before planning.",
    ),
    changed_files: list[str] = typer.Option(
        None,
        "--changed-file",
        help="Explicit changed file(s) to evaluate instead of git-detected changes.",
    ),
    skip_delta_audit: bool = typer.Option(
        False,
        "--skip-delta-audit",
        help="Skip automatic delta-audit checks before planning.",
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

    plan_kwargs: dict = {
        "enabled": True,
        "task": task,
        "reviewer_model": reviewer,
        "auto_review": not no_review,
        "max_stories": max_stories,
    }
    if output:
        plan_kwargs["output_path"] = Path(output)

    plan_config = PlanConfig(**plan_kwargs)

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
        plan_result = await agent.run_plan(
            task,
            review_feedback=review_feedback,
            failure_details=failure_details,
            changed_files=changed_files or None,
            skip_delta_audit=skip_delta_audit,
        )
        typer.echo(f"\nPlan complete: {plan_result.summary()}")
        typer.echo(f"  Stories: {len(plan_result.stories)}")
        if plan_result.delta_audit is not None:
            typer.echo(
                f"  Delta audit: {plan_result.delta_audit.recommended_action} "
                f"({len(plan_result.delta_audit.triggers)} trigger(s))"
            )
        if plan_result.specialist_audits:
            typer.echo(f"  Specialist audits: {len(plan_result.specialist_audits)}")
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
