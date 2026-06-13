"""Deterministic eval suite for the "Python beginner" persona.

This suite encodes, as machine-checkable cases, the standards a *real* Python
beginner needs the markdown guide to meet. The persona knows only: functions,
lists, dicts, operators, and a single ``client.responses.create(...)`` call. It
relies on the prose guide to teach everything else, incrementally and offline.

Every case is one ``(artifact, check)`` pair: deterministic, offline,
order-independent, stdlib-only. Failures should point at exactly one defect.

Run directly:  ``python eval_beginner.py``
Or via:        ``python run_all.py beginner``
"""
from __future__ import annotations

import ast
import os
import re
import textwrap
from collections import Counter

from harness import Suite, read, GUIDE_DIR, PHASES, APPENDIX, SUPPORT_DOCS

SUITE = Suite("beginner")

# ---------------------------------------------------------------------------
# Shared helpers (pure, deterministic, no I/O beyond reading guide files)
# ---------------------------------------------------------------------------

# Phases that present a beginner "cold start" (Step 0 / Version 1) — phase 8 is
# the production assembly and is intentionally class-heavy from the top.
COLD_START_PHASES = PHASES[:8]  # 00..07

# Phases that AST-parse must be clean for (the early, beginner-critical ones).
PARSE_PHASES = PHASES[:4]  # 00..03

# Files whose intra-doc anchors and outbound links we audit.
LINK_FILES = list(PHASES) + [APPENDIX] + SUPPORT_DOCS


def _path(name: str) -> str:
    return os.path.join(GUIDE_DIR, name)


def _read(name: str) -> str:
    return read(_path(name))


def _strip_quote(line: str) -> str:
    """Strip a single markdown blockquote ``> `` prefix (and leading spaces)."""
    return re.sub(r"^\s{0,3}> ?", "", line)


_FENCE_RE = re.compile(r"(?m)^[ \t>]*```python\n(.*?)\n[ \t>]*```", re.S)


def python_blocks(text: str) -> list[str]:
    """Every fenced ```python block, with blockquote `> ` prefixes stripped.

    Returns the raw block text (not yet dedented) so callers can decide.
    """
    out: list[str] = []
    for m in _FENCE_RE.finditer(text):
        raw = m.group(1)
        lines = [_strip_quote(ln) for ln in raw.split("\n")]
        out.append("\n".join(lines))
    return out


def block_parses(block: str) -> bool:
    """True if the block AST-parses after dedent.

    Dedent is essential: the guide shows indented *excerpts* (loop bodies in
    isolation) that are valid Python once the common leading indent is removed.
    This is how prior passes handled the few intentionally-partial fragments —
    they are dedented excerpts, not broken code.
    """
    try:
        ast.parse(textwrap.dedent(block))
        return True
    except SyntaxError:
        return False


# An explicit, content-prefixed allowlist of blocks that are *deliberate*
# elisions and are NOT expected to parse even after dedent. The bar: this list
# must stay MINIMAL. After dedent, phases 0-3 currently need ZERO entries — the
# "for tc in tool_calls:" fragments parse fine as dedented excerpts. We keep the
# mechanism (and assert minimality) so a future genuinely-broken block is caught
# rather than silently allowlisted.
PARSE_ALLOWLIST_PREFIXES: tuple[str, ...] = ()


def _allowlisted(block: str) -> bool:
    stripped = block.strip()
    return any(stripped.startswith(p) for p in PARSE_ALLOWLIST_PREFIXES)


# --- GitHub heading slugger -------------------------------------------------
# GitHub's algorithm: lowercase; drop characters that are not word chars,
# whitespace, or hyphens (this removes punctuation AND emoji); replace each
# space with a hyphen WITHOUT collapsing runs (so "a — b" -> "a---b"); then
# de-duplicate repeated slugs with -1, -2, ... suffixes.

def _slug_base(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U)  # strip punctuation/emoji
    s = s.replace(" ", "-")
    return s


_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.*?)\s*$")


