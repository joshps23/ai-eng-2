"""ToolRegistry: register, schema export, and dispatch."""
from __future__ import annotations

import json
from typing import Any

from .base import Tool


class ToolRegistry:
    """Maintains a collection of Tools and dispatches calls from the LLM."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        """Register a Tool instance."""
        self._tools[t.name] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def to_openai_schema(self) -> list[dict]:
        """Return list of tool defs in OpenAI Responses API flat format."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def dispatch(self, name: str, args_json_str: str) -> str:
        """Parse args_json_str, call the named tool, return string result.

        NEVER raises into the caller — all exceptions become "Error: ..." strings.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"

        try:
            args: dict[str, Any] = json.loads(args_json_str)
        except json.JSONDecodeError as exc:
            return f"Error: invalid JSON arguments: {exc}"

        # Basic required-key validation
        required = tool.parameters.get("required", [])
        missing = [k for k in required if k not in args]
        if missing:
            return f"Error: missing required arguments: {missing}"

        try:
            result = tool.run(**args)
            return str(result)
        except Exception as exc:  # noqa: BLE001
            return f"Error: {exc}"
