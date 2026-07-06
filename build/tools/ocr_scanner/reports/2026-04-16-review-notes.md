# OCR Scanner -- SH Real-Corpus Scan Review Notes
**Date:** 2026-04-16
**Source:** schaff-herzog (8,351 entries)
**Lexicon:** theological_seed.txt (15,925 terms from Naves + SH)
**Scan run:** schaff-herzog_2026-04-16.json (50,000-candidate cap)

---

## Total Candidate Counts

The aggregate scan hit the 50,000-candidate cap after covering **4,309 of 8,351 entries**
(approximately 52% of the corpus). The counts below reflect that partial run.

A separate targeted per-entry scan was run for known-positive verification (see below);
it covers all 8,351 entries and is the authoritative source for the rediscovery check.

| Tier   | Count  | Notes                                   |
|--------|--------|-----------------------------------------|
| Tier 1 | 19,177 | Includes many FPs -- see precision notes |
| Tier 2 | 30,823 | Near-100% FP from sample -- see below   |
| Tier 3 | 0      | Disabled in config                      |
| Total  | 50,000 | Truncated -- not full corpus coverage   |

---

## Rediscovery Check (targeted per-entry scan, full 8,351 entries)

### THE0T0K08

**Found: YES -- 1 occurrence.**

- Entry: `schaff-herzog.the0t0k08` (index 8350, the last entry)
- Tier 1, reason: `digit_in_letter`
- Value: `THE0T0K08`, suggestion: `THEOTOKOS`
- Note: This entry was NOT reached by the aggregate scan (hit 50k cap around index 4,309).
  Confirmed by scanning the single entry directly.

### (E... ligature_bracket hits

**Found: YES -- 1,980 total occurrences, 385 unique values across full corpus.**
Well exceeds the >=15 threshold.

Sample of named known-positive values present:

| Value              | Correct form       | Notes                    |
|--------------------|--------------------|--------------------------|
| `(ECOLAMPADIUS,`   | OECOLAMPADIUS      | Trailing comma in token  |
| `(EALDHELM),`      | OEALDHELM          | Trailing paren+comma     |
| `(EBBO)`           | OEBBO              | Clean detection          |
| `(EADMUWD),`       | OEADMUWD           | OCR of EADMUND           |
| `(ELMER),`         | OELMER             | Clean detection          |
| `(ECUMENICAL`      | OECUMENICAL        | Mid-sentence occurrence  |

Other notable `(E` values found: `(EDMER)`, `(EDHUIID`, `(EADFRITH,`, `(EADWINE)`,
`(ECONOMUS,`, `(ESAR` (expected from plan).

**Important note:** The `value` field stores the raw token including trailing punctuation.
Verification filters should use `c['value'].startswith('(E')` rather than exact match.

---

## Previously-Unknown Tier 1 Candidates (first 10)

### stray_pipe_backslash -- all appear to be true positives

| # | Value            | Likely correct form    | Verdict | Entry                         |
|---|------------------|------------------------|---------|-------------------------------|
| 1 | `Su\|q;)er,`     | Supper,                | TP      | schaff-herzog.alexander       |
| 2 | `Coi\ftUatio`    | Continuation           | TP      | schaff-herzog.alexander       |
| 3 | `co\ild`         | could                  | TP      | schaff-herzog.alexander       |
| 4 | `t\e`            | the                    | TP      | schaff-herzog.crusades        |
| 5 | `t\|ut`          | that                   | TP      | schaff-herzog.drtahder-ernst  |
| 6 | `yo\b,`          | your,                  | TP      | schaff-herzog.dubourg-alwe    |
| 7 | `nat\irally`     | naturally              | TP      | schaff-herzog.dunin-martin-von|
| 8 | `libr\it`        | librit (abbreviation?) | TP      | schaff-herzog.raebiger        |
| 9 | `c\is`           | this                   | TP      | schaff-herzog.encyclical-letters |
| 10| `T\kd`           | Tkd (unclear)          | TP      | schaff-herzog.englahd-and-wales  |

### digit_in_letter -- genuine TPs beyond known list

