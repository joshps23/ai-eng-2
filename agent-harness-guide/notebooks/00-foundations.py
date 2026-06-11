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
# # Phase 0 — Foundations, runnable
#
# Companion to [00-foundations.md](../00-foundations.md): the handshake ladder
# (§0.3 Version 1, §0.4 Version 2), one step per cell. The phase keeps the why;
# these cells run.
#
# **Conventions:** Run top-to-bottom. When confused: *Kernel → Restart & Run All*.
# Every cell below runs **WITHOUT** an API key.

# %%
import sys
import agent_harness
print(sys.executable)
print("agent_harness:", agent_harness.__file__)

# %% tags=["parameters"]
import os
from agent_harness.testing import FakeClient, fake_function_call, fake_message

USE_REAL_API = False  # flip to True (with OPENAI_API_KEY set) to talk to the real API
MODEL = "gpt-4o"      # the guide's canonical model id (Phase 0 §0.3.1)

def make_client(turns):
    """Real OpenAI() if opted in and a key is present, else a scripted FakeClient.

    The fake works because nothing in the handshake ever asks "are you real?" —
    it only calls client.responses.create(...) and reads resp.output. That
    injectable-client design is what makes the package's offline tests possible.
    """
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)

OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")

# %% [markdown]
# ## Version 1 — the whole handshake, line by line
#
# [§0.3.2 Step 1](../00-foundations.md#032-step-1--the-simplest-possible-call-text-in-text-out):
# the simplest possible call — text in, text out. The client is built *inside* the
# cell, so re-running it is always safe.

# %%
client = make_client([[fake_message("Hello there! How are you?")]])

resp = client.responses.create(
    model=MODEL,
    instructions="You are a terse assistant.",   # the system prompt
    input="Say hello in five words.",            # a string OR a list of items
)

print(resp.output_text)  # convenience: all text output concatenated
assert resp.output_text, "Step 1: the model should have said something"

# %% [markdown]
# **Step 2** ([§0.3.3](../00-foundations.md#033-step-2--input-as-a-list-of-items)):
# `input` as a **list of items** — the full-control form the harness owns and appends to.

# %%
client = make_client([[fake_message("Paris.")]])

input_items = [
    {"role": "user", "content": "What's the capital of France?"},
]
resp = client.responses.create(model=MODEL, input=input_items)
print(resp.output_text)
assert "Paris" in resp.output_text

# %% [markdown]
# **Step 3** ([§0.3.5](../00-foundations.md#035-step-3--defining-a-tool-and-seeing-the-model-request-it)):
# define one tool and watch the model *not* answer in text — it asks you to run
# `get_weather` instead. `resp.output` is a list of **typed items**.

# %%
client = make_client([[fake_function_call("get_weather", {"city": "Tokyo"}, "call_xyz789")]])

tools = [{
    "type": "function",
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name, e.g. 'Paris'"},
        },
        "required": ["city"],
        "additionalProperties": False,
    },
}]

input_items = [{"role": "user", "content": "What's the weather like in Tokyo?"}]
resp = client.responses.create(model=MODEL, input=input_items, tools=tools)

for item in resp.output:
    print(f"item.type = {item.type}")
    if item.type == "function_call":
        print(f"  name      = {item.name}")
        print(f"  arguments = {item.arguments}")
        print(f"  call_id   = {item.call_id}")

assert any(item.type == "function_call" for item in resp.output), \
    "Step 3: the model should request the tool, not answer in text"

# %% [markdown]
# **Step 4 — Version 1, complete**
# ([§0.3.6](../00-foundations.md#036-step-4--the-tool-call--result-handshake-the-critical-step)):
# the whole two-turn handshake, straight-line, no `def`. The tool is one inlined
# f-string; the `call_id` echo is the glue.

# %%
# version1_handshake.py — the complete handshake, straight-line, no def
import json

client = make_client([
    [fake_function_call("get_weather", {"city": "Tokyo"}, "call_xyz789")],
    [fake_message("The weather in Tokyo is sunny and 21°C.")],
])

input_items = [{"role": "user", "content": "What's the weather like in Tokyo?"}]

# Turn 1: model should ask to call get_weather
resp = client.responses.create(model=MODEL, input=input_items, tools=tools)
input_items += resp.output   # carry all output items forward

