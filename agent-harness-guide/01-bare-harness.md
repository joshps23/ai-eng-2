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

We'll build it as a **ladder of three complete versions** — each one a full program you can paste into a file and run, and each one *the same harness, reorganized*:

- **Version 1 — line-by-line.** The entire agent as a straight-line script: no `def`, no classes. Just statements, a `while True`, and some `if`s. You can read it top to bottom like a recipe.
- **Version 2 — functions.** The same harness with its parts given names: `get_current_time`, `dispatch`, `run_agent`, `main`. Along the way we add error handling, a REPL, and a safety cap — one idea per step.
- **Version 3 — classes.** The same harness with its *state* (client, tools, transcript) grouped into one small `Agent` class — a preview of the shape the final package uses.

Nothing conceptually new happens after Version 1. Versions 2 and 3 are reorganizations — the loop you see in Version 1 is the loop you ship.

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

## 3. Version 1 — Line-by-Line: No Functions, No Classes

**Why start here?** Before any helpers, classes, or abstractions, you need to see the loop working with your own eyes — and to be sure there is no magic hiding inside a function you haven't read yet. So Version 1 has **zero `def` statements**. The tool's logic (computing the current time) sits *directly inside* the dispatch branch, right where the tool's name matches. Every line executes top to bottom; the only control flow is one `while True` and a couple of `if`s.

Create a new file called `bare_harness.py` and paste this in — the whole thing:

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
```

> 🟢 **Two small bits of new syntax in Version 1.** (1) `args.get("timezone", "")` reads the `"timezone"` key out of the dict, falling back to `""` if the model omitted it — that's why an empty string means UTC. (2) `[item for item in resp.output if item.type == "function_call"]` is a **list comprehension** — a compact way to filter a list. It's identical to writing a `for` loop with an `if` inside that calls `.append()`. See [`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md) for the full list.

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

> 🟢 **No API key?** This script (like every ▶ checkpoint in this phase) calls the real
> API, so without a key it stops at `openai.OpenAIError: Missing credentials`, raised
> on the `client = OpenAI()` line before any request is made. That's expected — see
> the **"No API key?" box in [Phase 0](./00-foundations.md)** for the offline
> alternatives: read the expected output and trace the code against it, run the
> offline test suite (`python -m pytest -q` from `code/`), or peek at the `FakeClient`
> in `code/agent_harness/testing.py`.

That's the whole loop. There is genuinely nothing else: ask the model, run any tools it asked for, append the results, ask again. Everything that follows in this phase is the *same* program, reorganized to be more robust and more pleasant to grow.

---

## 4. Version 2 — Functions: The Same Harness, Named in Pieces

**Why reorganize?** Version 1 works, but it has three growing pains:

- The tool's logic is buried inside the loop — adding a second tool means stuffing more code into an already-busy `for` body.
- Any error (bad JSON, an invalid timezone name) **crashes the whole program** instead of telling the model what went wrong.
- The question is hardcoded; you have to edit the file to ask something else.

Version 2 fixes all three by giving the harness's parts **names**: a tool function, a `dispatch` function, a `run_agent` function, and a `main` REPL. We'll extract them one at a time, running after each step.

**What changed from V1 → V2**

- The inline time computation becomes a named function, `get_current_time(timezone="")`.
- The `if tc.name == ...` block becomes a `dispatch(name, arguments)` function wrapped in `try`/`except`, so tool errors become strings instead of crashes.
- The hardcoded question and bare `while True` become `run_agent(user_message)`, and a `main()` REPL reads questions from the terminal.
- `while True` becomes `for iteration in range(MAX_ITERATIONS)` — a safety cap against infinite loops.
- The loop body itself is **unchanged**: same `responses.create` call, same `input_items += resp.output`, same `function_call_output` handshake.

### Step 1 — Give the tool logic a name

