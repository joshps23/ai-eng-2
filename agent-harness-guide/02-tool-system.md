# Phase 2 — A Real Tool System

## Where We Left Off

Phase 1 gave us a working agent loop in roughly 80 lines. The dispatch logic looked something like this:

```python
def dispatch(name: str, arguments: str) -> str:
    args = json.loads(arguments)
    if name == "add":
        return str(args["a"] + args["b"])
    raise ValueError(f"Unknown tool: {name}")
```

That works for a demo. It does not work for anything else. Every new tool requires editing the dispatch function, the tool list passed to the API, and potentially the argument parsing. There is no schema generation, no validation, no structure, and no way to run multiple tools concurrently. This phase replaces the entire approach.

By the end of this phase you will have:

- A `Tool` base class with a clean interface
- A `@tool` decorator that generates JSON Schema automatically from Python type hints and docstrings
- A `ToolRegistry` that owns registration, schema export, dispatch, and parallel execution
- An updated agent loop that is completely decoupled from individual tool implementations
- A concrete demonstration of parallel tool execution

---

## 1. The Problem with Ad-Hoc Dispatch

The Phase 1 approach has five concrete failure modes:

**No single source of truth.** The tool's schema (sent to the model) and the tool's implementation (called at runtime) are defined in separate places. They drift.

**No validation.** If the model sends `{"a": "hello", "b": 2}` for an `add` tool expecting integers, the error surfaces as a Python `TypeError` inside dispatch. You either crash the loop or you catch it with a bare `except` that swallows all errors equally.

**No extensibility.** Adding a tool means touching at least three places: the schema list, the dispatch function, and probably a test. In a real project these are often in different files touched by different people.

**No parallelism.** The Responses API can return multiple `function_call` items in a single response. Phase 1 runs them serially with a for-loop. If tool A takes 2 seconds and tool B takes 2 seconds, you wait 4 seconds when you could wait 2.

**No error contract.** A tool that raises an unhandled exception kills the loop. The model never finds out what went wrong. The user sees a traceback instead of a graceful error message.

Good tooling infrastructure requires:

- **Registration**: a central place that maps names to implementations and schemas
- **Schema generation**: deriving the JSON Schema automatically from Python code so they cannot drift
- **Validation**: checking arguments before calling the tool
- **Parallel execution**: running independent tool calls concurrently
- **Structured errors**: returning error information as strings so the model can reason about failures

---

## 2. The `Tool` Abstraction — `tools/base.py`

Start with a clear interface. Every tool is an object with a name, a description, a JSON Schema for its parameters, and a `run` method that accepts keyword arguments and returns a string.

### 2a. Subclassing

The explicit approach: subclass `Tool` and override `run`.

```python
# tools/base.py
from __future__ import annotations

import inspect
import json
import traceback
import types
from typing import Any, Callable, get_type_hints


class Tool:
    """Base class for all tools. Subclass and override `run`."""

    name: str
    description: str
    parameters: dict  # JSON Schema object

    def run(self, **kwargs: Any) -> str:
        raise NotImplementedError


class AddTool(Tool):
    name = "add"
    description = "Return the sum of two numbers."
    parameters = {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First operand"},
            "b": {"type": "number", "description": "Second operand"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    }

    def run(self, a: float, b: float) -> str:
        return str(a + b)
```

This works but it is verbose. For every tool you must write the JSON Schema by hand, which means the schema and the Python signature can drift again.

### 2b. The `@tool` Decorator

The better approach: write a plain Python function with type hints and a docstring. The decorator generates the JSON Schema automatically.

