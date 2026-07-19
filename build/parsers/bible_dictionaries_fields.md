# Bible dictionary structured-field census

Audit date: 2026-07-16  
Parser: `build/parsers/bible_dictionaries.py`  
Upstream: `raw/bible_dictionaries/*.jsonl` from JWBickel/BibleDictionaries

This rationale lives beside the parser because it records source-to-schema
mapping decisions, not tradition or work classification.

## Full upstream field census

The census read every non-empty JSONL record, not a sample. Each source has the
same exact top-level field set:

| Source | Records | Exact keys | `term` present | `definitions` present |
|---|---:|---|---:|---:|
| `eastons.jsonl` | 3,963 | `term`, `definitions` | 3,963 | 3,963 |
| `smiths.jsonl` | 4,560 | `term`, `definitions` | 4,560 | 4,560 |
| `hitchcocks.jsonl` | 2,622 | `term`, `definitions` | 2,622 | 2,622 |
| `torreys.jsonl` | 623 | `term`, `definitions` | 623 | 623 |

No record in any of the four full files carries an explicit
`alt_terms`/`alt_topics`, `scripture_references`, or `related_terms`/
`related_topics` key. The latter apparatus is nevertheless present inline in
definition strings and is mapped below.

## Source-to-schema mapping

### Easton's, Smith's, and Hitchcock's (`reference_entry`)

- `term` maps to the schema `term` field.
- `definitions` maps to `definition_blocks` unchanged.
- Book-and-chapter/verse citations embedded in definition text are detected,
  retained in source spelling under `scripture_references[].raw`, and passed to
  `ocd_kernel.lib.bible_ref_normalizer.parse_thml_refs` for OSIS output.
- Explicit `See`/`See also` headword assertions map to `related_terms`.
  Source locator numbers such as `See [1]MOSES` are removed from the target;
  multiple indexed targets in one assertion are retained separately. Generic
  prose such as `See chapters ...` and `See illustration ...` is excluded.
- `alt_terms` stays empty. The source has no alternate-term field, and
  comma-separated or `Or`-containing headwords were not split because doing so
  would infer semantics not represented as a separate source assertion.

The regenerated output contains:

| Source | Entries with refs | Ref groups | Entries with related terms | Related links | Entries with `alt_terms` |
|---|---:|---:|---:|---:|---:|
| Easton's | 3,840 | 16,523 | 629 | 693 | 0 |
| Smith's | 3,964 | 12,235 | 123 | 144 | 0 |
| Hitchcock's | 0 | 0 | 2 | 2 | 0 |

Examples sampled from the census include Easton's `Rev. 1:8, 11; 21:6;
22:13`, which emits four OSIS values, and Smith's `See [1]Alpha`, which emits
`Alpha` as a related term. Hitchcock's two explicit links are `Ephratah` and
`Charran`; it carries no Bible citation strings recognized by the shared
normalizer.

### Torrey's (`topical_reference`)

- `term` maps to `topic`.
- Each `definitions` block containing ` -- ` maps to one subtopic. Its raw
  post-separator text remains one `references[].raw` value, while all
  source-backed citations in that value are normalized into its `osis` array.
- Explicit `See`/`See also` topic assertions map to `related_topics` using the
  same conservative extractor.
- `alt_topics` stays empty because the full source field census found no
  alternate-topic field or separate alternate-label apparatus.

The regenerated Torrey output contains 21,307 subtopics with at least one
normalized OSIS value and 37,992 normalized OSIS values total. Five topics have
six explicit `related_topics` links. The raw citation text remains in every
subtopic reference object, including blocks such as `See Prayer. De 4:7; Mt
6:6.` where `Prayer` is a topic link and the later values are Bible citations.

## Unverified or absent apparatus

An empty alternate-label array is a documented source absence, not a pending
implementation. No term or topic was split into alternate labels by inference.

The shared normalizer rejects some source citation spellings as unknown or
ambiguous (for example `Jdj`, unnumbered `Sam`/`Kings`, and deuterocanonical
forms such as `1 Macc`). Those citations remain in the original definition
text and are not guessed into OSIS. The parser's output therefore certifies
only the normalized citations it can support through the shared normalizer;
normalizer-coverage expansion is a separate follow-up if desired.

## Verification and blast radius

- `tests/test_bible_dictionaries.py`: 12 passed, including the full raw-key
  census when the raw files are present, reference-entry output, Torrey output,
  raw citation preservation, OSIS normalization, and explicit cross-reference
  extraction.
- `py -3 -m py_compile build/parsers/bible_dictionaries.py`: passed.
- `py -3 build/parsers/bible_dictionaries.py --all`: passed; 11,768 records
  written across four output files.
- The parser-generated files are `data/reference/eastons-bible-dictionary.json`,
  `smiths-bible-dictionary.json`, `hitchcocks-bible-names-dictionary.json`, and
  `torreys-topical-textbook.json`.
- No schema changed, so generated enum modules did not require regeneration.
  A future whole-corpus publication refresh would need to rerun the
  authoritative HuggingFace exporter after reviewing these parser outputs.
