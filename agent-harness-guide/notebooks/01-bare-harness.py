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
# # Phase 1 — A Bare Harness, runnable
#
# Companion to [01-bare-harness.md](../01-bare-harness.md): the full version ladder
# (V1 straight-line → V2 functions → V3 `Agent` class), one rung per section. The
# phase keeps the why; these cells run.
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
MODEL = "gpt-4o"

def make_client(turns):
    """Real OpenAI() if opted in and a key is present, else a scripted FakeClient.

    Only the *model* is faked — your tools, the handshake, and the transcript all
    run for real either way.
    """
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)

OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")

# %% [markdown]
# ## The Loop, Conceptually ([§2](../01-bare-harness.md#2-the-loop-conceptually))
#
# ```text
# ┌─────────────────────────────────────────────────────┐
# │  input_items (grows each iteration)                  │
# │                                                       │
# │  [user msg] ──► responses.create()                   │
# │                        │                             │
# │              ┌─────────▼──────────┐                  │
# │              │  resp.output items │                  │
# │              └──┬─────────────┬───┘                  │
# │          message│       function_call│               │
# │                 │                   │                │
# │           print &           dispatch() → str         │
# │           break            append output item        │
# │                                   │                  │
# │                       input_items += resp.output     │
# │                       input_items += [call_outputs]  │
# │                            │                         │
# │                            └──► responses.create()   │
# └─────────────────────────────────────────────────────┘
# ```

# %% [markdown]
# ## Version 1 — Line-by-Line ([§3](../01-bare-harness.md#3-version-1--line-by-line-no-functions-no-classes))
#
# The entire agent, no `def`, no classes — the tool's logic sits inline in the
# dispatch branch. The client and transcript are created at the top of the cell,
# so re-running it is always safe.

# %%
import datetime, json, zoneinfo

client = make_client([
    [fake_function_call("get_current_time", {"timezone": "Asia/Tokyo"}, "call_001")],
    [fake_message("The current time in Tokyo is shown above — straight from your tool result.")],
])

# ── Tool schema (what the model sees) ────────────────────────────────────────
GET_CURRENT_TIME_SCHEMA = {
    "type": "function",
    "name": "get_current_time",
    "description": "Return the current date and time in an IANA timezone (empty → UTC).",
    "parameters": {
        "type": "object",
        "properties": {
            "timezone": {"type": "string", "description": "IANA name, e.g. 'Asia/Tokyo'"}
        },
        "required": [],
    },
}

# ── Seed the transcript ───────────────────────────────────────────────────────
input_items = [{"role": "user", "content": "What time is it in Tokyo right now?"}]

# ── The loop ──────────────────────────────────────────────────────────────────
while True:
    resp = client.responses.create(
        model="gpt-4o",
        input=input_items,
        tools=[GET_CURRENT_TIME_SCHEMA],
    )

    input_items += resp.output   # always carry the model's output forward first

    tool_calls = [item for item in resp.output if item.type == "function_call"]

    if not tool_calls:           # no more tool calls → we have the final answer
        print("Assistant:", resp.output_text)
        break

    for tc in tool_calls:
        args = json.loads(tc.arguments)   # arguments is a JSON string, not a dict
        if tc.name == "get_current_time":
            # The tool's entire implementation, inline — no function needed yet.
            timezone = args.get("timezone", "")
            if timezone:
                tz = zoneinfo.ZoneInfo(timezone)
            else:
                tz = datetime.timezone.utc
            result = datetime.datetime.now(tz=tz).isoformat(timespec="seconds")
        else:
            result = f"ERROR: unknown tool '{tc.name}'"
        print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
        input_items.append({
            "type": "function_call_output",
            "call_id": tc.call_id,   # must echo call_id exactly — NOT tc.id
            "output": result,        # must be a string
        })

v1_items = input_items   # snapshot for the self-check

# %% [markdown]
# **▶ Self-check** — where the phase says *"you should see something like…"*, we
# assert the structural facts instead.

# %%
def item_type(item):
    # the transcript mixes plain dicts (ours) with SDK/Fake objects (the model's)
    return getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)

types = [item_type(i) for i in v1_items]
print("V1 transcript item types:", types)

