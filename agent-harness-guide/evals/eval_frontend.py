"""Frontend / design eval suite — the "$10k front-end designer" persona.

Deterministic, offline, stdlib-only checks that encode the engineering and
design standards prior front-end reviews established for the GENERATED HTML
site (``site/html/*.html`` — 17 full pages + 76 lesson pages = 93 — plus the
single global ``style.css``).

Three families of cases:

* **Per-page structural** (cheap, every one of the 93 pages): doctype, ``lang``,
  charset, viewport, title, description, canonical, Open Graph, favicon, the
  semantic landmark elements, a working skip link, unique ``id``s, and exactly
  one ``<h1>`` *on the pages that should carry one* (the first/standalone page of
  a phase; continuation lesson pages deliberately start at ``<h2>``).
* **style.css** (global): print stylesheet, the light ``:root`` token set, a dark
  ``prefers-color-scheme`` block, ``::selection``, ``:focus-visible``, the
  mono "label voice" rules, and the absence of leftover stock GitHub-blue /
  pygments-default code-theme hexes (the light code theme is the GitHub-Light
  token set).
* **Contrast** (WCAG 2.x ratios computed in pure Python from the hex tokens
  parsed out of ``style.css``): the documented foreground/background, muted,
  link/accent, on-accent, sidebar-current, hero-standfirst and selection pairs,
  in BOTH light and dark, plus the key pygments token classes on their code
  backgrounds — one case per (pair, scheme).

The site is a fixed artifact: these cases read it, they never regenerate it.
Parsing uses ``html.parser`` from the stdlib (html5lib is used opportunistically
if importable, but is never required).
"""
from __future__ import annotations

import glob
import os
import re
from html.parser import HTMLParser

from harness import SITE_HTML, Suite, read

SUITE = Suite("frontend")

CSS_PATH = os.path.join(SITE_HTML, "style.css")

# --- page inventory ------------------------------------------------------
ALL_PAGES = sorted(os.path.basename(p) for p in glob.glob(os.path.join(SITE_HTML, "*.html")))

# Full / standalone pages have no numeric "-N" lesson suffix; they each carry
# exactly one <h1>. Continuation lesson pages (-2, -3, ...) deliberately start
# at <h2> (they continue a phase split across pages) and so carry no <h1>; the
# FIRST lesson page of each phase (-1) does carry the phase <h1>.
_LESSON_SUFFIX = re.compile(r"-\d+\.html$")


def is_full_page(name: str) -> bool:
    return not _LESSON_SUFFIX.search(name)


def is_first_lesson(name: str) -> bool:
    return name.endswith("-1.html")


# Pages that must have exactly one <h1>: the 17 standalone pages + each phase's
# first lesson page. Everything else (continuation lesson pages) must have zero.
H1_PAGES = [p for p in ALL_PAGES if is_full_page(p) or is_first_lesson(p)]
NO_H1_PAGES = [p for p in ALL_PAGES if p not in set(H1_PAGES)]

# A representative sampled subset for the more detailed per-page checks: every
# full page (all 17) + a deterministic spread of lesson pages (every 7th).
_SAMPLE = list(dict.fromkeys(
    [p for p in ALL_PAGES if is_full_page(p)] + ALL_PAGES[::7]
))
SAMPLE_PAGES = sorted(_SAMPLE)


def slug(name: str) -> str:
    return name.replace(".html", "").replace("-", "_").replace(".", "_")


