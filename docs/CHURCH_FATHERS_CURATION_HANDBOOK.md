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

Use the retained TOML and current parser tests to establish conventions. Loose
downstream patch scripts are not source authority.

## Step 2 -- Triage

If all existing entries share a single source_title AND the TOML files
for missing entries contain no contradicting metadata (no different
source_url, no different append_to_author_name): this is a source
propagation gap. Verify with 2-3 quote-matches, then propose the upstream
source correction and prove it through parser tests. Do not patch generated
JSON.

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

## Step 3 -- Confidence rating (rate EVERY entry before changing source authority)

- **HIGH**: Verified against primary source (newadvent.org, CCEL,
  archive.org scan).
- **MEDIUM**: Multiple strong converging signals but no direct primary
  source check.
- **LOW**: Short quote (<20 words), single-signal inference, or
  alternative work is plausible.

Only promote HIGH entries into parser-consumed source authority. Leave MEDIUM
and LOW blank. The current supplemental authority is
`sources/church-fathers/source-title-corrections.json`; each record binds a
retained TOML path, block index, quote SHA-256, normalized title, and evidence
reference. Accepted `data/` entry IDs are never authority keys.

The 18 retained directories named for New Testament books are a distinct,
deterministic case: the directory names the source work that carries each Old
Testament quotation. The parser derives their normalized canonical book title
directly from that source-directory identity (300 current retained blocks). It
rejects a contradictory retained title. These rules do not belong in the
supplemental locator authority and must not be reintroduced as an output patch.

## Known failure modes (hard checks, not suggestions)

**FAILURE MODE A -- Scripture index off-by-one:** A Scripture index entry
like `Gen 1:14, 16: pp.90-91` spans a page break -- verify section number
by fetching the body text, not just the index.

**FAILURE MODE B -- Multiple sections in one TOML:** If a TOML has blocks
at sections 2.16 and 2.20 and a third missing block that is much longer,
the missing block is almost certainly from a third section. Look it up
independently.

## Step 4 -- Correct source authority and add parser tests

Submit the correction upstream to the retained Commentaries-Database source.
Until corrected source bytes are acquired, a HIGH claim may be recorded in the
supplemental authority above. The parser must fail if the bound quote changes or
the retained title contradicts the correction. Once corrected source is
acquired, remove the now-redundant supplemental record. Add focused parser tests
and regenerate through `build/parsers/church_fathers.py`. Never write
`data/church-fathers/*.json` directly and never introduce a post-parse patch,
accepted-output lookup, fallback, or compatibility branch.

## Step 5 -- Spot-check 3 riskiest before committing

The riskiest are:
1. Any entry where section number came from a Scripture index
   (Failure Mode A risk)
2. Any TOML file where the missing block is >=3x longer than surrounding
   blocks
3. Any entry assigned by single-signal inference only

Verify each proposed attribution against the quoted passage in a primary source.
Record the source URL or scan locator and matching section. Independently recheck
the three riskiest changes, or every change when there are fewer than three.
Leave an individual field blank when its evidence is insufficient. Browser
traversal depth is not evidence of a correct attribution.

Record the checks and any unresolved fields in the upstream issue or source
provenance record.

## Step 6 -- Verify the regenerated result

Run the focused parser tests, regenerate through the parser, and validate the
generated artifact. Commit the acquired source-authority change, parser tests,
and generated output together under the repository's normal data-production
workflow.

## Upstream bug log

If you find a source-side data bug (wrong verse tag, composite entry,
misattribution, truncated quote), add a row to `UPSTREAM_BUGS.md` at
the repo root rather than trying to fix it here.

## Reporting back

Agent summary to the orchestrator should cover: how many entries corrected,
how many left blank (with reason categories), any upstream bugs flagged,
any interesting findings.