```python
# tools/base.py  (continued — full file shown at the end of this section)

# Maps Python types to JSON Schema type strings
_PY_TO_JSON: dict[type, str] = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}


def _build_schema(fn: Callable) -> dict:
    """
    Introspect a function and produce a JSON Schema for its parameters.

    Rules:
    - Parameters with no default are marked required.
    - Parameter descriptions come from the docstring (Google style: "name: desc").
    - Return annotation is ignored (tools always return str at runtime).
    - *args and **kwargs are ignored.
    """
    hints = get_type_hints(fn)
    sig   = inspect.signature(fn)
    doc   = inspect.getdoc(fn) or ""

    # Parse "Args:" block from Google-style docstring for per-param descriptions
    param_docs: dict[str, str] = {}
    in_args = False
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.lower() in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if stripped and not stripped[0].isspace() and stripped.endswith(":"):
                # New top-level section — stop
                in_args = False
            elif ":" in stripped:
                pname, _, pdesc = stripped.partition(":")
                param_docs[pname.strip()] = pdesc.strip()

    # The first non-empty line before "Args:" is the function description
    fn_description = ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.lower() in ("args:", "arguments:", "parameters:"):
            break
        if stripped:
            fn_description = stripped
            break

    properties: dict[str, dict] = {}
    required:   list[str]       = []

    for pname, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        py_type = hints.get(pname, str)
        json_type = _PY_TO_JSON.get(py_type, "string")

        prop: dict[str, Any] = {"type": json_type}
        if pname in param_docs:
            prop["description"] = param_docs[pname]

        properties[pname] = prop

        if param.default is inspect.Parameter.empty:
            required.append(pname)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
        "description": fn_description,
    }


def tool(fn: Callable) -> "FunctionTool":
    """
    Decorator. Converts a plain function into a Tool instance.

    Usage::

        @tool
        def add(a: int, b: int) -> str:
            \"\"\"Add two integers.

            Args:
                a: First operand.
                b: Second operand.
            \"\"\"
            return str(a + b)

    The resulting object is a Tool; its .parameters dict is auto-generated.
    """
    schema = _build_schema(fn)
    return FunctionTool(
        name=fn.__name__,
        description=schema.pop("description", fn.__doc__ or ""),
        parameters=schema,
        fn=fn,
    )


class FunctionTool(Tool):
    """A Tool wrapping a plain callable, produced by the @tool decorator."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        fn: Callable,
    ) -> None:
        self.name        = name
        self.description = description
        self.parameters  = parameters
        self._fn         = fn

    def run(self, **kwargs: Any) -> str:
        result = self._fn(**kwargs)
        # Tools must return strings. Coerce if needed.
        if not isinstance(result, str):
            return json.dumps(result)
        return result
```

### Seeing the Generated Schema

Let's verify what the decorator actually produces for a real function:

```python
@tool
def word_count(text: str, strip_punctuation: bool = False) -> str:
    """Count the number of words in a string.

    Args:
        text: The text to count words in.
        strip_punctuation: If true, punctuation is removed before counting.
    """
    import re
    if strip_punctuation:
        text = re.sub(r"[^\w\s]", "", text)
    return str(len(text.split()))


import json
print(json.dumps(word_count.parameters, indent=2))
```

Output:

```text
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "description": "The text to count words in."
    },
    "strip_punctuation": {
      "type": "boolean",
      "description": "If true, punctuation is removed before counting."
    }
  },
  "required": [
    "text"
  ],
  "additionalProperties": false
}
```

`text` is required because it has no default. `strip_punctuation` is optional because it defaults to `False`. The descriptions came from the docstring. Nothing was written by hand.

### Python-to-JSON Schema Type Mapping

| Python type | JSON Schema `"type"` | Notes |
|-------------|----------------------|-------|
| `str`       | `"string"`           |       |
| `int`       | `"integer"`          | Excludes floats |
| `float`     | `"number"`           | Includes integers |
| `bool`      | `"boolean"`          | Must come before `int` in lookup since `bool` is a subclass of `int` |
| `list`      | `"array"`            | No item type enforcement at schema level |
| `dict`      | `"object"`           | No property type enforcement at schema level |
| anything else | `"string"`         | Conservative fallback |

> **Warning — `bool` before `int`.** In Python, `bool` is a subclass of `int`. If your lookup table iterates in the wrong order you will map `bool` parameters to `"integer"`. The `_PY_TO_JSON` dict above is ordered correctly in Python 3.7+ because dict preserves insertion order, and `bool` appears before `int` in the literal. If you ever switch to `isinstance` checks, test `bool` first.

> **Warning — mutable defaults.** If a function parameter has a mutable default like `def fn(items: list = [])`, `_build_schema` will still mark it optional correctly. But at call time, Python's mutable default trap still applies. Tools should use `None` as the default and construct the mutable object inside the function body. The decorator does not fix this for you.

