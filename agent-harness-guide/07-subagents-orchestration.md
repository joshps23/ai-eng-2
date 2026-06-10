# Phase 7 — Sub-Agents & Dynamic Parallel Orchestration

> **Series context:** Phases 0–6 built a complete, production-grade single-agent harness: a working loop, a typed tool system with `@tool` and `ToolRegistry`, streaming, conversation management, permission hooks, and structured outputs. This phase is the headline feature: turning that single agent into an **orchestrator** that spawns worker agents at runtime, fans them out in parallel, and synthesises their results. Read the earlier phases first; this phase builds on every concept they introduced without repeating them.

---

## 1. Why One Agent Is Not Enough

A single agent loop is surprisingly capable, but three hard limits surface quickly in real workloads.

### 1.1 Context-window pressure

Every tool call and its output accumulates in `input_items`. A thorough web search, a large file read, or a detailed code analysis can produce thousands of tokens — most of which the agent never needs again after it has extracted the key fact. Those tokens sit in every subsequent API call, consuming quota, increasing latency, and eventually hitting the model's context limit.

A sub-agent solves this cleanly: it does the noisy, expensive work in its **own isolated transcript**, produces a crisp summary, and the parent sees only that summary. The parent's context stays slim regardless of how much intermediate work happened.

### 1.2 Wall-clock parallelism

Independent subtasks executed serially add their latencies together. If summarising three code modules each takes four seconds, a serial approach takes twelve seconds. Three parallel sub-agents each with their own OpenAI connection take four seconds — the irreducible minimum. The OpenAI API is stateless and horizontally scalable; parallel calls are not just possible, they are encouraged.

### 1.3 Specialisation

Different subtasks benefit from different system prompts and different toolsets. A "researcher" agent should have web-search tools and a prompt that emphasises accuracy and citation. A "coder" agent needs file-system tools and a prompt that emphasises correctness and minimal diffs. A "reviewer" agent needs read-only access and a prompt that emphasises finding bugs. Packing all three roles into one agent with one prompt compromises all three.

### 1.4 The orchestrator-worker pattern

The architecture this phase builds:

```
                     ┌─────────────────────────────────────┐
                     │           ORCHESTRATOR               │
                     │  (decides what work needs doing,     │
                     │   how many workers, what each does)  │
                     └────────────────┬────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │ task()                │ task()                │ task()
              ▼                       ▼                       ▼
   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
   │  WORKER A        │   │  WORKER B        │   │  WORKER C        │
   │  role=researcher │   │  role=coder      │   │  role=reviewer   │
   │  own transcript  │   │  own transcript  │   │  own transcript  │
   │  own tools       │   │  own tools       │   │  own tools       │
   └────────┬────────┘   └────────┬────────┘   └────────┬────────┘
            │ summary             │ diff                 │ findings
            └───────────────────►─┴─◄──────────────────┘
                                  │
                     ┌────────────▼────────────┐
                     │  ORCHESTRATOR synthesises│
                     │  final answer            │
                     └─────────────────────────┘
```

The critical insight is that the orchestrator **decides at runtime** how many workers to spawn and what each does. This is a *dynamic* workflow, not a hardcoded pipeline. The model looks at the task, reasons about how to decompose it, and emits the appropriate `task` tool calls. If the task only warrants one worker, one is spawned. If it warrants seven, seven run in parallel.

---

## 2. The Key Trick — and the Plan for This Phase

> **Why now?** Before any classes or config, you need to see the core idea working. Everything else in this phase is just that one idea, better organized.

This phase presents **one harness, four times**, at increasing levels of abstraction.
Every version is a **complete program you can paste into a file and run**, and every
version does the same thing: an orchestrator agent delegates work to a sub-agent through
a `task` tool. Only the *organization* of the code changes:

- **Version 1 — line-by-line.** No `def`, no classes. The agent loop — and, inside its
  `task` dispatch branch, **a second copy of the exact same loop pasted inline**. The
  duplication is deliberate: you should *feel* "this is the same code twice."
- **Version 2 — functions.** The pasted copy collapses into a plain function, and then
  both loops collapse into one `run_agent` function used by orchestrator and worker alike.
- **Version 3 — classes.** The loop becomes an `Agent` object, roles become presets, and
  spawning becomes a `task` tool that constructs an `Agent` inside a tool — the shape of
  the real package (`code/agent_harness/subagents.py`). Same idea, organized.
- **Version 4 — threads.** Several sub-agents run *at the same time* via a thread pool —
  the shape of `code/agent_harness/tools/parallel.py`. Same harness, one new mechanism.

Between versions you'll find a short **"What changed"** list, so you can see each rung as
a reorganization of the previous one, never a brand-new program.

> ## 🟢 Beginner track: a "sub-agent" is just calling your agent loop again
>
> This phase uses an `Agent` **class**, but the whole idea works with the
> **agent-loop function** you already wrote in Phases 1–2 plus a couple of dicts.
> Here's the entire concept:
>
> > A **sub-agent** is what you get when one of your tools, instead of reading a file,
> > **runs the agent loop again** with a different prompt and its own fresh
> > conversation. The result it returns becomes the tool's output. That's it.
>
> **An "Agent" is just the loop + its own conversation list.** Bundle them in a dict:
>
> ```python
> def run_agent(instructions, task, tools_dict):
>     """Your Phase 1-2 loop, as a plain function. Returns the final text."""
>     conversation = [{"role": "user", "content": task}]
>     while True:
>         resp = client.responses.create(
>             model=MODEL, instructions=instructions,
>             input=conversation, tools=tools_for_api(tools_dict),
>         )
>         conversation += list(resp.output)
>         calls = [it for it in resp.output if it.type == "function_call"]
>         if not calls:
>             return resp.output_text          # done — hand back the answer
>         for fc in calls:                     # run tools (sequential is fine)
>             conversation.append({
>                 "type": "function_call_output",
>                 "call_id": fc.call_id,
>                 "output": dispatch(tools_dict, fc.name, fc.arguments),
>             })
> ```
>
> **Roles ("presets") are just a dict** of role name → its instructions and tool list:
>
> ```python
> PRESETS = {
>     "researcher": {"instructions": "Research and summarize. Return only the summary.",
>                    "tools": ["read_file", "list_directory"]},
>     "reviewer":   {"instructions": "Find bugs. Return a list of findings.",
>                    "tools": ["read_file"]},
> }
> ```
>
> **The `task` tool is a function that runs a sub-agent:**
>
> ```python
> def task(role, prompt):
>     preset = PRESETS.get(role, PRESETS["researcher"])
>     # Hand the worker only the tools its role allows (filter the big tools dict)
>     worker_tools = {name: ALL_TOOLS[name] for name in preset["tools"]}
>     return run_agent(preset["instructions"], prompt, worker_tools)  # <-- loop again
> ```
>
> Register `task` like any other tool. Now when the model calls `task("reviewer",
> "check auth.py")`, your harness runs a *second* agent loop with the reviewer's prompt
> and tools, and feeds its answer back as the tool result. The "orchestrator" is just an
> agent whose only tool is `task`.
>
> **Running several workers at once is the same optional speed-up as before.** A plain
> `for` loop over the `task` calls gives identical results; the `ThreadPoolExecutor`
> code just runs them at the same time to save wall-clock time. Start sequential.
>
> Syntax heads-ups for reading the original:
>
> | In the original | What it is |
> |-----------------|------------|
> | `class Agent:` with `self._conversation` | the loop + its conversation list, bundled. Read `agent.run(task)` as `run_agent(instructions, task, tools)`. |
> | `@dataclass class AgentPreset` | a fixed-field dict (the `PRESETS` dict above). |
> | `@property def total_tokens` | a method you read like a field: `usage.total_tokens`. Here it just returns `input + output`. |
> | `def make_task_tool(...)` returning a `class TaskTool` | a **closure/factory** — a function that builds the `task` tool with the registry "baked in." The plain `task(role, prompt)` function above does the same job. |
> | the `asyncio` section (§8) | an *alternative* to threads. Skip it; threads (and plain loops) cover everything. |
>
> Read the rest of the phase for the ideas (isolated context, depth limits, disjoint
> file scopes). Build it with the functions above.

---

## Version 1 — Line-by-Line: the Same Loop, Pasted Twice

> **Why this version first?** Because the entire phase rests on one claim — *a sub-agent
> is just the same loop run again* — and the most convincing proof is to literally paste
> the loop a second time, inside the dispatch branch of a `task` tool, and watch it work.
> No `def`, no classes: just statements, two `while` loops, and the Responses-API
> handshake you already know from Phase 1.

### Step 1.1 — The outer loop with a *stub* `task` tool

First, build only the **orchestrator**: a straight-line script whose single tool, `task`,
doesn't spawn anything yet — it returns a placeholder string. This proves the outer half
of the handshake (the model calls `task`, we answer with a `function_call_output`
carrying the same `call_id`) before any sub-agent exists.

