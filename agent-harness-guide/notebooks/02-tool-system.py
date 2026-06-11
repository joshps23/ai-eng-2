# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Phase 2 — A Real Tool System (companion notebook)
#
# Runnable companion to [Phase 2 — A Real Tool System](../02-tool-system.md): the
# version ladder from inline `if/elif` dispatch to the `@tool` decorator, executed live.
#
# **Conventions:** run top-to-bottom. When confused: *Kernel → Restart & Run All*.
# Every cell below runs **without** an API key.

# %%
import sys
import agent_harness

print(sys.executable)
print("agent_harness:", agent_harness.__file__)

# %% tags=["parameters"]
import os
import json

from agent_harness.testing import FakeClient, fake_function_call, fake_message

USE_REAL_API = False  # flip to True (with OPENAI_API_KEY set) to talk to the real API
MODEL = "gpt-4o"


def make_client(turns):
    """Real OpenAI() if opted in and a key exists; otherwise a scripted FakeClient."""
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)


OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")

# %% [markdown]
# ## Version 1 — inline `if/elif` dispatch
#
# A "tool" is just a dict describing a function, in the **flat** Responses-API format —
# see [§1.1 The schema dicts and the tools list](../02-tool-system.md#11-the-schema-dicts-and-the-tools-list).
# What prints below is *exactly* what the model will see. (`TOOLS_V1` is the phase's
# `TOOLS` list — suffixed here because Version 2 turns it into a dict.)

# %%
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

TOOLS_V1 = [add_schema, word_count_schema]
print(json.dumps(TOOLS_V1, indent=2))

# %% [markdown]
# Now [the loop with the tool logic inlined](../02-tool-system.md#12-the-loop-with-the-tool-logic-inlined) —
# `str(args["a"] + args["b"])` lives right inside the `if`. The client and transcript are
# created at the top of the cell, so re-running it always gives a clean run. Only the
# *model* is scripted; the tool arithmetic below is computed for real.

# %%
import re

client = make_client([
    [fake_function_call("add", {"a": 1234, "b": 5678}, "call_001"),
     fake_function_call("word_count",
                        {"text": "The quick brown fox jumps over the lazy dog"},
                        "call_002")],
    [fake_message("1234 + 5678 = 6912. The sentence has 9 words.")],
])

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
        tools=TOOLS_V1,
    )

    input_items += resp.output

    function_calls = [item for item in resp.output if item.type == "function_call"]

    if not function_calls:
        # No tool calls — the model is done. (The phase file digs the text out of
        # message parts; resp.output_text is the equivalent shortcut.)
        final_answer = resp.output_text
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

# %% [markdown]
# ▶ Self-check for Version 1 — asserts instead of "you should see". The tool outputs
# (`6912`, `9`) are real computation; only the model's words were scripted.

# %%
def item_type(item):
    # the transcript mixes plain dicts (ours) and SDK/Fake objects (the model's)
    return getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)


assert input_items[0]["role"] == "user", "transcript must start with the user message"

calls = [i for i in input_items if item_type(i) == "function_call"]
outs = [i for i in input_items if item_type(i) == "function_call_output"]
assert len(calls) == 2 and len(outs) == 2, "expected two tool calls, two results"
assert {getattr(c, "call_id", None) for c in calls} == {o["call_id"] for o in outs}, \
    "every function_call's call_id must have a matching function_call_output"

by_id = {o["call_id"]: o["output"] for o in outs}
assert by_id["call_001"] == "6912"   # the add branch really ran
assert by_id["call_002"] == "9"      # the word_count branch really ran

for schema in TOOLS_V1:              # flat format: no nested "function" wrapper
    assert schema["type"] == "function"
    assert {"name", "description", "parameters"} <= set(schema)

print("V1 checks passed")

# %% [markdown]
# ## Version 2 — functions and a dict registry
#
# V1's pain: a new tool means edits in **three places** that drift apart by hand. So:
# logic moves into named functions, the `if/elif` chain becomes a dict lookup, and dispatch
# learns to return `"Error: ..."` strings instead of crashing — see
# [Version 2 — Functions and a Dict Registry](../02-tool-system.md#version-2--functions-and-a-dict-registry).

