# Python Concepts Cheat-Sheet

> **Read this once before Phase 0.** This page is for you if you're comfortable with
> exactly five things: **functions**, **lists**, **dictionaries**, **operators**
> (`+ - * / == and or not in` …), and the **OpenAI Responses API** called with
> `client.responses.create(...)`. Everything else the guide uses is explained the
> first time it shows up, in a 🟢 box — and summarized here in one or two sentences
> each. Where the guide could use an advanced tool just for convenience, it also
> shows a plain-functions way to get the same result.

## Concepts beyond your five

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

That's the whole list. When a phase uses one of these, an inline 🟢 box re-explains it
right where it appears — and the **[Glossary](./GLOSSARY.md)** defines every other term
in the guide. Ready? Head to **[Phase 0](./00-foundations.md)** (or the
**[Learning Path](./LEARNING-PATH.md)** if you want a step-by-step plan).
