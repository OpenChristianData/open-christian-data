"""Bind the PG42957 reconstruction to its current retained-source manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from build.tei import modern_scepticism_christian_evidence_society_1871 as source_map
from ocd_kernel.lib.storage_topology import repository_relative_path
from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-l879-pg42957-modern-scepticism-to-tei"
CONVERTER_VERSION = "1"
MEMBER_ROLES = {"primary-source", "retained-source-member"}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _record(manifest: SourceManifest, name: str) -> dict[str, Any]:
    content = manifest.authority_path(name).read_bytes()
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} authority must contain a JSON object")
    return value


def _source_members(manifest: SourceManifest) -> list[dict[str, Any]]:
    members = [
        {
            "bytes": authority["bytes"],
            "name": Path(authority["path"]).name,
            "path": authority["path"],
            "role": authority["role"],
            "sha256": authority["sha256"],
            "treatment": authority["treatment"],
        }
        for authority in manifest.record["authorities"]
        if authority.get("role") in MEMBER_ROLES
    ]
    members.sort(key=lambda item: (item["path"], item["name"]))
    return members


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    """Produce the fixed five-member, nonaccepted candidate package."""

    source = manifest.authority_path("primary-source")
    source_logical_path = repository_relative_path(manifest.repository_root, source)
    if source_logical_path != manifest.record.get("retained_source_path"):
        raise ValueError("primary source path differs from the manifest scope")
    audit = source_map.audit_source(source, repository_root=manifest.repository_root)
    members = _source_members(manifest)
    if len(members) != 8:
        raise ValueError(f"expected all eight retained package members, found {len(members)}")

    source_receipt = _record(manifest, "source-receipt")
    receipt_members = {
        row["name"]: (row["bytes"], row["sha256"])
        for row in source_receipt.get("retained_members", [])
    }
    manifest_members = {
        Path(row["path"]).name: (row["bytes"], row["sha256"])
        for row in members
    }
    if receipt_members != manifest_members:
        raise ValueError("retained source receipt and manifest member sets differ")
    if audit["package_hashes"] != {
        Path(row["path"]).name: row["sha256"] for row in members
    }:
        raise ValueError("source package audit differs from bound member hashes")

    source_config = _record(manifest, "source-config")
    work_identity = _record(manifest, "work-identity")
    target_state = _record(manifest, "target-state")
    acquisition = _record(manifest, "acquisition-record")
    identifiers = {
        "work_id": work_identity["work_id"],
        "textual_form_id": work_identity["textual_forms"][0]["textual_form_id"],
        "edition_id": work_identity["textual_forms"][0]["editions"][0]["edition_id"],
        "acquisition_id": acquisition["acquisition_id"],
    }
    if identifiers["work_id"] != manifest.record.get("work_id"):
        raise ValueError("source manifest and current work identity differ")
    if identifiers["edition_id"] != acquisition.get("edition_id"):
        raise ValueError("current acquisition is linked to a different edition")
    if identifiers["acquisition_id"] not in work_identity["textual_forms"][0]["editions"][0][
        "acquisition_ids"
    ]:
        raise ValueError("current work identity does not link the retained acquisition")
    if not any(
        target.get("target_id") == identifiers["edition_id"]
        and target.get("target_type") == "edition"
        for target in target_state.get("targets", [])
    ):
        raise ValueError("current state has no linked edition target")

    document = source_map._transform(source_map._parse_source(source))
    if document.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=source_map.NS):
        raise ValueError("aggregate authorship is not source-established")
    tei_bytes = source_map.etree.tostring(
        document,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )

    profile = _record(manifest, "profile")
    policy = _record(manifest, "policy")
    account = {
        "contract": "ocd-pg42957-source-accountability-v1",
        **identifiers,
        "source_id": manifest.record["source_id"],
        "source_scope": manifest.record["source_scope"],
        "primary_source": {
            "path": manifest.record["retained_source_path"],
            "bytes": audit["source_bytes"],
            "sha256": audit["source_sha256"],
            "role": "sole structural and textual authority",
        },
        "retained_members": members,
        "retained_member_set_sha256": _sha(
            _canonical_bytes(
                [
                    {
                        "bytes": row["bytes"],
                        "name": Path(row["path"]).name,
                        "path": row["path"],
                        "sha256": row["sha256"],
                    }
                    for row in members
                ]
            )
        ),
        "complete_source_profile_sha256": next(
            item["sha256"]
            for item in manifest.record["authorities"]
            if item["name"] == "profile"
        ),
        "content_inventory": {
            "source_text_characters": audit["source_text_characters"],
            "source_text_sha256": audit["source_text_sha256"],
            "tag_counts": audit["tag_counts"],
            "class_counts": audit["class_counts"],
            "source_ids": audit["source_ids"],
            "internal_targets": audit["internal_targets"],
            "unresolved_internal_targets": audit["unresolved_internal_targets"],
            "footnotes": audit["footnotes"],
            "footnote_references": audit["footnote_references"],
            "page_markers": audit["page_markers"],
            "poetry_containers": audit["poetry_containers"],
            "tables": audit["tag_counts"].get("table", 0),
            "table_rows": audit["tag_counts"].get("tr", 0),
            "table_cells": audit["tag_counts"].get("td", 0),
            "lecture_heads": audit["lecture_heads"],
            "lecture_start_positions": audit["lecture_start_positions"],
            "transcribers_notes_present": audit["transcribers_notes_present"],
            "printer_line": audit["printer_line"],
            "start_marker": audit["project_gutenberg_start_marker"],
            "end_marker": audit["project_gutenberg_end_marker"],
        },
        "work_boundary": {
            "source_title": source_config["title"],
            "top_level_title_count": profile["top_level_title_count"],
            "source_boundary_evidence": profile["work_boundary_evidence"],
            "body_division_count": 12,
            "candidate_tei_count": 1,
            "rule": "one complete top-level titled work produces one TEI",
        },
        "mapping": profile["mapping"],
        "exclusions": profile["exclusions"],
        "metadata_disposition": {
            "aggregate_author": "omitted; source identifies a requester and multiple contributors, not one author",
            "contributors": "source-attested lecture and explanatory-paper contributors retained in teiHeader/respStmt",
            "provisional_config_author_removed": source_config.get("author") is None
            and source_config.get("author_id") is None,
        },
        "policy": policy["contract"],
        "acceptance_status": "nonaccepted",
        "rights_status": "not assessed by this technical reconstruction",
        "publication_status": "not authorized",
    }
    account_schema = _record(manifest, "accountability-schema")
    from jsonschema import Draft202012Validator

    errors = list(Draft202012Validator(account_schema).iter_errors(account))
    if errors:
        raise ValueError(f"source accountability schema failed: {errors[0].message}")

    provenance = {
        "contract": "ocd-reconstruction-provenance-v1",
        **identifiers,
        "source_id": manifest.record["source_id"],
        "source_manifest": {
            "path": manifest.path.relative_to(manifest.repository_root).as_posix(),
            "sha256": manifest.sha256,
        },
        "primary_source": {
            "provider": acquisition["provider"],
            "url": acquisition["url"],
            "path": manifest.record["retained_source_path"],
            "bytes": audit["source_bytes"],
            "sha256": audit["source_sha256"],
        },
        "source_members": [
            {
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "treatment": row["treatment"],
            }
            for row in members
        ],
        "source_edition": source_config["source_edition"],
        "original_publication_year": source_config["original_publication_year"],
        "project_gutenberg_id": source_config["gutenberg_id"],
        "candidate_tei_count": 1,
        "acceptance_status": "nonaccepted",
        "rights_status": "not assessed by this technical reconstruction",
        "publication_status": "not authorized",
    }
    readme = (
        "# Modern Scepticism (1871) candidate\n\n"
        "This package reconstructs the one complete titled volume *Modern Scepticism: "
        "A Course of Lectures Delivered at the Request of the Christian Evidence "
        "Society* as exactly one TEI document. The retained legacy XHTML is the sole "
        "structural and textual authority. Its title page and preface identify a "
        "collection of eleven lectures plus C. J. Ellicott's explanatory paper, "
        "gathered into one volume.\n\n"
        "All eight retained package members are inventoried in "
        "`source-accountability.json`. Current/legacy HTML and plain-text witnesses, "
        "provider pages, indexes, and the ZIP are supporting evidence; the ZIP's "
        "cover image is not an image embedded in the primary text. Source wording, "
        "front and back matter, notes, page markers, tables, poetry, and transcriber's "
        "notes are preserved. No text was inferred or modernized.\n\n"
        "The source says the lectures were delivered at the Society's request and "
        "names multiple contributors. The candidate therefore leaves the aggregate "
        "author field absent and retains the contributor statement. Print-page image "
        "collation and full visual review remain open. This candidate is nonaccepted; "
        "rights review, canonical integration, and publication are not authorized by "
        "this package.\n"
    ).encode("utf-8")
    unresolved = [
        {
            "id": "print-page-image-collation",
            "status": "open",
            "description": "No printed-page image scan is retained in this acquisition; electronic-source fidelity does not establish print-image correspondence.",
        },
        {
            "id": "full-visual-review",
            "status": "open",
            "description": "The exact candidate has not received a full source/TEI side-by-side review; old excerpt checks do not bind this candidate byte version.",
        },
        {
            "id": "aggregate-authorship",
            "status": "unassigned",
            "description": "The title page describes lectures delivered at the Christian Evidence Society's request and names several contributors; no sole author is stated.",
        },
    ]
    return {
        "README.source.md": readme,
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical_bytes(provenance),
        "source-accountability.json": _canonical_bytes(account),
        "unresolved.jsonl": b"".join(_canonical_bytes(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
