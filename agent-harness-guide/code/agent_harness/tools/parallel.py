"""Parallel tool call execution using ThreadPoolExecutor."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .registry import ToolRegistry


def run_tool_calls(
    registry: ToolRegistry,
    calls: list[dict[str, Any]],
    max_workers: int = 4,
) -> list[dict[str, str]]:
    """Execute a batch of function_call items in parallel.

    Each call dict must have 'call_id', 'name', 'arguments'.
    Returns list of {'call_id': ..., 'output': ...} preserving order.
    """
    results: dict[str, str] = {}

    def _execute(call: dict) -> tuple[str, str]:
        call_id = call["call_id"]
        name = call["name"]
        arguments = call.get("arguments", "{}")
        try:
            output = registry.dispatch(name, arguments)
        except Exception as exc:  # noqa: BLE001
            output = f"Error: {exc}"
        return call_id, output

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_execute, c): c["call_id"] for c in calls}
        for future in as_completed(futures):
            call_id, output = future.result()
            results[call_id] = output

    # Return in original call order
    return [{"call_id": c["call_id"], "output": results[c["call_id"]]} for c in calls]
