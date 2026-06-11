# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This is **an educational resource**, not a product. It teaches a Python beginner how to build an
agentic coding harness (the kind of loop behind Claude Code / Cursor) from scratch, using only the
OpenAI **Responses API** (`client.responses.create(...)`) and the standard library — no LangChain,
no agent SDKs. It has two parts that must be understood together:

- **`agent-harness-guide/0X-*.md`** — an 8-phase prose guide (Phase 0 foundations → Phase 8
  production). The code *snippets* here are deliberately incremental and **intentionally diverge**
  from the package: a phase shows ideas *as they grow*, often a simpler form than the final one.
- **`agent-harness-guide/code/`** — the single, consolidated, **tested** `agent_harness` package.
  This is the **source of truth**. **When a phase snippet and the package disagree, the package is
  correct** (it has the passing tests). Do not "fix" a phase to match the package, or vice-versa,
  without understanding this is the deliberate teaching arc.

Because it's a learning resource, **prose quality and pedagogy are first-class deliverables**, on par
with code correctness.

## Commands

All package commands run from `agent-harness-guide/code/`:

```bash
pip install -e ".[dev]"          # install package + pytest (needs network once for `openai`)
python -m pytest -q              # run the full suite (56 tests), fully offline
python -m pytest tests/test_agent_loop.py -v          # one file
python -m pytest tests/test_context.py::<name> -v     # one test
```

- **Always use `python -m pytest`, never bare `pytest`.** A globally-installed `pytest` can belong to
  a different interpreter and fail with `ModuleNotFoundError: No module named 'agent_harness'`. The
  `python -m` form binds the interpreter you installed into. A venv avoids this entirely.
- **No API key is needed for tests** — `agent_harness/testing.py` provides a `FakeClient` that scripts
  exact Responses-API replies offline. A key (`OPENAI_API_KEY`) is only needed to actually run the
  agent: `agent-harness` (or `python -m agent_harness.cli`).

## Package architecture (the big picture)

The core idea: an LLM is stateless text-in/text-out; the **harness** is the loop that gives it memory
(a transcript you resend each turn) and hands (tools). The Responses API contract every module relies
on: `responses.create(model, input, tools)` returns `response.output`, a **list of typed items**
(`message` vs `function_call`); a tool call is answered by appending a `function_call_output` carrying
the **same `call_id`** and a **string** result.

Data flows through collaborators wired together by `Agent` (`agent.py`):

- **`llm.py` (`LLMClient`)** — wraps the OpenAI client with retry/backoff; the client is **injectable**,
  which is what makes `FakeClient` testing possible. Don't call `OpenAI()` directly in new code paths;
  go through `LLMClient`.
- **`conversation.py` (`Conversation`)** — owns the transcript as a plain list; `to_input_dict()`
  normalizes SDK objects (`.model_dump()`) and plain dicts so both can be resent as `input`.
- **`tools/`** — `base.py` (`Tool` + `@tool`, which auto-builds JSON schema from type hints/docstring),
  `registry.py` (`ToolRegistry.dispatch()` — **catches all tool exceptions and returns `"Error: ..."`
  strings; never raises into the loop**), `parallel.py` (threaded dispatch), `files.py`/`shell.py`
  (the real tools; `bash` is workspace-confined via `set_workspace`).
- **`permissions.py` + `hooks.py`** — `check_permission()` gates tool calls by mode/policy before they
  run; denials become tool-result error strings. Hooks fire before/after tools without touching the loop.
- **`context.py`** — `count_tokens`, `prune_to_budget` (preserves `function_call`/`function_call_output`
  pairing and the first user message), `compact` (model-summarizes the older half) for long sessions.
- **`subagents.py`** — a sub-agent is just `run_agent`/`Agent` invoked again from inside a `task` tool.
- **`config.py`** — `Settings` dataclass; `MODEL_DEFAULT = "gpt-4o"` is the canonical model id.

Note the guide intentionally names a few files that **don't exist** as modules (`tools.py`,
`agent_loop.py`/`safe_dispatch()`, `sandbox.py`/`run_sandboxed()`) — these are illustrative; the
package consolidates them (see the mapping table in `agent-harness-guide/code/README.md`).

## Editing conventions for the guide (phase markdown)

These files follow a deliberate beginner-incremental shape; preserve it when editing:

- Each phase opens with **"Step 0 — the simplest version that works"** (basic functions/dicts, no
  classes/decorators/threads), then adds **one concept per step**, each ending in a **▶ Run it now**
  checkpoint, with the production/class-based form deferred and framed as "the same idea, organized."
- Keep the **🟢 beginner boxes**, **"Key takeaways"**, **"Check yourself"** (collapsible `<details>`
  answers), pitfalls, and the **"Next"** pointer at the end of each phase.
- Edits to phases are **markdown only** — never change `code/` to make a snippet match, and never run
  the guide's snippets against the package expecting equality.

## Notebooks (`agent-harness-guide/notebooks/`)

Companion runnables for phases 0–3 and 6 (+ `setup-check`). Rules (the drift firewall):

- Each notebook is a jupytext **py:percent pair**; the `.py` is the review surface — **edit the
  `.py`, then `jupytext --sync`**, never hand-edit the `.ipynb`.
- The `.ipynb` carries **committed FakeClient outputs** (GitHub rendering for keyless readers);
  refresh them via `notebooks/refresh.sh` after any notebook edit, and commit both files.
- Notebooks **import the package** and drive it — they do not re-paste phase version ladders.
- No `input()` / `while True` REPLs; no bare `OpenAI()` outside the `USE_REAL_API` guard; build a
  `FakeClient` and consume it **in the same cell** (turns pop off a list; re-running re-scripts).
- Every notebook must execute headlessly top-to-bottom with **no API key** — CI enforces this via
  the `notebooks` job in `.github/workflows/ci.yml` (jupytext-sync check + `jupyter execute`).
- When a notebook and a phase snippet differ, that is the deliberate divergence: **the package is
  correct** (see `notebooks/README.md`).

## Project-management artifacts

The repo is iterated against written specs; read these before large changes:

- **`agent-harness-guide/ROADMAP.md`** — standing goal, a 7-axis "best beginner resource" rubric, a
  status-tracked backlog, and an iteration log.
- **`agent-harness-guide/REVISION-BRIEF.md`** — the current focus (making every phase more
  incremental), the evaluation rubric, and a capped (≤10) revision loop counter + log.

## CI & workflow

- CI (`.github/workflows/ci.yml`) runs `python -m pytest` on a 3.10/3.11/3.12 matrix for every push to
  `main` and every PR. Keep it green.
- Development happens on feature branches (currently `claude/python-harness-learning-resource-rr3tpi`),
  not `main`. Commit and push frequently — the execution environment is ephemeral.
