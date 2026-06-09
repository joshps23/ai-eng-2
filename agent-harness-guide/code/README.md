# Agent Harness — Reference Implementation

A complete, runnable Python reference implementation of an LLM agent harness
targeting the **OpenAI Responses API**. Pure standard library + `openai` only.
No LangChain, no other frameworks. Requires Python 3.10+.

---

> ## 🟢 New to Python? Read this before opening the code
>
> This package is the **production reference**: it uses classes, decorators,
> dataclasses, and threads to stay organized and fast. That's more machinery than a
> beginner needs to *understand* the ideas. If you only know **functions, lists,
> dictionaries, operators, and `client.responses.create(...)`**, do this:
>
> 1. **Learn the ideas from the phase guides first**, not from this package. Start at
>    [`../BEGINNER-NOTES.md`](../BEGINNER-NOTES.md). Each phase has a green "🟢 Beginner
>    track" box that rebuilds that phase's piece using only functions and dicts.
> 2. **Treat this package as the "grown-up" version** of those same pieces. Nothing
>    here does anything the beginner boxes don't — it just adds structure. Use this map
>    to jump from a file to its plain-functions explanation:
>
> | Package file | What it is | Plain-functions version |
> |--------------|-----------|--------------------------|
> | `agent.py` | the agent loop, as a class | [Phase 1](../01-bare-harness.md) loop + [Phase 7 box](../07-subagents-orchestration.md) `run_agent` |
> | `tools/base.py`, `tools/registry.py` | `Tool` class, `@tool`, `ToolRegistry` | [Phase 2 beginner box](../02-tool-system.md) (tool = function + schema dict; registry = a dict) |
> | `tools/parallel.py` | run tools on threads | [Phase 2 box](../02-tool-system.md) `run_tool_calls` (a plain `for` loop) |
> | `tools/files.py`, `tools/shell.py` | the real tools | [Phase 4](../04-real-tools.md) — already plain functions |
> | `conversation.py` | `Conversation` class | [Phase 3 box](../03-conversation-and-streaming.md) (conversation = a dict + functions) |
> | `context.py` | token budget + compaction | [Phase 6 box](../06-context-management.md) (clip / drop-oldest / summarize) |
> | `permissions.py`, `hooks.py` | permission gate + hooks | [Phase 5 box](../05-permissions-and-safety.md) (dicts + `if`/`else`) |
> | `subagents.py` | sub-agent orchestration | [Phase 7 box](../07-subagents-orchestration.md) (a `task` tool that calls the loop again) |
> | `llm.py`, `config.py`, `cli.py` | retry, settings, REPL | [Phase 8 box](../08-production-harness.md) (polish: retry = `for` + `try/except` + `sleep`) |
>
> 3. **When you read a class**, remember the one rule from the beginner notes: a method
>    `obj.do(x)` is just a function call, and `self` is "this object's data." Read
>    `registry.dispatch(name, args)` as `dispatch(registry, name, args)`.
>
> You do **not** need to reproduce this package to have a working agent — the
> functions-and-dicts versions in the phase boxes run on their own. This package is here
> for when you're ready to see how the production shape fits together.

---

## Installation

```bash
# Editable install (recommended for development)
pip install -e .

# Or just install the dependency directly
pip install openai

# Optional: faster token counting
pip install ".[tiktoken]"

# Development (adds pytest)
pip install ".[dev]"
```

---

## Running

### One-shot mode

```bash
agent-harness -p "List the files in the current directory"
```

### Interactive REPL

```bash
agent-harness
```

### With options

```bash
agent-harness \
  --model gpt-4o \
  --mode accept_edits \
  --workspace ./my-project \
  -p "Refactor the main function in main.py"
```

