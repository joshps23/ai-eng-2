# Beginner Orientation & Review Tracker

> **Who this version is for.** You are comfortable with exactly five things:
> **functions**, **lists**, **dictionaries**, **operators** (`+ - * / == and or not in` …),
> and the **OpenAI Responses API** called with `client.responses.create(...)`.
> Everything else in this guide is explained the first time it shows up, in a box
> like the one below. Where the original guide used an advanced tool just for
> convenience, this version shows a plain-functions way to get the same result.

This file has two jobs:

1. **Orientation** — a cheat-sheet of every concept the guide uses that goes
   beyond your five, each explained in one or two sentences (below).
2. **Review tracker** — a checklist of which files have been adapted for you, so
   the review can continue in passes without losing its place.

---

## 1. Concepts beyond your five (the cheat-sheet)

Read these once. Each scaffolding box in the guide links back here.

| Thing you'll see | What it really is, in terms you know |
|------------------|--------------------------------------|
| **`class` / methods** | A bundle of related functions plus some shared data. You can mentally read `obj.do_thing(x)` as "call the `do_thing` function, passing `obj`'s data along." This version replaces classes with plain functions wherever it can. |
| **`item.type` (a dot, not `["type"]`)** | The Responses API gives back *objects*. Reading a field with a dot (`item.type`) is just like reading a dict key (`item["type"]`) — same idea, different punctuation. |
| **`json.loads(s)` / `json.dumps(d)`** | `loads` turns a **string that looks like a dict** (e.g. `'{"city": "Paris"}'`) into a real dict. `dumps` does the reverse: dict → string. The API hands you tool arguments as a *string*, so you `json.loads` it into a dict. |
| **JSON Schema** | Just a **dictionary** that describes what arguments a function takes (their names and types). The model reads it to decide how to call your function. You already know dicts — this is one with an agreed-upon shape. |
| **`try` / `except`** | "Try to run this; if it blows up, do that instead, don't crash." This version keeps these tiny and always explains them inline. |
| **`with ... as x:`** | A way to use something and clean it up automatically afterward. When you see `with client.responses.create(..., stream=True) as stream:`, read it as "open a stream, loop over it, close it when done." |
| **type hints** (`x: str`, `-> dict`) | Optional notes that say "this is a string" or "this returns a dict." They change nothing at runtime — you can ignore them while reading. |
| **`from __future__ import annotations`** | A switch at the top of some files that only affects how *type hints* are read (it lets newer hint syntax work on older Pythons). It changes nothing about what the code does — safe to ignore. |
| **`typing.TYPE_CHECKING`** | A constant that is `False` when your program actually runs; only type-checker tools see it as `True`. An `if TYPE_CHECKING:` block imports things purely for type hints, so at runtime it's skipped — also safe to ignore. |
| **`*args` / `**kwargs`** | "Accept any extra positional/keyword arguments." `run(**kwargs)` just means "this function accepts named arguments and gathers them into a dict called `kwargs`." |
| **decorators** (`@something`) | A line starting with `@` above a function that wraps it to add behavior. Where the original used these for convenience, this version shows the plain-function equivalent. |
| **threads / `ThreadPoolExecutor`** | A way to run several slow things (like API or disk calls) at the same time instead of one after another. The simple, sequential (one-after-another) version is always shown first. |
| **f-strings** (`f"hi {name}"`) | A string with `{...}` holes that get filled in with values. `f"{a} + {b}"` is the same as `str(a) + " + " + str(b)`. |

---

## 2. Review tracker

> **(For maintainers — readers can skip this section.)** This is bookkeeping from the
> editorial pass that adapted the guide for beginners. Nothing below is something *you*
> need to do; if you're here to learn, section 1 above is all you need from this file.

Status legend: ☐ not started · ◐ in progress · ☑ adapted for beginners

| File | Status | Notes |
|------|:------:|-------|
| `README.md` (top level) | ☑ | Beginner-track pointer box. |
| `agent-harness-guide/README.md` | ☑ | Beginner-track pointer in "Who this is for". |
| `00-foundations.md` | ☑ | Added orientation pointer + scaffolding for dot-access, `json.loads`, JSON Schema, `with`/stream, threads. |
| `01-bare-harness.md` | ☑ | Scaffolding for type hints, `**args`, `try/except`, list comprehension (with plain-loop equivalent), `__main__`. |
| `02-tool-system.md` | ☑ | Functions-only beginner material now lives in the version ladder itself (Versions 1–2 = schema dicts + dict registry + for-loop dispatch), flagged by the "🟢 Beginner track" heading near the top; plus inline boxes translating classes, the `@tool` decorator/introspection, and threads. |
| `03-conversation-and-streaming.md` | ☑ | Beginner track: `Conversation` as a plain dict + functions (new_conversation/add_user/extend_items/save/load); streaming framed as optional (use non-streaming `create()` + `output_text`). Inline boxes on the class methods and the argument-taking decorator. |
| `04-real-tools.md` | ☑ | One consolidated box: tools are plain functions; `@tool` is optional (hand-write schemas per Phase 2); plus heads-ups on `pathlib.Path`, `lambda`, f-string format specs, and try/except. |
| `05-permissions-and-safety.md` | ☑ | Beginner track: full permission check in dicts + if/else (TOOL_RISK, AUTO_OK, check_permission/ask_user); concept table for dataclass≈dict, Enum≈string constants, set≈list, closure, tuple-return, hooks. Inline box reframing hooks as plain functions. |
| `06-context-management.md` | ☑ | Beginner box: one idea (shrink the growing list) + three tactics (clip/drop-oldest/summarize) as plain functions; syntax notes on count_tokens≈len//4, the bare-`*` keyword-only marker, generator comprehensions, isinstance. |
| `07-subagents-orchestration.md` | ☑ | Beginner track: a sub-agent = calling your run_agent loop again from inside a `task` tool; Agent class→loop+conversation dict; presets→dict; parallel optional. Syntax table for @dataclass/@property/factory-closure/asyncio. |
| `08-production-harness.md` | ☑ | Beginner track: phase is polish not new ideas; retry shown as plain for-loop+try/except+sleep; table mapping dataclass/@property/@contextmanager/argparse/logging/typed-except/ThreadPool to known concepts. |
| `09-library-reference.md` | ☑ | Added a "beginner reading order" box: study §1 (openai, in-scope), skim §2–§4 (tiktoken/threads/subprocess) as background. |
| `code/` package | ☑ | Kept the tested package intact (source of truth); added a "New to Python?" reading-guide box to `code/README.md` mapping every module to its plain-functions phase box, plus beginner-pointer docstrings in `agent.py` and `tools/base.py`. |

**Review complete** — all files adapted for the beginner audience. Approach: in-place
scaffolding (green 🟢 boxes) + per-phase functions-and-dicts "Beginner track" rewrites
of anything using classes/decorators/threads, while leaving the original advanced
material intact for later. The runnable `code/` package was left untouched (so its tests
still pass) and bridged with a reading guide instead of a risky rewrite.

Each pass: pick the next ☐ file, adapt it, flip it to ☑, and note what was done.
