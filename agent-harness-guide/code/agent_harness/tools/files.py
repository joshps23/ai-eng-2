"""File system tools confined to a workspace root."""
from __future__ import annotations

import fnmatch
import glob as _glob
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .base import Tool, tool

if TYPE_CHECKING:
    pass

# Module-level workspace root — overridden by Settings at runtime
_WORKSPACE_ROOT: Path = Path(os.getcwd())

_MAX_READ_BYTES = 100_000  # ~100 KB read limit
_MAX_OUTPUT_CHARS = 20_000


def set_workspace(path: Path) -> None:
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = Path(path)


def _safe_path(rel_or_abs: str) -> Path:
    """Resolve path and ensure it stays inside workspace root."""
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = _WORKSPACE_ROOT / p
    p = p.resolve()
    workspace = _WORKSPACE_ROOT.resolve()
    if not str(p).startswith(str(workspace)):
        raise PermissionError(
            f"Path '{p}' is outside workspace root '{workspace}'"
        )
    return p


def _truncate(text: str, max_chars: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n...[truncated {len(text) - max_chars} chars]...\n" + text[-half:]


@tool
def read_file(path: str) -> str:
    """Read the contents of a file.

    path: Relative or absolute path to the file to read.
    """
    resolved = _safe_path(path)
    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except PermissionError as exc:
        return f"Error: {exc}"
    return _truncate(content)


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating directories as needed.

    path: Relative or absolute path to write.
    content: Text content to write.
    """
    try:
        resolved = _safe_path(path)
    except PermissionError as exc:
        return f"Error: {exc}"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {resolved}"


@tool
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Replace old_string with new_string in a file (first occurrence).

    path: Path to the file to edit.
    old_string: Exact text to find.
    new_string: Text to replace it with.
    """
    try:
        resolved = _safe_path(path)
    except PermissionError as exc:
        return f"Error: {exc}"
    try:
        content = resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    if old_string not in content:
        return f"Error: old_string not found in {path}"
    new_content = content.replace(old_string, new_string, 1)
    resolved.write_text(new_content, encoding="utf-8")
    return f"Edited {resolved}: replaced 1 occurrence"


@tool
def glob_files(pattern: str) -> str:
    """Find files matching a glob pattern within the workspace.

    pattern: Glob pattern relative to workspace root (e.g. '**/*.py').
    """
    workspace = _WORKSPACE_ROOT.resolve()
    full_pattern = str(workspace / pattern)
    matches = _glob.glob(full_pattern, recursive=True)
    # Filter to only files inside workspace
    safe = []
    for m in sorted(matches):
        try:
            p = Path(m).resolve()
            if str(p).startswith(str(workspace)):
                safe.append(str(p.relative_to(workspace)))
        except ValueError:
            pass
    if not safe:
        return "No files matched."
    return "\n".join(safe)


@tool
def grep(pattern: str, path: str = ".", recursive: bool = True) -> str:
    """Search for a regex pattern in files within the workspace.

    pattern: Regular expression to search for.
    path: File or directory to search (relative to workspace).
    recursive: Whether to search subdirectories.
    """
    try:
        resolved = _safe_path(path)
    except PermissionError as exc:
        return f"Error: {exc}"

    results: list[str] = []

    def _search_file(fp: Path) -> None:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        for lineno, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                rel = str(fp.relative_to(_WORKSPACE_ROOT.resolve()))
                results.append(f"{rel}:{lineno}: {line.rstrip()}")

    try:
        regex = re.compile(pattern)  # noqa: F841 — just validates
    except re.error as exc:
        return f"Error: invalid regex: {exc}"

    if resolved.is_file():
        _search_file(resolved)
    elif resolved.is_dir():
        if recursive:
            for fp in sorted(resolved.rglob("*")):
                if fp.is_file():
                    _search_file(fp)
        else:
            for fp in sorted(resolved.iterdir()):
                if fp.is_file():
                    _search_file(fp)

    if not results:
        return "No matches found."
    return _truncate("\n".join(results))


@tool
def list_dir(path: str = ".") -> str:
    """List files and directories at a path within the workspace.

    path: Directory path relative to workspace root.
    """
    try:
        resolved = _safe_path(path)
    except PermissionError as exc:
        return f"Error: {exc}"
    if not resolved.exists():
        return f"Error: path not found: {path}"
    if resolved.is_file():
        return str(resolved)
    entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
    lines = []
    for entry in entries:
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{suffix}")
    return "\n".join(lines) if lines else "(empty directory)"
