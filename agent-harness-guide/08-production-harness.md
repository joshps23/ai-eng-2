# Phase 8 — The Production Harness: Assembling Claude Code

You have built every organ of the system. Phase 2 gave you tools and parallel dispatch. Phase 3 gave you conversation persistence and streaming. Phase 4 gave you real filesystem and shell tools. Phase 5 gave you permissions and hooks. Phase 6 gave you token budgeting and compaction. Phase 7 gave you agent orchestration and sub-agents.

This phase wires all of that into a harness you could ship: reliable under network chaos, observable when something goes wrong, configurable without code edits, and pleasant to use from a terminal. The gap between a weekend demo and a production coding agent is almost entirely about these properties. We will close that gap, component by component.

---

## 0. You've Already Built All of This — the Ladder-to-Package Map

Every previous phase climbed the same **version ladder**: V1 line-by-line (no `def`, no
classes), V2 functions, V3 classes, and — where the phase taught it — V4 decorators or
threads. Phase 8 is where the ladders meet. There is no V1 here, because *you already
climbed it seven times*: this phase takes the **top rung of each earlier ladder** and
shows how those rungs snap together into the single tested package,
[`code/agent_harness/`](code/agent_harness/).

Here is the map. Each row is a top rung you have already built, and the package module
it became:

| Phase, top rung you built | Package module it became |
|---|---|
| Phase 1 — **V3**: the minimal `Agent` class around the loop | `agent.py` |
| Phase 2 — **V4**: `@tool` decorator + `ToolRegistry` | `tools/base.py` + `tools/registry.py` |
| Phase 3 — **V3**: the `Conversation` class owning the transcript | `conversation.py` |
| Phase 4 — **V3**: the workspace-confined file & shell tools | `tools/files.py` + `tools/shell.py` |
| Phase 5 — **V3/V4**: permission policy objects + hooks | `permissions.py` + `hooks.py` |
| Phase 6 — **V2–V4**: `count_tokens`, `prune_to_budget`, `compact` | `context.py` |
| Phase 7 — **V3/V4**: the `task` tool reusing `Agent` + threaded dispatch | `subagents.py` + `tools/parallel.py` |

What is genuinely *new* in Phase 8 is only the production wrapping — and each new piece
gets its own rung-by-rung treatment below, exactly like the earlier phases:

| New in this phase | Package module |
|---|---|
| Retry/backoff around `client.responses.create(...)` (Step 0 → §6) | `llm.py` |
| `Settings` — configuration without magic constants (Step 2) | `config.py` |
| The REPL / CLI entry point (Step 4) | `cli.py` |
| `FakeClient` — testing the loop offline (§9) | `testing.py` |

Each of these new pieces climbs its own *mini*-ladder inside this phase — first the
plain-function form (V2 in the vocabulary you know), then, only where state demands it,
the class form (V3). You will see a **"Which rung is this?"** note next to each
production listing so you always know where you are on the ladder.

> **A note on file names.** As a teaching device, this phase (like Phases 4, 5, and 7)
> sometimes shows code under illustrative file names — `tracer.py`, `accounting.py`,
> `tools.py`, `sub_agents.py` — that the consolidated package merges or renames. When
> you go looking in `code/agent_harness/`, use the tables above (and the mapping table
> in [`code/README.md`](code/README.md)) as your index. When a snippet here and the
> package disagree, **the package is the source of truth** — it has the passing tests.

If you can read each row of the first table and picture the code you wrote for it, you
are ready. The rest of this phase adds the second table's modules one step at a time,
then shows the fully assembled `Agent.run_turn` where every row plugs in.

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