# %%
# ── Tool 1 ────────────────────────────────────────────────────────────
def add(a, b):
    """Add two numbers."""
    return str(a + b)


# ── Tool 2 ────────────────────────────────────────────────────────────
def word_count(text):
    """Count the words in a string."""
    return str(len(re.findall(r"\S+", text)))


print(add(2, 3), "/", word_count("one two three"))  # plain functions — call them directly

# %% [markdown]
# The registry is just a dict mapping a tool's name to its function **and** its schema
# ([§2.2](../02-tool-system.md#22-register-them-in-a-plain-dict)–[§2.3](../02-tool-system.md#23-build-the-list-the-api-needs)).
# The phase's `TOOLS` dict is `TOOLS_V2` here, because V1's `TOOLS` was a *list*. The cell
# rebuilds and re-registers in one go, so re-running it is safe — with one caveat: the
# `@tool` section near the end rebinds `add` (and `word_count`) to `FunctionTool` objects.
# After you've run that section, re-run the V2 function-definition cell above first, so
# this cell registers the plain functions again and not the FunctionTools.

# %%
# The registry maps a tool name -> {"fn": the function, "schema": the dict}.
TOOLS_V2 = {}


def register(name, fn, schema):
    """Add one tool to the registry."""
    TOOLS_V2[name] = {"fn": fn, "schema": schema}


register("add", add, add_schema)
register("word_count", word_count, word_count_schema)


def tools_for_api():
    """Return the list passed to client.responses.create(tools=...)."""
    result = []
    for entry in TOOLS_V2.values():
        result.append(entry["schema"])
    return result


print("registered tools:", sorted(TOOLS_V2))

# %% [markdown]
# [§2.4 Dispatch](../02-tool-system.md#24-dispatch-look-up-a-tool-and-call-it): look up a
# tool, run it, and **always return a string** — never crash. The three probes below are
# the phase's "Check it now (no API key needed)" moment, verbatim.

# %%
def dispatch(name, arguments_str):
    """Look up a tool, run it, and ALWAYS return a string (never crash)."""
    if name not in TOOLS_V2:
        return f"Error: unknown tool '{name}'."
    try:
        args = json.loads(arguments_str)   # JSON string -> dict
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON arguments: {exc}"
    try:
        fn = TOOLS_V2[name]["fn"]
        result = fn(**args)                # call the function with the dict's keys
        if not isinstance(result, str):
            result = json.dumps(result)
        return result
    except Exception as exc:
        return f"Error ({type(exc).__name__}): {exc}"


print(dispatch("add", '{"a": 2, "b": 3}'))      # 5
print(dispatch("add", '{"a": 2}'))              # Error (TypeError): ...
print(dispatch("nope", '{}'))                   # Error: unknown tool 'nope'.

# %% [markdown]
# The loop wrapped in `run_agent()` ([§2.5](../02-tool-system.md#25-handle-multiple-tool-calls--a-plain-for-loop)–[§2.6](../02-tool-system.md#26-the-full-agent-loop-using-only-functions-and-dicts)) —
# now you can ask different questions without editing the file's middle.

# %%
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
            return resp.output_text   # (the phase file extracts this from message parts)

        tool_outputs = run_tool_calls(function_calls)
        input_items.extend(tool_outputs)
        print(f"[turn {turn + 1}] tools called: {[fc.name for fc in function_calls]}")

    raise RuntimeError(f"Agent did not finish within {max_turns} turns.")


print("run_agent ready")

# %%
client = make_client([
    [fake_function_call("add", {"a": 1234, "b": 5678}, "call_001"),
     fake_function_call("word_count",
                        {"text": "The quick brown fox jumps over the lazy dog"},
                        "call_002")],
    [fake_message("1234 + 5678 = 6912. The sentence has 9 words.")],
])

answer = run_agent(
    "What is 1234 + 5678? "
    "Also, how many words are in: 'The quick brown fox jumps over the lazy dog'?"
)
print("\nFinal answer:")
print(answer)

# %% [markdown]
# ▶ Self-check for Version 2. The last assert is the phase's whole point: *the same
# output as Version 1* — only the organization changed.

# %%
assert isinstance(TOOLS_V1, list) and isinstance(TOOLS_V2, dict), \
    "TOOLS_V1 is a list, TOOLS_V2 a dict — the type change IS the V1 -> V2 step"
