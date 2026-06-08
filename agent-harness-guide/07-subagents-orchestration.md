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

## 2. Refactoring the Loop into a Reusable `Agent` Class

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

            # Extend the transcript with the model's raw output. This includes
            # any `reasoning` item (reasoning models only), which must be carried
            # forward so the worker keeps its chain-of-thought across iterations.
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
- **Reasoning carries forward within a worker, never across the boundary.** As in Phase 3, `self._conversation.extend(resp.output)` appends *every* output item — including any `reasoning` item from a reasoning model — so the worker's chain-of-thought persists across its own tool-call iterations (the reason → act → observe → reason loop). Never drop reasoning items from `_conversation`, or you break that chain (and some models reject a `function_call` whose preceding `reasoning` item is missing). Crucially, that reasoning stays *inside* the sub-agent: the parent only ever receives the worker's final text as the `function_call_output`, so a worker's private thinking never leaks into the orchestrator's context. This context isolation is a feature, not a limitation — it is the main reason to delegate noisy, exploratory work to a sub-agent.

---

## 3. Sub-Agents as a Tool — The Key Trick

The elegance of this architecture is that from the orchestrator's perspective, spawning a sub-agent is just another tool call. The model emits a `function_call` item with `name="task"`, the harness intercepts it, instantiates and runs a worker `Agent`, and returns its final text as the `function_call_output`. The model never knows it talked to another model; it just sees a tool result.

This means the orchestrator needs no special awareness of sub-agents in its loop. The existing Phase 2 dispatch machinery handles everything — including parallelism.

### 3.1 Agent presets

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

### 3.2 The `dispatch_subagent` function

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

### 3.3 The `task` tool

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

---

## 4. Parallel Sub-Agents — The Centrepiece

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

### 5.3 Making the parallelism visible — timestamps

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

Phase 7 completes the orchestration story. The remaining phases build on this foundation:

- **Phase 8** — Persistent memory and cross-session state: giving agents the ability to remember things between runs via external storage, so knowledge accumulates rather than evaporating at the end of each conversation.
- **Phase 9** — Evaluation, testing, and reliability: how to write deterministic tests for non-deterministic agents, measure tool-call accuracy, and catch regressions before they reach production.
- **Phase 10** — Deployment: packaging the harness as a service, exposing it via HTTP, managing secrets, and operating it at scale.

The architecture you have now — a loop, a typed tool system, permissions, streaming, structured output, and multi-agent orchestration — is production-grade. The remaining phases harden, test, and deploy it.
