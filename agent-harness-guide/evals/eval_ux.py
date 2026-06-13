"""Deterministic UX / content-design eval suite for the MARKDOWN guide.

This encodes the documentation-UX standards prior persona reviews established for
the prose guide (the HTML site has its own frontend suite; here we assess the
markdown *structure*, *navigation*, and *consistency*). Everything is offline,
stdlib-only, and order-independent: each case is one `(artifact, check)` pair so a
failure points at exactly one thing.

What it checks (parametrized across the 9 phases + appendix + support docs):

* Nav-header breadcrumb above every phase H1 (`[← …] · [Guide index] · [… →]`).
* A `**Contents:**` mini-TOC near the top whose in-file anchors all resolve via
  the GitHub slugger.
* The closing-block ritual, in order: Pitfalls (## Pitfalls), ## Key takeaways,
  ## Check yourself (+ <details>), an Exercises pointer (link to EXERCISES.md),
  and a terminal `**Next:**` link. Known exceptions are encoded explicitly:
  Phase 0 has no Pitfalls; Phase 8 (last phase) has no `**Next:**`.
* Uniform checkpoint markup: every checkpoint is `### ▶ Run it now` /
  `### ▶ Check it now` (optionally with the sanctioned `(no API key needed)`
  suffix); no stray `**▶` or `#### ▶` forms.
* Component markup consistency: 🟢 beginner boxes are blockquotes-or-headings
  (never bare paragraphs), `> [!WARNING]` admonitions, and `> **Reference copy`
  banners are blockquotes.
* "What changed from Vn to Vn+1" lists are H3 headings.
* Cross-document navigation: every relative link across all phases + support docs
  resolves (file + #anchor via the slugger); each support doc exists, and the
  README links to each one.
* Single-H1 discipline per file; heading levels never skip within a phase.
* Coverage-counting aggregates: the number of phases with each ritual element is
  9 (or 8 where the Pitfalls / Next exceptions apply).
"""
from __future__ import annotations

import os
import re

from harness import Suite, read, GUIDE_DIR, PHASES, APPENDIX, SUPPORT_DOCS

SUITE = Suite("ux")

# --------------------------------------------------------------------------
# Document set & known, explicitly-encoded exceptions
# --------------------------------------------------------------------------
ALL_DOCS = list(PHASES) + [APPENDIX] + list(SUPPORT_DOCS)

# Phase 0 deliberately lacks a `## Pitfalls` section (its content is setup, not a
# place to trip). This is the ONLY phase allowed to omit Pitfalls.
PITFALLS_EXEMPT = {"00-foundations.md"}

# Phase 8 is the last numbered phase; it closes the guide with a "Graduation"
# section that routes onward (to the appendix/capstone) instead of a terminal
# `**Next:**` link. This is the only phase allowed to omit `**Next:**`.
NEXT_EXEMPT = {"08-production-harness.md"}


def P(name: str) -> str:
    return os.path.join(GUIDE_DIR, name)


# --------------------------------------------------------------------------
# Tiny markdown layer: strip fenced code, find headings, GitHub-slug them.
# --------------------------------------------------------------------------
_FENCE = re.compile(r"^(```+|~~~+)")


def strip_code_fences(text: str) -> str:
    """Blank out fenced code blocks, preserving line numbering.

    `#`-comments and `▶`/🟢 glyphs inside code samples must not be mistaken for
    markdown headings or components.
    """
    out = []
    in_fence = False
    fence_char = None
    for line in text.split("\n"):
        s = line.lstrip()
        m = _FENCE.match(s)
        if m:
            tok = m.group(1)
            if not in_fence:
                in_fence = True
                fence_char = tok[0]
            elif s.startswith(fence_char * 3):
                in_fence = False
                fence_char = None
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


_BQ_PREFIX = re.compile(r"^(\s*>\s?)+")
_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def github_slug(text: str) -> str:
    """Reproduce GitHub's heading-anchor slugger.

    Lowercase; drop link syntax (keep link text) and inline code backticks;
    remove every char that is not a Unicode word char, hyphen, or space (this is
    where `*`, `~`, `.`, `:`, `,`, em-dashes, and emoji disappear — and why a
    leading emoji yields a leading hyphen); finally spaces -> hyphens. Crucially,
    underscores are word chars and are KEPT (e.g. `coding_tools` -> `coding_tools`).
    """
    s = text.strip().lower()
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # [text](url) -> text
    s = s.replace("`", "")
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE)
    s = s.replace(" ", "-")
    return s


