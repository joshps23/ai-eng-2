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


# ---------------------------------------------------------------------------
# Figure 4 — the call_id handshake (00-foundations §"the handshake, end to end")
# ---------------------------------------------------------------------------
_HANDSHAKE_ALT = (
    "The tool-call handshake: your code sends the conversation; the model "
    "replies with a function_call carrying call_id call_xyz789; you run the "
    "tool and send back a function_call_output carrying the SAME call_id — "
    "that shared id is what pairs your result to the model's request."
)

_HANDSHAKE_SVG = f"""\
<svg viewBox="0 0 620 360" role="img" aria-labelledby="fig-hand-title">
<title id="fig-hand-title">{_HANDSHAKE_ALT}</title>
{_markers("fig-hand")}
<text class="d-label" x="150" y="22" text-anchor="middle">YOUR CODE</text>
<text class="d-label" x="470" y="22" text-anchor="middle">THE MODEL</text>
<line class="d-edge" x1="150" y1="30" x2="150" y2="338"/>
<line class="d-edge" x1="470" y1="30" x2="470" y2="338"/>
<!-- turn 1: send -->
<line class="d-edge" x1="158" y1="52" x2="428" y2="52" marker-end="url(#fig-hand-arrow)"/>
<text class="d-mono" x="290" y="46" text-anchor="middle">send conversation</text>
<text class="d-mono" x="476" y="56" text-anchor="start">thinks…</text>
<!-- the function_call request, carrying call_id -->
<line class="d-edge" x1="462" y1="92" x2="270" y2="92" marker-end="url(#fig-hand-arrow)"/>
<rect class="d-box" x="158" y="100" width="232" height="58"/>
<text class="d-mono-label" x="170" y="120" text-anchor="start">function_call</text>
<text class="d-mono" x="170" y="136" text-anchor="start">name: get_weather</text>
<text class="d-mono d-id" x="170" y="151" text-anchor="start">call_id: call_xyz789</text>
<!-- run the tool -->
<text class="d-mono" x="158" y="184" text-anchor="start">run get_weather("Paris") → "Sunny, 21°C"</text>
<!-- the function_call_output, carrying the SAME call_id -->
<rect class="d-box" x="158" y="198" width="232" height="42"/>
<text class="d-mono-label" x="170" y="216" text-anchor="start">function_call_output</text>
<text class="d-mono d-id" x="170" y="231" text-anchor="start">call_id: call_xyz789</text>
<line class="d-edge" x1="392" y1="219" x2="462" y2="219" marker-end="url(#fig-hand-arrow)"/>
<!-- THE LESSON: the same call_id ties request to result -->
<path class="d-edge-hot" d="M398 145 L424 145 L424 226 L398 226"/>
<rect class="d-box d-accent d-pill" x="430" y="156" width="150" height="54"/>
<text class="d-label d-accent-text" x="505" y="178" text-anchor="middle">same call_id</text>
<text class="d-mono d-accent-text" x="505" y="196" text-anchor="middle">pairs request→result</text>
<!-- turn 2: send again, model answers in text -->
<line class="d-edge" x1="158" y1="278" x2="428" y2="278" marker-end="url(#fig-hand-arrow)"/>
<text class="d-mono" x="290" y="272" text-anchor="middle">send conversation</text>
<text class="d-mono" x="476" y="282" text-anchor="start">thinks…</text>
<line class="d-edge" x1="462" y1="312" x2="158" y2="312" marker-end="url(#fig-hand-arrow)"/>
<text class="d-mono-label" x="158" y="306" text-anchor="start">message</text>
<text class="d-mono" x="158" y="330" text-anchor="start">"It's sunny and 21°C in Paris."</text>
</svg>"""


# ---------------------------------------------------------------------------
# Figure 5 — registry dispatch (02-tool-system §"what dispatch does")
# ---------------------------------------------------------------------------
_DISPATCH_ALT = (
    "Registry dispatch: the model wants add {a:2, b:3}; the TOOLS dict is a "
    "plain name→function lookup table, so looking up \"add\" returns its "
    "{fn, schema}; the harness runs fn(**args) and the result string \"5\" "
    "goes back into the conversation. Adding a tool is adding one row."
)