assert v1_items[0]["role"] == "user", "transcript starts with the user message"
assert "function_call" in types, "the model should have asked for the tool"
assert "function_call_output" in types, "the loop should have appended a tool result"

calls = [i for i in v1_items if item_type(i) == "function_call"]
outs = [i for i in v1_items if item_type(i) == "function_call_output"]
assert ({getattr(c, "call_id", None) or c.get("call_id") for c in calls}
        == {o["call_id"] for o in outs}), "every call_id must be answered"
assert all(isinstance(o["output"], str) for o in outs), "tool output must be a string"
print("V1 checks passed")

# %% [markdown]
# ## Version 2 — Functions ([§4](../01-bare-harness.md#4-version-2--functions-the-same-harness-named-in-pieces))
#
# **Step 1 — give the tool logic a name.** The phase says "open a Python shell and
# call it directly" — here the shell is already open:

# %%
def get_current_time(timezone=""):
    tz = zoneinfo.ZoneInfo(timezone) if timezone else datetime.timezone.utc
    return datetime.datetime.now(tz=tz).isoformat(timespec="seconds")


# ▶ The tool now exists independently of the agent — no model, no key:
print(get_current_time("Europe/London"))
assert "T" in get_current_time("Europe/London"), "ISO-8601 timestamp expected"

# %% [markdown]
# **Step 2 — extract `dispatch`** ([§4 Step 2](../01-bare-harness.md#4-version-2--functions-the-same-harness-named-in-pieces)):
# errors become strings the model can read — the loop never crashes. All three
# probes below are deterministic and keyless.

# %%
def dispatch(name, arguments):
    """Route a tool call. Always returns a string; never raises."""
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as exc:
        return f"ERROR: could not parse arguments JSON — {exc}"
    try:
        if name == "get_current_time":
            return get_current_time(**args)
        else:
            return f"ERROR: unknown tool '{name}'"
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


print(dispatch("get_current_time", '{"timezone": "Asia/Tokyo"}'))
print(dispatch("get_current_time", '{"timezone": "Not/AZone"}'))   # error string, not a crash
print(dispatch("nope", "{}"))
print(dispatch("get_current_time", "{not json"))

assert dispatch("get_current_time", '{"timezone": "Not/AZone"}').startswith("ERROR:")
assert dispatch("nope", "{}") == "ERROR: unknown tool 'nope'"
assert dispatch("get_current_time", "{not json").startswith("ERROR: could not parse")
print("dispatch checks passed")

# %% [markdown]
# **Step 3 — wrap the loop in `run_agent`.** The phase's `main()` REPL
# (`while True: input(...)`) is a terminal idea — in a notebook each call is its own
# cell, visible and replayable. Two small adaptations from the phase: the client
# comes in as a *parameter* (so each driver cell scripts its own — the same
# injectable-client idea the package uses), and the transcript is *returned* so
# later cells can inspect it.

# %%
def run_agent(user_message, client):
    """Run one conversation to completion; returns the transcript for inspection."""
    input_items = [{"role": "user", "content": user_message}]

    while True:
        resp = client.responses.create(
            model="gpt-4o",
            input=input_items,
            tools=[GET_CURRENT_TIME_SCHEMA],
        )
        input_items += resp.output
        tool_calls = [item for item in resp.output if item.type == "function_call"]

        if not tool_calls:
            print(f"\nAssistant: {resp.output_text}\n")
            return input_items

        for tc in tool_calls:
            result = dispatch(tc.name, tc.arguments)
            print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })

print("run_agent defined.")

# %%
transcript_tokyo = run_agent("What time is it in Tokyo?", make_client([
    [fake_function_call("get_current_time", {"timezone": "Asia/Tokyo"}, "call_t1")],
    [fake_message("It is currently the time shown above in Tokyo (JST).")],
]))

# %%
transcript_math = run_agent("What is 2 + 2?", make_client([
    [fake_message("2 + 2 = 4.")],
]))

# %% [markdown]
# **▶ Self-check** — the second question used **zero** tool calls: the model
# answered directly, so the loop broke after one `create()`.

# %%
tokyo_types = [item_type(i) for i in transcript_tokyo]
math_types = [item_type(i) for i in transcript_math]
print("Tokyo:", tokyo_types)
print("Math :", math_types)

