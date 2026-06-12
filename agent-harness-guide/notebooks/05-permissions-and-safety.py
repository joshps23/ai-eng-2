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
# # Phase 5 — Permissions, Safety & Hooks (companion notebook)
#
# [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/joshps23/ai-eng-2/blob/main/agent-harness-guide/notebooks/05-permissions-and-safety.ipynb)
#
# Companion to [05-permissions-and-safety.md](../05-permissions-and-safety.md): the
# permission gate as a function you can call and *stare at* — risk tiers × modes, a
# scripted asker standing in for `input()`, session memory as visible state (and why
# hard denials beat it), and a sandboxed subprocess with an env allowlist.
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
from agent_harness.testing import FakeClient, fake_function_call, fake_message

USE_REAL_API = False  # flip to True (with OPENAI_API_KEY set) to talk to the real API
MODEL = "gpt-4o"

def make_client(turns):
    """Real OpenAI() if opted in and a key is present, else a scripted FakeClient.

    Only the *model* is faked — your tools, the gate, and the transcript all
    run for real either way.
    """
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)

OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")

# %% [markdown]
# ## 1. The gate as a function
# ([Step 2.1](../05-permissions-and-safety.md#step-21--the-gate-as-a-function))
#
# The phase's own pitch: *"you can now test the decision in isolation, without an API
# call or a real shell"* — which makes this the most notebook-shaped code in the guide.
# `TOOL_RISK` + `check_permission`, verbatim, then call it and stare at the answers.

# %%
# How risky is each tool?
TOOL_RISK = {
    "read_file": "safe", "glob": "safe", "grep": "safe", "list_dir": "safe",
    "write_file": "caution", "edit_file": "caution",
    "bash": "dangerous",
}

def check_permission(tool_name, arg):
    """Return 'allow', 'deny', or 'ask'."""
    # Always block a few obviously destructive commands.
    if tool_name == "bash":
        for bad in ["rm -rf", "sudo ", ":(){"]:
            if bad in arg:
                return "deny"
    # Safe tools always pass.
    risk = TOOL_RISK.get(tool_name, "dangerous")
    if risk == "safe":
        return "allow"
    # Everything else: ask the user.
    return "ask"


print(check_permission("read_file", "hello.txt"))    # safe        -> allow
print(check_permission("write_file", "out.txt"))     # caution     -> ask
print(check_permission("bash", "ls"))                # dangerous   -> ask
print(check_permission("bash", "rm -rf /"))          # blocked     -> deny
print(check_permission("frobnicate", ""))            # unknown     -> treated as dangerous

assert check_permission("read_file", "hello.txt") == "allow", "safe tools must pass silently"
assert check_permission("write_file", "out.txt") == "ask", "caution tools must ask"
assert check_permission("bash", "rm -rf /") == "deny", (
    "blocked patterns are denied before anyone is even asked"
)
assert check_permission("frobnicate", "") == "ask", (
    "unknown tools default to 'dangerous' — fail closed, not open"
)
print("Step 2.1 checks passed")

# %% [markdown]
# ## 2. Modes: what is auto-allowed
# ([Step 2.2](../05-permissions-and-safety.md#step-22--add-permission-modes-one-new-idea-a-mode-controls-whats-auto-allowed))
#
# A mode is just a string controlling which risk levels pass without asking. Verbatim
# from the phase — `check_permission` is redefined with a `mode` parameter (the same
# grow-in-place refactor the phase performs).

# %%
# For each mode, which risk levels pass without asking?
AUTO_OK = {
    "plan":  ["safe"],                          # read-only; never mutate
    "auto":  ["safe", "caution"],               # approve file writes, ask before bash
    "yolo":  ["safe", "caution", "dangerous"],  # approve everything (careful!)
}

def check_permission(tool_name, arg, mode="auto"):
    """Return 'allow', 'deny', or 'ask'."""
    # Hard-block destructive patterns regardless of mode.
    if tool_name == "bash":
        for bad in ["rm -rf", "sudo ", ":(){"]:
            if bad in arg:
                return "deny"
    # Auto-approve if this tool's risk fits the mode.
    risk = TOOL_RISK.get(tool_name, "dangerous")
    if risk in AUTO_OK.get(mode, []):
        return "allow"
    # In plan mode, mutations are a hard deny (not just "ask").
    if mode == "plan" and risk in ["caution", "dangerous"]:
        return "deny"
    # Otherwise ask.
    return "ask"