assert dispatch("add", '{"a": 2, "b": 3}') == "5", (
    "dispatch should call the plain add function — if you re-ran the registry cell "
    "after the @tool section, re-run the V2 function-definition cell first"
)
assert dispatch("add", '{"a": 2}').startswith("Error"), \
    "a missing argument should come back as a readable Error string, not a crash"
assert dispatch("nope", '{}').startswith("Error"), \
    "an unknown tool should come back as a readable Error string"
assert len(tools_for_api()) == 2, "the registry should expose exactly two schemas"
assert answer == final_answer, "V2 must produce the same answer as V1 — that is the point"
print("V2 checks passed")

# %% [markdown]
# ## Version 3 — classes: `Tool` and `ToolRegistry`
#
# Same information, organized: each *function + schema* pair becomes one `Tool` object —
# see [Version 3 — Classes: `Tool` and `ToolRegistry`](../02-tool-system.md#version-3--classes-tool-and-toolregistry).
# `AddTool().run(a=2, b=3)` is the phase's "Check it now" probe.

# %%
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


print(AddTool().run(a=2, b=3))          # "5" — the object carries its own behavior...
print(AddTool().parameters["required"])  # ...and its own schema

# %% [markdown]
# The registry as a class (the phase's compact form). One object owns registration, schema
# export, and dispatch. `register` now **raises** on duplicates — which is why this cell
# builds the registry *and* registers the tools together: re-running it starts fresh.

# %%
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

print(registry.dispatch("add", '{"a": 1234, "b": 5678}'))
print([s["name"] for s in registry.to_openai_schema()])

# %% [markdown]
# ▶ Self-check for Version 3 — including the new behavior: duplicate registration is a
# loud `ValueError`, not a silent overwrite.

# %%
assert registry.dispatch("add", '{"a": 2, "b": 3}') == "5"
assert registry.dispatch("word_count", '{"text": "one two three"}') == "3"
assert registry.dispatch("nope", '{}').startswith("Error")

schemas = registry.to_openai_schema()
assert [s["name"] for s in schemas] == ["add", "word_count"]
assert schemas[0]["parameters"] == add_schema["parameters"]  # same dict as V1/V2

try:
    registry.register(AddTool())
    raise AssertionError("expected ValueError on duplicate registration")
except ValueError as exc:
    print("duplicate registration correctly refused:", exc)

print("V3 checks passed")

# %% [markdown]
# ## Version 4 — the `@tool` decorator
#
# [§4.2](../02-tool-system.md#42-write-a-function-with-type-hints-and-a-docstring) says
# *"Read, don't run (yet)"* — the `tool` decorator doesn't exist yet. In a notebook we can
# run it anyway and watch the failure. Without the `try/except` fence below you would see
# the raw `NameError: name 'tool' is not defined` traceback — we catch it only so
# *Restart & Run All* still passes. After this cell, `add` is still the V2 plain function.

# %%
try:
    @tool
    def add(a: float, b: float) -> str:
        """Add two numbers and return the result.

        Args:
            a: First number.
            b: Second number.
        """
        return str(a + b)
except NameError as exc:
    print(f"NameError: {exc}")
    print("(expected — we build the `tool` decorator in the next cell, then re-run this idea)")
else:
    print("(no error this time — `tool` now exists; it rebound `add` as a FunctionTool)")

# %% [markdown]
# Now build what was missing:
# [`FunctionTool`](../02-tool-system.md#45-functiontool--wrapping-a-decorated-function)
# wraps a plain function as a `Tool`, and
# [the decorator's internals](../02-tool-system.md#46-the-tool-decorators-internals)
# introspect type hints + docstring to build the schema dict for you.

# %%
import inspect
from typing import Any, Callable, get_type_hints


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


