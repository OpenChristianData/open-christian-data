# DESIGN — Gold-Free Corrector Stack (Claude, independent half)

**Status:** Design proposal. Independent design under the cross-architect pattern (DEL-02);
written without reading the Codex half. American English; relative paths only.

Implements the brief `docs/DESIGN_BRIEF_gold_free_corrector.md` (components P1–P5, hard
requirements HR1–HR8), grounded in `build/lib/wct_builder.py`, `build/lib/s3_reconciler.py`,
ADR-0014 (`docs/adr/0014-composed-readings.md`), ADR-0015 (`docs/adr/0015-surrogate-as-validator.md`),
`docs/BUILD_ROADMAP_2026-06-05.md`, `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md`, and the real
`reports/wct/vol_01/page_0010.json` / `reports/reconciled/vol_01/page_0010.json` outputs.

---

## Decision brief (read this first)

1. **The corrector is a new layer between the WCT and the reconciler, not an edit to either.**
   The WCT contract is "Layer 1 makes no irreversible choice" (`wct_builder.py` docstring,
   Boundary note). Voting *is* a choice, so it must not move into `build_wct_page`. A new
   package `build/lib/gold_free_corrector/` consumes a frozen WCT page and emits a *corrected
   page* (voted reading + character provenance + derivation level + scores per position). The
   reconciler gains a second entry point, `reconcile_corrected`, that consumes the corrected
   page; `reconcile_degraded` stays untouched as the embargo fallback.

2. **Voting weights are family-level, never engine-level.** The real `page_0010` ran five
   families but the historical fixture carried five ABBYY lineages. `_best_candidate` already
   counts `attesting_families` first (`s3_reconciler.py:163`). Per-character voting inherits
   that: a character's support is the count of *distinct families* that attested it. Correlated
   engine agreement is not trust (HR5).

3. **Every level is built; none is forbidden; publication is a measured threshold, not a
   doctrine** (HR2). The corrector emits L0–L3 readings for every eligible position. The
   decision policy assigns an action (auto-accept / flag / route) by comparing each level's
   *surrogate-measured* false-correction rate against a parameter, defaulting to "route
   everything above L0 until the surrogate sets the bar" (HR6).

4. **Protected classes are a routing override applied before any score is read** (HR5). Proper
   names, numbers, dates, Scripture references, Greek, Hebrew route to human/VLM regardless of
   agreement. This is the real-word-error reservoir; the corrector must never auto-accept here.

5. **The corrector is gold-free** (HR7). Its lexicon, LM, and thresholds-input all derive from
   multi-engine consensus + public-domain resources. Human gold and the JE surrogate are
   *validators*, never runtime inputs (ADR-0015).

---

## 1. Architecture

### 1.1 Where the layer sits

```
S1 engines ─► render_s2 ─► build_wct_page ──────────────►  WCT page (frozen Layer-1 contract)
                                                              │
                                       ┌──────────────────────┘
                                       ▼
                          build/lib/gold_free_corrector/   (NEW — this design)
                            P1 column_vote     ─┐
                            P2 lexicality       ├─► CorrectedPage (per-position:
                            P3 lm_rescore       │      voted reading, char provenance,
                            P4 decide           │      L0..L3 candidates, scores, action)
                            P5 select          ─┘
                                       │
                                       ▼
                          s3_reconciler.reconcile_corrected   (NEW entry point alongside
                                       │                        reconcile_degraded)
                                       ▼
                          reconciled_record + matrix candidates + reviewer queue
                                       │
                                       ▼
                          surrogate harness  (validation only — JE 1906, ADR-0015)
```

The corrector reads only fields the WCT already emits: `positions[].candidate_set[]`
(`candidate_id`, `raw_reading`, `candidate_key`, `attesting_engines`, `attesting_families`,
`normalisation_applied`), `positions[].span_records[]`, `positions[].script`,
`positions[].hyphenation`, `positions[].alignment_confidence`, `positions[].reference_bbox`,
and `available_engines[].family`. Confirmed present in `reports/wct/vol_01/page_0010.json`.

### 1.2 Data object the corrector adds

Per position, the corrector produces a `CorrectedPosition`:

```python
@dataclass(frozen=True)
class CharProvenance:
    char: str                       # the voted character (or "" for a voted deletion)
    families: tuple[str, ...]       # distinct WCT families attesting this char
    method: str                     # "engine" | "confusion_lexicon" | "lm" | "impossible_filtered"

@dataclass(frozen=True)
class LevelReading:
    level: str                      # "L0" | "L1" | "L2" | "L3"
    text: str
    char_provenance: tuple[CharProvenance, ...]
    agreement: float                # P1 column-agreement score in [0,1]
    lexicality: float | None        # P2 score; None if not run (protected class)
    lm_score: float | None          # P3 score; None if not run

@dataclass(frozen=True)
class CorrectedPosition:
    position_id: str
    protected_class: str | None     # None | "proper_name" | "number" | "date" |
                                    #   "scripture_ref" | "greek" | "hebrew"
    readings: dict[str, LevelReading]   # the levels that were derivable
    action: str                     # "auto_accept" | "flag" | "route_human" | "route_vlm"
    action_level: str | None        # which level was accepted/flagged; None if routed
    derivation_method: str          # the tag carried onto the canonical token (HR2)
```

`CorrectedPage` is `{page_id, positions: list[CorrectedPosition], corrector_version,
thresholds_id}`. It is a new sidecar schema `schemas/v1/corrected-page-v1.schema.json` (this
design adds it; see §7 schema work). It never overwrites the WCT.

### 1.3 Why a new schema rather than reusing the WCT

The WCT `candidate_set` records *what engines said*; the corrected page records *what the
machine decided and why*. Conflating them breaks the Layer-1 boundary and the determinism the
WCT guards (`PY-09` rep_key fix). Keeping them separate means a corrector regression can never
corrupt the alignment, and the surrogate harness can diff corrector versions by re-running P1–P5
against the same frozen WCT.

---

## 2. Component interfaces

### P1 — Character-column voting

**Module:** `build/lib/gold_free_corrector/column_vote.py`

**Inputs:** one WCT `position` dict. Uses `candidate_set[]` and the WCT confusion machinery.

**Outputs:** an `L1` `LevelReading` (when every voted character is engine-attested) plus the raw
column structure used downstream by P2/P3, and the `agreement` score.

**Algorithm:**

1. Collect the candidate strings `S = [c["candidate_key"] for c in candidate_set]` with each
   candidate's `attesting_families` as its weight set. (Use `candidate_key`, the
   grouping-normalized form already emitted, so we vote over comparable strings;
   `wct_builder.normalise_candidate` produced it.)
2. **Multiple-sequence character alignment.** Build a progressive MSA of the candidate strings,
   exactly mirroring the WCT's own progressive scheme (`wct_builder._align_engines`) but at the
   *character* grain: seed with the candidate having the most attesting families, then align each
   remaining candidate to the growing spine with Needleman–Wunsch. Substitution cost is the WCT's
   own per-character confusion cost — reuse `_sub_cost(a, b)` (`wct_builder.py:171`); see §3.1 for
   the one-line public accessor this requires. Gap cost reuses `GAP_PENALTY` (`wct_builder.py:67`).
   This is HR1: the same confusion costs, one grain finer, no new alignment design.
3. **Per-column vote.** For each character column, tally support by *distinct family*. The winner
   is the character with the most distinct attesting families; ties broken by total confusion-cost
   proximity to the column's other characters, then lexicographically (determinism, `PY-09`).
4. **Impossible-character filter.** Before tallying, drop any candidate-character that is a
   non-alphabetic glyph sitting in an alphabetic column (column where ≥1 family attests a letter).
   The real `▲belavd`/`Abelard` case (`page_0010` l000 p000) is exactly this: `▲` is filtered, the
   column resolves to `A` from the family that attested a letter. Filtered characters are recorded
   as `CharProvenance(method="impossible_filtered")` against the *losing* candidate, not the
   winner — provenance stays complete (HR3). "Alphabetic context" is script-aware: in a
   `routing="biblical-language-lane"` position the alphabet is the script's, but those positions
   are protected (P4) and never auto-accepted, so the filter there only annotates.