print("modes defined:", list(AUTO_OK))

# %% [markdown]
# **▶ The whole decision table at a glance** — safe/caution/dangerous × plan/auto/yolo,
# plus the blocked pattern that no mode can rescue.

# %%
probes = [
    ("read_file",  "hello.txt"),   # safe
    ("write_file", "out.txt"),     # caution
    ("bash",       "ls"),          # dangerous
    ("bash",       "rm -rf /"),    # blocked pattern
]

print(f"{'tool':<11} {'arg':<10} | {'plan':<6} {'auto':<6} {'yolo':<6}")
print("-" * 45)
for tool_name, arg in probes:
    row = [check_permission(tool_name, arg, mode=m) for m in ("plan", "auto", "yolo")]
    print(f"{tool_name:<11} {arg:<10} | {row[0]:<6} {row[1]:<6} {row[2]:<6}")

assert check_permission("read_file", "hello.txt", mode="plan") == "allow", "plan still reads"
assert check_permission("write_file", "out.txt", mode="plan") == "deny", (
    "plan mode HARD-denies mutations — the user asked for a read-only run"
)
assert check_permission("write_file", "out.txt", mode="auto") == "allow", "auto approves writes"
assert check_permission("bash", "ls", mode="auto") == "ask", "auto still asks before bash"
assert check_permission("bash", "ls", mode="yolo") == "allow", "yolo approves everything…"
assert all(check_permission("bash", "rm -rf /", mode=m) == "deny"
           for m in ("plan", "auto", "yolo")), (
    "…except blocked patterns, which are denied in EVERY mode, yolo included"
)
print("mode-grid checks passed")

# %% [markdown]
# ## 3. The asker — scripted, because notebooks have no stdin
#
# The phase's `ask_user` is an `input()` loop. **That cannot run here**: under headless
# notebook execution `input()` raises `IPython.core.error.StdinNotImplementedError` — a
# `RuntimeError` subclass, so even the phase's
# [`except (EOFError, KeyboardInterrupt)` guard](../05-permissions-and-safety.md#step-34--the-approval-gate-production-shape)
# does **not** catch it; the cell simply errors. This is structural, not stylistic:
# a notebook cell can't block on a terminal prompt.
#
# > 🟢 **The substitution.** The gate takes `ask` as a *parameter*, and we hand it a
# > closure that pops pre-scripted answers and prints both question and answer — so the
# > saved notebook reads like the phase's terminal session, and you can edit the answer
# > list (`["y", "n"]` → `["n", "n"]`) and re-run to explore. In the terminal version
# > this is `input()`; everything else is identical.

# %%
def make_scripted_asker(answers):
    """A stand-in for the phase's ask_user: pops scripted answers instead of blocking on stdin."""
    answers = list(answers)   # private copy; each asker is its own script
    def ask(tool_name):
        if not answers:
            print(f"Allow {tool_name}? [y/n] > (script exhausted — defaulting to deny)")
            return "deny"
        answer = answers.pop(0)
        print(f"Allow {tool_name}? [y/n] > {answer}   (scripted)")
        return "allow" if answer == "y" else "deny"
    return ask


demo_ask = make_scripted_asker(["y", "n"])
assert demo_ask("bash") == "allow" and demo_ask("bash") == "deny" and demo_ask("bash") == "deny", (
    "the asker should answer y, then n, then default to deny once the script runs out"
)
print("scripted asker works")

# %% [markdown]
# ## 4. The gated loop, end to end (offline)
#
# Now wire the gate into the V2 harness
# ([the four-line block](../05-permissions-and-safety.md#step-21--the-gate-as-a-function)
# between "the model asked" and "the OS acted"). Tools first — the phase's
# [`agent_v2.py`](../05-permissions-and-safety.md#version-2--functions-a-check_permission-you-can-call-and-test)
# bodies, with one adaptation the phase itself demands (its WARNING says *run V1–V3 only
# in a scratch folder*): paths and `bash`'s cwd are rooted in a throwaway tmpdir, exactly
# as in [notebook 04](./04-real-tools.ipynb).

# %%
import json, pathlib, subprocess, tempfile

