# Roadmap — Making This the Best Beginner's Resource for Harness Engineering

> **Standing goal.** Iterate this repo until it is the single best place for a
> **Python beginner** (someone who knows functions, lists, dicts, operators, and
> `client.responses.create(...)`) to learn **harness engineering** — building the
> agent loop that powers tools like Claude Code and Cursor, from scratch.
>
> This file is the project manager's source of truth. Each iteration: pick the
> highest-value unchecked item, ship it (with tests green and a clear commit),
> check it off, and log it at the bottom. Keep the backlog honest — add new items
> as gaps surface, remove ones that stop mattering.

> **⚑ Current focus (2026-06-10):** the incrementality goal has sharpened again — each
> phase must now present its harness as a **ladder of complete runnable versions**
> (V1 line-by-line with no functions → V2 functions → V3 classes → V4 decorators/threads
> where the phase teaches them), each framed as "the same harness, reorganized." The spec
> lives in **[`REVISION-BRIEF.md`](./REVISION-BRIEF.md)** (per-phase ladder table +
> rubric) and is driven by a capped evaluator loop (≤50 iterations). Backlog items 9
> and 10 below remain deferred until this pass is done.

## The rubric — what "best beginner resource" means

A beginner-first harness resource should score well on every axis below. We use
these to prioritise the backlog and to judge whether a change is worth making.

1. **Zero-to-running fast.** A beginner can get *something* running (or the tests
   passing) in minutes, with copy-paste-safe instructions and no hidden gotchas.
2. **No unexplained jargon.** Every term beyond the assumed five concepts is
   defined the first time it appears, and findable later in one place.
3. **Learn by doing.** Each phase has hands-on exercises with checkpoints and
   solutions — not just code to read.
4. **Tight feedback loops.** The reader can always check "did I get it right?"
   (recaps, self-checks, runnable tests).
5. **One obvious path.** A beginner is never unsure what to read next; the
   sequence and the beginner track are impossible to miss.
6. **Correct & current.** Code runs as written, tests pass, and model/API
   guidance reflects the latest stable Responses API.
7. **Concepts before cleverness.** The "manual" version is shown before the
   library shortcut; nothing important is hidden behind a framework.

## Backlog (prioritised)

Status: ☐ todo · ◐ in progress · ☑ done

| # | Item | Rubric axis | Status |
|--:|------|-------------|:------:|
| 1 | **Glossary** of every harness/Python term the guide uses, linked from the READMEs and referenced from phases | 2 | ☑ |
| 2 | **Setup gotchas fix**: document `python -m pytest` (not bare `pytest`), venv guidance, and an API-key-free first-run path | 1 | ☑ |
| 3 | **Per-phase "Key takeaways" + "Check yourself"** blocks, made consistent across all 8 phases | 4 | ☑ |
| 4 | **Hands-on exercises** ("Your turn") with hidden solutions — shipped as a dedicated `EXERCISES.md` (warm-up + stretch per phase) | 3 | ☑ |
| 5 | **A guided learning path / syllabus** ("Day 1 / Day 2 …" or "if you have 2 hours") at the top level | 5 | ☑ |
| 6 | **Beginner FAQ / troubleshooting** page: API keys, rate limits, common tracebacks, Windows vs. mac/Linux | 1, 4 | ☑ |
| 7 | **CI** that runs the test suite (and ideally a markdown link/code-block check) on every push | 6 | ☑ |
| 8 | **Verify phase code samples** against the canonical package — flag any drift between snippets and `code/` | 6 | ☑ |
| 9 | **Visual diagrams**: replace/augment ASCII with clearer flow diagrams where it helps a beginner | 4 | ◐ |
| 10 | **"What you'll have built" capstone** + a checklist mapping each phase's output to a feature of a real harness | 5 | ☐ |
| 11 | **Notebook resource**: executed jupytext companion notebooks for phases 0–3 + 6, offline CI gate, kernel/setup docs | 1, 3, 4 | ☑ |
| 12 | **Companion notebooks for phases 4/5/7/8** (hybrid slices per the expert v1-scope verdict: scripted-asker permission gate, tmpdir tools, sub-agent core, Phase-8 demo trio) | 3 | ☑ |

## Iteration log

Newest first. One line per shipped iteration.

- **2026-06-13** — Cycle 19 (user-seeded): persona-eval framework — five deterministic
  suites (beginner/ux/notebooks/frontend/pedagogy, 3305 cases, ≥200 each) codifying
  every persona's standards as offline machine-checks; all green, wired into CI as a
  permanent regression gate.
