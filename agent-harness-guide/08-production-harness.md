# Phase 8 — The Production Harness: Assembling Claude Code

You have built every organ of the system. Phase 2 gave you tools and parallel dispatch. Phase 3 gave you conversation persistence and streaming. Phase 4 gave you real filesystem and shell tools. Phase 5 gave you permissions and hooks. Phase 6 gave you token budgeting and compaction. Phase 7 gave you agent orchestration and sub-agents.

This phase wires all of that into a harness you could ship: reliable under network chaos, observable when something goes wrong, configurable without code edits, and pleasant to use from a terminal. The gap between a weekend demo and a production coding agent is almost entirely about these properties. We will close that gap, component by component.

---

## 1. What Separates a Demo from a Production Harness

A demo works when the network is fast, the model cooperates on the first try, no file is large, and you are watching. A production harness must handle:

| Property | What it means in practice |
|---|---|
| **Reliability** | Automatic retry on transient failures; clean Ctrl-C; crash-resumable transcripts |
| **Observability** | Every turn logged with tokens, latency, tool calls; JSONL trace; cost accounting |
| **Configuration** | Env vars + CLI flags + project file; no magic constants buried in source |
| **System prompt engineering** | Instructions that shape behavior the same way Claude Code's do |
| **CLI / REPL** | Slash-commands, streamed output, one-shot `-p` mode for CI |
| **Correct middleware order** | Budget → stream → hooks → permission → execute → trace → persist |
| **Packaging** | Installable, `pyproject.toml`, console-script entry point |
| **Testability** | Fake client, scripted tool calls, deterministic assertions |

Each section below is a self-contained module. All of them plug into `agent_harness/`.

---

## 2. Reliability

### 2.1 The Resilient LLM Wrapper — `llm.py`

The OpenAI client raises typed exceptions. Map them to a retry policy once, here, so no other file ever sees retry logic.

```python
# agent_harness/llm.py
"""
Thin resilient wrapper around client.responses.create / .stream.

Retryable:
  - RateLimitError (429)           — honour Retry-After header when present
  - APIConnectionError             — network blip
  - InternalServerError (5xx)      — transient backend fault
  - APIStatusError with status>=500

Fatal (raise immediately):
  - AuthenticationError (401)
  - PermissionDeniedError (403)
  - NotFoundError (404)
  - UnprocessableEntityError (422) — our payload is wrong
  - Any other 4xx
"""

from __future__ import annotations

import logging
import random
import time
from contextlib import contextmanager
from typing import Any, Generator

import openai
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_BASE_DELAY = 1.0      # seconds
DEFAULT_MAX_DELAY = 60.0      # seconds
DEFAULT_JITTER = 0.25         # fraction of computed delay added randomly


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (RateLimitError, APIConnectionError, InternalServerError)):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return True
    return False


def _retry_after(exc: Exception) -> float | None:
    """Return the Retry-After value in seconds if present, else None."""
    if isinstance(exc, RateLimitError):
        headers = getattr(exc, "response", None)
        if headers is not None:
            raw = headers.headers.get("retry-after")
            if raw is not None:
                try:
                    return float(raw)
                except ValueError:
                    pass
    return None


def _backoff(attempt: int, base: float, cap: float, jitter: float) -> float:
    delay = min(base * (2 ** attempt), cap)
    delay += delay * jitter * random.random()
    return delay


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create(
    client: OpenAI,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float = DEFAULT_JITTER,
    **kwargs: Any,
) -> Any:
    """
    Call client.responses.create(**kwargs) with retry + backoff.

    Passes **kwargs straight through so callers can set any parameter
    (model, input, instructions, tools, store, etc.).
    """
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return client.responses.create(**kwargs)

        except (AuthenticationError, PermissionDeniedError,
                NotFoundError, UnprocessableEntityError) as exc:
            # Fatal — bad credentials, wrong model name, bad payload
            log.error("Fatal API error (not retrying): %s", exc)
            raise

        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc):
                log.error("Non-retryable error: %s", exc)
                raise

            wait = _retry_after(exc) or _backoff(attempt, base_delay, max_delay, jitter)
            log.warning(
                "Retryable error on attempt %d/%d (%s). Sleeping %.1fs.",
                attempt + 1, max_attempts, type(exc).__name__, wait,
            )
            time.sleep(wait)

    # Exhausted all attempts
    raise RuntimeError(
        f"API call failed after {max_attempts} attempts"
    ) from last_exc


@contextmanager
def stream(
    client: OpenAI,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float = DEFAULT_JITTER,
    **kwargs: Any,
) -> Generator[Any, None, None]:
    """
    Context manager: yields a streaming response with the same retry policy.
    Because streaming errors often surface only after the first chunk,
    we retry at the connection / open stage. Mid-stream errors propagate as-is.
    """
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            with client.responses.stream(**kwargs) as s:
                yield s
            return  # clean exit from context manager

        except (AuthenticationError, PermissionDeniedError,
                NotFoundError, UnprocessableEntityError) as exc:
            log.error("Fatal API error (stream, not retrying): %s", exc)
            raise

        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc):
                raise

            wait = _retry_after(exc) or _backoff(attempt, base_delay, max_delay, jitter)
            log.warning(
                "Stream retryable error attempt %d/%d (%s). Sleeping %.1fs.",
                attempt + 1, max_attempts, type(exc).__name__, wait,
            )
            time.sleep(wait)

    raise RuntimeError(
        f"Streaming API call failed after {max_attempts} attempts"
    ) from last_exc
```

Call sites replace bare `client.responses.create(...)` with `llm.create(client, ...)` and `client.responses.stream(...)` with `llm.stream(client, ...)`.

### 2.2 Timeouts and KeyboardInterrupt Handling

A long-running turn should not lock up the REPL. Wrap each turn in a try/except for `KeyboardInterrupt` and let the thread finish cleanly:

