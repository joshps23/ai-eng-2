# ai-eng-2

[![CI](https://github.com/joshps23/ai-eng-2/actions/workflows/ci.yml/badge.svg)](https://github.com/joshps23/ai-eng-2/actions/workflows/ci.yml)

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

- 🧭 **[Learning path](./agent-harness-guide/LEARNING-PATH.md)** — not sure what to
  read or how long it takes? This turns the 8 phases into a step-by-step plan with
  time-budgeted tracks (2 hours / a weekend / deep) and per-phase checkpoints.
- 📖 **[The guide](./agent-harness-guide/README.md)** — 8 incremental phases, from an
  ~80-line agent to a production-shaped harness (loop, tools, streaming, permissions,
  context management, sub-agents).
- 📒 **[Glossary](./agent-harness-guide/GLOSSARY.md)** — every harness and Python
  term the guide uses, defined in plain language. Hit an unfamiliar word? Start here.
- 🛟 **[Beginner FAQ & troubleshooting](./agent-harness-guide/FAQ.md)** — fixes for
  the common first-run errors (install, API keys, models, "the agent did nothing",
  reading tracebacks, Windows notes).
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

### Setup & troubleshooting (read this if something won't run)

- **Use a virtual environment.** `python -m venv .venv && source .venv/bin/activate`
  (Windows: `.venv\Scripts\activate`) *before* `pip install`. This avoids the most
  common gotcha: a globally-installed `pytest` belonging to a different interpreter
  that can't find the package (`ModuleNotFoundError: No module named 'agent_harness'`).
- **Run tests as `python -m pytest`,** not bare `pytest`. The `python -m` form uses
  the *same* interpreter you installed into, so imports resolve. Run it from
  `agent-harness-guide/code`.
- **No API key needed to learn.** The full test suite runs offline — a `FakeClient`
  stands in for the API. You only need `OPENAI_API_KEY` to actually *chat* with the
  agent (`agent-harness`).
- **`agent-harness: command not found`?** The console script is installed by
  `pip install -e ".[dev]"`; make sure your venv is active, or run it as
  `python -m agent_harness.cli`.
- **Unfamiliar term anywhere?** See the
  **[Glossary](./agent-harness-guide/GLOSSARY.md)**.
