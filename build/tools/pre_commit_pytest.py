"""Select focused pytest evidence for staged build/kernel/CVW Python and changed tests.

Naming and direct static test imports select tests without executing imports or
walking transitive dependencies. Unmapped production changes fail explicitly.
Use --list [paths ...] to inspect a selection without running it. Selections over
50 files require OCD_PRECOMMIT_RUN_LARGE_SELECTION=1; this runs every selected test.
"""
import argparse
import ast
from contextlib import ExitStack
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_TESTS_WARN = 50
PUBLIC_INPUT_INVENTORY = "tests/fixtures/public-local-input-cases.json"
MIN_PARALLEL_TEST_BYTES = 100_000
MIN_PARALLEL_TEST_FILES = 3
MAX_PARALLEL_WORKERS = 8
DEFAULT_PARALLEL_WORKERS = 4
WORKER_LIMIT_ENV = "OCD_PRECOMMIT_WORKERS"
ADDITIONAL_SELECTION_ENV = "OCD_PRECOMMIT_ADDITIONAL_SELECTION"
# Check pinned historical inputs before expensive full-book reconstructions.
AUTHORITY_TEST_FILE_PRIORITY = (
    "tests/test_reconstruction_closure_corpus.py",
    "tests/test_four_source_accounting_sidecars.py",
    "tests/test_library_config_free_multi_binding.py",
    "tests/test_library_exclusive_manifest_binding.py",
    "tests/test_library_lib028_binding.py",
    "tests/test_library_manifest_exception_binding.py",
    "tests/test_standard_ebooks_spine_corrections.py",
    "tests/test_whitefield_two_witness_sidecars.py",
    "tests/test_gregory_select_letters_npnf207_acceptance_stage.py",
)
# Start measured corpus bottlenecks while other workers still have useful work.
SLOW_TEST_FILE_PRIORITY = (
    "tests/test_spurgeon_mtp_reconstruction_contract.py",
    "tests/test_john_owen_lib050_reconstruction_contract.py",
    "tests/test_maclaren_native.py",
    "tests/test_augustine_psalms_native.py",
)


def _worker_limit() -> int:
    configured = os.environ.get(WORKER_LIMIT_ENV)
    if configured is None:
        return DEFAULT_PARALLEL_WORKERS
    try:
        value = int(configured)
    except ValueError as exc:
        raise ValueError(f"{WORKER_LIMIT_ENV} must be an integer from 1 to 8") from exc
    if not 1 <= value <= MAX_PARALLEL_WORKERS:
        raise ValueError(f"{WORKER_LIMIT_ENV} must be an integer from 1 to 8")
    return value


def _xdist_available():
    """Return whether this interpreter can parallelize pytest workers."""
    try:
        import xdist  # noqa: F401
    except ImportError:
        return False
    return True


def _pytest_command(test_files, *, basetemp, xdist_available=None):
    """Build the bounded pytest command used by the commit hook."""
    if xdist_available is None:
        xdist_available = _xdist_available()

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        "--basetemp",
        basetemp,
    ]
    test_files_on_disk = {path.split("::", 1)[0] for path in test_files}
    try:
        total_test_bytes = sum(
            os.path.getsize(os.path.join(REPO_ROOT, path))
            for path in test_files_on_disk
        )
    except OSError:
        # Selection normally supplies existing files; direct command-building
        # probes can use hypothetical paths and safely remain serial.
        total_test_bytes = 0
    worker_count = min(_worker_limit(), len(test_files_on_disk), os.cpu_count() or 1)
    if (
        xdist_available
        and worker_count > 1
        and (
            total_test_bytes >= MIN_PARALLEL_TEST_BYTES
            or len(test_files_on_disk) >= MIN_PARALLEL_TEST_FILES
        )
    ):
        # Keep each test file on one worker. The mapped files often contain
        # process-wide corpus fixtures, while file-level parallelism removes
        # the commit hook's serial 40+ minute path without changing coverage.
        cmd.extend(["-n", str(worker_count), "--dist", "loadfile"])
        # Every exact node ID and file work unit is preserved. Stable sorting
        # keeps all unprioritized targets in their original relative order.
        priority = {path: index for index, path in enumerate(AUTHORITY_TEST_FILE_PRIORITY + SLOW_TEST_FILE_PRIORITY)}
        if any(path in priority for path in test_files_on_disk):
            test_files = sorted(
                test_files,
                key=lambda target: priority.get(target.split("::", 1)[0], len(priority)),
            )
            cmd.append("--no-loadscope-reorder")
    if len(test_files_on_disk) > MAX_TESTS_WARN:
        cmd[cmd.index("-q")] = "-v"
        cmd.append("--durations=20")
    cmd.extend(test_files)
    return cmd


# Nonmatching executable contracts; naming/direct imports cover ordinary modules.
ROUTE_CONTRACT_TEST = (
    "tests/test_source_manifest_route_validation.py::"
    "test_source_manifest_route_reconstructs_and_validates"
)

LIB048_CONTRACT_TESTS = (
    "tests/test_npnf2_lib048_reconstruction.py::test_exact_four_member_authority_and_fifteen_bindings",
    "tests/test_npnf2_lib048_reconstruction.py::test_retained_gregory_image_projection_and_binding",
    "tests/test_npnf2_lib048_reconstruction.py::test_rebound_image_authority_must_match_source_work_and_path[work-scope]",
    "tests/test_npnf2_lib048_reconstruction.py::test_rebound_image_authority_must_match_source_work_and_path[logical-path]",
)

COUNT_DATASET_ROUTE_TESTS = (
    "tests/test_count_dataset_records.py::test_source_manifest_allowlist_binds_only_target_work_without_unselected_reads",
    "tests/test_count_dataset_records.py::test_source_manifest_allowlist_rejects_invalid_paths_before_data_scan",
    "tests/test_count_dataset_records.py::test_source_manifest_allowlist_rejects_absolute_and_duplicate_paths",
    "tests/test_count_dataset_records.py::test_data_resource_allowlist_rejects_invalid_paths_before_data_scan",
    "tests/test_count_dataset_records.py::test_bounded_route_allowlists_must_be_supplied_together",
    "tests/test_count_dataset_records.py::test_historical_catalog_cli_forwards_repeatable_route_allowlists",
    "tests/test_count_dataset_records.py::test_source_hash_binds_a_partial_reconstruction_route_to_the_exact_work",
    "tests/test_count_dataset_records.py::test_catalog_flags_only_retained_config_members_missing_from_parser_provenance",
    "tests/test_count_dataset_records.py::test_catalog_reads_configured_external_raw_without_repository_junction",
)

CALVIN_MEMBER_PROJECTION_TESTS = (
    "tests/test_calvin_commentaries_member.py::test_calvin_selected_members_preserve_source_features_and_text",
)


@dataclass(frozen=True)
class ComponentTestPolicy:
    """Explicit precedence: add coverage, narrow a route, then replace all matches."""

    add: tuple[str, ...] = ()
    route: str | None = None
    replace: tuple[str, ...] | None = None


# One policy per source owns all overrides. Changed tests always run in full;
# their replacement targets also select any declared consumer coverage.
COMPONENT_TEST_POLICIES = {
    "cvw_app/hymn_tei.py": ComponentTestPolicy(add=("cvw_app/tests/test_additional_formats.py",)),
    "cvw_app/structured_text.py": ComponentTestPolicy(add=("cvw_app/tests/test_additional_formats.py",)),
    "cvw_app/toml_books.py": ComponentTestPolicy(add=("cvw_app/tests/test_additional_formats.py",)),
    "cvw_app/usfm_books.py": ComponentTestPolicy(add=("cvw_app/tests/test_additional_formats.py",)),
    # Public renderer tests exercise these extracted modules via compatibility
    # exports; static direct-import discovery cannot follow that boundary.
    "cvw_app/renderer_nodes.py": ComponentTestPolicy(
        add=(
            "cvw_app/tests/test_engineering_review.py",
            "cvw_app/tests/test_review_core.py",
        ),
    ),
    "cvw_app/tei_inline.py": ComponentTestPolicy(
        add=(
            "cvw_app/tests/test_engineering_review.py",
            "cvw_app/tests/test_tei_literary_rendering.py",
        ),
    ),
    "cvw_app/tei_renderer.py": ComponentTestPolicy(
        add=(
            "cvw_app/tests/test_engineering_review.py",
            "cvw_app/tests/test_tei_literary_rendering.py",
            "cvw_app/tests/test_hymnary_rendering.py",
        ),
    ),
    # Findlay's independent checker is exercised through the LIB-033 oracle.
    "build/tei/expositors_bible_findlay_validation.py": ComponentTestPolicy(
        add=(
            "tests/test_expositors_bible_lib033_reconstruction_contract.py",
        ),
    ),
    # These manifest-loaded modules are covered by the corpus closure checks.
    "build/tei/npnf211_lib049_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_reconstruction_closure_corpus.py",
        ),
    ),
    "build/tei/npnf211_lib049_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_reconstruction_closure_corpus.py",
        ),
    ),
    # Loaded from the manifest-bound temporary repository in the selected-ThML route test.
    "build/tei/selected_thml_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_selected_thml_lifecycle.py",
        ),
    ),
    # These selected-source modules are loaded dynamically by the route test.
    "build/tei/gutenberg_evangelical_lib071_selected_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_gutenberg_proofread_selected_sources.py",
        ),
    ),
    "build/tei/gutenberg_evangelical_lib072_selected_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_gutenberg_proofread_selected_sources.py",
        ),
    ),
    "build/tei/gutenberg_proofread_selected_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_gutenberg_proofread_selected_sources.py",
        ),
    ),
    # Loaded through importlib in the focused test rather than a static import.
    "build/tools/report_library_metadata.py": ComponentTestPolicy(
        add=("tests/test_library_metadata_report.py",),
    ),
    # These tests load the modules dynamically to contain import-time effects.
    "build/tools/audit_ref_coverage.py": ComponentTestPolicy(
        add=("tests/test_coherence_tool_contracts.py",),
    ),
    "cvw_app/tests/fixtures/make_binary_contract_fixtures.py": ComponentTestPolicy(
        add=(
            "tests/test_coherence_tool_contracts.py",
        ),
    ),
    "ocd_kernel/lib/_generated_enums.py": ComponentTestPolicy(
        add=("tests/test_generated_enums.py",),
    ),
    "ocd_kernel/tools/generate_schema_enums.py": ComponentTestPolicy(
        add=("tests/test_generated_enums.py",),
    ),
    "ocd_kernel/tools/check_schema_enums_fresh.py": ComponentTestPolicy(
        add=("tests/test_generated_enums.py",),
    ),
    "ocd_kernel/tools/__init__.py": ComponentTestPolicy(
        add=("tests/test_generated_enums.py",),
    ),
    "build/lib/coverage_strategies/none.py": ComponentTestPolicy(
        add=("tests/test_coverage_strategies.py",),
    ),
    "build/lib/coverage_strategies/entry_inventory.py": ComponentTestPolicy(
        add=("tests/test_coverage_strategies.py",),
    ),
    "build/lib/coverage_strategies/scriptural_canon.py": ComponentTestPolicy(
        add=("tests/test_coverage_strategies.py",),
    ),
    # These ticket-local routes load their producer and oracle from the
    # manifest, so the focused ticket tests are selected explicitly.
    "build/tei/augustines_confessions_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_062_augustines_confessions_reconstruction_contract.py",
        ),
    ),
    "build/tei/augustines_confessions_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_062_augustines_confessions_reconstruction_contract.py",
        ),
    ),
    "build/tei/barnes_nt_notes_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_066_barnes_nt_notes_reconstruction_contract.py",
        ),
    ),
    "build/tei/barnes_nt_notes_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_066_barnes_nt_notes_reconstruction_contract.py",
        ),
    ),
    "build/tei/ccel_puritan_lib055_edwards_religious_affections_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_142_edwards_religious_affections.py",
        ),
    ),
    "build/tei/ccel_puritan_lib055_edwards_religious_affections_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_142_edwards_religious_affections.py",
        ),
    ),
    "build/tei/ccel_puritan_lib055_flavel_method_of_grace_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_174_flavel_method_of_grace.py",
        ),
    ),
    "build/tei/ccel_puritan_lib055_flavel_method_of_grace_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_174_flavel_method_of_grace.py",
        ),
    ),
    "build/tei/kjva_oracle.py": ComponentTestPolicy(
        add=("tests/test_37c_240_kjva_reconstruction.py",),
    ),
    "build/tei/kjva_reconstruction.py": ComponentTestPolicy(
        add=("tests/test_37c_240_kjva_reconstruction.py",),
    ),
    # The LIB-073 route is dynamically manifest-bound; the checkout audit
    # verifies its producer/oracle paths and declared hashes together.
    "build/tei/maclaren_expositions_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_source_manifest_checkout_materialization.py",
        ),
    ),
    "build/tei/maclaren_expositions_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_source_manifest_checkout_materialization.py",
        ),
    ),
    "build/tei/robertson_word_pictures_vol1_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_266_source_contract.py",
        ),
    ),
    "build/tei/robertson_word_pictures_vol1_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_266_source_contract.py",
        ),
    ),
    "build/tei/ryle_expository_thoughts_matthew_lib055_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_268_ryle_matthew_source_route.py",
        ),
    ),
    "build/tei/ryle_expository_thoughts_matthew_lib055_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_268_ryle_matthew_source_route.py",
        ),
    ),
    "build/tei/watson_divine_contentment_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_316_watson_divine_contentment.py",
        ),
    ),
    "build/tei/watson_divine_contentment_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_316_watson_divine_contentment.py",
        ),
    ),
    "build/tei/webster_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_319_webster_reconstruction.py",
        ),
    ),
    "build/tei/ylt_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_323_ylt_reconstruction.py",
        ),
    ),
    "build/tei/webster_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_319_webster_reconstruction.py",
        ),
    ),
    "build/tei/ylt_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_37c_323_ylt_reconstruction.py",
        ),
    ),
    "build/tei/bible_dictionaries_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_lib021_bible_dictionaries_reconstruction.py",
        ),
        replace=(
            "tests/test_bible_dictionary_route_contract.py::"
            "test_dictionary_route_reconstructs_and_validates[eastons-bible-dictionary]",
            "tests/test_bible_dictionary_route_contract.py::"
            "test_dictionary_route_reconstructs_and_validates[hitchcocks-bible-names-dictionary]",
            "tests/test_bible_dictionary_route_contract.py::"
            "test_dictionary_route_reconstructs_and_validates[smiths-bible-dictionary]",
        ),
    ),
    "build/tei/bible_dictionaries_oracle.py": ComponentTestPolicy(
        add=(
            "tests/test_lib021_bible_dictionaries_reconstruction.py",
        ),
    ),
    "build/tei/lib067_andrewes_private_devotions.py": ComponentTestPolicy(
        add=(
            "tests/test_lib067_andrewes_private_devotions_reconstruction.py",
        ),
    ),
    "build/tei/lib068_source_local.py": ComponentTestPolicy(
        add=(
            "tests/test_lib068_source_local_reconstruction.py",
        ),
        replace=(
            "tests/test_lib068_source_local_reconstruction.py::"
            "test_lib068_source_manifest_reconstructs_and_passes_independent_oracle",
        ),
    ),
    "ocd_kernel/reconstruction/closure_verification.py": ComponentTestPolicy(
        add=(
            "tests/test_reconstruction_closure_corpus.py",
        ),
    ),
    "build/tei/bcp_1549_oracle.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[bcp-1549]",
    ),
    "build/tei/bcp_1549_reconstruction.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[bcp-1549]",
    ),
    "build/tei/bcp_1559_oracle.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[bcp-1559]",
    ),
    "build/tei/bcp_1559_reconstruction.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[bcp-1559]",
    ),
    "build/tei/calvin_commentaries_oracle.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[calvin-commentaries]",
        replace=CALVIN_MEMBER_PROJECTION_TESTS,
    ),
    # The full 46-member candidate remains in the slow route suite; pre-commit
    # validates producer and oracle behavior on representative first/last members.
    "build/tei/calvin_commentaries_reconstruction.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[calvin-commentaries]",
        replace=CALVIN_MEMBER_PROJECTION_TESTS,
    ),
    "build/tei/kjv_oracle.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[kjv]",
    ),
    "build/tei/kjv_reconstruction.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[kjv]",
    ),
    "build/tei/lib062_shorter_catechism_oracle.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[lib-062]",
    ),
    "build/tei/lib062_shorter_catechism_reconstruction.py": ComponentTestPolicy(
        route=f"{ROUTE_CONTRACT_TEST}[lib-062]",
    ),
    # The generic CLI is called by these route tests. Spurgeon's other tests
    # exercise its oracle/catalog, including a whole-library scan, not this CLI.
    # Whole-file targets retain future unit cases without enumerating functions.
    "build/tools/reconstruct_candidate.py": ComponentTestPolicy(
        replace=(
            "tests/test_reconstruct_candidate.py",
            "tests/test_law_serious_call_reconstruction.py",
            "tests/test_spurgeon_mtp_reconstruction_contract.py::test_complete_authority_bound_route",
        ),
    ),
    "build/tei/lib068_source_local_oracle.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_source_local_reconstruction.py::"
            "test_lib068_source_manifest_reconstructs_and_passes_independent_oracle",
        ),
    ),
    "build/tei/lib068_literary_blocks.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_literary_blocks.py::"
            "test_newman_tables_have_actual_source_columns_and_no_fake_cells",
        ),
    ),
    "build/tei/lib068_literary_blocks_oracle.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_literary_blocks_oracle.py::"
            "test_actual_special_tree_normalizes_to_source_floor",
        ),
    ),
    "build/tei/lib068_source_letters.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_source_letters.py::"
            "test_letter_normalization_is_nonmutating_and_preserves_actual_carriers",
        ),
    ),
    "build/tei/lib068_source_letters_oracle.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_source_letters.py::"
            "test_letter_normalization_is_nonmutating_and_preserves_actual_carriers",
        ),
    ),
    "tests/test_lib068_source_local_reconstruction.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_source_local_reconstruction.py::"
            "test_lib068_source_manifest_reconstructs_and_passes_independent_oracle",
        ),
    ),
    "tests/test_lib068_literary_blocks.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_literary_blocks.py::test_inventory_receipt_is_pinned_to_retained_source",
            "tests/test_lib068_literary_blocks.py::"
            "test_newman_tables_have_actual_source_columns_and_no_fake_cells",
        ),
    ),
    "tests/test_lib068_literary_blocks_oracle.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_literary_blocks_oracle.py::"
            "test_actual_special_tree_normalizes_to_source_floor",
            "tests/test_lib068_literary_blocks_oracle.py::"
            "test_mixed_inline_children_survive_fragment_merge",
        ),
    ),
    "tests/test_lib068_literary_determinism.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_literary_determinism.py::"
            "test_literary_blocks_are_byte_deterministic_across_work_orders",
        ),
    ),
    "tests/test_lib068_source_letters.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_source_letters.py::"
            "test_letter_normalization_is_nonmutating_and_preserves_actual_carriers",
            "tests/test_lib068_source_letters.py::"
            "test_profile_cannot_reclassify_a_prayer_as_a_salutation",
        ),
    ),
    "tests/test_lib068_source_letters_reconstruction.py": ComponentTestPolicy(
        replace=(
            "tests/test_lib068_source_letters_reconstruction.py::"
            "test_real_candidate_validates_and_reproduces",
        ),
    ),
    # The work producer is loaded through its SourceManifest by the real CLI baseline.
    "build/tei/npnf104_work_reconstruction.py": ComponentTestPolicy(
        add=("tests/test_npnf104_work_candidates.py",),
    ),
    "build/tei/npnf104_lib038_reconstruction.py": ComponentTestPolicy(
        replace=(
            "tests/test_npnf104_lib038_reconstruction_contract.py::"
            "test_candidate_passes_independent_oracle_and_preserves_assigned_scope",
        ),
    ),
    "build/tei/npnf104_lib038_oracle.py": ComponentTestPolicy(
        replace=(
            "tests/test_npnf104_lib038_reconstruction_contract.py::"
            "test_candidate_passes_independent_oracle_and_preserves_assigned_scope",
        ),
    ),
    "tests/test_npnf104_lib038_reconstruction_contract.py": ComponentTestPolicy(
        replace=(
            "tests/test_npnf104_lib038_reconstruction_contract.py::"
            "test_candidate_passes_independent_oracle_and_preserves_assigned_scope",
        ),
    ),
    "build/tei/npnf2_lib046_gregory_select_letters_reconstruction.py": ComponentTestPolicy(
        replace=(
            "tests/test_npnf2_lib046_gregory_select_letters_reconstruction.py::"
            "test_candidate_is_p5_valid_and_independently_verified",
        ),
    ),
    "build/tei/npnf2_lib046_gregory_select_letters_oracle.py": ComponentTestPolicy(
        replace=(
            "tests/test_npnf2_lib046_gregory_select_letters_reconstruction.py::"
            "test_candidate_is_p5_valid_and_independently_verified",
        ),
    ),
    "tests/test_npnf2_lib046_gregory_select_letters_reconstruction.py": ComponentTestPolicy(
        replace=(
            "tests/test_npnf2_lib046_gregory_select_letters_reconstruction.py::"
            "test_candidate_is_p5_valid_and_independently_verified",
        ),
    ),
    "build/tei/ryle_holiness_reconstruction.py": ComponentTestPolicy(
        replace=(
            "tests/test_ryle_holiness_reconstruction_contract.py::"
            "test_candidate_passes_independent_accounting_and_tei_schema",
        ),
    ),
    "build/tei/ryle_holiness_oracle.py": ComponentTestPolicy(
        replace=(
            "tests/test_ryle_holiness_reconstruction_contract.py::"
            "test_candidate_passes_independent_accounting_and_tei_schema",
        ),
    ),
    "tests/test_ryle_holiness_reconstruction_contract.py": ComponentTestPolicy(
        replace=(
            "tests/test_ryle_holiness_reconstruction_contract.py::"
            "test_candidate_passes_independent_accounting_and_tei_schema",
        ),
    ),
    "tests/test_source_manifest_route_validation.py": ComponentTestPolicy(
        replace=CALVIN_MEMBER_PROJECTION_TESTS,
    ),
    "tests/test_calvin_commentaries_member.py": ComponentTestPolicy(
        replace=CALVIN_MEMBER_PROJECTION_TESTS,
    ),
    # Keep LIB-048's large slow mutation suite out of each producer commit.
    "build/tei/npnf2_lib048_reconstruction.py": ComponentTestPolicy(
        replace=LIB048_CONTRACT_TESTS,
    ),
    "build/tei/npnf2_lib048_oracle.py": ComponentTestPolicy(
        replace=LIB048_CONTRACT_TESTS,
    ),
    "tests/test_npnf2_lib048_reconstruction.py": ComponentTestPolicy(
        replace=LIB048_CONTRACT_TESTS,
    ),
    "build/tools/count_dataset_records.py": ComponentTestPolicy(
        replace=COUNT_DATASET_ROUTE_TESTS,
    ),
    "tests/test_count_dataset_records.py": ComponentTestPolicy(
        replace=COUNT_DATASET_ROUTE_TESTS,
    ),
    "tests/test_athanasius_table_reconstruction_contract.py": ComponentTestPolicy(
        replace=(
            "tests/test_athanasius_table_reconstruction_contract.py::"
            "test_candidate_is_complete_nonaccepted_source_bound_and_reviewable",
        ),
    ),
    "tests/test_npnf_ambrose_reconstruction.py": ComponentTestPolicy(
        replace=(
            "tests/test_npnf_ambrose_reconstruction.py::"
            "test_candidate_is_complete_nonaccepted_and_preserves_credit_uncertainty",
        ),
    ),
    # Real CLI and transitive fixture consumers cross direct-import discovery.
    "build/tei/npnf206_work_reconstruction.py": ComponentTestPolicy(
        add=(
            "tests/test_npnf206_work_candidates.py",
        ),
    ),
    "tests/npnf_install_runtime_fixture.py": ComponentTestPolicy(
        add=(
            "tests/test_npnf109_third_work_acceptance_install.py",
            "tests/test_npnf109_work_acceptance_install.py",
            "tests/test_npnf113_work_acceptance_install.py",
            "tests/test_npnf205_work_acceptance_stage.py",
            "tests/test_npnf104_work_acceptance_install.py",
            "tests/test_npnf109_final_work_acceptance_install.py",
            "tests/test_npnf109_next_work_acceptance_install.py",
            "tests/test_npnf109_olympias_corpus_acceptance_install.py",
            "tests/test_npnf109_rome_corpus_acceptance_install.py",
        ),
    ),
    "tests/vendored_schema_mirrors.py": ComponentTestPolicy(
        add=(
            "tests/test_vendored_schema_mirrors.py",
            "tests/test_historical_authority_mirrors.py",
            "tests/test_apostolic_tradition_reconstruction.py",
            "tests/test_gregory_select_letters_npnf207_acceptance_stage.py",
            "tests/test_moody_prevailing_prayer_61883_reconstruction.py",
            "tests/test_davis_l332_ia.py",
            "tests/test_methodius_first1kgreek.py",
            "tests/test_schleitheim_confession_acceptance.py",
            "tests/test_sum_saving_knowledge_acceptance.py",
            "tests/test_npnf207_two_work_ccel_acceptance_stage.py",
            "tests/test_augustines_pg3296_install.py",
            "tests/test_wikisource_l594_chrysostom_v2.py",
        ),
    ),
    "tests/gregory_select_runtime_install_fixture.py": ComponentTestPolicy(
        add=(
            "tests/test_gregory_select_runtime_manifest.py",
        ),
    ),
}


