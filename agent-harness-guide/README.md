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

> **Start with [Phase 0](./00-foundations.md).** It establishes the API contract and
> conventions (naming, data shapes, project layout) that every later phase depends on.
> If a later code sample looks unfamiliar, Phase 0 is your reference.

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