WS = pathlib.Path(tempfile.mkdtemp(prefix="phase5-ws-")).resolve()
(WS / "hello.txt").write_text("Hello from Phase 5\n")
print("scratch workspace:", WS)

def read_file(path: str) -> str:
    try:
        with open(WS / path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as exc:
        return f"Error: cannot read file: {exc}"

def write_file(path: str, content: str) -> str:
    try:
        with open(WS / path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} characters to {path}."
    except OSError as exc:
        return f"Error: cannot write file: {exc}"

def bash(command: str) -> str:
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30, cwd=WS,
        )
        return (proc.stdout + proc.stderr) or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30s."

TOOLS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a text file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Write content to a file, overwriting it.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "type": "function",
        "name": "bash",
        "description": "Run a shell command and return its combined stdout/stderr.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]

def dispatch(name: str, args: dict) -> str:
    if name == "read_file":
        return read_file(**args)
    if name == "write_file":
        return write_file(**args)
    if name == "bash":
        return bash(**args)
    return f"Error: unknown tool '{name}'"

print("tools + dispatch defined.")

# %% [markdown]
# The loop is the phase's `run_agent`, with the client and the **asker injected as
# parameters** (the same injectable-client idea as every notebook in this series — and
# the asker injection is the one-line deviation section 3 explained).

# %%
def run_agent_gated(task, client, mode="auto", ask=None):
    """The V2 loop with the permission gate between 'the model asked' and 'the OS acted'."""
    input_items = [{"role": "user", "content": task}]
    while True:
        resp = client.responses.create(model=MODEL, input=input_items, tools=TOOLS)
        for item in resp.output:
            input_items.append(
                item.model_dump() if hasattr(item, "model_dump") else item
            )
        tool_calls = [item for item in resp.output
                      if getattr(item, "type", None) == "function_call"]
        if not tool_calls:
            print("ANSWER:", resp.output_text)
            return input_items
        for tc in tool_calls:
            args = json.loads(tc.arguments)
            # The permission gate — the four lines from Step 2.1:
            arg = args.get("command", args.get("path", ""))
            decision = check_permission(tc.name, arg, mode=mode)
            if decision == "ask":
                decision = ask(tc.name)
            if decision == "deny":
                result = "Permission denied by the harness."
            else:
                result = dispatch(tc.name, args)
            print(f"[tool] {tc.name}({arg!r}) -> {decision}")
            print(f"[result] {result[:100].rstrip()}{'...' if len(result) > 100 else ''}\n")
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })

print("run_agent_gated defined.")

# %% [markdown]
# Watch all three behaviours in one run: `read_file` (safe) passes **silently**, the
# first `bash` is asked and **allowed** (`y`), the second is asked and **denied** (`n`) —
# and the denial is not a crash: the same `call_id` gets a `function_call_output`
# carrying the error string, which the model reads and reacts to.

# %%
gated_items = run_agent_gated(
    "Read hello.txt, then run a couple of shell commands.",
    make_client([
        [fake_function_call("read_file", {"path": "hello.txt"}, "call_p1")],
        [fake_function_call("bash", {"command": "echo agent was here > proof.txt && cat proof.txt"}, "call_p2")],
        [fake_function_call("bash", {"command": "cat /etc/shadow"}, "call_p3")],
        [fake_message("I read hello.txt and ran the first command; the second was denied "
                      "by the user, so I stopped there.")],
    ]),
    mode="auto",
    ask=make_scripted_asker(["y", "n"]),
)

# %% [markdown]
# **▶ Self-check** — 8 transcript items (1 user + 3 calls + 3 outputs + 1 message),
# every `call_id` answered, the first `bash` *genuinely executed* (it left `proof.txt`
# in the workspace), the second never reached a shell.

# %%
types = [i.get("type") for i in gated_items]
print("transcript item types:", types)

calls = [i for i in gated_items if i.get("type") == "function_call"]
outs = [i for i in gated_items if i.get("type") == "function_call_output"]
assert len(gated_items) == 8, f"expected 8 transcript items, got {len(gated_items)}: {types}"
assert {c["call_id"] for c in calls} == {o["call_id"] for o in outs}, (
    "denied or not, EVERY call_id must get a function_call_output"
)
assert outs[0]["output"].startswith("Hello from Phase 5"), "the safe read ran silently"
assert "agent was here" in outs[1]["output"], "the allowed bash really executed"
assert (WS / "proof.txt").exists(), "…and really touched the workspace"
assert outs[2]["output"] == "Permission denied by the harness.", (
    "the denied bash became this exact error string — /etc/shadow was never read"
)
print("gated-loop checks passed")