5. **Agreement score** = mean over columns of (winning family count / total distinct families
   attesting the column). 1.0 = every family agreed every column.

**Parameters:** `IMPOSSIBLE_GLYPH_CLASS` (regex of glyphs always illegal in Latin alphabetic
context, e.g. geometric shapes, box-drawing); `MIN_COLUMN_FAMILIES = 1`; reuse `GAP_PENALTY`,
`SAME_SLOT_THRESHOLD` from `wct_builder`.

**Integration point:** consumes `build_wct_page` output; imports `confusion_distance`
(`wct_builder.py:202`) and the new `substitution_cost` accessor (§3.1). Does **not** modify
`wct_builder`.

**Provenance:** every winning character carries the set of families that attested it and
`method="engine"`. This is the L1 character-provenance trail (HR3).

### P2 — Lexicality rescore

**Module:** `build/lib/gold_free_corrector/lexicality.py`

**Inputs:** the P1 voted reading (and the per-column alternates, so P2 can propose a small-edit
fix when the vote is sub-lexical → L2). The domain lexicon.

**Outputs:** `lexicality` score in [0,1] on the L1 reading; optionally an `L2` `LevelReading`
when no engine attested a character but a small confusion-distance edit reaches a known word.

**Lexicon construction (gold-free, HR7):** built once per corpus, cached as
`build/lib/gold_free_corrector/lexicon/<corpus>.txt` with provenance:

- **Consensus words** — every WCT position across the already-built corpus where ≥2 *distinct
  families* agree on a `candidate_key` that is alphabetic and length ≥ 3. This is the corpus's
  own vocabulary, with zero human input. Source-counted so rare-but-real words survive.
- **Public-domain dictionaries** — Webster's 1913 (public domain) for English; a public-domain
  Latin headword list for the Latin lane. Greek/Hebrew lexica are *not* used to auto-accept
  (those scripts are protected, HR5) — they only annotate.
- **Confusion-model awareness** — `build/lib/ocr_error_models/{en,la}.yaml` supply the
  source→target pairs (e.g. `rn→m`, `cl→d`, long-s→f) used to generate the *candidate* small
  edits in the L2 path, not as lexicon entries.

**Algorithm:** (1) membership test of the L1 reading against the lexicon → real-word corroboration
signal. (2) If sub-lexical, enumerate edits within confusion-distance ≤ `LEX_EDIT_BUDGET` using the
confusion pairs, keep only edits landing on a lexicon word, score by `1 - confusion_distance`; the
best becomes the L2 reading with the corrected characters tagged `method="confusion_lexicon"` and
`families=()` (no engine attested them — that is what makes it L2, HR2).

**Parameters:** `LEX_EDIT_BUDGET = 1.0` (one unit substitution or one multi-char confusion);
`MIN_CONSENSUS_FAMILIES = 2`; `MIN_WORD_LEN = 3`.

**Integration point:** standalone; consumed by P4. Reuses the confusion pairs from
`wct_builder` and the YAML loaded by `wct_builder._load_ocr_model`.

**Real-word-error caution (HR4):** lexicality *raises* confidence in real words — including
real-word errors. A lexically-valid reading is not safe by itself; it is only one signal into P4,
and the surrogate measures the real-word-error rate it lets through.

### P3 — In-corpus LM rescore

**Module:** `build/lib/gold_free_corrector/lm_rescore.py`

**Inputs:** the L1/L2 reading in its position context (the reading plus the voted readings of the
N neighbors in `reading_order`). The trained in-corpus LM.

**Outputs:** `lm_score` in [0,1] (normalized perplexity rank); optionally an `L3` `LevelReading`
when the LM proposes a context character no engine attested and no lexicon edit reached — tagged
`method="lm"`, the only path by which a model authors a canonical character (HR8).

**Model:** a cheap character n-gram (order 5) plus a word bigram, add-k smoothed, trained **only**
on high-consensus consensus text: positions where agreement ≥ `LM_TRAIN_AGREEMENT` and the reading
is lexical. Pure-Python, deterministic, no heavy dependency; KenLM is an optional accelerator
behind the same interface. Training text is regenerated, never hand-curated (HR7). "Ranks
plausibility; never authors free text" (brief P3) — the LM scores and, on the explicit L3 path,
proposes a single character that is then provenance-tagged and surrogate-measured, never emitted
silently (HR8).

