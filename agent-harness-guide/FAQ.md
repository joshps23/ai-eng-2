# Beginner FAQ & Troubleshooting

> Stuck on a setup error, a confusing traceback, or "why did the agent do nothing"?
> Find your symptom below. For term definitions see the
> **[Glossary](./GLOSSARY.md)**; for the recommended order to learn in, see the
> **[Learning Path](./LEARNING-PATH.md)**.

---

## Setup & installation

This is the canonical setup recipe — other pages link here instead of repeating it.
From the **repo root**:

```bash
cd agent-harness-guide/code
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest -q          # expect: all tests pass, offline, no API key needed
```

Python 3.10+; the only required dependency is `openai>=1.66.0`. If any step
misbehaves, find your symptom below.

**Q: `ModuleNotFoundError: No module named 'agent_harness'` when I run the tests.**
Almost always an interpreter mismatch: a globally-installed `pytest` belongs to a
different Python than the one you `pip install`ed into. Two fixes, use both:
1. Work inside a virtual environment: `python -m venv .venv && source .venv/bin/activate`
   (Windows: `.venv\Scripts\activate`), then `pip install -e ".[dev]"`.
2. Run tests as **`python -m pytest`** (from `agent-harness-guide/code`), never bare
   `pytest`. The `python -m` form guarantees the same interpreter you installed into.

**Q: `pip install -e ".[dev]"` fails or can't reach the network.**
You need network access once to download `openai` and `pytest`. Behind a proxy, set
`HTTP_PROXY`/`HTTPS_PROXY`. If you already have the deps, `pip install -e . --no-deps`
installs just the package. The package itself is pure Python — no compiler needed.

**Q: `agent-harness: command not found`.**
The console script is created by `pip install -e ".[dev]"`. Make sure your virtual
environment is **active** (you should see `(.venv)` in your prompt), or just run the
module directly: `python -m agent_harness.cli`.

**Q: Which Python version do I need?**
3.10 or newer (`python --version` to check). The guide uses 3.10+ syntax such as
`X | Y` type unions.

**Q: How do I set up the companion notebooks?**
The optional [Jupyter notebooks](./notebooks/README.md) (every phase 0–8, plus a
setup check) need one extras group and one kernel registration on top of the canonical
setup above:

```bash
cd agent-harness-guide/code
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,notebooks]"
python -m ipykernel install --user --name agent-harness --display-name "Python (agent-harness)"
jupyter lab ../notebooks/
```

The `ipykernel install` line registers your venv as a named kernel so notebooks can
import `agent_harness` (see the next question for the failure mode it prevents).
JupyterLab is the documented default; VS Code's notebook UI works identically — it
discovers the same kernelspec. The notebooks run **fully offline by default** (a
`FakeClient` stands in for the API); see [`notebooks/README.md`](./notebooks/README.md)
for the `USE_REAL_API` switch and conventions.

**Q: My notebook can't import `agent_harness` (`ModuleNotFoundError` inside Jupyter).**
The kernel running your notebook isn't the venv you `pip install`ed into. This is the
notebook analog of the `python -m pytest` vs bare `pytest` rule above: a system-wide
Jupyter launches a system-wide Python, where `agent_harness` was never installed — even
though imports work fine in your terminal. Two fixes, use both:
1. Register the venv as a kernel (with the venv active, from `agent-harness-guide/code`):
   `python -m ipykernel install --user --name agent-harness --display-name "Python (agent-harness)"`.
2. In the notebook, pick **Kernel → Change Kernel → Python (agent-harness)**, then
   re-run. The notebooks' first cell prints `sys.executable` so you can confirm it
   points into your `.venv`.