> ## 🟢 Beginner track: this phase is polish, not new core ideas
>
> Take a breath — there's **no new agent concept** in Phase 8. The loop at the heart of
> `run_turn` (§7) is the *same loop* you wrote in Phases 1–2: call the model, run the
> tools it asks for, feed results back, repeat until done. Everything else here is
> *optional production polish* wrapped around that loop:
>
> - **Retries** (`llm.py`) — if the network hiccups, try again after waiting.
> - **Logging / tracing** — fancy `print()` that writes to a file for later debugging.
> - **Config** (`Settings`) — read options from the command line / env instead of
>   hardcoding them.
> - **Cost accounting** — add up tokens × price.
> - **CLI** (`cli.py`) — the `You: ` prompt loop and `/help`-style commands.
> - **Packaging** (`pyproject.toml`) — so you can type `agent` to start it.
>
> You can run the agent with **none** of this. We will add each piece one at a time,
> starting with the single most useful piece — retry — written with only the things
> you already know.
>
> How to read the heavier syntax that appears later in this phase:
>
> | In the original | What it is, in your terms |
> |-----------------|---------------------------|
> | `@dataclass class Settings` / `SessionAccounting` | a dict with fixed keys; read `settings.model` as `settings["model"]`. |
> | `@property def total_tokens` | a method you read like a field (`acc.total_tokens`); just returns a computed value. |
> | `@contextmanager` / `@classmethod` | decorators that adjust how a function is used. Skim past them; the function body is the part that matters. |
> | `argparse` | reads options typed after the command (`agent --model gpt-4o`). Conceptually: fill a settings dict from the command line. |
> | `logging` | `print()` with on/off levels that can write to a file. |
> | the typed `except RateLimitError / APIConnectionError` list | "which errors are worth retrying" — the simple version above just retries on *any* error. |
> | `ThreadPoolExecutor` (again) | run approved tools at the same time; a plain `for` loop over them works identically. |
>
> Read this phase to understand *what a production harness adds and why*. You do not
> need to build every module to have a working agent — you already do.

---

## Step 0 — The Smallest Reliability Win: Retry with Backoff

**Why now?** Networks are unreliable. The OpenAI API sometimes returns a 429 (rate limit) or a 500 (server error). Without retry logic, your agent dies on the first hiccup. With it, the agent waits a moment and tries again — the user never notices.

Here is the complete retry wrapper using only a `for` loop, `try`/`except`, and `time.sleep` — no new imports beyond `time`:

```python
import time

def create_with_retry(client, **kwargs):
    """Call the API; if it fails, wait a bit and try again, up to 5 times."""
    for attempt in range(5):
        try:
            return client.responses.create(**kwargs)
        except Exception as exc:
            wait = 2 ** attempt          # 1s, 2s, 4s, 8s, 16s
            print(f"API error ({exc}); retrying in {wait}s…")
            time.sleep(wait)
    raise RuntimeError("API still failing after 5 tries")
```

That is it. The `2 ** attempt` pattern is called **exponential backoff**: each failure waits twice as long as the last, giving the server time to recover.

Use `create_with_retry(client, model=..., input=..., tools=...)` anywhere the guide calls `client.responses.create(...)`. That one change captures 90% of the value of the much longer `llm.py` shown later.

> **Which rung is this?** This is the **V2 — functions** rung of `llm.py`'s ladder: one
> plain function, no classes, no decorators. §6 shows the hardened V2 form (smarter error
> sorting, jitter, `Retry-After`), and the tested package takes one final small step to
> **V3**: a tiny `LLMClient` class whose only state is *which client to wrap* — that
> injectability is exactly what makes the offline `FakeClient` testing in §9 possible.

### ▶ Run it now

You can test retry logic without a real API by using a fake client that fails the first two times:

```python
import time

class FakeClient:
    """Fails twice, then succeeds. Simulates a flaky network."""
    def __init__(self):
        self.responses = self
        self._call_count = 0

    def create(self, **kwargs):
        self._call_count += 1
        if self._call_count < 3:
            raise Exception(f"Simulated network error (attempt {self._call_count})")
        # Third attempt succeeds — return a minimal fake response
        class FakeResp:
            output = []
            class usage:
                input_tokens = 10
                output_tokens = 5
        return FakeResp()


def create_with_retry(client, **kwargs):
    for attempt in range(5):
        try:
            return client.responses.create(**kwargs)
        except Exception as exc:
            wait = 2 ** attempt
            print(f"API error ({exc}); retrying in {wait}s…")
            time.sleep(wait)
    raise RuntimeError("API still failing after 5 tries")


fake = FakeClient()
resp = create_with_retry(fake, model="gpt-4o", input=[], tools=[])
print("Success on attempt", fake._call_count)
```

Expected output (with actual 1s + 2s sleeps):
```
API error (Simulated network error (attempt 1)); retrying in 1s…
API error (Simulated network error (attempt 2)); retrying in 2s…
Success on attempt 3
```

Once this works, every call in your loop is retry-safe. The rest of this phase wraps the same loop in progressively more production machinery.

---

## Step 1 — Observability: Know What Your Agent Is Doing

**Why now?** Once retry is in place, the next failure mode is: *the agent runs but does the wrong thing and you have no idea why*. Structured logging turns invisible behaviour into a visible record.

