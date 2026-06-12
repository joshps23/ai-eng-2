# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Phase 8 — The Production Harness (companion notebook)
#
# [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/joshps23/ai-eng-2/blob/main/agent-harness-guide/notebooks/08-production-harness.ipynb)
#
# Companion to [08-production-harness.md](../08-production-harness.md) — with an honest
# framing: Phase 8 is about graduating **out** of notebooks. Its substance — argparse, the
# REPL, packaging, CI — belongs in a terminal, and pretending otherwise would teach the
# wrong lesson. This companion holds only the phase's three runnable demos:
# **retry-with-backoff**, the **JSONL tracer + cost accounting**, and **running the real
# test suite** against the installed package.
#
# **Conventions:** Run top-to-bottom. When confused: *Kernel → Restart & Run All*.
# Every cell below runs **WITHOUT** an API key.
#
# On Google Colab this cell installs everything automatically (private repo: add a
# `GH_TOKEN` secret — see [the README's Colab section](./README.md#running-on-google-colab)).

# %%
try:
    import agent_harness
except ModuleNotFoundError:
    import sys
    if "google.colab" not in sys.modules:
        raise SystemExit(
            "agent_harness is not installed in this kernel.\n"
            "Fix: pip install -e \"agent-harness-guide/code[dev,notebooks]\" from the repo root,\n"
            "then pick the 'Python (agent-harness)' kernel — see ../FAQ.md#setup--installation"
        )
    # Running on Google Colab: fetch the repo and install the package.
    import os, pathlib, subprocess
    REPO_URL = "https://github.com/joshps23/ai-eng-2.git"
    if not pathlib.Path("ai-eng-2").exists():
        token = None
        try:
            from google.colab import userdata
            token = userdata.get("GH_TOKEN")
        except Exception:
            pass  # no secret configured; try anonymous clone (works if the repo is public)
        url = REPO_URL if not token else REPO_URL.replace("https://", f"https://{token}@", 1)
        r = subprocess.run(["git", "clone", "-q", url], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(
                "Could not clone the repo (it is private). Add a fine-grained GitHub token with "
                "read-only Contents access for this repo as a Colab secret named GH_TOKEN "
                "(key icon in the left sidebar), enable notebook access, and re-run this cell."
            )
        if token:  # don't leave the token on disk in the git remote
            subprocess.run(["git", "-C", "ai-eng-2", "remote", "set-url", "origin", REPO_URL], check=False)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "./ai-eng-2/agent-harness-guide/code"], check=True)
    import agent_harness
import sys
print(sys.executable)
print("agent_harness:", agent_harness.__file__)

# %% tags=["parameters"]
import os

USE_REAL_API = False  # flip to True (and export OPENAI_API_KEY) to run the live cell

OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")
# This notebook's offline demos need no scripted client at all: Demo 1 hand-rolls a
# flaky client (the phase's own ▶ Run it now), and Demos 2–3 never touch a model.

# %% [markdown]
# ## Demo 1 — Retry with backoff
# ([Step 0](../08-production-harness.md#step-0--the-smallest-reliability-win-retry-with-backoff))
#
# The smallest reliability win: wrap `responses.create` in a retry loop with
# exponentially growing waits. The phase's ▶ Run it now tests it offline with a client
# that fails twice then succeeds — reproduced below with two notebook tweaks, both
# called out in the code: the phase's `FakeClient` is renamed **`FlakyClient`** (so it
# can't be confused with `agent_harness.testing.FakeClient`, which scripts *successful*
# replies), and the waits are `0.1 * 2**attempt` instead of `2**attempt` so Run-All
# takes ~2 seconds, not ~22. Each wait is also appended to a `sleeps` list so the
# checks can assert the exact backoff sequence.

# %%
import time