**Algorithm:** score the candidate string's char-LM log-prob, normalize against the position's
other level readings to a [0,1] rank. The L3 proposal is gated: only fires when L0–L2 are all
absent or sub-lexical, the LM's top completion is lexical, and the edit is within
`LM_EDIT_BUDGET`.

**Parameters:** `LM_ORDER = 5`; `LM_TRAIN_AGREEMENT = 0.9`; `LM_EDIT_BUDGET = 1`;
`LM_ADD_K = 0.01`.

**Integration point:** standalone; consumed by P4. Training corpus is the WCT/corrected output of
already-processed pages — a feedback the design bootstraps from L0 consensus only, so no circularity
with the corrector's own L1–L3 output.

### P4 — Decision policy (the canonical-text ceiling)

**Module:** `build/lib/gold_free_corrector/decide.py`

**Inputs:** a position's protected-class label, its L0–L3 `LevelReading`s with agreement,
lexicality, lm scores, and the threshold table.

**Outputs:** the `action` and `action_level`, plus the `derivation_method` tag that travels onto
the canonical token (HR2).

**Levels** (ADR-0014; HR2 — all built, none forbidden):

| Level | Definition | Provenance of the deciding chars |
|---|---|---|
| L0 | attested whole-word: one candidate is a single family-agreed whole word that is lexical | `observed` |
| L1 | character-voted: every character attested by ≥1 family (P1) | per-char `engine` |
| L2 | confusion+lexicon fix: ≥1 char no engine got, small-distance to a known word (P2) | `confusion_lexicon` |
| L3 | LM/context-proposed: ≥1 char proposed by the LM (P3) | `lm` |

**Protected-class override (HR5), applied first:** if `protected_class is not None`,
`action = route_human` (or `route_vlm` for Greek/Hebrew image checks), regardless of every score.
No level is auto-accepted for a protected class.

**Decision (parameterized, HR2/HR6):**

```
level = highest level present for this position           # L0 > L1 > L2 > L3
t = thresholds[region_class][level]                       # {accept, flag} false-corr bounds
score = combine(agreement, lexicality, lm_score)          # weighted; weights are PARAMETERS
if surrogate_false_correction[level][region_class] <= t.accept and score >= t.score_accept:
    action = auto_accept
elif surrogate_false_correction[level][region_class] <= t.flag:
    action = flag                                          # published-but-flagged
else:
    action = route_human
```

`surrogate_false_correction` is loaded from the harness output (§5). **Default thresholds ship
the whole table at `accept = 0.0`**, i.e. nothing auto-accepts until the surrogate fills the table
— the embargo's valid core (HR6: set accept where surrogate false-correction ~ 0.1%). The policy is
a function of a parameter file `config/corrector_thresholds.json`, never a hardcoded doctrine.

**`combine()` weights are themselves parameters** (`config/corrector_weights.json`), defaulting to
agreement-dominant. They are tuned only against the surrogate, never human gold.

**Integration point:** P4's output `derivation_method` and `action` are what `reconcile_corrected`
reads (§4).

### P5 — Active-learning selection

**Module:** `build/lib/gold_free_corrector/select.py`

**Inputs:** all `CorrectedPosition`s for a volume whose `action` is `route_human`/`route_vlm`
(the review residue), plus their agreement/lexicality/lm scores and `candidate_set` size.

**Outputs:** the residue ranked by informativeness, written to the reviewer queue order.

**Algorithm (Reul 2018 maximal-disagreement, +16%):** rank by an uncertainty score that is highest
where the engines maximally disagree *and* the corrector is least sure:
`informativeness = (1 - agreement) * family_disagreement_entropy * level_penalty`, where
`level_penalty` upweights L2/L3 (synthesized = higher review value) and protected classes are
pinned to the top regardless. Select the top-K to form the human gold sample so the ~300–500
adjudications (`docs/PIPELINE_BUILD_STATE.md`) are drawn from the most informative positions, not
uniformly.

**Parameters:** `GOLD_SAMPLE_K = 500`; `PROTECTED_PRIORITY = True`; entropy floor for ties.

