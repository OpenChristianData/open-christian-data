# A5 Codex Round 1 Independent Audit

- Plan: `plans/2026-05-17-phase-1-implementation.md`
- Generated: `2026-05-20T00:27:38.961010+00:00`
- File existence checks use tracked `HEAD` content (`git show HEAD:<path>` / `git ls-files`).
- Constraint observed: `audits/A5-claude-round1.md` was not opened or read.
- VCS write commands were not run.
- Mutating completion commands were not run where they intentionally write non-audit artefacts; these are marked `MANUAL` with the safety reason.

## Slot 0 — Atomic moves (R53 rename + schema-version-bump infra)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `tests/test_phase1_lexicon_rename_no_regression.py` | 58 | yes |  |

### NAMED TEST FUNCTIONS
- `MANUAL`: No named `test_...` functions appeared in this slot's `Tests first:` section after excluding test-file names.

### COMPLETION CRITERIA
- Criterion text: `py -3 -m pytest tests/test_phase1_lexicon_rename_no_regression.py tests/test_generated_enums.py tests/test_lang_classifier.py -v` is GREEN; `py -3 build/tools/check_schema_enums_fresh.py` exit code 0; `git log -1` shows one commit covering the rename + every reference + enum regen.
- `PASS` `py -3 -m pytest tests/test_phase1_lexicon_rename_no_regression.py tests/test_generated_enums.py tests/test_lang_classifier.py -v` (exit `0`, 1.4s)

```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.0.2, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: <project-root>
configfile: pyproject.toml
plugins: anyio-4.13.0
collecting ... collected 14 items

tests/test_phase1_lexicon_rename_no_regression.py::test_old_lexicon_files_do_not_exist PASSED [  7%]
tests/test_phase1_lexicon_rename_no_regression.py::test_new_lexicon_modules_import_successfully PASSED [ 14%]
tests/test_phase1_lexicon_rename_no_regression.py::test_lang_classifier_uses_new_lang_codes PASSED [ 21%]
tests/test_generated_enums.py::test_generated_enums_are_deterministic PASSED [ 28%]
tests/test_generated_enums.py::test_generated_constants_match_get_enum PASSED [ 35%]
tests/test_generated_enums.py::test_new_v3_schema_enums_loadable_via_get_enum PASSED [ 42%]
tests/test_generated_enums.py::test_drift_check_exits_nonzero_when_generated_file_is_stale PASSED [ 50%]
tests/test_lang_classifier.py::test_classify_returns_no_hint_for_unmatched_english PASSED [ 57%]
tests/test_lang_classifier.py::test_classify_spans_returns_empty_list_for_unmatched_english PASSED [ 64%]
tests/test_lang_classifier.py::test_classify_block_returns_dict PASSED   [ 71%]
tests/test_lang_classifier.py::test_classify_block_english_text PASSED   [ 78%]
tests/test_lang_classifier.py::test_classify_block_greek_script PASSED   [ 85%]
tests/test_lang_classifier.py::test_classify_block_und_on_empty PASSED   [ 92%]
tests/test_lang_classifier.py::test_classify_block_language_segments_type PASSED [100%]

============================= 14 passed in 0.72s ==============================
```
- `PASS` `py -3 build/tools/check_schema_enums_fresh.py` (exit `0`, 0.1s)

```text
(no output)
```
- `PASS` `git log -1 --stat` (exit `0`, 0.0s)

```text
commit 06c84b8fa5a4babfc1434ba0195aecb0c2d68386
Author: openchristiandata <271227258+OpenChristianData@users.noreply.github.com>
Date:   Wed May 20 09:42:14 2026 +1000

    chore(audit): hold advance Codex A3/A4 findings in _advance/
    
    Codex ran A3 and A4 during the A2 dispatch. Files moved to _advance/ to
    preserve independence — next session completes its own Claude pass before
    reading these. See LAST_SESSION for promotion instructions.
    
    Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

 audits/_advance/A3-codex-advance.md | 139 ++++++++++++++++++++++++++++++++++++
 audits/_advance/A4-codex-advance.md |  67 +++++++++++++++++
 2 files changed, 206 insertions(+)
```

### SCOPE CREEP
- `SCOPE_CREEP`: 304 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/lib/lexicons`, `build/lib`, `build/parsers`, `build/tools`, `review/writer-manifests`, `tests`, `schemas/v1`
  - `build/lib/lexicons/de.py`
  - `build/lib/lexicons/en.py`
  - `build/lib/lexicons/fr.py`
  - `build/lib/lexicons/la.py`
  - `build/lib/__init__.py`
  - `build/lib/atomic_io.py`
  - `build/lib/bible_ref_normalizer.py`
  - `build/lib/block_id.py`
  - `build/lib/ccel_thml.py`
  - `build/lib/citation_parser.py`
  - `build/lib/config_validation.py`
  - `build/lib/contributors.py`
  - `build/lib/evidence_renderer_loader.py`
  - `build/lib/lang_classifier.py`
  - `build/lib/layer_diff.py`
  - `build/lib/ocr_coordinates.py`
  - `build/lib/parser_regen_safety.py`
  - `build/lib/paths.py`
  - `build/lib/pdf_normalizer.py`
  - `build/lib/pdf_quality_gate.py`
  - `build/lib/render_cache.py`
  - `build/lib/resource_ids.py`
  - `build/lib/review_state.py`
  - `build/lib/review_warnings.py`
  - `build/lib/schema_enums.py`
  - `build/lib/scripture_canon.py`
  - `build/lib/sidecar_migrations.py`
  - `build/lib/text_alignment.py`
  - `build/lib/text_extractor.py`
  - `build/lib/text_layers.py`
  - `build/lib/text_utils.py`
  - `build/lib/writer_identities.py`
  - `build/parsers/bcp1662.py`
  - `build/parsers/bcp1928.py`
  - `build/parsers/bible_dictionaries.py`
  - `build/parsers/bsb_bible_text.py`
  - `build/parsers/ccel_anf.py`
  - `build/parsers/ccel_church_history.py`
  - `build/parsers/ccel_devotional.py`
  - `build/parsers/ccel_evangelical_holiness.py`
  - `build/parsers/ccel_expositors_bible.py`
  - `build/parsers/ccel_hodge_systematic.py`
  - `build/parsers/ccel_npnf1.py`
  - `build/parsers/ccel_npnf2.py`
  - `build/parsers/ccel_owen_works.py`
  - `build/parsers/ccel_pdf_commentary.py`
  - `build/parsers/ccel_puritan_works.py`
  - `build/parsers/ccel_schaff_hcc.py`
  - `build/parsers/ccel_schaff_herzog.anchor_fixture.json`
  - `build/parsers/ccel_schaff_herzog.py`
  - `build/parsers/ccel_sermon.py`
  - `build/parsers/ccel_whitefield_sermon.py`
  - `build/parsers/church_fathers.py`
  - `build/parsers/creeds_json_catechism.py`
  - `build/parsers/creeds_json_confession.py`
  - `build/parsers/didache.py`
  - `build/parsers/gutenberg_catechisms.py`
  - `build/parsers/gutenberg_evangelical.py`
  - `build/parsers/gutenberg_maclaren.py`
  - `build/parsers/gutenberg_puritan.py`
  - `build/parsers/gutenberg_sermons.py`
  - `build/parsers/gutenberg_systematics.py`
  - `build/parsers/gutenberg_theology.py`
  - `build/parsers/helloao_commentary.py`
  - `build/parsers/hymnary_pd.py`
  - `build/parsers/ia_census_output.txt`
  - `build/parsers/ia_fisher_marrow.py`
  - `build/parsers/ia_hastings_dictionary.py`
  - `build/parsers/ia_schaff_herzog.anchor_fixture.json`
  - `build/parsers/ia_schaff_herzog.py`
  - `build/parsers/ia_schaff_herzog_census.py`
  - `build/parsers/naves_topical.py`
  - `build/parsers/spurgeon_mtp.py`
  - `build/parsers/spurgeon_mtp_missing.py`
  - `build/parsers/standard_ebooks.py`
  - `build/parsers/sword_commentary.py`
  - `build/parsers/sword_devotional.py`
  - `build/parsers/westminster_standard_parser.py`
  - `build/parsers/wsc_parser.py`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/apply_review_patch.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bootstrap_renderings.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/calibration_report.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/derive_scan_jpegs.py`
  - `build/tools/export_hf_dataset.py`
  - `build/tools/fetch_rendering.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/inspect_review_patch.py`
  - `build/tools/migrate_schaff_herzog.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/modernise_record.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/parse_rendering.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/phase1_completion_audit.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/reconcile.py`
  - `build/tools/reconcile_status.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`
  - `review/writer-manifests/apply_correction_clarke_2_john.json`
  - `review/writer-manifests/phase_d_coverage_adam_clarke_2_john.json`
  - `review/writer-manifests/phase_d_coverage_schaff_herzog.json`
  - `review/writer-manifests/regenerate_layers_adam_clarke_2_john.json`
  - `review/writer-manifests/schaff_slot11_data_phase.json`
  - `review/writer-manifests/slot11_schaff_herzog_catalog.json`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`
  - `schemas/v1/audit_event.schema.json`
  - `schemas/v1/author_registry.schema.json`
  - `schemas/v1/bible_text.schema.json`
  - `schemas/v1/catechism_qa.schema.json`
  - `schemas/v1/church_fathers.schema.json`
  - `schemas/v1/commentary.schema.json`
  - `schemas/v1/correction_ledger.schema.json`
  - `schemas/v1/devotional.schema.json`
  - `schemas/v1/doctrinal_document.schema.json`
  - `schemas/v1/field_path_remap.schema.json`
  - `schemas/v1/hymn_collection.schema.json`
  - `schemas/v1/modernised_record.schema.json`
  - `schemas/v1/parser_anchor_fixture.schema.json`
  - `schemas/v1/parser_anchor_remap.schema.json`
  - `schemas/v1/prayer.schema.json`
  - `schemas/v1/reconciled_record.schema.json`
  - `schemas/v1/reference_entry.schema.json`
  - `schemas/v1/rendering_catalog.schema.json`
  - `schemas/v1/review_patch.schema.json`
  - `schemas/v1/review_state.schema.json`
  - `schemas/v1/scans_manifest.schema.json`
  - `schemas/v1/sermon.schema.json`
  - `schemas/v1/structured_text.schema.json`
  - `schemas/v1/topical_reference.schema.json`
  - `schemas/v1/warning_signature_remap.schema.json`
  - `schemas/v1/witness_registry.schema.json`
  - `schemas/v1/writer_manifest.schema.json`

## Slot 1 — Schema lock (reconciled, modernised, rendering_catalog, review_patch, metadata extensions, reference annotation validator)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `schemas/v1/reconciled_record.schema.json` | 353 | yes |  |
| SHIPPED | `schemas/v1/modernised_record.schema.json` | 350 | yes |  |
| SHIPPED | `schemas/v1/rendering_catalog.schema.json` | 141 | yes |  |
| SHIPPED | `schemas/v1/review_patch.schema.json` | 39 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_reconciled_record_round_trip` | yes | `tests\test_a1_schemas.py:513:def test_reconciled_record_round_trip():` |
| SHIPPED | `test_modernised_record_round_trip` | yes | `tests\test_a1_schemas.py:530:def test_modernised_record_round_trip():` |
| SHIPPED | `test_review_patch_round_trip` | yes | `tests\test_a1_schemas.py:572:def test_review_patch_round_trip():`<br>`tests\test_phase1_completion_audit.py:13:    "tests/test_review_patch_round_trip.py",` |
| SHIPPED | `test_rendering_catalog_role_lifecycle` | yes | `tests\test_a1_schemas.py:641:def test_rendering_catalog_role_lifecycle():` |

