"""GENERATED DO NOT EDIT.

Schema sha256s:
  - audit_event.schema.json: 12bd79954482d7d088e55716b6f8a86e195399d3245aff9f8933811bb8b52724
  - commentary.schema.json: bbfc250dfe8c99964781c8358a6d62a6850cbbc67e9ab6c470bdcba057e762d5
  - decision-event-v1.schema.json: a7667b06660a60583c5c4571bcb905e7dd4e6bf02c9c66f58da89fee9d85a76d
  - loss_receipt.schema.json: f356e22b644ca524fa073f7f6950fa2d50b92d1a9d387a0e0c17e3cb4a11f4a2
  - loss_receipt_v2.schema.json: 51eb20530d954819fcb74d22d75b88e6213866163a63fd10ef10949a0f69fcdd
  - matrix-events-v1.schema.json: f7762cecee3fe763448e8067b8933b6776a222bafa3b51e8efbd0c099ba2af45
  - modernised_record.schema.json: eb0103e76a835eb5e6f1eceb91684e32d06fd8f917501a75ce903c8e64a54555
  - reconciled_record.schema.json: a25d6f301789c6ec63ecd549d0395c8964482a9229ff45b2d0f4ad04d6170a33
  - reference_entry.schema.json: 0a61d1ef12f84020415657036f34669cfac355d55935410bbb744c9d438205e2
  - rendering_catalog.schema.json: 07b8b9989306cf6b4dcec2aee1f53bc6a9da267e19d6dc89d77cfbcf55a6f0d2
  - review_patch.schema.json: fca36a04261f3ad12f3093c56225aa398c509dbbfc4fd4564c09496a548f6ca3
  - review_state.schema.json: f1b4e706419623d17df42377092c2eb8ab297d90fe27e1d7889c233566ee55c8
  - sermon.schema.json: eb2428efa29088027696a3d1f90524bf349e589ab77d68999423556f6f964a05
"""

from __future__ import annotations

