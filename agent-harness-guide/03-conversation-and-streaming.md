[← Phase 2: A Real Tool System](./02-tool-system.md) · [Guide index](./README.md) · [Phase 4: Real-World Tools →](./04-real-tools.md)

# Phase 3 — Conversation State & Streaming

This phase addresses two tightly related concerns that every production agent harness must
solve: owning and persisting the transcript correctly, and streaming model output to give
users a responsive, observable interface.

By the end you will have:

- A `Conversation` class that serializes to/from JSON and correctly handles all item types
- A `stream_turn()` function that renders text deltas live and announces tool calls as they
  form
- An updated `run_agent_streaming()` loop that combines the Phase 2 tool registry with the
  above two pieces

As in the other phases, you will build the **same harness four times**, each version a
complete program you can run, each one rung more organized than the last:

- **Version 1 — line-by-line.** A multi-turn chat where the transcript is a plain list you
  append to inline. No `def`, no classes — just statements and a `while` loop.
- **Version 2 — functions.** The same chat, with the repeated moves named as plain
  functions (`add_user`, `extend_items`, `run_turn`, `save`/`load`).
- **Version 3 — classes.** The same chat, with the transcript owned by a `Conversation`
  class — the shape the final package uses.
- **Version 4 — streaming.** The same harness, with one new *mechanism*: the model's
  answer arrives as a stream of events instead of one finished response.

Nothing the harness *does* changes between versions; only how the code is organized (V1→V3)
and how the answer is displayed (V4). If a version ever feels confusing, drop back one rung
— the previous version is always still correct.

---

> ## 🟢 Beginner track: two things to know before you start
>
> **1. The `Conversation` class is just the `input_items` list you already used —
> with a few helper functions.** In Phase 1 you kept the whole conversation in a plain
> list and appended to it. This phase wraps that list in a `class` so it can also
> save/load itself. You can get every benefit using only a **dict** and **functions**:
>
> ```python
> import json
>
> def new_conversation(instructions=""):
>     # The conversation is just a dict holding a list of items.
>     return {"instructions": instructions, "items": []}
>
> def add_user(conv, text):
>     conv["items"].append({"role": "user", "content": text})
>
> def extend_items(conv, output_items):
>     # Turn each SDK object into a plain dict, then store it.
>     for item in output_items:
>         if hasattr(item, "model_dump"):
>             item = item.model_dump()   # SDK object -> plain dict
>         conv["items"].append(dict(item))
>
> def add_tool_result(conv, call_id, output):
>     conv["items"].append({
>         "type": "function_call_output",
>         "call_id": call_id,
>         "output": output,
>     })
>
> def to_input(conv):
>     return list(conv["items"])        # the list you pass to input=
>
> def save(conv, path):
>     with open(path, "w") as f:
>         json.dump(conv, f, indent=2)  # it's just a dict -> write it as JSON
>
> def load(path):
>     with open(path) as f:
>         return json.load(f)           # read the dict back
> ```
>
> Use these wherever the phase says `conv.add_user(...)`, `conv.extend(...)`,
> `conv.to_input()`, etc. — read the dot-method `conv.add_user(text)` as the function
> call `add_user(conv, text)`. (`hasattr(item, "model_dump")` just asks "does this
> object have a `model_dump` method?" — `True` for SDK objects, `False` for plain
> dicts.)
>
> **2. Streaming is optional. You can skip the entire streaming half of this phase.**
> Streaming only changes *how the answer is displayed* — character-by-character as the
> model types, instead of all at once. It does **not** change the loop or the results.
> The plain `client.responses.create(...)` call you already know (without
> `stream=True`) works perfectly; just read `resp.output_text` for the final text and
> loop over `resp.output` for tool calls, exactly as in Phases 1–2. Come back to the
> streaming code (`with ... stream=True`, the event types, the ANSI colors) only when
> you specifically want a live-typing UI.

---

**Contents:**