### COMPLETION CRITERIA
- Criterion text: `py -3 -m pytest tests/test_a1_schemas.py tests/test_generated_enums.py tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py tests/test_r19_catalog_record_pd_anchor_consistency.py tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py tests/test_phase1_reference_resource_registry_validation.py tests/test_match_explanations_discriminated_union.py -v` is GREEN; `check_schema_enums_fresh.py` exit 0; no file under `schemas/v1/` has additional-properties holes outside the explicit allow-lists.
- `PASS` `py -3 -m pytest tests/test_a1_schemas.py tests/test_generated_enums.py tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py tests/test_r19_catalog_record_pd_anchor_consistency.py tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py tests/test_phase1_reference_resource_registry_validation.py tests/test_match_explanations_discriminated_union.py -v` (exit `0`, 3.1s)

```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.0.2, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: <project-root>
configfile: pyproject.toml
plugins: anyio-4.13.0
collecting ... collected 65 items

tests/test_a1_schemas.py::test_review_state_accepts_empty_sidecar PASSED [  1%]
tests/test_a1_schemas.py::test_review_state_rejects_bad_confidence_tier PASSED [  3%]
tests/test_a1_schemas.py::test_review_state_rejects_dead_letter_overflow PASSED [  4%]
tests/test_a1_schemas.py::test_correction_ledger_accepts_approved_text_entry PASSED [  6%]
tests/test_a1_schemas.py::test_correction_ledger_rejects_approved_without_approver PASSED [  7%]
tests/test_a1_schemas.py::test_correction_ledger_rejects_unknown_correction_type PASSED [  9%]
tests/test_a1_schemas.py::test_writer_manifest_accepts_parser_example PASSED [ 10%]
tests/test_a1_schemas.py::test_writer_manifest_accepts_new_file_with_null_before_sha PASSED [ 12%]
tests/test_a1_schemas.py::test_writer_manifest_rejects_unknown_writer PASSED [ 13%]
tests/test_a1_schemas.py::test_audit_event_accepts_dismiss PASSED        [ 15%]
tests/test_a1_schemas.py::test_audit_event_accepts_correction_applied PASSED [ 16%]
tests/test_a1_schemas.py::test_audit_event_accepts_sidecar_schema_migrated PASSED [ 18%]
tests/test_a1_schemas.py::test_audit_event_accepts_set_confidence_axis PASSED [ 20%]
tests/test_a1_schemas.py::test_audit_event_accepts_stale_lock_broken PASSED [ 21%]
tests/test_a1_schemas.py::test_audit_event_rejects_unknown_event_type PASSED [ 23%]
tests/test_a1_schemas.py::test_parser_anchor_fixture_accepts_example PASSED [ 24%]
tests/test_a1_schemas.py::test_parser_anchor_fixture_rejects_empty_samples PASSED [ 26%]
tests/test_a1_schemas.py::test_parser_anchor_remap_accepts_example PASSED [ 27%]
tests/test_a1_schemas.py::test_field_path_remap_accepts_example PASSED   [ 29%]
tests/test_a1_schemas.py::test_warning_signature_remap_accepts_example PASSED [ 30%]
tests/test_a1_schemas.py::test_reconciled_record_round_trip PASSED       [ 32%]
tests/test_a1_schemas.py::test_modernised_record_round_trip PASSED       [ 33%]
tests/test_a1_schemas.py::test_review_patch_round_trip PASSED            [ 35%]
tests/test_a1_schemas.py::test_rendering_catalog_role_lifecycle PASSED   [ 36%]
tests/test_a1_schemas.py::test_copyrighted_catalog_entry_satisfies_allow_list PASSED [ 38%]
tests/test_generated_enums.py::test_generated_enums_are_deterministic PASSED [ 40%]
tests/test_generated_enums.py::test_generated_constants_match_get_enum PASSED [ 41%]
tests/test_generated_enums.py::test_new_v3_schema_enums_loadable_via_get_enum PASSED [ 43%]
tests/test_generated_enums.py::test_drift_check_exits_nonzero_when_generated_file_is_stale PASSED [ 44%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[paragraph] PASSED [ 46%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[heading] PASSED [ 47%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[lemma] PASSED [ 49%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[list_item] PASSED [ 50%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[footnote] PASSED [ 52%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[verse_line] PASSED [ 53%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[headword] PASSED [ 55%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[quote] PASSED [ 56%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase1_block_types_accepted[table_row] PASSED [ 58%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase2_block_types_rejected_in_phase1[article] PASSED [ 60%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase2_block_types_rejected_in_phase1[question] PASSED [ 61%]
tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py::test_phase2_block_types_rejected_in_phase1[answer] PASSED [ 63%]
tests/test_r19_catalog_record_pd_anchor_consistency.py::test_catalog_and_record_schemas_both_valid PASSED [ 64%]
tests/test_r19_catalog_record_pd_anchor_consistency.py::test_record_pd_anchor_matches_catalog_chosen_rendering PASSED [ 66%]
tests/test_r19_catalog_record_pd_anchor_consistency.py::test_stale_record_pd_anchor_detected PASSED [ 67%]
tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py::test_original_record_with_language_segment_validates PASSED [ 69%]
tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py::test_modernised_record_with_language_segment_validates PASSED [ 70%]
tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py::test_language_segment_content_fields_equal_across_siblings PASSED [ 72%]
tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py::test_language_segment_diverged_content_field_detected PASSED [ 73%]
tests/test_phase1_reference_resource_registry_validation.py::test_phase1_minimum_registry_files_exist[grc] PASSED [ 75%]
tests/test_phase1_reference_resource_registry_validation.py::test_phase1_minimum_registry_files_exist[hbo] PASSED [ 76%]
tests/test_phase1_reference_resource_registry_validation.py::test_phase1_minimum_registry_files_exist[la] PASSED [ 78%]
tests/test_phase1_reference_resource_registry_validation.py::test_registry_entries_have_required_fields[grc] PASSED [ 80%]
tests/test_phase1_reference_resource_registry_validation.py::test_registry_entries_have_required_fields[hbo] PASSED [ 81%]
tests/test_phase1_reference_resource_registry_validation.py::test_registry_entries_have_required_fields[la] PASSED [ 83%]
tests/test_phase1_reference_resource_registry_validation.py::test_registry_resource_types_valid[grc] PASSED [ 84%]
tests/test_phase1_reference_resource_registry_validation.py::test_registry_resource_types_valid[hbo] PASSED [ 86%]
tests/test_phase1_reference_resource_registry_validation.py::test_registry_resource_types_valid[la] PASSED [ 87%]
tests/test_phase1_reference_resource_registry_validation.py::test_phase1_minimum_entries_present[grc-liddell-scott] PASSED [ 89%]
tests/test_phase1_reference_resource_registry_validation.py::test_phase1_minimum_entries_present[hbo-bdb] PASSED [ 90%]
tests/test_phase1_reference_resource_registry_validation.py::test_phase1_minimum_entries_present[la-lewis-and-short] PASSED [ 92%]
tests/test_match_explanations_discriminated_union.py::test_edge_match_explanation_accepted PASSED [ 93%]
tests/test_match_explanations_discriminated_union.py::test_reading_score_explanation_accepted PASSED [ 95%]
tests/test_match_explanations_discriminated_union.py::test_structural_rule_explanation_accepted PASSED [ 96%]
tests/test_match_explanations_discriminated_union.py::test_unknown_decision_kind_rejected PASSED [ 98%]
tests/test_match_explanations_discriminated_union.py::test_missing_decision_kind_rejected PASSED [100%]

============================= 65 passed in 2.34s ==============================
```
- `PASS` `py -3 build/tools/check_schema_enums_fresh.py` (exit `0`, 0.1s)

```text
(no output)
```

### SCOPE CREEP
- `SCOPE_CREEP`: 195 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `schemas/v1`, `build/lib`, `tests`
  - `schemas/v1/audit_event.schema.json`
  - `schemas/v1/author_registry.schema.json`
  - `schemas/v1/bible_text.schema.json`
  - `schemas/v1/catechism_qa.schema.json`
  - `schemas/v1/church_fathers.schema.json`
  - `schemas/v1/correction_ledger.schema.json`
  - `schemas/v1/devotional.schema.json`
  - `schemas/v1/doctrinal_document.schema.json`
  - `schemas/v1/field_path_remap.schema.json`
  - `schemas/v1/hymn_collection.schema.json`
  - `schemas/v1/parser_anchor_fixture.schema.json`
  - `schemas/v1/parser_anchor_remap.schema.json`
  - `schemas/v1/prayer.schema.json`
  - `schemas/v1/review_state.schema.json`
  - `schemas/v1/scans_manifest.schema.json`
  - `schemas/v1/sermon.schema.json`
  - `schemas/v1/structured_text.schema.json`
  - `schemas/v1/topical_reference.schema.json`
  - `schemas/v1/warning_signature_remap.schema.json`
  - `schemas/v1/witness_registry.schema.json`
  - `schemas/v1/writer_manifest.schema.json`
  - `build/lib/__init__.py`
  - `build/lib/atomic_io.py`
  - `build/lib/bible_ref_normalizer.py`
  - `build/lib/block_id.py`
  - `build/lib/ccel_thml.py`
  - `build/lib/citation_parser.py`
  - `build/lib/config_validation.py`
  - `build/lib/contributors.py`
  - `build/lib/evidence_renderer_loader.py`
  - `build/lib/historical_lexicon.py`
  - `build/lib/lang_classifier.py`
  - `build/lib/layer_diff.py`
  - `build/lib/ocr_coordinates.py`
  - `build/lib/parser_regen_safety.py`
  - `build/lib/paths.py`
  - `build/lib/pdf_normalizer.py`
  - `build/lib/pdf_quality_gate.py`
  - `build/lib/render_cache.py`
  - `build/lib/resource_ids.py`
  - `build/lib/review_state.py`
  - `build/lib/review_warnings.py`
  - `build/lib/schema_enums.py`
  - `build/lib/scripture_canon.py`
  - `build/lib/sidecar_migrations.py`
  - `build/lib/text_alignment.py`
  - `build/lib/text_extractor.py`
  - `build/lib/text_layers.py`
  - `build/lib/text_utils.py`
  - `build/lib/writer_identities.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 2 — Language detection (Layer 1 + Layer 2 + cld3 fallback + source-transliteration + lexicon floors + OCR error models)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/lib/lexicons/fr.py` | 243 | yes |  |
