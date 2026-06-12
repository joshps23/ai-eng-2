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
     [("hover", "div.highlight")]),
    ("phase01-code-dark", "01-bare-harness.html#-run-it-now", (1440, 900), "dark", False, []),
    ("phase04-toc-open-light", "04-real-tools.html", (1440, 900), "light", False,
     [("click", ".page-toc > summary")]),
    ("phase04-footer-light", "04-real-tools.html", (1440, 900), "light", False,
     [("scroll-bottom", None)]),
    ("phase01-mobile-light", "01-bare-harness.html", (390, 844), "light", False, []),
    ("learning-path-light", "learning-path.html", (1440, 900), "light", False, []),
    ("glossary-dark", "glossary.html", (1440, 900), "dark", False, []),
    ("phase01-print", "01-bare-harness.html", (1240, 1600), "light", False,
     [("media-print", None)]),
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
            page.wait_for_timeout(350)
            dest = os.path.join(args.out, f"{name}.png")
            page.screenshot(path=dest, full_page=full)
            print(f"captured {dest}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
