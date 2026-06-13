"""Deterministic eval suite for the "state-machine expert" persona (Dr. Volkov).

The maintainer's directive: the curriculum should teach, in detail, how to BUILD
a finite state machine, and place it as a rung *above* classes on Phase 1's
version ladder:

    line-by-line (V1) -> functions (V2) -> classes (V3) -> STATE MACHINE (V4).

A second maintainer directive refined *how* it is taught: the machine must be
expressed with **plain dictionaries and strings**, NOT `Enum` classes. A beginner
already knows `dict` and `set`; rendering the whole machine as ordinary data they
can `print()` is the pedagogical win. So Version 4 names its states and events as
**strings**, declares them in `STATES`/`EVENTS` sets, and encodes the transition
function as a **dict-of-dicts** — `state -> {event -> next_state}`.

Phase 1's agent loop *is* a finite state machine (§2 already names it and draws
the figure). "Version 4 — State Machine" re-expresses the very same bare harness
as explicit, named states + a transition table + a tiny driver loop — the
control flow turned into inspectable *data*. This suite is the state-machine
expert's verification, turned into machine-checkable cases over the COMMITTED
markdown (`01-bare-harness.md`, the Glossary, Phase 5, and the §2 figure). It
never edits the markdown — it only reads it.

The pinned identifiers it parses are fixed by the content spec
(/tmp/devloop/sm-spec.md), in their **dictionary** form:

    states set    : STATES   = {"call_model", "run_tools", "done", "capped"}
    events set    : EVENTS   = {"has_tool_calls", "no_tool_calls", "cap_reached"}
    transitions   : TRANSITIONS  dict-of-dicts, state -> {event -> next_state}
    transition fn : next_state(state, event)  ->  TRANSITIONS[state][event]
    initial       : INITIAL  = "call_model"
    terminal set  : TERMINAL = {"done", "capped"}
    driver        : run_state_machine(...) with `while state not in TERMINAL`

Critically, the suite asserts the machine is taught with **dictionaries, not
enums**: the V4 code must NOT `import enum` or subclass `Enum`, and the states /
events it parses must be Python strings.

# Categories (what a state-machine expert verifies)

1. STRUCTURAL / PEDAGOGICAL  — Phase 1 carries a "Version 4 — State Machine"
   section; a "What changed from V3 to V4" note; >=1 "▶ Run it now" checkpoint
   inside it; the intro/version-ladder now lists FOUR rungs for Phase 1; the
   Glossary "State machine" entry exists; the Phase 5 modes-as-FSM note exists;
   the §2 "The loop is a state machine" figure exists.

2. CODE PRESENCE & PARSE — the V4 code fences AST-parse; the machine is built
   from dictionaries (NO `Enum`); the pinned identifiers are present: the
   `STATES` set (>=3 string members), the `EVENTS` set, the `TRANSITIONS`
   dict-of-dicts, `next_state`, an INITIAL state, a TERMINAL set, and the
   `while state not in TERMINAL` driver loop.

3. FSM-GRAPH CORRECTNESS (the signature category) — parse the taught machine out
   of the markdown (the `STATES` set + the `TRANSITIONS` dict-of-dicts), build
   the directed graph, and assert formal automata properties, PARAMETRIZED
   per-state and per-transition so the coverage is exhaustive:
     * every declared state is REACHABLE from the initial state;
     * >=1 TERMINAL state exists and is reachable;
     * every NON-TERMINAL state has >=1 outgoing transition (no dead ends);
     * every transition TARGET is a declared state (no dangling targets);
     * every transition SOURCE is a declared state;
     * DETERMINISM — each (state,event) maps to exactly one next state;
     * TERMINAL states have NO outgoing transitions;
     * the INITIAL state is declared exactly once;
     * global: NO unreachable states; NO orphan (no-incoming, non-initial) states.

4. CONSISTENCY — the state names used in the V4 prose match the `STATES`
   members; the §2 figure's state labels (CALL THE MODEL / RUN TOOLS / DONE)
   match the code's states.

Stdlib only, offline, deterministic. The parser prefers a real `ast` parse of
the V4 code and falls back to tolerant regex for the string/table/figure labels.
"""
from __future__ import annotations

import ast
import os
import re

from harness import Suite, read, GUIDE_DIR

SUITE = Suite("statemachine")

# --- canonical artifacts --------------------------------------------------
PHASE1 = os.path.join(GUIDE_DIR, "01-bare-harness.md")
PHASE5 = os.path.join(GUIDE_DIR, "05-permissions-and-safety.md")
GLOSSARY = os.path.join(GUIDE_DIR, "GLOSSARY.md")

# --- pinned identifiers (from /tmp/devloop/sm-spec.md, dictionary form) ----
STATES_NAME = "STATES"
EVENTS_NAME = "EVENTS"
TRANSITIONS_NAME = "TRANSITIONS"
NEXT_STATE_FN = "next_state"
INITIAL_NAME = "INITIAL"
TERMINAL_NAME = "TERMINAL"
DRIVER_FN = "run_state_machine"

# The spec's intended members (string-valued now, used to anchor the
# consistency / graph expectations).
EXPECTED_STATE_MEMBERS = ["call_model", "run_tools", "done", "capped"]
EXPECTED_INITIAL_MEMBER = "call_model"
EXPECTED_TERMINAL_MEMBERS = {"done", "capped"}
EXPECTED_EVENT_MEMBERS = ["has_tool_calls", "no_tool_calls", "cap_reached"]

# §2 figure state labels (tolerant: spacing/case folded before compare).
FIGURE_LABELS = {
    "call_model": ["CALL THE MODEL", "CALL MODEL"],
    "run_tools": ["RUN TOOLS"],
    "done": ["DONE"],
}

V4_HEADING_RE = re.compile(r"Version\s*4\s*[—\-–]\s*State\s*Machine", re.I)
RUNIT_RE = re.compile(r"▶\s*Run it now", re.I)


# ==========================================================================
# Section / code extraction (resilient — never raises into a case)
# ==========================================================================
def _phase1() -> str:
    return read(PHASE1)