The simplest upgrade is to add `print()` statements with consistent labels. Replace bare `print()` calls with a tiny helper:

```python
import time

def log(level, message):
    """Minimal structured log line — upgrade to stdlib logging later."""
    ts = time.strftime("%H:%M:%S")
    print(f"{ts} [{level}] {message}")
```

> **Which rung is this?** **V2 — functions**: one helper wrapped around `print`. (The V1
> form is what you have been doing all guide long — bare `print()` calls sprinkled in the
> loop.) Steps 1b–1d climb this ladder one rung at a time.

Inside your agent loop, add:

```python
# At turn start:
t0 = time.monotonic()
log("INFO", f"turn_start  messages={len(input_items)}")

# After the response arrives:
elapsed = time.monotonic() - t0
in_tok  = resp.usage.input_tokens
out_tok = resp.usage.output_tokens
log("INFO", f"turn_end  tokens_in={in_tok} tokens_out={out_tok} elapsed={elapsed:.2f}s")

# For each tool call:
log("INFO", f"tool_call  name={item.name}  call_id={item.call_id}")

# For each tool result:
log("INFO", f"tool_result  call_id={call_id}  ok={not result.startswith('Error')}")
```

### ▶ Run it now

Run your existing agent with these log lines added. Ask it something that triggers a tool call. You should now see a structured record of every turn: how many messages were in context, how many tokens were used, how long each call took, and which tools ran.

If something goes wrong, you will know *exactly* which turn failed and what the inputs were — instead of guessing.

### 1b — Graduating to stdlib `logging`

When you are ready for logs that can be silenced or redirected to a file, swap your `log()` helper for stdlib `logging`:

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

Replace your `log("INFO", ...)` calls with:

```python
import logging
log = logging.getLogger(__name__)

log.info("turn_start input_messages=%d", len(self.input_items))
log.info(
    "turn_end tokens_in=%d tokens_out=%d total=%d elapsed=%.2fs",
    resp.usage.input_tokens,
    resp.usage.output_tokens,
    resp.usage.total_tokens,
    elapsed,
)
log.info("tool_call name=%s call_id=%s", item.name, item.call_id)
log.info(
    "tool_result call_id=%s ok=%s preview=%.80r",
    call_id,
    not result.startswith("Error"),
    result,
)
```

The `logging` module is just `print()` with on/off levels. When `level="WARNING"`, INFO lines are silenced; turn on `level="DEBUG"` to see everything. You switch it once at startup, not at every call site.

> **Which rung is this?** Still **V2 — functions**. We swapped our hand-rolled `log()`
> function for the stdlib's, but nothing was reorganized: same calls, same places, better
> plumbing.

### 1c — The JSONL Tracer

A machine-readable event log is invaluable for post-hoc debugging and cost audits.

> **Which rung is this?** **V3 — classes.** The `Tracer` below is your `log()` helper
> *with state*: it has to remember the file path and a session id across every call, so
> — exactly like `Conversation` in Phase 3 — the function grows into a class that carries
> its own data. The method bodies are still just "build a dict, write a line."

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

### 1d — Cost and Token Accounting

Track usage across turns (and across sub-agents spawned in Phase 7). This is the same idea as the `log()` helper above — just accumulating numbers instead of printing strings:

> **Which rung is this?** **V3 — classes**, for the same reason as the `Tracer`: the
> running totals are *state*, and state is what justifies a class. The `@dataclass`
> decorator is only there to write `__init__` for us — see the beginner note below the
> listing.

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

> **Beginner note on `@dataclass` and `@property`:** A `@dataclass` is just a class where
> Python auto-generates `__init__` from the field names — read `SessionAccounting.model`
> exactly as you would read `acc["model"]` in a dict. A `@property` is a method you call
> without parentheses: `acc.total_tokens` calls the function and returns the result.
> The function bodies are what matter; skim the decorators.

Pass a single `SessionAccounting` instance into the `Agent` and every sub-agent so all usage rolls up to one object.

---

## Step 2 — Configuration: No More Magic Constants

**Why now?** After adding retry and logging, you will want to change the model name, the max iterations, or the workspace path without editing source. A single `Settings` object collects every tunable in one place and reads from environment variables, a project file, and CLI flags — in that order of precedence.

The plain-dict equivalent is just:

```python
settings = {
    "model": os.environ.get("AGENT_MODEL", "gpt-4o"),
    "max_iterations": int(os.environ.get("AGENT_MAX_ITERATIONS", "100")),
    "transcript_path": "transcript.json",
    # … and so on
}
```