```python
# v1_subagent_inline.py — Step 1.1: orchestrator with a stub task tool
import json
from openai import OpenAI

client = OpenAI()
MODEL = "gpt-4o"

# The one tool the orchestrator has: delegate work to a sub-agent.
TASK_TOOL_SCHEMA = {
    "type": "function",
    "name": "task",
    "description": "Spawn a sub-agent to complete an independent task.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Full task prompt for the sub-agent.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}

# ---- THE OUTER LOOP: the orchestrator --------------------------------------
outer_items = [{
    "role": "user",
    "content": (
        "Use the task tool to ask a sub-agent to read README.md and "
        "summarize it in two sentences."
    ),
}]

while True:
    outer_resp = client.responses.create(
        model=MODEL,
        instructions=(
            "You are an orchestrator. Delegate work with the task tool, "
            "then report back what the sub-agent found."
        ),
        input=outer_items,
        tools=[TASK_TOOL_SCHEMA],
    )
    outer_items += list(outer_resp.output)
    outer_calls = [it for it in outer_resp.output if it.type == "function_call"]
    if not outer_calls:
        break                          # no tool calls -> the model is done

    for outer_call in outer_calls:
        print(f"[outer] model called {outer_call.name!r}")
        # STUB: no sub-agent yet — just answer the call with a placeholder.
        outer_items.append({
            "type": "function_call_output",
            "call_id": outer_call.call_id,
            "output": "[stub] Sub-agents are not built yet. Report that "
                      "delegation is not implemented.",
        })

print("\nFinal answer:", outer_resp.output_text)
```

#### ▶ Run it now

```
python v1_subagent_inline.py
```

You should see `[outer] model called 'task'` once, then a final answer in which the
orchestrator relays that delegation isn't implemented yet. Nothing new happened here —
this is exactly the Phase 1 loop with one tool. The interesting part is next.

### Step 1.2 — Paste the loop *again* inside the `task` branch

Now replace the stub. What goes in its place? **The same loop, copy-pasted**, with three
renames: its own transcript list (`inner_items` instead of `outer_items`), its own
instructions, and its own tool (`read_file` instead of `task`). The inner loop's final
text becomes the string we hand back as the outer call's `function_call_output`.

Here is the complete file. Read the two `while True:` blocks side by side — they are the
same code. That *is* the lesson.

```python
# v1_subagent_inline.py — Step 1.2: the inner loop pasted inline. No def, no classes.
import json
from openai import OpenAI

client = OpenAI()
MODEL = "gpt-4o"

# The orchestrator's only tool: delegate to a sub-agent.
TASK_TOOL_SCHEMA = {
    "type": "function",
    "name": "task",
    "description": "Spawn a sub-agent to complete an independent task.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Full task prompt for the sub-agent.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    },
}

# The sub-agent's only tool: read a file.
READ_FILE_SCHEMA = {
    "type": "function",
    "name": "read_file",
    "description": "Read a file and return its contents.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}

# ---- THE OUTER LOOP: the orchestrator --------------------------------------
outer_items = [{
    "role": "user",
    "content": (
        "Use the task tool to ask a sub-agent to read README.md and "
        "summarize it in two sentences."
    ),
}]

while True:
    outer_resp = client.responses.create(
        model=MODEL,
        instructions=(
            "You are an orchestrator. Delegate work with the task tool, "
            "then report back what the sub-agent found."
        ),
        input=outer_items,
        tools=[TASK_TOOL_SCHEMA],
    )
    outer_items += list(outer_resp.output)
    outer_calls = [it for it in outer_resp.output if it.type == "function_call"]
    if not outer_calls:
        break                          # orchestrator is done

    for outer_call in outer_calls:
        args = json.loads(outer_call.arguments)
        print(f"[outer] spawning a sub-agent for: {args['prompt'][:60]}...")

        # ==== THE INNER LOOP: the sub-agent — the SAME loop, pasted again ====
        inner_items = [{"role": "user", "content": args["prompt"]}]
        inner_answer = ""
        while True:
            inner_resp = client.responses.create(
                model=MODEL,
                instructions=(
                    "You are a careful assistant. Use read_file if needed, "
                    "then answer concisely."
                ),
                input=inner_items,
                tools=[READ_FILE_SCHEMA],
            )
            inner_items += list(inner_resp.output)
            inner_calls = [it for it in inner_resp.output
                           if it.type == "function_call"]
            if not inner_calls:
                inner_answer = inner_resp.output_text   # sub-agent is done
                break
            for inner_call in inner_calls:
                inner_args = json.loads(inner_call.arguments)
                print(f"  [inner] model called {inner_call.name!r}")
                try:
                    with open(inner_args["path"]) as f:
                        tool_result = f.read()
                except OSError as exc:
                    tool_result = f"[error] {exc}"
                inner_items.append({
                    "type": "function_call_output",
                    "call_id": inner_call.call_id,
                    "output": tool_result,
                })
        # ==== inner loop finished ============================================

        print("[outer] sub-agent finished.")
        # The sub-agent's final text is the task tool's output — a plain string.
        outer_items.append({
            "type": "function_call_output",
            "call_id": outer_call.call_id,
            "output": inner_answer,
        })

print("\nFinal answer:", outer_resp.output_text)
```

Notice what the two loops do and don't share. They share the *client* and the *model id*
— nothing else. `inner_items` is a **fresh list**: the sub-agent never sees the
orchestrator's conversation, and the orchestrator never sees the sub-agent's. The only
thing that crosses the boundary is `inner_answer`, a plain string, handed back under the
outer call's `call_id` exactly like any other tool result.

#### ▶ Run it now

```
python v1_subagent_inline.py
```

You should see `[outer] spawning a sub-agent...`, then one or more
`  [inner] model called 'read_file'` lines (the sub-agent doing its own tool calls in its
own conversation), then `[outer] sub-agent finished.`, and finally the orchestrator's
synthesised answer. Two complete agent loops ran — one inside the other's dispatch branch.

The pasted copy works, but it should also bother you: if you wanted the orchestrator to
have *two* tools, or sub-agents that can spawn sub-sub-agents, you'd be pasting loops
inside loops inside loops. That itch is exactly what Version 2 scratches.

---

## What changed from V1 → V2

- The **inner pasted loop becomes a plain function**, `run_subagent(task_description) -> str`,
  and the `task` dispatch branch shrinks to a single call.
- Then comes the punchline: the outer loop is the *same code too*, so both collapse into
  **one function, `run_agent(instructions, task, tools_dict)`** — called once at top level
  for the orchestrator and once, from inside the `task` tool, for the worker.
- Tools move from hardcoded `if` branches into a **`tools_dict`** of
  `{name: {"fn": ..., "schema": ...}}`, with tiny `dispatch` / `tools_for_api` helpers, so
  the loop body no longer names any tool.
- Nothing else changes: same model, same Responses-API handshake, same `call_id`
  discipline, same isolated transcripts. Run both versions on the same prompt and you get
  the same behavior.

---

## Version 2 — Functions: the Duplication Collapses

> **Why now?** Version 1 proved the idea by brute force — two copies of the loop. Version
> 2 keeps the behavior and deletes the duplication, in two small moves.

### Step 2.1 — Extract the inner loop into `run_subagent`

Take the pasted inner loop from Step 1.2, wrap it in a `def`, and return the final text.
The `task` branch in the outer loop becomes one line:

```python
def run_subagent(task_description):
    """The inner loop from Version 1, wrapped in a function. Returns final text."""
    inner_items = [{"role": "user", "content": task_description}]
    while True:
        inner_resp = client.responses.create(
            model=MODEL,
            instructions=("You are a careful assistant. Use read_file if "
                          "needed, then answer concisely."),
            input=inner_items,
            tools=[READ_FILE_SCHEMA],
        )
        inner_items += list(inner_resp.output)
        inner_calls = [it for it in inner_resp.output
                       if it.type == "function_call"]
        if not inner_calls:
            return inner_resp.output_text
        for inner_call in inner_calls:
            inner_args = json.loads(inner_call.arguments)
            try:
                with open(inner_args["path"]) as f:
                    tool_result = f.read()
            except OSError as exc:
                tool_result = f"[error] {exc}"
            inner_items.append({
                "type": "function_call_output",
                "call_id": inner_call.call_id,
                "output": tool_result,
            })
```

…and in the outer loop, the whole `==== THE INNER LOOP ====` block becomes:

```python
        outer_items.append({
            "type": "function_call_output",
            "call_id": outer_call.call_id,
            "output": run_subagent(args["prompt"]),
        })
```

#### ▶ Run it now

Replace the inner-loop block in `v1_subagent_inline.py` with the function above (put the
`def` near the top of the file) and run it again. Same output as Step 1.2 — the program
didn't change, only its shape did.

### Step 2.2 — One loop function for both: `run_agent`

Look at `run_subagent` and the outer loop again. They differ only in their
*configuration*: which instructions, which tools, which starting prompt. So generalize
once — `run_agent(instructions, task, tools_dict)` — and call it twice.

Here is the complete Version 2 file — everything above expressed as runnable code. It uses only the concepts from Phases 1–2: a loop, a conversation list, `client.responses.create`, and plain functions as tools.

