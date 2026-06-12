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
# # Phase 3 — Conversation State (companion notebook)
#
# [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/joshps23/ai-eng-2/blob/main/agent-harness-guide/notebooks/03-conversation-and-streaming.ipynb)
#
# Runnable companion to [Phase 3 — Conversation State & Streaming](../03-conversation-and-streaming.md):
# the transcript is just a list, and that list — not the model — is the memory.
#
# **Conventions:** run top-to-bottom. When confused: *Kernel → Restart & Run All*.
# Every cell below runs **without** an API key.
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
import json

from agent_harness.testing import FakeClient, fake_message

USE_REAL_API = False  # flip to True (with OPENAI_API_KEY set) to talk to the real API
MODEL = "gpt-4o"
SESSION_PATH = "/tmp/agent_harness_nb03_session.json"
CLASS_SESSION_PATH = "/tmp/agent_harness_nb03_class_session.json"


def make_client(turns):
    """Real OpenAI() if opted in and a key exists; otherwise a scripted FakeClient."""
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)


OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")

# %% [markdown]
# ## Version 1 — two turns, fully inline
#
# [Step 1.1](../03-conversation-and-streaming.md#step-11--two-turns-fully-inline): a plain
# list that grows each turn and gets re-sent as `input=`.
#
# ⚠️ **Deliberate shared state ahead.** The next three cells share `client` and
# `input_items` on purpose — that persistence *is* the lesson. If anything desyncs
# (e.g. you re-ran a turn cell), re-run from this setup cell.

# %%
client = make_client([
    [fake_message("Got it! I'll remember your name is Alex.")],
    [fake_message("Your name is Alex.")],
])

# The entire conversation is a plain list of dicts.
# We will append to it and pass it as input= on every call.
input_items = []
print("fresh transcript:", input_items)

# %%
# --- Turn 1: ask the model something ---
input_items.append({"role": "user", "content": "My name is Alex. Remember that."})

resp = client.responses.create(
    model=MODEL,
    input=input_items,
)

# Append the model's output items so it "remembers" this turn.
for item in resp.output:
    input_items.append(item.model_dump())  # SDK object -> plain dict

print("Turn 1:", resp.output_text)

# %%
# --- Turn 2: ask a follow-up that requires memory ---
input_items.append({"role": "user", "content": "What is my name?"})

resp2 = client.responses.create(
    model=MODEL,
    input=input_items,
)

for item in resp2.output:
    input_items.append(item.model_dump())

print("Turn 2:", resp2.output_text)
print(f"\nTranscript now has {len(input_items)} items.")

# %% [markdown]
# ▶ Self-check: the turn-1 exchange is still sitting in `input_items` when turn 2 runs.
# That list *is* the memory — the kernel held it across the two cells above.

# %%
assert len(input_items) == 4, (
    f"expected 4 items, got {len(input_items)} — "
    "if you re-ran a turn cell, re-run from the setup cell above"
)
assert input_items[0] == {"role": "user", "content": "My name is Alex. Remember that."}
assert input_items[1]["type"] == "message" and input_items[1]["role"] == "assistant"
assert input_items[2] == {"role": "user", "content": "What is my name?"}
assert "Alex" in resp2.output_text
print("V1 checks passed — the list IS the memory")

# %%
# Reset the deliberate shared state from the demo above.
# Every cell below rebuilds its own state at its own top.
input_items = []
client = None
print("state cleared")

# %% [markdown]
# ### The forgetting A/B
#
# The phase's experiment ([end of Step 1.2](../03-conversation-and-streaming.md#step-12--a-chat-repl-the-same-two-turn-script-in-a-while-loop)):
# *move `input_items = []` into the loop body and watch it forget.* The fake's replies are
# scripted, so watch what each call **sends** instead — the model can only remember what
# you send it.

# %%
QUESTIONS = ["My name is Alex. Remember that.", "What is my name?"]

