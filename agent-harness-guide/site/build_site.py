#!/usr/bin/env python3
"""Generate the static HTML mirror of the agent-harness guide.

The markdown files in agent-harness-guide/ are the SOURCE OF TRUTH; the HTML
under site/html/ is generated and never hand-edited.  Re-running this script
is byte-idempotent.

Usage:
    pip install markdown pygments
    python build_site.py            # from agent-harness-guide/site/

Dependencies: stdlib + python-markdown + pygments.  No network, no CDN.
"""

from __future__ import annotations

import html as html_mod
import posixpath
import re
import sys
import xml.etree.ElementTree as etree
from pathlib import Path

import markdown
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

import figures

SITE_DIR = Path(__file__).resolve().parent
GUIDE_DIR = SITE_DIR.parent
HTML_DIR = SITE_DIR / "html"
GITHUB_BLOB = "https://github.com/joshps23/ai-eng-2/blob/main/agent-harness-guide/"
GITHUB_TREE = "https://github.com/joshps23/ai-eng-2/tree/main/agent-harness-guide/"
SITE_URL = "https://joshps23.github.io/ai-eng-2/"

# The loop mark — an open circular arrow, white on harness indigo — as an
# inline SVG data URI: zero extra requests, works in light and dark tabs.
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3.5' "
           "fill='%234F46E5'/%3E%3Cpath d='M11.5 8.5a3.5 3.5 0 1 1-1-2.45' "
           "fill='none' stroke='white' stroke-width='1.6' "
           "stroke-linecap='round'/%3E%3Cpath d='M11.7 3.6v2.6H9.1' "
           "fill='none' stroke='white' stroke-width='1.6' "
           "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")

# ---------------------------------------------------------------------------
# Page mapping (deterministic).  source path is relative to GUIDE_DIR.
# Tuples: (output basename, source relpath, short nav label, nav section)
# Order here IS the reading order used for prev/next footers.
# ---------------------------------------------------------------------------
PAGES = [
    ("index.html", "README.md", "Guide hub", "Start here"),
    ("learning-path.html", "LEARNING-PATH.md", "Learning Path", "Start here"),
    ("beginner-notes.html", "BEGINNER-NOTES.md", "Python Cheat-Sheet", "Start here"),
    ("faq.html", "FAQ.md", "Setup & FAQ", "Start here"),
    ("00-foundations.html", "00-foundations.md", "Phase 0 — Foundations", "Phases"),
    ("01-bare-harness.html", "01-bare-harness.md", "Phase 1 — Bare Harness", "Phases"),
    ("02-tool-system.html", "02-tool-system.md", "Phase 2 — Tool System", "Phases"),
    ("03-conversation-and-streaming.html", "03-conversation-and-streaming.md",
     "Phase 3 — Conversation & Streaming", "Phases"),
    ("04-real-tools.html", "04-real-tools.md", "Phase 4 — Real Tools", "Phases"),
    ("05-permissions-and-safety.html", "05-permissions-and-safety.md",
     "Phase 5 — Permissions & Safety", "Phases"),
    ("06-context-management.html", "06-context-management.md",
     "Phase 6 — Context Management", "Phases"),
    ("07-subagents-orchestration.html", "07-subagents-orchestration.md",
     "Phase 7 — Sub-agents", "Phases"),
    ("08-production-harness.html", "08-production-harness.md",
     "Phase 8 — Production Harness", "Phases"),
    ("09-library-reference.html", "09-library-reference.md",
     "Appendix — Library Reference", "Appendix"),
    ("exercises.html", "EXERCISES.md", "Exercises", "Practice"),
    ("glossary.html", "GLOSSARY.md", "Glossary", "Practice"),
    ("notebooks.html", "notebooks/README.md", "Notebooks", "Practice"),
]
NAV_SECTIONS = ["Start here", "Phases", "Appendix", "Practice"]

# source relpath -> output basename (for link rewriting)
SOURCE_TO_PAGE = {src: out for out, src, _, _ in PAGES}

ALERT_TYPES = {"NOTE": "Note", "TIP": "Tip", "IMPORTANT": "Important",
               "WARNING": "Warning", "CAUTION": "Caution"}
ALERT_RE = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", re.S)

# ---------------------------------------------------------------------------
# Lesson view (bite-sized delivery of the Phases pages).
#
# Each phase page is additionally sliced into flat ordinal lesson pages
# (04-real-tools-5.html) derived purely from heading structure — zero
# per-phase configuration.  The full pages stay the permanent addresses
# (identical id sets, canonical targets); lessons are a derived reading path
# whose boundaries may move when the markdown is edited.  The split rule:
# pack consecutive h2 sections greedily (a "Version N" h2 always starts a new
# lesson), budgeted by visible words (refsection content excluded at the
# collapsed-unit granularity); sub-split any lesson over LESSON_HARD at h3
# boundaries (a ▶ checkpoint h3 never begins a fragment); everything from the
# first "Pitfalls"/"Key takeaways" h2 onward is one terminal wrap-up lesson.
# ---------------------------------------------------------------------------
LESSON_CEIL = 1600        # visible-word packing budget per lesson
LESSON_FLOOR = 400        # below this a lesson never forces a break / merges back
LESSON_HARD = 2400        # hard ceiling: sub-split within the h2 (build-failing)
LESSON_WPM = 130          # reading pace for the ~N min estimate
LESSON_CHECKPOINT_MIN = 2  # extra minutes per ▶ run-it-now checkpoint
LESSON_MIN_MINUTES = 3
VERSION_RE = re.compile(r"\bVersion (\d)\b")   # same rung regex as the ladder
RITUAL_RE = re.compile(r"^(pitfalls|key takeaways)\b", re.I)
TAG_RE = re.compile(r"<[^>]+>")
ID_RE = re.compile(r'id="([^"]*)"')
ANCHOR_BASELINE = "anchor-baseline.txt"   # pinned id snapshot, lives in site/

# Fingerprints from figures.FIGURES that matched a fence during this build.
# main()'s drift gate fails the build if any figure never matched — the
# markdown diagram changed, so the SVG must be redrawn or re-fingerprinted.
FIGURE_HITS: set[str] = set()


# ---------------------------------------------------------------------------
# GitHub-compatible slugger
# ---------------------------------------------------------------------------
def gh_slug(text: str) -> str:
    """GitHub's heading-anchor algorithm: lowercase; drop everything that is
    not a unicode letter/digit, space, hyphen or underscore (emoji, ▶, em
    dashes, dots, backtick-stripped punctuation all vanish); spaces -> '-'.
    Runs of hyphens are NOT collapsed and leading hyphens survive, e.g.
    '▶ Run it now' -> '-run-it-now'."""
    text = text.strip().lower()
    kept = [ch for ch in text if ch.isalnum() or ch in "-_ "]
    return "".join(kept).replace(" ", "-")


def short_label(text: str) -> str:
    """Short label for a heading: text after the first em dash, cut at any
    ':', truncated near 28 chars.  Used by the ladder rungs and (identically,
    per the lesson spec) by derived lesson titles."""
    label = text.split("—", 1)[1] if "—" in text else text
    label = label.split(":", 1)[0].strip()
    if len(label) > 28:
        label = label[:28].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"
    return label


class SlugDeduper:
    """Duplicate slugs get -1, -2 ... suffixes, like github-slugger."""

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    def slug(self, text: str) -> str:
        base = gh_slug(text)
        n = self.seen.get(base, 0)
        self.seen[base] = n + 1
        return base if n == 0 else f"{base}-{n}"


def highlight_block(code: str, lang: str, cssclass: str = "highlight") -> str:
    """Pygments-render one code block in the same shape codehilite emits."""
    try:
        lexer = get_lexer_by_name(lang)
    except ClassNotFound:
        lexer = get_lexer_by_name("text")
    formatter = HtmlFormatter(cssclass=cssclass, wrapcode=True)
    return highlight(code, lexer, formatter).strip()


# ---------------------------------------------------------------------------
# Markdown extension: preprocessing + tree post-processing
# ---------------------------------------------------------------------------
class GuidePreprocessor(Preprocessor):
    """Fence-aware source fixes:
    1. python-markdown merges blockquotes separated by a single blank line;
       GitHub keeps them separate.  Insert an HTML comment between them.
    2. Tag <details>/<summary> so md_in_html renders the markdown inside.
    3. The core fenced_code extension only recognizes fences at column 0;
       fences nested in blockquotes or list items (GitHub renders these) are
       pygments-highlighted here and stashed as raw HTML.
    4. Column-0 plain-text fences (``` or ```text — ASCII diagrams, expected
       output) are highlighted here too, with a `nocopy` class so the
       copy-button JS skips them.
    5. python-markdown wants list continuations at the 4-space column; GitHub
       accepts 3.  Inside blockquote lists, 1–3-space continuation blocks
       (after a blank quote line) are re-indented to 4 so the list survives.
    """

    BQ = re.compile(r"^ {0,3}>(\s|$|>)")
    FENCE = re.compile(r"^(`{3,}|~{3,})")
    NESTED_OPEN = re.compile(
        r"^(?P<quotes>(?: {0,3}> ?)+)?(?P<indent> {1,3})?"
        r"(?P<fence>`{3,})(?P<lang>[\w+.-]*)\s*$")
    TEXT_OPEN = re.compile(r"^(?P<fence>`{3,})(?:text)?\s*$")
    QUOTE_PREFIX = re.compile(r"^(?: {0,3}> ?)+")
    LIST_ITEM = re.compile(r" {0,3}(?:\d+[.)]|[-*+]) ")

    def run(self, lines: list[str]) -> list[str]:
        out: list[str] = []
        in_fence = False
        fence_char, fence_len = "", 0
        bq_in_list = False   # a list is open inside the current blockquote
        bq_blank = False     # the previous blockquote line was blank (">")
        i = 0
        while i < len(lines):
            line = lines[i]
            m = self.FENCE.match(line)
            if m:
                if not in_fence:
                    tm = self.TEXT_OPEN.match(line)
                    if tm:
                        repl, j = self._text_fence(lines, i, tm)
                        if repl is not None:
                            out.extend(repl)
                            i = j
                            continue
                run = m.group(1)
                if not in_fence:
                    in_fence, fence_char, fence_len = True, run[0], len(run)
                elif run[0] == fence_char and len(run) >= fence_len:
                    in_fence = False
                out.append(line)
                i += 1
                continue
            if in_fence:
                out.append(line)
                i += 1
                continue
            nm = self.NESTED_OPEN.match(line)
            if nm and (nm.group("quotes") or nm.group("indent")):
                repl, i = self._nested_fence(lines, i, nm)
                out.extend(repl)
                continue
            if (self.BQ.match(line) and len(out) >= 2
                    and out[-1].strip() == "" and self.BQ.match(out[-2])):
                out[-1] = ""
                out.append("<!-- bq-split -->")
                out.append("")
            qm = self.QUOTE_PREFIX.match(line)
            if qm:
                content = line[qm.end():]
                if not content.strip():
                    bq_blank = True
                else:
                    if self.LIST_ITEM.match(content):
                        bq_in_list = True
                    elif (bq_in_list and bq_blank
                            and re.match(r" {1,3}\S", content)):
                        line = qm.group(0) + "    " + content.lstrip(" ")
                    elif bq_in_list and bq_blank and not content.startswith(" "):
                        bq_in_list = False  # column-0 paragraph ends the list
                    bq_blank = False
            else:
                bq_in_list = bq_blank = False
            line = line.replace("<details>", '<details markdown="1">')
            line = line.replace("<summary>", '<summary markdown="span">')
            out.append(line)
            i += 1
        return out

    def _text_fence(self, lines: list[str], i: int,
                    tm: re.Match) -> tuple[list[str] | None, int]:
        """Collect a column-0 plain-text fence (no language, or `text`),
        highlight it with a `nocopy` marker class, stash it, and return the
        replacement line plus the index just past the closing fence."""
        fence = tm.group("fence")
        code: list[str] = []
        j = i + 1
        closed = False
        while j < len(lines):
            cm = re.match(r"^(`{3,})\s*$", lines[j])
            if cm and len(cm.group(1)) >= len(fence):
                closed = True
                j += 1
                break
            code.append(lines[j])
            j += 1
        if not closed:
            return None, i  # malformed; let the normal fence path handle it
        text = "\n".join(code)
        html = highlight_block(text, "text", "highlight nocopy")
        fig = figures.FIGURES.get(figures.fingerprint(text))
        if fig is not None:
            FIGURE_HITS.add(figures.fingerprint(text))
            # The fence is one of the guide's ASCII diagrams: render the
            # designed SVG, and keep the original ASCII as the copyable,
            # md-faithful mirror in a collapsed details.
            html = (
                '<figure class="diagram" role="group">\n'
                + fig.svg
                + '\n<details class="diagram-text">'
                + "<summary>Text version of this diagram</summary>\n"
                + html
                + "\n</details>\n</figure>"
            )
        return [self.md.htmlStash.store(html)], j

    def _nested_fence(self, lines: list[str], i: int,
                      nm: re.Match) -> tuple[list[str], int]:
        """Collect a fence nested in a blockquote and/or list indentation,
        highlight it with pygments, stash it, and return the replacement
        line(s) plus the index just past the closing fence."""
        depth = (nm.group("quotes") or "").count(">")
        indent = len(nm.group("indent") or "")
        fence = nm.group("fence")
        lang = nm.group("lang") or "text"
        strip_quotes = re.compile(r"^ {0,3}> ?" * depth) if depth else None
        code: list[str] = []
        j = i + 1
        closed = False
        while j < len(lines):
            body = lines[j]
            if strip_quotes:
                qm = strip_quotes.match(body)
                if qm is None:
                    break  # blockquote ended without a closing fence
                body = body[qm.end():]
            stripped = body[:indent].lstrip() + body[indent:] if indent else body
            cm = re.match(r"^\s*(`{3,})\s*$", stripped)
            if cm and len(cm.group(1)) >= len(fence):
                closed = True
                j += 1
                break
            code.append(stripped)
            j += 1
        if not closed:
            return [lines[i]], i + 1  # leave malformed input untouched
        cssclass = ("highlight nocopy" if nm.group("lang") in ("", "text")
                    else "highlight")
        html = highlight_block("\n".join(code), lang, cssclass)
        placeholder = self.md.htmlStash.store(html)
        # GitHub treats a 1-3-space indent as list-item continuation, but
        # python-markdown wants the 4-space column — emit the placeholder
        # there so the code block stays inside its list item.
        prefix = ("> " * depth) + ("    " if indent else "")
        return [prefix + placeholder], j


