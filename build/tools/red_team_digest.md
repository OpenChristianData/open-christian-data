# Data Accuracy Red Team -- Digest
Generated: 2026-04-12
Red team report: build/tools/red_team_report.md
Audit report: build/tools/data_accuracy_report.md

## Publish Decision

**MAJOR FIX** -- Two parser bugs in the HelloAO commentary pipeline cause wholesale content loss (292 missing book introductions) and structured-data loss (71,057 entries with empty cross_references). The dataset is already published; these require a corrected release with parser fixes and a full re-export of the five HelloAO-derived commentary authors.

**Update 2026-04-12:** Findings 1 and 3 fixed. Book introductions (292) now emitted as `chapter: 0` entries. Chapter introductions separated into distinct `verse_range: "intro"` records. Schema updated to v2.2.0 (commentary.schema.json allows `chapter: 0`, `verse_range: "intro"`, `verse_range_osis: null`). Validator updated. All 5 authors re-run. Entry count: 71,057 -> 74,322 (+3,265). Findings 2 and 4 remain open.

## Triage Table

| # | Category | Finding | Severity | Affected entries | Action | Effort |
|---|----------|---------|----------|-----------------|--------|--------|
| 1 | Commentaries (HelloAO) | Book introductions dropped -- `book.introduction` in raw JSON is never read by the parser | P1 | 292 book files across 5 authors (Adam Clarke 57, JFB 66, John Gill 66, K-D 38, Matthew Henry 65) | **FIXED 2026-04-12** | Medium |
| 2 | Commentaries (HelloAO) | cross_references hardcoded to `[]` -- 71,057 entries contain visible scripture citations in text but the structured field is empty | P1 | 71,057 entries (adam-clarke 13,525; JFB 18,223; john-gill 28,452; K-D 6,702; matthew-henry 4,155) | Fix post-publish (parser) | High |
| 3 | Commentaries (HelloAO) | Chapter introductions merged into verse-scoped entries -- first-entry `entry_id` implies verse-local but text is chapter-level | P2 | ~292 first entries across all HelloAO book files | **FIXED 2026-04-12** | Medium |
| 4 | Commentaries (SWORD) + Devotionals | Paragraph boundaries lost -- `_WS_PATTERN.sub(" ", plain)` collapses `\n\n` to single space | P2 | All SWORD-derived commentary and devotional text (Barnes, Wesley, Daily Light) | Fix post-publish (parser) | Low |

### Verification of each finding

**Finding 1 -- CONFIRMED.** Checked `raw/helloao_local/api/c/jamieson-fausset-brown/ROM/1.json`: `book.introduction` exists (7,660 chars). Grep of `helloao_commentary.py` for `book` and `introduction`: zero matches. The parser never reads this field. Counted all 292 raw chapter-1 files: 292/292 have non-empty `book.introduction`. Zero book introductions appear in any exported file.

**Finding 2 -- CONFIRMED.** Checked line 234 of `helloao_commentary.py`: `"cross_references": []` is hardcoded in `make_entry()`. Counted across all five HelloAO authors: 71,057/71,057 entries have empty cross_references. By contrast, SWORD-derived Barnes has 871/974 entries with non-empty cross_references, confirming this is specific to the HelloAO pipeline.

**Finding 3 -- CONFIRMED.** Checked lines 293-313 of `helloao_commentary.py`: chapter introduction is prepended to first section's content when the section starts at verse 1. Scanned 292 first entries with intro-detecting regex: 20 match explicit patterns (INTRODUCTION, Preface to, This chapter contains). The red team found 28 with broader patterns; the discrepancy is from my regex being conservative. The content assignment issue is real.

**Finding 4 -- CONFIRMED.** Checked `sword_commentary.py:573` and `sword_devotional.py:76`: both use `_WS_PATTERN = re.compile(r"\s+")` followed by `.sub(" ", plain)`. Barnes Acts 1:5 output: 0 newlines in the commentary text. Daily Light 01-01-morning: 0 newlines in a 1,051-character content block. No word loss confirmed, but paragraph structure is flattened.

### Summary counts