---

## 3. The Tool Registry

The registry is the single object that knows about all tools. It owns three responsibilities: registering tools, exporting the API schema, and dispatching calls.

```python
# tools/registry.py
from __future__ import annotations

import json
import traceback
from typing import Any

from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register(self, tool: Tool) -> None:
        """Add a tool to the registry."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    # ------------------------------------------------------------------ #
    # Schema export                                                        #
    # ------------------------------------------------------------------ #

    def to_openai_schema(self, strict: bool = True) -> list[dict]:
        """
        Return the tools list suitable for the `tools=` parameter of
        client.responses.create().

        Each entry is the FLAT format required by the Responses API:
            {
                "type": "function",
                "name": ...,
                "description": ...,
                "parameters": <JSON Schema>,
                "strict": True,
            }

        When strict=True (recommended for production), the API enforces
        that all required properties are present and no extra keys are sent.
        This requires that every schema has `additionalProperties: false`
        and every property is listed in `required` (for optional params,
        you must use `anyOf: [<type>, {"type": "null"}]` with a null default).
        The schemas produced by @tool already satisfy this with one caveat:
        optional parameters are NOT in `required`, so strict mode will reject
        them if the model omits them. For strict=True with optional params,
        promote them to required and include null in their type. For
        simplicity, the examples here use strict=False so optional params
        work without modification.
        """
        result = []
        for t in self._tools.values():
            entry: dict[str, Any] = {
                "type":        "function",
                "name":        t.name,
                "description": t.description,
                "parameters":  t.parameters,
            }
            if strict:
                entry["strict"] = True
            result.append(entry)
        return result

    # ------------------------------------------------------------------ #
    # Dispatch                                                             #
    # ------------------------------------------------------------------ #

    def dispatch(self, name: str, arguments_str: str) -> str:
        """
        Parse arguments_str as JSON, validate, call the tool, return result.

        NEVER raises. On any failure, returns an error string that the model
        can read and reason about.
        """
        # 1. Look up the tool
        if name not in self._tools:
            return f"Error: no tool named '{name}' is registered."

        tool = self._tools[name]

        # 2. Parse the arguments JSON
        try:
            args: dict = json.loads(arguments_str)
        except json.JSONDecodeError as exc:
            return f"Error: arguments are not valid JSON: {exc}"

        if not isinstance(args, dict):
            return "Error: arguments must be a JSON object."

        # 3. Validate (lightweight — see Section 4 for details)
        validation_error = _validate_args(tool, args)
        if validation_error:
            return f"Error: {validation_error}"

        # 4. Run the tool
        try:
            return tool.run(**args)
        except Exception as exc:
            return _format_exception(exc)


def _validate_args(tool: Tool, args: dict) -> str | None:
    """
    Lightweight argument validation. Returns an error message string or None.
    See Section 4 for a full explanation.
    """
    schema     = tool.parameters
    required   = schema.get("required", [])
    properties = schema.get("properties", {})

    # Check required keys are present
    for key in required:
        if key not in args:
            return f"missing required argument '{key}'"

    # Check no extra keys (mirrors additionalProperties: false)
    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in properties:
                return f"unexpected argument '{key}'"

    # Basic type checks
    _JSON_TYPE_CHECK = {
        "string":  str,
        "integer": int,
        "number":  (int, float),
        "boolean": bool,
        "array":   list,
        "object":  dict,
    }
    for key, value in args.items():
        if key not in properties:
            continue
        expected_json_type = properties[key].get("type")
        if expected_json_type and expected_json_type in _JSON_TYPE_CHECK:
            expected_py = _JSON_TYPE_CHECK[expected_json_type]
            # bool is a subclass of int; reject bool where int is expected
            if expected_json_type == "integer" and isinstance(value, bool):
                return f"argument '{key}' must be integer, got boolean"
            if not isinstance(value, expected_py):
                return (
                    f"argument '{key}' must be {expected_json_type}, "
                    f"got {type(value).__name__}"
                )

    return None


def _format_exception(exc: Exception, include_traceback: bool = False) -> str:
    """
    Convert an exception into a model-readable error string.
    Never re-raises.
    """
    lines = [f"Error ({type(exc).__name__}): {exc}"]
    if include_traceback:
        tb = traceback.format_exc()
        # Truncate very long tracebacks so they do not flood the context window
        if len(tb) > 1000:
            tb = tb[:1000] + "\n... (truncated)"
        lines.append(tb)
    return "\n".join(lines)
```

