#!/usr/bin/env python3
"""Run every persona eval suite. Exits non-zero if any case fails.

Usage:
    python run_all.py            # all suites
    python run_all.py beginner   # one or more named suites

Each suite lives in eval_<name>.py and exposes `SUITE` (a harness.Suite).
"""
from __future__ import annotations

import importlib
import sys

from harness import Suite, run_suites

SUITE_MODULES = {
    "beginner": "eval_beginner",
    "ux": "eval_ux",
    "notebooks": "eval_notebooks",
    "frontend": "eval_frontend",
    "pedagogy": "eval_pedagogy",
}


def load(names: list[str]) -> list[Suite]:
    suites = []
    for name in names:
        mod = importlib.import_module(SUITE_MODULES[name])
        suites.append(mod.SUITE)
    return suites


def main() -> None:
    wanted = sys.argv[1:] or list(SUITE_MODULES)
    unknown = [w for w in wanted if w not in SUITE_MODULES]
    if unknown:
        raise SystemExit(f"unknown suite(s): {', '.join(unknown)}")
    print(f"Running persona evals: {', '.join(wanted)}\n")
    fails = run_suites(load(wanted))
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