# Execute any tool calls — the "tool" is inlined right here
for item in resp.output:
    if item.type == "function_call":
        args = json.loads(item.arguments)
        # Stub: a real harness would call a weather API here
        result = f"Sunny, 21°C in {args['city']}"
        input_items.append({
            "type": "function_call_output",
            "call_id": item.call_id,   # echo back the same call_id
            "output": result,          # a string
        })

# Turn 2: feed the result back; model should now answer in words
resp = client.responses.create(model=MODEL, input=input_items, tools=tools)
print(resp.output_text)

v1_items = input_items          # snapshot for the self-check below
v1_answer = resp.output_text

# %% [markdown]
# **▶ Self-check** — in the phase this checkpoint says *"you should see something
# like…"*; here we **assert** the structural facts that must hold no matter which
# client ran. One thing to expect in the printout: the `None` at the start of the
# type list is the user message — it's a plain dict with only a `role`, no `type`
# attribute, so the helper reports `None` for it.
#
# > 🟢 **Reading the check cells.** Three idioms recur in every ▶ self-check:
# > `getattr(x, "type", None) or x.get("type")` reads a field from either an SDK
# > *object* (dot access) or a plain *dict* (key access); `{... for c in calls}` is a
# > set comprehension (a list comprehension that builds a `set`, handy for comparing
# > "the same ids on both sides"); and `assert A or B` passes when *either* condition
# > holds (used to relax exact-match checks when the real API ran). More Python
# > refreshers: [BEGINNER-NOTES.md](../BEGINNER-NOTES.md).

# %%
def item_type(item):
    # the transcript mixes plain dicts (ours) with SDK/Fake objects (the model's)
    return getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)

types = [item_type(i) for i in v1_items]
print("V1 transcript item types:", types)

assert v1_items[0]["role"] == "user", "the transcript starts with the user message"
assert "function_call" in types, "the model should have asked for the tool"
assert "function_call_output" in types, "we should have appended a tool result"

calls = [i for i in v1_items if item_type(i) == "function_call"]
outs = [i for i in v1_items if item_type(i) == "function_call_output"]
call_ids = {getattr(c, "call_id", None) or c.get("call_id") for c in calls}
out_ids = {o["call_id"] for o in outs}
assert call_ids == out_ids, f"every call_id must be answered: {call_ids} vs {out_ids}"
assert all(isinstance(o["output"], str) for o in outs), "tool output must be a string"
print("V1 checks passed")

# %% [markdown]
# ## Version 2 — the same handshake, organized into functions
#
# [§0.4](../00-foundations.md#04-version-2--the-same-handshake-organized-into-functions):
# identical behavior, three new names. **Step 1 — `call_model`**: define the name,
# then re-run the *same* driver with both `create(...)` lines replaced. The output
# must not change — your first refactor.

# %%
def call_model(input_items):
    """One turn: send the whole transcript, get back the model's output items."""
    return client.responses.create(model=MODEL, input=input_items, tools=tools)


client = make_client([
    [fake_function_call("get_weather", {"city": "Tokyo"}, "call_xyz789")],
    [fake_message("The weather in Tokyo is sunny and 21°C.")],
])
input_items = [{"role": "user", "content": "What's the weather like in Tokyo?"}]

resp = call_model(input_items)        # was: client.responses.create(...)
input_items += resp.output
for item in resp.output:
    if item.type == "function_call":
        args = json.loads(item.arguments)
        result = f"Sunny, 21°C in {args['city']}"
        input_items.append({
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": result,
        })
resp = call_model(input_items)        # was: the second create(...)
print(resp.output_text)
assert OFFLINE is False or resp.output_text == v1_answer, "same program, one new name"

# %% [markdown]
# **Step 2 — `run_tool`**
# ([§0.4.2](../00-foundations.md#042-step-2--name-the-tools-work-run_tool)):
# the part that *is* the tool, separated from the bookkeeping. It returns a
# **string** — and reports failures as strings too, never raising.

# %%
def run_tool(name, args):
    """Execute one tool call and return its result as a STRING."""
    if name == "get_weather":
        # Stub: a real harness would call a weather API here
        return f"Sunny, 21°C in {args['city']}"
    return f"Error: unknown tool '{name}'"


# ▶ Check it now — no model, no key, just the tool:
print(run_tool("get_weather", {"city": "Paris"}))
print(run_tool("teleport", {}))
assert run_tool("get_weather", {"city": "Paris"}) == "Sunny, 21°C in Paris"
assert run_tool("teleport", {}).startswith("Error:")

