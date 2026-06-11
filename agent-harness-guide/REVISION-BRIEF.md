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

- Iterations used: **6 / 10** *(reset 2026-06-10 for the version-ladder pass; iterations 4–6 ran 2026-06-11 as the beginner-persona dev loop below)*
- Per iteration: score all phases on the rubric, pick the weakest, revise it one notch
  more incremental, increment the counter here, log it below, commit, push. Stop when the
  counter hits 10 **or** every phase scores ≥4 on every axis.

### Known issues for the loop to address (seed list)

- Phase 3's beginner-track code lives inside a `>` blockquote: renders fine on GitHub,
  but copying from the *raw* file grabs `> ` prefixes. Decide whether to restructure
  (carefully — additive-only) or add a one-line "copy from the rendered page" note.
- Phase 7 Step 4.3's `_dispatch_step` is a `self` method shown without its integration
  point (`sub_registry_context` never constructed; absent from the §7 consolidated
  listing) — a beginner can't tell where it goes or who calls it.
- The `ERROR:` vs `Error:` tool-result convention still differs between Phase 4 and
  Phase 5 (now documented in-phase; full standardization deliberately deferred).
- ~~Model-id inconsistency~~ — resolved (cycle 1): runnable snippets standardized on
  `gpt-4o`; deliberate prose exceptions documented in the 2026-06-11 log entry.
- ~~Phase 2/5 beginner-track recap check~~ — resolved (cycle 1): Phase 2 already clear;
  Phase 5 gained an explicit "V1+V2 is a legitimate stopping point" paragraph.

## Revision log (newest first)

- **2026-06-11 — Iteration 6: beginner-persona dev loop, cycle 3 (verification +
  closing polish).** A second cold-read pass (three fresh "Sam" readers, same scopes)
  confirmed every cycle-2 fix held under execution: phases 0–5 had **zero blockers**
  (all offline checkpoints byte-exact, keyless path honest, the reordered permission
  gate verified safe), and phases 6–8 had two: Phase 8 §9's tests imported four modules
  the phase never printed (fixed with a new §9.0 layout + shim listings —
  execution-verified, 2 passed), and the shown CLI's `--transcript` flag was dropped
  by an argparse `dest` mismatch (fixed). Remaining confusions/paper cuts across all
  phases closed in the same pass (getattr-fallback gloss, `_build_schema` agreement,
  Phase 0 layout diagram, fnmatch brace-glob in a model-facing docstring, first-line-
  only Args-parsing warning, `prune_to_budget` over-budget-by-design note, etc.).
  Commits: cycle-3 slices for phases 0–3, 4–5, 6–8. Tests 56 green throughout; the
  loop's verification method (cold beginner read + execute) is now the recommended
  acceptance gate for future passes.
- **2026-06-11 — Iterations 4–5: beginner-persona dev loop (cycles 1–2).** New
  verification method: after each revision pass, a fresh sub-agent role-plays "Sam," a
  Python beginner (the assumed five concepts only), reads the repo cold, executes every
  offline checkpoint, and reports blockers/confusions/paper cuts with file:line; that
  report seeds the next revision pass. Cycle 1 (iteration 4) closed the old seed list
  (model ids → `gpt-4o`; Phase 5 stopping-point recap). The beginner pass (three
  readers: phases 0–3, 4–5, 6–8) then found 13 verified blockers, including: a keyless
  reader dead-ends at every ▶ checkpoint despite "no key needed to learn" (and the
  documented missing-key error was wrong); Phase 4's `glob` `**` branch broken in all
  three copies (`lstrip("**/")` strips chars, not a prefix); Phase 5's hook regex never
  matched `rm -rf` and session memory silently overrode hard denials (one `a` answer
  re-enabled `bash(rm -rf /)`); Phase 8's §7 `run_turn` TypeError'd on its own §9.3
  test; Phase 7's sample transcripts were unproducible by the shown code; Phase 6
  referenced an undefined `_is_done`. Cycle 2 (iteration 5) fixed all of these plus
  ~20 confusions and ~30 paper cuts across all phases + entry docs (commits 9d5a6be,
  a03d9a1, 49b6a62), and one real package bug found by the pass (keyless CLI raw
  traceback — cf7cc0f, the only `code/` change; tests 56 green throughout). Remaining
  items carried into the seed list above.

- **2026-06-10 — Eval-loop iteration 3: Phase 5 repaired (27 → 30/30).** Re-diagnosis
  found Phase 5's V3 `Tool` dataclass / `ToolRegistry` are deliberate in-file upgrades
  (not phantoms) — but they were mislabeled "extend from Phase 2," the module name
  `tools.py` collided with Phase 2's `tools/` package, `tool_registry.py` used `Tool`
  without importing it (NameError), `to_api_dict` set `"strict": True` (rejected by the
  API for tools with optional params), and the final run checkpoint imported a phantom
  `real_tools.build_registry`. Fixed: renamed this phase's module to `risk_tools.py`
  with a Phase 2↔Phase 5 bridge table + shadowing warning, added the missing import,
  dropped strict, and built the missing `phase5_tools.py` (adapts Phase 4's seven
  `coding_tools` FunctionTools into risk-tagged Tools, rebuilds `bash` on the sandbox,
  exports `build_registry()`) with an offline ▶ check. Updated the run-checkpoint file
  list and files-added table. All 7 new/changed snippets AST-parse; tests green (56).
  Note: org spend limit currently blocks sub-agent launches — this iteration was done
  in-session; remaining candidates (P2 step-size 4, P8 continuity 4) are at-target
  (≥4 on all axes), so the loop's stop condition is met unless re-grading finds new
  below-4 evidence.
- **2026-06-10 — Eval-loop iteration 2: Phase 4 repaired (25 → 30/30).** Phase 7's
  iteration-1 repair verified intact. Confirmed and fixed Phase 4's continuity drift
  against Phase 2's real API: `from registry import tool, Registry` → `from tools
  import tool, ToolRegistry`, `tools_list()` → `to_openai_schema()`, dict-arg dispatch
  → raw-JSON-string dispatch; renamed Phase 4's module `tools.py` → `coding_tools.py`
  (it was shadowed by Phase 2's `tools/` package — a newly found beginner-breaking
  trap); added a Step 3.0 wiring bridge, `# Needs:` prerequisite headers, and two new
  run checkpoints (incl. an offline smoke test). Next target: **Phase 5** — confirmed
  phantom import `from tools import Tool, RISK_DANGEROUS` (`RISK_DANGEROUS` doesn't
  exist in Phase 2's package) plus its multi-file V4 assembly with unnamed
  prerequisites.
- **2026-06-10 — Eval-loop iteration 1: Phase 7 repaired.** Full 6-axis scoring of all
  phases (totals: P0 30, P1 30, P2 29, P3 30, P4 25, P5 27, P6 28, P7 24, P8 27).
  Weakest was Phase 7 (run-it cadence 3 — checkpoints with unrunnable placeholder
  files; continuity 3 — stale `ToolRegistry` API references and the only phase missing
  Exercises/Next footers). Fixed additively: a Step 3.0 "bridge" adding the three
  helper methods V3/V4 assume onto Phase 2's real `ToolRegistry`, complete
  self-contained `v3_agent_class.py` / `v3_task_tool.py` run files (no placeholders),
  and the missing Exercises link + Phase 8 pointer. Known remaining below-4 axis:
  **Phase 4 continuity 3** (imports a phantom `registry` module / `tools_list()` /
  dict-arg dispatch that don't match Phase 2's actual API) — queued for iteration 2.
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
