"""Build-time SVG figures for the guide's ASCII diagrams.

The markdown is the SOURCE OF TRUTH: a figure here only ever *replaces the
rendering* of an ASCII diagram that exists in a phase file as a plain-text
fence.  Matching is by content fingerprint — the sha256 of the normalized
fence text — so the moment the markdown diagram changes, the fingerprint
stops matching, the build fails loudly (see the drift gate in
build_site.main()), and the maintainer either redraws the SVG or
re-fingerprints.  Nothing regresses silently.

Every stroke and fill goes through the `.d-*` CSS classes defined in
build_site.BASE_CSS, so the figures pick up the light/dark palette for free.
The original ASCII stays on the page inside a collapsed
<details class="diagram-text"> as the copyable, screen-reader-traversable,
markdown-faithful mirror.
"""

from __future__ import annotations

import hashlib
from typing import NamedTuple


class Figure(NamedTuple):
    svg: str          # complete inline <svg> markup (role="img" + <title>)
    title: str        # short build-log / maintainer-facing name
    alt_summary: str  # the full prose alternative (also the svg <title> text)


def normalize(text: str) -> str:
    """Whitespace-insensitive view of a fence: strip blank edges, rstrip
    every line.  Indentation and box-drawing content still matter."""
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _markers(prefix: str) -> str:
    """Arrowhead markers, one neutral and one accent ('hot'), per figure —
    ids are prefixed so two figures could share a page without colliding."""
    head = 'M0 0 L10 5 L0 10 z'
    attrs = ('viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" '
             'markerHeight="7" orient="auto-start-reverse"')
    return (
        f'<defs>\n'
        f'<marker id="{prefix}-arrow" {attrs}>'
        f'<path class="d-arrow" d="{head}"/></marker>\n'
        f'<marker id="{prefix}-arrow-hot" {attrs}>'
        f'<path class="d-arrow-hot" d="{head}"/></marker>\n'
        f'</defs>'
    )


# ---------------------------------------------------------------------------
# Figure 1 — the agent loop (00-foundations §0.2)
# ---------------------------------------------------------------------------
_LOOP_ALT = (
    "The agent loop: send the conversation to the model; if it asks for "
    "tools, execute them, append outputs, and send again; when it answers "
    "in text, return it."
)

_LOOP_SVG = f"""\
<svg viewBox="0 0 560 300" role="img" aria-labelledby="fig-loop-title">
<title id="fig-loop-title">{_LOOP_ALT}</title>
{_markers("fig-loop")}
<path class="d-edge-hot" d="M430 40 L430 14 L140 14 L140 37" marker-end="url(#fig-loop-arrow-hot)"/>
<line class="d-edge" x1="240" y1="80" x2="327" y2="80" marker-end="url(#fig-loop-arrow)"/>
<line class="d-edge" x1="140" y1="104" x2="140" y2="197" marker-end="url(#fig-loop-arrow)"/>
<rect class="d-box d-accent" x="40" y="40" width="200" height="64"/>
<rect class="d-box" x="330" y="40" width="200" height="64"/>
<rect class="d-box d-good" x="70" y="200" width="140" height="52"/>
<text class="d-label" x="140" y="62" text-anchor="middle">Send conversation</text>
<text class="d-label" x="140" y="78" text-anchor="middle">to the model</text>
<text class="d-mono" x="140" y="95" text-anchor="middle">responses.create()</text>
<text class="d-label" x="430" y="60" text-anchor="middle">Execute tools,</text>
<text class="d-label" x="430" y="76" text-anchor="middle">append outputs to</text>
<text class="d-label" x="430" y="92" text-anchor="middle">the conversation</text>
<text class="d-mono" x="284" y="60" text-anchor="middle">wants to</text>
<text class="d-mono" x="284" y="73" text-anchor="middle">call tools</text>
<text class="d-mono" x="148" y="155" text-anchor="start">produced final text</text>
<text class="d-label" x="140" y="231" text-anchor="middle">Return answer</text>
</svg>"""