class GuideTreeprocessor(Treeprocessor):
    """After inline processing: GitHub heading ids, alert admonitions,
    🟢 beginner blockquotes, task-list checkboxes, link rewriting, and
    TOC collection.  Per-page state lives on self.ctx (a PageContext)."""

    def __init__(self, md, ctx: "PageContext") -> None:
        super().__init__(md)
        self.ctx = ctx

    def run(self, root: etree.Element) -> None:
        deduper = SlugDeduper()
        for el in root.iter():
            tag = el.tag
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = "".join(el.itertext())
                el.set("id", deduper.slug(text))
                if tag == "h1" and self.ctx.h1 is None:
                    self.ctx.h1 = text
                if tag == "h2":
                    # version-ladder rungs for the header map: the first h2
                    # mentioning each "Version N", with a short label (text
                    # after the first em dash, cut at any ":").
                    vm = VERSION_RE.search(text)
                    if vm and all(r[0] != int(vm.group(1))
                                  for r in self.ctx.ladder):
                        self.ctx.ladder.append(
                            (int(vm.group(1)), short_label(text),
                             el.get("id")))
                if tag in ("h2", "h3"):
                    # "▶ Run it now" checkpoints repeat near-identically and
                    # drown the page outline — keep their ids (GitHub anchor
                    # parity) but leave them out of the page TOC.
                    if not text.lstrip().startswith("▶"):
                        self.ctx.toc.append((int(tag[1]), text, el.get("id")))
                    anchor = etree.SubElement(el, "a")
                    anchor.set("class", "hanchor")
                    anchor.set("href", "#" + el.get("id"))
                    anchor.set("aria-label", "Permalink to this section")
                    anchor.text = "¶"
            elif tag == "blockquote":
                self._blockquote(el)
            elif tag in ("ul", "ol"):
                self._tasklist(el)
            elif tag == "a":
                href = el.get("href")
                if href:
                    new = rewrite_href(href, self.ctx.source_dir)
                    el.set("href", new)
                    if (new.startswith((GITHUB_BLOB, GITHUB_TREE))
                            and href != new):
                        # a repo file/dir, not a converted page: mark it
                        cls = (el.get("class", "") + " repo-file").strip()
                        el.set("class", cls)
                        if new.partition("#")[0].endswith(".ipynb"):
                            el.set("title", "Opens the notebook on GitHub "
                                            "— or use its "
                                            "Open-in-Colab badge")
                        else:
                            el.set("title",
                                   "Opens this repository file on GitHub")
                        self.ctx.repo_links += 1
            elif tag == "p" and self.ctx.first_para is None:
                text = "".join(el.itertext()).strip()
                # skip link-only paragraphs (the ←/→ breadcrumb lines): all
                # text outside <a> elements is whitespace or separators
                link_text = "".join(t for a in el.iter("a") for t in a.itertext())
                outside = text
                for chunk in link_text:
                    outside = outside.replace(chunk, "", 1)
                if text and outside.strip(" \n·•|/←→­–—-"):
                    self.ctx.first_para = text
                else:
                    # a link-only paragraph is a markdown breadcrumb: useless
                    # in print, and quieter on screen
                    el.set("class", (el.get("class", "") + " md-breadcrumb").strip())
        self._collapse_refsections(root)
        self._wrap_tables(root)
        # guide_tree is the last treeprocessor (priority 5): the tree is now
        # final — ids assigned, refsections collapsed.  Keep a reference so
        # the lesson splitter can slice the *rendered* tree (B2: lessons must
        # inherit the full page's exact ids).
        self.ctx.root = root

    HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def _collapse_refsections(self, root: etree.Element) -> None:
        """Collapse each banner-marked "Reference copy" section into a closed
        <details class="refsection">.  The unit of collapse is the banner's
        owning heading section: the nearest h2–h4 preceding the
        blockquote.refcopy, through to the next heading of the same-or-higher
        level.  The heading itself stays OUTSIDE the details, so its
        GitHub-parity id, ¶-anchor, and TOC entry are untouched."""
        for bq in list(root.findall("blockquote")):
            if bq.get("class") != "refcopy":
                continue
            children = list(root)
            if bq not in children:
                continue  # already moved into an earlier refsection
            bq_idx = children.index(bq)
            head_idx = level = None
            for i in range(bq_idx - 1, -1, -1):
                lv = self.HEADING_LEVELS.get(children[i].tag)
                if lv in (2, 3, 4):
                    head_idx, level = i, lv
                    break
            if head_idx is None:
                continue
            end = len(children)
            for i in range(head_idx + 1, len(children)):
                lv = self.HEADING_LEVELS.get(children[i].tag)
                if lv is not None and lv <= level:
                    end = i
                    break
            # a trailing <hr> is the source's `---` divider before the next
            # section — leave it outside so HR_BEFORE_H2 still strikes it
            while end > head_idx + 1 and children[end - 1].tag == "hr":
                end -= 1
            moved = children[head_idx + 1:end]
            if not moved:
                continue
            details = etree.Element("details")
            details.set("class", "refsection")
            summary = etree.SubElement(details, "summary")
            summary.text = "Show the reference copy "
            hint = etree.SubElement(summary, "span")
            hint.set("class", "refsection-hint")
            hint.text = "consolidated re-read — skim or skip"
            details.tail = moved[-1].tail
            moved[-1].tail = None
            for el in moved:
                root.remove(el)
                details.append(el)
            root.insert(head_idx + 1, details)

    def _wrap_tables(self, root: etree.Element) -> None:
        """`display: block` on <table> strips table semantics for assistive
        tech; wrap each table in a scrolling div instead, and mark the
        header-row cells with scope="col"."""
        parents = {child: parent for parent in root.iter() for child in parent}
        for table in list(root.iter("table")):
            thead = table.find("thead")
            if thead is not None:
                for th in thead.iter("th"):
                    th.set("scope", "col")
            parent = parents.get(table)
            if parent is None:
                continue
            idx = list(parent).index(table)
            wrap = etree.Element("div")
            wrap.set("class", "table-wrap")
            wrap.tail = table.tail
            table.tail = None
            parent.remove(table)
            parent.insert(idx, wrap)
            wrap.append(table)

    def _blockquote(self, el: etree.Element) -> None:
        first = None  # first paragraph or heading child
        for child in el:
            if child.tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6"):
                first = child
                break
        if first is None:
            return
        m = ALERT_RE.match(first.text or "") if first.tag == "p" else None
        if m:
            kind = m.group(1)
            first.text = ALERT_RE.sub("", first.text, count=1)
            el.tag = "div"
            el.set("class", f"admonition {kind.lower()}")
            title = etree.Element("p")
            title.set("class", "admonition-title")
            title.text = ALERT_TYPES[kind]
            el.insert(0, title)
        else:
            head = "".join(first.itertext())[:120]
            if "🟢" in head:
                el.set("class", "beginner")
            elif head.lstrip().startswith("Reference copy"):
                el.set("class", "refcopy")

    def _tasklist(self, el: etree.Element) -> None:
        changed = False
        for li in el.findall("li"):
            target = li
            if (li.text is None or not li.text.strip()) and len(li) and li[0].tag == "p":
                target = li[0]
            text = target.text or ""
            m = re.match(r"\[([ xX])\]\s+", text)
            if m is None:
                continue
            target.text = text[m.end():]
            box = etree.Element("input")
            box.set("type", "checkbox")
            box.set("disabled", "disabled")
            if m.group(1).lower() == "x":
                box.set("checked", "checked")
            box.tail = " " + (target.text or "")
            target.text = ""
            target.insert(0, box)
            li.set("class", "task-list-item")
            changed = True
        if changed:
            el.set("class", "contains-task-list")


class PageContext:
    """Mutable per-page state shared with the treeprocessor."""

    def __init__(self, source_dir: str) -> None:
        self.source_dir = source_dir          # source dir relative to GUIDE_DIR
        self.h1: str | None = None
        self.first_para: str | None = None
        self.toc: list[tuple[int, str, str]] = []
        self.ladder: list[tuple[int, str, str]] = []  # (version, label, slug)
        self.repo_links = 0                   # links that leave the site
        self.root: etree.Element | None = None  # final rendered tree (guide_tree)


class GuideExtension(Extension):
    def __init__(self, ctx: PageContext) -> None:
        super().__init__()
        self.ctx = ctx

    def extendMarkdown(self, md) -> None:
        md.preprocessors.register(GuidePreprocessor(md), "guide_pre", 28)
        md.treeprocessors.register(GuideTreeprocessor(md, self.ctx), "guide_tree", 5)


# ---------------------------------------------------------------------------
# Link rewriting
# ---------------------------------------------------------------------------
def rewrite_href(href: str, source_dir: str) -> str:
    """Rewrite a markdown link for a page that now lives in site/html/.

    - pure #anchors, http(s)/mailto: unchanged
    - links to converted .md sources -> their .html page (anchor preserved)
    - links to anything else in the repo -> repo-relative from site/html/
    """
    if href.startswith("#") or re.match(r"^(https?:|mailto:)", href):
        return href
    path, sep, frag = href.partition("#")
    if not path:
        return href
    # resolve relative to the source file's directory -> GUIDE_DIR-relative
    resolved = posixpath.normpath(posixpath.join(source_dir, path))
    if path.endswith("/") and not resolved.endswith("/"):
        resolved += "/"
    if resolved in SOURCE_TO_PAGE:
        return SOURCE_TO_PAGE[resolved] + sep + frag
    # Everything else lives in the repository, not on this site.  The site is
    # deployed standalone (GitHub Pages), so repo-relative paths would 404 —
    # send files to GitHub's rendered view (blob) and directories to tree.
    if resolved.endswith("/"):
        return GITHUB_TREE + resolved.rstrip("/") + sep + frag
    return GITHUB_BLOB + resolved + sep + frag


# ---------------------------------------------------------------------------
# Lesson partitioning
# ---------------------------------------------------------------------------
def hub_name(out_name: str) -> str:
    """A phase's lesson-1 page doubles as its hub."""
    return out_name[:-len(".html")] + "-1.html"


def lesson_name(out_name: str, k: int) -> str:
    return out_name[:-len(".html")] + f"-{k}.html"


def heading_text(el: etree.Element) -> str:
    """Heading text without the appended ¶ permalink anchor."""
    text = "".join(el.itertext())
    if text.endswith("¶"):
        text = text[:-1]
    return text.strip()


def render_chunk(md: markdown.Markdown, el: etree.Element) -> str:
    """Serialize ONE top-level element of the rendered tree to final HTML,
    running the same serializer + postprocessors `md.convert` used (the
    htmlStash is still populated — `md.reset()` is never called), so the
    concatenation of chunks reproduces the full page's article nodes."""
    wrapper = etree.Element("div")
    wrapper.append(el)          # ElementTree keeps `el` in its original tree
    out = md.serializer(wrapper)
    out = out[out.index(">") + 1:out.rindex("</div>")]
    for pp in md.postprocessors:
        out = pp.run(out)
    return out.strip()


class Chunk:
    """One top-level node of a phase's rendered tree, with split metadata."""

    __slots__ = ("el", "html", "level", "text", "is_ref", "words",
                 "is_checkpoint")

    def __init__(self, md: markdown.Markdown, el: etree.Element) -> None:
        self.el = el
        self.html = render_chunk(md, el)
        self.level = GuideTreeprocessor.HEADING_LEVELS.get(el.tag)
        self.text = heading_text(el) if self.level else None
        self.is_ref = (el.tag == "details"
                       and "refsection" in (el.get("class") or ""))
        # Visible-word budget: refsection content is excluded at exactly the
        # collapsed-unit granularity (a refsection is always a top-level
        # <details> — _collapse_refsections works on root children only).
        # Tags are stripped with "" (itertext() semantics): pygments wraps
        # every code token in a span, and a " " replacement would count
        # `client.responses.create(...)` as half a dozen words.
        self.words = 0 if self.is_ref else len(
            html_mod.unescape(TAG_RE.sub("", self.html)).split())
        self.is_checkpoint = (self.level == 3
                              and (self.text or "").startswith("▶"))