class FlakyClient:
    """Fails twice, then succeeds. Simulates a flaky network.

    (The phase's listing calls this class FakeClient — renamed here, see above.)
    """
    def __init__(self):
        self.responses = self
        self._call_count = 0

    def create(self, **kwargs):
        self._call_count += 1
        if self._call_count < 3:
            raise Exception(f"Simulated network error (attempt {self._call_count})")
        # Third attempt succeeds — return a minimal fake response
        class FakeResp:
            output = []
            class usage:
                input_tokens = 10
                output_tokens = 5
        return FakeResp()


def create_with_retry(client, sleeps, **kwargs):
    """Call the API; if it fails, wait a bit and try again, up to 5 times.

    Notebook tweaks vs the phase listing: waits are 0.1 * 2**attempt (was 2**attempt),
    and each wait is recorded in `sleeps` before sleeping.
    """
    for attempt in range(5):
        try:
            return client.responses.create(**kwargs)
        except Exception as exc:
            if attempt == 4:                 # that was the last attempt —
                break                        # don't sleep just to give up
            wait = 0.1 * 2 ** attempt        # 0.1s, 0.2s, 0.4s, 0.8s (phase: 1, 2, 4, 8)
            print(f"API error ({exc}); retrying in {wait:.1f}s…")
            sleeps.append(wait)
            time.sleep(wait)
    raise RuntimeError("API still failing after 5 tries")


print("FlakyClient and create_with_retry defined.")

# %% [markdown]
# **The happy path:** two failures, two sleeps, success on attempt 3 — the user never
# notices the hiccups.

# %%
flaky = FlakyClient()
sleeps = []
resp = create_with_retry(flaky, sleeps, model="gpt-4o", input=[], tools=[])
print("Success on attempt", flaky._call_count)
print("sleep sequence:", sleeps)

assert flaky._call_count == 3, "two simulated failures, then the third attempt succeeds"
assert sleeps == [0.1, 0.2], (
    "exponential backoff: each wait must DOUBLE the previous one (0.1*2**attempt)")
assert resp.usage.input_tokens == 10, "the successful response comes back intact"
print("happy-path checks passed")

# %% [markdown]
# **The give-up path** — and the detail the phase flags: the `if attempt == 4: break`
# guard means there is **no sleep after the final attempt**. Without it, the function
# would doze a pointless 1.6s before raising anyway.

# %%
class AlwaysDownClient:
    """Never recovers — every attempt raises. Simulates a real outage."""
    def __init__(self):
        self.responses = self
        self._call_count = 0

    def create(self, **kwargs):
        self._call_count += 1
        raise Exception(f"Simulated outage (attempt {self._call_count})")


down = AlwaysDownClient()
sleeps_down = []
try:
    create_with_retry(down, sleeps_down, model="gpt-4o", input=[], tools=[])
    raise AssertionError("create_with_retry should have raised RuntimeError")
except RuntimeError as exc:
    print("Gave up:", exc)
print("attempts:", down._call_count, "  sleep sequence:", sleeps_down)

assert down._call_count == 5, "all five attempts must be spent before giving up"
assert sleeps_down == [0.1, 0.2, 0.4, 0.8], "four doubling waits between the five attempts"
assert len(sleeps_down) == down._call_count - 1, (
    "NO sleep after the final attempt — the `if attempt == 4: break` guard breaks out "
    "before the sleep, so the last failure raises immediately instead of dozing first")
print("give-up-path checks passed")

# %% [markdown]
# ## Demo 2 — The JSONL tracer and cost accounting
# ([1c](../08-production-harness.md#1c--the-jsonl-tracer) /
# [1d](../08-production-harness.md#1d--cost-and-token-accounting))
#
# One JSON object per line, appended to a file — that's the whole tracer. The package's
# `Tracer` class is this `emit` function plus remembered state (the path, a session id).
# The trace lands in a fresh tmpdir created in the same cell, so re-running never
# double-appends.

# %%
import json
import tempfile
from pathlib import Path

TRACE_PATH = Path(tempfile.mkdtemp(prefix="harness-trace-")) / "trace.jsonl"


def emit(event, **data):
    """Append one JSON object per event — the V2-functions rung of tracer.py."""
    record = {"ts": round(time.time(), 3), "session": "demo-session", "event": event, **data}
    with TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# A miniature two-turn session, traced:
