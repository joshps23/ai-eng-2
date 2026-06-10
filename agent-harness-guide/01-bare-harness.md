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

We'll build it **one rung at a time**. Each step adds a single new idea, and each step ends with something you can run immediately.

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

### Step 0 — The absolute minimal loop (run this first)

**Why now?** Before any helpers, classes, or abstractions, you need to see the loop working with your own eyes. This is the entire agent in its rawest form: one tool defined inline, `json.loads` for the arguments, a plain `if` to dispatch, and a `while True` that stops when there are no more tool calls.

Create a new file called `bare_harness.py` and paste this in:

```python
import datetime, json, zoneinfo
from openai import OpenAI

client = OpenAI()   # reads OPENAI_API_KEY from environment

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

# ── Tool implementation (what runs locally) ───────────────────────────────────
def get_current_time(timezone=""):
    tz = zoneinfo.ZoneInfo(timezone) if timezone else datetime.timezone.utc
    return datetime.datetime.now(tz=tz).isoformat(timespec="seconds")

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
            result = get_current_time(**args)
        else:
            result = f"ERROR: unknown tool '{tc.name}'"
        print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
        input_items.append({
            "type": "function_call_output",
            "call_id": tc.call_id,   # must echo call_id exactly — NOT tc.id
            "output": result,        # must be a string
        })
```

**▶ Run it now**

```text
pip install openai
export OPENAI_API_KEY=sk-...
python bare_harness.py
```

You should see something like:

```text
  [tool] get_current_time({"timezone": "Asia/Tokyo"}) → 2026-06-06T22:47:13+09:00
Assistant: The current time in Tokyo is 10:47 PM on Saturday, June 6, 2026 (JST).
```

The `[tool]` line is printed by your harness — it's not part of the model's response. You can watch the call/result cycle directly.

> 🟢 **Two small bits of new syntax in Step 0.** (1) The `**args` in `get_current_time(**args)` "spreads" a dict into named arguments, so `get_current_time(**{"timezone": "Asia/Tokyo"})` is exactly the same as `get_current_time(timezone="Asia/Tokyo")`. (2) `[item for item in resp.output if item.type == "function_call"]` is a **list comprehension** — a compact way to filter a list. It's identical to writing a `for` loop with an `if` inside that calls `.append()`. See [`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md) for the full list.

That's the whole loop. Everything that follows is just making it more robust.

---

### Step 1 — Extract a `dispatch` helper

**Why now?** The inline `if tc.name == ...` works fine for one tool, but crashes the whole program if `json.loads` fails or the tool raises an exception. Wrapping that block in a function with `try`/`except` means errors become string messages the model can read and self-correct — the loop keeps running.

> 🟢 **`try:` / `except:` in one minute.** `try:` means "attempt the code below."
> `except SomeError as exc:` means "if that code crashes with this kind of error,
> jump here instead of stopping the whole program, and call the error object `exc`."
> So the dispatcher *tries* to parse the JSON and run the tool, and if anything goes
> wrong it *catches* the error and returns it as a plain string. That string travels
> back to the model, which can then fix its mistake — much better than crashing.

Replace the inline `if tc.name == ...` block with this function (add it just before the loop):

```python
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
```

And update the loop body to call it:

```python
    for tc in tool_calls:
        result = dispatch(tc.name, tc.arguments)
        print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
        input_items.append({
            "type": "function_call_output",
            "call_id": tc.call_id,
            "output": result,
        })
```

**▶ Run it now** — the output is identical, but now try passing a bad timezone name (e.g., `"Not/ATimezone"`). Instead of crashing, you'll see an `ERROR:` string returned and the model will politely tell the user it couldn't look that up.

> **Why catch everything?** A tool raising an unhandled exception would kill the loop and produce no answer. Returning the error string gives the model a chance to retry with corrected arguments or explain the problem to the user.

---

### Step 2 — Wrap the loop in a function and add a REPL

**Why now?** Right now the question is hardcoded. To handle any user input you need: (a) a function that runs one conversation to completion, and (b) an outer `while True` that reads from the terminal. These are two separate ideas, so we add them together in one small step.