---

## 4. Argument Validation: Strict Mode vs. Manual Checks

The Responses API supports a `"strict": True` field on each tool definition. When strict mode is active, the API guarantees:

1. The model will only send keys that are listed in `properties`.
2. The model will always send every key listed in `required`.
3. `additionalProperties` must be set to `false` in the schema.
4. Every property in `properties` must appear in `required` — there are no genuinely optional parameters in strict mode. To make a parameter "optional in meaning," you add `null` to its type (`anyOf: [{type: "string"}, {type: "null"}]`) and include it in `required`. The model can then send `null` for it.

This is a strong guarantee and it means you can skip the manual validation step shown in `_validate_args` — the API has already done it before the model's response reaches you.

The manual validation in the code above serves two purposes:

- It works when `strict=False`, which is necessary when your schema has genuinely optional parameters that are not null-typed.
- It documents exactly what strict mode is enforcing, so you understand the contract.

**For production: use `strict=True` and make all parameters required (using null for truly optional ones).** The API error messages when the model violates the schema are clearer than your own validation, and the enforcement happens before the response arrives so there is zero overhead in your loop.

### Strict-Compatible Schema Example

A tool with one required param and one "optional" param, strict-mode compatible:

```python
# Instead of:
#   "strip_punctuation": {"type": "boolean"}  (and not in required)
#
# Use:
{
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "The text to analyze."
        },
        "strip_punctuation": {
            "anyOf": [{"type": "boolean"}, {"type": "null"}],
            "description": "Remove punctuation before counting. Null means false.",
            "default": None
        }
    },
    "required": ["text", "strip_punctuation"],
    "additionalProperties": False
}
```

The `@tool` decorator does not currently generate this form automatically; it outputs simple schemas that work with `strict=False`. For a production system, you would either extend the decorator to accept `strict=True` and emit null-typed optionals, or write schemas by hand for strict-mode tools.

---

## 5. Parallel Tool Calls

The Responses API can return multiple `function_call` items in a single response. This happens when the model determines that several tools can be called simultaneously — for example, looking up two different pieces of information.

A single response `resp.output` might contain:

```python
[
    function_call(name="get_weather", call_id="call_abc", arguments='{"city": "Paris"}'),
    function_call(name="get_weather", call_id="call_def", arguments='{"city": "Tokyo"}'),
]
```

Both calls need results before the model can proceed. Running them serially wastes time. Since most tools are I/O-bound (network calls, file reads, subprocess runs), they release the GIL and `ThreadPoolExecutor` gives true concurrency.

### Parallel Dispatch

```python
# tools/parallel.py
from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry


def dispatch_parallel(
    registry: "ToolRegistry",
    function_calls: list,   # list of function_call output items from resp.output
    max_workers: int = 8,
) -> list[dict]:
    """
    Execute all function_call items concurrently.

    Returns a list of function_call_output dicts ready to be appended to
    input_items. Order in the returned list does not matter; the API matches
    results to calls via call_id.

    Each function_call item has:
        .name          - tool name
        .arguments     - JSON string
        .call_id       - must appear in the matching output
    """
    results: list[dict] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tool calls immediately
        future_to_call_id = {
            executor.submit(
                registry.dispatch,
                fc.name,
                fc.arguments,
            ): fc.call_id
            for fc in function_calls
        }

        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_call_id):
            call_id = future_to_call_id[future]
            try:
                output = future.result()
            except Exception as exc:
                # dispatch() never raises, but be defensive
                output = f"Error (unexpected): {exc}"

            results.append({
                "type":    "function_call_output",
                "call_id": call_id,
                "output":  output,
            })

    return results
```

### Sequential Fallback

Sometimes you cannot parallelize: if tool A writes to a database and tool B reads from the same table, running them concurrently is a race condition. Provide a sequential version for those cases:

```python
def dispatch_sequential(
    registry: "ToolRegistry",
    function_calls: list,
) -> list[dict]:
    """Execute tool calls one at a time, preserving order."""
    results = []
    for fc in function_calls:
        output = registry.dispatch(fc.name, fc.arguments)
        results.append({
            "type":    "function_call_output",
            "call_id": fc.call_id,
            "output":  output,
        })
    return results
```

### When Parallel is Unsafe

Use `dispatch_sequential` when:

- Tools share mutable state (in-memory caches, open file handles, database transactions) and the calls are not independent.
- Tool A's output is the input to Tool B (though in this case the model should not call them in the same turn).
- Tools have side effects that must happen in a specific order (e.g., "create record" then "send notification").

Use `dispatch_parallel` when:

- Tools make network requests to different services.
- Tools read from external APIs or databases without writing.
- Tools are pure functions with no shared state.

The safe default for unknown tools is sequential. Switch to parallel only when you understand each tool's side effects.

---

## 6. Structured Results and Errors

### The String Contract

Every tool returns a string. This is not a limitation — it is a deliberate interface boundary. The model receives text; strings are the natural unit.

For structured data, JSON-encode it:

```python
@tool
def get_user(user_id: int) -> str:
    """Fetch a user record by ID.

    Args:
        user_id: The user's numeric ID.
    """
    # Simulate a database lookup
    user = {"id": user_id, "name": "Ada Lovelace", "role": "engineer"}
    return json.dumps(user)
```

The model will see `{"id": 42, "name": "Ada Lovelace", "role": "engineer"}` and can reason about the fields naturally. Do not return a Python `repr` or a pretty-printed table — JSON is the most reliably parseable format for the model.

### Error Strings

When a tool fails, return an error string. Never raise. The `dispatch` method in `ToolRegistry` already wraps `tool.run()` in a try/except, but tools themselves must not raise either:

```python
@tool
def safe_divide(numerator: float, denominator: float) -> str:
    """Divide numerator by denominator.

    Args:
        numerator: The dividend.
        denominator: The divisor.
    """
    if denominator == 0:
        return "Error: cannot divide by zero."
    return str(numerator / denominator)
```

The `_format_exception` helper in `ToolRegistry` produces:

```text
Error (ZeroDivisionError): division by zero
```

This string is the tool output. The model reads it, understands something went wrong, and can inform the user or try a different approach. The agent loop continues normally.

---

## 7. The Updated Agent Loop

With the registry and parallel dispatch in place, the agent loop becomes completely decoupled from individual tools.

```python
# agent.py
from __future__ import annotations

from openai import OpenAI

from tools.registry import ToolRegistry
from tools.parallel import dispatch_parallel

client = OpenAI()
MODEL  = "gpt-5"


def run_agent(
    instructions:  str,
    user_message:  str,
    registry:      ToolRegistry,
    parallel:      bool = True,
    max_turns:     int  = 10,
) -> str:
    """
    Run the agent loop until the model produces a final text response.

    Parameters
    ----------
    instructions:  System-level instructions for the model.
    user_message:  The user's initial message.
    registry:      Populated ToolRegistry. Owns tool schemas and dispatch.
    parallel:      If True, tool calls in a single turn run concurrently.
    max_turns:     Hard limit on loop iterations to prevent infinite loops.

    Returns
    -------
    The model's final text response as a string.
    """
    input_items: list[dict] = [{"role": "user", "content": user_message}]
    tools_schema = registry.to_openai_schema(strict=False)

    for turn in range(max_turns):
        resp = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=input_items,
            tools=tools_schema,
        )

        # Extend the conversation history with everything the model output
        input_items += resp.output

        # Collect function_call items from this turn
        function_calls = [
            item for item in resp.output
            if item.type == "function_call"
        ]

        if not function_calls:
            # No tool calls — the model is done. Extract the text response.
            for item in resp.output:
                if item.type == "message":
                    for part in item.content:
                        if part.type == "output_text":
                            return part.text
            # Fallback: no text found (should not happen)
            return ""

        # Execute tool calls (parallel or sequential)
        if parallel:
            tool_outputs = dispatch_parallel(registry, function_calls)
        else:
            from tools.parallel import dispatch_sequential
            tool_outputs = dispatch_sequential(registry, function_calls)

        # Append all tool results to the conversation
        input_items.extend(tool_outputs)

        # Log usage for this turn
        print(
            f"[turn {turn + 1}] "
            f"tools={[fc.name for fc in function_calls]} "
            f"tokens={resp.usage.input_tokens}+{resp.usage.output_tokens}"
            f"={resp.usage.total_tokens}"
        )

    raise RuntimeError(f"Agent did not finish within {max_turns} turns.")
```