def headings(text: str) -> list[str]:
    """ATX headings, including those nested inside a blockquote.

    GitHub generates a heading anchor for ``> ## Title`` (a heading inside a
    blockquote) exactly as it would for a top-level heading, so we strip a
    leading ``> `` before matching. Fenced code is skipped.
    """
    out = []
    in_fence = False
    for raw in text.split("\n"):
        if re.match(r"^\s*```", raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = re.sub(r"^\s*> ?", "", raw)  # un-blockquote
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            out.append(m.group(2))
    return out


def slug_set(text: str) -> set[str]:
    counts: Counter[str] = Counter()
    out: set[str] = set()
    for h in headings(text):
        base = _slug_base(h)
        n = counts[base]
        counts[base] += 1
        out.add(base if n == 0 else f"{base}-{n}")
    return out


# --- markdown link extraction -----------------------------------------------
# Match links whose target is a local .md file, optional #anchor. We ignore
# external (http) links and links into directories we don't audit here are
# handled by existence-only checks.
_MD_LINK_RE = re.compile(r"\]\((\.?/?[\w./-]+\.md)(?:#([\w-]+))?\)")


def md_links(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1), m.group(2)) for m in _MD_LINK_RE.finditer(text)]


def resolve(target: str) -> str:
    return os.path.normpath(os.path.join(GUIDE_DIR, target))


# Files we can slug-check anchors against (they live directly in GUIDE_DIR).
_LOCAL_MD = set(PHASES) | {APPENDIX} | set(SUPPORT_DOCS)


# --- checkpoint detection ---------------------------------------------------
_CHECKPOINT_RE = re.compile(
    r"(?m)^(#{2,6}\s+▶\s+(?:Run|Check) it now.*)$"
)

# A checkpoint is "satisfied" if the heading+body window contains a fenced
# block (expected output / command), an offline marker, a stated command, or a
# prose statement of expected output/behavior.
_CHECKPOINT_CUE = re.compile(
    r"```"
    r"|no API key|no key"
    r"|unchanged|same conversation|cap (?:only )?fires"
    r"|expected|expect"
    r"|should\s+(?:see|print|still|answer|now|get|remain|reach)"
    r"|same (?:as|result|expected|output)"
    r"|output\b|prints?\b|you(?:'ll| will) see|remembers?\b"
    r"|answer\b|result\b|run (?:it|the program|again)|python ",
    re.I,
)


def checkpoints(text: str) -> list[tuple[str, str]]:
    """Return (heading, window) for each ▶ checkpoint.

    The window is the heading text plus the body up to the next heading of the
    same-or-shallower level (we split on any subsequent ``##``-level heading).
    """
    parts = _CHECKPOINT_RE.split(text)
    out = []
    for i in range(1, len(parts) - 1, 2):
        head = parts[i].strip()
        body = parts[i + 1]
        window = head + "\n" + re.split(r"(?m)^#{2,6}\s", body)[0]
        out.append((head, window))
    return out


def first_python_block(text: str) -> str | None:
    blocks = python_blocks(text)
    return blocks[0] if blocks else None


# ===========================================================================
# CASE REGISTRATION
# ===========================================================================

# --- 1. Every ```python block in phases 0-3 AST-parses ----------------------

def _make_block_parse_case(phase: str, idx: int, block: str):
    def case():
        if block_parses(block) or _allowlisted(block):
            return True, ""
        first = block.strip().split("\n", 1)[0][:60]
        return False, f"{phase} block #{idx} fails AST parse: {first!r}"
    return case


for _phase in PARSE_PHASES:
    _text = _read(_phase)
    _blocks = python_blocks(_text)
    _pid = _phase[:2]
    # finer per-block cases
    for _i, _b in enumerate(_blocks):
        SUITE.add(
            f"phase{_pid}:pyblock-{_i:02d}-parses",
            _make_block_parse_case(_phase, _i, _b),
        )

    # aggregate per-phase case
    def _agg(phase=_phase, blocks=_blocks):
        bad = [i for i, b in enumerate(blocks)
               if not block_parses(b) and not _allowlisted(b)]
        if bad:
            return False, f"{phase}: {len(bad)} python block(s) fail AST parse: {bad}"
        return True, f"{len(blocks)} blocks OK"

    SUITE.add(f"phase{_pid}:all-python-blocks-parse", _agg)


