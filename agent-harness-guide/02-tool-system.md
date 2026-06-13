[← Phase 1: A Bare Harness in ~80 Lines](./01-bare-harness.md) · [Guide index](./README.md) · [Phase 3: Conversation State & Streaming →](./03-conversation-and-streaming.md)

# Phase 2 — A Real Tool System

## Where We Left Off

Phase 1 gave us a working agent loop in roughly 80 lines. The dispatch logic was a hand-written router with one branch per tool:

```python
def dispatch(name: str, arguments: str) -> str:
    """Route a tool call. Always returns a string; never raises."""
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as exc:
        return f"ERROR: could not parse arguments JSON — {exc}"
    try:
        if name == "get_current_time":
            return get_current_time(**args)
        return f"ERROR: unknown tool '{name}'"
    except Exception as exc:               # errors become strings, never crashes
        return f"ERROR: {type(exc).__name__}: {exc}"
```

That works for a demo. It does not scale. Every new tool requires editing the dispatch function, the hand-written schema, and the tool list passed to the API. By the end of this phase you will have replaced that approach entirely — but we will do it as a **ladder of complete, runnable versions** of the *same* harness, each one a reorganization of the last, starting even lower than Phase 1 did: a script with no functions at all.

**The version ladder for this phase:**

- **Version 1 — line by line.** The harness with two tools dispatched by an inline `if/elif` chain. No `def`, no classes — just statements top to bottom. Runnable right now, and deliberately painful: you will *feel* why every later version exists.
- **Version 2 — functions and a dict registry.** The same harness where each tool is a plain function and dispatch is a dict lookup. No classes, no decorators.
- **Version 3 — classes.** The same harness with `Tool` and `ToolRegistry` classes — the same dict-plus-functions idea, organized for larger projects.
- **Version 4 — the `@tool` decorator.** The same harness, with schemas generated automatically from type hints and docstrings. "The grown-up convenience."
- **Going further (optional)** — parallel tool execution with threads.

You can stop at any version; each one is a complete, working tool system that produces the same answers. Each later version changes *how the code is organized*, never *what the agent does*.

### 🟢 Beginner track

> 🟢 **Beginner track.** If classes and decorators are still new to you, Versions 1 and 2
> are a perfectly legitimate stopping point — hand-written schema dicts plus a dict
> registry is a complete tool system, and it is exactly what the later versions automate.
> Read Versions 3 and 4 for the *ideas* and come back to the syntax when you are ready.

**Contents:**