_DISPATCH_SVG = f"""\
<svg viewBox="0 0 600 380" role="img" aria-labelledby="fig-disp-title">
<title id="fig-disp-title">{_DISPATCH_ALT}</title>
{_markers("fig-disp")}
<rect class="d-box d-accent d-pill" x="150" y="16" width="300" height="38"/>
<text class="d-mono-label" x="300" y="40" text-anchor="middle">model wants:  add  {{"a": 2, "b": 3}}</text>
<line class="d-edge" x1="300" y1="56" x2="300" y2="83" marker-end="url(#fig-disp-arrow)"/>
<!-- the TOOLS lookup table — the lesson element -->
<rect class="d-box d-accent" x="120" y="86" width="360" height="86"/>
<text class="d-label d-accent-text" x="138" y="108" text-anchor="start">TOOLS  (a plain dict)</text>
<text class="d-mono" x="468" y="104" text-anchor="end">look the NAME up</text>
<line class="d-edge-hot" x1="138" y1="116" x2="372" y2="116"/>
<text class="d-mono-label" x="138" y="138" text-anchor="start">"add"        → {{fn, schema}}</text>
<text class="d-mono" x="138" y="160" text-anchor="start">"word_count" → {{fn, schema}}</text>
<rect class="d-chip d-chip-accent" x="372" y="126" width="78" height="18"/>
<text class="d-chip-text d-chip-text-accent" x="411" y="139" text-anchor="middle">match</text>
<line class="d-edge" x1="300" y1="172" x2="300" y2="206" marker-end="url(#fig-disp-arrow)"/>
<text class="d-mono" x="312" y="192" text-anchor="start">found fn + schema</text>
<rect class="d-box" x="125" y="209" width="350" height="40"/>
<text class="d-mono-label" x="300" y="234" text-anchor="middle">run  fn(**{{"a": 2, "b": 3}})  →  "5"</text>
<line class="d-edge" x1="300" y1="249" x2="300" y2="283" marker-end="url(#fig-disp-arrow)"/>
<rect class="d-box d-good" x="105" y="286" width="390" height="40"/>
<text class="d-mono-label" x="300" y="311" text-anchor="middle">result string "5"  →  back into the conversation</text>
<text class="d-mono" x="300" y="352" text-anchor="middle">adding a tool = adding one row — the loop never changes</text>
</svg>"""


# ---------------------------------------------------------------------------
# Figure 6 — the transcript IS the memory (03-conversation §"seen as a picture")
# ---------------------------------------------------------------------------
_MEMORY_ALT = (
    "The transcript is the memory: the model is stateless and forgets after "
    "every call, but the harness owns input_items — a list that only grows. "
    "On turn 2 it resends the WHOLE list, so the model \"remembers\" the name "
    "Alex only because the list was re-sent, not because the model stored it."
)

