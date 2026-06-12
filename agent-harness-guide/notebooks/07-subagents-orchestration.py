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
# # Phase 7 — Sub-Agents & Orchestration (companion notebook)
#
# [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/joshps23/ai-eng-2/blob/main/agent-harness-guide/notebooks/07-subagents-orchestration.ipynb)
#
# Companion to [07-subagents-orchestration.md](../07-subagents-orchestration.md). The
# phase's whole claim — *a sub-agent is just the agent loop called again from inside a
# `task` tool* ([§2](../07-subagents-orchestration.md#2-the-key-trick--and-the-plan-for-this-phase)) —
# runs here for real: the Version 2 `run_agent` called recursively, the depth guard,
# and the threads-only-change-wall-clock-time demo.
#
# **Conventions:** Run top-to-bottom. When confused: *Kernel → Restart & Run All*.
# Every cell below runs **WITHOUT** an API key.
#
# On Google Colab this cell installs everything automatically (private repo: add a
# `GH_TOKEN` secret — see [the README's Colab section](./README.md#running-on-google-colab)).

# %%
try:
    import agent_harness
except ModuleNotFoundError:
    import sys
    if "google.colab" not in sys.modules:
        raise SystemExit(
            "agent_harness is not installed in this kernel.\n"
            "Fix: pip install -e \"agent-harness-guide/code[dev,notebooks]\" from the repo root,\n"
            "then pick the 'Python (agent-harness)' kernel — see ../FAQ.md#setup--installation"
        )
    # Running on Google Colab: fetch the repo and install the package.
    import os, pathlib, subprocess
    REPO_URL = "https://github.com/joshps23/ai-eng-2.git"
    if not pathlib.Path("ai-eng-2").exists():
        token = None
        try:
            from google.colab import userdata
            token = userdata.get("GH_TOKEN")
        except Exception:
            pass  # no secret configured; try anonymous clone (works if the repo is public)
        url = REPO_URL if not token else REPO_URL.replace("https://", f"https://{token}@", 1)
        r = subprocess.run(["git", "clone", "-q", url], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(
                "Could not clone the repo (it is private). Add a fine-grained GitHub token with "
                "read-only Contents access for this repo as a Colab secret named GH_TOKEN "
                "(key icon in the left sidebar), enable notebook access, and re-run this cell."
            )
        if token:  # don't leave the token on disk in the git remote
            subprocess.run(["git", "-C", "ai-eng-2", "remote", "set-url", "origin", REPO_URL], check=False)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "./ai-eng-2/agent-harness-guide/code"], check=True)
    import agent_harness
import sys
print(sys.executable)
print("agent_harness:", agent_harness.__file__)

# %% tags=["parameters"]
import os
from agent_harness.testing import FakeClient, fake_function_call, fake_message

USE_REAL_API = False  # flip to True (with OPENAI_API_KEY set) to talk to the real API
MODEL = "gpt-4o"

def make_client(turns):
    """Real OpenAI() if opted in and a key is present, else a scripted FakeClient.

    Only the *model* is faked — the recursion, the handshake, and both transcripts
    all run for real either way. One client per agent, always: a FakeClient's turns
    pop off a list, so two agents sharing one would eat each other's script.
    """
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)

OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")

# %% [markdown]
# ## 0. A workspace for the sub-agent to read
#
# The sub-agent's one tool is `read_file`, so give it a file: a throwaway tmpdir
# (never the notebook's own directory) with a planted `NOTES.md`.

# %%
import tempfile
from pathlib import Path

WORKSPACE = Path(tempfile.mkdtemp(prefix="subagents-workspace-"))
NOTES_PATH = WORKSPACE / "NOTES.md"
NOTES_PATH.write_text(
    "# Project notes\n\n"
    "Plan: ship the harness on Friday.\n"
    "TODO: add retry jitter (llm.py).\n"
    "TODO: prune_to_budget needs one more edge-case test.\n"
)
print("workspace:", WORKSPACE)
print(NOTES_PATH.read_text())

# %% [markdown]
# ## 1. The Version 2 core: one `run_agent` for orchestrator and worker alike
#
# [Version 2](../07-subagents-orchestration.md#version-2--functions-the-duplication-collapses)
# collapses Version 1's pasted-twice loop into one function,
# [`run_agent`](../07-subagents-orchestration.md#step-22--one-loop-function-for-both-run_agent),
# plus two helpers. `tools_for_api` and `dispatch` are the phase's code verbatim;
# `run_agent` carries two notebook adaptations (the same ones notebook 01 made): the
# **client is a parameter** — that injectability is what lets each agent get its own
# FakeClient — and the **conversation is returned** alongside the final text so cells
# can inspect transcripts.

