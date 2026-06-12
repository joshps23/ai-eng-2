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

## Loop control (max 20 iterations)

The evaluator-reviser loop runs **at most 20 times**, then stops on its own.

- Iterations used: **19 / 20** *(cap raised 10 → 20 on 2026-06-12 by maintainer decision; reset 2026-06-10 for the version-ladder pass; iterations 4–10 ran 2026-06-11 as the persona dev loop below — beginner persona for 4–6 and 9, UX designer for 7, Jupyter expert for 8, user-seeded Colab pass for 10)*
- Per iteration: score all phases on the rubric, pick the weakest, revise it one notch
  more incremental, increment the counter here, log it below, commit, push. Stop when the
  counter hits 20 **or** every phase scores ≥4 on every axis.

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

- **2026-06-12 — Iterations 18–19: independent second designer + implementation
  (cycles 15–16).** A second \$10k-designer persona ("Margaux", editorial school,
  deliberately blind to the first spec) reviewed 20 Playwright renders. Independent
  verdict: 3.5/5 — "\$6–7k work with \$10k bones" — with catches the first pass
  missed: the stock pygments default still on light mode's code (the largest
  surface), desktop nav chrome, viewport-overflowing TOCs, an affordance-free mobile
  toggle, hr+h2 double rules, half-blank print sheets. All 12 of her prioritized
  inputs implemented and pixel-verified (GitHub-Light token palette with recomputed
  AA, checkpoint-free TOCs, both-ends toggle fix, book-measure print, mono label
  voice, typographic agent-harness/ mark). Byte-idempotent; 530/530 heading ids
  stable; tests green. Two-designer protocol note for the loop: independent fresh
  eyes found a class of defects the spec-author's own sign-off could not.

- **2026-06-12 — Iteration 17: Playwright visual verification (cycle 14).** By
  maintainer instruction, the verification phase now renders real pixels: a committed
  harness (site/screenshot_site.py) drives headless Chromium over the served site —
  13 captures across desktop/mobile, light/dark, hover states, the opened long-page
  TOC, and print emulation. The designer persona reviewed the renders and found what
  CSS reading missed: a tier-killing mobile bug (column-flex align-items shrank main
  to max-content, clipping every line at 390px), the markdown breadcrumb printing as
  indigo links, a hero widow, and an unverified copy-button state (the capture had
  hovered a nocopy diagram — itself praised as correct design). All fixed and
  re-verified in pixels: mobile full-width, Copy pill reveals on hover, print
  chrome-free. Designer verdict: 4/5 pending these fixes → criteria met for the
  reinstated 4.5/5. Harness gotcha for posterity: smooth-scroll leaves unpainted
  white tiles in headless screenshots — use instant scrolls.

- **2026-06-12 — Iterations 15–16: \$10k-designer pass on the site (cycles 12–13).**
  New verification persona by maintainer instruction: an elite front-end designer
  ("creates \$10,000 webpages") critiqued the site's design quality. Verdict: "tier 2
  of 5 — a competent generated mirror wearing GitHub's clothes," with a real rendering
  bug found (pygments' line-height:125% silently overriding the intended 1.6 on every
  code block). The designer shipped a fully computed spec (type scale, harness-indigo
  palette with AA ratios for every pair, component redesigns, index landing treatment,
  the expensive-details kit). Iteration 16 implemented it end-to-end in build_site.py:
  48/48 recomputed contrast pairs pass both schemes, 513 heading ids byte-stable,
  protect list held (anchors, no-JS fallbacks, print, pygments, mobile),
  byte-idempotent. Designer sign-off review: all five implementation deviations
  approved (one fixed a bug in the spec itself); **final verdict tier 4.5/5 — signed
  off as \$10k work** (remaining half-tier: an og.png social card, deferred). Cycles
  ran ~290k of a 1M budget.