def all_headings(text: str, *, include_blockquoted: bool = True):
    """Yield (line_no, level, title, raw_line) for every ATX heading.

    GitHub renders (and slugs) headings inside blockquotes too, so anchor
    resolution must include them; structural checks (single-H1, no level-skip)
    pass include_blockquoted=False to see only the document's own outline.
    """
    text = strip_code_fences(text)
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        raw = line
        if include_blockquoted:
            raw = _BQ_PREFIX.sub("", raw)
        elif _BQ_PREFIX.match(line):
            continue
        m = _ATX.match(raw)
        if m:
            out.append((i, len(m.group(1)), m.group(2), line))
    return out


def slug_set(text: str) -> set[str]:
    """Every in-file anchor GitHub would generate, with duplicate suffixing."""
    seen: dict[str, int] = {}
    slugs: set[str] = set()
    for _, _, title, _raw in all_headings(text, include_blockquoted=True):
        base = github_slug(title)
        if base in seen:
            seen[base] += 1
            slugs.add(f"{base}-{seen[base]}")
        else:
            seen[base] = 0
            slugs.add(base)
    return slugs


# Cache reads / slug sets (deterministic, no mutation across cases).
_TEXT: dict[str, str] = {}
_SLUGS: dict[str, set[str]] = {}


def text_of(name: str) -> str:
    if name not in _TEXT:
        _TEXT[name] = read(P(name))
    return _TEXT[name]


def slugs_of(name: str) -> set[str]:
    if name not in _SLUGS:
        _SLUGS[name] = slug_set(text_of(name))
    return _SLUGS[name]


def line_no(text: str, needle_regex: str) -> int:
    """1-based line number of the first regex match (for `file:line` reports)."""
    for i, line in enumerate(text.split("\n"), 1):
        if re.search(needle_regex, line):
            return i
    return 0


# --------------------------------------------------------------------------
# 1. Nav-header breadcrumb above every phase H1
# --------------------------------------------------------------------------
def _make_nav_cases():
    for ph in PHASES:
        def has_nav(ph=ph):
            line1 = text_of(ph).split("\n", 1)[0]
            if "[Guide index]" not in line1:
                return False, f"{ph}:1 first line is not a nav breadcrumb: {line1!r}"
            return True, ""
        SUITE.add(f"nav/{ph}/breadcrumb-line1", has_nav)

        def guide_index_link(ph=ph):
            line1 = text_of(ph).split("\n", 1)[0]
            ok = re.search(r"\[Guide index\]\(\.?/?README\.md\)", line1) is not None
            return ok, "" if ok else f"{ph}:1 nav lacks [Guide index](./README.md): {line1!r}"
        SUITE.add(f"nav/{ph}/guide-index-link", guide_index_link)

        def nav_before_h1(ph=ph):
            lines = text_of(ph).split("\n")
            nav_idx = 0  # line 1 is the breadcrumb
            h1_idx = next((i for i, l in enumerate(lines)
                           if _ATX.match(l) and _ATX.match(l).group(1) == "#"), None)
            if h1_idx is None:
                return False, f"{ph}: no H1 found"
            if nav_idx >= h1_idx:
                return False, f"{ph}: nav line is not above the H1 (H1 at line {h1_idx + 1})"
            return True, ""
        SUITE.add(f"nav/{ph}/above-h1", nav_before_h1)

        # Directional arrows: Phase 0 has no back-arrow; all others have a forward
        # arrow, and phases 1..8 have a back-arrow too.
        idx = PHASES.index(ph)
        def back_arrow(ph=ph, idx=idx):
            line1 = text_of(ph).split("\n", 1)[0]
            has_back = "←" in line1
            if idx == 0:
                return (not has_back), ("" if not has_back
                                        else f"{ph}:1 Phase 0 should have no back-arrow")
            return has_back, "" if has_back else f"{ph}:1 missing back-arrow (←)"
        SUITE.add(f"nav/{ph}/back-arrow", back_arrow)

        def fwd_arrow(ph=ph):
            line1 = text_of(ph).split("\n", 1)[0]
            ok = "→" in line1
            return ok, "" if ok else f"{ph}:1 missing forward-arrow (→)"
        SUITE.add(f"nav/{ph}/forward-arrow", fwd_arrow)

    # Appendix nav: back-arrow to Phase 8, Guide index, no forward arrow.
    def appendix_nav():
        line1 = text_of(APPENDIX).split("\n", 1)[0]
        if "[Guide index]" not in line1 or "←" not in line1:
            return False, f"{APPENDIX}:1 appendix nav malformed: {line1!r}"
        return True, ""
    SUITE.add(f"nav/{APPENDIX}/breadcrumb-line1", appendix_nav)