```python
# Inside the REPL turn handler (see cli.py section)
try:
    agent.run_turn(user_text)
except KeyboardInterrupt:
    print("\n[Turn cancelled. Transcript preserved. Type your next message.]")
    # The agent's input_items list is still valid — the partial turn was
    # never committed because we always append *after* a successful response.
```

The key invariant: **append to `input_items` only after success**. If we crash mid-turn, the transcript stays at the last clean state and the next turn re-runs cleanly.

For the OpenAI client specifically, you can also set a per-request timeout:

```python
response = llm.create(
    client,
    model=MODEL,
    instructions=instructions,
    input=input_items,
    tools=tool_schemas,
    timeout=120,          # httpx timeout in seconds, passed through
)
```

### 2.3 Idempotency and Crash Resumability

From Phase 3, `Conversation.save(path)` serialises `input_items` to JSON. Call it after every step:

```python
# At the bottom of each loop iteration, before sleeping/continuing:
conversation.save(settings.transcript_path)
```

The CLI exposes `--resume`:

```bash
agent --resume                      # loads from default transcript path
agent --resume --transcript foo.json  # loads from explicit path
```

On resume, the harness loads the transcript and prints a one-line summary (`"Resuming from N messages, last saved at <timestamp>"`), then drops straight back into the REPL. No special bookkeeping required: the transcript _is_ the state.

---

## 3. Observability

### 3.1 Structured Logging

Use stdlib `logging` throughout. Configure it once at startup:

```python
# agent_harness/logging_config.py
import logging
import sys

def configure_logging(level: str = "WARNING") -> None:
    """
    level: "DEBUG", "INFO", "WARNING", "ERROR"
    DEBUG  — full request/response bodies (very verbose)
    INFO   — turn summaries, tool calls, durations
    WARNING — retries and recoverable errors only (default)
    ERROR  — fatal errors only
    """
    numeric = getattr(logging, level.upper(), logging.WARNING)
    logging.basicConfig(
        stream=sys.stderr,
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence the httpx chattiness unless we're in DEBUG
    if numeric > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
```

Inside `Agent.run_turn` (Phase 7) add structured INFO logs:

```python
log = logging.getLogger(__name__)

# At turn start:
t0 = time.monotonic()
log.info("turn_start input_messages=%d", len(self.input_items))

# After response arrives:
elapsed = time.monotonic() - t0
log.info(
    "turn_end tokens_in=%d tokens_out=%d total=%d elapsed=%.2fs",
    resp.usage.input_tokens,
    resp.usage.output_tokens,
    resp.usage.total_tokens,
    elapsed,
)

# For each tool call:
log.info("tool_call name=%s call_id=%s", item.name, item.call_id)

# For each tool result:
log.info(
    "tool_result call_id=%s ok=%s preview=%.80r",
    call_id,
    not result.startswith("Error"),
    result,
)
```

### 3.2 The JSONL Tracer

A machine-readable event log is invaluable for post-hoc debugging and cost audits.

```python
# agent_harness/tracer.py
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class Tracer:
    """
    Appends one JSON object per event to a .jsonl file.

    Event types:
      session_start    — harness boot
      turn_start       — new LLM call begins
      turn_end         — LLM response received (includes usage)
      tool_call        — tool about to be executed
      tool_result      — tool returned
      permission_decision — approved / denied / escalated
      compaction       — context window pruned
      error            — any caught exception
      session_end      — clean exit with aggregate stats
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._session_id = f"{int(time.time())}"

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        record = {
            "ts": time.time(),
            "session": self._session_id,
            "event": event_type,
            **data,
        }
        if self._path:
            try:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            except OSError as exc:
                log.warning("Tracer write failed: %s", exc)
        log.debug("trace %s %s", event_type, data)

    # ------------------------------------------------------------------
    # Convenience emitters
    # ------------------------------------------------------------------

    def session_start(self, settings_dict: dict[str, Any]) -> None:
        self._emit("session_start", {"settings": settings_dict})

    def turn_start(self, turn: int, n_messages: int) -> None:
        self._emit("turn_start", {"turn": turn, "n_messages": n_messages})

    def turn_end(
        self,
        turn: int,
        input_tokens: int,
        output_tokens: int,
        elapsed: float,
        stop_reason: str,
    ) -> None:
        self._emit(
            "turn_end",
            {
                "turn": turn,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "elapsed_s": round(elapsed, 3),
                "stop_reason": stop_reason,
            },
        )

    def tool_call(self, turn: int, name: str, call_id: str, args: dict) -> None:
        self._emit(
            "tool_call",
            {"turn": turn, "name": name, "call_id": call_id, "args": args},
        )

    def tool_result(
        self, turn: int, name: str, call_id: str, ok: bool, preview: str
    ) -> None:
        self._emit(
            "tool_result",
            {
                "turn": turn,
                "name": name,
                "call_id": call_id,
                "ok": ok,
                "preview": preview[:200],
            },
        )

    def permission_decision(
        self, turn: int, name: str, decision: str, reason: str = ""
    ) -> None:
        self._emit(
            "permission_decision",
            {"turn": turn, "name": name, "decision": decision, "reason": reason},
        )

    def compaction(self, turn: int, before: int, after: int) -> None:
        self._emit(
            "compaction",
            {"turn": turn, "tokens_before": before, "tokens_after": after},
        )

    def error(self, turn: int, exc_type: str, message: str) -> None:
        self._emit(
            "error", {"turn": turn, "exc_type": exc_type, "message": message}
        )

    def session_end(self, stats: dict[str, Any]) -> None:
        self._emit("session_end", {"stats": stats})
```

### 3.3 Cost and Token Accounting

Track usage across turns (and across sub-agents spawned in Phase 7):

