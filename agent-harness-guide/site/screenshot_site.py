#!/usr/bin/env python3
"""Render the generated site in a real browser and capture review screenshots.

Used by the dev loop's visual-verification phase (and handy for manual review).
Requires: pip install playwright, plus a Chromium executable — either
`python -m playwright install chromium` or pass --chrome /path/to/chrome.

Usage:
    python screenshot_site.py [--out DIR] [--chrome PATH]

Serves site/html/ over a local HTTP server (so JS like the mobile sidebar
collapse behaves as deployed) and captures the key surfaces at desktop and
mobile widths, in light and dark schemes, plus a print emulation.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "html")
PORT = 8731

SHOTS = [
    # name, path, viewport, color_scheme, full_page, actions
    ("index-desktop-light", "index.html", (1440, 900), "light", True, []),
    ("index-desktop-dark", "index.html", (1440, 900), "dark", True, []),
    ("index-mobile-light", "index.html", (390, 844), "light", True, []),
    ("phase01-top-light", "01-bare-harness.html", (1440, 900), "light", False, []),
    ("phase01-top-dark", "01-bare-harness.html", (1440, 900), "dark", False, []),
    ("phase01-code-light", "01-bare-harness.html#-run-it-now", (1440, 900), "light", False,
     [("hover", "div.highlight:not(.nocopy)")]),
    ("phase01-code-dark", "01-bare-harness.html#-run-it-now", (1440, 900), "dark", False, []),
    ("phase04-toc-open-light", "04-real-tools.html", (1440, 900), "light", False,
     [("click", ".page-toc > summary")]),
    ("phase04-footer-light", "04-real-tools.html", (1440, 900), "light", False,
     [("scroll-bottom", None)]),
    ("phase01-mobile-light", "01-bare-harness.html", (390, 844), "light", False, []),
    ("learning-path-light", "learning-path.html", (1440, 900), "light", False,
     [("scroll", "table")]),
    ("glossary-dark", "glossary.html", (1440, 900), "dark", False, []),
    ("phase01-print", "01-bare-harness.html", (1240, 1600), "light", False,
     [("media-print", None), ("open-details", None), ("scroll", "div.highlight")]),
    # phase wayfinding chrome: medallion + 0-8 rail + version-ladder map
    ("phase00-chrome-light", "00-foundations.html", (1440, 900), "light", False, []),
    ("phase00-chrome-dark", "00-foundations.html", (1440, 900), "dark", False, []),
    # build-time SVG figure (Figure 1, the agent loop), both schemes
    ("figure1-light", "00-foundations.html", (1440, 900), "light", False,
     [("scroll", "figure.diagram")]),
    ("figure1-dark", "00-foundations.html", (1440, 900), "dark", False,
     [("scroll", "figure.diagram")]),
    # the six concept figures (ROADMAP item 9), each scrolled to via the SVG's
    # aria-labelledby title id, in both colour schemes (12 shots).
    ("fig-handshake-light", "00-foundations.html", (1440, 900), "light", False,
     [("scroll", 'svg[aria-labelledby="fig-hand-title"]')]),
    ("fig-handshake-dark", "00-foundations.html", (1440, 900), "dark", False,
     [("scroll", 'svg[aria-labelledby="fig-hand-title"]')]),
    ("fig-dispatch-light", "02-tool-system.html", (1440, 900), "light", False,
     [("scroll", 'svg[aria-labelledby="fig-disp-title"]')]),
    ("fig-dispatch-dark", "02-tool-system.html", (1440, 900), "dark", False,
     [("scroll", 'svg[aria-labelledby="fig-disp-title"]')]),
    ("fig-memory-light", "03-conversation-and-streaming.html", (1440, 900), "light", False,
     [("scroll", 'svg[aria-labelledby="fig-mem-title"]')]),
    ("fig-memory-dark", "03-conversation-and-streaming.html", (1440, 900), "dark", False,
     [("scroll", 'svg[aria-labelledby="fig-mem-title"]')]),
    ("fig-permissions-light", "05-permissions-and-safety.html", (1440, 900), "light", False,
     [("scroll", 'svg[aria-labelledby="fig-perm-title"]')]),
    ("fig-permissions-dark", "05-permissions-and-safety.html", (1440, 900), "dark", False,
     [("scroll", 'svg[aria-labelledby="fig-perm-title"]')]),
    ("fig-pruning-light", "06-context-management.html", (1440, 900), "light", False,
     [("scroll", 'svg[aria-labelledby="fig-prune-title"]')]),
    ("fig-pruning-dark", "06-context-management.html", (1440, 900), "dark", False,
     [("scroll", 'svg[aria-labelledby="fig-prune-title"]')]),
    ("fig-architecture-light", "08-production-harness.html", (1440, 900), "light", False,
     [("scroll", 'svg[aria-labelledby="fig-arch-title"]')]),
    ("fig-architecture-dark", "08-production-harness.html", (1440, 900), "dark", False,
     [("scroll", 'svg[aria-labelledby="fig-arch-title"]')]),
    # a collapsed "Reference copy" card in Phase 4 ...
    ("phase04-refsection-closed-light", "04-real-tools.html", (1440, 900), "light", False,
     [("scroll", "details.refsection")]),
    # ... and the same region landed-on via a deep link (auto-expanded)
    ("phase04-refsection-deeplink-light",
     "04-real-tools.html#bash-production-form--shell-command-execution",
     (1440, 900), "light", False, [("wait", 800)]),
    # lesson view: the phase hub (lesson 1) with the generated lesson plan
    ("hub04-plan-desktop-light", "04-real-tools-1.html", (1440, 900), "light", False,
     [("scroll", ".lesson-plan")]),
    ("hub04-plan-desktop-dark", "04-real-tools-1.html", (1440, 900), "dark", False,
     [("scroll", ".lesson-plan")]),
    ("hub04-plan-mobile-light", "04-real-tools-1.html", (390, 844), "light", False,
     [("scroll", ".lesson-plan")]),
    ("hub04-plan-mobile-dark", "04-real-tools-1.html", (390, 844), "dark", False,
     [("scroll", ".lesson-plan")]),
    # a mid-phase lesson top: kicker + time chip + phase rail + lesson rail
    ("lesson04-5-top-light", "04-real-tools-5.html", (1440, 900), "light", False, []),
    ("lesson04-5-top-dark", "04-real-tools-5.html", (1440, 900), "dark", False, []),
    # the lesson rail at phone width (must hold ≤2 rows with 12 lessons)
    ("lesson04-5-rail-mobile-light", "04-real-tools-5.html", (390, 844), "light", False, []),
    # the Continue card at the bottom of a lesson, desktop and phone
    ("lesson04-5-continue-light", "04-real-tools-5.html", (1440, 900), "light", False,
     [("scroll-bottom", None)]),
    ("lesson04-5-continue-dark", "04-real-tools-5.html", (1440, 900), "dark", False,
     [("scroll-bottom", None)]),
    ("lesson04-5-continue-mobile-light", "04-real-tools-5.html", (390, 844), "light", False,
     [("scroll-bottom", None)]),
]


def serve() -> threading.Thread:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=SITE)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/site-shots")
    ap.add_argument("--chrome", default=None,
                    help="Chromium executable (default: playwright-managed)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    from playwright.sync_api import sync_playwright

    serve()
    with sync_playwright() as p:
        launch = {}
        if args.chrome:
            launch["executable_path"] = args.chrome
        browser = p.chromium.launch(**launch)
        for name, path, (w, h), scheme, full, actions in SHOTS:
            ctx = browser.new_context(
                viewport={"width": w, "height": h}, color_scheme=scheme)
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{PORT}/{path}")
            page.wait_for_load_state("networkidle")
            for kind, sel in actions:
                if kind == "click":
                    with contextlib.suppress(Exception):
                        page.click(sel)
                elif kind == "hover":
                    with contextlib.suppress(Exception):
                        page.hover(sel)
                elif kind == "scroll-bottom":
                    # instant jump (smooth-scroll animation leaves unpainted
                    # tiles in headless screenshots)
                    page.evaluate(
                        "document.querySelector('.page-footer')"
                        ".scrollIntoView({behavior: 'instant', block: 'end'})")
                elif kind == "media-print":
                    page.emulate_media(media="print")
                elif kind == "open-details":
                    # print *emulation* doesn't fire beforeprint; open manually
                    page.evaluate(
                        "document.querySelectorAll('article details')"
                        ".forEach(d => d.setAttribute('open', ''))")
                elif kind == "wait":
                    page.wait_for_timeout(sel)
                elif kind == "scroll":
                    page.evaluate(
                        "sel => document.querySelector(sel)"
                        ".scrollIntoView({behavior: 'instant', block: 'center'})",
                        sel)
            page.wait_for_timeout(350)
            dest = os.path.join(args.out, f"{name}.png")
            page.screenshot(path=dest, full_page=full)
            print(f"captured {dest}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