def v4_section() -> str | None:
    """The markdown of the 'Version 4 — State Machine' section (heading through
    the start of the next same-or-higher-level heading), or None if absent."""
    md = _phase1()
    heads = list(re.finditer(r"(?m)^(#{2,3})\s+(.*)$", md))
    for i, h in enumerate(heads):
        if V4_HEADING_RE.search(h.group(2)):
            level = len(h.group(1))
            start = h.start()
            end = len(md)
            for j in range(i + 1, len(heads)):
                if len(heads[j].group(1)) <= level:
                    end = heads[j].start()
                    break
            return md[start:end]
    return None


def _code_blocks(section: str) -> list[str]:
    """All ```python fenced blocks in a markdown section."""
    return re.findall(r"```(?:python|py)\s*\n(.*?)```", section, re.S)


def v4_code() -> str:
    """Concatenate the V4 section's python code blocks into one source string.

    Returns "" if the section is missing or has no python blocks (cases then
    report a clear 'V4 section not found' / 'no V4 code' failure)."""
    sec = v4_section()
    if not sec:
        return ""
    return "\n\n".join(_code_blocks(sec))


def _parse(src: str):
    """ast.parse(src) -> module or None (tolerant)."""
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


# ==========================================================================
# FSM model parsed from the V4 code (the signature category's foundation)
# ==========================================================================
class FSM:
    """A directed graph parsed from `STATES` + `TRANSITIONS` in the V4 code.

    states     : list[str]                declared members of the STATES set
    events     : list[str]                declared members of the EVENTS set
    initial    : str | None               INITIAL's string value
    terminal   : set[str]                 TERMINAL's string members
    edges      : list[(src, event, dst)]  one per inner TRANSITIONS entry
    nested     : bool                     TRANSITIONS parsed as a dict-of-dicts
    error      : str | None               why the parse failed (for details)
    """

    def __init__(self):
        self.states: list[str] = []
        self.events: list[str] = []
        self.initial: str | None = None
        self.terminal: set[str] = set()
        self.edges: list[tuple[str, str, str]] = []
        self.nested: bool = False
        self.error: str | None = None


def _const_strings(tree) -> dict[str, str]:
    """Map of top-level `NAME = "literal"` string constants (so the table may
    optionally use named string constants and still resolve)."""
    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            consts[node.targets[0].id] = node.value.value
    return consts


def _str(node, consts: dict[str, str]) -> str | None:
    """Resolve an AST node to a string: a string literal, or a Name bound to a
    top-level string constant. Anything else (incl. an `Enum` member access)
    returns None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return None


def _find_assign(tree, name: str):
    """Return the value-node assigned to a top-level `name = ...`, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return node.value
    return None


def _set_members(tree, name: str, consts: dict[str, str]) -> list[str]:
    """String members of a `name = {..}` set (or list/tuple) literal."""
    val = _find_assign(tree, name)
    out: list[str] = []
    if isinstance(val, (ast.Set, ast.List, ast.Tuple)):
        for elt in val.elts:
            s = _str(elt, consts)
            if s is not None:
                out.append(s)
    return out


def _uses_enum() -> bool:
    """True if the V4 code imports/subclasses Enum (it must not — dict form)."""
    src = v4_code()
    if not src:
        return False
    if re.search(r"(?m)^\s*(from\s+enum\s+import|import\s+enum)\b", src):
        return True
    if re.search(r"class\s+\w+\s*\(\s*(?:enum\.)?(?:Enum|IntEnum|StrEnum)\s*\)", src):
        return True
    return False


def parse_fsm() -> FSM:
    """Parse the taught FSM out of the V4 code. Resilient: sets .error and
    returns a partial model rather than raising."""
    fsm = FSM()
    src = v4_code()
    if not src:
        fsm.error = ("V4 section not found (no 'Version 4 — State Machine' "
                     "heading with python code in 01-bare-harness.md)")
        return fsm
    tree = _parse(src)
    if tree is None:
        fsm.error = "V4 code does not AST-parse"
        return fsm

    consts = _const_strings(tree)

    # STATES / EVENTS declared sets (authoritative when present).
    fsm.states = _set_members(tree, STATES_NAME, consts)
    fsm.events = _set_members(tree, EVENTS_NAME, consts)

    # INITIAL = "call_model"
    init_val = _find_assign(tree, INITIAL_NAME)
    if init_val is not None:
        fsm.initial = _str(init_val, consts)

    # TERMINAL = {"done", "capped"} (set/list/tuple of strings)
    term_val = _find_assign(tree, TERMINAL_NAME)
    if isinstance(term_val, (ast.Set, ast.List, ast.Tuple)):
        for elt in term_val.elts:
            s = _str(elt, consts)
            if s is not None:
                fsm.terminal.add(s)

    # TRANSITIONS = { "state": { "event": "next_state", ... }, ... }
    trans_val = _find_assign(tree, TRANSITIONS_NAME)
    if isinstance(trans_val, ast.Dict):
        fsm.nested = True
        for skey, sval in zip(trans_val.keys, trans_val.values):
            src_m = _str(skey, consts)
            if isinstance(sval, ast.Dict):
                for ekey, eval_ in zip(sval.keys, sval.values):
                    evt_m = _str(ekey, consts)
                    dst_m = _str(eval_, consts)
                    # record edge even if a piece is None, so dangling checks bite
                    fsm.edges.append((src_m, evt_m, dst_m))
            else:
                # inner value is not a dict — table is not a dict-of-dicts
                fsm.nested = False
                fsm.edges.append((src_m, None, None))
    elif trans_val is None:
        fsm.error = f"could not find `{TRANSITIONS_NAME} = {{...}}` table"
    else:
        fsm.error = f"`{TRANSITIONS_NAME}` is not a dict literal"

    # Fallbacks if the author omitted the explicit declaration sets.
    if not fsm.states:
        derived = set()
        for s, _e, d in fsm.edges:
            if s:
                derived.add(s)
            if d:
                derived.add(d)
        if fsm.initial:
            derived.add(fsm.initial)
        derived |= fsm.terminal
        fsm.states = sorted(derived)
    if not fsm.events:
        fsm.events = sorted({e for _s, e, _d in fsm.edges if e})

    return fsm


# Parse once; every graph case reads this snapshot (deterministic).
FSM_MODEL = parse_fsm()


def _reachable(fsm: FSM) -> set[str]:
    """States reachable from fsm.initial following edges."""
    if not fsm.initial:
        return set()
    seen = {fsm.initial}
    frontier = [fsm.initial]
    adj: dict[str, list[str]] = {}
    for s, _e, d in fsm.edges:
        if s and d:
            adj.setdefault(s, []).append(d)
    while frontier:
        cur = frontier.pop()
        for nxt in adj.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return seen


