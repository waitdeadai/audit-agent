"""AuditConfig — configuration for audit-agent runs."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class PlanConfig(BaseModel):
    """Configuration for the planning phase (runs after audit)."""

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

    def model_specs(self) -> list[tuple[str, str]]:
        """Return ordered (provider, model) pairs to try.

        Yields the primary model first, then fallbacks in order.
        """
        specs: list[tuple[str, str]] = []
        for model_str in self._model_chain():
            provider, _, model = model_str.partition("/")
            if provider and model:
                specs.append((provider, model))
            else:
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