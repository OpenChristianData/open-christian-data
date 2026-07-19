"""Schema-only tests for the 8 A1 schemas.

Each schema validates at least one hand-crafted accept example and rejects at
least one hand-crafted reject example. These tests are the A1 done-gate evidence
that the schemas hold their shape; they intentionally do not exercise the writer
CLI, the pre-commit gate, or any library behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ocd_kernel.lib.schema_enums import resolve_schema_path


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads(resolve_schema_path(name).read_text(encoding="utf-8"))


def _accepts(schema: dict, instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=schema)


def _rejects(schema: dict, instance: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


# --- review_state ------------------------------------------------------------


def test_review_state_accepts_empty_sidecar():
    schema = _schema("review_state")
    _accepts(
        schema,
        {
            "schema_type": "review_state",
            "schema_version": "1.0.0",
            "record_path": "data/foo.json",
            "record_resource_id": "foo",
            "record_checksum_sha256": "0" * 64,
            "parser_version_seen": "build/parsers/foo.py@v1.0.0",
            "confidence": {
                "structural_fidelity": "unverified",
                "text_fidelity": "unverified",
                "edition_provenance": "unverified",
            },
            "entries": {},
            "dead_letter": [],
        },
    )


def test_review_state_rejects_bad_confidence_tier():
    schema = _schema("review_state")
    _rejects(
        schema,
        {
            "schema_type": "review_state",
            "schema_version": "1.0.0",
            "record_path": "data/foo.json",
            "record_resource_id": "foo",
            "record_checksum_sha256": "0" * 64,
            "parser_version_seen": "build/parsers/foo.py@v1.0.0",
            "confidence": {
                "structural_fidelity": "great",  # not in enum
                "text_fidelity": "unverified",
                "edition_provenance": "unverified",
            },
            "entries": {},
            "dead_letter": [],
        },
    )


def test_review_state_rejects_dead_letter_overflow():
    schema = _schema("review_state")
    payload = {
        "schema_type": "review_state",
        "schema_version": "1.0.0",
        "record_path": "data/foo.json",
        "record_resource_id": "foo",
        "record_checksum_sha256": "0" * 64,
        "parser_version_seen": "build/parsers/foo.py@v1.0.0",
        "confidence": {
            "structural_fidelity": "unverified",
            "text_fidelity": "unverified",
            "edition_provenance": "unverified",
        },
        "entries": {},
        "dead_letter": [
            {
                "reason": "producer_unknown",
                "raw_warning": {"producer": "x"},
                "received_at": "2026-05-12T10:00:00+00:00",
            }
            for _ in range(101)
        ],
    }
    _rejects(schema, payload)


# --- correction_ledger -------------------------------------------------------


def test_correction_ledger_accepts_approved_text_entry():
    schema = _schema("correction_ledger")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "correction_id": "01HBQX0E9PNB6PV4N9X7CWNZRC",
            "resource_id": "schaff-herzog-encyclopedia",
            "record_path": "data/reference/schaff-herzog-encyclopedia.json",
            "entry_id": "schaff-herzog.theotokos",
            "field_path": "definition_blocks.b8f3a1c2d4e5f6a7",
            "correction_type": "text",
            "blocker": "none",
            "before_text": "THE0T0K08",
            "after_text": "THEOTOKOS",
            "producer_warning_signature": "field=definition_blocks.b8f3a1c2d4e5f6a7;offset=1832;token=THE0T0K08",
            "status": "approved",
            "created_at": "2026-05-12T10:00:00+00:00",
            "approved_at": "2026-05-12T10:05:00+00:00",
            "approved_by": "test_reviewer",
        },
    )


def test_correction_ledger_rejects_approved_without_approver():
    schema = _schema("correction_ledger")
    _rejects(
        schema,
        {
            "schema_version": "1.0.0",
            "correction_id": "id",
            "resource_id": "foo",
            "record_path": "data/foo.json",
            "entry_id": "foo.1",
            "field_path": "text",
            "correction_type": "text",
            "blocker": "none",
            "before_text": "a",
            "after_text": "b",
            "status": "approved",  # missing approved_at + approved_by
            "created_at": "2026-05-12T10:00:00+00:00",
        },
    )


def test_correction_ledger_rejects_unknown_correction_type():
    schema = _schema("correction_ledger")
    _rejects(
        schema,
        {
            "schema_version": "1.0.0",
            "correction_id": "id",
            "resource_id": "foo",
            "record_path": "data/foo.json",
            "entry_id": "foo.1",
            "field_path": "text",
            "correction_type": "cosmetic",  # not in enum
            "blocker": "none",
            "before_text": "a",
            "after_text": "b",
            "status": "proposed",
            "created_at": "2026-05-12T10:00:00+00:00",
        },
    )


# --- writer_manifest ---------------------------------------------------------


def test_writer_manifest_accepts_parser_example():
    schema = _schema("writer_manifest")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "writer": "parser",
            "writer_version": "build/parsers/ia_schaff_herzog.py@v1.1.0",
            "writer_identity": "ia_schaff_herzog_parser",
            "run_id": "9c1f3e8a-1234-4abc-9def-0123456789ab",
            "started_at": "2026-05-12T11:00:00+00:00",
            "data_paths": ["data/reference/schaff-herzog-encyclopedia.json"],
            "checksums": {
                "data/reference/schaff-herzog-encyclopedia.json": {
                    "before_sha256": "a" * 64,
                    "after_sha256": "b" * 64,
                }
            },
            "expected_delta_counts": {
                "data/reference/schaff-herzog-encyclopedia.json": {
                    "entries_changed": 12,
                    "fields_changed": 14,
                }
            },
            "allowed_field_paths": ["/data/*/layers/*/display"],
            "partial_completion_policy": "all_or_nothing",
            "renames": [],
        },
    )


def test_writer_manifest_accepts_new_file_with_null_before_sha():
    schema = _schema("writer_manifest")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "writer": "parser",
            "writer_version": "build/parsers/foo.py@v1.0.0",
            "writer_identity": "foo_parser",
            "run_id": "id",
            "started_at": "2026-05-12T11:00:00+00:00",
            "data_paths": ["data/foo.json"],
            "checksums": {
                "data/foo.json": {
                    "before_sha256": None,
                    "after_sha256": "c" * 64,
                }
            },
            "expected_delta_counts": {
                "data/foo.json": {"entries_changed": 1, "fields_changed": 1}
            },
            "allowed_field_paths": ["/*"],
            "partial_completion_policy": "all_or_nothing",
            "renames": [],
        },
    )


def test_writer_manifest_accepts_deleted_file_with_null_after_sha():
    schema = _schema("writer_manifest")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "writer": "parser",
            "writer_version": "build/parsers/foo.py@v1.0.0",
            "writer_identity": "foo_parser",
            "run_id": "delete-run",
            "started_at": "2026-07-18T08:00:00+10:00",
            "data_paths": ["data/foo.json"],
            "checksums": {
                "data/foo.json": {
                    "before_sha256": "c" * 64,
                    "after_sha256": None,
                }
            },
            "expected_delta_counts": {
                "data/foo.json": {"entries_changed": 1, "fields_changed": 0}
            },
            "allowed_field_paths": ["/"],
            "partial_completion_policy": "all_or_nothing",
            "renames": [],
        },
    )


def test_writer_manifest_rejects_path_absent_before_and_after():
    schema = _schema("writer_manifest")
    _rejects(
        schema,
        {
            "schema_version": "1.0.0",
            "writer": "parser",
            "writer_version": "build/parsers/foo.py@v1.0.0",
            "writer_identity": "foo_parser",
            "run_id": "no-op-run",
            "started_at": "2026-07-18T08:00:00+10:00",
            "data_paths": ["data/foo.json"],
            "checksums": {
                "data/foo.json": {
                    "before_sha256": None,
                    "after_sha256": None,
                }
            },
            "expected_delta_counts": {
                "data/foo.json": {"entries_changed": 0, "fields_changed": 0}
            },
            "allowed_field_paths": ["/"],
            "partial_completion_policy": "all_or_nothing",
            "renames": [],
        },
    )


def test_writer_manifest_rejects_unknown_writer():
    schema = _schema("writer_manifest")
    _rejects(
        schema,
        {
            "schema_version": "1.0.0",
            "writer": "human",  # not allowed
            "writer_version": "v",
            "writer_identity": "x",
            "run_id": "r",
            "started_at": "2026-05-12T11:00:00+00:00",
            "data_paths": ["data/foo.json"],
            "checksums": {"data/foo.json": {"before_sha256": None, "after_sha256": "f" * 64}},
            "expected_delta_counts": {"data/foo.json": {"entries_changed": 1, "fields_changed": 1}},
            "allowed_field_paths": ["/*"],
            "partial_completion_policy": "all_or_nothing",
            "renames": [],
        },
    )


# --- audit_event -------------------------------------------------------------


def test_audit_event_accepts_dismiss():
    schema = _schema("audit_event")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "event_type": "dismiss",
            "timestamp_utc": "2026-05-12T11:30:00+00:00",
            "actor": "test_reviewer",
            "resource_id": "schaff-herzog-encyclopedia",
            "record_path": "data/reference/schaff-herzog-encyclopedia.json",
            "entry_id": "schaff-herzog.theotokos",
            "warning_signature": "sig123",
            "warning_producer": "historical_lexicon",
            "warning_code": "archaic_variant",
            "decision_reason": "expected",
        },
    )


def test_audit_event_accepts_correction_applied():
    schema = _schema("audit_event")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "event_type": "correction_applied",
            "timestamp_utc": "2026-05-12T11:30:00+00:00",
            "actor": "correction_applier",
            "resource_id": "schaff-herzog-encyclopedia",
            "record_path": "data/reference/schaff-herzog-encyclopedia.json",
            "entry_id": "schaff-herzog.theotokos",
            "field_path": "definition_blocks.b8f3a1c2d4e5f6a7",
            "writer_manifest_run_id": "9c1f3e8a",
            "manifest_checksum_sha256": "0" * 64,
        },
    )


def test_audit_event_accepts_sidecar_schema_migrated():
    schema = _schema("audit_event")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "event_type": "sidecar_schema_migrated",
            "timestamp_utc": "2026-05-12T11:30:00+00:00",
            "actor": "migrate_sidecars",
            "resource_id": "schaff-herzog-encyclopedia",
            "record_path": "data/reference/schaff-herzog-encyclopedia.json",
            "from_version": "1.0.0",
            "to_version": "1.2.0",
            "migration_chain": ["1.0.0->1.1.0", "1.1.0->1.2.0"],
        },
    )


def test_audit_event_accepts_set_confidence_axis():
    schema = _schema("audit_event")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "event_type": "set_confidence_axis",
            "timestamp_utc": "2026-05-12T11:30:00+00:00",
            "actor": "test_reviewer",
            "resource_id": "schaff-herzog-encyclopedia",
            "record_path": "data/reference/schaff-herzog-encyclopedia.json",
            "confidence_axis": "text_fidelity",
            "confidence_tier": "human-reviewed",
        },
    )


def test_audit_event_accepts_stale_lock_broken():
    schema = _schema("audit_event")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "event_type": "stale_lock_broken",
            "timestamp_utc": "2026-05-12T11:30:00+00:00",
            "actor": "atomic_io",
            "resource_id": "schaff-herzog-encyclopedia",
            "record_path": "data/reference/schaff-herzog-encyclopedia.json",
            "lock_owner_pid": 12345,
            "lock_owner_hostname": "host.example",
            "target_path": "review/audit.jsonl",
        },
    )


def test_audit_event_rejects_unknown_event_type():
    schema = _schema("audit_event")
    _rejects(
        schema,
        {
            "schema_version": "1.0.0",
            "event_type": "deleted_everything",
            "timestamp_utc": "2026-05-12T11:30:00+00:00",
            "actor": "test_reviewer",
            "resource_id": "foo",
            "record_path": "data/foo.json",
        },
    )


# --- parser_anchor_fixture ---------------------------------------------------


def test_parser_anchor_fixture_accepts_example():
    schema = _schema("parser_anchor_fixture")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "parser_id": "build/parsers/ia_schaff_herzog.py",
            "slug_algorithm_version": 1,
            "samples": [
                {"input": "Aachen, Synods of", "expected_anchor": "schaff-herzog.aachen-synods-of"},
                {"input": "Theotokos", "expected_anchor": "schaff-herzog.theotokos"},
            ],
        },
    )


def test_parser_anchor_fixture_rejects_empty_samples():
    schema = _schema("parser_anchor_fixture")
    _rejects(
        schema,
        {
            "schema_version": "1.0.0",
            "parser_id": "build/parsers/ia_schaff_herzog.py",
            "slug_algorithm_version": 1,
            "samples": [],
        },
    )


# --- parser_anchor_remap -----------------------------------------------------


def test_parser_anchor_remap_accepts_example():
    schema = _schema("parser_anchor_remap")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "parser": "build/parsers/ia_schaff_herzog.py",
            "from_version": "v1.0.0",
            "to_version": "v1.1.0",
            "slug_algorithm_version_from": 1,
            "slug_algorithm_version_to": 1,
            "remap": {"schaff-herzog.old-anchor": "schaff-herzog.new-anchor"},
            "orphaned": ["schaff-herzog.dropped-entry"],
        },
    )


# --- field_path_remap --------------------------------------------------------


def test_field_path_remap_accepts_example():
    schema = _schema("field_path_remap")
    _accepts(
        schema,
        {
            "schema_version": "1.0.0",
            "parser": "build/parsers/ia_schaff_herzog.py",
            "from_version": "v1.1.0",
            "to_version": "v1.2.0",
            "remap": {
                "schaff-herzog.theotokos|layers.definition_blocks.b8f3a1c2d4e5f6a7":
                    "schaff-herzog.theotokos|layers.definition_blocks.c9a4b2d3e6f7a8b9"
            },
            "orphaned_field_paths": [
                "schaff-herzog.theotokos|layers.definition_blocks.deadbeefdeadbeef"
            ],
        },
    )


# --- reconciled_record (v3 new schema) ---------------------------------------

_GOLDEN_BLOCK = {
    "block_id": "b_0042abcd",
    "block_id_history": [],
    "block_type": "paragraph",
    "language": "en",
    "language_confidence": 0.98,
    "language_alternates": [],
    "language_segments": [],
    "original_text": "Whom he hath seen.",
    "modern_text": "Whom he has seen.",
    "annotations": {"verse": "1John.1.1"},
    "source_pages": [
        {"rendering_id": "ccel/wesley/notes-on-the-bible/1754-1765/thml", "page_number": None}
    ],
    "attested_by": ["ccel/wesley/notes-on-the-bible/1754-1765/thml"],
    "disagreements": [],
    "structural_disagreements": [],
    "modernisations": [],
}

_GOLDEN_META = {
    "id": "wesley.notes-on-the-bible.1754-1765",
    "title": "Notes on the Bible",
    "author_slug": "wesley",
    "author_display_name": "John Wesley",
    "author_birth_year": 1703,
    "author_death_year": 1791,
    "original_publication_year": 1754,
    "language": "en",
    "tradition": ["methodist"],
    "license": "public-domain",
    "schema_type": "reconciled_record",
    "schema_version": "3.0.0",
    "edition": "1754-1765",
    "pd_anchor": "ccel/wesley/notes-on-the-bible/1754-1765/thml",
    "modernisation_ruleset_version": None,
    "attestation_summary": {
        "block_count": 1,
        "fully_attested_blocks": 1,
        "blocks_with_disagreements": 0,
        "blocks_with_structural_disagreements": 0,
    },
}


def test_reconciled_record_round_trip():
    schema = _schema("reconciled_record")
    golden = {
        "meta": _GOLDEN_META,
        "blocks": [_GOLDEN_BLOCK],
        "match_explanations": [],
    }
    _accepts(schema, golden)
    # Missing block_id on a block fails
    bad_block = {k: v for k, v in _GOLDEN_BLOCK.items() if k != "block_id"}
    _rejects(schema, {**golden, "blocks": [bad_block]})
    # Missing match_explanations at record level fails
    _rejects(schema, {"meta": _GOLDEN_META, "blocks": [_GOLDEN_BLOCK]})


# --- modernised_record (v3 new schema) ----------------------------------------

def test_modernised_record_round_trip():
    schema = _schema("modernised_record")
    modernised_meta = {
        **_GOLDEN_META,
        "schema_type": "modernised_record",
        "modernisation_ruleset_version": "en@1.0.0",
        "paired_with": "data/commentary/wesley/notes-on-the-bible/1754-1765/original/vol-01.json",
    }
    rule_modernisation = {
        "rule_id": "en.archaic_verb_eth_to_s",
        "rule_version": "1.0.0",
        "span": {"start_token": 2, "end_token": 3},
        "original": "hath",
        "modern": "has",
    }
    modernised_block = {**_GOLDEN_BLOCK, "modernisations": [rule_modernisation]}
    golden = {
        "meta": modernised_meta,
        "blocks": [modernised_block],
        "match_explanations": [],
    }
    _accepts(schema, golden)
    # Editorial modernisation variant also valid
    editorial_modernisation = {
        "rule_id": None,
        "kind": "editorial",
        "editor_decision": {
            "rationale": "Natural prose.",
            "decided_at": "2026-05-17T00:00:00+00:00",
        },
        "span": {"start_token": 0, "end_token": 2},
        "original": "Yea, verily",
        "modern": "Yes, truly",
    }
    _accepts(schema, {**golden, "blocks": [{**modernised_block, "modernisations": [editorial_modernisation]}]})
    # Missing paired_with in meta fails
    meta_no_paired = {k: v for k, v in modernised_meta.items() if k != "paired_with"}
    _rejects(schema, {**golden, "meta": meta_no_paired})


# --- review_patch (v3 new schema) --------------------------------------------

def test_review_patch_round_trip():
    schema = _schema("review_patch")
    golden = {
        "schema_type": "review_patch",
        "schema_version": "3.0.0",
        "tool_version": "build/tools/apply_review_patch.py@1.0.0",
        "generated_at": "2026-05-17T00:00:00+00:00",
        "content_hashes": {
            "data/reference/schaff/encyclopedia/1908-1914/catalog.json": "sha256:" + "a" * 64,
        },
        "decisions": [
            {
                "decision_kind": "adjudication",
                "record_path": "data/reference/schaff/encyclopedia/1908-1914/original/vol-01.json",
                "block_id": "b_0042abcd",
                "disagreement_index": 0,
                "chosen_reading": "hath",
                "rationale": "CCEL preserves archaic form.",
                "decided_at": "2026-05-17T00:00:00+00:00",
            }
        ],
    }
    _accepts(schema, golden)
    # Missing tool_version fails
    _rejects(schema, {k: v for k, v in golden.items() if k != "tool_version"})
    # Unknown decision_kind fails
    bad_decisions = [{**golden["decisions"][0], "decision_kind": "destroy_everything"}]
    _rejects(schema, {**golden, "decisions": bad_decisions})


# --- rendering_catalog (v3 new schema) ----------------------------------------

_CCEL_RENDERING = {
    "rendering_id": "ccel/schaff/encyclopedia/1908-1914/thml",
    "role": "pd_anchor",
    "source": "ccel",
    "format": "thml",
    "license": "public-domain",
    "fetched_at": "2026-04-15",
    "source_hash": "sha256:" + "b" * 64,
    "coverage": {"volumes": [1, 2, 3]},
}

_IA_RENDERING = {
    "rendering_id": "ia/schaff/encyclopedia/1908-1914/ocr",
    "role": "pd_attestor",
    "source": "ia",
    "format": "ocr",
    "license": "public-domain",
    "engine": "abbyy@10.5",
    "fetched_at": "2026-05-15",
    "source_hash": "sha256:" + "c" * 64,
    "coverage": {"volumes": [1, 2, 3]},
}

_GOLDEN_CATALOG = {
    "work_id": "schaff.encyclopedia",
    "edition": "1908-1914",
    "modernisation_intent": "not_applicable",
    "pd_anchor_decision": {
        "chosen_rendering": "ccel/schaff/encyclopedia/1908-1914/thml",
        "rationale": "CCEL ThML preserves entry structure.",
        "decided_at": "2026-05-17T00:00:00+00:00",
        "alternates_considered": [],
    },
    "renderings": [_CCEL_RENDERING, _IA_RENDERING],
}


def test_rendering_catalog_role_lifecycle():
    schema = _schema("rendering_catalog")
    # Valid catalog with pd_anchor + pd_attestor
    _accepts(schema, _GOLDEN_CATALOG)
    # pending rendering is valid
    pending_catalog = {
        **_GOLDEN_CATALOG,
        "renderings": [
            _CCEL_RENDERING,
            _IA_RENDERING,
            {
                "rendering_id": "our-ocr/schaff/encyclopedia/1908-1914/ocr-v1",
                "role": "pending",
                "source": "our-ocr",
                "format": "ocr",
                "license": "public-domain-derived",
                "fetched_at": "2026-05-17",
                "source_hash": "sha256:" + "d" * 64,
                "coverage": {"volumes": [3]},
            },
        ],
    }
    _accepts(schema, pending_catalog)
    # reference_only PD rendering is valid
    reference_only_pd = {
        **_GOLDEN_CATALOG,
        "renderings": [
            _CCEL_RENDERING,
            {
                **_IA_RENDERING,
                "role": "reference_only",
            },
        ],
    }
    _accepts(schema, reference_only_pd)
    # Unknown role fails
    bad_role = {**_GOLDEN_CATALOG, "renderings": [{**_CCEL_RENDERING, "role": "honorary"}]}
    _rejects(schema, bad_role)


def test_copyrighted_catalog_entry_satisfies_allow_list():
    schema = _schema("rendering_catalog")
    copyrighted_rendering = {
        "rendering_id": "bdb/hebrew/lexicon/1906/print",
        "role": "reference_only",
        "rights": "copyrighted",
        "rights_holder": "Oxford University Press",
        "source": "print",
        "format": "ocr",
        "edition": "1906",
        "fetched_at": "2026-05-17",
        "source_url": "https://example.com/bdb",
        "source_hash": {"algorithm": "sha256", "value": "a" * 64},
        "page_count": 1234,
        "byte_size": 50000000,
        "coverage": {"ranges": [{"start_page": 1, "end_page": 100}]},
    }
    catalog_with_copyrighted = {
        **_GOLDEN_CATALOG,
        "renderings": [_CCEL_RENDERING, copyrighted_rendering],
    }
    _accepts(schema, catalog_with_copyrighted)
    # Prohibited free-text fields fail
    for bad_field in ("coverage_notes", "notes", "headword_list", "_index", "excerpt"):
        bad_rendering = {**copyrighted_rendering, bad_field: "some text here"}
        _rejects(schema, {**_GOLDEN_CATALOG, "renderings": [_CCEL_RENDERING, bad_rendering]})