# %% [markdown]
# ## 5. Session memory — hidden state made visible
# ([Step 3.4](../05-permissions-and-safety.md#step-34--the-approval-gate-production-shape))
#
# The production gate remembers `a`/`d` answers in two module-level sets and returns
# `(decision, reason)` tuples. Here is that gate in the functions shape of Version 2
# (the phase's V3 wraps the same ordering in policy objects — that multi-file build
# stays in the markdown). **The check order is load-bearing**: hard denials come
# *before* session memory.
#
# > ⚠️ **Kernel-lifetime state.** In a notebook these sets outlive every cell — the
# > canonical "why is bash auto-allowed? I typed `a` twenty cells ago" trap. So every
# > cell below that touches them starts with an explicit reset line.

# %%
# Session memory: tool names the user said "always allow" or "always deny" this run.
_session_always_allow = set()
_session_always_deny = set()

def check_permission_with_memory(tool_name, arg, mode="auto"):
    """Step 3.4's gate in V2 functions form. Returns (decision, reason)."""
    risk = TOOL_RISK.get(tool_name, "dangerous")

    # --- 1. Hard denials first: blocked patterns, then plan-mode mutations. ---
    # Session memory must NEVER outrank these — "always allow" (the `a` answer)
    # is a convenience for repeated prompts, not a licence to bypass the deny list.
    if tool_name == "bash":
        for bad in ["rm -rf", "sudo ", ":(){"]:
            if bad in arg:
                return ("deny", f"Blocked pattern {bad.strip()!r} — denied regardless of session memory.")
    if mode == "plan" and risk in ["caution", "dangerous"]:
        return ("deny", f"Mode 'plan' does not allow '{risk}' tools.")

    # --- 2. Session memory (only consulted once nothing hard-denies) ---
    if tool_name in _session_always_deny:
        return ("deny", f"Denied for this session (you denied '{tool_name}' earlier).")
    if tool_name in _session_always_allow:
        return ("allow", "Allowed by session memory.")

    # --- 3. Mode auto-approval ---
    if risk in AUTO_OK.get(mode, []):
        return ("allow", f"Auto-approved in mode '{mode}' (risk='{risk}').")

    # --- 4. Must ask the user ---
    return ("ask", "Needs user approval.")

print("gate-with-memory defined; sets are empty:", _session_always_allow, _session_always_deny)

# %% [markdown]
# Make the hidden state visible: add to the set by hand (that is all the `a` answer
# does), watch the same call flip from `ask` to `allow`, then clear it and watch it
# flip back.

# %%
_session_always_allow.clear(); _session_always_deny.clear()   # explicit reset (kernel-lifetime state!)

before = check_permission_with_memory("bash", "ls")
print("before 'a':", before)

_session_always_allow.add("bash")        # ← this is what answering `a` does, made visible
during = check_permission_with_memory("bash", "ls")
print("after  'a':", during)

_session_always_allow.clear()            # reset again — leave no surprises for later cells
after = check_permission_with_memory("bash", "ls")
print("cleared   :", after)

assert before == ("ask", "Needs user approval."), f"fresh session should ask, got {before}"
assert during == ("allow", "Allowed by session memory."), (
    f"after the 'a' answer the same call should auto-allow, got {during}"
)
assert after == before, "clearing the set must restore the original behaviour"
print("session-memory checks passed")

# %% [markdown]
# **▶ Deny beats session memory** — the property the phase's
# [WARNING](../05-permissions-and-safety.md#step-34--the-approval-gate-production-shape)
# calls load-bearing: one `a` on a harmless `bash(ls)` must NOT re-enable
# `bash(rm -rf /)`. Hard denials are checked first, so it doesn't.

# %%
_session_always_allow.clear(); _session_always_deny.clear()   # explicit reset
_session_always_allow.add("bash")        # the user said "always allow bash" on an innocent call…

harmless = check_permission_with_memory("bash", "ls")
destructive = check_permission_with_memory("bash", "rm -rf /")
print("bash('ls')       ->", harmless)
print("bash('rm -rf /') ->", destructive)

