# Phase 0 — Foundations: The Agent Loop and the Responses API

> **Goal of this phase:** Understand *what an agent harness actually is*, learn the
> exact shape of the OpenAI **Responses API** we will build on, and lock down the
> conventions (naming, data shapes, project layout) that every later phase reuses.
>
> No frameworks. No LangChain, no LlamaIndex, no agent SDK. Just `openai` (the raw
> HTTP client) and the Python standard library. The whole point of this guide is to
> show you what those frameworks hide.

> 🟢 **New to Python? Read this first.** This guide originally assumed an
> experienced engineer. If you only know **functions, lists, dictionaries,
> operators, and `client.responses.create(...)`**, start with
> [`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md). It explains — in those terms — every
> other concept the guide uses (classes, `json.loads`, JSON Schema, `with`,
> threads…). Green boxes like this one appear throughout to bridge each gap as it
> comes up.

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

## 0.3 The Responses API contract (build it up step by step)

This section is the **single source of truth** every later phase relies on. We
introduce each piece one at a time, with a working checkpoint after each new idea.
If a code sample in a later phase looks unfamiliar, come back here.

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

### 0.3.2 Step 1 — the simplest possible call (text in, text out)

Before tools, loops, or state: just ask the model a question and print its answer.
This is the smallest end-to-end program we can write.

```python
# step1_hello.py
from openai import OpenAI

MODEL = "gpt-5"
client = OpenAI()

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

**▶ Run it now.**

```
python step1_hello.py
```

You should see something like:

```
Hello there! How are you?
```

The exact words vary, but if any five-word greeting appears your API key is valid
and the client is wired up correctly. Move on only once this works.

### 0.3.3 Step 2 — `input` as a list of items

The plain-string shortcut is convenient, but the harness needs precise control over
the conversation history. The full form passes a Python list you own and append to:

```python
# step2_list_input.py
from openai import OpenAI

MODEL = "gpt-5"
client = OpenAI()

input_items = [
    {"role": "user", "content": "What's the capital of France?"},
]
resp = client.responses.create(model=MODEL, input=input_items)
print(resp.output_text)
```

A `message` item has a `role` (`"user"`, `"assistant"`, `"system"`/`"developer"`)
and `content`. Content can be a simple string, or a list of typed content parts
(`{"type": "input_text", "text": "..."}` for user input,
`{"type": "output_text", "text": "..."}` for assistant output). For our purposes,
plain-string content for user messages is fine.

**▶ Run it now.**

```
python step2_list_input.py
```

You should see "Paris" (or a short sentence containing it). This is the form we'll
use for every multi-turn conversation because we can append new items as the
conversation grows.

### 0.3.4 The output: a list of typed items

> 🟢 **`item.type` uses a dot, not `["type"]`.** The API gives back *objects*, not
> plain dicts. Reading a field with a dot — `item.type`, `item.name` — is the same
> idea as reading a dict key (`item["type"]`), just different punctuation. So
> `resp.output` is a list you can loop over, and each element's fields are read with
> a dot.

`resp.output` is a **list**. Each element has a `.type`. The types we care about:

| `item.type` | Meaning | Key fields |
|-------------|---------|-----------|
| `message` | The assistant's text (and/or other content parts) | `content` → list of parts; text parts are `output_text` |
| `function_call` | The model wants to call a tool | `name`, `arguments` (JSON **string**), `call_id`, `id` |
| `reasoning` | The model's internal reasoning (reasoning models) | `id`, `summary`, sometimes `encrypted_content` |

`resp.output_text` is a convenience property that concatenates the text of all
`output_text` parts. Great for simple cases; in the loop we iterate `resp.output`
directly so we can see tool calls.

You already saw `resp.output_text` in Steps 1 and 2. In Step 3 you'll see why we
need to iterate `resp.output` directly.

### 0.3.5 Step 3 — defining a tool and seeing the model request it

Now we add one tool and observe the two-turn handshake. In the Responses API a
function tool is a **flat** object (note: no nested `"function": {...}` wrapper like
Chat Completions used):

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

> 🟢 **"JSON Schema" is just a dictionary.** Don't let the name scare you — every
> tool above is a plain Python **dict**, the kind you already write. The
> `"parameters"` key holds another dict that describes the function's arguments:
> `"properties"` lists each argument name and its type, and `"required"` is a list
> of which ones must be provided. That's all a schema is — a dict in an agreed
> shape that tells the model how to call your function.

> **Strict mode (optional but recommended):** add `"strict": True` to a tool to make
> the model's `arguments` provably conform to your schema. Strict mode requires every
> property be listed in `required` and `additionalProperties: False`. We'll discuss
> this in Phase 2.

Here is the minimal program that defines one tool and prints what the model decided
to do (call it, or answer directly):

```python
# step3_tool_request.py
from openai import OpenAI

MODEL = "gpt-5"
client = OpenAI()

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
```

**▶ Run it now.**

```
python step3_tool_request.py
```

Expected output (exact values vary):

```
item.type = function_call
  name      = get_weather
  arguments = {"city": "Tokyo"}
  call_id   = call_xyz789
```

The model did **not** answer in text — it instead asked you to run `get_weather`.
That `call_id` is critical: you must echo it back in the next step.

### 0.3.6 Step 4 — the tool call → result handshake (the critical step)

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

> 🟢 **`json.loads` turns a string into a dict.** Look closely at `arguments` above:
> it's wrapped in quotes, so it's a **string** that merely *looks* like a dict, not a
> dict you can index yet. `import json` then `json.loads(item.arguments)` converts
> that string into a real dict — after which `args["city"]` gives you `"Paris"`.
> (`json.dumps(some_dict)` does the reverse: dict → string.)

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

Now let's run the complete two-turn exchange. This is the **complete handshake** in
under 30 lines:

```python
# step4_handshake.py
import json
from openai import OpenAI

MODEL = "gpt-5"
client = OpenAI()

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

def get_weather(city):
    # Stub: in a real harness this would call a weather API
    return f"Sunny, 21°C in {city}"

input_items = [{"role": "user", "content": "What's the weather like in Tokyo?"}]

# Turn 1: model should ask to call get_weather
resp = client.responses.create(model=MODEL, input=input_items, tools=tools)
input_items += resp.output   # carry all output items forward

# Execute any tool calls
for item in resp.output:
    if item.type == "function_call":
        args = json.loads(item.arguments)
        result = get_weather(**args)
        input_items.append({
            "type": "function_call_output",
            "call_id": item.call_id,   # echo back the same call_id
            "output": result,          # a string
        })

# Turn 2: feed the result back; model should now answer in words
resp = client.responses.create(model=MODEL, input=input_items, tools=tools)
print(resp.output_text)
```

**▶ Run it now.**

```
python step4_handshake.py
```

Expected output:

```
The weather in Tokyo is sunny and 21°C.
```

(Wording varies, but it will quote back the stub data.) If you see this, you have
successfully run the **complete agent loop** — model asks for a tool, you run it,
you feed the result back, and the model answers. Phase 1 simply wraps this pattern
in a `while` loop.

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

You already saw this pattern in `step4_handshake.py` — `input_items += resp.output`
is the key line that makes the conversation grow correctly.

---

## 0.3.8 Preview: streaming (full treatment in Phase 3)

> **This section is optional for now.** Skip it on your first pass. Come back after
> you have Phase 1 working. Streaming is a UI enhancement — it does not change the
> handshake logic you just learned.

For a live UI you stream events instead of waiting for the whole response. Pass
`stream=True` to the **same** `responses.create()` call — it then returns an iterator of
typed events instead of a single response:

> 🟢 **Reading the `with ... as stream:` line.** `with` is just a way to open
> something and have Python close it for you automatically when the block ends. Read
> this block as: "start a streaming response, call it `stream`, loop over its events,
> and close it when the loop finishes." The `for event in stream:` part is an
> ordinary loop — each `event` is an object whose `.type` you check, exactly like the
> output items above. You don't need to fully understand `with` to follow along;
> Phase 3 revisits streaming in detail.

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

There is no separate `get_final_response()` call: you assemble the final response yourself
by capturing `event.response` on the `response.completed` event. (The SDK does ship a
higher-level `client.responses.stream()` helper that does this for you, but we avoid it on
purpose — the harness drives the event loop itself.) Key event types you'll use:
`response.output_text.delta`, `response.function_call_arguments.delta`,
`response.output_item.added`, `response.completed`. Phase 3 builds a full streaming renderer.

---

## 0.3.9 Preview: usage & cost (full treatment in Phase 6)

> **This section is optional for now.** Skip it on your first pass. Token accounting
> matters a lot once your conversations grow long — but first get the handshake
> working.

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

> 🟢 **"Concurrency / threads" = doing slow things at the same time.** Normally your
> code runs one line after another: if you call three tools, the second waits for the
> first to finish. "Threads" let all three run *at once*, which is faster when each
> one is mostly waiting (for the network, the disk, a command). Until Phase 7 every
> example runs the simple one-after-another way, and when threads appear, this version
> shows the sequential version first so you can see they produce the same result.

---

## 0.5 Sanity-check script

Before moving to Phase 1, confirm your environment works end to end. This script is
a variant of `step4_handshake.py` that uses the integer `add` tool from
§0.3.5 — it exercises the exact handshake you just learned, with a tool that has
completely deterministic output so you can easily verify correctness.

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

**▶ Run it now.**

```
python check_setup.py
```

If that prints a sentence containing "42", your key, model access, and understanding of the
handshake are all good. **You now have everything you need to build the loop.**

---

## Key takeaways

- An LLM is **stateless**: text in, text out. The harness supplies the two things it
  lacks — **memory** (the growing `input` list) and **hands** (tools).
- The Responses API is `client.responses.create(model, input, tools)` →
  `response.output`, a **list of typed items**. Each item's `.type` is either a
  `message` (text for the user) or a `function_call` (a request to run a tool).
- The **tool handshake**: the model emits a `function_call` with a `call_id` and a
  JSON **string** of `arguments`; you run the matching function and append a
  `function_call_output` carrying the **same `call_id`** and a **string** result.
- The conversation is **append-only**: the model's own output items travel back into
  the next call's `input`. That re-sent list *is* the model's memory.

## Check yourself

Before moving on, can you answer these?

1. What two capabilities does a harness add to a stateless LLM?
2. What's inside `response.output`, and how do you tell a tool request from a final answer?
3. The model asks to call a tool. What must the `function_call_output` you send back contain?
4. Why must you append the model's *own* output items back into `input` each turn?

<details><summary>Answers</summary>

1. **Memory** (the persisted `input` transcript) and **hands** (tools it can call).
2. A **list of typed items**; check `item.type` — `"function_call"` means it wants a
   tool, `"message"` means it's the final text answer.
3. The **same `call_id`** as the call, a **string** `output`, and the type
   `function_call_output`. Always return one output per call, even on error.
4. Each `create()` call is stateless — the API only "remembers" what you send. Re-sending
   the model's prior output items is exactly what preserves the conversation.
</details>

Proceed to **Phase 1 — A bare harness in ~80 lines**.