# %% [markdown]
# **Step 3 — `handle_tool_calls`**
# ([§0.4.3](../00-foundations.md#043-step-3--name-the-handshake-bookkeeping-handle_tool_calls)):
# pure protocol — decode `arguments`, run the tool, echo the **same `call_id`**.
# Name it once and stop thinking about it.

# %%
def handle_tool_calls(output_items, input_items):
    """For every function_call in output_items, run the tool and append its result."""
    for item in output_items:
        if item.type == "function_call":
            args = json.loads(item.arguments)
            result = run_tool(item.name, args)
            input_items.append({
                "type": "function_call_output",
                "call_id": item.call_id,   # echo back the same call_id
                "output": result,          # a string
            })

print("handle_tool_calls defined.")

# %% [markdown]
# **The complete Version 2**
# ([§0.4.4](../00-foundations.md#044-the-complete-version-2-program)):
# the top-level script now tells the story in four lines.

# %%
client = make_client([
    [fake_function_call("get_weather", {"city": "Tokyo"}, "call_xyz789")],
    [fake_message("The weather in Tokyo is sunny and 21°C.")],
])
input_items = [{"role": "user", "content": "What's the weather like in Tokyo?"}]

resp = call_model(input_items)              # Turn 1: model asks for the tool
input_items += resp.output                  # carry all output items forward
handle_tool_calls(resp.output, input_items) # run tools, append their results
resp = call_model(input_items)              # Turn 2: model answers in words
print(resp.output_text)

v2_items = input_items
v2_answer = resp.output_text

# %% [markdown]
# **▶ Final self-check** — the ladder's key claim, machine-checked: *abstraction
# changes how code is arranged, never what it does.*

# %%
for label, transcript in [("V1", v1_items), ("V2", v2_items)]:
    types = [item_type(i) for i in transcript]
    assert transcript[0]["role"] == "user"
    assert "function_call" in types and "function_call_output" in types
    calls = [i for i in transcript if item_type(i) == "function_call"]
    outs = [i for i in transcript if item_type(i) == "function_call_output"]
    assert ({getattr(c, "call_id", None) or c.get("call_id") for c in calls}
            == {o["call_id"] for o in outs}), f"{label}: orphaned call_id"
    assert all(o["output"].startswith("Sunny, 21°C") for o in outs), \
        f"{label}: the stub tool really ran"

if OFFLINE:
    # Offline the scripts are deterministic, so we can check exact equality:
    assert v1_answer == v2_answer, "V1 and V2 are the same program on the wire"
print("All checks passed")

# %% [markdown]
# **Optional — the same Step 1 against the real API** (needs `OPENAI_API_KEY`):

# %%
if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    live = OpenAI()
    live_resp = live.responses.create(
        model=MODEL,
        instructions="You are a terse assistant.",
        input="Say hello in five words.",
    )
    print(live_resp.output_text)
else:
    print("(skipped — needs USE_REAL_API = True in the parameters cell AND an "
          "OPENAI_API_KEY; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - The harness gives a stateless LLM **memory** (the growing `input` list) and
#   **hands** (tools); `resp.output` is a list of typed items.
# - The handshake: a `function_call` with a `call_id` is answered by a
#   `function_call_output` carrying the **same `call_id`** and a **string** output.
# - V1 → V2 changed *arrangement*, not behavior — the asserts proved it.
#
# Now do the phase's [Check yourself](../00-foundations.md#check-yourself) and the
# Phase 0 exercise in [EXERCISES.md](../EXERCISES.md): reorganize `check_setup.py`
# (§0.8) into the Version 2 shape and add a `multiply` tool. Starter cell:

# %%
# Exercise (EXERCISES.md — Phase 0): port check_setup.py (§0.8) to the V2 shape and
# add a `multiply` tool to run_tool. Script your own client, e.g.:
#   make_client([[fake_function_call("add", {"a": 21, "b": 21}, "call_1")],
#                [fake_message("21 + 21 = 42")]])
# Remember: the model only sees tools whose schema dicts are in the `tools` list you
# pass to create() — write add/multiply schemas too, or a real API run never calls them.
# your code here

# assert run_tool("multiply", {"a": 6, "b": 7}) == "42"   # uncomment when ready
print("(exercise scaffold — fill in the code above)")