| SHIPPED | `build/lib/lexicons/de.py` | 222 | yes |  |
| SHIPPED | `build/lib/lexicons/grc.py` | 207 | yes |  |
| SHIPPED | `build/lib/lexicons/hbo_latn.py` | 189 | yes |  |
| SHIPPED | `build/lib/lexicons/la.py` | 266 | yes |  |
| SHIPPED | `build/lib/lexicons/en.py` | 24 | yes |  |
| SHIPPED | `build/lib/source_transliteration_lexicons/grc.yaml` | 74 | yes |  |
| SHIPPED | `build/lib/source_transliteration_lexicons/hbo.yaml` | 57 | yes |  |
| MISSING | `build/lib/source_transliteration_lexicons/la.yaml` | 2 | no |  |
| SHIPPED | `build/lib/ocr_error_models/en.yaml` | 19 | yes |  |
| SHIPPED | `build/lib/ocr_error_models/la.yaml` | 16 | yes |  |
| SHIPPED | `build/lib/ocr_error_models/grc.yaml` | 16 | yes |  |
| SHIPPED | `build/lib/ocr_error_models/hbo.yaml` | 16 | yes |  |
| SHIPPED | `build/lib/ocr_error_models/fr.yaml` | 16 | yes |  |
| SHIPPED | `build/lib/ocr_error_models/de.yaml` | 22 | yes |  |
| MISSING | `build/lib/reference_resources/grc.yaml` | 3 | no |  |
| MISSING | `build/lib/reference_resources/hbo.yaml` | 3 | no |  |
| MISSING | `build/lib/reference_resources/la.yaml` | 3 | no |  |

### NAMED TEST FUNCTIONS
- `MANUAL`: No named `test_...` functions appeared in this slot's `Tests first:` section after excluding test-file names.

### COMPLETION CRITERIA
- Criterion text: `py -3 -m pytest tests/test_lang_classifier.py tests/test_lang_classifier_confidence_bands.py tests/test_layer2_floor_prevents_cld3_fallthrough.py tests/test_source_transliteration_lexicon_detects_grc_hbo.py tests/test_source_transliteration_coverage.py -v` is GREEN; running the classifier on a Schaff-Herzog vol-01 bibliography page surfaces German-segment tokens at Layer 2 with confidence ≥ 0.60.
- `PASS` `py -3 -m pytest tests/test_lang_classifier.py tests/test_lang_classifier_confidence_bands.py tests/test_layer2_floor_prevents_cld3_fallthrough.py tests/test_source_transliteration_lexicon_detects_grc_hbo.py tests/test_source_transliteration_coverage.py -v` (exit `0`, 1.1s)

```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.0.2, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: <project-root>
configfile: pyproject.toml
plugins: anyio-4.13.0
collecting ... collected 85 items

tests/test_lang_classifier.py::test_classify_returns_no_hint_for_unmatched_english PASSED [  1%]
tests/test_lang_classifier.py::test_classify_spans_returns_empty_list_for_unmatched_english PASSED [  2%]
tests/test_lang_classifier.py::test_classify_block_returns_dict PASSED   [  3%]
tests/test_lang_classifier.py::test_classify_block_english_text PASSED   [  4%]
tests/test_lang_classifier.py::test_classify_block_greek_script PASSED   [  5%]
tests/test_lang_classifier.py::test_classify_block_und_on_empty PASSED   [  7%]
tests/test_lang_classifier.py::test_classify_block_language_segments_type PASSED [  8%]
tests/test_lang_classifier_confidence_bands.py::test_greek_script_is_high_confidence PASSED [  9%]
tests/test_lang_classifier_confidence_bands.py::test_hebrew_transliteration_is_low_confidence PASSED [ 10%]
tests/test_lang_classifier_confidence_bands.py::test_latin_abbreviation_is_medium_only_for_dictionary_match PASSED [ 11%]
tests/test_lang_classifier_confidence_bands.py::test_uncertain_spans_require_manual_override PASSED [ 12%]
tests/test_lang_classifier_confidence_bands.py::test_confidence_floor_is_60_percent PASSED [ 14%]
tests/test_lang_classifier_confidence_bands.py::test_lang_block_needs_review_fires_on_und PASSED [ 15%]
tests/test_lang_classifier_confidence_bands.py::test_lang_block_needs_review_fires_on_low_confidence PASSED [ 16%]
tests/test_lang_classifier_confidence_bands.py::test_und_language_has_zero_confidence PASSED [ 17%]
tests/test_lang_classifier_confidence_bands.py::test_lang_block_needs_review_constant_exists PASSED [ 18%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Blessed art thou among women] PASSED [ 20%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[For thine is the kingdom and the power] PASSED [ 21%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Verily verily I say unto thee] PASSED [ 22%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Hath God forgotten to be gracious] PASSED [ 23%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[The LORD is my shepherd I shall not want] PASSED [ 24%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Thy lovingkindness is better than life] PASSED [ 25%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Thus saith the LORD of hosts] PASSED [ 27%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Behold the Lamb of God which taketh away the sin] PASSED [ 28%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Thou shalt love the LORD thy God with all thine heart] PASSED [ 29%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_english[Whereunto I am appointed a preacher and an apostle] PASSED [ 30%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Pater noster qui es in caelis] PASSED [ 31%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Gloria in excelsis Deo et in terra pax] PASSED [ 32%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Kyrie eleison Christe eleison] PASSED [ 34%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Agnus Dei qui tollis peccata mundi] PASSED [ 35%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Sanctus Sanctus Sanctus Dominus Deus Sabaoth] PASSED [ 36%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Et incarnatus est de Spiritu Sancto] PASSED [ 37%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Credo in unum Deum Patrem omnipotentem] PASSED [ 38%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Miserere mei Deus secundum magnam misericordiam tuam] PASSED [ 40%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[Soli Deo gloria] PASSED [ 41%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_latin[In principio erat Verbum et Verbum erat apud Deum] PASSED [ 42%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[La gr\xe2ce de notre Seigneur J\xe9sus Christ] PASSED [ 43%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[Dieu est amour et celui qui demeure dans l amour] PASSED [ 44%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[Notre P\xe8re qui es aux cieux que ton nom soit sanctifi\xe9] PASSED [ 45%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[Car Dieu a tant aim\xe9 le monde qu il a donn\xe9 son Fils unique] PASSED [ 47%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[Je suis la r\xe9surrection et la vie] PASSED [ 48%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[La foi sans les oeuvres est morte] PASSED [ 49%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[L \xc9glise de Dieu rachet\xe9e par le sang de Christ] PASSED [ 50%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[Seigneur apprends nous \xe0 prier] PASSED [ 51%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[La parole de Dieu est vivante et efficace] PASSED [ 52%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_french[Que votre amour soit sans hypocrisie] PASSED [ 54%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Die Gnade unseres Herrn Jesus Christus] PASSED [ 55%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Gott ist die Liebe und wer in der Liebe bleibt] PASSED [ 56%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Gebet und Bibellesen sind die Grundlage des christlichen Lebens] PASSED [ 57%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Die Kirche Gottes ist das Fundament der Wahrheit] PASSED [ 58%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Der Heilige Geist wird euch in alle Wahrheit leiten] PASSED [ 60%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Christus ist das Haupt der Kirche seinen Leibes] PASSED [ 61%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Die Reformation hat das Evangelium neu entdeckt] PASSED [ 62%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Luther \xfcbersetzte die Bibel ins Deutsche] PASSED [ 63%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Glaube Hoffnung und Liebe diese drei] PASSED [ 64%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_german[Das Wort Gottes bleibt in Ewigkeit] PASSED [ 65%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the logos became flesh and dwelt among us] PASSED [ 67%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the agap\u0113 of God is shed abroad in our hearts] PASSED [ 68%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[pneuma is the spirit that gives life] PASSED [ 69%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the ekklesia is the body of Christ] PASSED [ 70%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[kurios Jesus is Lord over all] PASSED [ 71%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the parousia of Christ is the blessed hope] PASSED [ 72%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the diatheke is the new covenant in his blood] PASSED [ 74%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the christos the anointed one of God] PASSED [ 75%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the didache teaches the way of life and death] PASSED [ 76%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_grc_transliterated[the kerygma is the proclamation of the gospel] PASSED [ 77%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Yahweh is the covenant name of God in the Hebrew scriptures] PASSED [ 78%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Adonai is the name reverently spoken in place of YHWH] PASSED [ 80%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Elohim the creator God who made the heavens and the earth] PASSED [ 81%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Jehovah Jireh the LORD will provide] PASSED [ 82%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Zebaoth the LORD of hosts and of armies] PASSED [ 83%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Jahveh a variant transliteration used by German scholars] PASSED [ 84%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Jahweh another common German transliteration of the divine name] PASSED [ 85%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Yahveh used in some older English-language scholarship] PASSED [ 87%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[Yehovah a form reflecting the Masoretic vowel pointing] PASSED [ 88%]
tests/test_layer2_floor_prevents_cld3_fallthrough.py::test_layer2_hbo_latn[JHVH the tetragrammaton in older European scholarly conventions] PASSED [ 89%]
tests/test_source_transliteration_lexicon_detects_grc_hbo.py::test_agape_detected_as_grc_transliteration PASSED [ 90%]
tests/test_source_transliteration_lexicon_detects_grc_hbo.py::test_agape_variant_detected PASSED [ 91%]
tests/test_source_transliteration_lexicon_detects_grc_hbo.py::test_yahweh_detected_as_hbo_transliteration PASSED [ 92%]
tests/test_source_transliteration_lexicon_detects_grc_hbo.py::test_pneuma_without_citation_not_flagged_as_transliteration PASSED [ 94%]
tests/test_source_transliteration_lexicon_detects_grc_hbo.py::test_la_yaml_is_empty_in_phase1 PASSED [ 95%]
tests/test_source_transliteration_lexicon_detects_grc_hbo.py::test_source_transliteration_entry_shape PASSED [ 96%]
tests/test_source_transliteration_coverage.py::test_source_transliteration_lexicons_dir_exists PASSED [ 97%]
tests/test_source_transliteration_coverage.py::test_fixture_dir_exists PASSED [ 98%]
tests/test_source_transliteration_coverage.py::test_every_lexicon_entry_has_fixture PASSED [100%]

============================= 85 passed in 0.36s ==============================
```

