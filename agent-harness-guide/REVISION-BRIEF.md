# Revision Brief — Make Every Phase Radically More Incremental for a Python Beginner

> **Standing goal (current focus, sharpened 2026-06-10).** Revise the phases so a
> **Python beginner** is never asked to absorb more than one new idea at a time —
> and, crucially, so each phase presents its harness as a **ladder of complete,
> runnable versions** at increasing abstraction levels:
>
> - **Version 1 — line-by-line.** A straight-line script: no `def`, no classes —
>   just statements executed top to bottom (a `while`/`for` loop is allowed; the
>   point is *no user-defined abstractions*).
> - **Version 2 — functions.** The same harness reorganized into plain functions.
>   No classes, no decorators.
> - **Version 3 — classes.** The same harness with state grouped into classes.
> - **Version 4+ — decorators / threads / etc.** Only the advanced machinery the
>   phase actually teaches (e.g. `@tool` in Phase 2, threading in Phase 7).
>
> Each version is a **complete program the reader can run**, not a fragment, and each
> is explicitly framed as *“the same harness, reorganized”* — with a short “what
> changed and why” diff-style explanation between versions.
>
> This file is the shared spec for (a) the parallel sub-agents doing the revision
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
- **Version 1 — line-by-line**: the phase's harness as a straight-line script with
  **no `def` and no classes** (inline the tool logic in the dispatch branch if needed),
  ending in a **▶ Run it now**. (Phase 0 is conceptual — there its “Version 1” is the
  smallest end-to-end handshake script, introduced one item-type at a time.)
- **Version 2 — functions**: the same harness reorganized into plain functions, each
  function introduced as its own motivated step with a ▶ Run it / check.
- **Version 3 — classes**: the same harness with state moved into classes, explicitly
  framed as “the same idea, organized,” with a short *what-changed-and-why* note
  comparing it to Version 2.
- **Version 4+ (only if the phase teaches it)**: decorators, threads, etc. — same
  framing: the same harness, one new mechanism.
- Between versions, a short **“What changed from Vn to Vn+1”** list (3–6 bullets) so the
  reader sees the reorganization, not a brand-new program.
- Within each version, still **one idea per step**: prefer several small code blocks with
  prose between them over one big dump, each with its own ▶ Run it / check where feasible.
- **The production shape**: the consolidated form that matches `code/`, last.
- **Keep**: the existing 🟢 beginner boxes, “Key takeaways”, “Check yourself”, pitfalls,
  and the “Next” pointer. Link practice to `EXERCISES.md`.

### Which versions each phase needs (minimum ladder)

| Phase | V1 line-by-line | V2 functions | V3 classes | V4+ |
|------:|:---------------:|:------------:|:----------:|-----|
| 0 | ✓ (handshake script) | ✓ (tiny helpers ok) | — | — (stays conceptual) |
| 1 | ✓ (loop with inline tool, **no `def`**) | ✓ (`dispatch`, `run_agent`) | ✓ (a minimal `Agent` class preview) | — |
| 2 | ✓ (if/elif dispatch inline) | ✓ (dict registry of functions) | ✓ (`Tool` + `ToolRegistry`) | ✓ `@tool` decorator |
| 3 | ✓ (transcript as a plain list inline) | ✓ (helper functions) | ✓ (`Conversation` class) | streaming events |
| 4 | ✓ (one file-tool inline) | ✓ (tool functions + confinement helpers) | ✓ (workspace-confined tool set) | — |
| 5 | ✓ (inline `if` permission check) | ✓ (`check_permission`) | ✓ (policy/mode objects) | hooks |
| 6 | ✓ (inline token estimate + truncate) | ✓ (`count_tokens`, `prune_to_budget`) | ✓ (manager form) | `compact` |
| 7 | ✓ (a second loop pasted inline) | ✓ (`run_subagent` function) | ✓ (task-tool + Agent reuse) | threads/parallel |
| 8 | consolidation phase — shows how the V3/V4 forms fold into the package | | | |

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
2. **Version ladder** — does the phase present complete runnable versions at each
   abstraction level its row in the table above requires (line-by-line → functions →
   classes → decorators/threads), each framed as “the same harness, reorganized,” with
   a what-changed note between versions?
3. **Step size** — is each new idea introduced alone, with a motivation and a run/check?
4. **Basic-before-advanced ordering** — are classes/decorators/threads deferred until
   after the plain version?
5. **Run-it cadence** — are there frequent “▶ Run it now” checkpoints?
6. **Continuity** — does it still flow, with beginner boxes/recaps/exercises intact?

## Loop control (max 10 iterations)

The evaluator-reviser loop runs **at most 10 times**, then stops on its own.

- Iterations used: **0 / 10** *(reset 2026-06-10 for the version-ladder pass)*
- Per iteration: score all phases on the rubric, pick the weakest, revise it one notch
  more incremental, increment the counter here, log it below, commit, push. Stop when the
  counter hits 10 **or** every phase scores ≥4 on every axis.

### Known issues for the loop to address (seed list)

- **Model-id inconsistency.** Runnable examples mix `MODEL = "gpt-5"`, `"gpt-4o"`, and
  `gpt-4.1`/`gpt-4o-mini` across phases. Standardize the runnable `MODEL = "..."` constant
  to one default (**`gpt-4o`**, matching the canonical `code/agent_harness/config.py` and
  the FAQ), while leaving genuine prose discussion of model *families* intact. (Rubric
  axis: correct & current.)
- Re-check that phases whose agents folded the old sidebar 🟢 box into live steps (Phase 2,
  Phase 5) still carry an explicit beginner-track recap.

## Revision log (newest first)

- **2026-06-10 — Version-ladder parallel pass complete.** Nine sub-agents (one per
  phase, run concurrently) restructured every phase to the ladder spec: each now
  presents complete runnable versions of its harness at increasing abstraction levels
  (V1 line-by-line with no `def` → V2 functions → V3 classes → V4 decorators/streaming/
  hooks/compact/threads where the phase teaches them), with "What changed Vn → Vn+1"
  bullet lists between rungs and ▶ Run-it checkpoints throughout. Phase 8 reframed as
  the consolidation phase with a verified ladder-to-package mapping table and a closing
  capability checklist. Phase 6 needed a second attempt (first agent's edits never
  reached disk). Verified after the pass: `code/` untouched, `python -m pytest` green
  (56), every phase retains its 🟢 boxes, "Key takeaways", "Check yourself", pitfalls,
  and "Next" pointer; Phases 2 and 6 gained the Exercises/Next footers they previously
  lacked. The evaluator loop refines from here.
- **2026-06-10 — Brief sharpened to the version-ladder spec.** New PM directive: each
  phase must contain complete, runnable versions of its harness at increasing
  abstraction levels (V1 line-by-line with no `def` → V2 functions → V3 classes →
  V4 decorators/threads where taught). Added the per-phase minimum-ladder table, a
  "Version ladder" rubric axis, and reset the loop counter. Parallel revision pass
  launched against the new spec.
- **2026-06-09 — Initial parallel pass complete.** Nine sub-agents (one per phase, run
  concurrently) restructured every phase to lead with **Step 0 — the simplest version that
  works** (basic functions, basic tools, no classes/decorators/threads), followed by
  one-idea-per-step increments each with a **▶ Run it now** checkpoint, deferring the
  production/class-based shape to later. Verified: `code/` untouched, `python -m pytest`
  green (56), every phase retains its 🟢 boxes, "Key takeaways", "Check yourself", and
  "Next" pointer. The evaluator loop below now refines from here.