class Lesson:
    """One derived lesson page of a phase."""

    def __init__(self, idxs: list[int], part: tuple[int, int] | None,
                 owner_idx: int | None = None) -> None:
        self.idxs = idxs              # chunk indices (full partition: struck
        self.part = part              # hrs stay accounted here, skipped only
        self.owner_idx = owner_idx    # owning-h2 chunk for h3-split fragments
        self.number = 0               # when the body html is joined)
        self.out = ""
        self.title = ""
        self.is_wrapup = False
        self.words = 0
        self.checkpoints = 0
        self.minutes = 0
        self.ids: set[str] = set()
        self.first_heading_id: str | None = None
        self.toc: list[tuple[int, str, str]] = []
        self.body = ""
        self.desc = ""


class PhasePlan:
    """A phase page's derived lesson partition plus everything the lesson
    templates and the verification battery need."""

    def __init__(self, out_name: str, src_rel: str, phase_no: int,
                 body: str, ctx: PageContext, md: markdown.Markdown) -> None:
        self.out = out_name
        self.src_rel = src_rel
        self.phase_no = phase_no
        self.body = body              # full-page body (reconstruction gate)
        self.ctx = ctx
        self.chunks = [Chunk(md, el) for el in list(ctx.root)]
        # mirror HR_BEFORE_H2: an <hr> directly before an <h2> is struck from
        # the final page, so it is skipped when lesson bodies are joined
        self.struck = {i for i in range(len(self.chunks) - 1)
                       if self.chunks[i].el.tag == "hr"
                       and self.chunks[i + 1].html.startswith("<h2")}
        self.lessons = self._partition()
        self._finalize(md)
        self.total_minutes = sum(l.minutes for l in self.lessons)
        mins = sorted(l.minutes for l in self.lessons)
        mid = len(mins) // 2
        self.median_minutes = (mins[mid] if len(mins) % 2
                               else round((mins[mid - 1] + mins[mid]) / 2))
        # h2 id -> containing lesson (for the full page's per-h2 links) and
        # any id -> lesson (for cross-lesson ladder rungs)
        self.lesson_of_id: dict[str, Lesson] = {}
        for lesson in self.lessons:
            for i in lesson.ids:
                self.lesson_of_id.setdefault(i, lesson)
        self.h2_lessons: list[tuple[str, Lesson]] = []
        for lesson in self.lessons:
            for i in lesson.idxs:
                c = self.chunks[i]
                if c.level == 2 and c.el.get("id"):
                    self.h2_lessons.append((c.el.get("id"), lesson))

    # -- the split rule (A1.1–A1.7) ------------------------------------
    def _partition(self) -> list[Lesson]:
        chunks = self.chunks
        h2s = [i for i, c in enumerate(chunks) if c.level == 2]
        if not h2s:                      # never the case for a phase page
            return [Lesson(list(range(len(chunks))), None)]
        sections = []                    # (start, end, version, ref, ritual)
        for a, b in zip(h2s, h2s[1:] + [len(chunks)]):
            title = chunks[a].text or ""
            content = chunks[a + 1:b]
            ref_owned = (any(c.is_ref for c in content)
                         and all(c.is_ref or c.el.tag == "hr"
                                 for c in content))
            sections.append((a, b, bool(VERSION_RE.search(title)), ref_owned,
                             bool(RITUAL_RE.match(title))))
        tail_at = next((k for k, s in enumerate(sections) if s[4]),
                       len(sections))
        # content before the first h2 seeds Lesson 1 (the hub)
        groups: list[list[int]] = []
        cur = list(range(0, h2s[0]))
        cur_w = sum(chunks[i].words for i in cur)
        for a, b, version, ref, _ritual in sections[:tail_at]:
            sec = list(range(a, b))
            sec_w = sum(chunks[i].words for i in sec)
            if cur and ((version and not ref)
                        or (cur_w + sec_w > LESSON_CEIL
                            and cur_w >= LESSON_FLOOR)):
                groups.append(cur)
                cur, cur_w = [], 0
            cur += sec
            cur_w += sec_w
        if cur:
            if cur_w < LESSON_FLOOR and groups:   # sliver: merge backward
                groups[-1] += cur
            else:
                groups.append(cur)
        lessons: list[Lesson] = []
        for g in groups:
            if sum(chunks[i].words for i in g) > LESSON_HARD:
                lessons.extend(self._sub_split(g))
            else:
                lessons.append(Lesson(g, None))
        if tail_at < len(sections):               # one terminal wrap-up
            wrap = Lesson(list(range(sections[tail_at][0], len(chunks))),
                          None)
            wrap.is_wrapup = True
            lessons.append(wrap)
        return lessons

    def _sub_split(self, idxs: list[int]) -> list[Lesson]:
        """Split an oversize lesson at top-level h3 (and h2) boundaries.  A
        ▶ checkpoint h3 never begins a fragment, and the first fragment
        always retains the section's opening run."""
        chunks = self.chunks
        units: list[list[int]] = [[idxs[0]]]
        for i in idxs[1:]:
            c = chunks[i]
            if c.level in (2, 3) and not c.is_checkpoint:
                units.append([i])
            else:
                units[-1].append(i)
        frags: list[list[int]] = []
        cur: list[int] = []
        cur_w = 0
        for u in units:
            u_w = sum(chunks[i].words for i in u)
            if cur and cur_w + u_w > LESSON_CEIL and cur_w >= LESSON_FLOOR:
                frags.append(cur)
                cur, cur_w = [], 0
            cur += u
            cur_w += u_w
        if cur:
            if cur_w < LESSON_FLOOR and frags:
                frags[-1] += cur
            else:
                frags.append(cur)
        if len(frags) == 1:
            return [Lesson(frags[0], None)]
        # A1.5: fragments are titled "<h2 short label> · part k of m"
        owner = next((i for i in idxs if chunks[i].level in (1, 2)), idxs[0])
        return [Lesson(f, (k, len(frags)), owner)
                for k, f in enumerate(frags, start=1)]

    # -- per-lesson metadata and body ----------------------------------
    def _finalize(self, md: markdown.Markdown) -> None:
        chunks, ctx = self.chunks, self.ctx
        for k, lesson in enumerate(self.lessons, start=1):
            lesson.number = k
            lesson.out = lesson_name(self.out, k)
            lesson.words = sum(chunks[i].words for i in lesson.idxs)
            lesson.checkpoints = sum(
                1 for i in lesson.idxs if chunks[i].is_checkpoint)
            lesson.minutes = max(LESSON_MIN_MINUTES, round(
                lesson.words / LESSON_WPM
                + LESSON_CHECKPOINT_MIN * lesson.checkpoints))
            first = chunks[lesson.idxs[0]]
            if k == 1 and not lesson.part:
                lesson.title = short_label(ctx.h1 or self.out)
            elif lesson.owner_idx is not None:
                owner = chunks[lesson.owner_idx]
                lesson.title = short_label(
                    (ctx.h1 if owner.level == 1 else owner.text)
                    or self.out)
            else:
                head = next((chunks[i] for i in lesson.idxs
                             if chunks[i].level in (1, 2)), first)
                lesson.title = short_label(head.text or ctx.h1 or self.out)
            if lesson.part:
                lesson.title += f" · part {lesson.part[0]} of {lesson.part[1]}"
            for i in lesson.idxs:
                for el in chunks[i].el.iter():
                    if el.get("id"):
                        lesson.ids.add(el.get("id"))
                if (chunks[i].level and lesson.first_heading_id is None
                        and chunks[i].el.get("id")):
                    lesson.first_heading_id = chunks[i].el.get("id")
            lesson.toc = [e for e in ctx.toc if e[2] in lesson.ids]
            # first paragraph (skipping breadcrumbs) -> og description
            for i in lesson.idxs:
                el = chunks[i].el
                if (el.tag == "p"
                        and "md-breadcrumb" not in (el.get("class") or "")):
                    text = " ".join("".join(el.itertext()).split())
                    if text:
                        lesson.desc = text
                        break
            if not lesson.desc:
                lesson.desc = f"{lesson.title} — lesson {k} of " \
                              f"{len(self.lessons)} in {ctx.h1 or self.out}."
            body = "\n".join(chunks[i].html for i in lesson.idxs
                             if i not in self.struck)
            body = postprocess_body(body)
            # ¶ permalinks on a lesson always target the full page (B1: the
            # permanent addresses are the full pages and their fragments)
            body = body.replace('class="hanchor" href="#',
                                f'class="hanchor" href="{self.out}#')
            # any other same-page fragment whose target lives in a different
            # lesson is a consultation -> send it to the full page (B2)
            def _relocalize(m: re.Match) -> str:
                frag = m.group(1)
                if frag in lesson.ids or frag == "top":
                    return m.group(0)
                return f'href="{self.out}#{frag}"'
            lesson.body = re.sub(r'href="#([^"]*)"', _relocalize, body)


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
PAGE_JS = """\
(function () {
  /* On narrow screens the stacked sidebar would push content below the
     fold on every load — start it collapsed there.  The toggle <summary> is
     hidden at desktop widths, so re-open the sidebar whenever the viewport
     crosses back above the breakpoint (rotation, window resize). */
  var sb = document.querySelector('.sidebar-wrap');
  var narrow = matchMedia('(max-width: 800px)');
  if (sb && narrow.matches) { sb.removeAttribute('open'); }
  if (sb && narrow.addEventListener) {
    narrow.addEventListener('change', function (e) {
      if (!e.matches) { sb.setAttribute('open', ''); }
    });
  }

  /* Print: open every <details> (answers, TOC) and revert afterwards.
     diagram-text mirrors are excluded — print hides them entirely (the SVG
     figure already prints; opening the ASCII would print the diagram twice). */
  var openedForPrint = [];
  window.addEventListener('beforeprint', function () {
    openedForPrint = [];
    document.querySelectorAll('details:not(.diagram-text):not([open])').forEach(function (d) {
      d.setAttribute('open', '');
      openedForPrint.push(d);
    });
  });
  window.addEventListener('afterprint', function () {
    openedForPrint.forEach(function (d) { d.removeAttribute('open'); });
    openedForPrint = [];
  });

  /* Back-to-top: hidden until the reader scrolls ~1.5 screens down.
     Without JS the control simply stays visible (the old behavior). */
  var btt = document.querySelector('.back-to-top');
  if (btt) {
    var toggleBtt = function () {
      btt.classList.toggle('btt-hidden',
                           window.scrollY < window.innerHeight * 1.5);
    };
    window.addEventListener('scroll', toggleBtt, { passive: true });
    toggleBtt();
  }

  /* Reading progress: the fixed 3px accent bar tracks scroll position.
     Without JS the element simply stays at width 0 — invisible, harmless. */
  var pbar = document.querySelector('.progress-bar');
  if (pbar) {
    var setProgress = function () {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      pbar.style.width = (max > 0 ? (window.scrollY / max) * 100 : 0) + '%';
    };
    window.addEventListener('scroll', setProgress, { passive: true });
    setProgress();
  }

  /* Deep links into collapsed sections: open every <details> ancestor of the
     target, and the refsection that immediately follows a target heading.
     Re-scroll only if something actually opened (the layout above the target
     just changed), and instantly — the CSS smooth scroll would crawl across
     tens of thousands of pixels on the long phase pages. */
  function openForHash() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id) { return; }
    var el = document.getElementById(id);
    if (!el) { return; }
    var opened = false;
    var d = el.closest('details');
    while (d) {
      if (!d.hasAttribute('open')) { d.setAttribute('open', ''); opened = true; }
      d = d.parentElement && d.parentElement.closest('details');
    }
    var sib = el.nextElementSibling;
    if (sib && sib.matches('details.refsection') && !sib.hasAttribute('open')) {
      sib.setAttribute('open', '');
      opened = true;
    }
    if (!opened) { return; }
    var jump = function () {
      var y = el.getBoundingClientRect().top + window.scrollY - 16;
      try { window.scrollTo({ top: y, behavior: 'instant' }); }
      catch (e) { window.scrollTo(0, y); }
    };
    jump();
    /* the browser's own fragment scroll was computed against the collapsed
       layout and may still be animating (CSS smooth) — re-assert once, which
       cancels it */
    setTimeout(jump, 100);
  }
  window.addEventListener('hashchange', openForHash);
  openForHash();

  /* Copy buttons, with fallbacks: Clipboard API -> hidden-textarea
     execCommand -> select the block and ask for Ctrl-C.  If no mechanism
     exists at all, inject nothing. */
  var hasClipboard = !!(navigator.clipboard && navigator.clipboard.writeText);
  var hasExec = !!(document.queryCommandSupported &&
                   document.queryCommandSupported('copy'));
  if (!hasClipboard && !hasExec && !window.getSelection) { return; }

  function execCopy(text) {
    if (!hasExec) { return false; }
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }

  function selectBlock(pre) {
    var sel = window.getSelection ? window.getSelection() : null;
    if (!sel || !document.createRange) { return false; }
    var range = document.createRange();
    range.selectNodeContents(pre);
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }

  document.querySelectorAll('div.highlight:not(.nocopy)').forEach(function (block) {
    var btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.type = 'button';
    btn.textContent = 'Copy';
    function flash(label) {
      btn.textContent = label;
      setTimeout(function () { btn.textContent = 'Copy'; }, 2000);
    }
    function fallback(pre, code) {
      if (execCopy(code)) { btn.focus(); flash('Copied!'); }
      else if (selectBlock(pre)) { flash('Press Ctrl-C'); }
      else { flash('Copy failed'); }
    }
    btn.addEventListener('click', function () {
      var pre = block.querySelector('pre');
      var code = pre.innerText;
      if (hasClipboard) {
        navigator.clipboard.writeText(code).then(function () {
          flash('Copied!');
        }).catch(function () { fallback(pre, code); });
      } else {
        fallback(pre, code);
      }
    });
    block.insertBefore(btn, block.firstChild);
  });
})();
"""