_MEMORY_SVG = f"""\
<svg viewBox="0 0 640 360" role="img" aria-labelledby="fig-mem-title">
<title id="fig-mem-title">{_MEMORY_ALT}</title>
{_markers("fig-mem")}
<text class="d-label" x="150" y="22" text-anchor="middle">THE MODEL</text>
<text class="d-mono" x="150" y="38" text-anchor="middle">stateless — forgets each call</text>
<text class="d-label d-accent-text" x="450" y="22" text-anchor="middle">THE HARNESS owns input_items</text>
<text class="d-mono" x="450" y="38" text-anchor="middle">a list that only grows</text>
<!-- turn 1 -->
<text class="d-mono-label" x="40" y="68" text-anchor="start">Turn 1</text>
<rect class="d-box" x="40" y="76" width="170" height="54"/>
<text class="d-mono-label" x="125" y="100" text-anchor="middle">responses</text>
<text class="d-mono-label" x="125" y="116" text-anchor="middle">.create(...)</text>
<line class="d-edge" x1="218" y1="92" x2="300" y2="92" marker-end="url(#fig-mem-arrow)"/>
<text class="d-mono" x="259" y="86" text-anchor="middle">send</text>
<line class="d-edge" x1="300" y1="116" x2="218" y2="116" marker-end="url(#fig-mem-arrow)"/>
<text class="d-mono" x="259" y="128" text-anchor="middle">reply</text>
<rect class="d-box d-accent" x="300" y="62" width="300" height="68"/>
<text class="d-mono d-accent-text" x="314" y="82" text-anchor="start">input_items so far:</text>
<text class="d-mono" x="314" y="100" text-anchor="start">├─ user:  "My name is Alex."</text>
<text class="d-mono" x="314" y="118" text-anchor="start">└─ model: "Got it, Alex."</text>
<!-- the resend arrow — the lesson element -->
<path class="d-edge-hot" d="M450 130 L450 168" marker-end="url(#fig-mem-arrow-hot)"/>
<text class="d-mono d-accent-text" x="462" y="154" text-anchor="start">RESEND the WHOLE list ↓</text>
<!-- turn 2 -->
<text class="d-mono-label" x="40" y="206" text-anchor="start">Turn 2</text>
<rect class="d-box" x="40" y="214" width="170" height="54"/>
<text class="d-mono-label" x="125" y="238" text-anchor="middle">responses</text>
<text class="d-mono-label" x="125" y="254" text-anchor="middle">.create(...)</text>
<line class="d-edge" x1="218" y1="230" x2="300" y2="230" marker-end="url(#fig-mem-arrow)"/>
<text class="d-mono" x="259" y="224" text-anchor="middle">send</text>
<rect class="d-box d-accent" x="300" y="176" width="320" height="78"/>
<text class="d-mono" x="314" y="196" text-anchor="start">├─ user:  "My name is Alex."</text>
<text class="d-mono" x="314" y="214" text-anchor="start">├─ model: "Got it, Alex."</text>
<text class="d-mono" x="314" y="232" text-anchor="start">└─ user:  "What is my name?"</text>
<line class="d-edge" x1="300" y1="290" x2="218" y2="290" marker-end="url(#fig-mem-arrow)"/>
<text class="d-mono" x="125" y="300" text-anchor="middle">reply</text>
<rect class="d-box d-good" x="40" y="298" width="270" height="46"/>
<text class="d-label" x="56" y="318" text-anchor="start">"Your name is Alex."</text>
<text class="d-mono" x="56" y="336" text-anchor="start">it "remembers" — because the list was re-sent</text>
</svg>"""


# ---------------------------------------------------------------------------
# Figure 7 — the permission decision flow (05-permissions §"order of checks")
# ---------------------------------------------------------------------------
_PERM_ALT = (
    "The permission decision flow, in order: (1) does the mode hard-deny this "
    "risk tier? (2) does a policy DENY rule match? Those two hard denials run "
    "FIRST and end the decision. Only below that boundary does (3) session "
    "memory and (4) risk×mode run — so a remembered \"always allow\" can never "
    "re-open a tool the hard denials blocked."
)