# %%
import json

def tools_for_api(tools_dict):
    """Return the JSON-schema list for every tool in tools_dict."""
    return [t["schema"] for t in tools_dict.values()]


def dispatch(tools_dict, name, arguments_json):
    """Call the tool named `name` with the parsed JSON arguments."""
    args = json.loads(arguments_json)
    fn = tools_dict[name]["fn"]
    try:
        return str(fn(**args))
    except Exception as exc:
        return f"[error] {exc}"


def run_agent(instructions, task, tools_dict, client):
    """Run a fresh agent loop and return (final_text, conversation)."""
    conversation = [{"role": "user", "content": task}]
    while True:
        resp = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=conversation,
            tools=tools_for_api(tools_dict),
        )
        conversation += list(resp.output)
        calls = [it for it in resp.output if it.type == "function_call"]
        if not calls:
            return resp.output_text, conversation    # done
        for fc in calls:
            conversation.append({
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": dispatch(tools_dict, fc.name, fc.arguments),
            })


# ▶ dispatch's error contract, probed offline — errors come back as strings:
toy = {"shout": {"fn": lambda text: text.upper(),
                 "schema": {"type": "function", "name": "shout"}}}
print(dispatch(toy, "shout", '{"text": "hi"}'))
print(dispatch(toy, "shout", '{"wrong_arg": 1}'))   # an [error] string, not a crash

assert dispatch(toy, "shout", '{"text": "hi"}') == "HI"
assert dispatch(toy, "shout", '{"wrong_arg": 1}').startswith("[error]"), (
    "tool failures must become strings the model can read — raising would kill the loop")
print("dispatch checks passed")

# %% [markdown]
# **The sub-agent's tool** — `read_file`, verbatim from the phase's
# [`v2_subagent.py`](../07-subagents-orchestration.md#step-22--one-loop-function-for-both-run_agent).
# It exists independently of any agent: probe it directly, no model, no key.

# %%
def _read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError as exc:
        return f"[error] {exc}"