- **2026-06-12** — Cycle 18 (user-seeded): bite-sized lesson delivery — 76 ~10-minute
  lesson pages with hubs, Continue cards, time estimates, and a lesson rail, specced
  by a learning-science persona and gated on anchor parity (full pages id-identical),
  partition completeness, link integrity, and word ceilings.
- **2026-06-12** — Cycle 17 (user-seeded): pages-too-long/too-few-visuals — Reference
  sections collapse with anchor-safe auto-expand (Phase 4 −33.5%), the three ASCII
  diagrams now render as designed SVGs (Item 9 ◐ — site half done; md-side diagrams
  for Phase 0/6 remain), plus per-phase medallion, 0–8 rail, ladder map, progress bar.
- **2026-06-12** — Cycles 15–16: independent second \$10k-designer review (20 renders;
  verdict 3.5/5 with the stock light pygments palette as the headline catch) and full
  implementation of her 12 inputs — GitHub-Light code tokens, pruned TOCs, nav-toggle
  fixes, book-measure print, mono label voice, typographic site mark.
- **2026-06-12** — Cycle 14: visual verification via Playwright/Chromium (committed
  screenshot harness; 13 renders reviewed by the designer persona). Caught and fixed
  a mobile-clipping bug, printing breadcrumbs, and a hero widow; copy-button and
  print behaviors verified in pixels. \$10k verdict reinstated.
- **2026-06-12** — Cycles 12–13: \$10k-designer persona critiqued the site (tier 2/5,
  found the pygments line-height bug) and shipped a computed design spec; implemented
  end-to-end (indigo identity, type scale, index hero, component redesigns, detail
  kit). Designer sign-off: tier 4.5/5, approved as \$10k work.
- **2026-06-12** — Cycle 11: three-persona re-verification — all fixes confirmed,
  beginner verdict upgraded to "the best way to learn this guide"; 8 residual polish
  items closed (TOC suffixes, .ipynb→GitHub, back-to-top reveal, keyboard anchors).
- **2026-06-12** — Cycle 10: all ~15 banked site fixes applied (generator + markdown)
  with a pinned CI drift gate for site/html; output byte-idempotent, 0 broken links.
- **2026-06-12** — Cycle 9 (build + verify; fixes deferred): generated HTML mirror of
  the guide (site/build_site.py, 17 offline pages, GitHub-parity anchors, 0 broken
  links, byte-idempotent) reviewed by front-end/UX/beginner personas — beginner
  verdict: prefers the site over GitHub. ~15 ranked fixes banked for the next cycle.
