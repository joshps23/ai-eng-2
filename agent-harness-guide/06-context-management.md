# Phase 6 — Context Management: Token Budgeting & Compaction

Every model has a finite context window. In a toy demo that window is plenty; in a real agentic session — many tool calls, large file reads, multi-step plans, long reasoning traces — you will exceed it. When that happens you get one of three failure modes: an API error (hard limit breached), silently dropped instructions (the model just forgets the system prompt), or "context rot" — degraded output quality as the signal-to-noise ratio in the window falls. None of those is acceptable for a harness meant to run for an hour.

This phase adds active context management to the harness: token counting, a configurable budget, several compaction strategies in order of sophistication, and automatic triggering inside the agent loop.

---

## 1. The Problem in Numbers

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

## 2. Counting Tokens

The API returns ground-truth token counts in `resp.usage` after each call, but we also need *local* estimates to decide whether to compact *before* the next API call.

### 2.1 Install tiktoken

```text
pip install tiktoken
```

`tiktoken` implements the same byte-pair encoding the OpenAI models use, so its counts match the API exactly (within rounding).

### 2.2 `count_tokens` — tiered fallback

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

### 2.3 `count_items` — serialise the transcript

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

### 2.4 Ground truth from `resp.usage` and running totals

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

### 2.5 Budget constants

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

---

## 3. Compaction Strategies

The strategies below are ordered from simplest to most powerful. Use them in layers: apply an earlier strategy before reaching for the next.

### 3a. Truncating Tool Outputs at the Source

This is the cheapest strategy because it prevents tokens from ever entering the transcript.

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

**Tradeoff:** The agent may miss information present later in long outputs. Mitigate by having the agent request page ranges or grep patterns rather than whole files.

---

### 3b. Sliding Window / Recency Pruning

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

**Tradeoff:** The agent loses access to the full history of what it did and why. For short-horizon tasks this is fine; for long-horizon tasks (e.g. refactoring an entire codebase) the agent may repeat work or contradict earlier decisions. That is where compaction comes in.

---

### 3c. Summarisation / Compaction

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
filler. Do not truncate any heading just because it is empty — omit empty headings \
entirely. Maximum 600 tokens.
"""
```

#### `compact()` — the full function

```python
# context.py  (continued)

import openai  # or however you import the client

# Number of recent items to keep verbatim after compaction.
# These items will NOT be fed to the summariser — they stay intact.
KEEP_RECENT_VERBATIM = 10


def compact(
    conversation: "Conversation",
    client: openai.OpenAI,
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

#### Required addition to the `Conversation` class

`compact()` calls `conversation.replace_items(new_items)`. Add this method to the `Conversation` class from Phase 3:

```python
# conversation.py  (add to Conversation class)

def replace_items(self, new_items: list[dict]) -> None:
    """Replace the entire transcript with *new_items* (used by compaction)."""
    self._items.clear()
    self._items.extend(new_items)
```

---

### 3d. Auto-Compaction Trigger in the Agent Loop

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

        if _is_done(resp):
            break
```

The ordering matters: **check and compact first, then call the API.** Do not call the API and then compact; that wastes tokens and may fail if you are already over the limit.

---

## 4. What to Preserve vs Drop

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

## 5. Retrieval as an Alternative to Keeping Everything in Context

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

---

## 6. Persistent Memory Across Sessions

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

## 7. Full `context.py`

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
        # See §2.2: catch broadly so an offline vocab download can't crash import.
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
    Drop oldest items until count_items(result) <= budget.
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

Format as terse bullet points under those headings. Omit any heading whose \
content is empty. Maximum 600 tokens.\
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

---

## 8. Pitfalls

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

## Summary

| Mechanism | When to use | Token cost | Information loss |
|---|---|---|---|
| Clip tool output at source | Always | None (prevents tokens entering) | Possibly truncated tool data |
| Sliding-window pruning | Over hard budget, transcript too short to compact | None | Old turns discarded silently |
| Model compaction | Approaching budget (75 %), long sessions | ~500 tokens per compact call | Minimal — model preserves what matters |
| Externalised memory (filesystem) | Large artefacts (files, reports) | None in context | None — data on disk |
| Persistent memory file | Cross-session facts | Small (injected in instructions) | None |

With these five mechanisms layered in order, the harness can sustain arbitrarily long sessions without degrading or crashing — the difference between a demo and a tool you would trust with a real engineering task.
