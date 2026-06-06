"""Shared fixtures for the test suite."""
from __future__ import annotations

import pytest
from pathlib import Path

from agent_harness.config import Settings
from agent_harness.testing import FakeClient, FakeItem, fake_message, fake_function_call


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A temporary workspace directory."""
    return tmp_path


@pytest.fixture
def tmp_settings(tmp_workspace: Path) -> Settings:
    """Settings pointing at the temporary workspace."""
    return Settings(
        model="gpt-4o",
        max_iterations=10,
        permission_mode="always_allow",
        workspace_root=tmp_workspace,
        max_context_tokens=0,  # 0 = no pruning in tests
    )


@pytest.fixture
def fake_client_factory():
    """Factory that builds a FakeClient from a list of turn specifications."""
    def _factory(turns: list[list[FakeItem]]) -> FakeClient:
        return FakeClient(turns)
    return _factory


@pytest.fixture
def auto_approver():
    """An asker callable that always approves."""
    return lambda prompt: True
