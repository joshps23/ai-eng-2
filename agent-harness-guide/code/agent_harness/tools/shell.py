"""Shell execution tool."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .base import tool

_WORKSPACE_ROOT: Path = Path(os.getcwd())
_MAX_OUTPUT_CHARS = 20_000


def set_workspace(path: Path) -> None:
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = Path(path)


def _truncate(text: str, max_chars: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n...[truncated {len(text) - max_chars} chars]...\n" + text[-half:]


@tool(risk="high")
def bash(command: str, timeout: int = 120) -> str:
    """Run a shell command in the workspace directory.

    command: Shell command to execute.
    timeout: Maximum seconds to wait (default 120).
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(_WORKSPACE_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            errors="replace",
        )
        output = result.stdout or ""
        exit_code = result.returncode
        if exit_code != 0:
            output += f"\n[exit code: {exit_code}]"
        return _truncate(output)
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout} seconds"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"