emit("session_start", model="gpt-4o")
emit("turn_end", turn=1, input_tokens=1200, output_tokens=350)
emit("tool_call", turn=1, name="read_file", call_id="call_1")
emit("turn_end", turn=2, input_tokens=2100, output_tokens=410)
emit("session_end", turns=2)

print(TRACE_PATH)
print(TRACE_PATH.read_text())

# %% [markdown]
# **Read it back** — `json.loads` per line — and do the 1d accounting: sum the usage
# from the `turn_end` events and price it with the phase's `gpt-4o` rates
# (USD per 1,000,000 tokens).

# %%
records = [json.loads(line) for line in TRACE_PATH.read_text().splitlines()]
turn_ends = [r for r in records if r["event"] == "turn_end"]

input_tokens = sum(r["input_tokens"] for r in turn_ends)
output_tokens = sum(r["output_tokens"] for r in turn_ends)

PRICES = {"input": 2.50, "output": 10.00}   # gpt-4o row of the phase's DEFAULT_PRICE_TABLE
cost = (input_tokens * PRICES["input"] + output_tokens * PRICES["output"]) / 1_000_000

print(f"events: {len(records)}   turns: {len(turn_ends)}")
print(f"input tokens:   {input_tokens:,}")
print(f"output tokens:  {output_tokens:,}")
print(f"estimated cost: ${cost:.6f} USD")

assert len(records) == 5, "every emit above should be exactly one parseable line"
assert [r["event"] for r in records][0] == "session_start" and records[-1]["event"] == "session_end"
assert (input_tokens, output_tokens) == (3300, 760), "the sums must match the traced usage"
assert abs(cost - 0.01585) < 1e-12, "3300*2.50/1M + 760*10.00/1M = $0.01585"
print("tracer + accounting checks passed")

# %% [markdown]
# ## Demo 3 — Run the real test suite
# ([§8](../08-production-harness.md#8-testing-the-harness))
#
# The package this whole notebook series drives is the **tested** one — prove it from
# here. First locate `code/` (the notebook executes from `notebooks/`, so the suite
# lives next door — and on Colab it lives inside the bootstrap cell's clone):

# %%
import agent_harness
from pathlib import Path

candidates = [
    Path(agent_harness.__file__).resolve().parent.parent,        # editable install → the repo's code/
    Path.cwd().parent / "code",                                  # running from notebooks/ in the repo
    Path.cwd() / "ai-eng-2" / "agent-harness-guide" / "code",    # the bootstrap cell's Colab clone
]
CODE_DIR = next((c for c in candidates if (c / "tests").is_dir()), None)
assert CODE_DIR is not None, (
    "could not find the package's tests/ directory — run this notebook from the repo "
    "(agent-harness-guide/notebooks/), or re-run the bootstrap cell on Colab")
print("test suite:", CODE_DIR / "tests")

# %% [markdown]
# Always **`python -m pytest`, never bare `pytest`** — and in a notebook, prefer
# `{sys.executable} -m pytest` to pin the *kernel's* interpreter exactly (a bare
# `pytest` on PATH can belong to a different Python that has never seen
# `agent_harness`). Fully offline: the suite scripts every model reply with the same
# `FakeClient` these notebooks use.

# %%
# !{sys.executable} -m pytest -q --rootdir={CODE_DIR} {CODE_DIR}/tests

# %% [markdown]
# **▶ Self-check** — the same invocation, captured, so the result is machine-checked
# (and so a broken suite fails Run-All loudly instead of scrolling past).

# %%
import subprocess

proc = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", f"--rootdir={CODE_DIR}", str(CODE_DIR / "tests")],
    capture_output=True, text=True,
)
summary = proc.stdout.strip().splitlines()[-1]
print(summary)

assert proc.returncode == 0, (
    "the package's suite must pass — it is the source of truth these notebooks drive:\n"
    + proc.stdout[-2000:])
assert " passed" in summary and "failed" not in summary, summary
print("pytest checks passed")