**Integration point:** consumes the corrected page; writes the ranking into the
`reviewer_queue` order that `reconcile_corrected` emits (the existing reconciler already builds a
`reviewer_queue` list — `s3_reconciler.py:322`; P5 sets its order).

---

## 3. Exact integration points in the WCT / reconciler flow

### 3.1 WCT side — one non-breaking export, no logic change (HR1)

P1 needs the per-character substitution cost. `wct_builder._sub_cost(a, b)` (line 171) is private.
Add a one-line public alias so the corrector imports it without reaching into a private name:

```python
# wct_builder.py — public accessor; same costs, no behavior change.
def substitution_cost(a: str, b: str) -> float:
    return _sub_cost(a, b)
```

P1 also imports the existing public `confusion_distance` (line 202). Nothing in `build_wct_page`,
`_align_engines`, `_emit_position`, or `_candidate_sets` changes. The WCT fixture outputs stay
byte-identical (the determinism tests `tests/test_wct_determinism.py`,
`tests/probe_wct_builder_determinism.py` must still pass unchanged — that is the HR1 guard).

### 3.2 Reconciler side — a new entry point beside the degraded stub

`reconcile_degraded(wct_page, work_meta, ...)` (`s3_reconciler.py:189`) stays exactly as-is (the
embargo fallback). Add:

```python
def reconcile_corrected(
    wct_page: dict,
    corrected_page: dict,          # CorrectedPage from the gold_free_corrector
    work_meta: dict,
    *,
    occurred_at: str,
    thresholds_id: str,
) -> ReconcileResult:
    ...
```

It reuses the block-assembly, region-class stamping (`assign_region_class`,
`validate_region_class_stamp`), and reviewer-queue machinery already in the module. The two
behavioral differences from `reconcile_degraded`:

1. **Reading selection.** Where `reconcile_degraded` calls `_best_candidate` (line 254) and routes
   *everything* (all weights 0.0), `reconcile_corrected` reads the `CorrectedPosition.action`:
   - `auto_accept` → the voted reading becomes the block's `original_text` token; the disagreement
     `kind` records `corrector_auto_accept` and `chosen_reading_attested_by` carries the attesting
     families from char provenance.
   - `flag` → token is placed but the disagreement is marked `corrector_flagged` and
     `external_check_absent = True` so it never publishes unflagged (HR6).
   - `route_human` / `route_vlm` → identical to today's degraded routing.
2. **Matrix events.** Auto-accepted/flagged positions still emit **`not_measurement_eligible`**
   matrix candidates in the gold-free phase — the corrector is validated by the *surrogate*, not by
   the matrix; the matrix stays gold-gated (`_assert_no_premature_matrix_labels`,
   `s3_reconciler.py:425` is preserved verbatim). The corrector writes its derivation method and
   surrogate-measured rate into a new `post_alignment_signals` entry (the module already carries
   `post_alignment_signals`, line 101/286), keeping the lock-section-2 layer boundary intact.

### 3.3 Canonical-token fields the schema must gain

`reconciled_record.schema.json` today has no `source_raw_origin` / `derivation` / character
provenance (verified: 0 occurrences). The composed-reading model (ADR-0014) needs them. This design
adds, on the disagreement/token level:

- `derivation_method`: enum `observed | composed_l1 | composed_l2 | composed_l3 | human`
- `character_provenance`: array of `{char, families[], method}`
- `synthesized`: bool (true for L1–L3)
- `surrogate_false_correction`: number|null (the measured rate for this method/region at decision
  time)

These are additive; the gate's falsifiable check changes from "zero unattested tokens" to "zero
tokens lacking character provenance" (ADR-0014 Consequences). A code-level guard
`validate_character_provenance(record)` mirrors `validate_region_class_stamp`
(`s3_reconciler.py:138`) — every `synthesized` token must carry complete `character_provenance`.

---

## 4. Level 0–3 decision policy (parameterized)

Single source of truth: `config/corrector_thresholds.json`, shape
`{region_class: {level: {accept, flag, score_accept}}}`. Loaded by P4; never hardcoded.