# A — the list is created ONCE, before the loop (memory)
client = make_client([[fake_message("Got it!")], [fake_message("Your name is Alex.")]])
input_items = []
sent_sizes_a = []
for user_text in QUESTIONS:
    input_items.append({"role": "user", "content": user_text})
    sent_sizes_a.append(len(input_items))
    resp = client.responses.create(model=MODEL, input=input_items)
    for item in resp.output:
        input_items.append(item.model_dump())

# B — the list is recreated EVERY turn (the forgetting bug)
client = make_client([[fake_message("Got it!")], [fake_message("I don't know your name.")]])
sent_sizes_b = []
for user_text in QUESTIONS:
    forgetful_items = []                       # <- recreated inside the loop: the bug
    forgetful_items.append({"role": "user", "content": user_text})
    sent_sizes_b.append(len(forgetful_items))
    resp = client.responses.create(model=MODEL, input=forgetful_items)
    for item in resp.output:
        forgetful_items.append(item.model_dump())

print("items sent per call, with memory:  ", sent_sizes_a)
print("items sent per call, with the bug: ", sent_sizes_b)

# %% [markdown]
# ▶ Self-check: with memory, the turn-2 call carries the whole turn-1 exchange (3 items);
# with the bug it carries only the new question — "Alex" never reaches the model. Against
# the real API, version B answers *"I don't know your name."*

# %%
assert sent_sizes_a == [1, 3], "turn 2 should re-send the turn-1 exchange plus the new question"
assert sent_sizes_b == [1, 1], "the bug: turn 2 sends only itself — the name is gone"
print("A/B checks passed")

# %% [markdown]
# ### The same bug, notebook edition (run-it-twice)
#
# A cell that appends to a list defined in an *earlier* cell double-appends when you re-run
# it — the kernel kept the list alive, exactly like the harness keeps the transcript alive
# between API calls. Same mechanism: there, it's the feature; here, it's the trap.
# Below we simulate pressing Shift+Enter twice with a loop, so Run-All shows the damage.

# %%
input_items = []   # pretend this line lives in an EARLIER cell, run once

# a learner's turn cell that does NOT rebuild its own state — "re-run" twice:
for press in (1, 2):
    input_items.append({"role": "user", "content": "My name is Alex. Remember that."})

print(json.dumps(input_items, indent=2))
print("user messages in the transcript:", len(input_items), "<- double-append!")

# %% [markdown]
# The fix is this notebook series' rule C1 (see the conventions in this folder's
# [README](./README.md#series-conventions)): **the cell that appends also creates the
# list.** (Try it for real: copy the append into its own cell and run it twice — then fix
# it the same way.)

# %%
for press in (1, 2):
    # the fix: rebuild the state in the SAME cell that mutates it
    input_items = [{"role": "user", "content": "My name is Alex. Remember that."}]

assert len(input_items) == 1, "rebuilding in-cell makes re-runs idempotent"
print("fixed — re-running this cell can never double-append")
print("(the harness re-sending the transcript = the kernel remembering your list: same idea)")

# %% [markdown]
# ## Version 2 — helpers, then save/load
#
# [Step 2.1](../03-conversation-and-streaming.md#step-21--add-small-helper-functions)
# names the moves; the conversation becomes one plain dict, so
# [Step 2.2](../03-conversation-and-streaming.md#step-22--save-and-load-the-transcript)'s
# persistence is a one-line `json.dump`.

# %%
import json


def new_conversation(instructions=""):
    """Create a fresh conversation dict."""
    return {"instructions": instructions, "items": []}


def add_user(conv, text):
    """Append a user turn."""
    conv["items"].append({"role": "user", "content": text})


def extend_items(conv, output_items):
    """Append all items from resp.output, converting SDK objects to dicts."""
    for item in output_items:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        conv["items"].append(dict(item))


def add_tool_result(conv, call_id, output):
    """Append a function_call_output item."""
    conv["items"].append({
        "type": "function_call_output",
        "call_id": call_id,
        "output": output,
    })


def to_input(conv):
    """Return the items list ready to pass as input=."""
    return list(conv["items"])


def save(conv, path):
    """Write the conversation to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(conv, f, indent=2, ensure_ascii=False)


def load(path):
    """Read a conversation back from a JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