# %%
# Everything this notebook claimed, re-asserted in one place.
assert flaky._call_count == 3 and sleeps == [0.1, 0.2]            # retry: success on 3rd try
assert down._call_count == 5 and len(sleeps_down) == 4            # retry: no sleep after last
assert sleeps_down == [0.1 * 2 ** n for n in range(4)]            # retry: doubling backoff
assert len(records) == 5 and (input_tokens, output_tokens) == (3300, 760)   # tracer round-trip
assert abs(cost - 0.01585) < 1e-12                                # accounting
assert proc.returncode == 0                                       # the real suite passes
print("All checks passed")

# %% [markdown]
# **Optional — one real call through the retry wrapper** (needs `OPENAI_API_KEY`):
# the same `create_with_retry`, wrapped around a live client. On a healthy network the
# sleep sequence is simply empty — that's the point.

# %%
if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    live_sleeps = []
    live_resp = create_with_retry(
        OpenAI(), live_sleeps,
        model="gpt-4o",
        input=[{"role": "user",
                "content": "In one short sentence: what does retry-with-backoff buy a harness?"}],
        tools=[],
    )
    print(live_resp.output_text)
    print("retries needed:", len(live_sleeps))
else:
    print("(skipped — needs USE_REAL_API = True in the parameters cell AND an "
          "OPENAI_API_KEY; the offline demos above are the real lesson)")

# %% [markdown]
# ## Graduation — go to the terminal
#
# This is where the notebook hands you off. The REPL you built across the guide is not
# simulated here — it is a `while True: input()` loop by construction, and a notebook
# can't be a terminal. Run the real thing
# ([Graduation](../08-production-harness.md#graduation--run-the-real-thing)):
#
# ```bash
# cd agent-harness-guide/code
# pip install -e ".[dev]"      # one-time install (pulls openai + pytest)
# agent-harness                # the REPL — or: python -m agent_harness.cli
# python -m pytest -q          # the full suite: 56 passed, fully offline
# ```
#
# ## Key takeaways
#
# - **Retry with backoff** is the smallest reliability win: doubling waits between
#   attempts, and never a sleep after the final one.
# - **One JSON object per line** is a complete observability format: append to write,
#   `json.loads` per line to read, sum `turn_end` usage to price a session.
# - **`python -m pytest`** (here: `{sys.executable} -m pytest`) pins the interpreter
#   that has your package; the quiet `56 passed` is the whole guide in one line.
#
# Now do the phase's [Check yourself](../08-production-harness.md#check-yourself) and
# [Pitfalls](../08-production-harness.md#pitfalls), then the Phase 8 exercises in
# [EXERCISES.md](../EXERCISES.md#phase-8--the-production-harness) — and the
# [Capstone](../EXERCISES.md#capstone). Two starter cells:

# %%
# Quiz: after the FIFTH consecutive failure, how long does create_with_retry sleep
# before raising RuntimeError?
answer = "it doesn't sleep"   # <- edit me, then run

assert ("doesn't" in answer.lower() or "does not" in answer.lower()
        or answer.strip().rstrip("s") in {"0", "zero"}), (
    "Hint: re-read the `if attempt == 4: break` guard — what would sleeping buy "
    "when there is no attempt left to wait for?")
print("Correct — the guard breaks out before the sleep; the last failure raises immediately.")

# %%
# Exercise (the phase's §5 hardens Step 0 the same way): add JITTER to the backoff —
# wait = 0.1 * 2**attempt * random.uniform(0.5, 1.5) — so a fleet of clients hitting
# the same outage doesn't retry in lock-step. Copy create_with_retry here, add the
# jitter, and re-run the AlwaysDownClient experiment: the sleep COUNT must still be 4,
# but the values now vary run to run.
# your code here

# jitter_sleeps = []
# ...
# assert len(jitter_sleeps) == 4
# assert all(0.05 * 2**n <= s <= 0.15 * 2**n for n, s in enumerate(jitter_sleeps))
print("(exercise scaffold — fill in the code above)")
