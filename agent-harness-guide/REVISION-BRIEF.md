# Revision Brief — Make Every Phase Radically More Incremental for a Python Beginner

> **Standing goal (current focus).** Revise the 8 phases so a **Python beginner** is
> never asked to absorb more than one new idea at a time. The beginner must first see a
> **basic harness working with basic functions and basic tools**, run it, and only then
> meet each layer of production machinery — one small, motivated step at a time.
>
> This file is the shared spec for (a) the parallel sub-agents doing the initial revision
> pass and (b) the evaluator-reviser loop that refines afterward. Read it fully before
> editing any phase.

## What "incremental for a beginner" means here

A beginner reading a phase should experience a **ladder**, not a cliff:

1. **Start at zero.** The phase's *first* runnable code is the simplest thing that works,
   using **only** functions, lists, dicts, operators, and `client.responses.create(...)`
   — no classes, decorators, threads, or advanced stdlib yet. For phases about the loop
   and tools (1, 2, 4 especially) this means: a basic harness with a plain-function tool
   the reader can run *before* any abstraction appears.
2. **One idea per step.** After the minimal version runs, introduce each new concept
   (registry, classes, streaming, permissions, compaction, sub-agents) as its **own
   labeled step**, each answering *“why do we need this now?”* before showing how.
3. **Run it at every rung.** Each step ends with a concrete **“▶ Run it now”** checkpoint
   — what to type, what you should see — so the reader is never more than a few lines from
   a working program.
4. **Advanced material stays, but later.** The production-shaped code, classes, and
   threads are kept — moved *after* the basic version and clearly marked as the “grown-up”
   form of something the reader already understands.

## The required shape of each phase (target outline)

- **Intro** (unchanged in spirit): what we build, why it matters.
- **Step 0 — the simplest version that works**: minimal, plain-functions code + a
  **▶ Run it now**. (Phase 0 is conceptual — there its “simplest version” is the smallest
  end-to-end handshake, introduced one item-type at a time.)
- **Steps 1..n — add one thing at a time**: each a small, motivated increment with its own
  ▶ Run it / check. Prefer several small code blocks with prose between them over one big
  dump.
- **The production shape**: the consolidated/class-based version, explicitly framed as
  “the same idea, organized for real use.”
- **Keep**: the existing 🟢 beginner boxes, “Key takeaways”, “Check yourself”, pitfalls,
  and the “Next” pointer. Link practice to `EXERCISES.md`.

## Hard constraints (do not violate)

- **Markdown only.** Do **not** edit anything under `code/`. The runnable package is the
  source of truth; phases may show simpler, evolving snippets that differ from it.
- **Additive / restructuring, not destructive.** Do not delete existing explanations,
  beginner boxes, recaps, exercises, or pitfalls. You may reorder and split big blocks,
  and add minimal bridging prose, but preserve the substance.
- **No git, no test runs by sub-agents.** Just edit your assigned phase file and report
  what you changed. The parent commits once after verifying.
- **Keep code snippets correct.** Any code you add must be valid Python consistent with
  the OpenAI Responses API contract from Phase 0 (`responses.create(model, input, tools)`;
  output is a list of typed items; tool handshake via `call_id` + `function_call_output`).
- **One concept per step; basic-before-advanced** is the whole point — when in doubt, split.

## Evaluation rubric (used by the loop)

Score each phase 1–5 on each axis; the loop revises the lowest-scoring phase next:

1. **Cold-start runnable** — does the phase reach a runnable, *basic* program using only
   the assumed five concepts before any abstraction?
2. **Step size** — is each new idea introduced alone, with a motivation and a run/check?
3. **Basic-before-advanced ordering** — are classes/decorators/threads deferred until
   after the plain version?
4. **Run-it cadence** — are there frequent “▶ Run it now” checkpoints?
5. **Continuity** — does it still flow, with beginner boxes/recaps/exercises intact?

## Loop control (max 10 iterations)

The evaluator-reviser loop runs **at most 10 times**, then stops on its own.

- Iterations used: **0 / 10**
- Per iteration: score all phases on the rubric, pick the weakest, revise it one notch
  more incremental, increment the counter here, log it below, commit, push. Stop when the
  counter hits 10 **or** every phase scores ≥4 on every axis.

## Revision log (newest first)

- _(initial parallel pass and loop iterations will be logged here)_
