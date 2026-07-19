# Dataset fidelity and cutover successor queue

**Named queue:** Dataset Fidelity and Cutover Successor Queue  
**Opened:** 2026-07-16, from batch 10 integration  
**Publication state (2026-07-17):** the authorized Hugging Face data upload to
`OpenChristianDataOrg/open-christian-data` completed successfully and is live. The verified
data-upload revision immediately after all 12 JSONL uploads was
`c2b4c0e0dd6676020ee089139b665383a5bc498e` at `2026-07-17T02:41:41+00:00`. The reviewed
card-only upload completed successfully at final repository revision
`19f46f3a83913f5fd9734bf758d763d57380d5f3` (`2026-07-17T03:11:16+00:00`); it changed only the card
and did not alter the verified JSONL data payload. The queue now tracks remaining fidelity and future
TEI/per-family cutover decisions.

**Historical prepublication decision (2026-07-17):** before the authorized upload, corrected repository
data was not being publicly cut over because no explicit publication authorization had been given.
This was an authorization decision, not a claim that the published defects were harmless: at that
historical point, the legacy public data still contained the known SWORD misfiling and phantom books.

This is the cold-session queue for remaining fidelity and future cutover decisions after the completed
dataset-corrections and TEI-long-tail campaign, its successor closeout, and the whole-corpus Hugging
Face data upload. The strict-v2 ledger contract below retains its historical reproduction but is
complete; remaining items are marked explicitly. Counts below were recomputed from current code and
artifacts on 2026-07-16; the historical v1 ledger PASS means accounting passed, not that fidelity was
certified.

## P1 — remaining fidelity and future projection-cutover preconditions

### Make `check_ledger` prove projected text delivery — completed 2026-07-16 (B03a-B03c)

- **Fresh reproduction:**
  `py -3 -m build.tei.check_ledger ir/bcp/hf/book-of-common-prayer.bcp-1549.jsonl.loss.json`
  returns `PASS`, but an independent TEI-to-output substring probe finds **287 of 332** `<label>`
  texts absent. The receipt reports all 332 labels as projected.
- **Cause:** a projected node can have a target record without a checked character span; the checker
  then verifies disposition and target existence, not the node's delivered text.
