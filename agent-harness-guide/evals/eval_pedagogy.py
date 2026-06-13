"""Deterministic eval suite for the "learning-science professor" persona.

Cycle 18 shipped the *bite-sized lesson* reading track: every numbered phase
page (`04-real-tools.html`) is also sliced into a chain of lesson pages
(`04-real-tools-1.html` … `04-real-tools-11.html`), where lesson 1 doubles as
the phase hub (it carries the generated lesson plan). This suite encodes that
pedagogy as machine-checkable cases over the *rendered* HTML the generator
emits — it never edits the generator or the HTML, it only reads it.

The contract (learned by reading `site/build_site.py` and the rendered pages):

* Each lesson page carries a position **kicker** (`.phase-kicker`) reading
  "Phase p · Lesson k of n" or "Phase p · Wrap-up"; a **time estimate**
  (`.lesson-time`, "~N min"); a **Continue card** (`.continue-card[rel=next]`)
  linking the next step; a **canonical** link pointing at the matching FULL
  page (the permanent address); and the phase rail (`.phase-rail`) plus a
  lesson rail (`.lesson-rail`).
* The headline pedagogy bar is **bite-size**: a lesson's visible article words
  (tags stripped, refsection `<details>` excluded — matching the generator's
  own budget) stays under LESSON_HARD (≈2400) with modest slack.
* Each phase hub (lesson 1) carries a `.lesson-plan` whose numbered `<li>`
  count equals the phase's lesson count, a single-page escape-hatch link, and
  a plan total time.
* **Anchor parity**: every id inside the full page's `<article>` appears in
  exactly one of that phase's lesson articles (deep links stay serveable, and
  no id is duplicated across lessons).
* **Partition completeness**: every `<h2 id>` on the full page surfaces on some
  lesson page (no section is dropped from the lesson track).
* **Continue-card chain**: following each lesson's next link visits every
  lesson of the phase in order and exits at the next phase's lesson 1 (or, for
  phase 8, onward to the appendix).
* **Counts**: 76 lesson pages total; ≥4 per phase; a "Wrap-up" lesson per phase.

Stdlib only, offline, deterministic. Regex over the rendered HTML (no browser:
the visible-word count is the deterministic height proxy).
"""
from __future__ import annotations

import glob
import html as html_mod
import os
import re

from harness import Suite, read, SITE_HTML

SUITE = Suite("pedagogy")

# --- contract constants (mirrored from site/build_site.py) ----------------
# build_site.py: LESSON_HARD = 2400 visible words (the build-failing ceiling).
# The generator counts words by stripping tags with "" (so a pygments-wrapped
# code token collapses to one word) and excluding refsection <details>. We
# reproduce that proxy here and allow ~5% slack over the hard ceiling.
LESSON_HARD = 2400
WORD_SLACK = 1.05
WORD_CEIL = int(LESSON_HARD * WORD_SLACK)  # 2520

PHASES = [
    "00-foundations", "01-bare-harness", "02-tool-system",
    "03-conversation-and-streaming", "04-real-tools",
    "05-permissions-and-safety", "06-context-management",
    "07-subagents-orchestration", "08-production-harness",
]
EXPECTED_TOTAL_LESSONS = 77
MIN_LESSONS_PER_PHASE = 4

TAG_RE = re.compile(r"<[^>]+>")
_ARTICLE_RE = re.compile(r"<article>(.*?)</article>", re.S)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S)
# Refsections are top-level <details class="refsection"> the generator excludes
# from the visible-word budget; strip them so our proxy matches the generator.
_REFSECTION_RE = re.compile(
    r'<details class="refsection"[^>]*>.*?</details>', re.S)
# A figure's collapsed ASCII mirror is excluded too (the reader sees the SVG);
# mirror the generator's Chunk.words DIAGRAM_TEXT_RE so the proxies stay aligned.
_DIAGRAM_TEXT_RE = re.compile(
    r'<details class="diagram-text">.*?</details>', re.S)
_ID_RE = re.compile(r'id="([^"]*)"')
_H2_ID_RE = re.compile(r'<h2 id="([^"]*)"')


# --- small filesystem / parsing helpers -----------------------------------
def _path(name: str) -> str:
    return os.path.join(SITE_HTML, name)