```python
# agent_harness/accounting.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Prices in USD per 1 000 000 tokens (as of mid-2025, adjust as needed)
DEFAULT_PRICE_TABLE: dict[str, dict[str, float]] = {
    "gpt-5":           {"input": 10.00,  "output": 30.00},
    "gpt-4.1":         {"input": 2.00,   "output": 8.00},
    "gpt-4.1-mini":    {"input": 0.40,   "output": 1.60},
    "gpt-4o":          {"input": 2.50,   "output": 10.00},
    "o3":              {"input": 10.00,  "output": 40.00},
    "o4-mini":         {"input": 1.10,   "output": 4.40},
}


@dataclass
class SessionAccounting:
    model: str
    price_table: dict[str, dict[str, float]] = field(
        default_factory=lambda: DEFAULT_PRICE_TABLE
    )
    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
    tool_calls: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def record_turn(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.turns += 1

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def cost_usd(self) -> float:
        prices = self.price_table.get(self.model, {"input": 0.0, "output": 0.0})
        return (
            self.input_tokens  * prices["input"]  / 1_000_000
            + self.output_tokens * prices["output"] / 1_000_000
        )

    def summary(self) -> dict[str, Any]:
        return {
            "model":         self.model,
            "turns":         self.turns,
            "tool_calls":    self.tool_calls,
            "input_tokens":  self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens":  self.total_tokens,
            "cost_usd":      round(self.cost_usd(), 6),
            "elapsed_s":     round(self.elapsed_seconds, 1),
        }

    def print_summary(self) -> None:
        s = self.summary()
        print(
            f"\n── Session Summary ──────────────────────────────────\n"
            f"  Model:         {s['model']}\n"
            f"  Turns:         {s['turns']}   Tool calls: {s['tool_calls']}\n"
            f"  Input tokens:  {s['input_tokens']:,}\n"
            f"  Output tokens: {s['output_tokens']:,}\n"
            f"  Total tokens:  {s['total_tokens']:,}\n"
            f"  Estimated cost: ${s['cost_usd']:.4f} USD\n"
            f"  Wall time:     {s['elapsed_s']:.1f}s\n"
            f"─────────────────────────────────────────────────────"
        )
```

Pass a single `SessionAccounting` instance into the `Agent` and every sub-agent so all usage rolls up to one object.

---

## 4. Configuration — `config.py`

Keep every tunable in one place. Precedence: **defaults < `.agentrc` file < environment variables < CLI flags**.

```python
# agent_harness/config.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .accounting import DEFAULT_PRICE_TABLE

# ---------------------------------------------------------------------------
# The Settings dataclass
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    # Core model
    model: str = "gpt-5"

    # Context budget (tokens)
    max_context_tokens: int = 180_000
    compact_threshold: float = 0.85        # compact at 85 % of budget
    compaction_model: str = "gpt-4.1-mini" # cheap model for summary

    # Tool execution
    max_tool_concurrency: int = 4

    # Agent loop
    max_iterations: int = 100             # hard stop

    # Permissions (see Phase 5)
    permission_mode: str = "default"      # "default" | "strict" | "yolo"

    # Filesystem
    workspace_root: str = field(default_factory=lambda: os.getcwd())

    # Persistence
    transcript_path: str = "transcript.json"
    trace_path: str = "trace.jsonl"
    memory_path: str = "CLAUDE.md"

    # Cost
    price_table: dict[str, dict[str, float]] = field(
        default_factory=lambda: DEFAULT_PRICE_TABLE
    )

    # Display
    verbose: bool = False
    debug: bool = False
    stream: bool = True                   # stream output vs wait for full response

    # Misc
    project_config_path: str = ".agentrc"

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "Settings":
        """Load from environment variables (AGENT_ prefix)."""
        s = cls()
        mapping: dict[str, tuple[str, type]] = {
            "AGENT_MODEL":               ("model",               str),
            "AGENT_MAX_CONTEXT_TOKENS":  ("max_context_tokens",  int),
            "AGENT_COMPACT_THRESHOLD":   ("compact_threshold",   float),
            "AGENT_MAX_ITERATIONS":      ("max_iterations",      int),
            "AGENT_PERMISSION_MODE":     ("permission_mode",     str),
            "AGENT_WORKSPACE_ROOT":      ("workspace_root",      str),
            "AGENT_TRANSCRIPT_PATH":     ("transcript_path",     str),
            "AGENT_TRACE_PATH":          ("trace_path",          str),
            "AGENT_MEMORY_PATH":         ("memory_path",         str),
            "AGENT_VERBOSE":             ("verbose",             bool),
            "AGENT_DEBUG":               ("debug",               bool),
            "AGENT_STREAM":              ("stream",              bool),
        }
        for env_key, (attr, typ) in mapping.items():
            raw = os.environ.get(env_key)
            if raw is not None:
                if typ is bool:
                    setattr(s, attr, raw.lower() in ("1", "true", "yes"))
                else:
                    setattr(s, attr, typ(raw))
        return s

    def apply_project_config(self) -> None:
        """Merge an optional .agentrc JSON file (workspace root)."""
        path = Path(self.workspace_root) / self.project_config_path
        if not path.exists():
            return
        try:
            data: dict[str, Any] = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def apply_cli_args(self, args: Any) -> None:
        """Merge values from an argparse Namespace, skipping None."""
        for attr in vars(self):
            cli_val = getattr(args, attr, None)
            if cli_val is not None:
                setattr(self, attr, cli_val)

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)


def load_settings(cli_args: Any = None) -> Settings:
    """
    Build a Settings object with full precedence chain:
    defaults -> .agentrc -> env vars -> CLI flags
    """
    s = Settings.from_env()
    s.apply_project_config()
    if cli_args is not None:
        s.apply_cli_args(cli_args)
    return s
```

An example `.agentrc` file at the project root:

```json
{
  "model": "gpt-4.1",
  "permission_mode": "strict",
  "max_context_tokens": 128000,
  "memory_path": "AGENTS.md"
}
```

---

## 5. System Prompt Engineering

The instructions string shapes everything. Here is a production-grade prompt for a coding agent, with explanations of each section:

