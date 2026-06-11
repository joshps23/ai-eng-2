#!/usr/bin/env bash
# refresh.sh — re-sync every jupytext pair and re-execute every notebook in place.
#
# When to run this: after editing ANY notebook's .py source (the review surface),
# run this script as the last step before committing. It (1) regenerates each
# .ipynb from its .py pair via `jupytext --sync`, then (2) executes the .ipynb
# headlessly with OPENAI_API_KEY forced empty, so the committed outputs are the
# deterministic FakeClient outputs that keyless readers reproduce exactly.
# Commit BOTH files of each pair afterwards.
#
# Requires the notebook extras: from agent-harness-guide/code,
#   pip install -e ".[dev,notebooks]"
#
# CI runs the same sync + execute steps (see .github/workflows/ci.yml, job
# "notebooks") and fails if a pair has drifted or a notebook can't execute.

set -euo pipefail
cd "$(dirname "$0")"

shopt -s nullglob
pairs=(*.py)
if [ ${#pairs[@]} -eq 0 ]; then
    echo "No notebook .py sources found in $(pwd) — nothing to refresh."
    exit 0
fi

for py in "${pairs[@]}"; do
    nb="${py%.py}.ipynb"
    echo "== syncing $py"
    jupytext --sync "$py"
    echo "== executing $nb (offline — key forced empty)"
    env OPENAI_API_KEY= jupyter execute --kernel_name=python3 --timeout=120 --inplace "$nb"
done

echo "All notebooks refreshed. Remember to commit both the .py and .ipynb files."
