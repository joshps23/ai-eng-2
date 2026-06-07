# ai-eng-2

**Building a Full-Fledged Agent Harness with the OpenAI Responses API — in Pure Python.**

An exhaustive, phase-by-phase guide to building an agentic coding harness (the kind of
program that powers tools like Claude Code and Cursor) from scratch, using **only** the
OpenAI Responses API and the Python standard library. No LangChain, no agent SDKs — the
point is to understand what those frameworks hide and be able to rebuild them yourself.

## Start here

- 📖 **[The guide](./agent-harness-guide/README.md)** — 8 incremental phases, from an
  ~80-line agent to a production-shaped harness (loop, tools, streaming, permissions,
  context management, sub-agents).
- 📚 **[Library reference appendix](./agent-harness-guide/09-library-reference.md)** —
  every external library used (`openai`, `tiktoken`) plus key stdlib, documented with
  methods, parameters, return types, and examples.
- 💻 **[Runnable code](./agent-harness-guide/code/)** — the consolidated, tested
  `agent_harness` package. The source of truth for the implementation.

## Quick start

```bash
cd agent-harness-guide/code
pip install -e ".[dev]"
pytest -q                       # all tests pass offline (no API key needed)

export OPENAI_API_KEY="sk-..."  # then, to actually run the agent:
agent-harness
```

Python 3.10+. The only required dependency is `openai>=1.66.0` (the version that added
the Responses API); `tiktoken` is an optional extra for exact local token counting.