# These command entrypoints have operation-free help and invalid-argument tests.
CLI_CONTRACT_SOURCES = (
    'build/tei/bennett_retained_native_oracle.py',
    'build/tei/bennett_retained_native_prepare.py',
    'build/tei/blaikie_first_samuel_retained_native_oracle.py',
    'build/tei/blaikie_first_samuel_retained_native_prepare.py',
    'build/tei/blaikie_joshua_retained_native_oracle.py',
    'build/tei/blaikie_joshua_retained_native_prepare.py',
    'build/tei/blaikie_second_samuel_oracle.py',
    'build/tei/blaikie_second_samuel_prepare.py',
    'build/tei/boethius_complete_envelope.py',
    'build/tei/calvin_joshua_projection_draft.py',
    'build/tei/calvin_joshua_projection_draft_v2.py',
    'build/tei/calvin_joshua_projection_draft_v3.py',
    'build/tei/calvin_joshua_projection_draft_v4.py',
    'build/tei/calvin_joshua_projection_draft_v5.py',
    'build/tei/calvin_joshua_projection_draft_v6.py',
    'build/tei/calvin_joshua_projection_oracle.py',
    'build/tei/calvin_joshua_projection_oracle_v2.py',
    'build/tei/calvin_joshua_projection_oracle_v3.py',
    'build/tei/calvin_joshua_projection_oracle_v4.py',
    'build/tei/calvin_joshua_projection_oracle_v5.py',
    'build/tei/calvin_joshua_projection_oracle_v6.py',
    'build/tei/chadwick_retained_native_oracle.py',
    'build/tei/chadwick_retained_native_prepare.py',
    'build/tei/docsouth_green_v2_mutation_challenge.py',
    'build/tei/docsouth_green_v3_mutation_challenge.py',
    'build/tei/dods_complete_prepare.py',
    'build/tei/dods_retained_native_oracle.py',
    'build/tei/dods_retained_native_prepare.py',
    'build/tei/expositors_bible_lib034_readable_pair.py',
    'build/tei/expositors_bible_lib034_readable_pair_oracle.py',
    'build/tei/farrar_retained_native_oracle.py',
    'build/tei/farrar_retained_native_prepare.py',
    'build/tei/findlay_retained_prepare.py',
    'build/tei/l741_evangelische_gezangen_1806_reproduce.py',
    'build/tei/leeser_tanakh_1853_challenge.py',
    'build/tei/lib031_bounds_standalone.py',
    'build/tei/maclaren_expositions_package_v3.py',
    'build/tei/maclaren_retained_native_oracle.py',
    'build/tei/maclaren_retained_native_prepare.py',
    'build/tei/modern_scepticism_manifest_mutation_challenge.py',
    'build/tei/open_english_bible_2025_6_manifest.py',
    'build/tei/open_english_bible_2025_6_profile.py',
    'build/tei/plummer_retained_native_oracle.py',
    'build/tei/plummer_retained_native_prepare.py',
    'build/tei/revised_version_with_apocrypha_corpus.py',
    'build/tei/run_basil_hexaemeron.py',
    'build/tei/run_basil_holy_spirit.py',
    'build/tei/run_georgii_aliud.py',
    'build/tei/run_ludewic.py',
    'build/tei/run_manifest_pg_l640_noah_davis.py',
    'build/tei/run_nancy_prince_pg63579.py',
    'build/tei/run_walram.py',
    'build/tei/smith_retained_native_oracle.py',
    'build/tei/smith_retained_native_prepare.py',
    'build/tei/stokes_acts_complete_prepare.py',
    'build/tei/stokes_retained_completion.py',
    'build/tei/tcp_l879_stillingfleet_current.py',
    'build/tei/ursinus_heidelberg_1852_v2.py',
    'build/tei/ursinus_heidelberg_1852_v2_oracle.py',
    'build/tei/ursinus_heidelberg_1852_v3.py',
    'build/tei/ursinus_heidelberg_1852_v3_oracle.py',
    'build/tei/ursinus_heidelberg_1852_v4.py',
    'build/tei/ursinus_heidelberg_1852_v4_oracle.py',
    'build/tei/ursinus_heidelberg_1852_v5.py',
    'build/tei/ursinus_heidelberg_1852_v5_oracle.py',
    'build/tei/ursinus_heidelberg_1852_v6_oracle.py',
    'build/tei/watson_retained_native_oracle.py',
    'build/tei/watson_retained_native_prepare.py',
    'build/tei/whitefield_works_l646_v2_mutation_challenge.py',
    'build/tei/whitefield_works_l646_v2_replay_comparison.py',
    'build/tools/accept_ajops_retained.py',
    'build/tools/accept_coppens_pg70790.py',
    'build/tools/accept_davis_ocr_internal.py',
    'build/tools/accept_maclaren_expositions_v3.py',
    'build/tools/accept_openmgh_bsb754_rigoberti.py',
    'build/tools/accept_pg49917_holy_images.py',
    'build/tools/accept_pg77576_clement_second.py',
    'build/tools/accept_pg77576_ignatius_smyrnaeans.py',
    'build/tools/accept_pg77576_ignatius_virgin_mary.py',
    'build/tools/accept_robertson_keywords_internal.py',
    'build/tools/accept_ursinus_ocr_internal.py',
    'build/tools/accept_woolman_pg37311.py',
    'build/tools/acquire_docsouth_figure_pilot.py',
    'build/tools/audit_jwbickel_dictionary_candidates.py',
    'build/tools/audit_schaff_history_vol3_current.py',
    'build/tools/audit_schaff_history_vol4_current.py',
    'build/tools/audit_schaff_history_vol7_current.py',
    'build/tools/blaikie_joshua_title_install.py',
    'build/tools/capture_eusebius_l811_acceptance.py',
    'build/tools/capture_eusebius_l811_source.py',
    'build/tools/capture_l599_slave_trade_acceptance.py',
    'build/tools/capture_strong_vol2_current_acceptance.py',
    'build/tools/capture_tyerman_john_wesley_acceptance.py',
    'build/tools/capture_tyerman_samuel_acceptance.py',
    'build/tools/capture_tyerman_whitefield_acceptance.py',
    'build/tools/check_anderson_saved_projection.py',
    'build/tools/check_asv_saved_projection.py',
    'build/tools/check_basil_hexaemeron_mutations.py',
    'build/tools/check_basil_holy_spirit_mutations.py',
    'build/tools/check_bsb_saved_projection.py',
    'build/tools/check_eusebius_l811_native_proposal.py',
    'build/tools/check_expositors_lib033_harper_index_repair_fixture.py',
    'build/tools/check_expositors_lib034_denney_index_repair_fixture.py',
    'build/tools/check_expositors_lib034_lumby_index_repair_fixture.py',
    'build/tools/check_expositors_lib035_edwards_nested_index_repair_fixture.py',
    'build/tools/check_expositors_lib035_horton_index_repair_fixture.py',
    'build/tools/check_expositors_lib035_kellogg_index_repair_fixture.py',
    'build/tools/check_first_corinthians_collection_mutations.py',
    'build/tools/check_first_corinthians_collection_rollback.py',
    'build/tools/check_georgii_aliud_mutations.py',
    'build/tools/check_hilary_select_works_collection_mutations.py',
    'build/tools/check_hilary_select_works_collection_rollback.py',
    'build/tools/check_hodge_vol1_complete_mutations.py',
    'build/tools/check_hodge_vol2_complete.py',
    'build/tools/check_kjva_saved_projection.py',
    'build/tools/check_ludewic_mutations.py',
    'build/tools/check_matthew_collection_mutations.py',
    'build/tools/check_matthew_collection_rollback.py',
    'build/tools/check_modern_scepticism_current_mutations.py',
    'build/tools/check_nancy_prince_pg63579_mutations.py',
    'build/tools/check_newman_apologia_pg22088_stage.py',
    'build/tools/check_nyssa_letters_mutations.py',
    'build/tools/check_original_douay_companion_v2.py',
    'build/tools/check_original_douay_rollback.py',
    'build/tools/check_predestination_mutations.py',
    'build/tools/check_walram_mutations.py',
    'build/tools/check_webster_saved_projection.py',
    'build/tools/close_basil_holy_spirit.py',
    'build/tools/close_first_corinthians_collection.py',
    'build/tools/close_georgii_aliud.py',
    'build/tools/close_hilary_select_works_collection.py',
    'build/tools/close_ludewic.py',
    'build/tools/close_matthew_collection.py',
    'build/tools/close_nyssa_letters.py',
    'build/tools/close_predestination.py',
    'build/tools/close_walram.py',
    'build/tools/complete_baxter_christian_directory_private.py',
    'build/tools/complete_carey_enquiry_private.py',
    'build/tools/complete_convicts_visitor_private.py',
    'build/tools/complete_puritan_private_release.py',
    'build/tools/complete_smith_private_release.py',
    'build/tools/complete_stillingfleet_private.py',
    'build/tools/complete_young_children_private.py',
    'build/tools/eusebius_l811_install.py',
    'build/tools/farrar_stage_adapt.py',
    'build/tools/finalize_webster_log_binding.py',
    'build/tools/freeze_aquinas_four_current.py',
    'build/tools/freeze_calvin_complete_native.py',
    'build/tools/freeze_chrysostom_2_corinthians.py',
    'build/tools/freeze_chrysostom_romans.py',
    'build/tools/freeze_darby_current.py',
    'build/tools/freeze_donne_devotions.py',
    'build/tools/freeze_edwards_select_sermons_current.py',
    'build/tools/freeze_gregory_pastoral_epistles.py',
    'build/tools/freeze_gregory_selected_epistles.py',
    'build/tools/freeze_jerome_letters.py',
    'build/tools/freeze_murray_absolute_surrender_current.py',
    'build/tools/freeze_schaff_history_vol1_current.py',
    'build/tools/freeze_schaff_history_vol2_current.py',
    'build/tools/freeze_schaff_history_vol3_current.py',
    'build/tools/freeze_schaff_history_vol4_current.py',
    'build/tools/freeze_schaff_history_vol5_current.py',
    'build/tools/freeze_schaff_history_vol6_current.py',
    'build/tools/freeze_schaff_history_vol7_current.py',
    'build/tools/freeze_schaff_history_vol8_current.py',
    'build/tools/freeze_ylt_current.py',
    'build/tools/install_anderson_current.py',
    'build/tools/install_aquinas_four_current.py',
    'build/tools/install_arnulf_bsb830_master.py',
    'build/tools/install_augustine_confessions_electronic_acceptance.py',
    'build/tools/install_basil_hexaemeron.py',
    'build/tools/install_basil_holy_spirit.py',
    'build/tools/install_bay_psalm_book_1640_acceptance.py',
    'build/tools/install_bcp1559_current.py',
    'build/tools/install_bennett_retained_acceptance.py',
    'build/tools/install_blaikie_first_samuel_acceptance.py',
    'build/tools/install_blaikie_first_samuel_title_acceptance.py',
    'build/tools/install_blaikie_second_samuel.py',
    'build/tools/install_blaikie_second_samuel_title.py',
    'build/tools/install_bsb_current.py',
    'build/tools/install_calvin_complete_native.py',
    'build/tools/install_calvin_joshua_acceptance.py',
    'build/tools/install_calvin_joshua_acceptance_v11.py',
    'build/tools/install_calvin_joshua_acceptance_v12.py',
    'build/tools/install_calvin_joshua_acceptance_v14.py',
    'build/tools/install_chadwick_retained_acceptance.py',
    'build/tools/install_charnock_vol1_native_v2_acceptance.py',
    'build/tools/install_chinook_current.py',
    'build/tools/install_city_of_god_electronic_v2.py',
    'build/tools/install_convicts_visitor_acceptance.py',
    'build/tools/install_creeds_json_metadata_rebind.py',
    'build/tools/install_darby_current.py',
    'build/tools/install_dods_complete_acceptance.py',
    'build/tools/install_edwards_select_sermons_current.py',
    'build/tools/install_elmslie_pg71811.py',
    'build/tools/install_engwebpb_retained_acceptance.py',
    'build/tools/install_expositors_lib034_moule_skinner.py',
    'build/tools/install_expositors_lib034_readable_pair.py',
    'build/tools/install_farrar_retained_acceptance.py',
    'build/tools/install_findlay_retained_acceptance.py',
    'build/tools/install_first_corinthians_collection.py',
    'build/tools/install_georgii_aliud.py',
    'build/tools/install_green_current.py',
    'build/tools/install_guyon_pg24989_acceptance.py',
    'build/tools/install_hilary_select_works_collection.py',
    'build/tools/install_hitchcock_current.py',
    'build/tools/install_irenaeus_anf01_ccel_acceptance.py',
    'build/tools/install_kjva_current.py',
    'build/tools/install_l741_acceptance.py',
    'build/tools/install_l741_work_metadata.py',
    'build/tools/install_large_source_sets.py',
    'build/tools/install_lib030_spurgeon_morneve_acceptance.py',
    'build/tools/install_lib089_form_comments_acceptance.py',
    'build/tools/install_ludewic.py',
    'build/tools/install_maclaren_retained_acceptance.py',
    'build/tools/install_matthew_collection.py',
    'build/tools/install_moody_prevailing_prayer_61883.py',
    'build/tools/install_murray_absolute_surrender_current.py',
    'build/tools/install_nancy_prince_pg63579.py',
    'build/tools/install_nave_current.py',
    'build/tools/install_newman_apologia_pg22088.py',
    'build/tools/install_nyssa_letters.py',
    'build/tools/install_openmgh_bsb720_first_four.py',
    'build/tools/install_openmgh_bsb720_next_eleven.py',
    'build/tools/install_openmgh_bsb720_next_five.py',
    'build/tools/install_openmgh_bsb754_origo.py',
    'build/tools/install_original_douay_current.py',
    'build/tools/install_original_douay_notices.py',
    'build/tools/install_owen_evangelical_churches_acceptance.py',
    'build/tools/install_owen_lib052_sin_grace.py',
    'build/tools/install_owen_lib052_spiritually_minded.py',
    'build/tools/install_owen_lib052_temptation.py',
    'build/tools/install_owen_lib052_trinity.py',
    'build/tools/install_owen_lib052_truth_innocence.py',
    'build/tools/install_plummer_retained_acceptance.py',
    'build/tools/install_predestination.py',
    'build/tools/install_robertson_electronic_acceptance.py',
    'build/tools/install_robertson_harmony_doran_ocr.py',
    'build/tools/install_rutherford_letters_ccel_acceptance.py',
    'build/tools/install_schaff_history_vol2_current.py',
    'build/tools/install_schaff_history_vol5_current.py',
    'build/tools/install_schaff_history_vol6_current.py',
    'build/tools/install_schaff_history_vol8_current.py',
    'build/tools/install_smith_current.py',
    'build/tools/install_smith_retained_acceptance.py',
    'build/tools/install_stokes_retained_acceptance.py',
    'build/tools/install_walram.py',
    'build/tools/install_watson_retained_acceptance.py',
    'build/tools/install_webster_current.py',
    'build/tools/install_whole_duty_prayer_acceptance.py',
    'build/tools/install_ylt_current.py',
    'build/tools/inventory_docsouth_tei2.py',
    'build/tools/inventory_openmgh_exact_sources.py',
    'build/tools/l599_slave_trade_install.py',
    'build/tools/maclaren_psalms_complete_install.py',
    'build/tools/package_anderson_current.py',
    'build/tools/package_aquinas_four_current.py',
    'build/tools/package_bcp1559_current.py',
    'build/tools/package_brainerd_current.py',
    'build/tools/package_bsb_current.py',
    'build/tools/package_chrysostom_2_corinthians.py',
    'build/tools/package_chrysostom_romans.py',
    'build/tools/package_darby_current.py',
    'build/tools/package_donne_devotions.py',
    'build/tools/package_edwards_select_sermons_current.py',
    'build/tools/package_gregory_pastoral_epistles.py',
    'build/tools/package_gregory_selected_epistles.py',
    'build/tools/package_jerome_letters.py',
    'build/tools/package_jps_current.py',
    'build/tools/package_kjva_current.py',
    'build/tools/package_murray_absolute_surrender_current.py',
    'build/tools/package_original_douay_current.py',
    'build/tools/package_schaff_history_vol1_current.py',
    'build/tools/package_schaff_history_vol2_current.py',
    'build/tools/package_schaff_history_vol3_current.py',
    'build/tools/package_schaff_history_vol4_current.py',
    'build/tools/package_schaff_history_vol5_current.py',
    'build/tools/package_schaff_history_vol6_current.py',
    'build/tools/package_schaff_history_vol7_current.py',
    'build/tools/package_schaff_history_vol8_current.py',
    'build/tools/package_webster_current.py',
    'build/tools/package_ylt_current.py',
    'build/tools/preflight_didache_full_witness.py',
    'build/tools/preflight_npnf103_sidecars.py',
    'build/tools/prepare_blaikie_joshua_candidate.py',
    'build/tools/prepare_chrysostom_seven_sidecar_packet.py',
    'build/tools/prepare_city_of_god_acceptance_electronic_v2.py',
    'build/tools/prepare_creeds_json_six_lib062_manifests.py',
    'build/tools/prepare_direct_raw_four_sidecars.py',
    'build/tools/prepare_direct_raw_nine_sidecars.py',
    'build/tools/prepare_docsouth_tei2_illustrated_moore.py',
    'build/tools/prepare_docsouth_tei2_illustrated_slave_songs.py',
    'build/tools/prepare_docsouth_tei2_nested_quote.py',
    'build/tools/prepare_docsouth_tei2_simple.py',
    'build/tools/prepare_gutenberg_unreceipted_five.py',
    'build/tools/prepare_hodge_vol2_electronic_acceptance.py',
    'build/tools/prepare_l599_slave_trade_source.py',
    'build/tools/prepare_lookup_ccel_sidecar_packet.py',
    'build/tools/prepare_npnf103_work_candidates.py',
    'build/tools/prepare_npnf104_work_candidates.py',
    'build/tools/prepare_npnf105_work_candidates.py',
    'build/tools/prepare_npnf109_olympias_corpus.py',
    'build/tools/prepare_npnf109_rome_corpus.py',
    'build/tools/prepare_npnf113_work_candidates.py',
    'build/tools/prepare_npnf206_work_candidates.py',
    'build/tools/prepare_openmgh_bsb750_remaining.py',
    'build/tools/prepare_openmgh_bsb752_ansbert_hymn.py',
    'build/tools/prepare_openmgh_bsb754_rigoberti.py',
    'build/tools/prepare_openmgh_bsb829_flat_slices_manifests.py',
    'build/tools/prepare_openmgh_bsb829_gof_parts_manifests.py',
    'build/tools/prepare_openmgh_bsb829_parts_manifests.py',
    'build/tools/prepare_openmgh_bsb829_terminal_lines_manifests.py',
    'build/tools/prepare_openmgh_bsb830_alexandrinum_three.py',
    'build/tools/prepare_openmgh_bsb830_gerhoh.py',
    'build/tools/prepare_openmgh_bsb830_gualter_two.py',
    'build/tools/prepare_openmgh_bsb830_honorius.py',
    'build/tools/prepare_openmgh_bsb830_hugo.py',
    'build/tools/prepare_openmgh_bsb830_simony_seven.py',
    'build/tools/prepare_openmgh_bsb830_york.py',
    'build/tools/prepare_openmgh_bsb830_york_three.py',
    'build/tools/prepare_openmgh_exclusive_manifests.py',
    'build/tools/prepare_openmgh_passio_dormientium_dual.py',
    'build/tools/prepare_openmgh_vita_lupi_dual.py',
    'build/tools/prepare_original_douay_companion_v2.py',
    'build/tools/prepare_original_douay_release_notices.py',
    'build/tools/prepare_owen_lib051_readable_candidates.py',
    'build/tools/prepare_owen_sidecar_packet.py',
    'build/tools/prepare_revised_version_with_apocrypha_acceptance.py',
    'build/tools/prepare_robertson_electronic_acceptance.py',
    'build/tools/prepare_stokes_retained_candidates.py',
    'build/tools/prepare_tyerman_john_wesley_acceptance.py',
    'build/tools/prepare_tyerman_samuel_retained.py',
    'build/tools/prepare_tyerman_whitefield_complete.py',
    'build/tools/project_accepted_creeds_json.py',
    'build/tools/prototype_eusebius_l811_acceptance.py',
    'build/tools/prove_bennett_retained_install.py',
    'build/tools/prove_blaikie_first_samuel_install.py',
    'build/tools/prove_blaikie_first_samuel_title_install.py',
    'build/tools/prove_blaikie_second_samuel_install.py',
    'build/tools/prove_blaikie_second_samuel_title_install.py',
    'build/tools/prove_chadwick_retained_install.py',
    'build/tools/prove_dods_complete_install.py',
    'build/tools/prove_eusebius_l811_install.py',
    'build/tools/prove_eusebius_l811_retained.py',
    'build/tools/prove_farrar_retained_install.py',
    'build/tools/prove_findlay_retained_install.py',
    'build/tools/prove_green_install_rollback.py',
    'build/tools/prove_hitchcock_install_rollback.py',
    'build/tools/prove_l599_slave_trade_install.py',
    'build/tools/prove_maclaren_retained_install.py',
    'build/tools/prove_nave_install_rollback.py',
    'build/tools/prove_plummer_retained_install.py',
    'build/tools/prove_smith_retained_install.py',
    'build/tools/prove_stokes_acts_complete_install.py',
    'build/tools/prove_strong_vol2_current_install.py',
    'build/tools/prove_tyerman_john_wesley_install.py',
    'build/tools/prove_tyerman_samuel_install.py',
    'build/tools/prove_tyerman_samuel_retained.py',
    'build/tools/prove_tyerman_whitefield_complete.py',
    'build/tools/prove_tyerman_whitefield_install.py',
    'build/tools/prove_watson_retained_install.py',
    'build/tools/readback_lib030_spurgeon_morneve_install.py',
    'build/tools/reconstruct_first_corinthians_collection.py',
    'build/tools/reconstruct_hilary_select_works_collection.py',
    'build/tools/reconstruct_matthew_collection.py',
    'build/tools/record_brenton_septuagint_acceptance.py',
    'build/tools/refresh_chinook_notice.py',
    'build/tools/release_basil_hexaemeron.py',
    'build/tools/release_basil_holy_spirit.py',
    'build/tools/release_chrysostom_2_corinthians.py',
    'build/tools/release_chrysostom_romans.py',
    'build/tools/release_donne_devotions.py',
    'build/tools/release_first_corinthians_collection.py',
    'build/tools/release_gangulf_hymn.py',
    'build/tools/release_georgii_aliud.py',
    'build/tools/release_georgii_primum.py',
    'build/tools/release_gregory_pastoral_epistles.py',
    'build/tools/release_gregory_selected_epistles.py',
    'build/tools/release_hilary_select_works_collection.py',
    'build/tools/release_jerome_letters.py',
    'build/tools/release_ludewic.py',
    'build/tools/release_matthew_collection.py',
    'build/tools/release_nancy_prince_pg63579.py',
    'build/tools/release_nyssa_letters.py',
    'build/tools/release_openmgh_bsb830_york_four.py',
    'build/tools/release_prayers_baths_for_cure.py',
    'build/tools/release_predestination.py',
    'build/tools/release_schaff_history_vol1_current.py',
    'build/tools/release_schaff_history_vol2_current.py',
    'build/tools/release_schaff_history_vol3_current.py',
    'build/tools/release_schaff_history_vol4_current.py',
    'build/tools/release_schaff_history_vol5_current.py',
    'build/tools/release_schaff_history_vol6_current.py',
    'build/tools/release_schaff_history_vol7_current.py',
    'build/tools/release_walram.py',
    'build/tools/repair_charnock_vol1_publication_header.py',
    'build/tools/repair_install_nancy_prince_pg63579.py',
    'build/tools/replay_anderson_accepted.py',
    'build/tools/replay_aquinas_four_current.py',
    'build/tools/replay_bsb_accepted.py',
    'build/tools/replay_calvin_bound_header.py',
    'build/tools/replay_edwards_select_sermons_current.py',
    'build/tools/replay_hitchcock_current.py',
    'build/tools/replay_kjva_accepted.py',
    'build/tools/replay_murray_absolute_surrender_current.py',
    'build/tools/replay_nave_current.py',
    'build/tools/replay_schaff_history_vol5_current.py',
    'build/tools/replay_schaff_history_vol8_current.py',
    'build/tools/replay_webster_accepted.py',
    'build/tools/replay_ylt_accepted.py',
    'build/tools/resume_edwards_select_sermons_current_stage.py',
    'build/tools/revised_version_with_apocrypha_acceptance.py',
    'build/tools/run_anderson_current.py',
    'build/tools/run_aquinas_four_current.py',
    'build/tools/run_baltimore1_job.py',
    'build/tools/run_bcp1559_current.py',
    'build/tools/run_bcp1559_job.py',
    'build/tools/run_bsb_current.py',
    'build/tools/run_calvin_complete_native.py',
    'build/tools/run_darby_current.py',
    'build/tools/run_edwards_select_sermons_current.py',
    'build/tools/run_kjva_current.py',
    'build/tools/run_murray_absolute_surrender_current.py',
    'build/tools/run_openmgh_bsb829_flat_slices_stages.py',
    'build/tools/run_openmgh_bsb829_gof_parts_stages.py',
    'build/tools/run_openmgh_bsb829_parts_stages.py',
    'build/tools/run_schaff_history_vol1_current.py',
    'build/tools/run_schaff_history_vol2_current.py',
    'build/tools/run_schaff_history_vol3_current.py',
    'build/tools/run_schaff_history_vol4_current.py',
    'build/tools/run_schaff_history_vol5_current.py',
    'build/tools/run_schaff_history_vol6_current.py',
    'build/tools/run_schaff_history_vol7_current.py',
    'build/tools/run_schaff_history_vol8_current.py',
    'build/tools/run_webster_current.py',
    'build/tools/run_ylt_current.py',
    'build/tools/smith_isaiah_complete_install.py',
    'build/tools/stage_anderson_current.py',
    'build/tools/stage_anne_a22076_first_acceptance.py',
    'build/tools/stage_anne_a22095_acceptance.py',
    'build/tools/stage_anulus_openmgh_acceptance.py',
    'build/tools/stage_aquinas_four_current.py',
    'build/tools/stage_athanasius_npnf204_acceptances.py',
    'build/tools/stage_athanasius_npnf204_children.py',
    'build/tools/stage_augustine_confessions_electronic_acceptance.py',
    'build/tools/stage_augustine_harmony_electronic_acceptance.py',
    'build/tools/stage_basil_hexaemeron.py',
    'build/tools/stage_basil_holy_spirit.py',
    'build/tools/stage_bay_psalm_book_1640_acceptance.py',
    'build/tools/stage_bcp1549_current.py',
    'build/tools/stage_bcp1559_current.py',
    'build/tools/stage_bcp1662_current.py',
    'build/tools/stage_bennett_retained_acceptance.py',
    'build/tools/stage_blaikie_first_samuel_acceptance.py',
    'build/tools/stage_blaikie_first_samuel_title_acceptance.py',
    'build/tools/stage_blaikie_second_samuel.py',
    'build/tools/stage_blaikie_second_samuel_title.py',
    'build/tools/stage_boethius_complete_envelope_acceptance.py',
    'build/tools/stage_brainerd_current.py',
    'build/tools/stage_bsb_current.py',
    'build/tools/stage_calvin_complete_native.py',
    'build/tools/stage_chadwick_retained_acceptance.py',
    'build/tools/stage_charnock_vol1_current_acceptance.py',
    'build/tools/stage_chrysostom_2_corinthians.py',
    'build/tools/stage_chrysostom_liturgy.py',
    'build/tools/stage_chrysostom_romans.py',
    'build/tools/stage_convicts_visitor_acceptance.py',
    'build/tools/stage_creeds_json_first_eleven.py',
    'build/tools/stage_creeds_json_lib062_remaining.py',
    'build/tools/stage_creeds_json_metadata_rebind.py',
    'build/tools/stage_creeds_json_nested_confessions.py',
    'build/tools/stage_creeds_json_next_tranche.py',
    'build/tools/stage_creeds_json_two_catechisms.py',
    'build/tools/stage_creeds_json_westminster_proofs.py',
    'build/tools/stage_darby_current.py',
    'build/tools/stage_didache_full_witness_acceptance.py',
    'build/tools/stage_docsouth_tei2_illustrated_moore.py',
    'build/tools/stage_docsouth_tei2_illustrated_slave_songs.py',
    'build/tools/stage_docsouth_tei2_nested_quote.py',
    'build/tools/stage_docsouth_tei2_simple.py',
    'build/tools/stage_dods_complete_acceptance.py',
    'build/tools/stage_donne_devotions.py',
    'build/tools/stage_drummond_pg16739.py',
    'build/tools/stage_edwards_select_sermons_current.py',
    'build/tools/stage_elmslie_pg71811.py',
    'build/tools/stage_engwebpb_retained_acceptance.py',
    'build/tools/stage_evans_a63318_acceptance.py',
    'build/tools/stage_expositors_lib033_harper.py',
    'build/tools/stage_expositors_lib034_denney_pair.py',
    'build/tools/stage_expositors_lib034_lumby.py',
    'build/tools/stage_expositors_lib034_moule_skinner.py',
    'build/tools/stage_expositors_lib034_readable_pair.py',
    'build/tools/stage_expositors_lib035_edwards.py',
    'build/tools/stage_expositors_lib035_horton.py',
    'build/tools/stage_expositors_lib035_kellogg.py',
    'build/tools/stage_expositors_lib036_adeney_pair.py',
    'build/tools/stage_expositors_lib036_milligan.py',
    'build/tools/stage_farrar_retained_acceptance.py',
    'build/tools/stage_findlay_retained_acceptance.py',
    'build/tools/stage_first_confession_of_basel_acceptance.py',
    'build/tools/stage_first_corinthians_collection.py',
    'build/tools/stage_gangulf_hymn_acceptance.py',
    'build/tools/stage_georgii_aliud.py',
    'build/tools/stage_georgii_primum_acceptance.py',
    'build/tools/stage_green_current_acceptance.py',
    'build/tools/stage_gregory_eunomius_electronic_acceptance.py',
    'build/tools/stage_gregory_pastoral_epistles.py',
    'build/tools/stage_gregory_select_letters_npnf207_acceptance.py',
    'build/tools/stage_gregory_selected_epistles.py',
    'build/tools/stage_guyon_pg24989_acceptance.py',
    'build/tools/stage_hammon_n15943_acceptance.py',
    'build/tools/stage_hilary_select_works_collection.py',
    'build/tools/stage_hitchcock_current_acceptance.py',
    'build/tools/stage_hodge_vol1_complete.py',
    'build/tools/stage_hodge_vol2_complete.py',
    'build/tools/stage_hodge_vol3_electronic_acceptance.py',
    'build/tools/stage_irenaeus_anf01_ccel_acceptance.py',
    'build/tools/stage_jerome_letters.py',
    'build/tools/stage_jps_current.py',
    'build/tools/stage_kjva_current.py',
    'build/tools/stage_lib028_socrates_sozomen_acceptance.py',
    'build/tools/stage_lib029_complete_volume_acceptance.py',
    'build/tools/stage_lib030_spurgeon_morneve_acceptance.py',
    'build/tools/stage_lib031_bounds_power_acceptance.py',
    'build/tools/stage_lib031_remaining_acceptance.py',
    'build/tools/stage_lib040_augustine_division.py',
    'build/tools/stage_locke_a48888_acceptance.py',
    'build/tools/stage_ludewic.py',
    'build/tools/stage_maclaren_retained_acceptance.py',
    'build/tools/stage_marrant_n17016_acceptance.py',
    'build/tools/stage_matthew_collection.py',
    'build/tools/stage_modern_scepticism_current.py',
    'build/tools/stage_moody_prevailing_prayer_61883_acceptance.py',
    'build/tools/stage_murray_absolute_surrender_current.py',
    'build/tools/stage_nancy_prince_pg63579.py',
    'build/tools/stage_nave_current_acceptance.py',
    'build/tools/stage_newman_apologia_pg22088.py',
    'build/tools/stage_npnf103_work_acceptance.py',
    'build/tools/stage_npnf104_work_acceptance.py',
    'build/tools/stage_npnf105_work_acceptance.py',
    'build/tools/stage_npnf207_two_work_ccel_acceptance.py',
    'build/tools/stage_npnf211_electronic_acceptances.py',
    'build/tools/stage_nyssa_letters.py',
    'build/tools/stage_openmgh_bsb622_rupert_victoria_acceptance.py',
    'build/tools/stage_openmgh_bsb623_hermannus_epistola_acceptance.py',
    'build/tools/stage_openmgh_bsb623_hermannus_opusculum_acceptance.py',
    'build/tools/stage_openmgh_bsb720_carmina_three_acceptance.py',
    'build/tools/stage_openmgh_bsb720_first_four_acceptance.py',
    'build/tools/stage_openmgh_bsb720_heribert_hymns_acceptance.py',
    'build/tools/stage_openmgh_bsb720_next_eleven_acceptance.py',
    'build/tools/stage_openmgh_bsb720_next_five_acceptance.py',
    'build/tools/stage_openmgh_bsb720_reimundi_acceptance.py',
    'build/tools/stage_openmgh_bsb750_next.py',
    'build/tools/stage_openmgh_bsb751_nested.py',
    'build/tools/stage_openmgh_bsb752_ansbert_hymn.py',
    'build/tools/stage_openmgh_bsb752_nested.py',
    'build/tools/stage_openmgh_bsb752_next.py',
    'build/tools/stage_openmgh_bsb752_othgerii_acceptance.py',
    'build/tools/stage_openmgh_bsb753_desiderii_hymn_acceptance.py',
    'build/tools/stage_openmgh_bsb753_three_prose.py',
    'build/tools/stage_openmgh_bsb754_eucherii_acceptance.py',
    'build/tools/stage_openmgh_bsb754_nested.py',
    'build/tools/stage_openmgh_bsb754_vita_abbatum.py',
    'build/tools/stage_openmgh_bsb828_held_acceptance.py',
    'build/tools/stage_openmgh_bsb828_held_candidates.py',
    'build/tools/stage_openmgh_bsb828_next.py',
    'build/tools/stage_openmgh_bsb829_flat_slices_acceptance.py',
    'build/tools/stage_openmgh_bsb829_gof_parts_acceptance.py',
    'build/tools/stage_openmgh_bsb829_inspected.py',
    'build/tools/stage_openmgh_bsb829_next.py',
    'build/tools/stage_openmgh_bsb829_parts_acceptance.py',
    'build/tools/stage_openmgh_bsb829_terminal_lines_acceptance.py',
    'build/tools/stage_openmgh_bsb830_alexandrinum_three.py',
    'build/tools/stage_openmgh_bsb830_correspondence_pair_acceptance.py',
    'build/tools/stage_openmgh_bsb830_first_four.py',
    'build/tools/stage_openmgh_bsb830_gerhoh_acceptance.py',
    'build/tools/stage_openmgh_bsb830_gualter_two.py',
    'build/tools/stage_openmgh_bsb830_honorius_acceptance.py',
    'build/tools/stage_openmgh_bsb830_hugo_acceptance.py',
    'build/tools/stage_openmgh_bsb830_marbod_letters_acceptance.py',
    'build/tools/stage_openmgh_bsb830_marbod_poem_acceptance.py',
    'build/tools/stage_openmgh_bsb830_next.py',
    'build/tools/stage_openmgh_bsb830_remainder.py',
    'build/tools/stage_openmgh_bsb830_simony_seven.py',
    'build/tools/stage_openmgh_bsb830_verse.py',
    'build/tools/stage_openmgh_bsb830_york_acceptance.py',
    'build/tools/stage_openmgh_bsb830_york_four_acceptance.py',
    'build/tools/stage_openmgh_bsb830_york_three_acceptance.py',
    'build/tools/stage_openmgh_exact_work_div_acceptance.py',
    'build/tools/stage_openmgh_flat_ab_poetry.py',
    'build/tools/stage_openmgh_gesta.py',
    'build/tools/stage_openmgh_three_whole_acceptance.py',
    'build/tools/stage_original_douay_current.py',
    'build/tools/stage_original_douay_notices.py',
    'build/tools/stage_owen_evangelical_churches_acceptance.py',
    'build/tools/stage_owen_lib052_sin_grace.py',
    'build/tools/stage_owen_lib052_spiritually_minded.py',
    'build/tools/stage_owen_lib052_temptation.py',
    'build/tools/stage_owen_lib052_trinity.py',
    'build/tools/stage_owen_lib052_truth_innocence.py',
    'build/tools/stage_peter_jones_1860_acceptance.py',
    'build/tools/stage_pg_baltimore_no2_acceptance.py',
    'build/tools/stage_plummer_retained_acceptance.py',
    'build/tools/stage_prayers_baths_for_cure_acceptance.py',
    'build/tools/stage_predestination.py',
    'build/tools/stage_rutherford_letters_ccel_acceptance.py',
    'build/tools/stage_ryle_holiness_acceptance.py',
    'build/tools/stage_schaff_history_vol1_current.py',
    'build/tools/stage_schaff_history_vol2_current.py',
    'build/tools/stage_schaff_history_vol3_current.py',
    'build/tools/stage_schaff_history_vol4_current.py',
    'build/tools/stage_schaff_history_vol5_current.py',
    'build/tools/stage_schaff_history_vol6_current.py',
    'build/tools/stage_schaff_history_vol7_current.py',
    'build/tools/stage_schaff_history_vol8_current.py',
    'build/tools/stage_smith_retained_acceptance.py',
    'build/tools/stage_stephens_pg53809.py',
    'build/tools/stage_stokes_retained_acceptance.py',
    'build/tools/stage_strong_vol1_pg44035.py',
    'build/tools/stage_two_commentary_categories.py',
    'build/tools/stage_walram.py',
    'build/tools/stage_watson_retained_acceptance.py',
    'build/tools/stage_webster_current.py',
    'build/tools/stage_whole_duty_prayer_acceptance.py',
    'build/tools/stage_ylt_current.py',
    'build/tools/stokes_acts_complete_install.py',
    'build/tools/strong_vol2_current_header.py',
    'build/tools/strong_vol2_current_install.py',
    'build/tools/tyerman_john_wesley_install.py',
    'build/tools/tyerman_samuel_install.py',
    'build/tools/tyerman_whitefield_install.py',
    'build/tools/verify_robertson_pg36264.py',
)