def esc(text: str) -> str:
    return html_mod.escape(text, quote=True)


def build_sidebar(current: str, current_phase: str | None = None) -> str:
    """One sidebar for the whole site.  Phase entries point at the lesson-1
    hubs (the default reading path); `current_phase` is the Phases out-name
    the rendered page belongs to (the full page itself or any of its
    lessons), whose entry is marked current."""
    parts = []
    for section in NAV_SECTIONS:
        items = []
        for out, _src, label, sec in PAGES:
            if sec != section:
                continue
            href = hub_name(out) if sec == "Phases" else out
            if sec == "Phases":
                is_current = out == current_phase
            else:
                is_current = out == current
            cls = ' class="current"' if is_current else ""
            aria = ""
            if is_current:
                aria = (' aria-current="page"' if current == href
                        else ' aria-current="true"')
            items.append(f'<li{cls}><a href="{href}"{aria}>{esc(label)}</a></li>')
        parts.append(
            f'<p class="sidebar-heading">{esc(section)}</p>\n<ul>\n'
            + "\n".join(items) + "\n</ul>")
    return "\n".join(parts)


# the nine phase pages, in phase-number order (their PAGES order)
PHASE_PAGES = [(out, label) for out, _src, label, sec in PAGES
               if sec == "Phases"]


def build_phase_header(out_name: str,
                       ladder: list[tuple[int, str, str]]) -> str:
    """Wayfinding chrome for Phases pages only: a phase-number medallion
    eyebrow, the 0–8 phase rail (a map of the whole guide), and the page's
    own V1→V4 ladder map.  All generated from PAGES / the page's headings —
    no per-page configuration."""
    outs = [o for o, _ in PHASE_PAGES]
    if out_name not in outs:
        return ""
    n = outs.index(out_name)
    parts = [
        '<p class="phase-eyebrow"><span class="phase-medallion" '
        f'aria-hidden="true">{n}</span>'
        f'<span class="phase-kicker">Phase {n} of {len(outs) - 1}</span></p>'
    ]
    dots = []
    for i, (out, label) in enumerate(PHASE_PAGES):
        if i:
            dots.append('<span class="rail-link" aria-hidden="true"></span>')
        cur = ' aria-current="page"' if out == out_name else ""
        dots.append(f'<a class="rail-dot" href="{out}"{cur} '
                    f'title="{esc(label)}" aria-label="{esc(label)}">{i}</a>')
    parts.append('<nav class="phase-rail" aria-label="All phases">'
                 + "".join(dots) + "</nav>")
    if len(ladder) >= 2:
        rungs = []
        for k, (v, label, slug) in enumerate(ladder):
            if k:
                rungs.append('<span class="ladder-sep" aria-hidden="true">'
                             "→</span>")
            rungs.append(f'<a class="ladder-rung" href="#{slug}">'
                         f'<span class="ladder-medallion">V{v}</span> '
                         f"{esc(label)}</a>")
        parts.append('<nav class="ladder" aria-label="Version ladder">'
                     + "".join(rungs) + "</nav>")
    return "\n".join(parts)


def build_toc(toc: list[tuple[int, str, str]]) -> str:
    """Nested page TOC: h3 entries group under their h2 in a sub-<ul>.
    '▶ Run it now' checkpoints are excluded at collection time (see
    GuideTreeprocessor), which also removes every duplicate heading text —
    no disambiguation suffixes are needed."""
    if not toc:
        return ""
    parts = ["<ul>"]
    open_h2 = False     # an h2-level <li> is open
    open_sub = False    # a nested <ul> is open inside it
    for level, text, slug in toc:
        link = f'<a href="#{slug}">{esc(text)}</a>'
        if level == 2:
            if open_sub:
                parts.append("</ul>")
                open_sub = False
            if open_h2:
                parts.append("</li>")
            parts.append(f'<li class="toc-h2">{link}')
            open_h2 = True
        else:
            if not open_h2:  # h3 before any h2: keep it at the top level
                parts.append(f'<li class="toc-h3">{link}</li>')
                continue
            if not open_sub:
                parts.append("<ul>")
                open_sub = True
            parts.append(f'<li class="toc-h3">{link}</li>')
    if open_sub:
        parts.append("</ul>")
    if open_h2:
        parts.append("</li>")
    parts.append("</ul>")
    return (
        '<details class="page-toc">\n<summary>On this page</summary>\n'
        + "\n".join(parts) + "\n</details>"
    )


# ---------------------------------------------------------------------------
# Lesson chrome (kicker, rails, hub plan, Continue card, full-page strip)
# ---------------------------------------------------------------------------
def build_lesson_strip(plan: PhasePlan) -> str:
    """Slim strip under the full page's phase header: the labeled crossing
    into the lesson track (the only full-page addition besides the per-h2
    lesson links)."""
    n = len(plan.lessons)
    return (
        '<p class="lesson-strip">This phase is also available as '
        f'{n} lessons of ~{plan.median_minutes} min — '
        f'<a href="{hub_name(plan.out)}">start Lesson 1 →</a> '
        '<span class="lesson-strip-note">(this single page is best for '
        'printing)</span></p>')


def build_lesson_header(plan: PhasePlan, lesson: Lesson) -> str:
    """Wayfinding chrome for a lesson page: medallion + position kicker +
    time/checkpoint chips, the 0–8 phase rail (targeting the lesson-1 hubs),
    the lesson rail, the cross-lesson version ladder, and the conditional
    per-lesson TOC."""
    n = len(plan.lessons)
    p = plan.phase_no
    kicker = (f"Phase {p} · Wrap-up" if lesson.is_wrapup
              else f"Phase {p} · Lesson {lesson.number} of {n}")
    chips = f'<span class="lesson-time">~{lesson.minutes} min</span>'
    if lesson.checkpoints:
        noun = ("checkpoint" if lesson.checkpoints == 1 else "checkpoints")
        chips += (f'<span class="lesson-cp">{lesson.checkpoints} '
                  f'<span aria-hidden="true">▶</span> {noun}</span>')
    parts = [
        '<p class="phase-eyebrow"><span class="phase-medallion" '
        f'aria-hidden="true">{p}</span>'
        f'<span class="phase-kicker">{esc(kicker)}</span>{chips}</p>'
    ]
    dots = []
    for i, (out, label) in enumerate(PHASE_PAGES):
        if i:
            dots.append('<span class="rail-link" aria-hidden="true"></span>')
        cur = ' aria-current="true"' if out == plan.out else ""
        dots.append(f'<a class="rail-dot" href="{hub_name(out)}"{cur} '
                    f'title="{esc(label)}" aria-label="{esc(label)}">{i}</a>')
    parts.append('<nav class="phase-rail" aria-label="All phases">'
                 + "".join(dots) + "</nav>")
    ticks = []
    for sib in plan.lessons:
        cur = ' aria-current="page"' if sib.number == lesson.number else ""
        what = "Wrap-up" if sib.is_wrapup else f"Lesson {sib.number}"
        label = f"{what}: {sib.title} (~{sib.minutes} min)"
        ticks.append(f'<a class="lesson-tick" href="{sib.out}"{cur} '
                     f'title="{esc(label)}" aria-label="{esc(label)}">'
                     f'{sib.number}</a>')
    parts.append('<nav class="lesson-rail" aria-label="Lessons in this phase">'
                 + "".join(ticks) + "</nav>")
    if len(plan.ctx.ladder) >= 2:
        rungs = []
        for k, (v, label, slug) in enumerate(plan.ctx.ladder):
            if k:
                rungs.append('<span class="ladder-sep" aria-hidden="true">'
                             "→</span>")
            target = plan.lesson_of_id.get(slug)
            href = f"{target.out}#{slug}" if target else f"{plan.out}#{slug}"
            rungs.append(f'<a class="ladder-rung" href="{href}">'
                         f'<span class="ladder-medallion">V{v}</span> '
                         f"{esc(label)}</a>")
        parts.append('<nav class="ladder" aria-label="Version ladder">'
                     + "".join(rungs) + "</nav>")
    if len(lesson.toc) >= 3:
        parts.append(build_toc(lesson.toc))
    return "\n".join(parts)


def build_lesson_plan(plan: PhasePlan) -> str:
    """The hub's generated lesson plan: every lesson with title, time and
    checkpoint badge, the phase total, and the labeled single-page escape
    hatch.  Pure structure — no authored prose is invented."""
    n = len(plan.lessons)
    items = []
    for lesson in plan.lessons:
        meta = f"~{lesson.minutes} min"
        if lesson.checkpoints:
            noun = ("checkpoint" if lesson.checkpoints == 1
                    else "checkpoints")
            meta += (f' · {lesson.checkpoints} <span aria-hidden="true">▶'
                     f'</span><span class="visually-hidden"> {noun}</span>')
        badge = (' <span class="plan-badge">Wrap-up</span>'
                 if lesson.is_wrapup else "")
        inner = (f'<span class="plan-num" aria-hidden="true">'
                 f'{lesson.number}</span>'
                 f'<span class="plan-title">{esc(lesson.title)}{badge}</span>'
                 f'<span class="plan-meta">{meta}</span>')
        if lesson.number == 1:
            items.append('<li class="plan-here" aria-current="page">'
                         f'<span class="plan-row">{inner}</span></li>')
        else:
            items.append(f'<li><a class="plan-row" href="{lesson.out}">'
                         f'{inner}</a></li>')
    return (
        '<section class="lesson-plan" aria-label="Lesson plan">\n'
        '<p class="plan-kicker">Lesson plan <span class="plan-total">'
        f'{n} lessons · ~{plan.total_minutes} min</span></p>\n'
        '<ol class="plan-list">\n' + "\n".join(items) + '\n</ol>\n'
        f'<p class="plan-single">Prefer one scroll? <a href="{plan.out}">'
        'Read this phase as a single page</a>.</p>\n'
        '</section>')


def build_continue(plan: PhasePlan, lesson: Lesson,
                   plans: list[PhasePlan]) -> str:
    """The Continue card: one prominent next-step card (next title + its
    time + k+1 of n), a quieter previous link, and the labeled crossing to
    the single page."""
    n = len(plan.lessons)
    k = lesson.number
    # -- next: lesson k+1, or the next phase's hub, or the PAGES chain
    if k < n:
        nxt = plan.lessons[k]
        kicker = (f"Next · Wrap-up · Lesson {nxt.number} of {n}"
                  if nxt.is_wrapup else f"Next · Lesson {nxt.number} of {n}")
        href, title = nxt.out, nxt.title
        time_chip = f'<span class="continue-time">~{nxt.minutes} min</span>'
    elif plan.phase_no + 1 < len(plans):
        nplan = plans[plan.phase_no + 1]
        first = nplan.lessons[0]
        kicker = (f"Next · Phase {nplan.phase_no} · Lesson 1 of "
                  f"{len(nplan.lessons)}")
        href, title = first.out, first.title
        time_chip = f'<span class="continue-time">~{first.minutes} min</span>'
    else:
        idx = next(i for i, pg in enumerate(PAGES) if pg[0] == plan.out)
        href, title = PAGES[idx + 1][0], PAGES[idx + 1][2]
        kicker, time_chip = "Next", ""
    card = (
        f'<a class="continue-card" href="{href}" rel="next">\n'
        f'<span class="continue-kicker">{esc(kicker)}</span>\n'
        f'<span class="continue-title">{esc(title)}{time_chip}'
        '<span class="continue-arrow" aria-hidden="true">→</span></span>\n'
        '</a>')
    # -- quieter previous link
    if k > 1:
        prev = plan.lessons[k - 2]
        what = "Wrap-up" if prev.is_wrapup else f"Lesson {prev.number}"
        prev_link = (f'<a href="{prev.out}" rel="prev">← {what} · '
                     f'{esc(prev.title)}</a>')
    elif plan.phase_no > 0:
        pplan = plans[plan.phase_no - 1]
        prev = pplan.lessons[-1]
        prev_link = (f'<a href="{prev.out}" rel="prev">← Phase '
                     f'{pplan.phase_no} · Wrap-up</a>')
    else:
        idx = next(i for i, pg in enumerate(PAGES) if pg[0] == plan.out)
        prev_link = (f'<a href="{PAGES[idx - 1][0]}" rel="prev">← '
                     f'{esc(PAGES[idx - 1][2])}</a>')
    single = (f'<a class="continue-fullpage" href="{plan.out}'
              + (f'#{lesson.first_heading_id}' if lesson.first_heading_id
                 else "")
              + '">View this lesson on the single page</a>')
    return ('<nav class="continue" aria-label="Continue">\n'
            + card + '\n<p class="continue-aux">\n'
            + prev_link + '\n' + single + '\n</p>\n</nav>')


