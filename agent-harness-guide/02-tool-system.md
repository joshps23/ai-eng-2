# Phase 2 — A Real Tool System

## Where We Left Off

Phase 1 gave us a working agent loop in roughly 80 lines. The dispatch logic was a hand-written router with one branch per tool:

```python
def dispatch(name: str, arguments: str) -> str:
    args = json.loads(arguments)
    if name == "get_current_time":
        return get_current_time(**args)
    return f"ERROR: unknown tool '{name}'"   # returns a string, never raises
```

That works for a demo. It does not scale. Every new tool requires editing the dispatch function, the hand-written schema, and the tool list passed to the API. By the end of this phase you will have replaced that approach entirely — but we will do it in small, runnable steps, starting from ordinary functions and dicts.

**What we will build, step by step:**

- **Step 0** — two plain functions registered in a dict, hand-written schemas, dispatched with a lookup. Runnable right now.
- **Step 1** — the `@tool` decorator that generates schemas automatically from type hints. "The grown-up convenience."
- **Step 2** — the `ToolRegistry` class: the same dict-plus-functions idea, wrapped for larger projects.
- **Step 3 (optional)** — parallel tool execution with threads.

You can stop at any step; each one is a complete, working tool system.

---

## Step 0 — Two Functions, a Dict, and a Lookup

The whole idea in one sentence: a "tool" is just *a function plus a dict that describes it*, and a "registry" is just *a dict that maps a tool's name to those two things*.

### 0a. Write the functions and their schema dicts

```python
import json

# ── Tool 1 ────────────────────────────────────────────────────────────
def add(a, b):
    """Add two numbers."""
    return str(a + b)

add_schema = {
    "type": "function",
    "name": "add",
    "description": "Add two numbers and return the result.",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First number."},
            "b": {"type": "number", "description": "Second number."},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}

# ── Tool 2 ────────────────────────────────────────────────────────────
import re

def word_count(text):
    """Count the words in a string."""
    return str(len(re.findall(r"\S+", text)))

word_count_schema = {
    "type": "function",
    "name": "word_count",
    "description": "Count the number of words in a string.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to count."},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}
```

### 0b. Register them in a plain dict

```python
# The registry maps a tool name -> {"fn": the function, "schema": the dict}.
TOOLS = {}

def register(name, fn, schema):
    """Add one tool to the registry."""
    TOOLS[name] = {"fn": fn, "schema": schema}

register("add", add, add_schema)
register("word_count", word_count, word_count_schema)
```

### 0c. Build the list the API needs

```python
def tools_for_api():
    """Return the list passed to client.responses.create(tools=...)."""
    result = []
    for entry in TOOLS.values():
        result.append(entry["schema"])
    return result
```

### 0d. Dispatch: look up a tool and call it

```python
def dispatch(name, arguments_str):
    """Look up a tool, run it, and ALWAYS return a string (never crash)."""
    if name not in TOOLS:
        return f"Error: unknown tool '{name}'."
    try:
        args = json.loads(arguments_str)   # JSON string -> dict
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON arguments: {exc}"
    try:
        fn = TOOLS[name]["fn"]
        result = fn(**args)                # call the function with the dict's keys
        if not isinstance(result, str):
            result = json.dumps(result)
        return result
    except Exception as exc:
        return f"Error ({type(exc).__name__}): {exc}"
```

### 0e. Handle multiple tool calls — a plain `for` loop

The Responses API can return several `function_call` items in one response. A `for` loop handles them all:

```python
def run_tool_calls(function_calls):
    """function_calls is the list of function_call items from resp.output."""
    outputs = []
    for fc in function_calls:
        output = dispatch(fc.name, fc.arguments)
        outputs.append({
            "type": "function_call_output",
            "call_id": fc.call_id,   # echo this back exactly
            "output": output,
        })
    return outputs
```

### 0f. The full agent loop using only functions and dicts

Put it all together in a single file `agent_v0.py`:

```python
# agent_v0.py  — complete, no classes, no decorators, no threads
import json
import re
from openai import OpenAI

client = OpenAI()
MODEL  = "gpt-4o"   # or whichever model you have access to


# ── Tool implementations ───────────────────────────────────────────────

def add(a, b):
    return str(a + b)

def word_count(text):
    return str(len(re.findall(r"\S+", text)))


# ── Schema dicts (what the model sees) ────────────────────────────────

add_schema = {
    "type": "function",
    "name": "add",
    "description": "Add two numbers and return the result.",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First number."},
            "b": {"type": "number", "description": "Second number."},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}

word_count_schema = {
    "type": "function",
    "name": "word_count",
    "description": "Count the number of words in a string.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to count."},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}


# ── Registry (name -> {"fn": ..., "schema": ...}) ─────────────────────

TOOLS = {}

def register(name, fn, schema):
    TOOLS[name] = {"fn": fn, "schema": schema}

register("add",        add,        add_schema)
register("word_count", word_count, word_count_schema)


# ── Helpers ───────────────────────────────────────────────────────────

def tools_for_api():
    return [entry["schema"] for entry in TOOLS.values()]

def dispatch(name, arguments_str):
    if name not in TOOLS:
        return f"Error: unknown tool '{name}'."
    try:
        args = json.loads(arguments_str)
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON arguments: {exc}"
    try:
        result = TOOLS[name]["fn"](**args)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as exc:
        return f"Error ({type(exc).__name__}): {exc}"

def run_tool_calls(function_calls):
    outputs = []
    for fc in function_calls:
        output = dispatch(fc.name, fc.arguments)
        outputs.append({
            "type": "function_call_output",
            "call_id": fc.call_id,
            "output": output,
        })
    return outputs


# ── Agent loop ─────────────────────────────────────────────────────────

def run_agent(user_message, max_turns=10):
    input_items = [{"role": "user", "content": user_message}]

    for turn in range(max_turns):
        resp = client.responses.create(
            model=MODEL,
            input=input_items,
            tools=tools_for_api(),
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

        tool_outputs = run_tool_calls(function_calls)
        input_items.extend(tool_outputs)
        print(f"[turn {turn + 1}] tools called: {[fc.name for fc in function_calls]}")

    raise RuntimeError(f"Agent did not finish within {max_turns} turns.")


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    answer = run_agent(
        "What is 1234 + 5678? "
        "Also, how many words are in: 'The quick brown fox jumps over the lazy dog'?"
    )
    print("\nFinal answer:")
    print(answer)
```

### ▶ Run it now

```bash
python agent_v0.py
```

You should see one or two turn lines followed by:

```text
[turn 1] tools called: ['add', 'word_count']

Final answer:
1234 + 5678 = 6912. The sentence has 9 words.
```

That is the complete tool system — no classes, no decorators, no threads. Everything from here is a convenience upgrade.

> 🟢 **Checkpoint.** If the script ran and gave sensible answers, you have a fully working
> multi-tool agent. The remaining steps show how to remove repetitive boilerplate, not how
> to make the agent *work* — it already works.

---

## Step 1 — Auto-Generate Schemas with `@tool`

**Why now?** Writing schema dicts by hand is tedious and error-prone. If you rename a parameter in the function but forget to update the dict, the model gets a stale description. The `@tool` decorator reads the function's type hints and docstring and builds the dict for you — it's just automating the dict you already know how to write.

> 🟢 **Decorator + "introspection" — what's really happening.** A **decorator** is the
> `@tool` line written directly above a function. It means "after defining this
> function, pass it through `tool()` and keep the result under the same name." The
> `tool()` function here uses **introspection** (`inspect`, `get_type_hints`) — code
> that *reads other code* — to look at the function's parameter names, type hints, and
> docstring and **build the schema dict for you**. It's convenient, but it's just
> automating the dict you can write by hand. **If this feels like too much, don't use
> it:** the Step 0 code above writes the same schema dict directly, which is fewer
> moving parts and shows you exactly what the model receives. You can read this section
> for interest and skip straight to using hand-written schema dicts.

### 1a. Write a function with type hints and a docstring

```python
@tool
def add(a: float, b: float) -> str:
    """Add two numbers and return the result.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)
```

No schema dict. The decorator inspects the hints (`float`) and the docstring (`Args:` block) and produces the same dict you would write by hand.

### 1b. Verify what the decorator produced

```python
import json
print(json.dumps(add.parameters, indent=2))
```

Output:

```json
{
  "type": "object",
  "properties": {
    "a": {"type": "number", "description": "First number."},
    "b": {"type": "number", "description": "Second number."}
  },
  "required": ["a", "b"],
  "additionalProperties": false
}
```

Identical to the hand-written dict from Step 0. `add.name` is `"add"`, `add.description` is `"Add two numbers and return the result."`. Nothing was written by hand.

### 1c. The decorated object still has `.parameters`, `.name`, `.description`