### SCOPE CREEP
- `SCOPE_CREEP`: 177 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/lib`, `build/lib/lexicons`, `build/lib/source_transliteration_lexicons`, `build/lib/ocr_error_models`, `build/lib/reference_resources`, `tests`
  - `build/lib/__init__.py`
  - `build/lib/_generated_enums.py`
  - `build/lib/atomic_io.py`
  - `build/lib/bible_ref_normalizer.py`
  - `build/lib/block_id.py`
  - `build/lib/ccel_thml.py`
  - `build/lib/citation_parser.py`
  - `build/lib/config_validation.py`
  - `build/lib/contributors.py`
  - `build/lib/evidence_renderer_loader.py`
  - `build/lib/historical_lexicon.py`
  - `build/lib/layer_diff.py`
  - `build/lib/ocr_coordinates.py`
  - `build/lib/parser_regen_safety.py`
  - `build/lib/paths.py`
  - `build/lib/pdf_normalizer.py`
  - `build/lib/pdf_quality_gate.py`
  - `build/lib/render_cache.py`
  - `build/lib/resource_ids.py`
  - `build/lib/review_state.py`
  - `build/lib/review_warnings.py`
  - `build/lib/schema_enums.py`
  - `build/lib/scripture_canon.py`
  - `build/lib/sidecar_migrations.py`
  - `build/lib/text_alignment.py`
  - `build/lib/text_extractor.py`
  - `build/lib/text_layers.py`
  - `build/lib/text_utils.py`
  - `build/lib/writer_identities.py`
  - `build/lib/lexicons/__init__.py`
  - `build/lib/source_transliteration_lexicons/__init__.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 3 — Reconcile core (anchor graph + block alignment + token alignment + classify + structural + assemble + match_explanations)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/lib/reconcile/__init__.py` | 274 | yes |  |
| SHIPPED | `build/lib/reconcile/anchor_graph.py` | 42 | yes |  |
| SHIPPED | `build/lib/reconcile/block_alignment.py` | 302 | yes |  |
| SHIPPED | `build/lib/reconcile/token_alignment.py` | 43 | yes |  |
| SHIPPED | `build/lib/reconcile/classify.py` | 196 | yes |  |
| SHIPPED | `build/lib/reconcile/structural.py` | 85 | yes |  |
| SHIPPED | `build/lib/reconcile/assemble.py` | 372 | yes |  |
| SHIPPED | `build/lib/reconcile/match_explanations.py` | 114 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_n1_trivial_path` | yes | `tests\test_reconcile\test_integration.py:57:def test_n1_trivial_path():` |
| SHIPPED | `test_r20_n1_empty_match_explanations` | yes | `tests\test_reconcile\test_integration.py:78:def test_r20_n1_empty_match_explanations():` |
| SHIPPED | `test_n2_anchor_wins_tie_breaker` | yes | `tests\test_reconcile\test_integration.py:91:def test_n2_anchor_wins_tie_breaker():` |
| SHIPPED | `test_n3_majority_and_split_vote` | yes | `tests\test_reconcile\test_integration.py:132:def test_n3_majority_and_split_vote():` |
| SHIPPED | `test_split_merged_block_one_to_many_alignment` | yes | `tests\test_reconcile\test_block_alignment.py:23:def test_split_merged_block_one_to_many_alignment():` |
| MISSING | `test_reading_score_auto_choice_gate` | no |  |
| SHIPPED | `test_reference_only_routes_to_advisory_score` | yes | `tests\test_reconcile\test_assemble.py:124:def test_reference_only_routes_to_advisory_score():` |
| SHIPPED | `test_block_id_stability_across_re_reconcile` | yes | `tests\test_reconcile\test_integration.py:170:def test_block_id_stability_across_re_reconcile():` |
| SHIPPED | `test_reviewer_split_merge_re_keying` | yes | `tests\test_reconcile\test_integration.py:242:def test_reviewer_split_merge_re_keying():` |
| SHIPPED | `test_r24_promoted_ocr_scores_as_pd_attestor` | yes | `tests\test_reconcile\test_block_alignment.py:57:def test_r24_promoted_ocr_scores_as_pd_attestor():` |
| SHIPPED | `test_r25_punctuation_modifier_requires_anchor_style_threshold` | yes | `tests\test_reconcile\test_block_alignment.py:94:def test_r25_punctuation_modifier_requires_anchor_style_threshold():` |
| SHIPPED | `test_r27_attestor_retained_after_anchor_structure_acceptance` | yes | `tests\test_reconcile\test_structural.py:23:def test_r27_attestor_retained_after_anchor_structure_acceptance():` |
| SHIPPED | `test_r28_checker_surfaces_threshold_and_bucket_metrics` | yes | `tests\test_reconcile\test_block_alignment.py:121:def test_r28_checker_surfaces_threshold_and_bucket_metrics():` |
| SHIPPED | `test_r30_catalog_requires_schema_and_parser_checks` | yes | `tests\test_reconcile\test_integration.py:191:def test_r30_catalog_requires_schema_and_parser_checks():` |
| SHIPPED | `test_r31_typo_correction_reprint_collapse_requires_delta_classification` | yes | `tests\test_reconcile\test_classify.py:60:def test_r31_typo_correction_reprint_collapse_requires_delta_classification():` |
| SHIPPED | `test_r34_reference_copy_support_maps_rendering_to_reading_index` | yes | `tests\test_reconcile\test_assemble.py:164:def test_r34_reference_copy_support_maps_rendering_to_reading_index():` |
| SHIPPED | `test_r37_rendering_handle_tagged_segments_and_percent_encoded_slash` | yes | `tests\test_reconcile\test_integration.py:205:def test_r37_rendering_handle_tagged_segments_and_percent_encoded_slash():` |

### COMPLETION CRITERIA
- Criterion text: every Section 8 §"Reconcile" test in the locked plan passes; `match_explanations[]` arrays validate against the discriminated-union schema; running Reconcile on the `tests/fixtures/reconcile_goldens/schaff_herzog/` 10-block fixture produces a record byte-identical to the golden output.
- `MANUAL`: Criterion is prose or contains no direct shell command extracted for read-only execution.

### SCOPE CREEP
- `SCOPE_CREEP`: 29 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/lib/reconcile`, `build/lib`
  - `build/lib/__init__.py`
  - `build/lib/_generated_enums.py`
  - `build/lib/atomic_io.py`
  - `build/lib/bible_ref_normalizer.py`
  - `build/lib/block_id.py`
  - `build/lib/ccel_thml.py`
  - `build/lib/citation_parser.py`
  - `build/lib/config_validation.py`
  - `build/lib/contributors.py`
  - `build/lib/evidence_renderer_loader.py`
  - `build/lib/historical_lexicon.py`
  - `build/lib/lang_classifier.py`
  - `build/lib/layer_diff.py`
  - `build/lib/ocr_coordinates.py`
  - `build/lib/parser_regen_safety.py`
  - `build/lib/paths.py`
  - `build/lib/pdf_normalizer.py`
  - `build/lib/pdf_quality_gate.py`
  - `build/lib/render_cache.py`
  - `build/lib/resource_ids.py`
  - `build/lib/review_state.py`
  - `build/lib/review_warnings.py`
  - `build/lib/schema_enums.py`
  - `build/lib/scripture_canon.py`
  - `build/lib/sidecar_migrations.py`
  - `build/lib/text_extractor.py`
  - `build/lib/text_layers.py`
  - `build/lib/text_utils.py`
  - `build/lib/writer_identities.py`

## Slot 4 — ADR-0013 calibration gate (fixtures + script)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `tests/fixtures/calibration/score_bucket_boundaries/` | dir/6 tracked files | yes | directory at HEAD |
| SHIPPED | `tests/fixtures/calibration/reading_score_modifiers/` | dir/5 tracked files | yes | directory at HEAD |
| SHIPPED | `tests/fixtures/calibration/per_signal_contribution/` | dir/3 tracked files | yes | directory at HEAD |
| SHIPPED | `build/tools/calibration_report.py` | 278 | yes |  |

### NAMED TEST FUNCTIONS
- `MANUAL`: No named `test_...` functions appeared in this slot's `Tests first:` section after excluding test-file names.

### COMPLETION CRITERIA
- Criterion text: `py -3 -m pytest tests/test_adr0013_calibration_gate.py -v` is GREEN; `py -3 build/tools/calibration_report.py --json` writes a report whose `bucket_distribution` matches the fixture set's expected distribution and whose `per_signal_contributions` table is within tolerance of the golden values. **DONE:** Completed 2026-05-18. RED commit `53a165df`, GREEN commit `44dc0de0`. 1697/1697 tests pass.
- `PASS` `py -3 -m pytest tests/test_adr0013_calibration_gate.py -v` (exit `0`, 1.7s)

```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.0.2, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: <project-root>
configfile: pyproject.toml
plugins: anyio-4.13.0
collecting ... collected 3 items

tests/test_adr0013_calibration_gate.py::test_phase1_calibration_fixture_set_exists_and_runs PASSED [ 33%]
tests/test_adr0013_calibration_gate.py::test_reading_score_modifier_coverage PASSED [ 66%]
tests/test_adr0013_calibration_gate.py::test_score_bucket_boundaries PASSED [100%]

