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
# # Setup check — is your environment ready for the notebooks?
#
# [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/joshps23/ai-eng-2/blob/main/agent-harness-guide/notebooks/setup-check.ipynb)
#
# Companion to the [guide index](../README.md). Run this once before
# [00-foundations.ipynb](./00-foundations.ipynb).
#
# **Conventions for every notebook in this series:** Run top-to-bottom. When confused:
# *Kernel → Restart & Run All*. Every cell below runs **WITHOUT** an API key.
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
print("Python kernel :", sys.executable)
print("agent_harness :", agent_harness.__file__)

# %% [markdown]
# If the import above fails, your Jupyter kernel is not the environment where you ran
# `pip install -e ".[dev,notebooks]"` (from `agent-harness-guide/code/`) — the notebook
# analog of the guide's "always `python -m pytest`" rule. See the
# [FAQ — Setup & installation](../FAQ.md#setup--installation) for the fix.

# %%
import openai
print("openai SDK    :", openai.__version__)

# %% tags=["parameters"]
import os
from agent_harness.testing import FakeClient, fake_message

USE_REAL_API = False  # flip to True (with OPENAI_API_KEY set) to talk to the real API

def make_client(turns):
    """Real OpenAI() if opted in and a key is present, else a scripted FakeClient."""
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)

print("Mode:", "REAL API" if (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
      else "OFFLINE (FakeClient — no key needed)")

# %% [markdown]
# One scripted round trip — the exact `responses.create(...)` call every phase uses,
# answered offline by the package's `FakeClient` (see the "No API key?" box in
# [Phase 0 §0.3.2](../00-foundations.md#032-step-1--the-simplest-possible-call-text-in-text-out)).

# %%
client = make_client([[fake_message("pong")]])   # client built in the same cell → re-run safe
resp = client.responses.create(model="gpt-4o", input=[{"role": "user", "content": "ping"}])
print("Assistant:", resp.output_text)

# %%
assert resp.output, "the response should carry output items"
assert resp.output[0].type == "message", "the single scripted turn is a message item"
if not (USE_REAL_API and os.environ.get("OPENAI_API_KEY")):
    assert resp.output_text == "pong", "FakeClient should return exactly the scripted reply"
print("All checks passed")
print("You're ready — open 00-foundations.ipynb next.")
