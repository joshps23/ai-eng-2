"""Settings and configuration for the agent harness."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MODEL_DEFAULT = "gpt-4o"


@dataclass
class Settings:
    """Configuration for an Agent run."""

    model: str = MODEL_DEFAULT
    max_iterations: int = 50
    # permission_mode values: plan, auto, accept_edits, always_allow, bypass
    permission_mode: str = "auto"
    workspace_root: Path = field(default_factory=lambda: Path(os.getcwd()))
    max_context_tokens: int = 128_000

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root)
