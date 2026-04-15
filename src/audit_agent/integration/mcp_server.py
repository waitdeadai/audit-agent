"""MCP stdio JSON-RPC server for audit-agent.

Implements the Model Context Protocol over stdio.
Supports: audit/run, audit/status, audit/diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


class AuditMCPServer:
    """MCP server using stdio transport.

    Methods:
        - audit/run: Run full audit on a repo
        - audit/status: Check if AUDIT.md is current
        - audit/diff: Show changes since last audit
    """

    def __init__(self, repo_root: Path | None = None):
        self.repo_root = repo_root or Path.cwd()
        self._audit_result: dict | None = None

    async def handle_request(self, method: str, params: dict) -> dict:
        """Handle an MCP JSON-RPC request."""
        handler = {
            "audit/run": self._run_audit,
            "audit/status": self._check_status,
            "audit/diff": self._diff_audit,
        }.get(method)

        if not handler:
            return {
                "error": {
                    "code": -32601,
                    "message": f"Unknown method: {method}",
                }
            }

        try:
            return await handler(params)
        except Exception as e:
            return {
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {e}",
                }
            }

    async def _run_audit(self, params: dict) -> dict:
        """Run the full 11-step audit."""
        from audit_agent import AuditAgent, AuditConfig

        repo = Path(params.get("repo", "."))
        output = params.get("output")
        config = AuditConfig(
            repo_root=repo,
            output_path=Path(output) if output else repo / ".forgegod" / "AUDIT.md",
        )
        agent = AuditAgent(config)
        result = await agent.run()
        self._audit_result = {
            "audit_agent": {
                "version": "1.0",
                "repo": repo.name,
                "ready_to_plan": result.ready_to_plan,
                "blockers": result.blockers,
            }
        }
        return {"result": self._audit_result}

    async def _check_status(self, params: dict) -> dict:
        """Check if AUDIT.md is current."""
        from audit_agent.integration.forgegod_integration import check_audit_status

        repo = Path(params.get("repo", "."))
        stale_after = params.get("stale_after", 20)
        status = await check_audit_status(repo, stale_after)
        return {
            "result": {
                "status": status.value,
                "repo": repo.name,
            }
        }

    async def _diff_audit(self, params: dict) -> dict:
        """Show what changed since the last audit."""
        repo = Path(params.get("repo", "."))
        audit_path = repo / ".forgegod" / "AUDIT.md"
        if not audit_path.exists():
            return {"result": {"diff": None, "reason": "No AUDIT.md found"}}

        import subprocess
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "diff", str(audit_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return {
                "result": {
                    "diff": result.stdout or "(no changes staged)",
                    "repo": repo.name,
                }
            }
        except Exception as e:
            return {"result": {"diff": None, "error": str(e)}}


async def main():
    """Entry point for MCP server — reads JSON-RPC from stdin, writes to stdout."""
    server = AuditMCPServer()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id")
            response = await server.handle_request(method, params)
            if req_id is not None:
                response["id"] = req_id
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            continue


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