def inject_lesson_links(body: str, plan: PhasePlan) -> str:
    """Full pages, SHOULD C8: a small lesson-view link next to each h2's ¶
    anchor, targeting the lesson containing that h2.  Adds no ids — the
    anchor-parity contract is untouched."""
    n = len(plan.lessons)
    for h2_id, lesson in plan.h2_lessons:
        needle = f'class="hanchor" href="#{h2_id}">¶</a></h2>'
        link = (f'<a class="lesson-link" href="{lesson.out}" '
                f'title="Read this section in lesson view (Lesson '
                f'{lesson.number} of {n})">lesson {lesson.number}</a>')
        body = body.replace(
            needle,
            f'class="hanchor" href="#{h2_id}">¶</a>{link}</h2>', 1)
    return body


# A source `---` divider directly above an `##` renders as <hr> + <h2>, but
# every h2 already carries its own bottom border — the section would open
# with a double rule.  Strike the <hr> (string post-processing, like
# index_hero; the markdown source is untouched).
HR_BEFORE_H2 = re.compile(r"<hr>\s*(?=<h2\b)")

# A 🟢 beginner box directly after a heading sometimes re-states the heading
# as its bold lead-in ("### 🟢 Beginner track" then "🟢 **Beginner track.**…")
# — the label fires twice.  Drop the box's lead-in only when its text equals
# the heading's (conservative literal back-reference; plain-text headings
# only, content untouched everywhere else).
BEGINNER_DUP = re.compile(
    r'(<h([2-6])\b[^>]*>(?:🟢 ?)?(?P<t>[^<]+?) ?'
    r'<a aria-label="[^"]*" class="hanchor"[^>]*>¶</a></h\2>\s*'
    r'<blockquote class="beginner">\s*<p>)🟢 <strong>(?P=t)\.?</strong>\s*')


def postprocess_body(body: str) -> str:
    body = HR_BEFORE_H2.sub("", body)
    body = BEGINNER_DUP.sub(r"\1", body)
    return body


def index_hero(body: str) -> str:
    """Index-only landing treatment: wrap the lead h1 + standfirst blockquote
    in a hero, add the eyebrow kicker before the h1 and the CTA buttons after
    the blockquote.  Pure string post-processing; the markdown is untouched."""
    start = body.find("<h1")
    end = body.find("</blockquote>", start)
    if start == -1 or end == -1:
        return body
    end += len("</blockquote>")
    return (
        body[:start]
        + '<div class="hero">\n<p class="hero-eyebrow">The Agent Harness Guide</p>\n'
        + body[start:end]
        + '\n<p class="hero-cta">\n'
        + '<a class="btn btn-primary" href="00-foundations.html">Start with Phase 0 →</a>\n'
        + '<a class="btn btn-ghost" href="learning-path.html">Pick a learning path</a>\n'
        + '</p>\n</div>'
        + body[end:]
    )


PAGE_SHELL = """<!DOCTYPE html>
<!-- GENERATED from {src_rel} — do not edit; run site/build_site.py -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{og_url}">
<meta property="og:site_name" content="Agent Harness Guide">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#FDFDFE" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0E1016" media="(prefers-color-scheme: dark)">
<title>{title}</title>
<link rel="stylesheet" href="style.css">
<link rel="icon" href="{favicon}">
</head>
<body{body_class}>
<div class="progress-bar" aria-hidden="true"></div>
<a class="skip-link" href="#main">Skip to content</a>
<div class="layout">
<details class="sidebar-wrap" open>
<summary class="sidebar-toggle">Guide navigation</summary>
<nav class="sidebar" aria-label="Guide pages">
<p class="site-mark">agent-harness<span class="mark-slash">/</span></p>
{sidebar}
</nav>
</details>
<main id="main">
<header class="page-header">
{header}
</header>
<article>
{body}
</article>
{after_article}<footer class="page-footer">
{footer_nav}
<p class="generated-note">{generated_note}</p>
<p class="source-link"><a class="repo-file" href="{source_url}" title="Requires access to the repository">View the markdown source on GitHub</a></p>
</footer>
<a class="back-to-top" href="#top" aria-label="Back to top">↑ Top</a>
</main>
</div>
<script>
{page_js}</script>
</body>
</html>
"""


def build_page(out_name: str, src_rel: str, body: str, ctx: PageContext,
               idx: int, plan: PhasePlan | None = None) -> str:
    h1 = ctx.h1 or PAGES[idx][2]
    # the hub's h1 is ~90 chars; use its short nav label in the tab title
    title_text = PAGES[idx][2] if out_name == "index.html" else h1
    title = f"{title_text} — Agent Harness Guide"
    desc = (ctx.first_para or h1).replace("\n", " ")
    if len(desc) > 158:
        desc = desc[:157].rstrip() + "…"

    prev_link = next_link = ""
    if idx > 0:
        p_out, _, p_label, _ = PAGES[idx - 1]
        prev_link = f'<a class="prev" href="{p_out}" rel="prev">← {esc(p_label)}</a>'
    if idx < len(PAGES) - 1:
        n_out, _, n_label, _ = PAGES[idx + 1]
        next_link = f'<a class="next" href="{n_out}" rel="next">{esc(n_label)} →</a>'

    repo_note = (" Links marked ↗ open files of this project on GitHub."
                 if ctx.repo_links else "")

    is_index = out_name == "index.html"
    body = postprocess_body(body)
    if is_index:
        body = index_hero(body)
    if plan is not None:
        body = inject_lesson_links(body, plan)
    header = "\n".join(part for part in
                       (build_phase_header(out_name, ctx.ladder),
                        build_lesson_strip(plan) if plan else "",
                        build_toc(ctx.toc)) if part)

    return PAGE_SHELL.format(
        src_rel=src_rel,
        desc=esc(desc),
        canonical=f"{SITE_URL}{out_name}",
        og_type="website" if is_index else "article",
        og_url=f"{SITE_URL}{out_name}",
        title=esc(title),
        favicon=FAVICON,
        body_class=' class="page-index"' if is_index else "",
        sidebar=build_sidebar(out_name, plan.out if plan else None),
        header=header,
        body=body,
        after_article="",
        footer_nav=('<nav class="prevnext" aria-label="Previous and next '
                    f'page">\n{prev_link}\n{next_link}\n</nav>'),
        generated_note=(f"Generated from <code>{esc(src_rel)}</code> — the "
                        f"markdown is the source of truth.{repo_note}"),
        source_url=f"{GITHUB_BLOB}{src_rel}",
        page_js=PAGE_JS,
    )


def build_lesson_page(plan: PhasePlan, lesson: Lesson,
                      plans: list[PhasePlan]) -> str:
    """One derived lesson page.  Same chrome as build_page; the canonical
    URL points at the full page (the permanent address), the footer is the
    Continue card, and lesson 1 doubles as the phase hub (lesson plan
    injected after its content)."""
    n = len(plan.lessons)
    what = ("Wrap-up" if lesson.is_wrapup
            else f"Lesson {lesson.number}")
    title = (f"Phase {plan.phase_no} · {what} — {lesson.title} "
             "— Agent Harness Guide")
    desc = lesson.desc.replace("\n", " ")
    if len(desc) > 158:
        desc = desc[:157].rstrip() + "…"
    repo_note = (" Links marked ↗ open files of this project on GitHub."
                 if ' repo-file"' in lesson.body
                 or " repo-file " in lesson.body else "")
    after = ""
    if lesson.number == 1:
        after = build_lesson_plan(plan) + "\n"
    generated_note = (
        f"Generated from <code>{esc(plan.src_rel)}</code> — lesson "
        f"{lesson.number} of {n} in the derived lesson view (boundaries may "
        f'move when the markdown changes; the <a href="{plan.out}">single '
        f"page</a> is the permanent address).{repo_note}")
    return PAGE_SHELL.format(
        src_rel=plan.src_rel,
        desc=esc(desc),
        canonical=f"{SITE_URL}{plan.out}",
        og_type="article",
        og_url=f"{SITE_URL}{lesson.out}",
        title=esc(title),
        favicon=FAVICON,
        body_class="",
        sidebar=build_sidebar(lesson.out, plan.out),
        header=build_lesson_header(plan, lesson),
        body=lesson.body,
        after_article=after,
        footer_nav=build_continue(plan, lesson, plans),
        generated_note=generated_note,
        source_url=f"{GITHUB_BLOB}{plan.src_rel}",
        page_js=PAGE_JS,
    )


