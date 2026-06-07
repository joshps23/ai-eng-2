"""FakeClient for offline testing — no real OpenAI API needed."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Fake output items
# ---------------------------------------------------------------------------

@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20
    total_tokens: int = 30


@dataclass
class FakeItem:
    """Mimics an SDK output item with both attribute access and .model_dump()."""

    type: str
    # For message items
    content: list[dict] = field(default_factory=list)
    output_text: str = ""
    # For function_call items
    name: str = ""
    arguments: str = "{}"
    call_id: str = ""
    id: str = ""

    def model_dump(self) -> dict:
        if self.type == "message":
            # Mirror the real SDK: the dumped input item has no top-level
            # "output_text" (that's a response-level accessor only).
            return {
                "type": "message",
                "role": "assistant",
                "content": self.content,
                "id": self.id,
            }
        elif self.type == "function_call":
            return {
                "type": "function_call",
                "name": self.name,
                "arguments": self.arguments,
                "call_id": self.call_id,
                "id": self.id,
            }
        else:
            return {"type": self.type, "id": self.id}


@dataclass
class FakeResponse:
    """Mimics the object returned by client.responses.create()."""

    output: list[FakeItem] = field(default_factory=list)
    usage: FakeUsage = field(default_factory=FakeUsage)
    id: str = "resp_fake"

    @property
    def output_text(self) -> str:
        texts = []
        for item in self.output:
            if item.type == "message":
                if item.output_text:
                    texts.append(item.output_text)
                else:
                    for part in item.content:
                        if isinstance(part, dict) and part.get("type") == "output_text":
                            texts.append(part.get("text", ""))
        return "\n".join(texts)


# ---------------------------------------------------------------------------
# Scripted FakeClient
# ---------------------------------------------------------------------------

class _FakeResponses:
    """Mimics client.responses namespace."""

    def __init__(self, turns: list[list[FakeItem]]) -> None:
        self._turns = list(turns)
        self._call_count = 0

    def create(self, *, model: str, instructions: str, input: list, tools: list | None = None, **kwargs) -> FakeResponse:
        if not self._turns:
            raise RuntimeError("FakeClient: no more scripted turns")
        items = self._turns.pop(0)
        self._call_count += 1
        return FakeResponse(output=items)


class FakeClient:
    """Drop-in replacement for openai.OpenAI() for testing.

    Construct with a list of "turns"; each turn is a list of FakeItem objects
    (or use the helper builders). On each call to responses.create(), the next
    turn is returned.

    Example::

        client = FakeClient([
            [fake_function_call("read_file", {"path": "foo.txt"}, "call_1")],
            [fake_message("Done!")],
        ])
    """

    def __init__(self, turns: list[list[FakeItem]]) -> None:
        self.responses = _FakeResponses(turns)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def fake_message(text: str, id: str = "msg_fake") -> FakeItem:
    """Build a FakeItem representing a text message."""
    return FakeItem(
        type="message",
        output_text=text,
        content=[{"type": "output_text", "text": text}],
        id=id,
    )


def fake_function_call(name: str, args_dict: dict, call_id: str, id: str = "fc_fake") -> FakeItem:
    """Build a FakeItem representing a function_call."""
    return FakeItem(
        type="function_call",
        name=name,
        arguments=json.dumps(args_dict),
        call_id=call_id,
        id=id,
    )
