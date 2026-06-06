"""Unit tests for the tools subsystem."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_harness.tools.base import Tool, tool, _build_schema
from agent_harness.tools.registry import ToolRegistry
from agent_harness.tools import files as files_module
from agent_harness.tools import shell as shell_module
from agent_harness.tools.parallel import run_tool_calls


# ---------------------------------------------------------------------------
# @tool decorator and schema generation
# ---------------------------------------------------------------------------

class TestToolSchemaGeneration:
    def test_basic_types(self):
        @tool
        def my_func(name: str, count: int, ratio: float, flag: bool) -> str:
            """Do something.

            name: The name.
            count: The count.
            ratio: The ratio.
            flag: The flag.
            """
            return "ok"

        schema = my_func.parameters
        props = schema["properties"]
        assert props["name"]["type"] == "string"
        assert props["count"]["type"] == "integer"
        assert props["ratio"]["type"] == "number"
        assert props["flag"]["type"] == "boolean"

    def test_required_vs_optional(self):
        @tool
        def my_func(required_arg: str, optional_arg: str = "default") -> str:
            """Test function."""
            return "ok"

        schema = my_func.parameters
        assert "required_arg" in schema.get("required", [])
        assert "optional_arg" not in schema.get("required", [])

    def test_additional_properties_false(self):
        @tool
        def my_func(x: str) -> str:
            """Test."""
            return x

        assert my_func.parameters["additionalProperties"] is False

    def test_list_and_dict_types(self):
        @tool
        def my_func(items: list, mapping: dict) -> str:
            """Test."""
            return "ok"

        props = my_func.parameters["properties"]
        assert props["items"]["type"] == "array"
        assert props["mapping"]["type"] == "object"

    def test_tool_name_from_function(self):
        @tool
        def my_special_func(x: str) -> str:
            """Desc."""
            return x

        assert my_special_func.name == "my_special_func"

    def test_tool_name_override(self):
        @tool(name="custom_name")
        def my_func(x: str) -> str:
            """Desc."""
            return x

        assert my_func.name == "custom_name"

    def test_description_from_docstring(self):
        @tool
        def my_func(x: str) -> str:
            """This is the description."""
            return x

        assert my_func.description == "This is the description."

    def test_to_openai_schema(self):
        @tool
        def my_func(x: str) -> str:
            """Test."""
            return x

        schema = my_func.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["name"] == "my_func"
        assert "parameters" in schema
        assert schema.get("strict") is True

    def test_no_params(self):
        @tool
        def no_params_func() -> str:
            """No params."""
            return "ok"

        schema = no_params_func.parameters
        assert schema["properties"] == {}
        assert "required" not in schema or schema.get("required") == []


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()

        @tool
        def my_tool(x: str) -> str:
            """A tool."""
            return f"result: {x}"

        registry.register(my_tool)
        assert registry.get("my_tool") is my_tool
        assert "my_tool" in registry.names()

    def test_to_openai_schema(self):
        registry = ToolRegistry()

        @tool
        def tool_a(x: str) -> str:
            """Tool A."""
            return x

        registry.register(tool_a)
        schema = registry.to_openai_schema()
        assert len(schema) == 1
        assert schema[0]["name"] == "tool_a"
        assert schema[0]["type"] == "function"

    def test_dispatch_happy_path(self):
        registry = ToolRegistry()

        @tool
        def adder(a: int, b: int) -> str:
            """Add two numbers."""
            return str(a + b)

        registry.register(adder)
        result = registry.dispatch("adder", json.dumps({"a": 3, "b": 4}))
        assert result == "7"

    def test_dispatch_unknown_tool(self):
        registry = ToolRegistry()
        result = registry.dispatch("nonexistent", "{}")
        assert result.startswith("Error:")
        assert "unknown" in result.lower()

    def test_dispatch_invalid_json(self):
        registry = ToolRegistry()

        @tool
        def dummy(x: str) -> str:
            """Dummy."""
            return x

        registry.register(dummy)
        result = registry.dispatch("dummy", "not-json")
        assert result.startswith("Error:")

    def test_dispatch_missing_required_args(self):
        registry = ToolRegistry()

        @tool
        def my_func(required: str) -> str:
            """Requires required."""
            return required

        registry.register(my_func)
        result = registry.dispatch("my_func", "{}")
        assert result.startswith("Error:")
        assert "missing" in result.lower()

    def test_dispatch_exception_becomes_error_string(self):
        registry = ToolRegistry()

        @tool
        def exploding_tool(x: str) -> str:
            """Always fails."""
            raise ValueError("Boom!")

        registry.register(exploding_tool)
        result = registry.dispatch("exploding_tool", json.dumps({"x": "hi"}))
        assert result.startswith("Error:")
        assert "Boom!" in result

    def test_dispatch_never_raises(self):
        """dispatch() must NEVER propagate exceptions."""
        registry = ToolRegistry()

        @tool
        def raises_always(x: str) -> str:
            """Always raises."""
            raise RuntimeError("Should be caught")

        registry.register(raises_always)
        # This should not raise
        result = registry.dispatch("raises_always", json.dumps({"x": "test"}))
        assert "Error" in result


# ---------------------------------------------------------------------------
# File tools (in tmp workspace)
# ---------------------------------------------------------------------------

class TestFileTools:
    def setup_method(self, method):
        """Reset to a clean state."""
        pass

    def test_read_write_file(self, tmp_path):
        files_module.set_workspace(tmp_path)

        # Write a file
        write_result = files_module.write_file.run(path="hello.txt", content="Hello, world!")
        assert "Wrote" in write_result

        # Read it back
        read_result = files_module.read_file.run(path="hello.txt")
        assert read_result == "Hello, world!"

    def test_read_nonexistent(self, tmp_path):
        files_module.set_workspace(tmp_path)
        result = files_module.read_file.run(path="missing.txt")
        assert "Error" in result

    def test_edit_file(self, tmp_path):
        files_module.set_workspace(tmp_path)
        (tmp_path / "edit_me.txt").write_text("old content here", encoding="utf-8")
        result = files_module.edit_file.run(
            path="edit_me.txt",
            old_string="old content",
            new_string="new content",
        )
        assert "Edited" in result
        assert (tmp_path / "edit_me.txt").read_text() == "new content here"

    def test_edit_file_not_found(self, tmp_path):
        files_module.set_workspace(tmp_path)
        result = files_module.edit_file.run(path="nope.txt", old_string="x", new_string="y")
        assert "Error" in result

    def test_edit_file_string_not_found(self, tmp_path):
        files_module.set_workspace(tmp_path)
        (tmp_path / "f.txt").write_text("content", encoding="utf-8")
        result = files_module.edit_file.run(path="f.txt", old_string="NOTHERE", new_string="y")
        assert "Error" in result

    def test_safe_path_blocks_escape(self, tmp_path):
        files_module.set_workspace(tmp_path)
        result = files_module.read_file.run(path="/etc/passwd")
        assert "Error" in result

    def test_glob_files(self, tmp_path):
        files_module.set_workspace(tmp_path)
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.py").write_text("y", encoding="utf-8")
        (tmp_path / "c.txt").write_text("z", encoding="utf-8")
        result = files_module.glob_files.run(pattern="*.py")
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_grep(self, tmp_path):
        files_module.set_workspace(tmp_path)
        (tmp_path / "search_me.txt").write_text(
            "line one\nfoo bar baz\nline three\n", encoding="utf-8"
        )
        result = files_module.grep.run(pattern="foo", path=".")
        assert "foo bar baz" in result

    def test_list_dir(self, tmp_path):
        files_module.set_workspace(tmp_path)
        (tmp_path / "file1.txt").write_text("", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        result = files_module.list_dir.run(path=".")
        assert "file1.txt" in result
        assert "subdir" in result


# ---------------------------------------------------------------------------
# Bash tool
# ---------------------------------------------------------------------------

class TestBashTool:
    def test_echo(self, tmp_path):
        shell_module.set_workspace(tmp_path)
        result = shell_module.bash.run(command="echo hello")
        assert "hello" in result

    def test_exit_code_appended(self, tmp_path):
        shell_module.set_workspace(tmp_path)
        result = shell_module.bash.run(command="exit 1")
        assert "exit code: 1" in result

    def test_timeout(self, tmp_path):
        shell_module.set_workspace(tmp_path)
        result = shell_module.bash.run(command="sleep 100", timeout=1)
        assert "Error" in result.lower() or "timed out" in result.lower()


# ---------------------------------------------------------------------------
# Parallel tool execution
# ---------------------------------------------------------------------------

class TestParallelToolCalls:
    def test_basic_parallel(self):
        registry = ToolRegistry()

        @tool
        def echo_tool(msg: str) -> str:
            """Echo a message."""
            return msg

        registry.register(echo_tool)

        calls = [
            {"call_id": "c1", "name": "echo_tool", "arguments": json.dumps({"msg": "hello"})},
            {"call_id": "c2", "name": "echo_tool", "arguments": json.dumps({"msg": "world"})},
        ]
        results = run_tool_calls(registry, calls, max_workers=2)
        assert len(results) == 2
        by_id = {r["call_id"]: r["output"] for r in results}
        assert by_id["c1"] == "hello"
        assert by_id["c2"] == "world"

    def test_parallel_preserves_order(self):
        registry = ToolRegistry()

        @tool
        def identity(val: str) -> str:
            """Return val."""
            return val

        registry.register(identity)

        calls = [
            {"call_id": f"c{i}", "name": "identity", "arguments": json.dumps({"val": str(i)})}
            for i in range(5)
        ]
        results = run_tool_calls(registry, calls, max_workers=3)
        assert [r["call_id"] for r in results] == [f"c{i}" for i in range(5)]

    def test_parallel_isolates_errors(self):
        registry = ToolRegistry()

        @tool
        def sometimes_fails(x: str) -> str:
            """Fails if x == 'fail'."""
            if x == "fail":
                raise RuntimeError("intentional failure")
            return x

        registry.register(sometimes_fails)

        calls = [
            {"call_id": "ok", "name": "sometimes_fails", "arguments": json.dumps({"x": "good"})},
            {"call_id": "bad", "name": "sometimes_fails", "arguments": json.dumps({"x": "fail"})},
        ]
        results = run_tool_calls(registry, calls, max_workers=2)
        by_id = {r["call_id"]: r["output"] for r in results}
        assert by_id["ok"] == "good"
        assert "Error" in by_id["bad"]