# ---------------------------------------------------------------------------
# Figure 2 — one iteration of the bare loop (01-bare-harness §2)
# ---------------------------------------------------------------------------
_ITER_ALT = (
    "One loop iteration: input_items goes to responses.create; message "
    "items print and end the turn; function_call items are dispatched, "
    "their outputs appended to input_items, and the loop calls the model "
    "again."
)

_ITER_SVG = f"""\
<svg viewBox="0 0 560 380" role="img" aria-labelledby="fig-iter-title">
<title id="fig-iter-title">{_ITER_ALT}</title>
{_markers("fig-iter")}
<path class="d-edge-hot" d="M520 332 L545 332 L545 34 L385 34" marker-end="url(#fig-iter-arrow-hot)"/>
<line class="d-edge" x1="280" y1="52" x2="280" y2="83" marker-end="url(#fig-iter-arrow)"/>
<line class="d-edge" x1="280" y1="130" x2="280" y2="161" marker-end="url(#fig-iter-arrow)"/>
<path class="d-edge" d="M210 208 L141 257" marker-end="url(#fig-iter-arrow)"/>
<path class="d-edge" d="M350 208 L424 246" marker-end="url(#fig-iter-arrow)"/>
<line class="d-edge" x1="430" y1="290" x2="430" y2="309" marker-end="url(#fig-iter-arrow)"/>
<rect class="d-box d-accent d-pill" x="180" y="16" width="200" height="36"/>
<rect class="d-box" x="180" y="86" width="200" height="44"/>
<rect class="d-box" x="180" y="164" width="200" height="44"/>
<rect class="d-box d-good" x="60" y="260" width="150" height="56"/>
<rect class="d-box" x="340" y="250" width="180" height="40"/>
<rect class="d-box" x="340" y="312" width="180" height="40"/>
<text class="d-mono-label" x="280" y="38" text-anchor="middle">input_items</text>
<text class="d-mono" x="172" y="38" text-anchor="end">grows each iteration</text>
<text class="d-mono-label" x="280" y="112" text-anchor="middle">responses.create()</text>
<text class="d-mono-label" x="280" y="190" text-anchor="middle">resp.output items</text>
<text class="d-mono" x="168" y="226" text-anchor="end">message</text>
<text class="d-mono" x="388" y="222" text-anchor="start">function_call</text>
<text class="d-label" x="135" y="292" text-anchor="middle">print &amp; break</text>
<text class="d-mono-label" x="430" y="274" text-anchor="middle">dispatch() → str</text>
<text class="d-mono-label" x="430" y="329" text-anchor="middle">append</text>
<text class="d-mono-label" x="430" y="344" text-anchor="middle">function_call_output</text>
<text class="d-mono" x="538" y="144" text-anchor="end">input_items += resp.output</text>
<text class="d-mono" x="538" y="158" text-anchor="end">input_items += [call_outputs]</text>
</svg>"""


# ---------------------------------------------------------------------------
# Figure 3 — orchestrator and workers (07-subagents §1.4)
# ---------------------------------------------------------------------------
_ORCH_ALT = (
    "Orchestrator-worker fan-out: the orchestrator plans the work and "
    "spawns workers via task(); each worker runs with its own transcript "
    "and its own tools; their results — summary, diff, findings — fan back "
    "in to the orchestrator, which synthesises the final answer."
)