assert "function_call" in tokyo_types and "function_call_output" in tokyo_types
assert "function_call" not in math_types, "no tool needed for arithmetic"
calls = [i for i in transcript_tokyo if item_type(i) == "function_call"]
outs = [i for i in transcript_tokyo if item_type(i) == "function_call_output"]
assert ({getattr(c, "call_id", None) or c.get("call_id") for c in calls}
        == {o["call_id"] for o in outs})
print("V2 checks passed")

# %% [markdown]
# **Step 4 — the `MAX_ITERATIONS` cap** ([§4 Step 4](../01-bare-harness.md#4-version-2--functions-the-same-harness-named-in-pieces)).
# The phase can only *describe* a runaway loop; a scripted model can get stuck on
# demand. This demo always uses `FakeClient` directly — five `function_call` turns
# in a row — so you can watch the cap fire, offline.

# %%
MAX_ITERATIONS = 5   # the phase uses 25; small here so the demo is quick

def run_agent(user_message, client):
    """Same loop, with `while True` replaced by a safety cap."""
    input_items = [{"role": "user", "content": user_message}]

    for iteration in range(MAX_ITERATIONS):   # <-- was: while True
        resp = client.responses.create(
            model="gpt-4o",
            input=input_items,
            tools=[GET_CURRENT_TIME_SCHEMA],
        )
        input_items += resp.output
        tool_calls = [item for item in resp.output if item.type == "function_call"]

        if not tool_calls:
            print(f"\nAssistant: {resp.output_text}\n")
            return input_items

        for tc in tool_calls:
            result = dispatch(tc.name, tc.arguments)
            print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })

    # Only reached if the cap fires
    print(f"[Agent stopped: reached {MAX_ITERATIONS}-iteration safety cap]")
    return input_items


# A model stuck in a loop, scripted: it asks for a bad timezone five times running.
stuck_client = FakeClient([
    [fake_function_call("get_current_time", {"timezone": "Not/AZone"}, f"call_s{i}")]
    for i in range(5)
])
stuck_items = run_agent("What time is it in Nowhere?", stuck_client)

stuck_outs = [i for i in stuck_items if item_type(i) == "function_call_output"]
assert len(stuck_outs) == MAX_ITERATIONS, "the cap should stop it at exactly MAX_ITERATIONS"
assert all(o["output"].startswith("ERROR:") for o in stuck_outs)
print(f"Cap fired after {MAX_ITERATIONS} iterations — loop terminated safely.")

# %% [markdown]
# ## Version 3 — Classes: a minimal `Agent` ([§6](../01-bare-harness.md#6-version-3--classes-a-minimal-agent-preview))
#
# Same loop, same dispatch, same handshake — the *state* moves onto `self`, and
# because the transcript now lives on the object, it **survives between calls to
# `run`**. The next three cells demonstrate that across cell boundaries.

# %%
MAX_ITERATIONS = 25   # back to the phase default


class Agent:
    """The same harness as Version 2, with its state grouped into one object."""

    def __init__(self, client, tools):
        self.client = client          # was: the global `client`
        self.tools = tools            # was: the [GET_CURRENT_TIME_SCHEMA] literal
        self.input_items = []         # was: a local in run_agent — now it persists!

    def dispatch(self, name, arguments):
        """Route a tool call. Always returns a string; never raises."""
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError as exc:
            return f"ERROR: could not parse arguments JSON — {exc}"
        try:
            if name == "get_current_time":
                return get_current_time(**args)
            return f"ERROR: unknown tool '{name}'"
        except Exception as exc:
            return f"ERROR: {type(exc).__name__}: {exc}"

    def run(self, user_message):
        """Run one user message to completion. Same loop as Version 2."""
        self.input_items.append({"role": "user", "content": user_message})

        for iteration in range(MAX_ITERATIONS):
            resp = self.client.responses.create(
                model=MODEL,
                input=self.input_items,
                tools=self.tools,
            )
            self.input_items += resp.output
            tool_calls = [item for item in resp.output if item.type == "function_call"]

            if not tool_calls:
                print(f"\nAssistant: {resp.output_text}\n")
                return

            for tc in tool_calls:
                result = self.dispatch(tc.name, tc.arguments)
                print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
                self.input_items.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result,
                })

        print(f"[Agent stopped: reached {MAX_ITERATIONS}-iteration safety cap]")


