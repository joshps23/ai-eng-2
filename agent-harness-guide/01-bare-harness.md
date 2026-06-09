# Phase 1 — A Bare Harness in ~80 Lines

> **Series context:** Phase 0 established the agent-loop theory and the full API contract (how `responses.create` works, the structure of `resp.output`, the tool-call handshake, and the `function_call_output` pattern). This phase puts that contract into practice with the smallest possible working implementation. Read Phase 0 first; this phase references it but does not repeat it.

---

## 1. What We're Building

By the end of this phase you will have a single Python file — `bare_harness.py` — that:

- Accepts free-form user messages in a REPL.
- Maintains a growing transcript (`input_items`) across turns.
- Routes tool calls to real Python functions and feeds results back to the model.
- Terminates cleanly when the model produces a final text answer.

The tool is deliberately trivial (`get_current_time`), because the goal is to make the **loop** visible, not to build useful tooling yet. Once you understand this loop, you understand 90% of every agent ever written — the rest is scaffolding around it.

---

## 2. The Loop, Conceptually

Every agent iteration is the same three-step cycle:

1. **Ask** — send the current transcript to the model.
2. **Inspect** — if the response contains tool calls, execute them and append the results; go to step 1.
3. **Answer** — if the response contains no tool calls, emit the text and stop.

```
┌─────────────────────────────────────────────────────┐
│  input_items (grows each iteration)                  │
│                                                       │
│  [user msg] ──► responses.create()                   │
│                        │                             │
│              ┌─────────▼──────────┐                  │
│              │  resp.output items │                  │
│              └──┬─────────────┬───┘                  │
│          message│       function_call│               │
│                 │                   │                │
│           print &           dispatch() → str         │
│           break            append output item        │
│                                   │                  │
│                       input_items += resp.output     │
│                       input_items += [call_outputs]  │
│                            │                         │
│                            └──► responses.create()   │
└─────────────────────────────────────────────────────┘
```

The transcript is **append-only**: nothing is ever removed, and the model's own output items travel back in unchanged as part of the next call's `input`.

---

## 3. Building It Incrementally

### 3a. Define One Tool

We need two things for every tool: a **JSON schema definition** (what we send to the API) and a **Python function** (what runs locally).

```python
# ── Tool schema ───────────────────────────────────────────────────────────────
import zoneinfo, datetime

GET_CURRENT_TIME_SCHEMA = {
    "type": "function",
    "name": "get_current_time",
    "description": (
        "Return the current date and time. "
        "Pass an IANA timezone name (e.g. 'America/New_York') to localise; "
        "omit or pass an empty string for UTC."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone name, e.g. 'Europe/London'. Empty → UTC.",
            }
        },
        "required": [],
    },
}


def get_current_time(timezone: str = "") -> str:
    """Return the current time as an ISO-8601 string in the requested zone."""
    if timezone:
        tz = zoneinfo.ZoneInfo(timezone)          # raises ZoneInfoNotFoundError on bad name
    else:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz=tz)
    return now.isoformat(timespec="seconds")
```