assert harmless[0] == "allow", "session memory still works for harmless calls"
assert destructive[0] == "deny", (
    "HARD DENIALS MUST BEAT SESSION MEMORY — if this is 'allow', the gate consulted "
    "the session set before the deny list, and one 'a' just re-enabled rm -rf"
)
assert "regardless of session memory" in destructive[1], f"unexpected reason: {destructive[1]}"

_session_always_allow.clear(); _session_always_deny.clear()   # leave the sets clean
print("deny-beats-session-memory holds")

# %% [markdown]
# > **Hard stop — Versions 3 and 4 stay in the phase.** The `Enum`/`@dataclass`
# > policy engine ([Version 3](../05-permissions-and-safety.md#version-3--classes-the-same-gate-as-policy-objects))
# > and the hook system ([Version 4](../05-permissions-and-safety.md#version-4--hooks-functions-you-hand-to-the-harness))
# > are the same gate reorganized into objects — a multi-file build that belongs in
# > files, not cells. The maintained forms are
# > [`code/agent_harness/permissions.py`](../code/agent_harness/permissions.py) and
# > [`hooks.py`](../code/agent_harness/hooks.py).
#
# ## 6. The sandbox — strip the environment before the shell sees it
# ([Interlude — Sandboxing](../05-permissions-and-safety.md#interlude--sandboxing-what-pure-python-can-do))
#
# The permission gate decides *whether* a command runs; the sandbox constrains *what it
# inherits*. The phase's `run_sandboxed` locks the cwd, allowlists the environment, caps
# the output, and (on POSIX) adds CPU/file-size limits via `preexec_fn` — here we keep
# the env-allowlist core, which is the part with a one-cell payoff: your `OPENAI_API_KEY`
# never reaches the child process.

# %%
# Environment variables allowed to pass into subprocesses.
# Everything else is stripped to prevent leaking credentials from the parent env.
_ALLOWED_ENV_KEYS = {
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM",
    "TMPDIR", "TZ", "SHELL",
}

def _build_clean_env(workspace_root: str) -> dict:
    clean = {}
    for key in _ALLOWED_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            clean[key] = value
    clean["PWD"] = workspace_root
    return clean

def run_sandboxed(command: str, workspace_root: str, timeout_seconds: float = 30.0,
                  max_output_bytes: int = 512 * 1024) -> str:
    """The phase's hardened subprocess, minus the POSIX rlimits (see the Interlude for those)."""
    env = _build_clean_env(workspace_root)
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True,
            cwd=workspace_root, env=env, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout_seconds}s."
    except OSError as exc:
        return f"Error: could not launch subprocess: {exc}"

    raw_output = proc.stdout + proc.stderr
    truncated = len(raw_output) > max_output_bytes
    text = raw_output[:max_output_bytes].decode("utf-8", errors="replace")
    if proc.returncode != 0:
        text = f"[exit {proc.returncode}]\n{text}"
    if truncated:
        text += f"\n[output truncated at {max_output_bytes} bytes]"
    return text

print("run_sandboxed defined — allowlist:", sorted(_ALLOWED_ENV_KEYS))

# %% [markdown]
# **▶ Watch the key get stripped.** We plant a fake `OPENAI_API_KEY` in the kernel's
# environment (restored at the end of the cell), then ask a child process to print it —
# once with plain inherited env, once through the sandbox.

# %%
probe = f"{sys.executable} -c 'import os; print(os.environ.get(\"OPENAI_API_KEY\"))'"

_had_key = "OPENAI_API_KEY" in os.environ
_old_key = os.environ.get("OPENAI_API_KEY")
os.environ["OPENAI_API_KEY"] = "sk-demo-not-a-real-key"
try:
    leaky = subprocess.run(probe, shell=True, capture_output=True, text=True, cwd=WS)
    leaked = leaky.stdout.strip()
    sandboxed_out = run_sandboxed(probe, workspace_root=str(WS)).strip()
finally:   # never leave the fake key in the kernel env — later cells gate on it
    if _had_key:
        os.environ["OPENAI_API_KEY"] = _old_key
    else:
        del os.environ["OPENAI_API_KEY"]

print("plain subprocess sees :", leaked)
print("sandboxed child sees  :", sandboxed_out)