Key points in this loop:

- `resp.output` is appended wholesale to `input_items` before anything else. This is the handshake: the model's output becomes part of the next input.
- `function_call_output` items are appended after `resp.output`. Every `function_call` item in `resp.output` must have a matching `function_call_output` in `input_items` before the next `responses.create` call.
- The loop terminates when no `function_call` items appear in `resp.output`.
- `max_turns` is a hard guard against runaway loops. 10 is a reasonable default for most tasks; increase it for complex multi-step agents.

---

## 8. Full Runnable Example

Here is the complete file layout and a runnable script.

### File Layout

```text
project/
├── agent.py
└── tools/
    ├── __init__.py
    ├── base.py
    ├── registry.py
    └── parallel.py
```

### `tools/base.py` — Complete

```python
# tools/base.py
from __future__ import annotations

import inspect
import json
import traceback
import types
from typing import Any, Callable, get_type_hints


_PY_TO_JSON: dict[type, str] = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}


class Tool:
    """Base class for all tools."""
    name:        str
    description: str
    parameters:  dict

    def run(self, **kwargs: Any) -> str:
        raise NotImplementedError


class FunctionTool(Tool):
    def __init__(self, name: str, description: str, parameters: dict, fn: Callable) -> None:
        self.name        = name
        self.description = description
        self.parameters  = parameters
        self._fn         = fn

    def run(self, **kwargs: Any) -> str:
        result = self._fn(**kwargs)
        if not isinstance(result, str):
            return json.dumps(result)
        return result


def _parse_google_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Return (function_description, {param_name: param_description})."""
    fn_desc    = ""
    param_docs: dict[str, str] = {}
    in_args    = False

    for line in doc.splitlines():
        stripped = line.strip()
        if not fn_desc and stripped and not stripped.lower().endswith(":"):
            fn_desc = stripped
        if stripped.lower() in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if stripped and not line.startswith((" ", "\t")):
                in_args = False
            elif ":" in stripped:
                pname, _, pdesc = stripped.partition(":")
                param_docs[pname.strip()] = pdesc.strip()

    return fn_desc, param_docs


def _build_schema(fn: Callable) -> dict:
    """Derive a JSON Schema from a function's signature, hints, and docstring."""
    hints = get_type_hints(fn)
    sig   = inspect.signature(fn)
    doc   = inspect.getdoc(fn) or ""

    fn_desc, param_docs = _parse_google_docstring(doc)

    properties: dict[str, dict] = {}
    required:   list[str]       = []

    for pname, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        py_type   = hints.get(pname, str)
        json_type = _PY_TO_JSON.get(py_type, "string")

        prop: dict[str, Any] = {"type": json_type}
        if pname in param_docs:
            prop["description"] = param_docs[pname]

        properties[pname] = prop

        if param.default is inspect.Parameter.empty:
            required.append(pname)

    return {
        "description":          fn_desc or (doc.splitlines()[0] if doc else ""),
        "type":                 "object",
        "properties":           properties,
        "required":             required,
        "additionalProperties": False,
    }


def tool(fn: Callable) -> FunctionTool:
    """Decorator: convert a plain function into a FunctionTool."""
    schema = _build_schema(fn)
    desc   = schema.pop("description", "")
    return FunctionTool(name=fn.__name__, description=desc, parameters=schema, fn=fn)
```

### `tools/registry.py` — Complete

