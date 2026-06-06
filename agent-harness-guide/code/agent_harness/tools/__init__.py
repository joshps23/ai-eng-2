"""Tools package: Tool dataclass, @tool decorator, ToolRegistry."""

from .base import Tool, tool
from .registry import ToolRegistry

__all__ = ["Tool", "tool", "ToolRegistry"]