_PERM_SVG = f"""\
<svg viewBox="0 0 620 470" role="img" aria-labelledby="fig-perm-title">
<title id="fig-perm-title">{_PERM_ALT}</title>
{_markers("fig-perm")}
<rect class="d-box d-pill" x="180" y="12" width="300" height="32"/>
<text class="d-mono" x="330" y="32" text-anchor="middle">tool call (tool, args, mode, policy)</text>
<line class="d-edge" x1="330" y1="44" x2="330" y2="63" marker-end="url(#fig-perm-arrow)"/>
<!-- 1. mode hard-deny -->
<rect class="d-box d-accent" x="70" y="66" width="380" height="34"/>
<text class="d-label" x="86" y="88" text-anchor="start">1. Mode hard-denies this risk tier?</text>
<line class="d-edge-hot" x1="450" y1="83" x2="540" y2="83" marker-end="url(#fig-perm-arrow-hot)"/>
<text class="d-mono d-accent-text" x="495" y="77" text-anchor="middle">yes</text>
<rect class="d-box d-deny" x="540" y="68" width="60" height="30"/>
<text class="d-label d-deny-text" x="570" y="88" text-anchor="middle">DENY</text>
<line class="d-edge" x1="330" y1="100" x2="330" y2="119" marker-end="url(#fig-perm-arrow)"/>
<text class="d-mono" x="342" y="114" text-anchor="start">no</text>
<!-- 2. policy DENY -->
<rect class="d-box d-accent" x="70" y="122" width="380" height="34"/>
<text class="d-label" x="86" y="144" text-anchor="start">2. A policy DENY rule matches?</text>
<line class="d-edge-hot" x1="450" y1="139" x2="540" y2="139" marker-end="url(#fig-perm-arrow-hot)"/>
<text class="d-mono d-accent-text" x="495" y="133" text-anchor="middle">yes</text>
<rect class="d-box d-deny" x="540" y="124" width="60" height="30"/>
<text class="d-label d-deny-text" x="570" y="144" text-anchor="middle">DENY</text>
<line class="d-edge" x1="330" y1="156" x2="330" y2="200" marker-end="url(#fig-perm-arrow)"/>
<text class="d-mono" x="320" y="170" text-anchor="end">no</text>
<!-- THE BOUNDARY: hard denials end here / session memory starts below -->
<text class="d-mono d-accent-text" x="330" y="184" text-anchor="middle">↑ hard denials end here · session memory starts below ↓</text>
<line class="d-edge-hot d-dash" x1="40" y1="192" x2="600" y2="192"/>
<!-- 3. session memory -->
<rect class="d-box" x="70" y="202" width="380" height="44"/>
<text class="d-label" x="86" y="220" text-anchor="start">3. In session memory?</text>
<text class="d-mono" x="86" y="238" text-anchor="start">(remembered "always allow / always deny")</text>
<line class="d-edge" x1="450" y1="218" x2="540" y2="218" marker-end="url(#fig-perm-arrow)"/>
<text class="d-mono" x="495" y="212" text-anchor="middle">deny</text>
<rect class="d-box d-deny" x="540" y="203" width="60" height="28"/>
<text class="d-label d-deny-text" x="570" y="222" text-anchor="middle">DENY</text>
<line class="d-edge" x1="450" y1="236" x2="540" y2="236" marker-end="url(#fig-perm-arrow)"/>
<text class="d-mono" x="495" y="252" text-anchor="middle">allow</text>
<rect class="d-box d-good" x="540" y="240" width="60" height="28"/>
<text class="d-label" x="570" y="259" text-anchor="middle">ALLOW</text>
<line class="d-edge" x1="330" y1="246" x2="330" y2="287" marker-end="url(#fig-perm-arrow)"/>
<text class="d-mono" x="342" y="270" text-anchor="start">neither</text>
<!-- 4. risk x mode -->
<rect class="d-box" x="70" y="290" width="380" height="34"/>
<text class="d-label" x="86" y="312" text-anchor="start">4. risk × mode decides</text>
<line class="d-edge" x1="450" y1="307" x2="540" y2="307" marker-end="url(#fig-perm-arrow)"/>
<text class="d-mono" x="495" y="301" text-anchor="middle">allow</text>
<rect class="d-box d-good" x="540" y="292" width="60" height="30"/>
<text class="d-label" x="570" y="312" text-anchor="middle">ALLOW</text>
<line class="d-edge" x1="330" y1="324" x2="330" y2="367" marker-end="url(#fig-perm-arrow)"/>
<text class="d-mono" x="342" y="346" text-anchor="start">otherwise</text>
<!-- ASK -->
<rect class="d-box d-pill" x="170" y="370" width="320" height="40"/>
<text class="d-label" x="330" y="388" text-anchor="middle">ASK the user → ALLOW / DENY</text>
<text class="d-mono" x="330" y="404" text-anchor="middle">(y/n, or a/d to remember in step 3)</text>
</svg>"""