# ---------------------------------------------------------------------------
# CSS (handwritten + deterministic pygments defs)
# ---------------------------------------------------------------------------
BASE_CSS = """\
/* GENERATED by site/build_site.py — do not edit. */
/* Contrast ratios in comments are WCAG 2.x, recomputed against this palette. */
:root {
  color-scheme: light dark;
  /* "harness indigo" light scheme */
  --bg: #FDFDFE;            /* off-white, cool cast */
  --fg: #1B1F27;            /* 16.24:1 on bg */
  --muted: #5A6172;         /* 6.10:1 on bg; 5.79:1 on code-bg; 5.88:1 on sidebar-bg */
  --border: #E3E6EC;        /* hairlines, decorative */
  --border-strong: #C9CEDA; /* table rules, control borders (decorative — labels carry contrast) */
  --accent: #4F46E5;        /* links: 6.19:1 on bg, 5.87:1 on code-bg; white on it: 6.29:1 */
  --accent-deep: #4338CA;   /* hover / text-on-tint: 7.77:1 on bg, 6.47:1 on 10% accent tint */
  --code-bg: #F6F7FA;
  --sidebar-bg: #F8F9FB;
  --green: #166F33;         /* 6.16:1 on bg, 5.57:1 on its 7% tint */
  --warn: #8A5C04;          /* 5.72:1 on bg, 5.39:1 on its 8% tint */
  --warn-border: #D4A72C;
  --selection: #CDD3FF;     /* fg on it: 11.29:1 */
  --font-sans: ui-sans-serif, -apple-system, BlinkMacSystemFont,
    "Segoe UI Variable Text", "Segoe UI", Roboto, "Helvetica Neue", Arial,
    sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
  --font-mono: ui-monospace, "SF Mono", SFMono-Regular, "Cascadia Code",
    "JetBrains Mono", Menlo, Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0E1016;            /* violet-black, not GitHub navy */
    --fg: #E7EAF3;            /* 15.81:1 on bg, 14.45:1 on code-bg */
    --muted: #99A1B3;         /* 7.34:1 on bg, 6.71:1 on code-bg */
    --border: #2A2F3C;
    --border-strong: #3A4150;
    --accent: #8C9BFF;        /* 7.47:1 on bg, 6.82:1 on code-bg; dark text on it: 7.47:1 */
    --accent-deep: #A5B0FF;   /* hover step up: 9.28:1 on bg, 8.49:1 on code-bg */
    --code-bg: #171A23;
    --sidebar-bg: #12141C;
    --green: #3FB950;         /* 7.49:1 on bg, 6.68:1 on its 9% tint */
    --warn: #D29922;          /* 7.53:1 on bg, 7.01:1 on its 9% tint */
    --warn-border: #9E6A03;
    --selection: #3D4380;     /* fg on it: 7.55:1 */
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: var(--font-sans);
  line-height: 1.6;
}
::selection { background: var(--selection); color: var(--fg); } /* 11.29:1 light, 7.55:1 dark */
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sidebar a:focus-visible, .btn:focus-visible { outline-offset: 0; } /* inside rounded rows */
@media (prefers-reduced-motion: no-preference) {
  html { scroll-behavior: smooth; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important; }
}
.skip-link {
  position: absolute; left: -999px; top: 0; background: var(--accent);
  color: #fff; padding: 0.5em 1em; z-index: 10;
}
.skip-link:focus { left: 0; }
.layout { display: flex; align-items: flex-start; max-width: 1200px; margin: 0 auto; }
.sidebar-wrap {
  flex: 0 0 250px; position: sticky; top: 0; max-height: 100vh;
  overflow-y: auto; background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
}
.sidebar-toggle {
  cursor: pointer; padding: 0.875rem 1rem; font-weight: 600;
  list-style: none; display: block;
  font-family: var(--font-mono); font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); /* 5.88:1 on sidebar-bg */
  border-bottom: 1px solid var(--border);
}
.sidebar-toggle::-webkit-details-marker { display: none; }
.sidebar-toggle::after { content: " ▾"; color: var(--muted); }
details[open] > .sidebar-toggle::after { content: " ▴"; }
/* The sidebar is always expanded on desktop (the JS re-opens it above the
   breakpoint), so the "Guide navigation" chrome is redundant there — the
   site mark becomes the sidebar's first line.  <details> content stays
   rendered: visibility follows the [open] attribute, not the summary. */
@media (min-width: 801px) {
  .sidebar-toggle { display: none; }
}
.sidebar { padding: 0 1rem 1rem; font-size: 0.875rem; line-height: 1.5; }
/* typographic site mark: mono `agent-harness/`, the slash in accent */
.site-mark {
  font-family: var(--font-mono); font-weight: 700; font-size: 0.875rem;
  letter-spacing: 0; margin: 0.875rem 0 0.25rem; color: var(--fg);
}
.site-mark .mark-slash { color: var(--accent); }
.sidebar .sidebar-heading {
  font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
  margin: 1.25em 0 0.25em;
}
.sidebar ul { list-style: none; margin: 0; padding: 0; }
.sidebar li { margin: 0; }
.sidebar a {
  display: block; padding: 0.3em 0.625em; border-radius: 6px;
  color: var(--fg); text-decoration: none; font-size: 0.875rem;
  transition: background-color 120ms ease-out, color 120ms ease-out;
}
.sidebar a:hover { background: color-mix(in srgb, var(--fg) 7%, transparent); }
.sidebar li.current > a {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent-deep); font-weight: 600;
  box-shadow: inset 2px 0 0 var(--accent);
}
main { flex: 1; min-width: 0; padding: 1.5rem 2rem 3rem; max-width: 80ch; }
article { max-width: 75ch; font-size: 1.0625rem; line-height: 1.7; }
article p, article ul, article ol { margin: 0 0 1.25rem; }
article blockquote > :last-child, article .admonition > :last-child,
article details > :last-child { margin-bottom: 0; }
/* tablet: a 250px rail + 2rem padding pinches the article to ~55ch at 834w;
   give the text back ~6ch.  Must precede the 800px block so the stacked-
   layout rules below win the cascade at phone widths. */
@media (max-width: 1000px) {
  .sidebar-wrap { flex-basis: 220px; }
  main { padding: 1.5rem; }
}
@media (max-width: 800px) {
  .layout { flex-direction: column; }
  /* column flex: align-items flex-start would shrink main to max-content
     (~80ch), clipping at narrow viewports — found by the Playwright pass */
  main { width: 100%; }
  .sidebar-wrap { position: static; flex: none; width: 100%; max-height: none;
    border-right: none; border-bottom: 1px solid var(--border); }
  main { padding: 1rem; }
  /* keep the fixed back-to-top control clear of the next-phase link */
  .page-footer { padding-bottom: 3.5rem; }
}
h1, h2, h3, h4 { scroll-margin-top: 1.25rem; }
.md-breadcrumb { font-size: 0.8125rem; color: var(--muted); }
h1 {
  font-size: 2.25rem; line-height: 1.15; font-weight: 800;
  letter-spacing: -0.022em; margin: 0 0 1rem;
}
h2 {
  font-size: 1.5rem; line-height: 1.25; font-weight: 700;
  letter-spacing: -0.015em; margin: 3rem 0 1rem; padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--border);
}
h3 {
  font-size: 1.1875rem; line-height: 1.35; font-weight: 650;
  letter-spacing: -0.008em; margin: 2.25rem 0 0.75rem;
}
h4 { font-size: 1rem; line-height: 1.4; font-weight: 600; letter-spacing: 0;
  margin: 1.75rem 0 0.625rem; }
.hanchor {
  margin-left: 0.35em; font-size: 0.8em; text-decoration: none;
  color: var(--muted); opacity: 0; transition: opacity 120ms ease-out;
}
h2:hover > .hanchor, h3:hover > .hanchor, .hanchor:focus-visible { opacity: 1; }
.hanchor:hover { color: var(--accent-deep); }
a { color: var(--accent); }
hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
/* tables: rows by rule, not grid+zebra */
.table-wrap { overflow-x: auto; max-width: 100%; margin: 0 0 1.25rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.9375rem; }
th, td { border: 0; border-bottom: 1px solid var(--border);
  padding: 0.5em 0.875em; text-align: left; }
th { background: transparent; border-bottom: 2px solid var(--border-strong);
  font-family: var(--font-mono); font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
/* hover paint only where rows lead somewhere: the index phase table */
.page-index tbody tr:hover td {
  background: color-mix(in srgb, var(--fg) 3%, transparent); }
code, pre, kbd {
  font-family: var(--font-mono);
  font-size: 0.875em;
}
code { background: var(--code-bg); padding: 0.15em 0.35em; border-radius: 4px; }
pre code { background: none; padding: 0; font-size: 1em; }
div.highlight {
  position: relative; background: var(--code-bg);
  border: 1px solid var(--border); border-radius: 8px; margin: 1.25rem 0;
}
/* div.highlight pre (0,1,1) must beat the appended pygments `pre` (0,0,1),
   which sets line-height 125% — specificity wins regardless of order. */
div.highlight pre { margin: 0; padding: 0.875rem 1rem; overflow-x: auto;
  line-height: 1.6; font-size: 0.875rem; }
div.highlight pre, .sidebar-wrap {
  scrollbar-width: thin; scrollbar-color: var(--border-strong) transparent; }
div.highlight pre::-webkit-scrollbar { height: 8px; }
div.highlight pre::-webkit-scrollbar-thumb {
  background: var(--border-strong); border-radius: 4px; }
div.highlight pre::-webkit-scrollbar-track { background: transparent; }
.copy-btn {
  position: absolute; top: 0.5rem; right: 0.5rem;
  padding: 0.25em 0.7em; font-size: 0.75rem; font-family: var(--font-sans);
  cursor: pointer; border: 1px solid var(--border-strong); border-radius: 6px;
  background: var(--bg); color: var(--muted);
  /* always visible (a long block scrolls the corner out of reach before a
     hover reveal could help); dimmed until hovered/focused */
  opacity: 0.7;
  transition: opacity 120ms ease-out, color 120ms ease-out;
}
div.highlight:hover .copy-btn, .copy-btn:hover,
.copy-btn:focus-visible { opacity: 1; }
.copy-btn:hover { color: var(--fg); }
blockquote {
  margin: 1.25rem 0; padding: 0.75rem 1.25rem; color: var(--muted);
  border-left: 3px solid var(--border-strong); border-radius: 0 8px 8px 0;
}
blockquote.beginner {
  border-left-color: var(--green);
  background: color-mix(in srgb, var(--green) 7%, var(--bg));
  color: var(--fg);
}
blockquote.refcopy {
  border-left-color: var(--muted);
  background: color-mix(in srgb, var(--muted) 8%, var(--bg));
  color: var(--fg);
}
blockquote.refcopy > p:first-child::before { content: "🔖 "; }
.admonition {
  margin: 1.25rem 0; padding: 0.75rem 1.25rem;
  border-left: 3px solid var(--warn-border); border-radius: 0 8px 8px 0;
  background: color-mix(in srgb, var(--warn-border) 8%, var(--bg));
}
.admonition > .admonition-title { margin: 0 0 0.5rem; }
.admonition-title { font-weight: 700; color: var(--warn); }
.admonition-title::before { content: "⚠ "; }
.admonition.note, .admonition.tip, .admonition.important {
  border-left-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 7%, var(--bg));
}
.admonition.note .admonition-title, .admonition.tip .admonition-title,
.admonition.important .admonition-title { color: var(--accent); }
.admonition.note .admonition-title::before, .admonition.tip .admonition-title::before,
.admonition.important .admonition-title::before { content: "ℹ "; }
details { margin: 1.25rem 0; }
details > summary { cursor: pointer; font-weight: 600; }
article details:not(.page-toc) {
  border: 1px solid var(--border); border-radius: 10px;
  padding: 0.625rem 1rem; background: transparent;
}
.page-toc {
  background: transparent; border: 1px solid var(--border);
  border-radius: 10px; padding: 0.625rem 1rem; font-size: 0.875rem;
}
.page-toc > summary {
  color: var(--muted); font-weight: 600;
  font-family: var(--font-mono); font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.page-toc ul { list-style: none; padding-left: 0; margin: 0.5em 0; }
.page-toc ul ul { padding-left: 1.5em; margin: 0; }
.page-toc li { margin: 0.25em 0; }
.page-toc a { color: var(--fg); text-decoration: none; }
.page-toc a:hover { color: var(--accent-deep); }
.page-toc li.toc-h2 > a { font-weight: 600; }
ul.contains-task-list { list-style: none; padding-left: 1em; }
.task-list-item input { margin-right: 0.5em; }
.page-footer { margin-top: 3em; border-top: 1px solid var(--border); padding-top: 1em; }
.prevnext { display: flex; justify-content: space-between; gap: 1rem; }
.prevnext a {
  flex: 0 1 48%; padding: 0.75rem 1rem;
  border: 1px solid var(--border); border-radius: 10px;
  text-decoration: none; font-weight: 600; font-size: 0.9375rem;
  color: var(--fg);
  transition: border-color 120ms ease-out, color 120ms ease-out;
}
.prevnext a:hover { border-color: var(--accent); color: var(--accent-deep); }
.prevnext .prev::before { content: "Previous"; }
.prevnext .next::before { content: "Next"; }
.prevnext a::before {
  display: block; font-family: var(--font-mono); font-size: 0.6875rem;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); margin-bottom: 0.2rem;
}
.prevnext .next { margin-left: auto; text-align: right; }
.generated-note { color: var(--muted); font-size: 0.8125rem; line-height: 1.5; }
.source-link { font-size: 0.8125rem; line-height: 1.5; margin: 0.5em 0 0; }
a.repo-file::after { content: " ↗"; font-size: 0.85em; }
.back-to-top {
  position: fixed; right: 1rem; bottom: 1rem; z-index: 5;
  background: var(--code-bg); color: var(--fg);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 0.35em 0.7em; font-size: 0.8rem; text-decoration: none;
  opacity: 0.85;
  box-shadow: 0 1px 3px rgb(0 0 0 / 0.12);
  transition: opacity 160ms ease-out, visibility 160ms;
}
.back-to-top:hover, .back-to-top:focus-visible { opacity: 1; }
/* JS adds/removes this near the top of the page; with JS disabled the
   class is never applied and the control stays visible. */
.back-to-top.btt-hidden { visibility: hidden; opacity: 0; pointer-events: none; }
/* ---- reading-progress bar (JS sets the width; 0 = invisible without JS) ---- */
.progress-bar {
  position: fixed; top: 0; left: 0; height: 3px; width: 0;
  background: var(--accent); z-index: 9; pointer-events: none;
}
/* ---- collapsed "Reference copy" sections ---- */
details.refsection {
  background: color-mix(in srgb, var(--muted) 6%, var(--bg));
}
details.refsection > summary { color: var(--fg); }
details.refsection > summary::before { content: "🔖 "; }
details.refsection[open] > summary { margin-bottom: 1rem; }
.refsection-hint {
  font-family: var(--font-mono); font-size: 0.75rem; font-weight: 400;
  color: var(--muted); margin-left: 0.5em;
}
/* ---- build-time SVG diagrams (figures.py) ---- */
figure.diagram { margin: 1.5rem 0; padding: 0; }
.diagram svg { display: block; width: 100%; max-width: 100%; height: auto; }
.d-box   { fill: var(--code-bg); stroke: var(--border-strong); stroke-width: 1.25; rx: 8; }
.d-pill  { rx: 18; }
.d-accent{ stroke: var(--accent); fill: color-mix(in srgb, var(--accent) 7%, var(--bg)); }
.d-good  { stroke: var(--green);  fill: color-mix(in srgb, var(--green) 7%, var(--bg)); }
.d-edge  { stroke: var(--border-strong); fill: none; stroke-width: 1.5; }
.d-edge-hot { stroke: var(--accent); fill: none; stroke-width: 2; }  /* the loop-back */
.d-label { fill: var(--fg); font: 600 13px var(--font-sans); }
.d-mono  { fill: var(--muted); font: 11px var(--font-mono); }  /* ≥6.1:1 on bg */
.d-mono-label { fill: var(--fg); font: 600 12px var(--font-mono); }
.d-arrow { fill: var(--border-strong); }
.d-arrow-hot { fill: var(--accent); }
.d-chip { stroke-width: 1; rx: 9; }
.d-chip-accent { stroke: var(--accent); fill: color-mix(in srgb, var(--accent) 10%, var(--bg)); }
.d-chip-green  { stroke: var(--green);  fill: color-mix(in srgb, var(--green) 9%, var(--bg)); }
.d-chip-warn   { stroke: var(--warn-border); fill: color-mix(in srgb, var(--warn) 9%, var(--bg)); }
.d-chip-text { font: 10.5px var(--font-mono); }
.d-chip-text-accent { fill: var(--accent-deep); }
.d-chip-text-green  { fill: var(--green); }
.d-chip-text-warn   { fill: var(--warn); }
details.diagram-text { margin: 0.75rem 0 0; font-size: 0.875rem; }
details.diagram-text > summary {
  color: var(--muted); font-weight: 600; font-size: 0.8125rem;
}
/* ---- phase wayfinding chrome (Phases pages only) ---- */
.phase-eyebrow {
  display: flex; align-items: center; gap: 0.75rem; margin: 0.25rem 0 1rem;
}
.phase-medallion {
  flex: none; width: 44px; height: 44px; border-radius: 10px;
  background: var(--accent); color: #fff;             /* 6.29:1 */
  display: flex; align-items: center; justify-content: center;
  font: 800 1.25rem var(--font-mono);
}
.phase-kicker {
  font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--accent-deep);
}
.phase-rail { display: flex; align-items: center; margin: 0 0 1rem; }
.rail-dot {
  flex: none; width: 26px; height: 26px; border-radius: 50%;
  border: 1px solid var(--border-strong); background: var(--bg);
  color: var(--muted);                                /* 6.10:1 */
  display: flex; align-items: center; justify-content: center;
  font: 600 0.75rem var(--font-mono); text-decoration: none;
  transition: border-color 120ms ease-out, color 120ms ease-out;
}
.rail-dot:hover { border-color: var(--accent); color: var(--accent-deep); }
.rail-dot[aria-current] {
  background: var(--accent); border-color: var(--accent);
  color: #fff;                                        /* 6.29:1 */
}
.rail-link { flex: none; width: 14px; height: 1px; background: var(--border); }
.ladder {
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 0.375rem 0.5rem; margin: 0 0 1rem;
}
.ladder-rung {
  display: inline-flex; align-items: center; gap: 0.4em;
  border: 1px solid var(--border-strong); border-radius: 999px;
  padding: 0.2em 0.8em 0.2em 0.3em; text-decoration: none;
  color: var(--fg); font-size: 0.8125rem; font-weight: 600;
  transition: border-color 120ms ease-out, color 120ms ease-out;
}
.ladder-rung:hover { border-color: var(--accent); color: var(--accent-deep); }
.ladder-medallion {
  font: 700 0.6875rem var(--font-mono);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent-deep); border-radius: 999px; padding: 0.15em 0.5em;
}
.ladder-sep { color: var(--muted); }
/* ---- lesson view (derived bite-size pages) ---- */
.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap;
}
.phase-eyebrow { flex-wrap: wrap; }
.lesson-time, .lesson-cp {
  font: 600 0.75rem var(--font-mono); letter-spacing: 0.02em;
  border: 1px solid var(--border-strong); border-radius: 999px;
  padding: 0.2em 0.7em; color: var(--muted); white-space: nowrap;
}
.lesson-cp {
  color: var(--accent-deep);
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
}
/* full-page strip: the labeled crossing into the lesson track */
.lesson-strip {
  margin: 0 0 1rem; padding: 0.625rem 1rem; font-size: 0.875rem;
  border: 1px solid var(--border); border-radius: 10px;
  background: color-mix(in srgb, var(--accent) 5%, var(--bg));
}
.lesson-strip a { font-weight: 600; }
.lesson-strip-note { color: var(--muted); }
/* lesson rail: one tick per lesson, 18px gaps -> 44px tap pitch */
.lesson-rail {
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 1.125rem; margin: 0 0 1rem;
}
.lesson-tick {
  position: relative; flex: none; width: 26px; height: 26px;
  border-radius: 8px; border: 1px solid var(--border-strong);
  background: var(--bg); color: var(--muted);              /* 6.10:1 */
  display: flex; align-items: center; justify-content: center;
  font: 600 0.75rem var(--font-mono); text-decoration: none;
  transition: border-color 120ms ease-out, color 120ms ease-out;
}
.lesson-tick::after { content: ""; position: absolute; inset: -9px; } /* 44px target */
.lesson-tick:hover { border-color: var(--accent); color: var(--accent-deep); }
.lesson-tick[aria-current="page"] {
  background: var(--accent); border-color: var(--accent);
  color: #fff;                                             /* 6.29:1 */
}
/* hub lesson plan */
.lesson-plan {
  margin: 2.5rem 0 0; padding: 1rem 1.25rem;
  border: 1px solid var(--border); border-radius: 12px;
}
.plan-kicker {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 1rem; flex-wrap: wrap; margin: 0 0 0.5rem;
  font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
}
.plan-total { color: var(--accent-deep); letter-spacing: 0.02em; }
.plan-list { list-style: none; margin: 0 0 1rem; padding: 0; }
.plan-list li { margin: 0; border-bottom: 1px solid var(--border); }
.plan-list li:last-child { border-bottom: 0; }
.plan-row {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.55rem 0.375rem; border-radius: 8px;
  text-decoration: none; color: var(--fg);
  transition: background-color 120ms ease-out, color 120ms ease-out;
}
a.plan-row:hover { background: color-mix(in srgb, var(--accent) 7%, transparent); }
a.plan-row:hover .plan-title { color: var(--accent-deep); }
.plan-num {
  flex: none; width: 1.9em; height: 1.9em; border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font: 700 0.75rem var(--font-mono);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent-deep);
}
.plan-title { font-weight: 600; font-size: 0.9375rem; min-width: 0; }
.plan-meta {
  margin-left: auto; text-align: right;
  font: 600 0.75rem var(--font-mono); color: var(--muted);
  white-space: nowrap;
}
.plan-badge {
  font: 700 0.625rem var(--font-mono); text-transform: uppercase;
  letter-spacing: 0.08em; white-space: nowrap; color: var(--green);
  border: 1px solid color-mix(in srgb, var(--green) 45%, transparent);
  border-radius: 999px; padding: 0.1em 0.6em; margin-left: 0.4em;
}
.plan-here .plan-row { background: color-mix(in srgb, var(--accent) 8%, transparent); }
.plan-here .plan-title::after {
  content: " — you are here"; font-weight: 400; font-size: 0.8125rem;
  color: var(--muted);
}
.plan-single { margin: 0; font-size: 0.875rem; color: var(--muted); }
/* Continue card: the goal-gradient pull at the end of every lesson */
.continue { margin: 0; }
.continue-card {
  display: block; padding: 1rem 1.25rem; text-decoration: none;
  border: 1px solid var(--border-strong); border-radius: 12px;
  background: color-mix(in srgb, var(--accent) 4%, var(--bg));
  transition: border-color 120ms ease-out;
}
.continue-card:hover { border-color: var(--accent); }
.continue-kicker {
  display: block; margin-bottom: 0.3rem;
  font-family: var(--font-mono); font-size: 0.6875rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
}
.continue-title {
  display: flex; align-items: baseline; gap: 0.6em; flex-wrap: wrap;
  font-weight: 700; font-size: 1.125rem; color: var(--fg);
}
.continue-card:hover .continue-title { color: var(--accent-deep); }
.continue-time {
  font: 600 0.75rem var(--font-mono); color: var(--muted);
  white-space: nowrap;
}
.continue-arrow { margin-left: auto; color: var(--accent); }
.continue-aux {
  display: flex; justify-content: space-between; gap: 0.5rem 1.5rem;
  flex-wrap: wrap; margin: 0.75rem 0 0; font-size: 0.875rem;
}
.continue-aux a { color: var(--muted); text-decoration: none; }
.continue-aux a:hover { color: var(--accent-deep); text-decoration: underline; }
/* per-h2 lesson-view links on full pages: hover-revealed, like ¶ */
.lesson-link {
  margin-left: 0.6em; padding: 0.1em 0.6em; white-space: nowrap;
  font: 600 0.6875rem var(--font-mono); letter-spacing: 0.04em;
  text-transform: uppercase; text-decoration: none; color: var(--muted);
  border: 1px solid var(--border-strong); border-radius: 999px;
  vertical-align: 0.2em;
  opacity: 0; transition: opacity 120ms ease-out, color 120ms ease-out,
    border-color 120ms ease-out;
}
h2:hover > .lesson-link, .lesson-link:focus-visible { opacity: 1; }
.lesson-link:hover { color: var(--accent-deep); border-color: var(--accent); }
/* ---- index landing page (body.page-index only) ---- */
.hero { padding: 1.5rem 0 0.5rem; }
.hero .hero-eyebrow {
  font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--accent-deep); margin: 0 0 0.75rem;
}
.page-index h1 { font-size: clamp(2rem, 4.5vw, 2.75rem); text-wrap: balance; }
.hero blockquote {
  border: 0; padding: 0; background: transparent;
  font-size: 1.1875rem; line-height: 1.6; color: #444B5A;  /* 8.61:1 on bg */
}
.hero .hero-cta { display: flex; gap: 0.75rem; flex-wrap: wrap; margin: 1.5rem 0 0; }
.btn {
  display: inline-block; padding: 0.6em 1.2em; border-radius: 8px;
  font-weight: 600; font-size: 0.9375rem; text-decoration: none;
  transition: background-color 120ms ease-out, border-color 120ms ease-out;
}
.btn-primary { background: var(--accent); color: #fff; }   /* 6.29:1 */
.btn-primary:hover { background: var(--accent-deep); }     /* white on it: 7.90:1 */
.btn-ghost { border: 1px solid var(--border-strong); color: var(--fg); }
.btn-ghost:hover { border-color: var(--accent); color: var(--accent-deep); }
.page-index .page-header { display: none; }
.page-index .table-wrap td:first-child strong {
  font-size: 1.25rem; color: var(--accent-deep);
  font-variant-numeric: tabular-nums;
}
@media (prefers-color-scheme: dark) {
  /* dark text on the accent fill: 7.47:1 on #8C9BFF */
  .skip-link { color: var(--bg); }
  .btn-primary { color: var(--bg); }
  .phase-medallion { color: var(--bg); }                   /* 7.47:1 */
  .rail-dot[aria-current] { color: var(--bg); }            /* 7.47:1 */
  .lesson-tick[aria-current="page"] { color: var(--bg); }  /* 7.47:1 */
  .btn-primary:hover { background: #A5B0FF; }  /* dark text on it: 9.28:1 */
  .hero blockquote { color: var(--muted); }    /* 7.34:1 */
  blockquote.beginner { background: color-mix(in srgb, var(--green) 9%, var(--bg)); }
  .admonition { background: color-mix(in srgb, var(--warn-border) 9%, var(--bg)); }
  .admonition.note, .admonition.tip, .admonition.important {
    background: color-mix(in srgb, var(--accent) 10%, var(--bg)); }
}
@media print {
  .sidebar-wrap, .skip-link, .copy-btn, .page-header, .page-toc, .prevnext,
  .back-to-top, .hanchor, .hero-cta, .source-link, .progress-bar,
  .diagram-text, .md-breadcrumb, .lesson-strip, .lesson-rail, .lesson-link,
  .lesson-plan, .continue { display: none !important; }
  /* use the sheet: drop the screen column, center the text at a book-like
     measure instead of hugging the left half of the page */
  .layout { max-width: none; }
  main { max-width: none; }
  article { max-width: 65ch; margin: 0 auto; }
  article a { color: inherit; }
  div.highlight pre { white-space: pre-wrap; overflow-x: visible; }
  .table-wrap { overflow-x: visible; }
  th, td { word-break: break-word; }
}
"""


