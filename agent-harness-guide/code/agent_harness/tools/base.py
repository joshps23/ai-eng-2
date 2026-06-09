"""Base Tool class and @tool decorator.

Beginner note: a "tool" here is just a function plus a dict describing it. The
@tool decorator auto-builds that dict from the function's type hints; you can
instead write the dict by hand. See the "Beginner track" box in
../../02-tool-system.md for the functions-and-dicts version of this whole file.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints

# Python type -> JSON Schema type
_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(annotation: Any) -> str:
    """Map a Python type annotation to a JSON Schema type string."""
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    return _PY_TO_JSON.get(annotation, "string")


def _build_schema(func: Callable) -> dict:
    """Auto-generate a JSON Schema parameter object from a function signature."""
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        ann = hints.get(name, str)
        json_t = _json_type(ann)

        prop: dict[str, Any] = {"type": json_t}

        # Pull per-parameter description from docstring if present
        doc = inspect.getdoc(func) or ""
        # Simple heuristic: look for "name: description" lines in docstring
        for line in doc.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{name}:"):
                desc = stripped[len(f"{name}:"):].strip()
                if desc:
                    prop["description"] = desc
                break

        properties[name] = prop

        # Required = no default value
        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required

    return schema


@dataclass
class Tool:
    """A single callable tool exposed to the LLM."""

    name: str
    description: str
    parameters: dict  # JSON Schema dict
    run: Callable[..., str]
    risk: str = "low"  # low / medium / high
    # Strict mode makes the API guarantee the arguments match the schema, but it
    # requires EVERY property to be listed in "required" and
    # "additionalProperties": False. Our auto-generated schemas leave optional
    # parameters out of "required" (so the model can omit them), which is
    # incompatible with strict mode. Default to non-strict so tools with
    # optional params (e.g. bash's timeout, grep's recursive) are accepted.
    strict: bool = False

    def to_openai_schema(self) -> dict:
        schema: dict[str, Any] = {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        if self.strict:
            schema["strict"] = True
        return schema


def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    risk: str = "low",
) -> Tool | Callable:
    """Decorator that turns a plain Python function into a Tool.

    Can be used as @tool or @tool(name=..., description=..., risk=...).
    """

    def _wrap(fn: Callable) -> Tool:
        tool_name = name or fn.__name__
        tool_desc = description or (inspect.getdoc(fn) or "").split("\n")[0] or tool_name
        schema = _build_schema(fn)
        return Tool(
            name=tool_name,
            description=tool_desc,
            parameters=schema,
            run=fn,
            risk=risk,
        )

    if func is not None:
        # Used as @tool without arguments
        return _wrap(func)

    # Used as @tool(...) with arguments
    return _wrap