_make_nav_cases()


# --------------------------------------------------------------------------
# 2. Contents mini-TOC near the top; every anchor resolves in-file
# --------------------------------------------------------------------------
_CONTENTS_RE = re.compile(r"^\*\*Contents:\*\*\s*$", re.MULTILINE)
_INFILE_LINK = re.compile(r"\[[^\]]+\]\((#[A-Za-z0-9\-]+)\)")


def _toc_block(name: str):
    """Return (start_line, anchors[]) for the `**Contents:**` mini-TOC."""
    text = strip_code_fences(text_of(name))
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines)
                  if l.strip() == "**Contents:**"), None)
    if start is None:
        return None, []
    anchors = []
    # Collect contiguous-ish TOC region: from the header to the next H2/`---`.
    for l in lines[start + 1: start + 60]:
        if l.startswith("## ") or l.strip() == "---":
            break
        for m in _INFILE_LINK.finditer(l):
            anchors.append(m.group(1)[1:])  # drop leading '#'
    return start + 1, anchors


def _make_contents_cases():
    for ph in PHASES:
        def has_contents(ph=ph):
            ok = _CONTENTS_RE.search(text_of(ph)) is not None
            ln = line_no(text_of(ph), r"^\*\*Contents:\*\*")
            return ok, "" if ok else f"{ph}: no **Contents:** mini-TOC"
        SUITE.add(f"contents/{ph}/present", has_contents)

        def contents_near_top(ph=ph):
            # "Near the top" = within the opening region, before the bulk of the
            # phase. Some phases carry a longer series-context blockquote and/or a
            # beginner-track box ahead of the TOC, so allow generous headroom.
            ln = line_no(text_of(ph), r"^\*\*Contents:\*\*")
            ok = 0 < ln <= 120
            return ok, "" if ok else f"{ph}:{ln} **Contents:** not near the top"
        SUITE.add(f"contents/{ph}/near-top", contents_near_top)

        def contents_nonempty(ph=ph):
            start, anchors = _toc_block(ph)
            ok = bool(anchors)
            return ok, "" if ok else f"{ph}: **Contents:** TOC has no in-file links"
        SUITE.add(f"contents/{ph}/has-links", contents_nonempty)

        def contents_resolve(ph=ph):
            start, anchors = _toc_block(ph)
            slugs = slugs_of(ph)
            missing = [a for a in anchors if a not in slugs]
            if missing:
                return False, (f"{ph}:{start} TOC anchors do not resolve: "
                               f"{missing[:4]}")
            return True, ""
        SUITE.add(f"contents/{ph}/anchors-resolve", contents_resolve)


_make_contents_cases()


# --------------------------------------------------------------------------
# 3. Closing-block ritual (one case per element per phase)
# --------------------------------------------------------------------------
def _has_h2(text: str, title: str) -> bool:
    return re.search(rf"^## {re.escape(title)}\s*$", text, re.MULTILINE) is not None


