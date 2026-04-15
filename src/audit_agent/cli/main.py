"""CLI entry point for audit-agent."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from audit_agent.core.agent import AuditAgent
from audit_agent.core.config import AuditConfig

app = typer.Typer(
    name="audit",
    help="Mandatory pre-planning auditor — produces AUDIT.md via 11-step protocol.",
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


@app.callback()
def main() -> None:
    """audit — Mandatory pre-planning auditor for AI coding agents."""
    pass


if __name__ == "__main__":
    app()