READ_FILE_TOOL = {
    "fn": _read_file,
    "schema": {
        "type": "function",
        "name": "read_file",
        "description": "Read a file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

ALL_TOOLS = {"read_file": READ_FILE_TOOL}

print(_read_file(NOTES_PATH))
missing = _read_file(WORKSPACE / "missing.md")
print(missing)
assert "[error]" in missing, "a missing file must come back as an error STRING, not an exception"

# %% [markdown]
# ## 2. The key trick: `run_agent` called from inside a `task` tool
#
# The next cell is the whole phase in one run. The **orchestrator**'s client is
# scripted with two turns — *call `task`*, then a final message. The `task` tool
# builds the **sub-agent's own FakeClient inside the tool function** (one client per
# agent — never shared) and calls `run_agent` *again*: a second, completely separate
# loop with its own transcript and its own tool. The only thing that crosses back is
# the sub-agent's final text — a plain string, answered under the outer call's
# `call_id` like any other tool result.
#
# Everything consumable (both scripts, the transcript log) is created in this one
# cell, so re-running it is always safe.

# %%
ORCHESTRATOR_INSTRUCTIONS = (
    "You are a helpful orchestrator. When given a task, use the `task` tool "
    "to delegate work to a specialist sub-agent and report back what it found."
)

SUB_AGENT_INSTRUCTIONS = (
    "You are a careful reviewer. Read the requested file and summarise any "
    "issues you find. Return a short bullet list."
)

INNER_TRANSCRIPTS = []   # the task tool deposits each sub-agent's private transcript here


def task(role, prompt):
    """Spawn a sub-agent and return its answer as a plain string."""
    print(f"  [task] spawning sub-agent for role={role!r} ...")
    inner_client = make_client([   # the sub-agent's OWN client, built fresh per spawn
        [fake_function_call("read_file", {"path": str(NOTES_PATH)}, "call_inner_1")],
        [fake_message("NOTES.md: ship Friday; two TODOs remain "
                      "(retry jitter in llm.py, one more prune_to_budget test).")],
    ])
    answer, inner_conv = run_agent(SUB_AGENT_INSTRUCTIONS, prompt, ALL_TOOLS, inner_client)
    INNER_TRANSCRIPTS.append(inner_conv)
    print("  [task] sub-agent finished.")
    return answer


TASK_TOOL = {
    "fn": task,
    "schema": {
        "type": "function",
        "name": "task",
        "description": "Spawn a sub-agent to complete an independent task.",
        "parameters": {
            "type": "object",
            "properties": {
                "role":   {"type": "string", "description": "Sub-agent role (e.g. 'reviewer')."},
                "prompt": {"type": "string", "description": "Full task prompt for the sub-agent."},
            },
            "required": ["role", "prompt"],
            "additionalProperties": False,
        },
    },
}

ORCHESTRATOR_TOOLS = {"task": TASK_TOOL}

# The orchestrator's script: turn 1 delegates, turn 2 reports back.
outer_client = make_client([
    [fake_function_call(
        "task",
        {"role": "reviewer",
         "prompt": f"Read {NOTES_PATH} and summarise the plan and open TODOs."},
        "call_outer_1",
    )],
    [fake_message("The reviewer sub-agent reports: the harness ships Friday, with two "
                  "TODOs still open — retry jitter and a prune_to_budget edge case.")],
])

final_answer, outer_conv = run_agent(
    ORCHESTRATOR_INSTRUCTIONS,
    f"Use the task tool to ask a reviewer sub-agent to check {NOTES_PATH}.",
    ORCHESTRATOR_TOOLS,
    outer_client,
)
print("\nFinal answer:", final_answer)

# %% [markdown]
# **▶ Self-check — read the two transcripts.** The outer transcript shows the
# handshake: the model's `function_call` for `task`, then a `function_call_output`
# whose payload **is the inner run's final text**. The inner transcript is a complete,
# separate conversation (its own `read_file` round-trip) that never entered the outer
# one — isolation is the design feature
# ([§6.3](../07-subagents-orchestration.md#63-context-isolation-as-a-design-feature)).
# The leading `None` in each type list is the user message (a plain dict with only a
# `role` — same as notebook 01).

# %%
def item_type(item):
    # the transcript mixes plain dicts (ours) with SDK/Fake objects (the model's)
    return getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)

outer_types = [item_type(i) for i in outer_conv]
print("outer transcript:", outer_types)

inner_conv = INNER_TRANSCRIPTS[0]
inner_types = [item_type(i) for i in inner_conv]
print("inner transcript:", inner_types)

# The outer handshake: one task call, answered under the same call_id.
outer_calls = [i for i in outer_conv if item_type(i) == "function_call"]
outer_outs = [i for i in outer_conv if item_type(i) == "function_call_output"]
assert outer_conv[0]["role"] == "user", "the outer transcript starts with the user's goal"
assert [getattr(c, "name", "") for c in outer_calls] == ["task"], (
    "the orchestrator's only tool call should be `task` — it delegates, it doesn't read files")
assert ({getattr(c, "call_id", None) for c in outer_calls}
        == {o["call_id"] for o in outer_outs}), "every call_id must be answered exactly"

# The inner result crossed the boundary as a STRING in a function_call_output.
assert len(INNER_TRANSCRIPTS) == 1, "exactly one sub-agent should have been spawned"
assert isinstance(outer_outs[0]["output"], str), "only a plain string crosses the boundary"
if OFFLINE:
    inner_final = [i for i in inner_conv if item_type(i) == "message"][-1].output_text
    assert outer_outs[0]["output"] == inner_final, (
        "the task tool's output must BE the sub-agent's final text, word for word")

# Isolation: the sub-agent did its own tool work, invisible to the orchestrator.
inner_calls = [i for i in inner_conv if item_type(i) == "function_call"]
assert any(getattr(c, "name", "") == "read_file" for c in inner_calls), (
    "the sub-agent should have used its own read_file tool in its own transcript")
assert not any(getattr(c, "name", "") == "read_file" for c in outer_calls), (
    "isolation broken: the sub-agent's tool calls leaked into the outer transcript")
print("recursive handshake checks passed")

# %% [markdown]
# ## 3. The depth guard: harness code, not model obedience
#
# A sub-agent whose role allows the `task` tool can spawn sub-sub-agents — a fork
# bomb without a cap
# ([§6.1](../07-subagents-orchestration.md#61-depth-limits-and-recursion-guards)).
# The guard is the first check inside the package's `dispatch_subagent`: a **pure
# function** of the depth counter, returning the error *string* the would-be parent
# receives as its tool result. Assert both sides of the boundary.

# %%
MAX_SUBAGENT_DEPTH = 4   # the package's Agent.MAX_DEPTH


def depth_guard(depth):
    """Return the §6.1 error string when the cap is hit, else None (spawn allowed)."""
    if depth >= MAX_SUBAGENT_DEPTH:
        return (
            f"[error] Sub-agent depth limit ({MAX_SUBAGENT_DEPTH}) reached. "
            "Task not executed to prevent runaway recursion."
        )
    return None


# The fork-bomb arithmetic the guard exists to stop (3 spawns per level):
for depth in range(MAX_SUBAGENT_DEPTH + 2):
    verdict = depth_guard(depth) or "spawn allowed"
    print(f"depth {depth}: {3 ** depth:>3} agents if each spawns 3 → {verdict}")

assert depth_guard(0) is None, "depth 0 (the top-level orchestrator) must be allowed to spawn"
assert depth_guard(MAX_SUBAGENT_DEPTH - 1) is None, (
    "the last level under the cap must still be allowed — the guard is >=, not >")
blocked = depth_guard(MAX_SUBAGENT_DEPTH)
assert isinstance(blocked, str) and blocked.startswith("[error]"), (
    "at the cap the guard must return an error STRING (a tool result the parent's model "
    "can read and report) — raising here would kill the parent's loop instead")
assert depth_guard(MAX_SUBAGENT_DEPTH + 10).startswith("[error]"), "and it stays blocked beyond"
print("depth-guard checks passed")

# %% [markdown]
# ## 4. Version 4's lesson, model-free: threads change *when*, never *what*
#
# A sub-agent spends nearly all its wall-clock time waiting on the network
# ([Step 4.1](../07-subagents-orchestration.md#step-41--why-threads-and-what-a-thread-even-is)),
# so `time.sleep` workers of distinct durations are an honest stand-in for
# `dispatch_subagent` — no model needed. Sequential first:

# %%
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKER_SLEEPS = {"researcher": 0.6, "analyst": 0.2, "reviewer": 0.4}


def fake_worker(role, duration, t0):
    """Stands in for dispatch_subagent: 'works' by sleeping, like a network wait."""
    start = time.perf_counter() - t0
    time.sleep(duration)
    end = time.perf_counter() - t0
    print(f"    [done] {role:<10}  start={start:.2f}s  end={end:.2f}s  (worked {duration:.1f}s)")
    return f"{role} report"


t0 = time.perf_counter()
sequential_results = {role: fake_worker(role, d, t0) for role, d in WORKER_SLEEPS.items()}
sequential_elapsed = time.perf_counter() - t0
print(f"sequential total: {sequential_elapsed:.2f}s "
      f"(~the SUM of the waits: {sum(WORKER_SLEEPS.values()):.1f}s)")

# %% [markdown]
# Now the same three workers through a `ThreadPoolExecutor`
# ([Step 4.5](../07-subagents-orchestration.md#step-45--making-the-parallelism-visible--timestamps)).
# The `with` block joins every thread before the cell returns — no stray prints
# landing in later cells. **The order of the `[done]` lines may differ on your
# machine** (`as_completed` yields fastest-first); the *timestamps* are the point:
# every worker starts at ~0.00s, and the total is the slowest worker, not the sum.

# %%
t0 = time.perf_counter()
threaded_results = {}
with ThreadPoolExecutor(max_workers=3) as pool:
    futures = {pool.submit(fake_worker, role, d, t0): role
               for role, d in WORKER_SLEEPS.items()}
    for future in as_completed(futures):
        threaded_results[futures[future]] = future.result()
threaded_elapsed = time.perf_counter() - t0
print(f"threaded total:   {threaded_elapsed:.2f}s "
      f"(~the SLOWEST wait: {max(WORKER_SLEEPS.values()):.1f}s)")

assert threaded_results == sequential_results, (
    "threads must not change WHAT the workers return — a plain for loop gives "
    "identical results; threads only change wall-clock time")
assert threaded_elapsed < sequential_elapsed, (
    f"threaded ({threaded_elapsed:.2f}s) should beat sequential "
    f"({sequential_elapsed:.2f}s): the three waits overlap instead of queueing")
print("threading checks passed")

# %% [markdown]
# ## What this notebook deliberately skips
#
# - **Version 3's class wiring** (`Agent` + `AGENT_PRESETS` + `dispatch_subagent` +
#   `make_task_tool` across `agent.py`/`subagents.py`) is a multi-file build — files
#   are scripts' job, not cells'. Read
#   [Version 3](../07-subagents-orchestration.md#version-3--classes-the-same-harness-organized)
#   and the maintained form in
#   [`code/agent_harness/subagents.py`](../code/agent_harness/subagents.py) — same
#   idea as section 2 above, organized.
# - **The §5 dynamic fan-out audit** needs a real repository and a real model:
#   [§5 — a complete worked example](../07-subagents-orchestration.md#5-a-complete-worked-example--dynamic-fan-out),
#   driven by the full [§7 listing](../07-subagents-orchestration.md#7-full-code--subagentspy).

# %%
# Everything this notebook claimed, re-asserted in one place.
types = [item_type(i) for i in outer_conv]
assert types.count("function_call") == 1 and types.count("function_call_output") == 1
assert all(isinstance(o["output"], str) for o in outer_conv
           if item_type(o) == "function_call_output")
assert len(INNER_TRANSCRIPTS) == 1                                # one spawn, one transcript
assert any(getattr(c, "name", "") == "read_file" for c in INNER_TRANSCRIPTS[0]
           if item_type(c) == "function_call")                    # the worker worked...
assert not any(getattr(c, "name", "") == "read_file" for c in outer_conv
               if item_type(c) == "function_call")                # ...invisibly to the parent
assert depth_guard(MAX_SUBAGENT_DEPTH - 1) is None                # under the cap: spawn
assert depth_guard(MAX_SUBAGENT_DEPTH).startswith("[error]")      # at the cap: error string
assert threaded_results == sequential_results                     # threads change nothing...
assert threaded_elapsed < sequential_elapsed                      # ...except wall-clock time
print("All checks passed")

# %% [markdown]
# **Optional — the same orchestration against the real API** (needs
# `OPENAI_API_KEY`): `make_client` flips both agents to live clients, so the model
# really decides when to delegate and the sub-agent really reads the planted file.

# %%
if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    live_answer, live_conv = run_agent(
        ORCHESTRATOR_INSTRUCTIONS,
        f"Use the task tool to ask a reviewer sub-agent to check {NOTES_PATH}.",
        ORCHESTRATOR_TOOLS,
        OpenAI(),
    )
    print("\nFinal answer:", live_answer)
else:
    print("(skipped — needs USE_REAL_API = True in the parameters cell AND an "
          "OPENAI_API_KEY; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - A **sub-agent is the same loop called again** from inside a tool; the only thing
#   that crosses the boundary is a string, under the outer call's `call_id`.
# - Transcripts are **isolated by construction** — fresh list per `run_agent` call —
#   and each agent gets its **own client** (scripted turns are consumable).
# - The **depth guard lives in harness code** and returns an error string, never an
#   exception; do not rely on the model obeying instructions.
# - **Threads change wall-clock time only**: same results as a `for` loop, finished
#   in the slowest worker's time instead of the sum.
#
# Now do the phase's [Check yourself](../07-subagents-orchestration.md#check-yourself)
# and [Pitfalls](../07-subagents-orchestration.md#pitfalls), then the Phase 7 exercises
# in [EXERCISES.md](../EXERCISES.md#phase-7--sub-agents--orchestration). Two starter cells:

# %%
# Quiz: what is the ONLY thing that crosses the boundary between the orchestrator
# and its sub-agent — the transcripts, the client, or a string?
answer = "a string"   # <- edit me, then run

assert "string" in answer.lower(), (
    "Hint: look at what the task tool returns and what dispatch puts in the "
    "function_call_output's `output` field.")
print("Correct — the sub-agent's final text, delivered under the outer call's call_id.")

# %%
# Exercise: a two-worker fan-out, offline. Script an outer FakeClient whose FIRST
# turn contains TWO task function_calls (distinct call_ids, e.g. "call_f1"/"call_f2"),
# then a final message. run_agent's for-loop dispatches them one after another —
# sequential is correct, just slower (V4 is only a speed-up). Give the task tool a
# fresh inner FakeClient per spawn (it already does), then assert the outer
# transcript carries TWO function_call_outputs, one per call_id.
# your code here

# fanout_answer, fanout_conv = run_agent(ORCHESTRATOR_INSTRUCTIONS, "...", ..., ...)
# outs = sorted(o["call_id"] for o in fanout_conv if item_type(o) == "function_call_output")
# assert outs == ["call_f1", "call_f2"]
print("(exercise scaffold — fill in the code above)")