# Hand-written light token rules: pygments 2.20 ships github-dark but no
# github-light, so the light scheme is GitHub-Light's palette transcribed by
# hand, mirroring the github-dark block's class coverage and bold/italic
# treatment so both schemes speak one language.  Comments are nudged from
# GitHub's #6E7781 (only 4.24:1 on --code-bg) to #59626E.  Every color is
# >= 4.5:1 on --code-bg #F6F7FA: #CF222E 5.00, #8250DF 4.71, #0A3069 11.96,
# #0550AE 7.09, #59626E 5.77, #953800 6.89, #116329 6.90, #82071E 9.81,
# #1B1F27 15.41.
LIGHT_PYGMENTS = """\
.highlight .hll { background-color: #FFF8C5 }
.highlight .c { color: #59626E; font-style: italic } /* Comment */
.highlight .err { color: #82071E } /* Error */
.highlight .k { color: #CF222E } /* Keyword */
.highlight .n { color: #1B1F27 } /* Name */
.highlight .o { color: #CF222E; font-weight: bold } /* Operator */
.highlight .p { color: #1B1F27 } /* Punctuation */
.highlight .ch { color: #59626E; font-style: italic } /* Comment.Hashbang */
.highlight .cm { color: #59626E; font-style: italic } /* Comment.Multiline */
.highlight .cp { color: #59626E } /* Comment.Preproc */
.highlight .cpf { color: #59626E; font-style: italic } /* Comment.PreprocFile */
.highlight .c1 { color: #59626E; font-style: italic } /* Comment.Single */
.highlight .cs { color: #59626E; font-style: italic } /* Comment.Special */
.highlight .gd { color: #82071E } /* Generic.Deleted */
.highlight .ge { font-style: italic } /* Generic.Emph */
.highlight .ges { font-weight: bold; font-style: italic } /* Generic.EmphStrong */
.highlight .gr { color: #82071E } /* Generic.Error */
.highlight .gh { color: #0A3069; font-weight: bold } /* Generic.Heading */
.highlight .gi { color: #116329 } /* Generic.Inserted */
.highlight .go { color: #59626E } /* Generic.Output */
.highlight .gp { color: #59626E } /* Generic.Prompt */
.highlight .gs { font-weight: bold } /* Generic.Strong */
.highlight .gu { color: #0A3069; font-weight: bold } /* Generic.Subheading */
.highlight .gt { color: #0550AE } /* Generic.Traceback */
.highlight .kc { color: #0550AE } /* Keyword.Constant */
.highlight .kd { color: #CF222E } /* Keyword.Declaration */
.highlight .kn { color: #CF222E } /* Keyword.Namespace */
.highlight .kp { color: #0550AE } /* Keyword.Pseudo */
.highlight .kr { color: #CF222E } /* Keyword.Reserved */
.highlight .kt { color: #CF222E } /* Keyword.Type */
.highlight .m { color: #0550AE } /* Literal.Number */
.highlight .s { color: #0A3069 } /* Literal.String */
.highlight .na { color: #0550AE } /* Name.Attribute */
.highlight .nb { color: #1B1F27 } /* Name.Builtin */
.highlight .nc { color: #953800; font-weight: bold } /* Name.Class */
.highlight .no { color: #0550AE } /* Name.Constant */
.highlight .nd { color: #8250DF; font-weight: bold } /* Name.Decorator */
.highlight .ni { color: #59626E; font-weight: bold } /* Name.Entity */
.highlight .ne { color: #953800; font-weight: bold } /* Name.Exception */
.highlight .nf { color: #8250DF; font-weight: bold } /* Name.Function */
.highlight .nl { color: #953800 } /* Name.Label */
.highlight .nn { color: #CF222E } /* Name.Namespace */
.highlight .nt { color: #116329 } /* Name.Tag */
.highlight .nv { color: #953800 } /* Name.Variable */
.highlight .ow { color: #CF222E; font-weight: bold } /* Operator.Word */
.highlight .w { color: #59626E } /* Text.Whitespace */
.highlight .mb { color: #0550AE } /* Literal.Number.Bin */
.highlight .mf { color: #0550AE } /* Literal.Number.Float */
.highlight .mh { color: #0550AE } /* Literal.Number.Hex */
.highlight .mi { color: #0550AE } /* Literal.Number.Integer */
.highlight .mo { color: #0550AE } /* Literal.Number.Oct */
.highlight .sa { color: #0550AE } /* Literal.String.Affix */
.highlight .sb { color: #0A3069 } /* Literal.String.Backtick */
.highlight .sc { color: #0A3069 } /* Literal.String.Char */
.highlight .dl { color: #0A3069 } /* Literal.String.Delimiter */
.highlight .sd { color: #0A3069; font-style: italic } /* Literal.String.Doc */
.highlight .s2 { color: #0A3069 } /* Literal.String.Double */
.highlight .se { color: #0550AE } /* Literal.String.Escape */
.highlight .sh { color: #0A3069 } /* Literal.String.Heredoc */
.highlight .si { color: #0A3069 } /* Literal.String.Interpol */
.highlight .sx { color: #0A3069 } /* Literal.String.Other */
.highlight .sr { color: #0A3069 } /* Literal.String.Regex */
.highlight .s1 { color: #0A3069 } /* Literal.String.Single */
.highlight .ss { color: #0550AE } /* Literal.String.Symbol */
.highlight .bp { color: #1B1F27 } /* Name.Builtin.Pseudo */
.highlight .fm { color: #8250DF; font-weight: bold } /* Name.Function.Magic */
.highlight .vc { color: #953800 } /* Name.Variable.Class */
.highlight .vg { color: #953800 } /* Name.Variable.Global */
.highlight .vi { color: #953800 } /* Name.Variable.Instance */
.highlight .vm { color: #0550AE } /* Name.Variable.Magic */
.highlight .il { color: #0550AE } /* Literal.Number.Integer.Long */
"""


