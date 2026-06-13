# Glossary

> Every term this guide uses that goes beyond basic Python (functions, lists,
> dicts, operators, `client.responses.create(...)`), defined in plain language. When a phase uses a word you don't recognise, look here first.
> Terms are grouped, then alphabetical within a group. 🟢 marks the most
> beginner-essential entries.

---

## Harness & agent concepts

**Agent** 🟢 — An LLM wrapped in a loop that lets it *act*: call tools, read the
results, and decide what to do next, repeatedly, until the task is done. The model
alone only produces text; the agent is the model **plus** the code around it.

**Agent loop** 🟢 — The core cycle this whole guide is about: *send the
conversation → did the model ask to use a tool? → if yes, run it and append the
result, then loop; if no, return the answer.* Everything else (streaming,
permissions, sub-agents) is refinement on top of this loop.

**State machine (finite state machine)** 🟢 — A system that is always in exactly
one of a few named **states** and moves between them along defined **transitions**.
The **agent loop** is one: it sits in *call the model* or *run tools*, and the
model's reply (a tool call vs. a plain message) decides the next state — until it
reaches the terminal *done* state and returns the answer. Naming the shape helps:
almost every later phase adds machinery *inside* a state without changing the
machine. Permission **modes** are a second, smaller state machine — the harness is
in exactly one mode at a time.

**Harness** 🟢 — The program around the model that gives it "hands and a memory":
the loop, the tools, the transcript, the safety checks, the CLI. Building this is
"harness engineering." Tools like Claude Code and Cursor are harnesses.

**Tool** 🟢 — A Python function the model is allowed to call (e.g. `read_file`,
`bash`). You describe it to the model with a *schema*; when the model "calls" it,
your harness runs the real function and feeds the result back.

**Tool call / function call** 🟢 — The model's request to run a tool. It comes back
as an item in the response saying "call this function with these arguments." The
model does **not** run anything itself — it asks, and your harness executes.

**Tool result / `function_call_output`** — The string your harness sends back after
running a tool, so the model can see what happened. Paired to the call by a shared
`call_id`. This handshake (call → run → result) is the heartbeat of the loop.

**Tool registry** — A lookup (a dict) mapping a tool's name to its function and
schema, so the harness can find the right function when the model asks for it by
name.

**Dispatch** — The step where the harness takes a tool call's name, looks it up in
the registry, and runs the matching function with the given arguments.

**System prompt** — The standing instructions you put at the front of the
conversation to shape the model's behavior ("you are a coding assistant…"). Sent
on every turn.

**Transcript / conversation / `input_items`** 🟢 — The growing list of everything
said so far: user messages, the model's messages, tool calls, and tool results.
The harness owns this list and sends it back on every turn — that's the model's
"memory." It is **append-only**: nothing is removed (until context management).

**Turn** — One round of the loop: you send the transcript, the model responds. A
single user request may take several turns if the model uses tools along the way.

**Sub-agent** — A second agent the main agent spawns to handle a focused subtask
(e.g. "search the codebase"), often with its own tools and its own short
conversation. Lets a big job be split up, sometimes run in parallel (Phase 7).

**Orchestration** — Coordinating multiple agents/sub-agents: deciding who does
what, running them (possibly in parallel), and combining their results.

**Permission / approval gate** 🟢 — A safety check before a risky tool runs (e.g.
deleting a file, running shell commands). The harness pauses and asks the user, or
applies a rule, instead of blindly executing (Phase 5).

**Hook** — A function the harness calls at a defined moment (before/after a tool
runs) so you can add behavior — logging, blocking, modifying — without changing the
core loop (Phase 5).

**Sandbox** — Restricting what tools can touch (e.g. only files under one
directory, no network) so a misbehaving model can't do damage.

---

## Model, API & token concepts

**LLM (large language model)** 🟢 — The text-prediction model (e.g. GPT-class).
Think of it as a pure function: text in, text out. It can't remember anything
between calls or touch the world on its own — the harness supplies both.

**Responses API** 🟢 — OpenAI's interface this guide builds on, called with
`client.responses.create(...)`. You pass the conversation (`input`) and the tool
schemas (`tools`); it returns the model's next move in `response.output`.

**`response.output`** — A **list of items** the model produced this turn. Each item
has a `.type`: a `message` (text for the user) or a `function_call` (a request to
run a tool). The loop inspects these to decide what to do next.

**`output_text`** — A convenience field holding the model's final text answer as a
plain string, so you don't have to dig it out of the items yourself.

**Token** 🟢 — The unit models read and bill in — roughly ¾ of a word, or about 4
characters. "Costs tokens" ≈ "costs words." Both your input and the model's output
are measured in tokens.

**Context window** 🟢 — The maximum number of tokens the model can consider at once
(its whole transcript + the reply). Long sessions eventually bump against it, which
is why Phase 6 exists.

**Context management / compaction** — Techniques to keep a long conversation under
the context-window limit: trimming old turns, or summarising them so the gist
survives while the token count drops (Phase 6).

**Token budgeting** — Counting tokens in the transcript and deciding what to keep,
drop, or summarise so you stay under the window.

**Streaming** — Receiving the model's output incrementally (token by token) as it's
generated, instead of waiting for the whole reply — so the user sees text appear
live. Optional; the non-streaming `create()` is simpler and shown first (Phase 3).

