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
| 3 | **Per-phase "Key takeaways" + "Check yourself"** blocks, made consistent across all 8 phases | 4 | ◐ |
| 4 | **Hands-on exercises** ("Your turn") with hidden solutions at the end of each phase | 3 | ☐ |
| 5 | **A guided learning path / syllabus** ("Day 1 / Day 2 …" or "if you have 2 hours") at the top level | 5 | ☑ |
| 6 | **Beginner FAQ / troubleshooting** page: API keys, rate limits, common tracebacks, Windows vs. mac/Linux | 1, 4 | ☑ |
| 7 | **CI** that runs the test suite (and ideally a markdown link/code-block check) on every push | 6 | ☑ |
| 8 | **Verify phase code samples** against the canonical package — flag any drift between snippets and `code/` | 6 | ☐ |
| 9 | **Visual diagrams**: replace/augment ASCII with clearer flow diagrams where it helps a beginner | 4 | ☐ |
| 10 | **"What you'll have built" capstone** + a checklist mapping each phase's output to a feature of a real harness | 5 | ☐ |

## Iteration log

Newest first. One line per shipped iteration.

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