````python
# agent_harness/instructions.py
"""
Build the system instructions string at startup.
Inject environment context so the model knows where it is.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def _git_status(workspace: str) -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "(not a git repo)"
    except Exception:
        return "(git unavailable)"


def _read_memory(memory_path: str, workspace: str) -> str:
    full = Path(workspace) / memory_path
    if full.exists():
        content = full.read_text(errors="replace")[:4000]
        return f"\n## Project Memory ({memory_path})\n\n{content}"
    return ""


def build_instructions(
    workspace_root: str,
    memory_path: str = "CLAUDE.md",
    permission_mode: str = "default",
) -> str:
    cwd = os.path.abspath(workspace_root)
    os_info = f"{platform.system()} {platform.release()}"
    git = _git_status(cwd)
    memory = _read_memory(memory_path, cwd)

    return f"""You are a highly capable coding agent operating in a terminal environment.
You have access to tools that let you read, write, and edit files, run shell
commands, search codebases, and delegate work to sub-agents.

## Role and Tone
- Be concise and precise. Prefer working code over lengthy explanation.
- When you are uncertain, say so. Ask one clarifying question rather than guessing.
- Think step-by-step for complex tasks, but do not narrate every micro-decision.
- Prefer making targeted, minimal changes rather than rewriting large chunks.

## Tool Use Guidance
- Always read a file before editing it.
- For multi-file edits, edit files one at a time and verify each change.
- Use the `bash` tool for tasks that need the shell (tests, builds, installs).
- Use the `task` tool to delegate independent sub-problems in parallel.
- When a tool returns an error, diagnose before retrying. Do not loop blindly.
- Tool results are the ground truth; do not assume results you have not seen.

## When to Act vs When to Ask
- Act autonomously on clear, well-scoped requests.
- Ask before: deleting data, making irreversible changes, or taking actions
  with significant side effects that were not explicitly requested.
- In strict mode, ask before any file modification outside the workspace.
- Current permission mode: **{permission_mode}**

## Output Conventions
- For code, use fenced blocks with the correct language tag.
- For file paths, use absolute paths when precision matters.
- When you complete a task, give a brief summary of what you did and why.
- Do not apologise for normal behaviour. Do not add unnecessary caveats.

## Safety
- Never expose secrets, keys, or credentials in your output.
- Do not run commands that could harm the host system outside the workspace.
- If a request seems destructive or unusual, confirm intent before proceeding.

## Environment
- Working directory: {cwd}
- OS: {os_info}
- Git status:
```
{git}
```
{memory}
"""
````

The memory file (Phase 6's `CLAUDE.md` or `AGENTS.md`) is injected here so the model always has project-specific context without consuming it as a conversation turn.

---

## 6. The CLI / REPL — `cli.py`

The REPL is the face of the harness. It needs to feel solid.

```python
# agent_harness/cli.py
"""
Entry point: interactive REPL and one-shot -p mode.

Usage:
  agent                          # interactive
  agent --resume                 # resume last session
  agent -p "Fix the test suite"  # one-shot (for CI / scripting)
  agent --mode strict            # override permission mode
  agent --debug                  # full logging
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from openai import OpenAI

from .accounting import SessionAccounting
from .agent import Agent
from .config import Settings, load_settings
from .conversation import Conversation
from .instructions import build_instructions
from .logging_config import configure_logging
from .permissions import PermissionPolicy
from .tools import build_registry       # builds the Phase 4 tool set
from .tracer import Tracer

MODEL = "gpt-5"

# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent",
        description="A production coding agent harness.",
    )
    p.add_argument("-p", "--prompt", metavar="TEXT",
                   help="One-shot prompt (non-interactive)")
    p.add_argument("--resume", action="store_true",
                   help="Resume from saved transcript")
    p.add_argument("--transcript", metavar="PATH",
                   help="Transcript file path (default: transcript.json)")
    p.add_argument("--model", metavar="MODEL",
                   help=f"Model to use (default: {MODEL})")
    p.add_argument("--mode", dest="permission_mode",
                   choices=["default", "strict", "yolo"],
                   help="Permission mode")
    p.add_argument("--workspace", dest="workspace_root", metavar="DIR",
                   help="Workspace root directory")
    p.add_argument("--no-stream", dest="stream", action="store_false",
                   help="Disable streaming output")
    p.add_argument("--verbose", action="store_true",
                   help="INFO-level logging")
    p.add_argument("--debug", action="store_true",
                   help="DEBUG-level logging")
    p.add_argument("--max-iterations", type=int, metavar="N",
                   help="Hard limit on agent loop iterations")
    return p


# ---------------------------------------------------------------------------
# Slash-command dispatch
# ---------------------------------------------------------------------------

HELP_TEXT = """\
Slash commands:
  /help              Show this help
  /clear             Start a new conversation (discards transcript)
  /compact           Manually trigger context compaction
  /save [path]       Save transcript to path (default: transcript.json)
  /resume [path]     Load transcript from path
  /mode <mode>       Set permission mode: default | strict | yolo
  /cost              Show token and cost summary for this session
  /tools             List registered tools
  /quit  /exit       Exit the agent
"""


def handle_slash(
    command: str,
    agent: "Agent",
    settings: Settings,
    accounting: SessionAccounting,
) -> bool:
    """
    Handle a slash-command string.
    Returns True if the REPL should continue, False to exit.
    """
    parts = command.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("/quit", "/exit"):
        return False

    elif cmd == "/help":
        print(HELP_TEXT)

    elif cmd == "/clear":
        agent.conversation.items.clear()
        print("[Conversation cleared]")

    elif cmd == "/compact":
        before = agent.estimate_tokens()
        agent.compact()
        after = agent.estimate_tokens()
        print(f"[Compacted: {before:,} → {after:,} tokens]")

    elif cmd == "/save":
        path = args[0] if args else settings.transcript_path
        agent.conversation.save(path)
        print(f"[Saved to {path}]")

    elif cmd == "/resume":
        path = args[0] if args else settings.transcript_path
        agent.conversation.load(path)
        print(f"[Loaded {len(agent.conversation.items)} messages from {path}]")

    elif cmd == "/mode":
        if not args:
            print(f"Current mode: {settings.permission_mode}")
        elif args[0] in ("default", "strict", "yolo"):
            settings.permission_mode = args[0]
            agent.policy = PermissionPolicy(mode=args[0])
            print(f"[Permission mode set to {args[0]}]")
        else:
            print("Unknown mode. Choose: default | strict | yolo")

    elif cmd == "/cost":
        accounting.print_summary()

    elif cmd == "/tools":
        names = sorted(agent.registry.tools.keys())
        print("Registered tools:")
        for name in names:
            tool = agent.registry.tools[name]
            print(f"  {name:20s}  {tool.description[:60]}")

    else:
        print(f"Unknown command: {cmd}. Type /help for commands.")

    return True