| Field | Meaning | Default | Set by |
|---|---|---|---|
| `accept` | max surrogate false-correction to auto-accept | `0.0` (route until measured) | surrogate harness (§5), target ~0.001 (HR6) |
| `flag` | max surrogate false-correction to publish-flagged | `0.0` | surrogate harness |
| `score_accept` | min combined P1/P2/P3 score to auto-accept | `1.0` | surrogate sweep |

**Region-class keys** come from the existing `region_class` enum (`bibliography_entry`, `body`,
`footnote`, `headword`, `foreign_language_greek`, `foreign_language_hebrew`, …) so the policy is
per-region as HR6 requires ("threshold set per region class", roadmap §2). Greek/Hebrew region
classes are pinned to `route` at every level (HR5).

**Worked example (`page_0010` l000 p000, `Abelard` vs `▲belavd`):** P1 filters `▲`, votes `Abelard`
(L0 — tesseract attested it whole and it is lexical, but it is also a *proper name* → protected
class → `route_human` regardless). This is the HR5 reservoir in action: an apparently easy win is
still routed because proper names are where real-word errors hide. Contrast `fulfil` vs `fulfl`
(l005 p004): body common word, L1 voted `fulfil`, not protected → eligible for auto-accept once the
surrogate fills the L1/body threshold.

---

## 5. Surrogate measurement harness (HR4, HR6)

**Module:** `build/tools/ocr_pipeline/measure_corrector_surrogate.py`

**Reference:** Jewish Encyclopedia 1906 — paired diplomatic transcription + same-edition facsimiles
(ADR-0015, `docs/JE_SURROGATE_FINDINGS.md`). Non-circular: the corrector never sees the diplomatic
text; the harness does, only to score.

**Procedure:**
1. Run S1→WCT→corrector on JE facsimile pages to produce `CorrectedPage`s.
2. Align each corrected position to the JE diplomatic token (the same WCT alignment machinery, or a
   simple positional align where JE provides token offsets).
3. Per `(level, region_class)`, compute the three metrics below.
4. Emit `reports/surrogate/corrector_rates.json` keyed `{level: {region_class: {…}}}`, which is
   exactly the table P4 loads as `surrogate_false_correction`.

**Metrics, per level and region class:**

- **False-correction rate** = corrector changed a position whose engine consensus was already
  right, or produced a wrong reading where it auto-accepted. Denominator = auto-accepted positions.
  This is the number the accept-threshold targets at ~0.1% (HR6).
- **Coverage** = fraction of positions the level can auto-accept.
- **Real-word-error rate (HR4 — first-class, distinct from CER):** of the corrector's auto-accepted
  outputs, the fraction where `output ∈ lexicon` **AND** `output != JE_diplomatic`. Every error is
  decomposed into **non-word** (output not a lexical word — the lexical/LM filters catch these) vs
  **real-word** (output is a valid word but wrong — the dangerous class the filters are blind to).
  Reported as its own column per level, never folded into CER.

```python
def classify_error(output: str, gold: str, lexicon: Lexicon) -> str:
    if output == gold:
        return "correct"
    return "real_word_error" if lexicon.contains(output) else "non_word_error"
```

**Standing oracle (ADR-0015 Negative):** the harness re-runs on every corrector change; a level
whose real-word-error rate rises above its region's bound is demoted from `auto_accept` to `flag`
or `route` by regenerating the threshold table — no code change, a parameter regeneration.

**Why real-word-error is measured separately (Levchenko 2025, synthesis finding 4/5):** aggressive
L2/L3 correction injects real-word errors that CER hides (a one-character "fix" from a correct word
to another correct word is invisible to non-word filters and to perplexity). HR4 forces it into the
open as the gating metric for the synthesized tiers.

---

## 6. Risks and open questions

