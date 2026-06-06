"""Tests for the Agent loop using FakeClient (no real API)."""
from __future__ import annotations

import json

import pytest

from agent_harness.agent import Agent
from agent_harness.config import Settings
from agent_harness.llm import LLMClient
from agent_harness.tools import ToolRegistry, tool
from agent_harness.testing import FakeClient, fake_message, fake_function_call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_llm(client: FakeClient, model: str = "gpt-4o") -> LLMClient:
    return LLMClient(client=client, model=model)


def make_settings(**kwargs) -> Settings:
    defaults = dict(
        model="gpt-4o",
        max_iterations=10,
        permission_mode="always_allow",
        max_context_tokens=0,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Basic agent loop
# ---------------------------------------------------------------------------

class TestAgentLoop:
    def test_single_turn_no_tools(self):
        """Agent returns text when there are no function calls."""
        client = FakeClient([[fake_message("Hello there!")]])
        llm = make_llm(client)
        agent = Agent(
            instructions="Be helpful.",
            registry=ToolRegistry(),
            llm=llm,
            settings=make_settings(),
        )
        result = agent.run("Say hi")
        assert result == "Hello there!"

    def test_tool_call_then_final_answer(self):
        """Agent calls a tool and uses the result in a final answer."""
        @tool
        def get_value(key: str) -> str:
            """Get a value by key."""
            return f"value_of_{key}"

        registry = ToolRegistry()
        registry.register(get_value)

        client = FakeClient([
            # Turn 1: model requests the tool
            [fake_function_call("get_value", {"key": "x"}, call_id="call_1")],
            # Turn 2: model produces final answer after seeing tool result
            [fake_message("The value is: value_of_x")],
        ])
        llm = make_llm(client)
        agent = Agent(
            instructions="Use the tools.",
            registry=registry,
            llm=llm,
            settings=make_settings(),
        )
        result = agent.run("What is the value of x?")
        assert result == "The value is: value_of_x"

    def test_transcript_contains_function_call_output(self):
        """The conversation transcript must contain a function_call_output with matching call_id."""
        @tool
        def my_tool(x: str) -> str:
            """A tool."""
            return f"done:{x}"

        registry = ToolRegistry()
        registry.register(my_tool)

        call_id = "unique_call_abc"
        client = FakeClient([
            [fake_function_call("my_tool", {"x": "hello"}, call_id=call_id)],
            [fake_message("Finished")],
        ])
        llm = make_llm(client)
        agent = Agent(
            instructions="Use tools.",
            registry=registry,
            llm=llm,
            settings=make_settings(),
        )
        agent.run("Do the thing")

        # Find function_call_output in transcript
        messages = agent.conversation.messages
        fc_outputs = [
            m for m in messages
            if isinstance(m, dict) and m.get("type") == "function_call_output"
        ]
        assert len(fc_outputs) >= 1
        matching = [m for m in fc_outputs if m.get("call_id") == call_id]
        assert len(matching) == 1
        assert matching[0]["output"] == "done:hello"

    def test_max_iterations_cap(self):
        """Agent stops after max_iterations and returns an error message."""
        @tool
        def infinite_tool(x: str) -> str:
            """Always requests another call."""
            return x

        registry = ToolRegistry()
        registry.register(infinite_tool)

        # Script 5 turns all returning function_calls
        turns = [
            [fake_function_call("infinite_tool", {"x": "loop"}, call_id=f"c{i}")]
            for i in range(5)
        ]
        client = FakeClient(turns)
        llm = make_llm(client)
        settings = make_settings(max_iterations=3)
        agent = Agent(
            instructions="Loop forever.",
            registry=registry,
            llm=llm,
            settings=settings,
        )
        result = agent.run("Start")
        assert "max iterations" in result.lower() or "error" in result.lower()

    def test_multiple_tool_calls_in_one_turn(self):
        """Multiple function_calls in one turn are all dispatched."""
        results_seen = []

        @tool
        def recorder(msg: str) -> str:
            """Record a message."""
            results_seen.append(msg)
            return f"recorded:{msg}"

        registry = ToolRegistry()
        registry.register(recorder)

        client = FakeClient([
            # Turn 1: two function calls at once
            [
                fake_function_call("recorder", {"msg": "first"}, call_id="c1"),
                fake_function_call("recorder", {"msg": "second"}, call_id="c2"),
            ],
            # Turn 2: final answer
            [fake_message("Both recorded.")],
        ])
        llm = make_llm(client)
        agent = Agent(
            instructions="Record things.",
            registry=registry,
            llm=llm,
            settings=make_settings(),
        )
        result = agent.run("Record both")
        assert result == "Both recorded."
        assert set(results_seen) == {"first", "second"}

    def test_unknown_tool_becomes_error_result(self):
        """Calling an unregistered tool becomes a tool-result error, not an exception."""
        client = FakeClient([
            [fake_function_call("nonexistent_tool", {"x": "y"}, call_id="c1")],
            [fake_message("Handled the error")],
        ])
        llm = make_llm(client)
        agent = Agent(
            instructions=".",
            registry=ToolRegistry(),
            llm=llm,
            settings=make_settings(),
        )
        # Should not raise
        result = agent.run("Try something")
        # Error became a tool-result string
        messages = agent.conversation.messages
        fc_output = next(
            (m for m in messages if isinstance(m, dict) and m.get("type") == "function_call_output"),
            None,
        )
        assert fc_output is not None
        assert "Error" in fc_output["output"]


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_permission_deny_becomes_tool_result_string(self):
        """When permission is denied, it becomes a tool-result error string."""
        @tool
        def secret_tool(x: str) -> str:
            """Should be blocked."""
            return "you shouldn't see this"

        registry = ToolRegistry()
        registry.register(secret_tool)

        client = FakeClient([
            [fake_function_call("secret_tool", {"x": "hi"}, call_id="c1")],
            [fake_message("Permission was denied")],
        ])
        llm = make_llm(client)
        # Use 'plan' mode which denies write tools — but secret_tool is read-only.
        # Use 'auto' mode with an asker that always denies.
        settings = make_settings(permission_mode="auto")
        deny_all = lambda prompt: False  # always deny

        agent = Agent(
            instructions=".",
            registry=registry,
            llm=llm,
            settings=settings,
            asker=deny_all,
        )
        # Should NOT raise
        result = agent.run("Do the thing")

        # The function_call_output should be an error string about permission
        messages = agent.conversation.messages
        fc_output = next(
            (m for m in messages
             if isinstance(m, dict) and m.get("type") == "function_call_output"),
            None,
        )
        assert fc_output is not None
        assert "permission" in fc_output["output"].lower() or "Error" in fc_output["output"]

    def test_always_allow_mode_permits_all(self, auto_approver):
        """always_allow mode lets all tools through."""
        @tool
        def write_tool(content: str) -> str:
            """Write something."""
            return f"wrote:{content}"

        registry = ToolRegistry()
        registry.register(write_tool)

        client = FakeClient([
            [fake_function_call("write_tool", {"content": "data"}, call_id="c1")],
            [fake_message("Done")],
        ])
        llm = make_llm(client)
        settings = make_settings(permission_mode="always_allow")
        agent = Agent(
            instructions=".",
            registry=registry,
            llm=llm,
            settings=settings,
            asker=auto_approver,
        )
        result = agent.run("Write stuff")
        assert result == "Done"

        # Check that the tool actually ran (output is the tool result, not error)
        messages = agent.conversation.messages
        fc_output = next(
            (m for m in messages if isinstance(m, dict) and m.get("type") == "function_call_output"),
            None,
        )
        assert fc_output is not None
        assert fc_output["output"] == "wrote:data"


# ---------------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------------

class TestUsageAccounting:
    def test_usage_is_accumulated(self):
        """Agent accumulates token usage across turns."""
        client = FakeClient([
            [fake_message("Turn 1")],
        ])
        # FakeUsage defaults: 10 input, 20 output, 30 total
        llm = make_llm(client)
        agent = Agent(
            instructions=".",
            registry=ToolRegistry(),
            llm=llm,
            settings=make_settings(),
        )
        agent.run("Hello")
        assert agent.usage.total_tokens >= 30