def _make_ritual_cases():
    for ph in PHASES:
        # Pitfalls (Phase 0 is the sanctioned exception).
        def pitfalls(ph=ph):
            present = _has_h2(text_of(ph), "Pitfalls")
            if ph in PITFALLS_EXEMPT:
                return (not present), ("" if not present
                                       else f"{ph}: has ## Pitfalls but is the known exempt phase")
            return present, "" if present else f"{ph}: missing ## Pitfalls section"
        SUITE.add(f"ritual/{ph}/pitfalls", pitfalls)

        def key_takeaways(ph=ph):
            ok = _has_h2(text_of(ph), "Key takeaways")
            return ok, "" if ok else f"{ph}: missing ## Key takeaways"
        SUITE.add(f"ritual/{ph}/key-takeaways", key_takeaways)

        def check_yourself(ph=ph):
            ok = _has_h2(text_of(ph), "Check yourself")
            return ok, "" if ok else f"{ph}: missing ## Check yourself"
        SUITE.add(f"ritual/{ph}/check-yourself", check_yourself)

        def check_details(ph=ph):
            text = text_of(ph)
            cy = line_no(text, r"^## Check yourself")
            if cy == 0:
                return False, f"{ph}: no ## Check yourself, so no <details>"
            tail = "\n".join(text.split("\n")[cy - 1:])
            ok = "<details>" in tail and "</details>" in tail
            return ok, "" if ok else f"{ph}:{cy} Check yourself lacks a <details> block"
        SUITE.add(f"ritual/{ph}/check-details", check_details)

        def exercises_pointer(ph=ph):
            ok = re.search(r"\]\(\.?/?EXERCISES\.md", text_of(ph)) is not None
            return ok, "" if ok else f"{ph}: no Exercises pointer (link to EXERCISES.md)"
        SUITE.add(f"ritual/{ph}/exercises-pointer", exercises_pointer)

        # Terminal **Next:** link (Phase 8 is the sanctioned exception).
        def next_link(ph=ph):
            text = text_of(ph)
            nexts = [l for l in text.split("\n") if l.startswith("**Next:**")]
            if ph in NEXT_EXEMPT:
                return (not nexts), ("" if not nexts
                                     else f"{ph}: last phase should not carry a **Next:** link")
            if not nexts:
                return False, f"{ph}: missing terminal **Next:** link"
            last = nexts[-1]
            ok = "](" in last
            return ok, "" if ok else f"{ph}: **Next:** present but not a link: {last!r}"
        SUITE.add(f"ritual/{ph}/next-link", next_link)

        # Terminal: the LAST paragraph of the file begins with **Next:**. The
        # pointer may wrap across continuation lines, so walk back from EOF over
        # non-blank lines to the start of the final block and inspect its lead.
        def next_is_terminal(ph=ph):
            if ph in NEXT_EXEMPT:
                return True, ""
            lines = text_of(ph).split("\n")
            j = len(lines) - 1
            while j >= 0 and not lines[j].strip():  # skip trailing blanks
                j -= 1
            end = j
            while j >= 0 and lines[j].strip():       # back to block start
                j -= 1
            block_start = j + 1
            if block_start > end:
                return False, f"{ph}: empty file"
            ok = lines[block_start].startswith("**Next:**")
            return ok, "" if ok else (f"{ph}: final block is not the **Next:** pointer "
                                      f"({lines[block_start][:40]!r})")
        SUITE.add(f"ritual/{ph}/next-terminal", next_is_terminal)

        # Ordering: Pitfalls (if any) < Key takeaways < Check yourself < Next.
        def ritual_order(ph=ph):
            text = text_of(ph)
            def at(rx):
                return line_no(text, rx)
            kt = at(r"^## Key takeaways")
            cy = at(r"^## Check yourself")
            seq = [("Key takeaways", kt), ("Check yourself", cy)]
            if ph not in PITFALLS_EXEMPT:
                seq.insert(0, ("Pitfalls", at(r"^## Pitfalls")))
            if ph not in NEXT_EXEMPT:
                nx = max((i for i, l in enumerate(text.split("\n"), 1)
                          if l.startswith("**Next:**")), default=0)
                seq.append(("Next", nx))
            positions = [p for _, p in seq]
            if any(p == 0 for p in positions):
                return False, f"{ph}: a ritual element is missing for ordering check"
            if positions != sorted(positions):
                return False, f"{ph}: ritual elements out of order: {seq}"
            return True, ""
        SUITE.add(f"ritual/{ph}/order", ritual_order)


_make_ritual_cases()