============================== 3 passed in 0.90s ==============================
```
- `PASS` `py -3 build/tools/calibration_report.py --json` (exit `0`, 0.3s)

```text
{
  "pass": true,
  "failures": [],
  "bucket_distribution": {
    "high": 1,
    "mid_high": 2,
    "mid_low": 2,
    "low": 1
  },
  "per_modifier_fired": {
    "broken_unicode": {
      "triggering_fired": true,
      "near_miss_fired": false
    },
    "lexicon": {
      "triggering_fired": true,
      "near_miss_fired": false
    },
    "ocr_confusion": {
      "triggering_fired": true,
      "near_miss_fired": false
    },
    "punctuation": {
      "triggering_fired": true,
      "near_miss_fired": false
    },
    "reference_only_advisory": {
      "triggering_fired": true,
      "near_miss_fired": false
    }
  },
  "per_signal_contributions": [
    {
      "fixture_id": "per_signal_annotation_dominant",
      "all_signals_match": true,
      "signal_results": [
        {
          "signal": "annotation_key",
          "expected": 30,
          "actual": 30,
          "match": true
        },
        {
          "signal": "text_similarity",
          "expected": 0,
          "actual": 0,
          "match": true
        },
        {
          "signal": "source_order",
          "expected": 15,
          "actual": 15,
          "match": true
        },
        {
          "signal": "block_type",
          "expected": 0,
          "actual": 0,
          "match": true
        },
        {
          "signal": "page_proximity",
          "expected": 0,
          "actual": 0,
          "match": true
        },
        {
          "signal": "language_profile",
          "expected": 0,
          "actual": 0,
          "match": true
        },
        {
          "signal": "ocr_skeleton",
          "expected": 0,
          "actual": 0,
          "match": true
        }
      ]
    },
    {
      "fixture_id": "per_signal_page_proximity_dominant",
      "all_signals_match": true,
      "signal_results": [
        {
          "signal": "annotation_key",
          "expected": 18,
          "actual": 18,
          "match": true
        },
        {
          "signal": "text_similarity",
          "expected": 0,
          "actual": 0,
          "match": true
        },
        {
          "signal": "source_order",
          "expected": 7,
          "actual": 7,
          "match": true
        },
        {
          "signal": "block_type",
          "expected": 5,
          "actual": 5,
          "match": true
        },
        {
          "signal": "page_proximity",
          "expected": 10,
          "actual": 10,
          "match": true
        },
        {
          "signal": "language_profile",
          "expected": 2,
          "actual": 2,
          "match": true
        },
        {
          "signal": "ocr_skeleton",
          "expected": 0,
          "actual": 0,
          "match": true
        }
      ]
    },
    {
      "fixture_id": "per_signal_text_similarity_dominant",
      "all_signals_match": true,
      "signal_results": [
        {
          "signal": "annotation_key",
          "expected": 0,
          "actual": 0,
          "match": true
        },
        {
          "signal": "text_similarity",
          "expected": 25,
          "actual": 25,
          "match": true
        },
        {
          "signal": "source_order",
          "expected": 15,
          "actual": 15,
          "match": true
        },
        {
          "signal": "block_type",
          "expected": 10,
          "actual": 10,
          "match": true
        },
        {
          "signal": "page_proximity",
          "expected": 0,
          "actual": 0,
          "match": true
        },
        {
          "signal": "language_profile",
          "expected": 5,
          "actual": 5,
          "match": true
        },
        {
          "signal": "ocr_skeleton",
          "expected": 5,
          "actual": 5,
          "match": true
        }
      ]
    }
  ],
  "boundary_results": [
    {
      "fixture_id": "boundary_score_44",
      "expected_score": 44,
      "actual_score": 44,
      "expected_bucket": "low",
      "actual_bucket": "low",
      "expected_action": "no_edge",
      "actual_action": "no_edge",
      "bucket_match": true,
      "action_match": true
    },
    {
      "fixture_id": "boundary_score_45",
      "expected_score": 45,
      "actual_score": 45,
      "expected_bucket": "mid_low",
      "actual_bucket": "mid_low",
      "expected_action": "no_cluster",
      "actual_action": "no_cluster",
      "bucket_match": true,
      "action_match": true
    },
    {
      "fixture_id": "boundary_score_59",
      "expected_score": 59,
      "actual_score": 59,
      "expected_bucket": "mid_low",
      "actual_bucket": "mid_low",
      "expected_action": "no_cluster",
      "actual_action": "no_cluster",
      "bucket_match": true,
      "action_match": true
    },
    {
      "fixture_id": "boundary_score_60",
      "expected_score": 60,
      "actual_score": 60,
      "expected_bucket": "mid_high",
      "actual_bucket": "mid_high",
      "expected_action": "cluster",
      "actual_action": "cluster",
      "bucket_match": true,
      "action_match": true
    },
    {
      "fixture_id": "boundary_score_77",
      "expected_score": 77,
      "actual_score": 77,
      "expected_bucket": "mid_high",
      "actual_bucket": "mid_high",
      "expected_action": "cluster",
      "actual_action": "cluster",
      "bucket_match": true,
      "action_match": true
    },
    {
      "fixture_id": "boundary_score_78",
      "expected_score": 78,
      "actual_score": 78,
      "expected_bucket": "high",
      "actual_bucket": "high",
      "expected_action": "cluster",
      "actual_action": "cluster",
      "bucket_match": true,
      "action_match": true
    }
  ],
  "modifier_results": [
    {
      "modifier": "broken_unicode",
      "triggering_fired": true,
      "near_miss_fired": false
    },
    {
      "modifier": "lexicon",
      "triggering_fired": true,
      "near_miss_fired": false
    },
    {
      "modifier": "ocr_confusion",
      "triggering_fired": true,
      "near_miss_fired": false
    },
    {
      "modifier": "punctuation",
      "triggering_fired": true,
      "near_miss_fired": false
    },
    {
      "modifier": "reference_only_advisory",
      "triggering_fired": true,
      "near_miss_fired": false
    }
  ]
}
```

### SCOPE CREEP
- `SCOPE_CREEP`: 210 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `tests/fixtures/calibration/score_bucket_boundaries`, `tests/fixtures/calibration/reading_score_modifiers`, `tests/fixtures/calibration/per_signal_contribution`, `build/tools`, `tests`
  - `tests/fixtures/calibration/score_bucket_boundaries/score_44_low.json`
  - `tests/fixtures/calibration/score_bucket_boundaries/score_45_mid_low.json`
  - `tests/fixtures/calibration/score_bucket_boundaries/score_59_mid_low.json`
  - `tests/fixtures/calibration/score_bucket_boundaries/score_60_mid_high.json`
  - `tests/fixtures/calibration/score_bucket_boundaries/score_77_mid_high.json`
  - `tests/fixtures/calibration/score_bucket_boundaries/score_78_high.json`
  - `tests/fixtures/calibration/reading_score_modifiers/broken_unicode.json`
  - `tests/fixtures/calibration/reading_score_modifiers/lexicon.json`
  - `tests/fixtures/calibration/reading_score_modifiers/ocr_confusion.json`
  - `tests/fixtures/calibration/reading_score_modifiers/punctuation.json`
  - `tests/fixtures/calibration/reading_score_modifiers/reference_only_advisory.json`
  - `tests/fixtures/calibration/per_signal_contribution/annotation_dominant.json`
  - `tests/fixtures/calibration/per_signal_contribution/page_proximity_dominant.json`
  - `tests/fixtures/calibration/per_signal_contribution/text_similarity_dominant.json`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/apply_review_patch.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bootstrap_renderings.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/derive_scan_jpegs.py`
  - `build/tools/export_hf_dataset.py`
  - `build/tools/fetch_rendering.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/inspect_review_patch.py`
  - `build/tools/lexicon_coverage_report.py`
  - `build/tools/migrate_schaff_herzog.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/modernise_record.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/parse_rendering.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/phase1_completion_audit.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/reconcile.py`
  - `build/tools/reconcile_status.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 5 — Transliterate engine + rulesets (`grc`, `hbo`)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/lib/modernisation/rulesets/transliteration/grc.yaml` | 122 | yes |  |
| SHIPPED | `build/lib/modernisation/rulesets/transliteration/hbo.yaml` | 98 | yes |  |
| SHIPPED | `build/lib/modernisation/engine.py` | 460 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_round_trip_per_language` | yes | `tests\test_transliterate.py:93:def test_round_trip_per_language() -> None:` |
| SHIPPED | `test_original_script_byte_preservation` | yes | `tests\test_transliterate.py:111:def test_original_script_byte_preservation() -> None:` |
| SHIPPED | `test_transliterated_from_for_latin_source_segments` | yes | `tests\test_transliterate.py:124:def test_transliterated_from_for_latin_source_segments() -> None:` |
| SHIPPED | `test_no_op_for_latin_only_blocks` | yes | `tests\test_transliterate.py:138:def test_no_op_for_latin_only_blocks() -> None:` |
| SHIPPED | `test_mixed_script_disagreement_carries_original_script` | yes | `tests\test_transliterate.py:148:def test_mixed_script_disagreement_carries_original_script() -> None:` |
| SHIPPED | `test_re_transliterate_preserves_editorial_overrides` | yes | `tests\test_transliterate.py:163:def test_re_transliterate_preserves_editorial_overrides() -> None:` |

### COMPLETION CRITERIA
- Criterion text: every Section 8 §"Transliterate" test passes; Transliterate run on a Schaff-Herzog vol-01 fixture page surfaces `transliterated_from: "grc"` on `agapē` and `transliterated_from: "hbo"` on `Yahweh` (Phase 1's main exercise of the pipeline — active transliteration is rare).
- `MANUAL`: Criterion is prose or contains no direct shell command extracted for read-only execution.

### SCOPE CREEP
- `SCOPE_CREEP`: 151 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/lib/modernisation/rulesets/transliteration`, `build/lib/modernisation`, `tests`
  - `build/lib/modernisation/__init__.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 6 — Modernise engine + en@1.0.0 ruleset (fixture-tested; NOT corpus-applied to Schaff-Herzog — R43)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/lib/modernisation/engine.py` | 460 | yes |  |
| SHIPPED | `build/lib/modernisation/rulesets/en.yaml` | 67 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_eth_rule_fires_correctly` | yes | `tests\test_modernise.py:27:def test_eth_rule_fires_correctly():` |
| SHIPPED | `test_editorial_modernisation_entry_survives_re_modernise` | yes | `tests\test_modernise.py:50:def test_editorial_modernisation_entry_survives_re_modernise():` |
| SHIPPED | `test_reviewer_override_survives_re_modernise` | yes | `tests\test_modernise.py:77:def test_reviewer_override_survives_re_modernise():` |
| SHIPPED | `test_english_ruleset_v1_round_trip` | yes | `tests\test_modernise.py:111:def test_english_ruleset_v1_round_trip():` |

### COMPLETION CRITERIA
- Criterion text: every Section 8 §"Modernise" test passes; `py -3 build/lib/modernisation/engine.py` against the 5 fixture records produces modernised siblings that validate against `modernised_record.schema.json` and pass every Modernisation Completeness Checker sub-check; **no `data/<work>/modernised/` directory is corpus-populated for Schaff-Herzog**.
- `PASS` `py -3 build/lib/modernisation/engine.py` (exit `0`, 0.3s)

```text
OK catechism.json
OK hymn.json
OK schaff_herzog.json
OK spurgeon.json
OK wesley.json
```

### SCOPE CREEP
- `SCOPE_CREEP`: 151 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/lib/modernisation`, `build/lib/modernisation/rulesets`, `tests`
  - `build/lib/modernisation/__init__.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 7 — Checkers wired (8 of them)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/lib/warning_producers/attestation_coverage.py` | 53 | yes |  |
