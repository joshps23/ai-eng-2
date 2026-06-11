# Learning Path — Your Route Through This Guide

> New here and not sure what to read, in what order, or how long it takes? Start
> on this page. It turns the 8 phases into a **step-by-step plan** with time
> estimates, what to *do* at each step (not just read), and checkpoints so you know
> you're on track. Pick the track that matches your time budget.

If you ever hit an unfamiliar word, keep the **[Glossary](./GLOSSARY.md)** open in a
tab. If you're newer to Python, read **[`BEGINNER-NOTES.md`](./BEGINNER-NOTES.md)**
once before Phase 1. To *practice* (not just read), each phase has a warm-up and a
stretch task in **[`EXERCISES.md`](./EXERCISES.md)** — do them right after the phase's
"Check yourself".

---

## Before you start (15 min, once)

1. **Check Python.** You need 3.10+. Run `python --version`.
2. **Make a virtual environment and install the code:**
   ```bash
   cd agent-harness-guide/code   # from the repo root (just `cd code` if you're already in agent-harness-guide/)
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   python -m pytest -q          # expect: all tests pass, no API key needed
   ```
   If anything here fails, check the **[Beginner FAQ & troubleshooting](./FAQ.md)**
   (or **Setup & troubleshooting** in the [top-level README](../README.md)). Getting
   the tests green now means every later "run it" step will just work.
3. **(Optional, for actually chatting with the agent)** Set `OPENAI_API_KEY`. You do
   **not** need this to learn — the whole guide and its tests run offline. (To be
   precise: the phases' "▶ Run it now" scripts call the real API, so without a key
   they stop at `openai.OpenAIError: Missing credentials`. That's fine — the
   "No API key?" box in Phase 0 shows how to verify each checkpoint keylessly:
   check the printed expected output, and lean on the offline test suite above.)

---

## Pick your track

| Track | Time | For you if… | Do this |
|-------|------|-------------|---------|
| 🥾 **Taster** | ~2 hours | You want the core idea and a working agent, fast. | Phases **0 → 1 → 2**, then skim the README's big diagram. |
| 🧗 **Weekend** | ~6–8 hours | You want to genuinely understand a real harness. | Phases **0 → 6** in order, running each one. |
| 🏔️ **Deep** | ~15+ hours | You want to be able to *rebuild* Claude Code's shape. | **All 8 phases + the appendix**, doing the exercises and reading `code/`. |

You can stop at the end of any phase and have something that runs. Nothing later is
required to make earlier phases work.

---

## The full path, phase by phase

Each phase below lists **what you'll build**, **what to do**, and a **checkpoint** —
a concrete sign you've understood it before moving on.

### Phase 0 — Foundations · [`00-foundations.md`](./00-foundations.md)
- **Build:** nothing yet — the mental model and the API contract every phase reuses.
- **Do:** read it carefully; run the sanity-check script at the end to confirm your
  environment and (optionally) API access.
- **Checkpoint:** you can explain, in one sentence, the loop *send → tool call? →
  run & append → repeat → answer*, and you know what `response.output` contains.

### Phase 1 — A bare harness in ~80 lines · [`01-bare-harness.md`](./01-bare-harness.md)
- **Build:** a complete working agent in one file, with one trivial tool.
- **Do:** type it out (don't just copy), run it, and watch a tool call happen.
- **Checkpoint:** you can point at the exact lines where (a) the model *asks* for a
  tool and (b) your code *runs* it and feeds the result back.

### Phase 2 — The tool system · [`02-tool-system.md`](./02-tool-system.md)
- **Build:** an extensible way to register tools and auto-describe them to the model.
- **Do:** add one tool of your own (e.g. a calculator) and call it from the agent.
- **Checkpoint:** you can add a new tool without touching the loop itself.

### Phase 3 — Conversation & streaming · [`03-conversation-and-streaming.md`](./03-conversation-and-streaming.md)
- **Build:** ownership of the transcript as state; optional live (streaming) output.
- **Do:** save a conversation to disk and reload it; treat streaming as optional.
- **Checkpoint:** you can describe what's stored in the transcript and why the model
  "remembers" across turns.

### Phase 4 — The real toolset · [`04-real-tools.md`](./04-real-tools.md)
- **Build:** `read_file`, `edit_file`, `bash`, `grep`, `glob` — a coding agent's hands.
- **Do:** point the agent at a small scratch directory and have it read/edit a file.
- **Checkpoint:** the agent can make a real change on disk that you can `git diff`.

### Phase 5 — Permissions & safety · [`05-permissions-and-safety.md`](./05-permissions-and-safety.md)
- **Build:** approval gates, sandboxing, and the hook system.
- **Do:** make a destructive tool require approval; watch a hook fire before a tool runs.
- **Checkpoint:** you can name the layer that stops the agent from running `rm -rf`
  without asking.

### Phase 6 — Context management · [`06-context-management.md`](./06-context-management.md)
- **Build:** token budgeting, pruning, and compaction for long sessions.
- **Do:** force a tiny token budget and watch old turns get summarised/dropped.
- **Checkpoint:** you can explain why a long chat eventually *must* shed history, and
  the three tactics for doing it.

### Phase 7 — Sub-agents & orchestration · [`07-subagents-orchestration.md`](./07-subagents-orchestration.md)
- **Build:** spawning focused sub-agents, optionally in parallel.
- **Do:** add a `task` tool that runs a sub-agent for a search-style subtask.
- **Checkpoint:** you can describe how a sub-agent is "just the loop, called again."

### Phase 8 — The production harness · [`08-production-harness.md`](./08-production-harness.md)
- **Build:** the full assembled CLI — retries, observability, persistence.
- **Do:** run `agent-harness` (or `python -m agent_harness.cli`) end-to-end.
- **Checkpoint:** you can map each earlier phase to a part of the finished harness.

### Appendix — Library reference · [`09-library-reference.md`](./09-library-reference.md)
- **Use as needed:** look up any `openai` / `tiktoken` / stdlib method the guide uses.

---

## When you're done

You'll have built — and understood from the inside — a Claude-Code-shaped harness:
a loop, a sandboxed toolset, an approval system, automatic context compaction, and
parallel sub-agents. The canonical, tested version of all of it lives in
[`code/agent_harness/`](./code/). Read it, run it, break it, rebuild it.

> Found a step that was confusing or a gap in the path? That's signal — it's exactly
> what the [`ROADMAP.md`](./ROADMAP.md) standing goal exists to fix.
