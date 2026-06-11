"""CLI entry point for the agent harness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agent-harness",
        description="LLM Agent Harness — powered by the OpenAI Responses API",
    )
    parser.add_argument(
        "-p", "--prompt",
        metavar="PROMPT",
        help="Run a single prompt (one-shot mode) and exit",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["plan", "auto", "accept_edits", "always_allow", "bypass"],
        help="Permission mode (default: auto)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="OpenAI model to use (default: gpt-4o)",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root directory (default: current directory)",
    )
    parser.add_argument(
        "--resume",
        metavar="FILE",
        help="Resume from a saved conversation JSONL file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra debug information",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=50,
        help="Maximum agent iterations per task (default: 50)",
    )

    args = parser.parse_args()

    # Build settings
    from .config import Settings
    workspace = Path(args.workspace) if args.workspace else Path.cwd()
    settings = Settings(
        model=args.model,
        max_iterations=args.max_iterations,
        permission_mode=args.mode,
        workspace_root=workspace,
    )

    # Configure workspace for file/shell tools
    from .tools import files, shell
    from .tools.files import set_workspace as set_file_workspace
    from .tools.shell import set_workspace as set_shell_workspace
    set_file_workspace(workspace)
    set_shell_workspace(workspace)

    # Build default tool registry
    from .tools import ToolRegistry
    from .tools.files import read_file, write_file, edit_file, glob_files, grep, list_dir
    from .tools.shell import bash

    registry = ToolRegistry()
    for t in [read_file, write_file, edit_file, glob_files, grep, list_dir, bash]:
        registry.register(t)

    # Build LLM client
    from .llm import LLMClient
    try:
        from openai import OpenAI
        client = OpenAI()
    except Exception as exc:
        print(f"Error: could not create OpenAI client: {exc}", file=sys.stderr)
        print(
            "The CLI needs a real API key (set the OPENAI_API_KEY environment "
            "variable). No key is needed for the tests — see FAQ.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    llm = LLMClient(client=client, model=args.model)

    # Build sub-agent task tool and add to registry
    from .subagents import make_task_tool
    task_tool = make_task_tool(settings, llm, registry)
    registry.register(task_tool)

    # Interactive asker
    def _asker(prompt: str) -> bool:
        try:
            answer = input(prompt).strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    # Build agent
    from .agent import Agent
    agent = Agent(
        name="cli-agent",
        instructions=(
            "You are a helpful assistant with access to the local filesystem "
            "and shell. Be concise and accurate."
        ),
        registry=registry,
        llm=llm,
        settings=settings,
        asker=_asker,
    )

    # Resume conversation if requested
    if args.resume:
        try:
            from .conversation import Conversation
            agent.conversation = Conversation.load(args.resume)
            print(f"Resumed from {args.resume} ({len(agent.conversation)} messages)")
        except Exception as exc:
            print(f"Warning: could not resume from {args.resume}: {exc}", file=sys.stderr)

    # One-shot mode
    if args.prompt:
        result = agent.run(args.prompt)
        print(result)
        if args.verbose:
            print(f"\n[{agent.usage}]", file=sys.stderr)
        return

    # Interactive REPL
    print("Agent Harness — interactive mode. Type /help for commands, Ctrl-D to exit.")
    print(f"Model: {args.model} | Mode: {args.mode} | Workspace: {workspace}")
    print()

    def _handle_slash(cmd: str) -> bool:
        """Handle slash commands. Returns True if handled."""
        parts = cmd.split(None, 1)
        command = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            print(
                "Slash commands:\n"
                "  /help              Show this help\n"
                "  /clear             Clear conversation\n"
                "  /compact           Summarize old conversation\n"
                "  /cost              Show token usage\n"
                "  /tools             List available tools\n"
                "  /mode <mode>       Change permission mode\n"
                "  /save <file>       Save conversation to file\n"
                "  /resume <file>     Load conversation from file\n"
            )
        elif command == "/clear":
            from .conversation import Conversation
            agent.conversation = Conversation()
            print("Conversation cleared.")
        elif command == "/compact":
            from .context import compact
            agent.conversation.messages = compact(agent.conversation.messages, llm)
            print(f"Compacted to {len(agent.conversation)} messages.")
        elif command == "/cost":
            print(agent.usage)
        elif command == "/tools":
            names = registry.names()
            print(f"Available tools ({len(names)}): {', '.join(names)}")
        elif command == "/mode":
            if rest:
                settings.permission_mode = rest.strip()
                print(f"Permission mode set to: {settings.permission_mode}")
            else:
                print(f"Current mode: {settings.permission_mode}")
        elif command == "/save":
            if rest:
                agent.conversation.save(rest.strip())
                print(f"Saved to {rest.strip()}")
            else:
                print("Usage: /save <filename>")
        elif command == "/resume":
            if rest:
                try:
                    from .conversation import Conversation
                    agent.conversation = Conversation.load(rest.strip())
                    print(f"Loaded from {rest.strip()}")
                except Exception as exc:
                    print(f"Error: {exc}")
            else:
                print("Usage: /resume <filename>")
        else:
            return False
        return True

    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if not _handle_slash(user_input):
                print(f"Unknown command: {user_input}. Type /help for help.")
            continue

        try:
            result = agent.run(user_input)
            print(f"\nAgent> {result}\n")
            if args.verbose:
                print(f"[{agent.usage}]", file=sys.stderr)
        except KeyboardInterrupt:
            print("\n[Interrupted]")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