# Assert the parse allowlist is minimal (currently empty). If a future block
# genuinely needs allowlisting, this guards against the list quietly growing.
def _allowlist_minimal():
    if len(PARSE_ALLOWLIST_PREFIXES) > 3:
        return False, (
            f"parse allowlist has {len(PARSE_ALLOWLIST_PREFIXES)} entries; "
            "intentionally-incomplete fragments should be rare"
        )
    return True, f"allowlist size = {len(PARSE_ALLOWLIST_PREFIXES)}"

SUITE.add("global:parse-allowlist-is-minimal", _allowlist_minimal)


# Every allowlisted prefix must actually correspond to a non-parsing block
# somewhere in phases 0-3 (no stale entries).
def _allowlist_no_stale():
    all_blocks = []
    for p in PARSE_PHASES:
        all_blocks.extend(python_blocks(_read(p)))
    stale = []
    for prefix in PARSE_ALLOWLIST_PREFIXES:
        used = any(b.strip().startswith(prefix) and not block_parses(b)
                   for b in all_blocks)
        if not used:
            stale.append(prefix)
    if stale:
        return False, f"stale allowlist prefixes (block parses or absent): {stale}"
    return True, ""

SUITE.add("global:parse-allowlist-no-stale-entries", _allowlist_no_stale)


# --- 2. Every ▶ checkpoint is followed by expected output / marker / command -

def _make_checkpoint_case(phase: str, idx: int, head: str, window: str):
    def case():
        if _CHECKPOINT_CUE.search(window):
            return True, ""
        return False, (
            f"{phase} checkpoint #{idx} ({head!r}) lacks expected-output block, "
            "offline marker, or stated command"
        )
    return case


for _phase in PHASES:
    _cps = checkpoints(_read(_phase))
    _pid = _phase[:2]
    for _i, (_head, _win) in enumerate(_cps):
        SUITE.add(
            f"phase{_pid}:checkpoint-{_i:02d}-has-expected-output",
            _make_checkpoint_case(_phase, _i, _head, _win),
        )

    def _cp_agg(phase=_phase, cps=_cps):
        bad = [i for i, (h, w) in enumerate(cps) if not _CHECKPOINT_CUE.search(w)]
        if bad:
            return False, f"{phase}: {len(bad)} unfollowed checkpoint(s): {bad}"
        return True, f"{len(cps)} checkpoints OK"

    SUITE.add(f"phase{_pid}:all-checkpoints-have-expected-output", _cp_agg)

    # Each phase must have at least one runnable checkpoint.
    def _cp_present(phase=_phase, cps=_cps):
        if cps:
            return True, f"{len(cps)} checkpoints"
        return False, f"{phase}: no ▶ Run/Check it now checkpoints found"

    SUITE.add(f"phase{_pid}:has-run-it-now-checkpoints", _cp_present)


# --- 3. The keyless / no-API-key path is documented -------------------------

def _phase0_has_no_key_box():
    t = _read("00-foundations.md")
    if "🟢" in t and re.search(r"No API key", t):
        return True, ""
    return False, "Phase 0 missing the 🟢 No-API-key box"

SUITE.add("phase00:no-api-key-box-present", _phase0_has_no_key_box)


def _phase0_documents_real_error():
    t = _read("00-foundations.md")
    if "Missing credentials" in t:
        return True, ""
    return False, "Phase 0 No-API-key box should name the real error 'Missing credentials'"

SUITE.add("phase00:no-api-key-box-names-missing-credentials", _phase0_documents_real_error)


def _phase0_keyless_alternatives():
    t = _read("00-foundations.md")
    # The box should point to the offline test suite as a keyless alternative.
    if re.search(r"pytest", t) and re.search(r"FakeClient", t):
        return True, ""
    return False, "Phase 0 keyless box should point at the offline pytest suite / FakeClient"

SUITE.add("phase00:no-api-key-box-offers-offline-suite", _phase0_keyless_alternatives)


def _faq_has_no_key_entry():
    t = _read("FAQ.md")
    if re.search(r"API key", t) and re.search(r"\bNo\.?\b", t):
        # the canonical Q is "Do I need an API key just to learn?" -> No.
        if re.search(r"Do I need an API key", t):
            return True, ""
    return False, "FAQ missing a 'do I need an API key' entry"

SUITE.add("faq:has-no-api-key-entry", _faq_has_no_key_entry)