| # | Risk | Mitigation / open question |
|---|---|---|
| R1 | **Correlated-family agreement on real-word errors** (HR5 core). Two families share a training corpus and agree on a wrong real word. | Family-level voting helps but does not prove independence; `family_independence.py` must report low same-wrong-string rate before any auto-accept threshold > 0 is set. Open: is five families enough independence for body text? |
| R2 | **Lexicon contamination.** Consensus-word lexicon ingests a consensus *error*, then blesses it as real. | `MIN_CONSENSUS_FAMILIES = 2` + `MIN_WORD_LEN = 3`; cross-check against PD dictionary; surrogate real-word-error rate is the backstop. |
| R3 | **In-corpus LM learns the corpus's systematic OCR errors** and proposes them as L3. | Train only on agreement ≥ 0.9 lexical text; L3 gated to single-char edits landing on lexicon words; L3 default threshold = route. |
| R4 | **Impossible-character filter is script-naive.** A legitimate non-Latin glyph in a mixed position is wrongly filtered. | Filter only fires in `routing="normal-latin"` positions; mixed/biblical lanes annotate, never filter-then-accept (they are protected). |
| R5 | **Proper-name detection is itself error-prone** (the protected-class gate depends on it). | Conservative recall-first detector (capitalized non-sentence-initial tokens, gazetteer of consensus capitalized words, number/date regex, Scripture-ref regex). False *positives* only cost review time; false *negatives* are the danger → tune for recall. Open: build the Scripture-reference detector from the existing citation parser in `build/lib/`? |
| R6 | **Surrogate edition mismatch.** JE diplomatic not truly diplomatic to its facsimile. | ADR-0015 facsimile spot-check before adoption; `docs/JE_SURROGATE_FINDINGS.md` records it. |
| R7 | **Threshold table overfits to JE** (a single surrogate). | Thresholds are per-region and conservative; a second surrogate or the human gold set cross-validates before any threshold is loosened. |
| R8 | **Schema migration** of `reconciled_record` for character provenance touches downstream consumers. | Additive fields + `validate_character_provenance` guard; `TEST-03` grep of `build/` for every consumer in the same change. |

**Contested calls made (stated per the brief):** new package vs. extending the reconciler → new
package + new `reconcile_corrected` entry point (keeps the embargo fallback intact). Family-level
vs engine-level voting → family-level (matches `_best_candidate`, honors HR5). Pure-Python LM vs
KenLM → pure-Python default, KenLM optional (no heavy dep, deterministic). Voting lives outside the
WCT → yes, to preserve the Layer-1 no-irreversible-choice boundary.

---

## 7. Failing-first test inventory (TDD contract — TEST-16)

Each test names the architectural slot it covers and its failing-first assertion. Per the project
TDD contract these are written-failed-then-satisfied; a phase is incomplete until each has gone
RED→GREEN. New parser/module rule (CLAUDE.md): a `tests/test_<module>.py` accompanies each module.

### P1 — `tests/test_corrector_column_vote.py`
- `test_reuses_wct_substitution_cost` — slot: HR1 cost reuse. RED: import of `wct_builder.substitution_cost` fails (accessor not yet added). GREEN once §3.1 alias exists and P1 calls it.
- `test_votes_abelard_over_triangle_belavd` — slot: P1 vote + impossible filter. Fixture = `page_0010` l000 p000 (`Abelard` / `▲belavd`). RED: voted reading != `Abelard`. GREEN: `▲` filtered, column resolves `Abelard`.
- `test_char_provenance_complete_for_every_voted_char` — slot: HR3. RED: a voted char has empty `families` and no `method`.
- `test_impossible_filter_only_fires_in_latin_context` — slot: R4. RED: a glyph filtered inside a `biblical-language-lane` position.
- `test_vote_is_deterministic_across_hashseed` — slot: PY-09. RED: output differs under `PYTHONHASHSEED=0` vs `1` on a family-count tie.

### P2 — `tests/test_corrector_lexicality.py`
- `test_consensus_lexicon_excludes_singletons` — slot: HR7 lexicon build. RED: a single-family word enters the lexicon.
- `test_l2_proposes_rn_to_m_fix` — slot: P2 confusion+lexicon. Input `rnodern`. RED: no L2 reading `modern`; GREEN: L2 with the `m` char tagged `confusion_lexicon`, `families=()`.
- `test_l2_reading_has_no_engine_families_on_fixed_char` — slot: HR2 level distinction. RED: a confusion-fixed char claims engine attestation.
- `test_lexicality_flags_realword_but_does_not_auto_accept` — slot: HR4 caution. RED: a lexical reading is auto-accepted on lexicality alone.

