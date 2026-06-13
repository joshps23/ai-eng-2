"""Shared, dependency-free harness for the persona eval suites.

The dev loop's verification phase used to be role-played persona reviews; this
turns each persona's standards into a deterministic, offline, machine-checkable
suite. Stdlib only (matching the repo's no-extra-deps culture). Each
`eval_<persona>.py` builds a `Suite` of independently-named cases; `run_all.py`
runs every suite and exits non-zero if any case fails.

A *case* is a named callable returning `(ok: bool, detail: str)`. Cases must be
deterministic and order-independent. Parametrize liberally — one assertion per
(artifact, check) pair — so the suite is exhaustive and every failure points at
exactly one thing.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

# --- canonical paths (all suites import these) ---------------------------
GUIDE_DIR = os.path.dirname(os.path.abspath(__file__)).rsplit(os.sep, 1)[0]
REPO_DIR = GUIDE_DIR.rsplit(os.sep, 1)[0]
SITE_HTML = os.path.join(GUIDE_DIR, "site", "html")
SITE_DIR = os.path.join(GUIDE_DIR, "site")
NOTEBOOKS = os.path.join(GUIDE_DIR, "notebooks")
CODE_DIR = os.path.join(GUIDE_DIR, "code")

# the nine numbered phase files, in order
PHASES = [
    "00-foundations.md", "01-bare-harness.md", "02-tool-system.md",
    "03-conversation-and-streaming.md", "04-real-tools.md",
    "05-permissions-and-safety.md", "06-context-management.md",
    "07-subagents-orchestration.md", "08-production-harness.md",
]
APPENDIX = "09-library-reference.md"
SUPPORT_DOCS = ["README.md", "LEARNING-PATH.md", "BEGINNER-NOTES.md",
                "GLOSSARY.md", "FAQ.md", "EXERCISES.md"]


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@dataclass
class Result:
    suite: str
    case_id: str
    ok: bool
    detail: str = ""


class Suite:
    """A named collection of eval cases."""

    def __init__(self, name: str):
        self.name = name
        self._cases: list[tuple[str, object]] = []
        self._seen: set[str] = set()

    def add(self, case_id: str, fn) -> None:
        """Register one case. `fn()` returns (ok, detail)."""
        if case_id in self._seen:
            raise ValueError(f"{self.name}: duplicate case id {case_id!r}")
        self._seen.add(case_id)
        self._cases.append((case_id, fn))

    def case(self, case_id: str):
        def deco(fn):
            self.add(case_id, fn)
            return fn
        return deco

    def __len__(self) -> int:
        return len(self._cases)

    def run(self) -> list[Result]:
        out: list[Result] = []
        for cid, fn in self._cases:
            try:
                ok, detail = fn()
            except Exception as exc:  # a throwing case is a failing case
                ok, detail = False, f"exception: {type(exc).__name__}: {exc}"
            out.append(Result(self.name, cid, bool(ok), "" if ok else str(detail)))
        return out


def run_suites(suites: list[Suite], *, verbose: bool = False) -> int:
    """Run suites, print a report, return the number of failures."""
    t0 = time.time()
    total = fails = 0
    failed: list[Result] = []
    for s in suites:
        results = s.run()
        s_fail = [r for r in results if not r.ok]
        total += len(results)
        fails += len(s_fail)
        failed.extend(s_fail)
        status = "PASS" if not s_fail else f"FAIL ({len(s_fail)})"
        print(f"  {s.name:<14} {len(results):>4} cases  {status}")
    if failed:
        print("\nFailures:")
        for r in failed:
            print(f"  [{r.suite}] {r.case_id}: {r.detail}")
    dt = time.time() - t0
    print(f"\n{total} cases, {total - fails} passed, {fails} failed  ({dt:.1f}s)")
    return fails


def main(suite: Suite) -> None:
    """Entry point for running a single suite module directly."""
    raise SystemExit(1 if run_suites([suite]) else 0)