def _exists(name: str) -> bool:
    return os.path.isfile(_path(name))


def _html(name: str) -> str:
    return read(_path(name))


def _lesson_number(name: str) -> int:
    m = re.search(r"-(\d+)\.html$", name)
    return int(m.group(1)) if m else -1


def lesson_pages(phase: str) -> list[str]:
    """Ordered lesson-page filenames for a phase (lesson 1 = hub)."""
    files = [os.path.basename(p)
             for p in glob.glob(os.path.join(SITE_HTML, f"{phase}-*.html"))]
    # keep only the numeric `<phase>-<k>.html` slices (not e.g. a sibling phase)
    files = [f for f in files if re.fullmatch(rf"{re.escape(phase)}-\d+\.html", f)]
    return sorted(files, key=_lesson_number)


def article_html(html: str) -> str:
    m = _ARTICLE_RE.search(html)
    return m.group(1) if m else ""


def visible_words(article: str) -> int:
    """The generator's visible-word proxy: drop script/style and refsections,
    strip tags with "" (collapsing pygments code spans), unescape, count."""
    a = _SCRIPT_STYLE_RE.sub("", article)
    a = _REFSECTION_RE.sub("", a)
    a = _DIAGRAM_TEXT_RE.sub("", a)
    a = html_mod.unescape(TAG_RE.sub("", a))
    return len(a.split())


def article_ids(html: str) -> list[str]:
    return _ID_RE.findall(article_html(html))


def article_h2_ids(html: str) -> list[str]:
    return _H2_ID_RE.findall(article_html(html))


# Build the lesson roster once (deterministic, order-independent registration).
_ALL_LESSONS: list[tuple[str, str, int, int]] = []  # (phase, file, k, n)
for _ph in PHASES:
    _files = lesson_pages(_ph)
    _n = len(_files)
    for _f in _files:
        _ALL_LESSONS.append((_ph, _f, _lesson_number(_f), _n))


def _kicker(html: str) -> str | None:
    m = re.search(r'<span class="phase-kicker">([^<]*)</span>', html)
    return m.group(1) if m else None


def _continue_next(html: str) -> str | None:
    m = re.search(r'class="continue-card" href="([^"]*)" rel="next"', html)
    return m.group(1) if m else None


def _canonical(html: str) -> str | None:
    m = re.search(r'rel="canonical" href="([^"]*)"', html)
    return m.group(1) if m else None


# ==========================================================================
# Global gates
# ==========================================================================
@SUITE.case("count/total-lesson-pages-eq-76")
def _count_total():
    n = len(_ALL_LESSONS)
    return (n == EXPECTED_TOTAL_LESSONS,
            f"expected {EXPECTED_TOTAL_LESSONS} lesson pages, found {n}")


@SUITE.case("count/nine-phases-present")
def _count_phases():
    missing = [p for p in PHASES if not _exists(f"{p}.html")]
    return (not missing, f"missing full pages: {missing}")


