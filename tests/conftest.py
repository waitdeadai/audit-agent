import pytest
import sys
from pathlib import Path

# Ensure src/ is on path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def repo_root():
    """Path to the audit-agent repo root (self-audit)."""
    return Path(__file__).parent.parent.resolve()


@pytest.fixture
def mock_audit_config(repo_root, tmp_path):
    """Minimal AuditConfig pointing at the audit-agent repo."""
    from audit_agent.core.audit_config import AuditConfig
    return AuditConfig(
        repo_root=repo_root,
        output_path=tmp_path / "AUDIT.md",
        model="minimax/minimax-m2.7-highspeed",
        temperature=0.2,
        max_tokens=100,
        verbose=False,
    )