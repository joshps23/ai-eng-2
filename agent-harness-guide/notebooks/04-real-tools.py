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
# # Phase 4 — Real-World Tools (companion notebook)
#
# [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/joshps23/ai-eng-2/blob/main/agent-harness-guide/notebooks/04-real-tools.ipynb)
#
# Companion to [04-real-tools.md](../04-real-tools.md): the agent touches a disk —
# a *throwaway* one. Version 1's unguarded `open()`, Version 2's `_safe_path`
# confinement and the visceral `../../etc/passwd` check, one FakeClient-driven
# tool loop, the `bash` tool, and the production toolset imported from the package.
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

    Only the *model* is faked — your tools, the handshake, and the transcript all
    run for real either way.
    """
    if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        return OpenAI()
    return FakeClient(turns)

OFFLINE = not (USE_REAL_API and os.environ.get("OPENAI_API_KEY"))
print("Mode:", "OFFLINE (FakeClient — no key needed)" if OFFLINE else "REAL API")

# %% [markdown]
# ## 0. A throwaway workspace — **before** any tool exists
#
# The phase's [Version 1 warning](../04-real-tools.md#version-1--line-by-line-the-agent-touches-your-disk-no-def-no-classes)
# — *"the agent can now touch your disk"* — is literal. In a notebook it is worse:
# the kernel's working directory is wherever Jupyter launched (here: this repo!), so a
# tool rooted at the cwd would read and write **your actual checkout**. Rule for this
# whole notebook: every tool operates inside a fresh temporary directory, never the cwd.

# %%
import pathlib, tempfile

WORKSPACE = pathlib.Path(tempfile.mkdtemp(prefix="phase4-ws-")).resolve()

# Plant the phase's test file so there is something to read.
(WORKSPACE / "hello.txt").write_text("Hello from Phase 4!\nThis is line 2.\n")

print("workspace:", WORKSPACE)
print("planted  :", [p.name for p in WORKSPACE.iterdir()])
print("notebook cwd (NOT the workspace):", os.getcwd())

# %% [markdown]
# ## 1. Version 1's lesson — an unguarded tool reads *anything*
# ([Version 1](../04-real-tools.md#version-1--line-by-line-the-agent-touches-your-disk-no-def-no-classes))
#
# V1's `read_file` is a bare `open()` around whatever path *the model chose*. The phase
# says "try `/etc/passwd`" — here, no model needed: call the tool function directly and
# watch it walk straight out of any project, because nothing confines it yet.

# %%
def read_file_unguarded(path):
    """Version 1's inline tool, as a function: a bare open() — zero safety machinery."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return "ERROR: File not found: " + path
    except OSError as exc:
        return "ERROR: Cannot read file: " + str(exc)


print("our planted file:", read_file_unguarded(str(WORKSPACE / "hello.txt"))[:20], "…")

passwd = read_file_unguarded("/etc/passwd")   # nothing stops this
print("…and /etc/passwd, far outside any workspace:")
print(" ", passwd.splitlines()[0], f"  (+{len(passwd.splitlines()) - 1} more lines)")

assert not passwd.startswith("ERROR:"), (
    "on Linux this read should sail straight through — that unguarded success IS the problem"
)

# %% [markdown]
# ## 2. Version 2 — `_safe_path` and `_truncate`, the two safety helpers
# ([Step 2.3](../04-real-tools.md#step-23--safety-first-add-_safe_path-and-_truncate-before-writing-anything))
#
# Verbatim from the phase's complete V2 file
# ([Step 2.7](../04-real-tools.md#step-27--version-2-complete-the-whole-harness-in-one-file)),
# with **one deliberate change**: the phase sets
# `WORKSPACE_ROOT = pathlib.Path(os.getcwd()).resolve()` — in a notebook that would be
# the repo, so we point it at the throwaway workspace instead.

# %%
WORKSPACE_ROOT = WORKSPACE   # the phase uses os.getcwd(); in a notebook, NEVER do that

def _safe_path(user_path: str) -> pathlib.Path:
    """Resolve user_path inside WORKSPACE_ROOT or raise ValueError."""
    p = pathlib.Path(user_path)
    if p.is_absolute():
        p = WORKSPACE_ROOT / pathlib.Path(*p.parts[1:])
    else:
        p = WORKSPACE_ROOT / p
    resolved = p.resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(
            f"Path '{user_path}' resolves outside the workspace root '{WORKSPACE_ROOT}'."
        )
    return resolved

