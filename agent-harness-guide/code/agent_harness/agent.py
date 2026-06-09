"""Agent: the main agentic loop.

Beginner note: this is the production (class-based) version of the loop. For the
same loop written with only functions, lists, and dicts, see the green "Beginner
track" boxes in ../../01-bare-harness.md and ../../07-subagents-orchestration.md
(and ../../BEGINNER-NOTES.md for the concept cheat-sheet). Read `agent.run(task)`
as "call the run() loop with this agent's data."
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Settings
from .conversation import Conversation, to_input_dict
from .context import count_items, prune_to_budget
from .hooks import HookRegistry
from .llm import LLMClient
from .permissions import PermissionMode, PermissionPolicy, check_permission, default_policy
from .tools.parallel import run_tool_calls
from .tools.registry import ToolRegistry


@dataclass
class UsageAccumulator:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.total_tokens += getattr(usage, "total_tokens", 0) or 0

    def __str__(self) -> str:
        return (
            f"Usage: {self.input_tokens} input + "
            f"{self.output_tokens} output = "
            f"{self.total_tokens} total tokens"
        )


class Agent:
    """Runs the agentic loop: call LLM -> dispatch tools -> loop.

    Parameters
    ----------
    name:
        Human-readable name for this agent.
    instructions:
        System-level instructions (the "system prompt").
    registry:
        ToolRegistry with all available tools.
    llm:
        LLMClient (or a FakeClient wrapper) for API calls.
    settings:
        Agent configuration.
    policy:
        Permission policy (defaults to ``default_policy()``).
    hooks:
        HookRegistry for pre/post hooks (defaults to empty).
    asker:
        Callable(prompt)->bool for interactive permission prompts.
        Tests pass an auto-approver; CLI passes input()-based prompt.
    max_workers:
        Thread-pool size for parallel tool execution.
    """

    def __init__(
        self,
        name: str = "Agent",
        instructions: str = "You are a helpful assistant.",
        registry: ToolRegistry | None = None,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
        policy: PermissionPolicy | None = None,
        hooks: HookRegistry | None = None,
        asker: Callable[[str], bool] | None = None,
        max_workers: int = 4,
    ) -> None:
        self.name = name
        self.instructions = instructions
        self.registry = registry or ToolRegistry()
        self.llm = llm or LLMClient()
        self.settings = settings or Settings()
        self.policy = policy or default_policy()
        self.hooks = hooks or HookRegistry()
        self.asker = asker
        self.max_workers = max_workers

        self.conversation = Conversation()
        self.usage = UsageAccumulator()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, task: str) -> str:
        """Run the agent loop for a user task. Returns final text output."""
        self.conversation.add_user(task)

        tools_schema = self.registry.to_openai_schema()
        iterations = 0

        while iterations < self.settings.max_iterations:
            iterations += 1

            # Budget check / prune
            current_items = self.conversation.to_input()
            if self.settings.max_context_tokens > 0:
                pruned = prune_to_budget(
                    current_items,
                    self.settings.max_context_tokens,
                    model=self.settings.model,
                )
                # If pruning changed things, update conversation
                if len(pruned) < len(current_items):
                    self.conversation.messages = pruned
                    current_items = pruned

            # Call the LLM
            response = self.llm.create(
                instructions=self.instructions,
                input=self.conversation.to_input(),
                tools=tools_schema,
            )

            # Accumulate usage
            self.usage.add(getattr(response, "usage", None))

            # Extend conversation with model's output
            output_items = getattr(response, "output", [])
            self.conversation.extend(output_items)

            # Collect function_call items
            fc_items = [
                item for item in output_items
                if getattr(item, "type", None) == "function_call"
                   or (isinstance(item, dict) and item.get("type") == "function_call")
            ]

            if not fc_items:
                # No tool calls — return the text response
                output_text = getattr(response, "output_text", "")
                if not output_text:
                    # Fallback: scan output items
                    for item in output_items:
                        t = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
                        if t == "message":
                            output_text = getattr(item, "output_text", "") or (
                                item.get("output_text", "") if isinstance(item, dict) else ""
                            )
                            if output_text:
                                break
                return output_text or ""

            # Process tool calls
            calls_to_run: list[dict] = []
            denied_results: list[dict[str, str]] = []

            for fc_item in fc_items:
                # Normalize to dict for consistent access
                if isinstance(fc_item, dict):
                    fc_dict = fc_item
                else:
                    fc_dict = to_input_dict(fc_item)

                tool_name = fc_dict.get("name", "")
                args_json = fc_dict.get("arguments", "{}")
                call_id = fc_dict.get("call_id", "")

                # Parse args for permission checking
                try:
                    args_dict = json.loads(args_json)
                except Exception:
                    args_dict = {}

                # Run pre-hooks
                pre_ctx = self.hooks.run_pre(tool_name, args_dict)
                if pre_ctx.blocked:
                    self.conversation.add_tool_result(
                        call_id,
                        f"Error: blocked by hook: {pre_ctx.block_reason}",
                    )
                    continue

                # Permission check
                allowed = check_permission(
                    tool_name=tool_name,
                    args=args_dict,
                    policy=self.policy,
                    mode=self.settings.permission_mode,
                    asker=self.asker,
                )
                if not allowed:
                    self.conversation.add_tool_result(
                        call_id,
                        f"Error: permission denied for {tool_name}",
                    )
                    continue

                calls_to_run.append({
                    "call_id": call_id,
                    "name": tool_name,
                    "arguments": args_json,
                    "_args_dict": args_dict,
                })

            # Dispatch all allowed calls in parallel
            if calls_to_run:
                # Strip internal _args_dict before passing to dispatcher
                dispatch_calls = [
                    {"call_id": c["call_id"], "name": c["name"], "arguments": c["arguments"]}
                    for c in calls_to_run
                ]
                results = run_tool_calls(self.registry, dispatch_calls, self.max_workers)

                # Post-hooks and record results
                args_by_call_id = {c["call_id"]: c["_args_dict"] for c in calls_to_run}
                name_by_call_id = {c["call_id"]: c["name"] for c in calls_to_run}

                for r in results:
                    call_id = r["call_id"]
                    output = r["output"]
                    tool_name = name_by_call_id.get(call_id, "")
                    args_dict = args_by_call_id.get(call_id, {})

                    post_ctx = self.hooks.run_post(tool_name, args_dict, output)
                    self.conversation.add_tool_result(call_id, post_ctx.output)

        # Max iterations reached
        return f"Error: max iterations ({self.settings.max_iterations}) reached without a final answer"