# --------------------------------------------------------------------------
# 4. Checkpoint markup uniformity (per phase)
# --------------------------------------------------------------------------
_GOOD_CHECKPOINT = re.compile(
    r"^### ▶ (Run it now|Check it now)( \(no API key needed\))?$")


def _make_checkpoint_cases():
    for ph in PHASES:
        text = strip_code_fences(text_of(ph))

        def good_form(ph=ph, text=text):
            # Any heading line containing ▶ must match the sanctioned form.
            bad = []
            for i, line in enumerate(text.split("\n"), 1):
                if "▶" in line and _ATX.match(line):
                    if not _GOOD_CHECKPOINT.match(line):
                        bad.append((i, line.strip()[:50]))
            if bad:
                return False, f"{ph}: non-uniform checkpoint heading(s): {bad[:3]}"
            return True, ""
        SUITE.add(f"checkpoint/{ph}/uniform-heading", good_form)

        def no_bold_form(ph=ph, text=text):
            bad = [i for i, line in enumerate(text.split("\n"), 1)
                   if re.match(r"^\s*\*\*▶", line)]
            if bad:
                return False, f"{ph}:{bad[0]} stray bold-form **▶ checkpoint"
            return True, ""
        SUITE.add(f"checkpoint/{ph}/no-bold-form", no_bold_form)

        def no_h4_form(ph=ph, text=text):
            bad = [i for i, line in enumerate(text.split("\n"), 1)
                   if re.match(r"^#{4,6} ▶", line)]
            if bad:
                return False, f"{ph}:{bad[0]} stray #### ▶ checkpoint (must be H3)"
            return True, ""
        SUITE.add(f"checkpoint/{ph}/no-h4-form", no_h4_form)

        def has_checkpoints(ph=ph, text=text):
            n = sum(1 for line in text.split("\n") if _GOOD_CHECKPOINT.match(line))
            return n > 0, "" if n > 0 else f"{ph}: no ▶ checkpoints found"
        SUITE.add(f"checkpoint/{ph}/has-some", has_checkpoints)


_make_checkpoint_cases()


# --------------------------------------------------------------------------
# 5. Component markup consistency: 🟢 boxes, [!WARNING], Reference copy banners
# --------------------------------------------------------------------------
def _make_component_cases():
    for ph in PHASES:
        text = strip_code_fences(text_of(ph))
        lines = text.split("\n")

        # A 🟢 box-opener is either the bold blockquote form (`> 🟢 **…`) or the
        # heading form (`> ## 🟢 …` / `### 🟢 …`). Either way it must sit in a
        # blockquote OR be a heading — never a bare paragraph. (Plain inline prose
        # mentions of 🟢 mid-sentence are allowed and are not box-openers.)
        def _is_green_opener(line: str) -> bool:
            stripped = _BQ_PREFIX.sub("", line)
            is_bq = _BQ_PREFIX.match(line) is not None
            is_head = _ATX.match(stripped) is not None
            if is_head and "🟢" in stripped:
                return True
            if re.search(r"🟢 \*\*", line) and is_bq:
                return True
            return False

        def green_box_shape(ph=ph, lines=lines):
            # Any bold-🟢 line OR heading-🟢 line must be a proper box (blockquote
            # or heading), not a bare paragraph.
            bad = []
            for i, line in enumerate(lines, 1):
                stripped = _BQ_PREFIX.sub("", line)
                looks_like_box = (re.search(r"🟢 \*\*", line)
                                  or (_ATX.match(stripped) and "🟢" in stripped))
                if looks_like_box and not _is_green_opener(line):
                    bad.append((i, line.strip()[:50]))
            if bad:
                return False, f"{ph}: 🟢 box-opener not a blockquote/heading: {bad[:2]}"
            return True, ""
        SUITE.add(f"component/{ph}/green-box-shape", green_box_shape)

        def green_box_present(ph=ph, lines=lines):
            n = sum(1 for l in lines if _is_green_opener(l))
            return n > 0, "" if n > 0 else f"{ph}: no 🟢 beginner box found"
        SUITE.add(f"component/{ph}/green-box-present", green_box_present)

        # Every [!WARNING] admonition must be on a blockquote line `> [!WARNING]`.
        def warning_shape(ph=ph, lines=lines):
            bad = []
            for i, line in enumerate(lines, 1):
                if "[!WARNING]" in line and not re.match(r"^\s*> \[!WARNING\]", line):
                    bad.append((i, line.strip()[:50]))
            if bad:
                return False, f"{ph}: [!WARNING] not a `> [!WARNING]` blockquote: {bad[:2]}"
            return True, ""
        SUITE.add(f"component/{ph}/warning-shape", warning_shape)

        # Every **Reference copy** banner must lead a blockquote line.
        def refcopy_shape(ph=ph, lines=lines):
            bad = []
            for i, line in enumerate(lines, 1):
                if re.search(r"\*\*Reference copy", line) and not re.match(
                        r"^\s*> \*\*Reference copy", line):
                    bad.append((i, line.strip()[:50]))
            if bad:
                return False, f"{ph}: **Reference copy** banner not a blockquote: {bad[:2]}"
            return True, ""
        SUITE.add(f"component/{ph}/refcopy-shape", refcopy_shape)