def _truncate(text: str, max_chars: int = 40_000, max_lines: int = 2_000,
              label: str = "output") -> str:
    """Cap text at max_lines / max_chars with a visible notice."""
    lines = text.splitlines(keepends=True)
    if len(lines) > max_lines:
        text = "".join(lines[:max_lines])
        text += f"\n[... {label} truncated at {max_lines} lines ...]"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n[... {label} truncated at {max_chars} chars ...]"
    return text

print("helpers defined — WORKSPACE_ROOT =", WORKSPACE_ROOT)

# %% [markdown]
# ## 3. The confined tools: `read_file`, `write_file`, `list_dir`
#
# The same plain functions from
# [Step 2.7](../04-real-tools.md#step-27--version-2-complete-the-whole-harness-in-one-file),
# verbatim — every path now funnels through `_safe_path`, every read through `_truncate`.

# %%
def read_file(path: str) -> str:
    """Read a text file and return its contents, or an ERROR string."""
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return f"ERROR: File not found: {path}"
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"
    return _truncate(text, label=f"read_file({path})")

def write_file(path: str, content: str) -> str:
    """Write content to a file, creating it (and parent dirs) if needed."""
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        p.write_bytes(encoded)
    except OSError as exc:
        return f"ERROR: Cannot write file: {exc}"
    return f"Wrote {len(encoded)} bytes ({content.count(chr(10))} lines) to '{path}'."

def list_dir(path: str = ".") -> str:
    """List the contents of a directory."""
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not p.exists():
        return f"ERROR: Directory not found: {path}"
    if not p.is_dir():
        return f"ERROR: '{path}' is a file, not a directory."
    # Tuple sort key: False < True, so dirs (is_file()=False) come first, then by name.
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    lines = []
    for e in entries:
        if e.is_dir():
            lines.append(f"D  {e.name}/")
        else:
            lines.append(f"F  {e.name}  ({e.stat().st_size} bytes)")
    return _truncate(f"Directory: {path}\n" + "\n".join(lines), label="list_dir")

print("tools defined.")

# %% [markdown]
# **▶ The visceral check** — the phase's
# ["Check it now (no API key needed)"](../04-real-tools.md#step-23--safety-first-add-_safe_path-and-_truncate-before-writing-anything),
# plus the [Step 2.7 note](../04-real-tools.md#step-27--version-2-complete-the-whole-harness-in-one-file)
# about absolute paths: a *relative* escape (`../../etc/passwd`) trips the guard with the
# outside-the-workspace ERROR; an *absolute* path is **re-rooted** under the workspace, so
# it fails with an ordinary `File not found`. Either way, nothing outside is touched —
# compare with section 1, where the very same `/etc/passwd` read sailed through.

# %%
# Should succeed — the planted file, by relative path this time.
print(read_file("hello.txt"))

# Should return ERROR, not read the file.
escape = read_file("../../etc/passwd")
print(escape)
rerooted = read_file("/etc/passwd")
print(rerooted)

assert "Hello from Phase 4!" in read_file("hello.txt"), "the planted file should read normally"
assert escape.startswith("ERROR:") and "outside the workspace root" in escape, (
    "the relative escape must trip _safe_path — if you see passwd contents, the guard is not wired in"
)
assert rerooted == "ERROR: File not found: /etc/passwd", (
    "an absolute path is re-rooted UNDER the workspace, so it should miss, not escape"
)

# write_file + list_dir, confined the same way:
print(write_file("notes/notes.txt", "# TODO: finish this\nx = 1\n"))
print(list_dir("."))
assert write_file("../escape.txt", "nope").startswith("ERROR:"), "writes must be confined too"
assert not (WORKSPACE.parent / "escape.txt").exists(), "no file may appear outside the workspace"
print("confinement checks passed")

# %% [markdown]
# ## 4. The harness drives the confined tools (one FakeClient loop)
#
# The V2 harness from [Step 2.7](../04-real-tools.md#step-27--version-2-complete-the-whole-harness-in-one-file):
# schemas, the `TOOL_FNS` dispatch dict, and `run()`. Two notebook adaptations (same as
# notebook 01): the client comes in as a parameter, and the transcript is returned for
# inspection.

# %%
import json

SCHEMAS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a text file and return its contents. Returns an ERROR string on failure.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace root."},
            },
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": (
            "Write content to a file, creating it (and parent directories) if needed. "
            "Overwrites existing files completely."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace root."},
                "content": {"type": "string", "description": "Full text content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "type": "function",
        "name": "list_dir",
        "description": "List the files and directories at a path, one entry per line.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path. Default '.'."},
            },
            "required": [],
        },
    },
]

