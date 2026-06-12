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

SITE_DIR = Path(__file__).resolve().parent
GUIDE_DIR = SITE_DIR.parent
HTML_DIR = SITE_DIR / "html"
GITHUB_BLOB = "https://github.com/joshps23/ai-eng-2/blob/main/agent-harness-guide/"

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
        html = highlight_block("\n".join(code), "text", "highlight nocopy")
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
                if tag in ("h2", "h3"):
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
                    if new.startswith("../"):
                        # points out of site/html/ into the repo checkout
                        cls = (el.get("class", "") + " repo-file").strip()
                        el.set("class", cls)
                        el.set("title", "Opens a file in the repository "
                                        "checkout — not part of this site")
                        self.ctx.repo_links += 1
                    elif (new.startswith(GITHUB_BLOB)
                            and new.partition("#")[0].endswith(".ipynb")):
                        cls = (el.get("class", "") + " repo-file").strip()
                        el.set("class", cls)
                        el.set("title", "Opens the notebook on GitHub "
                                        "(requires repo access) — or use its "
                                        "Open-in-Colab badge")
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
        self._wrap_tables(root)

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
        self.repo_links = 0                   # links that leave the site


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
    if resolved.endswith(".ipynb"):
        # raw .ipynb is unreadable JSON in a checkout — send it to GitHub's
        # rendered view instead (same base URL as the source links)
        return GITHUB_BLOB + resolved + sep + frag
    # not converted: point back into the repo checkout (html/ is 2 deep)
    return posixpath.normpath(posixpath.join("../..", resolved)) + (
        "/" if resolved.endswith("/") else "") + sep + frag


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
PAGE_JS = """\
(function () {
  /* On narrow screens the stacked sidebar would push content below the
     fold on every load — start it collapsed there. */
  if (matchMedia('(max-width: 800px)').matches) {
    var sb = document.querySelector('.sidebar-wrap');
    if (sb) { sb.removeAttribute('open'); }
  }

  /* Print: open every <details> (answers, TOC) and revert afterwards. */
  var openedForPrint = [];
  window.addEventListener('beforeprint', function () {
    openedForPrint = [];
    document.querySelectorAll('details:not([open])').forEach(function (d) {
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


def build_sidebar(current: str) -> str:
    parts = []
    for section in NAV_SECTIONS:
        items = []
        for out, _src, label, sec in PAGES:
            if sec != section:
                continue
            cls = ' class="current"' if out == current else ""
            aria = ' aria-current="page"' if out == current else ""
            items.append(f'<li{cls}><a href="{out}"{aria}>{esc(label)}</a></li>')
        parts.append(
            f'<p class="sidebar-heading">{esc(section)}</p>\n<ul>\n'
            + "\n".join(items) + "\n</ul>")
    return "\n".join(parts)


def toc_suffix(text: str) -> str:
    """Short disambiguation suffix for a TOC checkpoint: the parent heading's
    leading identifier — the text before the first ' — ' or ':' (e.g.
    'Step 2.4 — Add write_file' -> 'Step 2.4')."""
    cut = len(text)
    for sep in (" — ", ":"):
        pos = text.find(sep)
        if pos != -1:
            cut = min(cut, pos)
    return text[:cut].strip() or text


def build_toc(toc: list[tuple[int, str, str]]) -> str:
    """Nested page TOC: h3 entries group under their h2 in a sub-<ul>, and
    duplicate h3 texts (the repeated '▶ Run it now' checkpoints) are suffixed
    with the leading identifier of the nearest preceding non-checkpoint
    heading (any level) so they are distinguishable.  Heading ids are not
    touched — only the visible labels."""
    if not toc:
        return ""
    counts: dict[str, int] = {}
    for _level, text, _slug in toc:
        counts[text] = counts.get(text, 0) + 1
    parts = ["<ul>"]
    nearest = None      # nearest preceding non-checkpoint heading text
    open_h2 = False     # an h2-level <li> is open
    open_sub = False    # a nested <ul> is open inside it
    for level, text, slug in toc:
        label = text
        if level == 3 and nearest and counts[text] > 1:
            label = f"{text} — {toc_suffix(nearest)}"
        if counts[text] == 1:
            nearest = text
        link = f'<a href="#{slug}">{esc(label)}</a>'
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


def build_page(out_name: str, src_rel: str, body: str, ctx: PageContext,
               idx: int) -> str:
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

    repo_note = (" Links marked ↗ open repository files and need a full"
                 " checkout (or GitHub)." if ctx.repo_links else "")

    return f"""<!DOCTYPE html>