# ==========================================================================
# Per-phase gates (9 phases × several checks)
# ==========================================================================
def _register_phase(phase: str) -> None:
    files = lesson_pages(phase)
    n = len(files)
    hub = files[0] if files else None
    wrap = files[-1] if files else None

    @SUITE.case(f"phase/{phase}/lesson-count-ge-{MIN_LESSONS_PER_PHASE}")
    def _min_count(n=n):
        return (n >= MIN_LESSONS_PER_PHASE,
                f"phase has {n} lessons, want >= {MIN_LESSONS_PER_PHASE}")

    @SUITE.case(f"phase/{phase}/wrapup-lesson-exists")
    def _wrapup(wrap=wrap, phase=phase):
        if wrap is None:
            return False, "no lesson pages"
        k = _kicker(_html(wrap))
        return ("Wrap-up" in (k or ""),
                f"last lesson {wrap} kicker={k!r} lacks 'Wrap-up'")

    # --- hub: lesson plan, item count, single-page hatch, total time -------
    @SUITE.case(f"phase/{phase}/hub-has-lesson-plan")
    def _hub_plan(hub=hub):
        return ('class="lesson-plan"' in _html(hub),
                f"hub {hub} missing .lesson-plan section")

    @SUITE.case(f"phase/{phase}/hub-plan-item-count-eq-{n}")
    def _hub_plan_items(hub=hub, n=n):
        html = _html(hub)
        m = re.search(r'<ol class="plan-list">(.*?)</ol>', html, re.S)
        if not m:
            return False, f"hub {hub} has no .plan-list"
        items = len(re.findall(r"<li", m.group(1)))
        return (items == n,
                f"plan-list has {items} <li>, expected {n} (one per lesson)")

    @SUITE.case(f"phase/{phase}/hub-single-page-escape-hatch")
    def _hub_hatch(hub=hub, phase=phase):
        html = _html(hub)
        ok = ('class="plan-single"' in html
              and f'href="{phase}.html"' in html
              and "Read this phase as a single page" in html)
        return (ok, f"hub {hub} missing single-page escape hatch link")

    @SUITE.case(f"phase/{phase}/hub-plan-total-time-present")
    def _hub_total(hub=hub):
        html = _html(hub)
        m = re.search(r'class="plan-total">([^<]*)</span>', html)
        ok = bool(m) and bool(re.search(r"~\d+\s*min", m.group(1) if m else ""))
        return (ok, f"hub {hub} plan total time missing/garbled: "
                    f"{m.group(1) if m else None!r}")

    # --- anchor parity -----------------------------------------------------
    @SUITE.case(f"phase/{phase}/anchor-parity-full-subset-of-lessons")
    def _anchor_subset(phase=phase, files=files):
        full_ids = set(article_ids(_html(f"{phase}.html")))
        union: set[str] = set()
        for f in files:
            union |= set(article_ids(_html(f)))
        missing = sorted(full_ids - union)
        return (not missing,
                f"full-page article ids absent from every lesson: {missing[:8]}"
                + (" …" if len(missing) > 8 else ""))

    @SUITE.case(f"phase/{phase}/anchor-parity-single-owner")
    def _anchor_owner(files=files):
        owners: dict[str, list[str]] = {}
        for f in files:
            for i in article_ids(_html(f)):
                owners.setdefault(i, []).append(f)
        dup = {i: v for i, v in owners.items() if len(set(v)) > 1}
        return (not dup,
                "ids owned by >1 lesson: "
                + ", ".join(f"{i}->{sorted(set(v))}" for i, v in
                            list(dup.items())[:5]))

    # --- partition completeness (every full-page h2 surfaces in a lesson) --
    @SUITE.case(f"phase/{phase}/partition-h2-coverage")
    def _partition(phase=phase, files=files):
        full_h2 = set(article_h2_ids(_html(f"{phase}.html")))
        union: set[str] = set()
        for f in files:
            union |= set(article_h2_ids(_html(f)))
        missing = sorted(full_h2 - union)
        return (not missing,
                f"full-page <h2 id> sections missing from lessons: "
                f"{missing[:8]}" + (" …" if len(missing) > 8 else ""))

    # --- continue-card chain integrity -------------------------------------
    @SUITE.case(f"phase/{phase}/continue-chain-visits-all-in-order")
    def _chain(phase=phase, files=files):
        expected = files[:]  # already ordered 1..n
        visited: list[str] = []
        seen: set[str] = set()
        cur = files[0] if files else None
        # walk the next-chain only while it stays inside this phase
        while (cur and re.fullmatch(rf"{re.escape(phase)}-\d+\.html", cur)
               and cur not in seen):
            if not _exists(cur):
                return False, f"chain hit missing page {cur}"
            seen.add(cur)
            visited.append(cur)
            cur = _continue_next(_html(cur))
        if visited != expected:
            return False, (f"chain visited {visited} != lessons {expected}")
        # after the last lesson, `cur` is the exit target; it must exist
        if cur is None or not _exists(cur):
            return False, f"wrap-up exits to missing/none page {cur!r}"
        return True, ""


for _ph in PHASES:
    _register_phase(_ph)