```python
# v2_subagent.py  — minimal sub-agent demo, plain functions, no classes
import json
from openai import OpenAI

client = OpenAI()
MODEL = "gpt-4o"


# ---------------------------------------------------------------------------
# Helper: convert a plain-function tool dict to the schema list the API needs
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# The core loop — returns a text answer, owns its own conversation list
# ---------------------------------------------------------------------------

def run_agent(instructions, task, tools_dict):
    """Run a fresh agent loop and return the final text answer."""
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
            return resp.output_text           # done
        for fc in calls:
            conversation.append({
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": dispatch(tools_dict, fc.name, fc.arguments),
            })


# ---------------------------------------------------------------------------
# A real tool the sub-agent can use
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# The `task` tool — THIS is the key trick
# ---------------------------------------------------------------------------
# When the orchestrator calls task(role, prompt), we just call run_agent again.
# The sub-agent gets its own fresh conversation and a limited tool set.

ORCHESTRATOR_INSTRUCTIONS = (
    "You are a helpful orchestrator. When given a task, use the `task` tool "
    "to delegate work to a specialist sub-agent and report back what it found."
)

SUB_AGENT_INSTRUCTIONS = (
    "You are a careful reviewer. Read the requested file and summarise any "
    "issues you find. Return a short bullet list."
)


def task(role, prompt):
    """Spawn a sub-agent and return its answer as a plain string."""
    # For now, every role gets the same instructions and tools.
    # Version 3 (presets) will turn this into a proper role/preset lookup.
    print(f"  [task] spawning sub-agent for role={role!r} ...")
    result = run_agent(SUB_AGENT_INSTRUCTIONS, prompt, ALL_TOOLS)
    print(f"  [task] sub-agent finished.")
    return result


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


# ---------------------------------------------------------------------------
# Run the orchestrator
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    answer = run_agent(
        ORCHESTRATOR_INSTRUCTIONS,
        "Use the task tool to ask a reviewer sub-agent to check README.md for clarity.",
        ORCHESTRATOR_TOOLS,
    )
    print("\nFinal answer:", answer)
```

#### ▶ Run it now

```
python v2_subagent.py
```

You should see one `[task] spawning sub-agent...` line appear while the orchestrator is running, then `[task] sub-agent finished.`, and finally the orchestrator's synthesised answer. The sub-agent ran a completely separate conversation with its own tool calls, returned plain text, and that text became the tool output the orchestrator reasoned about.

**What you've just seen:** one call to `run_agent` (the orchestrator) caused another call to `run_agent` (the sub-agent) through the `task` tool. That's the entire mechanism. Everything that follows is making this more organized and capable.

---

## What changed from V2 → V3

- `run_agent`'s parameters (`instructions`, the tool set, plus model and client) become
  **constructor arguments of an `Agent` class**; the local `conversation` list becomes
  `self._conversation`. `agent.run(task)` is `run_agent(...)` with the configuration
  pre-bundled.
- The hand-rolled `tools_dict` is replaced by **Phase 2's `ToolRegistry`**, so schemas,
  dispatch, and error-catching come for free.
- The role-string check inside `task` grows into a **preset table** — an `AgentPreset`
  dataclass mapping each role name to its instructions and *allowed tool names*.
- The plain `task(role, prompt)` function becomes **`dispatch_subagent` + `make_task_tool`**,
  a factory that bakes the parent's registry, client, and depth into the tool.
- One genuinely new safety feature appears: a **`depth` counter** carried from parent to
  child, so sub-agents spawning sub-agents can't recurse forever.
- Behavior is unchanged: a sub-agent is still your loop called again — now spelled
  `Agent(...).run(prompt)` inside a tool.

---

## Version 3 — Classes: the Same Harness, Organized

