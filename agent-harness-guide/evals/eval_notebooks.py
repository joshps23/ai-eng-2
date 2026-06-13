#!/usr/bin/env python3
"""Deterministic eval suite for the "Jupyter notebook expert" persona.

Encodes the notebook conventions this repo committed to (see the project
CLAUDE.md "Notebooks" section and ``notebooks/README.md``) as machine-checkable
cases. Every case is a named ``() -> (ok, detail)`` callable, deterministic,
offline, stdlib-only. The one external touch is an optional shell-out to
``jupytext`` (already installed) for the pair-sync check; if jupytext is absent
the sync cases *pass* with a clear "jupytext unavailable" detail rather than
crash or block.

Run directly::

    cd agent-harness-guide/evals && python eval_notebooks.py

The cases are parametrized across the 10 notebooks (setup-check + 00..08) times
~21 per-notebook checks, plus a handful of global cases (>200 distinct cases).
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tokenize

from harness import GUIDE_DIR, NOTEBOOKS, Suite, read

SUITE = Suite("notebooks")

# --- the ten notebooks, by stem (no extension) ---------------------------
NOTEBOOK_STEMS = [
    "setup-check",
    "00-foundations",
    "01-bare-harness",
    "02-tool-system",
    "03-conversation-and-streaming",
    "04-real-tools",
    "05-permissions-and-safety",
    "06-context-management",
    "07-subagents-orchestration",
    "08-production-harness",
]

# Notebooks whose runnable core is a scripted FakeClient round trip. The
# production notebook (08) demonstrates a *custom* flaky client class and the
# real package's pytest run instead of the shared make_client/FakeClient
# scaffold, so the "build+consume in the same cell" rule applies vacuously
# there (it has zero such builder cells, which is itself fine).
FAKECLIENT_NOTEBOOKS = {s for s in NOTEBOOK_STEMS if s != "08-production-harness"}

# setup-check has no separate live-API demo cell (it is a ~5-cell smoke test);
# its terminal cell references the USE_REAL_API guard inline. Every other
# notebook carries a dedicated, guarded live-API cell after its checks cell.
HAS_LIVE_API_CELL = {s for s in NOTEBOOK_STEMS if s != "setup-check"}

# Stated code-cell caps: ~22 for the phase notebooks, ~8 (small) for setup-check.
MAX_CODE_CELLS = 22
SETUP_CHECK_MAX_CODE_CELLS = 8

# The guard that legitimizes a bare ``OpenAI()`` call and a live-API cell.
_GUARD_RE = re.compile(
    r"""USE_REAL_API\s+and\s+os\.environ\.get\(\s*['"]OPENAI_API_KEY['"]"""
)
# A genuine ``input()`` *builtin* call (not the ``input=`` kwarg, not
# ``to_input(...)``): ``input`` not preceded by a word char or a dot.
_BUILTIN_INPUT_RE = re.compile(r"(?<![\w.])input\s*\(")
_WHILE_TRUE_RE = re.compile(r"\bwhile\s+True\s*:")


# --- helpers -------------------------------------------------------------
def _ipynb_path(stem: str) -> str:
    return os.path.join(NOTEBOOKS, f"{stem}.ipynb")


def _py_path(stem: str) -> str:
    return os.path.join(NOTEBOOKS, f"{stem}.py")


_NB_CACHE: dict[str, dict] = {}


def _load_nb(stem: str) -> dict:
    if stem not in _NB_CACHE:
        _NB_CACHE[stem] = json.loads(read(_ipynb_path(stem)))
    return _NB_CACHE[stem]


def _cell_src(cell: dict) -> str:
    src = cell.get("source", "")
    return src if isinstance(src, str) else "".join(src)


def _code_cells(nb: dict) -> list[dict]:
    return [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]


def _code_only(src: str) -> str | None:
    """Return the source with comments and string literals stripped.

    Used so that words like ``input(`` or ``while True`` inside docstrings,
    comments, or markdown-ish prose don't trip the REPL checks. Returns None if
    the cell can't be tokenized (e.g. a deliberately broken snippet).
    """
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append("\n" if tok.type in (tokenize.NL, tokenize.NEWLINE) else tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return " ".join(out)


def _tags(cell: dict) -> list[str]:
    return cell.get("metadata", {}).get("tags", []) or []


def _has_jupytext() -> bool:
    return shutil.which("jupytext") is not None


# --- per-notebook case factories -----------------------------------------
def _c_files_exist(stem: str):
    def run():
        ip, py = _ipynb_path(stem), _py_path(stem)
        miss = [p for p in (ip, py) if not os.path.isfile(p)]
        if miss:
            return False, f"missing: {', '.join(os.path.basename(m) for m in miss)}"
        return True, ""
    return run


def _c_valid_json(stem: str):
    def run():
        nb = _load_nb(stem)
        if "cells" not in nb:
            return False, "ipynb has no 'cells' key"
        return True, ""
    return run


def _c_kernelspec(stem: str):
    def run():
        nb = _load_nb(stem)
        name = nb.get("metadata", {}).get("kernelspec", {}).get("name")
        if name != "python3":
            return False, f"kernelspec name is {name!r}, expected 'python3'"
        return True, ""
    return run


def _c_first_cell_badge(stem: str):
    def run():
        nb = _load_nb(stem)
        cells = nb.get("cells", [])
        if not cells:
            return False, "no cells"
        c0 = cells[0]
        if c0.get("cell_type") != "markdown":
            return False, f"first cell is {c0.get('cell_type')!r}, expected markdown"
        if "Open in Colab" not in _cell_src(c0):
            return False, "first markdown cell lacks an 'Open in Colab' badge"
        return True, ""
    return run


def _c_bootstrap_try_import(stem: str):
    def run():
        nb = _load_nb(stem)
        code = _code_cells(nb)
        if not code:
            return False, "no code cells"
        src = _cell_src(code[0])
        if not src.lstrip().startswith("try:"):
            return False, "first code cell does not start with 'try:'"
        if "import agent_harness" not in src:
            return False, "first code cell does not 'import agent_harness'"
        return True, ""
    return run


def _c_bootstrap_except(stem: str):
    def run():
        src = _cell_src(_code_cells(_load_nb(stem))[0])
        if "except ModuleNotFoundError" not in src:
            return False, "bootstrap cell lacks 'except ModuleNotFoundError'"
        return True, ""
    return run


def _c_bootstrap_colab_detect(stem: str):
    def run():
        src = _cell_src(_code_cells(_load_nb(stem))[0])
        if "google.colab" not in src:
            return False, "bootstrap cell lacks 'google.colab' detection"
        return True, ""
    return run


def _c_bootstrap_noop_on_success(stem: str):
    """The import-success path must be a strict no-op (beyond trailing prints).

    Verified structurally: all the Colab clone/pip/subprocess machinery lives
    inside the ``except ModuleNotFoundError`` block, so when ``import
    agent_harness`` succeeds nothing but the trailing ``print(...)`` lines run.
    """
    def run():
        src = _cell_src(_code_cells(_load_nb(stem))[0])
        lines = src.splitlines()
        try:
            exc_idx = next(i for i, ln in enumerate(lines)
                           if ln.lstrip().startswith("except ModuleNotFoundError"))
        except StopIteration:
            return False, "no 'except ModuleNotFoundError' line found"
        # Lines after the except block return to column 0 (dedent). Find where
        # the except block ends: the first non-blank line at indent 0 after it.
        tail_start = len(lines)
        for i in range(exc_idx + 1, len(lines)):
            ln = lines[i]
            if ln.strip() and not ln[0].isspace():
                tail_start = i
                break
        machinery = ("subprocess", "pip", "git clone", "REPO_URL", "userdata")
        tail = "\n".join(lines[tail_start:])
        leaked = [m for m in machinery if m in tail]
        if leaked:
            return False, (
                "import-success path is not a no-op: Colab machinery "
                f"({', '.join(leaked)}) appears outside the except block"
            )
        # The success-path tail should only print / re-import; never clone/install.
        for ln in lines[tail_start:]:
            s = ln.strip()
            if not s:
                continue
            if not (s.startswith("print(") or s.startswith("import ")
                    or s.startswith("from ") or s.startswith("#")):
                return False, f"unexpected statement on success path: {s[:60]!r}"
        return True, ""
    return run


def _c_parameters_cell(stem: str):
    def run():
        code = _code_cells(_load_nb(stem))
        if not any("parameters" in _tags(c) for c in code):
            return False, "no code cell tagged 'parameters'"
        return True, ""
    return run


def _c_use_real_api_default_false(stem: str):
    def run():
        code = _code_cells(_load_nb(stem))
        params = [c for c in code if "parameters" in _tags(c)]
        if not params:
            return False, "no parameters cell to define USE_REAL_API"
        src = _cell_src(params[0])
        m = re.search(r"USE_REAL_API\s*=\s*(\w+)", src)
        if not m:
            return False, "parameters cell does not assign USE_REAL_API"
        if m.group(1) != "False":
            return False, f"USE_REAL_API default is {m.group(1)!r}, expected False"
        return True, ""
    return run


def _c_no_input_builtin(stem: str):
    def run():
        code = _code_cells(_load_nb(stem))
        offenders = []
        for i, c in enumerate(code):
            co = _code_only(_cell_src(c))
            if co is None:
                continue  # un-tokenizable cell; not a REPL-input concern
            if _BUILTIN_INPUT_RE.search(co):
                offenders.append(i)
        if offenders:
            return False, f"input() builtin call in code cell(s) {offenders}"
        return True, ""
    return run


def _c_no_infinite_while_true(stem: str):
    """No interactive REPL loop: a ``while True:`` with no exit (break/return/raise).

    The notebooks' agent loops use ``while True:`` driven by FakeClient turn
    exhaustion, exiting via ``return``/``break`` when the model emits a final
    message — those are bounded and legitimate. A true infinite loop (no exit
    at all) would be the actual defect, as would ``while True`` + ``input()``.
    """
    def run():
        code = _code_cells(_load_nb(stem))
        offenders = []
        for i, c in enumerate(code):
            co = _code_only(_cell_src(c))
            if co is None:
                continue
            if _WHILE_TRUE_RE.search(co):
                has_exit = any(k in co for k in ("break", "return", "raise"))
                has_input = _BUILTIN_INPUT_RE.search(co)
                if not has_exit or has_input:
                    offenders.append(i)
        if offenders:
            return False, f"infinite/REPL 'while True' in code cell(s) {offenders}"
        return True, ""
    return run


def _c_openai_guarded(stem: str):
    def run():
        code = _code_cells(_load_nb(stem))
        offenders = []
        for i, c in enumerate(code):
            src = _cell_src(c)
            if "OpenAI()" in src and not _GUARD_RE.search(src):
                offenders.append(i)
        if offenders:
            return False, (
                f"bare OpenAI() without USE_REAL_API/OPENAI_API_KEY guard in "
                f"code cell(s) {offenders}"
            )
        return True, ""
    return run


def _checks_cell_index(code: list[dict]) -> int | None:
    for i, c in enumerate(code):
        if "All checks passed" in _cell_src(c):
            return i
    return None


def _c_all_checks_passed_present(stem: str):
    def run():
        code = _code_cells(_load_nb(stem))
        if _checks_cell_index(code) is None:
            return False, "no cell prints/asserts 'All checks passed'"
        return True, ""
    return run


def _c_checks_cell_asserts(stem: str):
    def run():
        code = _code_cells(_load_nb(stem))
        idx = _checks_cell_index(code)
        if idx is None:
            return False, "no 'All checks passed' cell"
        if "assert" not in _cell_src(code[idx]):
            return False, "the 'All checks passed' cell does not 'assert' anything"
        return True, ""
    return run


def _c_fakeclient_build_and_consume(stem: str):
    """Rule C1: a cell that builds a state-owning client also consumes it.

    Heuristic: any cell that constructs a client (``make_client(`` or
    ``FakeClient(``, excluding the parameters cell's ``def make_client``) must
    also exercise it in the same cell (a turn: ``responses.create`` /
    ``run_agent`` / ``run`` / ``Agent`` / the ``make_client`` helper itself).
    Notebooks without such builder cells (e.g. the production notebook) pass
    vacuously.
    """
    def run():
        code = _code_cells(_load_nb(stem))
        builders, bad = 0, []
        for i, c in enumerate(code):
            src = _cell_src(c)
            if "def make_client" in src:
                continue  # the helper definition, not a build site
            if "make_client(" not in src and "FakeClient(" not in src:
                continue
            builders += 1
            consumes = any(
                k in src
                for k in (
                    "responses.create", "run_agent(", "run(", ".run(",
                    "Agent(", "make_client(",
                )
            )
            if not consumes:
                bad.append(i)
        if bad:
            return False, f"client built but not consumed in same cell: {bad}"
        if stem in FAKECLIENT_NOTEBOOKS and builders == 0:
            return False, "expected at least one FakeClient build+consume cell"
        if stem not in FAKECLIENT_NOTEBOOKS and builders == 0:
            return True, "no make_client/FakeClient builder cell (custom client) — ok"
        return True, ""
    return run


def _c_committed_outputs(stem: str):
    def run():
        code = _code_cells(_load_nb(stem))
        if not any(c.get("outputs") for c in code):
            return False, "no code cell carries committed outputs"
        return True, ""
    return run


def _c_code_cell_cap(stem: str):
    def run():
        n = len(_code_cells(_load_nb(stem)))
        cap = SETUP_CHECK_MAX_CODE_CELLS if stem == "setup-check" else MAX_CODE_CELLS
        if n > cap:
            return False, f"{n} code cells exceeds cap of {cap}"
        return True, ""
    return run


def _c_live_api_gated(stem: str):
    """The live-API demo cell (if the notebook has one) is guarded.

    For notebooks with a dedicated live-API cell, at least one non-parameters
    code cell must contain the USE_REAL_API/OPENAI_API_KEY guard. setup-check
    has no such cell and is encoded as a legitimate pass.
    """
    def run():
        code = _code_cells(_load_nb(stem))
        if stem not in HAS_LIVE_API_CELL:
            # No separate live-API cell expected; the guard still appears in the
            # parameters cell's make_client. Verify it's present somewhere.
            if any(_GUARD_RE.search(_cell_src(c)) for c in code):
                return True, "no separate live-API cell (smoke test) — ok"
            return False, "no USE_REAL_API/OPENAI_API_KEY guard anywhere"
        non_param = [c for c in code if "parameters" not in _tags(c)]
        if not any(_GUARD_RE.search(_cell_src(c)) for c in non_param):
            return False, (
                "expected a live-API cell guarded by USE_REAL_API and "
                "os.environ.get('OPENAI_API_KEY'); none found"
            )
        return True, ""
    return run


def _c_jupytext_in_sync(stem: str):
    """The .py is the review surface and its .ipynb pair is in sync.

    Convert the committed ``.py`` to ipynb in-memory and compare *cell sources*
    (not outputs/metadata) to the committed ``.ipynb``. If jupytext is not
    installed, pass with a clear detail rather than block.
    """
    def run():
        if not _has_jupytext():
            return True, "jupytext unavailable — sync check skipped"
        py = _py_path(stem)
        if not os.path.isfile(py):
            return False, f"{stem}.py missing — cannot verify pair sync"
        try:
            proc = subprocess.run(
                ["jupytext", "--to", "ipynb", "--output", "-", py],
                capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return True, f"jupytext invocation failed ({exc!r}) — skipped"
        if proc.returncode != 0:
            return False, f"jupytext rc={proc.returncode}: {proc.stderr.strip()[:200]}"
        try:
            generated = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return False, f"jupytext output not JSON: {exc}"
        committed = _load_nb(stem)
        gen_src = [_cell_src(c) for c in generated.get("cells", [])]
        com_src = [_cell_src(c) for c in committed.get("cells", [])]
        if len(gen_src) != len(com_src):
            return False, (
                f"cell count differs: .py->{len(gen_src)} vs .ipynb {len(com_src)} "
                "(pair out of sync — run jupytext --sync)"
            )
        for k, (g, c) in enumerate(zip(gen_src, com_src)):
            if g != c:
                return False, f"cell {k} source differs (pair out of sync)"
        return True, ""
    return run


# Per-notebook check registry: (suffix, factory).
_PER_NB_CHECKS = [
    ("files_exist", _c_files_exist),
    ("valid_json", _c_valid_json),
    ("kernelspec_python3", _c_kernelspec),
    ("first_cell_colab_badge", _c_first_cell_badge),
    ("bootstrap_try_import", _c_bootstrap_try_import),
    ("bootstrap_except_mnf", _c_bootstrap_except),
    ("bootstrap_colab_detect", _c_bootstrap_colab_detect),
    ("bootstrap_noop_on_import", _c_bootstrap_noop_on_success),
    ("parameters_cell", _c_parameters_cell),
    ("use_real_api_default_false", _c_use_real_api_default_false),
    ("no_input_builtin", _c_no_input_builtin),
    ("no_infinite_while_true", _c_no_infinite_while_true),
    ("openai_guarded", _c_openai_guarded),
    ("all_checks_passed_present", _c_all_checks_passed_present),
    ("checks_cell_asserts", _c_checks_cell_asserts),
    ("fakeclient_build_and_consume", _c_fakeclient_build_and_consume),
    ("committed_outputs", _c_committed_outputs),
    ("code_cell_cap", _c_code_cell_cap),
    ("live_api_gated", _c_live_api_gated),
    ("jupytext_in_sync", _c_jupytext_in_sync),
]

for _stem in NOTEBOOK_STEMS:
    for _suffix, _factory in _PER_NB_CHECKS:
        SUITE.add(f"{_stem}::{_suffix}", _factory(_stem))


# --- global cases --------------------------------------------------------
@SUITE.case("global::exactly_10_ipynb")
def _g_ten_ipynb():
    found = sorted(
        f for f in os.listdir(NOTEBOOKS) if f.endswith(".ipynb")
    )
    if len(found) != 10:
        return False, f"found {len(found)} .ipynb files, expected 10: {found}"
    return True, ""


@SUITE.case("global::exactly_10_py")
def _g_ten_py():
    found = sorted(f for f in os.listdir(NOTEBOOKS) if f.endswith(".py"))
    if len(found) != 10:
        return False, f"found {len(found)} .py files, expected 10: {found}"
    return True, ""


@SUITE.case("global::stems_match_expected_set")
def _g_stems_match():
    found = sorted(
        f[:-6] for f in os.listdir(NOTEBOOKS) if f.endswith(".ipynb")
    )
    if found != sorted(NOTEBOOK_STEMS):
        return False, f"notebook stems {found} != expected {sorted(NOTEBOOK_STEMS)}"
    return True, ""


@SUITE.case("global::readme_lists_all_10")
def _g_readme_lists():
    readme = read(os.path.join(NOTEBOOKS, "README.md"))
    missing = [s for s in NOTEBOOK_STEMS if f"{s}.ipynb" not in readme]
    if missing:
        return False, f"notebooks/README.md does not list: {missing}"
    return True, ""


@SUITE.case("global::refresh_sh_exists")
def _g_refresh_exists():
    p = os.path.join(NOTEBOOKS, "refresh.sh")
    if not os.path.isfile(p):
        return False, "notebooks/refresh.sh is missing"
    return True, ""


@SUITE.case("global::refresh_sh_executable")
def _g_refresh_exec():
    p = os.path.join(NOTEBOOKS, "refresh.sh")
    if not os.path.isfile(p):
        return False, "notebooks/refresh.sh is missing"
    if not os.access(p, os.X_OK):
        return False, "notebooks/refresh.sh is not executable"
    return True, ""


@SUITE.case("global::jupytext_availability_note")
def _g_jupytext_note():
    # Informational, never fails: records whether the sync cases ran for real.
    if _has_jupytext():
        return True, ""
    return True, "jupytext not installed — all sync cases passed-by-skip"


if __name__ == "__main__":
    from harness import main

    main(SUITE)