> 🟢 **Two small bits of new syntax in that function.** (1) The `: str` and `-> str`
> are **type hints** — optional labels saying "this is a string." They do nothing when
> the code runs; read past them. (2) Later you'll see the function called as
> `get_current_time(**args)` where `args` is a dict like `{"timezone": "Asia/Tokyo"}`.
> The `**` "spreads" a dict into named arguments, so that call is exactly the same as
> writing `get_current_time(timezone="Asia/Tokyo")`. See
> [`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md) for the full list.

Key points:

- The schema is **flat** — `type`, `name`, `description`, `parameters` are all top-level keys. There is no nested `"function"` wrapper.
- `required` is an empty list because `timezone` is optional; the model may omit it entirely.
- We do **not** set `"strict": True` here. Strict mode makes the API guarantee
  the arguments match the schema exactly, but it requires *every* property to be
  listed in `required` (and `"additionalProperties": false`). That is
  incompatible with an optional parameter like `timezone`. To use strict mode
  you would have to make `timezone` required with a nullable type
  (`"type": ["string", "null"]`). We keep it simple and non-strict for now.
- `zoneinfo` is stdlib (Python 3.9+). No external dependencies.

---

### 3b. The Dispatcher

The dispatcher is a thin router: it receives a tool name and a raw `arguments` string, parses the JSON, calls the right function, and always returns a string. It **never raises** into the agent loop — errors become string results so the model can self-correct.

> 🟢 **`try:` / `except:` in one minute.** `try:` means "attempt the code below."
> `except SomeError as exc:` means "if that code crashes with this kind of error,
> jump here instead of stopping the whole program, and call the error object `exc`."
> So the dispatcher *tries* to parse the JSON and run the tool, and if anything goes
> wrong it *catches* the error and returns it as a plain string. That string travels
> back to the model, which can then fix its mistake — much better than crashing.

```python
import json

def dispatch(name: str, arguments: str) -> str:
    """
    Route a tool call to its implementation.
    Always returns a string; exceptions are caught and returned as error strings.
    """
    try:
        args = json.loads(arguments)          # arguments is always a JSON string
    except json.JSONDecodeError as exc:
        return f"ERROR: could not parse arguments JSON — {exc}"

    try:
        if name == "get_current_time":
            return get_current_time(**args)
        else:
            return f"ERROR: unknown tool '{name}'"
    except Exception as exc:                  # never let tool errors crash the loop
        return f"ERROR: {type(exc).__name__}: {exc}"
```

> **Why catch everything?** A tool raising an unhandled exception would kill the loop and produce no answer. Returning the error string gives the model a chance to retry with corrected arguments or explain the problem to the user.

---

### 3c. The Agent Loop

> 🟢 **One new line to decode below:**
> `tool_calls = [item for item in resp.output if item.type == "function_call"]`.
> That's a **list comprehension** — a compact way to build a list. It means exactly
> the same as this plain loop you already know how to write:
> ```python
> tool_calls = []
> for item in resp.output:
>     if item.type == "function_call":
>         tool_calls.append(item)
> ```
> Both produce a list of just the tool-call items. Use whichever you find clearer —
> they behave identically.

```python
from openai import OpenAI

MODEL = "gpt-5"
client = OpenAI()                             # reads OPENAI_API_KEY from environment

SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Use the get_current_time tool whenever the user asks about the current time or date. "
    "Always confirm the timezone with the user if it matters."
)

MAX_ITERATIONS = 25                           # safety cap — explained below


def run_agent(user_message: str) -> None:
    """
    Run a single-turn agent conversation for user_message.
    Prints the final assistant response to stdout.
    """
    # ── Seed the transcript ──────────────────────────────────────────────────
    input_items: list = [{"role": "user", "content": user_message}]

    for iteration in range(MAX_ITERATIONS):
        # ── Step 1: Ask ──────────────────────────────────────────────────────
        resp = client.responses.create(
            model=MODEL,
            instructions=SYSTEM_PROMPT,
            input=input_items,
            tools=[GET_CURRENT_TIME_SCHEMA],
        )

        # ── Step 2a: Carry the model's output forward FIRST ──────────────────
        # This is the most common mistake: appending tool outputs before
        # resp.output causes the model to see orphaned function_call_output
        # items with no preceding function_call — the API will reject it.
        input_items += resp.output

        # ── Step 2b: Collect any tool calls ──────────────────────────────────
        tool_calls = [item for item in resp.output if item.type == "function_call"]

        if not tool_calls:
            # ── Step 3: No more tool calls — we have the final answer ─────────
            print(f"\nAssistant: {resp.output_text}\n")
            print(
                f"[tokens used: {resp.usage.input_tokens} in / "
                f"{resp.usage.output_tokens} out / "
                f"{resp.usage.total_tokens} total]"
            )
            return

        # ── Step 2c: Execute each tool call and append results ───────────────
        for tc in tool_calls:
            result = dispatch(tc.name, tc.arguments)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": tc.call_id,    # MUST echo exactly — do not use tc.id
                    "output": result,          # must be a string
                }
            )
        # Loop continues — send grown transcript back to the model

    # Fell through the iteration cap
    print(f"[Agent stopped: reached {MAX_ITERATIONS}-iteration safety cap]")