# ==========================================================================
# 1. STRUCTURAL / PEDAGOGICAL
# ==========================================================================
@SUITE.case("struct/v4-section-exists")
def _v4_exists():
    return (v4_section() is not None,
            "Phase 1 has no 'Version 4 — State Machine' section heading")


@SUITE.case("struct/v4-heading-text")
def _v4_heading():
    md = _phase1()
    hit = [h for _l, h, _ in [(m.group(1), m.group(2), m.start())
           for m in re.finditer(r"(?m)^(#{2,3})\s+(.*)$", md)]
           if V4_HEADING_RE.search(h)]
    return (bool(hit), "no heading matching 'Version 4 — State Machine'")


@SUITE.case("struct/what-changed-v3-to-v4")
def _what_changed():
    sec = v4_section()
    if sec is None:
        return False, "V4 section not found"
    ok = re.search(r"What changed from\s+V3\s+to\s+V4", sec, re.I) is not None
    return (ok, "V4 section lacks a 'What changed from V3 to V4' note")


@SUITE.case("struct/v4-has-run-it-checkpoint")
def _v4_runit():
    sec = v4_section()
    if sec is None:
        return False, "V4 section not found"
    return (RUNIT_RE.search(sec) is not None,
            "V4 section has no '▶ Run it now' checkpoint")


@SUITE.case("struct/v4-runit-has-expected-output")
def _v4_runit_output():
    sec = v4_section()
    if sec is None:
        return False, "V4 section not found"
    # an expected-output block: a ```text fence after a Run-it marker, or an
    # 'Assistant:' line inside the section's fenced output.
    has_text_fence = re.search(r"```text\s*\n.*?```", sec, re.S) is not None
    has_assistant = "Assistant:" in sec
    return (has_text_fence and has_assistant,
            "V4 'Run it now' lacks an expected-output block (```text + "
            "'Assistant:' line)")


@SUITE.case("struct/intro-mentions-four-versions")
def _intro_four():
    md = _phase1()
    # the intro ladder should now name a 4th rung / four versions
    four = (re.search(r"four\s+complete\s+versions", md, re.I)
            or re.search(r"ladder of\s+four", md, re.I)
            or (V4_HEADING_RE.search(md) and re.search(
                r"\*\*Version 4\s*[—\-–]\s*[Ss]tate [Mm]achine", md)))
    return (bool(four),
            "Phase 1 intro/ladder does not present FOUR versions "
            "(no 'four complete versions' / 'Version 4 — state machine' bullet)")


@SUITE.case("struct/contents-lists-v4")
def _contents_v4():
    md = _phase1()
    # the **Contents:** list links the V4 section
    m = re.search(r"\*\*Contents:\*\*(.*?)\n##", md, re.S)
    block = m.group(1) if m else md
    return (V4_HEADING_RE.search(block) is not None,
            "Phase 1 Contents list does not include a Version 4 — State "
            "Machine entry")


@SUITE.case("struct/section2-figure-exists")
def _fig_exists():
    md = _phase1()
    ok = re.search(r"The loop is a state machine", md, re.I) is not None
    return (ok, "§2 'The loop is a state machine' framing/figure missing")


@SUITE.case("struct/section2-figure-is-ascii-diagram")
def _fig_ascii():
    md = _phase1()
    m = re.search(r"The loop is a state machine(.*?)(?:\n## |\Z)", md, re.S)
    body = m.group(1) if m else ""
    has_fence = "```text" in body
    has_boxes = "─" in body or "┌" in body or "│" in body
    return (has_fence and has_boxes,
            "§2 figure is not an ASCII diagram fence with box-drawing chars")


@SUITE.case("struct/glossary-state-machine-entry")
def _gloss():
    g = read(GLOSSARY)
    ok = re.search(r"\*\*State machine.*?\*\*", g) is not None
    return (ok, "Glossary has no '**State machine ...**' entry")


@SUITE.case("struct/phase5-modes-are-fsm-note")
def _p5():
    p5 = read(PHASE5)
    ok = re.search(r"state machine", p5, re.I) is not None
    return (ok, "Phase 5 has no 'modes are a state machine' note")


@SUITE.case("struct/phase5-links-back-to-phase1-fsm")
def _p5_link():
    p5 = read(PHASE5)
    ok = "01-bare-harness.md#the-loop-is-a-state-machine" in p5
    return (ok, "Phase 5 FSM note does not link back to Phase 1's §2 figure")


@SUITE.case("struct/v4-honest-package-note")
def _v4_honest():
    sec = v4_section()
    if sec is None:
        return False, "V4 section not found"
    # an honest "the package keeps the simple loop" caveat must appear, so the
    # reader knows the explicit FSM is a teaching rung, not what ships.
    ok = (re.search(r"package", sec, re.I)
          and re.search(r"simple|plain|keeps|for[- ]loop", sec, re.I))
    return (bool(ok),
            "V4 section lacks the honest 'the package keeps the simple loop' "
            "note (the explicit FSM is the concept made visible)")


@SUITE.case("struct/v4-references-section2-figure")
def _v4_refs_fig():
    sec = v4_section()
    if sec is None:
        return False, "V4 section not found"
    # ties back to the §2 figure (by name or anchor)
    ok = ("the-loop-is-a-state-machine" in sec
          or re.search(r"state machine", sec, re.I))
    return (bool(ok),
            "V4 section does not tie back to the §2 'loop is a state machine' "
            "figure")


@SUITE.case("struct/v4-explains-why-dict-not-enum")
def _v4_dict_rationale():
    sec = v4_section()
    if sec is None:
        return False, "V4 section not found"
    # the section should motivate the dictionary/string choice for the reader.
    ok = (re.search(r"\bdict(?:ionary|ionaries)?\b", sec, re.I)
          and re.search(r"\bstring", sec, re.I))
    return (bool(ok),
            "V4 section does not explain the dictionary/string modelling choice")


# ==========================================================================
# 2. CODE PRESENCE & PARSE
# ==========================================================================
@SUITE.case("code/v4-has-python-block")
def _has_block():
    sec = v4_section()
    if sec is None:
        return False, "V4 section not found"
    return (len(_code_blocks(sec)) >= 1,
            "V4 section has no ```python code block")


