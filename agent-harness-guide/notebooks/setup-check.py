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
# Companion to the [guide index](../README.md). Run this once before
# [00-foundations.ipynb](./00-foundations.ipynb).
#
# **Conventions for every notebook in this series:** Run top-to-bottom. When confused:
# *Kernel → Restart & Run All*. Every cell below runs **WITHOUT** an API key.

# %%
import sys
import agent_harness
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