**`tiktoken`** — An optional library that counts tokens exactly for a given model.
Without it, the guide approximates with `len(text) // 4`.

**Reasoning model** — A model that does extra internal "thinking" before answering;
tends to give better agentic (tool-using) behavior. The guide works on these and on
smaller/faster models alike.

**Rate limit** — A cap on how many requests/tokens you can send per minute. Hitting
it returns an error; production harnesses retry with backoff (Phase 8).

**Retry / backoff** — Re-sending a failed request after waiting, with the wait
growing each time (1s, 2s, 4s…), to ride out transient errors and rate limits.

---

## Python you'll meet (beyond your five)

**`class` / method / instance** 🟢 — A `class` bundles related data with the
functions that act on it (its *methods*); an *instance* is one such bundle.
`obj.do(x)` means "run `do`, with `obj`'s data available." This guide's beginner
track replaces classes with plain functions wherever it can.

**Attribute / dot-access (`item.type`)** 🟢 — Reading a field off an object with a
dot. `item.type` is the object version of `item["type"]` on a dict — same idea,
different punctuation. The Responses API returns objects, so you use the dot.

**`json.loads` / `json.dumps`** 🟢 — `loads` turns a *string that looks like a
dict* (`'{"city":"Paris"}'`) into a real dict; `dumps` does the reverse. The API
hands you tool arguments as a string, so you `json.loads` them.

**JSON Schema** 🟢 — Just a **dict that describes a function's arguments** (their
names and types). You send it so the model knows how to call your tool. You already
know dicts; this is one with an agreed-upon shape.

**`try` / `except`** 🟢 — "Try this; if it raises an error, do that instead of
crashing." How the harness survives bad tool arguments, missing files, and API
errors.

**Exception / raise / traceback** — An *exception* is Python's way of signalling an
error; code can `raise` one. A *traceback* is the error report Python prints when
one isn't caught — read it bottom-up: the last line is *what* went wrong.

**`with ... as x:` (context manager)** — Use a resource and clean it up
automatically when the block ends. `with client.responses.create(..., stream=True)
as stream:` = "open the stream, use it, close it for me."

**Type hint (`x: str`, `-> dict`)** — An optional note saying "this is a string" or
"this returns a dict." Ignored at runtime; you can skip them while reading. The
guide also uses them to *auto-generate* tool schemas (Phase 2).

**Decorator (`@something`)** — A line with `@` above a function that wraps it to add
behavior (e.g. `@tool` registers a function as a tool). The beginner track always
shows the plain-function equivalent.

**`*args` / `**kwargs`** — "Accept any extra positional / keyword arguments."
`run(**kwargs)` gathers named arguments into a dict called `kwargs`.

**f-string (`f"hi {name}"`)** — A string with `{...}` holes filled by values.
`f"{a}+{b}"` equals `str(a) + "+" + str(b)`.

**List / dict comprehension (`[f(x) for x in xs]`)** — A compact way to build a list
or dict with a loop inside brackets. The guide pairs the first few with the plain
`for`-loop they replace.

**Generator / `yield`** — A function that produces values one at a time on demand
(with `yield`) instead of building a whole list. Used for streaming.

**`dataclass`** — A class that's mostly just named fields — think "a dict with fixed
keys and dot-access." A shorthand for grouping related data.

**`Enum`** — A small set of named constant values (e.g. risk levels). Read it as
"named string constants kept together."

**`set`** — A list with no duplicates and fast "is this in it?" checks. Order
doesn't matter.

**`tuple`** — A fixed, unchangeable list, often used to return several values at
once: `return name, age`.

**`lambda`** — A tiny unnamed function written inline: `lambda x: x + 1` is a
function that adds one.

**`pathlib.Path`** — An object for file paths with handy methods
(`path.read_text()`, `path / "sub"`), nicer than juggling path strings.

**`subprocess`** — The standard-library way to run external shell commands from
Python (powers the `bash` tool).

**Thread / `ThreadPoolExecutor`** — Run several slow things (API or disk calls) at
the same time instead of one after another. The simple sequential version is always
shown first; threads are an optional speed-up (parallel tool calls, sub-agents).

**`asyncio` / async-await** — Another way to do many things concurrently. The guide
prefers threads for beginners and treats async as optional background.

**REPL** — A "read-eval-print loop": an interactive prompt where you type input and
see a reply. Phase 1's harness is a REPL for chatting with the agent.

**CLI (command-line interface)** — A program you run from the terminal with
arguments/flags (built with `argparse` in Phase 8).

**`argparse`** — The standard-library tool for reading command-line flags
(`--model gpt-...`) into your program.

**Logging / observability** — Recording what the harness did (which tools ran, how
long, what failed) so you can see inside a run and debug it (Phase 8).

**`pytest` / fixture / mock (`FakeClient`)** 🟢 — `pytest` runs your tests. A
*fixture* is reusable setup. A *mock* (here `FakeClient`) is a stand-in for the
real API so tests run **offline, with no API key**. Run them with
`python -m pytest` from the `code/` directory.

**Editable install (`pip install -e .`)** — Installs the package so Python can
`import agent_harness` from anywhere, while still pointing at your source files so
edits take effect immediately.

---

> Spotted a gap or an error? Open an issue on the repo.