print("helpers ready")

# %%
# --- Session A: first turn, then save ---
client = make_client([[fake_message("Got it! I'll remember your name is Alex.")]])

conv = new_conversation(instructions="You are a helpful assistant.")
add_user(conv, "My name is Alex. Remember that.")
resp = client.responses.create(
    model=MODEL,
    instructions=conv["instructions"],
    input=to_input(conv),
)
extend_items(conv, resp.output)
save(conv, SESSION_PATH)
print("Saved session to", SESSION_PATH)
print("Turn 1:", resp.output_text)

# %% [markdown]
# ### Restart the "process" for real
#
# In the phase, the proof is restarting the Python process. The notebook equivalent:
# **Kernel → Restart** (the kernel forgets *everything*), then run only the first two code
# cells, the helpers cell, and the load cell below — **skipping Session A**. The
# conversation comes back from disk anyway. Also open the JSON file: the full transcript
# is right there in plain text.

# %%
# --- Session B: simulate (or actually perform) a restart by loading from disk ---
conv2 = load(SESSION_PATH)
print(f"Loaded {len(conv2['items'])} items from disk")

add_user(conv2, "What is my name?")
client = make_client([[fake_message("Your name is Alex.")]])
resp2 = client.responses.create(
    model=MODEL,
    instructions=conv2["instructions"],
    input=to_input(conv2),
)
extend_items(conv2, resp2.output)
print("Loaded session. Turn 2:", resp2.output_text)

# %% [markdown]
# ▶ Self-check: the transcript survived the disk round-trip intact — turn 2 was answered
# from a conversation the current objects never saw being created.

# %%
assert os.path.exists(SESSION_PATH)
on_disk = json.load(open(SESSION_PATH, encoding="utf-8"))
assert set(on_disk) == {"instructions", "items"}
assert on_disk["items"][0] == {"role": "user", "content": "My name is Alex. Remember that."}
assert conv2["items"][0]["content"] == "My name is Alex. Remember that."
assert len(conv2["items"]) == 4   # user, assistant, user, assistant
print("save/load checks passed")

# %% [markdown]
# ## Version 3 — the `Conversation` class
#
# [Step 3.1](../03-conversation-and-streaming.md#step-31--the-conversation-class): the dict
# plus its seven loose functions become one class — same logic, organized. This is the
# shape the package's `conversation.py` uses.

# %%
import pathlib
from typing import Any


class Conversation:
    """
    Owns the input_items list for a single conversation thread.

    All methods that accept output items accept either SDK objects
    (anything with .model_dump()) or plain dicts.
    """

    def __init__(self, instructions: str = ""):
        self._items: list[dict] = []
        self.instructions = instructions

    # ------------------------------------------------------------------
    # Building the transcript
    # ------------------------------------------------------------------

    def add_user(self, text: str) -> None:
        """Append a user message."""
        self._items.append({"role": "user", "content": text})

    def extend(self, output_items) -> None:
        """
        Append all items from resp.output (or any iterable of items).
        Normalizes SDK objects to dicts automatically.
        """
        for item in output_items:
            d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            self._items.append(d)

    def add_tool_result(self, call_id: str, output: str) -> None:
        """Append a function_call_output item."""
        self._items.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        })

    # ------------------------------------------------------------------
    # Sending to the API
    # ------------------------------------------------------------------

    def to_input(self) -> list[dict]:
        """Return the items list ready to pass as input=."""
        return list(self._items)  # shallow copy; items are dicts

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | pathlib.Path) -> None:
        """Serialize the full transcript to a JSON file."""
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(
                {"instructions": self.instructions, "items": self._items},
                f,
                indent=2,
                ensure_ascii=False,
            )

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Conversation":
        """Reconstruct a Conversation from a saved JSON file."""
        path = pathlib.Path(path)
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        conv = cls(instructions=data.get("instructions", ""))
        conv._items = data["items"]
        return conv

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def last_assistant_text(self) -> str:
        """Return the concatenated text from the last assistant message."""
        for item in reversed(self._items):
            if item.get("type") == "message" and item.get("role") == "assistant":
                parts = item.get("content", [])
                return "".join(
                    p.get("text", "") for p in parts if p.get("type") == "output_text"
                )
        return ""