_make_component_cases()


# --------------------------------------------------------------------------
# 6. "What changed from Vn to Vn+1" lists are H3 headings
# --------------------------------------------------------------------------
def _make_what_changed_cases():
    for ph in PHASES:
        text = strip_code_fences(text_of(ph))
        for i, line in enumerate(text.split("\n"), 1):
            m = re.match(r"^(#+)\s+What changed from (V\d+) to (V\d+)\b", line)
            if not m:
                # also catch any heading mentioning "What changed" generally
                m2 = re.match(r"^(#+)\s+What changed\b", line)
                if not m2:
                    continue
                level = len(m2.group(1))
                cid = f"whatchanged/{ph}/L{i}"
                def is_h3(ph=ph, i=i, level=level, line=line):
                    ok = level == 3
                    return ok, "" if ok else f"{ph}:{i} 'What changed' heading is H{level}, want H3"
                SUITE.add(cid, is_h3)
                continue
            level, vfrom, vto = len(m.group(1)), m.group(2), m.group(3)
            cid = f"whatchanged/{ph}/{vfrom}-{vto}"
            def is_h3(ph=ph, i=i, level=level):
                ok = level == 3
                return ok, "" if ok else f"{ph}:{i} 'What changed' heading is H{level}, want H3"
            SUITE.add(cid, is_h3)


_make_what_changed_cases()


# --------------------------------------------------------------------------
# 7. Cross-document navigation: every relative link resolves (file + #anchor)
# --------------------------------------------------------------------------
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# md files we can resolve anchors for (anything outside this set: file-only check)
_ANCHORED = set(ALL_DOCS)


def _iter_links(name: str):
    """Yield (line_no, target) for every markdown link outside code fences."""
    text = strip_code_fences(text_of(name))
    for i, line in enumerate(text.split("\n"), 1):
        for m in _LINK_RE.finditer(line):
            yield i, m.group(1).strip()


def _resolve(name: str, target: str):
    """Return (kind, detail). kind in {'ok','nofile','noanchor','skip'}."""
    if target.startswith(("http://", "https://", "mailto:", "tel:")):
        return "skip", ""
    if "#" in target:
        filepart, anchor = target.split("#", 1)
    else:
        filepart, anchor = target, None
    if filepart == "":
        rel = name
    else:
        rel = os.path.normpath(os.path.join(os.path.dirname(name), filepart))
    full = os.path.join(GUIDE_DIR, rel)
    if filepart != "":
        if not os.path.exists(full):
            return "nofile", rel
    if anchor:
        tgt = rel if filepart != "" else name
        if tgt in _ANCHORED:
            if anchor not in slugs_of(tgt):
                return "noanchor", f"{tgt}#{anchor}"
        # else: target is a code/site/notebook md or non-md; skip anchor check
    return "ok", ""