for _cli_source in CLI_CONTRACT_SOURCES:
    COMPONENT_TEST_POLICIES[_cli_source] = ComponentTestPolicy(add=(
        "tests/test_cli_input_guards.py::"
        f"test_cli_parses_help_and_rejects_unknown_arguments_without_operations[{_cli_source}]",
    ))


# Imported route APIs must load without operations and expose their declared callables.
MODULE_CONTRACT_SOURCES = {
    'build/tei/ajops_jats_to_tei_v3.py': (('_convert', 1),),
    'build/tei/anderson_current_oracle.py': (('_oracle', 2),),
    'build/tei/anderson_current_reconstruction.py': (('_convert', 1),),
    'build/tei/anne_a22076_first_oracle_v1.py': (('_oracle', 2),),
    'build/tei/aquinas_four_current_oracle.py': (('_oracle', 2),),
    'build/tei/aquinas_four_current_reconstruction.py': (('_convert', 1),),
    'build/tei/asv_reviewed_header_v2.py': (('convert', 1),),
    'build/tei/asv_reviewed_header_v2_oracle.py': (('oracle', 2),),
    'build/tei/basil_hexaemeron_oracle.py': (('_oracle', 2),),
    'build/tei/basil_hexaemeron_reconstruction.py': (('_convert', 1),),
    'build/tei/basil_holy_spirit_oracle.py': (('_oracle', 2),),
    'build/tei/basil_holy_spirit_reconstruction.py': (('_convert', 1),),
    'build/tei/bcp1549_current_oracle.py': (('_oracle', 2),),
    'build/tei/bcp1549_current_reconstruction.py': (('_convert', 1),),
    'build/tei/bcp1559_current_oracle.py': (('_oracle', 2),),
    'build/tei/bcp1559_current_reconstruction.py': (('_convert', 1),),
    'build/tei/bcp1662_current_reconstruction.py': (('_convert', 1),),
    'build/tei/bcp1928_current_oracle.py': (),
    'build/tei/bcp1928_current_reconstruction.py': (),
    'build/tei/before_most_holy_pg76888_oracle.py': (('_oracle', 2),),
    'build/tei/before_most_holy_pg76888_reconstruction.py': (('_convert', 1),),
    'build/tei/bennett_retained_native_emitter.py': (),
    'build/tei/bennett_retained_scope.py': (),
    'build/tei/blaikie_first_samuel_retained_native_emitter.py': (),
    'build/tei/blaikie_joshua_legacy_oracle.py': (),
    'build/tei/blaikie_joshua_retained_native_emitter.py': (),
    'build/tei/blaikie_joshua_retained_scope.py': (),
    'build/tei/blaikie_second_samuel_emitter.py': (),
    'build/tei/blaikie_second_samuel_scope.py': (),
    'build/tei/boethius_complete_envelope_oracle.py': (('_oracle', 2),),
    'build/tei/brainerd_current_oracle.py': (('_oracle', 2),),
    'build/tei/brainerd_current_reconstruction.py': (('_convert', 1),),
    'build/tei/bsb_current_oracle.py': (('_oracle', 2),),
    'build/tei/bsb_current_reconstruction.py': (('_convert', 1),),
    'build/tei/calvin_institutes_complete_native.py': (('_convert', 1),),
    'build/tei/calvin_institutes_complete_native_oracle.py': (('_oracle', 2),),
    'build/tei/calvin_joshua_catalogue_oracle_draft.py': (),
    'build/tei/calvin_joshua_catalogue_oracle_v2.py': (),
    'build/tei/calvin_joshua_catalogue_oracle_v3.py': (),
    'build/tei/calvin_joshua_catalogue_oracle_v4.py': (),
    'build/tei/calvin_joshua_oracle_v2.py': (('_oracle', 2),),
    'build/tei/calvin_joshua_oracle_v3.py': (('_oracle', 2),),
    'build/tei/calvin_joshua_oracle_v4.py': (('_oracle', 2),),
    'build/tei/calvin_joshua_oracle_v5.py': (('_oracle', 2),),
    'build/tei/calvin_joshua_reconstruction.py': (('_convert', 1),),
    'build/tei/calvin_joshua_reconstruction_v2.py': (('_convert', 1),),
    'build/tei/calvin_joshua_reconstruction_v3.py': (('_convert', 1),),
    'build/tei/calvin_joshua_source_native_draft.py': (),
    'build/tei/ccel_retained_native_emitter.py': (),
    'build/tei/chadwick_retained_native_emitter.py': (),
    'build/tei/chadwick_retained_scope.py': (),
    'build/tei/charnock_gutenberg_native_v2_oracle.py': (('_oracle', 2),),
    'build/tei/charnock_gutenberg_native_v2_reconstruction.py': (('_convert', 1),),
    'build/tei/chrysostom_2_corinthians_oracle.py': (('_oracle', 2),),
    'build/tei/chrysostom_2_corinthians_reconstruction.py': (('_convert', 1),),
    'build/tei/chrysostom_romans_oracle.py': (('_oracle', 2),),
    'build/tei/chrysostom_romans_reconstruction.py': (('_convert', 1),),
    'build/tei/coppens_pg70790_source_native_v2.py': (('_convert', 1),),
    'build/tei/coppens_pg70790_source_native_v2_oracle.py': (('_oracle', 2),),
    'build/tei/coppens_pg70790_source_native_v3.py': (('_convert', 1),),
    'build/tei/coppens_pg70790_source_native_v3_oracle.py': (('_oracle', 2),),
    'build/tei/coppens_pg70790_source_native_v4.py': (('_convert', 1),),
    'build/tei/coppens_pg70790_source_native_v4_oracle.py': (('_oracle', 2),),
    'build/tei/coppens_pg70790_source_native_v5.py': (('_convert', 1),),
    'build/tei/coppens_pg70790_source_native_v5_oracle.py': (('_oracle', 2),),
    'build/tei/cox_pg39440_native_oracle_v1.py': (),
    'build/tei/cox_pg39440_native_v1.py': (),
    'build/tei/darby_current_oracle.py': (('_oracle', 2),),
    'build/tei/darby_current_reconstruction.py': (('_convert', 1),),
    'build/tei/docsouth_gaines_exact_v4_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_gaines_exact_v5_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_gaines_exact_v6_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_green_exact_v2.py': (('_convert', 1),),
    'build/tei/docsouth_green_exact_v2_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_green_exact_v3_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_green_gaines_exact_v1.py': (('_convert', 1),),
    'build/tei/docsouth_green_gaines_exact_v3_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_jamison_v2.py': (('_convert', 1),),
    'build/tei/docsouth_jamison_v2_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_l739_slave_songs.py': (),
    'build/tei/docsouth_l739_slave_songs_oracle.py': (),
    'build/tei/docsouth_l739_slave_songs_oracle_v3.py': (('_oracle', 2),),
    'build/tei/docsouth_l739_slave_songs_v2.py': (('_convert', 1),),
    'build/tei/docsouth_l761_l762.py': (),
    'build/tei/docsouth_l761_l762_one_root_oracle.py': (),
    'build/tei/docsouth_l761_l762_one_root_v2_oracle.py': (),
    'build/tei/docsouth_l762_walters_v2.py': (('_convert', 1),),
    'build/tei/docsouth_l762_walters_v2_oracle.py': (('_oracle', 2),),
    'build/tei/docsouth_truth75_v2.py': (('_convert', 1),),
    'build/tei/docsouth_truth75_v2_oracle.py': (('_oracle', 2),),
    'build/tei/dods_complete_oracle.py': (('_oracle', 2),),
    'build/tei/dods_retained_native_emitter.py': (),
    'build/tei/donne_devotions_scoped_oracle.py': (('_oracle', 2),),
    'build/tei/durham_import_closure.py': (),
    'build/tei/edwards_select_sermons_current_oracle.py': (('_oracle', 2),),
    'build/tei/edwards_select_sermons_current_reconstruction.py': (('_convert', 1),),
    'build/tei/eliza_southall_pg11959_reconstruction.py': (('_convert', 1),),
    'build/tei/engwebpb_repaired_semantic_inline_oracle.py': (('oracle', 2),),
    'build/tei/engwebpb_retained_tei_heading_repair.py': (('_convert', 1),),
    'build/tei/eusebius_l811_native_accepted_check_proposal.py': (),
    'build/tei/eusebius_l811_native_accepted_proposal.py': (),
    'build/tei/eusebius_l811_native_context_proposal.py': (),
    'build/tei/eusebius_l811_native_leaf_proposal.py': (),
    'build/tei/eusebius_l811_native_observer_proposal.py': (),
    'build/tei/eusebius_l811_retained_repair.py': (('_convert', 1),),
    'build/tei/eusebius_l811_runtime.py': (),
    'build/tei/eusebius_l811_source_oracle.py': (('_oracle', 2),),
    'build/tei/evening_incense_pg50916_reconstruction.py': (('_convert', 1),),
    'build/tei/farrar_original_scope.py': (),
    'build/tei/farrar_retained_native_emitter.py': (),
    'build/tei/fell_a41072_reconstruction.py': (('_convert', 1),),
    'build/tei/findlay_retained_oracle.py': (('_oracle', 2),),
    'build/tei/first_corinthians_collection_oracle.py': (('_oracle', 2),),
    'build/tei/first_corinthians_collection_reconstruction.py': (('_convert', 1),),
    'build/tei/gangulf_hymn_reconstruction.py': (('_convert', 1),),
    'build/tei/georgii_aliud_oracle.py': (('_oracle', 2),),
    'build/tei/georgii_aliud_reconstruction.py': (('_convert', 1),),
    'build/tei/georgii_primum_reconstruction.py': (('_convert', 1),),
    'build/tei/gregory_pastoral_epistles_oracle.py': (('_oracle', 2),),
    'build/tei/gregory_pastoral_epistles_reconstruction.py': (('_convert', 1),),
    'build/tei/gregory_selected_epistles_oracle.py': (('_oracle', 2),),
    'build/tei/gregory_selected_epistles_reconstruction.py': (('_convert', 1),),
    'build/tei/guyon_short_method_24989_v13.py': (('_convert', 1),),
    'build/tei/guyon_short_method_24989_v13_oracle.py': (('_oracle', 2),),
    'build/tei/guyon_short_method_24989_v14.py': (('_convert', 1),),
    'build/tei/guyon_short_method_24989_v14_oracle.py': (('_oracle', 2),),
    'build/tei/guyon_short_method_24989_v15.py': (('_convert', 1),),
    'build/tei/guyon_short_method_24989_v15_oracle.py': (('_oracle', 2),),
    'build/tei/guyon_short_method_24989_v16.py': (('_convert', 1),),
    'build/tei/guyon_short_method_24989_v16_oracle.py': (('_oracle', 2),),
    'build/tei/hilary_select_works_collection_oracle.py': (('_oracle', 2),),
    'build/tei/hilary_select_works_collection_reconstruction.py': (('_convert', 1),),
    'build/tei/hodge_systematic_theology_vol_2_reconstruction_visual_v2.py': (('_convert', 1),),
    'build/tei/hodge_vol1_complete_oracle.py': (('_oracle', 2),),
    'build/tei/hodge_vol1_complete_reconstruction.py': (('_convert', 1),),
    'build/tei/hodge_vol2_complete_oracle.py': (('_oracle', 2),),
    'build/tei/hodge_vol2_complete_reconstruction.py': (('_convert', 1),),
    'build/tei/jarena_lee_pg66953_reconstruction.py': (('_convert', 1),),
    'build/tei/jerome_letters_oracle.py': (('_oracle', 2),),
    'build/tei/jerome_letters_reconstruction.py': (('_convert', 1),),
    'build/tei/john_l812_profile_v1/__init__.py': (),
    'build/tei/john_l812_profile_v1/accepted_runtime.py': (),
    'build/tei/john_l812_profile_v1/header_profile.py': (),
    'build/tei/john_l812_profile_v1/john_l812_leaf_v5.py': (),
    'build/tei/john_l812_profile_v1/reader_profile.py': (),
    'build/tei/john_l812_profile_v1/source_projection.py': (),
    'build/tei/jps_current_oracle.py': (('_oracle', 2),),
    'build/tei/jps_current_reconstruction.py': (('_convert', 1),),
    'build/tei/kjva_current_oracle.py': (('_oracle', 2),),
    'build/tei/kjva_current_reconstruction.py': (('_convert', 1),),
    'build/tei/l225_engwebc_native_oracle_v1.py': (),
    'build/tei/l225_engwebc_native_v1.py': (),
    'build/tei/l225_engwebpb_semantic_inline_oracle.py': (('oracle', 2),),
    'build/tei/l225_engwmb_native_oracle_v1.py': (),
    'build/tei/l225_engwmb_native_v1.py': (),
    'build/tei/l599_slave_trade_readable.py': (),
    'build/tei/l599_slave_trade_readable_check.py': (),
    'build/tei/l599_slave_trade_runtime.py': (),
    'build/tei/l599_slave_trade_source_facts.py': (),
    'build/tei/l599_slave_trade_source_oracle.py': (('_oracle', 2),),
    'build/tei/l599_slave_trade_source_package.py': (('_convert', 1),),
    'build/tei/l671_l674_semantic.py': (('_convert', 1),),
    'build/tei/l744_hymns.py': (('_convert', 1),),
    'build/tei/leeser_tanakh_1853.py': (('convert', 1),),
    'build/tei/leeser_tanakh_1853_oracle.py': (('oracle', 2),),
    'build/tei/lib031_bounds_standalone_oracle.py': (),
    'build/tei/lib062_six_catechisms_oracle.py': (('oracle', 2),),
    'build/tei/lib062_six_catechisms_reconstruction.py': (('convert', 1),),
    'build/tei/ludewic_oracle.py': (('_oracle', 2),),
    'build/tei/ludewic_reconstruction.py': (('_convert', 1),),
    'build/tei/luther_galatians_native_v2_oracle.py': (('_oracle', 2),),
    'build/tei/luther_galatians_native_v2_reconstruction.py': (('_convert', 1),),
    'build/tei/lutheran_hymnbook_pg76498.py': (('_convert', 1),),
    'build/tei/maclaren_psalms_complete_oracle.py': (('oracle', 2),),
    'build/tei/maclaren_psalms_complete_prepare.py': (('convert', 1),),
    'build/tei/maclaren_retained_native_emitter.py': (),
    'build/tei/manifest_acquisition_ocr_oracle.py': (('_oracle', 2),),
    'build/tei/manifest_acquisition_ocr_reconstruction.py': (('_convert', 1),),
    'build/tei/manifest_held_pg_one_root.py': (('_convert', 1),),
    'build/tei/manifest_held_pg_one_root_oracle.py': (('_oracle', 2),),
    'build/tei/manifest_pg_l640_noah_davis.py': (('_convert', 1),),
    'build/tei/manifest_pg_l640_noah_davis_oracle.py': (('_oracle', 2),),
    'build/tei/manifest_pg_l772_l790.py': (('_convert', 1),),
    'build/tei/manifest_pg_l772_l790_oracle.py': (('_oracle', 2),),
    'build/tei/manifest_pg_l793_l795.py': (('_convert', 1),),
    'build/tei/manifest_pg_l793_l795_oracle.py': (('_oracle', 2),),
    'build/tei/matthew_collection_oracle.py': (('_oracle', 2),),
    'build/tei/matthew_collection_reconstruction.py': (('_convert', 1),),
    'build/tei/modern_scepticism_current_oracle.py': (('_oracle', 2),),
    'build/tei/modern_scepticism_current_reconstruction.py': (('_convert', 1),),
    'build/tei/modern_scepticism_manifest_oracle.py': (('_oracle', 2),),
    'build/tei/modern_scepticism_manifest_reconstruction.py': (('_convert', 1),),
    'build/tei/murray_absolute_surrender_current_oracle.py': (('_oracle', 2),),
    'build/tei/murray_absolute_surrender_current_reconstruction.py': (('_convert', 1),),
    'build/tei/nancy_prince_pg63579_oracle.py': (('_oracle', 2),),
    'build/tei/nancy_prince_pg63579_reconstruction.py': (('_convert', 1),),
    'build/tei/newman_grammar_pg34022_package.py': (('_convert', 1),),
    'build/tei/newman_parochial_pg_oracle.py': (),
    'build/tei/newman_parochial_pg_reconstruction.py': (),
    'build/tei/newman_parochial_pg_work_oracle.py': (),
    'build/tei/newman_parochial_pg_work_reconstruction.py': (),
    'build/tei/npnf103_work_reconstruction.py': (('_convert', 1),),
    'build/tei/npnf103_work_reconstruction_v2.py': (('_convert', 1),),
    'build/tei/npnf105_work_reconstruction.py': (('_convert', 1),),
    'build/tei/npnf109_olympias_corpus.py': (('_convert', 1),),
    'build/tei/npnf109_rome_corpus.py': (('_convert', 1),),
    'build/tei/npnf109_work_reconstruction.py': (('_convert', 1),),
    'build/tei/npnf205_work_reconstruction.py': (('_convert', 1),),
    'build/tei/npnf_ambrose_duties_faith_title_v3.py': (('_convert', 1),),
    'build/tei/npnf_ambrose_repentance_note_v3.py': (('_convert', 1),),
    'build/tei/npnf_ambrose_satyrus_title_v3.py': (('_convert', 1),),
    'build/tei/npnf_ambrose_widows_title_v3.py': (('_convert', 1),),
    'build/tei/npnf_ambrose_work_local.py': (('_convert', 1),),
    'build/tei/nyssa_letters_oracle.py': (('_oracle', 2),),
    'build/tei/nyssa_letters_reconstruction.py': (('_convert', 1),),
    'build/tei/old_elizabeth_pg17826_oracle.py': (('_oracle', 2),),
    'build/tei/old_elizabeth_pg17826_reconstruction.py': (('_convert', 1),),
    'build/tei/open_english_bible_2025_6_oracle.py': (('_oracle', 2),),
    'build/tei/openmgh_bsb754_rigoberti_oracle.py': (),
    'build/tei/openmgh_bsb828_held_reconstruction.py': (('_convert', 1),),
    'build/tei/openmgh_bsb830_gerhoh_reconstruction.py': (('_convert', 1),),
    'build/tei/openmgh_bsb830_honorius_reconstruction.py': (('_convert', 1),),
    'build/tei/openmgh_bsb830_hugo_reconstruction.py': (('_convert', 1),),
    'build/tei/openmgh_bsb830_york_four_reconstruction.py': (('_convert', 1),),
    'build/tei/openmgh_bsb830_york_reconstruction.py': (('_convert', 1),),
    'build/tei/openmgh_bsb830_york_three_reconstruction.py': (('_convert', 1),),
    'build/tei/original_douay_current_oracle.py': (('_oracle', 2),),
    'build/tei/original_douay_current_reconstruction.py': (('_convert', 1),),
    'build/tei/otterbein_pg16455.py': (('_convert', 1),),
    'build/tei/otterbein_pg16455_oracle.py': (('_oracle', 2),),
    'build/tei/pg49917_holy_images.py': (('_convert', 1),),
    'build/tei/pg49917_holy_images_oracle.py': (('_oracle', 2),),
    'build/tei/pg_gutenberg_html.py': (),
    'build/tei/plummer_retained_native_emitter.py': (),
    'build/tei/plummer_retained_scope.py': (),
    'build/tei/predestination_oracle.py': (('_oracle', 2),),
    'build/tei/predestination_reconstruction.py': (('_convert', 1),),
    'build/tei/prepare_pg42957_manifest.py': (),
    'build/tei/private_devotions_a75019_consumer.py': (),
    'build/tei/pta_l812_retained_tei_oracle_v3.py': (('_oracle', 2),),
    'build/tei/pta_retained_tei.py': (('_convert', 1),),
    'build/tei/pta_retained_tei_oracle.py': (('_oracle', 2),),
    'build/tei/revised_version_with_apocrypha_corpus_oracle.py': (('_oracle', 2),),
    'build/tei/robertson_harmony_1922_reconstruction.py': (('_convert', 1),),
    'build/tei/robertson_pg36264_oracle.py': (('_oracle', 2),),
    'build/tei/robertson_pg36264_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol1_current_oracle.py': (('_oracle', 2),),
    'build/tei/schaff_history_vol1_current_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol2_current_oracle.py': (('_oracle', 2),),
    'build/tei/schaff_history_vol2_current_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol3_current_oracle.py': (('_oracle', 2),),
    'build/tei/schaff_history_vol3_current_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol4_current_oracle.py': (('_oracle', 2),),
    'build/tei/schaff_history_vol4_current_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol5_current_oracle.py': (('_oracle', 2),),
    'build/tei/schaff_history_vol5_current_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol6_current_oracle.py': (('_oracle', 2),),
    'build/tei/schaff_history_vol6_current_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol7_current_oracle.py': (('_oracle', 2),),
    'build/tei/schaff_history_vol7_current_reconstruction.py': (('_convert', 1),),
    'build/tei/schaff_history_vol8_current_reconstruction.py': (('_convert', 1),),
    'build/tei/smith_isaiah_complete_oracle.py': (('oracle', 2),),
    'build/tei/smith_isaiah_complete_prepare.py': (('convert', 1),),
    'build/tei/smith_isaiah_source_oracle.py': (),
    'build/tei/spurgeon_mtp_install_20261003_oracle.py': (('_oracle', 2),),
    'build/tei/spurgeon_mtp_install_20261003_repair.py': (),
    'build/tei/stokes_acts_complete_oracle.py': (('oracle', 2),),
    'build/tei/stokes_retained_completion_oracle.py': (('oracle', 2),),
    'build/tei/stokes_retained_scope.py': (),
    'build/tei/strong_vol2_current_oracle.py': (('_oracle', 2),),
    'build/tei/strong_vol2_current_prepare.py': (('_convert', 1),),
    'build/tei/tcp_private_devotions_a75019.py': (('_convert', 1),),
    'build/tei/tcp_private_devotions_a75019_oracle.py': (('_oracle', 2),),
    'build/tei/thome_pg70704_complete_v3.py': (('_convert', 1),),
    'build/tei/thome_pg70704_complete_v3_oracle.py': (('_oracle', 2),),
    'build/tei/tyerman_john_wesley_emitter.py': (),
    'build/tei/tyerman_john_wesley_oracle.py': (('_oracle', 2),),
    'build/tei/tyerman_john_wesley_prepare.py': (('_convert', 1),),
    'build/tei/tyerman_pg_html.py': (('_convert', 1),),
    'build/tei/tyerman_pg_html_oracle.py': (('_oracle', 2),),
    'build/tei/tyerman_samuel_retained_repair.py': (('_convert', 1),),
    'build/tei/tyerman_samuel_source_oracle.py': (('_oracle', 2),),
    'build/tei/tyerman_whitefield_complete.py': (('_convert', 1),),
    'build/tei/tyerman_whitefield_complete_oracle.py': (('_oracle', 2),),
    'build/tei/tyerman_whitefield_runtime.py': (),
    'build/tei/ursinus_heidelberg_1852_reconstruction.py': (('convert', 1),),
    'build/tei/ursinus_heidelberg_1852_reconstruction_oracle.py': (('oracle', 2),),
    'build/tei/ursinus_heidelberg_1852_v3_reconstruction.py': (('convert', 1),),
    'build/tei/ursinus_heidelberg_1852_v3_reconstruction_oracle.py': (('oracle', 2),),
    'build/tei/ursinus_heidelberg_1852_v4_reconstruction.py': (('convert', 1),),
    'build/tei/ursinus_heidelberg_1852_v4_reconstruction_oracle.py': (('oracle', 2),),
    'build/tei/ursinus_heidelberg_1852_v5_reconstruction.py': (('convert', 1),),
    'build/tei/ursinus_heidelberg_1852_v5_reconstruction_oracle.py': (('oracle', 2),),
    'build/tei/ursinus_heidelberg_1852_v6_reconstruction.py': (('convert', 1),),
    'build/tei/ursinus_heidelberg_1852_v6_reconstruction_oracle.py': (('oracle', 2),),
    'build/tei/vincent_pg6733_oracle.py': (('_oracle', 2),),
    'build/tei/vincent_pg6733_reconstruction.py': (('_convert', 1),),
    'build/tei/walram_oracle.py': (('_oracle', 2),),
    'build/tei/walram_reconstruction.py': (('_convert', 1),),
    'build/tei/watson_original_scope.py': (),
    'build/tei/watson_retained_native_emitter.py': (),
    'build/tei/web_eng_reconstruction.py': (('_convert', 1),),
    'build/tei/webster_current_oracle.py': (('_oracle', 2),),
    'build/tei/webster_current_reconstruction.py': (('_convert', 1),),
    'build/tei/westminster_shorter_catechism_provider_editions.py': (),
    'build/tei/westminster_shorter_catechism_provider_oracle.py': (),
    'build/tei/whitefield_works_l646_oracle.py': (),
    'build/tei/whitefield_works_l646_seed_reconstruction.py': (),
    'build/tei/whitefield_works_l646_v2_oracle.py': (),
    'build/tei/whitefield_works_l646_v2_reconstruction.py': (),
    'build/tei/whitefield_works_l646_v3_oracle.py': (),
    'build/tei/whitefield_works_l646_v3_reconstruction.py': (),
    'build/tei/woolman_37311_reconstruction.py': (('_convert', 1),),
    'build/tei/ylt_current_oracle.py': (('_oracle', 2),),
    'build/tei/ylt_current_reconstruction.py': (('_convert', 1),),
    'build/tools/accept_westminster_shorter_catechism_provider_editions.py': (),
    'build/tools/acquire_pta_l813_sources.py': (),
    'build/tools/align_donne_devotions_scope.py': (),
    'build/tools/anderson_context_annex.py': (),
    'build/tools/apply_anne_first_metadata.py': (),
    'build/tools/apply_bede_prose_prerequisite.py': (),
    'build/tools/apply_hitchcock_native_support.py': (),
    'build/tools/apply_nave_category_prerequisite.py': (),
    'build/tools/apply_nave_native_support.py': (),
    'build/tools/apply_smith_category.py': (),
    'build/tools/apply_smith_native_support.py': (),
    'build/tools/assess_blaikie_joshua_retained.py': (),
    'build/tools/assess_eusebius_l811_retained.py': (),
    'build/tools/assess_smith_isaiah_complete.py': (),
    'build/tools/audit_anderson_final.py': (),
    'build/tools/audit_asv_final.py': (),
    'build/tools/audit_bsb_final.py': (),
    'build/tools/audit_docsouth_figure_entities.py': (),
    'build/tools/audit_kjva_final.py': (),
    'build/tools/audit_openmgh_bsb829_stages.py': (),
    'build/tools/audit_schaff_history_vol6_current.py': (),
    'build/tools/audit_walters_final.py': (),
    'build/tools/audit_webster_final.py': (),
    'build/tools/bind_bcp1662_current_mutations.py': (),
    'build/tools/capture_expositors_lib034_denney_loci.py': (),
    'build/tools/challenge_blaikie_first_samuel_candidates.py': (),
    'build/tools/challenge_blaikie_first_samuel_contracts.py': (),
    'build/tools/challenge_dods_complete_candidates.py': (),
    'build/tools/challenge_dods_complete_contracts.py': (),
    'build/tools/check_aquinas_four_current_runtime.py': (),
    'build/tools/check_aquinas_four_public_route.py': (),
    'build/tools/check_bede_downstream_prerequisite.py': (),
    'build/tools/check_bede_isolated_route.py': (),
    'build/tools/check_green_current_candidate.py': (),
    'build/tools/check_green_relationships.py': (),
    'build/tools/check_lib031_remaining_stages.py': (),
    'build/tools/check_lib054_work_local_stages.py': (),
    'build/tools/check_openmgh_bsb828_held_reproduction.py': (),
    'build/tools/check_original_douay_release_notices.py': (),
    'build/tools/check_watson_beatitudes_installed_closure.py': (),
    'build/tools/check_ylt_final_source_readback.py': (),
    'build/tools/close_chrysostom_2_corinthians.py': (),
    'build/tools/close_chrysostom_romans.py': (),
    'build/tools/close_donne_devotions.py': (),
    'build/tools/close_gregory_pastoral_epistles.py': (),
    'build/tools/close_gregory_selected_epistles.py': (),
    'build/tools/close_jerome_letters.py': (),
    'build/tools/close_nave_private_release.py': (),
    'build/tools/close_schaff_history_vol1_current.py': (),
    'build/tools/complete_american_missionary_private_release.py': (),
    'build/tools/complete_anne_first_private_release.py': (),
    'build/tools/complete_apostolic_tradition_private_release.py': (),
    'build/tools/complete_aquinas_four_private_release.py': (),
    'build/tools/complete_asv_private.py': (),
    'build/tools/complete_baltimore1_private_release.py': (),
    'build/tools/complete_baltimore2_private_release.py': (),
    'build/tools/complete_bcp1559_private_release.py': (),
    'build/tools/complete_bcp1928_private_release.py': (),
    'build/tools/complete_bede_private_release.py': (),
    'build/tools/complete_blaikie_first_samuel_private_release.py': (),
    'build/tools/complete_boethius_private_release.py': (),
    'build/tools/complete_chinook_private_release.py': (),
    'build/tools/complete_clarke_private_release.py': (),
    'build/tools/complete_darby_private_release.py': (),
    'build/tools/complete_darby_private_release_resume.py': (),
    'build/tools/complete_directory_family_worship_private.py': (),
    'build/tools/complete_easton_private_release.py': (),
    'build/tools/complete_edwards_select_sermons_private_release.py': (),
    'build/tools/complete_engwebpb_private_release.py': (),
    'build/tools/complete_equiano_private_release.py': (),
    'build/tools/complete_equiano_private_release_v2.py': (),
    'build/tools/complete_eusebius_l811_source.py': (),
    'build/tools/complete_green_private_release.py': (),
    'build/tools/complete_hitchcock_private_release.py': (),
    'build/tools/complete_hodge_vol1_private_release.py': (),
    'build/tools/complete_law_serious_call_private_release.py': (),
    'build/tools/complete_lib030_spurgeon_morneve_private_release.py': (),
    'build/tools/complete_matthew_henry_private_release.py': (),
    'build/tools/complete_modern_scepticism_private_release.py': (),
    'build/tools/complete_murray_absolute_surrender_private_release.py': (),
    'build/tools/complete_nave_private_release.py': (),
    'build/tools/complete_original_douay_lossless_release.py': (),
    'build/tools/complete_original_douay_private_release.py': (),
    'build/tools/complete_pascal_pensees_private_release.py': (),
    'build/tools/complete_pg49917_assumption_sermon_i_private_release.py': (),
    'build/tools/complete_pg49917_assumption_sermon_ii_private_release.py': (),
    'build/tools/complete_pg49917_assumption_sermon_iii_private_release.py': (),
    'build/tools/complete_pg77576_ignatius_magnesians_private_release.py': (),
    'build/tools/complete_pg77576_ignatius_philadelphians_private_release.py': (),
    'build/tools/complete_pg77576_ignatius_polycarp_private_release.py': (),
    'build/tools/complete_pg77576_ignatius_romans_private_release.py': (),
    'build/tools/complete_pg77576_ignatius_smyrnaeans_private_release.py': (),
    'build/tools/complete_pg77576_polycarp_epistle_private_release.py': (),
    'build/tools/complete_pg77576_virgin_mary_private_release.py': (),
    'build/tools/complete_revised_version_private_release.py': (),
    'build/tools/complete_rutherford_letters_private_release.py': (),
    'build/tools/complete_schaff_history_vol5_private_release.py': (),
    'build/tools/complete_schaff_history_vol8_private_release.py': (),
    'build/tools/complete_spurgeon_mtp_private_release.py': (),
    'build/tools/complete_torrey_private_release.py': (),
    'build/tools/complete_tyerman_samuel_source_proof.py': (),
    'build/tools/complete_walters_private_release.py': (),
    'build/tools/complete_watson_private_release.py': (),
    'build/tools/complete_whole_duty_prayer_private_release.py': (),
    'build/tools/complete_ylt_private_release.py': (),
    'build/tools/corroborate_baltimore1_final.py': (),
    'build/tools/derive_blaikie_first_samuel_install.py': (),
    'build/tools/derive_blaikie_first_samuel_title_install.py': (),
    'build/tools/derive_blaikie_joshua_route.py': (),
    'build/tools/derive_smith_isaiah_install.py': (),
    'build/tools/derive_smith_isaiah_source_oracle.py': (),
    'build/tools/diagnose_equiano_current_receipt.py': (),
    'build/tools/draft_bede_notice.py': (),
    'build/tools/draft_calvin_release_notice_v2.py': (),
    'build/tools/eusebius_l811_unexpected_late_v1.py': (),
    'build/tools/farrar_initialize_retained.py': (),
    'build/tools/farrar_retained_assess.py': (),
    'build/tools/farrar_unexpected_import_not_authorized.py': (),
    'build/tools/farrar_unexpected_import_not_authorized_v2.py': (),
    'build/tools/final_audit_calvin_complete_native.py': (),
    'build/tools/final_audit_schaff_history_vol6_current.py': (),
    'build/tools/finalize_bcp1559_private_release.py': (),
    'build/tools/finalize_bcp1662_private_release.py': (),
    'build/tools/finalize_jps_review_bindings.py': (),
    'build/tools/finalize_original_douay_notices.py': (),
    'build/tools/finalize_ylt_private_release.py': (),
    'build/tools/findlay_stage_adapt.py': (),
    'build/tools/finish_aquinas_four_public_route.py': (),
    'build/tools/finish_aquinas_four_publication_notices.py': (),
    'build/tools/finish_baltimore1_private_release.py': (),
    'build/tools/freeze_bcp1559_current.py': (),
    'build/tools/freeze_docsouth_tei2_illustrated_moore.py': (),
    'build/tools/freeze_docsouth_tei2_illustrated_slave_songs.py': (),
    'build/tools/freeze_docsouth_tei2_nested_quote.py': (),
    'build/tools/freeze_docsouth_tei2_simple.py': (),
    'build/tools/freeze_openmgh_bsb622_rupert_victoria.py': (),
    'build/tools/freeze_openmgh_bsb623_hermannus_epistola.py': (),
    'build/tools/freeze_openmgh_bsb623_hermannus_opusculum.py': (),
    'build/tools/freeze_openmgh_bsb720_carmina_three.py': (),
    'build/tools/freeze_openmgh_bsb720_heribert_hymns.py': (),
    'build/tools/freeze_openmgh_bsb751_nested.py': (),
    'build/tools/freeze_openmgh_bsb752_nested.py': (),
    'build/tools/freeze_openmgh_bsb752_othgerii.py': (),
    'build/tools/freeze_openmgh_bsb753_desiderii_hymn.py': (),
    'build/tools/freeze_openmgh_bsb753_three_prose.py': (),
    'build/tools/freeze_openmgh_bsb754_eucherii.py': (),
    'build/tools/freeze_openmgh_bsb754_nested.py': (),
    'build/tools/freeze_openmgh_bsb754_vita_abbatum.py': (),
    'build/tools/freeze_openmgh_bsb829_flat_slices.py': (),
    'build/tools/freeze_openmgh_bsb829_gof_parts.py': (),
    'build/tools/freeze_openmgh_bsb829_parts.py': (),
    'build/tools/freeze_openmgh_bsb830_alexandrinum_three.py': (),
    'build/tools/freeze_openmgh_bsb830_correspondence_pair.py': (),
    'build/tools/freeze_openmgh_bsb830_gerhoh_nested_pair.py': (),
    'build/tools/freeze_openmgh_bsb830_gerhoh_simple_parts.py': (),
    'build/tools/freeze_openmgh_bsb830_gualter_two.py': (),
    'build/tools/freeze_openmgh_bsb830_marbod_letters.py': (),
    'build/tools/freeze_openmgh_bsb830_marbod_poem.py': (),
    'build/tools/freeze_openmgh_bsb830_residual_parts.py': (),
    'build/tools/freeze_openmgh_bsb830_simony_seven.py': (),
    'build/tools/freeze_openmgh_three_whole.py': (),
    'build/tools/freeze_original_douay_install.py': (),
    'build/tools/freeze_watson_beatitudes_private_release.py': (),
    'build/tools/generate_exclusive_manifest_packet.py': (),
    'build/tools/inspect_bede_primary_notice.py': (),
    'build/tools/inspect_openmgh_bsb829_remainder_flat.py': (),
    'build/tools/install_bcp1559_publication_pointers.py': (),
    'build/tools/install_easton_current.py': (),
    'build/tools/install_torrey_current.py': (),
    'build/tools/integrate_watson_beatitudes_closure_v3.py': (),
    'build/tools/inventory_openmgh_bsb829_remainder.py': (),
    'build/tools/library_member_set_binding.py': (),
    'build/tools/original_douay_context_annex.py': (),
    'build/tools/original_douay_readable_context.py': (),
    'build/tools/preflight_aquinas_four_current.py': (),
    'build/tools/preflight_augustine_first_john_downstream.py': (),
    'build/tools/preflight_augustine_sermon_mount_downstream.py': (),
    'build/tools/preflight_augustine_sermons_lessons_downstream.py': (),
    'build/tools/preflight_augustine_tractates_john_downstream.py': (),
    'build/tools/preflight_augustines_pg3296_downstream.py': (),
    'build/tools/preflight_barclay_apology_downstream.py': (),
    'build/tools/preflight_bede_downstream.py': (),
    'build/tools/preflight_calvin_institutes_current.py': (),
    'build/tools/preflight_green_current.py': (),
    'build/tools/preflight_revised_version_current.py': (),
    'build/tools/preflight_watson_beatitudes_private.py': (),
    'build/tools/prepare_anderson_current.py': (),
    'build/tools/prepare_anne_first_final_delivery.py': (),
    'build/tools/prepare_anne_first_metadata_proposal.py': (),
    'build/tools/prepare_aquinas_four_current.py': (),
    'build/tools/prepare_aquinas_four_install_drivers.py': (),
    'build/tools/prepare_aquinas_four_publication_notices.py': (),
    'build/tools/prepare_aquinas_four_stage_driver.py': (),
    'build/tools/prepare_arnulf_bsb830_cvw.py': (),
    'build/tools/prepare_baltimore1_private_release.py': (),
    'build/tools/prepare_baltimore2_private_notices.py': (),
    'build/tools/prepare_basil_hexaemeron.py': (),
    'build/tools/prepare_basil_holy_spirit.py': (),
    'build/tools/prepare_basil_three_sidecar_packet.py': (),
    'build/tools/prepare_bcp1559_current.py': (),
    'build/tools/prepare_before_most_holy_pg76888_manifest.py': (),
    'build/tools/prepare_bennett_retained_candidates.py': (),
    'build/tools/prepare_bible_member_sidecar_packet.py': (),
    'build/tools/prepare_blaikie_first_samuel_candidates.py': (),
    'build/tools/prepare_blaikie_second_samuel.py': (),
    'build/tools/prepare_boethius_complete_envelope_authority.py': (),
    'build/tools/prepare_boethius_complete_envelope_cvw.py': (),
    'build/tools/prepare_boethius_private_release.py': (),
    'build/tools/prepare_bsb_current.py': (),
    'build/tools/prepare_calvin_complete_native.py': (),
    'build/tools/prepare_chadwick_retained_candidates.py': (),
    'build/tools/prepare_charnock_native_v2_manifest.py': (),
    'build/tools/prepare_chinook_current.py': (),
    'build/tools/prepare_chinook_notices.py': (),
    'build/tools/prepare_darby_current.py': (),
    'build/tools/prepare_docsouth_nested_quote_public_notices.py': (),
    'build/tools/prepare_docsouth_simple_public_notices.py': (),
    'build/tools/prepare_dods_complete_candidates.py': (),
    'build/tools/prepare_easton_acceptance_scope.py': (),
    'build/tools/prepare_easton_current_header.py': (),
    'build/tools/prepare_easton_source_accounting.py': (),
    'build/tools/prepare_edwards_select_sermons_current.py': (),
    'build/tools/prepare_eliza_southall_pg11959_manifest.py': (),
    'build/tools/prepare_eusebius_l811_retained.py': (),
    'build/tools/prepare_evening_incense_pg50916_manifest.py': (),
    'build/tools/prepare_expositors_lib033_harper_public_notice.py': (),
    'build/tools/prepare_expositors_lib034_ccel_public_notices.py': (),
    'build/tools/prepare_expositors_lib034_denney_pair_cvw.py': (),
    'build/tools/prepare_expositors_lib034_denney_public_notice.py': (),
    'build/tools/prepare_expositors_lib034_lumby_public_notice.py': (),
    'build/tools/prepare_expositors_lib034_moule_skinner_cvw.py': (),
    'build/tools/prepare_expositors_lib034_readable_denney_pair_authority.py': (),
    'build/tools/prepare_expositors_lib034_readable_moule_skinner_authority.py': (),
    'build/tools/prepare_expositors_lib034_readable_pair_authority.py': (),
    'build/tools/prepare_expositors_lib035_edwards_public_notice.py': (),
    'build/tools/prepare_expositors_lib035_horton_public_notice.py': (),
    'build/tools/prepare_expositors_lib035_kellogg_public_notice.py': (),
    'build/tools/prepare_expositors_lib036_milligan_public_notice.py': (),
    'build/tools/prepare_farrar_retained_candidates.py': (),
    'build/tools/prepare_fell_a41072_source.py': (),
    'build/tools/prepare_findlay_retained_candidates.py': (),
    'build/tools/prepare_first_corinthians_collection.py': (),
    'build/tools/prepare_georgii_aliud.py': (),
    'build/tools/prepare_green_body_adapter.py': (),
    'build/tools/prepare_green_current.py': (),
    'build/tools/prepare_green_notices_and_metadata.py': (),
    'build/tools/prepare_hilary_select_works_collection.py': (),
    'build/tools/prepare_hitchcock_current.py': (),
    'build/tools/prepare_hitchcock_native_support_proposal.py': (),
    'build/tools/prepare_hitchcock_release_notices.py': (),
    'build/tools/prepare_hodge_vol2_complete.py': (),
    'build/tools/prepare_jarena_lee_pg66953_manifest.py': (),
    'build/tools/prepare_kjva_current.py': (),
    'build/tools/prepare_l599_slave_trade_header.py': (),
    'build/tools/prepare_l744_hymns_sources.py': (),
    'build/tools/prepare_lib029_complete_volume_authority.py': (),
    'build/tools/prepare_ludewic.py': (),
    'build/tools/prepare_luther_galatians_native_v2_manifest.py': (),
    'build/tools/prepare_maclaren_member_set_binding.py': (),
    'build/tools/prepare_maclaren_psalms_complete.py': (),
    'build/tools/prepare_maclaren_retained_candidates.py': (),
    'build/tools/prepare_matthew_collection.py': (),
    'build/tools/prepare_murray_absolute_surrender_current.py': (),
    'build/tools/prepare_nancy_prince_pg63579.py': (),
    'build/tools/prepare_nave_current.py': (),
    'build/tools/prepare_nave_install_helpers.py': (),
    'build/tools/prepare_nave_native_support_proposal.py': (),
    'build/tools/prepare_nave_release_helper.py': (),
    'build/tools/prepare_nyssa_letters.py': (),
    'build/tools/prepare_openmgh_bsb622_rupert_victoria_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb623_hermannus_epistola_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb623_hermannus_opusculum_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb720_carmina_three_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb720_heribert_hymns_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb720_reimundi_public_notice.py': (),
    'build/tools/prepare_openmgh_bsb752_ansbert_hymn_public_notice.py': (),
    'build/tools/prepare_openmgh_bsb752_othgerii_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb753_desiderii_hymn_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb753_three_prose_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb754_eucherii_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb754_vita_abbatum_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_alexandrinum_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_correspondence_pair_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_gerhoh_nested_pair_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_gerhoh_simple_parts_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_gualter_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_marbod_letters_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_marbod_poem_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_residual_parts_public_notices.py': (),
    'build/tools/prepare_openmgh_bsb830_simony_public_notices.py': (),
    'build/tools/prepare_openmgh_passio_dormientium_dual_public_notice.py': (),
    'build/tools/prepare_openmgh_three_whole_public_notices.py': (),
    'build/tools/prepare_openmgh_vita_abbatum_dual_public_notice.py': (),
    'build/tools/prepare_openmgh_vita_lupi_public_notice.py': (),
    'build/tools/prepare_original_douay_current.py': (),
    'build/tools/prepare_owen_lib052_sin_grace_public_notice.py': (),
    'build/tools/prepare_owen_lib052_spiritually_minded_public_notice.py': (),
    'build/tools/prepare_owen_lib052_temptation_public_notice.py': (),
    'build/tools/prepare_owen_lib052_trinity_public_notice.py': (),
    'build/tools/prepare_owen_lib052_truth_innocence_public_notice.py': (),
    'build/tools/prepare_pg77576_ignatius_virgin_mary_publication.py': (),
    'build/tools/prepare_plummer_retained_candidates.py': (),
    'build/tools/prepare_prayers_baths_for_cure_source.py': (),
    'build/tools/prepare_predestination.py': (),
    'build/tools/prepare_schaff_history_vol2_current.py': (),
    'build/tools/prepare_schaff_history_vol5_current.py': (),
    'build/tools/prepare_schaff_history_vol6_current.py': (),
    'build/tools/prepare_schaff_history_vol8_current.py': (),
    'build/tools/prepare_smith_current_header.py': (),
    'build/tools/prepare_smith_final_delivery.py': (),
    'build/tools/prepare_smith_isaiah_complete.py': (),
    'build/tools/prepare_smith_native_support_proposal.py': (),
    'build/tools/prepare_smith_retained_candidates.py': (),
    'build/tools/prepare_smith_source_accounting.py': (),
    'build/tools/prepare_smith_stage_review.py': (),
    'build/tools/prepare_spurgeon_ccel_public_notice.py': (),
    'build/tools/prepare_stokes_acts_complete.py': (),
    'build/tools/prepare_tyerman_whitefield_accepted_header.py': (),
    'build/tools/prepare_walram.py': (),
    'build/tools/prepare_watson_beatitudes_closure_proposal.py': (),
    'build/tools/prepare_watson_private_release.py': (),
    'build/tools/prepare_watson_retained_candidates.py': (),
    'build/tools/prepare_webster_current.py': (),
    'build/tools/prepare_whole_duty_prayer_a23804_source.py': (),
    'build/tools/prepare_ylt_current.py': (),
    'build/tools/preserve_smith_isaiah_initial_contract.py': (),
    'build/tools/preserve_smith_isaiah_proof_v1.py': (),
    'build/tools/preserve_smith_isaiah_v2_contract.py': (),
    'build/tools/probe_anderson_current_route.py': (),
    'build/tools/probe_aquinas_four_public_route.py': (),
    'build/tools/probe_bsb_current_route.py': (),
    'build/tools/probe_chinook_hymn_projection.py': (),
    'build/tools/probe_kjva_book_labels.py': (),
    'build/tools/probe_openmgh_bsb829_flat_projection.py': (),
    'build/tools/probe_original_douay_route.py': (),
    'build/tools/probe_watson_beatitudes_selection_guard.py': (),
    'build/tools/probe_webster_book_labels.py': (),
    'build/tools/profile_expositors_lib034_remaining.py': (),
    'build/tools/project_apostles_creed.py': (),
    'build/tools/project_first_helvetic_confession.py': (),
    'build/tools/project_ten_theses_of_berne.py': (),
    'build/tools/propose_blaikie_first_samuel_title_identity.py': (),
    'build/tools/propose_blaikie_joshua_title_identity.py': (),
    'build/tools/propose_blaikie_second_samuel_identity.py': (),
    'build/tools/propose_eusebius_l811_identity.py': (),
    'build/tools/propose_eusebius_l811_repair.py': (),
    'build/tools/propose_l599_slave_trade_reader.py': (),
    'build/tools/propose_maclaren_psalms_complete.py': (),
    'build/tools/propose_nave_authority.py': (),
    'build/tools/propose_tyerman_whitefield_identity.py': (),
    'build/tools/propose_tyerman_whitefield_reader.py': (),
    'build/tools/prototype_eusebius_l811_repair.py': (),
    'build/tools/prove_anne_first_projection.py': (),
    'build/tools/prove_aquinas_four_rollback.py': (),
    'build/tools/prove_bcp1559_isolated_rollback.py': (),
    'build/tools/prove_blaikie_joshua_candidate.py': (),
    'build/tools/prove_easton_install_rollback.py': (),
    'build/tools/prove_green_repaired_handoff.py': (),
    'build/tools/prove_hitchcock_candidate.py': (),
    'build/tools/prove_hitchcock_compatibility.py': (),
    'build/tools/prove_l599_slave_trade_source.py': (),
    'build/tools/prove_original_douay_current.py': (),
    'build/tools/prove_smith_actual_projection.py': (),
    'build/tools/prove_smith_install_rollback.py': (),
    'build/tools/prove_smith_isaiah_complete.py': (),
    'build/tools/prove_smith_native_support_proposal.py': (),
    'build/tools/prove_torrey_install_rollback.py': (),
    'build/tools/prove_tyerman_whitefield_reader.py': (),
    'build/tools/prove_tyerman_whitefield_reader_anchor.py': (),
    'build/tools/prove_ylt_isolated_rollback.py': (),
    'build/tools/reconcile_anne_first_prior_releases.py': (),
    'build/tools/reconcile_anne_first_source.py': (),
    'build/tools/reconcile_bsb_current.py': (),
    'build/tools/reconcile_nave_retained.py': (),
    'build/tools/reconcile_webster_retained.py': (),
    'build/tools/record_original_douay_clearance.py': (),
    'build/tools/record_original_douay_zero_patch_clearance.py': (),
    'build/tools/recover_kjva_historical.py': (),
    'build/tools/refine_blaikie_joshua_source_contract.py': (),
    'build/tools/refresh_green_preinstall_proof.py': (),
    'build/tools/rehearse_apostles_creed_release.py': (),
    'build/tools/rehearse_first_helvetic_confession_release.py': (),
    'build/tools/rehearse_npnf210_mysteries_projection.py': (),
    'build/tools/rehearse_pg77576_ignatius_smyrnaeans_release.py': (),
    'build/tools/rehearse_pg77576_ignatius_virgin_mary_release.py': (),
    'build/tools/rehearse_ten_theses_of_berne_release.py': (),
    'build/tools/release_anderson_private.py': (),
    'build/tools/release_bsb_private.py': (),
    'build/tools/release_calvin_complete_native.py': (),
    'build/tools/release_kjva_private.py': (),
    'build/tools/release_pascal_pensees_private.py': (),
    'build/tools/release_pascal_pensees_private_v2.py': (),
    'build/tools/release_rutherford_letters_private.py': (),
    'build/tools/release_webster_private.py': (),
    'build/tools/renew_blaikie_joshua_source_contract.py': (),
    'build/tools/repair_l599_state_proposal.py': (),
    'build/tools/resume_aquinas_four_private_release.py': (),
    'build/tools/resume_baltimore1_private_release.py': (),
    'build/tools/resume_chinook_private_release.py': (),
    'build/tools/resume_modern_scepticism_private_release.py': (),
    'build/tools/retain_original_douay_stage.py': (),
    'build/tools/retain_original_douay_zero_proposal.py': (),
    'build/tools/review_bsb_baseline_source_directly.py': (),
    'build/tools/review_donne_devotions_conservation.py': (),
    'build/tools/review_eusebius_l811_source_root.py': (),
    'build/tools/select_openmgh_bsb829_flat_supported.py': (),
    'build/tools/stage_easton_current_acceptance.py': (),
    'build/tools/stage_l741_acceptance.py': (),
    'build/tools/stage_l742_acceptance.py': (),
    'build/tools/stage_lib089_form_comments_acceptance.py': (),
    'build/tools/stage_npnf210_satyrus_v3_candidate.py': (),
    'build/tools/stage_smith_current_acceptance.py': (),
    'build/tools/strong_vol2_native_leaf_proposal.py': (),
    'build/tools/test_expositors_lib033_harper_rollback.py': (),
    'build/tools/test_expositors_lib034_denney_pair_rollback.py': (),
    'build/tools/test_expositors_lib034_lumby_rollback.py': (),
    'build/tools/test_expositors_lib034_moule_skinner_install_fixture.py': (),
    'build/tools/test_expositors_lib034_readable_pair_install_fixture.py': (),
    'build/tools/test_expositors_lib035_edwards_rollback.py': (),
    'build/tools/test_expositors_lib035_horton_rollback.py': (),
    'build/tools/test_expositors_lib035_kellogg_rollback.py': (),
    'build/tools/test_expositors_lib036_adeney_pair_rollback.py': (),
    'build/tools/test_expositors_lib036_adeney_pair_v2_rollback.py': (),
    'build/tools/test_expositors_lib036_milligan_index_repair_rollback.py': (),
    'build/tools/test_expositors_lib036_milligan_rollback.py': (),
    'build/tools/test_owen_lib052_sin_grace_rollback.py': (),
    'build/tools/test_owen_lib052_spiritually_minded_rollback.py': (),
    'build/tools/test_owen_lib052_temptation_rollback.py': (),
    'build/tools/test_owen_lib052_trinity_rollback.py': (),
    'build/tools/test_owen_lib052_truth_innocence_rollback.py': (),
    'build/tools/verify_docsouth_retained_images.py': (),
    'build/tools/verify_schaff_history_vol6_header_replay.py': (),
    'build/tools/watson_boundary_review.py': (),
    'build/tools/watson_derive_initial.py': (),
    'build/tools/watson_fix_initial_binding.py': (),
    'build/tools/watson_prepare_authoring.py': (),
    'build/tools/watson_renew_aborted_proof.py': (),
    'build/tools/watson_retained_assess.py': (),
    'build/tools/watson_review_current.py': (),
    'build/tools/watson_stage_adapt.py': (),
    'build/tools/watson_strengthen_source_contract.py': (),
    'build/tools/watson_unexpected_import_not_authorized_v1.py': (),
    'build/tools/write_openmgh_bsb829_handoff.py': (),
    'ocd_kernel/projection/categories/calvin_joshua_source_native.py': (),
    'ocd_kernel/projection/categories/cassiodorus_source_profile.py': (),
    'ocd_kernel/projection/categories/coppens_pg70790_source_profile.py': (),
    'ocd_kernel/projection/categories/creeds_json_lib062_remaining_profile.py': (),
    'ocd_kernel/projection/categories/daily_light.py': (),
    'ocd_kernel/projection/categories/fox_pg43031_source_profile.py': (),
    'ocd_kernel/projection/categories/geneva_native_bible.py': (),
    'ocd_kernel/projection/categories/geneva_native_bible_check.py': (),
    'ocd_kernel/projection/categories/guyon_source_profile.py': (),
    'ocd_kernel/projection/categories/hymnary_pd_native.py': (),
    'ocd_kernel/projection/categories/l599_slave_trade_source_profile.py': (),
    'ocd_kernel/projection/categories/leeser_native_bible.py': (),
    'ocd_kernel/projection/categories/leeser_native_bible_check.py': (),
    'ocd_kernel/projection/categories/lib025_native_reference.py': (),
    'ocd_kernel/projection/categories/lib025_native_reference_accepted.py': (),
    'ocd_kernel/projection/categories/lib025_native_reference_observer.py': (),
    'ocd_kernel/projection/categories/lib040_augustine_divisions.py': (),
    'ocd_kernel/projection/categories/lib040_harmony.py': (),
    'ocd_kernel/projection/categories/lib061_toml_native.py': (),
    'ocd_kernel/projection/categories/liturgies_chrysostom_check.py': (),
    'ocd_kernel/projection/categories/liturgies_office_check.py': (),
    'ocd_kernel/projection/categories/pg20476_hymns.py': (),
    'ocd_kernel/projection/categories/pg20476_hymns_check.py': (),
    'ocd_kernel/projection/categories/pg33128_hymns_check.py': (),
    'ocd_kernel/projection/categories/strong_complete_group_profile.py': (),
    'ocd_kernel/projection/categories/strong_vol2_source_lines.py': (),
    'ocd_kernel/projection/categories/topical_nave.py': (),
    'ocd_kernel/projection/categories/tyerman_john_group_profile.py': (),
    'ocd_kernel/projection/categories/tyerman_whitefield_source_profile.py': (),
    'ocd_kernel/projection/categories/tyndale_native_bible.py': (),
    'ocd_kernel/projection/categories/tyndale_native_bible_check.py': (),
    'ocd_kernel/projection/categories/whitefield_retained.py': (),
    'ocd_kernel/projection/native_public_dispositions.py': (),
    'ocd_kernel/release/catholic_encyclopedia_public.py': (),
    'ocd_kernel/release/final_public_privacy.py': (),
}