_ORCH_SVG = f"""\
<svg viewBox="0 0 640 420" role="img" aria-labelledby="fig-orch-title">
<title id="fig-orch-title">{_ORCH_ALT}</title>
{_markers("fig-orch")}
<path class="d-edge" d="M260 84 L126 125" marker-end="url(#fig-orch-arrow)"/>
<line class="d-edge" x1="320" y1="84" x2="320" y2="125" marker-end="url(#fig-orch-arrow)"/>
<path class="d-edge" d="M380 84 L514 125" marker-end="url(#fig-orch-arrow)"/>
<path class="d-edge" d="M125 230 L249 325" marker-end="url(#fig-orch-arrow)"/>
<line class="d-edge" x1="320" y1="230" x2="320" y2="325" marker-end="url(#fig-orch-arrow)"/>
<path class="d-edge" d="M515 230 L391 325" marker-end="url(#fig-orch-arrow)"/>
<rect class="d-box d-accent" x="190" y="20" width="260" height="64"/>
<rect class="d-box" x="40" y="130" width="170" height="100"/>
<rect class="d-box" x="235" y="130" width="170" height="100"/>
<rect class="d-box" x="430" y="130" width="170" height="100"/>
<rect class="d-box d-accent" x="190" y="330" width="260" height="60"/>
<text class="d-label" x="320" y="48" text-anchor="middle">ORCHESTRATOR</text>
<text class="d-mono" x="320" y="66" text-anchor="middle">plans the work, spawns workers</text>
<text class="d-mono" x="194" y="102" text-anchor="end">task()</text>
<text class="d-mono" x="328" y="108" text-anchor="start">task()</text>
<text class="d-mono" x="446" y="102" text-anchor="start">task()</text>
<text class="d-label" x="125" y="154" text-anchor="middle">Worker A</text>
<rect class="d-chip d-chip-accent" x="69" y="164" width="112" height="18"/>
<text class="d-chip-text d-chip-text-accent" x="125" y="177" text-anchor="middle">role=researcher</text>
<text class="d-mono" x="125" y="202" text-anchor="middle">own transcript</text>
<text class="d-mono" x="125" y="218" text-anchor="middle">own tools</text>
<text class="d-label" x="320" y="154" text-anchor="middle">Worker B</text>
<rect class="d-chip d-chip-green" x="280" y="164" width="80" height="18"/>
<text class="d-chip-text d-chip-text-green" x="320" y="177" text-anchor="middle">role=coder</text>
<text class="d-mono" x="320" y="202" text-anchor="middle">own transcript</text>
<text class="d-mono" x="320" y="218" text-anchor="middle">own tools</text>
<text class="d-label" x="515" y="154" text-anchor="middle">Worker C</text>
<rect class="d-chip d-chip-warn" x="465" y="164" width="100" height="18"/>
<text class="d-chip-text d-chip-text-warn" x="515" y="177" text-anchor="middle">role=reviewer</text>
<text class="d-mono" x="515" y="202" text-anchor="middle">own transcript</text>
<text class="d-mono" x="515" y="218" text-anchor="middle">own tools</text>
<text class="d-mono" x="177" y="274" text-anchor="end">summary</text>
<text class="d-mono" x="328" y="278" text-anchor="start">diff</text>
<text class="d-mono" x="463" y="274" text-anchor="start">findings</text>
<text class="d-label" x="320" y="354" text-anchor="middle">ORCHESTRATOR synthesises</text>
<text class="d-label" x="320" y="372" text-anchor="middle">the final answer</text>
</svg>"""


# key = sha256 of normalize(fence_text) — see fingerprint().  Recompute with:
#   python -c "import figures; print(figures.fingerprint(open('f').read()))"
FIGURES: dict[str, Figure] = {
    # 00-foundations.md — "What "an agent" actually is", loop-cycle diagram
    "cdb5bc40d9948c5c414d6c71fb632364106e944db4ca39655520007ad365dabf":
        Figure(_LOOP_SVG, "The agent loop (Phase 0)", _LOOP_ALT),
    # 01-bare-harness.md — §2 "The Loop, Conceptually", data-flow diagram
    "454e4aa3db0d31eeb44ef6e4876a9ab430aa93828997d7b391ef3c5c0d44a0b9":
        Figure(_ITER_SVG, "One iteration of the bare loop (Phase 1)", _ITER_ALT),
    # 07-subagents-orchestration.md — §1.4 orchestrator-worker tree
    "c510ac843973eb931dd9fe7091ad6c6e3e9b54140e7029351e2f36e420c061c1":
        Figure(_ORCH_SVG, "Orchestrator and workers (Phase 7)", _ORCH_ALT),
}