# ---------------------------------------------------------------------------
# Multi-line input helper
# ---------------------------------------------------------------------------

def read_multiline(prompt: str = "You: ") -> str:
    """
    Single-line by default. If the user ends a line with '\\', continue.
    Empty input returns empty string.
    """
    try:
        line = input(prompt)
    except EOFError:
        return ""
    lines = [line.rstrip("\\")]
    while line.endswith("\\"):
        try:
            line = input("... ")
        except EOFError:
            break
        lines.append(line.rstrip("\\"))
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = make_parser()
    args = parser.parse_args()

    # 1. Settings (defaults → .agentrc → env → CLI)
    settings = load_settings(args)
    if settings.debug:
        configure_logging("DEBUG")
    elif settings.verbose:
        configure_logging("INFO")
    else:
        configure_logging("WARNING")

    # 2. Build collaborators
    client = OpenAI()
    tracer = Tracer(path=settings.trace_path)
    accounting = SessionAccounting(
        model=settings.model,
        price_table=settings.price_table,
    )
    policy = PermissionPolicy(mode=settings.permission_mode)
    registry = build_registry(workspace_root=settings.workspace_root)
    instructions = build_instructions(
        workspace_root=settings.workspace_root,
        memory_path=settings.memory_path,
        permission_mode=settings.permission_mode,
    )

    # 3. Build the agent
    agent = Agent(
        client=client,
        model=settings.model,
        instructions=instructions,
        registry=registry,
        policy=policy,
        accounting=accounting,
        tracer=tracer,
        settings=settings,
    )

    # 4. Resume if requested
    if args.resume:
        path = settings.transcript_path
        if Path(path).exists():
            agent.conversation.load(path)
            n = len(agent.conversation.items)
            print(f"[Resumed from {path}: {n} messages]")
        else:
            print(f"[No transcript found at {path}, starting fresh]")

    tracer.session_start(settings.to_dict())

    # 5a. One-shot mode
    if args.prompt:
        try:
            agent.run_turn(args.prompt)
        except KeyboardInterrupt:
            print("\n[Cancelled]")
        finally:
            accounting.print_summary()
            tracer.session_end(accounting.summary())
        sys.exit(0)

    # 5b. Interactive REPL
    print("Agent ready. Type /help for commands. Ctrl-C cancels turn; Ctrl-D exits.")
    while True:
        try:
            user_input = read_multiline("You: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            should_continue = handle_slash(user_input, agent, settings, accounting)
            if not should_continue:
                break
            continue

        try:
            agent.run_turn(user_input)
        except KeyboardInterrupt:
            print("\n[Turn cancelled. Transcript preserved.]")
        except Exception as exc:
            tracer.error(agent.turn_count, type(exc).__name__, str(exc))
            print(f"\n[Error: {exc}]")

    accounting.print_summary()
    tracer.session_end(accounting.summary())


if __name__ == "__main__":
    main()
```

---

## 7. The Definitive `Agent.run_turn` Loop

This is the fully-annotated reference implementation. It wires every middleware component in the correct order. Read it as the canonical specification.

```python
# agent_harness/agent.py  (run_turn — full implementation)
"""
Agent.run_turn encapsulates one user message → zero-or-more LLM+tool
iterations → final assistant reply.

Middleware order (per iteration):
  1. Budget check / auto-compact
  2. Append pending tool results (from prior iteration)
  3. Stream LLM turn (with retry via llm.py)
  4. Record usage in accounting
  5. Carry output items into next input
  6. For each function_call item in output:
       a. Pre-use hooks
       b. Permission gate (approve / deny / escalate to user)
       c. Parallel execution via ThreadPoolExecutor
       d. Post-use hooks
       e. Build function_call_output items
  7. Trace the turn
  8. Persist the transcript
  9. If no tool calls: done. Otherwise: loop.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import llm
from .accounting import SessionAccounting
from .config import Settings
from .conversation import Conversation
from .hooks import run_pre_hooks, run_post_hooks
from .permissions import Decision, PermissionPolicy
from .tools import ToolRegistry
from .tracer import Tracer

log = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        *,
        client,
        model: str,
        instructions: str,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        accounting: SessionAccounting,
        tracer: Tracer,
        settings: Settings,
        name: str = "main",
    ) -> None:
        self.client = client
        self.model = model
        self.instructions = instructions
        self.registry = registry
        self.policy = policy
        self.accounting = accounting
        self.tracer = tracer
        self.settings = settings
        self.name = name

        self.conversation = Conversation()
        self.turn_count = 0

    # ------------------------------------------------------------------
    # Token estimation (rough; use tiktoken in production)
    # ------------------------------------------------------------------

    def estimate_tokens(self) -> int:
        raw = json.dumps(self.conversation.items)
        return len(raw) // 4  # ~4 chars per token

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    def compact(self) -> None:
        """
        Summarise the conversation using a cheap model (Phase 6).
        Replace input_items with [summary_message, ...recent_messages].
        """
        from .compaction import compact_conversation  # Phase 6
        before = self.estimate_tokens()
        self.conversation.items = compact_conversation(
            client=self.client,
            model=self.settings.compaction_model,
            items=self.conversation.items,
        )
        after = self.estimate_tokens()
        self.tracer.compaction(self.turn_count, before, after)
        log.info("Compaction: %d → %d estimated tokens", before, after)

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    def run_turn(self, user_text: str) -> str:
        """
        Drive the agent until the model stops calling tools.
        Returns the final assistant text.
        """
        # Append the user message to the transcript.
        self.conversation.items.append({"role": "user", "content": user_text})

        pending_tool_outputs: list[dict[str, Any]] = []
        final_text = ""

        for iteration in range(self.settings.max_iterations):
            self.turn_count += 1

            # ── Step 1: Budget check ──────────────────────────────────
            est_tokens = self.estimate_tokens()
            threshold = int(
                self.settings.max_context_tokens * self.settings.compact_threshold
            )
            if est_tokens > threshold:
                log.info(
                    "Auto-compact triggered: %d > %d tokens", est_tokens, threshold
                )
                self.compact()

            # ── Step 2: Append pending tool outputs ───────────────────
            # Tool outputs from the previous iteration are added now so
            # they are part of the input to this LLM call.
            for output_item in pending_tool_outputs:
                self.conversation.items.append(output_item)
            pending_tool_outputs = []

            # ── Step 3: LLM call (with retry and streaming) ───────────
            t0 = time.monotonic()
            self.tracer.turn_start(self.turn_count, len(self.conversation.items))
            log.info(
                "[%s] Turn %d, %d messages, ~%d tokens",
                self.name, self.turn_count,
                len(self.conversation.items), est_tokens,
            )

            tool_schemas = self.registry.schemas()

            if self.settings.stream:
                # Streamed path: print chunks as they arrive, collect full response
                resp = self._stream_turn(tool_schemas)
            else:
                # Non-streamed path
                resp = llm.create(
                    self.client,
                    model=self.model,
                    instructions=self.instructions,
                    input=self.conversation.items,
                    tools=tool_schemas,
                )

            elapsed = time.monotonic() - t0

            # ── Step 4: Record usage ──────────────────────────────────
            # usage can be None on some streaming paths — guard it.
            usage = getattr(resp, "usage", None)
            in_tok = getattr(usage, "input_tokens", 0) if usage else 0
            out_tok = getattr(usage, "output_tokens", 0) if usage else 0
            self.accounting.record_turn(
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
            self.tracer.turn_end(
                self.turn_count,
                in_tok,
                out_tok,
                elapsed,
                stop_reason=str(getattr(resp, "status", "unknown")),
            )

            # ── Step 5: Carry output items into transcript ────────────
            # The Responses API returns output as a list of typed items.
            # Append them so future turns see the model's prior output.
            for item in resp.output:
                self.conversation.items.append(item)

            # Collect assistant text for the final return value.
            function_calls = []
            for item in resp.output:
                if getattr(item, "type", None) == "message":
                    for block in getattr(item, "content", []):
                        if getattr(block, "type", None) == "output_text":
                            final_text += block.text
                elif getattr(item, "type", None) == "function_call":
                    function_calls.append(item)

            # If no tool calls, the model is done.
            if not function_calls:
                break

            # ── Step 6: Execute tool calls ────────────────────────────
            # 6a. Pre-use hooks
            for fc in function_calls:
                args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments
                run_pre_hooks(tool_name=fc.name, args=args)

            # 6b. Permission gate
            approved: list[Any] = []
            for fc in function_calls:
                args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments
                decision = self.policy.check(tool_name=fc.name, args=args)
                self.tracer.permission_decision(
                    self.turn_count, fc.name, decision.value
                )
                if decision == Decision.DENY:
                    log.warning("Permission DENIED: %s", fc.name)
                    pending_tool_outputs.append({
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": f"Error: permission denied for tool '{fc.name}'",
                    })
                elif decision == Decision.ESCALATE:
                    # Ask the user interactively
                    granted = self._ask_user_approval(fc.name, args)
                    if granted:
                        approved.append(fc)
                    else:
                        pending_tool_outputs.append({
                            "type": "function_call_output",
                            "call_id": fc.call_id,
                            "output": f"Error: user denied permission for '{fc.name}'",
                        })
                else:
                    approved.append(fc)

            # 6c. Parallel execution
            results: dict[str, str] = {}
            with ThreadPoolExecutor(
                max_workers=self.settings.max_tool_concurrency
            ) as pool:
                future_to_fc = {
                    pool.submit(self._execute_tool, fc): fc
                    for fc in approved
                }
                for future in as_completed(future_to_fc):
                    fc = future_to_fc[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        # Tools must not raise; if they do, catch here
                        result = f"Error: unexpected exception: {exc}"
                    results[fc.call_id] = result

            # 6d. Post-use hooks + build outputs
            for fc in approved:
                args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments
                result = results[fc.call_id]
                run_post_hooks(tool_name=fc.name, args=args, result=result)

                self.tracer.tool_result(
                    self.turn_count,
                    fc.name,
                    fc.call_id,
                    ok=not result.startswith("Error"),
                    preview=result,
                )
                self.accounting.record_tool_call()

                pending_tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": result,
                })

            # ── Step 7 & 8: Trace + persist ───────────────────────────
            # Trace already updated in the tool_result calls above.
            self.conversation.save(self.settings.transcript_path)

        else:
            # Hit max_iterations without a clean stop
            log.warning("Hit max_iterations=%d", self.settings.max_iterations)
            final_text += "\n[Agent reached maximum iterations limit]"

        return final_text

    # ------------------------------------------------------------------
    # Streaming helper
    # ------------------------------------------------------------------

    def _stream_turn(self, tool_schemas: list[dict]) -> Any:
        """Stream the turn, printing text chunks, then return the final response."""
        with llm.stream(
            self.client,
            model=self.model,
            instructions=self.instructions,
            input=self.conversation.items,
            tools=tool_schemas,
        ) as stream_ctx:
            for event in stream_ctx:
                # The streaming event object varies; adapt to your SDK version.
                chunk_text = getattr(event, "text", None)
                if chunk_text:
                    print(chunk_text, end="", flush=True)
            print()  # newline after streamed output
            return stream_ctx.get_final_response()

    # ------------------------------------------------------------------
    # Tool execution (never raises)
    # ------------------------------------------------------------------

    def _execute_tool(self, fc: Any) -> str:
        args = json.loads(fc.arguments) if isinstance(fc.arguments, str) else fc.arguments
        self.tracer.tool_call(self.turn_count, fc.name, fc.call_id, args)
        log.info("Executing tool %s call_id=%s", fc.name, fc.call_id)
        try:
            return self.registry.call(fc.name, args)
        except Exception as exc:
            log.error("Tool %s raised: %s", fc.name, exc)
            return f"Error: {exc}"

    # ------------------------------------------------------------------
    # Interactive approval
    # ------------------------------------------------------------------

    def _ask_user_approval(self, tool_name: str, args: dict) -> bool:
        print(f"\n[Permission required] Tool: {tool_name}")
        print(f"  Arguments: {json.dumps(args, indent=2)}")
        try:
            answer = input("Allow? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")
```

---

## 8. Packaging and Operations

### Project Layout

```text
agent_harness/
├── __init__.py
├── accounting.py        # SessionAccounting, price table
├── agent.py             # Agent class, run_turn
├── cli.py               # argparse + REPL
├── compaction.py        # compact_conversation (Phase 6)
├── config.py            # Settings dataclass
├── conversation.py      # Conversation, save/load (Phase 3)
├── hooks.py             # PreToolUse / PostToolUse (Phase 5)
├── instructions.py      # build_instructions
├── llm.py               # Resilient wrapper (this phase)
├── logging_config.py    # configure_logging
├── permissions.py       # PermissionPolicy, Decision (Phase 5)
├── streaming.py         # Streaming renderer (Phase 3)
├── tools.py             # Tool, @tool, ToolRegistry + real tools (Phases 2, 4)
│   └── filesystem.py    # read_file, write_file, bash, etc. (Phase 4)
├── tracer.py            # Tracer, JSONL event log
└── sub_agents.py        # sub-agent presets, task tool (Phase 7)

pyproject.toml
.agentrc                 # optional project config
CLAUDE.md                # optional memory file
transcript.json          # auto-saved transcript (gitignore this)
trace.jsonl              # auto-saved event log (gitignore this)
```

### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "agent-harness"
version = "0.1.0"
description = "A production-grade LLM agent harness in pure Python"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    # The Responses API (client.responses.create) was added in openai 1.66.0.
    "openai>=1.66.0",
]

[project.optional-dependencies]
tiktoken = ["tiktoken>=0.7"]  # accurate token counting
dev = ["pytest>=8"]

[project.scripts]
agent = "agent_harness.cli:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["agent_harness*"]
```

Install in development mode:

```bash
pip install -e ".[tiktoken,dev]"
```

Run:

```bash
agent                              # interactive REPL
agent -p "Summarise all TODO comments in this repo"
agent --resume --mode strict
AGENT_MODEL=gpt-4.1 agent         # cheaper model via env
```

### Running the Bash Tool Safely in Production

The `bash` tool (Phase 4) executes arbitrary shell commands inside `WORKSPACE_ROOT`. For real deployments, isolate it:

- **Docker container**: mount the workspace directory read-write; use a network-disabled container for the agent process itself.
- **Linux namespaces / `unshare`**: `unshare --user --pid --net --mount bash -c "..."` gives a throwaway namespace.
- **Firejail / bubblewrap**: lighter-weight sandboxing on Linux desktops.
- **`timeout` prefix**: wrap every bash invocation with `timeout 30 <cmd>` to prevent runaway commands.

The harness does not enforce sandboxing itself; that is an infrastructure concern. Document your threat model and choose accordingly.

---

## 9. Testing the Harness

### 9.1 Guiding Principles

- **Unit-test tools directly**: call `read_file({"path": "..."})` and assert the output. No LLM involved.
- **Mock the OpenAI client** for loop tests: return canned responses.
- **Scripted tool calls**: make the fake model emit known `function_call` items so you can assert the tool was called and the result fed back correctly.

### 9.2 A Fake Client

```python
# tests/fake_client.py
"""
A minimal fake that replaces the real OpenAI client.
Each call to responses.create() pops from a script of pre-defined responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    total_tokens: int = 150


@dataclass
class FakeOutputText:
    type: str = "output_text"
    text: str = "Done."


@dataclass
class FakeFunctionCall:
    type: str = "function_call"
    name: str = ""
    call_id: str = ""
    arguments: str = "{}"


@dataclass
class FakeMessage:
    type: str = "message"
    content: list = field(default_factory=list)


@dataclass
class FakeResponse:
    output: list = field(default_factory=list)
    usage: FakeUsage = field(default_factory=FakeUsage)
    stop_reason: str = "end_turn"


class FakeResponses:
    def __init__(self, script: list[FakeResponse]) -> None:
        self._script = list(script)

    def create(self, **kwargs: Any) -> FakeResponse:
        if not self._script:
            raise RuntimeError("FakeClient script exhausted")
        return self._script.pop(0)


class FakeClient:
    def __init__(self, script: list[FakeResponse]) -> None:
        self.responses = FakeResponses(script)
```

### 9.3 A Loop Test

```python
# tests/test_agent_loop.py
import json
import pytest
from pathlib import Path
import tempfile

from agent_harness.agent import Agent
from agent_harness.accounting import SessionAccounting
from agent_harness.config import Settings
from agent_harness.permissions import PermissionPolicy
from agent_harness.tools import ToolRegistry, tool
from agent_harness.tracer import Tracer
from tests.fake_client import (
    FakeClient, FakeResponse, FakeFunctionCall,
    FakeMessage, FakeOutputText, FakeUsage,
)


# A trivial echo tool for testing
@tool
def echo(message: str) -> str:
    """Echo the message back."""
    return f"echo: {message}"


def make_agent(script, workspace):
    registry = ToolRegistry()
    registry.register(echo)

    # Turn 1: model calls echo("hello")
    # Turn 2: model says "Done." with no tool calls
    settings = Settings(
        workspace_root=str(workspace),
        transcript_path=str(workspace / "transcript.json"),
        trace_path=str(workspace / "trace.jsonl"),
        stream=False,
        max_iterations=10,
    )
    return Agent(
        client=FakeClient(script),
        model="gpt-5",
        instructions="You are a test agent.",
        registry=registry,
        policy=PermissionPolicy(mode="yolo"),  # no approval prompts
        accounting=SessionAccounting(model="gpt-5"),
        tracer=Tracer(path=None),              # no file output
        settings=settings,
    )


def test_tool_call_loop():
    """
    Verify: model calls echo → harness executes → feeds result back →
    model replies with text → run_turn returns that text.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)

        # Script: first response has a function_call; second has text.
        script = [
            FakeResponse(
                output=[
                    FakeFunctionCall(
                        name="echo",
                        call_id="call_001",
                        arguments=json.dumps({"message": "hello"}),
                    )
                ],
                usage=FakeUsage(input_tokens=50, output_tokens=20, total_tokens=70),
            ),
            FakeResponse(
                output=[
                    FakeMessage(content=[FakeOutputText(text="All done.")])
                ],
                usage=FakeUsage(input_tokens=80, output_tokens=10, total_tokens=90),
            ),
        ]

        agent = make_agent(script, workspace)
        result = agent.run_turn("Call echo with hello.")

        assert "All done." in result
        # The transcript should contain: user msg, function_call, function_call_output, message
        items = agent.conversation.items
        types = [item.get("type") if isinstance(item, dict) else getattr(item, "type", "?")
                 for item in items]
        assert "function_call_output" in types

        # Cost accounting should have both turns
        assert agent.accounting.turns == 2
        assert agent.accounting.tool_calls == 1
        assert agent.accounting.input_tokens == 130
        assert agent.accounting.output_tokens == 30


def test_tool_error_does_not_crash_loop():
    """
    A tool that raises must not crash run_turn — the harness catches it.
    """
    @tool
    def exploding_tool(x: int) -> str:
        """Always raises."""
        raise ValueError("boom")

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)

        script = [
            FakeResponse(
                output=[
                    FakeFunctionCall(
                        name="exploding_tool",
                        call_id="call_002",
                        arguments=json.dumps({"x": 1}),
                    )
                ],
            ),
            FakeResponse(
                output=[FakeMessage(content=[FakeOutputText(text="Caught it.")])],
            ),
        ]

        settings = Settings(
            workspace_root=str(workspace),
            transcript_path=str(workspace / "transcript.json"),
            stream=False,
        )
        registry = ToolRegistry()
        registry.register(exploding_tool)

        agent = Agent(
            client=FakeClient(script),
            model="gpt-5",
            instructions="test",
            registry=registry,
            policy=PermissionPolicy(mode="yolo"),
            accounting=SessionAccounting(model="gpt-5"),
            tracer=Tracer(path=None),
            settings=settings,
        )
        result = agent.run_turn("Do the thing.")
        assert "Caught it." in result

        # Confirm the error was returned as a function_call_output string
        outputs = [
            item for item in agent.conversation.items
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert any("Error" in o["output"] for o in outputs)
```

Run with:

```bash
pytest tests/ -v
```

---

## 10. Where to Go Next

**Evals and benchmarks.** Attach [SWE-bench](https://swe-bench.github.io/) or a custom task suite to your harness. Score the agent on real codebases. Evals catch regressions from prompt or model changes before they hit users.

**MCP-style external tool servers.** The Model Context Protocol defines a JSON-RPC interface for serving tools from a separate process (or remote host). Replace the in-process `ToolRegistry` with an MCP client, and tools become independently deployable and language-agnostic.

**Multi-model routing.** Use a cheap model (`gpt-4.1-mini`) for tool-call-heavy iterations and a powerful model (`gpt-5`) only for reasoning-intensive turns. The `Settings.model` field can be changed per-turn based on heuristics (e.g., how many tokens remain, what kind of task is active).

**Prompt caching and `previous_response_id`.** If you pass `previous_response_id` instead of managing `input_items` yourself, the API handles state server-side and can cache the system prompt prefix cheaply. Useful when the instructions are large and stable. The trade-off: you lose offline resumability from a local transcript.

**Richer TUI.** Replace `print()` calls with [Rich](https://github.com/Textualize/rich) for live progress panels, syntax-highlighted diffs, and tool-call spinners. The streaming renderer from Phase 3 is the right hook point.

---

## 11. Closing Recap — Production Properties to Phases

| Production property | Foundation phase |
|---|---|
| Tool execution, parallel dispatch | Phase 2 — Tool system |
| Conversation persistence, streaming | Phase 3 — Conversation and streaming |
| Filesystem and shell tools | Phase 4 — Real tools |
| Permission gate, approval hooks | Phase 5 — Permissions and hooks |
| Token budgeting, auto-compaction | Phase 6 — Context management |
| Agent class, sub-agents, `task` tool | Phase 7 — Orchestration |
| Retry/backoff, Tracer, Settings, CLI | **Phase 8 — This phase** |

Every abstraction introduced in earlier phases was chosen so it would slot cleanly into this final assembly. The `Conversation` owns the transcript as a plain list. The `ToolRegistry` produces JSON schemas on demand. The `PermissionPolicy` is a pure function of tool name and args. The `Agent` is a thin coordinator that calls each collaborator in a fixed order.

The result is a harness where each concern is isolated, each component is testable independently, and the whole thing behaves predictably under the conditions that actually matter in production: slow networks, large files, adversarial model outputs, and impatient users who press Ctrl-C.

---

*End of Phase 8 — and of the guide. You now have a complete, from-scratch implementation of a production coding agent in pure Python.*