- **2026-06-12 — Iteration 14: site re-verification + sign-off polish (cycle 11).**
  The three personas re-reviewed the fixed site: front-end — ship-ready, all ten
  findings resolved, zero regressions (heading ids byte-stable vs the old build);
  UX — 8/12 fully resolved, flagged the TOC-suffix regression and the .ipynb raw-JSON
  dead-end; beginner — everything resolved, verdict upgraded to "clearly the best way
  to learn this guide". Their 8 residual items closed in one polish pass (short
  nearest-step TOC suffixes, .ipynb → GitHub routing, scroll-revealed back-to-top,
  keyboard-reachable permalink anchors, labeled navs, print tables, index title,
  focus restore). Final state: byte-idempotent, 0 broken links/anchors, 513 heading
  ids unchanged, tests green. Cycles 10–11 ran ~420k of the refreshed 1M budget.

- **2026-06-12 — Iteration 13: HTML-site fix cycle (cycle 10).** Applied all three
  cycle-9 persona reviews: root-cause repair of the blockquote-list fence indentation
  (04's split/renumbered list — fix also caught a latent identical split in 07),
  dark-mode AA contrast, print stylesheet + beforeprint details-opener, mobile sidebar
  collapsed by default, copy-button fallback chain, semantic table wrappers + th
  scopes, nested/disambiguated long-page TOCs + back-to-top, a distinct Reference-copy
  component, hover heading anchors, repo-file link affordances (↗ + footer explainer),
  plus the markdown-side fixes (surface-neutral Warning legend, Exercises deep links,
  FAQ list spacing, hint/heading name match, Phase-6 box link) and a pinned CI drift
  gate that regenerates the site and fails on diff. Output re-verified: byte-
  idempotent, 0 broken links/anchors, all pages parse, tests green.

- **2026-06-12 — Iteration 12: generated HTML site + three-persona review (cycle 9;
  build + verify only, fixes deferred by maintainer instruction).** Shipped
  site/build_site.py (offline-first, python-markdown + pygments, no CDN) generating 17
  pages with GitHub-compatible slugs (every md-authored anchor resolves), rewritten
  links, styled warnings/beginner boxes, working details blocks, sidebar nav +
  per-page TOCs + prev/next; byte-idempotent; 1,126 hrefs 0 broken; the markdown
  remains source of truth. Verified by three personas: a front-end engineer
  (structural hygiene excellent; found a split/renumbered <ol> around a list-nested
  fence in 04, a dark-mode AA contrast failure on the current-nav item, no print
  stylesheet, mobile sidebar defaults open, silent copy-button failure), a UX
  reviewer (IA and component differentiation beat GitHub; long-page TOC doesn't scale
  — nine identical "Run it now" entries; Reference-copy banners still visually flat;
  .ipynb links dead-end off-GitHub), and a beginner reader (zero blockers; code
  conversion verified byte-identical 93/93 blocks in phases 0–2; verdict: prefers the
  site over GitHub — but out-of-site links need an affordance, the Learning Path
  legend says [!WARNING] which the site never displays, FAQ ordered lists flattened).
  Reports banked as the next cycle's seed (cycle9-fe/ux/beginner-site). Ran under a
  500k budget (~315k used).

- **2026-06-12 — Iteration 11: companion notebooks for phases 4/5/7/8 (cycle 8, ROADMAP
  Item 12).** Built to the cycle-5 Jupyter-expert v1-scope verdict via a cycle-8
  addendum to the build contract: 04 (confinement arc in a throwaway tmpdir; production
  tools imported from the package, nothing rebuilt), 05 (risk-by-mode decision table;
  scripted asker replacing input() with the StdinNotImplementedError explanation;
  deny-beats-session-memory asserted; env-allowlisted sandbox), 07 (recursive task tool
  with one FakeClient per agent; depth guard asserted both sides; model-free
  sequential-vs-threaded timing), 08 (the honest thin slice: retry backoff with
  no-sleep-after-final-attempt assert; JSONL tracer + cost accounting; the package's
  56-test suite run and machine-asserted from a cell). Docs: four table rows replacing
  the 'no notebook on purpose' note, phase pointer lines, 'every phase 0–8' coverage
  mentions. Acceptance: all TEN notebooks execute headlessly keyless, 20 pair files in
  sync, tests green. Ran under a 900k budget (~300k used).

- **2026-06-11 — Iteration 10: Colab seamlessness (cycle 7, user-seeded).** A real
  Colab user hit `ModuleNotFoundError: No module named 'agent_harness'` on the first
  cell — Colab fetches a single .ipynb, never the repo. Requirement: a seamless Colab
  experience with no missing-package errors. Shipped: a self-bootstrapping first cell
  in all six notebooks (strict no-op locally/CI; on Colab it clones via the GH_TOKEN
  Colab secret — private repo — with anonymous fallback, scrubs the token from the
  git remote, pip-installs into the running kernel, and exits with guidance instead
  of a traceback when the secret is missing), Open-in-Colab badges, a
  Running-on-Google-Colab README section, a FAQ entry, and the no-op rule in
  CLAUDE.md. Verified: all six still execute headlessly offline; the bootstrap's
  success AND failure paths were simulated end-to-end in a bare venv against a local
  clone; pairs in sync; 56 tests green. (This entry originally closed the loop at the
  10-iteration cap; the cap was later raised to 20, reopening the loop.)
- **2026-06-11 — Iteration 9: beginner-persona pass through the notebooks (cycle 6).**
  Two fresh "Sam" readers verified the new notebook resource end to end on /tmp
  copies: discovery from the front door works three ways; the documented setup
  works; **zero blockers** in all six notebooks; keyless outputs reproduced
  cell-for-cell against the committed ones; re-run resilience, the kernel-restart
  save/load flow, the hidden-state lesson, and the hard-stop handoffs all behaved
  as designed (the readers called 03 "the standout"). Their ~10 fixes landed in one
  pass: the Exercise 1.1 silent tools-list trap, live-API cells now gated on the
  USE_REAL_API switch (the README's one-switch contract is now true — no surprise
  spend), reset-cell rebuild, the unexplained None in self-checks, check-cell idiom
  boxes, 02's stale re-run-safety claim + self-diagnosing asserts, 06 convention
  drift, subsection anchors, and a Series-conventions list (defining C1) in
  notebooks/README.md. Re-verified: all six execute headlessly with no key, pairs
  in sync, 56 tests green. Cycle ran under a 500k-token budget (≈340k used).
- **2026-06-11 — Iteration 8: persona dev loop, cycle 5 (Jupyter-expert verification →
  notebook build).** The verification persona became a Jupyter-notebook expert: three
  reviewers (core funnel, advanced phases, notebook engineering) assessed how to turn
  the guide into a notebook resource, each shipping an *executed* proof of concept.
  Consensus: notebooks are companion runnables that import the tested package (never a
  third diverging copy); FakeClient makes the keyless path primary; review happens on
  jupytext py:percent pairs with committed deterministic outputs; CI executes every
  notebook headlessly with no key. Their PoCs surfaced real traps now codified in
  CLAUDE.md's notebook rules: notebook input() raises StdinNotImplementedError (Phase
  5's EOFError guard misses it), FakeClient.create() required instructions= (fixed in
  testing.py — the cycle's one code/ change, 56 tests green), and importlib.reload
  resets WORKSPACE_ROOT, silently un-confining the file tools. The build pass then
  shipped: notebooks/ with six executed jupytext pairs (setup-check, 00, 01, 02
  pre-package half, 03 transcript half, 06), notebooks/README.md contract +
  refresh.sh, a 'notebooks' extras group, a CI job (pair-sync check + offline
  execution), FAQ kernel entries, and link lines in the covered phases. Acceptance
  gate re-verified independently: all six execute offline, pairs in sync, links
  resolve, tests green. Deferred to the backlog: companion notebooks for phases
  4/5/7/8 (per the expert v1-scope verdict: hybrid/thin slices only).
- **2026-06-11 — Iteration 7: persona dev loop, cycle 4 (UX-designer verification).**
  The verification persona switched from "Python beginner" (correctness) to "senior
  UX/content designer" (reading experience): three reviewers covered the entry funnel,
  the in-phase experience (with measurements: code:prose ratios, checkpoint gaps up to
  999 lines, longest code blocks), and the late-guide/consistency axis (a component ×
  phase matrix). Their conflicting suggestions were resolved into a binding design
  contract (checkpoints as `### ▶ Run it now` H3s; a nav header on every phase; linked
  mini-TOCs; Reference-copy banners + offline Check-it-nows over consolidated listings;
  one closing-block template ending in a linked Next; 🟢 restricted to gloss/track;
  `> [!WARNING]` only for destructive-op sites; Phase 4's colliding dual numbering and
  Phase 8's ghost-§5 repaired). Front door rebuilt around a single Learning Path CTA;
  BEGINNER-NOTES became the "Python Concepts Cheat-Sheet" (its maintainer tracker moved
  to this file's appendix); Phase 8 now ends on a Graduation section instead of a
  fade-out; Appendix 09 got an explicit identity and inbound links. Verified after:
  repo-wide link/anchor check 0 problems, snippet-parse regressions 0, tests 56 green,
  `code/` untouched.
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

## Appendix — beginner-adaptation review tracker

*(Moved here from BEGINNER-NOTES.md in the cycle-4 UX pass: it is maintainer bookkeeping,
not learner content.)*

Status legend: ☐ not started · ◐ in progress · ☑ adapted for beginners

| File | Status | Notes |
|------|:------:|-------|
| `README.md` (top level) | ☑ | Beginner-track pointer box. |
| `agent-harness-guide/README.md` | ☑ | Beginner-track pointer in "Who this is for". |
| `00-foundations.md` | ☑ | Added orientation pointer + scaffolding for dot-access, `json.loads`, JSON Schema, `with`/stream, threads. |
| `01-bare-harness.md` | ☑ | Scaffolding for type hints, `**args`, `try/except`, list comprehension (with plain-loop equivalent), `__main__`. |
| `02-tool-system.md` | ☑ | Functions-only beginner material now lives in the version ladder itself (Versions 1–2 = schema dicts + dict registry + for-loop dispatch), flagged by the "🟢 Beginner track" heading near the top; plus inline boxes translating classes, the `@tool` decorator/introspection, and threads. |
| `03-conversation-and-streaming.md` | ☑ | Beginner track: `Conversation` as a plain dict + functions (new_conversation/add_user/extend_items/save/load); streaming framed as optional (use non-streaming `create()` + `output_text`). Inline boxes on the class methods and the argument-taking decorator. |
| `04-real-tools.md` | ☑ | One consolidated box: tools are plain functions; `@tool` is optional (hand-write schemas per Phase 2); plus heads-ups on `pathlib.Path`, `lambda`, f-string format specs, and try/except. |
| `05-permissions-and-safety.md` | ☑ | Beginner track: full permission check in dicts + if/else (TOOL_RISK, AUTO_OK, check_permission/ask_user); concept table for dataclass≈dict, Enum≈string constants, set≈list, closure, tuple-return, hooks. Inline box reframing hooks as plain functions. |
| `06-context-management.md` | ☑ | Beginner box: one idea (shrink the growing list) + three tactics (clip/drop-oldest/summarize) as plain functions; syntax notes on count_tokens≈len//4, the bare-`*` keyword-only marker, generator comprehensions, isinstance. |
| `07-subagents-orchestration.md` | ☑ | Beginner track: a sub-agent = calling your run_agent loop again from inside a `task` tool; Agent class→loop+conversation dict; presets→dict; parallel optional. Syntax table for @dataclass/@property/factory-closure/asyncio. |
| `08-production-harness.md` | ☑ | Beginner track: phase is polish not new ideas; retry shown as plain for-loop+try/except+sleep; table mapping dataclass/@property/@contextmanager/argparse/logging/typed-except/ThreadPool to known concepts. |
| `09-library-reference.md` | ☑ | Added a "beginner reading order" box: study §1 (openai, in-scope), skim §2–§4 (tiktoken/threads/subprocess) as background. |
| `code/` package | ☑ | Kept the tested package intact (source of truth); added a "New to Python?" reading-guide box to `code/README.md` mapping every module to its plain-functions phase box, plus beginner-pointer docstrings in `agent.py` and `tools/base.py`. |

**Review complete** — all files adapted for the beginner audience. Approach: in-place
scaffolding (green 🟢 boxes) + per-phase functions-and-dicts "Beginner track" rewrites
of anything using classes/decorators/threads, while leaving the original advanced
material intact for later. The runnable `code/` package was left untouched (so its tests
still pass) and bridged with a reading guide instead of a risky rewrite.

Each pass: pick the next ☐ file, adapt it, flip it to ☑, and note what was done.