# Maps Python types to JSON Schema type strings
_PY_TO_JSON = {
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
    param_docs = {}
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

    properties = {}
    required   = []

    for pname, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        py_type = hints.get(pname, str)
        json_type = _PY_TO_JSON.get(py_type, "string")

        prop = {"type": json_type}
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
    """Decorator. Converts a plain function into a Tool instance."""
    schema = _build_schema(fn)
    return FunctionTool(
        name=fn.__name__,
        description=schema.pop("description", fn.__doc__ or ""),
        parameters=schema,
        fn=fn,
    )


print("@tool decorator defined")

# %% [markdown]
# The §4.2 moment, re-run now that `tool` exists — and
# [§4.3 verify what the decorator produced](../02-tool-system.md#43-verify-what-the-decorator-produced).
# **Heads-up:** from here `add` (and `word_count` below) is no longer a plain function —
# it is a `FunctionTool`. `add(2, 3)` stops working; `add.run(a=2, b=3)` starts.
# (The V2 registry still works: it stored references to the original functions.)

# %%
@tool
def add(a: float, b: float) -> str:
    """Add two numbers and return the result.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)


print(type(add).__name__)   # FunctionTool — the decorator returned an object, not a function
print(json.dumps(add.parameters, indent=2))

# %% [markdown]
# [A more complex function](../02-tool-system.md#seeing-the-generated-schema-for-a-more-complex-function):
# `strip_punctuation` has a default, so the decorator leaves it out of `required` —
# optionality inferred straight from the signature.

# %%
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


print(json.dumps(word_count.parameters, indent=2))

# %% [markdown]
# ▶ Final self-check: the decorator's schema is **identical** to the hand-written V1 dict,
# and the V3 registry accepts `@tool` objects unchanged — `registry.register(add)`, done.

# %%
assert isinstance(add, FunctionTool) and isinstance(word_count, FunctionTool)
assert add.run(a=2, b=3) == "5"
assert add.parameters == add_schema["parameters"], "auto-built schema == hand-written schema"
assert word_count.parameters["required"] == ["text"], "default value => optional parameter"

registry_v4 = ToolRegistry()
registry_v4.register(add)            # a FunctionTool IS a Tool — no adapter needed
registry_v4.register(word_count)
assert registry_v4.dispatch("add", '{"a": 2, "b": 3}') == "5"
assert registry_v4.dispatch("word_count", '{"text": "one two three"}') == "3"
assert [s["name"] for s in registry_v4.to_openai_schema()] == ["add", "word_count"]

# cross-version invariants: the whole ladder is one behavior, reorganized
assert isinstance(TOOLS_V1, list) and isinstance(TOOLS_V2, dict)
assert registry_v4.to_openai_schema()[0]["parameters"] == TOOLS_V1[0]["parameters"]

print("All checks passed")

# %% [markdown]
# ## 🛑 This notebook stops here — the multi-file form is files' job
#
# Everything after this point in the phase — parallel dispatch, strict mode, and the
# **`tools/` package** with its relative imports — belongs in real files, not kernel cells.
# Continue in [Full Runnable Example — the `tools/` Package](../02-tool-system.md#full-runnable-example--the-tools-package)
# (and [parallel tool execution](../02-tool-system.md#going-further-optional--parallel-tool-execution)),
# then read the tested versions in `code/agent_harness/tools/`.

# %%
if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    client = OpenAI()            # run_agent reads the module-level `client`
    print(run_agent(
        "What is 1234 + 5678? "
        "Also, how many words are in: 'The quick brown fox jumps over the lazy dog'?"
    ))
else:
    print("(skipped — needs USE_REAL_API = True in the parameters cell AND an "
          "OPENAI_API_KEY; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - A tool = a function + a schema dict; a registry = a dict (or object) mapping a name to both.
# - `dispatch` **never raises** — errors become strings the model can read and recover from.
# - `@tool` just automates the schema dict you already wrote by hand in V1.
#
# More: the phase's [Check yourself](../02-tool-system.md#check-yourself) and
# [EXERCISES.md — Phase 2](../EXERCISES.md#phase-2--the-tool-system).

# %%
# Exercise 2.1 (warm-up): register a calculator(expression: str) tool through the
# registry — without editing any loop. Uncomment and complete:
#
# @tool
# def calculator(expression: str) -> str:
#     """Evaluate a basic arithmetic expression.
#
#     Args:
#         expression: An arithmetic expression like "2+3*4".
#     """
#     # your code here
#
# registry_ex = ToolRegistry()
# registry_ex.register(calculator)
# assert registry_ex.dispatch("calculator", '{"expression": "2+3*4"}') == "14"
# print("exercise 2.1 passed")
print("your turn — uncomment the scaffold above and complete it")