**Q: Can I run the notebooks on Google Colab?**
**Yes.** Each notebook has an **"Open in Colab" badge** at the top, and its first code
cell bootstraps itself on Colab: it clones the repo and `pip install`s `agent_harness`
automatically (locally, where the package is already installed, that cell does nothing
extra). Because the repo is private, you need a one-time **`GH_TOKEN`** Colab secret — a
fine-grained GitHub token with read-only Contents access. Full steps (token setup, the
optional `OPENAI_API_KEY` secret for real-API mode, and Colab caveats) are in
[`notebooks/README.md` — Running on Google Colab](./notebooks/README.md#running-on-google-colab).

**Q: Do I need an API key just to learn?**
**No.** The entire guide is readable offline and the full test suite passes with **no
key and no network** — a `FakeClient` (see `code/agent_harness/testing.py`) stands in
for the real API. You only need a key to actually *chat* with the agent. One honest
caveat: the phases' "▶ Run it now" scripts *do* call the real API, so without a key
they stop at `openai.OpenAIError: Missing credentials` (see below). That's expected —
the "No API key?" box in Phase 0 gives the keyless alternatives: verify each
checkpoint against its printed expected output, and run the offline test suite.

---

## API keys, models & cost

**Q: How does the harness find my API key?**
It calls `OpenAI()` with no arguments, which reads the **`OPENAI_API_KEY`**
environment variable. Set it before running:
```bash
export OPENAI_API_KEY="sk-..."        # Windows (PowerShell): $env:OPENAI_API_KEY="sk-..."
```

**Q: `openai.OpenAIError: Missing credentials` (and the traceback points at `client = OpenAI()`).**
This is the error you get when **no key is set at all**. `OpenAI()` looks for
`OPENAI_API_KEY` the moment the client is constructed and raises right there — *before*
any request is sent, which is why the traceback points at the `client = OpenAI()` line
rather than at `responses.create`. Fix: `export OPENAI_API_KEY="sk-..."` in the same
terminal, then re-run. (No key and just want to learn? See the previous section — the
guide and its tests work offline; the phases' "▶ Run it now" boxes explain the keyless
alternatives.)

**Q: `openai.AuthenticationError` / 401.**
The key is **set but wrong** — mistyped or revoked. (A completely missing key fails
earlier and differently; see the previous question.) Re-check `echo $OPENAI_API_KEY`,
regenerate it in your OpenAI dashboard if unsure, and confirm your account has billing
set up.

**Q: Which model does it use, and how do I change it?**
The default is **`gpt-4o`** (`MODEL_DEFAULT` in `code/agent_harness/config.py`). Override
per run with `--model`, e.g. `agent-harness --model gpt-4o-mini`. Reasoning-capable
models give the best agentic (tool-using) behavior; smaller models are cheaper and
faster and still work. Use whatever Responses-API model your account can access.

**Q: `model_not_found` / 404 on the model.**
Your account doesn't have access to that model name, or it's misspelled. Try a model
you know you can use (e.g. `--model gpt-4o-mini`).

**Q: `RateLimitError` / 429.**
You've hit a per-minute request or token cap (or run out of quota). Wait and retry;
Phase 8 adds automatic retry-with-backoff for exactly this. If it's a quota problem,
check billing.

**Q: How do I avoid surprise costs while experimenting?**
Use a smaller model (`--model gpt-4o-mini`), keep `--max-iterations` low, and point
the agent at a tiny scratch directory so tool output stays short. Tokens ≈ cost — the
shorter the transcript, the cheaper the run.

---

## Running the agent

**Q: The agent answered in plain text but never used a tool I expected.**
The model *chooses* whether to call a tool. If it didn't, usually (a) the tool's
`description`/schema doesn't make its purpose obvious, (b) the task didn't actually
need it, or (c) your system prompt didn't point at it. Sharpen the tool description
(Phase 2/4) — the schema is how the model "sees" the tool.

**Q: It loops forever / hits the iteration cap.**
There's a safety limit (`max_iterations`, default 50, settable with
`--max-iterations`). Hitting it usually means the model is stuck retrying a failing
tool. Read the tool results in the transcript — a tool that keeps erroring will make
the model keep trying. Fix the tool or tighten its error message so the model can
recover.

**Q: A tool raised an exception and the whole program crashed.**
Tool functions should return an error *string* rather than raise, so the model can
see what went wrong and adapt. See how the real tools wrap risky work in
`try`/`except` (Phase 4) and the permission/hook layer (Phase 5).

**Q: How do I resume a previous conversation?**
Use `--resume` (see the CLI flags in Phase 8 / `cli.py`). Conversations can be saved
and reloaded — that's the transcript-as-state idea from Phase 3.

**Q: How do I stop it from doing something dangerous (e.g. `rm -rf`)?**
That's the permission layer (Phase 5). Run with a stricter `--mode` so risky tools
require approval, and keep the agent's `--workspace` pointed at a sandbox directory.

---

## Reading tracebacks (a 20-second skill)

Python prints the **call stack oldest-first**, so the *last* line is what actually
went wrong — read a traceback **bottom-up**:
- `ModuleNotFoundError` → something isn't installed in *this* interpreter (see setup).
- `KeyError` / `AttributeError` → you read a field that wasn't there; print the object.
- `json.JSONDecodeError` → you tried to `json.loads` something that isn't valid JSON
  (often empty tool arguments — guard with `args or "{}"`).
- `openai.*Error` → the API rejected the request; the message says why (auth, model,
  rate limit).

---

## Platform notes

- **Windows:** activate the venv with `.venv\Scripts\activate`; set env vars with
  `$env:OPENAI_API_KEY="..."` (PowerShell). The `bash` tool (Phase 4) assumes a
  Unix-style shell — run under WSL or Git Bash if you want it to behave like the guide.
- **macOS / Linux:** the commands in the guide work as written.

---

> Spotted a gap or an error? Open an issue on the repo.
