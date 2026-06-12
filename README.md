# Building a Full-Fledged Agent Harness with the OpenAI Responses API — in Pure Python

[![CI](https://github.com/joshps23/ai-eng-2/actions/workflows/ci.yml/badge.svg)](https://github.com/joshps23/ai-eng-2/actions/workflows/ci.yml)

An exhaustive, phase-by-phase guide to building an agentic coding harness (the kind of
program that powers tools like Claude Code and Cursor) from scratch, using **only** the
OpenAI Responses API and the Python standard library. No LangChain, no agent SDKs — the
point is to understand what those frameworks hide and be able to rebuild them yourself.

**👉 New here? Follow the [Learning Path](./agent-harness-guide/LEARNING-PATH.md)** —
pick the track that fits your time (2 hours / a weekend / deep) and it walks you
through Phases 0–8 step by step, with per-phase checkpoints.

> 🟢 **Who this is for.** Written for working engineers **and** for beginners who know
> **functions, lists, dictionaries, operators, and `client.responses.create(...)`** —
> the 🟢 beginner track is built in. If that beginner description is you, read the
> **[Python Concepts Cheat-Sheet](./agent-harness-guide/BEGINNER-NOTES.md)** once
> before Phase 0 — it translates every other concept (classes, `json.loads`,
> JSON Schema, `with`, threads) into those terms, and inline 🟢 boxes in each phase
> bridge the gaps as they appear.

## Reference shelf

The Learning Path will send you to these when you need them:

- 📖 **[The guide](./agent-harness-guide/README.md)** — Phases 0–8, incremental, from an
  ~80-line agent to a production-shaped harness (loop, tools, streaming, permissions,
  context management, sub-agents).
- 🛠️ **[Exercises](./agent-harness-guide/EXERCISES.md)** — a warm-up + a stretch task per
  phase (with hints) so you *build*, not just read.
- 📒 **[Glossary](./agent-harness-guide/GLOSSARY.md)** — every harness and Python
  term the guide uses, defined in plain language. Hit an unfamiliar word? Start here.
- 🛟 **[Beginner FAQ & troubleshooting](./agent-harness-guide/FAQ.md)** — the canonical
  setup and troubleshooting page: fixes for the common first-run errors (install, API
  keys, models, "the agent did nothing", reading tracebacks, Windows notes).
- 📚 **[Library reference appendix](./agent-harness-guide/09-library-reference.md)** —
  every external library used (`openai`, `tiktoken`) plus key stdlib, documented with
  methods, parameters, return types, and examples.
- 💻 **[Runnable code](./agent-harness-guide/code/)** — the consolidated, tested
  `agent_harness` package. The source of truth for the implementation.
- 📓 **[Notebooks](./agent-harness-guide/notebooks/README.md)** — companion Jupyter
  notebooks for every phase 0–8 (plus a setup check): run each phase's checkpoints
  top-to-bottom, fully offline, no API key needed.

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

**Something won't run?** The **[FAQ](./agent-harness-guide/FAQ.md)** is the canonical
setup & troubleshooting page — symptom-first fixes for installs, API keys, models, and
tracebacks. (Two habits prevent most problems: work inside a virtual environment, and
run tests as `python -m pytest`, never bare `pytest`.)