TOOL_FNS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
}

def run(task, client):
    """The V2 loop: dict dispatch, ERROR strings, the call_id handshake. Returns the transcript."""
    input_items = [{"role": "user", "content": task}]
    while True:
        resp = client.responses.create(model=MODEL, input=input_items, tools=SCHEMAS)
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
            args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
            print(f"[tool] {tc.name}({args})")
            fn = TOOL_FNS.get(tc.name)
            result = fn(**args) if fn else f"ERROR: Unknown tool: {tc.name}"
            print(f"[result] {result[:120]}{'...' if len(result) > 120 else ''}\n")
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })

print("harness defined.")

# %% [markdown]
# The scripted model asks to list the workspace, then read the planted file. Only the
# *model* is scripted — both tools genuinely execute against the tmpdir.

# %%
v2_items = run(
    "List the files in the workspace, then read hello.txt.",
    make_client([
        [fake_function_call("list_dir", {"path": "."}, "call_f1")],
        [fake_function_call("read_file", {"path": "hello.txt"}, "call_f2")],
        [fake_message("The workspace holds hello.txt (plus your notes dir); hello.txt says "
                      "'Hello from Phase 4!' and 'This is line 2.'")],
    ]),
)

# %% [markdown]
# **▶ Self-check** — the transcript is all plain dicts here (the loop `model_dump()`s
# every output item), so `.get()` is enough.

# %%
types = [i.get("type") for i in v2_items]
print("transcript item types:", types)

calls = [i for i in v2_items if i.get("type") == "function_call"]
outs = [i for i in v2_items if i.get("type") == "function_call_output"]
assert len(calls) == 2 and len(outs) == 2, (
    f"expected 2 tool round-trips, got {len(calls)} calls / {len(outs)} outputs"
)
assert {c["call_id"] for c in calls} == {o["call_id"] for o in outs}, (
    "every call_id must be answered — an orphan here is an API 400 in real life"
)
assert "Hello from Phase 4!" in outs[1]["output"], "the read really hit the planted file"
assert all(isinstance(o["output"], str) for o in outs), "tool output must be a string"
print("V2 loop checks passed")

# %% [markdown]
# ## 5. `bash` — the escape hatch, captured and confined
# ([Step 2.6](../04-real-tools.md#step-26--add-bash-high-risk--arbitrary-execution))
#
# Verbatim from the phase: `subprocess.run` with **captured** output (so it lands in the
# cell, and in the transcript, not on some server console), stdin closed, a timeout, and
# `cwd=WORKSPACE_ROOT` so the command starts inside the throwaway workspace. No model
# needed to feel it — call it directly.

# %%
import subprocess

