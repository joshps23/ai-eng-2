"""Sub-agent presets and dispatch utilities."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .config import Settings
from .llm import LLMClient
from .tools.base import Tool, tool
from .tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Presets: role -> (instructions, tool_names)
# ---------------------------------------------------------------------------

AGENT_PRESETS: dict[str, tuple[str, list[str]]] = {
    "researcher": (
        "You are a research assistant. You can read files and search for information. "
        "Do not write or modify files.",
        ["read_file", "glob_files", "grep", "list_dir"],
    ),
    "coder": (
        "You are a coding assistant. You can read and write files and run shell commands.",
        ["read_file", "write_file", "edit_file", "glob_files", "grep", "list_dir", "bash"],
    ),
    "reviewer": (
        "You are a code reviewer. You can read files and analyze code. "
        "You do not write or modify files.",
        ["read_file", "glob_files", "grep", "list_dir"],
    ),
}

_MAX_DEPTH = 3


def dispatch_subagent(
    role: str,
    task: str,
    parent_settings: Settings,
    llm: LLMClient,
    depth: int = 0,
    max_depth: int = _MAX_DEPTH,
    available_tools: ToolRegistry | None = None,
) -> str:
    """Spawn a sub-agent for *role* with *task* and return its text output.

    Depth guard prevents infinite recursion. On failure returns an error string.
    """
    if depth >= max_depth:
        return f"Error: max sub-agent depth ({max_depth}) reached"

    if role not in AGENT_PRESETS:
        return f"Error: unknown sub-agent role '{role}'"

    instructions, tool_names = AGENT_PRESETS[role]

    # Build a registry with only the allowed tools
    from .agent import Agent  # local import to avoid circular
    registry = ToolRegistry()
    if available_tools is not None:
        for name in tool_names:
            t = available_tools.get(name)
            if t is not None:
                registry.register(t)

    child_settings = Settings(
        model=parent_settings.model,
        max_iterations=min(parent_settings.max_iterations, 20),
        permission_mode="always_allow",
        workspace_root=parent_settings.workspace_root,
        max_context_tokens=parent_settings.max_context_tokens,
    )

    try:
        agent = Agent(
            name=f"{role}-subagent",
            instructions=instructions,
            registry=registry,
            llm=llm,
            settings=child_settings,
        )
        return agent.run(task)
    except Exception as exc:
        return f"Error: sub-agent failed: {exc}"


def make_task_tool(
    parent_settings: Settings,
    llm: LLMClient,
    available_tools: ToolRegistry | None = None,
    depth: int = 0,
) -> Tool:
    """Return a Tool that spawns a sub-agent when called by the parent agent."""

    def _run_task(role: str, task: str) -> str:
        """Dispatch a sub-agent for a specific role and task.

        role: Agent role: researcher, coder, or reviewer.
        task: The task description for the sub-agent.
        """
        return dispatch_subagent(
            role=role,
            task=task,
            parent_settings=parent_settings,
            llm=llm,
            depth=depth + 1,
            available_tools=available_tools,
        )

    from .tools.base import _build_schema, Tool as _Tool
    schema = _build_schema(_run_task)
    return _Tool(
        name="task",
        description="Delegate a task to a specialized sub-agent (researcher/coder/reviewer).",
        parameters=schema,
        run=_run_task,
        risk="medium",
    )


def run_subagents_parallel(
    tasks: list[tuple[str, str]],  # list of (role, task)
    parent_settings: Settings,
    llm: LLMClient,
    available_tools: ToolRegistry | None = None,
    depth: int = 0,
    max_workers: int = 3,
) -> list[str]:
    """Run multiple sub-agents in parallel; return their results in order."""

    results: dict[int, str] = {}

    def _run(idx: int, role: str, task: str) -> tuple[int, str]:
        output = dispatch_subagent(
            role=role,
            task=task,
            parent_settings=parent_settings,
            llm=llm,
            depth=depth + 1,
            available_tools=available_tools,
        )
        return idx, output

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run, i, role, task): i
            for i, (role, task) in enumerate(tasks)
        }
        for future in as_completed(futures):
            idx, output = future.result()
            results[idx] = output

    return [results[i] for i in range(len(tasks))]