def build_css() -> str:
    dark = HtmlFormatter(style="github-dark").get_style_defs(".highlight")
    return (
        BASE_CSS
        + "\n/* pygments: light (GitHub-Light, hand-tuned — see LIGHT_PYGMENTS) */\n"
        + LIGHT_PYGMENTS
        + "\n/* pygments: dark */\n@media (prefers-color-scheme: dark) {\n"
        + "\n".join("  " + line for line in dark.splitlines())
        + "\n}\n"
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def convert_page(src_rel: str) -> tuple[str, PageContext, markdown.Markdown]:
    source = (GUIDE_DIR / src_rel).read_text(encoding="utf-8")
    ctx = PageContext(source_dir=posixpath.dirname(src_rel))
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "codehilite", "md_in_html",
                    GuideExtension(ctx)],
        extension_configs={
            "codehilite": {"css_class": "highlight", "guess_lang": False},
        },
        output_format="html5",
    )
    body = md.convert(source)
    # md is returned un-reset: render_chunk needs the live serializer,
    # postprocessors and htmlStash to slice lessons out of ctx.root.
    return body, ctx, md


# ---------------------------------------------------------------------------
# Verification battery (anchor parity, partition completeness, link
# integrity and the lesson word ceiling are build-failing gates; the
# checkpoint report is a warning).
# ---------------------------------------------------------------------------
def anchor_snapshot(written: dict[str, str]) -> str:
    """Ordered id lists of the full (non-lesson) pages, in the exact format
    pinned in site/anchor-baseline.txt."""
    lines = []
    for name in sorted(out for out, _src, _l, _s in PAGES):
        ids = ID_RE.findall(written[name])
        lines.append(f"== {name} ({len(ids)} ids)")
        lines.extend(ids)
    return "\n".join(lines) + "\n"


def run_battery(written: dict[str, str], plans: list[PhasePlan]) -> None:
    errors: list[str] = []
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731

    # 1. Anchor parity: the full pages' ordered id lists must be byte-equal
    #    to the pinned snapshot (the permanent-address contract, B2).
    snap = anchor_snapshot(written)
    baseline = SITE_DIR / ANCHOR_BASELINE
    if baseline.exists():
        if baseline.read_text(encoding="utf-8") != snap:
            import difflib
            diff = list(difflib.unified_diff(
                baseline.read_text(encoding="utf-8").splitlines(),
                snap.splitlines(), ANCHOR_BASELINE, "this build",
                lineterm="", n=1))
            errors.append(
                "ANCHOR PARITY: full-page id lists drifted from the pinned "
                f"site/{ANCHOR_BASELINE}.  If the markdown legitimately "
                "changed, re-pin the baseline deliberately.  Diff (first 40 "
                "lines):\n  " + "\n  ".join(diff[:40]))
    else:
        baseline.write_text(snap, encoding="utf-8")
        print(f"NOTE: pinned new anchor snapshot at site/{ANCHOR_BASELINE}")

    # 2. Partition completeness: every top-level rendered node of each phase
    #    appears in exactly one lesson, and the chunk rendering reproduces
    #    the full page's article (whitespace-normalized).
    for plan in plans:
        allocated = sorted(i for l in plan.lessons for i in l.idxs)
        if allocated != list(range(len(plan.chunks))):
            errors.append(f"PARTITION: {plan.out}: lessons do not cover the "
                          "article nodes exactly (lost/duplicated chunks)")
        if norm("\n".join(c.html for c in plan.chunks)) != norm(plan.body):
            errors.append(f"PARTITION: {plan.out}: per-chunk rendering does "
                          "not reconstruct the full-page article")
        got = written[plan.out].count('class="lesson-link"')
        if got != len(plan.h2_lessons):
            errors.append(f"PARTITION: {plan.out}: expected "
                          f"{len(plan.h2_lessons)} per-h2 lesson links, "
                          f"injected {got}")

    # 3. Link integrity: every internal href in every generated page (full
    #    pages AND lessons) resolves to an existing file, and every fragment
    #    to an id present in the target.
    ids_by_file = {name: set(ID_RE.findall(text))
                   for name, text in written.items()}
    for name, text in sorted(written.items()):
        for href in sorted(set(re.findall(r'href="([^"]*)"', text))):
            href = html_mod.unescape(href)
            if href.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            path, _, frag = href.partition("#")
            if not path:
                if frag in ("", "top") or frag in ids_by_file[name]:
                    continue  # #top is the browser-native back-to-top target
                errors.append(f"LINK: {name}: dangling fragment #{frag}")
            elif path == "style.css":
                continue
            elif path not in ids_by_file:
                errors.append(f"LINK: {name}: target file missing: {href}")
            elif frag and frag not in ids_by_file[path]:
                errors.append(f"LINK: {name}: missing fragment: {href}")

    # 4. Pedagogy gates: hard word ceiling (fail) + checkpoint report (warn),
    #    with the per-phase lesson plan printed so drift is visible.
    warnings: list[str] = []
    print("\nDerived lesson plan:")
    for plan in plans:
        print(f"  Phase {plan.phase_no}  {plan.out}: {len(plan.lessons)} "
              f"lessons · ~{plan.total_minutes} min")
        for lesson in plan.lessons:
            tag = "wrap-up" if lesson.is_wrapup else f"L{lesson.number}"
            print(f"    {tag:>7}  {lesson.words:5d}w  "
                  f"{lesson.checkpoints}cp  ~{lesson.minutes:2d} min  "
                  f"{lesson.title}")
            if lesson.words > LESSON_HARD:
                if lesson.is_wrapup:  # A1.6: the ritual is never split
                    print(f"    NOTE: wrap-up over {LESSON_HARD}w "
                          "(never split by rule A1.6)")
                else:
                    errors.append(f"CEILING: {lesson.out}: {lesson.words} "
                                  f"visible words > LESSON_HARD "
                                  f"{LESSON_HARD} after sub-split")
            if (lesson.number > 1 and not lesson.is_wrapup
                    and lesson.checkpoints == 0):
                warnings.append(f"{lesson.out} ({lesson.title}): no ▶ "
                                "checkpoint (bridge/design lesson? "
                                "seed item D3)")
    if warnings:
        print(f"\nWARNING: {len(warnings)} checkpoint-less content "
              "lesson(s) (non-failing; feeds the markdown-side worklist):")
        for w in warnings:
            print(f"  - {w}")
    if errors:
        print(f"\nverification battery FAILED ({len(errors)} error(s)):",
              file=sys.stderr)
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
    total = sum(len(p.lessons) for p in plans)
    print(f"\nverification battery passed: anchor parity OK, partition "
          f"complete OK, link integrity OK, word ceiling OK "
          f"({total} lessons across {len(plans)} phases)")


def main() -> None:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_HITS.clear()
    # Pass 1: convert every page once (lessons are sliced, never
    # re-converted), and derive each phase's lesson plan.
    converted = []
    plans: list[PhasePlan] = []
    for idx, (out_name, src_rel, _label, sec) in enumerate(PAGES):
        body, ctx, md = convert_page(src_rel)
        plan = None
        if sec == "Phases":
            phase_no = [o for o, _ in PHASE_PAGES].index(out_name)
            plan = PhasePlan(out_name, src_rel, phase_no, body, ctx, md)
            plans.append(plan)
        converted.append((out_name, src_rel, body, ctx, idx, plan))
    # Pass 2: write the full pages, then the lesson pages (cross-phase
    # Continue cards need every plan).
    written: dict[str, str] = {}
    for out_name, src_rel, body, ctx, idx, plan in converted:
        page = build_page(out_name, src_rel, body, ctx, idx, plan)
        (HTML_DIR / out_name).write_text(page, encoding="utf-8")
        written[out_name] = page
        print(f"wrote html/{out_name}  <- {src_rel}")
    for plan in plans:
        for lesson in plan.lessons:
            page = build_lesson_page(plan, lesson, plans)
            (HTML_DIR / lesson.out).write_text(page, encoding="utf-8")
            written[lesson.out] = page
        print(f"wrote html/{lesson_name(plan.out, 1)} … "
              f"html/{plan.lessons[-1].out}  ({len(plan.lessons)} lessons)")
    # Lesson boundaries are derived; a re-split can shrink the count — drop
    # any stale lesson page so html/ holds exactly this build's output.
    for path in sorted(HTML_DIR.glob("*.html")):
        if path.name not in written:
            path.unlink()
            print(f"removed stale html/{path.name}")
    # Drift gate: every figure in figures.FIGURES must have matched a fence.
    # An unmatched key means the markdown diagram changed (or moved) — fail
    # loudly so the SVG is redrawn or re-fingerprinted, never silently stale.
    unmatched = sorted(set(figures.FIGURES) - FIGURE_HITS)
    if unmatched:
        for key in unmatched:
            print(f"ERROR: figure {key[:12]}… "
                  f"({figures.FIGURES[key].title}) matched no text fence — "
                  "the markdown diagram changed; redraw the SVG in "
                  "site/figures.py or re-fingerprint it.", file=sys.stderr)
        raise SystemExit(1)
    (HTML_DIR / "style.css").write_text(build_css(), encoding="utf-8")
    print("wrote html/style.css")
    run_battery(written, plans)


if __name__ == "__main__":
    main()