for _module_source in MODULE_CONTRACT_SOURCES:
    COMPONENT_TEST_POLICIES[_module_source] = ComponentTestPolicy(add=(
        "tests/test_source_module_contracts.py::"
        f"test_module_imports_without_operations_and_exposes_declared_callables[{_module_source}]",
    ))

AUTHORITY_GUARD_ROUTES = (
    ("build/tei/anderson_current_oracle.py", "_oracle", 2),
    ("build/tei/anderson_current_reconstruction.py", "_convert", 1),
    ("build/tei/aquinas_four_current_reconstruction.py", "_convert", 1),
    ("build/tei/asv_reviewed_header_v2.py", "convert", 1),
    ("build/tei/asv_reviewed_header_v2_oracle.py", "oracle", 2),
    ("build/tei/basil_hexaemeron_reconstruction.py", "_convert", 1),
    ("build/tei/basil_holy_spirit_reconstruction.py", "_convert", 1),
    ("build/tei/bcp1549_current_reconstruction.py", "_convert", 1),
    ("build/tei/bcp1559_current_oracle.py", "_oracle", 2),
    ("build/tei/bcp1559_current_reconstruction.py", "_convert", 1),
    ("build/tei/bcp1662_current_reconstruction.py", "_convert", 1),
    ("build/tei/boethius_complete_envelope_oracle.py", "_oracle", 2),
    ("build/tei/brainerd_current_reconstruction.py", "_convert", 1),
    ("build/tei/bsb_current_reconstruction.py", "_convert", 1),
    ("build/tei/calvin_institutes_complete_native.py", "_convert", 1),
    ("build/tei/calvin_institutes_complete_native_oracle.py", "_oracle", 2),
    ("build/tei/calvin_joshua_oracle_v2.py", "_oracle", 2),
    ("build/tei/calvin_joshua_oracle_v3.py", "_oracle", 2),
    ("build/tei/calvin_joshua_oracle_v4.py", "_oracle", 2),
    ("build/tei/calvin_joshua_oracle_v5.py", "_oracle", 2),
    ("build/tei/calvin_joshua_reconstruction.py", "_convert", 1),
    ("build/tei/calvin_joshua_reconstruction_v2.py", "_convert", 1),
    ("build/tei/calvin_joshua_reconstruction_v3.py", "_convert", 1),
    ("build/tei/charnock_gutenberg_native_v2_oracle.py", "_oracle", 2),
    ("build/tei/charnock_gutenberg_native_v2_reconstruction.py", "_convert", 1),
    ("build/tei/chrysostom_2_corinthians_reconstruction.py", "_convert", 1),
    ("build/tei/chrysostom_romans_reconstruction.py", "_convert", 1),
    ("build/tei/darby_current_reconstruction.py", "_convert", 1),
    ("build/tei/dods_complete_oracle.py", "_oracle", 2),
    ("build/tei/edwards_select_sermons_current_reconstruction.py", "_convert", 1),
    ("build/tei/engwebpb_repaired_semantic_inline_oracle.py", "oracle", 2),
    ("build/tei/engwebpb_retained_tei_heading_repair.py", "_convert", 1),
    ("build/tei/findlay_retained_oracle.py", "_oracle", 2),
    ("build/tei/first_corinthians_collection_reconstruction.py", "_convert", 1),
    ("build/tei/gangulf_hymn_reconstruction.py", "_convert", 1),
    ("build/tei/georgii_aliud_reconstruction.py", "_convert", 1),
    ("build/tei/georgii_primum_reconstruction.py", "_convert", 1),
    ("build/tei/gregory_pastoral_epistles_reconstruction.py", "_convert", 1),
    ("build/tei/gregory_selected_epistles_reconstruction.py", "_convert", 1),
    ("build/tei/hilary_select_works_collection_reconstruction.py", "_convert", 1),
    ("build/tei/hodge_systematic_theology_vol_2_reconstruction_visual_v2.py", "_convert", 1),
    ("build/tei/hodge_vol1_complete_reconstruction.py", "_convert", 1),
    ("build/tei/hodge_vol2_complete_reconstruction.py", "_convert", 1),
    ("build/tei/jerome_letters_reconstruction.py", "_convert", 1),
    ("build/tei/jps_current_reconstruction.py", "_convert", 1),
    ("build/tei/kjva_current_reconstruction.py", "_convert", 1),
    ("build/tei/l225_engwebpb_semantic_inline_oracle.py", "oracle", 2),
    ("build/tei/leeser_tanakh_1853.py", "convert", 1),
    ("build/tei/leeser_tanakh_1853_oracle.py", "oracle", 2),
    ("build/tei/lib062_six_catechisms_oracle.py", "oracle", 2),
    ("build/tei/ludewic_reconstruction.py", "_convert", 1),
    ("build/tei/luther_galatians_native_v2_oracle.py", "_oracle", 2),
    ("build/tei/luther_galatians_native_v2_reconstruction.py", "_convert", 1),
    ("build/tei/lutheran_hymnbook_pg76498.py", "_convert", 1),
    ("build/tei/maclaren_psalms_complete_prepare.py", "convert", 1),
    ("build/tei/manifest_acquisition_ocr_oracle.py", "_oracle", 2),
    ("build/tei/manifest_acquisition_ocr_reconstruction.py", "_convert", 1),
    ("build/tei/matthew_collection_reconstruction.py", "_convert", 1),
    ("build/tei/murray_absolute_surrender_current_reconstruction.py", "_convert", 1),
    ("build/tei/npnf103_work_reconstruction.py", "_convert", 1),
    ("build/tei/npnf103_work_reconstruction_v2.py", "_convert", 1),
    ("build/tei/npnf105_work_reconstruction.py", "_convert", 1),
    ("build/tei/npnf109_olympias_corpus.py", "_convert", 1),
    ("build/tei/npnf109_rome_corpus.py", "_convert", 1),
    ("build/tei/npnf109_work_reconstruction.py", "_convert", 1),
    ("build/tei/npnf205_work_reconstruction.py", "_convert", 1),
    ("build/tei/npnf_ambrose_duties_faith_title_v3.py", "_convert", 1),
    ("build/tei/npnf_ambrose_repentance_note_v3.py", "_convert", 1),
    ("build/tei/npnf_ambrose_satyrus_title_v3.py", "_convert", 1),
    ("build/tei/npnf_ambrose_widows_title_v3.py", "_convert", 1),
    ("build/tei/npnf_ambrose_work_local.py", "_convert", 1),
    ("build/tei/openmgh_bsb828_held_reconstruction.py", "_convert", 1),
    ("build/tei/openmgh_bsb830_gerhoh_reconstruction.py", "_convert", 1),
    ("build/tei/openmgh_bsb830_honorius_reconstruction.py", "_convert", 1),
    ("build/tei/openmgh_bsb830_hugo_reconstruction.py", "_convert", 1),
    ("build/tei/openmgh_bsb830_york_four_reconstruction.py", "_convert", 1),
    ("build/tei/openmgh_bsb830_york_reconstruction.py", "_convert", 1),
    ("build/tei/openmgh_bsb830_york_three_reconstruction.py", "_convert", 1),
    ("build/tei/original_douay_current_oracle.py", "_oracle", 2),
    ("build/tei/original_douay_current_reconstruction.py", "_convert", 1),
    ("build/tei/otterbein_pg16455.py", "_convert", 1),
    ("build/tei/otterbein_pg16455_oracle.py", "_oracle", 2),
    ("build/tei/pg49917_holy_images_oracle.py", "_oracle", 2),
    ("build/tei/predestination_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol1_current_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol2_current_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol3_current_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol4_current_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol5_current_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol6_current_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol7_current_reconstruction.py", "_convert", 1),
    ("build/tei/schaff_history_vol8_current_reconstruction.py", "_convert", 1),
    ("build/tei/smith_isaiah_complete_prepare.py", "convert", 1),
    ("build/tei/stokes_retained_completion_oracle.py", "oracle", 2),
    ("build/tei/thome_pg70704_complete_v3.py", "_convert", 1),
    ("build/tei/thome_pg70704_complete_v3_oracle.py", "_oracle", 2),
    ("build/tei/ursinus_heidelberg_1852_reconstruction_oracle.py", "oracle", 2),
    ("build/tei/ursinus_heidelberg_1852_v3_reconstruction_oracle.py", "oracle", 2),
    ("build/tei/ursinus_heidelberg_1852_v4_reconstruction_oracle.py", "oracle", 2),
    ("build/tei/ursinus_heidelberg_1852_v5_reconstruction_oracle.py", "oracle", 2),
    ("build/tei/ursinus_heidelberg_1852_v6_reconstruction_oracle.py", "oracle", 2),
    ("build/tei/walram_reconstruction.py", "_convert", 1),
    ("build/tei/webster_current_reconstruction.py", "_convert", 1),
    ("build/tei/ylt_current_reconstruction.py", "_convert", 1),
)