# --- HTML parsing --------------------------------------------------------
class _PageParser(HTMLParser):
    """Collect the structural facts each case needs, in one pass.

    Stdlib ``html.parser`` (html5lib used only if importable, below). We track
    start tags, ids, the skip link, anchor hrefs, <title> text, and a small set
    of <meta>/<link> facts keyed for quick lookup.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: dict[str, int] = {}
        self.ids: list[str] = []
        self.has_role_attr = False
        self.header_like = False  # <header> OR an element with role=banner
        self.skip_href: str | None = None
        self.in_page_hrefs: list[str] = []
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.has_lang = False
        self.charset: str | None = None
        self._in_title = False
        self._title_parts: list[str] = []
        self.title = ""

    def handle_starttag(self, tag, attrs):  # noqa: D401
        d = {k: (v or "") for k, v in attrs}
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if "id" in d:
            self.ids.append(d["id"])
        if "role" in d:
            self.has_role_attr = True
            if d.get("role") == "banner":
                self.header_like = True
        if tag == "header":
            self.header_like = True
        if tag == "html" and d.get("lang"):
            self.has_lang = True
        cls = d.get("class", "")
        if tag == "a" and "skip-link" in cls.split():
            self.skip_href = d.get("href")
        href = d.get("href", "")
        if tag == "a" and href.startswith("#"):
            self.in_page_hrefs.append(href[1:])
        if tag == "meta":
            if "charset" in d:
                self.charset = d["charset"]
            self.metas.append(d)
        if tag == "link":
            self.links.append(d)
        if tag == "title":
            self._in_title = True
            self._title_parts = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            self.title = "".join(self._title_parts).strip()

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)


_PAGE_CACHE: dict[str, _PageParser] = {}


def parse_page(name: str) -> _PageParser:
    if name not in _PAGE_CACHE:
        p = _PageParser()
        p.feed(read(os.path.join(SITE_HTML, name)))
        _PAGE_CACHE[name] = p
    return _PAGE_CACHE[name]


def raw(name: str) -> str:
    return read(os.path.join(SITE_HTML, name))


def meta_by(page: _PageParser, key: str, val: str) -> dict[str, str] | None:
    for m in page.metas:
        if m.get(key) == val:
            return m
    return None


# --- CSS token extraction ------------------------------------------------
CSS = read(CSS_PATH)


def _root_block(css: str) -> str:
    """The light :root {...} body (before any media query)."""
    m = re.search(r":root\s*\{(.*?)\}", css, re.DOTALL)
    return m.group(1) if m else ""


def _dark_root_block(css: str) -> str:
    """The :root {...} nested inside @media (prefers-color-scheme: dark)."""
    m = re.search(
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{(.*?)\}",
        css,
        re.DOTALL,
    )
    return m.group(1) if m else ""


def _tokens(block: str) -> dict[str, str]:
    """Map of --name -> #hex from a CSS block (hex-valued custom props only)."""
    out: dict[str, str] = {}
    for name, val in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block):
        hexes = re.findall(r"#[0-9A-Fa-f]{3,6}", val)
        if hexes:
            out[name] = hexes[0]
    return out


LIGHT = _tokens(_root_block(CSS))
DARK = _tokens(_dark_root_block(CSS))


# --- WCAG contrast (pure Python) -----------------------------------------
def _srgb_to_lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb_to_lin(r) + 0.7152 * _srgb_to_lin(g) + 0.0722 * _srgb_to_lin(b)


def contrast(fg: str, bg: str) -> float:
    la, lb = _luminance(fg), _luminance(bg)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ======================================================================
# Family 1 — per-page structural checks (cheap, all 93 pages)
# ======================================================================
def _check_doctype(name):
    def fn():
        ok = raw(name).lstrip().lower().startswith("<!doctype html>")
        return ok, f"{name}: missing/incorrect <!doctype html>"
    return fn


def _check_lang(name):
    def fn():
        return parse_page(name).has_lang, f"{name}: <html> missing lang attribute"
    return fn


def _check_charset(name):
    def fn():
        cs = parse_page(name).charset
        return bool(cs), f"{name}: missing <meta charset>"
    return fn


def _check_viewport(name):
    def fn():
        m = meta_by(parse_page(name), "name", "viewport")
        ok = bool(m and "width=device-width" in m.get("content", ""))
        return ok, f"{name}: missing/incomplete viewport meta"
    return fn


def _check_title(name):
    def fn():
        t = parse_page(name).title
        return bool(t.strip()), f"{name}: empty or missing <title>"
    return fn


def _check_description(name):
    def fn():
        m = meta_by(parse_page(name), "name", "description")
        ok = bool(m and m.get("content", "").strip())
        return ok, f"{name}: missing/empty <meta name=description>"
    return fn


def _check_canonical(name):
    def fn():
        page = parse_page(name)
        ok = any(l.get("rel") == "canonical" and l.get("href", "").strip()
                 for l in page.links)
        return ok, f"{name}: missing <link rel=canonical>"
    return fn


def _check_og_title(name):
    def fn():
        m = meta_by(parse_page(name), "property", "og:title")
        ok = bool(m and m.get("content", "").strip())
        return ok, f"{name}: missing og:title"
    return fn


def _check_og_type(name):
    def fn():
        m = meta_by(parse_page(name), "property", "og:type")
        ok = bool(m and m.get("content", "").strip())
        return ok, f"{name}: missing og:type"
    return fn