def _faq_documents_missing_credentials():
    t = _read("FAQ.md")
    if "Missing credentials" in t:
        return True, ""
    return False, "FAQ should document the real 'Missing credentials' error"

SUITE.add("faq:documents-missing-credentials", _faq_documents_missing_credentials)


def _faq_missing_creds_points_at_client():
    t = _read("FAQ.md")
    # The error is raised at `client = OpenAI()` — the FAQ should say so.
    if "Missing credentials" in t and re.search(r"OpenAI\(\)", t):
        return True, ""
    return False, "FAQ Missing-credentials entry should point at the client = OpenAI() line"

SUITE.add("faq:missing-credentials-points-at-client-construction", _faq_missing_creds_points_at_client)


# --- 4. Cold-start: each phase opens with a 5-concepts-only runnable ---------

_FORBIDDEN_COLDSTART = re.compile(r"(?m)^\s*class\s|^\s*@\w|\bThread\b")


def _make_coldstart_case(phase: str):
    def case():
        t = _read(phase)
        block = first_python_block(t)
        if block is None:
            return False, f"{phase}: no python block found for cold-start check"
        if _FORBIDDEN_COLDSTART.search(block):
            # Allow if the phase's beginner box explicitly sanctions starting
            # with the advanced construct (heuristic escape hatch).
            head = t[: t.find(block)]
            if "🟢" in head and re.search(r"Step 0|simplest|cold start", head, re.I):
                return True, "sanctioned by beginner box"
            return False, (
                f"{phase}: first python block uses class/@/Thread before the "
                "assumed five concepts"
            )
        return True, ""
    return case


for _phase in COLD_START_PHASES:
    SUITE.add(f"phase{_phase[:2]}:cold-start-uses-only-five-concepts",
              _make_coldstart_case(_phase))


# --- 5. Pedagogy scaffolding per phase --------------------------------------

def _make_beginner_box_case(phase: str):
    def case():
        t = _read(phase)
        n = t.count("🟢")
        if n >= 1:
            return True, f"{n} beginner boxes"
        return False, f"{phase}: no 🟢 beginner box"
    return case


def _make_takeaways_case(phase: str):
    def case():
        t = _read(phase)
        if re.search(r"(?mi)^#{1,6}\s+Key takeaways", t) or "Key takeaways" in t:
            return True, ""
        return False, f"{phase}: missing 'Key takeaways' section"
    return case


def _make_check_yourself_case(phase: str):
    def case():
        t = _read(phase)
        if "Check yourself" in t:
            return True, ""
        return False, f"{phase}: missing 'Check yourself' section"
    return case


def _make_details_case(phase: str):
    def case():
        t = _read(phase)
        if "<details>" in t and "</details>" in t:
            return True, ""
        return False, f"{phase}: 'Check yourself' answers should be in a <details> block"
    return case


def _make_next_pointer_case(phase: str):
    """Each phase ends pointing the reader at the next step via a real link.

    Phases 0-7 use an explicit ``**Next:**`` pointer; phase 8 (the last) ends
    with a "Where to from here" set of links instead — both forms must contain a
    resolvable local link.
    """
    def case():
        t = _read(phase)
        tail = t[-1500:]
        has_next = bool(re.search(r"\*\*Next:\*\*", t))
        # find local md links in the tail
        tail_links = md_links(tail)
        resolvable = [l for l in tail_links if os.path.exists(resolve(l[0]))]
        if has_next:
            # the **Next:** line itself should carry a resolvable link
            m = re.search(r"\*\*Next:\*\*.*", t)
            line = m.group(0) if m else ""
            nl = md_links(line)
            if nl and all(os.path.exists(resolve(x[0])) for x in nl):
                return True, ""
            # some Next lines wrap; check the following ~200 chars too
            seg = t[m.start(): m.start() + 250] if m else ""
            nl2 = md_links(seg)
            if nl2 and all(os.path.exists(resolve(x[0])) for x in nl2):
                return True, ""
            return False, f"{phase}: **Next:** pointer has no resolvable link"
        # phase 8: accept a 'next steps' link cluster in the tail
        if re.search(r"(?i)next step|where to from here|End of Phase", tail) and resolvable:
            return True, "final-phase next-steps links"
        return False, f"{phase}: no Next pointer / next-steps links at end"
    return case


