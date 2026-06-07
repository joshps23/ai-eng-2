"""Context management: token counting, pruning, and compaction."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .llm import LLMClient

# Try importing tiktoken; fall back to heuristic
try:
    import tiktoken as _tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False

# Cache encoders per model so we don't re-resolve (and re-download) on every call.
_ENCODER_CACHE: dict[str, Any] = {}
# Once tiktoken proves it can't load an encoding (e.g. offline, blocked network),
# stop retrying the network on every call and use the heuristic instead.
_TIKTOKEN_USABLE = _TIKTOKEN_AVAILABLE


def _get_encoder(model: str) -> Any | None:
    """Return a cached tiktoken encoder for ``model``, or None if unavailable.

    tiktoken's ``encoding_for_model`` may raise ``KeyError`` for unknown models,
    but it can also raise network errors the *first* time an encoding is used
    because the vocabulary file is downloaded lazily. We catch broadly and fall
    back to a heuristic so the harness keeps working offline.
    """
    global _TIKTOKEN_USABLE
    if not _TIKTOKEN_USABLE:
        return None
    if model in _ENCODER_CACHE:
        return _ENCODER_CACHE[model]
    try:
        try:
            enc = _tiktoken.encoding_for_model(model)
        except KeyError:
            enc = _tiktoken.get_encoding("cl100k_base")
        # Force the (possibly lazy) vocabulary download to happen now so any
        # network failure is caught here, not deep inside a later .encode call.
        enc.encode("warmup")
    except Exception:
        # Any failure (network, KeyError, etc.) -> disable tiktoken for good.
        _TIKTOKEN_USABLE = False
        return None
    _ENCODER_CACHE[model] = enc
    return enc


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens in text using tiktoken if available, else ~4 chars/token heuristic."""
    enc = _get_encoder(model)
    if enc is not None:
        return len(enc.encode(text))
    # Heuristic: ~4 characters per token (good enough for budgeting).
    return max(1, len(text) // 4)


def _item_text(item: dict) -> str:
    """Extract text representation of an item for token counting."""
    return json.dumps(item)


def count_items(items: list[dict], model: str = "gpt-4o") -> int:
    """Total token count across all items."""
    total = 0
    for item in items:
        total += count_tokens(_item_text(item), model)
    return total


def prune_to_budget(
    items: list[dict],
    budget: int,
    model: str = "gpt-4o",
) -> list[dict]:
    """Prune items to fit within token budget while preserving:

    - The first user message (if any) is never dropped.
    - function_call / function_call_output pairs are kept together.
    - Recency is preferred (newer items are kept).

    Returns a new list (does not modify in place).
    """
    if not items:
        return []

    # Build a list of "groups" — each group is one or more items that must stay together
    # A function_call must be paired with its matching function_call_output
    groups: list[list[dict]] = []
    i = 0
    while i < len(items):
        item = items[i]
        if item.get("type") == "function_call":
            call_id = item.get("call_id", "")
            # Find matching output
            group = [item]
            j = i + 1
            while j < len(items):
                candidate = items[j]
                if (candidate.get("type") == "function_call_output"
                        and candidate.get("call_id") == call_id):
                    group.append(candidate)
                    # Consume everything up to and including the matched output.
                    groups.append(group)
                    i = j + 1
                    break
                j += 1
            else:
                # No matching output found — treat as standalone
                groups.append([item])
                i += 1
        else:
            groups.append([item])
            i += 1

    # Identify pinned groups (first user message)
    pinned_indices: set[int] = set()
    for gi, group in enumerate(groups):
        for item in group:
            role = item.get("role", "")
            if role == "user":
                pinned_indices.add(gi)
                break
        if pinned_indices:
            break  # only pin the very first user item

    # Count total tokens
    def group_tokens(g: list[dict]) -> int:
        return sum(count_tokens(_item_text(item), model) for item in g)

    total = sum(group_tokens(g) for g in groups)

    if total <= budget:
        return items  # nothing to prune

    # Remove groups from oldest to newest (excluding pinned)
    removable = [gi for gi in range(len(groups)) if gi not in pinned_indices]

    # Remove from the front (oldest non-pinned) until within budget
    result_groups = list(groups)
    for gi in removable:
        if total <= budget:
            break
        total -= group_tokens(result_groups[gi])
        result_groups[gi] = None  # type: ignore[call-overload]

    # Rebuild flat list
    return [item for g in result_groups if g is not None for item in g]


def compact(conversation_items: list[dict], llm: "LLMClient") -> list[dict]:
    """Summarize the older portion of a conversation via the model.

    Splits the conversation in half; summarizes the older half; returns
    [summary_message] + newer_half.

    Works with FakeClient (the summary is whatever the fake returns).
    """
    if len(conversation_items) < 4:
        return conversation_items

    mid = len(conversation_items) // 2
    older = conversation_items[:mid]
    newer = conversation_items[mid:]

    summary_prompt = (
        "Please produce a concise summary of the following conversation history. "
        "Focus on key facts, decisions, and tool results that are important for "
        "continuing the task.\n\n"
        + json.dumps(older, indent=2)
    )

    try:
        response = llm.create(
            instructions="You are a helpful summarizer.",
            input=[{"role": "user", "content": summary_prompt}],
            tools=[],
        )
        # Extract text from response
        summary_text = ""
        if hasattr(response, "output_text"):
            summary_text = response.output_text
        if not summary_text and hasattr(response, "output"):
            for item in response.output:
                if getattr(item, "type", None) == "message":
                    summary_text = getattr(item, "output_text", "") or summary_text
                    if not summary_text:
                        for part in getattr(item, "content", []):
                            if isinstance(part, dict) and part.get("type") == "output_text":
                                summary_text = part.get("text", "")
                    break
    except Exception as exc:
        summary_text = f"[Summary unavailable: {exc}]"

    summary_item: dict = {
        "role": "user",
        "content": f"[Previous conversation summary]\n{summary_text}",
    }
    return [summary_item] + list(newer)
