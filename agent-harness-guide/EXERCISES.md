# Exercises — Learn by Doing

> The phases teach by *reading*; this page makes you *build*. Each phase below has a
> **warm-up** (cements the core idea) and a **stretch** (pushes a little further). Try
> each before opening its hint. You only need what that phase has already taught.
>
> Work in a scratch copy so you can experiment freely:
> ```bash
> cd code && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
> ```
> The canonical implementation in [`code/agent_harness/`](./code/) is your answer key —
> if you get stuck, find the same idea there. New terms? See the
> [Glossary](./GLOSSARY.md). Lost? See the [Learning Path](./LEARNING-PATH.md).

---

## Phase 0 — Foundations

**0.1 (warm-up)** Run the sanity-check script at the end of
[`00-foundations.md`](./00-foundations.md). Then add a **second** tool — `multiply(a, b)`
— alongside the adder, and ask the model a question that needs it. Confirm the handshake
fires for the right tool.

**0.2 (stretch)** For one prompt that needs a tool and one that doesn't, print
`[item.type for item in response.output]`. Predict each list *before* you run it.

<details><summary>Hint</summary>

A tool is a schema dict (in `tools`) plus a local function. For 0.2: a tool-using turn
contains a `function_call` item; a direct answer is a single `message` item. The model
decides — your job is only to inspect `response.output`.
</details>

---

## Phase 1 — A bare harness

**1.1 (warm-up)** Add a second tool to your bare harness (e.g. `get_weather(city)`
returning a fixed string). Ask a question that should use it, and one that shouldn't.
Did the model choose correctly?

**1.2 (stretch)** Make a tool that *always* returns an error string. Ask the model to use
it. Watch the loop retry — then confirm your `MAX_ITERATIONS` cap stops it. Remove the cap
briefly to feel why it matters (then put it back!).

<details><summary>Hint</summary>

The loop stops when `response.output` has no `function_call` items. A tool that always
errors keeps the model trying, so the **cap** is the only thing that ends it. See
"Common Pitfalls" at the end of Phase 1.
</details>

---

## Phase 2 — The tool system

**2.1 (warm-up)** Register a new `calculator(expression: str)` tool through the registry
(use `@tool`, or hand-write the schema per the beginner track). Call it from the agent
without editing the loop.

**2.2 (stretch)** Give two tools an artificial `time.sleep(2)`. Run them in the same turn
once with parallel dispatch and once sequentially; time both. Then describe a case where
parallel would be **unsafe**.

<details><summary>Hint</summary>

2.1: the whole point of the registry is that adding a tool doesn't touch the loop. 2.2:
parallel ≈ `max(durations)`, sequential ≈ `sum(durations)`. Parallel is unsafe when tools
have **conflicting side effects** (e.g. two writes to the same file). See `tools/parallel.py`.
</details>

---

## Phase 3 — Conversation & streaming

**3.1 (warm-up)** Have a short multi-turn chat, save the conversation to a JSON file, exit,
reload it in a fresh run, and continue. Confirm the model "remembers" the earlier turns.

**3.2 (stretch)** Run the same prompt with streaming on and off. Confirm the final answer
is identical, and note *where* in your code the only difference lives.

<details><summary>Hint</summary>

3.1: the transcript is just a list — `json.dump` it and `json.load` it back. 3.2: streaming
changes presentation only; the final `Response` comes from the `response.completed` event.
The model's output is the same either way.
</details>

---

## Phase 4 — Real tools

**4.1 (warm-up)** Point the agent at an empty scratch directory and ask it to create and
then edit a small file. Verify the change with `git diff` (or by reading the file).

**4.2 (stretch)** Feed `read_file` a large file. Add/confirm output truncation and observe
the transcript stay small. What happens to the model's answer quality without truncation?

<details><summary>Hint</summary>

4.1: the real tools are `read_file`, `edit_file`, `bash`, `grep`, `glob`; assemble them via
`make_default_registry()`. 4.2: oversized output crowds the context window — see
"Output-Size Discipline" in Phase 4. Return an **error string**, never raise, on a bad path.
</details>

---

## Phase 5 — Permissions & safety

**5.1 (warm-up)** Put `edit_file` (or `bash`) behind the approval gate. Trigger it, then
**deny** the request, and confirm the tool did **not** run and the model adapted.

**5.2 (stretch)** Write a pre-tool hook that logs every tool name + args before it runs.
Confirm it fires for every call without changing the agent loop.

<details><summary>Hint</summary>

5.1: choose a stricter `permission_mode` so risky tools require approval. 5.2: hooks are
functions the harness calls before/after each tool — see the hook system in Phase 5
(`hooks.py`). The loop never needs to know your hook exists.
</details>

---

## Phase 6 — Context management

**6.1 (warm-up)** Set an artificially tiny token budget and run a long chat. Watch old turns
get pruned/compacted. Confirm the system prompt and recent turns survive.

**6.2 (stretch)** If `tiktoken` is installed, count a sample transcript both ways
(`tiktoken` vs `len(text) // 4`). How far apart are they? When is the approximation good enough?

<details><summary>Hint</summary>

6.1: the tactics layer in order — clip → prune → compact → externalise → persist. 6.2: the
`// 4` rule is a rough proxy for "≈4 chars per token"; it's fine for budgeting decisions,
not for billing. See "Counting Tokens" in Phase 6.
</details>

---

## Phase 7 — Sub-agents & orchestration

**7.1 (warm-up)** Add a `task` tool that spawns a sub-agent (your `run_agent` loop, called
again) to handle a focused search, and have the main agent call it.

**7.2 (stretch)** Fan out **two** sub-agents in parallel on independent subtasks and combine
their results in the main agent's answer. Measure the wall-clock saving vs running them in series.

<details><summary>Hint</summary>

The key trick: a sub-agent *is* the loop invoked again, exposed **as a tool**. Give it a
narrow brief and few tools. Parallelism helps only when the subtasks are **independent**.
See `subagents.py`.
</details>

---

## Phase 8 — The production harness

**8.1 (warm-up)** Wrap the API call in retry-with-exponential-backoff. Use the `FakeClient`
to fail the first attempt and succeed on the second; confirm your loop recovers.

**8.2 (stretch)** Add a structured log line for every tool call (name, duration, ok/error),
then run with `--model <something>` and read your logs to reconstruct exactly what happened.

<details><summary>Hint</summary>

8.1: backoff = sleep 1s, 2s, 4s… between attempts; the `FakeClient` (in
`code/agent_harness/testing.py`) lets you script failures offline. 8.2: this is the
observability section of Phase 8 — logs are how you see *inside* a run.
</details>

---

## Capstone

Combine everything: point your Phase-8 harness at a small real repository and give it a
genuine task ("add a docstring to every function in `foo.py` and run the tests"). Watch the
loop read, edit, run `bash`, hit the permission gate, and stay within its context budget.
If it does that end-to-end, you've built — and understood — a coding agent from scratch.

> Found an exercise that was too easy, too hard, or unclear? That's signal for the
> standing goal — see [`ROADMAP.md`](./ROADMAP.md).
