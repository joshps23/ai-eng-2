"""Tests for context management: token counting, pruning, and compaction."""
from __future__ import annotations

import pytest

from agent_harness.context import count_tokens, count_items, prune_to_budget, compact
from agent_harness.llm import LLMClient
from agent_harness.testing import FakeClient, fake_message


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

class TestCountTokens:
    def test_empty_string(self):
        # Should return at least 1 (heuristic)
        result = count_tokens("")
        assert result >= 0

    def test_heuristic_proportional(self):
        short = count_tokens("hello")
        long = count_tokens("hello " * 100)
        assert long > short

    def test_returns_integer(self):
        result = count_tokens("test string here")
        assert isinstance(result, int)
        assert result > 0

    def test_count_items(self):
        items = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi there"},
        ]
        total = count_items(items)
        assert total > 0
        assert isinstance(total, int)


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

class TestPruneTobudget:
    def _make_items(self, n: int) -> list[dict]:
        """Create a list of n alternating user/assistant messages."""
        items = []
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            items.append({"role": role, "content": f"Message {i}: " + "x" * 100})
        return items

    def test_no_pruning_within_budget(self):
        items = self._make_items(3)
        budget = count_items(items) + 1000
        result = prune_to_budget(items, budget)
        assert result == items

    def test_prunes_to_fit_budget(self):
        items = self._make_items(20)
        # Set a very small budget to force pruning
        small_budget = count_items(items[:3])
        result = prune_to_budget(items, small_budget)
        assert len(result) < len(items)

    def test_preserves_recency(self):
        """Newer items should be kept over older ones."""
        items = [
            {"role": "user", "content": "FIRST " + "x" * 200},
            {"role": "assistant", "content": "second " + "x" * 200},
            {"role": "user", "content": "third " + "x" * 200},
            {"role": "assistant", "content": "LAST " + "x" * 200},
        ]
        # Budget that fits about 2 items
        budget = count_items(items[:2]) + 50
        result = prune_to_budget(items, budget)
        # The last item should still be present
        contents = [m.get("content", "") for m in result]
        assert any("LAST" in c for c in contents)

    def test_preserves_function_call_pairs(self):
        """function_call and its function_call_output must be kept together."""
        items = [
            {"role": "user", "content": "start"},
            {"type": "function_call", "name": "my_tool", "call_id": "c1", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "result"},
            {"role": "assistant", "content": "done " + "x" * 500},
        ]
        # Budget that might drop some items
        budget = count_items(items) - count_items([items[0]])
        result = prune_to_budget(items, budget)

        # If function_call is present, its output must also be present
        fc_items = [m for m in result if isinstance(m, dict) and m.get("type") == "function_call"]
        fc_outputs = [m for m in result if isinstance(m, dict) and m.get("type") == "function_call_output"]

        for fc in fc_items:
            call_id = fc["call_id"]
            matching_outputs = [o for o in fc_outputs if o["call_id"] == call_id]
            assert len(matching_outputs) >= 1, f"function_call {call_id} has no matching output"

    def test_empty_list(self):
        result = prune_to_budget([], 1000)
        assert result == []

    def test_never_drops_first_user_message(self):
        """The very first user message must not be dropped."""
        items = [
            {"role": "user", "content": "ANCHOR"},
        ]
        # Add many more messages
        for i in range(10):
            items.append({"role": "assistant", "content": "x" * 200})

        # Very small budget
        budget = 10
        result = prune_to_budget(items, budget)
        contents = [m.get("content", "") for m in result]
        assert any("ANCHOR" in c for c in contents)


# ---------------------------------------------------------------------------
# compact()
# ---------------------------------------------------------------------------

class TestCompact:
    def test_compact_reduces_length(self):
        """compact() should return fewer items than the original."""
        items = []
        for i in range(10):
            items.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"})

        client = FakeClient([[fake_message("This is a summary of the old conversation.")]])
        llm = LLMClient(client=client, model="gpt-4o")

        result = compact(items, llm)
        # Should be shorter (summary + newer half)
        assert len(result) < len(items)

    def test_compact_preserves_newer_items(self):
        """compact() should preserve the newer portion of the conversation."""
        items = []
        for i in range(8):
            items.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg_{i}"})

        mid = len(items) // 2
        newer_content = [m["content"] for m in items[mid:]]

        client = FakeClient([[fake_message("Summary of old stuff.")]])
        llm = LLMClient(client=client, model="gpt-4o")

        result = compact(items, llm)
        result_content = [m.get("content", "") for m in result]

        for nc in newer_content:
            assert any(nc in rc for rc in result_content), f"'{nc}' missing from compacted result"

    def test_compact_short_conversation_unchanged(self):
        """Very short conversations should not be compacted."""
        items = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        client = FakeClient([])
        llm = LLMClient(client=client, model="gpt-4o")
        result = compact(items, llm)
        assert result == items

    def test_compact_includes_summary_item(self):
        """The compacted result should contain a summary item."""
        items = [
            {"role": "user", "content": f"message {i}" + " x" * 50}
            for i in range(8)
        ]
        client = FakeClient([[fake_message("Summary: key points here.")]])
        llm = LLMClient(client=client, model="gpt-4o")
        result = compact(items, llm)

        # Should contain a summary marker
        all_content = " ".join(str(m.get("content", "")) for m in result)
        assert "summary" in all_content.lower() or "Summary" in all_content