# ---------------------------------------------------------------------------
# Figure 8 — context pruning (06-context-management §"picture what those rules do")
# ---------------------------------------------------------------------------
_PRUNE_ALT = (
    "Context pruning: before, the transcript is over budget. prune_to_budget "
    "drops the oldest droppable groups (call#0–2 with their outputs) but pins "
    "the first user message — the task — and keeps each function_call glued to "
    "its function_call_output, so the result fits the budget and no pair is "
    "ever orphaned."
)

_PRUNE_SVG = f"""\
<svg viewBox="0 0 640 420" role="img" aria-labelledby="fig-prune-title">
<title id="fig-prune-title">{_PRUNE_ALT}</title>
{_markers("fig-prune")}
<text class="d-label" x="160" y="22" text-anchor="middle">BEFORE (over budget)</text>
<text class="d-label" x="480" y="22" text-anchor="middle">AFTER prune_to_budget</text>
<!-- BEFORE column -->
<rect class="d-box d-accent" x="40" y="34" width="240" height="34"/>
<text class="d-mono-label d-accent-text" x="52" y="55" text-anchor="start">user: the task</text>
<rect class="d-chip d-chip-accent" x="190" y="42" width="78" height="18"/>
<text class="d-chip-text d-chip-text-accent" x="229" y="55" text-anchor="middle">★ pinned</text>
<rect class="d-box d-drop" x="40" y="74" width="200" height="38"/>
<text class="d-mono d-drop-text" x="52" y="91" text-anchor="start">call#0 ┐ pair (oldest)</text>
<text class="d-mono d-drop-text" x="52" y="106" text-anchor="start">output#0 ┘</text>
<text class="d-mono d-drop-text" x="248" y="97" text-anchor="start">drop ✗</text>
<rect class="d-box d-drop" x="40" y="118" width="200" height="38"/>
<text class="d-mono d-drop-text" x="52" y="135" text-anchor="start">call#1 ┐ pair</text>
<text class="d-mono d-drop-text" x="52" y="150" text-anchor="start">output#1 ┘</text>
<text class="d-mono d-drop-text" x="248" y="141" text-anchor="start">drop ✗</text>
<rect class="d-box d-drop" x="40" y="162" width="200" height="38"/>
<text class="d-mono d-drop-text" x="52" y="179" text-anchor="start">call#2 ┐ pair</text>
<text class="d-mono d-drop-text" x="52" y="194" text-anchor="start">output#2 ┘</text>
<text class="d-mono d-drop-text" x="248" y="185" text-anchor="start">drop ✗</text>
<rect class="d-box d-good" x="40" y="206" width="200" height="38"/>
<text class="d-mono" x="52" y="223" text-anchor="start">call#3 ┐ pair</text>
<text class="d-mono" x="52" y="238" text-anchor="start">output#3 ┘</text>
<text class="d-mono" x="248" y="229" text-anchor="start">keep</text>
<rect class="d-box d-good" x="40" y="250" width="200" height="38"/>
<text class="d-mono" x="52" y="267" text-anchor="start">call#4 ┐ pair (newest)</text>
<text class="d-mono" x="52" y="282" text-anchor="start">output#4 ┘</text>
<text class="d-mono" x="248" y="273" text-anchor="start">keep</text>
<line class="d-edge-hot d-dash" x1="40" y1="300" x2="280" y2="300"/>
<text class="d-mono d-deny-text" x="40" y="316" text-anchor="start">── budget line ──  ✗ over</text>
<!-- the kept set survives -->
<path class="d-edge" d="M280 51 C330 51 330 130 388 130" marker-end="url(#fig-prune-arrow)"/>
<path class="d-edge" d="M240 225 C320 225 320 175 388 175" marker-end="url(#fig-prune-arrow)"/>
<path class="d-edge" d="M240 269 C330 269 330 220 388 220" marker-end="url(#fig-prune-arrow)"/>
<!-- AFTER column -->
<rect class="d-box d-accent" x="390" y="110" width="240" height="34"/>
<text class="d-mono-label d-accent-text" x="402" y="131" text-anchor="start">user: the task  ★ pin</text>
<text class="d-mono d-accent-text" x="402" y="103" text-anchor="start">always kept</text>
<rect class="d-box d-good" x="390" y="158" width="200" height="38"/>
<text class="d-mono" x="402" y="175" text-anchor="start">call#3 ┐ pair</text>
<text class="d-mono" x="402" y="190" text-anchor="start">output#3 ┘</text>
<rect class="d-box d-good" x="390" y="203" width="200" height="38"/>
<text class="d-mono" x="402" y="220" text-anchor="start">call#4 ┐ pair (newest)</text>
<text class="d-mono" x="402" y="235" text-anchor="start">output#4 ┘</text>
<line class="d-edge d-dash" x1="390" y1="250" x2="630" y2="250"/>
<text class="d-mono d-good-text" x="390" y="266" text-anchor="start">── budget line ──  ✓ fits</text>
<text class="d-mono d-accent-text" x="20" y="328" text-anchor="start">a call and its output drop together (never orphan one); the task is</text>
<text class="d-mono d-accent-text" x="20" y="344" text-anchor="start">pinned no matter how old it gets.</text>
</svg>"""


