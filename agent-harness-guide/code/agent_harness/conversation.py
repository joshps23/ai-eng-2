"""Conversation: manages the running input_items transcript."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# to_input_dict — normalize SDK objects or plain dicts to plain dicts
# ---------------------------------------------------------------------------

def to_input_dict(item: Any) -> dict:
    """Convert an SDK output item (or plain dict) to a plain dict.

    SDK items expose .model_dump(); plain dicts are returned as-is.
    We also handle FakeItem objects which have a .model_dump() method.
    """
    if isinstance(item, dict):
        return item
    # SDK objects / FakeItem have .model_dump()
    if hasattr(item, "model_dump"):
        return item.model_dump()
    # Fallback: manually read attributes
    item_type = getattr(item, "type", "unknown")
    if item_type == "message":
        # Note: we deliberately do NOT include a top-level "output_text" — that
        # is a convenience accessor on the *response*, not a valid field on an
        # input message item. The text lives inside content parts.
        return {
            "type": "message",
            "role": getattr(item, "role", "assistant"),
            "content": getattr(item, "content", []),
            "id": getattr(item, "id", ""),
        }
    elif item_type == "function_call":
        return {
            "type": "function_call",
            "name": getattr(item, "name", ""),
            "arguments": getattr(item, "arguments", "{}"),
            "call_id": getattr(item, "call_id", ""),
            "id": getattr(item, "id", ""),
        }
    else:
        return {"type": item_type, "id": getattr(item, "id", "")}


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

class Conversation:
    """Maintains the running list of input_items for the Responses API."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        """Append a user message."""
        self.messages.append({"role": "user", "content": text})

    def extend(self, output_items: list[Any]) -> None:
        """Normalize and append model output items to the transcript."""
        for item in output_items:
            self.messages.append(to_input_dict(item))

    def add_tool_result(self, call_id: str, output: str) -> None:
        """Append a function_call_output item."""
        self.messages.append({
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        })

    def to_input(self) -> list[dict]:
        """Return a copy of the messages list suitable for passing to the API."""
        return list(self.messages)

    def save(self, path: Path | str) -> None:
        """Persist conversation to a JSONL file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for msg in self.messages:
                fh.write(json.dumps(msg) + "\n")

    @classmethod
    def load(cls, path: Path | str) -> "Conversation":
        """Load conversation from a JSONL file."""
        c = cls()
        path = Path(path)
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    c.messages.append(json.loads(line))
        return c

    def __len__(self) -> int:
        return len(self.messages)

    def __repr__(self) -> str:
        return f"Conversation({len(self.messages)} messages)"
