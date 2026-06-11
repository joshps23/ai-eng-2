# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Phase 6 — Context Management (companion notebook)
#
# Runs the offline checkpoints from [Phase 6 — Context Management](../06-context-management.md):
# feel the transcript grow, count tokens, prune without breaking the transcript, and compact.
#
# > **Conventions:** Run top-to-bottom. When confused: Kernel → Restart & Run All.
# > Every cell below runs WITHOUT an API key.

# %%
import sys, agent_harness; print(sys.executable)

# %% tags=["parameters"]
import os

USE_REAL_API = False  # flip to True (and export OPENAI_API_KEY) to run the live cells


def make_client(turns):
    """Real OpenAI client if you opted in, else a FakeClient scripted with *turns*."""
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    from agent_harness.testing import FakeClient
    return FakeClient(turns)

# %% [markdown]
# ## 1. Feel the growth
#
# The transcript is a list you re-send every turn, and it only ever grows.
# This is [Step 1.1](../06-context-management.md#step-11--feel-the-growth-no-api-key-needed)'s
# warm-up, verbatim: 8 fake turns, with the inline `len(text) // 4` estimate printed after each.

# %%
transcript = []

# Pretend each "turn" adds a user message and an assistant reply.
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

# %% [markdown]
# **The simplest fix:** pop the oldest item until the total fits a budget — still
# [Step 1.1](../06-context-management.md#step-11--feel-the-growth-no-api-key-needed), no `def`.
# (This naive version has two planted bugs — see
# [Step 1.3](../06-context-management.md#step-13--make-the-pain-visible-two-planted-bugs) — fixed in section 3.)

# %%
# Rebuild the same 8-turn transcript fresh, then prune it naively.
transcript = []
for turn in range(1, 9):
    transcript.append({"type": "message", "role": "user",
                       "content": f"Turn {turn}: what should we do next?"})
    transcript.append({"type": "message", "role": "assistant",
                       "content": (f"Turn {turn}: here is my plan. "
                                   + "Step one, do this. Step two, do that. Step three, check the result. " * 20)})

TOKEN_BUDGET = 1000   # tiny budget so we can see truncation fire

total = 0
for item in transcript:
    total += len(item["content"]) // 4
print(f"Before pruning: {len(transcript)} items, ~{total} tokens")

# Naive truncation: treat every item as independent and pop from the front.
dropped_count = 0
while transcript and total > TOKEN_BUDGET:
    dropped = transcript.pop(0)            # drop the oldest item
    total -= len(dropped["content"]) // 4
    dropped_count += 1

print(f"After  pruning: {len(transcript)} items, ~{total} tokens")
print(f"Dropped {dropped_count} items to stay under {TOKEN_BUDGET} tokens")

assert total <= TOKEN_BUDGET, "pruning failed to reach the budget"
assert len(transcript) == 4 and dropped_count == 12

# %% [markdown]
# ## 2. Name the estimate: `count_tokens` and `count_items`
#
# The inline arithmetic becomes two plain functions you can test offline —
# [Step 2.1](../06-context-management.md#step-21--name-the-estimate-count_tokens-and-count_items), verbatim.

# %%
import json