# ==========================================================================
# Per-lesson-page gates (76 pages × several checks)
# ==========================================================================
def _register_lesson(phase: str, fname: str, k: int, n: int) -> None:
    is_wrapup = (k == n)

    @SUITE.case(f"lesson/{fname}/kicker-position")
    def _kick(fname=fname, phase=phase, k=k, n=n, is_wrapup=is_wrapup):
        html = _html(fname)
        kick = _kicker(html)
        if kick is None:
            return False, f"{fname} has no .phase-kicker"
        p = int(phase[:2])
        if is_wrapup:
            want = f"Phase {p} · Wrap-up"
        else:
            want = f"Phase {p} · Lesson {k} of {n}"
        return (kick == want, f"kicker={kick!r}, expected {want!r}")

    @SUITE.case(f"lesson/{fname}/time-estimate")
    def _time(fname=fname):
        html = _html(fname)
        ok = bool(re.search(r'class="lesson-time">~\d+\s*min</span>', html))
        return (ok, f"{fname} missing .lesson-time '~N min' chip")

    @SUITE.case(f"lesson/{fname}/canonical-points-at-full-page")
    def _canon(fname=fname, phase=phase):
        html = _html(fname)
        canon = _canonical(html)
        ok = bool(canon) and canon.endswith(f"/{phase}.html")
        return (ok, f"{fname} canonical={canon!r}, expected to end "
                    f"with /{phase}.html")

    @SUITE.case(f"lesson/{fname}/phase-rail-present")
    def _prail(fname=fname):
        return ('class="phase-rail"' in _html(fname),
                f"{fname} missing .phase-rail")

    @SUITE.case(f"lesson/{fname}/lesson-rail-present")
    def _lrail(fname=fname):
        return ('class="lesson-rail"' in _html(fname),
                f"{fname} missing .lesson-rail")

    @SUITE.case(f"lesson/{fname}/continue-card-next-link")
    def _cont(fname=fname, phase=phase, k=k, n=n, is_wrapup=is_wrapup):
        html = _html(fname)
        nxt = _continue_next(html)
        if not nxt:
            return False, f"{fname} missing .continue-card[rel=next]"
        if not _exists(nxt):
            return False, f"{fname} Continue next -> missing page {nxt!r}"
        if not is_wrapup:
            # non-wrap-up lessons continue to the next lesson in this phase
            want = f"{phase}-{k + 1}.html"
            return (nxt == want, f"Continue next={nxt!r}, expected {want!r}")
        # wrap-up: must continue ONWARD, never back into this phase
        if re.fullmatch(rf"{re.escape(phase)}-\d+\.html", nxt):
            return False, f"wrap-up {fname} loops back into phase via {nxt!r}"
        return True, ""

    @SUITE.case(f"lesson/{fname}/bite-size-word-ceiling")
    def _bite(fname=fname):
        w = visible_words(article_html(_html(fname)))
        return (w <= WORD_CEIL,
                f"{fname} has {w} visible words > ceiling {WORD_CEIL} "
                f"(LESSON_HARD {LESSON_HARD} + slack)")


for _ph, _f, _k, _n in _ALL_LESSONS:
    _register_lesson(_ph, _f, _k, _n)


# --- wrap-up-specific exit-boundary cases (per phase) ---------------------
def _register_wrapup_boundary(phase: str, idx: int) -> None:
    files = lesson_pages(phase)
    wrap = files[-1]

    @SUITE.case(f"phase/{phase}/wrapup-continue-boundary")
    def _boundary(phase=phase, idx=idx, wrap=wrap):
        nxt = _continue_next(_html(wrap))
        if not nxt or not _exists(nxt):
            return False, f"wrap-up {wrap} exits to missing/none {nxt!r}"
        if idx < len(PHASES) - 1:
            # exits to the NEXT phase's lesson 1
            want = f"{PHASES[idx + 1]}-1.html"
            return (nxt == want,
                    f"wrap-up exits to {nxt!r}, expected next phase hub {want!r}")
        # the very last phase-8 wrap-up: must continue onward (out of phase),
        # not loop back; any existing onward page is acceptable.
        looped = bool(re.fullmatch(rf"{re.escape(phase)}-\d+\.html", nxt))
        return (not looped,
                f"final wrap-up {wrap} loops back via {nxt!r} instead of onward")


for _idx, _ph in enumerate(PHASES):
    _register_wrapup_boundary(_ph, _idx)


if __name__ == "__main__":
    from harness import main
    main(SUITE)