- Findings that block publish: 0 (already published)
- Findings requiring corrected release: 2 (P1 #1, P1 #2)
- Findings to document as known limitations: 4 (all four)
- Findings fixable this session: 0 (all require parser changes + full re-run)
- Findings already fixed or invalid: 0

## Fixes Applied

No fixes were applied this session. All four findings are parser-level issues that require:

1. Changes to `build/parsers/helloao_commentary.py` (findings 1, 2, 3)
2. Changes to `build/parsers/sword_commentary.py` and `build/parsers/sword_devotional.py` (finding 4)
3. Full re-run of affected parsers
4. Re-export and push to HuggingFace

### Fix list for future session

#### ~~Parser bug: HelloAO book introductions (Finding 1)~~ FIXED 2026-04-12

- **What was done:** Added `make_intro_entry()` to parser. Book introductions read from `raw["book"]["introduction"]` in chapter 1 raw files and emitted as `chapter: 0`, `verse_range: "intro"` entries. Schema updated to v2.2.0 (allows `chapter: 0`, `verse_range: "intro"`, `verse_range_osis: null`). Validator updated to handle intro entries.
- **Result:** 292 book intro records added. Validation: 0 errors.

#### Parser limitation: HelloAO cross_references (Finding 2)

- **File:** `build/parsers/helloao_commentary.py:234`
- **Root cause:** `make_entry()` hardcodes `"cross_references": []`. The text contains visible citations (e.g., `Luk 1:2`, `Exo 20:9-11`) but no extraction is attempted.
- **Fix:** Add a text-scan pass before `make_entry()` that extracts scripture references from `commentary_text`. Reuse `build/lib/bible_ref_normalizer.py` which already handles OSIS normalization. The SWORD pipeline already does this successfully (`sword_commentary.py:566-568`).
- **Affected entries:** 71,057 entries. The red team estimated 44,500 contain visible citations; actual extraction count depends on regex coverage.
- **Verification:** After fix, count non-empty `cross_references` across all five authors. Compare with SWORD Barnes baseline (89% populated) as a sanity check. Run `validate.py`.

#### ~~Content assignment: chapter intros in verse entries (Finding 3)~~ FIXED 2026-04-12

- **What was done:** Replaced prepend-to-first-section logic with separate `verse_range: "intro"` entries per chapter. Chapter intros now have entry_id `{resource_id}.{book_osis}.{chapter}.intro`.
- **Result:** ~2,973 chapter intro entries now separated. First verse entries no longer contain prepended intro text. Validation: 0 errors.

#### Paragraph flattening: SWORD normalization (Finding 4)

- **File:** `build/parsers/sword_commentary.py:573`, `build/parsers/sword_devotional.py:76`
- **Root cause:** `_WS_PATTERN.sub(" ", plain)` collapses all whitespace including `\n\n` paragraph breaks from `<br /><br />` tags.
- **Fix:** Before the whitespace collapse, convert `<br /><br />` (and `<br/><br/>` variants) to `\n\n`. Then only collapse runs of spaces (not newlines) to single space. Preserve `\n\n` as paragraph separators.
- **Affected entries:** All SWORD-derived commentary and devotional text.
- **Verification:** After fix, check Barnes Acts 1:5 and Daily Light 01-01-morning for `\n\n` presence. Confirm no word loss by comparing token counts before/after.

## Known Limitations (for dataset card)

```markdown
## Known Limitations

- **Commentary coverage varies by author.** Older commentaries (Clarke, Keil-Delitzsch, Jamieson-Fausset-Brown) comment selectively -- coverage ranges from 5% to 100% depending on book and author. This is characteristic of the source material, not a parsing error.

- ~~**HelloAO commentary book introductions are not yet included.**~~ **FIXED 2026-04-12.** 292 book introductions now included as `chapter: 0` entries with `verse_range: "intro"`.

- **HelloAO commentary cross-references are not yet extracted.** The `cross_references` field is empty for all 74,322 entries from the five HelloAO-derived authors, even though their commentary text contains visible scripture citations. SWORD-derived commentaries (Barnes, Wesley) do have populated cross-references. Extraction for HelloAO authors will be added in a future release.

- ~~**Some first-chapter entries contain chapter-level introductions.**~~ **FIXED 2026-04-12.** Chapter introductions are now emitted as separate `verse_range: "intro"` records before verse-scoped entries.

- **Paragraph boundaries are flattened in SWORD-derived text.** Commentary and devotional entries sourced from SWORD modules (Barnes, Wesley, Daily Light) have paragraph breaks collapsed to single spaces. No words are lost, but multi-paragraph entries read as continuous prose. A future release will preserve paragraph structure.

- **Church fathers `source_title` coverage is incomplete.** Approximately 113 entries across the church-fathers category have empty `source_title` fields. This is an upstream gap in the source database being addressed through ongoing manual curation.

- **`era` metadata is inconsistently populated.** The `era` field is present in structured-text and sermon files but absent in commentary, reference, and topical-reference outputs. This does not affect content accuracy.
```

## New Validate Baseline

0 errors, 113 warnings -- unchanged from pre-digest baseline. No fixes were applied this session (all findings require parser changes, not data patches), so the validation baseline is unchanged.