CANDIDATE_GUARD_ROUTES = (
    ("build/tei/aquinas_four_current_oracle.py", "_oracle", 2),
    ("build/tei/brainerd_current_oracle.py", "_oracle", 2),
    ("build/tei/bsb_current_oracle.py", "_oracle", 2),
    ("build/tei/chrysostom_2_corinthians_oracle.py", "_oracle", 2),
    ("build/tei/chrysostom_romans_oracle.py", "_oracle", 2),
    ("build/tei/darby_current_oracle.py", "_oracle", 2),
    ("build/tei/donne_devotions_scoped_oracle.py", "_oracle", 2),
    ("build/tei/edwards_select_sermons_current_oracle.py", "_oracle", 2),
    ("build/tei/gregory_pastoral_epistles_oracle.py", "_oracle", 2),
    ("build/tei/gregory_selected_epistles_oracle.py", "_oracle", 2),
    ("build/tei/jerome_letters_oracle.py", "_oracle", 2),
    ("build/tei/jps_current_oracle.py", "_oracle", 2),
    ("build/tei/kjva_current_oracle.py", "_oracle", 2),
    ("build/tei/l599_slave_trade_source_oracle.py", "_oracle", 2),
    ("build/tei/murray_absolute_surrender_current_oracle.py", "_oracle", 2),
    ("build/tei/schaff_history_vol1_current_oracle.py", "_oracle", 2),
    ("build/tei/schaff_history_vol2_current_oracle.py", "_oracle", 2),
    ("build/tei/schaff_history_vol3_current_oracle.py", "_oracle", 2),
    ("build/tei/schaff_history_vol4_current_oracle.py", "_oracle", 2),
    ("build/tei/schaff_history_vol5_current_oracle.py", "_oracle", 2),
    ("build/tei/schaff_history_vol6_current_oracle.py", "_oracle", 2),
    ("build/tei/schaff_history_vol7_current_oracle.py", "_oracle", 2),
    ("build/tei/webster_current_oracle.py", "_oracle", 2),
    ("build/tei/ylt_current_oracle.py", "_oracle", 2),
)