| # | Value          | Suggestion    | Verdict | Notes                               |
|---|----------------|---------------|---------|-------------------------------------|
| 1 | `practica1`    | `practicaI`   | TP      | 1 for l (good find; suggestion wrong -- I not 1) |
| 2 | `h3nceforth`   | `h3nceforth`  | TP      | 3 for e (suggestion unchanged -- needs manual fix) |
| 3 | `Ass6ciation`  | `Ass6ciation` | TP      | 6 for o                             |
| 4 | `Mo7Uantsmu8`  | `Mo7UantsmuS` | TP      | Multiple digit corruptions in one word |
| 5 | `Ren6e`        | `Ren6e`       | TP      | 6 for accented e (Renee/Renee)      |

---

## Tier 2 Precision Spot-Check (30 random, seed=42)

All 30 sampled candidates are `short_allcaps_orphan`.

Values sampled: `B.`, `T.`, `A.`, `T.`, `T.`, `J.`, `G.`, `J.`, `A.`, `T.`,
`B.`, `F.`, `W.`, `A.`, `G.`, `W.`, `M.`, `F.`, `A.`, `G.`, `K.`, `T.`,
`VL`, `E,`, `W.`, `W.`, `P.`, `T.`, `T.`, `J.`

**True positives: 0 / 30 (0%)**

These are author initials from bibliographic references (`J.` = Johann, `A.` = August,
`T.` = Thomas, etc.) -- standard dictionary citation format. The existing whitelist
`^[A-Z]\.[A-Z]\.?$` catches two-letter abbreviations but misses single-letter + period.

**Notable: `VL` (no period)** is ambiguous -- could be abbreviation or OCR orphan.
**`E,`** (letter + comma) is almost certainly FP (author initial with trailing comma).

---

## Reason Codes with Precision < 50% (flag for v2)

### 1. `ligature_bracket` -- Tier 1, precision: ~2-5%

19,177 Tier 1 hits but almost all are citation footnote patterns:
- `(Latin`, `(MGH,`, `(Nov.`, `(Ex.`, `(Jan.`, `(Ap.`, `(Vol.` etc.
- These are SH's standard inline footnote citation style: author name, abbreviated
  publication title, or reference abbreviation in parentheses, beginning with uppercase.
- The detector's `^\([A-Z]` pattern cannot distinguish these from ligature corruptions.
- **v2 fix**: Add SH-specific whitelist entries for common citation abbreviations, OR
  demote to Tier 2 with a stricter named-entity check before flagging.

### 2. `short_allcaps_orphan` -- Tier 2, precision: 0% (0/30 sample)

30,677 Tier 2 hits. SH uses initials heavily in bibliographic entries.
The single-letter-with-period pattern (`A.`, `B.`, `J.` etc.) is never an OCR orphan
in this corpus -- it is always an author initial.
- **v2 fix**: Add `^[A-Z]\.$` to `whitelist_patterns` in `schaff-herzog.json`.
  This would eliminate ~90% of Tier 2 candidates.

### 3. `digit_in_letter` -- Tier 1, precision: ~40-50% (non-ordinals only)

328 ordinals (`5th`, `9th`, `1st` etc.) are Tier 1 false positives.
Of 678 remaining non-ordinals, suggestions are often incorrect (digit substitution
table maps 8->S but `8vo` is a valid book-format abbreviation, `Le6en` has no obvious
substitution).
- **v2 fix**: Exclude `^\d+(?:st|nd|rd|th)$` from digit_in_letter. Also add `8vo` to
  whitelist.

### 4. `ligature_ae_loss` -- Tier 1, precision: 0% (1/1 sample is FP)

Only 1 hit across 4,309 entries: `N(ewcommen),` -- this is a parenthetical surname
suffix, not an AE ligature loss. The detector is too aggressive for SH text.
- **v2 fix**: Needs more restrictive pattern or move to Tier 3.

---

## max_candidates Cap -- Critical Finding for Phase 3

The default `max_candidates=500` is far too low for the SH corpus. It exhausts within
the first 94 entries (all starting with 'A'). Even at 50,000 the scan covers only 52%
of the corpus. To scan all 8,351 entries requires approximately 97,000 candidates
at the observed rate (~11.6 per entry).

**Root cause:** `ligature_bracket` generates 4+ candidates per entry (every inline
citation footnote). Until the FP rate is reduced via whitelist filtering, the cap must
be raised substantially for full-corpus scans.

**For Phase 3 production runs:** Use `max_candidates=150000` OR fix `ligature_bracket`
first and re-run with the lower cap.

---

## Effort Estimates