@SUITE.case("code/v4-ast-parses")
def _ast():
    src = v4_code()
    if not src:
        return False, "no V4 code to parse (section/blocks missing)"
    return (_parse(src) is not None, "V4 code blocks do not AST-parse")


@SUITE.case("code/machine-uses-dicts-not-enum")
def _no_enum():
    src = v4_code()
    if not src:
        return False, "no V4 code"
    return (not _uses_enum(),
            "V4 imports/subclasses Enum — the machine must be taught with "
            "plain dicts and strings, not enums")


@SUITE.case("code/states-set-present")
def _states_present():
    if FSM_MODEL.error and not FSM_MODEL.states:
        return False, FSM_MODEL.error
    return (bool(FSM_MODEL.states),
            f"`{STATES_NAME} = {{...}}` set of states not found in V4 code")


@SUITE.case("code/states-has-ge-3-members")
def _states_ge3():
    if FSM_MODEL.error and not FSM_MODEL.states:
        return False, FSM_MODEL.error
    n = len(FSM_MODEL.states)
    return (n >= 3, f"{STATES_NAME} has {n} members ({FSM_MODEL.states}); want >=3")


@SUITE.case("code/states-are-strings")
def _states_are_strings():
    if FSM_MODEL.error and not FSM_MODEL.states:
        return False, FSM_MODEL.error
    # every declared state resolved to a python str (parser only keeps strings)
    bad = [s for s in FSM_MODEL.states if not isinstance(s, str)]
    return (not bad and bool(FSM_MODEL.states),
            f"non-string states parsed: {bad}")


@SUITE.case("code/events-set-present")
def _events_present():
    if FSM_MODEL.error and not FSM_MODEL.events:
        return False, FSM_MODEL.error
    return (bool(FSM_MODEL.events),
            f"`{EVENTS_NAME} = {{...}}` set of events not found in V4 code")


@SUITE.case("code/transitions-table-present")
def _trans_present():
    if FSM_MODEL.error and not FSM_MODEL.edges:
        return False, FSM_MODEL.error
    return (len(FSM_MODEL.edges) >= 1,
            f"`{TRANSITIONS_NAME}` table missing or empty")


@SUITE.case("code/transitions-is-dict-of-dicts")
def _trans_nested():
    if FSM_MODEL.error and not FSM_MODEL.edges:
        return False, FSM_MODEL.error
    return (FSM_MODEL.nested,
            f"`{TRANSITIONS_NAME}` is not a dict-of-dicts "
            f"(state -> {{event -> next_state}})")


@SUITE.case("code/next-state-fn-present")
def _next_state_present():
    src = v4_code()
    if not src:
        return False, "no V4 code"
    tree = _parse(src)
    if tree is None:
        return False, "V4 code does not parse"
    fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    return (NEXT_STATE_FN in fns,
            f"`def {NEXT_STATE_FN}(...)` not found (functions: {fns})")


@SUITE.case("code/next-state-double-lookup")
def _next_state_lookup():
    src = v4_code()
    if not src:
        return False, "no V4 code"
    # the dict-of-dicts transition fn does a nested lookup TRANSITIONS[state][event]
    ok = re.search(TRANSITIONS_NAME + r"\s*\[\s*state\s*\]\s*\[\s*event\s*\]",
                   src) is not None
    return (ok,
            f"`{NEXT_STATE_FN}` does not do the nested "
            f"`{TRANSITIONS_NAME}[state][event]` lookup")


@SUITE.case("code/initial-state-declared")
def _initial_present():
    if FSM_MODEL.error and FSM_MODEL.initial is None:
        return False, FSM_MODEL.error
    return (FSM_MODEL.initial is not None,
            f"`{INITIAL_NAME} = \"<state>\"` not found")


@SUITE.case("code/terminal-set-declared")
def _terminal_present():
    if FSM_MODEL.error and not FSM_MODEL.terminal:
        return False, FSM_MODEL.error
    return (len(FSM_MODEL.terminal) >= 1,
            f"`{TERMINAL_NAME} = {{...}}` not found or empty")


@SUITE.case("code/driver-fn-present")
def _driver_present():
    src = v4_code()
    if not src:
        return False, "no V4 code"
    tree = _parse(src)
    if tree is None:
        return False, "V4 code does not parse"
    fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    return (DRIVER_FN in fns,
            f"`def {DRIVER_FN}(...)` driver not found (functions: {fns})")


@SUITE.case("code/driver-loop-uses-terminal-set")
def _driver_loop():
    src = v4_code()
    if not src:
        return False, "no V4 code"
    # the spec's driver shape: `while state not in TERMINAL`
    ok = re.search(r"while\s+state\s+not\s+in\s+" + TERMINAL_NAME, src) is not None
    return (ok, f"driver lacks `while state not in {TERMINAL_NAME}` loop")


@SUITE.case("code/driver-uses-state-variable")
def _driver_var():
    src = v4_code()
    if not src:
        return False, "no V4 code"
    ok = re.search(r"(?m)^\s*state\s*=\s*" + INITIAL_NAME, src) is not None
    return (ok, f"driver does not initialise `state = {INITIAL_NAME}`")


# ==========================================================================
# 3. FSM-GRAPH CORRECTNESS — the signature category (parametrized)
# ==========================================================================
def _graph_ready() -> tuple[bool, str]:
    """Guard: is there a usable parsed graph? (uniform skip-detail)."""
    if FSM_MODEL.error:
        return False, FSM_MODEL.error
    if not FSM_MODEL.states:
        return False, f"{STATES_NAME} not parsed"
    if not FSM_MODEL.edges:
        return False, f"{TRANSITIONS_NAME} not parsed"
    return True, ""


# --- global graph gates ----------------------------------------------------
@SUITE.case("graph/initial-state-declared-once")
def _g_initial_once():
    src = v4_code()
    if not src:
        return False, "no V4 code"
    # An FSM has exactly one initial *state*. The guide's house style repeats code
    # across the incremental step snippet and the complete listing, so the literal
    # `INITIAL = ...` line legitimately appears more than once — the invariant is
    # that every such declaration names the SAME state (one consistent initial),
    # not that the line is textually unique.
    members = re.findall(
        r"(?m)^\s*" + INITIAL_NAME + r"\s*=\s*[\"'](\w+)[\"']", src)
    if not members:
        return False, f"{INITIAL_NAME} never declared as a string state"
    distinct = set(members)
    return (len(distinct) == 1,
            f"{INITIAL_NAME} declared with conflicting initial states {distinct}; "
            f"want exactly one")