```

**Why `MAX_ITERATIONS`?**
Without a cap, a model stuck in a reasoning loop or a buggy tool that always returns errors could spin indefinitely, burning API quota and dollars. 25 is a conservative default for single-turn tasks; multi-step workflows may need more. Log a clear message when the cap fires so you can detect and debug runaway loops.

**Why `tc.call_id` and not `tc.id`?**
`function_call` items have two identifiers: `id` (the item's own identity in the response output list) and `call_id` (the correlation key the API uses to match a `function_call_output` to its originating call). The handshake requires `call_id`.

---

### 3d. The REPL

```python
def main() -> None:
    print("Agent ready. Type your message (Ctrl-C or empty line to quit).\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not user_input:
            break
        run_agent(user_input)


if __name__ == "__main__":
    main()
```

> 🟢 **`if __name__ == "__main__":`** is boilerplate that means "only run `main()`
> when this file is executed directly (e.g. `python bare_harness.py`), not when it's
> imported by another file." You can treat it as a fixed phrase that goes at the
> bottom of a runnable script.

---

## 4. The Complete File

```python
#!/usr/bin/env python3
"""
bare_harness.py — Phase 1: minimal agent loop with one tool.

Requires:
    pip install openai
    export OPENAI_API_KEY=sk-...
"""

import datetime
import json
import zoneinfo
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────

MODEL = "gpt-5"
MAX_ITERATIONS = 25

SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Use the get_current_time tool whenever the user asks about the current time or date. "
    "Always confirm the timezone with the user if it matters."
)

client = OpenAI()  # reads OPENAI_API_KEY from environment

# ── Tool schema ───────────────────────────────────────────────────────────────

GET_CURRENT_TIME_SCHEMA = {
    "type": "function",
    "name": "get_current_time",
    "description": (
        "Return the current date and time. "
        "Pass an IANA timezone name (e.g. 'America/New_York') to localise; "
        "omit or pass an empty string for UTC."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone name, e.g. 'Europe/London'. Empty → UTC.",
            }
        },
        "required": [],
    },
    # No "strict": True — see note above; strict mode requires every property
    # to be in "required", which is incompatible with an optional timezone.
}

# ── Tool implementation ───────────────────────────────────────────────────────

def get_current_time(timezone: str = "") -> str:
    """Return the current time as an ISO-8601 string in the requested zone."""
    if timezone:
        tz = zoneinfo.ZoneInfo(timezone)
    else:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz=tz)
    return now.isoformat(timespec="seconds")

# ── Dispatcher ────────────────────────────────────────────────────────────────

def dispatch(name: str, arguments: str) -> str:
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

# ── Agent loop ────────────────────────────────────────────────────────────────

def run_agent(user_message: str) -> None:
    """Run one conversation turn to completion, printing the final answer."""
    input_items: list = [{"role": "user", "content": user_message}]

    for iteration in range(MAX_ITERATIONS):
        resp = client.responses.create(
            model=MODEL,
            instructions=SYSTEM_PROMPT,
            input=input_items,
            tools=[GET_CURRENT_TIME_SCHEMA],
        )

        # Append model output BEFORE tool outputs (order matters to the API)
        input_items += resp.output

        tool_calls = [item for item in resp.output if item.type == "function_call"]

        if not tool_calls:
            print(f"\nAssistant: {resp.output_text}\n")
            print(
                f"[tokens used: {resp.usage.input_tokens} in / "
                f"{resp.usage.output_tokens} out / "
                f"{resp.usage.total_tokens} total]"
            )
            return

        for tc in tool_calls:
            result = dispatch(tc.name, tc.arguments)
            print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result,
                }
            )

    print(f"[Agent stopped: reached {MAX_ITERATIONS}-iteration safety cap]")

