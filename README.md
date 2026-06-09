# ai-eng-2

**Building a Full-Fledged Agent Harness with the OpenAI Responses API — in Pure Python.**

An exhaustive, phase-by-phase guide to building an agentic coding harness (the kind of
program that powers tools like Claude Code and Cursor) from scratch, using **only** the
OpenAI Responses API and the Python standard library. No LangChain, no agent SDKs — the
point is to understand what those frameworks hide and be able to rebuild them yourself.

> 🟢 **New to Python?** This guide was written for experienced engineers, but it now
> ships with a beginner track. If you know **functions, lists, dictionaries,
> operators, and `client.responses.create(...)`**, start with
> **[`BEGINNER-NOTES.md`](./agent-harness-guide/BEGINNER-NOTES.md)** — it translates
> every other concept (classes, `json.loads`, JSON Schema, `with`, threads) into
> those terms, and inline 🟢 boxes in each phase bridge the gaps as they appear.

## Start here

- 📖 **[The guide](./agent-harness-guide/README.md)** — 8 incremental phases, from an
  ~80-line agent to a production-shaped harness (loop, tools, streaming, permissions,
  context management, sub-agents).
- 📒 **[Glossary](./agent-harness-guide/GLOSSARY.md)** — every harness and Python
  term the guide uses, defined in plain language. Hit an unfamiliar word? Start here.
- 📚 **[Library reference appendix](./agent-harness-guide/09-library-reference.md)** —
  every external library used (`openai`, `tiktoken`) plus key stdlib, documented with
  methods, parameters, return types, and examples.
- 💻 **[Runnable code](./agent-harness-guide/code/)** — the consolidated, tested
  `agent_harness` package. The source of truth for the implementation.

## Quick start

```bash
cd agent-harness-guide/code
pip install -e ".[dev]"
python -m pytest -q             # all tests pass offline (no API key needed)

export OPENAI_API_KEY="sk-..."  # then, to actually run the agent:
agent-harness
```

Python 3.10+. The only required dependency is `openai>=1.66.0` (the version that added
the Responses API); `tiktoken` is an optional extra for exact local token counting.