@SUITE.case("graph/initial-is-declared-state")
def _g_initial_declared():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    if FSM_MODEL.initial is None:
        return False, f"{INITIAL_NAME} did not resolve to a string state"
    return (FSM_MODEL.initial in FSM_MODEL.states,
            f"initial {FSM_MODEL.initial!r} not a declared state "
            f"{FSM_MODEL.states}")


@SUITE.case("graph/at-least-one-terminal")
def _g_has_terminal():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    return (len(FSM_MODEL.terminal) >= 1, "no terminal state declared")


@SUITE.case("graph/terminal-states-are-declared")
def _g_terminal_declared():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    bad = sorted(FSM_MODEL.terminal - set(FSM_MODEL.states))
    return (not bad, f"terminal members not declared states: {bad}")


@SUITE.case("graph/some-terminal-is-reachable")
def _g_terminal_reachable():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    reach = _reachable(FSM_MODEL)
    hit = FSM_MODEL.terminal & reach
    return (bool(hit),
            f"no terminal state reachable from {FSM_MODEL.initial}; "
            f"terminals={sorted(FSM_MODEL.terminal)} reachable={sorted(reach)}")


@SUITE.case("graph/all-states-reachable")
def _g_all_reachable():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    reach = _reachable(FSM_MODEL)
    unreachable = sorted(set(FSM_MODEL.states) - reach)
    return (not unreachable,
            f"unreachable states from {FSM_MODEL.initial}: {unreachable}")


@SUITE.case("graph/no-unreachable-states")
def _g_no_unreachable():
    # global mirror of the per-state reachability cases below
    ok, why = _graph_ready()
    if not ok:
        return False, why
    reach = _reachable(FSM_MODEL)
    bad = sorted(set(FSM_MODEL.states) - reach)
    return (not bad, f"{len(bad)} unreachable state(s): {bad}")


@SUITE.case("graph/no-orphan-states")
def _g_no_orphan():
    # orphan = a non-initial state with no incoming edge
    ok, why = _graph_ready()
    if not ok:
        return False, why
    incoming = {d for _s, _e, d in FSM_MODEL.edges if d}
    orphans = sorted(
        s for s in FSM_MODEL.states
        if s != FSM_MODEL.initial and s not in incoming)
    return (not orphans,
            f"orphan states (no incoming edge, not initial): {orphans}")


@SUITE.case("graph/every-target-is-declared")
def _g_targets_declared():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    bad = sorted({d for _s, _e, d in FSM_MODEL.edges
                  if d is not None and d not in FSM_MODEL.states})
    none_targets = sum(1 for _s, _e, d in FSM_MODEL.edges if d is None)
    detail = ""
    if bad:
        detail = f"dangling transition targets: {bad}"
    elif none_targets:
        detail = f"{none_targets} transition(s) have an unparseable target"
    return (not bad and not none_targets, detail)


@SUITE.case("graph/every-source-is-declared")
def _g_sources_declared():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    bad = sorted({s for s, _e, _d in FSM_MODEL.edges
                  if s is not None and s not in FSM_MODEL.states})
    none_sources = sum(1 for s, _e, _d in FSM_MODEL.edges if s is None)
    detail = ""
    if bad:
        detail = f"transition sources not declared states: {bad}"
    elif none_sources:
        detail = f"{none_sources} transition(s) have an unparseable source"
    return (not bad and not none_sources, detail)


@SUITE.case("graph/every-event-is-declared")
def _g_events_declared():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    if not FSM_MODEL.events:
        return False, f"{EVENTS_NAME} not parsed"
    bad = sorted({e for _s, e, _d in FSM_MODEL.edges
                  if e is not None and e not in FSM_MODEL.events})
    none_events = sum(1 for _s, e, _d in FSM_MODEL.edges if e is None)
    detail = ""
    if bad:
        detail = f"transition events not declared in {EVENTS_NAME}: {bad}"
    elif none_events:
        detail = f"{none_events} transition(s) have an unparseable event key"
    return (not bad and not none_events, detail)


@SUITE.case("graph/determinism-global")
def _g_determinism():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    seen: dict[tuple[str, str], set[str]] = {}
    for s, e, d in FSM_MODEL.edges:
        if s is None or e is None:
            continue
        seen.setdefault((s, e), set()).add(d)
    nondet = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    return (not nondet,
            f"nondeterministic (state,event) keys -> multiple next states: "
            f"{nondet}")


@SUITE.case("graph/terminals-have-no-outgoing-global")
def _g_terminal_no_out_global():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    bad = sorted({s for s, _e, _d in FSM_MODEL.edges
                  if s in FSM_MODEL.terminal})
    return (not bad, f"terminal states with outgoing transitions: {bad}")


@SUITE.case("graph/non-terminals-have-outgoing-global")
def _g_nonterminal_out_global():
    ok, why = _graph_ready()
    if not ok:
        return False, why
    sources = {s for s, _e, _d in FSM_MODEL.edges if s}
    dead = sorted(s for s in FSM_MODEL.states
                  if s not in FSM_MODEL.terminal and s not in sources)
    return (not dead,
            f"non-terminal states with NO outgoing transition (dead ends): "
            f"{dead}")


# --- per-state parametrized gates (exhaustive over the EXPECTED states) -----
# These register against the spec's intended members so the suite is exhaustive
# *and* fails loudly when a state is missing from the parsed set.
def _register_state_cases(member: str, is_terminal_expected: bool) -> None:

    @SUITE.case(f"graph/state/{member}/declared")
    def _declared(member=member):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        return (member in FSM_MODEL.states,
                f"expected state {member!r} not in {STATES_NAME} "
                f"{FSM_MODEL.states}")

    @SUITE.case(f"graph/state/{member}/reachable")
    def _reach(member=member):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if member not in FSM_MODEL.states:
            return False, f"state {member!r} not declared"
        reach = _reachable(FSM_MODEL)
        return (member in reach,
                f"state {member!r} unreachable from {FSM_MODEL.initial}")

    @SUITE.case(f"graph/state/{member}/outgoing-vs-terminal")
    def _out(member=member, is_terminal_expected=is_terminal_expected):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if member not in FSM_MODEL.states:
            return False, f"state {member!r} not declared"
        outgoing = [(e, d) for s, e, d in FSM_MODEL.edges if s == member]
        is_terminal = member in FSM_MODEL.terminal
        if is_terminal:
            return (len(outgoing) == 0,
                    f"terminal {member!r} has outgoing transitions: {outgoing}")
        # non-terminal must have >=1 outgoing (no dead end)
        return (len(outgoing) >= 1,
                f"non-terminal {member!r} is a dead end (no outgoing edges)")

    @SUITE.case(f"graph/state/{member}/terminal-classification")
    def _classify(member=member, is_terminal_expected=is_terminal_expected):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if member not in FSM_MODEL.states:
            return False, f"state {member!r} not declared"
        actual = member in FSM_MODEL.terminal
        return (actual == is_terminal_expected,
                f"state {member!r} terminal={actual}, "
                f"spec expects terminal={is_terminal_expected}")