- **Mechanism, traced to source 2026-07-16 (do not re-derive this).** The text comparison in
  `build/tei/check_ledger.py` is gated on an *optional* field:

  ```python
  if "char_start" in target or "char_end" in target:
      expected_text = _node_clean_text(element)
      actual_text = record.get("text", "")[start:end]
  ```

  No span on the target means that block never executes, and the node still passes every other
  check (present in receipt, element matches, disposition matches, target record exists) -> `PASS`.
  **The span is the only trigger for text verification, and emitting it is optional.**

  Three components disagree, and `<label>` falls in the gap:

  | Component | Treatment of `<label>` |
  |---|---|
  | `check_ledger._expected_disposition()` | `projected` — not in `DROP_ELEMENTS` (`note`, `pb`), not in `NORMALIZED_ELEMENTS` (`ref`, `hi`, `emph`, `foreign`, `seg`, `abbr`, `title`) |
  | `project_hf.BLOCK_ELEMENTS` (`p`, `quote`, `lg`, `sp`) | not a block -> a standalone label's text never enters `record["text"]` |
  | the emitted receipt | `disposition: projected`, target record_id present, **no char span** |

  Span statistics in the BCP-1549 receipt confirm it: **613 of 613 `<p>` nodes carry a char span**
  (text verified 100%), while **321 of 332 `<label>` nodes carry none** (text never verified). The
  ~45 label texts that *do* appear in output are the 11 with spans plus labels nested inside a
  projected paragraph, picked up via `_text_with_children`. 332 − 287 = 45. The counts reconcile.

  **This is a shared-rule-set drift between two enforcement surfaces, not a BCP or label bug.** Any
  element that is neither dropped, nor normalized, nor a block element hits the same hole; `label`
  is merely the one that exposed it. Fix the contract (make a span mandatory for any projected
  text-bearing node, or derive both surfaces' element sets from one source), not the symptom.
- **Exit criterion:** every projected text-bearing node has verifiable output evidence; add a seeded
  BCP-label regression that fails before the fix and passes after it. Rerun every projection ledger.
  A fix that only special-cases `<label>` does not satisfy this.
- **Resolution (B03a-B03c):** B03a (`416bd563`) added the `loss-receipt-v2` contract and
  independent strict checker: delivery evidence is mandatory through `targets[]`, the exact
  output field/index, and character offsets; element roles are declarative and unknown elements
  fail closed. B03b (`2d60e523`) delivered all nine Class B element types, switched the projector
  and all 15 committed receipts to v2, moved dropped accounting from 10,835 to 25,695 nodes
  (+14,860, with `addressable_nodes` unchanged at 58,011), and added 65 mixed-content records
  carrying 33,127 characters. The independent v2 probe measured Class B from 1,489 to 3 residual
  probe artifacts; the word-level diff added 5,165 words and its 3 apparent removals were
  corrected run-together words. B03c (`93bd28dd`) restored structural roles for
  `list`/`item`/`table`/`row`/`cell`, made `<lb>` preserve newlines, rejected direct text
  on delivered `<sp>`, regenerated every committed projection, and verified all 15 receipts
  with strict-v2. The 287-of-332 `<label>` result above is retained as the pre-v2 historical
  reproduction, not a current unfixed defect.

### Preserve speaker roles through the clean-text projection — completed 2026-07-16

- **Historical reproduction:** the 1549/1559/1662 TEIs contained **124/137/233** `<sp>` and `<speaker>`
  pairs. Their projection rows exposed only `id`, `work_id`, `rendering_id`, `title_path`, `argument`,
  `text`, `language`, and `source`; no speaker-role field survived.
- **Resolution:** clean-text rows now carry ordered `speeches` entries with speaker, text, and
  character offsets while preserving flat `text` byte-for-byte. Record-owned speeches nested under
  wrappers are included, strict receipts cover the nested field, and carrier-level tests cover the
  role exchanges. Live speech counts are 124/137/233/455 for BCP 1549/1559/1662 and Fisher.

## P2 — blocking source/projection defects

### Correct BCP 1662 collect nesting — completed 2026-07-16

- **Historical reproduction:** all **85 of 85** `<div type="collect">` nodes descended from the final
  service, so every projected collect had the false title path “Consecration of Bishops”.
- **Resolution:** the 85 standalone collects are body peers, service-owned content remains nested,
  and the 1928 grouped collects retain explicit parents. Row count and all 495 XML IDs are preserved;
  no collect retains the false “Consecration of Bishops” ancestor.

### Remove false BCP translator metadata — completed 2026-07-16

- **Historical reproduction:** `source.translator` was `Marcus Dods` on every BCP projection row.
  Dods translated Augustine's *City of God*; these BCP renderings are English originals.
- **Resolution:** translator metadata is optional and rendering-specific. All **257 of 257** current
  BCP rows (34/16/105/102) are empty, while the genuine City of God translator remains preserved.

### Acquire or explicitly defer Westminster Standards HTML — completed 2026-07-16

- **Resolution:** five canonical HTML witnesses were politely acquired, cached, hash-pinned, and
  exact-compared; four doctrinal outputs were regenerated with config-derived provenance. The
  Directory for Publick Worship remains explicitly deferred after canonical HTTP 403 and documented
  alternative-route checks. This does not classify the distinct Creeds.json route.

## P3 — fidelity, coverage, and test debt

### Add missing BCP viewer smokes — completed 2026-07-16

- **Resolution:** reviewed 1280x1800 viewer smokes now cover representative BCP 1559 and 1928
  collects output.

### Explain the BCP 1559 record delta — completed 2026-07-16

- **Resolution:** the mapping is documented and tested: 14 legacy sections minus one legacy-only PDF
  download notice plus three current-only carriers equals 16 current rows. Thirteen records map
  directly, with four intentionally empty current services documented and no unexplained split or
  merge.

### Shorten or redesign HuggingFace dataset cache locking on Windows — completed 2026-07-16

- **Fresh verification:** installed `datasets` 4.8.5 still constructs a lock filename by embedding
  the full cache path in `datasets/builder.py`; its helper shortens the filename component but does
  not guarantee that the full Windows path stays below `MAX_PATH`. The positive workaround remains a
  short external pytest basetemp. Batch 10 did not rerun the deliberately long-basetemp failure
  because its execution boundary requires short basetemps.
- **Resolution:** export tests use deterministic session-unique short cache roots while leaving
  export artifacts under pytest's managed temp tree. A regression constructs the real builder lock
  path, proves it stays at or below 220 characters, and checks cross-session uniqueness.

### Resolve Calvin SWORD coverage mapping — completed 2026-07-16

- **Historical reproduction (before 2026-07-16):** `py -3 -m build.parsers.sword_commentary --module calvin --dry-run`
  produces **49** mapped books and 13,338 entries, including 713 Acts entries. The source config
  declares **47** books and explicitly excludes Acts.
- **Resolution:** the shared KJV versification table was corrected against the repository's KJV
  canon, Calvin's settled book set was reconciled, and the rebuilt output removed the phantom
  `judges` and `proverbs` files. The fix and book-set tests are in `be0ec729`; the rebuilt Calvin
  data is in `5b6cfbba`.

### Preserve Nave pre-arrow Scripture references — completed 2026-07-16

- **Historical reproduction (before 2026-07-16):** the raw zLD entries contained **77,935** `ref osisRef` tags while
  `py -3 -m build.parsers.naves_topical --dry-run` emits **76,957** references. The parser logs and
  code deliberately discard pre-arrow segments: a loss of **978** references.
- **Resolution:** pre-arrow references are preserved and reconciled by focused tests in committed
  fix `15266929`.

### Audit Bible dictionary structured fields — completed 2026-07-16

- **Completed 2026-07-16:** the full census found only `term` and `definitions` in all four
  JWBickel JSONL sources. The parser now maps embedded Bible citations through the shared OSIS
  normalizer, maps explicit See/See-also assertions to related-term/topic fields, and records
  genuinely absent alternate-label apparatus as empty arrays with provenance documentation.
  Evidence and exact counts: `build/parsers/bible_dictionaries_fields.md`. The implementation,
  regenerated data, and focused tests are committed in `d615d830`.

### Move Torrey's topical work out of the legacy reference path — follow-up

- **Current state:** `data/reference/torreys-topical-textbook.json` correctly declares
  `schema_type: topical_reference` and publishes with *Nave's Topical Bible* in the Hugging Face
  `topical_reference` configuration, but its filesystem location still classifies it as a general
  reference work in path-based tools.
- **Required migration:** change the parser output to a stable path under `data/topical-reference/`,
  regenerate rather than hand-move the data, and update the corresponding source configuration,
  writer manifest or other path-bound evidence, tests, catalogs, documentation, and export checks.
  Preserve the public work and entry identifiers and keep the Hugging Face configuration unchanged.
- **Temporary compatibility:** public catalog tools classify the work by its `topical_reference`
  schema until the path migration is completed. Do not retain that exception as a substitute for
  moving the file.

### Reconcile the writer-manifest corpus with its own schema — completed 2026-07-17

- **Historical reproduction:** 76 of the 89 manifests in `review/writer-manifests/` fail validation
  against `schemas/v1/writer_manifest.schema.json`. This historical corpus remains grandfathered;
  it is not an active blocker when those manifests are not staged.
- **Resolution (`be1e6df0`):**
  `build/tools/check_writer_manifest_gate.py` inspects only staged paths. Every newly staged or
  modified writer manifest is loaded from the staged index, validated against the staged writer-
  manifest schema, checked for a registered `writer_identity` against the staged identity allowlist,
  and required to cover staged `data/*.json` edits. Manifest-only staged changes are allowed, while
  historical manifests that are not staged are not scanned. The gate fails closed when staged schema,
  identity, or Git path discovery cannot be verified.
- **Review evidence:** the gate tests cover unstaged historical-manifest grandfathering, staged-index
  schema loading, paired-data coverage, default rejection, registered-identity allow cases, and real
  temporary-index behavior. The final independent C01 review passed with 18 focused tests; the
  closeout tracker records the preceding host verification of 56 tests, CLI smoke, compile, and diff
  checks.
- **Exit criterion:** newly staged or modified manifests and their staged data coverage are checked
  from staged state; the 76 historical schema-invalid manifests remain explicitly grandfathered.

### Stop the SWORD parser leaving books it no longer produces — completed 2026-07-17

- **Historical reproduction (before the current guard):** `build/parsers/sword_commentary.py` wrote one file per book
  inside its parse loop and never removes a book file it stops producing. Rebuilding `calvin` and
  `wesley` with the corrected versification table left four phantom files on disk — `calvin/judges.json`,
  `calvin/proverbs.json`, `wesley/1-kings.json`, `wesley/philemon.json` — all still publishable.
  They were removed by hand in `5b6cfbba`; at that time, nothing stopped the next regeneration
  recreating the class.
- **Resolution (`be1e6df0`):** each selected module is fully parsed into an
  in-memory `ModulePlan`; every planned book is schema-validated before any target replacement. The
  source configs declare exact expected OSIS sets: Barnes **27** books, Calvin **48**, and Wesley
  **64**. `validate_expected_book_set` rejects missing or unexpected books. `reconcile_book_outputs`
  compares the produced file set with existing JSON and raises `StaleBookOutputError` before writes;
  incomplete source reads fail closed with `IncompleteSourceError`.
- **Write safety:** `--all` plans Barnes, Calvin, and Wesley before `write_module_plans` starts any
  replacement. Each output is serialized to a same-directory temporary file and replaced per file
  atomically; each replacement retains the existing writer-manifest emission. Staging failures leave
  prior targets untouched. No cross-module transaction is claimed if an operating-system replacement
  fails after earlier files have been replaced.
- **Review evidence:** `tests/test_sword_commentary.py` covers exact configured book sets, plan-before-
  write behavior, stale detection for all three modules, incomplete-source preservation, atomic
  replacement, and staging/replacement failures. Independent C02 review passed; the closeout tracker
  records host verification of 25 tests. The implementation landed in `be1e6df0`.

### Investigate the Wesley SWORD module's missing 1 Kings and Philemon — accepted locally 2026-07-17; external handoff pending

- **Fresh reproduction (2026-07-16):** the CrossWire `Wesley` module returns text at **0** verse
  positions for both 1 Kings and Philemon, probed directly via `SwordZComReader`. Wesley's
  *Explanatory Notes* do cover both books. Logged in `UPSTREAM_BUGS.md` (SWORD modules section).
- **Why it is here and not just in the bug log:** this is a real coverage hole in a published dataset
  — consumers get no Wesley on either book. Before 2026-07-16 they got something worse: fabricated
  commentary, because the bad versification table filled both files with other books' text.
- **Local acceptance:** the corrected local output accepts this as an upstream-source limitation:
  no alternative edition-matched witness is being substituted, and the corrected output has no
  Wesley coverage for 1 Kings or Philemon. This accepts local incompleteness only; it does not accept
  the upstream module as correct and does not make the old published fabricated commentary harmless.
- **External handoff:** a self-contained report draft is ready at
  `research/2026-07-17-wesley-module-gap-report.md`, but it has not been sent and no external issue
  has been filed. Choosing a destination and sending the report remain outside this task and require
  maintainer authority.
- **Future module recheck:** after any Wesley module update, probe `1Kgs` (OT) and `Phlm` (NT) with
  `SwordZComReader` and the repository's verse-position map. Require a non-zero count of text-bearing
  positions for both books, then confirm the returned text is from the requested book rather than an
  offset-shifted neighboring book before re-ingesting.

## P4 — maintainer-owned local tooling

### Remove or implement nonexistent edit hooks — completed 2026-07-16

- **Historical reproduction (before 2026-07-16):** `.claude/settings.json` referenced
  `post_py_compile.py`, `post_standards_check.py`, `post_ruff_check.py`, and
  `post_ocd_validate.py`; none exists under `.claude/hooks/`.
- **Owner:** maintainer, because the prior orchestrator was denied self-modification of local agent
  settings.
- **Resolution:** the four registered hooks were implemented under `.claude/hooks/` in `7bb3d0e5`;
  the registration problem is resolved by implementation rather than removal.