After `@tool`, `add` is no longer a plain function — it is a `FunctionTool` object with those three attributes, plus a `.run(**kwargs)` method. You can still call `add.run(a=2, b=3)` and get `"5"`.

### Seeing the Generated Schema for a More Complex Function

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

### 1d. Using `@tool` objects with the Step 0 registry

A `FunctionTool` produced by `@tool` has `.name`, `.parameters`, and `.run()`. You can slot it into the Step 0 TOOLS dict:

```python
TOOLS["add"]        = {"fn": add.run,        "schema": {"type": "function", "name": add.name,        "description": add.description,        "parameters": add.parameters}}
TOOLS["word_count"] = {"fn": word_count.run, "schema": {"type": "function", "name": word_count.name, "description": word_count.description, "parameters": word_count.parameters}}
```

That works, but it is getting wordy. The next step introduces a helper object that handles this wrapping for you.

### ▶ Run it now

Replace the two function definitions and schema dicts in `agent_v0.py` with `@tool`-decorated versions. Everything else (the `TOOLS` dict, `register`, `dispatch`, the loop) stays the same. Run the script and confirm the output is identical.

---

## Step 2 — The `Tool` Abstraction and `ToolRegistry` Class

**Why now?** The `TOOLS` dict plus standalone functions is fine for two or three tools. As the project grows, you want: a type (`Tool`) so editors and type-checkers understand what goes in the dict; a `ToolRegistry` class that bundles registration, schema export, and dispatch in one place; and duplicate-registration protection. These are the same ideas as Step 0, organized for real use.

> 🟢 **What a `class` is, in one box.** A `class` bundles some data with the functions
> that work on it. A function defined inside a class is called a **method**, and its
> first parameter is always `self` — a handle to "this particular object's data." So
> `class Tool: ... def run(self, **kwargs): ...` defines a blueprint, and writing
> `AddTool().run(a=2, b=3)` *makes* an `AddTool` object and calls its `run`. "Subclass
> and override `run`" means: make a new blueprint based on `Tool` and supply your own
> `run`. The Step 0 beginner track replaces this whole class with *a function plus a
> `schema` dict* — same information, no new syntax.

### The mapping: class version ↔ Step 0 plain-function version

| Class/decorator version | Step 0 plain-function version |
|-------------------------|-------------------------------|
| `class Tool` / `class FunctionTool` | a function + its `schema` dict |
| `@tool` decorator (auto-builds schema) | you write the `schema` dict by hand |
| `class ToolRegistry` + `.register()` | the `TOOLS` dict + `register()` function |
| `registry.to_openai_schema()` | `tools_for_api()` |
| `registry.dispatch()` | `dispatch()` |
| `dispatch_parallel()` (threads) | `run_tool_calls()` (a `for` loop) |

### 2a. The `Tool` base class

Start with a clear interface. Every tool is an object with a name, a description, a JSON Schema for its parameters, and a `run` method that accepts keyword arguments and returns a string.

**The explicit approach: subclass `Tool` and override `run`.**

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

This works but it is verbose. For every tool you must write the JSON Schema by hand, which means the schema and the Python signature can drift again. That is why the `@tool` decorator (Step 1) is more practical for most tools.

### 2b. `FunctionTool` — wrapping a decorated function

The `@tool` decorator produces a `FunctionTool`, which is a `Tool` subclass that delegates `run` to the original function:

```python
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

### 2c. The `@tool` decorator's internals

```python
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
```

### 2d. The `ToolRegistry` class

The registry is the single object that knows about all tools. It owns three responsibilities: registering tools, exporting the API schema, and dispatching calls. It is the same idea as the Step 0 `TOOLS` dict plus `register()`, `tools_for_api()`, and `dispatch()` — bundled into one object.

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

    def to_openai_schema(self, strict: bool = False) -> list[dict]:
        """
        Return the tools list suitable for the `tools=` parameter of
        client.responses.create().

        Each entry is the FLAT format required by the Responses API:
            {
                "type": "function",
                "name": ...,
                "description": ...,
                "parameters": <JSON Schema>,
            }

        We default to strict=False. Strict mode (strict=True) makes the API
        enforce that the model's arguments validate against the schema, but it
        requires every property to be listed in `required` AND
        `additionalProperties: false`. That is incompatible with ordinary
        optional parameters (to make a param optional under strict mode you'd
        promote it to required with a nullable type:
        `"type": ["<type>", "null"]`). Since @tool leaves optional parameters
        out of `required`, we keep strict off so they work without
        modification.
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

### ▶ Run it now — using the registry

Create `agent_v2.py` with the registry approach:

```python
# agent_v2.py — same tools, now using ToolRegistry
import json
import re
from openai import OpenAI
from tools import tool, ToolRegistry