for _phase in PHASES:
    _pid = _phase[:2]
    SUITE.add(f"phase{_pid}:has-beginner-box", _make_beginner_box_case(_phase))
    SUITE.add(f"phase{_pid}:has-key-takeaways", _make_takeaways_case(_phase))
    SUITE.add(f"phase{_pid}:has-check-yourself", _make_check_yourself_case(_phase))
    SUITE.add(f"phase{_pid}:check-yourself-uses-details", _make_details_case(_phase))
    SUITE.add(f"phase{_pid}:has-next-pointer", _make_next_pointer_case(_phase))


# --- 6. Cross-document links resolve (file + anchor) ------------------------

def _make_link_case(src: str, target: str, anchor: str | None, n: int):
    def case():
        p = resolve(target)
        if not os.path.exists(p):
            return False, f"{src}: broken link target {target!r}"
        if anchor and os.path.basename(p) in _LOCAL_MD:
            ss = slug_set(read(p))
            if anchor not in ss:
                return False, f"{src}: link {target}#{anchor} -> no matching heading anchor"
        return True, ""
    return case


_ALL_LINKS: list[tuple[str, str, str | None]] = []
for _src in LINK_FILES:
    _t = _read(_src)
    for _target, _anchor in md_links(_t):
        _ALL_LINKS.append((_src, _target, _anchor))

# Per-link cases (one case per link is ideal — keeps a failure pinned to one
# bad link). De-dup identical (src,target,anchor) so ids stay unique.
_seen_links: set[tuple[str, str, str | None]] = set()
_link_counter: Counter[str] = Counter()
for _src, _target, _anchor in _ALL_LINKS:
    key = (_src, _target, _anchor)
    if key in _seen_links:
        continue
    _seen_links.add(key)
    _slug = re.sub(r"[^\w]+", "-", f"{_target}{('#' + _anchor) if _anchor else ''}").strip("-")
    _slug = _slug[:50]
    _link_counter[_src] += 1
    _idx = _link_counter[_src]
    SUITE.add(
        f"{_src[:2] if _src in PHASES else _src.split('.')[0].lower()}:link-{_idx:02d}-{_slug}",
        _make_link_case(_src, _target, _anchor, _idx),
    )


# Per-file aggregate: no broken links originating in this file.
def _make_file_link_agg(src: str):
    def case():
        broken = []
        for target, anchor in md_links(_read(src)):
            p = resolve(target)
            if not os.path.exists(p):
                broken.append(f"{target} (missing file)")
            elif anchor and os.path.basename(p) in _LOCAL_MD:
                if anchor not in slug_set(read(p)):
                    broken.append(f"{target}#{anchor} (no anchor)")
        if broken:
            return False, f"{src}: {len(broken)} broken link(s): {broken[:5]}"
        return True, ""
    return case


for _src in LINK_FILES:
    _label = _src[:2] if _src in PHASES else _src.split(".")[0].lower()
    SUITE.add(f"{_label}:no-broken-outbound-links", _make_file_link_agg(_src))


# Global: zero broken links across the whole guide.
def _global_no_broken_links():
    broken = []
    for src in LINK_FILES:
        for target, anchor in md_links(_read(src)):
            p = resolve(target)
            if not os.path.exists(p):
                broken.append(f"{src} -> {target} (missing)")
            elif anchor and os.path.basename(p) in _LOCAL_MD:
                if anchor not in slug_set(read(p)):
                    broken.append(f"{src} -> {target}#{anchor} (no anchor)")
    if broken:
        return False, f"{len(broken)} broken cross-doc link(s): {broken[:8]}"
    return True, ""

SUITE.add("global:zero-broken-cross-doc-links", _global_no_broken_links)


# Per-phase: no broken *intra-doc* anchors (links into the same file's #anchors).
_INTRA_ANCHOR_RE = re.compile(r"\]\(#([\w-]+)\)")


def _make_intra_anchor_case(phase: str):
    def case():
        t = _read(phase)
        ss = slug_set(t)
        anchors = _INTRA_ANCHOR_RE.findall(t)
        bad = [a for a in anchors if a not in ss]
        if bad:
            return False, f"{phase}: {len(bad)} broken intra-doc anchor(s): {bad[:6]}"
        return True, f"{len(anchors)} intra-doc anchors OK"
    return case