def _check_favicon(name):
    def fn():
        page = parse_page(name)
        ok = any("icon" in l.get("rel", "").split() and l.get("href", "").strip()
                 for l in page.links)
        return ok, f"{name}: missing favicon <link rel=icon>"
    return fn


def _check_landmark(name, tag):
    def fn():
        return parse_page(name).tags.get(tag, 0) >= 1, f"{name}: no <{tag}> landmark"
    return fn


def _check_header(name):
    def fn():
        p = parse_page(name)
        return p.header_like, f"{name}: no <header> nor role=banner"
    return fn


def _check_h1_one(name):
    def fn():
        n = parse_page(name).tags.get("h1", 0)
        return n == 1, f"{name}: expected exactly one <h1>, found {n}"
    return fn


def _check_h1_zero(name):
    def fn():
        n = parse_page(name).tags.get("h1", 0)
        return n == 0, f"{name}: continuation page should have no <h1>, found {n}"
    return fn


def _check_skip_link(name):
    def fn():
        p = parse_page(name)
        href = p.skip_href
        if not href or not href.startswith("#"):
            return False, f"{name}: no skip link with #fragment href"
        target = href[1:]
        ok = target in set(p.ids)
        return ok, f"{name}: skip-link target #{target} has no matching id"
    return fn


def _check_unique_ids(name):
    def fn():
        ids = parse_page(name).ids
        seen, dups = set(), set()
        for i in ids:
            if i in seen:
                dups.add(i)
            seen.add(i)
        return not dups, f"{name}: duplicate id(s): {sorted(dups)[:5]}"
    return fn


def _check_anchor_integrity(name):
    def fn():
        p = parse_page(name)
        ids = set(p.ids)
        # "#top" is a browser scroll-to-top convention (the back-to-top control),
        # which needs no element; all other in-page anchors must resolve.
        missing = sorted({h for h in p.in_page_hrefs if h and h != "top" and h not in ids})
        return not missing, f"{name}: in-page anchors with no target: {missing[:5]}"
    return fn


# register the cheap per-page family across ALL pages
for _name in ALL_PAGES:
    s = slug(_name)
    SUITE.add(f"page_{s}__doctype", _check_doctype(_name))
    SUITE.add(f"page_{s}__lang", _check_lang(_name))
    SUITE.add(f"page_{s}__charset", _check_charset(_name))
    SUITE.add(f"page_{s}__viewport", _check_viewport(_name))
    SUITE.add(f"page_{s}__title", _check_title(_name))
    SUITE.add(f"page_{s}__description", _check_description(_name))
    SUITE.add(f"page_{s}__canonical", _check_canonical(_name))
    SUITE.add(f"page_{s}__og_title", _check_og_title(_name))
    SUITE.add(f"page_{s}__og_type", _check_og_type(_name))
    SUITE.add(f"page_{s}__favicon", _check_favicon(_name))
    SUITE.add(f"page_{s}__nav", _check_landmark(_name, "nav"))
    SUITE.add(f"page_{s}__main", _check_landmark(_name, "main"))
    SUITE.add(f"page_{s}__header", _check_header(_name))
    SUITE.add(f"page_{s}__footer", _check_landmark(_name, "footer"))
    SUITE.add(f"page_{s}__skip_link", _check_skip_link(_name))
    SUITE.add(f"page_{s}__unique_ids", _check_unique_ids(_name))

# h1 expectations: one on standalone/first-lesson pages, zero on continuations
for _name in H1_PAGES:
    SUITE.add(f"page_{slug(_name)}__h1_one", _check_h1_one(_name))
for _name in NO_H1_PAGES:
    SUITE.add(f"page_{slug(_name)}__h1_zero", _check_h1_zero(_name))

# anchor integrity across the representative sample (the cross-page fan-out is
# heavier, so it runs on the sampled subset)
for _name in SAMPLE_PAGES:
    SUITE.add(f"anchors_{slug(_name)}", _check_anchor_integrity(_name))


# ======================================================================
# Family 2 — style.css global checks
# ======================================================================
def _css_contains(label, pattern, *, flags=0):
    def fn():
        ok = re.search(pattern, CSS, flags) is not None
        return ok, f"style.css: missing {label} (/{pattern}/)"
    return fn