# ---------------------------------------------------------------------------
# Figure 9 — the production architecture (08-production §"snapped together")
# ---------------------------------------------------------------------------
_ARCH_ALT = (
    "The production architecture: the Agent loop sits at the centre and calls "
    "each collaborator in a fixed order — Conversation owns the transcript; "
    "LLMClient wraps responses.create with retry/backoff to the model; the "
    "permissions+hooks gate checks every tool call BEFORE it runs (a denial "
    "becomes an error string); allowed calls go to the ToolRegistry's parallel "
    "dispatch over files, shell, task. It is the parts you already built, wired up."
)

_ARCH_SVG = f"""\
<svg viewBox="0 0 660 420" role="img" aria-labelledby="fig-arch-title">
<title id="fig-arch-title">{_ARCH_ALT}</title>
{_markers("fig-arch")}
<!-- Agent loop, centre -->
<rect class="d-box d-accent" x="200" y="20" width="300" height="64"/>
<text class="d-label d-accent-text" x="350" y="44" text-anchor="middle">AGENT loop</text>
<text class="d-mono" x="350" y="62" text-anchor="middle">calls each collaborator</text>
<text class="d-mono" x="350" y="76" text-anchor="middle">in a fixed order — no cleverness</text>
<!-- Conversation, left -->
<rect class="d-box" x="20" y="110" width="150" height="70"/>
<text class="d-label" x="95" y="134" text-anchor="middle">Conversation</text>
<text class="d-mono" x="95" y="152" text-anchor="middle">owns the</text>
<text class="d-mono" x="95" y="166" text-anchor="middle">transcript</text>
<path class="d-edge" d="M170 130 C188 130 188 52 200 52" marker-end="url(#fig-arch-arrow)"/>
<path class="d-edge" d="M200 64 C188 64 188 150 170 150" marker-end="url(#fig-arch-arrow)"/>
<text class="d-mono" x="183" y="100" text-anchor="middle">transcript in/out</text>
<!-- LLMClient + model, right -->
<rect class="d-box" x="430" y="110" width="160" height="56"/>
<text class="d-label" x="510" y="132" text-anchor="middle">LLMClient</text>
<text class="d-mono" x="510" y="150" text-anchor="middle">retry / backoff</text>
<rect class="d-box" x="600" y="118" width="50" height="40"/>
<text class="d-mono-label" x="625" y="142" text-anchor="middle">model</text>
<path class="d-edge" d="M500 84 C500 96 510 96 510 108" marker-end="url(#fig-arch-arrow)"/>
<text class="d-mono" x="556" y="100" text-anchor="middle">responses.create</text>
<line class="d-edge" x1="590" y1="132" x2="598" y2="132" marker-end="url(#fig-arch-arrow)"/>
<line class="d-edge" x1="600" y1="148" x2="592" y2="148" marker-end="url(#fig-arch-arrow)"/>
<!-- down the spine to the gate -->
<line class="d-edge" x1="350" y1="84" x2="350" y2="201" marker-end="url(#fig-arch-arrow)"/>
<text class="d-mono" x="362" y="180" text-anchor="start">each tool call</text>
<!-- permissions + hooks gate (BEFORE) -->
<rect class="d-box d-accent" x="230" y="204" width="240" height="50"/>
<text class="d-label d-accent-text" x="350" y="226" text-anchor="middle">permissions + hooks gate</text>
<text class="d-mono" x="350" y="244" text-anchor="middle">check BEFORE it runs</text>
<!-- deny -> error string back to loop (the lesson: the gate guards) -->
<path class="d-edge-hot" d="M470 218 L560 218 L560 312" marker-end="url(#fig-arch-arrow-hot)"/>
<text class="d-mono d-accent-text" x="476" y="212" text-anchor="start">deny → error string</text>
<text class="d-mono d-accent-text" x="566" y="316" text-anchor="start">(back to loop)</text>
<line class="d-edge" x1="350" y1="254" x2="350" y2="293" marker-end="url(#fig-arch-arrow)"/>
<text class="d-mono" x="362" y="276" text-anchor="start">allow</text>
<!-- ToolRegistry -->
<rect class="d-box" x="230" y="296" width="240" height="50"/>
<text class="d-label" x="350" y="318" text-anchor="middle">ToolRegistry</text>
<text class="d-mono" x="350" y="336" text-anchor="middle">parallel dispatch</text>
<line class="d-edge" x1="470" y1="321" x2="540" y2="321" marker-end="url(#fig-arch-arrow)"/>
<text class="d-mono" x="350" y="372" text-anchor="middle">files · shell · task …</text>
<text class="d-mono" x="350" y="388" text-anchor="middle">(results → transcript)</text>
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
    # 00-foundations.md — the call_id handshake (request ↔ result pairing)
    "b98bdd12e337d169ad945330c5b03b73d60e967facdc42efad3dc677607b4876":
        Figure(_HANDSHAKE_SVG, "The call_id handshake (Phase 0)", _HANDSHAKE_ALT),
    # 02-tool-system.md — registry dispatch (name→function lookup table)
    "a4db4eaba10027a387bea37fba726751b84d8be630b00963bfae29e7ad171472":
        Figure(_DISPATCH_SVG, "Registry dispatch (Phase 2)", _DISPATCH_ALT),
    # 03-conversation-and-streaming.md — the transcript IS the memory
    "f7ef2bb3246417503286dc421553b6d01a2c07da2f8111ae9d24300d174ad491":
        Figure(_MEMORY_SVG, "The transcript is the memory (Phase 3)", _MEMORY_ALT),
    # 05-permissions-and-safety.md — the permission decision flow
    "1532ffdc22d867635fb53e2450333d4cb3115847121c9df703716ae14fa97c60":
        Figure(_PERM_SVG, "The permission decision flow (Phase 5)", _PERM_ALT),
    # 06-context-management.md — context-window pruning (pin + keep pairs)
    "58d646e07784dd0748bd978522e6f5704c6332fb78ba2144967c334e054ce35a":
        Figure(_PRUNE_SVG, "Context pruning (Phase 6)", _PRUNE_ALT),
    # 08-production-harness.md — the production architecture, wired together
    "92d184603c5846f92b98ed66041c3d7029c52de6c878e3a90904e3f818528231":
        Figure(_ARCH_SVG, "The production architecture (Phase 8)", _ARCH_ALT),
}
