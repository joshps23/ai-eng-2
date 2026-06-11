[← Phase 5: Permissions, Safety & the Hook System](./05-permissions-and-safety.md) · [Guide index](./README.md) · [Phase 7: Sub-Agents & Orchestration →](./07-subagents-orchestration.md)

# Phase 6 — Context Management: Token Budgeting & Compaction

> **Series context:** Phases 0–5 built a complete, safe single-agent harness: the loop,
> a typed tool system, streaming and conversation management, real file/shell tools, and
> a permission layer in front of them. One resource is still unmanaged: the **context
> window** itself. This phase adds the budgeting and compaction machinery that lets a
> session run for an hour instead of ten minutes.

Every model has a finite context window. In a toy demo that window is plenty; in a real agentic session — many tool calls, large file reads, multi-step plans, long reasoning traces — you will exceed it. When that happens you get one of three failure modes: an API error (hard limit breached), silently dropped instructions (the model just forgets the system prompt), or "context rot" — degraded output quality as the signal-to-noise ratio in the window falls. None of those is acceptable for a harness meant to run for an hour.

This phase adds active context management to the harness: token counting, a configurable budget, several compaction strategies in order of sophistication, and automatic triggering inside the agent loop.

---

> ## 🟢 Beginner track: one idea, three tactics — all plain functions
>
> Good news: this phase adds **no classes and no decorators**. It's all functions that
> take your `input_items` **list** and return a smaller list. The single idea:
>
> > The conversation list keeps growing. The model can only read so much at once. So
> > before each call, **make the list smaller** if it's getting too big.
>
> Three tactics, simplest first:
>
> 1. **Clip** — chop down a single huge tool result *before* you add it to the list
>    (`clip_output`). Just a string slice.
> 2. **Drop oldest** — when the list is too long, remove the oldest items
>    (`prune_to_budget`). Like `del items[0]`, with one rule: a `function_call` and its
>    matching `function_call_output` must be removed *together* (the API rejects a
>    lonely half). That pairing rule is the only reason this code looks fiddly.
> 3. **Summarize** — ask the model to write a short summary of the old part, then
>    replace the old items with that one summary (`compact`). It's a normal
>    `client.responses.create(...)` call — the same API you already know.
>
> A few syntax heads-ups so nothing surprises you:
>
> - **`count_tokens(text)`** is basically `len(text) // 4` — a "token" is roughly 4
>   characters. The [`tiktoken`](./09-library-reference.md#2-tiktoken--local-token-counting)
>   library just makes that estimate exact; if it isn't
>   installed, the code falls back to the divide-by-4 version. Tokens are the unit the
>   model's limit is measured in.
> - **`def f(items, *, keep_last_n=6)`** — the bare `*` only forces `keep_last_n` to be
>   passed *by name* (`f(items, keep_last_n=10)`). Ignore the `*`; it changes nothing
>   about what the function does.
> - **`sum(count_tokens(t) for t in ...)`** and **`" ".join(... for ...)`** are
>   comprehension-style one-liners (see the [Phase 1 box](./01-bare-harness.md)): a loop
>   that adds up / joins values. Mentally expand them to a `for` loop if clearer.
> - **`isinstance(x, list)`** just asks "is `x` a list?" — `True`/`False`.
>
> With those, every function here reads as ordinary Python. Focus on the *idea* of each
> of the three tactics; you don't need to trace the index-juggling in `prune_to_budget`
> to use it.
>
> The steps below follow this same order — **simplest demo first**, one tactic per step.
>
> **How the phase is organized:** four complete, runnable versions of the *same*
> harness, each one rung more organized than the last. **Version 1** is a straight-line
> script (no `def`, no classes) with the token estimate and a naive drop-oldest right
> inside the loop. **Version 2** is the same harness with `count_tokens` and
> `prune_to_budget` as plain functions — plus the two correctness rules the naive
> version is missing. **Version 3** moves those functions into a `context.py` module the
> loop consults each turn (and upgrades counting and clipping). **Version 4** adds
> tactic 3, `compact`. You can stop and run the harness at every rung.

---

## How this phase climbs (the version ladder)

| Version | Shape | What it adds |
|---|---|---|
| **V1 — line-by-line** | One straight-line file, no `def` | An inline `len(str(item)) // 4` estimate printed every turn, and a naive "pop the oldest item" truncation — with two bugs deliberately left in so you can feel them |
| **V2 — functions** | Same harness, plain functions | `count_tokens` / `count_items` / `prune_to_budget`, with the two correctness rules: pairs travel together, and the first user message is never dropped |
| **V3 — organized** | A `context.py` module the loop consults | Exact counting via `tiktoken`, budget constants, `clip_output`, a recency window for pruning |
| **V4 — `compact`** | Same module, one more function | Model-written summaries replace the older half of the transcript — spending one API call to buy back context |

Each version is **the same harness, reorganized** — between versions there's a short
"what changed" list so you can see the reorganization rather than re-learn the program.

**Contents:**

- [The problem in numbers](#the-problem-in-numbers)
- [Version 1 — line-by-line: watch the window fill up](#version-1--line-by-line-watch-the-window-fill-up)
- [Version 2 — functions: `count_tokens` and `prune_to_budget`](#version-2--functions-count_tokens-and-prune_to_budget)
- [Version 3 — the organized form: a `context.py` module](#version-3--the-organized-form-a-contextpy-module-the-loop-consults)
- [Version 4 — `compact`: spend one API call to buy back context](#version-4--compact-spend-one-api-call-to-buy-back-context)
- [Beyond the ladder: keep tokens out of the window entirely](#beyond-the-ladder-keep-tokens-out-of-the-window-entirely)
- [Persistent memory across sessions](#persistent-memory-across-sessions)
- [The production shape: full `context.py`](#the-production-shape-full-contextpy)

> **Prefer running this phase as a notebook?** [`notebooks/06-context-management.ipynb`](./notebooks/06-context-management.ipynb) executes this phase's checkpoints offline — see [notebooks/README.md](./notebooks/README.md).

---

## The Problem in Numbers

A model with a 128 k-token window sounds enormous, but consider a session where:

- The system instructions are 800 tokens.
- Every round-trip adds an average of 600 tokens (user message + assistant response).
- One `read_file` call on a medium-sized source file returns 3 000 tokens of content.
- A `run_command("pytest --verbose")` returns 2 000 tokens of output.

After 20 such round-trips the running input total is roughly:

```
800 (system) + 20 × 600 (chat) + 10 × 3 000 (files) + 5 × 2 000 (commands)
= 800 + 12 000 + 30 000 + 10 000
= 52 800 tokens
```

That is already 41 % of a 128 k window — and the session has only begun. Without management the harness will eventually fail.

---

## Version 1 — line-by-line: watch the window fill up

No `def`, no classes — the whole harness straight down the page, with the token
estimate and the truncation written inline where they run. First a tiny offline warm-up
so you can see the *growth* without an API key, then the real harness.

### Step 1.1 — Feel the growth (no API key needed)

Before writing any strategy, let's see the problem in concrete numbers. Run this
self-contained script — it needs only the Python standard library, and like everything
in Version 1 it is **straight-line code**: no `def`, no classes, just statements top to
bottom. (Giving these fragments names is exactly what Version 2 will do.)

```python
# demo_context_problem.py
# Run with: python demo_context_problem.py
# No def, no classes — straight down the page.

transcript = []

# Pretend each "turn" adds a user message and an assistant reply.
# We'll simulate 8 turns with a short user question and a longer assistant answer.
for turn in range(1, 9):
    transcript.append({
        "type": "message", "role": "user",
        "content": f"Turn {turn}: what should we do next?",
    })
    transcript.append({
        "type": "message", "role": "assistant",
        "content": (
            f"Turn {turn}: here is my plan. "
            + "Step one, do this. Step two, do that. Step three, check the result. " * 20
        ),
    })

    # Inline token estimate: ~4 characters per token, summed over every item.
    total = 0
    for item in transcript:
        total += len(item["content"]) // 4
    print(f"After turn {turn}: {len(transcript)} items, ~{total} tokens in transcript")
```

### ▶ Run it now (no API key needed)

```bash
python demo_context_problem.py
```

You should see:

```
After turn 1: 2 items, ~353 tokens in transcript
After turn 2: 4 items, ~706 tokens in transcript
After turn 3: 6 items, ~1059 tokens in transcript
...
After turn 8: 16 items, ~2824 tokens in transcript
```

The transcript grows every turn — linearly here, and faster in real sessions, where
tool outputs (file reads, test logs) add thousands of tokens at a time. You hit limits
fast.

#### The simplest fix: drop oldest turns when over a budget

Now trim the list, in the same inline style: a `while` loop that pops the oldest item
until the total fits. Still no `def` — just list operations.

```python
# demo_context_problem.py  (continued — append these lines and re-run)

TOKEN_BUDGET = 1000   # tiny budget so we can see truncation fire

# Re-estimate the total (same inline arithmetic as above).
total = 0
for item in transcript:
    total += len(item["content"]) // 4
print(f"\nBefore pruning: {len(transcript)} items, ~{total} tokens")

# Naive truncation: treat every item as independent and pop from the front.
# (No pairing rules yet — Version 2 adds them, and Step 1.3 shows why we must.)
dropped_count = 0
while transcript and total > TOKEN_BUDGET:
    dropped = transcript.pop(0)            # drop the oldest item
    total -= len(dropped["content"]) // 4
    dropped_count += 1

print(f"After  pruning: {len(transcript)} items, ~{total} tokens")
print(f"Dropped {dropped_count} items to stay under {TOKEN_BUDGET} tokens")
```

### ▶ Run it now (no API key needed)

Same file — just append the lines above and re-run:

```bash
python demo_context_problem.py
```

Expected output (after the growth lines):

```
Before pruning: 16 items, ~2824 tokens
After  pruning: 4 items, ~706 tokens
Dropped 12 items to stay under 1000 tokens
```

**That's the whole idea.** Everything in the rest of this phase is a refinement:
counting tokens more accurately, handling the pairing rule, summarising instead of
discarding, and wiring it into the agent loop.

### Step 1.2 — The same idea inside the real harness

**Why now?** The warm-up faked the transcript. The real pain only shows up when the
transcript is fed back to `client.responses.create(...)` every turn — so let's put the
estimate and the truncation *inside* the harness from Phase 1, written inline, no `def`
at all. The only tool is `read_file`, because reading files is the fastest way to blow
a token budget.

Paste this whole file as `harness_v1.py`:

```python
# harness_v1.py — Phase 6, Version 1: the whole harness straight down the page.
# No def, no classes. New this phase: the [context] lines inside the loop.
import json
from openai import OpenAI

client = OpenAI()                  # reads OPENAI_API_KEY from the environment
MODEL = "gpt-4o"
TOKEN_BUDGET = 800                 # absurdly small ON PURPOSE — we want to SEE truncation fire

READ_FILE_SCHEMA = {
    "type": "function",
    "name": "read_file",
    "description": "Read a UTF-8 text file and return its contents.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to read."}
        },
        "required": ["path"],
    },
}

input_items = []

print("Context-aware harness v1 — type 'exit' to quit.")
while True:
    user_text = input("\nyou> ").strip()
    if user_text.lower() in ("exit", "quit"):
        break
    input_items.append({"role": "user", "content": user_text})

    while True:                                    # inner loop: one user turn
        # ── context management, written inline ──────────────────────────────
        estimated = 0
        for item in input_items:
            estimated += len(str(item)) // 4       # ~4 characters per token
        print(f"[context] ~{estimated} tokens across {len(input_items)} item(s)")

        while estimated > TOKEN_BUDGET and len(input_items) > 1:
            dropped = input_items.pop(0)           # naive: drop the oldest item
            estimated -= len(str(dropped)) // 4
            print(f"[context] over budget ({TOKEN_BUDGET}) — dropped oldest item")
        # ─────────────────────────────────────────────────────────────────────

        resp = client.responses.create(
            model=MODEL,
            input=input_items,
            tools=[READ_FILE_SCHEMA],
        )
        input_items += resp.output                 # carry the model's items forward

        tool_calls = [item for item in resp.output if item.type == "function_call"]
        if not tool_calls:                         # no tool calls → final answer
            print("agent>", resp.output_text)
            break                                  # turn done — back to input()

        for tc in tool_calls:
            args = json.loads(tc.arguments)
            if tc.name == "read_file":
                try:
                    result = open(args["path"], encoding="utf-8").read()
                except OSError as exc:
                    result = f"Error: {exc}"
            else:
                result = f"Error: unknown tool '{tc.name}'"
            print(f"[tool] {tc.name}({tc.arguments}) → {len(result)} chars")
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,             # echo the SAME call_id back
                "output": result,                  # must be a string
            })
```

The harness is exactly Phase 1's loop; the *only* new code is the block between the
`──` rules: estimate the transcript size, print it, and pop the oldest item while over
budget.

### ▶ Run it now

```bash
echo "The launch checklist: 1) freeze the schema. 2) tag the release. \
3) run the smoke tests twice. 4) page the on-call before deploying." > notes.txt
python harness_v1.py
```

(No `OPENAI_API_KEY` set? The script dies immediately at `client = OpenAI()` with a raw
`openai.OpenAIError: Missing credentials` traceback — that's expected, and it applies to
every key-requiring script in Phases 6–8. See Phase 0's "No API key?" box for how to
follow these checkpoints keyless.)

Then have a conversation that involves the file:

```
you> Read notes.txt and tell me what step 3 is.
[context] ~16 tokens across 1 item(s)
[tool] read_file({"path":"notes.txt"}) → 142 chars
[context] ~213 tokens across 4 item(s)
agent> Step 3 is to run the smoke tests twice.

you> Great. Now explain why smoke tests matter, in detail.
[context] ~244 tokens across 5 item(s)
agent> ...
```

Watch the `[context] ~N tokens` line **grow every single turn** — that's the whole
problem of this phase, live on your screen. Keep chatting (or point `read_file` at a
bigger file) until the estimate crosses 800 and you see
`[context] over budget (800) — dropped oldest item` fire.

### Step 1.3 — Make the pain visible: two planted bugs

Version 1 *works*, but its naive `pop(0)` has two failure modes you can reproduce:

1. **It forgets the goal.** The first thing dropped is your *first user message* — which
   usually states the task. After a few truncations, ask `you> What did I originally ask
   you to do?` and watch the model guess (or apologize). The transcript literally no
   longer contains the answer.
2. **It can corrupt the transcript.** `pop(0)` doesn't know that a `function_call` and
   its `function_call_output` are a matched pair. If truncation pops the call but the
   budget is satisfied before it reaches the output, the next API call sends an
   *orphaned* `function_call_output` — and the API rejects the whole request with a
   `400` validation error. With the tiny budget above and a couple of `read_file` calls,
   you can crash the harness this way in under a minute.

Both bugs come from the same root cause: the truncation treats the transcript as a flat
list of interchangeable items, when really it has *structure* (a pinned goal, and pairs
that must travel together). Encoding that structure is exactly what Version 2 does.

---

## Version 2 — functions: `count_tokens` and `prune_to_budget`

### What changed from V1 to V2

- The inline estimate gets a name: `count_tokens(text)` plus `count_items(items)` for a
  whole transcript — same `// 4` arithmetic, now callable and testable on its own.
- The naive `pop(0)` loop becomes `prune_to_budget(items, budget)`, a pure function
  that returns a new list instead of mutating in place.
- **Rule 1 added:** a `function_call` and its `function_call_output` are grouped and
  dropped *together* — no more orphaned-item `400` errors.
- **Rule 2 added:** the *first user message* is pinned and never dropped — the agent
  keeps its goal no matter how much else is shed.
- The model's output items are normalized to plain dicts with `.model_dump()` as they
  are appended, so the functions only ever deal with one shape of item.
- Nothing else moves: same tool, same loop, same prints — the same harness, reorganized.

Still no classes. We lift the three inline fragments into three plain functions and fix
both planted bugs. These are the same two correctness rules the production package
enforces in `code/agent_harness/context.py`.

### Step 2.1 — Name the estimate: `count_tokens` and `count_items`

**Why now?** Once the estimate is a function, you can test it offline, swap in a better
implementation later (V3 does), and reuse it inside `prune_to_budget`.

```python
import json

def count_tokens(text):
    """Rough estimate: ~4 characters per token."""
    return max(1, len(text) // 4)

def count_items(items):
    """Token estimate for a whole transcript (a list of plain dicts)."""
    return sum(count_tokens(json.dumps(item)) for item in items)
```

> 🟢 `json.dumps(item)` turns a dict into its JSON text so we can measure its length.
> For this to work on *every* item, the harness below converts the SDK objects in
> `resp.output` to plain dicts with **`item.model_dump()`** as it appends them — the
> same normalization trick `Conversation.to_input()` uses in Phase 3. (The tested
> package's `conversation.py` spells the same method `to_input_dict()`.)

### ▶ Run it now (no API key needed)

```python
items = [{"role": "user", "content": "hello"},
         {"role": "assistant", "content": "Hi! " * 50}]
print(count_items(items))    # 68 — a number, instantly, no API
```

### Step 2.2 — Rule 1: pairs travel together

**Why now?** This is the fix for the `400` crash. Instead of dropping *items*, we drop
*groups*: a `function_call` and its matching `function_call_output` (same `call_id`)
form one group; everything else is a group of one. A group either survives whole or is
dropped whole — the API can never see half a pair.

```python
def group_items(items):
    """Split the transcript into groups that must survive or be dropped TOGETHER.

    Rule 1: a function_call and its matching function_call_output (same
    call_id) form one group — the API rejects an input that contains one
    half without the other. Everything else is a group of one.
    """
    groups = []
    i = 0
    while i < len(items):
        item = items[i]
        if item.get("type") == "function_call":
            call_id = item.get("call_id", "")
            j = i + 1
            while j < len(items):
                other = items[j]
                if (other.get("type") == "function_call_output"
                        and other.get("call_id") == call_id):
                    break
                j += 1
            if j < len(items):                   # found the matching output
                groups.append(items[i:j + 1])    # call … output, one group
                i = j + 1
                continue
        groups.append([item])                    # ordinary item — group of one
        i += 1
    return groups
```

### Step 2.3 — Rule 2: keep the first user message — `prune_to_budget`

**Why now?** This is the fix for the forgotten goal. While dropping old groups, we
*pin* the first group that contains a user message — it usually states the task, and an
agent that forgets its task is useless.

```python
def prune_to_budget(items, budget):
    """Drop the OLDEST groups until the transcript fits the budget.

    Rule 1: pairs travel together (enforced by group_items).
    Rule 2: the FIRST user message is never dropped — it usually states the
            goal, and an agent that forgets its goal is useless.

    Returns a new list; the list you pass in is not modified.
    """
    groups = group_items(items)

    # Find the first group that contains a user message — pin it (rule 2).
    pinned = None
    for gi, group in enumerate(groups):
        if any(member.get("role") == "user" for member in group):
            pinned = gi
            break

    total = sum(count_items(group) for group in groups)
    kept = list(groups)
    for gi in range(len(groups)):
        if total <= budget:
            break
        if gi == pinned:
            continue
        total -= count_items(kept[gi])
        kept[gi] = None                          # mark dropped

    return [item for group in kept if group is not None for item in group]
```

### ▶ Run it now (no API key needed)

Verify both rules offline:

```python
# Build a transcript: one goal message, then five tool round-trips.
items = [{"role": "user", "content": "Refactor the billing module."}]
for i in range(5):
    cid = f"call_{i}"
    items.append({"type": "function_call", "call_id": cid, "name": "read_file",
                  "arguments": f'{{"path": "file{i}.py"}}'})
    items.append({"type": "function_call_output", "call_id": cid,
                  "output": "x = 1\n" * 200})

print(f"Before: {len(items)} items, ~{count_items(items)} tokens")
pruned = prune_to_budget(items, budget=500)
print(f"After:  {len(pruned)} items, ~{count_items(pruned)} tokens")

# Rule 1: every remaining call still has its output (no orphans)
calls   = {it["call_id"] for it in pruned if it.get("type") == "function_call"}
outputs = {it["call_id"] for it in pruned if it.get("type") == "function_call_output"}
assert calls == outputs, "Orphaned tool call/output detected!"

# Rule 2: the first user message survived
assert pruned[0]["role"] == "user", "The goal was dropped!"
print("Both rules hold: no orphans, goal preserved.")
```

Expected output (numbers will vary slightly):

```
Before: 11 items, ~1980 tokens
After:  3 items, ~410 tokens
Both rules hold: no orphans, goal preserved.
```

### Step 2.4 — The full Version 2 file

Here is the complete harness with the three functions in place of the inline block.
The loop body is character-for-character the spirit of Version 1; only the marked lines
changed.

```python
# harness_v2.py — Phase 6, Version 2: the same harness, reorganized into functions.
import json
from openai import OpenAI

client = OpenAI()
MODEL = "gpt-4o"
TOKEN_BUDGET = 800                 # still tiny on purpose


# ── context management as plain functions ────────────────────────────────────

def count_tokens(text):
    """Rough estimate: ~4 characters per token."""
    return max(1, len(text) // 4)


def count_items(items):
    """Token estimate for a whole transcript (a list of plain dicts)."""
    return sum(count_tokens(json.dumps(item)) for item in items)


def group_items(items):
    """Split the transcript into groups that must survive or be dropped TOGETHER."""
    groups = []
    i = 0
    while i < len(items):
        item = items[i]
        if item.get("type") == "function_call":
            call_id = item.get("call_id", "")
            j = i + 1
            while j < len(items):
                other = items[j]
                if (other.get("type") == "function_call_output"
                        and other.get("call_id") == call_id):
                    break
                j += 1
            if j < len(items):
                groups.append(items[i:j + 1])
                i = j + 1
                continue
        groups.append([item])
        i += 1
    return groups


def prune_to_budget(items, budget):
    """Drop oldest groups until under budget. Pairs travel together (rule 1);
    the first user message is never dropped (rule 2)."""
    groups = group_items(items)

    pinned = None
    for gi, group in enumerate(groups):
        if any(member.get("role") == "user" for member in group):
            pinned = gi
            break

    total = sum(count_items(group) for group in groups)
    kept = list(groups)
    for gi in range(len(groups)):
        if total <= budget:
            break
        if gi == pinned:
            continue
        total -= count_items(kept[gi])
        kept[gi] = None

    return [item for group in kept if group is not None for item in group]


# ── the one tool ──────────────────────────────────────────────────────────────

READ_FILE_SCHEMA = {
    "type": "function",
    "name": "read_file",
    "description": "Read a UTF-8 text file and return its contents.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to read."}
        },
        "required": ["path"],
    },
}


def read_file(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError as exc:
        return f"Error: {exc}"


# ── the loop (same shape as Version 1) ────────────────────────────────────────

input_items = []

print("Context-aware harness v2 — type 'exit' to quit.")
while True:
    user_text = input("\nyou> ").strip()
    if user_text.lower() in ("exit", "quit"):
        break
    input_items.append({"role": "user", "content": user_text})

    while True:
        print(f"[context] ~{count_items(input_items)} tokens "
              f"across {len(input_items)} items")
        input_items = prune_to_budget(input_items, TOKEN_BUDGET)   # ← CHANGED

        resp = client.responses.create(
            model=MODEL,
            input=input_items,
            tools=[READ_FILE_SCHEMA],
        )
        # Normalize SDK objects to plain dicts as we append them.   ← CHANGED
        input_items += [item.model_dump() for item in resp.output]

        tool_calls = [item for item in resp.output if item.type == "function_call"]
        if not tool_calls:
            print("agent>", resp.output_text)
            break

        for tc in tool_calls:
            args = json.loads(tc.arguments)
            if tc.name == "read_file":
                result = read_file(**args)
            else:
                result = f"Error: unknown tool '{tc.name}'"
            print(f"[tool] {tc.name}({tc.arguments}) → {len(result)} chars")
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })
```

### ▶ Run it now

```bash
python harness_v2.py
```

Repeat the Version 1 experiment: read `notes.txt`, chat past the budget, then ask
`you> What did I originally ask you to do?` This time the model **answers correctly** —
the pinned first message survived pruning — and no amount of truncation can produce the
orphaned-pair `400` error.

One rough edge remains, and it's worth seeing: with a brutally small budget, pruning can
drop the tool round-trip the model *just* made — there's no notion of "recent items are
precious" yet. Version 3 fixes that with a recency window.

---

## Version 3 — the organized form: a `context.py` module the loop consults

### What changed from V2 to V3

- The functions move out of the harness file into their own **`context.py` module**;
  the loop just imports and consults it before every API call — the same shape the
  `agent_harness` package uses.
- `count_tokens` is upgraded from `// 4` to **`tiktoken`** (exact, with a graceful
  fallback to the heuristic when offline).
- Magic numbers become named **budget constants** derived from the model's real window
  (`MAX_CONTEXT_TOKENS`, `RESPONSE_RESERVE`, `INPUT_BUDGET`, `COMPACT_TRIGGER`).
- A new tactic, **`clip_output`**, bounds each tool result *before* it ever enters the
  transcript — the cheapest token is the one you never store.
- `prune_to_budget` gains a **recency window** (`keep_last_n`) so the freshest items —
  including the tool round-trip in flight — are never shed.
- After each call, `resp.usage` provides **ground-truth token counts** to check the
  estimate against.

Nothing conceptually new at this rung — it's Version 2's functions, *organized*: moved
into a module, hardened with exact counting, named constants, clipping, and a recency
window. This is the shape the production package uses (`agent_harness/context.py`),
where the `Agent` consults the context helpers at the top of every turn.

### Step 3.1 — Counting Tokens exactly: `tiktoken` with a tiered fallback

The API returns ground-truth token counts in `resp.usage` after each call, but we also need *local* estimates to decide whether to compact *before* the next API call.

First, install tiktoken — this step is **optional**: as the next paragraph explains, the
code below falls back to the divide-by-4 heuristic whenever tiktoken is missing or you
are offline, so you can skip the install and keep going:

```text
pip install tiktoken
```

`tiktoken` implements the same byte-pair encoding the OpenAI models use, so its counts match the API exactly (within rounding). (Its full API — the encodings, the lazy vocabulary download, the robust fallback pattern — is documented in the [Appendix's tokenizer section](./09-library-reference.md#2-tiktoken--local-token-counting).)

**Why now?** Versions 1 and 2 used `len(text) // 4`. That's good enough for experimentation, but
for a real harness you want exact counts so you don't compact too late. This function
uses `tiktoken` when installed, and falls back to the divide-by-4 heuristic otherwise —
so the code works offline or without the extra dependency.

```python
# context.py  (start of file)
from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Token counting — tiktoken if available, else heuristic (4 chars ≈ 1 token)
# ---------------------------------------------------------------------------

def _heuristic(text: str) -> int:
    # Dependency-free fallback: empirically ~4 characters per token across
    # English prose and code.  Overestimates slightly, which is the safe
    # direction (we compact a little earlier than strictly necessary).
    return max(1, len(text) // 4)


try:
    import tiktoken

    def _get_encoding():
        """Return an encoding for current-generation OpenAI models, or None.

        IMPORTANT: the FIRST time an encoding is used, tiktoken downloads the
        vocabulary file over the network. encoding_for_model can raise KeyError
        for an unknown model name, but the download can raise *other* errors
        (e.g. requests.ConnectionError/HTTPError) when offline. We catch
        broadly and return None so we fall back to the heuristic instead of
        crashing the whole import.
        """
        try:
            try:
                enc = tiktoken.encoding_for_model("gpt-4o")
            except KeyError:
                enc = tiktoken.get_encoding("o200k_base")
            enc.encode("warmup")  # force the lazy download to happen here
            return enc
        except Exception:
            return None

    _ENC = _get_encoding()

    def count_tokens(text: str) -> int:
        """Return the BPE token count, or the heuristic if tiktoken is unusable."""
        if _ENC is None:
            return _heuristic(text)
        return len(_ENC.encode(text))

except ImportError:
    def count_tokens(text: str) -> int:  # type: ignore[misc]
        return _heuristic(text)
```

> 🟢 The comment `# type: ignore[misc]` is for **type checkers only** — Python itself
> ignores it. It silences the checker's complaint that `count_tokens` is defined twice
> (once in the `try`, once in the `except`); at runtime exactly one of the two
> definitions exists, which is the whole point of the fallback.

### Step 3.2 — `count_items` — serialise the transcript

The transcript is a list of dicts. We serialize each item to a compact JSON string, count its tokens, and sum.

```python
def _item_to_text(item: dict[str, Any]) -> str:
    """Produce a text representation of one transcript item for token counting."""
    item_type = item.get("type", "")

    if item_type == "message":
        # {"type": "message", "role": "user"|"assistant", "content": ...}
        content = item.get("content", "")
        if isinstance(content, list):
            # Content may be a list of content blocks
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", "") or json.dumps(block))
                else:
                    parts.append(str(block))
            content = " ".join(parts)
        return f"{item.get('role', '')}: {content}"

    if item_type == "function_call":
        return f"function_call {item.get('name', '')} {json.dumps(item.get('arguments', ''))}"

    if item_type == "function_call_output":
        return f"function_call_output {item.get('call_id', '')} {item.get('output', '')}"

    if item_type == "reasoning":
        # Reasoning items may have a list of summary objects or a text field
        summary = item.get("summary", [])
        if isinstance(summary, list):
            return " ".join(s.get("text", "") for s in summary if isinstance(s, dict))
        return str(summary)

    # Fallback: dump the whole thing
    return json.dumps(item)


def count_items(items: list[dict[str, Any]]) -> int:
    """Estimate the token count of a list of transcript items."""
    return sum(count_tokens(_item_to_text(item)) for item in items)
```

### Step 3.3 — Ground truth from `resp.usage` and running totals

After every API call, reconcile the estimate with reality and update a running total.

```python
# In your agent loop (agent.py):

total_input_tokens  = 0
total_output_tokens = 0

# ... inside the loop, after client.responses.create() returns:
total_input_tokens  += resp.usage.input_tokens
total_output_tokens += resp.usage.output_tokens

print(
    f"[tokens] this turn: {resp.usage.input_tokens} in / "
    f"{resp.usage.output_tokens} out | "
    f"session total: {total_input_tokens} in / {total_output_tokens} out"
)
```

The per-call `input_tokens` count IS the true size of the full input the API processed (including system instructions, tools schema, all transcript items). Use it, not a cumulative sum across turns, for the most accurate picture of context pressure.

### Step 3.4 — Budget constants

```python
# context.py — budget constants (tune per deployment)

# Hard model limit — set to your actual model's context window.
MAX_CONTEXT_TOKENS = 128_000

# Reserve this many tokens for the model's next *output* so we never
# overflow even if the response is verbose.
RESPONSE_RESERVE = 4_096

# Usable input budget = max window − response reserve.
INPUT_BUDGET = MAX_CONTEXT_TOKENS - RESPONSE_RESERVE  # 123 904

# Compact when input usage exceeds this fraction of the input budget.
# 0.75 gives a comfortable cushion for the compaction call itself.
COMPACT_THRESHOLD = 0.75
COMPACT_TRIGGER = int(INPUT_BUDGET * COMPACT_THRESHOLD)  # ~92 928
```

The strategies below are ordered from simplest to most powerful. Use them in layers: apply an earlier strategy before reaching for the next.

### Step 3.5 — Tactic A: Clip Tool Output at the Source

**Why now?** The cheapest token to save is the one that never enters the transcript.
Before you think about compacting history, ensure each individual tool result is
bounded. A `pytest --verbose` run can easily return 10 000+ characters; if you clip it
to 2 000 tokens at the point of collection, your transcript stays lean from the start.

Already covered in Phase 4, but the rule of thumb: **clip tool output to the first N tokens before appending it as a `function_call_output` item.** If the agent needs more it can call the tool again with a narrower query.

```python
MAX_TOOL_OUTPUT_TOKENS = 2_000  # per tool call

def clip_output(text: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    """Truncate tool output so it does not bloat the transcript."""
    if count_tokens(text) <= max_tokens:
        return text
    # Binary-search style: approximate character limit then trim
    char_limit = max_tokens * 4
    clipped = text[:char_limit]
    return clipped + f"\n... [output truncated to ~{max_tokens} tokens]"
```

### ▶ Check it now (no API key needed)

```python
# Quick test — no API needed
long_output = "line of output\n" * 1000   # ~3 750 tokens
safe_output = clip_output(long_output)
print(f"Original: ~{count_tokens(long_output)} tokens")
print(f"Clipped:  ~{count_tokens(safe_output)} tokens")
print("Last line:", safe_output.splitlines()[-1])
```

Expected output (with the heuristic counter — exact numbers vary slightly with
tiktoken installed):

```
Original: ~3750 tokens
Clipped:  ~2009 tokens
Last line: ... [output truncated to ~2000 tokens]
```

**Tradeoff:** The agent may miss information present later in long outputs. Mitigate by having the agent request page ranges or grep patterns rather than whole files.

### Step 3.6 — Tactic B: Sliding Window / Recency Pruning

**Why now?** Clipping handles large individual results, but the transcript still grows
turn-by-turn from normal conversation. Version 2's `prune_to_budget` already enforces
the pairing rule and pins the first user message — but it will happily drop the tool
round-trip the model made *seconds ago*. This production form adds a **recency window**
(`keep_last_n`): the newest items are protected outright, along with any pair partner
that reaches into the window. (When you adopt this form, keep Version 2's
first-user-message pin too — the package version does both.)

When the transcript is already large, drop the oldest items — but with two hard constraints:

1. **Never drop the system instructions** (they live outside `input_items` in the `instructions` field, so they are safe as long as you do not embed them in items).
2. **Never drop a `function_call` without its matching `function_call_output`**, or vice-versa — the API will reject the request with a validation error.

```python
# context.py

def _paired_indices(items: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """
    Map each call_id to the (function_call_index, function_call_output_index)
    pair within *items*.  Only call_ids where BOTH items are present are included.
    """
    fc_idx: dict[str, int] = {}
    fco_idx: dict[str, int] = {}

    for i, item in enumerate(items):
        t = item.get("type")
        cid = item.get("call_id") or item.get("id")
        if t == "function_call" and cid:
            fc_idx[cid] = i
        elif t == "function_call_output" and cid:
            fco_idx[cid] = i

    return {
        cid: (fc_idx[cid], fco_idx[cid])
        for cid in fc_idx
        if cid in fco_idx
    }


def prune_to_budget(
    items: list[dict[str, Any]],
    budget: int,
    *,
    keep_last_n: int = 6,
) -> list[dict[str, Any]]:
    """
    Drop the oldest items from *items* until ``count_items(items) <= budget``,
    subject to:

    - The last *keep_last_n* items are never dropped (recency guarantee).
    - A ``function_call`` and its ``function_call_output`` are always dropped
      together; neither is dropped without the other.
    - Items with no natural pair (orphaned tool calls, plain messages) may be
      dropped individually once they fall outside the recency window.

    When only protected items remain, pruning stops — so the result may still
    exceed *budget*. The recency guarantee outranks the budget target.

    Returns a new list; does not mutate *items*.
    """
    if count_items(items) <= budget:
        return list(items)

    # Build a set of indices protected by the recency window.
    protected: set[int] = set(range(max(0, len(items) - keep_last_n), len(items)))

    # Also protect each half of any pair that is itself protected.
    pairs = _paired_indices(items)
    for cid, (fi, foi) in pairs.items():
        if fi in protected or foi in protected:
            protected.add(fi)
            protected.add(foi)

    # Walk from the front; drop items that are not protected.
    result = list(items)
    i = 0
    while i < len(result) and count_items(result) > budget:
        # Recompute pairs over the *current* result list each iteration
        # (indices shift as we drop).
        if i in _protected_set(result, keep_last_n):
            i += 1
            continue

        item = result[i]
        t = item.get("type")
        cid = item.get("call_id") or item.get("id")

        if t == "function_call" and cid:
            # Find the paired output in result.
            partner = _find_output(result, cid)
            if partner is not None:
                result.pop(partner)  # remove output first (higher index)
                result.pop(i)       # then the call
                # Do NOT advance i — new item is now at position i.
                continue

        elif t == "function_call_output" and cid:
            # Find the paired call in result.
            partner = _find_call(result, cid)
            if partner is not None and partner < i:
                result.pop(i)       # output
                result.pop(partner) # call (lower index)
                i = partner         # re-examine from partner position
                continue

        # Plain message or unpaired item — safe to drop alone.
        result.pop(i)

    return result


# ---- helpers used by prune_to_budget ----

def _protected_set(items: list[dict[str, Any]], keep_last_n: int) -> set[int]:
    protected = set(range(max(0, len(items) - keep_last_n), len(items)))
    pairs = _paired_indices(items)
    for cid, (fi, foi) in pairs.items():
        if fi in protected or foi in protected:
            protected.add(fi)
            protected.add(foi)
    return protected


def _find_output(items: list[dict[str, Any]], call_id: str) -> int | None:
    for i, item in enumerate(items):
        if item.get("type") == "function_call_output" and (
            item.get("call_id") == call_id or item.get("id") == call_id
        ):
            return i
    return None


def _find_call(items: list[dict[str, Any]], call_id: str) -> int | None:
    for i, item in enumerate(items):
        if item.get("type") == "function_call" and (
            item.get("call_id") == call_id or item.get("id") == call_id
        ):
            return i
    return None
```

### ▶ Check it now (no API key needed)

```python
# Quick check — build a transcript with tool calls and prune it
items = []
for i in range(5):
    cid = f"call_{i}"
    items.append({"type": "function_call",        "call_id": cid, "name": "read_file",
                  "arguments": f'{{"path": "file{i}.py"}}'})
    items.append({"type": "function_call_output", "call_id": cid,
                  "output": "x = 1\n" * 200})   # ~100 tokens each

print(f"Before: {len(items)} items, ~{count_items(items)} tokens")
pruned = prune_to_budget(items, budget=200, keep_last_n=2)
print(f"After:  {len(pruned)} items, ~{count_items(pruned)} tokens")

# Verify all remaining tool calls have their output (no orphans)
calls  = {it["call_id"] for it in pruned if it["type"] == "function_call"}
outputs = {it["call_id"] for it in pruned if it["type"] == "function_call_output"}
assert calls == outputs, "Orphaned tool call/output detected!"
print("Pairing check passed — no orphaned tool calls.")
```

Expected output (with the heuristic counter; exact numbers shift a little if
`tiktoken` is installed):

```text
Before: 10 items, ~1595 tokens
After:  2 items, ~319 tokens
Pairing check passed — no orphaned tool calls.
```

Look closely: the result is **still over the 200-token budget** — and that is correct
behavior, not a bug. `keep_last_n=2` protects the final
`function_call`/`function_call_output` pair outright, and protected items can never be
dropped, so once only protected items remain, pruning stops even though the budget is
unmet. The budget is a *target*; the recency window is a *guarantee*; when the two
conflict, the window wins. (In the real harness this is the right trade: sending a
slightly-too-big input is recoverable, but orphaning the round-trip the model made one
second ago is not.)

**Tradeoff:** The agent loses access to the full history of what it did and why. For short-horizon tasks this is fine; for long-horizon tasks (e.g. refactoring an entire codebase) the agent may repeat work or contradict earlier decisions. That is where compaction comes in.

### Step 3.7 — The loop consults the module

**Why now?** This is the rung's payoff: the harness file shrinks back down because all
the context machinery lives in `context.py`. The loop's only job is to *ask* before
each call. (Compare with Version 2, where the functions sat in the same file — the same
idea, organized.)

```python
# harness_v3.py — the loop, now consulting context.py each turn
from context import INPUT_BUDGET, count_items, prune_to_budget, clip_output

# ... schema, read_file, input_items as in Version 2 ...

while True:
    estimated = count_items(input_items)
    print(f"[context] ~{estimated} est. input tokens")
    if estimated > INPUT_BUDGET:
        input_items = prune_to_budget(input_items, INPUT_BUDGET)

    resp = client.responses.create(
        model=MODEL,
        input=input_items,
        tools=[READ_FILE_SCHEMA],
    )
    # ... unchanged turn-processing from Version 2, except tool results
    # pass through clip_output(result) before being appended ...
```

### ▶ Run it now

Same conversation as before. With the real `INPUT_BUDGET` (≈124 k
tokens) pruning won't fire in a short chat; to watch the same truncation behavior as V2,
temporarily *replace the derived line* `INPUT_BUDGET = MAX_CONTEXT_TOKENS -
RESPONSE_RESERVE` in `context.py` with `INPUT_BUDGET = 800` — now with the recency
window keeping the latest round-trip intact. (Restore the derived line afterwards.)

---

## Version 4 — `compact`: spend one API call to buy back context

### What changed from V3 to V4

- One new function in `context.py`: **`compact(conversation, client, model)`** — it
  spends *one extra API call* asking the model to summarize the older portion of the
  transcript, then splices the summary in where those items used to be.
- A pair of carefully-written **summarisation prompts** (system + instruction) tell the
  summarizer exactly what a future turn will need: decisions, file paths, errors, TODOs.
- The `Conversation` class from Phase 3 gains a tiny **`replace_items()`** method so
  compaction can swap the transcript wholesale.
- The loop's pre-call check becomes two-tier: **compact at 75 % of budget** (preserve
  the gist), **prune as the fallback** (when the transcript is too short to compact).
- Information is now *summarized* instead of *discarded* — old turns survive as gist.

The phase's advanced rung. Pruning is free but lossy; compaction costs one API call and
a few seconds, and in exchange the agent *remembers* what it did. Same harness, one new
mechanism.

### Step 4.1 — Tactic C: Summarisation / Compaction

**Why now?** Pruning silently discards old turns. For a long task — one that may span
dozens of steps — you want the agent to *remember* key decisions, file paths it edited,
and errors it resolved, even after those items are too old to keep verbatim. Compaction
replaces the old turns with a dense model-generated summary, so the gist survives while
the bulk is shed.

This is the deep solution — the equivalent of Claude Code's `/compact` command. Instead of silently dropping old turns, you ask the model itself to distill the older portion of the transcript into a dense summary, then replace those items with the summary.

**Why let the model summarise?** Because it understands the semantics. A dumb truncation might drop "we decided to use PostgreSQL, not SQLite" while keeping ten lines of boilerplate; the model will prioritise what actually matters.

#### The summarisation prompt

```python
SUMMARIZATION_SYSTEM = """\
You are a precise technical summariser. You will be given a partial transcript \
of an AI agent session. Produce a compact structured summary that captures \
everything a continuation of that session needs to know. Do not editorialize. \
Be specific: use exact file paths, function names, error messages, and decisions \
rather than vague descriptions.
"""

SUMMARIZATION_INSTRUCTION = """\
Summarise the following agent session transcript into a single dense note. \
Include ALL of the following that are present:

1. **Current task** — the user's goal as stated and any refinements agreed so far.
2. **Key decisions** — architectural choices, technology choices, any explicit \
   "we decided to …" moments.
3. **Work completed** — files created or modified (list exact paths), commands \
   run and their outcomes, tests passed or failed.
4. **Important facts discovered** — error messages, surprising findings, \
   constraints uncovered.
5. **Open TODOs** — what the agent was about to do or has been asked to do next.
6. **Critical file paths / identifiers** — anything the agent will need to \
   reference going forward.

Format as terse bullet points under those headings. Do not include conversational \
filler. Omit any heading whose content is empty. Maximum 600 tokens.
"""
```

#### `compact()` — the full function

```python
# context.py  (continued)
#
# Deliberately NO module-level `import openai` here: compact() only ever
# *receives* an already-built client, so the type hint below is written as
# the string "openai.OpenAI". That keeps context.py importable — and all its
# offline functions usable — on a machine without the openai package. The
# consolidated listing at the end of this phase makes the same choice.

# Number of recent items to keep verbatim after compaction.
# These items will NOT be fed to the summariser — they stay intact.
KEEP_RECENT_VERBATIM = 10


def compact(
    conversation: "Conversation",
    client: "openai.OpenAI",
    model: str,
    *,
    keep_recent: int = KEEP_RECENT_VERBATIM,
) -> str:
    """
    Summarise the older portion of *conversation*'s transcript and replace it
    with a single compact summary item.

    Returns the summary text so the caller can log or inspect it.

    The *conversation* object is mutated in place.  Call ``conversation.save()``
    afterwards if persistence is enabled.

    Raises ``ValueError`` if there is nothing old enough to summarise
    (i.e. the transcript has fewer than ``keep_recent + 2`` items).
    """
    items = conversation.to_input()  # returns list[dict]

    if len(items) <= keep_recent + 1:
        raise ValueError(
            f"Transcript too short to compact: {len(items)} items, "
            f"need at least {keep_recent + 2}."
        )

    # Split: items to summarise vs items to keep verbatim.
    cutoff = len(items) - keep_recent
    to_summarise = items[:cutoff]
    to_keep = items[cutoff:]

    # Ensure we don't break a function_call / function_call_output pair across
    # the boundary.  If the last item in to_summarise is a function_call whose
    # output is the first item in to_keep, move the call into to_keep as well.
    while to_summarise and to_keep:
        last = to_summarise[-1]
        if last.get("type") == "function_call":
            cid = last.get("call_id") or last.get("id")
            first_keep = to_keep[0]
            if (
                first_keep.get("type") == "function_call_output"
                and (first_keep.get("call_id") == cid or first_keep.get("id") == cid)
            ):
                # Move the function_call into the verbatim section.
                to_keep.insert(0, to_summarise.pop())
        break  # Only need to check the boundary once.

    if not to_summarise:
        raise ValueError("Nothing left to summarise after boundary adjustment.")

    # Build the transcript text to feed the summariser.
    transcript_text = "\n\n".join(
        f"[{item.get('type', 'item')}] {_item_to_text(item)}"
        for item in to_summarise
    )

    summarise_input = [
        {
            "type": "message",
            "role": "user",
            "content": (
                SUMMARIZATION_INSTRUCTION
                + "\n\n---\n\n"
                + transcript_text
            ),
        }
    ]

    print("[compact] Calling model to summarise older transcript…")
    summary_resp = client.responses.create(
        model=model,
        instructions=SUMMARIZATION_SYSTEM,
        input=summarise_input,
    )

    # Extract the summary text from the response.
    summary_text = ""
    for out_item in summary_resp.output:
        if getattr(out_item, "type", None) == "message":
            for block in getattr(out_item, "content", []):
                if getattr(block, "type", None) == "output_text":
                    summary_text += block.text
    summary_text = summary_text.strip()

    if not summary_text:
        raise RuntimeError("Compaction produced an empty summary — aborting.")

    print(
        f"[compact] Summarised {len(to_summarise)} items → "
        f"{count_tokens(summary_text)} tokens. "
        f"Keeping {len(to_keep)} recent items verbatim."
    )

    # Build the replacement item — a user-role message marked as a summary note.
    summary_item: dict[str, Any] = {
        "type": "message",
        "role": "user",
        "content": (
            "[CONTEXT SUMMARY — earlier transcript compacted]\n\n"
            + summary_text
        ),
    }

    # Splice: replace old items with the summary, then append the recent items.
    new_items = [summary_item] + list(to_keep)
    conversation.replace_items(new_items)

    return summary_text
```

> 🟢 Read the body top to bottom and notice it's all moves you've made before: split a
> list with slicing, nudge the boundary so a pair isn't split (Version 2's rule 1
> again), build one `client.responses.create(...)` call, pull the text out of
> `resp.output`, and splice lists back together. The only *new* idea is **what** the
> call is for: one turn of API spend that shrinks every future turn.

#### Required addition to the `Conversation` class

`compact()` calls `conversation.replace_items(new_items)`. Add this method to the `Conversation` class from Phase 3:

```python
# conversation.py  (add to Conversation class)

def replace_items(self, new_items: list[dict]) -> None:
    """Replace the entire transcript with *new_items* (used by compaction)."""
    self._items.clear()
    self._items.extend(new_items)
```

### Step 4.2 — Auto-Compaction Trigger in the Agent Loop

Wire the check into the top of the agent loop so compaction happens automatically before the next API call, not after an error.

```python
# agent.py  (agent loop with context management integrated)

from context import (
    INPUT_BUDGET,
    COMPACT_TRIGGER,
    count_items,
    prune_to_budget,
    compact,
)

def run_agent(
    conversation: Conversation,
    client: openai.OpenAI,
    model: str,
    instructions: str,
    tools: list[dict],
    tool_registry: dict,
) -> None:
    total_input_tokens  = 0
    total_output_tokens = 0

    while True:
        # ------------------------------------------------------------------ #
        # Context management — check before every API call                   #
        # ------------------------------------------------------------------ #
        current_items = conversation.to_input()
        estimated_tokens = count_items(current_items)

        if estimated_tokens > COMPACT_TRIGGER:
            print(
                f"[context] Estimated input {estimated_tokens} tokens exceeds "
                f"compact trigger {COMPACT_TRIGGER}. Compacting…"
            )
            try:
                compact(conversation, client, model)
            except ValueError as exc:
                # Transcript too short to compact — fall back to pruning.
                print(f"[context] Compaction skipped ({exc}). Pruning instead.")
                pruned = prune_to_budget(conversation.to_input(), INPUT_BUDGET)
                conversation.replace_items(pruned)

        elif estimated_tokens > INPUT_BUDGET:
            # Already over hard budget but below compact trigger — prune.
            print(
                f"[context] Estimated input {estimated_tokens} tokens exceeds "
                f"hard budget {INPUT_BUDGET}. Pruning."
            )
            pruned = prune_to_budget(conversation.to_input(), INPUT_BUDGET)
            conversation.replace_items(pruned)

        # ------------------------------------------------------------------ #
        # Normal agent turn                                                   #
        # ------------------------------------------------------------------ #
        resp = client.responses.create(
            model=model,
            instructions=instructions,
            input=conversation.to_input(),
            tools=tools,
        )

        total_input_tokens  += resp.usage.input_tokens
        total_output_tokens += resp.usage.output_tokens
        print(
            f"[tokens] in={resp.usage.input_tokens} "
            f"out={resp.usage.output_tokens} "
            f"total_session={total_input_tokens + total_output_tokens}"
        )

        # … process resp.output, append items, handle tool calls …
        # (see Phase 2 / Phase 3 for the full turn-processing code)

        # Done when the model issued no function_call items this turn —
        # the same stop condition every loop in this guide has used.
        if not any(
            getattr(item, "type", None) == "function_call"
            for item in resp.output
        ):
            break
```

The ordering matters: **check and compact first, then call the API.** Do not call the API and then compact; that wastes tokens and may fail if you are already over the limit.

### ▶ Run it now

To see compaction fire without an hour-long session, temporarily set
`COMPACT_TRIGGER = 800` and `KEEP_RECENT_VERBATIM = 4`, chat for a few file-reading
turns, and watch the `[compact]` lines appear. Then ask the agent what it did earlier:
unlike pruning, it can answer from the summary.

---

## Beyond the ladder: keep tokens out of the window entirely

### Tactic D: Externalised Memory (Filesystem as a Cache)

**Why now?** Even with pruning and compaction, some content shouldn't live in the
transcript at all. Large artefacts — file contents, grep output, test logs — occupy the
window for every subsequent turn, even after the agent is done with them. The fix is to
write them to disk immediately and keep only a path in the transcript.

There is a conceptual alternative to compaction: **do not put the content in context in the first place**.

If the agent reads a 4 000-token file just to check one function, that content occupies the window for every subsequent turn even after the check is done. Instead:

- Keep only **pointers** (file paths, line ranges, database keys) in the conversation.
- Re-read on demand using the existing `read_file` tool when the agent needs the content again.
- For generated artefacts (reports, diffs, test output), write them to disk immediately and store the path in the transcript rather than the content.

This is **externalised memory**: the filesystem is an infinite, cheap, persistent store; the context window is a small, expensive, volatile cache. The agent already has `read_file` — use it as a cache miss handler rather than a one-shot loader.

Practical rules of thumb:

- Files > 500 tokens: pass the path in the tool output, not the content. Let the agent decide whether to read more.
- Intermediate results (e.g. grep output, compilation log): write to a temp file, return the path + a one-line summary.
- Always-needed reference material (API docs, schema): inject once at session start in `instructions`, not as a tool call.

### ▶ Check it now

After adding `clip_output` and the filesystem rule to your tools, run a
session and check `resp.usage.input_tokens` each turn. It should grow much more slowly
than before.

---

## What to Preserve vs Drop

| Item type | Priority | Notes |
|---|---|---|
| System instructions | **Always keep** | Live in `instructions=`, not in `input_items`; never at risk |
| Latest user message / goal | **Always keep** | Must be in the recency window |
| Recent assistant messages | Keep | Last 3–5 turns |
| Active `function_call` + `function_call_output` pair | Keep | Cannot drop one without the other |
| Old assistant messages (resolved steps) | Summarise | Good candidates for compaction prefix |
| Old verbose `function_call_output` (file reads, command output) | Drop / summarise | Highest token cost, lowest ongoing value |
| `reasoning` items | Can drop oldest | Reasoning traces are ephemeral; the conclusions matter, not the process |
| Summary items injected by prior compaction | Keep short-term | They replace the old content; keep until they themselves become stale |

---

## Persistent Memory Across Sessions

**Why this step?** All the tactics so far manage context *within* a session. But
tool-call history vanishes when the process exits. For a long-running project the agent
needs a way to remember decisions made in previous sessions.

Tool-call history vanishes when the process exits. For a long-running project the agent needs a way to remember decisions made in previous sessions.

The pattern, inspired by `CLAUDE.md`: maintain a **memory file** (e.g. `agent_memory.md`) that the agent can write to, and inject its contents into `instructions` at startup.

### Writing to the memory file

Register a tool:

```python
# tools/memory.py

import pathlib

MEMORY_FILE = pathlib.Path("agent_memory.md")


def update_memory(note: str) -> str:
    """
    Append *note* to the persistent memory file.
    Call this whenever you learn something important that should survive
    across sessions: a design decision, a discovered constraint, a file
    that must not be modified, etc.
    """
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MEMORY_FILE.open("a", encoding="utf-8") as f:
        from datetime import datetime, timezone
        f.write(f"\n## {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
        f.write(note.strip() + "\n")
    return f"Memory updated. File is now {MEMORY_FILE.stat().st_size} bytes."
```

Tool schema entry:

```python
{
    "type": "function",
    "name": "update_memory",
    "description": (
        "Append an important note to the persistent memory file. Use this "
        "for decisions, constraints, or facts that must be remembered in "
        "future sessions. Keep notes terse and factual."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "The note to append.",
            }
        },
        "required": ["note"],
    },
}
```

### Injecting the memory file at startup

```python
# agent.py — startup

import pathlib

MEMORY_FILE = pathlib.Path("agent_memory.md")


def load_memory() -> str:
    """Return the contents of the memory file, or an empty string."""
    if MEMORY_FILE.exists():
        return MEMORY_FILE.read_text(encoding="utf-8").strip()
    return ""


def build_instructions(base_instructions: str) -> str:
    memory = load_memory()
    if not memory:
        return base_instructions
    return (
        base_instructions
        + "\n\n---\n"
        + "## Persistent Memory (from previous sessions)\n\n"
        + memory
        + "\n---"
    )


# Usage:
instructions = build_instructions(
    "You are a software engineering agent working on the project in the "
    "current directory. Follow the existing code style. Prefer small, "
    "focused commits."
)
```

The memory file is injected once into `instructions` — which is **outside** `input_items` — so it costs tokens every call but is never lost to compaction.

---

## The production shape: full `context.py`

This is the consolidated module — Versions 3 and 4 in one file, the form that maps onto
`code/agent_harness/context.py` in the tested package.

> **Reference copy.** Assembled from Steps 3.1–4.1 unchanged (except: `compact` gains a
> local `import openai` guard). Nothing new to type here — skim or skip. The maintained
> version lives in [`code/agent_harness/context.py`](./code/agent_harness/context.py).

> 🟢 One new bit of typing machinery appears in the imports below. The
> `if TYPE_CHECKING:` block **never runs** — type checkers read it, Python skips it — so
> we can name the `openai` and `Conversation` types in annotations without importing
> those modules at runtime. That is also why the annotations are *quoted strings*
> (`"Conversation"`, `"openai.OpenAI"`): the names don't exist when Python defines the
> function, but a string annotation is fine — only the type checker ever resolves it.

```python
# context.py
"""
Context management for the agent harness.

Provides:
  - count_tokens(text)         — token count via tiktoken or heuristic
  - count_items(items)         — token estimate for a transcript list
  - clip_output(text)          — truncate tool output before it enters the transcript
  - prune_to_budget(items, n)  — recency-based pruning respecting fc/fco pairing
  - compact(conversation, client, model) — model-based summarisation / compaction

Constants (tune to your model and deployment):
  MAX_CONTEXT_TOKENS, RESPONSE_RESERVE, INPUT_BUDGET,
  COMPACT_THRESHOLD, COMPACT_TRIGGER
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import openai
    from conversation import Conversation

# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def _heuristic(text: str) -> int:
    return max(1, len(text) // 4)


try:
    import tiktoken

    def _get_encoding():
        # See Step 3.1: catch broadly so an offline vocab download can't crash import.
        try:
            try:
                enc = tiktoken.encoding_for_model("gpt-4o")
            except KeyError:
                enc = tiktoken.get_encoding("o200k_base")
            enc.encode("warmup")
            return enc
        except Exception:
            return None

    _ENC = _get_encoding()

    def count_tokens(text: str) -> int:
        return _heuristic(text) if _ENC is None else len(_ENC.encode(text))

except ImportError:
    def count_tokens(text: str) -> int:  # type: ignore[misc]
        return _heuristic(text)


def _item_to_text(item: dict[str, Any]) -> str:
    item_type = item.get("type", "")

    if item_type == "message":
        content = item.get("content", "")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", "") or json.dumps(block))
                else:
                    parts.append(str(block))
            content = " ".join(parts)
        return f"{item.get('role', '')}: {content}"

    if item_type == "function_call":
        return (
            f"function_call {item.get('name', '')} "
            f"{json.dumps(item.get('arguments', ''))}"
        )

    if item_type == "function_call_output":
        return (
            f"function_call_output {item.get('call_id', '')} "
            f"{item.get('output', '')}"
        )

    if item_type == "reasoning":
        summary = item.get("summary", [])
        if isinstance(summary, list):
            return " ".join(
                s.get("text", "") for s in summary if isinstance(s, dict)
            )
        return str(summary)

    return json.dumps(item)


def count_items(items: list[dict[str, Any]]) -> int:
    return sum(count_tokens(_item_to_text(item)) for item in items)


# ---------------------------------------------------------------------------
# Budget constants
# ---------------------------------------------------------------------------

MAX_CONTEXT_TOKENS = 128_000
RESPONSE_RESERVE   = 4_096
INPUT_BUDGET       = MAX_CONTEXT_TOKENS - RESPONSE_RESERVE
COMPACT_THRESHOLD  = 0.75
COMPACT_TRIGGER    = int(INPUT_BUDGET * COMPACT_THRESHOLD)

MAX_TOOL_OUTPUT_TOKENS = 2_000

# ---------------------------------------------------------------------------
# Tool output clipping
# ---------------------------------------------------------------------------

def clip_output(text: str, max_tokens: int = MAX_TOOL_OUTPUT_TOKENS) -> str:
    if count_tokens(text) <= max_tokens:
        return text
    char_limit = max_tokens * 4
    return text[:char_limit] + f"\n... [output truncated to ~{max_tokens} tokens]"


# ---------------------------------------------------------------------------
# Sliding-window pruning
# ---------------------------------------------------------------------------

def _paired_indices(items: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    fc_idx:  dict[str, int] = {}
    fco_idx: dict[str, int] = {}
    for i, item in enumerate(items):
        t   = item.get("type")
        cid = item.get("call_id") or item.get("id")
        if t == "function_call" and cid:
            fc_idx[cid] = i
        elif t == "function_call_output" and cid:
            fco_idx[cid] = i
    return {
        cid: (fc_idx[cid], fco_idx[cid])
        for cid in fc_idx
        if cid in fco_idx
    }


def _protected_set(items: list[dict[str, Any]], keep_last_n: int) -> set[int]:
    protected = set(range(max(0, len(items) - keep_last_n), len(items)))
    for _cid, (fi, foi) in _paired_indices(items).items():
        if fi in protected or foi in protected:
            protected.add(fi)
            protected.add(foi)
    return protected


def _find_output(items: list[dict[str, Any]], call_id: str) -> int | None:
    for i, item in enumerate(items):
        if item.get("type") == "function_call_output" and (
            item.get("call_id") == call_id or item.get("id") == call_id
        ):
            return i
    return None


def _find_call(items: list[dict[str, Any]], call_id: str) -> int | None:
    for i, item in enumerate(items):
        if item.get("type") == "function_call" and (
            item.get("call_id") == call_id or item.get("id") == call_id
        ):
            return i
    return None


def prune_to_budget(
    items: list[dict[str, Any]],
    budget: int,
    *,
    keep_last_n: int = 6,
) -> list[dict[str, Any]]:
    """
    Drop oldest items until count_items(result) <= budget — or until only
    protected items remain, in which case the result may still exceed budget.
    Never splits a function_call / function_call_output pair.
    Never drops items in the recency window (last keep_last_n items, plus
    any paired partners that are themselves in the window).
    """
    if count_items(items) <= budget:
        return list(items)

    result = list(items)

    i = 0
    while i < len(result) and count_items(result) > budget:
        if i in _protected_set(result, keep_last_n):
            i += 1
            continue

        item = result[i]
        t    = item.get("type")
        cid  = item.get("call_id") or item.get("id")

        if t == "function_call" and cid:
            partner = _find_output(result, cid)
            if partner is not None:
                result.pop(partner)
                result.pop(i)
                continue  # new item now at index i

        elif t == "function_call_output" and cid:
            partner = _find_call(result, cid)
            if partner is not None and partner < i:
                result.pop(i)
                result.pop(partner)
                i = partner
                continue

        result.pop(i)
        # Do not advance i — new item is at same index.

    return result


# ---------------------------------------------------------------------------
# Compaction (model-based summarisation)
# ---------------------------------------------------------------------------

SUMMARIZATION_SYSTEM = """\
You are a precise technical summariser. You will be given a partial transcript \
of an AI agent session. Produce a compact structured summary that captures \
everything a continuation of that session needs to know. Do not editorialize. \
Be specific: use exact file paths, function names, error messages, and decisions \
rather than vague descriptions.\
"""

SUMMARIZATION_INSTRUCTION = """\
Summarise the following agent session transcript into a single dense note. \
Include ALL of the following that are present:

1. **Current task** — the user's goal as stated and any refinements agreed so far.
2. **Key decisions** — architectural choices, technology choices, any explicit \
   "we decided to …" moments.
3. **Work completed** — files created or modified (list exact paths), commands \
   run and their outcomes, tests passed or failed.
4. **Important facts discovered** — error messages, surprising findings, \
   constraints uncovered.
5. **Open TODOs** — what the agent was about to do or has been asked to do next.
6. **Critical file paths / identifiers** — anything the agent will need to \
   reference going forward.

Format as terse bullet points under those headings. Do not include conversational \
filler. Omit any heading whose content is empty. Maximum 600 tokens.\
"""

KEEP_RECENT_VERBATIM = 10


def compact(
    conversation: "Conversation",
    client: "openai.OpenAI",
    model: str,
    *,
    keep_recent: int = KEEP_RECENT_VERBATIM,
) -> str:
    """
    Summarise the older portion of *conversation* and replace it with a
    single compact summary item.  The most recent *keep_recent* items are
    kept verbatim.

    Returns the summary text.  Mutates *conversation* in place.
    Raises ValueError if the transcript is too short to compact.
    """
    import openai as _openai  # local import to keep module importable without openai

    items = conversation.to_input()

    if len(items) <= keep_recent + 1:
        raise ValueError(
            f"Transcript too short to compact: {len(items)} items, "
            f"need at least {keep_recent + 2}."
        )

    cutoff      = len(items) - keep_recent
    to_summarise = list(items[:cutoff])
    to_keep      = list(items[cutoff:])

    # Do not split a function_call / function_call_output across the boundary.
    while to_summarise:
        last = to_summarise[-1]
        if last.get("type") == "function_call":
            cid = last.get("call_id") or last.get("id")
            if to_keep and (
                to_keep[0].get("type") == "function_call_output"
                and (
                    to_keep[0].get("call_id") == cid
                    or to_keep[0].get("id") == cid
                )
            ):
                to_keep.insert(0, to_summarise.pop())
        break

    if not to_summarise:
        raise ValueError("Nothing to summarise after boundary adjustment.")

    transcript_text = "\n\n".join(
        f"[{item.get('type', 'item')}] {_item_to_text(item)}"
        for item in to_summarise
    )

    summarise_input = [
        {
            "type": "message",
            "role": "user",
            "content": (
                SUMMARIZATION_INSTRUCTION
                + "\n\n---\n\n"
                + transcript_text
            ),
        }
    ]

    print(
        f"[compact] Summarising {len(to_summarise)} items "
        f"({count_items(to_summarise)} est. tokens)…"
    )

    summary_resp = client.responses.create(
        model=model,
        instructions=SUMMARIZATION_SYSTEM,
        input=summarise_input,
    )

    summary_text = ""
    for out_item in summary_resp.output:
        if getattr(out_item, "type", None) == "message":
            for block in getattr(out_item, "content", []):
                if getattr(block, "type", None) == "output_text":
                    summary_text += block.text
    summary_text = summary_text.strip()

    if not summary_text:
        raise RuntimeError("Compaction produced an empty summary — aborting.")

    print(
        f"[compact] Done. {len(to_summarise)} items → "
        f"{count_tokens(summary_text)} tokens. "
        f"{len(to_keep)} recent items kept verbatim."
    )

    summary_item: dict[str, Any] = {
        "type": "message",
        "role": "user",
        "content": (
            "[CONTEXT SUMMARY — earlier transcript compacted]\n\n"
            + summary_text
        ),
    }

    conversation.replace_items([summary_item] + to_keep)
    return summary_text
```

> One difference worth knowing about: the tested package's `prune_to_budget`
> (`code/agent_harness/context.py`) uses the *group-based* algorithm from Version 2 —
> pairs grouped, first user message pinned — rather than the recency-window walk shown
> above. Both satisfy the same two correctness rules; as ever, when a guide snippet and
> the package disagree, the package is the source of truth.

---

## Pitfalls

> **Watch out for these common mistakes.**

| Pitfall | Consequence | Fix |
|---|---|---|
| Dropping a `function_call` without its `function_call_output` | API validation error: orphaned tool call | Always drop pairs together; use `_paired_indices` before removing anything |
| Summarising away the active task | Agent loses track of what it is supposed to do; wanders | Keep the most recent user message outside the compaction prefix; use `keep_recent` conservatively |
| Compaction cost and latency | Each compact call takes ~1–3 s and costs tokens | Only trigger at 75 % of budget, not at 100 %; log timing so you can tune the threshold |
| Double-counting tokens | Comparing `resp.usage.input_tokens` *between* turns as if it measures only the *new* items | `input_tokens` is the size of the *full* input including system instructions and the entire transcript — compare it against `MAX_CONTEXT_TOKENS`, not against a per-turn delta |
| Never compacting the latest user instruction | The instruction that triggered the current task gets summarised or dropped | The recency window (`keep_recent`) must always include at least the last user message |
| Compacting too aggressively (small `keep_recent`) | Agent loses context of ongoing tool call chains | Increase `keep_recent`; keep at least the last 2 full round-trips (4 items) |
| Injecting the compaction summary as an `assistant` message | Some API versions reject assistant messages whose content was not produced by the model | Use `role: "user"` for injected summary items, labelled clearly as a system note |

---

## Key takeaways

The five mechanisms at a glance:

| Mechanism | When to use | Token cost | Information loss |
|---|---|---|---|
| Clip tool output at source | Always | None (prevents tokens entering) | Possibly truncated tool data |
| Sliding-window pruning | Over hard budget, transcript too short to compact | None | Old turns discarded silently |
| Model compaction | Approaching budget (75 %), long sessions | ~500 tokens per compact call | Minimal — model preserves what matters |
| Externalised memory (filesystem) | Large artefacts (files, reports) | None in context | None — data on disk |
| Persistent memory file | Cross-session facts | Small (injected in instructions) | None |

With these five mechanisms layered in order, the harness can sustain arbitrarily long sessions without degrading or crashing — the difference between a demo and a tool you would trust with a real engineering task.

- **One core problem:** the transcript grows every turn, but the context window is
  finite — a long session *must* shed tokens without losing the thread.
- **Know your budget:** count tokens with `tiktoken` (exact) or `len(text) // 4`
  (approximate) so you know when you're approaching the limit.
- **Two correctness rules govern any pruning:** never separate a `function_call` from
  its `function_call_output`, and never drop the first user message (the goal).
- **Layer the tactics in order:** clip oversized tool output at the source → sliding-window
  prune old turns → model **compaction** (summarise) as you near ~75% of budget →
  externalise big artefacts to disk → a persistent memory file for cross-session facts.
- **Preserve vs drop:** always keep the system prompt, the most recent turns, and
  task-critical facts; drop stale, reconstructable detail first.

## Check yourself

1. Why must a long agentic session eventually summarise or drop history?
2. Give two ways to count tokens, and when you'd use each.
3. How does **sliding-window pruning** differ from **model compaction**?
4. When the budget gets tight, what do you protect from being dropped?

<details><summary>Answers</summary>

1. The context window is **finite** — past some length the transcript no longer fits, so
   tokens must be shed or the call fails / the model degrades.
2. **`tiktoken`** for an exact per-model count (when installed); **`len(text) // 4`** as a
   cheap, dependency-free approximation for budgeting.
3. Pruning **discards old turns silently** (no token cost, information lost); compaction
   **summarises** them (small token cost, gist preserved).
4. The **system prompt, recent turns, and task-critical facts** — drop stale/reconstructable
   detail instead.
</details>

---

## Exercises

See [`EXERCISES.md` — Phase 6](./EXERCISES.md) for hands-on practice:

- **6.1 (warm-up):** Set an artificially tiny token budget and run a long chat. Watch old turns get pruned/compacted. Confirm the system prompt and recent turns survive.
- **6.2 (stretch):** If `tiktoken` is installed, count a sample transcript both ways (`tiktoken` vs `len(text) // 4`). How far apart are they? When is the approximation good enough?

---

**Next:** [Phase 7 — Sub-agents & orchestration](./07-subagents-orchestration.md), where the harness learns to delegate: a `task` tool that spins up a fresh agent with its own clean context — another way to keep the main window lean.