The production `Settings` dataclass below is exactly that, with nicer access syntax and a loader chain. Read `settings.model` as `settings["model"]`:

> **Which rung is this?** The plain dict above is the **V2** form; the dataclass below is
> its **V3** rung — *the same settings, organized*, exactly like the V2→V3 climbs you made
> in Phases 1–7. What changed and why: (1) fields get defaults and types in one place,
> (2) typos like `settings.modle` fail loudly instead of silently creating a new key, and
> (3) the loaders (`from_env`, `apply_project_config`, `apply_cli_args`) live next to the
> data they fill in. This is the package's `config.py`.

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
    model: str = "gpt-4o"

    # Context budget (tokens)
    max_context_tokens: int = 180_000
    compact_threshold: float = 0.85        # compact at 85 % of budget
    compaction_model: str = "gpt-4o"      # summaries don't need the best model —
                                          # swap in a cheaper one (e.g. gpt-4o-mini)
                                          # to cut compaction cost

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
  "model": "gpt-4o",
  "permission_mode": "strict",
  "max_context_tokens": 128000,
  "memory_path": "AGENTS.md"
}
```

### ▶ Run it now

```python
import os
os.environ["AGENT_MODEL"] = "gpt-4o"

settings = Settings.from_env()
print(settings.model)          # gpt-4o
print(settings.max_iterations) # 100  (default)
```

Any field you do not set stays at its default. The loop now reads `settings.max_iterations` instead of the magic constant `100`.

---

## Step 3 — System Prompt Engineering

**Why now?** With retry, logging, and config in place, the next lever is the instructions string. The right system prompt prevents whole classes of model mistakes before they happen: the agent knows its working directory, its permission mode, and whether the project has special conventions.

Here is a production-grade prompt for a coding agent, with explanations of each section:

> **Which rung is this?** **V2 — functions**, and it stays there: building a string needs
> no state, so `build_instructions` and its two helpers never become a class. (In the
> consolidated package there is no separate `instructions.py`; the instructions string is
> built in `cli.py` and handed to `Agent` — remember the file-name note in §0.)

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

### ▶ Run it now

```python
instructions = build_instructions(
    workspace_root=".",
    permission_mode="default",
)
print(instructions[:300])   # should show the working directory and OS info
```

The model will now know exactly where it is and what it is allowed to do, without you having to repeat it in every user message.

---

## Step 4 — The CLI / REPL: The Face of the Harness

**Why now?** With reliability, observability, and config in place, the last piece is a user interface you would actually want to use. The REPL is just a `while True` loop that reads a line, calls `agent.run_turn()`, and handles `/help`-style commands. The argparse layer adds `--model`, `--debug`, and `-p` (one-shot mode for CI).

The full `cli.py` wires together everything built above. Read it as the final assembly step:

> **Which rung is this?** None — and that is the point. `cli.py` is not a new rung on any
> ladder; it is the **assembly floor** where the *top rungs you already built* get bolted
> together. Watch the `main()` function: every object it constructs is a ladder-top from
> the §0 map — `build_registry` (Phase 2 V4 + Phase 4 V3), `PermissionPolicy` (Phase 5 V3),
> `Agent` (Phase 1 V3, grown up in §7), plus this phase's `Settings`, `Tracer`, and
> `SessionAccounting`. If you can name the phase each line comes from, you have absorbed
> the whole guide.

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

MODEL = "gpt-4o"

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

> **Beginner note on `argparse`:** `argparse` is just a way to read flags from the command
> line. `p.add_argument("--model", ...)` means: if the user types `agent --model gpt-4o`,
> then `args.model` will be `"gpt-4o"`. You can replicate the whole thing with
> `sys.argv` and a dict; `argparse` just handles the parsing and `--help` for you.

---

## 6. Reliability (Production Shape: `llm.py`)

> **Which rung is this?** The listing below is the **hardened V2 — functions** form: the
> same rung as Step 0, with better error sorting. It is a hardening pass, not a climb.
> The consolidated package then makes one last short climb to **V3**: it wraps these
> functions in an `LLMClient` class whose only state is the OpenAI client it holds —
> so tests can hand it a `FakeClient` instead (§9). Same retry logic either way.

The `create_with_retry` function from Step 0 is the essential idea. The production `llm.py` below is the same idea with three additions:

1. It distinguishes *retryable* errors (rate limits, network blips, server errors) from *fatal* ones (wrong API key, bad model name) — fatal errors are raised immediately without retrying.
2. It honours the `Retry-After` header that rate-limit responses sometimes include.
3. It adds jitter (a small random amount) to the backoff delay so that multiple agents do not all retry at exactly the same moment.

```python
# agent_harness/llm.py
"""
Thin resilient wrapper around client.responses.create (including stream=True).

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

    We stay on the low-level primitive: this is just
    ``client.responses.create(stream=True, **kwargs)``, which returns an
    iterator of typed events (and is itself a context manager, so the HTTP
    connection closes cleanly). We deliberately do NOT use the higher-level
    ``client.responses.stream()`` helper — driving the event loop and
    assembling the final response is the whole point of the harness.

    Because streaming errors often surface only after the first chunk,
    we retry at the connection / open stage. Mid-stream errors propagate as-is.
    """
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            with client.responses.create(stream=True, **kwargs) as s:
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