for _guard_source, _, _ in AUTHORITY_GUARD_ROUTES + CANDIDATE_GUARD_ROUTES:
    COMPONENT_TEST_POLICIES[_guard_source] = ComponentTestPolicy(add=(
        "tests/test_source_module_contracts.py::"
        f"test_module_imports_without_operations_and_exposes_declared_callables[{_guard_source}]",
        "tests/test_declared_route_authority_guards.py",
    ))


HISTORICAL_EXECUTION_TESTS = {'build/tei/woolman_37311_challenge.py': 'tests/test_woolman_37311_entrypoints.py',
 'build/tei/woolman_37311_runner.py': 'tests/test_woolman_37311_entrypoints.py',
 'build/tools/check_guyon_short_method_24989_v16.py': 'tests/test_check_guyon_short_method_24989_v16.py',
 'build/tools/prepare_blaikie_first_samuel_route.py': 'tests/test_historical_execution_boundaries.py',
 'build/tools/probe_blaikie_joshua_title_execution.py': 'tests/test_historical_execution_boundaries.py',
 'build/tools/probe_farrar_retained_execution.py': 'tests/test_historical_execution_boundaries.py',
 'build/tools/probe_smith_isaiah_execution.py': 'tests/test_historical_execution_boundaries.py',
 'build/tools/probe_watson_retained_execution.py': 'tests/test_historical_execution_boundaries.py'}