- **2026-06-12** — Cycle 8: shipped Item 12 — companion notebooks for phases 4/5/7/8
  (tmpdir-confined tools, scripted-asker permission gate with deny-beats-session-memory
  asserted, recursive task tool with per-agent FakeClients + depth guard + threaded
  timing, and Phase 8's demo trio incl. the 56-test suite run from a cell). Every phase
  0–8 now has a notebook; all ten execute headlessly keyless, pairs in sync.
- **2026-06-11** — Cycle 7 (user-seeded, Colab): notebooks now self-bootstrap on Google
  Colab (GH_TOKEN secret for the private repo, no-op locally/CI), with badges, README
  Colab section, and FAQ entry; bootstrap success/failure paths simulated end-to-end.
  (The loop's cap was subsequently raised 10 → 20, so the loop remains open.)
- **2026-06-11** — Persona dev loop, cycle 6 (beginner through the notebooks): two
  readers verified all six notebooks keyless — zero blockers, outputs reproduced
  cell-for-cell; their ~10 fixes (Exercise 1.1 tools-list trap, USE_REAL_API gating
  on live cells, convention drift) landed in one pass; all six re-executed offline,
  pairs in sync, tests green.
- **2026-06-11** — Persona dev loop, cycle 5 (Jupyter expert → build): shipped Item 11 —
  six executed notebook pairs (setup-check, 0, 1, 2, 3, 6) + contract README +
  refresh.sh + offline CI gate + FakeClient instructions= fix, all verified to execute
  headlessly with no API key. Phases 4/5/7/8 companions logged as Item 12.
- **2026-06-11** — Persona dev loop, cycle 4 (UX): three UX-designer reviewers audited
  the entry funnel, in-phase pacing, and cross-guide consistency; a shared design
  contract was applied by four agents (single front-door CTA, nav headers + mini-TOCs,
  uniform checkpoints, Reference-copy banners, Phase 4/8 numbering repairs, Phase 8
  Graduation ending, Appendix identity). Links/anchors 0 broken; tests green.
- **2026-06-11** — Beginner-persona dev loop, cycle 3: re-verification found zero
  blockers in phases 0–5 and two in Phase 8 (un-runnable §9 tests → new §9.0 shims,
  execution-verified; dead `--transcript` flag → fixed); closing polish landed across
  all phases. Loop converged: 13 verified blockers (cycle 1) → 2 (cycle 3) → 0.
- **2026-06-11** — Beginner-persona dev loop, cycles 1–2: a role-played Python-beginner
  reader executed every offline checkpoint and filed 13 verified blockers + ~50 smaller
  issues; all fixed across phases 0–8, entry docs, and one real `code/` bug (keyless CLI
  traceback). Details in `REVISION-BRIEF.md` (iterations 4–5). Tests green (56).

- **2026-06-09** — Shipped **Item 8**: audited phase snippets vs the canonical package by
  extracting every module/symbol and every `*.py` reference. Found real drift — phases
  name `tools.py`, `agent_loop.py`/`safe_dispatch()`, and `sandbox.py`/`run_sandboxed()`,
  none of which exist as modules in `code/`. Added a "Phase file names this package
  consolidates" reconciliation table to `code/README.md` so beginners can always find
  where a phase's code actually lives. (Two stale phase cross-references were already
  fixed in the Item 3 passes.)
- **2026-06-09** — Shipped **Item 4**: `EXERCISES.md` — a warm-up + a stretch task per
  phase (0–8) plus a capstone, each with a collapsible hint that points at the relevant
  phase section and the canonical `code/` answer key. Linked from the README and Learning
  Path. (Kept as one consolidated file rather than scattered per-phase blocks, so it's a
  single practice surface that complements the per-phase "Check yourself".)
- **2026-06-09** — **Completed Item 3** ☑: added "Key takeaways" + "Check yourself" to
  phases **6, 7, 8** — all 8 phases now carry the recap/self-test layer. Also fixed a
  second navigation bug: phase 7's "What's Next" described a stale 10-phase plan
  (phases 8/9/10) instead of the real, final Phase 8.
- **2026-06-09** — Continued **Item 3** (◐): added "Key takeaways" + "Check yourself"
  to phases **3, 4, 5**. Also fixed a navigation bug — phase 3's "Next" pointer
  mislabeled Phase 4 as context management (it's Real Tools). Remaining: phases 6–8.
- **2026-06-09** — Started **Item 3** (◐): added "Key takeaways" + "Check yourself"
  (with collapsible answers) to the Taster-track phases **0, 1, 2**. Remaining: phases
  3–8. Confirmed the CI run on PR #6 went green (3.10/3.11/3.12).
- **2026-06-09** — Shipped **Item 7**: GitHub Actions CI (`.github/workflows/ci.yml`)
  running `python -m pytest` on a 3.10/3.11/3.12 matrix for every push/PR (offline, no
  secrets). Added a CI badge to the README. Markdown link-check left as a future add-on.
- **2026-06-09** — Shipped **Item 6**: `FAQ.md` — beginner troubleshooting grounded in
  the actual code (install/interpreter mismatch, `OPENAI_API_KEY`, model selection &
  `--model`, rate limits, "agent did nothing", reading tracebacks bottom-up, Windows
  notes). Linked from the README and Learning Path.
- **2026-06-09** — Shipped **Item 5**: `LEARNING-PATH.md` — a guided route with three
  time-budgeted tracks (Taster / Weekend / Deep), a per-phase "build / do / checkpoint"
  plan, and a one-time setup block. Linked as the first "Start here" item in both READMEs.
- **2026-06-09** — Shipped **Item 2**: a "Setup & troubleshooting" section on the
  top-level README (venv guidance, `python -m pytest` rationale, API-key-free path,
  `command not found` fix). Verified `python -m agent_harness.cli` is a valid entry.
- **2026-06-09** — Established this roadmap + rubric; shipped **Item 1**: a 50+ term
  `GLOSSARY.md` covering harness, agent-loop, and Python/API jargon, linked from
  both READMEs. Confirmed the test suite (56 tests) passes via `python -m pytest`.