```python
# tools/registry.py
from __future__ import annotations

import json
import traceback
from typing import Any

from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> "ToolRegistry":
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        return self  # allow chaining

    def to_openai_schema(self, strict: bool = False) -> list[dict]:
        result = []
        for t in self._tools.values():
            entry: dict[str, Any] = {
                "type":        "function",
                "name":        t.name,
                "description": t.description,
                "parameters":  t.parameters,
            }
            if strict:
                entry["strict"] = True
            result.append(entry)
        return result

    def dispatch(self, name: str, arguments_str: str) -> str:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'."
        tool = self._tools[name]
        try:
            args = json.loads(arguments_str)
        except json.JSONDecodeError as exc:
            return f"Error: invalid JSON arguments: {exc}"
        if not isinstance(args, dict):
            return "Error: arguments must be a JSON object."
        err = _validate(tool, args)
        if err:
            return f"Error: {err}"
        try:
            return tool.run(**args)
        except Exception as exc:
            return f"Error ({type(exc).__name__}): {exc}"


def _validate(tool: Tool, args: dict) -> str | None:
    schema     = tool.parameters
    required   = schema.get("required", [])
    properties = schema.get("properties", {})
    for key in required:
        if key not in args:
            return f"missing required argument '{key}'"
    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in properties:
                return f"unexpected argument '{key}'"
    _type_map = {
        "string": str, "integer": int, "number": (int, float),
        "boolean": bool, "array": list, "object": dict,
    }
    for key, value in args.items():
        if key not in properties:
            continue
        jtype = properties[key].get("type")
        if jtype in _type_map:
            expected = _type_map[jtype]
            if jtype == "integer" and isinstance(value, bool):
                return f"'{key}' must be integer, got boolean"
            if not isinstance(value, expected):
                return f"'{key}' expected {jtype}, got {type(value).__name__}"
    return None
```

### `tools/parallel.py` — Complete

```python
# tools/parallel.py
from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry


def dispatch_parallel(
    registry: "ToolRegistry",
    function_calls: list,
    max_workers: int = 8,
) -> list[dict]:
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_call_id = {
            executor.submit(registry.dispatch, fc.name, fc.arguments): fc.call_id
            for fc in function_calls
        }
        for future in concurrent.futures.as_completed(future_to_call_id):
            call_id = future_to_call_id[future]
            try:
                output = future.result()
            except Exception as exc:
                output = f"Error (unexpected): {exc}"
            results.append({
                "type":    "function_call_output",
                "call_id": call_id,
                "output":  output,
            })
    return results


def dispatch_sequential(registry: "ToolRegistry", function_calls: list) -> list[dict]:
    return [
        {
            "type":    "function_call_output",
            "call_id": fc.call_id,
            "output":  registry.dispatch(fc.name, fc.arguments),
        }
        for fc in function_calls
    ]
```

### `tools/__init__.py`

```python
# tools/__init__.py
from .base import Tool, FunctionTool, tool
from .registry import ToolRegistry
from .parallel import dispatch_parallel, dispatch_sequential

__all__ = [
    "Tool",
    "FunctionTool",
    "tool",
    "ToolRegistry",
    "dispatch_parallel",
    "dispatch_sequential",
]
```

### `agent.py` — Complete with Example Tools

