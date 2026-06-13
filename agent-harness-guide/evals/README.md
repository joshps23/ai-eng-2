# Persona evals

The dev loop's verification phase historically used role-played persona reviews
(a Python beginner, a UX designer, a Jupyter expert, a $10k front-end designer,
a learning-science professor). This directory turns each persona's standards
into a **deterministic, offline, machine-checkable** suite — so a regression
that a persona *would* have caught now fails a test instead.

## Layout

| File | Persona | Judges |
|------|---------|--------|
| `eval_beginner.py` | Python beginner | the markdown phases: runnable cold-starts, checkpoint/expected-output rhythm, keyless path, glossary coverage, link integrity |
| `eval_ux.py` | UX / content designer | markdown structure: nav headers, mini-TOCs, the closing-block ritual, checkpoint markup uniformity, cross-doc navigation |
| `eval_notebooks.py` | Jupyter expert | the 10 notebooks: bootstrap cell, `USE_REAL_API` guard, no `input()`/bare `OpenAI()`, committed outputs, jupytext pair-sync |
| `eval_frontend.py` | $10k front-end designer | the generated site: semantics, a11y, computed WCAG contrast, the design-token system, no stock-pygments leakage |
| `eval_pedagogy.py` | learning-science professor | the bite-sized lessons: position cues, time estimates, Continue cards, the bite-size word ceiling, anchor parity, partition completeness |
| `eval_statemachine.py` | state-machine expert | the state-machine curriculum: the Phase 1 V4 rung exists and teaches it, and the *taught* FSM is well-formed — graph reachability, terminals, no dead ends, determinism, no dangling transitions (parsed from the markdown) |

`harness.py` is the shared, dependency-free framework (a `Suite` of named
`(ok, detail)` cases + a runner). `run_all.py` runs every suite.

## Running

```bash
cd agent-harness-guide/evals
python run_all.py            # every suite; exits non-zero on any failure
python run_all.py beginner   # one or more named suites
python eval_frontend.py      # a suite module directly
```

No API key, no network: every case reads committed artifacts. The site evals
read `site/html/` (regenerate with `site/build_site.py` first if you changed
the markdown). The notebook pair-sync check uses `jupytext` if present and
skips cleanly if not.

## Conventions

- One assertion per `(artifact, check)` pair, with a precise case id, so every
  failure points at exactly one thing.
- Cases are deterministic and order-independent; a throwing case is a failing
  case.
- A case encodes a *defensible* standard a real reviewer of that persona would
  insist on — not arbitrary busywork. If a standard is aspirational/deferred,
  it lives in `REVISION-BRIEF.md`'s seed list, not as a perpetually-red case.
