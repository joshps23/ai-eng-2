# Notebooks — companion runnables for the guide

These notebooks are the **experiential leg** of the resource: they *run* the ideas the
phase markdown explains. They exercise the **tested `agent_harness` package** (the same
one the test suite covers) rather than re-pasting the phases' growing code ladders.

> **The contract.** These notebooks are companion runnables of the tested package in
> [`../code/`](../code/). When a notebook and a phase snippet differ, that is the same
> deliberate divergence described in [`code/README.md`](../code/README.md) — the phases
> show ideas *as they grow*, and **the package is correct**.

## Setup

One block, from the repo root (mirrors the [FAQ's canonical setup](../FAQ.md#setup--installation)):

```bash
cd agent-harness-guide/code
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,notebooks]"
python -m ipykernel install --user --name agent-harness --display-name "Python (agent-harness)"
jupyter lab ../notebooks/
```

The `ipykernel install` line registers **the venv that has `agent_harness` installed**
as a named kernel. **After opening a notebook, pick the "Python (agent-harness)"
kernel** — in JupyterLab via *Kernel → Change Kernel…*, in VS Code via the kernel
picker in the top-right of the notebook (it discovers the same kernelspec). If a
notebook hits `ModuleNotFoundError: No module named 'agent_harness'`, your kernel
isn't that venv — switch to **Python (agent-harness)** the same way (this is the
notebook analog of the `python -m pytest` vs bare `pytest` gotcha; see the
[FAQ](../FAQ.md)).

## No API key needed (the `USE_REAL_API` switch)

Every notebook runs **fully offline by default**: a tagged parameter cell near the top
sets `USE_REAL_API = False`, and a `make_client(...)` helper hands the agent a
`FakeClient` (from `agent_harness.testing`) scripted with exact Responses-API replies.
The committed outputs you see on GitHub are these deterministic FakeClient outputs —
what you reproduce keylessly is exactly what's rendered.

Have a key and want the live API? `export OPENAI_API_KEY="sk-..."`, flip
`USE_REAL_API = True` in that one cell, and re-run. Everything downstream is identical
on both paths — the duality lives in that single cell, which is itself a curriculum
point (client injection).

## Series conventions

The notebooks refer back to these by name (e.g. Phase 3's notebook cites "rule C1"):

- **Run top-to-bottom.** When in doubt (or after experimenting): **Kernel → Restart &
  Run All**. The notebooks are written for strict top-to-bottom execution, and every one
  must pass that headlessly with no API key — CI enforces it on every push.
- **C1 — the cell that appends/consumes also creates.** Every state-owning cell rebuilds
  its own state: a cell that appends to a transcript creates that transcript at its own
  top, and a cell that consumes a scripted `FakeClient` builds that client in the same
  cell. That's what makes re-running any single cell safe. (The few cells that
  deliberately *break* this rule, to demonstrate persistence, say so in a ⚠️ warning and
  are followed by a reset cell.)
- **Check-cell idioms.** Every ▶ self-check cell asserts structural facts using a small,
  recurring vocabulary — `getattr(x, "type", None) or x.get("type")` (read a field from
  an SDK object *or* a plain dict), set comprehensions, and `assert A or B`. The first
  self-check in each of 00/01 has a 🟢 box unpacking these; the broader Python
  refreshers live in [BEGINNER-NOTES.md](../BEGINNER-NOTES.md).
- Each notebook ends in an assertion cell printing `All checks passed`.

## Editing rule (contributors)

Each notebook is a **jupytext pair**: a `py:percent` `.py` file (the review surface —
diffs like code) and the `.ipynb` (carries committed outputs for GitHub rendering).
**Edit the `.py`, then run `jupytext --sync <file>.py`** — never hand-edit the `.ipynb`.
To re-sync and re-execute everything (refreshing committed outputs), run
[`./refresh.sh`](./refresh.sh).

## The notebooks

| Notebook | What it runs | Phase |
|----------|--------------|-------|
| [`setup-check.ipynb`](./setup-check.ipynb) | ~5 cells: verify your kernel, imports, and one offline FakeClient round trip — you're ready. | [Phase 0 setup](../00-foundations.md) / [FAQ](../FAQ.md#setup--installation) |
| [`00-foundations.ipynb`](./00-foundations.ipynb) | The Responses-API handshake ladder, step by step, ending with the V1→V2 refactor. | [`00-foundations.md`](../00-foundations.md) |
| [`01-bare-harness.ipynb`](./01-bare-harness.ipynb) | The bare agent loop: tool-call round trips, the `Agent` remembering across cells, the iteration cap. | [`01-bare-harness.md`](../01-bare-harness.md) |
| [`02-tool-system.ipynb`](./02-tool-system.ipynb) | Schema dicts → dict registry → `Tool`/`ToolRegistry` → `@tool`, with dispatch probes you can poke. | [`02-tool-system.md`](../02-tool-system.md) |
| [`03-conversation-and-streaming.ipynb`](./03-conversation-and-streaming.ipynb) | The transcript as memory: two-turn recall, the forgetting A/B, save/load, the `Conversation` class. | [`03-conversation-and-streaming.md`](../03-conversation-and-streaming.md) |
| [`06-context-management.ipynb`](./06-context-management.ipynb) | Feel the window fill up: `count_tokens`, `prune_to_budget` (no orphaned call pairs), `compact`. | [`06-context-management.md`](../06-context-management.md) |

Phases 4, 5, 7, and 8 have no notebook on purpose — their material (real file/shell
tools, permission prompts, sub-agent orchestration, the CLI) belongs in a terminal, not
a kernel. Follow those phases' ▶ Run-it-now checkpoints directly.