- [Two Orthogonal Concerns](#two-orthogonal-concerns)
- [Version 1 — Line-by-Line: the Transcript Is Just a List](#version-1--line-by-line-the-transcript-is-just-a-list)
- [Version 2 — Functions: Name the Moves](#version-2--functions-name-the-moves)
- [Interlude — Transcript Management Deep-Dive](#interlude--transcript-management-deep-dive)
- [Version 3 — Classes: the `Conversation` Object](#version-3--classes-the-conversation-object)
- [Version 4 — Streaming (optional)](#version-4--streaming-the-same-harness-live-optional)
- [Pitfalls](#pitfalls)

---

## Two Orthogonal Concerns

**Transcript management** determines what you send in `input` on each call.  You have two
options:

1. **Own the list** — append every `resp.output` item to your local `input_items` list and
   send the whole list on the next call.
2. **Delegate to the server** — pass `previous_response_id=resp.id` and send only the new
   items; the server stitches the history together.

**Streaming** is independent of which state strategy you pick.  You can stream with either
approach.

---

## Version 1 — Line-by-Line: the Transcript Is Just a List

The first rung is the whole idea of this phase with **no `def` and no classes** — just
statements, a list, and (in Step 1.2) a `while` loop. If you understand Version 1 you
already understand the whole phase; every later version is this code, reorganized.

### Step 1.1 — Two turns, fully inline

Before introducing any classes or helpers, let's see the core idea in the most direct form:
a plain Python list that grows with every turn and gets passed back to the model so it
"remembers" the conversation.

**Why this first?** Everything in this phase is just an organized version of what you are
about to write. If you understand this loop you already understand the whole phase.

```python
import json
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()

# The entire conversation is a plain list of dicts.
# We will append to it and pass it as input= on every call.
input_items = []

# --- Turn 1: ask the model something ---
input_items.append({"role": "user", "content": "My name is Alex. Remember that."})

resp = client.responses.create(
    model=MODEL,
    input=input_items,
)

# Append the model's output items so it "remembers" this turn.
for item in resp.output:
    input_items.append(item.model_dump())  # SDK object -> plain dict

print("Turn 1:", resp.output_text)

# --- Turn 2: ask a follow-up that requires memory ---
input_items.append({"role": "user", "content": "What is my name?"})

resp2 = client.responses.create(
    model=MODEL,
    input=input_items,
)

for item in resp2.output:
    input_items.append(item.model_dump())

print("Turn 2:", resp2.output_text)
print(f"\nTranscript now has {len(input_items)} items.")
```

### ▶ Run it now

You should see:

```text
Turn 1: Got it! I'll remember your name is Alex.
Turn 2: Your name is Alex.

Transcript now has 4 items.
```

The model answered "Alex" on turn 2 because `input_items` still contained the turn-1
exchange. That list *is* the memory.

> 🟢 **What just happened?**
> After each `responses.create()` call you called `.model_dump()` on every item in
> `resp.output` to convert it from an SDK object (a Python class instance) to a plain
> `dict`.  Plain dicts are JSON-serializable, easy to print, and accepted by the API
> as input on the next call.  You will use this pattern everywhere.

### Step 1.2 — A chat REPL: the same two-turn script, in a `while` loop

The script above hard-codes exactly two turns. A real chat keeps going until *you* decide
to stop. The fix is purely mechanical: put the per-turn statements inside a `while True:`
loop and read the user's message with `input()`. Still no `def`, still no classes — the
loop body is exactly the turn you already wrote.

**Why this matters:** this is the key teaching moment of the whole phase. `input_items` is
created **once, before the loop**, and only ever appended to **inside** the loop. That is
the entire mechanism of "memory": the list outlives each turn, so every new API call sees
everything that came before. The model itself remembers nothing — the list does.

Here is the complete Version 1 program — paste it into `chat_v1.py` and run it:

```python
# chat_v1.py — Version 1: a multi-turn chat, line by line.
# No def, no classes. The transcript is the plain list `input_items`.
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()

input_items = []   # created ONCE — this list IS the conversation's memory

print("Chat started. Type 'quit' to exit.")
while True:
    user_text = input("\nYou: ")
    if user_text.strip().lower() in ("quit", "exit"):
        break

    # 1. Remember what the user said.
    input_items.append({"role": "user", "content": user_text})

    # 2. Send the WHOLE transcript so far.
    resp = client.responses.create(
        model=MODEL,
        input=input_items,
    )

    # 3. Remember what the model said (SDK objects -> plain dicts).
    for item in resp.output:
        input_items.append(item.model_dump())

    print("Assistant:", resp.output_text)

print(f"\nGoodbye — the transcript held {len(input_items)} items.")
```

### ▶ Run it now

Tell it your name on the first turn, then ask `What is my name?` on the
second. It answers correctly — not because the model remembers, but because the turn-1
exchange is still sitting in `input_items` and gets re-sent on turn 2:

```text
Chat started. Type 'quit' to exit.

You: My name is Alex. Remember that.
Assistant: Got it! I'll remember your name is Alex.

You: What is my name?
Assistant: Your name is Alex.

You: quit

Goodbye — the transcript held 4 items.
```

As an experiment, move `input_items = []` to the top of the loop body (so the list is
recreated every turn) and run it again — the model instantly "forgets" your name. Memory
lives in that one line's placement.

---

## Version 2 — Functions: Name the Moves

### What changed from V1 to V2

- **Nothing about behavior.** Version 2 is the exact same chat — same API calls, same
  transcript, same output.
- The three inline moves of the loop body — append a user message, call the API, append
  the output — get **names**: `add_user`, `run_turn`, `extend_items`.
- The bare `input_items` list becomes a small **dict** (`{"instructions": ..., "items":
  [...]}`) so the system instructions travel with the transcript.
- Because the conversation is now one plain dict, **save/load** becomes a one-line
  `json.dump`/`json.load` — Version 2's one genuinely new capability.
- Still **no classes** — only plain functions taking `conv` as their first argument.

### Step 2.1 — Add Small Helper Functions

The four operations you just did inline — add user message, extend with model output, add a
tool result, return the list to pass as `input=` — will repeat every turn.  Naming them
makes the loop easier to read and avoids copy-paste mistakes.

**Why now?** Because the next step (save/load) is much cleaner once the helpers are in place.

```python
import json

def new_conversation(instructions=""):
    """Create a fresh conversation dict."""
    return {"instructions": instructions, "items": []}

def add_user(conv, text):
    """Append a user turn."""
    conv["items"].append({"role": "user", "content": text})

def extend_items(conv, output_items):
    """Append all items from resp.output, converting SDK objects to dicts."""
    for item in output_items:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        conv["items"].append(dict(item))

def add_tool_result(conv, call_id, output):
    """Append a function_call_output item."""
    conv["items"].append({
        "type": "function_call_output",
        "call_id": call_id,
        "output": output,
    })

def to_input(conv):
    """Return the items list ready to pass as input=."""
    return list(conv["items"])
```

Now rewrite the two-turn chat using these helpers:

```python
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()

conv = new_conversation(instructions="You are a helpful assistant.")

add_user(conv, "My name is Alex. Remember that.")
resp = client.responses.create(
    model=MODEL,
    instructions=conv["instructions"],
    input=to_input(conv),
)
extend_items(conv, resp.output)
print("Turn 1:", resp.output_text)

add_user(conv, "What is my name?")
resp2 = client.responses.create(
    model=MODEL,
    instructions=conv["instructions"],
    input=to_input(conv),
)
extend_items(conv, resp2.output)
print("Turn 2:", resp2.output_text)
print(f"Transcript has {len(conv['items'])} items.")
```

### ▶ Run it now

Output should be the same as Step 1.1.  Nothing changed externally —
only the code is cleaner.

---

### Step 2.2 — Save and Load the Transcript

Right now, if the program restarts, the conversation is lost.  Because `conv` is just a
dict with a list, saving it is one `json.dump()` call.

**Why now?** This is the whole point of owning the transcript locally — you can persist it,
reload it, and resume without touching the server.

```python
def save(conv, path):
    """Write the conversation to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, indent=2, ensure_ascii=False)

def load(path):
    """Read a conversation back from a JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
```

Try it — save after turn 1 and reload before turn 2:

```python
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()

# --- Session A: first turn ---
conv = new_conversation(instructions="You are a helpful assistant.")
add_user(conv, "My name is Alex. Remember that.")
resp = client.responses.create(
    model=MODEL,
    instructions=conv["instructions"],
    input=to_input(conv),
)
extend_items(conv, resp.output)
save(conv, "/tmp/my_session.json")
print("Saved session. Turn 1:", resp.output_text)

# --- Session B: simulate a restart by loading from disk ---
conv2 = load("/tmp/my_session.json")
add_user(conv2, "What is my name?")
resp2 = client.responses.create(
    model=MODEL,
    instructions=conv2["instructions"],
    input=to_input(conv2),
)
extend_items(conv2, resp2.output)
print("Loaded session. Turn 2:", resp2.output_text)
```

### ▶ Run it now

The model should still answer "Alex" on turn 2, even though the
conversation dict was serialized to disk and loaded back.  Open `/tmp/my_session.json`
in a text editor — you will see the full transcript as plain JSON.

> **Windows note.** `/tmp/...` is a Linux/macOS scratch directory that doesn't exist on
> Windows. Wherever this phase uses a `/tmp/...` path, substitute any writable path —
> the simplest is a bare filename like `"my_session.json"` (saved in the folder you run
> Python from).

---

### Step 2.3 — Version 2, complete: `chat_v2.py`

You have now seen every Version 2 piece on its own. Here they are assembled into one
complete file — the same chat REPL as `chat_v1.py`, reorganized into functions, with one
genuinely new capability: the transcript autosaves after every turn, and if a saved
session exists the chat **resumes** it on startup.

```python
# chat_v2.py — Version 2: the same multi-turn chat, organized into functions.
# Still no classes. New capability: the conversation survives a restart.
import json
import os
from openai import OpenAI

MODEL = "gpt-4o"
SESSION_PATH = "/tmp/chat_v2_session.json"  # on Windows use e.g. "chat_v2_session.json"
client = OpenAI()


def new_conversation(instructions=""):
    """Create a fresh conversation dict."""
    return {"instructions": instructions, "items": []}


def add_user(conv, text):
    """Append a user turn."""
    conv["items"].append({"role": "user", "content": text})


def extend_items(conv, output_items):
    """Append all items from resp.output, converting SDK objects to dicts."""
    for item in output_items:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        conv["items"].append(dict(item))


def to_input(conv):
    """Return the items list ready to pass as input=."""
    return list(conv["items"])


def save(conv, path):
    """Write the conversation to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, indent=2, ensure_ascii=False)


def load(path):
    """Read a conversation back from a JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_turn(conv, user_text):
    """One full turn: remember the user, call the API, remember the model."""
    add_user(conv, user_text)
    resp = client.responses.create(
        model=MODEL,
        instructions=conv["instructions"],
        input=to_input(conv),
    )
    extend_items(conv, resp.output)
    return resp.output_text


# --- the REPL: identical in behavior to chat_v1.py ---
if os.path.exists(SESSION_PATH):
    conv = load(SESSION_PATH)
    print(f"Resumed session with {len(conv['items'])} items.")
else:
    conv = new_conversation(instructions="You are a helpful assistant.")
    print("Started a new session.")

print("Type 'quit' to exit.")
while True:
    user_text = input("\nYou: ")
    if user_text.strip().lower() in ("quit", "exit"):
        break
    print("Assistant:", run_turn(conv, user_text))
    save(conv, SESSION_PATH)   # persist after every turn

print(f"\nGoodbye — transcript saved to {SESSION_PATH}.")
```

### ▶ Run it now

Tell it your name, type `quit`, then **run the program again** and ask
`What is my name?`. It remembers — across a full process restart — because the transcript
was sitting in `/tmp/chat_v2_session.json` the whole time. (Delete that file to start
fresh.) Compare the `while` loop body to `chat_v1.py`: the same three moves, now named.

---

## Interlude — Transcript Management Deep-Dive

Before climbing to Version 3, a short detour into the design decisions behind what you
just built. No new code to run here — this is the "why" behind owning the list.

### Own vs. Delegate — Which Should You Choose?

The two-turn example above used **owning the list** (`input_items` / `conv["items"]`).
The alternative is passing `previous_response_id=resp.id` and letting the server stitch
history together.  Here is when each makes sense:

| Concern | Own `input_items` | `previous_response_id` |
|---|---|---|
| Wire bytes per call | Grows with conversation length | Only new items each turn |
| Server-side persistence required | No (`store=False` works fine) | Yes — the response must be retrievable |
| Portability (save, load, replay) | Trivial — you have all items | Hard — history lives on the server |
| Debuggability | Full transcript locally | Need API call to inspect history |
| Multi-process / multi-host agents | Works natively | Works if responses are accessible |
| Reasoning items with `store=False` | Must carry `encrypted_content` forward | Server handles it automatically |

**Recommendation for a harness:** own `input_items`.  The transcript is your source of
truth.  You can persist it, replay it, and audit it without touching the server.  The
growing payload is rarely a bottleneck in practice, and you control exactly what the model
sees.

`previous_response_id` is worth revisiting when conversations are very long and you trust
the server to retain history — Phase 8 covers it as an optimization.

### Serializing SDK Objects

`resp.output` is a list of typed SDK objects, not plain dicts.  If you put them straight
back into `input` on the next call, that works for the current process.  But if you want to
save the transcript to disk or send it across a process boundary you need plain dicts.

Every SDK response object exposes `.model_dump()`:

```python
item_dict = item.model_dump()          # one item
full_dump = resp.model_dump()          # whole response including usage
```

The `input` field of `client.responses.create()` accepts either SDK objects or plain dicts,
so normalizing to dicts is safe.

### The `to_input()` Helper

Before sending items back you need to strip any fields that are output-only and not accepted
in `input`.  The simplest approach: let each item carry its `type` and the fields that matter
for the input contract, and discard everything else.  A helper that works for all item types
produced by the API:

```python
def to_input(items: list) -> list[dict]:
    """
    Normalize a mixed list of SDK output objects and/or plain dicts into
    the plain-dict form accepted by client.responses.create(input=...).
    """
    result = []
    for item in items:
        # SDK objects expose model_dump(); plain dicts pass through
        d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        result.append(d)
    return result
```

This is intentionally minimal.  The API silently ignores unknown fields in input items, so
including extra fields from `model_dump()` is harmless.

---

## Version 3 — Classes: the `Conversation` Object

### What changed from V2 to V3

- **Nothing about behavior.** Version 3 is the same chat-with-memory harness — same API
  calls, same transcript on disk, same answers.
- The conversation **dict** plus its seven loose functions become one **class**:
  `Conversation` bundles the data (`_items`, `instructions`) with the functions that
  operate on it.
- Call sites flip from `add_user(conv, text)` to `conv.add_user(text)` — `self` inside a
  method is exactly the `conv` argument the V2 functions took.
- `save`/`load` become methods too; `load` is a `@classmethod` "alternate constructor"
  (`Conversation.load(path)` builds a conversation straight from a file).
- The class picks up two small conveniences the dict didn't have: `len(conv)` and
  `last_assistant_text()`.
- Underneath, it is still the **same plain list** (`self._items`) you appended to in
  Version 1 — this is the shape the final package's `conversation.py` uses.

You now have five functions (`new_conversation`, `add_user`, `extend_items`,
`add_tool_result`, `to_input`) and two persistence functions (`save`, `load`).  They work
fine as standalone functions.

**Why introduce a class now?** A class bundles the data (`_items`, `instructions`) together
with the functions that operate on it, so you cannot accidentally call `add_user` on the
wrong list.  It also gives you a natural home for the `save`/`load` pair.  The class below
is *exactly the same logic* — just organized.

### Step 3.1 — The `Conversation` Class

> 🟢 **Reading the class.** Each `def ...(self, ...)` below is a **method** — a
> function attached to the conversation object, where `self` is the object's own data
> (here, `self._items`, the list of items). `__init__` is the setup function that runs
> when you write `Conversation(...)`. `@classmethod def load(cls, ...)` is an
> alternate constructor — `Conversation.load(path)` builds a conversation from a file.
> Every one of these maps directly to a plain function in the
> [beginner box above](#-beginner-track-two-things-to-know-before-you-start); if
> classes are unfamiliar, use those functions and skip this class entirely.
> One more newcomer in `save`/`load`: **`pathlib.Path`** is just an object-flavored
> file path — `pathlib.Path(path)` wraps a path string so you can call helpers like
> `.parent.mkdir(...)` (create the folder) and `.open(...)` (same as `open(path)`).
> Phase 4 uses it more heavily.

```python
import json
import pathlib
from typing import Any


class Conversation:
    """
    Owns the input_items list for a single conversation thread.

    All methods that accept output items accept either SDK objects
    (anything with .model_dump()) or plain dicts.
    """

    def __init__(self, instructions: str = ""):
        self._items: list[dict] = []
        self.instructions = instructions

    # ------------------------------------------------------------------
    # Building the transcript
    # ------------------------------------------------------------------

    def add_user(self, text: str) -> None:
        """Append a user message."""
        self._items.append({"role": "user", "content": text})

    def extend(self, output_items) -> None:
        """
        Append all items from resp.output (or any iterable of items).
        Normalizes SDK objects to dicts automatically.
        """
        for item in output_items:
            d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            self._items.append(d)

    def add_tool_result(self, call_id: str, output: str) -> None:
        """Append a function_call_output item."""
        self._items.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        })

    # ------------------------------------------------------------------
    # Sending to the API
    # ------------------------------------------------------------------

    def to_input(self) -> list[dict]:
        """Return the items list ready to pass as input=."""
        return list(self._items)  # shallow copy; items are dicts

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | pathlib.Path) -> None:
        """Serialize the full transcript to a JSON file."""
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(
                {"instructions": self.instructions, "items": self._items},
                f,
                indent=2,
                ensure_ascii=False,
            )

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Conversation":
        """Reconstruct a Conversation from a saved JSON file."""
        path = pathlib.Path(path)
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        conv = cls(instructions=data.get("instructions", ""))
        conv._items = data["items"]
        return conv

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def last_assistant_text(self) -> str:
        """Return the concatenated text from the last assistant message."""
        for item in reversed(self._items):
            if item.get("type") == "message" and item.get("role") == "assistant":
                parts = item.get("content", [])
                return "".join(
                    p.get("text", "") for p in parts if p.get("type") == "output_text"
                )
        return ""
```

The two-turn chat now reads:

```python
conv = Conversation(instructions="You are a helpful assistant.")
conv.add_user("What is 2 + 2?")

resp = client.responses.create(
    model=MODEL,
    instructions=conv.instructions,
    input=conv.to_input(),
    tools=[],
)

conv.extend(resp.output)   # append assistant message + any reasoning items
conv.save("./sessions/session-001.json")
```

### ▶ Run it now

Same result as Step 1.1.  The only difference is `conv.add_user(...)`
instead of `add_user(conv, ...)` and `conv.extend(...)` instead of
`extend_items(conv, ...)`.  Everything else is identical.

### Step 3.2 — Reasoning Items and `encrypted_content`

When you use a reasoning model (e.g. `o3`) you will see `reasoning` items in `resp.output`.
**Always append them with `conv.extend(resp.output)`** — including reasoning items — so the
model can use that intermediate work in subsequent turns.

If you set `store=False` (no server-side storage), reasoning content is redacted by default.
To preserve reasoning across turns without server storage, request encrypted reasoning:

```python
resp = client.responses.create(
    model=MODEL,
    instructions=conv.instructions,
    input=conv.to_input(),
    tools=tools_list,
    store=False,
    include=["reasoning.encrypted_content"],
)
```

The reasoning items in `resp.output` will then carry an `encrypted_content` field.  When you
pass those items back in the next call (via `conv.extend(resp.output)` → `conv.to_input()`),
the server uses the ciphertext to reconstruct reasoning without ever exposing the raw
content to you.

**This is optional** and only relevant for:

- Reasoning models with `store=False`
- Multi-turn conversations where you want the model's reasoning chain to persist across
  calls

For non-reasoning models or `store=True`, ignore `encrypted_content` entirely.

### Step 3.3 — The `instructions` Field

`instructions` is **not** part of `input_items`.  It is a top-level parameter on
`client.responses.create()`.  Pass it on every call:

```python
resp = client.responses.create(
    model=MODEL,
    instructions=conv.instructions,   # always pass this
    input=conv.to_input(),
    tools=tools_list,
)
```

If you change `instructions` mid-conversation, the new instructions apply immediately without
any entry in the input list.

---

### Step 3.4 — A Non-Streaming Agent Loop (Primary Path)

So far Versions 1–3 have been pure chat — no tools.  Now bring back the Phase 2 tool loop,
with the `Conversation` class managing the transcript.  This is the version you should
understand first — streaming (Version 4) only changes how text is *displayed*, not how the
loop works.

**Why non-streaming first?** It is simpler, has fewer moving parts, and produces identical
results.  Once you have this running you can add streaming as a display-layer enhancement
without touching any logic.

```python
import json
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()

# Simple sequential tool dispatcher (no threads needed for a beginner version)
def run_tool_calls(function_calls, registry):
    """Execute each tool call in order and return output items."""
    results = []
    for fc in function_calls:
        fn = registry.get(fc["name"])
        if fn is None:
            output = f"Error: unknown tool '{fc['name']}'"
        else:
            try:
                kwargs = json.loads(fc["arguments"])
                output = str(fn(**kwargs))
            except Exception as exc:
                output = f"Error: {exc}"
        results.append({
            "type": "function_call_output",
            "call_id": fc["call_id"],
            "output": output,
        })
    return results


def run_agent(user_message, instructions, tools_list, registry, max_turns=10):
    """
    Non-streaming agent loop.  Returns the Conversation when done.
    """
    conv = Conversation(instructions=instructions)
    conv.add_user(user_message)

    for turn in range(max_turns):
        resp = client.responses.create(
            model=MODEL,
            instructions=conv.instructions,
            input=conv.to_input(),
            tools=tools_list,
        )

        # Append ALL output items (message, reasoning, function_call) FIRST.
        conv.extend(resp.output)

        # Print the assistant's text response (empty string if no text yet).
        if resp.output_text:
            print(f"Assistant: {resp.output_text}")

        # Collect any tool calls.
        function_calls = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in resp.output
            if (getattr(item, "type", None) or item.get("type")) == "function_call"
        ]

        if not function_calls:
            break  # model is done

        # Run tools and append results.
        tool_outputs = run_tool_calls(function_calls, registry)
        for output in tool_outputs:
            conv.add_tool_result(output["call_id"], output["output"])

    return conv
```

> 🟢 **The `(getattr(item, "type", None) or item.get("type"))` line, unpacked.**
> `getattr(obj, "type", None)` is just `obj.type` with a fallback: it returns
> `obj.type` if the attribute exists, or `None` instead of crashing if it doesn't.
> The `or item.get("type")` part is the second attempt: items in `resp.output` can be
> **SDK objects** (use dot-access, `item.type`) *or* **plain dicts** (use
> `item.get("type")`) — for example after a save/load round-trip. So the line reads:
> "try dot-access first; if that gave `None`, try dict-lookup." It's the same
> object-vs-dict dance as `item.model_dump() if hasattr(item, "model_dump") else item`
> two lines above.

Try it with a simple tool:

```python
# A tiny tool registry: just a dict of name -> function
REGISTRY = {
    "add": lambda a, b: a + b,
}

TOOLS_LIST = [{
    "type": "function",
    "name": "add",
    "description": "Add two numbers.",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
    },
}]

conv = run_agent(
    user_message="What is 1234 + 5678?",
    instructions="You are a helpful math assistant. Use the add tool.",
    tools_list=TOOLS_LIST,
    registry=REGISTRY,
)
print(f"\nTranscript has {len(conv)} items.")
conv.save("/tmp/phase3-nonstreaming.json")
print("Saved to /tmp/phase3-nonstreaming.json")
```

> 🟢 `lambda a, b: a + b` is just a one-line way to write a function without naming it —
> exactly the same as `def add(a, b): return a + b` and then using `add`. (See
> [`GLOSSARY.md`](./GLOSSARY.md) under **`lambda`**.) The complete Version 3 file below
> uses the same shortcut.

### ▶ Run it now

You should see:

```text
Assistant: The sum of 1234 and 5678 is 6912.

Transcript has 4 items.
Saved to /tmp/phase3-nonstreaming.json
```

The four transcript items are: user message, `function_call` item, `function_call_output`
item, and the final assistant message.

> 🟢 **`output_text` is a shortcut.**  `resp.output_text` is a convenience property that
> concatenates all text content from the response into one string.  For most use cases it
> is all you need.  When you want to inspect individual items (e.g. to find tool calls),
> iterate `resp.output` directly.

### Step 3.5 — Version 3, complete: `chat_v3.py`

The snippets above introduced the class and the loop separately.  Here is Version 3 as one
complete file you can paste and run — the `Conversation` class plus the non-streaming agent
loop plus a tool, nothing else:

```python
#!/usr/bin/env python3
# chat_v3.py — Version 3, complete: the Conversation class + the tool loop.
# Same harness as chat_v2.py, organized into a class — and tools are back.
# (Named chat_v3.py to continue this phase's chat_v1/chat_v2 ladder — and to
# avoid colliding with Phase 2's separate agent_v3.py.)
import json
import pathlib
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()


# ── The Conversation class (Step 3.1, verbatim essentials) ───────────

class Conversation:
    """Owns the input_items list for a single conversation thread."""

    def __init__(self, instructions: str = ""):
        self._items: list[dict] = []
        self.instructions = instructions

    def add_user(self, text: str) -> None:
        self._items.append({"role": "user", "content": text})

    def extend(self, output_items) -> None:
        for item in output_items:
            d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            self._items.append(d)

    def add_tool_result(self, call_id: str, output: str) -> None:
        self._items.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        })

    def to_input(self) -> list[dict]:
        return list(self._items)

    def save(self, path) -> None:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(
                {"instructions": self.instructions, "items": self._items},
                f, indent=2, ensure_ascii=False,
            )

    @classmethod
    def load(cls, path) -> "Conversation":
        with pathlib.Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
        conv = cls(instructions=data.get("instructions", ""))
        conv._items = data["items"]
        return conv

    def __len__(self) -> int:
        return len(self._items)


# ── Tools (a plain dict registry, as in Phase 2) ─────────────────────

REGISTRY = {
    "add": lambda a, b: a + b,
}

TOOLS_LIST = [{
    "type": "function",
    "name": "add",
    "description": "Add two numbers.",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
    },
}]


# ── The loop (Step 3.4, verbatim) ────────────────────────────────────

def run_tool_calls(function_calls, registry):
    """Execute each tool call in order and return output items."""
    results = []
    for fc in function_calls:
        fn = registry.get(fc["name"])
        if fn is None:
            output = f"Error: unknown tool '{fc['name']}'"
        else:
            try:
                kwargs = json.loads(fc["arguments"])
                output = str(fn(**kwargs))
            except Exception as exc:
                output = f"Error: {exc}"
        results.append({
            "type": "function_call_output",
            "call_id": fc["call_id"],
            "output": output,
        })
    return results


def run_agent(user_message, instructions, tools_list, registry, max_turns=10):
    """Non-streaming agent loop.  Returns the Conversation when done."""
    conv = Conversation(instructions=instructions)
    conv.add_user(user_message)

    for turn in range(max_turns):
        resp = client.responses.create(
            model=MODEL,
            instructions=conv.instructions,
            input=conv.to_input(),
            tools=tools_list,
        )
        conv.extend(resp.output)          # output items FIRST (see Pitfall 3)

        if resp.output_text:
            print(f"Assistant: {resp.output_text}")

        function_calls = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in resp.output
            if (getattr(item, "type", None) or item.get("type")) == "function_call"
        ]
        if not function_calls:
            break                          # model is done

        for output in run_tool_calls(function_calls, registry):
            conv.add_tool_result(output["call_id"], output["output"])

    return conv


if __name__ == "__main__":
    conv = run_agent(
        user_message="What is 1234 + 5678?",
        instructions="You are a helpful math assistant. Use the add tool.",
        tools_list=TOOLS_LIST,
        registry=REGISTRY,
    )
    print(f"\nTranscript has {len(conv)} items.")
    conv.save("/tmp/phase3-chat-v3.json")
    print("Saved to /tmp/phase3-chat-v3.json")
```

### ▶ Run it now

Same expected output as the Step 3.4 check (the answer 6912, then a
4-item transcript).  Open `/tmp/phase3-chat-v3.json` — you can read the entire tool
handshake (`function_call` → `function_call_output`, matched by `call_id`) in plain JSON.
This file is the Version 3 harness in full; Version 4 changes exactly one thing about it.

---

## Version 4 — Streaming: the Same Harness, Live (optional)

> **This entire version is optional** — the beginner box at the top of this phase
> already sanctioned skipping the whole streaming half. If streaming is not a priority
> for you right now, skip ahead to [Pitfalls](#pitfalls) — the non-streaming Version 3
> above is complete and correct.  Come back here when you specifically want characters
> to appear as the model types.

### What changed from V3 to V4

- **The loop, the `Conversation` class, the tools, and the transcript are untouched.**
  Version 4 changes *presentation*, not logic — run V3 and V4 with the same prompt and
  the saved transcripts are equivalent.
- `client.responses.create(...)` gains one argument, `stream=True` — and instead of one
  finished `Response`, it now returns an **iterator of typed events**.
- Text is printed **delta by delta** as it streams in, instead of `resp.output_text`
  once at the end.
- Tool calls become *visible as they form*: a `response.output_item.added` event announces
  the call, then `response.function_call_arguments.delta` events stream its JSON arguments.
- The final structured `Response` (the thing V3's loop already uses) arrives on the
  **`response.completed`** event — capture it there, and everything after that line is
  exactly the V3 loop.
- One new helper, `stream_turn()`, replaces the bare `create()` call inside the loop.

Streaming does not change the loop logic or the transcript.  It changes only *how the
model's text reaches the terminal*: instead of printing `resp.output_text` after the whole
response arrives, you print each small text chunk (`delta`) as it streams in.

**Why streaming?** Faster perceived responsiveness, and tool calls become visible as they
form — useful for debugging.

### Step 4.1 — What an Event Stream Is

**Why do we need a new mechanism at all?** The model generates its answer one token at a
time, but plain `create()` makes the server *buffer* the whole response and hand it to you
only when generation finishes.  For a long answer that can mean staring at a frozen prompt
for many seconds.  With `stream=True`, the server instead sends you a sequence of small
**events** over the same HTTP connection, *as generation happens*:

- Most events are tiny **deltas** — "here are the next few characters of text"
  (`response.output_text.delta`) or "here are the next few characters of a tool call's
  JSON arguments" (`response.function_call_arguments.delta`).  Deltas exist because the
  model produces output incrementally; the stream simply forwards each increment instead
  of hoarding them.
- A few events are **markers** — "a new output item just started"
  (`response.output_item.added`), "this item is finished" (`response.output_item.done`),
  and finally "the whole response is finished" (`response.completed`), which carries the
  same fully-assembled `Response` object a non-streamed call would have returned.

So a stream is not a different *kind* of answer — it is the same answer, delivered as a
play-by-play.  Your code's new job is small: loop over the events, print the text deltas
as they arrive, and keep the final object from `response.completed`.

Here is the smallest possible streaming program — no tools, no loop, no class:

```python
# stream_hello.py — the smallest possible streaming program.
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()

final = None
with client.responses.create(
    model=MODEL,
    input=[{"role": "user", "content": "Count from 1 to 10, one number per line."}],
    stream=True,                       # <- the only new ingredient
) as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)   # print each chunk as it lands
        elif event.type == "response.completed":
            final = event.response                    # the assembled Response

print("\n\n--- after the stream ---")
print("final.output_text:", final.output_text[:40], "...")
```

### ▶ Run it now

Watch the numbers appear *as they are generated*, not all at once.  Then
note the last line: `final` is a normal `Response` object — `.output`, `.output_text`,
`.usage` all present — recovered from the `response.completed` event.  That object is what
the V3 loop already consumes, which is why streaming bolts on without touching the loop.

> 🟢 **`flush=True` matters.** `print(..., end="")` without a newline normally sits in
> Python's output buffer; `flush=True` forces each delta onto the screen immediately.
> Forget it and your "stream" appears in jerky chunks or all at the end.

### Step 4.2 — Why Stream?

| Without streaming | With streaming |
|---|---|
| User waits for the full response | First token appears within ~200 ms |
| Tool calls are invisible until done | Tool arguments form visibly — easy to debug |
| Cannot cancel mid-generation | `KeyboardInterrupt` breaks cleanly |
| No incremental logging | Can log each delta to a trace file |

### Step 4.3 — Event Reference

The stream emits these event types (in rough order of appearance):

| Event type | Key fields | When it fires |
|---|---|---|
| `response.created` | — | Stream opened, response ID assigned |
| `response.output_item.added` | `.item` (the new item, may be partial) | A new output item starts (message, function_call, reasoning) |
| `response.reasoning_summary_part.added` | `.part` | A new reasoning chain-of-thought section starts (reasoning models only) |
| `response.reasoning_summary_text.delta` | `.delta` (string) | A chunk of the model's reasoning summary |
| `response.reasoning_summary_text.done` | `.text` (the full summary) | A reasoning summary section is complete |
| `response.output_text.delta` | `.delta` (string) | A text chunk within a message item |
| `response.output_text.done` | — | The text item is complete |
| `response.function_call_arguments.delta` | `.delta` (string) | A chunk of JSON arguments for a tool call |
| `response.function_call_arguments.done` | — | Tool call arguments are complete |
| `response.output_item.done` | `.item` (the fully-formed item) | An output item is complete |
| `response.completed` | — | All output items are done |
| `response.error` | `.error` | An error occurred mid-stream |

The `response.completed` event carries the fully-assembled response on `event.response` —
the same structured object as a non-streamed call (with `.output`, `.usage`, etc.).  Capture
it as the events go by: when you stream with `client.responses.create(stream=True)` there is
no separate "get the final response" call, so you assemble it yourself from this event.

#### Reasoning and the reason → act → observe chain

With a reasoning model (e.g. `gpt-5` or `o3` — note the runnable examples in this phase
use `gpt-4o`, which is *not* one), each turn can begin with a
`reasoning` output item — the model's private chain-of-thought — *before* it emits any text
or tool calls.  Two things are needed to make that chain visible and to keep it working
across turns:

1. **Ask for a summary.** Raw reasoning is never exposed, but passing
   `reasoning={"summary": "auto"}` to `responses.create()` makes the model emit a
   human-readable *summary* of its thinking, which streams in via the
   `response.reasoning_summary_text.delta` events above.  (This parameter only applies to
   reasoning models; sending it to a non-reasoning model like `gpt-4o` is a 400 error.)
2. **Carry it forward.** The loop already appends every output item — reasoning included —
   with `conv.extend(resp.output)`.  That is what turns isolated turns into a *chain*: the
   reasoning item from turn _N_ is sent back as input on turn _N+1_, so after a tool result
   comes back the model resumes the same train of thought instead of starting over.  This is
   the reason → act (tool call) → observe (tool result) → reason loop.  **Never drop
   reasoning items from the transcript** — doing so breaks the chain (and, for some models,
   the API rejects a `function_call` whose preceding `reasoning` item is missing).

### Step 4.4 — `stream_turn()`: Full Implementation

```python
import sys
from typing import Any
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()


def stream_turn(
    conversation: "Conversation",
    tools: list[dict],
    instructions: str,
) -> Any:
    """
    Run one model turn with streaming.

    - Prints assistant text deltas live to stdout.
    - Announces tool calls as they begin and finish.
    - Returns the final response object (same shape as non-streamed).

    Does NOT mutate `conversation`; the caller appends resp.output.
    """
    # These two trackers aren't required for rendering (the deltas are printed
    # directly as they arrive) — they accumulate the in-flight call's name and
    # full JSON-arguments string so you can log or inspect a complete call when
    # its "...arguments.done" event fires. The compact V4 file below omits them.
    _current_tool_name: str | None = None
    _current_tool_args: str = ""
    final = None  # we assemble the final Response ourselves from the events

    print("\nAssistant: ", end="", flush=True)

    # stream=True turns responses.create() into an iterator of typed events
    # instead of a single Response. The returned object is still a context
    # manager, so the HTTP connection is closed cleanly on exit. We deliberately
    # avoid the higher-level client.responses.stream() helper so the event loop
    # — and the assembly of the final response — stays fully in our hands.
    with client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=conversation.to_input(),
        tools=tools,
        # reasoning={"summary": "auto"},  # uncomment when MODEL is a reasoning
        #   model (e.g. gpt-5/o3) to stream a chain-of-thought summary via the
        #   response.reasoning_summary_text.* events. On gpt-4o this parameter
        #   is rejected with a 400 error, so it stays off here.
        stream=True,
    ) as stream:
        try:
            for event in stream:
                etype = event.type

                # --- New output item starting ---
                if etype == "response.output_item.added":
                    item = event.item
                    if getattr(item, "type", None) == "function_call":
                        # Print a separator before the tool announcement
                        print()  # end the current line if text was streaming
                        _current_tool_name = item.name
                        _current_tool_args = ""
                        print(f"\n\033[2m⚙  calling {item.name}(\033[0m", end="", flush=True)

                # --- Reasoning chain-of-thought starting ---
                elif etype == "response.reasoning_summary_part.added":
                    print("\n\033[2m🤔 thinking: \033[0m", end="", flush=True)

                # --- Reasoning summary streaming (the model's thought process) ---
                elif etype == "response.reasoning_summary_text.delta":
                    print(f"\033[2m{event.delta}\033[0m", end="", flush=True)

                # --- Reasoning summary section complete ---
                elif etype == "response.reasoning_summary_text.done":
                    print()  # newline before text / tool calls begin

                # --- Text streaming ---
                elif etype == "response.output_text.delta":
                    print(event.delta, end="", flush=True)

                # --- Tool argument streaming ---
                elif etype == "response.function_call_arguments.delta":
                    _current_tool_args += event.delta
                    print(event.delta, end="", flush=True)

                # --- Tool call arguments complete ---
                elif etype == "response.function_call_arguments.done":
                    print("\033[2m)\033[0m", flush=True)  # close the dim paren
                    _current_tool_name = None
                    _current_tool_args = ""

                # --- Text item done ---
                elif etype == "response.output_text.done":
                    pass  # text already printed via deltas

                # --- The whole response is finished ---
                elif etype == "response.completed":
                    # event.response is the fully-assembled Response object —
                    # same shape as a non-streamed create() (.output, .usage…).
                    final = event.response

                # --- Error ---
                elif etype == "response.error":
                    print(f"\n[stream error: {event.error}]", file=sys.stderr)
                    break

        except KeyboardInterrupt:
            # The 'with' block's __exit__ closes the HTTP stream cleanly.
            print("\n[cancelled]", flush=True)
            raise

    print()  # newline after streaming ends
    return final
```

**Key implementation notes:**

- Streaming with `client.responses.create(stream=True)` gives you the raw event stream and
  nothing else — there is no `get_final_response()` helper.  You reconstruct the final
  structured object yourself by capturing `event.response` on the `response.completed`
  event.  That object has the same shape as a non-streamed `client.responses.create()`
  (`.output`, `.usage`, …).
- `KeyboardInterrupt` propagates after the context manager closes the connection, so no
  resource leak occurs.
- The dim ANSI escape `\033[2m` is purely cosmetic; remove it for plain terminals.

### ▶ Run it now

A streaming check: call `stream_turn` with a `Conversation` that has a
user message, using `tools=[]`.  You should see the assistant's response print
character-by-character.  The returned `final` object should have `.output_text` set.

```python
conv = Conversation(instructions="You are a helpful assistant.")
conv.add_user("Say hello in three words.")
final_resp = stream_turn(conv, tools=[], instructions=conv.instructions)
print("\nFull response object output_text:", final_resp.output_text)
```

### Step 4.5 — A Simpler Renderer (No ANSI)

If you want zero escape codes:

```python
def stream_turn_plain(conversation, tools, instructions):
    print("\nAssistant: ", end="", flush=True)
    final = None

    with client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=conversation.to_input(),
        tools=tools,
        # reasoning={"summary": "auto"},  # reasoning models only (400 on gpt-4o)
        stream=True,
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                print(event.delta, end="", flush=True)
            elif event.type == "response.reasoning_summary_text.delta":
                print(event.delta, end="", flush=True)   # chain-of-thought
            elif event.type == "response.output_item.added":
                item = event.item
                if getattr(item, "type", None) == "function_call":
                    print(f"\n[calling {item.name}]", flush=True)
            elif event.type == "response.function_call_arguments.delta":
                print(event.delta, end="", flush=True)
            elif event.type == "response.function_call_arguments.done":
                print()
            elif event.type == "response.completed":
                final = event.response

    print()
    return final
```

---

### Step 4.6 — The Integrated `run_agent_streaming` Loop

This function wires together the `Conversation` class, `stream_turn()`, and the Phase 2
parallel tool dispatcher.  Compare it line by line with Version 3's `run_agent`: the only
structural difference is that `stream_turn(...)` replaces the bare
`client.responses.create(...)` call.

> 🟢 **The `register(schema)` here is a "decorator that takes an argument," which is
> why there's a function inside a function.** You can ignore that machinery. It does
> the same job as the simple `register(name, fn, schema)` from the
> [Phase 2 beginner track](./02-tool-system.md#-beginner-track):
> store the function in a dict under its name, and store its schema in a list. If you
> built the Phase 2 `TOOLS` dict, you can keep using it here — with **one one-line
> adaptation**: Phase 2's dict maps a name to `{"fn": ..., "schema": ...}`, while this
> phase's `_registry` maps a name straight to the function. So where the code below
> says `fn = _registry.get(fc["name"])`, write
> `entry = TOOLS.get(fc["name"]); fn = entry["fn"] if entry else None`
> instead (and build the schema list with Phase 2's `tools_for_api()`). Also note
> `dispatch_parallel` uses **threads** again — the plain `for`-loop `run_tool_calls`
> from Phase 2 produces identical results if you prefer to avoid threads.

```python
import json
import sys
import concurrent.futures
from typing import Callable, Any

# -----------------------------------------------------------------------
# Phase 2 tool registry (reproduced inline for completeness)
# -----------------------------------------------------------------------

ToolFn = Callable[..., Any]
_registry: dict[str, ToolFn] = {}
_schemas: list[dict] = []


def register(schema: dict):
    """Decorator: register a Python function as a tool."""
    def decorator(fn: ToolFn):
        _registry[schema["name"]] = fn
        # Responses API wants the function fields FLAT (name/description/
        # parameters at the top level), NOT nested under a "function" key the
        # way the older Chat Completions API did.
        _schemas.append({"type": "function", **schema})
        return fn
    return decorator


def dispatch_parallel(function_calls: list[dict]) -> list[dict]:
    """
    Execute all function_call items in parallel.
    Returns a list of function_call_output dicts.
    """
    def call_one(fc: dict) -> dict:
        fn = _registry.get(fc["name"])
        if fn is None:
            result = f"Error: unknown tool '{fc['name']}'"
        else:
            try:
                kwargs = json.loads(fc["arguments"])
                result = str(fn(**kwargs))
            except Exception as exc:
                result = f"Error: {exc}"
        return {
            "type": "function_call_output",
            "call_id": fc["call_id"],
            "output": result,
        }

    with concurrent.futures.ThreadPoolExecutor() as pool:
        futures = [pool.submit(call_one, fc) for fc in function_calls]
        return [f.result() for f in concurrent.futures.as_completed(futures)]


# -----------------------------------------------------------------------
# The streaming agent loop
# -----------------------------------------------------------------------

def run_agent_streaming(
    user_message: str,
    instructions: str = "You are a helpful assistant.",
    max_turns: int = 10,
    save_path: str | None = None,
) -> Conversation:
    """
    Run a full agentic conversation with streaming output.

    Returns the Conversation object (full transcript).
    Optionally saves the transcript to `save_path` after each turn.
    """
    conv = Conversation(instructions=instructions)
    conv.add_user(user_message)

    for turn in range(max_turns):
        # --- Stream the model's response and get the structured final object ---
        resp = stream_turn(conv, _schemas, instructions)

        # --- Append ALL output items (message, reasoning, function_call) ---
        conv.extend(resp.output)

        # --- Optionally persist after each turn ---
        if save_path:
            conv.save(save_path)

        # --- Collect any tool calls ---
        function_calls = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in resp.output
            if (getattr(item, "type", None) or item.get("type")) == "function_call"
        ]

        if not function_calls:
            # No tool calls — the model is done
            break

        # --- Dispatch tools in parallel, append results ---
        tool_outputs = dispatch_parallel(function_calls)
        for output in tool_outputs:
            conv.add_tool_result(output["call_id"], output["output"])

        if save_path:
            conv.save(save_path)

    else:
        print(f"[Warning: reached max_turns={max_turns}]", file=sys.stderr)

    print(f"\n[Usage so far reflected in final resp: "
          f"in={resp.usage.input_tokens} "
          f"out={resp.usage.output_tokens} "
          f"total={resp.usage.total_tokens}]")

    return conv
```

> 🟢 **`for ... else:` is real Python, not a typo.** A `for` loop can have an `else`
> clause: the `else` block runs **only if the loop finished all its iterations without
> hitting `break`**. Here that means: if we went through all `max_turns` turns and the
> model *still* wanted more tool calls (so `break` never fired), print the warning.
> If the model finished early, `break` skips the `else`. The same effect with a plain
> flag variable:
>
> ```python
> finished = False
> for turn in range(max_turns):
>     ...
>     if not function_calls:
>         finished = True
>         break
>     ...
> if not finished:
>     print(f"[Warning: reached max_turns={max_turns}]", file=sys.stderr)
> ```
>
> The complete Version 4 file below uses the same `for/else` — read it the same way.

**Ordering note:** `conv.extend(resp.output)` must come **before** `dispatch_parallel`.  The
tool results reference `call_id` values that appear in `function_call` items; those items
must already be in the transcript when the tool results are appended, or the API will reject
the sequence.

---

### Step 4.7 — Version 4, complete: the Full Streaming Harness

Everything from this phase in one pasteable file: the `Conversation` class (Version 3),
the Phase 2 registry, `stream_turn()`, and the integrated loop.  This is the phase's
final form — and structurally it is still `chat_v1.py`: a list that grows, re-sent every
call.

> **Reference copy.** Assembled from Steps 4.1–4.6 unchanged (except: `stream_turn` is
> the compact form without the two in-flight trackers noted in Step 4.4). Nothing new
> to type here — skim or skip. The maintained `Conversation` lives in
> [`code/agent_harness/conversation.py`](./code/agent_harness/conversation.py).

```python
#!/usr/bin/env python3
"""
Phase 3 example: streaming agent with Conversation state management.

Tools:
  - add(a, b)         — returns a + b
  - count_words(text) — returns word count
"""

import json
import sys
import concurrent.futures
import pathlib
from typing import Any, Callable
from openai import OpenAI

MODEL = "gpt-4o"
client = OpenAI()

# ── Tool registry ─────────────────────────────────────────────────────

ToolFn = Callable[..., Any]
_registry: dict[str, ToolFn] = {}
_schemas: list[dict] = []


def register(schema: dict):
    def decorator(fn: ToolFn):
        _registry[schema["name"]] = fn
        # Responses API wants the function fields FLAT (name/description/
        # parameters at the top level), NOT nested under a "function" key the
        # way the older Chat Completions API did.
        _schemas.append({"type": "function", **schema})
        return fn
    return decorator


def dispatch_parallel(function_calls: list[dict]) -> list[dict]:
    def call_one(fc: dict) -> dict:
        fn = _registry.get(fc["name"])
        if fn is None:
            result = f"Error: unknown tool '{fc['name']}'"
        else:
            try:
                kwargs = json.loads(fc["arguments"])
                result = str(fn(**kwargs))
            except Exception as exc:
                result = f"Error: {exc}"
        return {"type": "function_call_output", "call_id": fc["call_id"], "output": result}

    with concurrent.futures.ThreadPoolExecutor() as pool:
        futures = [pool.submit(call_one, fc) for fc in function_calls]
        return [f.result() for f in concurrent.futures.as_completed(futures)]


# ── Register tools ────────────────────────────────────────────────────

@register({
    "name": "add",
    "description": "Add two numbers and return the result.",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First operand"},
            "b": {"type": "number", "description": "Second operand"},
        },
        "required": ["a", "b"],
    },
})
def add(a: float, b: float) -> float:
    return a + b


@register({
    "name": "count_words",
    "description": "Count the number of words in a string.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to count words in"},
        },
        "required": ["text"],
    },
})
def count_words(text: str) -> int:
    return len(text.split())


# ── Conversation class ────────────────────────────────────────────────

class Conversation:
    def __init__(self, instructions: str = ""):
        self._items: list[dict] = []
        self.instructions = instructions

    def add_user(self, text: str) -> None:
        self._items.append({"role": "user", "content": text})

    def extend(self, output_items) -> None:
        for item in output_items:
            d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            self._items.append(d)

    def add_tool_result(self, call_id: str, output: str) -> None:
        self._items.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        })

    def to_input(self) -> list[dict]:
        return list(self._items)

    def save(self, path: str | pathlib.Path) -> None:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump({"instructions": self.instructions, "items": self._items}, f, indent=2)

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Conversation":
        with pathlib.Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
        conv = cls(instructions=data.get("instructions", ""))
        conv._items = data["items"]
        return conv

    def last_assistant_text(self) -> str:
        for item in reversed(self._items):
            if item.get("type") == "message" and item.get("role") == "assistant":
                parts = item.get("content", [])
                return "".join(
                    p.get("text", "") for p in parts if p.get("type") == "output_text"
                )
        return ""


# ── stream_turn ───────────────────────────────────────────────────────

def stream_turn(conversation: Conversation, tools: list[dict], instructions: str) -> Any:
    print("\nAssistant: ", end="", flush=True)
    final = None

    with client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=conversation.to_input(),
        tools=tools,
        # reasoning={"summary": "auto"},  # uncomment on a reasoning model
        #   (e.g. gpt-5/o3) to stream a thought summary; 400 error on gpt-4o
        stream=True,
    ) as stream:
        try:
            for event in stream:
                etype = event.type

                if etype == "response.output_item.added":
                    item = event.item
                    if getattr(item, "type", None) == "function_call":
                        print(f"\n\033[2m⚙  calling {item.name}(\033[0m", end="", flush=True)

                elif etype == "response.reasoning_summary_part.added":
                    print("\n\033[2m🤔 thinking: \033[0m", end="", flush=True)

                elif etype == "response.reasoning_summary_text.delta":
                    print(f"\033[2m{event.delta}\033[0m", end="", flush=True)

                elif etype == "response.reasoning_summary_text.done":
                    print()

                elif etype == "response.output_text.delta":
                    print(event.delta, end="", flush=True)

                elif etype == "response.function_call_arguments.delta":
                    print(event.delta, end="", flush=True)

                elif etype == "response.function_call_arguments.done":
                    print("\033[2m)\033[0m", flush=True)

                elif etype == "response.completed":
                    final = event.response

                elif etype == "response.error":
                    print(f"\n[stream error: {event.error}]", file=sys.stderr)
                    break

        except KeyboardInterrupt:
            print("\n[cancelled]", flush=True)
            raise

    print()
    return final


# ── Agent loop ────────────────────────────────────────────────────────

def run_agent_streaming(
    user_message: str,
    instructions: str = "You are a helpful assistant.",
    max_turns: int = 10,
    save_path: str | None = None,
) -> Conversation:
    conv = Conversation(instructions=instructions)
    conv.add_user(user_message)

    for turn in range(max_turns):
        resp = stream_turn(conv, _schemas, instructions)
        conv.extend(resp.output)

        if save_path:
            conv.save(save_path)

        function_calls = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in resp.output
            if (getattr(item, "type", None) or item.get("type")) == "function_call"
        ]

        if not function_calls:
            break

        tool_outputs = dispatch_parallel(function_calls)
        for output in tool_outputs:
            conv.add_tool_result(output["call_id"], output["output"])

        if save_path:
            conv.save(save_path)

    else:
        print(f"[Warning: reached max_turns={max_turns}]", file=sys.stderr)

    print(
        f"\n[tokens: in={resp.usage.input_tokens} "
        f"out={resp.usage.output_tokens} "
        f"total={resp.usage.total_tokens}]"
    )
    return conv


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    INSTRUCTIONS = (
        "You are a helpful math and text assistant. "
        "Use the provided tools when calculations or word counts are needed."
    )
    USER_MSG = (
        "Please do two things: "
        "first, add 1234 and 5678; "
        "second, count the words in the sentence "
        "'The quick brown fox jumps over the lazy dog'. "
        "Then summarise both results in one sentence."
    )

    print(f"User: {USER_MSG}")
    conv = run_agent_streaming(
        user_message=USER_MSG,
        instructions=INSTRUCTIONS,
        save_path="./sessions/phase3-demo.json",
    )

    print("\n--- Saved transcript: ./sessions/phase3-demo.json ---")
    print(f"Transcript has {len(conv)} items.")
```

### Expected terminal output (conceptual)

There is nothing new to run here — the file above assembles Steps 4.1–4.6, each of
which you have already run. The transcript below shows what a full session looks like:
the deltas stream in character-by-character; the tool-call lines appear as the model
generates arguments.  The session is saved to disk after each turn.

> **Before you compare your output:** the `🤔 thinking:` lines below appear **only** if
> you run a *reasoning* model with the `reasoning={"summary": "auto"}` line uncommented.
> **The canonical run — plain `gpt-4o`, as written — shows no `🤔 thinking:` lines at
> all.** You will see only the `⚙ calling ...` lines and the assistant text; if that's
> what you got, nothing is wrong — that *is* the expected `gpt-4o` output. Mentally
> delete the two `🤔 thinking:` bursts from the transcript below when comparing.

```text
User: Please do two things: first, add 1234 and 5678; second, count the words in the
sentence 'The quick brown fox jumps over the lazy dog'. Then summarise both results in
one sentence.

Assistant: 
🤔 thinking: The user wants two things — a sum and a word count. I'll call add
for the arithmetic and count_words for the sentence, then summarise.

⚙  calling add({"a": 1234, "b": 5678})

⚙  calling count_words({"text": "The quick brown fox jumps over the lazy dog"})

Assistant: 
🤔 thinking: add returned 6912 and count_words returned 9. I have both results,
so I can write the one-sentence summary now.
The sum of 1234 and 5678 is 6912, and the sentence
'The quick brown fox jumps over the lazy dog' contains 9 words.

[tokens: in=312 out=47 total=359]

--- Saved transcript: ./sessions/phase3-demo.json ---
Transcript has 6 items.
```

The six items in the saved transcript (running on plain `gpt-4o`, which emits no
`reasoning` items) are:

1. `{"role": "user", "content": "Please do two things..."}` — the initial user message
2. A `function_call` item for `add` (with its `call_id` and `arguments`) — from the
   first API call
3. A `function_call` item for `count_words` — also from the first API call
4. A `function_call_output` item for `add` (result: `"6912"`) — appended by your loop
5. A `function_call_output` item for `count_words` (result: `"9"`) — appended by your loop
6. The final assistant `message` item containing the summary sentence — from the
   second API call, after which the loop terminates because `function_calls` is empty

On a **reasoning model** (the only case where the `🤔 thinking:` bursts shown above
actually appear), each API call also emits a `reasoning` item before its other output,
so the same session saves **8** items: a `reasoning` item slots in before the two
`function_call` items (between items 1 and 2), and another before the final `message`
(between items 5 and 6).

---

## Pitfalls

> **Pitfall 1 — Losing the final structured response**
>
> If you break out of the stream loop early, or never handle the `response.completed`
> event, you keep only the raw event deltas — no `.output` list, no `.usage`.  When you
> stream with `client.responses.create(stream=True)` there is no `get_final_response()`
> helper: the fully-assembled `Response` arrives exactly once, on the `response.completed`
> event's `event.response`.  Capture it there, or you lose it.

> **Pitfall 2 — Mixing streamed text handling with tool-call ordering**
>
> Do not assume text ends before tool calls begin.  A model may emit text, then start a
> function_call, then emit more text.  Drive your rendering purely from events; never
> assume a particular interleaving.  The `response.output_item.added` event tells you a
> new item type has started — use it to switch rendering mode.

> **Pitfall 3 — Appending tool results before the function_call items**
>
> `conv.extend(resp.output)` must run **before** `conv.add_tool_result(...)`.  The API
> validates that every `function_call_output` item is preceded by a matching
> `function_call` item with the same `call_id`.  If you append tool results first, the
> next API call will return a 400 error.

> **Pitfall 4 — Assuming `output_text` exists mid-stream**
>
> During streaming, a `response.output_item.added` event for a `message` item does not
> mean any text is available yet.  Text arrives only via `response.output_text.delta`
> events.  Do not try to read `.content` or `.text` from a partial item object; use the
> delta events exclusively for live rendering.

> **Pitfall 5 — Using SDK objects in `input` across process boundaries**
>
> SDK output objects are not JSON-serializable by default.  If you serialize with
> `json.dumps(conv.to_input())` and one of the items is still an SDK object (not yet
> normalized via `.model_dump()`), you will get a `TypeError`.  `Conversation.extend()`
> normalizes to dicts immediately, so this is only a risk if you bypass `extend()` and
> push SDK objects directly into `_items`.

> **Pitfall 6 — Ignoring `response.error` events**
>
> If the server encounters an error mid-stream it emits a `response.error` event and
> closes the stream.  If your loop only handles text and function-call events, the error
> is silently swallowed.  Always handle `response.error` — at minimum print it to stderr
> and break, or raise an exception.

---

## Key takeaways

- This phase separates **two orthogonal concerns**: *owning the transcript* (state) and
  *streaming* (presentation). Each works without the other.
- The transcript is **yours to manage**. Every turn, append the model's output items
  **first**, then the tool results — `conv.extend(resp.output)` before
  `conv.add_tool_result(...)`, always.
- **Streaming is optional.** `create(..., stream=True)` yields events you drive the UI
  from; grab the final complete `Response` from the `response.completed` event. Plain
  `create()` + `output_text` is simpler and behaves identically to the model.
- Because you own the transcript, you can **save and reload** a conversation — that's
  what makes resuming a session possible.

The whole phase at a glance:

| Concept | Key takeaway |
|---|---|
| Transcript ownership | Own `input_items`; use `previous_response_id` only as an optimization |
| Serialization | Call `.model_dump()` immediately; store dicts, not SDK objects |
| `Conversation` class | Single source of truth; handles add/extend/tool-result/save/load |
| Reasoning items | Append them like any other output; use `encrypted_content` with `store=False` |
| `instructions` | Top-level parameter, not in `input_items`; pass on every call |
| Streaming | Use `client.responses.create(..., stream=True)`; drive UI from events; capture the final `Response` from the `response.completed` event |
| Append order | `conv.extend(resp.output)` before `conv.add_tool_result(...)` — always |
| Cancellation | `KeyboardInterrupt` inside `with stream:` is safe; context manager cleans up |

## Check yourself

1. What are the two orthogonal concerns this phase pulls apart?
2. In what order must you append the model's items and the tool results each turn, and why?
3. With streaming, where do you obtain the final, complete `Response` object?
4. Do you need streaming for a *correct* agent?

<details><summary>Answers</summary>

1. **Transcript/state** (what the model remembers) vs **streaming/presentation** (how
   output reaches the user).
2. **Model output items first, then tool results.** The tool results refer back to the
   model's `function_call` items by `call_id`, so those must already be in the transcript.
3. From the **`response.completed`** event emitted at the end of the stream.
4. **No** — streaming only changes *how* text is displayed, not what the model computes.
   It's a UX feature.
</details>

---

## Exercises

**Practice:** see [`EXERCISES.md` — Phase 3](./EXERCISES.md#phase-3--conversation--streaming)
for hands-on exercises (session persistence, replay, and streaming renderers) before
moving on.

---

**Next:** [Phase 4 — Real-World Tools](./04-real-tools.md) (the `read_file`, `edit_file`,
`bash`, `grep`, `glob` toolset that turns the loop into a genuine coding agent).