| SHIPPED | `build/lib/warning_producers/disagreement_classification.py` | 57 | yes |  |
| SHIPPED | `build/lib/warning_producers/language_confidence.py` | 72 | yes |  |
| SHIPPED | `build/lib/warning_producers/transliteration_completeness.py` | 69 | yes |  |
| SHIPPED | `build/lib/warning_producers/source_page_coverage.py` | 61 | yes |  |
| SHIPPED | `build/lib/warning_producers/modernisation_completeness.py` | 306 | yes |  |
| SHIPPED | `build/lib/warning_producers/paired_record_invariant.py` | 81 | yes |  |
| SHIPPED | `build/lib/warning_producers/within_edition_divergence.py` | 73 | yes |  |
| SHIPPED | `build/lib/warning_producers/attested_by_reference_resolution.py` | 71 | yes |  |
| SHIPPED | `build/lib/warning_producers/paired_with_reference_resolution.py` | 56 | yes |  |
| SHIPPED | `build/lib/warning_producers/modernisation_coverage_consistency.py` | 106 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_mod_stale_ruleset` | yes | `tests\test_warning_producer_modernisation_completeness.py:39:def test_mod_stale_ruleset() -> None:` |
| SHIPPED | `test_mod_span_inconsistent` | yes | `tests\test_warning_producer_modernisation_completeness.py:61:def test_mod_span_inconsistent() -> None:` |
| SHIPPED | `test_mod_translit_inconsistent` | yes | `tests\test_warning_producer_modernisation_completeness.py:72:def test_mod_translit_inconsistent() -> None:` |
| SHIPPED | `test_mod_rule_gone` | yes | `tests\test_warning_producer_modernisation_completeness.py:109:def test_mod_rule_gone() -> None:` |
| SHIPPED | `test_mod_delta_unreconstructable` | yes | `tests\test_warning_producer_modernisation_completeness.py:120:def test_mod_delta_unreconstructable() -> None:` |
| SHIPPED | `test_paired_record_invariant` | yes | `tests\test_warning_producer_paired_record_invariant.py:43:def test_paired_record_invariant() -> None:` |
| SHIPPED | `test_pass_then_fail_across_two_gates` | yes | `tests\test_warning_producers_registry.py:325:def test_pass_then_fail_across_two_gates() -> None:` |
| SHIPPED | `test_modernise_gate_enforcement` | yes | `tests\test_warning_producers_registry.py:354:def test_modernise_gate_enforcement() -> None:` |
| SHIPPED | `test_within_edition_divergence_checker` | yes | `tests\test_warning_producer_within_edition_divergence.py:11:def test_within_edition_divergence_checker() -> None:` |
| SHIPPED | `test_source_page_coverage_checker` | yes | `tests\test_warning_producer_source_page_coverage.py:24:def test_source_page_coverage_checker() -> None:` |
| SHIPPED | `test_attested_by_reference_resolution` | yes | `tests\test_warning_producer_attested_by_reference_resolution.py:20:def test_attested_by_reference_resolution() -> None:` |
| SHIPPED | `test_paired_with_reference_resolution` | yes | `tests\test_warning_producer_paired_with_reference_resolution.py:25:def test_paired_with_reference_resolution(tmp_path) -> None:` |
| SHIPPED | `test_modernisation_coverage_consistency` | yes | `tests\test_warning_producer_modernisation_coverage_consistency.py:23:def test_modernisation_coverage_consistency(tmp_path) -> None:` |

### COMPLETION CRITERIA
- Criterion text: every Section 8 Checker test passes; running every Checker against the Slot 6 fixture records produces zero false positives and the expected positives.
- `MANUAL`: Criterion is prose or contains no direct shell command extracted for read-only execution.

### SCOPE CREEP
- `SCOPE_CREEP`: 158 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/lib/warning_producers`, `tests`
  - `build/lib/warning_producers/__init__.py`
  - `build/lib/warning_producers/coverage.py`
  - `build/lib/warning_producers/historical_lexicon.py`
  - `build/lib/warning_producers/llm_triage.py`
  - `build/lib/warning_producers/ocr_scanner.py`
  - `build/lib/warning_producers/structural_integrity.py`
  - `build/lib/warning_producers/taxonomy_consistency.py`
  - `build/lib/warning_producers/text_suspicion.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 8 — Reviewer UI extension (5 affordances + split-pane + bbox + scan-derived + 3 sample pages)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/tools/derive_scan_jpegs.py` | 20 | yes |  |
| SHIPPED | `tests/fixtures/scan_samples/ia/schaff/encyclopedia/1908-1914/ocr/p001.webp` | binary/38 bytes | yes | binary |
| SHIPPED | `build/lib/review_ui_js/` | dir/7 tracked files | yes | directory at HEAD |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_render_review_html_emits_split_pane` | yes | `tests\test_render_review_html.py:288:def test_render_review_html_emits_split_pane():` |
| SHIPPED | `test_render_review_html_loads_scan_via_webp_derivative` | yes | `tests\test_render_review_html.py:296:def test_render_review_html_loads_scan_via_webp_derivative():` |
| SHIPPED | `test_bbox_highlight_fires_on_hocr_block` | yes | `tests\test_render_review_html_split_pane.py:75:def test_bbox_highlight_fires_on_hocr_block():` |
| SHIPPED | `test_bbox_highlight_falls_back_when_bbox_absent` | yes | `tests\test_render_review_html_split_pane.py:89:def test_bbox_highlight_falls_back_when_bbox_absent():` |
| SHIPPED | `test_disagreement_adjudication_affordance` | yes | `tests\test_render_review_html_affordances.py:85:def test_disagreement_adjudication_affordance():` |
| SHIPPED | `test_structural_disagreement_split_merge_interactions` | yes | `tests\test_render_review_html_affordances.py:103:def test_structural_disagreement_split_merge_interactions():` |
| SHIPPED | `test_modernisation_accept_override_per_token` | yes | `tests\test_render_review_html_affordances.py:122:def test_modernisation_accept_override_per_token():` |
| SHIPPED | `test_catalog_management_promote_demote` | yes | `tests\test_render_review_html_affordances.py:141:def test_catalog_management_promote_demote():` |
| SHIPPED | `test_derive_scan_jpegs_writes_lossless_webp` | yes | `tests\test_derive_scan_jpegs.py:7:def test_derive_scan_jpegs_writes_lossless_webp(tmp_path: Path):` |

### COMPLETION CRITERIA
- Criterion text: every Section 8 Reviewer-UI test passes; aggregate interactive JS LoC under 1900 (ADR-0012 ceiling) — if over, the slot escalates per the ADR's tripwire; `render_review_html` run against a Slot 6 fixture record produces an HTML page that opens cleanly in Chrome and Firefox from a `file://` URL.
- `MANUAL`: Criterion is prose or contains no direct shell command extracted for read-only execution.

### SCOPE CREEP
- `SCOPE_CREEP`: 235 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/lib`, `build/tools`, `tests/fixtures/scan_samples/ia/schaff/encyclopedia/1908-1914/ocr`, `build/lib/review_ui_js`, `tests`
  - `build/lib/__init__.py`
  - `build/lib/_generated_enums.py`
  - `build/lib/atomic_io.py`
  - `build/lib/bible_ref_normalizer.py`
  - `build/lib/block_id.py`
  - `build/lib/ccel_thml.py`
  - `build/lib/citation_parser.py`
  - `build/lib/config_validation.py`
  - `build/lib/contributors.py`
  - `build/lib/evidence_renderer_loader.py`
  - `build/lib/historical_lexicon.py`
  - `build/lib/lang_classifier.py`
  - `build/lib/layer_diff.py`
  - `build/lib/ocr_coordinates.py`
  - `build/lib/parser_regen_safety.py`
  - `build/lib/paths.py`
  - `build/lib/pdf_normalizer.py`
  - `build/lib/pdf_quality_gate.py`
  - `build/lib/render_cache.py`
  - `build/lib/resource_ids.py`
  - `build/lib/review_state.py`
  - `build/lib/review_warnings.py`
  - `build/lib/schema_enums.py`
  - `build/lib/scripture_canon.py`
  - `build/lib/sidecar_migrations.py`
  - `build/lib/text_alignment.py`
  - `build/lib/text_extractor.py`
  - `build/lib/text_layers.py`
  - `build/lib/text_utils.py`
  - `build/lib/writer_identities.py`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/apply_review_patch.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bootstrap_renderings.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/calibration_report.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/export_hf_dataset.py`
  - `build/tools/fetch_rendering.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/inspect_review_patch.py`
  - `build/tools/lexicon_coverage_report.py`
  - `build/tools/migrate_schaff_herzog.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/modernise_record.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/parse_rendering.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/phase1_completion_audit.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/reconcile.py`
  - `build/tools/reconcile_status.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`
  - `tests/fixtures/scan_samples/ia/schaff/encyclopedia/1908-1914/ocr/p002.webp`
  - `tests/fixtures/scan_samples/ia/schaff/encyclopedia/1908-1914/ocr/p003.webp`
  - `build/lib/review_ui_js/__init__.py`
  - `build/lib/review_ui_js/bbox_highlight.js`
  - `build/lib/review_ui_js/catalog_management.js`
  - `build/lib/review_ui_js/disagreement_affordance.js`
  - `build/lib/review_ui_js/modernisation_affordance.js`
  - `build/lib/review_ui_js/split_pane.js`
  - `build/lib/review_ui_js/structural_affordance.js`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 9 — Review-patch persistence (schema is already locked in Slot 1; apply + inspect tooling here)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/tools/apply_review_patch.py` | 162 | yes |  |
| SHIPPED | `build/tools/inspect_review_patch.py` | 33 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_review_patch_round_trip_via_apply_review_patch` | yes | `tests\test_review_patch_round_trip.py:174:def test_review_patch_round_trip_via_apply_review_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:` |
| SHIPPED | `test_content_hash_drift_detection` | yes | `tests\test_content_hash_drift_detection.py:103:def test_content_hash_drift_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:` |
| SHIPPED | `test_inspect_review_patch_is_read_only` | yes | `tests\test_inspect_review_patch_is_read_only.py:111:def test_inspect_review_patch_is_read_only(` |

### COMPLETION CRITERIA
- Criterion text: every Section 8 §"Reviewer UI persistence" test passes; running `apply_review_patch.py` against a Slot 8-generated patch updates audit/catalog/workbench correctly. **DONE:** Completed 2026-05-18. RED commit `6aca06ad`, GREEN commit `57e873cf`. 1821/1821 tests pass.
- `MANUAL`: Criterion is prose or contains no direct shell command extracted for read-only execution.

### SCOPE CREEP
- `SCOPE_CREEP`: 193 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/tools`, `tests`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bootstrap_renderings.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/calibration_report.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/derive_scan_jpegs.py`
  - `build/tools/export_hf_dataset.py`
  - `build/tools/fetch_rendering.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/lexicon_coverage_report.py`
  - `build/tools/migrate_schaff_herzog.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/modernise_record.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/parse_rendering.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/phase1_completion_audit.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/reconcile.py`
  - `build/tools/reconcile_status.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 10 — CLI tooling (catalog population, reconcile, dry-run, anchor-swap, bootstrap, status)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/tools/fetch_rendering.py` | 88 | yes |  |