def count_tokens(text):
    """Rough estimate: ~4 characters per token."""
    return max(1, len(text) // 4)

def count_items(items):
    """Token estimate for a whole transcript (a list of plain dicts)."""
    return sum(count_tokens(json.dumps(item)) for item in items)

items = [{"role": "user", "content": "hello"},
         {"role": "assistant", "content": "Hi! " * 50}]
print(count_items(items))    # a number, instantly, no API

assert count_items(items) == 68   # deterministic: the heuristic needs no network

# %% [markdown]
# ### Which counter is actually active?
#
# The package's `count_tokens` upgrades to exact `tiktoken` counts when it can
# ([Step 3.1](../06-context-management.md#step-31--counting-tokens-exactly-tiktoken-with-a-tiered-fallback)'s tiered fallback).
# In this committed run **tiktoken is not installed**, so the heuristic path is the one
# executing below — that is the fallback *working as designed*, not a degraded demo.
# Install tiktoken and re-run to see the exact counter take over.

# %%
import agent_harness.context as ctx

try:
    import tiktoken  # noqa: F401
    tiktoken_installed = True
except ImportError:
    tiktoken_installed = False

encoder = ctx._get_encoder("gpt-4o")   # the package's cached-encoder probe
active = "tiktoken (exact BPE)" if encoder is not None else "heuristic: len(text) // 4"
print(f"tiktoken installed: {tiktoken_installed}")
print(f"active counter:     {active}")

probe = "The launch checklist: freeze the schema, tag the release."
print(f"package count_tokens(probe) = {ctx.count_tokens(probe)}")
print(f"our V2 heuristic            = {count_tokens(probe)}")
if encoder is None:
    assert ctx.count_tokens(probe) == count_tokens(probe)   # same fallback arithmetic

# %% [markdown]
# ## 3. Prune without breaking the transcript: `prune_to_budget`
#
# Naive `pop(0)` forgets the goal and can orphan a tool-call pair (an API `400`).
# The fixes are two rules — pairs travel together
# ([Step 2.2](../06-context-management.md#step-22--rule-1-pairs-travel-together)), and the first
# user message is pinned
# ([Step 2.3](../06-context-management.md#step-23--rule-2-keep-the-first-user-message--prune_to_budget)).
# Watching this work *is* the lesson, so the code is on screen, verbatim.

# %%
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

# %%
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

# %% [markdown]
# Verify both rules offline — [Step 2.3's checkpoint](../06-context-management.md#step-23--rule-2-keep-the-first-user-message--prune_to_budget),
# asserts and all.

# %%
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
assert count_items(pruned) <= 500
print("Both rules hold: no orphans, goal preserved.")

# %% [markdown]
# **Protection outranks the budget.** Give pruning a budget smaller than the pinned goal
# itself and the result *stays over budget* — documented behavior, not a bug. The phase's
# V3 form has the same property with its recency window
# ([Step 3.6](../06-context-management.md#step-36--tactic-b-sliding-window--recency-pruning):
# "the budget is a *target*; the recency window is a *guarantee*").

# %%
# Fresh transcript, absurd budget: only the pinned goal can survive — and it alone
# already exceeds 10 tokens, so the result is over budget BY DESIGN.
items = [{"role": "user", "content": "Refactor the billing module."}]
for i in range(5):
    cid = f"call_{i}"
    items.append({"type": "function_call", "call_id": cid, "name": "read_file",
                  "arguments": f'{{"path": "file{i}.py"}}'})
    items.append({"type": "function_call_output", "call_id": cid,
                  "output": "x = 1\n" * 200})

TIGHT_BUDGET = 10
pruned_tight = prune_to_budget(items, budget=TIGHT_BUDGET)
print(f"Asked for <= {TIGHT_BUDGET} tokens, got {len(pruned_tight)} item(s), "
      f"~{count_items(pruned_tight)} tokens: {pruned_tight[0]['content']!r}")

assert pruned_tight == [items[0]]                      # only the pinned goal survives
assert count_items(pruned_tight) > TIGHT_BUDGET        # still over budget — by design

# %% [markdown]
# ## 4. `compact`: spend one API call to buy back context
#
# Pruning discards; compaction *summarizes* — one model call replaces the older half with
# a dense note ([Step 4.1](../06-context-management.md#step-41--tactic-c-summarisation--compaction)).
# The phase's V4 `compact` takes a `Conversation`; here we run the package's simpler
# list-based form (`agent_harness.context.compact` — the
# [source of truth](../06-context-management.md#the-production-shape-full-contextpy)),
# with the summarizer scripted as one `fake_message("SUMMARY: ...")` turn.

# %%
from agent_harness.context import compact, count_items as pkg_count_items
from agent_harness.llm import LLMClient
from agent_harness.testing import fake_message

# Fresh transcript: one goal + five tool round-trips (same shape as section 3).
items = [{"role": "user", "content": "Refactor the billing module."}]
for i in range(5):
    cid = f"call_{i}"
    items.append({"type": "function_call", "call_id": cid, "name": "read_file",
                  "arguments": f'{{"path": "file{i}.py"}}'})
    items.append({"type": "function_call_output", "call_id": cid,
                  "output": "x = 1\n" * 200})

# The single API call compaction spends — scripted, so it runs offline.
summary = ("SUMMARY: user asked to refactor the billing module; file0.py and file1.py "
           "were read (each is 200 lines of 'x = 1'); next: read the remaining files.")
llm = LLMClient(client=make_client([[fake_message(summary)]]))

print(f"Before: {len(items)} items, ~{pkg_count_items(items)} tokens")
compacted = compact(items, llm)
print(f"After:  {len(compacted)} items, ~{pkg_count_items(compacted)} tokens")
print()
print(compacted[0]["content"])

assert len(compacted) < len(items)                          # transcript got shorter
assert pkg_count_items(compacted) < pkg_count_items(items)  # and cheaper
assert compacted[0]["content"].startswith("[Previous conversation summary]")
assert "SUMMARY:" in compacted[0]["content"]                # the scripted gist survived

# %% [markdown]
# ### Final structural checks

# %%
# Everything this notebook claimed, re-asserted in one place.
calls   = {it["call_id"] for it in pruned if it.get("type") == "function_call"}
outputs = {it["call_id"] for it in pruned if it.get("type") == "function_call_output"}
assert calls == outputs                                     # no orphaned pairs
assert pruned[0].get("role") == "user"                      # goal pinned
assert len(pruned_tight) == 1 and count_items(pruned_tight) > TIGHT_BUDGET
assert len(compacted) == 7 and compacted[0]["content"].startswith(
    "[Previous conversation summary]")
assert "SUMMARY:" in compacted[0]["content"]
print("All checks passed")

# %% [markdown]
# ### Optional: live compaction
#
# The same `compact` call against the real API — the model writes the summary instead of
# our script. Safe to run keyless: it skips itself.

# %%
if os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI

    live_items = [{"role": "user", "content": "Refactor the billing module."}]
    for i in range(5):
        cid = f"call_{i}"
        live_items.append({"type": "function_call", "call_id": cid, "name": "read_file",
                           "arguments": f'{{"path": "file{i}.py"}}'})
        live_items.append({"type": "function_call_output", "call_id": cid,
                           "output": "x = 1\n" * 200})

    live_llm = LLMClient(client=OpenAI())
    live_compacted = compact(live_items, live_llm)
    print(f"{len(live_items)} items -> {len(live_compacted)} items")
    print(live_compacted[0]["content"][:600])
else:
    print("(skipped — no API key; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - The transcript grows every turn; the window is finite — long sessions **must** shed tokens.
# - Two correctness rules govern any pruning: pairs travel together, and the goal is pinned.
# - Protections (pinned goal, recency window) outrank the budget when they conflict.
# - Compaction trades one API call for a summary that keeps the *gist* of dropped turns.
#
# Quiz yourself with the phase's [Check yourself](../06-context-management.md#check-yourself),
# then try [`EXERCISES.md` — Phase 6](../EXERCISES.md). Two scaffolds below.

# %%
# Exercise 1 (phase Step 3.5): implement clip_output — bound a tool result BEFORE it
# enters the transcript. The cheapest token is the one you never store.
def clip_output(text, max_tokens=2000):
    # your code here: return text unchanged if it fits, else cut to ~max_tokens * 4
    # characters and append a "... [output truncated]" marker.
    ...

# Uncomment to check your work:
# long_output = "line of output\n" * 1000              # ~3750 heuristic tokens
# safe = clip_output(long_output)
# assert count_tokens(safe) <= 2050
# assert "truncated" in safe.splitlines()[-1]
# print(f"~{count_tokens(long_output)} tokens -> ~{count_tokens(safe)} tokens")

# %%
# Exercise 2 (EXERCISES.md 6.2): pip install tiktoken, Restart & Run All, and watch the
# "which counter is active" cell flip. Then compare exact vs heuristic counts here —
# how far apart are they on prose vs code?
sample = "def prune_to_budget(items, budget): ..." * 10
# your code here
# import tiktoken
# enc = tiktoken.encoding_for_model("gpt-4o")
# print(f"tiktoken: {len(enc.encode(sample))}  heuristic: {count_tokens(sample)}")