> **Framing.** Nothing in this version is a new idea — it is Version 2 with its state
> grouped into objects, in the shape the real package uses
> (`code/agent_harness/subagents.py`). Three steps: bundle the loop into an `Agent`
> class, turn roles into presets, and expose spawning as a registered `task` tool. The
> complete file for this version appears in [§7 — Full Code](#7-full-code--subagentspy);
> each step below is a replace-this-block increment toward it.

### Step 3.1 — Refactoring the Loop into a Reusable `Agent` Class

> **Why now?** In Version 2 we passed `instructions`, `task`, and `tools_dict` as separate arguments everywhere. When you want to run many sub-agents — or reuse the same agent for different tasks — it is cleaner to bundle the loop with its conversation into an object. This step does exactly that refactor. No new capability is added; the behavior is identical.

Until now the agent loop lived in a standalone function or script. To support sub-agents we need agents to be *values* — objects you can instantiate, configure, and pass around. The refactor is small but important.

```python
# agent.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from tools.registry import ToolRegistry

MODEL = "gpt-4o"


@dataclass
class UsageSummary:
    """Accumulated token usage across all loop iterations."""
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return
        self.input_tokens += getattr(usage, "input_tokens", 0)
        self.output_tokens += getattr(usage, "output_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __repr__(self) -> str:
        return (
            f"UsageSummary(in={self.input_tokens}, "
            f"out={self.output_tokens}, total={self.total_tokens})"
        )


class Agent:
    """
    A self-contained agent: owns its transcript, runs the tool loop,
    and returns a final text answer.

    Parameters
    ----------
    name:
        Human-readable label used in logs and error messages.
    instructions:
        System-prompt text. Passed as the ``instructions`` argument to
        ``responses.create``.  Defaults to a sensible generic prompt.
    registry:
        The ``ToolRegistry`` this agent may call.  Pass ``None`` for a
        tool-less agent.
    model:
        OpenAI model identifier.
    client:
        Shared ``OpenAI`` client.  If ``None`` a new one is created.
    max_iterations:
        Hard cap on loop iterations — prevents runaway tool loops.
    depth:
        Current recursion depth.  Sub-agents receive ``parent.depth + 1``.
        The harness refuses to spawn agents beyond ``MAX_DEPTH``.
    """

    MAX_DEPTH: int = 4          # class-level hard cap on nesting depth
    MAX_ITERATIONS: int = 30    # maximum tool-call loop iterations

    def __init__(
        self,
        name: str = "agent",
        instructions: str = "You are a helpful assistant.",
        registry: ToolRegistry | None = None,
        model: str = MODEL,
        client: OpenAI | None = None,
        max_iterations: int = MAX_ITERATIONS,
        depth: int = 0,
    ) -> None:
        self.name = name
        self.instructions = instructions
        self.registry = registry or ToolRegistry()
        self.model = model
        self.client = client or OpenAI()
        self.max_iterations = max_iterations
        self.depth = depth

        # Mutable state — reset between independent tasks via .reset()
        self._conversation: list[dict] = []
        self.usage = UsageSummary()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Wipe transcript and usage counters (useful when reusing an
        Agent instance for a second independent task)."""
        self._conversation = []
        self.usage = UsageSummary()

    def run(self, task: str) -> str:
        """
        Run the agent loop for a single task.

        Appends a user message for *task*, then iterates until the model
        produces a final text output with no pending tool calls.

        Returns the final text string.
        """
        self._conversation.append({"role": "user", "content": task})

        tools_schema = self.registry.schemas()   # [] if no tools

        for iteration in range(self.max_iterations):
            resp = self.client.responses.create(
                model=self.model,
                instructions=self.instructions,
                input=self._conversation,
                tools=tools_schema if tools_schema else [],
            )
            self.usage.add(getattr(resp, "usage", None))

            # Collect function_call items from this response
            tool_calls = [
                item for item in resp.output
                if item.type == "function_call"
            ]

            # Extend the transcript with the model's raw output
            self._conversation.extend(resp.output)

            if not tool_calls:
                # No tool calls → the model has finished
                return self._extract_text(resp)

            # Execute tool calls, possibly in parallel
            outputs = self.registry.dispatch_parallel(tool_calls)
            self._conversation.extend(outputs)

        raise RuntimeError(
            f"Agent '{self.name}' exceeded {self.max_iterations} iterations."
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_text(self, resp: Any) -> str:
        for item in resp.output:
            if getattr(item, "type", None) == "message":
                for block in item.content:
                    if getattr(block, "type", None) == "output_text":
                        return block.text
        return ""

    def __repr__(self) -> str:
        return (
            f"Agent(name={self.name!r}, depth={self.depth}, "
            f"model={self.model!r})"
        )
```

Key design decisions:

- **One transcript per instance.** Calling `.run()` on a fresh `Agent` starts with a clean slate. There is no shared global state between agents.
- **`depth` is carried from parent to child.** When the orchestrator spawns a sub-agent it passes `depth=self.depth + 1`, allowing the guard to trigger before a recursion goes too deep.
- **`registry.dispatch_parallel` is the Phase 2 machinery.** Phase 2 already handles running multiple tool calls concurrently; nothing new is needed here.

#### ▶ Run it now

After putting the `Agent` class in `agent.py`, rewrite Version 2's orchestrator using it:

```python
# v3_agent_class.py  — same behavior as v2_subagent.py, using the Agent class
from agent import Agent
from tools.registry import ToolRegistry

# Register the same read_file tool via ToolRegistry (Phase 2 style)
# ... (setup identical to your Phase 2 harness) ...

sub_registry = ToolRegistry()
sub_registry.register(read_file)   # @tool-decorated function from Phase 2

def task_fn(role: str, prompt: str) -> str:
    """Spawn a fresh sub-agent and return its answer."""
    print(f"  [task] spawning {role!r} ...")
    worker = Agent(
        name=role,
        instructions="Read the file and return a short bullet list of issues.",
        registry=sub_registry,
    )
    return worker.run(prompt)

# Register task_fn as a tool in the orchestrator's registry
orchestrator_registry = ToolRegistry()
# ... register task_fn as a tool ...

orchestrator = Agent(
    name="orchestrator",
    instructions="Delegate to sub-agents via the task tool. Report what they find.",
    registry=orchestrator_registry,
)
print(orchestrator.run("Check README.md for clarity issues."))
```

The behavior is identical to Version 2. The `Agent` class is just `run_agent` with its conversation stored as `self._conversation` and its configuration as constructor arguments.

### Step 3.2 — Agent Presets: Named Roles with Fixed Instructions and Tools

> **Why now?** In Step 3.1 you hardcoded the sub-agent's instructions and tool set inside `task_fn`. Once you have more than one role (researcher, coder, reviewer …) you want a lookup table so the orchestrator can ask for a role by name and get the right configuration automatically. That table is all a "preset" is.

Define a small registry of named roles, each with a system prompt and a list of allowed tool names.

```python
# subagents.py  (partial — full file at the end of this phase)
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from agent import Agent
from tools.registry import ToolRegistry
from tools.base import tool

# ---------------------------------------------------------------------------
# Agent presets
# ---------------------------------------------------------------------------

@dataclass
class AgentPreset:
    """Blueprint for a sub-agent role."""
    instructions: str
    allowed_tools: list[str]  # tool names from the parent registry to expose
    model: str = "gpt-4o"


AGENT_PRESETS: dict[str, AgentPreset] = {
    "researcher": AgentPreset(
        instructions=(
            "You are a research specialist. Your job is to gather information "
            "accurately and return a concise, well-structured summary. "
            "Cite sources where possible. Return ONLY the summary — no preamble."
        ),
        allowed_tools=["web_search", "read_file", "list_directory"],
    ),
    "coder": AgentPreset(
        instructions=(
            "You are a software engineer. Implement exactly what is requested. "
            "Return ONLY the result: the code, the diff, or a terse status. "
            "Do not add unsolicited commentary."
        ),
        allowed_tools=["read_file", "write_file", "run_command", "list_directory"],
    ),
    "reviewer": AgentPreset(
        instructions=(
            "You are a code reviewer. Read the artefacts and return a structured "
            "list of findings: CRITICAL, WARNING, or INFO, each with file and line. "
            "Return ONLY the findings list."
        ),
        allowed_tools=["read_file", "list_directory"],
    ),
    "analyst": AgentPreset(
        instructions=(
            "You are a data analyst. Examine the provided data or files and "
            "return a concise summary of key metrics, trends, and anomalies."
        ),
        allowed_tools=["read_file", "run_command"],
    ),
    "generic": AgentPreset(
        instructions="You are a helpful assistant. Complete the task and return a concise result.",
        allowed_tools=[],   # caller must supply tools explicitly
    ),
}
```

| Role | Typical use | Tools exposed |
|------|-------------|---------------|
| `researcher` | Gather and synthesise information | `web_search`, `read_file`, `list_directory` |
| `coder` | Write or modify code | `read_file`, `write_file`, `run_command`, `list_directory` |
| `reviewer` | Read-only analysis and critique | `read_file`, `list_directory` |
| `analyst` | Metric extraction from data/logs | `read_file`, `run_command` |
| `generic` | Fallback; caller supplies tools | (none by default) |

Now update `task_fn` to do a preset lookup:

```python
def task_fn(role: str, prompt: str) -> str:
    """Look up the preset for `role`, build a restricted registry, run a sub-agent."""
    preset = AGENT_PRESETS.get(role, AGENT_PRESETS["generic"])

    # Give the worker only the tools its role allows
    worker_registry = ToolRegistry()
    for tool_name in preset.allowed_tools:
        t = full_registry.get(tool_name)   # full_registry has everything
        if t is not None:
            worker_registry.register(t)

    worker = Agent(
        name=f"{role}-worker",
        instructions=preset.instructions,
        registry=worker_registry,
    )
    return worker.run(prompt)
```

#### ▶ Run it now

```python
# Quick test: ask a reviewer sub-agent to check a file
result = task_fn("reviewer", "Check auth.py for security issues.")
print(result)
```

The reviewer agent receives only `read_file` and `list_directory` — it literally cannot call `write_file` even if you wanted it to. That restricted view comes directly from `preset.allowed_tools`.

### Step 3.3 — Sub-Agents as a Tool: Wiring It to the Orchestrator

> **Why now?** So far `task_fn` is a plain Python function. To let the orchestrator *model* decide when to delegate, you need to expose it as a tool the model can call — exactly the same way you exposed `read_file` in Phase 2.

The elegance of this architecture is that from the orchestrator's perspective, spawning a sub-agent is just another tool call. The model emits a `function_call` item with `name="task"`, the harness intercepts it, instantiates and runs a worker `Agent`, and returns its final text as the `function_call_output`. The model never knows it talked to another model; it just sees a tool result.

This means the orchestrator needs no special awareness of sub-agents in its loop. The existing Phase 2 dispatch machinery handles everything — including parallelism.

#### The `dispatch_subagent` function

```python
# subagents.py (continued)

MAX_SUBAGENT_DEPTH = Agent.MAX_DEPTH  # 4 — inherited from Agent class


def dispatch_subagent(
    *,
    role: str,
    task: str,
    parent_registry: ToolRegistry,
    client: OpenAI,
    depth: int,
    extra_instructions: str = "",
) -> str:
    """
    Instantiate a fresh sub-agent for *role*, run it on *task*, return its
    final text.  Raises ``RuntimeError`` if depth exceeds the hard cap.

    Parameters
    ----------
    role:
        Key into ``AGENT_PRESETS``.  Falls back to "generic" if unknown.
    task:
        The prompt sent to the sub-agent as its initial user message.
    parent_registry:
        The orchestrator's full tool registry.  The sub-agent receives a
        *filtered* view containing only the tools permitted for this role.
    client:
        Shared ``OpenAI`` client (HTTP connection pool is reused).
    depth:
        Current nesting depth — passed through so the sub-agent enforces
        the cap on any of *its* tool calls.
    extra_instructions:
        Optional text appended to the preset's system prompt.
    """
    if depth >= MAX_SUBAGENT_DEPTH:
        return (
            f"[error] Sub-agent depth limit ({MAX_SUBAGENT_DEPTH}) reached. "
            "Task not executed."
        )

    preset = AGENT_PRESETS.get(role, AGENT_PRESETS["generic"])

    # Build a restricted registry containing only allowed tools
    sub_registry = ToolRegistry()
    for tool_name in preset.allowed_tools:
        t = parent_registry.get(tool_name)
        if t is not None:
            sub_registry.register(t)

    instructions = preset.instructions
    if extra_instructions:
        instructions = f"{instructions}\n\n{extra_instructions}"

    agent = Agent(
        name=f"{role}-depth{depth}",
        instructions=instructions,
        registry=sub_registry,
        model=preset.model,
        client=client,
        depth=depth,
    )

    try:
        return agent.run(task)
    except Exception as exc:  # noqa: BLE001
        # Sub-agent errors become error strings, not exceptions.
        # The orchestrator can decide what to do.
        return f"[error] Sub-agent '{role}' failed: {exc}"
```

Three things are worth emphasising here.

**Restricted registry.** The sub-agent receives a *filtered* view of the parent's tools. A `reviewer` agent literally cannot call `write_file` even if the parent registry has one — the tool does not exist from its perspective. This is the simplest possible permissions model; Phase 5's hook system can layer additional checks on top.

**Isolated transcript.** The `Agent` object is created fresh, with an empty `_conversation`. No transcript leaks between parent and child.

**Errors as strings.** The `except` block returns a descriptive string rather than re-raising. This is the same contract Phase 2 established for tools: errors are information the model can reason about, not exceptions that kill the loop.

#### The `task` tool

Now expose `dispatch_subagent` as a tool the orchestrator can call.

```python
# subagents.py (continued)

def make_task_tool(
    parent_registry: ToolRegistry,
    client: OpenAI,
    parent_depth: int,
) -> "TaskTool":
    """
    Factory that captures the parent context in the closure.
    Returns a ``Tool`` instance ready for registration.
    """

    class TaskTool:
        name = "task"
        description = (
            "Spawn a sub-agent to complete an independent task. "
            "Use this to parallelise work: call 'task' multiple times in one "
            "response to run workers concurrently. Each worker has its own "
            "isolated context. "
            "Available roles: researcher, coder, reviewer, analyst, generic."
        )
        parameters = {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": list(AGENT_PRESETS.keys()),
                    "description": (
                        "The sub-agent persona to instantiate. Determines "
                        "which tools and system prompt the worker receives."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "One-sentence summary of what this worker should do. "
                        "Used in progress logging."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "The full task prompt sent to the sub-agent. Be specific: "
                        "include all context the worker needs; it cannot read the "
                        "parent's conversation."
                    ),
                },
            },
            "required": ["role", "description", "prompt"],
            "additionalProperties": False,
        }

        def run(self, *, role: str, description: str, prompt: str) -> str:
            print(f"    [task] spawning {role!r}: {description}")
            return dispatch_subagent(
                role=role,
                task=prompt,
                parent_registry=parent_registry,
                client=client,
                depth=parent_depth + 1,
            )

    return TaskTool()
```

Register this tool in the orchestrator's registry and the model gains the ability to spawn workers. The schema's `enum` for `role` tells the model exactly which values are valid, which reduces hallucination significantly.

#### ▶ Run it now

```python
# v3_task_tool.py  — orchestrator with a real task tool
from openai import OpenAI
from agent import Agent
from tools.registry import ToolRegistry
from subagents import make_task_tool, AGENT_PRESETS

client = OpenAI()

# Full tool registry that sub-agents may draw from
full_registry = ToolRegistry()
full_registry.register(read_file)        # your @tool-decorated functions
full_registry.register(list_directory)

# Orchestrator only has the task tool — it delegates everything
orchestrator_registry = ToolRegistry()
orchestrator_registry.register(
    make_task_tool(full_registry, client, parent_depth=0)
)

orchestrator = Agent(
    name="orchestrator",
    instructions=(
        "You are a senior engineer. Break complex tasks into subtasks and "
        "delegate each one to a specialist sub-agent using the 'task' tool. "
        "After receiving results, synthesise a final answer."
    ),
    registry=orchestrator_registry,
    client=client,
)

print(orchestrator.run("Review auth.py and list any security concerns."))
```

The orchestrator will call `task("reviewer", ..., "Check auth.py ...")`. Your harness intercepts that, runs a reviewer sub-agent with only `read_file` and `list_directory`, and returns the text. The model then synthesises the final report.

---

## Step 4 — Parallel Sub-Agents (Optional Speed-Up)

> **Why now?** Everything so far works serially — sub-agents run one at a time. If the orchestrator issues multiple `task` calls in a single response, Phase 2's `dispatch_parallel` already runs them concurrently via `ThreadPoolExecutor`. This step makes that visible, adds per-worker timing, and explains when it helps. **You can skip this step** and everything still works; you just wait longer.

When the orchestrator emits **multiple `task` tool calls in a single response**, Phase 2's `dispatch_parallel` runs them concurrently via `ThreadPoolExecutor`. Each sub-agent makes its own independent OpenAI HTTP calls and maintains its own transcript, so there is zero interference between workers.

The mechanism is already built. This section shows it explicitly and adds a small wrapper that makes the concurrency visible and handles per-worker failure isolation.

```python
# subagents.py (continued)

MAX_CONCURRENT_SUBAGENTS = 8   # cap the thread pool for sub-agent work


def run_subagents_parallel(
    tasks: list[dict],   # list of {"role": ..., "description": ..., "prompt": ..., "call_id": ...}
    parent_registry: ToolRegistry,
    client: OpenAI,
    parent_depth: int,
) -> list[dict]:
    """
    Run a batch of sub-agent tasks concurrently.

    Returns a list of ``function_call_output`` dicts ready for appending
    to the parent's transcript, in the SAME ORDER as the input list.
    """
    results: dict[str, str] = {}   # call_id -> result string

    n = len(tasks)
    workers = min(n, MAX_CONCURRENT_SUBAGENTS)
    print(f"\n  [orchestrator] running {n} sub-agent(s) in parallel "
          f"(max_workers={workers}) …")
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_id = {
            pool.submit(
                dispatch_subagent,
                role=t["role"],
                task=t["prompt"],
                parent_registry=parent_registry,
                client=client,
                depth=parent_depth + 1,
            ): t["call_id"]
            for t in tasks
        }

        for future in as_completed(future_to_id):
            call_id = future_to_id[future]
            try:
                results[call_id] = future.result()
            except Exception as exc:  # noqa: BLE001
                # One worker failing must not cancel siblings.
                results[call_id] = f"[error] Worker crashed unexpectedly: {exc}"

    elapsed = time.perf_counter() - t0
    print(f"  [orchestrator] all sub-agents done in {elapsed:.1f}s")

    # Return outputs in the original order (preserves call_id alignment)
    return [
        {
            "type": "function_call_output",
            "call_id": t["call_id"],
            "output": results[t["call_id"]],
        }
        for t in tasks
    ]
```

### 4.1 Integrating parallel dispatch into `ToolRegistry`

Phase 2's `ToolRegistry.dispatch_parallel` already uses `ThreadPoolExecutor`. The only addition needed is separating `task` tool calls from regular tool calls so that `run_subagents_parallel` handles the former.

```python
# In the agent loop — augmented dispatch step
# (inside Agent.run, replacing the existing dispatch_parallel call)

def _dispatch_step(
    self,
    tool_calls: list[Any],
    sub_registry_context: dict | None = None,
) -> list[dict]:
    """
    Dispatch a mixed batch of tool calls:
    - ``task`` calls go to ``run_subagents_parallel``
    - everything else goes to ``self.registry.dispatch_parallel``

    ``sub_registry_context`` carries the parent_registry and depth
    needed to launch sub-agents; None means sub-agent spawning is
    not available for this agent (leaf worker).
    """
    task_calls = []
    regular_calls = []

    for tc in tool_calls:
        if tc.name == "task" and sub_registry_context:
            args = json.loads(tc.arguments)
            task_calls.append({
                "role": args.get("role", "generic"),
                "description": args.get("description", ""),
                "prompt": args.get("prompt", ""),
                "call_id": tc.call_id,
            })
        else:
            regular_calls.append(tc)

    outputs = []

    if regular_calls:
        outputs.extend(self.registry.dispatch_parallel(regular_calls))

    if task_calls and sub_registry_context:
        outputs.extend(
            run_subagents_parallel(
                task_calls,
                parent_registry=sub_registry_context["registry"],
                client=sub_registry_context["client"],
                parent_depth=sub_registry_context["depth"],
            )
        )

    return outputs
```

### 4.2 Why this is safe

Each sub-agent is an independent Python object in its own thread. There is no shared mutable state between workers because:

- Each `Agent` instance owns its own `_conversation` list.
- The `OpenAI` client is thread-safe for concurrent reads (HTTP/2 multiplexing or connection-per-thread depending on `httpx` version).
- Tool results are accumulated in a local `dict` keyed by `call_id` and only merged back into the parent after all futures complete.
- A worker crash is caught by the `except` in `as_completed` and becomes an error string, not a propagated exception.

The pattern is identical to Phase 2's parallel tool execution. The only difference is that each "tool" is itself an LLM call — potentially spawning further tool calls internally.

### 4.3 Making the parallelism visible — timestamps

Add a thin wrapper around `dispatch_subagent` for debugging:

```python
def timed_dispatch(role: str, description: str, task: str, **kwargs) -> tuple[float, str]:
    """Run a sub-agent and time it. Returns (elapsed_seconds, result)."""
    t0 = time.perf_counter()
    result = dispatch_subagent(role=role, task=task, **kwargs)
    elapsed = time.perf_counter() - t0
    return elapsed, result


# In run_subagents_parallel, replace the submit call:
future_to_meta = {
    pool.submit(
        timed_dispatch,
        role=t["role"],
        description=t["description"],
        task=t["prompt"],
        parent_registry=parent_registry,
        client=client,
        depth=parent_depth + 1,
    ): t
    for t in tasks
}

for future in as_completed(future_to_meta):
    meta = future_to_meta[future]
    elapsed, result = future.result()
    print(f"    [done] {meta['role']!r} finished in {elapsed:.1f}s")
    results[meta["call_id"]] = result
```

Sample output:
```text
  [orchestrator] running 3 sub-agent(s) in parallel (max_workers=3) …
    [task] spawning 'researcher': summarise architecture
    [task] spawning 'analyst': TODO inventory
    [task] spawning 'reviewer': security concerns
    [done] 'analyst' finished in 4.1s
    [done] 'reviewer' finished in 5.8s
    [done] 'researcher' finished in 6.2s
  [orchestrator] all sub-agents done in 6.2s
```

The wall time equals the slowest worker (researcher at 6.2 s), not their sum (16.1 s).

---

## 5. A Complete Worked Example — Dynamic Fan-Out

This example demonstrates the full pattern end-to-end. The orchestrator receives a repository audit task and autonomously decides to fan it out into three parallel workers.

### 5.1 Setup

```python
# example_orchestrator.py
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from agent import Agent
from tools.registry import ToolRegistry
from tools.base import tool
from subagents import (
    AGENT_PRESETS,
    make_task_tool,
    run_subagents_parallel,
    dispatch_subagent,
    MAX_CONCURRENT_SUBAGENTS,
)

# ---------------------------------------------------------------------------
# Define the "real" tools available to sub-agents
# ---------------------------------------------------------------------------

@tool
def read_file(path: str) -> str:
    """Read a file from disk and return its contents."""
    try:
        with open(path) as f:
            return f.read()
    except OSError as exc:
        return f"[error] {exc}"


@tool
def list_directory(path: str = ".") -> str:
    """List the contents of a directory."""
    import os
    try:
        entries = sorted(os.listdir(path))
        return "\n".join(entries)
    except OSError as exc:
        return f"[error] {exc}"


@tool
def run_command(command: str) -> str:
    """Run a shell command and return stdout+stderr (read-only operations only)."""
    import subprocess
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "[error] Command timed out after 30s"
    except Exception as exc:  # noqa: BLE001
        return f"[error] {exc}"


# ---------------------------------------------------------------------------
# Build registries
# ---------------------------------------------------------------------------

full_registry = ToolRegistry()
full_registry.register(read_file)
full_registry.register(list_directory)
full_registry.register(run_command)

# The orchestrator's registry contains ONLY the task tool.
# It has no direct access to file/shell tools — it delegates everything.
orchestrator_registry = ToolRegistry()
client = OpenAI()

task_tool = make_task_tool(
    parent_registry=full_registry,
    client=client,
    parent_depth=0,
)
orchestrator_registry.register(task_tool)


# ---------------------------------------------------------------------------
# Orchestrator agent
# ---------------------------------------------------------------------------

ORCHESTRATOR_INSTRUCTIONS = """
You are a senior engineering lead orchestrating a team of specialist agents.

When given a complex task, break it into INDEPENDENT subtasks and spawn
specialist sub-agents using the 'task' tool. Emit ALL task calls in a SINGLE
response so they run in parallel — do NOT call 'task' one at a time.

After receiving the workers' results, synthesise them into a single, coherent
final report. Do not repeat verbatim what each worker said; distil and integrate.

Available sub-agent roles: researcher, coder, reviewer, analyst, generic.
"""

orchestrator = Agent(
    name="orchestrator",
    instructions=ORCHESTRATOR_INSTRUCTIONS,
    registry=orchestrator_registry,
    client=client,
    depth=0,
)


# ---------------------------------------------------------------------------
# Run the audit
# ---------------------------------------------------------------------------

REPO_PATH = "/path/to/repo"   # set to a real path when running

audit_task = f"""
Perform a comprehensive audit of the repository at {REPO_PATH}.

Return a structured report covering:
1. Architecture overview — key components, their responsibilities, and how they interact.
2. TODO / FIXME inventory — every TODO or FIXME comment in the codebase.
3. Security concerns — obvious issues such as hardcoded secrets, unsafe shell invocations,
   missing input validation, and insecure defaults.

Spawn three sub-agents in PARALLEL — one per section — to do the work concurrently.
Each worker should return a concise, structured summary (not raw dumps).
"""

print("=" * 60)
print("Starting repository audit …")
print("=" * 60)
t_start = time.perf_counter()

final_report = orchestrator.run(audit_task)

elapsed = time.perf_counter() - t_start
print(f"\n{'=' * 60}")
print(f"Audit complete in {elapsed:.1f}s")
print("=" * 60)
print(final_report)
print(f"\nToken usage: {orchestrator.usage}")
```

### 5.2 Representative execution transcript

```text
============================================================
Starting repository audit …
============================================================

  [orchestrator] running 3 sub-agent(s) in parallel (max_workers=3) …
    [task] spawning 'researcher': summarise repository architecture
    [task] spawning 'analyst': enumerate all TODO and FIXME comments
    [task] spawning 'reviewer': identify security concerns

  [orchestrator] all sub-agents done in 6.2s

============================================================
Audit complete in 8.7s
============================================================

## Repository Audit Report

### 1. Architecture

The repository follows a layered design with three main packages:

- **`core/`** — domain models and business logic; no I/O dependencies.
- **`api/`** — FastAPI routers that translate HTTP into core operations.
- **`infra/`** — database adapters (SQLAlchemy), cache (Redis), and
  third-party client wrappers.

Communication flows strictly downward: `api` → `core` → `infra`.
No circular imports were found.

### 2. TODO / FIXME Inventory (17 items)

| File | Line | Severity | Comment |
|------|------|----------|---------|
| core/auth.py | 42 | WARNING | TODO: replace MD5 with bcrypt |
| api/upload.py | 118 | INFO | TODO: add file-size validation |
| infra/db.py | 77 | WARNING | FIXME: connection pool leak on timeout |
| … | … | … | … |

### 3. Security Concerns

**CRITICAL**
- `infra/shell_runner.py:34` — `subprocess.run(user_input, shell=True)` with
  no sanitisation. Arbitrary code execution risk.
- `config/settings.py:12` — AWS secret key hardcoded as string literal.

**WARNING**
- `api/auth.py:89` — JWT `algorithm` parameter accepts caller-supplied value.
  Pin to `["HS256"]`.
- `core/auth.py:42` — MD5 used for password hashing (noted in TODO above).

**INFO**
- No `Content-Security-Policy` header set in middleware stack.

Token usage: UsageSummary(in=14823, out=2341, total=17164)
```

The three workers ran concurrently (6.2 s wall time vs. ~18 s serial) and the orchestrator spent 2.5 s synthesising the final report. The parent's transcript contains only three tool outputs — the summaries — rather than the raw file contents each worker processed.

---

## 6. Design Considerations

### 6.1 Depth limits and recursion guards

Sub-agents can spawn sub-sub-agents if their role allows the `task` tool. Without a guard this creates a fork bomb that multiplies cost exponentially.

```
depth 0: orchestrator spawns 3 workers
depth 1: each worker spawns 3 sub-workers  → 9 agents
depth 2: each spawns 3 more               → 27 agents
depth 3: …                                → 81 agents
```

Two guards are required, not one:

1. **Depth cap** — `Agent.MAX_DEPTH = 4`. `dispatch_subagent` checks `depth >= MAX_DEPTH` before instantiating an agent and returns an error string. Set this to 2 or 3 for most production workloads; 4 is the absolute maximum you should ever need.

2. **Concurrent worker cap** — `MAX_CONCURRENT_SUBAGENTS = 8`. Even at depth 2, a poorly-prompted orchestrator could try to spawn 50 workers. The `ThreadPoolExecutor(max_workers=...)` cap serialises excess work rather than letting it all fire at once.

Do not rely on the model obeying the instructions. The guards must be in the harness code.

```python
# Enforced in dispatch_subagent — not optional
if depth >= MAX_SUBAGENT_DEPTH:
    return (
        f"[error] Sub-agent depth limit ({MAX_SUBAGENT_DEPTH}) reached. "
        "Task not executed to prevent runaway recursion."
    )
```

### 6.2 Cost and token accounting across the tree

Each sub-agent call to `responses.create` incurs its own token cost. The parent sees none of this; it only sees the output string. To get full cost visibility, aggregate usage bottom-up.

```python
# Augment dispatch_subagent to return usage alongside the result
@dataclass
class SubAgentResult:
    output: str
    usage: UsageSummary


def dispatch_subagent_with_usage(...) -> SubAgentResult:
    agent = Agent(...)
    try:
        output = agent.run(task)
        return SubAgentResult(output=output, usage=agent.usage)
    except Exception as exc:
        return SubAgentResult(
            output=f"[error] {exc}",
            usage=UsageSummary(),
        )
```

Then accumulate in the orchestrator:

```python
total_usage = UsageSummary()
total_usage.add(orchestrator.usage)
for result in subagent_results:
    total_usage.add(result.usage)
```

For production systems, log per-agent token consumption so you can identify which roles are most expensive.

### 6.3 Context isolation as a design feature

It is tempting to think that giving the orchestrator full visibility into every worker's internal reasoning would improve quality. In practice the opposite is true.

The parent's context budget is finite. If each worker dumps 2,000 tokens of raw reasoning into the parent transcript, three workers consume 6,000 tokens before the orchestrator writes a single word. The model's attention on its own synthesis task diminishes as the context grows.

The right interface between orchestrator and worker is a **narrow, structured result**. The orchestrator's prompt should specify the output format explicitly:

```
Return your findings as a JSON object with keys:
  "summary" (≤100 words), "items" (list of findings), "confidence" ("high"|"medium"|"low")
```

This mirrors how good human teams work: the junior writes a full analysis in their notes, hands the manager a one-page memo.

### 6.4 When NOT to use sub-agents

Sub-agents add latency (one full LLM call to spawn a worker that makes more LLM calls), token overhead (each agent has its own system prompt and task framing), and complexity. They are the wrong tool when:

- **Work is tightly sequential.** If step B depends on step A's output, parallelism gains nothing. Run it in a single agent.
- **State is shared and mutable.** Two coders writing to the same file at the same time will produce conflicts (see §6.6). Assign disjoint scopes or run sequentially.
- **The task is tiny.** A sub-agent that does a single `read_file` and returns is slower than doing the read directly in the parent. Reserve sub-agents for tasks that justify the overhead: multi-step reasoning, multiple tool calls, or work that produces large intermediate output.
- **Reliability is critical and errors compound.** Each hop is a new failure point. A three-deep tree with each node at 95% reliability has an 86% end-to-end reliability. Prefer shallow trees for production-critical paths.

### 6.5 Result schemas — getting structured output from workers

Workers should return structured, concise results. Two techniques:

**Option A — Prompt engineering.** The preset's `instructions` explicitly specifies the output format. Workers reliably follow format instructions when they are in the system prompt rather than the task prompt.

**Option B — Structured outputs.** Pass `text={"format": {"type": "json_schema", "name": "WorkerResult", "schema": {...}}}` to `responses.create` in the sub-agent's `run` method. This guarantees schema conformance at the API level. Particularly valuable when the orchestrator needs to parse and aggregate worker outputs programmatically.

```python
# Agent.run with structured output (optional)
resp = self.client.responses.create(
    model=self.model,
    instructions=self.instructions,
    input=self._conversation,
    tools=tools_schema,
    text={
        "format": {
            "type": "json_schema",
            "name": "worker_result",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["summary", "findings"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    },
)
```

### 6.6 Shared workspace coordination

Parallel coder agents editing the same files will produce last-write-wins conflicts. The strategies, in order of preference:

1. **Assign disjoint scopes.** Each worker owns a specific set of files or directories. The orchestrator's prompt makes this explicit: "Worker A handles `core/`, worker B handles `api/`, worker C handles `infra/`."

2. **Git worktrees.** Each worker operates in a separate worktree (`git worktree add ../worker-a-tree -b worker-a`), makes its changes, and the orchestrator merges the branches. This is how production coding agents (including Claude Code's internal harness) handle parallel coder sub-agents. The merge step can itself be a sub-agent ("merger" role).

   ```bash
   # Per-worker setup (called from Python via run_command)
   git worktree add /tmp/worker-a worker-a-branch
   git worktree add /tmp/worker-b worker-b-branch
   ```

3. **Write-then-merge protocol.** Workers write to temporary files (`patch_a.diff`, `patch_b.diff`), the orchestrator collects and applies them sequentially. Simpler than worktrees but requires a merge-capable orchestrator.

4. **Sequential execution.** If disjoint scoping is impractical and worktrees are overkill, just run the coder agents one after another. You lose the parallelism benefit but gain correctness.

---

## 7. Full Code — `subagents.py`

```python
# subagents.py
"""
Sub-agent orchestration layer.

Provides:
  - AgentPreset / AGENT_PRESETS  — role definitions
  - dispatch_subagent            — run a single sub-agent, return its text
  - run_subagents_parallel       — run a batch concurrently
  - make_task_tool               — produce the 'task' Tool for an orchestrator
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

# Assumes agent.py and tools/ are on the Python path
from agent import Agent, UsageSummary
from tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SUBAGENT_DEPTH: int = Agent.MAX_DEPTH   # 4
MAX_CONCURRENT_SUBAGENTS: int = 8


# ---------------------------------------------------------------------------
# Agent presets
# ---------------------------------------------------------------------------

@dataclass
class AgentPreset:
    """Blueprint for a sub-agent role."""
    instructions: str
    allowed_tools: list[str]
    model: str = "gpt-4o"


AGENT_PRESETS: dict[str, AgentPreset] = {
    "researcher": AgentPreset(
        instructions=(
            "You are a research specialist. Gather information accurately and "
            "return a concise, well-structured summary. Cite sources where "
            "possible. Return ONLY the summary — no preamble or sign-off."
        ),
        allowed_tools=["web_search", "read_file", "list_directory"],
    ),
    "coder": AgentPreset(
        instructions=(
            "You are a software engineer. Implement exactly what is requested. "
            "Return ONLY the result: code, diff, or terse status. "
            "Do not add unsolicited commentary."
        ),
        allowed_tools=["read_file", "write_file", "run_command", "list_directory"],
    ),
    "reviewer": AgentPreset(
        instructions=(
            "You are a code reviewer with read-only access. Return a structured "
            "list of findings tagged CRITICAL, WARNING, or INFO, each with "
            "file and line number where relevant."
        ),
        allowed_tools=["read_file", "list_directory"],
    ),
    "analyst": AgentPreset(
        instructions=(
            "You are a data analyst. Examine the provided data or files and "
            "return a concise summary of key metrics, trends, and anomalies."
        ),
        allowed_tools=["read_file", "run_command"],
    ),
    "generic": AgentPreset(
        instructions=(
            "You are a helpful assistant. Complete the task and return a "
            "concise, accurate result."
        ),
        allowed_tools=[],
    ),
}


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------

@dataclass
class SubAgentResult:
    """Result from a sub-agent, including its token usage."""
    output: str
    usage: UsageSummary = field(default_factory=UsageSummary)
    call_id: str = ""


def dispatch_subagent(
    *,
    role: str,
    task: str,
    parent_registry: ToolRegistry,
    client: OpenAI,
    depth: int,
    extra_instructions: str = "",
) -> str:
    """
    Instantiate and run a sub-agent.  Returns final text or an error string.

    This function is designed to be called from a ThreadPoolExecutor worker:
    it is thread-safe because every Agent owns its own transcript and the
    OpenAI client uses per-thread HTTP connections.
    """
    if depth >= MAX_SUBAGENT_DEPTH:
        return (
            f"[error] Sub-agent depth limit ({MAX_SUBAGENT_DEPTH}) reached. "
            "Task not executed to prevent runaway recursion."
        )

    preset = AGENT_PRESETS.get(role, AGENT_PRESETS["generic"])

    # Build a filtered registry
    sub_registry = ToolRegistry()
    for tool_name in preset.allowed_tools:
        t = parent_registry.get(tool_name)
        if t is not None:
            sub_registry.register(t)

    # Optionally, sub-agents at depth < MAX_SUBAGENT_DEPTH - 1 can also
    # spawn sub-agents themselves.  To enable this, create a task tool here
    # and register it in sub_registry.  For most use cases, leave workers
    # as leaf agents (no task tool) to keep the tree shallow.

    instructions = preset.instructions
    if extra_instructions:
        instructions = f"{instructions}\n\n{extra_instructions}"

    agent = Agent(
        name=f"{role}@depth{depth}",
        instructions=instructions,
        registry=sub_registry,
        model=preset.model,
        client=client,
        depth=depth,
    )

    try:
        return agent.run(task)
    except Exception as exc:  # noqa: BLE001
        return f"[error] Sub-agent '{role}' failed: {exc}"


# ---------------------------------------------------------------------------
# Parallel runner
# ---------------------------------------------------------------------------

def run_subagents_parallel(
    tasks: list[dict],
    parent_registry: ToolRegistry,
    client: OpenAI,
    parent_depth: int,
) -> list[dict]:
    """
    Run a batch of sub-agent tasks concurrently.

    ``tasks`` is a list of dicts with keys:
      role, description, prompt, call_id

    Returns a list of ``function_call_output`` dicts, one per task,
    in the SAME ORDER as the input list.  A failed worker contributes
    an error string rather than raising.
    """
    results: dict[str, str] = {}
    n = len(tasks)
    workers = min(n, MAX_CONCURRENT_SUBAGENTS)

    print(
        f"\n  [orchestrator] running {n} sub-agent(s) in parallel "
        f"(max_workers={workers}) …"
    )
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_task = {
            pool.submit(
                _timed_dispatch,
                role=t["role"],
                description=t["description"],
                task=t["prompt"],
                parent_registry=parent_registry,
                client=client,
                depth=parent_depth + 1,
            ): t
            for t in tasks
        }

        for future in as_completed(future_to_task):
            meta = future_to_task[future]
            try:
                elapsed, result = future.result()
                print(f"    [done] {meta['role']!r} finished in {elapsed:.1f}s")
                results[meta["call_id"]] = result
            except Exception as exc:  # noqa: BLE001
                print(f"    [error] {meta['role']!r} crashed: {exc}")
                results[meta["call_id"]] = (
                    f"[error] Worker crashed unexpectedly: {exc}"
                )

    elapsed_total = time.perf_counter() - t0
    print(f"  [orchestrator] all sub-agents done in {elapsed_total:.1f}s\n")

    return [
        {
            "type": "function_call_output",
            "call_id": t["call_id"],
            "output": results[t["call_id"]],
        }
        for t in tasks
    ]


def _timed_dispatch(
    *,
    role: str,
    description: str,
    task: str,
    parent_registry: ToolRegistry,
    client: OpenAI,
    depth: int,
) -> tuple[float, str]:
    """Wrapper that times dispatch_subagent and prints a start log."""
    print(f"    [task] spawning {role!r}: {description}")
    t0 = time.perf_counter()
    result = dispatch_subagent(
        role=role,
        task=task,
        parent_registry=parent_registry,
        client=client,
        depth=depth,
    )
    return time.perf_counter() - t0, result


# ---------------------------------------------------------------------------
# The 'task' tool
# ---------------------------------------------------------------------------

def make_task_tool(
    parent_registry: ToolRegistry,
    client: OpenAI,
    parent_depth: int,
) -> Any:
    """
    Return a Tool instance that an orchestrator can register.

    When the orchestrator model calls 'task', this runs ``dispatch_subagent``
    in the current thread.  Parallel execution happens because Phase 2's
    ``ToolRegistry.dispatch_parallel`` already fans out concurrent function
    calls via ThreadPoolExecutor — 'task' is just another tool from that
    perspective.
    """

    class TaskTool:
        name = "task"
        description = (
            "Spawn a specialist sub-agent to complete an independent task. "
            "IMPORTANT: emit ALL task calls in a SINGLE response so they run "
            "in parallel. Do NOT call 'task' one at a time — that is serial, "
            "not parallel. Each worker runs in its own isolated context and "
            "returns a concise result.\n"
            f"Available roles: {', '.join(AGENT_PRESETS.keys())}."
        )
        parameters = {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": list(AGENT_PRESETS.keys()),
                    "description": (
                        "Specialist persona: determines system prompt and "
                        "available tools."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "One-sentence summary of what this worker should do. "
                        "Used in progress logs."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Full task prompt for the sub-agent. Include all context "
                        "it needs — the worker cannot read the parent's conversation."
                    ),
                },
            },
            "required": ["role", "description", "prompt"],
            "additionalProperties": False,
        }

        def run(self, *, role: str, description: str, prompt: str) -> str:
            return dispatch_subagent(
                role=role,
                task=prompt,
                parent_registry=parent_registry,
                client=client,
                depth=parent_depth + 1,
            )

    return TaskTool()


# ---------------------------------------------------------------------------
# Orchestrator factory — convenience wrapper
# ---------------------------------------------------------------------------

def make_orchestrator(
    full_registry: ToolRegistry,
    client: OpenAI | None = None,
    extra_instructions: str = "",
) -> Agent:
    """
    Return a ready-to-use orchestrator Agent that has the 'task' tool.

    The orchestrator has NO direct access to any other tools; it must
    delegate all work through sub-agents.

    Parameters
    ----------
    full_registry:
        Registry containing every tool sub-agents may need.  The task tool
        filters it per-role before handing it to workers.
    client:
        Shared OpenAI client.  Created if not provided.
    extra_instructions:
        Additional text appended to the default orchestrator system prompt.
    """
    if client is None:
        client = OpenAI()

    orchestrator_registry = ToolRegistry()
    task_tool = make_task_tool(
        parent_registry=full_registry,
        client=client,
        parent_depth=0,
    )
    orchestrator_registry.register(task_tool)

    base_instructions = (
        "You are an orchestration agent. When given a complex task, decompose "
        "it into independent subtasks and spawn specialist sub-agents using the "
        "'task' tool.\n\n"
        "PARALLELISM RULE: emit ALL task calls in a SINGLE response turn so they "
        "run concurrently. Never call 'task' sequentially unless later tasks "
        "genuinely depend on earlier results.\n\n"
        "After receiving results, synthesise them into a coherent final answer. "
        "Distil and integrate — do not repeat workers' output verbatim."
    )
    if extra_instructions:
        base_instructions = f"{base_instructions}\n\n{extra_instructions}"

    return Agent(
        name="orchestrator",
        instructions=base_instructions,
        registry=orchestrator_registry,
        client=client,
        depth=0,
    )
```

---

## 8. Async Alternative

The guide uses `ThreadPoolExecutor` throughout because it works with the standard `OpenAI` client, requires no `asyncio` knowledge, and maps naturally to the I/O-bound nature of LLM calls. For completeness, here is the async equivalent.

```python
# async_orchestrator.py (sketch)
import asyncio
from openai import AsyncOpenAI

async def dispatch_subagent_async(
    *, role: str, task: str, client: AsyncOpenAI, depth: int, ...
) -> str:
    agent = AsyncAgent(...)   # async variant of Agent
    return await agent.run(task)


async def run_subagents_parallel_async(tasks: list[dict], ...) -> list[dict]:
    coros = [
        dispatch_subagent_async(
            role=t["role"], task=t["prompt"], client=client, depth=depth + 1, ...
        )
        for t in tasks
    ]
    # asyncio.gather runs all coroutines concurrently in a single event loop
    results = await asyncio.gather(*coros, return_exceptions=True)
    return [
        {
            "type": "function_call_output",
            "call_id": t["call_id"],
            "output": str(r) if isinstance(r, Exception) else r,
        }
        for t, r in zip(tasks, results)
    ]
```

`asyncio.gather` is the async analogue of `ThreadPoolExecutor` + `as_completed`. The semantics are identical: all coroutines are scheduled concurrently, `return_exceptions=True` prevents one failure from cancelling siblings, and results map back to call IDs in order.

For HTTP-heavy workloads (many parallel sub-agents all making long-running API calls), the async approach is more efficient because it does not consume OS threads. For CPU-light, I/O-bound workloads like this one, the threaded approach is simpler and adequate.

---

## 9. Pitfalls

> **Fork-bomb recursion.** The single most dangerous failure mode. If a sub-agent's role includes the `task` tool and its prompt encourages decomposition, each generation spawns multiple children. At depth 4 with a fan-out of 3, you have 3⁴ = 81 concurrent agents, each making multiple API calls. **Always cap depth and max-concurrent workers in harness code, not just in the prompt.**

> **Parallel writes clobbering files.** Two `coder` agents both writing to `core/auth.py` will race. Last write wins; the loser's changes disappear silently. Assign disjoint file scopes in the orchestrator prompt, or use git worktrees for each parallel coder.

> **Swallowing sub-agent errors.** The `dispatch_subagent` function returns error strings rather than raising. This is correct — it lets siblings continue — but the orchestrator must notice the error string in the result and react appropriately. Include explicit error-handling instruction in the orchestrator's system prompt: "If a worker returns `[error]`, note it in the final report and do not fabricate the missing data."

> **Unbounded cost.** Each agent call is independently billed. A three-level tree with average fan-out 3 and 1,000 input tokens per node costs 3 + 9 + 27 = 39 API calls and potentially hundreds of thousands of tokens. Set a hard budget in the harness and abort once it is exceeded, or use a cheaper model for worker agents (`gpt-4o-mini` for simple tasks).

> **Parent context bloat from large worker output.** If workers return 5,000-token essays, the orchestrator's context fills up despite the isolation. Instruct workers in their system prompt to return summaries, not raw data. Enforce this with the structured output schema (§6.5): a `summary` field capped at N words prevents accidental verbosity.

> **Transcript reuse between tasks.** If you call `agent.run(task)` twice on the same `Agent` instance, the second call sees the first task's conversation. Call `agent.reset()` between tasks, or instantiate a fresh `Agent` for each independent use — which is what `dispatch_subagent` does.

---

## 10. What's Next

Phase 7 completes the orchestration story. One phase remains:

- **Phase 8 — The production harness:** the final assembly. Reliability (retries with
  backoff, iteration caps, graceful Ctrl-C), observability (structured logging),
  configuration, system-prompt engineering, packaging, and a real CLI — all wrapped
  around the loop you've built since Phase 1. (Persistent cross-session memory was
  already introduced back in Phase 6.)

The architecture you have now — a loop, a typed tool system, permissions, streaming,
structured output, and multi-agent orchestration — is production-grade. Phase 8 hardens,
packages, and ships it.

---

## Key takeaways

- **One agent isn't enough** for large jobs; the fix is to let the agent **delegate** to
  focused sub-agents.
- **The key trick:** a sub-agent is just **your `run_agent` loop called again** from
  inside a `task` *tool* — so spawning a sub-agent is itself something the main agent can
  *choose* to do, with its own short conversation and limited toolset.
- Independent sub-agents can run **in parallel** (threads) for fan-out; `asyncio` is an
  alternative shown at the end.
- Give each sub-agent a **narrow brief and limited tools**, then combine their results —
  this keeps each context small and the blast radius contained.

## Check yourself

1. In one sentence, what *is* a sub-agent in this design?
2. How does the *main* agent decide to delegate work to a sub-agent?
3. When does running sub-agents in parallel actually help?
4. Why hand each sub-agent a focused brief and a restricted set of tools?

<details><summary>Answers</summary>

1. The **same agent loop invoked again** from within a tool, with its own conversation
   and tools.
2. Sub-agent spawning is exposed **as a tool** (`task`), so the model calls it like any
   other tool when it judges delegation is useful.
3. When the subtasks are **independent** (e.g. searching several areas at once) — fan-out
   overlaps their latency instead of serialising it.
4. Focus improves quality, a small toolset limits what can go wrong, and a short brief
   keeps each sub-agent's **context small** (cheaper, clearer reasoning).
</details>
