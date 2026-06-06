"""Hook system for pre/post tool execution."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class PreToolContext:
    """Context passed to pre-execution hooks."""

    tool_name: str
    args: dict[str, Any]
    blocked: bool = False           # Hook can set True to block execution
    block_reason: str = ""


@dataclass
class PostToolContext:
    """Context passed to post-execution hooks."""

    tool_name: str
    args: dict[str, Any]
    output: str                     # Hook can mutate this


PreHook = Callable[[PreToolContext], None]
PostHook = Callable[[PostToolContext], None]


class HookRegistry:
    """Registry of pre and post tool hooks."""

    def __init__(self) -> None:
        self.pre_hooks: list[PreHook] = []
        self.post_hooks: list[PostHook] = []

    def add_pre_hook(self, hook: PreHook) -> None:
        self.pre_hooks.append(hook)

    def add_post_hook(self, hook: PostHook) -> None:
        self.post_hooks.append(hook)

    def run_pre(self, tool_name: str, args: dict) -> PreToolContext:
        ctx = PreToolContext(tool_name=tool_name, args=args)
        for hook in self.pre_hooks:
            hook(ctx)
            if ctx.blocked:
                break
        return ctx

    def run_post(self, tool_name: str, args: dict, output: str) -> PostToolContext:
        ctx = PostToolContext(tool_name=tool_name, args=args, output=output)
        for hook in self.post_hooks:
            hook(ctx)
        return ctx


# --------------------------------------------------------------------------- #
#  Built-in example hooks
# --------------------------------------------------------------------------- #

_DANGEROUS_PATTERNS = [
    re.compile(r"rm\s+-rf"),
    re.compile(r"sudo\s+rm"),
    re.compile(r":.*\(\)\s*\{.*\|.*&"),  # fork bomb
    re.compile(r">\s*/dev/sda"),
]


def dangerous_command_blocker(ctx: PreToolContext) -> None:
    """Pre-hook: block obviously dangerous shell commands."""
    if ctx.tool_name != "bash":
        return
    command = ctx.args.get("command", "")
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            ctx.blocked = True
            ctx.block_reason = f"Blocked dangerous pattern: {pattern.pattern!r}"
            return


_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{20,}")


def secret_scrubber(ctx: PostToolContext) -> None:
    """Post-hook: redact API key-like strings from tool output."""
    ctx.output = _SECRET_PATTERN.sub("[REDACTED]", ctx.output)


def audit_logger(log_path: Path) -> PostHook:
    """Factory: returns a post-hook that appends JSONL audit entries."""

    def _log(ctx: PostToolContext) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": ctx.tool_name,
            "args": ctx.args,
            "output_preview": ctx.output[:200],
        }
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    return _log