Call sites replace bare `client.responses.create(...)` with `llm.create(client, ...)` and the streaming form `client.responses.create(..., stream=True)` with `llm.stream(client, ...)`.

### 6.2 Timeouts and KeyboardInterrupt Handling

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

### 6.3 Idempotency and Crash Resumability

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

## 7. The Definitive `Agent.run_turn` Loop

This is the fully-annotated reference implementation. It wires every middleware component in the correct order. Read it as the canonical specification.

> **Which rung is this?** The **top rung of the entire guide**. The skeleton is Phase 1's
> V3 — an `Agent` class wrapped around the call-model → run-tools → feed-results loop —
> and every collaborator it touches is the top rung of another phase's ladder:
>
> | Line in `run_turn` you'll see below | Whose ladder-top it is |
> |---|---|
> | `self.conversation.items.append(...)` / `.save(...)` | Phase 3 V3 (`Conversation`) |
> | `self.registry.schemas()` / `self.registry.call(...)` | Phase 2 V4 (`@tool` + `ToolRegistry`) |
> | `self.policy.check(...)`, `run_pre_hooks` / `run_post_hooks` | Phase 5 V3/V4 (policy + hooks) |
> | `self.estimate_tokens()` / `self.compact()` | Phase 6 (`count_tokens` → `compact`) |
> | `ThreadPoolExecutor(...)` over approved calls | Phase 7 V4 (threaded dispatch) |
> | `llm.create(...)` / `llm.stream(...)` | this phase, Step 0 → §6 |
>
> Nothing in the body is new. If any line feels foreign, the table tells you which phase
> to revisit — climb that ladder again and come back.

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
        final = None
        with llm.stream(
            self.client,
            model=self.model,
            instructions=self.instructions,
            input=self.conversation.items,
            tools=tool_schemas,
            reasoning={"summary": "auto"},  # surface the chain-of-thought
        ) as stream_ctx:
            for event in stream_ctx:
                if event.type == "response.output_text.delta":
                    print(event.delta, end="", flush=True)
                elif event.type == "response.reasoning_summary_text.delta":
                    print(event.delta, end="", flush=True)  # chain-of-thought
                elif event.type == "response.completed":
                    # The raw stream has no get_final_response(); the assembled
                    # Response arrives here, on event.response.
                    final = event.response
            print()  # newline after streamed output
        return final

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

> **Mapping note.** The layout above is the *teaching* layout, using this phase's
> illustrative file names. The consolidated, tested package merges further:
> `tools.py`/`filesystem.py` became the `tools/` subpackage (`base.py`, `registry.py`,
> `files.py`, `shell.py`, `parallel.py`); `sub_agents.py` became `subagents.py`;
> `compaction.py` is `context.py`'s `compact()`; the token half of `accounting.py`
> survives as a small `UsageAccumulator` inside `agent.py` (the price table is an
> extension you can add); `tracer.py`, `logging_config.py`, and `instructions.py` are
> production extensions shown here, not separate package modules; and the package adds
> `testing.py` — the fake client from §9. Compare for yourself: the real tree is in
> [`code/agent_harness/`](code/agent_harness/) and the name-by-name mapping table is in
> [`code/README.md`](code/README.md).

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
AGENT_MODEL=gpt-4o agent          # override model via env
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