**Why now?** The time-computing code currently lives inside the dispatch branch. Pulling it out into a function does two things: the loop body gets shorter, and the tool becomes *callable on its own* — you can test it without the model in the picture.

Add this function near the top of the file (after the imports), and shrink the dispatch branch to a single call:

```python
def get_current_time(timezone=""):
    tz = zoneinfo.ZoneInfo(timezone) if timezone else datetime.timezone.utc
    return datetime.datetime.now(tz=tz).isoformat(timespec="seconds")
```

```python
    for tc in tool_calls:
        args = json.loads(tc.arguments)
        if tc.name == "get_current_time":
            result = get_current_time(**args)
        else:
            result = f"ERROR: unknown tool '{tc.name}'"
        print(f"  [tool] {tc.name}({tc.arguments}) → {result}")
        input_items.append({
            "type": "function_call_output",
            "call_id": tc.call_id,
            "output": result,
        })
```

> 🟢 **The `**args` in `get_current_time(**args)`** "spreads" a dict into named arguments, so `get_current_time(**{"timezone": "Asia/Tokyo"})` is exactly the same as `get_current_time(timezone="Asia/Tokyo")`. This is why the model's JSON arguments can drive a normal Python function directly. See [`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md) for more.

**▶ Run it now** — the output is identical to Version 1. Bonus check: open a Python shell, paste the three-line function in, and call `get_current_time("Europe/London")` directly. The tool now exists independently of the agent. (Paste rather than `import bare_harness`: importing the file also executes its module-level `client = OpenAI()` line, which needs your API key set — see the note in §5.)

### Step 2 — Extract a `dispatch` helper

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

### Step 3 — Wrap the loop in a function and add a REPL

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

### Step 4 — Add a `MAX_ITERATIONS` cap

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

## 5. The Complete File (Version 2, Polished)

At this point you already have a working harness. The file below is the **same thing, tidied up**: imports grouped at the top, a `SYSTEM_PROMPT` added, `KeyboardInterrupt` handled gracefully, and `if __name__ == "__main__":` added so that importing the file doesn't start the REPL. (One honest caveat: `client = OpenAI()` still runs at module level, so importing this file *does* still require `OPENAI_API_KEY` to be set — `OpenAI()` raises `openai.OpenAIError: Missing credentials` without it. Version 3 below avoids this by building the client inside `main()`; the same trick works here if you ever need a key-free import.) Nothing here is conceptually new. This is the polished end-state of Version 2 — keep it as your reference copy.