def _make_crossdoc_cases():
    # One aggregate "all links in DOC resolve" case per doc (fine-grained detail
    # in the message), plus the per-doc existence + README-links-to-support set.
    docs_to_scan = list(PHASES) + [APPENDIX] + list(SUPPORT_DOCS)
    for doc in docs_to_scan:
        def links_resolve(doc=doc):
            broken = []
            for ln, target in _iter_links(doc):
                kind, detail = _resolve(doc, target)
                if kind in ("nofile", "noanchor"):
                    broken.append(f"{doc}:{ln} {kind} -> {target}")
            if broken:
                return False, "; ".join(broken[:6]) + (
                    f" (+{len(broken) - 6} more)" if len(broken) > 6 else "")
            return True, ""
        SUITE.add(f"xdoc/{doc}/links-resolve", links_resolve)

    # Each support doc + appendix exists.
    for doc in list(SUPPORT_DOCS) + [APPENDIX]:
        def exists(doc=doc):
            ok = os.path.exists(P(doc))
            return ok, "" if ok else f"{doc}: support doc missing"
        SUITE.add(f"xdoc/exists/{doc}", exists)

    # README links to each support doc (reachability from the guide index).
    readme = "README.md"
    for doc in [d for d in SUPPORT_DOCS if d != readme] + [APPENDIX]:
        def readme_links(doc=doc, readme=readme):
            text = strip_code_fences(text_of(readme))
            ok = re.search(rf"\]\(\.?/?{re.escape(doc)}(#[^)]*)?\)", text) is not None
            return ok, "" if ok else f"{readme}: no link to {doc}"
        SUITE.add(f"xdoc/readme-links/{doc}", readme_links)

    # README links to every numbered phase too (full reachability of the spine).
    for ph in PHASES:
        def readme_links_phase(ph=ph):
            text = strip_code_fences(text_of("README.md"))
            ok = re.search(rf"\]\(\.?/?{re.escape(ph)}(#[^)]*)?\)", text) is not None
            return ok, "" if ok else f"README.md: no link to {ph}"
        SUITE.add(f"xdoc/readme-links-phase/{ph}", readme_links_phase)


_make_crossdoc_cases()


# --------------------------------------------------------------------------
# 8. Single-H1 discipline & no heading-level skips (per phase + appendix)
# --------------------------------------------------------------------------
def _make_structure_cases():
    for name in list(PHASES) + [APPENDIX]:
        def single_h1(name=name):
            heads = all_headings(text_of(name), include_blockquoted=False)
            h1s = [h for h in heads if h[1] == 1]
            if len(h1s) != 1:
                return False, (f"{name}: expected exactly one H1, found {len(h1s)} "
                               f"(lines {[h[0] for h in h1s][:5]})")
            return True, ""
        SUITE.add(f"struct/{name}/single-h1", single_h1)

        def first_heading_is_h1(name=name):
            heads = all_headings(text_of(name), include_blockquoted=False)
            if not heads:
                return False, f"{name}: no headings"
            ok = heads[0][1] == 1
            return ok, "" if ok else f"{name}:{heads[0][0]} first heading is H{heads[0][1]}, want H1"
        SUITE.add(f"struct/{name}/first-heading-h1", first_heading_is_h1)

        def no_level_skip(name=name):
            heads = all_headings(text_of(name), include_blockquoted=False)
            prev = None
            for ln, lvl, title, _raw in heads:
                if prev is not None and lvl > prev + 1:
                    return False, (f"{name}:{ln} heading jumps H{prev}->H{lvl} "
                                   f"({title[:40]!r})")
                prev = lvl
            return True, ""
        SUITE.add(f"struct/{name}/no-level-skip", no_level_skip)


_make_structure_cases()


# --------------------------------------------------------------------------
# 9. Coverage-counting aggregates (make ritual regressions obvious)
# --------------------------------------------------------------------------
def _count_phases(predicate) -> int:
    return sum(1 for ph in PHASES if predicate(ph))