HISTORICAL_EXECUTION_TESTS.update({
    "build/tools/prepare_maclaren_code.py": "tests/test_historical_execution_boundaries.py",
    "build/tools/prepare_maclaren_stage_code.py": "tests/test_historical_execution_boundaries.py",
})

for _historical_source, _historical_test in HISTORICAL_EXECUTION_TESTS.items():
    COMPONENT_TEST_POLICIES[_historical_source] = ComponentTestPolicy(add=(_historical_test,))


PROJECTION_BOUNDARY_SOURCES = ('ocd_kernel/projection/categories/calvin_joshua_source_native.py',
 'ocd_kernel/projection/categories/cassiodorus_source_profile.py',
 'ocd_kernel/projection/categories/coppens_pg70790_source_profile.py',
 'ocd_kernel/projection/categories/creeds_json_lib062_remaining_profile.py',
 'ocd_kernel/projection/categories/daily_light.py',
 'ocd_kernel/projection/categories/fox_pg43031_source_profile.py',
 'ocd_kernel/projection/categories/geneva_native_bible.py',
 'ocd_kernel/projection/categories/geneva_native_bible_check.py',
 'ocd_kernel/projection/categories/guyon_source_profile.py',
 'ocd_kernel/projection/categories/hymnary_pd_native.py',
 'ocd_kernel/projection/categories/l599_slave_trade_source_profile.py',
 'ocd_kernel/projection/categories/leeser_native_bible.py',
 'ocd_kernel/projection/categories/leeser_native_bible_check.py',
 'ocd_kernel/projection/categories/lib025_native_reference.py',
 'ocd_kernel/projection/categories/lib025_native_reference_accepted.py',
 'ocd_kernel/projection/categories/lib025_native_reference_observer.py',
 'ocd_kernel/projection/categories/lib040_augustine_divisions.py',
 'ocd_kernel/projection/categories/lib040_harmony.py',
 'ocd_kernel/projection/categories/lib061_toml_native.py',
 'ocd_kernel/projection/categories/liturgies_chrysostom_check.py',
 'ocd_kernel/projection/categories/liturgies_office_check.py',
 'ocd_kernel/projection/categories/pg20476_hymns.py',
 'ocd_kernel/projection/categories/pg20476_hymns_check.py',
 'ocd_kernel/projection/categories/pg33128_hymns_check.py',
 'ocd_kernel/projection/categories/strong_complete_group_profile.py',
 'ocd_kernel/projection/categories/strong_vol2_source_lines.py',
 'ocd_kernel/projection/categories/topical_nave.py',
 'ocd_kernel/projection/categories/tyerman_john_group_profile.py',
 'ocd_kernel/projection/categories/tyerman_whitefield_source_profile.py',
 'ocd_kernel/projection/categories/tyndale_native_bible.py',
 'ocd_kernel/projection/categories/tyndale_native_bible_check.py',
 'ocd_kernel/projection/categories/whitefield_retained.py',
 'ocd_kernel/projection/native_public_dispositions.py')

for _projection_source in PROJECTION_BOUNDARY_SOURCES:
    _projection_test = (
        "tests/test_projection_pg33128_hymns.py"
        if _projection_source.endswith("/pg33128_hymns_check.py")
        else "tests/test_projection_closed_native_profiles.py"
    )
    COMPONENT_TEST_POLICIES[_projection_source] = ComponentTestPolicy(add=(_projection_test,))


COMPONENT_TEST_POLICIES[
    "tests/fixtures/reconstruction-runtime/l225_ebible_usfm.py"
] = ComponentTestPolicy(add=("tests/test_l225_engwebpb_semantic_inline.py",))
COMPONENT_TEST_POLICIES["tests/runtime_candidate_baselines.py"] = ComponentTestPolicy(add=(
    "tests/test_npnf210_repentance_note_v3.py",
    "tests/test_npnf210_satyrus_title_v3.py",
    "tests/test_npnf210_widows_title_v3.py",
    "tests/test_john_owen_lib052_reconstruction_contract.py::test_ticket_maps_catalog_and_ten_exact_identity_routes",
    "tests/test_helloao_john_gill_reconstruction_contract.py::test_john_gill_catalog_claim_lineage_and_work_map_route",
    "tests/test_lib016_hastings_dictionary_reconstruction_contract.py::test_exact_work_catalog_route_is_verified_nonaccepted_and_not_ready",
    "tests/test_npnf109_chrysostom_reconstruction.py::test_frozen_maps_and_workcatalog_bind_all_sixteen",
    "tests/test_npnf2_lib048_reconstruction.py::test_all_fifteen_workcatalog_routes_are_verified_and_nonaccepted",
    "tests/test_gutenberg_evangelical_lib071_reconstruction_contract.py::test_global_work_catalog_binds_all_ten_verified_nonaccepted_routes",
    "tests/test_lib089_three_acceptances.py",
    "tests/test_gregory_select_letters_npnf207_acceptance_stage.py",
    "tests/test_lib028_remaining_histories_acceptance_stage.py",
    "tests/test_lib028_socrates_sozomen_acceptance_stage.py",
    "tests/test_npnf207_two_work_ccel_acceptance_stage.py",
    "tests/test_schleitheim_confession_acceptance.py",
    "tests/test_standard_ebooks_four_acceptance_stage.py",
    "tests/test_sum_saving_knowledge_acceptance.py",
))