> **Which rung is this?** You met the V1 of this idea back in Step 0's ▶ Run it now — a
> fake client that fails twice then succeeds, written inline to test retry. This is its
> **V3**: the same trick (an object with a `.responses.create(...)` that returns scripted
> answers instead of calling the network) organized into reusable dataclasses. The tested
> package ships this as `testing.py`, and it only works because the client is *injectable*
> — the `Agent` takes a `client` argument rather than constructing `OpenAI()` itself.

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
        model="gpt-4o",
        instructions="You are a test agent.",
        registry=registry,
        policy=PermissionPolicy(mode="yolo"),  # no approval prompts
        accounting=SessionAccounting(model="gpt-4o"),
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
            model="gpt-4o",
            instructions="test",
            registry=registry,
            policy=PermissionPolicy(mode="yolo"),
            accounting=SessionAccounting(model="gpt-4o"),
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
python -m pytest tests/ -v
```

(The `python -m` form guarantees pytest runs under the same interpreter you installed the
package into — a bare `pytest` on your PATH might belong to a different Python.)

This is also exactly how the consolidated package is verified: from
[`code/`](code/), `python -m pytest -q` runs the full suite offline — no API key needed,
because every test drives the real `Agent` through the scripted `FakeClient` in
`testing.py`. Your seven ladders, assembled and proven, without a single network call.

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

### What you'll have built — the final checklist

Tick these off. Each line is a capability of the finished harness, the phase whose ladder
taught it, and the module of the tested package
([`code/agent_harness/`](code/agent_harness/)) where its top rung now lives:

- [ ] **An agent loop** — call the model, run the tools it asks for, feed results back
      with matching `call_id`s, repeat until done — *Phase 1* → `agent.py`
- [ ] **A tool system** — plain functions promoted to schema-bearing tools with `@tool`,
      dispatched through a registry that returns `"Error: ..."` strings instead of
      crashing the loop — *Phase 2* → `tools/base.py`, `tools/registry.py`
- [ ] **Memory** — a transcript the model never has (it's stateless!), owned as a plain
      list you can save, load, and resume — *Phase 3* → `conversation.py`
- [ ] **Hands** — real file and shell tools, confined to a workspace root — *Phase 4* →
      `tools/files.py`, `tools/shell.py`
- [ ] **Judgment** — a permission gate before every tool call, and hooks that observe
      without touching the loop — *Phase 5* → `permissions.py`, `hooks.py`
- [ ] **Endurance** — token counting, budget-aware pruning that never orphans a
      `function_call`/`function_call_output` pair, and model-written compaction —
      *Phase 6* → `context.py`
- [ ] **Delegation** — sub-agents that are just the same `Agent` run inside a `task`
      tool, plus threaded parallel dispatch — *Phase 7* → `subagents.py`,
      `tools/parallel.py`
- [ ] **Production fitness** — retry/backoff, settings from env/file/flags, a REPL with
      slash-commands, and offline tests against a scripted fake — *Phase 8* → `llm.py`,
      `config.py`, `cli.py`, `testing.py`

If every box is honest, you have built, from scratch, the kind of harness that powers
Claude Code — and you understand every line of it.

**Practice:** the [Phase 8 exercises](EXERCISES.md#phase-8--the-production-harness)
(plus the capstone) walk you through hardening and extending this assembly yourself.

---

## Key takeaways

- The gap between a **demo and a production harness** is *not* new agent ideas — it's
  **reliability, observability, configuration, and clean packaging** around the same loop.
- **Reliability:** retry transient/rate-limit errors with **exponential backoff**, cap
  iterations, and handle **Ctrl-C** gracefully.
- **Observability:** **structured logging** of tool calls, timings, and failures lets you
  see *inside* a run and debug it.
- It all assembles into **one CLI** (`argparse`) over the `Conversation`, `ToolRegistry`,
  and `PermissionPolicy` you've built since Phase 1 — each a separately testable piece.

## Check yourself

1. Name two things that separate a production harness from a demo.
2. What technique rides out a transient `RateLimitError`?
3. What does structured logging buy you operationally?
4. Is this phase mostly new concepts, or hardening of the existing loop?

<details><summary>Answers</summary>

1. Any two of: **retries/reliability**, **observability/logging**, **configuration**, and
   **packaging/CLI**.
2. **Retry with exponential backoff** (wait 1s, 2s, 4s… between attempts).
3. **Visibility** — which tools ran, how long they took, and what failed — so you can
   diagnose problems instead of guessing.
4. **Hardening and assembly.** The agent ideas are already in place; Phase 8 makes them
   reliable, observable, and shippable.
</details>

---

*End of Phase 8 — and of the guide. You now have a complete, from-scratch implementation of a production coding agent in pure Python.*