AUDIT_EVENT__CONFIDENCE_AXIS = frozenset(['edition_provenance', 'structural_fidelity', 'text_fidelity'])
AUDIT_EVENT__CONFIDENCE_TIER = frozenset(['human-reviewed', 'machine-checked', 'reference-grade', 'unverified', 'witness-compared'])
AUDIT_EVENT__EVENT_TYPE = frozenset(['acknowledge', 'bulk_acknowledged', 'bulk_dismissed', 'correction_applied', 'dead_letter_gc', 'dead_letter_replayed', 'dismiss', 'set_confidence_axis', 'sidecar_schema_migrated', 'stale_lock_broken'])
COMMENTARY__DATA__SUMMARY_REVIEW_STATUS = frozenset(['ai-generated-seminary-reviewed', 'ai-generated-spot-checked', 'ai-generated-unreviewed', 'human-written', 'withheld'])
COMMENTARY__DEFS__COVERAGE_PARAMETER_PROVENANCE__SOURCE = frozenset(['config', 'generated_inventory', 'source_metadata'])
COMMENTARY__DEFS__TEXT_LAYER_ENTRY__SOURCE_RAW_ORIGIN = frozenset(['observed', 'reconstructed', 'unavailable'])
COMMENTARY__META__COMPLETENESS = frozenset(['full', 'in-progress', 'partial'])
COMMENTARY__META__COVERAGE__INTENT = frozenset(['exhaustive', 'selective', 'thematic'])
COMMENTARY__META__COVERAGE__STRATEGY = frozenset(['none', 'scriptural_canon'])
COMMENTARY__META__LICENSE = frozenset(['cc-by-4.0', 'cc-by-sa-4.0', 'cc0-1.0', 'public-domain'])
COMMENTARY__META__PROVENANCE__PROCESSING_METHOD = frozenset(['automated', 'automated-with-review', 'manual', 'ocr', 'ocr-with-review'])
COMMENTARY__META__SCAN_STORAGE = frozenset(['external_url', 'git_lfs'])
COMMENTARY__META__TEXT_LAYER_SHAPE = frozenset(['single_field'])
COMMENTARY__META__TRADITION = frozenset(['adventist', 'anabaptist', 'anglican', 'arminian', 'baptist', 'brethren', 'calvinist', 'calvinist-methodist', 'catholic', 'confessional', 'congregationalist', 'continental-reformed', 'dutch-reformed', 'ecumenical', 'evangelical', 'free-church', 'fundamentalist', 'holiness', 'jansenist', 'lutheran', 'mennonite', 'methodist', 'monastic', 'moravian', 'non-denominational', 'nonconformist', 'orthodox', 'particular-baptist', 'patristic', 'pietist', 'presbyterian', 'puritan', 'quaker', 'reformed', 'revivalist', 'salvation-army', 'scholastic', 'wesleyan'])
COVERAGE_STRATEGIES = frozenset(['scriptural_canon', 'entry_inventory', 'none'])
DECISION_EVENT_V1__DEFS__DECISION_TOKEN = frozenset(['amend', 'cold_review', 'override', 'ratification'])
DECISION_EVENT_V1__DEFS__MATCH_METHOD = frozenset(['ambiguous_target', 'anchor_high_confidence', 'anchor_partial', 'cold_start_fingerprint_unique', 'fingerprint_collision', 'no_match', 'reviewer_manual'])
DECISION_EVENT_V1__DEFS__ORPHAN_REASON = frozenset(['ambiguous_rebind', 'article_reassigned', 'fingerprint_not_unique', 'invalid_seed', 'no_anchor_match'])
DECISION_EVENT_V1__DEFS__REBIND_REASON = frozenset(['anchor_overlap', 'cold_start_fingerprint_unique', 'reviewer_explicit'])
DECISION_EVENT_V1__DEFS__STATUS_AUTHORITY = frozenset(['consensus', 'llm_resolved', 'reviewed', 'unresolved'])
DECISION_EVENT_V1__DEFS__STRUCTURE_RESOLUTION_KIND = frozenset(['block_type_repair', 'other', 'page_repair', 'reading_order_repair'])
DECISION_EVENT_V1__EVENT_CATEGORY = frozenset(['authority_decision', 'workflow_event'])
DECISION_EVENT_V1__EVENT_TYPE = frozenset(['amend_text', 'auto_rebind_system', 'choose_attestation', 'confirm_unresolved', 'machine_release', 'mark_gold', 'orphan_decision', 'rebind_target', 'reject_machine_flag', 'resolve_structure', 'reviewer_recheck_requested', 'supersede_decision', 'typography_tier_correction', 'withdraw_gold'])
LOSS_RECEIPT_V2__DEFS__NODE__DISPOSITION = frozenset(['delivered', 'dropped', 'empty', 'normalized', 'structural'])
LOSS_RECEIPT_V2__DEFS__NODE__REASON_CODE = frozenset(['drop.ancestor.div-type', 'drop.ancestor.note', 'drop.ancestor.pb', 'drop.div.type', 'drop.element.note', 'drop.element.pb', 'empty.text-bearing', 'normalize.inline.markup-removed', 'normalize.ref.annotation-removed', 'structural.back', 'structural.body', 'structural.cell', 'structural.div', 'structural.front', 'structural.item', 'structural.lb', 'structural.list', 'structural.row', 'structural.table', 'structural.text'])
LOSS_RECEIPT_V2__DEFS__TARGET__FIELD = frozenset(['argument', 'speeches', 'text', 'title_path'])
LOSS_RECEIPT_V2__DEFS__TARGET__ITEM_FIELD = frozenset(['speaker', 'text'])
LOSS_RECEIPT__DEFS__NODE__DISPOSITION = frozenset(['dropped', 'normalized', 'projected'])
MATRIX_EVENTS_V1__DEFS__LABEL__BINARY_OUTCOME = frozenset(['correct', 'incorrect'])
MATRIX_EVENTS_V1__DEFS__OUTCOME = frozenset(['ineligible_event_type', 'labels_emitted', 'not_measurement_eligible', 'page_repaired', 'queued_region_class_pending', 'region_reassigned', 'skipped_low_order_no_override', 'skipped_page_coverage_ineligible', 'supersedes', 'vote_excluded_reversed'])
MATRIX_EVENTS_V1__DEFS__REGION_CLASS = frozenset(['bibliography_entry', 'bibliography_section_marker', 'body', 'caption', 'cross_reference', 'footnote', 'foreign_language_german', 'foreign_language_greek', 'foreign_language_hebrew', 'foreign_language_latin', 'heading_subsection', 'headword', 'list_item', 'quotation', 'section_heading', 'table_cell', 'unknown'])
MATRIX_EVENTS_V1__DEFS__WEAK_REASON = frozenset(['dictionary_pass_only', 'insufficient_family_diversity', 'llm_agreement_only', 'llm_resolved_event', 'no_family_map_readiness', 'no_independent_check'])
MODERNISED_RECORD__DEFS__BLOCK__BLOCK_TYPE = frozenset(['footnote', 'heading', 'headword', 'lemma', 'list_item', 'paragraph', 'quote', 'table_row', 'verse_line'])
MODERNISED_RECORD__DEFS__MATCH_EXPLANATION__SCOPE = frozenset(['block_pair_edge', 'disagreement', 'structural_disagreement'])
MODERNISED_RECORD__DEFS__MODERNISATION__KIND = frozenset(['editorial'])
MODERNISED_RECORD__DEFS__STRUCTURAL_DISAGREEMENT__KIND = frozenset(['annotation_chunking_disagreement', 'block_missing_in_source', 'block_split_in_source', 'block_type_conflict_in_source', 'heading_extra_in_source', 'heading_missing_in_source', 'neighbour_merged_in_source', 'unclassified'])
MODERNISED_RECORD__META__LICENSE = frozenset(['all-rights-reserved', 'cc-by', 'cc-by-4.0', 'cc-by-nc', 'cc-by-nc-nd', 'cc-by-nc-sa', 'cc-by-nd', 'cc-by-sa', 'cc-by-sa-4.0', 'cc0-1.0', 'public-domain', 'restricted'])
MODERNISED_RECORD__META__TRADITION = frozenset(['adventist', 'anabaptist', 'anglican', 'arminian', 'baptist', 'brethren', 'calvinist', 'calvinist-methodist', 'catholic', 'confessional', 'congregationalist', 'continental-reformed', 'dutch-reformed', 'ecumenical', 'evangelical', 'free-church', 'fundamentalist', 'holiness', 'jansenist', 'lutheran', 'mennonite', 'methodist', 'monastic', 'moravian', 'non-denominational', 'nonconformist', 'orthodox', 'particular-baptist', 'patristic', 'pietist', 'presbyterian', 'puritan', 'quaker', 'reformed', 'revivalist', 'salvation-army', 'scholastic', 'wesleyan'])
RECONCILED_RECORD__DEFS__BLOCK__BLOCK_TYPE = frozenset(['footnote', 'heading', 'headword', 'lemma', 'list_item', 'paragraph', 'quote', 'table_row', 'verse_line'])
RECONCILED_RECORD__DEFS__CANONICAL_POSITION__CANONICAL_DERIVATION_LEVEL = frozenset(['L0', 'L1', 'L2', 'L3'])
RECONCILED_RECORD__DEFS__CANONICAL_POSITION__CANONICAL_ORIGIN_KIND = frozenset(['human_amended', 'machine_composed', 'observed'])
RECONCILED_RECORD__DEFS__CHARACTER_PROVENANCE_ENTRY__SOURCE_TYPE = frozenset(['confusion_rule', 'engine_family', 'human', 'language_model', 'lexicon'])
RECONCILED_RECORD__DEFS__MATCH_EXPLANATION__SCOPE = frozenset(['block_pair_edge', 'disagreement', 'structural_disagreement'])
RECONCILED_RECORD__DEFS__MODERNISATION__KIND = frozenset(['editorial'])
RECONCILED_RECORD__DEFS__RECORD_META__LICENSE = frozenset(['all-rights-reserved', 'cc-by', 'cc-by-4.0', 'cc-by-nc', 'cc-by-nc-nd', 'cc-by-nc-sa', 'cc-by-nd', 'cc-by-sa', 'cc-by-sa-4.0', 'cc0-1.0', 'public-domain', 'restricted'])
RECONCILED_RECORD__DEFS__RECORD_META__TRADITION = frozenset(['adventist', 'anabaptist', 'anglican', 'arminian', 'baptist', 'brethren', 'calvinist', 'calvinist-methodist', 'catholic', 'confessional', 'congregationalist', 'continental-reformed', 'dutch-reformed', 'ecumenical', 'evangelical', 'free-church', 'fundamentalist', 'holiness', 'jansenist', 'lutheran', 'mennonite', 'methodist', 'monastic', 'moravian', 'non-denominational', 'nonconformist', 'orthodox', 'particular-baptist', 'patristic', 'pietist', 'presbyterian', 'puritan', 'quaker', 'reformed', 'revivalist', 'salvation-army', 'scholastic', 'wesleyan'])
RECONCILED_RECORD__DEFS__STRUCTURAL_DISAGREEMENT__KIND = frozenset(['annotation_chunking_disagreement', 'block_missing_in_source', 'block_split_in_source', 'block_type_conflict_in_source', 'heading_extra_in_source', 'heading_missing_in_source', 'neighbour_merged_in_source', 'unclassified'])
REFERENCE_ENTRY__DEFS__COVERAGE_PARAMETER_PROVENANCE__SOURCE = frozenset(['config', 'generated_inventory', 'source_metadata'])
REFERENCE_ENTRY__DEFS__TEXT_LAYER_ENTRY__SOURCE_RAW_ORIGIN = frozenset(['observed', 'reconstructed', 'unavailable'])
REFERENCE_ENTRY__META__COMPLETENESS = frozenset(['full', 'in-progress', 'partial'])
REFERENCE_ENTRY__META__COVERAGE__INTENT = frozenset(['exhaustive', 'selective', 'thematic'])
REFERENCE_ENTRY__META__COVERAGE__STRATEGY = frozenset(['entry_inventory', 'none'])
REFERENCE_ENTRY__META__LICENSE = frozenset(['cc-by-4.0', 'cc-by-sa-4.0', 'cc0-1.0', 'public-domain'])
REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD = frozenset(['automated', 'automated-with-review', 'manual', 'ocr', 'ocr-with-review'])
REFERENCE_ENTRY__META__SCAN_STORAGE = frozenset(['external_url', 'git_lfs'])
REFERENCE_ENTRY__META__TEXT_LAYER_SHAPE = frozenset(['multi_field'])
REFERENCE_ENTRY__META__TRADITION = frozenset(['adventist', 'anabaptist', 'anglican', 'arminian', 'baptist', 'brethren', 'calvinist', 'calvinist-methodist', 'catholic', 'confessional', 'congregationalist', 'continental-reformed', 'dutch-reformed', 'ecumenical', 'evangelical', 'free-church', 'fundamentalist', 'holiness', 'jansenist', 'lutheran', 'mennonite', 'methodist', 'monastic', 'moravian', 'non-denominational', 'nonconformist', 'orthodox', 'particular-baptist', 'patristic', 'pietist', 'presbyterian', 'puritan', 'quaker', 'reformed', 'revivalist', 'salvation-army', 'scholastic', 'wesleyan'])
RENDERING_CATALOG__DEFS__COPYRIGHTED_RENDERING__FORMAT = frozenset(['epub', 'html', 'ocr', 'pdf', 'plain', 'tei', 'thml'])
RENDERING_CATALOG__DEFS__PD_RENDERING__FORMAT = frozenset(['epub', 'html', 'ocr', 'pdf', 'plain', 'tei', 'thml'])
RENDERING_CATALOG__DEFS__PD_RENDERING__ROLE = frozenset(['pd_anchor', 'pd_attestor', 'pending', 'reference_only'])
RENDERING_CATALOG__MODERNISATION_INTENT = frozenset(['intended', 'not_applicable'])
RENDERING_CATALOG__RENDERINGS__ROLE = frozenset(['pd_anchor', 'pd_attestor', 'pending', 'reference_only'])
RESOURCE_TYPES = frozenset(['commentary', 'encyclopedia', 'sermon'])
REVIEW_PATCH__DECISIONS__DECISION_KIND = frozenset(['adjudication', 'catalog_role_change', 'modernisation_approval', 'structural_resolution'])
REVIEW_STATE__DEFS__CONFIDENCE_TIER = frozenset(['human-reviewed', 'machine-checked', 'reference-grade', 'unverified', 'witness-compared'])
REVIEW_STATE__DEFS__DEAD_LETTER_ENTRY__REASON = frozenset(['correction_orphaned_by_parser', 'evidence_schema_failed', 'producer_budget_exhausted', 'producer_dedupe_evidence_mismatch', 'producer_output_schema_failed', 'producer_signature_field_missing', 'producer_unknown', 'renderer_unknown_evidence_shape', 'sidecar_schema_too_old'])
REVIEW_STATE__DEFS__WARNING_DECISION__REASON = frozenset(['confirmed', 'expected', 'false_positive', 'other', 'wont_fix'])
SERMON__META__AUDIENCE = frozenset(['children', 'lay', 'pastoral', 'scholarly'])
SERMON__META__COMPLETENESS = frozenset(['full', 'in-progress', 'partial'])
SERMON__META__ERA = frozenset(['apostolic', 'medieval', 'modern', 'patristic', 'post-reformation', 'reformation'])
SERMON__META__LICENSE = frozenset(['cc-by-4.0', 'cc-by-sa-4.0', 'cc0-1.0', 'public-domain'])
SERMON__META__PROVENANCE__PROCESSING_METHOD = frozenset(['automated', 'automated-with-review', 'manual', 'ocr', 'ocr-with-review'])
SERMON__META__TRADITION = frozenset(['adventist', 'anabaptist', 'anglican', 'arminian', 'baptist', 'brethren', 'calvinist', 'calvinist-methodist', 'catholic', 'confessional', 'congregationalist', 'continental-reformed', 'dutch-reformed', 'ecumenical', 'evangelical', 'free-church', 'fundamentalist', 'holiness', 'jansenist', 'lutheran', 'mennonite', 'methodist', 'monastic', 'moravian', 'non-denominational', 'nonconformist', 'orthodox', 'particular-baptist', 'patristic', 'pietist', 'presbyterian', 'puritan', 'quaker', 'reformed', 'revivalist', 'salvation-army', 'scholastic', 'wesleyan'])
TEXT_LAYER_SHAPES = frozenset(['single_field', 'multi_field'])