| SHIPPED | `build/tools/parse_rendering.py` | 91 | yes |  |
| SHIPPED | `build/tools/bootstrap_renderings.py` | 123 | yes |  |
| SHIPPED | `build/tools/reconcile.py` | 222 | yes |  |
| SHIPPED | `build/tools/reconcile_status.py` | 90 | yes |  |
| SHIPPED | `build/tools/modernise_record.py` | 50 | yes |  |
| SHIPPED | `build/tools/migrate_schaff_herzog.py` | 405 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_bootstrap_renderings_per_work` | yes | `tests\test_bootstrap_renderings.py:43:def test_bootstrap_renderings_per_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:` |
| SHIPPED | `test_reconcile_anchor_swap_atomic` | yes | `tests\test_reconcile_cli.py:112:def test_reconcile_anchor_swap_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:` |
| SHIPPED | `test_reconcile_status_four_dimensions` | yes | `tests\test_reconcile_status.py:48:def test_reconcile_status_four_dimensions(` |

### COMPLETION CRITERIA
- Criterion text: every Section 8 §"Catalog & roles" test passes; `py -3 build/tools/reconcile.py --help` and each sibling tool emit usable help; bootstrap_renderings runs end-to-end against a hand-crafted catalog fixture.
- `PASS` `py -3 build/tools/reconcile.py --help` (exit `0`, 0.2s)

```text
usage: reconcile.py [-h] [--dry-run]
                    [--superseding-rendering SUPERSEDING_RENDERING]
                    [--supersedes SUPERSEDES]
                    [work_handle]

Run Reconcile operations.

positional arguments:
  work_handle

options:
  -h, --help            show this help message and exit
  --dry-run
  --superseding-rendering SUPERSEDING_RENDERING
  --supersedes SUPERSEDES
```
- `PASS` `py -3 build/tools/fetch_rendering.py --help` (exit `0`, 0.3s)

```text
usage: fetch_rendering.py [-h] [--work-handle WORK_HANDLE]
                          [--rendering-id RENDERING_ID]
                          source_url

Fetch and cache one rendering source.

positional arguments:
  source_url

options:
  -h, --help            show this help message and exit
  --work-handle WORK_HANDLE
  --rendering-id RENDERING_ID
```
- `PASS` `py -3 build/tools/parse_rendering.py --help` (exit `0`, 0.2s)

```text
usage: parse_rendering.py [-h] rendering_id

Parse a cached rendering.

positional arguments:
  rendering_id

options:
  -h, --help    show this help message and exit
```
- `PASS` `py -3 build/tools/bootstrap_renderings.py --help` (exit `0`, 0.3s)

```text
usage: bootstrap_renderings.py [-h] [work_handle]

Bootstrap all renderings for a work.

positional arguments:
  work_handle

options:
  -h, --help   show this help message and exit
```
- `PASS` `py -3 build/tools/reconcile_status.py --help` (exit `0`, 0.3s)

```text
usage: reconcile_status.py [-h] [--json] work_handle

Report Reviewer-clean status.

positional arguments:
  work_handle

options:
  -h, --help   show this help message and exit
  --json
```
- `PASS` `py -3 build/tools/modernise_record.py --help` (exit `0`, 0.3s)

```text
usage: modernise_record.py [-h] record_path

Modernise one Reviewer-clean record.

positional arguments:
  record_path

options:
  -h, --help   show this help message and exit
```
- `PASS` `py -3 build/tools/migrate_schaff_herzog.py --help` (exit `0`, 0.2s)

```text
usage: migrate_schaff_herzog.py [-h] [--dry-run] [work_handle]

Migrate Schaff-Herzog records. Populated in Slot 11.

positional arguments:
  work_handle  Work handle, e.g. reference/schaff/encyclopedia/1908-1914.

options:
  -h, --help   show this help message and exit
  --dry-run    Reserved for Slot 11.
```

### SCOPE CREEP
- `SCOPE_CREEP`: 181 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/tools`, `tests`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/apply_review_patch.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/calibration_report.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/derive_scan_jpegs.py`
  - `build/tools/export_hf_dataset.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/inspect_review_patch.py`
  - `build/tools/lexicon_coverage_report.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/phase1_completion_audit.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 11 — Schaff-Herzog migration (two-rendering record, Reviewer-clean on `original`, `modernised` empty per R43)

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `data/reference/schaff/encyclopedia/1908-1914/catalog.json` | 48 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_block_count_preservation_where_applicable` | yes | `tests\test_migrate_schaff_herzog.py:71:def test_block_count_preservation_where_applicable(tmp_path):` |
| SHIPPED | `test_text_concatenation_equality` | yes | `tests\test_migrate_schaff_herzog.py:80:def test_text_concatenation_equality(tmp_path):` |
| SHIPPED | `test_annotation_presence` | yes | `tests\test_migrate_schaff_herzog.py:89:def test_annotation_presence(tmp_path):` |
| SHIPPED | `test_old_to_new_review_state_mapping_count` | yes | `tests\test_migrate_schaff_herzog.py:97:def test_old_to_new_review_state_mapping_count(tmp_path):` |
| SHIPPED | `test_schema_validation_post_migration` | yes | `tests\test_migrate_schaff_herzog.py:126:def test_schema_validation_post_migration(tmp_path):` |
| SHIPPED | `test_audit_append_validation` | yes | `tests\test_migrate_schaff_herzog.py:135:def test_audit_append_validation(tmp_path):` |
| SHIPPED | `test_r70_migration_writes_operator_chosen_anchor` | yes | `tests\test_r70_migration_writes_operator_chosen_anchor.py:34:def test_r70_migration_writes_operator_chosen_anchor(tmp_path, monkeypatch):` |
| SHIPPED | `test_r70_migration_resumes_after_post_anchor_abort` | yes | `tests\test_migrate_schaff_herzog.py:149:def test_r70_migration_resumes_after_post_anchor_abort(tmp_path, monkeypatch):` |
| SHIPPED | `test_r68_migration_preflight_rejects_unremoved_consumers` | yes | `tests\test_r68_migration_preflight_rejects_unremoved_consumers.py:28:def test_r68_migration_preflight_rejects_unremoved_consumers(tmp_path):` |
| SHIPPED | `test_r68_migration_drops_summary_and_key_quote_fields` | yes | `tests\test_migrate_schaff_herzog.py:178:def test_r68_migration_drops_summary_and_key_quote_fields(tmp_path):` |

### COMPLETION CRITERIA
- Criterion text: `py -3 build/tools/reconcile_status.py reference/schaff/encyclopedia/1908-1914 --json` returns clean across all four R44 dimensions on the `original` config; `data/reference/schaff/encyclopedia/1908-1914/modernised/` is empty (no JSON files); every migration-invariant test in Section 8 passes; `compare_text_witness.py` is removed from `git ls-files`.
- `PASS` `py -3 build/tools/reconcile_status.py reference/schaff/encyclopedia/1908-1914 --json` (exit `0`, 2.2s)

```text
{
  "dimensions": {
    "audit_log_incomplete": {
      "clean": true
    },
    "catalog_pending": {
      "clean": true,
      "renderings": []
    },
    "checker_warnings": {
      "clean": true,
      "count": 0
    },
    "workbench_pending": {
      "clean": true,
      "entries": []
    }
  },
  "reviewer_clean": true,
  "work_handle": "reference/schaff/encyclopedia/1908-1914"
}
```
- `PASS` `git ls-files build/tools/compare_text_witness.py` (exit `0`, 0.0s)

```text
(no output)
```

### SCOPE CREEP
- `SCOPE_CREEP`: 196 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `data/reference/schaff/encyclopedia/1908-1914`, `build/tools`, `tests`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/apply_review_patch.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bootstrap_renderings.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/calibration_report.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/derive_scan_jpegs.py`
  - `build/tools/export_hf_dataset.py`
  - `build/tools/fetch_rendering.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/inspect_review_patch.py`
  - `build/tools/lexicon_coverage_report.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/modernise_record.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/parse_rendering.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/phase1_completion_audit.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/reconcile.py`
  - `build/tools/reconcile_status.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_export_hf_dataset.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_publisher_glob_finds_all_records.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 12 — Publish local-export

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/tools/export_hf_dataset.py` | 185 | yes |  |
| MISSING | `exports/` | dir/0 tracked files | no | directory at HEAD |
| SHIPPED | `docs/HUGGINGFACE_DATASET_CARD.md` | 134 | yes |  |

### NAMED TEST FUNCTIONS
| Status | Function | Found | Evidence |
|---|---|---|---|
| SHIPPED | `test_exports_artefact_validates` | yes | `tests\test_export_hf_dataset.py:172:def test_exports_artefact_validates(tmp_path: Path) -> None:` |
| SHIPPED | `test_two_config_split_correct` | yes | `tests\test_export_hf_dataset.py:190:def test_two_config_split_correct(tmp_path: Path) -> None:` |
| SHIPPED | `test_coverage_gap_dataset_card_surfacing` | yes | `tests\test_export_hf_dataset.py:205:def test_coverage_gap_dataset_card_surfacing(tmp_path: Path) -> None:` |
| SHIPPED | `test_publisher_glob_finds_all_records` | yes | `tests\test_publisher_glob_finds_all_records.py:120:def test_publisher_glob_finds_all_records(tmp_path: Path) -> None:` |

### COMPLETION CRITERIA
- Criterion text: `py -3 build/tools/export_hf_dataset.py` writes to `exports/`; `load_dataset("local-path", "original")` and `load_dataset("local-path", "modernised")` succeed; the dataset card includes the R65 modernisation-coverage-gap table with Schaff-Herzog listed as `original`: present, `modernised`: absent.
- `MANUAL` `py -3 build/tools/export_hf_dataset.py` (exit `None`, 0.0s)

```text
NOT RUN: command intentionally writes non-audit artefacts; audit safety constraint says read-only except audits/A5-codex-round1.md.
```
- `FAIL` `py -3 -c from datasets import load_dataset; load_dataset('exports', 'original'); load_dataset('exports', 'modernised')` (exit `1`, 0.2s)

```text
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    from datasets import load_dataset; load_dataset('exports', 'original'); load_dataset('exports', 'modernised')
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'datasets'
```

### SCOPE CREEP
- `SCOPE_CREEP`: 206 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/tools`, `exports`, `docs`, `tests`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/apply_review_patch.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bootstrap_renderings.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/calibration_report.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/derive_scan_jpegs.py`
  - `build/tools/fetch_rendering.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/inspect_review_patch.py`
  - `build/tools/lexicon_coverage_report.py`
  - `build/tools/migrate_schaff_herzog.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/modernise_record.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/parse_rendering.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/phase1_completion_audit.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/reconcile.py`
  - `build/tools/reconcile_status.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`
  - `docs/CHURCH_FATHERS_CURATION_HANDBOOK.md`
  - `docs/CODEX_SCHEMA_REVIEW.md`
  - `docs/CODEX_SCHEMA_REVIEW_PROMPT.md`
  - `docs/PROJECT_CONTEXT.md`
  - `docs/SCHEMA_RED_TEAM_BRIEF.md`
  - `docs/SCHEMA_RED_TEAM_REPORT.md`
  - `docs/SCHEMA_SPEC.md`
  - `docs/SEMANTIC_CROSS_REFERENCE_NOTES.md`
  - `docs/WESTMINSTER_STANDARDS_IMPLEMENTATION_PLAN.md`
  - `docs/WESTMINSTER_STANDARDS_SCRAPER_SPEC.md`
  - `docs/spurgeon_mtp_missing_sermons.md`
  - `tests/probe_ordinal_parser.py`
  - `tests/test_a1_schemas.py`
  - `tests/test_adr0013_calibration_gate.py`
  - `tests/test_apply_correction.py`
  - `tests/test_apply_corrections.py`
  - `tests/test_atomic_io.py`
  - `tests/test_bible_ref_normalizer.py`
  - `tests/test_block_id.py`
  - `tests/test_bootstrap_renderings.py`
  - `tests/test_bulk_review_writer.py`
  - `tests/test_ccel_anf.py`
  - `tests/test_ccel_church_history.py`
  - `tests/test_ccel_evangelical_holiness.py`
  - `tests/test_ccel_npnf1.py`
  - `tests/test_ccel_npnf2.py`
  - `tests/test_ccel_puritan_works.py`
  - `tests/test_ccel_schaff_hcc.py`
  - `tests/test_citation_parser.py`
  - `tests/test_compare_text_witness_alignment.py`
  - `tests/test_config_validation.py`
  - `tests/test_content_hash_drift_detection.py`
  - `tests/test_contributor_schema.py`
  - `tests/test_correction_ledger.py`
  - `tests/test_coverage_parameter_provenance.py`
  - `tests/test_coverage_resource_type_pair_validity.py`
  - `tests/test_coverage_strategies.py`
  - `tests/test_dead_letter_index.py`
  - `tests/test_dead_letter_replay.py`
  - `tests/test_derive_scan_jpegs.py`
  - `tests/test_evidence_renderer_load.py`
  - `tests/test_fetch_rendering.py`
  - `tests/test_generated_enums.py`
  - `tests/test_gutenberg_anglican.py`
  - `tests/test_gutenberg_evangelical.py`
  - `tests/test_gutenberg_puritan.py`
  - `tests/test_gutenberg_sermons.py`
  - `tests/test_gutenberg_systematics.py`
  - `tests/test_historical_lexicon.py`
  - `tests/test_hooker_gutenberg_systematics.py`
  - `tests/test_hymnary_pd.py`
  - `tests/test_ia_fisher_marrow.py`
  - `tests/test_ia_hastings_dictionary.py`
  - `tests/test_ia_schaff_herzog_parsing.py`
  - `tests/test_ia_schaff_herzog_units.py`
  - `tests/test_inspect_review_patch_is_read_only.py`
  - `tests/test_lang_classifier.py`
  - `tests/test_lang_classifier_confidence_bands.py`
  - `tests/test_layer2_floor_prevents_cld3_fallthrough.py`
  - `tests/test_layer_diff.py`
  - `tests/test_lexicon_coverage_report.py`
  - `tests/test_lexicon_coverage_status_gating.py`
  - `tests/test_lexicon_per_language_dispatch.py`
  - `tests/test_luther_gutenberg_systematics.py`
  - `tests/test_maclaren_ref_extraction.py`
  - `tests/test_match_explanations_discriminated_union.py`
  - `tests/test_migrate_schaff_herzog.py`
  - `tests/test_migrate_sidecars.py`
  - `tests/test_mixed_script_flag.py`
  - `tests/test_modernise.py`
  - `tests/test_modernise_record_cli.py`
  - `tests/test_naves_osis.py`
  - `tests/test_ocr_coordinates.py`
  - `tests/test_ocr_ensemble_compare.py`
  - `tests/test_ocr_ensemble_compare_alignment.py`
  - `tests/test_ocr_models.py`
  - `tests/test_ocr_patterns.py`
  - `tests/test_ocr_report.py`
  - `tests/test_ocr_scanner.py`
  - `tests/test_ordinal_parser.py`
  - `tests/test_parse_rendering.py`
  - `tests/test_parser_output_invariants.py`
  - `tests/test_parser_regen_safety.py`
  - `tests/test_paths.py`
  - `tests/test_pending_dry_run_emits_report_without_attestation_mutation.py`
  - `tests/test_phase1_block_type_enum_rejects_phase2_types_until_staged.py`
  - `tests/test_phase1_completion_audit.py`
  - `tests/test_phase1_lexicon_rename_no_regression.py`
  - `tests/test_phase1_reference_resource_registry_validation.py`
  - `tests/test_propose_correction.py`
  - `tests/test_r19_catalog_record_pd_anchor_consistency.py`
  - `tests/test_r33_language_segments_shared_fields_equal_across_sibling_configs.py`
  - `tests/test_r58_ocr_promotion_compound_gate.py`
  - `tests/test_r59_engine_field_captured_from_runtime.py`
  - `tests/test_r59_ocr_bytes_changed_preserves_reviewer_decisions.py`
  - `tests/test_r59_rendering_supersession_preserves_bytes.py`
  - `tests/test_r68_migration_preflight_rejects_unremoved_consumers.py`
  - `tests/test_r70_migration_writes_operator_chosen_anchor.py`
  - `tests/test_reconcile_cli.py`
  - `tests/test_reconcile_status.py`
  - `tests/test_regenerate_layers_commentary.py`
  - `tests/test_regenerate_layers_reference_entry.py`
  - `tests/test_rekey_review_state.py`
  - `tests/test_render_cache.py`
  - `tests/test_render_corpus_dashboard.py`
  - `tests/test_render_ocr_disagreement_html.py`
  - `tests/test_render_review_html.py`
  - `tests/test_render_review_html_affordances.py`
  - `tests/test_render_review_html_html_escape.py`
  - `tests/test_render_review_html_split_pane.py`
  - `tests/test_render_review_html_viewport.py`
  - `tests/test_render_strategies_dispatch.py`
  - `tests/test_render_strategy_commentary_snapshot.py`
  - `tests/test_render_strategy_encyclopedia_snapshot.py`
  - `tests/test_resource_ids.py`
  - `tests/test_review_patch_round_trip.py`
  - `tests/test_review_state.py`
  - `tests/test_review_warnings.py`
  - `tests/test_scanner_max_candidates_sentinel.py`
  - `tests/test_scans_manifest_load.py`
  - `tests/test_schema_default_resource_type_drift.py`
  - `tests/test_schema_enums.py`
  - `tests/test_sh_parser_anchor_fixture.py`
  - `tests/test_sidecar_migrations.py`
  - `tests/test_source_transliteration_coverage.py`
  - `tests/test_source_transliteration_lexicon_detects_grc_hbo.py`
  - `tests/test_spurgeon_split.py`
  - `tests/test_surface_field_invariant.py`
  - `tests/test_text_alignment.py`
  - `tests/test_text_confidence_report.py`
  - `tests/test_text_extractor.py`
  - `tests/test_text_layers.py`
  - `tests/test_text_utils.py`
  - `tests/test_transliterate.py`
  - `tests/test_update_review_state.py`
  - `tests/test_upstream_output_typing.py`
  - `tests/test_versification_map.py`
  - `tests/test_warning_producer_attestation_coverage.py`
  - `tests/test_warning_producer_attested_by_reference_resolution.py`
  - `tests/test_warning_producer_disagreement_classification.py`
  - `tests/test_warning_producer_historical_lexicon.py`
  - `tests/test_warning_producer_language_confidence.py`
  - `tests/test_warning_producer_llm_triage.py`
  - `tests/test_warning_producer_modernisation_completeness.py`
  - `tests/test_warning_producer_modernisation_coverage_consistency.py`
  - `tests/test_warning_producer_ocr_scanner.py`
  - `tests/test_warning_producer_paired_record_invariant.py`
  - `tests/test_warning_producer_paired_with_reference_resolution.py`
  - `tests/test_warning_producer_source_page_coverage.py`
  - `tests/test_warning_producer_structural_integrity.py`
  - `tests/test_warning_producer_taxonomy_consistency.py`
  - `tests/test_warning_producer_text_suspicion.py`
  - `tests/test_warning_producer_transliteration_completeness.py`
  - `tests/test_warning_producer_within_edition_divergence.py`
  - `tests/test_warning_producers_registry.py`
  - `tests/test_warning_signature_stability.py`
  - `tests/test_witness_inventory.py`
  - `tests/test_witness_registry.py`
  - `tests/test_writer_manifest_gate.py`
  - `tests/test_writer_manifest_gate_allow_case.py`

## Slot 13 — Completion-gate audit

### FILE EXISTENCE
| Status | Path | Approx line count | Substantive | Note |
|---|---|---|---|---|
| SHIPPED | `build/tools/phase1_completion_audit.py` | 174 | yes |  |
| MISSING | `LAST_SESSION_<timestamp>_phase1_complete.md` | glob | no | no tracked match at HEAD |

### NAMED TEST FUNCTIONS
- `MANUAL`: No named `test_...` functions appeared in this slot's `Tests first:` section after excluding test-file names.

### COMPLETION CRITERIA
- Criterion text: `py -3 build/tools/phase1_completion_audit.py --json` exits 0 with `{ "tdd_conformance": "pass", "adr0013_calibration": "pass", "schaff_herzog_reviewer_clean": "pass" }`; the LAST_SESSION file records the audit outputs.
- `MANUAL` `py -3 build/tools/phase1_completion_audit.py --json` (exit `None`, 0.0s)

```text
NOT RUN: command intentionally writes non-audit artefacts; audit safety constraint says read-only except audits/A5-codex-round1.md.
```

### SCOPE CREEP
- `SCOPE_CREEP`: 46 extra direct tracked files found in parsed touched directories beyond this slot's `Files:` list.
- Touched dirs checked: `build/tools`
  - `build/tools/acceptance_review_task3_anf_npnf2_hooker.md`
  - `build/tools/apply_correction.py`
  - `build/tools/apply_review_patch.py`
  - `build/tools/audit_data_accuracy.py`
  - `build/tools/audit_ref_coverage.py`
  - `build/tools/bootstrap_renderings.py`
  - `build/tools/bulk_review_writer.py`
  - `build/tools/calibration_report.py`
  - `build/tools/check_schema_enums_fresh.py`
  - `build/tools/check_witness_inventory.py`
  - `build/tools/check_writer_manifest_gate.py`
  - `build/tools/correction_ledger.py`
  - `build/tools/derive_scan_jpegs.py`
  - `build/tools/export_hf_dataset.py`
  - `build/tools/fetch_rendering.py`
  - `build/tools/generate_schema_enums.py`
  - `build/tools/generate_sh_inventory.py`
  - `build/tools/inspect_bcp1928_structure.py`
  - `build/tools/inspect_review_patch.py`
  - `build/tools/lexicon_coverage_report.py`
  - `build/tools/migrate_schaff_herzog.py`
  - `build/tools/migrate_sidecars.py`
  - `build/tools/modernise_record.py`
  - `build/tools/npnf1_census.py`
  - `build/tools/ocr_ensemble_compare.py`
  - `build/tools/parse_rendering.py`
  - `build/tools/patch_schaff_source_pages.py`
  - `build/tools/pre_commit_pytest.py`
  - `build/tools/propose_correction.py`
  - `build/tools/puritan_census.py`
  - `build/tools/reconcile.py`
  - `build/tools/reconcile_status.py`
  - `build/tools/red_team_digest.md`
  - `build/tools/red_team_report.md`
  - `build/tools/regenerate_layers.py`
  - `build/tools/rekey_review_state.py`
  - `build/tools/render_corpus_dashboard.py`
  - `build/tools/render_ocr_disagreement_html.py`
  - `build/tools/render_review_html.py`
  - `build/tools/replay_dead_letter.py`
  - `build/tools/scaffold_witness_inventory.py`
  - `build/tools/split_schaff_merged.py`
  - `build/tools/text_confidence_report.py`
  - `build/tools/update_dead_letter_index.py`
  - `build/tools/update_review_state.py`
  - `build/tools/witness_registry.py`

## Summary

- Total `SHIPPED`: 153
- Total `MISSING`: 8
- Total `SCOPE_CREEP`: 2432

Counting note: `SHIPPED` / `MISSING` count file deliverables, named test functions, command results, and no-extra scope checks. `SCOPE_CREEP` counts each extra direct tracked file found in touched directories beyond the slot-local `Files:` list.