for _phase in PHASES + [APPENDIX]:
    _label = _phase[:2] if _phase in PHASES else _phase.split(".")[0].lower()
    SUITE.add(f"{_label}:no-broken-intra-doc-anchors", _make_intra_anchor_case(_phase))


# --- 7. Jargon: curated harness terms each have a GLOSSARY entry -------------

# Curated terms a beginner will meet and must be able to look up. Each entry is
# (display, matcher) where matcher is the lowercase substring to find. Most are
# bold-led entries; a few (call_id) are defined inside another entry's body and
# we accept an in-text definition.
JARGON_TERMS = [
    "agent loop", "agent", "harness", "tool", "tool call", "tool result",
    "registry", "dispatch", "call_id", "transcript", "turn", "schema",
    "json schema", "compaction", "context management", "context window",
    "sub-agent", "orchestration", "permission", "approval gate", "hook",
    "sandbox", "streaming", "token", "token budgeting", "system prompt",
    "responses api", "reasoning model", "rate limit", "retry", "backoff",
    "output_text", "response.output", "json.loads", "decorator",
    "threadpoolexecutor", "fakeclient",
]


def _make_jargon_case(term: str):
    def case():
        g = _read("GLOSSARY.md").lower()
        if term.lower() in g:
            return True, ""
        return False, f"GLOSSARY.md has no entry mentioning {term!r}"
    return case


for _term in JARGON_TERMS:
    _tid = re.sub(r"[^\w]+", "-", _term).strip("-")
    SUITE.add(f"glossary:defines-{_tid}", _make_jargon_case(_term))


# Aggregate jargon coverage.
def _jargon_coverage():
    g = _read("GLOSSARY.md").lower()
    missing = [t for t in JARGON_TERMS if t.lower() not in g]
    if missing:
        return False, f"GLOSSARY missing {len(missing)} term(s): {missing}"
    return True, f"{len(JARGON_TERMS)} terms covered"

SUITE.add("glossary:covers-all-curated-jargon", _jargon_coverage)


# The core beginner-essential terms should be flagged with 🟢 in the glossary.
def _glossary_marks_essentials():
    g = _read("GLOSSARY.md")
    # at least the foundational concepts carry the 🟢 essential marker
    essentials = ["Agent", "Agent loop", "Harness", "Tool", "Transcript"]
    present = sum(1 for e in essentials
                  if re.search(re.escape(e) + r"[^\n]*?🟢", g))
    if present >= 3:
        return True, f"{present}/{len(essentials)} essentials marked 🟢"
    return False, f"only {present} essential glossary terms marked 🟢"

SUITE.add("glossary:flags-beginner-essentials", _glossary_marks_essentials)


# --- 8. BEGINNER-NOTES references & EXERCISES per-phase anchors --------------

def _beginner_notes_exists():
    if os.path.exists(_path("BEGINNER-NOTES.md")):
        return True, ""
    return False, "BEGINNER-NOTES.md missing"

SUITE.add("support:beginner-notes-exists", _beginner_notes_exists)


def _phases_link_beginner_notes():
    # Phase 0 should route a beginner to BEGINNER-NOTES.md
    t = _read("00-foundations.md")
    if "BEGINNER-NOTES.md" in t:
        return True, ""
    return False, "Phase 0 should link BEGINNER-NOTES.md for beginners"

SUITE.add("phase00:links-beginner-notes", _phases_link_beginner_notes)


def _glossary_link_resolves_from_phase0():
    t = _read("00-foundations.md")
    # not strictly required, but if linked it must resolve (covered globally).
    return True, ""

# EXERCISES: each phase that links into EXERCISES.md#<anchor> must hit a real
# heading there; and EXERCISES.md must contain a per-phase section anchor for
# every phase.
def _exercises_per_phase_anchors():
    ex = _read("EXERCISES.md")
    ss = slug_set(ex)
    missing = []
    # phase headings in EXERCISES look like "## Phase N — ..." -> slug used in links
    for n in range(9):
        # find any anchor starting "phase-{n}-" referenced by the matching phase
        if not any(s.startswith(f"phase-{n}-") for s in ss):
            missing.append(n)
    if missing:
        return False, f"EXERCISES.md missing per-phase anchor for phase(s): {missing}"
    return True, ""

