# Appendix — Library Reference

> A focused reference for every **external library** the harness depends on, plus the
> two standard-library modules it leans on most heavily. For each, you get the
> methods we actually use, their parameters, return types, and a small runnable
> example. Nothing here is exhaustive — it's the subset you need to understand the
> harness, with pointers to the official docs for the rest.

The harness has exactly **two third-party dependencies**:

| Library | Why we use it | Required? |
|---------|---------------|-----------|
| [`openai`](#1-openai--the-responses-api) | Talk to the model via the Responses API | **Yes** |
| [`tiktoken`](#2-tiktoken--local-token-counting) | Count tokens locally for context budgeting | Optional (Phase 6+) |

Everything else is the Python standard library. Two stdlib modules are central enough
to document here too: [`concurrent.futures`](#3-concurrentfutures--running-tools-in-parallel)
(parallel tool/sub-agent execution) and [`subprocess`](#4-subprocess--running-shell-commands)
(the `bash` tool).

```bash
pip install "openai>=1.66.0"   # Responses API was added in 1.66.0
pip install tiktoken           # optional
```

---

## 1. `openai` — the Responses API

The `openai` package is the official Python SDK. We use **only** the Responses API
(`client.responses.*`). We never touch Chat Completions (`client.chat.completions.*`).

> **Version note.** `client.responses` was introduced in `openai==1.66.0` (March 2025).
> Examples here were checked against `openai==2.x`. The shapes below are stable across
> that range.

### 1.1 Creating the client — `openai.OpenAI`

```python
from openai import OpenAI

client = OpenAI()                       # reads OPENAI_API_KEY from the environment
client = OpenAI(api_key="sk-...")       # or pass it explicitly
```

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `api_key` | `str` | `$OPENAI_API_KEY` | Your API key. |
| `base_url` | `str` | OpenAI's URL | Point at a compatible endpoint. |
| `timeout` | `float` | `600` | Per-request timeout in seconds. |
| `max_retries` | `int` | `2` | SDK-level automatic retries. |

**Returns:** an `OpenAI` client instance. The only attribute we use is
`client.responses`.

### 1.2 `client.responses.create(...)` — one model turn

This is the heart of the harness. One call = one model turn.

```python
response = client.responses.create(
    model="gpt-4o",
    instructions="You are a helpful coding assistant.",
    input=[{"role": "user", "content": "What is 2 + 2?"}],
    tools=[],
)
print(response.output_text)      # -> "4"
```

**Parameters we use** (it accepts many more — see the table after):

| Parameter | Type | Required | Meaning |
|-----------|------|:--------:|---------|
| `model` | `str` | ✅ | Model id, e.g. `"gpt-4o"`. |
| `input` | `str \| list[dict]` | ✅ | The conversation so far. A plain string is shorthand for a single user message; normally it's a **list of items** (see §1.4). |
| `instructions` | `str \| None` | – | The system prompt. The dedicated channel for "who the assistant is" — prefer this over a `role:"system"` item in `input`. |
| `tools` | `list[dict]` | – | Tool/function schemas the model may call (see §1.5). |
| `tool_choice` | `str \| dict` | – | `"auto"` (default), `"none"`, `"required"`, or force a specific tool. |
| `parallel_tool_calls` | `bool` | – | Allow the model to emit several tool calls in one turn (default `True`). |
| `stream` | `bool` | – | If `True`, returns an iterator of events instead of a `Response` (see §1.7). |
| `reasoning` | `dict` | – | For reasoning models, e.g. `{"effort": "medium"}`. |
| `max_output_tokens` | `int` | – | Cap the response length. |
| `temperature` | `float` | – | Sampling randomness (0–2). |
| `store` | `bool` | – | Whether OpenAI stores the response server-side (default `True`). |
| `previous_response_id` | `str` | – | Continue from a stored response without resending history. |
| `include` | `list[str]` | – | Ask for extra fields, e.g. `["reasoning.encrypted_content"]`. |

**Returns:** a `Response` object (see §1.3). Streaming changes the return type (§1.7).

**Raises** (the ones worth catching — see §1.6): `RateLimitError`,
`APIConnectionError`, `InternalServerError`, `BadRequestError`,
`AuthenticationError`.

### 1.3 The `Response` object

The object returned by a non-streaming `create()`. Fields the harness reads:

| Attribute | Type | Meaning |
|-----------|------|---------|
| `response.output` | `list` of items | The model's output items, in order: `message`, `function_call`, `reasoning`, … (see §1.4). **This is what you append back into `input`.** |
| `response.output_text` | `str` | Convenience: all text parts of all `message` items, concatenated. `""` if the turn produced only tool calls. |
| `response.usage` | `ResponseUsage` | Token accounting (see below). May be `None` in some streaming paths — guard with `getattr`. |
| `response.id` | `str` | The response id (use with `previous_response_id`). |
| `response.status` | `str` | `"completed"`, `"incomplete"`, etc. |
| `response.error` | object \| `None` | Set if the response failed. |

`response.usage` fields: `input_tokens` (int), `output_tokens` (int),
`total_tokens` (int), plus `input_tokens_details` / `output_tokens_details`
(breakdowns, e.g. cached and reasoning tokens).

```python
print(response.usage.input_tokens, response.usage.output_tokens)
```

### 1.4 Output / input **item** shapes

The Responses API speaks in *items*. You send a list of items as `input`; you get a
list of items back as `response.output`. **The core loop is: append every item in
`response.output` to your running `input` list, then call `create()` again.**

The item types you'll handle:

**`message`** — assistant (or user) text.

```python
{
    "type": "message",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "Hello!"}],
}
```

**`function_call`** — the model wants to run a tool.

```python
{
    "type": "function_call",
    "name": "get_current_time",
    "arguments": "{\"timezone\": \"UTC\"}",   # a JSON *string*, parse it yourself
    "call_id": "call_abc123",                 # echo this back in your result
}
```

**`function_call_output`** — *you* send this back with the tool's result. Matched to
the call by `call_id` (position doesn't matter).

```python
{
    "type": "function_call_output",
    "call_id": "call_abc123",
    "output": "2025-06-07T12:00:00+00:00",    # always a string
}
```

**`reasoning`** — opaque reasoning items from reasoning models. You don't read them,
but because you append *all* of `response.output` back into `input`, they ride along
automatically, which is exactly what the API wants.

> **Two gotchas the harness handles for you:**
> 1. `arguments` is a JSON **string**, not a dict — `json.loads()` it.
> 2. When you store `response.output` items (which are SDK objects) as plain dicts,
>    call `item.model_dump()`. Do **not** add a top-level `output_text` key to a
>    `message` dict — that's a response-level accessor, not a valid input field.

### 1.5 Tool schemas — the **flat** shape

Function tools use a **flat** schema. The function fields are top-level — there is
**no** nested `"function"` wrapper (that was the older Chat Completions shape).

```python
{
    "type": "function",
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "parameters": {                       # a JSON Schema object
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
        },
        "required": ["city"],
        "additionalProperties": False,
    },
    # "strict": True,                     # optional — see note
}
```

> **`strict` mode.** Setting `"strict": True` makes the API *guarantee* the
> arguments validate against your schema. The catch: strict mode requires **every**
> property to appear in `required` and `"additionalProperties": False`. So you can't
> have a plain optional parameter under strict mode — you'd model it as required with
> a nullable type (`"type": ["string", "null"]`). The harness defaults to
> **non-strict** so tools can have ordinary optional parameters.

### 1.6 Error types and retries

Import these from the top-level package:

```python
from openai import (
    RateLimitError,        # 429 — back off and retry
    APIConnectionError,    # network failure — retry
    InternalServerError,   # 5xx — retry
    BadRequestError,       # 400 — your request is malformed; do NOT retry
    AuthenticationError,   # 401 — bad key; do NOT retry
)
```

A minimal retry wrapper (this is what `llm.py` does):

```python
import time

def create_with_retry(client, **kwargs):
    delay = 1.0
    for attempt in range(5):
        try:
            return client.responses.create(**kwargs)
        except (RateLimitError, APIConnectionError, InternalServerError):
            if attempt == 4:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)   # exponential back-off, capped
```

### 1.7 Streaming — `client.responses.create(..., stream=True)`

For live, token-by-token output, pass `stream=True` to the **same** `create()` call. It
takes the same parameters as a non-streamed call but returns an iterator of typed events
instead of a single `Response`. The returned object is itself a context manager, so the
HTTP connection closes cleanly on exit.

```python
final = None
with client.responses.create(
    model="gpt-4o",
    instructions="You are concise.",
    input=[{"role": "user", "content": "Count to three."}],
    stream=True,
) as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)   # a text chunk
        elif event.type == "response.completed":
            final = event.response   # the same Response object as a non-streamed create()
print()
print(final.usage.total_tokens)
```

Event types you'll care about:

| `event.type` | Useful fields | Meaning |
|--------------|---------------|---------|
| `response.output_text.delta` | `event.delta` (str) | A chunk of assistant text. |
| `response.function_call_arguments.delta` | `event.delta` (str) | A chunk of a tool call's JSON arguments. |
| `response.output_item.done` | `event.item` | An output item finished. |
| `response.completed` | `event.response` | The whole response is done; carries the final `Response`. |
| `response.error` | `event.error` | Something went wrong. |

There is no `get_final_response()` when you stream this way: you reconstruct the assembled
`Response` (same shape as §1.3) yourself by capturing `event.response` on the
`response.completed` event, so after streaming for display you still get `output`,
`output_text`, and `usage` for your bookkeeping.

> **Why not `client.responses.stream()`?** The SDK also ships a higher-level
> `client.responses.stream()` context-manager helper that auto-accumulates state and
> exposes `get_final_response()`. We deliberately avoid it throughout this guide: the
> whole point is to drive the event loop and assemble the final response ourselves, so you
> can see exactly what that helper does under the hood. Everything here uses the low-level
> `create(stream=True)` primitive.

---

## 2. `tiktoken` — local token counting

`tiktoken` is OpenAI's fast BPE tokenizer. We use it in Phase 6 to count tokens
**locally** (no API call) so we can budget and prune the conversation. It's optional:
the harness falls back to a `len(text) // 4` heuristic if it isn't installed or can't
load its vocabulary.

> **The single most important fact:** the **first** time you use an encoding,
> tiktoken **downloads the vocabulary file over the network**. Offline, that raises a
> `requests` error (e.g. `HTTPError`), **not** a `KeyError`. Always catch broadly and
> fall back to the heuristic — see §2.4.

### 2.1 `tiktoken.encoding_for_model(model_name)`

Pick the right encoding for a model by name.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `model_name` | `str` | e.g. `"gpt-4o"`, `"gpt-4"`. |

**Returns:** an `Encoding` object.
**Raises:** `KeyError` if the model name is unknown (and a network error on first
download).

```python
import tiktoken
enc = tiktoken.encoding_for_model("gpt-4o")
```

### 2.2 `tiktoken.get_encoding(encoding_name)`

Get an encoding by its raw name (use as a fallback for unknown models).

| Parameter | Type | Meaning |
|-----------|------|---------|
| `encoding_name` | `str` | One of `tiktoken.list_encoding_names()`, e.g. `"o200k_base"` (GPT-4o family), `"cl100k_base"` (GPT-4/3.5). |

**Returns:** an `Encoding` object. **Raises:** `ValueError` for an unknown name (and a
network error on first download).

```python
enc = tiktoken.get_encoding("o200k_base")
```

`tiktoken.list_encoding_names()` **returns** `list[str]`, e.g.
`['gpt2', 'r50k_base', 'p50k_base', 'p50k_edit', 'cl100k_base', 'o200k_base', 'o200k_harmony']`.

### 2.3 The `Encoding` object

| Method / attribute | Signature | Returns | Meaning |
|--------------------|-----------|---------|---------|
| `enc.encode(text)` | `(text: str) -> list[int]` | list of token ids | Tokenize. `len(...)` is your token count. |
| `enc.decode(tokens)` | `(tokens: list[int]) -> str` | str | Inverse of `encode`. |
| `enc.name` | attribute | str | The encoding's name. |

```python
ids = enc.encode("hello world")     # e.g. [24912, 2375]
n_tokens = len(ids)                  # 2
text_again = enc.decode(ids)         # "hello world"
```

### 2.4 The robust pattern the harness uses

```python
def _heuristic(text: str) -> int:
    return max(1, len(text) // 4)    # ~4 chars/token; overestimates slightly (safe)

try:
    import tiktoken
    try:
        _ENC = tiktoken.encoding_for_model("gpt-4o")
        _ENC.encode("warmup")        # force the lazy download NOW so we catch failures
    except Exception:                # unknown model OR offline download failure
        _ENC = None
except ImportError:
    _ENC = None

def count_tokens(text: str) -> int:
    return _heuristic(text) if _ENC is None else len(_ENC.encode(text))
```

This never crashes: missing package, unknown model, or no network all degrade
gracefully to the heuristic.

---

## 3. `concurrent.futures` — running tools in parallel

Standard library. The harness uses a `ThreadPoolExecutor` to run independent tool
calls (and sub-agents) at the same time. Threads are the right tool here because the
work is **I/O-bound** (waiting on the network / disk / subprocesses), so the GIL isn't
a bottleneck.

### 3.1 `ThreadPoolExecutor`

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

| Constructor | `ThreadPoolExecutor(max_workers=None)` | `max_workers` caps concurrent threads. |
|-------------|------------------------------------------|----------------------------------------|

Use it as a context manager so threads are cleaned up automatically.

| Method | Signature | Returns | Meaning |
|--------|-----------|---------|---------|
| `executor.submit(fn, *args, **kwargs)` | – | `Future` | Schedule `fn` to run; returns immediately. |
| `future.result(timeout=None)` | – | the function's return value | Blocks until done; **re-raises** any exception the function raised. |
| `as_completed(futures)` | `(iterable_of_futures) -> iterator` | yields futures | Yields each future **as it finishes** (completion order, not submission order). |

### 3.2 The `{future: key}` idiom

Because `as_completed` yields in completion order, map each future back to its input:

```python
def run_in_parallel(calls):
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_id = {
            pool.submit(do_one_call, call): call["call_id"]
            for call in calls
        }
        for future in as_completed(future_to_id):
            call_id = future_to_id[future]
            try:
                results[call_id] = future.result()
            except Exception as exc:
                results[call_id] = f"Error: {exc}"   # never let one failure kill the batch
    return results
```

Returning results keyed by `call_id` is exactly why ordering doesn't matter for the
Responses API — `function_call_output` items are matched to calls by `call_id`.

---

## 4. `subprocess` — running shell commands

Standard library. Powers the `bash` tool. We use `subprocess.run`.

```python
import subprocess

result = subprocess.run(
    "echo hello",
    shell=True,
    cwd="/path/to/workspace",
    stdin=subprocess.DEVNULL,          # no interactive input — prevents hangs
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,          # fold stderr into stdout
    timeout=120,                        # seconds; raises TimeoutExpired if exceeded
    text=True,                          # decode bytes -> str
    errors="replace",                   # don't crash on bad UTF-8
)
```

Key `run()` parameters:

| Parameter | Type | Meaning |
|-----------|------|---------|
| `args` | `str` or `list[str]` | The command. With `shell=True`, pass a string. |
| `shell` | `bool` | Run via the shell (enables pipes, `&&`, globs). **Powerful and dangerous** — only with trusted/sandboxed input. |
| `cwd` | `str` | Working directory. |
| `timeout` | `float` | Kill and raise `TimeoutExpired` after this many seconds. |
| `capture_output` | `bool` | Shortcut for `stdout=PIPE, stderr=PIPE`. |
| `text` | `bool` | Decode output to `str` (vs `bytes`). |

**Returns:** a `CompletedProcess` with:

| Attribute | Type | Meaning |
|-----------|------|---------|
| `result.returncode` | `int` | `0` = success. |
| `result.stdout` | `str` | Captured stdout (and stderr if folded). |
| `result.stderr` | `str` | Captured stderr (if separate). |

**Raises:** `subprocess.TimeoutExpired` on timeout. Catch it and return an error
*string* — tools never raise into the agent loop.

```python
try:
    result = subprocess.run("sleep 5", shell=True, timeout=1, capture_output=True, text=True)
except subprocess.TimeoutExpired:
    print("command timed out")
```

---

## Where to go next

- **OpenAI Responses API** — official docs: <https://platform.openai.com/docs/api-reference/responses>
- **tiktoken** — <https://github.com/openai/tiktoken>
- **`concurrent.futures`** — <https://docs.python.org/3/library/concurrent.futures.html>
- **`subprocess`** — <https://docs.python.org/3/library/subprocess.html>

These four cover every external and load-bearing-stdlib dependency in the harness. If
you understand the four pages above, no part of the `agent_harness` package is a black
box.
