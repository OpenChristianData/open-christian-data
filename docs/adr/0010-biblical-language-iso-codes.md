# ADR-0010: Biblical-language ISO codes (`grc`, `hbo`, `arc`) over modern defaults

**Status:** Accepted (2026-05-15); amended 2026-05-16 (R14 — `arc`, `syr`, `cop` removed from Phase 1 schema enum; staged re-introduction rule documented)

## Context

The OCD corpus crosses nine languages: Greek, Hebrew, Aramaic, Latin, French, German, English, Syriac, Coptic. Each needs a stable ISO code that appears in block-level `language` fields, `language_segments[].language`, per-language lexicon paths (`build/lib/lexicons/<lang>.py`), per-language OCR error models (`build/lib/ocr_error_models/<lang>.yaml`), per-language transliteration rulesets, and across the catalog and schemas.

The default code per language has two candidates for several:

| Language | ISO 639-1 (modern) | ISO 639-3 (ancient / biblical) |
|---|---|---|
| Greek | `el` (Modern Greek) | `grc` (Koine / Ancient Greek) |
| Hebrew | `he` (Modern Hebrew) | `hbo` (Biblical Hebrew) |
| Aramaic | (none in 639-1; usually flagged within `he`) | `arc` (Imperial / Biblical Aramaic) |

Existing OCD stubs use the 639-1 codes (`build/lib/lexicons/el.py`, `he_latn.py`). That's accurate for *modern* Greek and Hebrew, but the corpus is overwhelmingly **biblical** (Koine NT, OT Hebrew, biblical Aramaic in Daniel / Ezra). Modern codes mislabel the actual content.

## Decision

Use biblical-language ISO codes throughout the architecture where they differ from modern defaults. The codes are introduced in two cohorts: the **Phase 1 active set** (real corpus input, full per-language artefact set) and the **staged-introduction set** (re-introduced when real corpus input arrives in a later phase, with artefacts shipped in the same change).

**Phase 1 active set** (six languages):

- **`grc`** for Koine / Ancient Greek (replaces `el`).
- **`hbo`** for Biblical Hebrew (replaces `he`).
- **`la`** for Latin.
- **`en`** for English.
- **`fr`** for French.
- **`de`** for German.

**Staged-introduction set** (re-introduced in the phase that brings real corpus input):

- **`arc`** for Biblical / Imperial Aramaic — distinct from Hebrew. Re-introduced when a phase brings real Aramaic content (likely Phase 2 patristic ingestion, Phase 4 commentary content on Daniel/Ezra, or sooner if a Phase 1 corpus survey identifies real Aramaic tokens in Schaff-Herzog).
- **`syr`** for Syriac. Re-introduced when patristic Syriac ingestion lands.
- **`cop`** for Coptic. Re-introduced when Coptic patristic ingestion lands.

The lexicon directory follows: `build/lib/lexicons/grc.py`, `hbo_latn.py` (transliterated Hebrew), etc. OCR error models, transliteration rulesets, language tags in block schemas, catalog entries, and Reviewer UI all use these codes consistently for the Phase 1 active set.

### Staged re-introduction rule

A staged-introduction language re-enters the schema enum *only when real corpus input has been verified*. The change that re-introduces a language ships, in the same commit:

1. Verified corpus citations of the language (at least one rendering containing real input the producer chain will fire on).
2. The per-language artefacts the architecture requires for that language: lexicon (when the language uses Latin script for source-transliterated content), transliteration ruleset, OCR error model, language-detection wiring as needed.
3. Tests that exercise the producer chain on the verified real input, not synthetic-only fixtures.
4. An ADR-0010 amendment recording the re-introduction with the corpus evidence.

This rule guarantees ADR-0008 holds at all times: every schema enum value has a producer firing on real input and a consumer using the output. There is no "designed-but-not-built" lane; staged-introduction codes are simply not in the architecture until they are.

## Consequences

**Positive**

- The dataset's `language` tags match what's actually in the corpus. A consumer filtering for `grc` knows they're getting biblical / Koine Greek content, not modern Greek.
- ISO 639-3 codes are tooling-supported (HuggingFace recognises them; most language-detection libraries handle them).
- New contributors arriving at the codebase don't need to learn that `el` "really means" Koine Greek in OCD context — the code says what it means.
- Per-language artefacts (lexicon, OCR error model, transliteration ruleset) align with the linguistic distinction that matters for our work: ancient / biblical vocabulary, not modern.
- The staged-introduction rule keeps ADR-0008 strictly satisfied: a language code exists in the schema enum only when it has real Phase 1 input, a real producer firing on that input, and a real consumer downstream. No designed-but-not-built lanes. The Phase 2+ growth path is evidence-triggered, not pre-promised.

**Negative**

- Existing OCD stubs at `build/lib/lexicons/el.py` and `he_latn.py` must be renamed (rename is straightforward, but every reference in code and plan changes too).
- A consumer pulling our dataset who expected `el` / `he` (because they're the conventional 2-letter codes) has to adjust. We surface the choice in the dataset card.
- ISO 639-3 codes are less recognisable to a reader who only knows 639-1. The dataset card and CONTEXT.md make the mapping explicit.
- The Phase 1 schema enum will grow over time as staged languages re-enter. Consumers who pin to a specific Phase 1 enum will see additions; this is documented in the dataset card. Phase 1 deliberately does not push to HuggingFace publicly (locked plan §HuggingFace publication), so internal Phase 1 enum changes are not consumer-visible until Phase 3's first soft-launch.

## Alternatives considered

- **Keep `el` and `he`; document that "in OCD they mean Koine and Biblical Hebrew."** Rejected. Codes-with-special-local-meanings break tooling that resolves codes against ISO references. The downstream consumer with general-purpose language tooling expects standard semantics.
- **Use 639-3 codes universally — `eng`, `lat`, `fra`, `deu`, `ell`, `heb` rather than the 639-1 forms.** Considered. Rejected because the 639-1 forms are more familiar for the modern languages (English, French, German, Latin) and there's no biblical-vs-modern distinction for those. Using `en` + `grc` is a deliberate mix; using `eng` + `grc` would normalise but at the cost of familiarity. The mix is intentional: 639-1 where it's accurate and conventional; 639-3 where the biblical / ancient distinction matters.
- **Defer to ISO 639-1 across the board for simplicity.** Rejected. Accuracy of what's actually in the corpus matters more than across-the-board consistency with the more familiar code set.