<!-- GENERATED from {src_rel} — do not edit; run site/build_site.py -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{esc(desc)}">
<title>{esc(title)}</title>
<link rel="stylesheet" href="style.css">
<link rel="icon" href="data:,">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<div class="layout">
<details class="sidebar-wrap" open>
<summary class="sidebar-toggle">Guide navigation</summary>
<nav class="sidebar" aria-label="Guide pages">
{build_sidebar(out_name)}
</nav>
</details>
<main id="main">
<header class="page-header">
<p class="source-link"><a class="repo-file" href="{GITHUB_BLOB}{src_rel}" title="Requires access to the repository">View the markdown source on GitHub</a></p>
{build_toc(ctx.toc)}
</header>
<article>
{body}
</article>
<footer class="page-footer">
<nav class="prevnext" aria-label="Previous and next page">
{prev_link}
{next_link}
</nav>
<p class="generated-note">Generated from <code>{esc(src_rel)}</code> — the markdown is the source of truth.{repo_note}</p>
</footer>
<a class="back-to-top" href="#top" aria-label="Back to top">↑ Top</a>
</main>
</div>
<script>
{PAGE_JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CSS (handwritten + deterministic pygments defs)
# ---------------------------------------------------------------------------
BASE_CSS = """\
/* GENERATED by site/build_site.py — do not edit. */
:root {
  color-scheme: light dark;
  --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --border: #d1d9e0;
  --accent: #0969da; --code-bg: #f6f8fa; --sidebar-bg: #f6f8fa;
  --warn: #9a6700; --warn-border: #d4a72c; --green: #1a7f37;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --border: #3d444d;
    --accent: #4493f8; --code-bg: #161b22; --sidebar-bg: #161b22;
    --warn: #d29922; --warn-border: #9e6a03; --green: #3fb950;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial,
    sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
  line-height: 1.6;
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
  cursor: pointer; padding: 0.75rem 1rem; font-weight: 600;
  list-style: none; display: block;
}
.sidebar-toggle::-webkit-details-marker { display: none; }
.sidebar { padding: 0 1rem 1rem; }
.sidebar .sidebar-heading {
  font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); margin: 1.25em 0 0.25em;
}
.sidebar ul { list-style: none; margin: 0; padding: 0; }
.sidebar li { margin: 0; }
.sidebar a {
  display: block; padding: 0.2em 0.5em; border-radius: 6px;
  color: var(--fg); text-decoration: none; font-size: 0.875rem;
}
.sidebar a:hover { background: var(--border); }
.sidebar li.current > a { background: var(--accent); color: #fff; }
main { flex: 1; min-width: 0; padding: 1.5rem 2rem 3rem; max-width: 80ch; }
article { max-width: 75ch; }
@media (max-width: 800px) {
  .layout { flex-direction: column; }
  .sidebar-wrap { position: static; flex: none; width: 100%; max-height: none;
    border-right: none; border-bottom: 1px solid var(--border); }
  main { padding: 1rem; }
  /* keep the fixed back-to-top control clear of the next-phase link */
  .page-footer { padding-bottom: 3.5rem; }
}
h1, h2, h3, h4 { line-height: 1.25; scroll-margin-top: 0.5em; }
.hanchor {
  margin-left: 0.35em; font-size: 0.85em; text-decoration: none;
  color: var(--muted); opacity: 0;
}
h2:hover > .hanchor, h3:hover > .hanchor, .hanchor:focus,
.hanchor:focus-visible { opacity: 1; }
h1 { font-size: 1.8rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }
h2 { font-size: 1.4rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; margin-top: 1.6em; }
h3 { font-size: 1.15rem; margin-top: 1.4em; }
a { color: var(--accent); }
hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
.table-wrap { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; }
th, td { border: 1px solid var(--border); padding: 0.4em 0.8em; }
th { background: var(--code-bg); }
tr:nth-child(2n) td { background: var(--code-bg); }
code, pre, kbd {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
    "Liberation Mono", monospace;
  font-size: 0.875em;
}
code { background: var(--code-bg); padding: 0.15em 0.35em; border-radius: 4px; }
pre { line-height: 1.45; }
pre code { background: none; padding: 0; font-size: 1em; }
div.highlight {
  position: relative; background: var(--code-bg);
  border: 1px solid var(--border); border-radius: 6px; margin: 1em 0;
}
div.highlight pre { margin: 0; padding: 0.85em 1em; overflow-x: auto; }
.copy-btn {
  position: absolute; top: 0.4em; right: 0.4em; padding: 0.15em 0.6em;
  font-size: 0.75rem; cursor: pointer; border: 1px solid var(--border);
  border-radius: 6px; background: var(--bg); color: var(--fg); opacity: 0.7;
}
.copy-btn:hover, .copy-btn:focus-visible { opacity: 1; }
blockquote {
  margin: 1em 0; padding: 0.1em 1em; color: var(--muted);
  border-left: 4px solid var(--border);
}
blockquote.beginner {
  border-left-color: var(--green);
  background: color-mix(in srgb, var(--green) 6%, transparent);
  color: var(--fg);
}
blockquote.refcopy {
  border-left: 4px solid var(--muted);
  background: color-mix(in srgb, var(--muted) 8%, transparent);
  color: var(--fg);
}
blockquote.refcopy > p:first-child::before { content: "🔖 "; }
.admonition {
  margin: 1em 0; padding: 0.1em 1em; border-left: 4px solid var(--warn-border);
  background: color-mix(in srgb, var(--warn-border) 8%, transparent);
}
.admonition-title { font-weight: 700; color: var(--warn); }
.admonition-title::before { content: "⚠ "; }
.admonition.note, .admonition.tip, .admonition.important {
  border-left-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.admonition.note .admonition-title, .admonition.tip .admonition-title,
.admonition.important .admonition-title { color: var(--accent); }
.admonition.note .admonition-title::before, .admonition.tip .admonition-title::before,
.admonition.important .admonition-title::before { content: "ℹ "; }
details { margin: 1em 0; }
details > summary { cursor: pointer; font-weight: 600; }
article details:not(.page-toc) {
  border: 1px solid var(--border); border-radius: 6px; padding: 0.5em 1em;
}
.page-toc {
  background: var(--code-bg); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.5em 1em; font-size: 0.9rem;
}
.page-toc ul { list-style: none; padding-left: 0; margin: 0.5em 0; }
.page-toc ul ul { padding-left: 1.5em; margin: 0; }
.page-toc a { text-decoration: none; }
ul.contains-task-list { list-style: none; padding-left: 1em; }
.task-list-item input { margin-right: 0.5em; }
.source-link { font-size: 0.85rem; margin: 0 0 0.5em; }
.page-footer { margin-top: 3em; border-top: 1px solid var(--border); padding-top: 1em; }
.prevnext { display: flex; justify-content: space-between; gap: 1em; }
.prevnext a { text-decoration: none; font-weight: 600; }
.prevnext .next { margin-left: auto; }
.generated-note { color: var(--muted); font-size: 0.8rem; }
a.repo-file::after { content: " ↗"; font-size: 0.85em; }
.back-to-top {
  position: fixed; right: 1rem; bottom: 1rem; z-index: 5;
  background: var(--code-bg); color: var(--fg);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 0.35em 0.7em; font-size: 0.8rem; text-decoration: none;
  opacity: 0.85;
}
.back-to-top:hover, .back-to-top:focus-visible { opacity: 1; }
/* JS adds/removes this near the top of the page; with JS disabled the
   class is never applied and the control stays visible. */
.back-to-top.btt-hidden { visibility: hidden; opacity: 0; pointer-events: none; }
@media (prefers-color-scheme: dark) {
  /* white-on-accent is 3.1:1 in the dark palette; the page bg is 6.7:1 */
  .skip-link, .sidebar li.current > a { color: var(--bg); }
}
@media print {
  .sidebar-wrap, .skip-link, .copy-btn, .page-header, .prevnext,
  .back-to-top, .hanchor { display: none !important; }
  div.highlight pre { white-space: pre-wrap; overflow-x: visible; }
  .table-wrap { overflow-x: visible; }
  th, td { word-break: break-word; }
}
"""


def build_css() -> str:
    light = HtmlFormatter(style="default").get_style_defs(".highlight")
    dark = HtmlFormatter(style="github-dark").get_style_defs(".highlight")
    return (
        BASE_CSS
        + "\n/* pygments: light */\n" + light
        + "\n/* pygments: dark */\n@media (prefers-color-scheme: dark) {\n"
        + "\n".join("  " + line for line in dark.splitlines())
        + "\n}\n"
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def convert_page(src_rel: str) -> tuple[str, PageContext]:
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
    return body, ctx


def main() -> None:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    for idx, (out_name, src_rel, _label, _sec) in enumerate(PAGES):
        body, ctx = convert_page(src_rel)
        page = build_page(out_name, src_rel, body, ctx, idx)
        (HTML_DIR / out_name).write_text(page, encoding="utf-8")
        print(f"wrote html/{out_name}  <- {src_rel}")
    (HTML_DIR / "style.css").write_text(build_css(), encoding="utf-8")
    print("wrote html/style.css")


if __name__ == "__main__":
    main()