print("Conversation class defined")

# %% [markdown]
# The same two-turn chat, now reading as `conv.add_user(...)` / `conv.extend(...)` —
# `self` inside a method is exactly the `conv` argument the V2 functions took.

# %%
client = make_client([
    [fake_message("Nice to meet you, Alex!")],
    [fake_message("Your name is Alex.")],
])
conv = Conversation(instructions="You are a helpful assistant.")

conv.add_user("My name is Alex. Remember that.")
resp = client.responses.create(
    model=MODEL,
    instructions=conv.instructions,
    input=conv.to_input(),
)
conv.extend(resp.output)
print("Turn 1:", resp.output_text)

conv.add_user("What is my name?")
resp2 = client.responses.create(
    model=MODEL,
    instructions=conv.instructions,
    input=conv.to_input(),
)
conv.extend(resp2.output)
conv.save(CLASS_SESSION_PATH)

print("Turn 2:", resp2.output_text)
print(f"len(conv) = {len(conv)}; saved to {CLASS_SESSION_PATH}")

# %% [markdown]
# ▶ Final self-check: identical behavior to Versions 1–2, plus the class's conveniences
# (`len(conv)`, `last_assistant_text()`, `Conversation.load`).

# %%
assert len(conv) == 4
assert conv.last_assistant_text() == "Your name is Alex."

restored = Conversation.load(CLASS_SESSION_PATH)
assert restored.instructions == "You are a helpful assistant."
assert len(restored) == len(conv)
assert restored.to_input() == conv.to_input()   # the disk round-trip is lossless

print("All checks passed")

# %% [markdown]
# ## Streaming (Version 4) — read it in the phase, not here
#
# Streaming is a terminal-UI concern: live deltas, ANSI colors, `stream=True` events —
# none of which a saved notebook (or the offline `FakeClient`) can show faithfully. It
# changes how text is *displayed*, never how the loop works. Read
# [Version 4 — Streaming](../03-conversation-and-streaming.md#version-4--streaming-the-same-harness-live-optional)
# in the phase.

# %%
if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    real = OpenAI()
    conv_live = Conversation(instructions="You are a helpful assistant.")
    conv_live.add_user("My name is Alex. Remember that.")
    r1 = real.responses.create(model=MODEL, instructions=conv_live.instructions,
                               input=conv_live.to_input())
    conv_live.extend(r1.output)
    conv_live.add_user("What is my name?")
    r2 = real.responses.create(model=MODEL, instructions=conv_live.instructions,
                               input=conv_live.to_input())
    print("Turn 2 (real model):", r2.output_text)
else:
    print("(skipped — needs USE_REAL_API = True in the parameters cell AND an "
          "OPENAI_API_KEY; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - The model is stateless; **the list is the memory** — re-send it and the model "remembers".
# - Own the transcript and persistence is one `json.dump`; a kernel restart proves it.
# - The kernel remembering your list between cells is the *same mechanism* — feature in the
#   harness, trap in a notebook. State-owning cells rebuild their own state.
#
# More: the phase's [Check yourself](../03-conversation-and-streaming.md#check-yourself) and
# [EXERCISES.md — Phase 3](../EXERCISES.md#phase-3--conversation--streaming).

# %%
# Exercise 3.1 (warm-up): have a short multi-turn chat (scripted is fine), save it,
# reload it into a NEW Conversation, and continue for one more turn. Uncomment and complete:
#
# ex_client = make_client([
#     [fake_message("Hello!")],
#     [fake_message("You asked about notebooks.")],
# ])
# ex_conv = Conversation(instructions="You are a helpful assistant.")
# # your code here: turn 1 -> save -> Conversation.load -> turn 2
#
# assert len(ex_conv) >= 4
# print("exercise 3.1 passed")
print("your turn — uncomment the scaffold above and complete it")
