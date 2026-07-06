# Church Fathers source_title Curation Handbook

Static workflow, conventions, and failure modes for source_title curation
agents. Per-agent dispatch prompts reference this handbook so the variable
parts (author slug, entry counts, per-author constraint notes) stay small.

## What source_title is

Each church_fathers entry is a commentary block from one TOML file
(author + verse). The source_title is the specific work the block came
from -- e.g. "City of God", "Commentary on 2 Thessalonians",
"Homilies on Matthew". NOT the author name.

## Title format conventions

This project demands certainty. Do not assign a source_title unless you
can verify it against a primary source (not just plausibility or
adjacent-entry inference alone). Leave entries blank rather than assign
a best-guess.

- Title Case: Capitalise The First Letter Of Each Significant Word.
- For Pauline epistle commentaries: use per-epistle titles
  ("Commentary on Galatians") not a single catch-all. Exception:
  Ambrosiaster uses "Commentary On Paul's Epistles".
- Match the section-specificity convention already in the file exactly.
- The dominant-format hint in the dispatched agent prompt's Pre-flight
  findings block is authoritative unless TOML metadata contradicts it.

## Step 1 -- Format census (run first)

    py -3 -c "
    import json
    from collections import Counter
    d = json.load(open('data/church-fathers/SLUG.json', encoding='utf-8'))
    titles = Counter(e['source_title'] for e in d['data'] if e.get('source_title'))
    for t, c in titles.most_common(30): print(f'{c:3d}  {t}')
    "

Check the most recent comparable patch script in `build/scripts/` for
conventions.

## Step 2 -- Triage

If all existing entries share a single source_title AND the TOML files
for missing entries contain no contradicting metadata (no different
source_url, no different append_to_author_name): this is a data
propagation gap. Verify with 2-3 quote-matches then patch directly --
don't spend time researching what's already answered.

Otherwise: open `raw/Commentaries-Database/<Author Name>/` and map each
TOML block to its source work using:
1. `source_url` field (URL often contains the work title)
2. Quote text + verse reference cross-referenced against the author's
   known works
3. Adjacent entries in the same TOML file that already have source_title

If the convention is section-specific (e.g. "HOMILY ON PSALM 1:11",
"Commentary on Matthew 10.5", "ON THE TRINITY 7.22"), you must match that
format exactly. Do NOT commit a work-level title ("Commentary on Psalms",
"On the Trinity") when section-specific is the file's established
convention.

If section numbers are not determinable from TOML alone: look them up
before committing. NewAdvent (newadvent.org/fathers/) has most patristic
texts online with numbered sections -- WebFetch the right page and match
each quote's opening words against the numbered sections. If lookup
fails after trying NewAdvent and tertullian.org, leave the entry blank
and document why -- an empty field is more honest than a format-
inconsistent one.

## Step 3 -- Confidence rating (rate EVERY entry before writing patch)

- **HIGH**: Verified against primary source (newadvent.org, CCEL,
  archive.org scan).
- **MEDIUM**: Multiple strong converging signals but no direct primary
  source check.
- **LOW**: Short quote (<20 words), single-signal inference, or
  alternative work is plausible.

Only include HIGH entries in the patch. Leave MEDIUM and LOW blank.

## Known failure modes (hard checks, not suggestions)

**FAILURE MODE A -- Scripture index off-by-one:** A Scripture index entry
like `Gen 1:14, 16: pp.90-91` spans a page break -- verify section number
by fetching the body text, not just the index.

**FAILURE MODE B -- Multiple sections in one TOML:** If a TOML has blocks
at sections 2.16 and 2.20 and a third missing block that is much longer,
the missing block is almost certainly from a third section. Look it up
independently.

## Step 4 -- Write patch script

Write `build/scripts/patch_source_title_<SLUG>.py` that:
- Loads `data/church-fathers/<SLUG>.json`
- Applies a patch dict (entry_id -> source_title)
- Is idempotent (skips already-set entries)
- Prints how many were set vs skipped
- Asserts `len(PATCH) == expected` before `main()`
- Saves to the same file
- Uses `Path(__file__).resolve().parents[N]` for DATA_FILE -- no
  hardcoded user paths
- Runs `py -3 build/validate.py data/church-fathers/<SLUG>.json` to
  verify

## Step 5 -- Spot-check 3 riskiest before committing

The riskiest are:
1. Any entry where section number came from a Scripture index
   (Failure Mode A risk)
2. Any TOML file where the missing block is >=3x longer than surrounding
   blocks
3. Any entry assigned by single-signal inference only

For each: fetch the relevant NewAdvent/CCEL/archive.org page and confirm
the quote's opening words appear in the claimed section. Use Playwright
at depth>=4 for historicalchristian.faith and NewAdvent.

Add a spot-check block to the patch script's docstring:

    Spot-checked against primary source:
      - [entry_id] (URL) -- confirmed/failed/skipped + reason

The commit must contain this block. If fewer than 3 are confirmed,
document why and flag to the orchestrator before committing.

## Step 6 -- Commit

    git add data/church-fathers/<SLUG>.json \
            build/scripts/patch_source_title_<SLUG>.py
    git commit -m "curate: source_title for <SLUG> (N entries)"

## Upstream bug log

If you find a source-side data bug (wrong verse tag, composite entry,
misattribution, truncated quote), add a row to `UPSTREAM_BUGS.md` at
the repo root rather than trying to fix it here.

## Reporting back

Agent summary to the orchestrator should cover: how many entries patched,
how many left blank (with reason categories), any upstream bugs flagged,
any interesting findings.