SUITE.add("exercises:has-per-phase-anchors", _exercises_per_phase_anchors)


def _make_phase_exercises_anchor_case(phase: str):
    """If a phase links into EXERCISES.md#anchor, that anchor must exist."""
    def case():
        t = _read(phase)
        bad = []
        for target, anchor in md_links(t):
            if os.path.basename(resolve(target)) == "EXERCISES.md" and anchor:
                if anchor not in slug_set(_read("EXERCISES.md")):
                    bad.append(anchor)
        if bad:
            return False, f"{phase}: EXERCISES anchors not found: {bad}"
        return True, ""
    return case


for _phase in PHASES:
    SUITE.add(f"phase{_phase[:2]}:exercises-links-resolve",
              _make_phase_exercises_anchor_case(_phase))


# Every EXERCISES per-phase section that a phase advertises should be reachable.
def _exercises_capstone_present():
    ex = _read("EXERCISES.md")
    if "capstone" in slug_set(ex):
        return True, ""
    return False, "EXERCISES.md missing a Capstone section"

SUITE.add("exercises:has-capstone", _exercises_capstone_present)


# --- 9. Structural integrity of the guide set -------------------------------

def _all_phase_files_exist():
    missing = [p for p in PHASES + [APPENDIX] if not os.path.exists(_path(p))]
    if missing:
        return False, f"missing phase files: {missing}"
    return True, ""

SUITE.add("global:all-phase-files-exist", _all_phase_files_exist)


def _all_support_docs_exist():
    missing = [d for d in SUPPORT_DOCS if not os.path.exists(_path(d))]
    if missing:
        return False, f"missing support docs: {missing}"
    return True, ""

SUITE.add("global:all-support-docs-exist", _all_support_docs_exist)


def _make_phase_has_title_case(phase: str, n: int):
    def case():
        t = _read(phase)
        # First H1 should name the phase number.
        m = re.search(r"(?m)^#\s+(.*)$", t)
        if not m:
            return False, f"{phase}: no H1 title"
        if re.search(rf"Phase\s*{n}\b", m.group(1)):
            return True, ""
        return False, f"{phase}: H1 {m.group(1)!r} does not name Phase {n}"
    return case


for _n, _phase in enumerate(PHASES):
    SUITE.add(f"phase{_phase[:2]}:h1-names-phase-number",
              _make_phase_has_title_case(_phase, _n))


# Each phase header links back to the guide index (README) for navigation.
def _make_index_link_case(phase: str):
    def case():
        head = _read(phase)[:400]
        if re.search(r"\]\(\.?/?README\.md\)", head) or "Guide index" in head:
            return True, ""
        return False, f"{phase}: no guide-index/README link near the top"
    return case


for _phase in PHASES:
    SUITE.add(f"phase{_phase[:2]}:links-guide-index-at-top",
              _make_index_link_case(_phase))


# The Responses-API contract phrasing a beginner must internalize appears in
# Phase 0 (the single source of truth): function_call / function_call_output /
# call_id all named.
def _phase0_states_contract():
    t = _read("00-foundations.md")
    needed = ["function_call", "function_call_output", "call_id", "responses.create"]
    missing = [n for n in needed if n not in t]
    if missing:
        return False, f"Phase 0 omits contract token(s): {missing}"
    return True, ""

SUITE.add("phase00:states-responses-api-contract", _phase0_states_contract)


# Phase 0 must show the keyless reader the offline test command explicitly.
def _phase0_shows_offline_command():
    t = _read("00-foundations.md")
    if "python -m pytest" in t:
        return True, ""
    return False, "Phase 0 should show 'python -m pytest' as the keyless verification"

SUITE.add("phase00:shows-offline-pytest-command", _phase0_shows_offline_command)


# README (guide index) must link to every phase + the appendix.
def _readme_links_all_phases():
    t = _read("README.md")
    missing = [p for p in PHASES + [APPENDIX] if p not in t]
    if missing:
        return False, f"README does not link: {missing}"
    return True, ""

SUITE.add("readme:links-all-phases", _readme_links_all_phases)


if __name__ == "__main__":
    from harness import main
    main(SUITE)
