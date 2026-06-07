# Phase 0 — Foundations: The Agent Loop and the Responses API

> **Goal of this phase:** Understand *what an agent harness actually is*, learn the
> exact shape of the OpenAI **Responses API** we will build on, and lock down the
> conventions (naming, data shapes, project layout) that every later phase reuses.
>
> No frameworks. No LangChain, no LlamaIndex, no agent SDK. Just `openai` (the raw
> HTTP client) and the Python standard library. The whole point of this guide is to
> show you what those frameworks hide.

---

## 0.1 What is an "agent harness"?

An LLM by itself is a **pure function**: text in, text out. It cannot read a file,
run a command, call an API, or remember anything between calls. It is frozen.

An **agent harness** is the program wrapped *around* the model that gives it hands
and a memory. It is a loop that:

1. Sends the conversation so far to the model.
2. Reads what the model wants to do next. The model either:
   - produces a final text answer (we're done), **or**
   - asks to call one or more **tools** (functions you exposed to it).
3. If the model asked for tools, the harness **executes** those tools, captures
   their results, appends them to the conversation, and **goes back to step 1**.

That loop — *model → tool calls → execute → feed results back → model* — is the
entire ballgame. Everything else (streaming, permissions, sub-agents, context
compaction, retries) is refinement on top of this loop.

```
                ┌─────────────────────────────────────────────┐
                │                                             │
                ▼                                             │
   ┌────────────────────────┐     wants to    ┌──────────────┴───────────────┐
   │  Send conversation to  │──── call tools ─▶│  Execute tools, append their  │
   │  the model (Responses) │                  │  outputs to the conversation  │
   └────────────────────────┘                  └──────────────────────────────┘
                │
                │ produced final text
                ▼
        ┌───────────────┐
        │  Return answer │
        └───────────────┘
```

Claude Code, Cursor, and every "coding agent" you've used is — at its core — this
loop with a good set of tools and a lot of production polish. We will build up to
that polish phase by phase.

### The phase map

| Phase | What you build | Key concept |
|------|----------------|-------------|
| 0 | Foundations (this doc) | The agent loop; the Responses API contract |
| 1 | A bare harness in ~80 lines | The minimal viable loop with one tool |
| 2 | A real tool system | Tool registry, JSON-schema, parallel tool calls, error handling |
| 3 | Conversation state & streaming | Managing input items, streaming events, live UI |
| 4 | Real-world tools | `read_file`, `write_file`, `edit_file`, `bash`, `grep`, `glob` |
| 5 | Permissions & safety | Approval gates, sandboxing, the hook system |
| 6 | Context management | Token budgeting, history compaction, summarization |
| 7 | Sub-agents & orchestration | Spawning parallel agents, the dynamic-workflow pattern |
| 8 | Production harness | Retries, observability, persistence, the full assembled CLI |

Each phase is runnable on its own and builds directly on the previous one.

---

## 0.2 Why the Responses API (and not Chat Completions)?

OpenAI has two surfaces for talking to its models:

- **Chat Completions** (`/v1/chat/completions`) — the older, stateless,
  message-list API.
- **Responses** (`/v1/responses`) — the newer API designed *specifically for
  agents*. It is the one we use throughout.

The Responses API matters for harness-builders because it natively understands the
agent loop:

- **It thinks in "items," not just "messages."** A turn's output is a *list* of
  typed items — text, function calls, reasoning, etc. — instead of a single message
  with a bolted-on `tool_calls` array.
- **It can carry server-side state.** Pass `previous_response_id` and the API
  remembers the prior turn for you (we'll mostly manage state ourselves for
  transparency, but it's there).
- **It models reasoning as first-class items.** Reasoning models (e.g. the `o`
  series and `gpt-5`-class models) emit reasoning items you can carry forward, which
  materially improves multi-step tool use.
- **Tools are flatter and easier to construct** (no nested `function` wrapper).

> If you only know Chat Completions, the mental shift is: *stop thinking "a list of
> messages" and start thinking "a running list of typed items."*

---

## 0.3 The Responses API contract (memorize this)

This section is the **single source of truth** every later phase relies on. If a
code sample in a later phase looks unfamiliar, come back here.

### 0.3.1 Installation & client

```bash
pip install openai
export OPENAI_API_KEY="sk-..."
```

```python
from openai import OpenAI

client = OpenAI()  # reads OPENAI_API_KEY from the environment
```

We pin a model id in one place so every phase agrees:

```python
MODEL = "gpt-5"  # any Responses-API-capable model works; swap as you like
```

> Throughout this guide, `MODEL` refers to a current, capable OpenAI model. Use the
> latest model available to you. Reasoning-capable models give the best agentic
> behavior; everything here also works on smaller/faster models.

### 0.3.2 A basic call

```python
resp = client.responses.create(
    model=MODEL,
    instructions="You are a terse assistant.",   # the system prompt
    input="Say hello in five words.",            # a string OR a list of items
)

print(resp.output_text)  # convenience: all text output concatenated
```

Two important fields on the request:

- **`instructions`** — the system/developer prompt. Equivalent to a `system`
  message. Prefer this over stuffing a system message into `input`.
- **`input`** — either a plain string (shorthand for one user message) or a **list
  of input items** (the real, full-control form we use everywhere).

### 0.3.3 `input` as a list of items

This is the form the harness actually uses. The conversation is a Python list you
own and append to:

```python
input_items = [
    {"role": "user", "content": "What's the capital of France?"},
]
resp = client.responses.create(model=MODEL, input=input_items)
```

A `message` item has a `role` (`"user"`, `"assistant"`, `"system"`/`"developer"`)
and `content`. Content can be a simple string, or a list of typed content parts
(`{"type": "input_text", "text": "..."}` for user input,
`{"type": "output_text", "text": "..."}` for assistant output). For our purposes,
plain-string content for user messages is fine.

### 0.3.4 The output: a list of typed items

`resp.output` is a **list**. Each element has a `.type`. The types we care about:

| `item.type` | Meaning | Key fields |
|-------------|---------|-----------|
| `message` | The assistant's text (and/or other content parts) | `content` → list of parts; text parts are `output_text` |
| `function_call` | The model wants to call a tool | `name`, `arguments` (JSON **string**), `call_id`, `id` |
| `reasoning` | The model's internal reasoning (reasoning models) | `id`, `summary`, sometimes `encrypted_content` |

`resp.output_text` is a convenience property that concatenates the text of all
`output_text` parts. Great for simple cases; in the loop we iterate `resp.output`
directly so we can see tool calls.

### 0.3.5 Defining tools

In the Responses API a function tool is a **flat** object (note: no nested
`"function": {...}` wrapper like Chat Completions used):

```python
tools = [
    {
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
    }
]

resp = client.responses.create(model=MODEL, input=input_items, tools=tools)
```

The `parameters` object is a **JSON Schema**. The model uses it to decide *whether*
and *how* to call your function. Good descriptions here are the difference between a
useful agent and a confused one.

> **Strict mode (optional but recommended):** add `"strict": True` to a tool to make
> the model's `arguments` provably conform to your schema. Strict mode requires every
> property be listed in `required` and `additionalProperties: False`. We'll discuss
> this in Phase 2.

### 0.3.6 Handling a tool call — the critical handshake

When the model wants a tool, `resp.output` contains a `function_call` item:

```python
# pseudo-shape of a function_call item
{
    "type": "function_call",
    "id": "fc_abc123",          # the item id
    "call_id": "call_xyz789",   # <-- the id you must echo back
    "name": "get_weather",
    "arguments": '{"city": "Paris"}',  # JSON *string*, you must json.loads it
}
```

To answer it, you append **two things** to your `input_items` list, in order:

1. **The function_call item itself** (so the model sees what it asked for). The
   simplest robust way is to feed back the model's own output items.
2. A **`function_call_output`** item that references the same `call_id`:

```python
{
    "type": "function_call_output",
    "call_id": "call_xyz789",   # MUST match the function_call's call_id
    "output": "Sunny, 21°C",    # a STRING (JSON-encode structured data)
}
```

Then you call `client.responses.create(...)` again with the grown `input_items`.
That is the entire loop. The `call_id` is the glue that ties a request to its
result — **echoing it back exactly is mandatory**.

> **Two ways to carry state.** Either (a) keep your own `input_items` list and append
> output items + tool results yourself (explicit, portable, what we do), or (b) pass
> `previous_response_id=resp.id` and send *only the new* `function_call_output`
> items. We use (a) by default because it's transparent and survives process
> restarts; we cover (b) in Phase 8.

### 0.3.7 Carrying model output back into the conversation

The cleanest, least error-prone pattern — and the one we standardize on — is to
append the model's **raw output items** to our list and then append our tool
results:

```python
# after a response:
input_items += resp.output            # carry forward messages, function_calls, reasoning
# ... then for each function_call, append a function_call_output ...
```

`resp.output` items are SDK objects; they serialize correctly when passed back. If
you ever need plain dicts (e.g. to persist to disk), use
`item.model_dump()` / `resp.model_dump()`. We'll formalize a `to_input()` helper in
Phase 3.

### 0.3.8 Streaming (preview — full treatment in Phase 3)

For a live UI you stream events instead of waiting for the whole response:

```python
final = None
with client.responses.create(model=MODEL, input=input_items, tools=tools, stream=True) as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
        elif event.type == "response.function_call_arguments.delta":
            ...  # tool arguments streaming in token by token
        elif event.type == "response.completed":
            final = event.response   # same shape as a non-streamed response
```

Key event types you'll use: `response.output_text.delta`,
`response.function_call_arguments.delta`, `response.output_item.added`,
`response.completed`. Phase 3 builds a full streaming renderer.

### 0.3.9 Usage & cost

Every response carries token accounting:

```python
resp.usage.input_tokens
resp.usage.output_tokens
resp.usage.total_tokens
```

We track these in Phase 6 (context budgeting) and Phase 8 (observability).

---

## 0.4 Project conventions (used by every phase)

To keep eight phases coherent, we fix these conventions now.

### 0.4.1 Repository layout

By the end of the guide the consolidated package lives in `code/` and looks like:

```
agent_harness/
├── __init__.py
├── config.py          # MODEL, defaults, env
├── llm.py             # thin wrapper around client.responses with retries
├── tools/
│   ├── __init__.py    # the registry
│   ├── base.py        # Tool abstraction
│   ├── files.py       # read/write/edit/glob/grep
│   └── shell.py       # bash
├── permissions.py     # approval gates & policy
├── hooks.py           # pre/post tool hooks
├── context.py         # token budgeting & compaction
├── agent.py           # the core loop (the "harness")
├── subagents.py       # spawning parallel agents
└── cli.py             # the REPL / entrypoint
```

Each phase introduces the file(s) it needs; later phases extend them. You can build
the whole thing incrementally in one folder and watch it grow.

### 0.4.2 The vocabulary we use consistently

- **item** — one element of `input`/`output` (a message, function_call, reasoning…).
- **turn** — one round trip to the model (`responses.create` → its `output`).
- **step / loop iteration** — one pass through the agent loop (may be many turns).
- **tool** — a Python callable exposed to the model with a JSON schema.
- **tool call** — a `function_call` item from the model.
- **tool result** — the `function_call_output` we send back.
- **transcript / history** — our owned `input_items` list, the full conversation.
- **harness / agent** — the loop object that drives all of the above.

### 0.4.3 Data shapes we standardize on

A **tool result** that the harness produces internally is always:

```python
{
    "call_id": "<echoed call_id>",
    "output": "<string — JSON-encoded if structured>",
}
```

A **tool definition** the harness registers is always a Python object exposing:
`name`, `description`, `parameters` (JSON Schema dict), and a `run(**kwargs)` method.
We formalize this `Tool` abstraction in Phase 2.

### 0.4.4 Error-handling stance

Tools **never raise into the loop**. A tool that fails returns its error *as a
string result* so the model can read it and recover (retry, try another path, or
report). A raised exception kills the agent; a returned error string makes the agent
self-correct. This single rule is responsible for a huge fraction of an agent's
apparent "intelligence."

### 0.4.5 Async vs sync

Phases 1–5 use the **synchronous** client for clarity. Phase 7 (sub-agents) and
Phase 8 (production) introduce concurrency for parallel tool calls and parallel
agents — we use `concurrent.futures.ThreadPoolExecutor` for tool/agent parallelism
(the OpenAI SDK also has a fully `async` client, `AsyncOpenAI`, which we note as the
alternative). Threads are simplest because our tools are I/O bound (network, disk,
subprocess).

---

## 0.5 Sanity-check script

Before moving to Phase 1, confirm your environment works end to end. This is the
"hello world" of the Responses API *with a tool round trip* — it exercises the exact
handshake from §0.3.6.

```python
# check_setup.py
import json
from openai import OpenAI

MODEL = "gpt-5"
client = OpenAI()

tools = [{
    "type": "function",
    "name": "add",
    "description": "Add two integers and return the sum.",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}]

input_items = [{"role": "user", "content": "What is 21 + 21? Use the add tool."}]

# Turn 1: the model should ask to call `add`
resp = client.responses.create(model=MODEL, input=input_items, tools=tools)
input_items += resp.output

# Execute any tool calls
for item in resp.output:
    if item.type == "function_call":
        args = json.loads(item.arguments)
        result = args["a"] + args["b"]
        input_items.append({
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": str(result),
        })

# Turn 2: feed the result back; the model should answer in words
resp = client.responses.create(model=MODEL, input=input_items, tools=tools)
print(resp.output_text)   # -> something like "21 + 21 = 42"
```

If that prints a correct answer, your key, model access, and understanding of the
handshake are all good. **You now have everything you need to build the loop.**

Proceed to **Phase 1 — A bare harness in ~80 lines**.