SUITE.add("css__media_print", _css_contains("@media print block", r"@media\s+print\s*\{"))
SUITE.add("css__root_light", _css_contains("light :root token block", r":root\s*\{"))
SUITE.add(
    "css__dark_scheme",
    _css_contains(
        "dark prefers-color-scheme block",
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{",
    ),
)
SUITE.add("css__selection", _css_contains("::selection rule", r"::selection\s*\{"))
SUITE.add("css__focus_visible", _css_contains(":focus-visible rule", r":focus-visible"))


# light token set must be present and complete (the documented palette)
_REQUIRED_TOKENS = [
    "bg", "fg", "muted", "border", "border-strong", "accent", "accent-deep",
    "code-bg", "sidebar-bg", "green", "warn", "selection",
]
for _tok in _REQUIRED_TOKENS:
    def _mk(tok):
        def fn():
            return tok in LIGHT, f"style.css :root missing --{tok}"
        return fn
    SUITE.add(f"css_light_token__{_tok.replace('-', '_')}", _mk(_tok))

# dark block must redefine the scheme-dependent tokens
for _tok in ["bg", "fg", "muted", "accent", "accent-deep", "code-bg", "selection"]:
    def _mkd(tok):
        def fn():
            return tok in DARK, f"style.css dark :root missing --{tok}"
        return fn
    SUITE.add(f"css_dark_token__{_tok.replace('-', '_')}", _mkd(_tok))


# the light code theme must be the GitHub-Light token set, NOT pygments default:
# no leftover stock GitHub-blue / default code-theme hexes in the NON-pygments
# portion (everything before the "pygments: light" marker). We also assert the
# stock-blue link/keyword hexes are absent from the whole file (the theme is
# hand-tuned GitHub-Light, which doesn't use them).
_PYG_MARKER = re.search(r"/\*\s*pygments:\s*light", CSS)
_NON_PYG = CSS[: _PYG_MARKER.start()] if _PYG_MARKER else CSS

_FORBIDDEN = {
    "github_blue_0969da": r"#0969da",
    "github_blue_4493f8": r"#4493f8",
    "pure_blue_0000ff": r"#0000ff",
    "pure_blue_00f": r"#00f\b",
    "stock_green_008000": r"#008000",
}
for _key, _pat in _FORBIDDEN.items():
    def _mkf(key, pat):
        def fn():
            hits = re.findall(pat, _NON_PYG, re.IGNORECASE)
            return not hits, f"style.css (non-pygments) contains stock hex {pat} ({len(hits)}x)"
        return fn
    SUITE.add(f"css_no_stock_hex__{_key}", _mkf(_key, _pat))


# the pygments LIGHT theme must be GitHub-Light, not the default: the default
# light theme keywords are blue (#0000ff/#008000); GitHub-Light keywords are red
# (#cf222e). Assert the light pygments keyword color is the GitHub-Light value.
def _check_pyg_light_keyword():
    m = re.search(r"\.highlight\s+\.k\s*\{\s*color:\s*(#[0-9A-Fa-f]{3,6})", CSS)
    if not m:
        return False, "style.css: no light .highlight .k rule"
    val = m.group(1).lower()
    return val == "#cf222e", f"style.css: light pygments .k is {val}, expected GitHub-Light #CF222E"


SUITE.add("css_pyg_light__keyword_is_github_light", _check_pyg_light_keyword)


# the mono "label voice": uppercase eyebrow/kicker/th rules carry tracking
# (letter-spacing). Assert tracking is applied to <th> and to the mono kicker
# classes, and that the standard 0.08em label tracking appears.
def _check_label_voice_th():
    m = re.search(r"\bth\s*\{[^}]*\}", CSS, re.DOTALL)
    ok = bool(m and "letter-spacing" in m.group(0) and "text-transform: uppercase" in m.group(0))
    return ok, "style.css: <th> label-voice (uppercase + letter-spacing) missing"


def _check_label_voice_eyebrow():
    # .hero-eyebrow and .phase-kicker should both use letter-spacing tracking
    ok = True
    detail = []
    for cls in [".hero-eyebrow", ".phase-kicker"]:
        m = re.search(re.escape(cls) + r"\s*\{[^}]*\}", CSS, re.DOTALL)
        if not (m and "letter-spacing" in m.group(0)):
            ok = False
            detail.append(cls)
    return ok, f"style.css: kicker/eyebrow letter-spacing missing on {detail}"


def _check_label_voice_tracking_value():
    ok = "letter-spacing: 0.08em" in CSS
    return ok, "style.css: standard 0.08em label tracking not found"


SUITE.add("css_label_voice__th", _check_label_voice_th)
SUITE.add("css_label_voice__eyebrow_kicker", _check_label_voice_eyebrow)
SUITE.add("css_label_voice__tracking_value", _check_label_voice_tracking_value)


# ======================================================================
# Family 3 — contrast (WCAG ratios from parsed tokens), light + dark
# ======================================================================
WHITE = "#ffffff"
TEXT_BAR = 4.5   # AA normal text
UI_BAR = 3.0     # AA large text / UI components

# Each entry: (case-suffix, fg-getter, bg-getter, bar, justification)
# Getters pull from LIGHT/DARK token maps or use literal hexes documented in CSS.
LIGHT_HERO_STANDFIRST = "#444B5A"   # .hero blockquote color (light), doc 8.61:1
ONACCENT_LIGHT_TEXT = WHITE          # .btn-primary / skip-link color light
ONACCENT_DARK_TEXT = DARK.get("bg", "#0E1016")  # dark uses --bg as on-accent text


def _pair_case(fg, bg, bar, why):
    def fn():
        r = contrast(fg, bg)
        return r >= bar, f"{fg} on {bg} = {r:.2f}:1 < {bar}:1 ({why})"
    return fn


# ---- light scheme text pairs ----
_LIGHT_PAIRS = [
    ("body_fg_on_bg", LIGHT["fg"], LIGHT["bg"], TEXT_BAR, "body text"),
    ("muted_on_bg", LIGHT["muted"], LIGHT["bg"], TEXT_BAR, "muted text"),
    ("muted_on_codebg", LIGHT["muted"], LIGHT["code-bg"], TEXT_BAR, "muted on code bg"),
    ("muted_on_sidebar", LIGHT["muted"], LIGHT["sidebar-bg"], TEXT_BAR, "muted on sidebar"),
    ("accent_on_bg", LIGHT["accent"], LIGHT["bg"], TEXT_BAR, "link on bg"),
    ("accent_on_codebg", LIGHT["accent"], LIGHT["code-bg"], TEXT_BAR, "link on code bg"),
    ("accent_deep_on_bg", LIGHT["accent-deep"], LIGHT["bg"], TEXT_BAR, "hover/strong link"),
    ("white_on_accent", ONACCENT_LIGHT_TEXT, LIGHT["accent"], TEXT_BAR, "white text on accent button"),
    ("white_on_accent_deep", ONACCENT_LIGHT_TEXT, LIGHT["accent-deep"], TEXT_BAR, "white text on hover button"),
    ("hero_standfirst", LIGHT_HERO_STANDFIRST, LIGHT["bg"], TEXT_BAR, "hero standfirst"),
    ("selection_fg", LIGHT["fg"], LIGHT["selection"], TEXT_BAR, "fg on selection"),
    ("green_on_bg", LIGHT["green"], LIGHT["bg"], TEXT_BAR, "success text"),
    ("warn_on_bg", LIGHT["warn"], LIGHT["bg"], TEXT_BAR, "warning text"),
]
# sidebar current-row: accent-deep text on a 10% accent-on-bg tint. Compute the
# composited tint (10% accent over bg) the way color-mix(in srgb) does.


def _mix(top, bottom, alpha):
    """Composite `top` at `alpha` over `bottom` (color-mix in srgb)."""
    t = top.lstrip("#")
    b = bottom.lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(b) == 3:
        b = "".join(c * 2 for c in b)
    out = []
    for i in (0, 2, 4):
        tv = int(t[i:i + 2], 16)
        bv = int(b[i:i + 2], 16)
        out.append(round(tv * alpha + bv * (1 - alpha)))
    return "#%02x%02x%02x" % tuple(out)


_SIDEBAR_TINT_LIGHT = _mix(LIGHT["accent"], LIGHT["bg"], 0.10)
_LIGHT_PAIRS.append(
    ("sidebar_current_row", LIGHT["accent-deep"], _SIDEBAR_TINT_LIGHT, TEXT_BAR,
     "current sidebar row: accent-deep on 10% accent tint")
)

for _suffix, _fg, _bg, _bar, _why in _LIGHT_PAIRS:
    SUITE.add(f"contrast_light__{_suffix}", _pair_case(_fg, _bg, _bar, _why + " (light)"))


# ---- dark scheme text pairs ----
_DARK_HERO_STANDFIRST = DARK["muted"]   # dark .hero blockquote uses --muted
_DARK_PAIRS = [
    ("body_fg_on_bg", DARK["fg"], DARK["bg"], TEXT_BAR, "body text"),
    ("muted_on_bg", DARK["muted"], DARK["bg"], TEXT_BAR, "muted text"),
    ("muted_on_codebg", DARK["muted"], DARK["code-bg"], TEXT_BAR, "muted on code bg"),
    ("accent_on_bg", DARK["accent"], DARK["bg"], TEXT_BAR, "link on bg"),
    ("accent_on_codebg", DARK["accent"], DARK["code-bg"], TEXT_BAR, "link on code bg"),
    ("accent_deep_on_bg", DARK["accent-deep"], DARK["bg"], TEXT_BAR, "hover/strong link"),
    ("darktext_on_accent", ONACCENT_DARK_TEXT, DARK["accent"], TEXT_BAR, "dark text on accent button"),
    ("darktext_on_accent_deep", ONACCENT_DARK_TEXT, DARK["accent-deep"], TEXT_BAR, "dark text on hover button"),
    ("hero_standfirst", _DARK_HERO_STANDFIRST, DARK["bg"], TEXT_BAR, "hero standfirst"),
    ("selection_fg", DARK["fg"], DARK["selection"], TEXT_BAR, "fg on selection"),
    ("green_on_bg", DARK["green"], DARK["bg"], TEXT_BAR, "success text"),
    ("warn_on_bg", DARK["warn"], DARK["bg"], TEXT_BAR, "warning text"),
]
_SIDEBAR_TINT_DARK = _mix(DARK["accent"], DARK["bg"], 0.10)
_DARK_PAIRS.append(
    ("sidebar_current_row", DARK["accent-deep"], _SIDEBAR_TINT_DARK, TEXT_BAR,
     "current sidebar row: accent-deep on 10% accent tint")
)

for _suffix, _fg, _bg, _bar, _why in _DARK_PAIRS:
    SUITE.add(f"contrast_dark__{_suffix}", _pair_case(_fg, _bg, _bar, _why + " (dark)"))


# ---- pygments token contrast in both emitted code themes ----
# Light pygments theme renders on --code-bg (#F6F7FA); dark theme sets its own
# .highlight background (#0d1117). Sample the key token classes and assert each
# clears the text bar on its code background.
def _pyg_color(scheme_block: str, cls: str) -> str | None:
    m = re.search(r"\.highlight\s+\." + re.escape(cls) + r"\s*\{[^}]*?color:\s*(#[0-9A-Fa-f]{3,6})",
                  scheme_block)
    return m.group(1) if m else None


_PYG_LIGHT_BLOCK = CSS[_PYG_MARKER.start():] if _PYG_MARKER else CSS
_PYG_DARK_M = re.search(r"/\*\s*pygments:\s*dark", CSS)
_PYG_DARK_BLOCK = CSS[_PYG_DARK_M.start():] if _PYG_DARK_M else ""
# light theme block is between the light marker and the dark marker
if _PYG_MARKER and _PYG_DARK_M:
    _PYG_LIGHT_BLOCK = CSS[_PYG_MARKER.start():_PYG_DARK_M.start()]

LIGHT_CODE_BG = LIGHT["code-bg"]            # #F6F7FA
_dark_bg_m = re.search(r"\.highlight\s*\{[^}]*background:\s*(#[0-9A-Fa-f]{3,6})", _PYG_DARK_BLOCK)
DARK_CODE_BG = _dark_bg_m.group(1) if _dark_bg_m else DARK["code-bg"]

# key token classes: keyword, string, comment, number, name/function, builtin
_PYG_CLASSES = ["k", "s", "c", "mi", "nf", "nb", "nc", "s2", "kn", "ow"]


def _pyg_case(scheme, block, cls, bg):
    def fn():
        col = _pyg_color(block, cls)
        if col is None:
            return False, f"pygments {scheme}: no color for .{cls}"
        r = contrast(col, bg)
        return r >= TEXT_BAR, f"pygments {scheme} .{cls} {col} on {bg} = {r:.2f}:1 < {TEXT_BAR}:1"
    return fn


for _cls in _PYG_CLASSES:
    SUITE.add(f"pyg_contrast_light__{_cls}", _pyg_case("light", _PYG_LIGHT_BLOCK, _cls, LIGHT_CODE_BG))
    SUITE.add(f"pyg_contrast_dark__{_cls}", _pyg_case("dark", _PYG_DARK_BLOCK, _cls, DARK_CODE_BG))


if __name__ == "__main__":
    from harness import main
    main(SUITE)