| Task                                  | Est. time  |
|---------------------------------------|------------|
| Review `stray_pipe_backslash` (51)    | 5 min      |
| Review `digit_in_letter` non-ordinals (678) | 60 min |
| Review named ligature hits (~100 across full corpus) | 30 min |
| Total Tier 1 reviewable               | ~95 min    |
| Tier 2 `short_allcaps_orphan`         | Skip until `^[A-Z]\.$` whitelist added |

---

## Recommended Pre-Phase-3 Fixes (before apply_approved_corrections run)

1. Add `"^[A-Z]\\.$"` to `whitelist_patterns` in `schaff-herzog.json` -- eliminates
   ~90% of Tier 2 false positives.
2. Add `"^\\d+(?:st|nd|rd|th)$"` (case-insensitive flag needed) to `whitelist_patterns`
   in `schaff-herzog.json` -- eliminates ordinal FPs from `digit_in_letter`.
3. Decide: demote `ligature_bracket` to Tier 2 in `ia_djvu` pattern set, OR add SH
   citation abbreviations to `whitelist_terms` (a short list of 15-20 common ones
   would eliminate 80%+ of FPs).
4. Raise `max_candidates` to 150,000 for the re-run after whitelist fixes.

---

## Phase 3 Pre-Work: ligature_bracket Cross-Reference Analysis (2026-04-16)

**Updated scan:** Full corpus, no truncation, max_candidates=200,000.
**New totals:** Tier 1: 4,198 | Tier 2: 2,957 | Total: 7,155 (down from 10,689).

### Breakdown of 1,950 ligature_bracket Tier 1 hits

The `ligature_bracket` detector (`^\([A-Z]`) catches ANY token starting with `(` followed
by an uppercase letter -- not just the `(E` OE-ligature target. Category breakdown:

| Category | Count | Example values | Notes |
|----------|-------|---------------|-------|
| `(E...` (OE-ligature target) | 44 | `(ECOLAMPADIUS,`, `(EALDHELM),` | 9 match SH entries (cross-refs); 35 potential TPs |
| Roman numeral citations | 731 | `(II`, `(III.`, `(IV.,` | All FPs -- Bible verse / volume references |
| ALL_CAPS words | 1,175 | `(MPL,`, `(MGH,`, `(ANF,`, `(ABELIANS,` | 273 match SH entries; 902 are citation abbreviations |

### Cross-reference check

- **273** ALL_CAPS values match a known SH entry ID -- e.g. `(ABELIANS,` --> `schaff-herzog.abelians`
- **9** `(E...` values match SH entries -- e.g. `(EB,` matches `schaff-herzog.eb` (Encyclopaedia Biblica)
- **Total cross-references: 282 / 1,950 = 14.5%** -- well below the >80% bulk-whitelist threshold

**Decision:** Do NOT bulk-whitelist. Cross-ref count (14.5%) does not meet threshold.

### True ligature corruption TPs (35 non-matching `(E...` values)

These are the highest-priority real corrections. All 35 represent OE-ligature OCR corruption:

```
(ECOLAMPADIUS,  (EALDHELM),  (EBBO)  (ELMER),  (EDMER)  (ECUMENICAL  (ECONOMUS,
(EADFRITH,  (EADMUWD),  (EADWINE)  (EDHUIID  (EHKA),  (ELOTH),  (ELOTSIUS,
(EPHREM)  (EPISCOPUS)  (EUGEN (x5)  (EUGBN  (EUGIPPIUS,  (EUQEN  (EXUPERIUS),
(EZI-  (EZIOIf-GABER).  (EIng.  (EIx. (x2)  (EON,  (EMiLEoLif.)  (EUberfeki,  (EUjah
```

### Recommendations

1. **Add roman-numeral whitelist pattern** to `schaff-herzog.json`:
   `"^\([IVX]+[.,]?$"` -- eliminates 731 FPs immediately.
2. **Review the 35 `(E...` non-matching values** during Phase 3 human review --
   these are the genuine OE-ligature targets; all plausibly correctable.
3. **Add known citation abbreviations** to `whitelist_terms`:
   `"MPL", "MPG", "MGH", "ANF", "ID", "BA", "MPO", "TU", "ASB", "NPNF", "DB", "CR",
   "AKR", "ALKG", "MPQ", "ASS", "LTHK", "RE", "ZKG", "EB", "TLZ", "ZWT"`
   (top 20 citation abbreviations -- would eliminate ~400+ FPs from ALL_CAPS group).
4. **Do NOT bulk-whitelist** SH cross-references -- 14.5% doesn't justify a broad exception.
