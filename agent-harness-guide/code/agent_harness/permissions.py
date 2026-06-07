"""Permission system for tool execution."""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class PermissionMode(str, Enum):
    """Operating mode that determines how permissions are handled."""

    PLAN = "plan"               # Only show plans; no writes
    AUTO = "auto"               # Ask for medium/high risk
    ACCEPT_EDITS = "accept_edits"  # Auto-accept file edits; ask for shell
    ALWAYS_ALLOW = "always_allow"  # Allow everything (still obey hard denies)
    BYPASS = "bypass"           # Bypass all permission checks


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class Rule:
    """A single permission rule."""

    pattern: str          # fnmatch pattern matched against "tool_name(arg_summary)"
    decision: Decision


@dataclass
class PermissionPolicy:
    """Ordered list of rules; first match wins."""

    rules: list[Rule] = field(default_factory=list)

    def evaluate(self, tool_name: str, arg_summary: str) -> Decision | None:
        """Return the first matching decision, or None (no match)."""
        key = f"{tool_name}({arg_summary})"
        for rule in self.rules:
            if fnmatch.fnmatch(key, rule.pattern):
                return rule.decision
        return None


# Hard-deny patterns — always blocked regardless of mode
_HARD_DENY_PATTERNS = [
    "bash(* rm -rf *)",
    "bash(*rm -rf*)",
    "bash(*sudo rm*)",
    "bash(*:(){:|:&};:*)",  # fork bomb
    "bash(*> /dev/sda*)",
]


def default_policy() -> PermissionPolicy:
    """Return a sensible default permission policy with hard denies."""
    rules = [
        Rule(pattern=pat, decision=Decision.DENY)
        for pat in _HARD_DENY_PATTERNS
    ]
    return PermissionPolicy(rules=rules)


def _arg_summary(args: dict, truncate: bool = True) -> str:
    """Produce a string representation of args.

    truncate=True shortens long values for a readable human prompt.
    truncate=False keeps the full text — REQUIRED for hard-deny matching, so a
    long command can't push a dangerous substring (e.g. "rm -rf") past the cap
    and silently bypass the deny rules.
    """
    parts = []
    for v in args.values():
        s = str(v)
        if truncate and len(s) > 60:
            s = s[:60] + "..."
        parts.append(s)
    return " ".join(parts)


def check_permission(
    tool_name: str,
    args: dict,
    policy: PermissionPolicy,
    mode: PermissionMode | str,
    asker: Callable[[str], bool] | None = None,
) -> bool:
    """Check whether executing tool_name with args is permitted.

    Returns True (allowed) or False (denied).
    On ASK: calls asker(prompt)->bool; if asker is None defaults to False.
    """
    mode = PermissionMode(mode) if isinstance(mode, str) else mode
    summary = _arg_summary(args)                       # for display
    full_summary = _arg_summary(args, truncate=False)  # for matching

    # Bypass mode skips everything
    if mode == PermissionMode.BYPASS:
        return True

    # Always check hard denies first (even in always_allow mode).
    # Match against the FULL (untruncated) args so denies can't be evaded.
    decision = policy.evaluate(tool_name, full_summary)
    if decision == Decision.DENY:
        return False

    # PLAN mode: deny all writes/shell
    if mode == PermissionMode.PLAN:
        write_tools = {"write_file", "edit_file", "bash"}
        if tool_name in write_tools:
            return False

    # ALWAYS_ALLOW: permit after hard-deny check
    if mode == PermissionMode.ALWAYS_ALLOW:
        return True

    # Policy ALLOW
    if decision == Decision.ALLOW:
        return True

    # ACCEPT_EDITS: auto-accept file edits, ask for bash
    if mode == PermissionMode.ACCEPT_EDITS:
        if tool_name in {"write_file", "edit_file"}:
            return True
        # Falls through to ASK for bash / unknown

    # AUTO mode: allow read-only tools automatically
    if mode == PermissionMode.AUTO:
        read_tools = {"read_file", "list_dir", "glob_files", "grep"}
        if tool_name in read_tools:
            return True

    # Ask the user / auto-approver
    if decision == Decision.ASK or mode in (PermissionMode.AUTO, PermissionMode.ACCEPT_EDITS):
        prompt = f"Allow {tool_name}({summary})? [y/N] "
        if asker is not None:
            return asker(prompt)
        return False

    # Default deny
    return False