def bash(command: str, timeout: int = 120) -> str:
    """Run a shell command; return exit code plus combined stdout/stderr."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        output = result.stdout.decode("utf-8", errors="replace")
        output = _truncate(output, label=f"bash({command[:60]})")
        return f"Exit code: {result.returncode}\n---\n{output}"
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout} seconds: {command}"
    except OSError as exc:
        return f"ERROR: Failed to start command: {exc}"


print(bash("echo Hello from bash"))
print(bash("ls -1"))                  # runs in the workspace, not the notebook's cwd
print(bash("cat no-such-file"))       # failure is an exit code the model can read, not a crash

ok = bash("echo Hello from bash")
assert ok.startswith("Exit code: 0") and "Hello from bash" in ok, (
    "echo should exit 0 with its output captured below the --- line"
)
assert "hello.txt" in bash("ls -1"), "cwd must be the workspace — ls should see the planted file"
assert bash("cat no-such-file").startswith("Exit code: 1"), (
    "a failing command returns a nonzero exit code as TEXT — the loop never crashes"
)
print("bash checks passed")

# %% [markdown]
# ## 6. Version 3 — the production toolset, imported (not rebuilt)
# ([Version 3](../04-real-tools.md#version-3--the-organized-toolset-the-same-idea-organized))
#
# The phase assembles `coding_tools.py` from your Phase 2 `tools/` package; the
# consolidated, **tested** form already lives in
# [`code/agent_harness/tools/files.py`](../code/agent_harness/tools/files.py) and
# [`shell.py`](../code/agent_harness/tools/shell.py) — same `_safe_path` idea, enforced
# centrally, with `set_workspace()` as the one switch. So we don't rebuild it here; we
# import it. Two things to notice: each tool is a `Tool` object (the `@tool` decorator
# wrapped the function — call the raw function via `.run`), and the package spells
# failures `Error: ...` where the phase's V2 says `ERROR: ...` (the phase
# [calls this out](../05-permissions-and-safety.md#interlude--sandboxing-what-pure-python-can-do);
# the package spelling is the canonical one).

# %%
from agent_harness.tools import files as af

af.set_workspace(WORKSPACE)   # the package's one-line confinement switch

print(af.read_file.run("hello.txt"))
print(af.glob_files.run("**/*.txt"))

pkg_escape = af.read_file.run("../../etc/passwd")
print(pkg_escape)

assert "Hello from Phase 4!" in af.read_file.run("hello.txt")
assert "notes/notes.txt" in af.glob_files.run("**/*.txt"), (
    "glob_files should find the nested file write_file created in section 3"
)
assert pkg_escape.startswith("Error:") and "outside workspace root" in pkg_escape, (
    "the package guard refuses the same escape — note the 'Error:' spelling"
)
assert af.read_file.name == "read_file" and af.read_file.parameters["type"] == "object", (
    "@tool wrapped the function into a Tool carrying its auto-built schema"
)
print("package toolset checks passed")

# %% [markdown]
# ### Final structural checks

# %%
# Everything this notebook claimed, re-asserted in one place.
assert not read_file_unguarded("/etc/passwd").startswith("ERROR:")      # V1: unguarded reads escape
assert read_file("../../etc/passwd").startswith("ERROR:")               # V2: the guard stops it
assert read_file("/etc/passwd") == "ERROR: File not found: /etc/passwd" # absolute → re-rooted
assert "Hello from Phase 4!" in read_file("hello.txt")                  # normal reads still work
calls = [i for i in v2_items if i.get("type") == "function_call"]
outs = [i for i in v2_items if i.get("type") == "function_call_output"]
assert {c["call_id"] for c in calls} == {o["call_id"] for o in outs}    # handshake intact
assert bash("pwd").splitlines()[-1] == str(WORKSPACE_ROOT)              # bash confined to the tmpdir
assert af.read_file.run("../../etc/passwd").startswith("Error:")        # package guard agrees
print("All checks passed")

# %% [markdown]
# **Optional — the same harness against the real API** (needs `OPENAI_API_KEY`).
# The real model gets the same three confined tools and the same throwaway workspace —
# whatever it decides to read or write stays inside the tmpdir.

# %%
if USE_REAL_API and os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI
    live_items = run("List the files in the workspace, then read hello.txt.", OpenAI())
else:
    print("(skipped — needs USE_REAL_API = True in the parameters cell AND an "
          "OPENAI_API_KEY; the FakeClient cells above are the real lesson)")

# %% [markdown]
# ## Key takeaways
#
# - A real tool is real power: V1's bare `open()` read `/etc/passwd` the moment we asked.
# - `_safe_path` (resolve, then `relative_to` the workspace root) turns escapes into
#   ERROR strings the model can read; `_truncate` keeps any output context-sized.
# - Relative escapes trip the guard; absolute paths are re-rooted — both stay inside.
# - `bash` is `subprocess.run` with captured output, closed stdin, a timeout, and
#   `cwd=workspace` — and it is exactly why Phase 5's permission gate exists.
# - The production form is the same idea organized: `agent_harness.tools.files` /
#   `shell`, confined centrally via `set_workspace()`.
#
# Now do the phase's [Pitfalls](../04-real-tools.md#pitfalls), then the Phase 4
# exercises in [EXERCISES.md](../EXERCISES.md). Two starter cells:

# %%
# Quiz: which path makes read_file return the "resolves outside the workspace root"
# ERROR — "../../etc/passwd" or "/etc/passwd"?
answer = "../../etc/passwd"   # <- edit me, then run

assert answer == "../../etc/passwd", (
    "Hint: absolute paths are RE-ROOTED under the workspace (so they miss); "
    "only the relative escape actually resolves outside and trips the guard."
)
print("Correct — absolute paths get re-rooted; relative ones can really escape, so the guard fires.")

# %%
# Exercise (Step 2.1): add `glob` as a plain function — pattern + optional path,
# confined with _safe_path, sorted file matches one per line. Write GLOB_SCHEMA,
# add it to SCHEMAS and TOOL_FNS, then script a FakeClient turn that calls it
# through run().
# your code here

# assert "hello.txt" in glob("*.txt")                       # uncomment when ready
# assert glob("*.nope").startswith("No files match")        # uncomment when ready
print("(exercise scaffold — fill in the code above)")