assert leaked == "sk-demo-not-a-real-key", (
    "the unsandboxed child inherits the parent env — the leak is the default"
)
assert sandboxed_out == "None", (
    f"the allowlisted env must strip OPENAI_API_KEY — child saw {sandboxed_out!r}"
)
assert os.environ.get("OPENAI_API_KEY") == _old_key, "kernel env must be restored exactly"
print("sandbox checks passed (and the kernel env is back to normal)")

# %% [markdown]
# What pure Python *cannot* do — network blocking, true filesystem isolation, reliable
# memory limits — [stays honest in the phase](../05-permissions-and-safety.md#what-sandboxing-cannot-do-in-pure-python):
# this layer shrinks the blast radius for accidents; determined adversaries need
# containers.
#
# ### Final structural checks

# %%
# Everything this notebook claimed, re-asserted in one place.
assert check_permission("read_file", "x", mode="plan") == "allow"
assert check_permission("write_file", "x", mode="plan") == "deny"
assert check_permission("bash", "ls", mode="auto") == "ask"
assert all(check_permission("bash", "rm -rf /", mode=m) == "deny" for m in AUTO_OK)

_session_always_allow.clear(); _session_always_deny.clear()   # explicit reset
_session_always_allow.add("bash")
assert check_permission_with_memory("bash", "ls")[0] == "allow"
assert check_permission_with_memory("bash", "sudo rm -rf /")[0] == "deny"   # deny beats `a`
_session_always_allow.clear(); _session_always_deny.clear()   # leave the sets clean

calls = [i for i in gated_items if i.get("type") == "function_call"]
outs = [i for i in gated_items if i.get("type") == "function_call_output"]
assert {c["call_id"] for c in calls} == {o["call_id"] for o in outs}
assert outs[2]["output"] == "Permission denied by the harness."
assert sandboxed_out == "None"
print("All checks passed")

# %% [markdown]
# **Optional — the gated loop against the real API** (needs `OPENAI_API_KEY`). The real
# model gets the same tools, the same scratch workspace, and a generous scripted asker —
# watch which calls pass silently and which stop at the gate.

# %%
if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    live_items = run_agent_gated(
        "List the files in your workspace, then read hello.txt.",
        OpenAI(), mode="auto", ask=make_scripted_asker(["y"] * 8),
    )
else:
    print("(skipped — needs USE_REAL_API = True in the parameters cell AND an "
          "OPENAI_API_KEY; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - The whole permission system is one decision between "the model asked" and "the OS
#   acted": `allow` / `deny` / `ask` — and a denial is a *tool result string*, never a crash.
# - Modes auto-approve by risk tier; blocked patterns are denied in every mode.
# - Notebooks can't block on stdin (`input()` raises `StdinNotImplementedError` headless,
#   and the `EOFError` guard doesn't catch it) — inject the asker; the terminal version
#   uses `input()`.
# - Session memory is convenience state; **hard denials are checked first**, so one `a`
#   never re-enables `rm -rf`.
# - The sandbox allowlists the child env — your API key never reaches the shell.
#
# Now do the phase's [Check yourself](../05-permissions-and-safety.md#check-yourself) and
# the Phase 5 exercises in [EXERCISES.md](../EXERCISES.md). Two starter cells:

# %%
# Quiz: earlier this session the user answered `a` ("always allow") for bash.
# The model now calls bash("sudo rm -rf /"). What does the gate return?
answer = "deny"   # <- edit me ("allow" or "deny"), then run

assert answer == "deny", (
    "Hint: re-read the deny-beats-session-memory cell — hard denials are checked FIRST."
)
print("Correct — convenience layers never outrank the deny list.")

# %%
# Exercise (Step 2.3): structured rules — "always allow `git status` without asking,
# even though bash is dangerous." Write apply_rules(tool_name, arg, rules) and a
# DEFAULT_RULES list ({"decision": ..., "tool": ..., "arg_contains": ...}, first match
# wins), then a check_permission_with_rules that consults rules BEFORE mode logic.
# your code here

# assert check_permission_with_rules("bash", "git status", mode="auto") == "allow"  # uncomment when ready
# assert check_permission_with_rules("bash", "git push", mode="auto") == "ask"      # uncomment when ready
# assert check_permission_with_rules("bash", "rm -rf /", mode="yolo") == "deny"     # uncomment when ready
print("(exercise scaffold — fill in the code above)")