> 🟢 **First sighting of type hints.** The polished file annotates functions like
> `def get_current_time(timezone: str = "") -> str:` — those `: str` / `-> str` notes are
> **type hints**. They change nothing at runtime; you can read straight past them. See the
> **type hints** row in [`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md).

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

## 6. Version 3 — Classes: A Minimal `Agent` (Preview)

**Why now?** Look at Version 2's moving parts: the `client`, the tool schemas, and the transcript all float around as globals and locals, and `run_agent` has to know about all of them. That's fine for one agent in one file. But the moment you want *two* agents (Phase 7 builds sub-agents!), or want to keep a transcript alive between turns, you need a way to bundle **state** together. That's exactly what a class is for — and nothing more. Version 3 is **the same harness, organized**: same loop, same dispatch, same handshake, with the state grouped into one small `Agent` object.

**What changed from V2 → V3**

- The three pieces of state — `client`, the tool schemas, and `input_items` — move into `self.client`, `self.tools`, and `self.input_items` on an `Agent` object, created once in `__init__`.
- `dispatch` and the loop become **methods** (`agent.dispatch(...)`, `agent.run(...)`) — same bodies, now reading state from `self` instead of globals.
- Because the transcript now lives on the object, it **survives between calls to `run`** — this version gets multi-turn memory for free (a deliberate preview of Phase 3).
- `main()` shrinks to: build one `Agent`, feed it user input in a loop.
- The loop body, the `function_call_output` handshake, `MAX_ITERATIONS`, and the error-string discipline are all **byte-for-byte the same ideas** as Version 2.

> 🟢 **Classes in one minute.** A `class` is a bundle of data plus the functions that
> operate on that data. `__init__` runs when you create an instance
> (`agent = Agent(...)`) and stashes values on `self`. Every method takes `self` as
> its first parameter, which is how it reaches that stashed data — `self.input_items`
> instead of a global `input_items`. That's the whole trick: nothing in the loop's
> *logic* changes, only where its state lives.

Here is the complete Version 3 — paste it into `bare_harness_v3.py`:

```python
#!/usr/bin/env python3
"""
bare_harness_v3.py — Phase 1, Version 3: the same harness, as a class.

Requires:
    pip install openai
    export OPENAI_API_KEY=sk-...
"""

import datetime
import json
import zoneinfo
from openai import OpenAI

MODEL = "gpt-4o"
MAX_ITERATIONS = 25

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


def get_current_time(timezone: str = "") -> str:
    """Return the current time as an ISO-8601 string in the requested zone."""
    tz = zoneinfo.ZoneInfo(timezone) if timezone else datetime.timezone.utc
    return datetime.datetime.now(tz=tz).isoformat(timespec="seconds")


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


def main():
    agent = Agent(OpenAI(), [GET_CURRENT_TIME_SCHEMA])
    print("Agent ready. Type your message (Ctrl-C or empty line to quit).\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not user_input:
            break
        agent.run(user_input)


if __name__ == "__main__":
    main()
```

**▶ Run it now**

```text
python bare_harness_v3.py
```

Ask `What time is it in Tokyo?`, then follow up with `And in London?` — and notice something new: the model understands `"And in London?"` because the transcript persisted on `agent.input_items` between turns. Version 2 forgot everything after each answer; Version 3 remembers, purely because of where the state lives. (Phase 3 is all about this.)

This `Agent` shape — a constructor that takes a client and tools, plus a `run` method around the same loop — is exactly the skeleton the final package uses in [`code/agent_harness/agent.py`](./code/agent_harness/agent.py). The production version adds a `Conversation` object, a `ToolRegistry`, permissions, and hooks, but when you read it later you'll recognize this same ~40-line core. No decorators, no threads, no inheritance — just the same idea, organized.

---

## 7. Example Session

```text
Agent ready. Type your message (Ctrl-C or empty line to quit).

You: What time is it in Tokyo right now?
  [tool] get_current_time({"timezone": "Asia/Tokyo"}) → 2026-06-06T22:47:13+09:00
Assistant: The current time in Tokyo is 10:47 PM on Saturday, June 6, 2026 (JST).
[tokens used: 312 in / 45 out / 357 total]

You: What is 2 + 2?

Assistant: 2 + 2 = 4.
[tokens used: 298 in / 12 out / 310 total]

You:
Bye.
```

The second question does not call `get_current_time` at all — the model answers directly from its own knowledge. Notice that `tool_calls` was empty, so the loop broke immediately after the first `responses.create` call.

---

## 8. Common Pitfalls

| Pitfall | What happens | How to avoid |
|---------|--------------|---------------|
| **Appending tool outputs *before* `resp.output`** | The API rejects the request with a validation error: it sees `function_call_output` items with no preceding `function_call`. | Always do `input_items += resp.output` *first*, then append your tool outputs. |
| **Using `tc.id` instead of `tc.call_id`** | The API cannot correlate the output to the call; you get a validation error on the next `create()`. | Use `tc.call_id` verbatim. If in doubt, print both and compare — they look similar but are different strings. |
| **Returning a non-string from a tool** | The `output` field of `function_call_output` must be a string. Returning an `int`, `dict`, or `None` causes a type error. | Always `return str(...)` or `return json.dumps(...)` from your tool functions. |
| **No `MAX_ITERATIONS` cap** | A buggy tool that always errors will loop forever, consuming API quota until you kill the process. | Replace `while True` with `for _ in range(MAX_ITERATIONS)` and print a warning when the cap fires. |
| **Raising an exception from a tool** | Without `try/except`, an unhandled exception kills the whole program with no answer for the user. | Wrap all tool logic in `try/except Exception` and return the error as a string; let the model decide what to do with it. |
| **Forgetting to export `OPENAI_API_KEY`** | `openai.OpenAIError: Missing credentials` raised at the `client = OpenAI()` line — *before* any request is sent, so the traceback points at the client construction, not at `responses.create`. | Run `export OPENAI_API_KEY=sk-...` in the same terminal session before running the script. |
| **Key set but wrong/revoked** | `openai.AuthenticationError` (HTTP 401) on the first `responses.create` call — construction succeeds, the API rejects the request. | Re-check `echo $OPENAI_API_KEY`; regenerate the key in your OpenAI dashboard if unsure. |
| **Using Python < 3.9** | `zoneinfo` is not available; you get `ModuleNotFoundError`. | Run `python --version`. If you see < 3.9, install `backports.zoneinfo` and import from there, or upgrade Python. |

---

## Key takeaways

- The agent loop is **three lines of logic**: call `responses.create`, check for tool calls, execute them and append results — then repeat. Everything else is convenience.
- The transcript is **append-only**: always carry `resp.output` forward before appending tool outputs. The order matters; the API enforces it.
- The `function_call_output` handshake needs exactly two fields beyond `type`: the **same `call_id`** from the call, and a **string** `output`. Always return one output per call, even on error.
- A `dispatch` helper that **catches all exceptions** and returns error strings keeps the loop alive — the model can read the error and try again or explain the failure.
- A **`MAX_ITERATIONS` cap** is not optional for production code. Always include one.
- All three versions in this phase are **the same harness**. V1 → V2 names the pieces and adds robustness; V2 → V3 groups the state into an `Agent` object. The loop itself never changed — and the `Agent` class is the shape the final package builds on.

## Check yourself

Before moving on, can you answer these?

1. What two things must you append to `input_items` each iteration, and which must come first?
2. A tool raises a `ValueError`. What should your `dispatch` function return, and why?
3. Why is `tc.call_id` the right field to use — not `tc.id`?
4. What happens if you remove `MAX_ITERATIONS` and a tool always returns an error?
5. Version 3 suddenly handles follow-up questions like "And in London?" even though we never touched the loop logic. What single change made that possible?

<details><summary>Answers</summary>

1. **`resp.output` first**, then your `function_call_output` items. The API requires that every `function_call_output` follow its matching `function_call` in the input list.
2. Return a **string** like `f"ERROR: ValueError: {exc}"`. Raising lets the exception kill the loop; returning the string gives the model a chance to self-correct and keeps every `call_id` matched.
3. `call_id` is the **correlation key** the API uses to match outputs to calls. `id` is the item's own identity in the response list — a different field that happens to look similar.
4. The model keeps requesting the tool, the loop never breaks, and you burn API quota indefinitely until you manually kill the process.
5. The transcript moved from a **local variable** inside `run_agent` (recreated empty on every call) to **instance state** (`self.input_items`) that persists for the lifetime of the `Agent` object. Same loop, different home for the state.
</details>

---

## Exercises

See [`EXERCISES.md` — Phase 1](./EXERCISES.md) for hands-on practice:

- **1.1 (warm-up):** Add a second tool (e.g. `get_weather(city)` returning a fixed string). Ask a question that should use it, and one that shouldn't. Did the model choose correctly?
- **1.2 (stretch):** Make a tool that *always* returns an error string. Watch the loop retry — then confirm your `MAX_ITERATIONS` cap stops it.

---

Proceed to **[Phase 2 — The tool system](./02-tool-system.md)**, where you'll replace the `if/elif` dispatch with a registry and auto-generate schemas from type hints.