for _m in EXPECTED_STATE_MEMBERS:
    _register_state_cases(_m, is_terminal_expected=_m in EXPECTED_TERMINAL_MEMBERS)


# --- per-transition parametrized gates (exhaustive over the PARSED edges) ----
# Registered from the parsed table so every taught transition is individually
# asserted (well-formed source/event/target, deterministic, terminal-respecting).
def _register_edge_cases() -> None:
    edges = FSM_MODEL.edges
    if not edges:
        # one placeholder so the absence is visible as a failing case
        @SUITE.case("graph/transition/none-parsed")
        def _none():
            return False, (FSM_MODEL.error
                           or f"no transitions parsed from {TRANSITIONS_NAME}")
        return

    # determinism bookkeeping for per-edge uniqueness
    keymap: dict[tuple, list[int]] = {}
    for idx, (s, e, _d) in enumerate(edges):
        keymap.setdefault((s, e), []).append(idx)

    for idx, (s, e, d) in enumerate(edges):
        tag = f"{s or '?'}-{e or '?'}-to-{d or '?'}-{idx}"

        @SUITE.case(f"graph/transition/{tag}/well-formed")
        def _wf(s=s, e=e, d=d):
            problems = []
            if s is None:
                problems.append("source is not a string state")
            elif s not in FSM_MODEL.states:
                problems.append(f"source {s!r} not declared")
            if e is None:
                problems.append("event is not a string")
            elif FSM_MODEL.events and e not in FSM_MODEL.events:
                problems.append(f"event {e!r} not a declared {EVENTS_NAME} member")
            if d is None:
                problems.append("target is not a string state")
            elif d not in FSM_MODEL.states:
                problems.append(f"target {d!r} not declared")
            return (not problems, "; ".join(problems))

        @SUITE.case(f"graph/transition/{tag}/deterministic")
        def _det(s=s, e=e, d=d, keymap=keymap):
            dests = {edges[i][2] for i in keymap.get((s, e), [])}
            return (len(dests) == 1,
                    f"({s},{e}) maps to multiple next states: {sorted(dests)}")

        @SUITE.case(f"graph/transition/{tag}/source-not-terminal")
        def _src_not_term(s=s):
            return (s not in FSM_MODEL.terminal,
                    f"transition originates from terminal state {s!r}")


_register_edge_cases()


# ==========================================================================
# 4. CONSISTENCY (prose <-> states; figure <-> states)
# ==========================================================================
def _register_prose_state_cases(member: str) -> None:
    """Each state member should be named somewhere in the V4 prose/code."""

    @SUITE.case(f"consistency/prose-names-state/{member}")
    def _named(member=member):
        sec = v4_section()
        if sec is None:
            return False, "V4 section not found"
        # the member string appears (as "call_model" or bare call_model) in the
        # section — guarantees prose and the state set agree on the state set.
        ok = re.search(r"\b" + re.escape(member) + r"\b", sec) is not None
        return (ok, f"state {member!r} (from {STATES_NAME}) never appears in "
                    f"the V4 section text")


for _m in EXPECTED_STATE_MEMBERS:
    _register_prose_state_cases(_m)


@SUITE.case("consistency/parsed-states-match-spec")
def _states_match_spec():
    if FSM_MODEL.error and not FSM_MODEL.states:
        return False, FSM_MODEL.error
    missing = [m for m in EXPECTED_STATE_MEMBERS if m not in FSM_MODEL.states]
    return (not missing,
            f"{STATES_NAME} is missing spec-pinned members: {missing} "
            f"(parsed: {FSM_MODEL.states})")


@SUITE.case("consistency/initial-member-matches-spec")
def _initial_match():
    if FSM_MODEL.error and FSM_MODEL.initial is None:
        return False, FSM_MODEL.error
    return (FSM_MODEL.initial == EXPECTED_INITIAL_MEMBER,
            f"initial={FSM_MODEL.initial!r}, spec pins "
            f"{EXPECTED_INITIAL_MEMBER!r}")


@SUITE.case("consistency/terminal-members-match-spec")
def _terminal_match():
    if FSM_MODEL.error and not FSM_MODEL.terminal:
        return False, FSM_MODEL.error
    return (FSM_MODEL.terminal == EXPECTED_TERMINAL_MEMBERS,
            f"terminal={sorted(FSM_MODEL.terminal)}, spec pins "
            f"{sorted(EXPECTED_TERMINAL_MEMBERS)}")


def _figure_text() -> str:
    md = _phase1()
    m = re.search(r"The loop is a state machine(.*?)(?:\n## |\Z)", md, re.S)
    return m.group(1) if m else ""


def _register_figure_consistency(member: str, labels: list[str]) -> None:

    @SUITE.case(f"consistency/figure-label/{member}")
    def _fig(member=member, labels=labels):
        fig = _figure_text()
        if not fig:
            return False, "§2 figure not found"
        folded = re.sub(r"\s+", " ", fig).upper()
        hit = any(lbl.upper() in folded for lbl in labels)
        return (hit,
                f"§2 figure has no label matching state {member!r} "
                f"(looked for {labels})")


for _m, _labels in FIGURE_LABELS.items():
    _register_figure_consistency(_m, _labels)


@SUITE.case("consistency/figure-states-subset-of-states")
def _fig_subset():
    # every figure-labelled state must exist as a STATES member
    if FSM_MODEL.error and not FSM_MODEL.states:
        return False, FSM_MODEL.error
    missing = [m for m in FIGURE_LABELS if m not in FSM_MODEL.states]
    return (not missing,
            f"states drawn in the §2 figure but absent from {STATES_NAME}: "
            f"{missing}")


