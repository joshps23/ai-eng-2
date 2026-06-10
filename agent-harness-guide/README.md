# Building a Full-Fledged Agent Harness with the OpenAI Responses API — in Pure Python

> An exhaustive, phase-by-phase guide to building an agentic coding harness — the kind
> of program that powers tools like **Claude Code** and **Cursor** — from scratch,
> using only the OpenAI **Responses API** and the Python standard library.
>
> **No frameworks.** No LangChain, no LlamaIndex, no agent SDK. The entire point is to
> teach the concepts *from under the hood* so you understand what those frameworks
> hide — and could rebuild them yourself.

---

## Who this is for

A competent Python engineer who wants to *really* understand how modern AI agents
work: the loop, tools, streaming, permissions, context management, and multi-agent
orchestration. By the end you'll have built a production-shaped harness with a CLI,
a sandboxed toolset, an approval system, automatic context compaction, and parallel
sub-agents.

> 🟢 **Newer to Python?** You don't need to be an expert to follow along. If you're
> comfortable with **functions, lists, dictionaries, operators, and
> `client.responses.create(...)`**, read **[`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md)**
> first. It explains every other concept the guide uses — classes, `json.loads`,
> JSON Schema, `with`, threads — in those terms, and green 🟢 boxes throughout the
> phases bridge each gap exactly where it appears. Keep the
> **[`GLOSSARY.md`](./GLOSSARY.md)** open in a tab: it defines every harness and
> Python term used here, so you never have to leave to look something up.

## How the guide is structured

The guide is **incremental**. Each phase is runnable on its own and builds directly
on the previous one. Phase 1 is a working agent in ~80 lines; by Phase 8 you have a
Claude-Code-shaped harness.

| Phase | File | What you build | Key concept |
|------:|------|----------------|-------------|
| **0** | [`00-foundations.md`](./00-foundations.md) | Setup + the contract every phase reuses | The agent loop; the Responses API |
| **1** | [`01-bare-harness.md`](./01-bare-harness.md) | A working agent in ~80 lines | The minimal viable loop with one tool |
| **2** | [`02-tool-system.md`](./02-tool-system.md) | An extensible tool system | Registry, auto-schema from type hints, parallel tool calls |
| **3** | [`03-conversation-and-streaming.md`](./03-conversation-and-streaming.md) | State + live output | Owning the transcript; streaming events |
| **4** | [`04-real-tools.md`](./04-real-tools.md) | The real toolset | `read_file`, `edit_file`, `bash`, `grep`, `glob`, … |
| **5** | [`05-permissions-and-safety.md`](./05-permissions-and-safety.md) | The safety layer | Approval gates, sandboxing, the hook system |
| **6** | [`06-context-management.md`](./06-context-management.md) | Long-session survival | Token budgeting, pruning, compaction |
| **7** | [`07-subagents-orchestration.md`](./07-subagents-orchestration.md) | Multi-agent orchestration | Spawning **parallel** sub-agents dynamically |
| **8** | [`08-production-harness.md`](./08-production-harness.md) | The full assembled harness | Retries, observability, persistence, the CLI |
| **A** | [`09-library-reference.md`](./09-library-reference.md) | Reference appendix | Every external library (`openai`, `tiktoken`) + key stdlib, with methods, parameters, return types, and examples |
| **G** | [`GLOSSARY.md`](./GLOSSARY.md) | Plain-language glossary | Every harness/Python term used in the guide, defined for beginners |

> **New and want a plan?** The **[Learning Path](./LEARNING-PATH.md)** turns these
> phases into a step-by-step route with time-budgeted tracks and per-phase
> checkpoints. Otherwise, **start with [Phase 0](./00-foundations.md).** It
> establishes the API contract and conventions (naming, data shapes, project layout)
> that every later phase depends on. If a later code sample looks unfamiliar, Phase 0
> is your reference.

## The canonical, runnable code

Each phase's markdown shows code **as it grows** — a Phase 3 snippet is deliberately
simpler than its Phase 8 descendant, and a few designs (the tool registry, the
conversation object) are intentionally refactored as the guide introduces new needs.
That's the teaching arc, not the finished product.

The **single, consistent, end-to-end implementation** lives in
[`code/agent_harness/`](./code/). It is the source of truth: one tool registry, one
`Conversation`, one permission system, wired together and **covered by a passing test
suite** that runs entirely offline (a `FakeClient` stands in for the API):

```bash
cd code
pip install -e ".[dev]"
python -m pytest -q   # all tests pass, no API key or network needed
```

If a per-phase snippet and the package ever seem to disagree, the package is correct —
read the phase for the *idea*, read `code/agent_harness/` for the *implementation*.

## The one idea behind everything

An LLM is a pure function: text in, text out. It can't touch the world or remember
anything. An **agent harness** is the loop wrapped around it that gives it hands and a
memory:

```
   send conversation ──▶ model wants tools? ──yes──▶ run tools, append results ──┐
        ▲                        │ no                                            │
        └────────────────────────┼───────────────────────────────────────────────┘
                                  ▼
                            return answer
```

Everything in this guide — streaming, permissions, sub-agents, compaction, retries —
is refinement on top of that loop.

## Prerequisites

```bash
pip install openai          # the only required dependency
pip install tiktoken        # optional: local token counting (Phase 6)
export OPENAI_API_KEY="sk-..."
```

Python 3.10+. Run the sanity-check script at the end of [Phase 0](./00-foundations.md)
to confirm your environment and API access before starting Phase 1.

## A note on models

Throughout, code pins a single `MODEL` constant. Use the latest capable
Responses-API model available to you; reasoning-capable models give the best agentic
behavior. Everything here also works on smaller, faster models.

## License & intent

This is educational material. The code is written for clarity over cleverness; in
several places we deliberately show the "manual" version of something a library would
hide, then point at the production-grade variant. Read it, run it, break it, rebuild
it.