# ── REPL ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Agent ready. Type your message (Ctrl-C or empty line to quit).\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not user_input:
            break
        run_agent(user_input)


if __name__ == "__main__":
    main()
```

---

## 5. Run It

Install and run:

```text
pip install openai
export OPENAI_API_KEY=sk-...
python bare_harness.py
```

Example session:

```text
Agent ready. Type your message (Ctrl-C or empty line to quit).

You: What time is it in Tokyo right now?
  [tool] get_current_time({"timezone": "Asia/Tokyo"}) → 2026-06-06T22:47:13+09:00

Assistant: The current time in Tokyo is 10:47 PM on Saturday, June 6, 2026 (JST — Japan Standard Time).

[tokens used: 312 in / 28 out / 340 total]

You: What about in UTC?
  [tool] get_current_time({}) → 2026-06-06T13:47:31+00:00

Assistant: In UTC it is currently 1:47 PM on Saturday, June 6, 2026.

[tokens used: 389 in / 22 out / 411 total]

You:
Bye.
```

The `[tool]` lines are printed by the harness so you can watch the call/result cycle.
They are not part of the model's response.

---

## 6. What's Missing

This harness is intentionally thin. The table below maps every gap to the phase that closes it.

| Gap | Why it matters | Closed in |
|-----|---------------|-----------|
| Single hardcoded tool; no registry | Adding a second tool requires editing the loop | Phase 2 — Tool registry & multi-tool dispatch |
| No argument schema validation | Bad model output passes silently to the function | Phase 2 |
| No streaming | First token appears only after the full response | Phase 3 — Conversation & streaming |
| Single-turn only (`run_agent` does not persist state) | Every call starts fresh; no multi-turn memory | Phase 3 |
| No real-world tools | `get_current_time` is illustrative; real agents need file I/O, shell, search, etc. | Phase 4 — Real-world tools |
| No tool permissions / confirmation | Any tool runs unconditionally | Phase 5 — Permissions & safety |
| Context limits not managed | Long conversations will eventually exceed the token window | Phase 6 — Context management |
| No sub-agents or parallelism | One model call at a time; no fan-out | Phase 7 — Sub-agents & orchestration |

---

## 7. Common Pitfalls

> **Callout: Mistakes that will cost you hours**

**Forgetting to echo `call_id` exactly.**
The API matches each `function_call_output` to its originating `function_call` via `call_id`.
If you echo `tc.id` (the item's output-list identity) instead of `tc.call_id`, or
if you mutate or truncate the value, the API will reject the request with a validation error.
Copy the field verbatim: `"call_id": tc.call_id`.

**Appending `function_call_output` items before `resp.output`.**
The API requires that the `function_call` item precede its corresponding `function_call_output`
in `input_items`. If you append the tool results first, the API sees an output item with no
preceding call — a protocol violation that raises an error. Always do
`input_items += resp.output` before appending any `function_call_output` items.

**Treating `tc.arguments` as a dict.**
`arguments` is a **JSON string**, not a parsed dict. Always call `json.loads(tc.arguments)`
before passing to the function. Skipping this causes a `TypeError` deep inside your tool
function that is hard to trace back to the loop.

**No iteration cap.**
If a tool always returns an error, the model will keep calling it. Without `MAX_ITERATIONS`
your process runs (and bills) until you kill it manually. Always set a cap and log clearly
when it fires.

**Returning non-string tool output.**
The `output` field of `function_call_output` must be a string. If your tool returns a dict
or list, call `json.dumps()` on it before appending. Passing a non-string object will raise
a serialisation error at the API boundary.

---

*Next: Phase 2 — Tool Registry and Multi-Tool Dispatch*
