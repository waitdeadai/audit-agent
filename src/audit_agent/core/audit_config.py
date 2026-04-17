"""AuditConfig — configuration for audit-agent runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanConfig(BaseModel):
    """Configuration for the planning phase (runs after audit)."""

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = Field(default=False)
    output_path: Path = Field(default_factory=lambda: Path(".forgegod/PLAN.md"))
    task: str = Field(default="")
    # Reviewer model for adversarial plan review (optional)
    reviewer_model: str | None = Field(default=None)
    # Auto-review the plan with a second model before writing
    auto_review: bool = Field(default=True)
    # Max stories to generate
    max_stories: int = Field(default=20)
    # Temperature for planning (lower = more deterministic)
    temperature: float = Field(default=0.3)
    # Temperature for reviewer (slightly higher for critique)
    review_temperature: float = Field(default=0.4)
    max_tokens: int = Field(default=8192)


class AuditConfig(BaseModel):
    """Configuration for audit-agent runs."""

    model_config = ConfigDict(protected_namespaces=())

    repo_root: Path = Field(default_factory=Path.cwd)
    output_path: Path = Field(default_factory=lambda: Path(".forgegod/AUDIT.md"))
    model: str = Field(default="minimax/minimax-m2.7-highspeed")
    temperature: float = Field(default=0.2)
    top_p: float = Field(default=0.9)
    max_tokens: int = Field(default=8000)
    stale_after_commits: int = Field(default=20)
    verbose: bool = Field(default=False)

    # Optional model overrides (fallback chain)
    model_fallback: str | None = Field(default=None)
    model_fallback2: str | None = Field(default=None)

    # MiniMax-specific settings
    minimax_api_key: str | None = Field(default=None)
    minimax_base_url: str = Field(default="https://api.minimax.io/v1")

    # Azure OpenAI settings
    azure_api_key: str | None = Field(default=None)
    azure_base_url: str | None = Field(default=None)
    azure_api_version: str = Field(default="2024-02-01")

    # Planning configuration (None = planning disabled)
    plan: PlanConfig | None = Field(default=None)

    def model_post_init(self, __context: Any) -> None:
        """Resolve repo-relative output paths after validation."""
        self.repo_root = self.repo_root.expanduser().resolve()
        self.output_path = _resolve_repo_path(self.repo_root, self.output_path)
        if self.plan is not None:
            self.plan.output_path = _resolve_repo_path(
                self.repo_root,
                self.plan.output_path,
            )

    def model_specs(self) -> list[tuple[str, str]]:
        """Return ordered (provider, model) pairs to try.

        Handles three formats:
        - "provider/model" (e.g. "openai/gpt-4o")
        - "provider:model" (e.g. "zai:glm-5", "minimax:MiniMax-M2.7")
        - bare model name (e.g. "glm-5") — assumes openai-compatible

        Yields the primary model first, then fallbacks in order.
        """
        specs: list[tuple[str, str]] = []
        for model_str in self._model_chain():
            # Try "/" first (OpenAI format)
            if "/" in model_str:
                provider, _, model = model_str.partition("/")
                if provider and model:
                    specs.append((provider, model))
                    continue
            # Try ":" (Z.AI / MiniMax Token Plan format)
            if ":" in model_str:
                provider, _, model = model_str.partition(":")
                if provider and model:
                    specs.append((provider, model))
                    continue
            # bare model name — assume openai-compatible
            specs.append(("openai", model_str))
        return specs

    def _model_chain(self) -> list[str]:
        """Build the full model chain including fallbacks."""
        chain: list[str] = []
        if self.model:
            chain.append(self.model)
        if self.model_fallback:
            chain.append(self.model_fallback)
        if self.model_fallback2:
            chain.append(self.model_fallback2)
        return chain


def _resolve_repo_path(repo_root: Path, path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return repo_root / expanded