COMPONENT_TEST_POLICIES["tests/current_frozen_install_context.py"] = ComponentTestPolicy(add=(
    'tests/test_old_elizabeth_pg17826_install.py',
    'tests/test_jarena_lee_pg66953_install.py',
    'tests/test_charnock_vol2_native_v2_install.py',
    'tests/test_luther_galatians_native_v2_install.py',
    'tests/test_before_most_holy_pg76888_install.py',
    'tests/test_eliza_southall_pg11959_install.py',
    'tests/test_evening_incense_pg50916_install.py',
    'tests/test_luther_pg1722_install.py',
    'tests/test_native_v2_install_runtime_manifests.py',
))


for _release_source in (
    "ocd_kernel/release/catholic_encyclopedia_public.py",
    "ocd_kernel/release/final_public_privacy.py",
):
    COMPONENT_TEST_POLICIES[_release_source] = ComponentTestPolicy(add=(
        "tests/test_release_private_carrier_contracts.py",
    ))


COMPONENT_TEST_POLICIES["tests/historical_bcp_packet_context.py"] = ComponentTestPolicy(add=(
    'tests/test_library_exclusive_multi_binding.py',
    'tests/test_library_mixed_manifest_binding.py',
))


COMPONENT_TEST_POLICIES["tests/watson_public_runtime_fixture.py"] = ComponentTestPolicy(add=(
    "tests/test_tei_acceptance_beatitudes.py",
    "tests/test_tei_acceptance_divine_contentment.py",
))


RUNTIME_FIXTURE_PREFIX = "tests/fixtures/reconstruction-runtime/"
COMPONENT_TEST_POLICIES["tests/retained_handoff_runtime_fixture.py"] = ComponentTestPolicy(add=('tests/test_prepare_law_serious_call_acceptance.py', 'tests/test_prepare_owen_conscience_acceptance.py', 'tests/test_prepare_augustine_christian_doctrine_acceptance.py'))

COMPONENT_TEST_POLICIES["tests/watson_rebind_runtime_fixture.py"] = ComponentTestPolicy(add=('tests/test_prepare_watson_divine_contentment_closure_rebind.py',))

RUNTIME_FIXTURE_PROOFS = (
    "tests/test_reconstruction_closure_corpus.py",
    "tests/test_owned_runtime_closure_baselines.py",
    "tests/test_runtime_manifest_binding_boundaries.py",
    "tests/test_missing_baseline_runtime_manifests.py",
    "tests/test_newline_runtime_manifests.py",
    "tests/test_helloao_adam_clarke_reconstruction_contract.py::test_runtime_fixture_preserves_retained_inputs_and_only_updates_storage_dependencies",
    "tests/test_luther_bondage_covenanter_reconstruction_contract.py::test_runtime_fixture_preserves_retained_inputs_and_only_updates_shared_runtime_closures",
    "tests/test_npnf105_reconstruction.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure",
    "tests/test_john_owen_lib052_reconstruction_contract.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure",
    "tests/test_spurgeon_mtp_reconstruction_contract.py::test_runtime_fixture_preserves_retained_inputs_and_only_updates_changed_dependencies",
    "tests/test_helloao_matthew_henry_reconstruction_contract.py::test_runtime_fixture_preserves_retained_inputs_and_only_updates_storage_closure",
    "tests/test_helloao_keil_delitzsch_reconstruction_contract.py::test_runtime_fixture_preserves_retained_inputs_and_only_updates_storage_closure",
    "tests/test_westminster_shorter_catechism_reconstruction_contract.py::test_runtime_fixture_preserves_retained_inputs_and_only_updates_shared_runtime_closures",
    "tests/test_npnf_ambrose_reconstruction.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_storage_closure",
    "tests/test_imitation_of_christ_reconstruction_contract.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_shared_runtime_closures",
    "tests/test_strong_systematic_theology_vol_2_reconstruction_contract.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_shared_runtime_closures",
    "tests/test_athanasius_table_reconstruction_contract.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure",
    "tests/test_lib068_source_letters_reconstruction.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure",
    "tests/test_lib014_puritan_ia_reconstruction_contract.py::test_runtime_fixtures_preserve_retained_records_and_only_update_runtime_bindings",
    "tests/test_next_binding_henry.py",
    "tests/test_source_manifest_route_validation.py::test_runtime_fixture_preserves_retained_authorities_and_only_updates_closure",
    "tests/test_next_puritan_runtime_bindings.py",
    "tests/test_lib038_runtime_manifests.py",
    "tests/test_creeds_json_lib062_remaining_install.py",
    "tests/test_creeds_json_two_catechisms_install.py",
    "tests/test_fell_a41072_exact_source_and_install.py",
    "tests/test_lib089_westminster_standards_reconstruction.py::test_runtime_fixture_preserves_complete_record_except_declared_closures",
    "tests/test_asv_lib072_runtime_manifests.py::test_runtime_fixture_preserves_complete_frozen_record",
    "tests/test_gregory_select_runtime_manifest.py::test_complete_historical_record_preserved",
    "tests/test_l596_web_runtime_manifest.py::test_runtime_preserves_complete_historical_record",
    "tests/test_lib021_bible_dictionaries_reconstruction.py::test_runtime_fixture_preserves_complete_record_except_declared_closures",
    "tests/test_lib031_work_local_runtime_manifests.py::test_runtime_copy_preserves_complete_original_record",
    "tests/test_lib054_edwards_fragments.py::test_runtime_manifest_preserves_complete_original_record",
    "tests/test_lib054_work_local_runtime_manifests.py::test_runtime_copy_preserves_complete_original_record",
    "tests/test_lib068_source_local_reconstruction.py::test_runtime_fixture_preserves_complete_original_record_except_closure",
    "tests/test_lutheran_hymnbook_pg76498_canonical.py::test_runtime_manifest_preserves_original_record_except_two_EOL_bindings_and_closure",
    "tests/test_npnf103_runtime_manifest.py::test_complete_original_source_record_preserved",
    "tests/test_npnf103104_runtime_manifests.py::test_complete_original_record_is_preserved",
    "tests/test_npnf210_title_runtime_manifests.py::test_complete_record_preserved_with_exact_historical_work_authority",
    "tests/test_npnf210_work_runtime_manifests.py::test_complete_original_record_and_authority_bytes_preserved",
    "tests/test_npnf_work_late_runtime_manifests.py::test_complete_original_record_is_preserved",
    "tests/test_prepare_watson_body_of_divinity_acceptance.py::test_exact_route_stage_passes_both_gates",
    "tests/test_se_four_runtime_manifests.py::test_runtime_copy_preserves_complete_frozen_source_record",
    "tests/test_strong_vol1_pg44035_native_stage.py::test_runtime_copy_preserves_complete_original_strong_records",
    'tests/test_old_elizabeth_pg17826_install.py::test_runtime_manifest_preserves_complete_original_record',
    'tests/test_jarena_lee_pg66953_install.py::test_runtime_manifest_preserves_complete_original_record',
    'tests/test_native_v2_install_runtime_manifests.py',
    'tests/test_charnock_vol2_native_v2_install.py::test_exact_receipt_pin_and_read_only_preflight',
    'tests/test_luther_galatians_native_v2_install.py::test_exact_receipt_pin_and_read_only_preflight',
    'tests/test_before_most_holy_pg76888_install.py::test_runtime_source_preserves_complete_historical_record',
    'tests/test_eliza_southall_pg11959_install.py::test_runtime_source_preserves_complete_historical_record',
    'tests/test_evening_incense_pg50916_install.py::test_runtime_source_preserves_complete_historical_record',
    'tests/test_luther_pg1722_install.py::test_runtime_source_preserves_complete_historical_record',
    "tests/test_install_lib040_augustine_child.py",
    "tests/test_npnf210_two_acceptances.py",
    "tests/test_gangulf_hymn.py",
    "tests/test_ajops_jats_link_repair.py",
    "tests/test_wikisource_l594_chrysostom_v2.py",
    "tests/test_gutenberg_proofread_selected_sources.py",
    "tests/test_npnf205_work_acceptance_stage.py",
    "tests/test_four_source_accounting_sidecars.py",
    "tests/test_bede_gutenberg_reconstruction.py",
    "tests/test_install_boethius_complete_envelope_acceptance.py",
    "tests/test_install_didache_full_witness_acceptance.py",
    "tests/test_newman_grammar_pg34022_handoff.py",
    "tests/test_vincent_pg6733_install.py",
    "tests/test_eliza_southall_pg11959_oracle.py",
    "tests/test_evening_incense_pg50916_oracle.py",
    "tests/test_jarena_lee_pg66953_oracle.py",
    "tests/test_arnulf_bsb830_cvw.py",
    "tests/test_npnf113_work_candidates.py",
    "tests/test_openmgh_exclusive_reconstruction.py",
    "tests/test_practical_mysticism_spine_sidecars.py",
    'tests/test_library_exclusive_multi_binding.py',
    'tests/test_library_mixed_manifest_binding.py',
    'tests/test_accepted_standard_ebooks_spine_rebind.py',
    'tests/test_37c_317_watson_lords_prayer.py::test_bound_work_and_complete_source_envelope',
    'tests/test_37c_318_watson_ten_commandments.py::test_bound_work_and_complete_source_envelope',
    'tests/test_library_exclusive_manifest_binding.py',
    'tests/test_library_config_free_multi_binding.py',
    'tests/test_library_manifest_exception_binding.py',
    "tests/test_prepare_watson_lords_prayer_acceptance.py",
    'tests/test_prepare_law_serious_call_acceptance.py',
    'tests/test_prepare_owen_conscience_acceptance.py',
    'tests/test_prepare_augustine_christian_doctrine_acceptance.py',
    'tests/test_prepare_watson_divine_contentment_closure_rebind.py',
)


def _runtime_fixture(path):
    return path.startswith(RUNTIME_FIXTURE_PREFIX) and (
        path.endswith(".json") or path.startswith(RUNTIME_FIXTURE_PREFIX + "authorities/")
        or (path.endswith(".md") and Path(path).name not in {"README.md", "missing-baseline-manifests.README.md"})
    )


def _governed(path):
    return path in {"conftest.py", PUBLIC_INPUT_INVENTORY} or _runtime_fixture(path) or (
        path.endswith(".py") and path.startswith(("build/", "ocd_kernel/", "cvw_app/", "tests/"))
    )


def _get_staged_changes():
    """Include deleted paths and both sides of renames; Git errors are failures."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-status", "--no-renames",
             "--diff-filter=ACDMR", "-z"],
            capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise RuntimeError(f"Cannot discover staged Python paths: {exc}") from exc
    fields = result.stdout.rstrip("\0").split("\0") if result.stdout else []
    if len(fields) % 2:
        raise RuntimeError("Malformed staged name/status output")
    changed, deleted = [], []
    for status, path in zip(fields[::2], fields[1::2]):
        if _governed(path):
            changed.append(path)
            if status == "D":
                deleted.append(path)
    return {"changed": changed, "deleted": deleted}


def _direct_imports(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise RuntimeError(f"Cannot inspect test imports in {path}: {exc}") from exc
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def _validate_targets(path, root, targets, diagnostic):
    for target in targets:
        test_file, separator, nodeid = target.partition("::")
        if (separator and not nodeid) or not (root / test_file).is_file():
            raise RuntimeError(f"{diagnostic}: {path} -> {target}")


def _component_matches(path, root, matches, *, changed_test=False):
    """Apply one path's coverage policy, preserving stale-mapping checks in order."""
    matches = set(matches)
    policy = COMPONENT_TEST_POLICIES.get(path)
    if policy is None:
        return matches
    if not changed_test:
        _validate_targets(path, root, policy.add, "Stale component mapping")
        matches.update(policy.add)
        if policy.route is not None:
            _validate_targets(path, root, (policy.route,), "Stale route node mapping")
            matches.discard(policy.route.split("::", 1)[0])
            matches.add(policy.route)
    if policy.replace is not None:
        _validate_targets(path, root, policy.replace, "Stale component target mapping")
        matches = set(policy.replace)
    return matches


def select_tests(changed_paths, repository_root=REPO_ROOT, *, deleted_paths=()):
    """Return deterministic evidence selection and unproved production paths."""
    root = Path(repository_root)
    changed_paths = sorted({path for path in changed_paths if _governed(path)})
    if not changed_paths:
        return {"tests": [], "unmapped": []}
    test_paths = sorted({
        path.relative_to(root).as_posix()
        for folder in ("tests", "build", "ocd_kernel", "cvw_app")
        for path in (root / folder).rglob("test_*.py")
        if "tests" in path.relative_to(root).parts
        and not any(part in {"fixtures", "__pycache__"} for part in path.parts)
    })
    imports = {path: _direct_imports(root / path) for path in test_paths}
    selected, unmapped = set(), set()
    for path in sorted(set(changed_paths)):
        if path == PUBLIC_INPUT_INVENTORY:
            proofs = ("tests/test_public_release_inputs.py",)
            _validate_targets(path, root, proofs, "Missing public test input proof")
            selected.update(proofs)
            continue
        if not _governed(path):
            continue
        if _runtime_fixture(path):
            _validate_targets(path, root, RUNTIME_FIXTURE_PROOFS, "Missing runtime fixture preservation proof")
            selected.update(RUNTIME_FIXTURE_PROOFS)
            continue
        if path in test_paths:
            selected.add(path)
            selected.update(_component_matches(path, root, (), changed_test=True))
            continue
        if Path(path).name == "conftest.py":
            matches = {test for test in test_paths if Path(test).is_relative_to(Path(path).parent)}
            selected.update(matches)
            if not matches:
                if path in deleted_paths and test_paths:
                    selected.update(test_paths)
                else:
                    unmapped.add(path)
            continue
        module = path[:-3].replace("/", ".")
        package = module.removesuffix(".__init__") if module.endswith(".__init__") else None
        stem = Path(path).stem
        names = {f"test_{stem}.py", f"test_{stem}_contract.py"}
        if stem.endswith("_oracle"):
            names.add(f"test_{stem[:-7]}_reconstruction_contract.py")
            names.add(f"test_{stem[:-7]}_reconstruction.py")
        matches = {
            test for test in test_paths
            if Path(test).name in names or module in imports[test]
            or (package and any(item == package or item.startswith(package + ".") for item in imports[test]))
        }
        matches = _component_matches(path, root, matches)
        if matches:
            selected.update(matches)
        elif path in deleted_paths:
            # Any known staged deletion without a surviving focused mapping needs
            # the maintained regression surface, including after a rename.
            # The ordinary large-selection opt-in still runs every selected test.
            selected.update(test_paths)
            if not test_paths:
                unmapped.add(path)
        else:
            unmapped.add(path)
    full_test_files = {test for test in selected if "::" not in test}
    selected = {
        test for test in selected
        if "::" not in test or test.split("::", 1)[0] not in full_test_files
    }
    return {"tests": sorted(selected), "unmapped": sorted(unmapped)}


def run_selection(selection, environment=None):
    environment = os.environ if environment is None else environment
    print(json.dumps(selection, indent=2, ensure_ascii=True))
    if selection["unmapped"]:
        print("[pre-commit pytest] No proving tests mapped for the listed paths. "
              "Add focused tests/direct imports or a reviewed COMPONENT_TEST_POLICIES mapping.")
        return 1
    paths = selection["tests"]
    if len(paths) > MAX_TESTS_WARN and environment.get("OCD_PRECOMMIT_RUN_LARGE_SELECTION") != "1":
        print("[pre-commit pytest] Selection exceeds 50 files. Inspect --list, then "
              "set $env:OCD_PRECOMMIT_RUN_LARGE_SELECTION='1' in PowerShell and "
              "rerun the commit in that same session (or run py -3 build/tools/pre_commit_pytest.py first). ALL selected tests run.")
        return 1
    return _run_pytest(paths) if paths else 0


def _include_additional_selection(selection, path, repository_root=REPO_ROOT):
    """Retain an earlier release gate's coverage alongside the fresh selection."""
    additional = json.loads(Path(path).read_bytes())
    if (not isinstance(additional, dict) or set(additional) != {"tests", "unmapped"}
            or additional["unmapped"] != [] or not isinstance(additional["tests"], list)):
        raise ValueError("Additional test selection must have tests and no unmapped paths")
    root = Path(repository_root)
    for target in additional["tests"]:
        if not isinstance(target, str):
            raise ValueError("Additional test targets must be strings")
        logical = Path(target.split("::", 1)[0])
        if logical.is_absolute() or ".." in logical.parts or not logical.name.startswith("test_"):
            raise ValueError(f"Invalid additional test target: {target}")
        _validate_targets(path, root, (target,), "Stale additional test target")
        (root / logical).resolve(strict=True).relative_to(root.resolve(strict=True))
    combined = set(selection["tests"]) | set(additional["tests"])
    full_files = {target for target in combined if "::" not in target}
    return {"tests": sorted(target for target in combined
                            if "::" not in target or target.split("::", 1)[0] not in full_files),
            "unmapped": selection["unmapped"]}


def _pytest_temp_parent(environment=None):
    """Return the verified sandbox temp root, or None for ordinary host temp."""
    environment = os.environ if environment is None else environment
    configured = environment.get("PYTEST_DEBUG_TEMPROOT")
    if not configured:
        return None

    try:
        temp_root = Path(configured).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            f"PYTEST_DEBUG_TEMPROOT is unavailable: {configured}"
        ) from exc
    repository = Path(REPO_ROOT).resolve(strict=True)
    if temp_root == repository or temp_root.is_relative_to(repository):
        raise RuntimeError(
            f"PYTEST_DEBUG_TEMPROOT must be outside the repository: {temp_root}"
        )
    if not temp_root.is_dir() or not os.access(temp_root, os.W_OK):
        raise RuntimeError(f"PYTEST_DEBUG_TEMPROOT is not writable: {temp_root}")
    return temp_root


def _pytest_environment():
    # Git exports these from worktree hooks. Tests may query retained sources
    # or create fixture repositories, so their Git commands must resolve cwd.
    # Staged-path discovery above deliberately retains the hook's own index.
    routing = {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_PREFIX", "GIT_IMPLICIT_WORK_TREE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_GRAFT_FILE",
        "GIT_SHALLOW_FILE", "GIT_NAMESPACE", ADDITIONAL_SELECTION_ENV,
    }
    return {key: value for key, value in os.environ.items() if key.upper() not in routing}


def _run_pytest(test_files):
    """Run the selected pytest targets and return their authoritative exit code."""
    temp_parent = _pytest_temp_parent()
    with tempfile.TemporaryDirectory(
        # Deep edition paths plus xdist's worker directory need a short parent.
        prefix="t-", dir=temp_parent
    ) as basetemp, ExitStack() as response_files:
        cmd = _pytest_command(test_files, basetemp=basetemp)
        if len(subprocess.list2cmdline(cmd)) > 30_000:
            # Keep arguments outside basetemp, which pytest clears before worker setup.
            argument_root = response_files.enter_context(
                tempfile.TemporaryDirectory(prefix="a-", dir=temp_parent)
            )
            arguments = Path(argument_root) / "targets.txt"
            # Use the actual command tail so priority is identical for @files.
            ordered_targets = cmd[-len(test_files):]
            arguments.write_text("\n".join(ordered_targets) + "\n", encoding="utf-8")
            cmd = cmd[:-len(test_files)] + ["@" + str(arguments)]
        try:
            priority = subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 0
            result = subprocess.run(cmd, cwd=REPO_ROOT, env=_pytest_environment(), check=True,
                                    creationflags=priority)
            return result.returncode
        except subprocess.CalledProcessError as e:
            return e.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Print selection without running tests")
    parser.add_argument("paths", nargs="*", help="Explicit paths instead of staged Git paths")
    args = parser.parse_args()
    try:
        staged = {"changed": args.paths, "deleted": []} if args.paths else _get_staged_changes()
        selection = select_tests(staged["changed"], deleted_paths=staged["deleted"])
        if additional := os.environ.get(ADDITIONAL_SELECTION_ENV):
            selection = _include_additional_selection(selection, additional)
        if args.list:
            print(json.dumps(selection, indent=2))
            return 1 if selection["unmapped"] else 0
        return run_selection(selection)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"[pre-commit pytest] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