Replace the hardcoded `input_items = [...]` and the bare `while True` loop with this:

```python
def run_agent(user_message):
    """Run one conversation turn to completion, printing the final answer."""
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
            return

        for tc in tool_calls:
            result = dispatch(tc.name, tc.arguments)
            print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })


def main():
    print("Agent ready. Type your message (empty line to quit).\n")
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            break
        run_agent(user_input)


main()
```

**▶ Run it now**

```text
python bare_harness.py
```

You'll see the familiar prompt. Try two questions back-to-back — each one starts a fresh conversation (single-turn for now; multi-turn memory comes in Phase 3).

> 🟢 **`if __name__ == "__main__":`** is boilerplate that means "only run `main()`
> when this file is executed directly (e.g. `python bare_harness.py`), not when it's
> imported by another file." We'll add it in the final tidy-up below. For now,
> calling `main()` directly at the bottom of the file works fine.

---

### Step 3 — Add a `MAX_ITERATIONS` cap

**Why now?** Without a cap, a tool that always returns an error will make the model keep calling it — looping forever and billing you until you kill the process. A simple `for` loop instead of `while True` fixes this in one line.

Change the `while True:` inside `run_agent` to:

```python
MAX_ITERATIONS = 25

def run_agent(user_message):
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
            return

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
```

**▶ Run it now** — normal use is unchanged. The cap only fires if the model gets stuck in a loop.

**Why `MAX_ITERATIONS`?**
Without a cap, a model stuck in a reasoning loop or a buggy tool that always returns errors could spin indefinitely, burning API quota and dollars. 25 is a conservative default for single-turn tasks; multi-step workflows may need more. Log a clear message when the cap fires so you can detect and debug runaway loops.

---

## 4. The Complete File

At this point you already have a working harness. The file below is the **same thing, tidied up**: imports grouped at the top, a `SYSTEM_PROMPT` added, `KeyboardInterrupt` handled gracefully, and `if __name__ == "__main__":` added so the file can be imported without running. Nothing here is conceptually new.

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

MODEL = "gpt-4o"
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
    # No "strict": True — strict mode requires every property to be in "required",
    # which is incompatible with an optional parameter like timezone.
}

# ── Tool implementation ───────────────────────────────────────────────────────

def get_current_time(timezone: str = "") -> str:
    """Return the current time as an ISO-8601 string in the requested zone."""
    if timezone:
        tz = zoneinfo.ZoneInfo(timezone)          # raises ZoneInfoNotFoundError on bad name
    else:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz=tz)
    return now.isoformat(timespec="seconds")

# ── Dispatcher ────────────────────────────────────────────────────────────────

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

# ── Agent loop ────────────────────────────────────────────────────────────────

def run_agent(user_message: str) -> None:
    """Run one conversation turn to completion, printing the final answer."""
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
            print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
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

Key points about the schema you may have noticed:

- The schema is **flat** — `type`, `name`, `description`, `parameters` are all top-level keys. There is no nested `"function"` wrapper.
- `required` is an empty list because `timezone` is optional; the model may omit it entirely.
- We do **not** set `"strict": True` here. Strict mode makes the API guarantee
  the arguments match the schema exactly, but it requires *every* property to be
  listed in `required` (and `"additionalProperties": false`). That is
  incompatible with an optional parameter like `timezone`. To use strict mode
  you would have to make `timezone` required with a nullable type
  (`"type": ["string", "null"]`). We keep it simple and non-strict for now.
- `zoneinfo` is stdlib (Python 3.9+). No external dependencies.

**Why `tc.call_id` and not `tc.id`?**
`function_call` items have two identifiers: `id` (the item's own identity in the response output list) and `call_id` (the correlation key the API uses to match a `function_call_output` to its originating call). The handshake requires `call_id`.

---

## 5. Example Session

```text
Agent ready. Type your message (Ctrl-C or empty line to quit).

You: What time is it in Tokyo right now?
  [tool] get_current_time({"timezone": "Asia/Tokyo"}) → 2026-06-06T22:47:13+09:00