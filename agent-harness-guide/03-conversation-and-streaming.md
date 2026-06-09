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

## 1. Two Orthogonal Concerns

**Transcript management** determines what you send in `input` on each call.  You have two
options:

1. **Own the list** — append every `resp.output` item to your local `input_items` list and
   send the whole list on the next call.
2. **Delegate to the server** — pass `previous_response_id=resp.id` and send only the new
   items; the server stitches the history together.

**Streaming** is independent of which state strategy you pick.  You can stream with either
approach.

---

## 2. Transcript Management Deep-Dive

### 2.1 Own vs. Delegate — Which Should You Choose?

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

### 2.2 Serializing SDK Objects

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

### 2.3 The `to_input()` Helper

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

### 2.4 The `Conversation` Class

> 🟢 **Reading the class.** Each `def ...(self, ...)` below is a **method** — a
> function attached to the conversation object, where `self` is the object's own data
> (here, `self._items`, the list of items). `__init__` is the setup function that runs
> when you write `Conversation(...)`. `@classmethod def load(cls, ...)` is an
> alternate constructor — `Conversation.load(path)` builds a conversation from a file.
> Every one of these maps directly to a plain function in the
> [beginner box above](#-beginner-track-two-things-to-know-before-you-start); if
> classes are unfamiliar, use those functions and skip this class entirely.

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

Usage:

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

### 2.5 Reasoning Items and `encrypted_content`

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

### 2.6 The `instructions` Field

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

## 3. Streaming Deep-Dive

### 3.1 Why Stream?

| Without streaming | With streaming |
|---|---|
| User waits for the full response | First token appears within ~200 ms |
| Tool calls are invisible until done | Tool arguments form visibly — easy to debug |
| Cannot cancel mid-generation | `KeyboardInterrupt` breaks cleanly |
| No incremental logging | Can log each delta to a trace file |

### 3.2 Event Reference

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

With a reasoning model (the guide standardizes on `gpt-5`), each turn can begin with a
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

### 3.3 `stream_turn()` — Full Implementation

```python
import sys
from openai import OpenAI

MODEL = "gpt-5"
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
        reasoning={"summary": "auto"},  # surface the chain-of-thought (reasoning
                                        # models only); streams via the
                                        # response.reasoning_summary_text.* events
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

### 3.4 A Simpler Renderer (No ANSI)

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
        reasoning={"summary": "auto"},
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

## 4. The Integrated `run_agent_streaming` Loop

This function wires together the `Conversation` class, `stream_turn()`, and the Phase 2
parallel tool dispatcher.

> 🟢 **The `register(schema)` here is a "decorator that takes an argument," which is
> why there's a function inside a function.** You can ignore that machinery. It does
> the same job as the simple `register(name, fn, schema)` from the
> [Phase 2 beginner track](./02-tool-system.md#-beginner-track-the-same-tool-system-using-only-functions--dicts):
> store the function in a dict under its name, and store its schema in a list. If you
> built the Phase 2 `TOOLS` dict, keep using it here. Also note `dispatch_parallel`
> uses **threads** again — the plain `for`-loop `run_tool_calls` from Phase 2 produces
> identical results if you prefer to avoid threads.

```python
import json
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

**Ordering note:** `conv.extend(resp.output)` must come **before** `dispatch_parallel`.  The
tool results reference `call_id` values that appear in `function_call` items; those items
must already be in the transcript when the tool results are appended, or the API will reject
the sequence.

---

## 5. Complete Runnable Example

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

MODEL = "gpt-5"
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
        reasoning={"summary": "auto"},  # stream the chain-of-thought too
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

The deltas stream in character-by-character; the tool-call lines appear as the model
generates arguments.  The session is saved to disk after each turn.

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

The six items in the saved transcript are:

1. `{"role": "user", "content": "Please do two things..."}` — the initial user message
2. A `reasoning` item (if using a reasoning model; absent with standard GPT models)
3. A `function_call` item for `add` (with its `call_id` and `arguments`)
4. A `function_call` item for `count_words`
5. A `function_call_output` item for `add` (result: `"6912"`)
6. A `function_call_output` item for `count_words` (result: `"9"`)

After the second API call the model produces a `message` item containing the final text,
which is appended as item 7.  The loop then terminates because `function_calls` is empty.

---

## 6. Pitfalls

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

## Summary

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

**Next:** Phase 4 — Real Tools (the `read_file`, `edit_file`, `bash`, `grep`, `glob`
toolset that turns the loop into a genuine coding agent).
