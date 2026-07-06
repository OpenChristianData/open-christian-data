from __future__ import annotations

from build.lib.publish_projection import (
    AUDIT_ONLY_FIELDS,
    build_audit_artifact,
    build_slim_config,
    slim_leaks_audit_fields,
)


def _records() -> list[dict]:
    return [
        {
            "record_id": "rec-001",
            "canonical_text": "In the beginning was the Word.",
            "title": "Sample entry",
            "work_id": "schaff_herzog",
            "internal_id": "internal-001",
            "output_status": "human_confirmed",
            "attestations": [{"engine": "tesseract", "token": "Word"}],
            "evidence": [{"kind": "page", "ref": "vol-01-page-0001"}],
        }
    ]


def test_slim_strips_audit_only_fields() -> None:
    records = _records()
    slim = build_slim_config(records)
    audit = build_audit_artifact(records)

    assert slim_leaks_audit_fields(slim) == []
    assert audit["records"][0]["attestations"] == records[0]["attestations"]
    assert audit["records"][0]["evidence"] == records[0]["evidence"]
    assert audit["records"][0]["output_status"] == records[0]["output_status"]
    assert AUDIT_ONLY_FIELDS.isdisjoint(slim["records"][0])


def test_slim_clean_text_matches_audit() -> None:
    slim = build_slim_config(_records())
    audit = build_audit_artifact(_records())

    audit_text_by_id = {
        record["record_id"]: record["canonical_text"] for record in audit["records"]
    }
    for record in slim["records"]:
        assert record["canonical_text"] == audit_text_by_id[record["record_id"]]