print("Agent defined.")

# %% [markdown]
# > ⚠️ **Deliberate persistence demo.** The next three cells share one `agent`
# > whose memory — and whose consumable FakeClient script — persists *across*
# > cells. Run them **once, in order**. To replay, re-run from the construction
# > cell below (a reset cell follows the demo).

# %%
agent = Agent(make_client([
    [fake_function_call("get_current_time", {"timezone": "Asia/Tokyo"}, "call_a1")],
    [fake_message("It is currently the time shown above in Tokyo.")],
    [fake_function_call("get_current_time", {"timezone": "Europe/London"}, "call_a2")],
    [fake_message("And in London it is the time shown above — same moment, different zone.")],
]), [GET_CURRENT_TIME_SCHEMA])

print("Agent built — transcript length:", len(agent.input_items))

# %%
agent.run("What time is it in Tokyo?")
print("transcript length after turn 1:", len(agent.input_items))

# %%
# "And in London?" only makes sense because the Tokyo turn is still in the
# transcript — the memory lives on agent.input_items, not in the model.
agent.run("And in London?")
print("transcript length after turn 2:", len(agent.input_items))

v3_items = agent.input_items   # snapshot for the final check

# %%
# Reset the persistence demo: the agent above is spent (its scripted client has no
# turns left). Re-run the three cells above, in order, to replay it.
agent = None
print("agent reset — the v3_items snapshot is kept for the final check below")

# %% [markdown]
# **▶ Final self-check** — every rung of the ladder, machine-checked.

# %%
user_turns = [i for i in v3_items if isinstance(i, dict) and i.get("role") == "user"]
assert len(user_turns) == 2, "V3's memory: BOTH questions live in one transcript"

for label, transcript in [("V1", v1_items), ("V2", transcript_tokyo), ("V3", v3_items)]:
    calls = [i for i in transcript if item_type(i) == "function_call"]
    outs = [i for i in transcript if item_type(i) == "function_call_output"]
    assert calls and outs, f"{label}: the tool handshake should have happened"
    assert ({getattr(c, "call_id", None) or c.get("call_id") for c in calls}
            == {o["call_id"] for o in outs}), f"{label}: orphaned call_id"
    assert all(isinstance(o["output"], str) for o in outs), f"{label}: outputs are strings"

assert "function_call" not in [item_type(i) for i in transcript_math]
print("All checks passed")

# %% [markdown]
# **Optional — the same harness against the real API** (needs `OPENAI_API_KEY`):

# %%
if os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    live_items = run_agent("What time is it in Tokyo right now?", OpenAI())
else:
    print("(skipped — no API key; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - The agent loop is three lines of logic: `create` → check for tool calls →
#   dispatch and append — repeat. All three versions are **the same harness**.
# - Carry `resp.output` forward **first**, then the tool outputs; echo `call_id`
#   exactly; tool errors return as **strings**; always keep a `MAX_ITERATIONS` cap.
#
# Now do the phase's [Check yourself](../01-bare-harness.md#check-yourself) and
# [Pitfalls](../01-bare-harness.md#pitfalls), then the Phase 1 exercises in
# [EXERCISES.md](../EXERCISES.md). Two starter cells:

# %%
# Quiz: a function_call item has both `.id` and `.call_id`. Which one do you echo back?
answer = "call_id"   # <- edit me, then run

assert answer == "call_id", "Hint: re-read the comment in the V1 loop's append."
print("Correct — call_id is the correlation key; id is just the item's identity.")

# %%
# Exercise 1.1 (warm-up): add a second tool — get_weather(city) returning a fixed
# string. Extend dispatch, write GET_WEATHER_SCHEMA, then script a FakeClient turn
# that calls it and run it through run_agent.
# your code here

# assert dispatch("get_weather", '{"city": "Paris"}') == "Sunny, 21°C in Paris"  # uncomment when ready
print("(exercise scaffold — fill in the code above)")