client = OpenAI()
MODEL  = "gpt-4o"

@tool
def add(a: float, b: float) -> str:
    """Add two numbers and return the result.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)

@tool
def word_count(text: str) -> str:
    """Count the number of words in a string.

    Args:
        text: The text to count words in.
    """
    return str(len(re.findall(r"\S+", text)))

registry = ToolRegistry()
registry.register(add)
registry.register(word_count)

def run_agent(user_message, max_turns=10):
    input_items = [{"role": "user", "content": user_message}]
    tools_schema = registry.to_openai_schema()

    for turn in range(max_turns):
        resp = client.responses.create(
            model=MODEL,
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
        tool_outputs = []
        for fc in function_calls:
            output = registry.dispatch(fc.name, fc.arguments)
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": output,
            })
        input_items.extend(tool_outputs)
        print(f"[turn {turn + 1}] tools called: {[fc.name for fc in function_calls]}")

    raise RuntimeError(f"Agent did not finish within {max_turns} turns.")

if __name__ == "__main__":
    answer = run_agent(
        "What is 1234 + 5678? "
        "Also, how many words are in: 'The quick brown fox jumps over the lazy dog'?"
    )
    print("\nFinal answer:")
    print(answer)
```

```bash
python agent_v2.py
```

You should see the same output as Step 0. The tool *behavior* is identical — you have only reorganized who owns the registry.

---

## Step 3 (Optional) — Parallel Tool Execution

**Why now?** The `for` loop in Steps 0 and 2 runs tool calls one at a time. If the model asks for weather in Paris and weather in Tokyo simultaneously, you wait for Paris to finish before starting Tokyo. Threads fix this. This is a speed optimization only — it does not change the results.

> 🟢 **Parallel tools are an optimization, not a requirement.** The code below uses
> **threads** (`ThreadPoolExecutor`) to run several tool calls at the same time so the
> turn finishes faster. It does **not** change the *results* — a plain `for` loop over
> the tool calls (the `run_tool_calls` / `dispatch_sequential` version) produces
> identical outputs, just one after another. If threads are unfamiliar, use the
> sequential loop everywhere; come back to this section only when speed matters. One
> bit of new syntax below — `{... for fc in function_calls}` — is a **dict
> comprehension**, the dict cousin of the list comprehension from Phase 1; it builds a
> dict in one line instead of with a loop.

### Why the Phase 1 serial loop is slow here

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

## 5. Structured Results and Errors

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

## 6. The Updated Agent Loop

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

## 7. Full Runnable Example

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
    # utcnow() is deprecated in Python 3.12+; use a timezone-aware "now".
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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

## 8. Why We Built It in Steps: The Problems with Ad-Hoc Dispatch

You now have a full tool system. This section names the five failure modes of the original Phase 1 one-branch-per-tool approach — useful when you need to explain *why* the registry matters:

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

---

## Key takeaways

- A **registry** (a name → tool lookup) replaces ad-hoc `if/elif` dispatch, so adding a
  tool no longer means editing the loop.
- `@tool` **auto-generates the JSON schema** from the function's type hints and
  docstring — or hand-write the schema yourself (the Step 0 approach from this
  phase). Either way the model gets the same dict.
- Tool results are always **strings**: return an **error string** instead of raising, and
  return exactly **one output per `call_id`** — even for a failed call.
- Run **independent** tool calls in **parallel** (threads) for speed; fall back to
  **sequential** when tools have conflicting side effects.

## Check yourself

1. What can you change *without touching the agent loop* once you have a registry?
2. Where does `@tool` get the schema's parameter names and types from?
3. When should you **not** run tool calls in parallel?
4. A tool hits an error. What should it return, and why does that matter for the loop?

<details><summary>Answers</summary>

1. Add, remove, or swap tools — the loop just looks them up by name in the registry.
2. From the function's **type hints** (for the JSON types) and its **docstring** (for the
   descriptions).
3. When the calls have **conflicting side effects** (e.g. two edits to the same file) —
   run those **sequentially** so order is deterministic.
4. An **error string**. The model can then *see* what went wrong and adapt, and every
   `call_id` still gets its required matching output so the next `create()` is valid.
</details>