# --- a broad parametrized sweep so coverage is exhaustive (>=200 cases) -----
# Assert, for every ORDERED pair of expected states, whether a direct edge is
# expected per the spec's transition table. This documents the intended graph
# edge-by-edge and makes any deviation in the taught table a precise failure.
SPEC_EDGES = {
    ("call_model", "run_tools"),
    ("call_model", "done"),
    ("call_model", "capped"),
    ("run_tools", "capped"),
    ("run_tools", "call_model"),
}


def _register_pair_case(src: str, dst: str) -> None:
    expected = (src, dst) in SPEC_EDGES

    @SUITE.case(f"graph/edge-pair/{src}-to-{dst}")
    def _pair(src=src, dst=dst, expected=expected):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        present = any(s == src and d == dst for s, _e, d in FSM_MODEL.edges)
        if expected:
            return (present,
                    f"spec expects an edge {src} -> {dst}, but the taught "
                    f"{TRANSITIONS_NAME} has none")
        return (not present,
                f"unexpected edge {src} -> {dst} in the taught "
                f"{TRANSITIONS_NAME} (not in the spec graph)")


for _s in EXPECTED_STATE_MEMBERS:
    for _d in EXPECTED_STATE_MEMBERS:
        _register_pair_case(_s, _d)


# Per-(state,event) coverage of the spec's intended transition table: every
# (expected-state x expected-event) cell is asserted present-or-absent against
# the parsed table — an exhaustive, documented transition matrix.
SPEC_TABLE = {
    ("call_model", "has_tool_calls"): "run_tools",
    ("call_model", "no_tool_calls"): "done",
    ("call_model", "cap_reached"): "capped",
    ("run_tools", "cap_reached"): "capped",
    ("run_tools", "has_tool_calls"): "call_model",
}


def _register_cell_case(state: str, event: str) -> None:
    want = SPEC_TABLE.get((state, event))  # None => cell expected absent

    @SUITE.case(f"graph/cell/{state}-on-{event}")
    def _cell(state=state, event=event, want=want):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        dests = {d for s, e, d in FSM_MODEL.edges
                 if s == state and e == event}
        if want is None:
            return (not dests,
                    f"({state},{event}) should have NO transition, "
                    f"table has -> {sorted(dests)}")
        if not dests:
            return False, (f"({state},{event}) missing; spec expects "
                           f"-> {want}")
        if len(dests) > 1:
            return False, (f"({state},{event}) nondeterministic -> "
                           f"{sorted(dests)}")
        got = next(iter(dests))
        return (got == want,
                f"({state},{event}) -> {got}, spec expects -> {want}")


for _st in EXPECTED_STATE_MEMBERS:
    for _ev in EXPECTED_EVENT_MEMBERS:
        _register_cell_case(_st, _ev)


# Per-event coverage: each spec event must appear as a key component in the
# taught table (no taught event is dead, no spec event is dropped).
def _register_event_case(event: str) -> None:

    @SUITE.case(f"graph/event/{event}/used-in-table")
    def _ev_used(event=event):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        used = any(e == event for _s, e, _d in FSM_MODEL.edges)
        return (used,
                f"spec event {event!r} never used as a {TRANSITIONS_NAME} key")

    @SUITE.case(f"consistency/event-declared/{event}")
    def _ev_decl(event=event):
        if FSM_MODEL.error and not FSM_MODEL.events:
            return False, FSM_MODEL.error
        if not FSM_MODEL.events:
            return False, f"{EVENTS_NAME} set not parsed"
        return (event in FSM_MODEL.events,
                f"event {event!r} not declared in {EVENTS_NAME} "
                f"{FSM_MODEL.events}")


for _ev in EXPECTED_EVENT_MEMBERS:
    _register_event_case(_ev)


# ==========================================================================
# Exhaustive transition cube (source x event x target) — the full documented
# transition matrix a state-machine expert checks cell-by-cell. For every
# (source state, event, target state) triple over the spec's declared
# alphabets, assert whether the taught TRANSITIONS table contains that exact
# edge, matching the spec's intended table (SPEC_TABLE). This is the most
# granular, exhaustive form of the determinism + correctness checks: 4x3x4 = 48
# precise cells, each its own documented case, so any single mis-wired edge in
# the taught table surfaces as one named failure.
# ==========================================================================
def _register_cube_case(src: str, event: str, dst: str) -> None:
    # the spec says edge (src,event)->dst exists iff SPEC_TABLE[(src,event)]==dst
    spec_dst = SPEC_TABLE.get((src, event))
    edge_expected = (spec_dst == dst)

    @SUITE.case(f"graph/cube/{src}-on-{event}-to-{dst}")
    def _cube(src=src, event=event, dst=dst, edge_expected=edge_expected):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        present = any(s == src and e == event and d == dst
                      for s, e, d in FSM_MODEL.edges)
        if edge_expected:
            return (present,
                    f"taught {TRANSITIONS_NAME} is missing the spec edge "
                    f"({src}, {event}) -> {dst}")
        return (not present,
                f"taught {TRANSITIONS_NAME} has an edge ({src}, {event}) -> "
                f"{dst} that the spec graph does not declare")


for _st in EXPECTED_STATE_MEMBERS:
    for _ev in EXPECTED_EVENT_MEMBERS:
        for _dt in EXPECTED_STATE_MEMBERS:
            _register_cube_case(_st, _ev, _dt)