### Slash commands (interactive mode)

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/clear` | Clear conversation |
| `/compact` | Summarize old conversation to save context |
| `/cost` | Show accumulated token usage |
| `/tools` | List available tools |
| `/mode <mode>` | Change permission mode |
| `/save <file>` | Save conversation to JSONL |
| `/resume <file>` | Load saved conversation |

### Permission modes

| Mode | Behavior |
|------|----------|
| `plan` | Read-only; denies all writes and shell |
| `auto` | Auto-allow reads; ask for writes/shell |
| `accept_edits` | Auto-allow file edits; ask for shell |
| `always_allow` | Allow everything (except hard-deny patterns) |
| `bypass` | Bypass all permission checks |

---

## Testing

```bash
# Install dev dependencies
pip install pytest

# Run all tests (no API key required — uses FakeClient)
cd code/
python -m pytest -q

# Run a specific test file
python -m pytest tests/test_agent_loop.py -v
```

All tests run **offline** using `FakeClient` — no OpenAI API key is needed.

---

## Package Layout

```
code/
├── README.md               # This file
├── pyproject.toml          # Package metadata; console_script agent-harness
└── agent_harness/
    ├── __init__.py         # Exports: Agent, ToolRegistry, tool, Settings
    ├── config.py           # Settings dataclass (model, max_iterations, ...)
    ├── llm.py              # LLMClient with retry/backoff; injectable client
    ├── conversation.py     # Conversation transcript management + to_input_dict
    ├── context.py          # count_tokens, prune_to_budget, compact
    ├── agent.py            # Agent: main agentic loop
    ├── permissions.py      # PermissionMode, PermissionPolicy, check_permission
    ├── hooks.py            # HookRegistry, pre/post hooks, built-in examples
    ├── subagents.py        # AGENT_PRESETS, dispatch_subagent, make_task_tool
    ├── cli.py              # CLI entry point (argparse + interactive REPL)
    ├── testing.py          # FakeClient, FakeResponse, fake_message, fake_function_call
    └── tools/
        ├── __init__.py     # Exports: Tool, tool, ToolRegistry
        ├── base.py         # Tool dataclass + @tool decorator (auto JSON schema)
        ├── registry.py     # ToolRegistry: register, dispatch, to_openai_schema
        ├── parallel.py     # run_tool_calls (ThreadPoolExecutor)
        ├── files.py        # read_file, write_file, edit_file, glob_files, grep, list_dir
        └── shell.py        # bash (subprocess, workspace-confined)
└── tests/
    ├── conftest.py         # Fixtures: tmp_settings, fake_client_factory, auto_approver
    ├── test_tools.py       # Tool schema, registry dispatch, file/bash/parallel tests
    ├── test_agent_loop.py  # Agent loop: tool calls, transcript, max_iter, permissions
    └── test_context.py     # Token counting, pruning, compaction
```

---

## Key Design Decisions

### OpenAI Responses API contract

- Uses `client.responses.create(model, instructions, input, tools)`.
- Tool definitions are **flat**: `{"type":"function","name":...,"description":...,"parameters":...}`.
- Multi-turn handshake: append model output items → append `function_call_output` items → call again.
- `to_input_dict()` normalizes both SDK objects (`.model_dump()`) and plain dicts.

### Offline testability

Inject any client into `LLMClient(client=...)`. `FakeClient` scripts exact responses:

```python
from agent_harness.testing import FakeClient, fake_message, fake_function_call
from agent_harness.llm import LLMClient
from agent_harness.agent import Agent

client = FakeClient([
    [fake_function_call("read_file", {"path": "foo.txt"}, call_id="c1")],
    [fake_message("The file contains: hello world")],
])
llm = LLMClient(client=client)
agent = Agent(llm=llm, ...)
result = agent.run("Read foo.txt")
```

### Tools never raise into the loop

`ToolRegistry.dispatch()` catches all exceptions and returns `"Error: ..."` strings.
Permission denials are also converted to tool-result error strings.

### Context management

`prune_to_budget()` respects `function_call`/`function_call_output` pairing and
preserves the first user message. `compact()` summarizes the older half via the
model itself.