def _make_coverage_cases():
    def cov_contents():
        n = _count_phases(lambda ph: _CONTENTS_RE.search(text_of(ph)) is not None)
        return n == 9, "" if n == 9 else f"only {n}/9 phases have a **Contents:** TOC"
    SUITE.add("coverage/contents-eq-9", cov_contents)

    def cov_nav():
        n = _count_phases(lambda ph: "[Guide index]" in text_of(ph).split("\n", 1)[0])
        return n == 9, "" if n == 9 else f"only {n}/9 phases have a nav breadcrumb"
    SUITE.add("coverage/nav-eq-9", cov_nav)

    def cov_key():
        n = _count_phases(lambda ph: _has_h2(text_of(ph), "Key takeaways"))
        return n == 9, "" if n == 9 else f"only {n}/9 phases have ## Key takeaways"
    SUITE.add("coverage/key-takeaways-eq-9", cov_key)

    def cov_check():
        n = _count_phases(lambda ph: _has_h2(text_of(ph), "Check yourself"))
        return n == 9, "" if n == 9 else f"only {n}/9 phases have ## Check yourself"
    SUITE.add("coverage/check-yourself-eq-9", cov_check)

    def cov_details():
        def has_details(ph):
            t = text_of(ph)
            cy = line_no(t, r"^## Check yourself")
            if cy == 0:
                return False
            tail = "\n".join(t.split("\n")[cy - 1:])
            return "<details>" in tail
        n = _count_phases(has_details)
        return n == 9, "" if n == 9 else f"only {n}/9 phases have a Check-yourself <details>"
    SUITE.add("coverage/check-details-eq-9", cov_details)

    def cov_exercises():
        n = _count_phases(lambda ph: re.search(r"\]\(\.?/?EXERCISES\.md", text_of(ph)) is not None)
        return n == 9, "" if n == 9 else f"only {n}/9 phases have an Exercises pointer"
    SUITE.add("coverage/exercises-pointer-eq-9", cov_exercises)

    def cov_pitfalls():
        # 8 phases carry Pitfalls; Phase 0 is the sole sanctioned exception.
        present = [ph for ph in PHASES if _has_h2(text_of(ph), "Pitfalls")]
        absent = [ph for ph in PHASES if ph not in present]
        if len(present) != 8:
            return False, f"{len(present)}/9 phases have ## Pitfalls (want 8)"
        if absent != list(PITFALLS_EXEMPT):
            return False, f"Pitfalls absent in {absent}, but only {sorted(PITFALLS_EXEMPT)} is sanctioned"
        return True, ""
    SUITE.add("coverage/pitfalls-eq-8-exception-only-phase0", cov_pitfalls)

    def cov_next():
        # 8 phases carry a terminal **Next:** link; Phase 8 is the exception.
        present = [ph for ph in PHASES
                   if any(l.startswith("**Next:**") for l in text_of(ph).split("\n"))]
        absent = [ph for ph in PHASES if ph not in present]
        if len(present) != 8:
            return False, f"{len(present)}/9 phases have **Next:** (want 8)"
        if absent != list(NEXT_EXEMPT):
            return False, f"**Next:** absent in {absent}, but only {sorted(NEXT_EXEMPT)} is sanctioned"
        return True, ""
    SUITE.add("coverage/next-eq-8-exception-only-phase8", cov_next)

    def cov_checkpoints():
        def has_cp(ph):
            t = strip_code_fences(text_of(ph))
            return any(_GOOD_CHECKPOINT.match(l) for l in t.split("\n"))
        n = _count_phases(has_cp)
        return n == 9, "" if n == 9 else f"only {n}/9 phases have ▶ checkpoints"
    SUITE.add("coverage/checkpoints-eq-9", cov_checkpoints)

    def cov_green_box():
        def has_green(ph):
            t = strip_code_fences(text_of(ph))
            for l in t.split("\n"):
                stripped = _BQ_PREFIX.sub("", l)
                if (_ATX.match(stripped) and "🟢" in stripped) or (
                        re.search(r"🟢 \*\*", l) and _BQ_PREFIX.match(l)):
                    return True
            return False
        n = _count_phases(has_green)
        return n == 9, "" if n == 9 else f"only {n}/9 phases have a 🟢 beginner box"
    SUITE.add("coverage/green-box-eq-9", cov_green_box)

    def cov_single_h1():
        n = sum(1 for name in PHASES
                if len([h for h in all_headings(text_of(name), include_blockquoted=False)
                        if h[1] == 1]) == 1)
        return n == 9, "" if n == 9 else f"only {n}/9 phases have exactly one H1"
    SUITE.add("coverage/single-h1-eq-9", cov_single_h1)


_make_coverage_cases()


if __name__ == "__main__":
    from harness import main
    main(SUITE)