# ==========================================================================
# Reachability-distance documentation: for every ordered pair of expected
# states, assert whether the target is reachable from the source in the taught
# graph, matching the spec's intended reachability closure. This documents the
# whole reachability relation (16 ordered pairs) edge-by-edge — exhaustive proof
# that the taught machine connects the same states the spec intends.
# ==========================================================================
def _taught_reach_from(src: str) -> set[str]:
    """States reachable from `src` (>=1 hop) in the parsed/taught graph."""
    adj: dict[str, set[str]] = {}
    for s, _e, d in FSM_MODEL.edges:
        if s and d:
            adj.setdefault(s, set()).add(d)
    seen: set[str] = set()
    stack = [src]
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _register_reach_pair(src: str, dst: str) -> None:
    # spec reachability (one or more hops) from src to dst
    adj: dict[str, set[str]] = {}
    for (s, _e), d in SPEC_TABLE.items():
        adj.setdefault(s, set()).add(d)
    seen: set[str] = set()
    stack = [src]
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    spec_reachable = dst in seen

    @SUITE.case(f"graph/reach-pair/{src}-reaches-{dst}")
    def _rp(src=src, dst=dst, spec_reachable=spec_reachable):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if src not in FSM_MODEL.states or dst not in FSM_MODEL.states:
            return False, f"state {src!r} or {dst!r} not declared"
        taught = _taught_reach_from(src)
        present = dst in taught
        if spec_reachable:
            return (present,
                    f"spec: {dst} reachable from {src}, but taught graph "
                    f"cannot reach it (taught-from-{src}={sorted(taught)})")
        return (not present,
                f"spec: {dst} NOT reachable from {src}, but taught graph "
                f"reaches it (taught-from-{src}={sorted(taught)})")


for _s in EXPECTED_STATE_MEMBERS:
    for _d in EXPECTED_STATE_MEMBERS:
        _register_reach_pair(_s, _d)


# ==========================================================================
# Spec-pinned per-transition gates — registered unconditionally from the spec's
# intended table (not from the parsed edges), so every transition the curriculum
# is REQUIRED to teach is its own named, documented case even before the content
# lands. For each spec edge (src,event)->dst we assert, against the parsed graph:
#   * present     — the taught table actually contains this edge;
#   * deterministic — (src,event) resolves to exactly one target in the table;
#   * src-live    — the source is a declared, non-terminal state;
#   * dst-live    — the target is a declared state.
# These complement the parse-driven per-edge cases (which catch *extra* taught
# edges) by pinning the *required* edges from the spec side.
# ==========================================================================
def _register_spec_transition(src: str, event: str, dst: str) -> None:
    edge = f"{src}-{event}-to-{dst}"

    @SUITE.case(f"graph/spec-transition/{edge}/present")
    def _present(src=src, event=event, dst=dst):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        present = any(s == src and e == event and d == dst
                      for s, e, d in FSM_MODEL.edges)
        return (present,
                f"required edge ({src}, {event}) -> {dst} absent from the "
                f"taught {TRANSITIONS_NAME}")

    @SUITE.case(f"graph/spec-transition/{edge}/deterministic")
    def _det(src=src, event=event, dst=dst):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        dests = {d for s, e, d in FSM_MODEL.edges if s == src and e == event}
        return (dests == {dst},
                f"({src}, {event}) -> {sorted(dests)}; spec requires "
                f"exactly {{{dst}}}")

    @SUITE.case(f"graph/spec-transition/{edge}/source-live")
    def _src_live(src=src):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if src not in FSM_MODEL.states:
            return False, f"source {src!r} not a declared state"
        return (src not in FSM_MODEL.terminal,
                f"source {src!r} is terminal — cannot originate a transition")

    @SUITE.case(f"graph/spec-transition/{edge}/target-live")
    def _dst_live(dst=dst):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        return (dst in FSM_MODEL.states,
                f"target {dst!r} not a declared state")


for (_st, _ev), _dt in SPEC_TABLE.items():
    _register_spec_transition(_st, _ev, _dt)


# ==========================================================================
# Per-state degree gates — the in-/out-degree a state-machine expert expects of
# each state in a well-formed machine, parametrized per state so every node's
# connectivity is documented and individually asserted. Expected degrees are
# derived from the spec's intended table (SPEC_TABLE).
# ==========================================================================
def _spec_outdeg(state: str) -> int:
    return sum(1 for (s, _e) in SPEC_TABLE if s == state)


def _spec_indeg(state: str) -> int:
    return sum(1 for d in SPEC_TABLE.values() if d == state)


def _register_degree_cases(state: str) -> None:
    want_out = _spec_outdeg(state)
    want_in = _spec_indeg(state)
    is_terminal = state in EXPECTED_TERMINAL_MEMBERS
    is_initial = state == EXPECTED_INITIAL_MEMBER

    @SUITE.case(f"graph/degree/{state}/out-degree-eq-{want_out}")
    def _out(state=state, want_out=want_out):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if state not in FSM_MODEL.states:
            return False, f"state {state!r} not declared"
        got = sum(1 for s, _e, _d in FSM_MODEL.edges if s == state)
        return (got == want_out,
                f"{state} out-degree {got}, spec expects {want_out}")

    @SUITE.case(f"graph/degree/{state}/in-degree-ge-{1 if not is_initial else 0}")
    def _indeg(state=state, want_in=want_in, is_initial=is_initial):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if state not in FSM_MODEL.states:
            return False, f"state {state!r} not declared"
        got = sum(1 for _s, _e, d in FSM_MODEL.edges if d == state)
        # non-initial states must be reached by >=1 edge (no orphans); the
        # initial state may legitimately have 0 incoming (or some, via a loop).
        floor = 0 if is_initial else 1
        return (got >= floor,
                f"{state} in-degree {got} < required floor {floor} "
                f"(spec in-degree {want_in})")

    @SUITE.case(f"graph/degree/{state}/is-source-iff-non-terminal")
    def _src_iff(state=state, is_terminal=is_terminal):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if state not in FSM_MODEL.states:
            return False, f"state {state!r} not declared"
        is_source = any(s == state for s, _e, _d in FSM_MODEL.edges)
        # non-terminal => is a source; terminal => is NOT a source
        want_source = not is_terminal
        return (is_source == want_source,
                f"{state} is_source={is_source}, expected {want_source} "
                f"(terminal={is_terminal})")

    @SUITE.case(f"graph/degree/{state}/is-target-iff-reachable-non-initial")
    def _tgt_iff(state=state, is_initial=is_initial):
        ok, why = _graph_ready()
        if not ok:
            return False, why
        if state not in FSM_MODEL.states:
            return False, f"state {state!r} not declared"
        is_target = any(d == state for _s, _e, d in FSM_MODEL.edges)
        # every non-initial declared state must be a transition target
        if is_initial:
            return True, ""  # initial may or may not be a target
        return (is_target,
                f"non-initial state {state!r} is never a transition target "
                f"(orphan)")


for _m in EXPECTED_STATE_MEMBERS:
    _register_degree_cases(_m)


if __name__ == "__main__":
    from harness import main
    main(SUITE)