### P3 — `tests/test_corrector_lm_rescore.py`
- `test_lm_trains_only_on_high_agreement_text` — slot: HR7/R3. RED: a low-agreement position contributes to LM training counts.
- `test_l3_only_proposes_single_char_on_lexicon_word` — slot: HR8. RED: L3 emits a multi-char free-text completion, or a non-lexicon word.
- `test_lm_never_emits_silent_freetext` — slot: HR8 invariant. RED: an L3 reading exists with no `method="lm"` provenance tag.

### P4 — `tests/test_corrector_decide.py`
- `test_protected_class_routes_regardless_of_score` — slot: HR5. Fixture = `Abelard` (proper name). RED: `action == auto_accept` instead of `route_human`.
- `test_greek_hebrew_route_to_vlm_every_level` — slot: HR5. RED: a Greek position auto-accepts at any level.
- `test_default_thresholds_route_everything` — slot: HR6 embargo default. RED: any position auto-accepts with the shipped (all-zero) threshold table.
- `test_accept_requires_surrogate_rate_below_bound` — slot: HR6. RED: auto-accept fires when `surrogate_false_correction[level][region] > accept`.
- `test_derivation_method_tag_present_on_every_decision` — slot: HR2. RED: an accepted token lacks `derivation_method`.

### P5 — `tests/test_corrector_select.py`
- `test_residue_ranked_by_disagreement` — slot: Reul active learning. RED: a high-agreement position outranks a maximal-disagreement one.
- `test_protected_class_pinned_to_top` — slot: HR5/P5. RED: a protected position ranks below a body position.

### Reconciler integration — `tests/test_reconcile_corrected.py`
- `test_reconcile_degraded_unchanged` — slot: embargo fallback intact. RED: `reconcile_degraded` output differs from the committed `reports/reconciled/vol_01/page_0010.json` baseline.
- `test_auto_accept_writes_voted_reading` — slot: §3.2. RED: an `auto_accept` position's voted reading is absent from the block `original_text`.
- `test_flag_sets_external_check_absent` — slot: HR6. RED: a `flag` position publishes without `external_check_absent`.
- `test_matrix_stays_not_measurement_eligible` — slot: lock section 2. RED: a corrected position emits a `labels_emitted` matrix candidate (must still hit `_assert_no_premature_matrix_labels`).
- `test_character_provenance_guard_rejects_bare_synthesized_token` — slot: ADR-0014 new invariant. RED: a `synthesized` token with empty `character_provenance` passes `validate_character_provenance`.

### Surrogate harness — `tests/test_measure_corrector_surrogate.py`
- `test_real_word_error_distinct_from_cer` — slot: HR4. RED: error classification folds real-word errors into CER instead of reporting them separately.
- `test_classify_error_realword_vs_nonword` — slot: HR4. Inputs `(output="modem", gold="modern")` (real-word) and `(output="m0dern", gold="modern")` (non-word). RED: misclassification of either.
- `test_false_correction_only_counts_auto_accepted` — slot: §5 denominator. RED: routed/flagged positions counted in the false-correction denominator.
- `test_thresholds_output_shape_matches_p4_loader` — slot: §4/§5 contract. RED: harness output keys don't match `{level: {region_class: {...}}}` P4 reads.

### Schema — `tests/test_corrected_page_schema.py` / `tests/test_reconciled_record_provenance.py`
- `test_corrected_page_v1_validates_real_page` — slot: §1.2 new schema. RED: a `CorrectedPage` built from `page_0010` fails `corrected-page-v1.schema.json`.
- `test_reconciled_record_accepts_character_provenance` — slot: §3.3 additive fields. RED: an L1 token with `character_provenance` fails schema validation.

---

## 8. Build sequence (informative, not part of the deliverable contract)

P1 → P2 → P3 in parallel after P1 → P4 (needs P1–P3 + threshold loader) → surrogate harness (fills
the table P4 reads) → P5 (consumes the corrected page). The schema work (§1.2, §3.3) lands before
the reconciler integration. Per-component build prompts are authored after this design lands and
its sibling Codex design is reconciled (roadmap §9, DEL-02 step 4).
