# Agent Harness — Reference Implementation

A complete, runnable Python reference implementation of an LLM agent harness
targeting the **OpenAI Responses API**. Pure standard library + `openai` only.
No LangChain, no other frameworks. Requires Python 3.10+.

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