```python
# agent.py
from __future__ import annotations

import datetime
import json
import re

from openai import OpenAI

from tools import tool, ToolRegistry
from tools.parallel import dispatch_parallel, dispatch_sequential

client = OpenAI()
MODEL  = "gpt-5"


# ------------------------------------------------------------------ #
# Tool definitions                                                     #
# ------------------------------------------------------------------ #

@tool
def add(a: float, b: float) -> str:
    """Add two numbers and return the result.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)


@tool
def get_time(timezone: str) -> str:
    """Return the current UTC time. The timezone argument is noted but UTC is always returned.

    Args:
        timezone: The desired timezone label (informational only).
    """
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return json.dumps({"timezone": timezone, "time": now})


@tool
def word_count(text: str) -> str:
    """Count the number of words in a piece of text.

    Args:
        text: The text to count words in.
    """
    count = len(re.findall(r"\S+", text))
    return json.dumps({"word_count": count})


# ------------------------------------------------------------------ #
# Registry setup                                                       #
# ------------------------------------------------------------------ #

def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(add)
    registry.register(get_time)
    registry.register(word_count)
    return registry


# ------------------------------------------------------------------ #
# Agent loop                                                           #
# ------------------------------------------------------------------ #

def run_agent(
    instructions: str,
    user_message: str,
    registry:     ToolRegistry,
    parallel:     bool = True,
    max_turns:    int  = 10,
) -> str:
    input_items: list[dict] = [{"role": "user", "content": user_message}]
    tools_schema = registry.to_openai_schema(strict=False)

    for turn in range(max_turns):
        resp = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=input_items,
            tools=tools_schema,
        )

        input_items += resp.output

        function_calls = [item for item in resp.output if item.type == "function_call"]

        if not function_calls:
            for item in resp.output:
                if item.type == "message":
                    for part in item.content:
                        if part.type == "output_text":
                            return part.text
            return ""

        if parallel:
            tool_outputs = dispatch_parallel(registry, function_calls)
        else:
            tool_outputs = dispatch_sequential(registry, function_calls)

        input_items.extend(tool_outputs)

        print(
            f"[turn {turn + 1}] "
            f"tools called: {[fc.name for fc in function_calls]} | "
            f"tokens: {resp.usage.input_tokens}in "
            f"{resp.usage.output_tokens}out "
            f"{resp.usage.total_tokens}total"
        )

    raise RuntimeError(f"Agent did not finish within {max_turns} turns.")


# ------------------------------------------------------------------ #
# Entry point                                                          #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    registry = build_registry()

    # Prompt designed to elicit two simultaneous tool calls
    answer = run_agent(
        instructions="You are a helpful assistant. Use tools when needed.",
        user_message=(
            "What is 1234 + 5678? "
            "Also, how many words are in this sentence: "
            "'The quick brown fox jumps over the lazy dog'? "
            "Answer both questions."
        ),
        registry=registry,
        parallel=True,
    )

    print("\nFinal answer:")
    print(answer)
```

### Example Transcript

```text
[turn 1] tools called: ['add', 'word_count'] | tokens: 312in 45out 357total

Final answer:
1234 + 5678 = 6912.

The sentence "The quick brown fox jumps over the lazy dog" contains 9 words.
```

In turn 1 the model issued two `function_call` items simultaneously. Both ran in parallel via `ThreadPoolExecutor`. The results were appended with their respective `call_id` values. The model received both outputs in turn 2 and produced the final text response with no further tool calls.

---

## 9. Pitfalls

| Pitfall | What happens | How to avoid |
|---------|--------------|--------------|
| **Missing `call_id` on a tool output** | The API returns a validation error on the next `responses.create` call. The error message says a function call has no matching output. | Always use the `call_id` from `fc.call_id` verbatim. Never construct call IDs yourself. Never skip a function call without returning an output for it — even if the tool fails, return an error string. |
| **Schema too loose (no `required`, no `additionalProperties: false`)** | The model may omit required arguments or send extra keys. Your tool gets `TypeError` or silently uses wrong data. | Use `@tool` (which sets `additionalProperties: False` and `required` correctly) or use `strict=True` so the API enforces the schema. |
| **Blocking the loop on slow sequential tools** | A turn with three 2-second tools takes 6 seconds instead of 2. The user waits; the loop holds the thread. | Default to `dispatch_parallel`. Only use sequential when tools have conflicting side effects. |
| **Mutable default arguments in decorated functions** | `def fn(items: list = [])` shares the same list across all calls. Subsequent calls accumulate state. | Use `None` as the default and construct inside the function: `if items is None: items = []`. The decorator does not fix this — it is a Python language trap. |
| **Registering the same tool twice** | `ToolRegistry.register` raises `ValueError`. In multi-module projects, import order can trigger this unexpectedly. | Import tools from one place; instantiate the registry once at startup and pass it around. Do not call `register` from module-level code that might be imported multiple times. |
| **Returning non-string from `run`** | `FunctionTool.run` JSON-encodes non-strings, but a handwritten `Tool` subclass that returns `None` or an integer will cause a type error when the API receives it. | Always return `str` from `run`. `FunctionTool` coerces automatically; subclasses must do it manually. |
| **Truncated or enormous tool output** | Very large outputs (e.g., a full file) consume most of the context window, crowding out conversation history. | Truncate, summarize, or paginate tool output. A good rule: keep any single tool output under 2000 characters. |
