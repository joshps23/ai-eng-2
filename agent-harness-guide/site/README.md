# site/ — generated HTML mirror of the guide

This directory holds a **generated** HTML mirror of the agent-harness guide, for
reading in a browser (including fully offline via `file://` — no CDN, no external
requests). `html/` contains one page per guide document plus a single
`style.css`; the sidebar, per-page table of contents, prev/next links, and
GitHub source links are added by the generator.

## Source of truth

**The markdown files are the source of truth. When the HTML and the markdown
disagree, the markdown is correct — regenerate.**

Never hand-edit anything under `html/` — every page carries a
`GENERATED from <source>.md — do not edit; run site/build_site.py` header, and
the build is byte-idempotent, so any hand edit is a diff waiting to be
clobbered (and a CI drift gate can verify `html/` matches a fresh build).

## How to rebuild

```bash
pip install markdown pygments html5lib   # html5lib only needed for verification
cd agent-harness-guide/site
python build_site.py
```

## What gets generated

| Page | Source |
|------|--------|
| `index.html` | `README.md` (the guide hub) |
| `00-foundations.html` … `09-library-reference.html` | the phase files, same basenames |
| `learning-path.html`, `beginner-notes.html`, `faq.html`, `exercises.html`, `glossary.html` | the support docs (lowercased basenames) |
| `notebooks.html` | `notebooks/README.md` |
| `style.css` | emitted by the script (handwritten rules + pygments styles) |

Deliberately **not** converted: `ROADMAP.md`, `REVISION-BRIEF.md` (maintainer
backstage) and `code/README.md` — links to them (and to anything else in the
repo: `code/…`, `notebooks/*.ipynb`, …) are rewritten to repo-relative paths so
they resolve inside a repo checkout.

## Conversion notes

- Heading anchors use GitHub's slug algorithm (duplicates get `-1`, `-2` …
  suffixes), so every `#anchor` link from the markdown resolves identically.
- `> [!WARNING]`-style GitHub alerts become styled admonitions; 🟢 beginner
  blockquotes get a green-tinted border; `<details>` answers, tables, task
  lists, and code fences nested inside blockquotes/lists all render as on
  GitHub.