- [Version 1 — Line by Line: Inline `if/elif` Dispatch](#version-1--line-by-line-inline-ifelif-dispatch)
- [Version 2 — Functions and a Dict Registry](#version-2--functions-and-a-dict-registry)
- [Version 3 — Classes: `Tool` and `ToolRegistry`](#version-3--classes-tool-and-toolregistry)
- [Version 4 — The `@tool` Decorator](#version-4--the-tool-decorator)
- [Going Further (Optional) — Parallel Tool Execution](#going-further-optional--parallel-tool-execution)
- [Argument Validation (optional)](#argument-validation-strict-mode-vs-manual-checks-optional) · [Structured Results and Errors (optional)](#structured-results-and-errors-optional)
- [The Updated Agent Loop — the Production Shape](#the-updated-agent-loop--the-production-shape)
- [Full Runnable Example — the `tools/` Package](#full-runnable-example--the-tools-package)
- [Pitfalls](#pitfalls)

> **Prefer running this phase as a notebook?** [`notebooks/02-tool-system.ipynb`](./notebooks/02-tool-system.ipynb) executes this phase's checkpoints offline — see [notebooks/README.md](./notebooks/README.md).

---

## Version 1 — Line by Line: Inline `if/elif` Dispatch

**Why start here?** Before we build any machinery, we should see the harness in its rawest possible form: every tool's schema written out, every tool's *logic* pasted directly into the dispatch branch, no functions of our own at all. This version works — and the moment you try to add a third tool, you will see exactly which pain each later version removes.

### 1.1 The schema dicts and the tools list

A "tool", from the API's point of view, is just a dict describing a function the model may call. We write two of them by hand and collect them in a list. Note the **flat** format the Responses API requires: `type`, `name`, `description`, `parameters` all at the top level — no nested `"function"` wrapper.

```python
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

TOOLS = [add_schema, word_count_schema]
```

### ▶ Check it now (no API key needed)

Paste just this much into a file, add `import json` and `print(json.dumps(TOOLS, indent=2))` at the bottom, and run it. What prints is *exactly* what the model will see — there is no magic between your dict and the API.

### 1.2 The loop, with the tool logic inlined

Now the agent loop from Phase 1, but with the tool *implementations* written directly inside the dispatch branches — `str(args["a"] + args["b"])` lives right there in the `if`. No `def` anywhere.

### The full file: `agent_v1.py`

```python
# agent_v1.py — complete. No def, no classes: statements top to bottom.
import json
import re
from openai import OpenAI

client = OpenAI()
MODEL = "gpt-4o"

# ── Tool schemas (what the model sees) ─────────────────────────────────

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

TOOLS = [add_schema, word_count_schema]

# ── The agent loop, everything inline ──────────────────────────────────

input_items = [{
    "role": "user",
    "content": (
        "What is 1234 + 5678? "
        "Also, how many words are in: 'The quick brown fox jumps over the lazy dog'?"
    ),
}]

final_answer = None
MAX_TURNS = 10

for turn in range(MAX_TURNS):
    resp = client.responses.create(
        model=MODEL,
        input=input_items,
        tools=TOOLS,
    )

    input_items += resp.output

    function_calls = [item for item in resp.output if item.type == "function_call"]

    if not function_calls:
        # No tool calls — the model is done. Pull out the text and stop.
        for item in resp.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "output_text":
                        final_answer = part.text
        break

    for fc in function_calls:
        args = json.loads(fc.arguments)

        # ---- inline dispatch: one branch per tool, logic pasted in ----
        if fc.name == "add":
            output = str(args["a"] + args["b"])
        elif fc.name == "word_count":
            output = str(len(re.findall(r"\S+", args["text"])))
        else:
            output = f"Error: unknown tool '{fc.name}'."

        input_items.append({
            "type": "function_call_output",
            "call_id": fc.call_id,   # echo this back exactly
            "output": output,
        })

    print(f"[turn {turn + 1}] tools called: {[fc.name for fc in function_calls]}")

print("\nFinal answer:")
print(final_answer)
```

### ▶ Run it now

```bash
python agent_v1.py
```

You should see something like:

```text
[turn 1] tools called: ['add', 'word_count']

Final answer:
1234 + 5678 = 6912. The sentence has 9 words.
```

A complete multi-tool agent — no `def`, no classes, no decorators.

### The pain point: every new tool means edits in three places

Now imagine adding a third tool, `get_time`. You must:

1. **Write a new schema dict** (`get_time_schema = {...}`) — and get every key right.
2. **Add it to the `TOOLS` list** — forget this and the model never learns the tool exists.
3. **Add an `elif` branch** to the dispatch chain — forget this and the model calls a tool that silently falls into the `else` error branch.

Three places, in different parts of the file, that must stay in sync by hand. And there are quieter problems: if `args["a"]` is missing or the tool logic raises, the whole script crashes — the model never gets to see an error and recover. Every version that follows is an answer to this paragraph.

---

## Version 2 — Functions and a Dict Registry

### What changed from V1 to V2

- Each tool's logic moves out of the `elif` branch into a **named function** (`add`, `word_count`).
- The `if/elif` chain becomes a **dict lookup**: `TOOLS[name]` finds both the function and its schema in one place.
- The tools list for the API is now **generated from the registry** (`tools_for_api()`), so the schema list can no longer drift out of sync with dispatch.
- Dispatch gains **error handling**: unknown tools, bad JSON, and tool exceptions all become `"Error: ..."` strings instead of crashes.
- The loop itself is wrapped in `run_agent()`, so you can ask different questions without editing the file's middle.

Same harness, same two tools, same answers — reorganized.

The whole idea in one sentence: a "tool" is just *a function plus a dict that describes it*, and a "registry" is just *a dict that maps a tool's name to those two things*.

### 2.1 Write the functions and their schema dicts

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

### 2.2 Register them in a plain dict

```python
# The registry maps a tool name -> {"fn": the function, "schema": the dict}.
TOOLS = {}

def register(name, fn, schema):
    """Add one tool to the registry."""
    TOOLS[name] = {"fn": fn, "schema": schema}

register("add", add, add_schema)
register("word_count", word_count, word_count_schema)
```

### 2.3 Build the list the API needs

```python
def tools_for_api():
    """Return the list passed to client.responses.create(tools=...)."""
    result = []
    for entry in TOOLS.values():
        result.append(entry["schema"])
    return result
```

### 2.4 Dispatch: look up a tool and call it

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

Here is what `dispatch` does, drawn out — the registry is a name→function
lookup table, so adding a tool never touches the loop:

```text
   model wants:  add  {"a": 2, "b": 3}
                  │
                  ▼
        ┌───────────────────────┐
        │  TOOLS  (a plain dict) │   look the NAME up
        │  ─────────────────────  │
        │  "add"        → {fn, schema}  ◀── match
        │  "word_count" → {fn, schema}  │
        └───────────────────────┘
                  │  found fn + schema
                  ▼
        run  fn(**{"a": 2, "b": 3})  →  "5"
                  │
                  ▼
   result string  "5"  ──▶ back into the conversation
```

Adding a tool means adding one row to that table — the loop and `dispatch`
never change.

### ▶ Check it now (no API key needed)

With everything above in one file, no API key is needed to test dispatch itself. Add and run:

```python
print(dispatch("add", '{"a": 2, "b": 3}'))      # 5
print(dispatch("add", '{"a": 2}'))              # Error (TypeError): ...
print(dispatch("nope", '{}'))                   # Error: unknown tool 'nope'.
```

Notice the last two: the bad calls produce *readable error strings*, not crashes. In Version 1 they would have killed the script.

### 2.5 Handle multiple tool calls — a plain `for` loop

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

### 2.6 The full agent loop using only functions and dicts

Put it all together in a single file `agent_v2.py`:

```python
# agent_v2.py  — complete, no classes, no decorators, no threads
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
python agent_v2.py
```

You should see one or two turn lines followed by:

```text
[turn 1] tools called: ['add', 'word_count']

Final answer:
1234 + 5678 = 6912. The sentence has 9 words.
```

The same output as Version 1 — that is the point. That is the complete tool system — no classes, no decorators, no threads. Everything from here is a convenience upgrade. Adding a tool now means: write a function, write its schema, call `register(...)` once. The dispatch code never changes again.

> **Checkpoint.** If the script ran and gave sensible answers, you have a fully working
> multi-tool agent. The remaining versions show how to remove repetitive boilerplate, not how
> to make the agent *work* — it already works.

---

## Version 3 — Classes: `Tool` and `ToolRegistry`

### What changed from V2 to V3

- Each *function + schema dict* pair becomes a single **`Tool` object** — the data and the behavior now live in one place.
- The module-level `TOOLS` dict and its three loose helpers (`register`, `tools_for_api`, `dispatch`) become one **`ToolRegistry` object** with methods `register()`, `to_openai_schema()`, and `dispatch()`.
- Duplicate registration now **raises a clear `ValueError`** instead of silently overwriting a tool.
- `dispatch()` gains lightweight **argument validation** before the tool runs.
- Behavior is identical: same prompts, same tool calls, same answers.

**Why now?** The `TOOLS` dict plus standalone functions is fine for two or three tools. As the project grows, you want: a type (`Tool`) so editors and type-checkers understand what goes in the dict; a `ToolRegistry` class that bundles registration, schema export, and dispatch in one place; and duplicate-registration protection. These are the same ideas as Version 2, organized for real use.

> 🟢 **What a `class` is, in one box.** A `class` bundles some data with the functions
> that work on it. A function defined inside a class is called a **method**, and its
> first parameter is always `self` — a handle to "this particular object's data." So
> `class Tool: ... def run(self, **kwargs): ...` defines a blueprint, and writing
> `AddTool().run(a=2, b=3)` *makes* an `AddTool` object and calls its `run`. "Subclass
> and override `run`" means: make a new blueprint based on `Tool` and supply your own
> `run`. The Version 2 beginner track replaces this whole class with *a function plus a
> `schema` dict* — same information, no new syntax.

### The mapping: class/decorator version ↔ Version 2 plain-function version

| Class/decorator version (V3/V4) | Version 2 plain-function version |
|-------------------------|-------------------------------|
| `class Tool` / `class FunctionTool` | a function + its `schema` dict |
| `@tool` decorator (auto-builds schema) | you write the `schema` dict by hand |
| `class ToolRegistry` + `.register()` | the `TOOLS` dict + `register()` function |
| `registry.to_openai_schema()` | `tools_for_api()` |
| `registry.dispatch()` | `dispatch()` |
| `dispatch_parallel()` (threads) | `run_tool_calls()` (a `for` loop) |

### 3.1 The `Tool` base class

Start with a clear interface. Every tool is an object with a name, a description, a JSON Schema for its parameters, and a `run` method that accepts keyword arguments and returns a string.

**The explicit approach: subclass `Tool` and override `run`.**

```python
# tools/base.py
from __future__ import annotations

import inspect
import json
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

### ▶ Check it now (no API key needed)

In a Python REPL with the class pasted in, run `AddTool().run(a=2, b=3)` — you should get `"5"`. The object also carries its own schema: `AddTool().parameters` is the dict you used to keep in a separate variable.

This works but it is verbose. For every tool you must write the JSON Schema by hand, which means the schema and the Python signature can drift again. That is why the `@tool` decorator (Version 4) is more practical for most tools.

### 3.2 The `ToolRegistry` class

The registry is the single object that knows about all tools. It owns three responsibilities: registering tools, exporting the API schema, and dispatching calls. It is the same idea as the Version 2 `TOOLS` dict plus `register()`, `tools_for_api()`, and `dispatch()` — bundled into one object.

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

        # 3. Validate (lightweight — see the "Argument Validation" section below)
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
    See the "Argument Validation" section below for a full explanation.
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

(That is the full production-shaped module, the form that ends up in the package. For the single-file version below we use a compact registry with the same three methods.)

### 3.3 The full file: `agent_v3.py`

The same harness as `agent_v2.py`, in one pasteable file. Compare them side by side: the loop is character-for-character the same except that it asks `registry` instead of calling loose functions.

```python
# agent_v3.py — same harness; tools are objects, the registry is a class
import json
import re
from openai import OpenAI

client = OpenAI()
MODEL  = "gpt-4o"


# ── Tools as classes ───────────────────────────────────────────────────

class Tool:
    """Base class for all tools. Subclass and override `run`."""
    name: str
    description: str
    parameters: dict

    def run(self, **kwargs) -> str:
        raise NotImplementedError


class AddTool(Tool):
    name = "add"
    description = "Add two numbers and return the result."
    parameters = {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First number."},
            "b": {"type": "number", "description": "Second number."},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    }

    def run(self, a, b) -> str:
        return str(a + b)


class WordCountTool(Tool):
    name = "word_count"
    description = "Count the number of words in a string."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to count."},
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def run(self, text) -> str:
        return str(len(re.findall(r"\S+", text)))


# ── The registry as a class (compact form) ─────────────────────────────

class ToolRegistry:
    def __init__(self):
        self._tools = {}                       # name -> Tool object

    def register(self, tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def to_openai_schema(self):
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    def dispatch(self, name, arguments_str):
        if name not in self._tools:
            return f"Error: unknown tool '{name}'."
        try:
            args = json.loads(arguments_str)
        except json.JSONDecodeError as exc:
            return f"Error: invalid JSON arguments: {exc}"
        try:
            result = self._tools[name].run(**args)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as exc:
            return f"Error ({type(exc).__name__}): {exc}"


registry = ToolRegistry()
registry.register(AddTool())
registry.register(WordCountTool())


# ── Agent loop — unchanged except for who it asks ──────────────────────

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
        for fc in function_calls:
            input_items.append({
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": registry.dispatch(fc.name, fc.arguments),
            })
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

### ▶ Run it now

```bash
python agent_v3.py
```

You should see the same output as Versions 1 and 2. The tool *behavior* is identical — you have only reorganized who owns the registry. The same idea, organized.

---

## Version 4 — The `@tool` Decorator

### What changed from V3 to V4

- The hand-written schema dicts **disappear**: `@tool` builds each one automatically from the function's **type hints** and **docstring**.
- A new `Tool` subclass, **`FunctionTool`**, wraps a plain function — so a decorated function *is* an ordinary `Tool` object that the V3 registry already accepts, unchanged.
- `required` vs. optional parameters are inferred from **defaults**; per-parameter descriptions come from the docstring's `Args:` block.
- Nothing else changes: the registry, dispatch, and the agent loop are untouched.

**Why now?** Writing schema dicts by hand is tedious and error-prone. If you rename a parameter in the function but forget to update the dict, the model gets a stale description. The `@tool` decorator reads the function's type hints and docstring and builds the dict for you — it's just automating the dict you already know how to write.

### 4.1 Decorators in 60 seconds

A decorator is **just a function that takes a function**. There is no other magic. Watch:

```python
def shout(fn):                        # takes a function...
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs).upper()
    return wrapper                    # ...returns a replacement for it

@shout
def greet(name):
    return f"hello, {name}"

print(greet("ada"))   # HELLO, ADA
```

The line `@shout` means exactly `greet = shout(greet)`: define `greet`, pass it through `shout`, and keep whatever comes back under the same name. A decorator doesn't have to return a function, either — ours will return a `FunctionTool` *object* built from the function. Run the snippet above before continuing; once `@shout` makes sense, `@tool` is the same move with a fancier factory.

> 🟢 **Decorator + "introspection" — what's really happening.** A **decorator** is the
> `@tool` line written directly above a function. It means "after defining this
> function, pass it through `tool()` and keep the result under the same name." The
> `tool()` function here uses **introspection** (`inspect`, `get_type_hints`) — code
> that *reads other code* — to look at the function's parameter names, type hints, and
> docstring and **build the schema dict for you**. It's convenient, but it's just
> automating the dict you can write by hand. **If this feels like too much, don't use
> it:** the Version 1–3 code above writes the same schema dict directly, which is fewer
> moving parts and shows you exactly what the model receives. You can read this section
> for interest and skip straight to using hand-written schema dicts.

### 4.2 Write a function with type hints and a docstring

> **Read, don't run (yet).** The `tool` decorator used in §4.2–4.4 doesn't exist
> yet — we build it ourselves in §4.5–4.6 below. Pasting this block on its own gives
> `NameError: name 'tool' is not defined`. Read these three short sections as a
> preview of the *experience* we're about to build, then run them once `tool` is
> defined (or use the complete `tools/base.py` listing at the end of the phase).

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

### 4.3 Verify what the decorator produced

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

Identical to the hand-written dict from Versions 1–3. `add.name` is `"add"`, `add.description` is `"Add two numbers and return the result."`. Nothing was written by hand.

### 4.4 The decorated object still has `.parameters`, `.name`, `.description`

After `@tool`, `add` is no longer a plain function — it is a `FunctionTool` object with those three attributes, plus a `.run(**kwargs)` method. You can still call `add.run(a=2, b=3)` and get `"5"`.

### 4.5 `FunctionTool` — wrapping a decorated function

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

Because `FunctionTool` *is a* `Tool`, the Version 3 registry accepts it with no changes: `registry.register(add)` — done.

### 4.6 The `@tool` decorator's internals

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
            if stripped and not line.startswith((" ", "\t")):
                # Un-indented line = new top-level section — stop
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

### 4.7 Using `@tool` objects with the Version 2 dict registry

The decorator does not *require* the class-based registry. A `FunctionTool` produced by `@tool` has `.name`, `.parameters`, and `.run()`, so you can even slot it into the Version 2 `TOOLS` dict:

```python
TOOLS["add"]        = {"fn": add.run,        "schema": {"type": "function", "name": add.name,        "description": add.description,        "parameters": add.parameters}}
TOOLS["word_count"] = {"fn": word_count.run, "schema": {"type": "function", "name": word_count.name, "description": word_count.description, "parameters": word_count.parameters}}
```

That works, but it is getting wordy — which is exactly what the Version 3 `ToolRegistry` removes: it accepts `Tool` objects directly, so registration is just `registry.register(add)`.

### The full file: `agent_v4.py`

The whole ladder in one pasteable file: the V3 classes, the new decorator, and the unchanged loop. It is longer than `agent_v3.py` only because the decorator machinery lives inside it — once it moves into a `tools/` package (next section), the agent file shrinks dramatically.

```python
# agent_v4.py — same harness; @tool builds the schemas for us
import inspect
import json
import re
from typing import Any, Callable, get_type_hints

from openai import OpenAI

client = OpenAI()
MODEL  = "gpt-4o"


# ── Tool machinery: the V3 classes plus the decorator ──────────────────

class Tool:
    """Base class for all tools."""
    name: str
    description: str
    parameters: dict

    def run(self, **kwargs: Any) -> str:
        raise NotImplementedError


class FunctionTool(Tool):
    """A Tool wrapping a plain callable, produced by the @tool decorator."""

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


_PY_TO_JSON = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}


def _build_schema(fn: Callable) -> dict:
    """Derive a JSON Schema from a function's signature, hints, and docstring."""
    hints = get_type_hints(fn)
    sig   = inspect.signature(fn)
    doc   = inspect.getdoc(fn) or ""

    # Per-parameter descriptions from the Google-style "Args:" block
    param_docs: dict[str, str] = {}
    in_args = False
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped.lower() in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if stripped and not line.startswith((" ", "\t")):
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
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
        "description": fn_description,
    }


def tool(fn: Callable) -> FunctionTool:
    """Decorator: convert a plain function into a FunctionTool."""
    schema = _build_schema(fn)
    return FunctionTool(
        name=fn.__name__,
        description=schema.pop("description", fn.__doc__ or ""),
        parameters=schema,
        fn=fn,
    )


class ToolRegistry:
    def __init__(self):
        self._tools = {}                       # name -> Tool object

    def register(self, tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def to_openai_schema(self):
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    def dispatch(self, name, arguments_str):
        if name not in self._tools:
            return f"Error: unknown tool '{name}'."
        try:
            args = json.loads(arguments_str)
        except json.JSONDecodeError as exc:
            return f"Error: invalid JSON arguments: {exc}"
        try:
            result = self._tools[name].run(**args)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as exc:
            return f"Error ({type(exc).__name__}): {exc}"


# ── Tools: plain functions, schemas auto-generated ─────────────────────

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


# ── Agent loop — identical to agent_v3.py ──────────────────────────────

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
        for fc in function_calls:
            input_items.append({
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": registry.dispatch(fc.name, fc.arguments),
            })
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

### ▶ Run it now

```bash
python agent_v4.py
```

Same output as Versions 1, 2, and 3 — confirm it for yourself. Then notice what *writing a new tool* costs now: a function with type hints and a docstring, plus one `registry.register(...)` line. No schema dict, no `elif` branch, no list to update. Alternatively, take your `agent_v2.py`, replace its two function definitions and schema dicts with the `@tool`-decorated versions (plus the machinery), and confirm the output is identical there too.

---

## Going Further (Optional) — Parallel Tool Execution

**Why now?** The `for` loop over tool calls in Versions 1–4 runs them one at a time. If the model asks for weather in Paris and weather in Tokyo simultaneously, you wait for Paris to finish before starting Tokyo. Threads fix this. This is a speed optimization only — it does not change the results.

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

## Argument Validation: Strict Mode vs. Manual Checks (optional)

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

## Structured Results and Errors (optional)

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

## The Updated Agent Loop — the Production Shape

*The optional detour ends here — the core path resumes with this section.*

With the registry and parallel dispatch in place, the agent loop becomes completely decoupled from individual tools.

```python
# agent.py
from __future__ import annotations

from openai import OpenAI

from tools.registry import ToolRegistry
from tools.parallel import dispatch_parallel

client = OpenAI()
MODEL  = "gpt-4o"


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

## Full Runnable Example — the `tools/` Package

Here is the complete file layout and a runnable script — the Version 4 harness split into modules, the way the consolidated package organizes it.

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

> **Reference copy.** Assembled from Version 4 (§4.5–4.6) unchanged, except the
> docstring parsing is factored into a `_parse_google_docstring` helper. Nothing new to
> type here — skim or skip. The maintained version lives in
> [`code/agent_harness/tools/base.py`](./code/agent_harness/tools/base.py).

```python
# tools/base.py
from __future__ import annotations

import inspect
import json
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

> **Reference copy.** Assembled from Version 3 (§3.2) unchanged, except the validation
> helper is compacted and `register()` returns `self` for chaining. Nothing new to type
> here — skim or skip. The maintained version lives in
> [`code/agent_harness/tools/registry.py`](./code/agent_harness/tools/registry.py).

```python
# tools/registry.py
from __future__ import annotations

import json
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

> **Reference copy.** Assembled from the "Going Further" section above unchanged
> (minus comments). Nothing new to type here — skim or skip. The maintained version
> lives in [`code/agent_harness/tools/parallel.py`](./code/agent_harness/tools/parallel.py).

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

### ▶ Check it now (no API key needed)

The whole `tools/` package can be exercised offline — dispatch never touches the
network. From the `project/` directory, save this as `check_tools.py` and run it:

```python
# check_tools.py — exercises the tools/ package; no API key, no network.
from tools import tool, ToolRegistry

@tool
def add(a: float, b: float) -> str:
    """Add two numbers and return the result.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)

registry = ToolRegistry()
registry.register(add)

print(registry.dispatch("add", '{"a": 2, "b": 3}'))
print(registry.dispatch("add", '{"a": 2}'))
print(registry.dispatch("nope", '{}'))
```

```bash
python check_tools.py
```

You should see:

```text
5
Error: missing required argument 'b'
Error: unknown tool 'nope'.
```

The same three behaviors as the Version 2 dispatch check (§2.4) — proof the package
reorganization changed nothing about what the tool system *does*.

### `agent.py` — Complete with Example Tools

> **Reference copy.** Assembled from "The Updated Agent Loop" above plus three
> `@tool` example tools — unchanged logic. Nothing new to type here — skim or skip.
> The maintained version lives in
> [`code/agent_harness/agent.py`](./code/agent_harness/agent.py).

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
MODEL  = "gpt-4o"


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

## Why We Built It in Versions: The Problems with Ad-Hoc Dispatch

You now have a full tool system. This section names the five failure modes of the Version 1 / Phase 1 one-branch-per-tool approach — useful when you need to explain *why* the registry matters:

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

Track each requirement back through the ladder: registration arrived in V2, classes organized it in V3, schema generation arrived in V4, and validation and parallelism came as add-ons to the registry. Same harness all the way up.

---

## Pitfalls

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

- The same harness climbed a **ladder of versions**: inline `if/elif` (V1) → functions +
  dict registry (V2) → `Tool`/`ToolRegistry` classes (V3) → the `@tool` decorator (V4).
  Every rung produced the same answers; only the organization changed.
- A **registry** (a name → tool lookup) replaces ad-hoc `if/elif` dispatch, so adding a
  tool no longer means editing the loop.
- `@tool` **auto-generates the JSON schema** from the function's type hints and
  docstring — or hand-write the schema yourself (the Version 1–2 approach from this
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

---

## Exercises

See [`EXERCISES.md` — Phase 2](./EXERCISES.md) for hands-on practice:

- **2.1 (warm-up):** Register a new `calculator(expression: str)` tool through the registry (use `@tool`, or hand-write the schema per the beginner track). Call it from the agent without editing the loop.
- **2.2 (stretch):** Give two tools an artificial `time.sleep(2)`. Run them in the same turn once with parallel dispatch and once sequentially; time both. Then describe a case where parallel would be **unsafe**.

---

**Next:** [Phase 3 — Conversation State & Streaming](./03-conversation-and-streaming.md), where the transcript you have been growing by hand gets an owner (a `Conversation` class) and the model's answers start arriving token by token.
